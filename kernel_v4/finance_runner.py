from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kernel_v4.context import ToolUseContext
from kernel_v4.contracts import JsonObject, LoopResult, ModelClient, ToolCall
from kernel_v4.finance_tools import (
    V4_FINANCE_TOOLCHAIN_AUDIT,
    V4_FINANCE_TOOLCHAIN_DESCRIBE,
    V4_FINANCE_WORKBENCH_OPEN,
    register_finance_tool_surface,
)
from kernel_v4.loop import SingleAgentLoop, SingleAgentLoopConfig
from kernel_v4.runtime import AbortController, WorkflowEventSink
from kernel_v4.tooling import ToolRegistry

_QUESTION_KEYS = ("question", "query", "prompt", "task", "user_message")
_CONTEXT_KEYS = (
    "provided_context",
    "oracle_context",
    "context",
    "report_context",
    "prompt_context",
    "table",
    "tables",
    "evidence_text",
    "evidence",
)
_NESTED_CONTEXT_CONTAINERS = ("metadata",)
_TASK_ID_KEYS = ("task_id", "id", "benchmark_id", "item_id", "question_id")
_SAFE_METADATA_KEYS = {
    "benchmark_family",
    "dataset",
    "split",
    "offset",
    "company",
    "companies",
    "ticker",
    "tickers",
    "identifier",
    "identifiers",
    "cik",
    "form",
    "doc_link",
    "doc_name",
    "doc_period",
    "doc_type",
    "filing_url",
    "source_url",
    "period",
    "fiscal_year",
    "fiscal_period",
    "question_type",
    "category",
}
_GOLD_REFERENCE_EXACT_KEYS = {
    "gold",
    "gold_answer",
    "gold_answers",
    "gold_program",
    "gold_reference",
    "reference",
    "reference_answer",
    "reference_answers",
    "reference_program",
    "answer",
    "answers",
    "final_answer",
    "expected",
    "expected_answer",
    "expected_answers",
    "expected_numeric",
    "label",
    "labels",
    "rubric",
    "scoring",
    "score",
    "annotation",
    "annotations",
    "rationale",
    "explanation",
    "program",
    "qa_program",
}
_GOLD_REFERENCE_KEY_MARKERS = (
    "gold",
    "reference_answer",
    "expected_answer",
    "expected_numeric",
    "gold_numeric",
    "answer_numeric",
)


@dataclass(frozen=True, kw_only=True)
class FinanceQuestionSpec:
    """No-gold task packet for Kernel v4 finance runs.

    This is an input contract, not a solver. It packages the benchmark/user
    question, optional supplied context, and safe metadata while keeping
    reference/gold/scoring fields out of the model-visible prompt.
    """

    question: str
    task_id: str | None = None
    benchmark_family: str = "finance"
    provided_context: str | None = None
    provided_context_format: str | None = None
    source_policy: str = "public_filings_or_provided_context"
    metadata: JsonObject = field(default_factory=dict)
    excluded_gold_reference_fields: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, Any],
        *,
        benchmark_family: str | None = None,
        source_policy: str = "public_filings_or_provided_context",
        provided_context_format: str | None = None,
    ) -> "FinanceQuestionSpec":
        excluded = tuple(sorted(key for key in row if _is_gold_reference_key(key)))
        question = _first_text(row, _QUESTION_KEYS)
        if not question:
            raise ValueError("finance question row does not contain a question/prompt field")
        return cls(
            question=question,
            task_id=_first_text(row, _TASK_ID_KEYS) or None,
            benchmark_family=(benchmark_family or _first_text(row, ("benchmark_family", "dataset")) or "finance"),
            provided_context=_first_serialized(row, _CONTEXT_KEYS),
            provided_context_format=provided_context_format or _first_text(row, ("context_format", "format")),
            source_policy=source_policy,
            metadata=_safe_metadata(row),
            excluded_gold_reference_fields=excluded,
        )

    def to_user_message(self) -> str:
        packet: JsonObject = {
            "schema": "holo.kernel_v4.finance_question_packet.v1",
            "benchmark_family": self.benchmark_family,
            "source_policy": self.source_policy,
            "question": self.question,
            "gold_reference_material_included": False,
            "excluded_gold_reference_field_count": len(self.excluded_gold_reference_fields),
            "solver_contract": [
                "Use the question and supplied context/tools only; no benchmark gold/reference answer is provided.",
                "For broad or ambiguous finance tasks, call finance.workbench.open when available to assemble task-family evidence, transform, artifact, and verification contracts before choosing concrete tools.",
                "When calling tools, include every required input field from the tool schema; never send empty arguments for tools with required fields.",
                "For provided_context.parse use {'context_ref': 'task_provided_context'} when supplied context is large, or {'context': supplied_context_text} for short snippets. For calculator.compute use {'expression': arithmetic_expression}; for data.table.query use {'sql': select_query}.",
                "If supplied context exists, inspect it with provided_context.parse before external retrieval unless the task clearly requires public filings.",
                "If supplied context already contains the relevant filing excerpt/table and line items, use at most one external source-validation step, then compute; do not rediscover every supplied row through external retrieval.",
                "After a successful parse/retrieval/read observation, do not repeat the same tool call with the same input; use the observed text_blocks, tables, or evidence and move to calculation, verification, or final answer.",
                "Before each additional retrieval/search/read/source tool call, identify the exact missing fact; if no exact missing fact remains, stop retrieving and compute or finalize.",
                "If filing evidence is required, use SEC/EDGAR or document tools and cite line items, periods, units, and source/artifact ids.",
                "When task metadata or the question names a target fiscal year, document period, or source URL, include that target in SEC/EDGAR and document tool calls; do not let default latest-filing behavior replace the requested period.",
                "If a company static source URL fails, call sec.edgar.company_filings with target fiscal_year/period/form, then sec.edgar.filing_documents for the relevant accession and extract the official SEC exhibit or primary document.",
                "For static company filing PDFs, 8-Ks, proxy/vote tables, or when Docling is slow or fails, use document.text.extract as the fast open-source text path before repeated document conversion attempts.",
                "Use market.openbb.fetch for prices, market data, and structured public financial-statement fundamentals only when useful. For target-document filing-accounting questions, do not call market/OpenBB unless the question explicitly asks for market data or the primary filing/document path has stalled; if used, keep the requested fiscal period explicit to avoid latest-period drift.",
                "Use calculator.compute, data.table.query, calendar.days_between, math.sympy.compute, and finance.verify_numeric as needed.",
                "When calling finance.verify_numeric, do not use a newly asserted answer number as its own proof. Bind facts to observed evidence/citation text or use calculator traces whose input values are tied to observed evidence, citations, or user-provided assumptions.",
                "For trend, improvement, worsening, drop, increase/decrease, or change questions, compute the latest value, prior/base comparable value, latest-minus-prior absolute change, and, for amount/balance/count level values, percent change from the prior/base value; for percentage ratios, report percentage-point change.",
                "For free cash flow conversion, unless the prompt/source defines another measure, use (net cash provided by operating activities - capex) / net income; retrieve capex from purchases of property/equipment or similar capital-expenditure labels and do not substitute operating cash flow / net income.",
                "Batch related arithmetic in as few calculator.compute calls as practical once the source inputs are observed.",
                "For product, service, business-overview, or 'what does the company sell' questions, retrieve Item 1 Business/Overview/Product descriptions from the target filing and finalize once the product/service list is observed; do not search financial statements or market data unless amounts or rankings are requested.",
                "For shareholder vote, board nominee, annual meeting, or Item 5.07 questions, retrieve the actual vote table from the target 8-K/proxy-related filing; search Proposal 1, Board of Directors, Votes For, Votes Against, Withheld, Abstentions, and Broker Non-Votes. For substantially-more-votes-against questions, compare every nominee's Votes Against value before answering.",
                "For margin-change or driver-analysis questions, retrieve the margin bridge and MD&A operating-expense discussion; include cost of sales/gross margin, SG&A, R&D, gains/impairments, and management-named special items when available.",
                "For revenue-change, sales-change, or 'what drove revenue/sales' questions, retrieve the MD&A revenue discussion and comparable segment table if useful; if management already names the drivers and no contribution-share ranking is requested, synthesize instead of expanding into market data or repeated statement retrieval.",
                "For yes/no disclosure questions, answer yes/no directly and include exact disclosed numbers such as percentages, amounts, customer counts, dates, and segment qualifiers when the evidence contains them.",
                "For legal battle, legal proceedings, litigation, lawsuit, regulatory investigation, or contingency-disclosure questions, retrieve actual Item 3 Legal Proceedings and relevant legal/contingency notes for each requested year. Do not rely only on table-of-contents entries, risk factors, cautionary forward-looking language, or generic statements. If income-statement legal charges are found, still search the legal-proceedings/contingencies note for named matters, settlement amounts, accruals, or loss ranges. Name proceedings or matter categories plus years, status, amounts/accruals, and source section when disclosed.",
                "For revenue-threshold category questions, such as whether any product/service categories, reportable segments, businesses, or similar categories exceed a stated share of revenue/sales, retrieve the complete comparable category table, compute each category's share of total revenue, and list every category that meets the threshold rather than only one example.",
                "For liquidation, bankruptcy-recovery, book-value-per-share, tangible-book-value, or shareholder residual questions, resolve the metric basis before finalizing: compare total equity, common stockholders' equity, tangible common equity, preferred-stock priority, goodwill/intangible exclusions, and shares outstanding when those concepts may change the answer.",
                "For store-count, location-count, branch-count, square-footage, or footprint-change questions, retrieve comparable period store data/counts, compute latest-minus-prior change, and answer whether the count changed; do not use market/OpenBB for these filing count questions.",
                "For segment-growth or M&A-exclusion questions, map excluding M&A to organic sales when available; retrieve the Worldwide Sales Change by Business Segment table and compare organic sales across all segments before ranking.",
                "For gross-margin profile questions, retrieve revenue, every relevant cost-of-sales row, and any directly reported gross profit/subtotal immediately following those rows. Prefer the filing-reported subtotal when present, reconcile it to component rows, normalize whether cost rows are positive cost magnitudes or signed negative expenses, compute latest/prior gross margins and percentage-point change, and state whether the metric is useful or limited for the business context.",
                "For primary-customer, customer-concentration, major-customer, or 'who are the customers' questions, retrieve Item 1 Business and customer-concentration disclosures; include customer groups plus any disclosed revenue share, concentration percentage, customer count, or named government/customer group.",
                "For dividend, shareholder-distribution, stability/trend, or common-shareholder payment questions, retrieve Item 5 Dividends and the shareholders' equity/dividends note when useful; search quarterly cash dividend, common shareholders, common stock, dividends per share, dividends declared, and dividends paid. Do not confuse subsidiary dividends to the parent with dividends paid to common shareholders.",
                "For acquisition or transaction-list questions, carry disclosed cash consideration, purchase price, goodwill, and ownership percentages into the final table when present; ownership percentage is not a substitute for cash consideration.",
                "For liquidity or working-capital questions, treat the metric basis as potentially ambiguous: compute standard net working capital from total current assets minus total current liabilities, and compute operating/non-cash working capital from current operating asset/liability components when those rows are available. State which basis is used and include the alternate when it could affect interpretation.",
                "For capital-intensity or asset-intensity questions, consider revenue/sales, capex, PP&E, total assets, operating cash flow, and profitability/ROA as candidate evidence; compute multiple relevant ratios when facts are available, including capex/revenue, PP&E/revenue, PP&E/assets, capex/operating cash flow, asset turnover, and ROA; do not decide from one ratio alone if more relevant facts are available.",
                "For restructuring, reserve, accrual, allowance, or liability-nature questions, retrieve the liability rollforward or composition table; if component amounts and a total are present, compute the dominant component's percentage of the total before explaining the purpose from the note.",
                "When using ROA/profitability for a business-characterization task, prefer net income / total assets when those facts are available; operating income / assets is only supplemental unless the question asks for operating ROA.",
                "Do not introduce unsourced generic threshold numbers for business judgment; self-edit the final answer to remove unsupported industry benchmark percentages, and distinguish material fixed assets from a capital-intensive business.",
                "After the needed calculation or verification succeeds, give the final answer instead of calling more tools only to restate the same result.",
                "Do not finalize early while another available tool can resolve missing evidence or arithmetic.",
                "Final answers must be compact scoring-ready answers. Do not include repeated internal retry narration, scratchpad loops, or long tool-plan text.",
            ],
            "metadata": self.metadata,
        }
        if self.task_id:
            packet["task_id"] = self.task_id
        if self.provided_context:
            packet["provided_context"] = {
                "format": self.provided_context_format or "auto",
                "text": self.provided_context,
            }
        return (
            "Finance task packet. It intentionally excludes benchmark gold/reference material.\n"
            + json.dumps(packet, ensure_ascii=False, sort_keys=True)
        )


def build_finance_registry(*, allow_network: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=allow_network)
    registry.install_core_tools()
    return registry


async def audit_finance_question_closure(
    spec: FinanceQuestionSpec,
    *,
    registry: ToolRegistry | None = None,
    allow_network: bool = True,
) -> JsonObject:
    """No-provider structural audit from one finance row to the v4 closure contracts.

    This is deliberately not a scorer or solver. It checks whether a no-gold task
    packet can reach workbench profiles whose tools exist in the active registry.
    """

    active_registry = _ensure_finance_registry(registry or build_finance_registry(allow_network=allow_network), allow_network=allow_network)
    audit_mode = _closure_audit_mode(spec=spec, allow_network=allow_network)
    context = ToolUseContext(
        run_id=f"closure-audit-{_stable_digest(spec.question)[:12]}",
        thread_key=spec.task_id or "kernel-v4-finance-closure-audit",
        metadata=_initial_finance_metadata(spec),
    )
    toolchain = await active_registry.execute(
        ToolCall(
            tool_call_id="closure-toolchain-audit",
            name=V4_FINANCE_TOOLCHAIN_AUDIT,
            input={"mode": audit_mode},
        ),
        context,
    )
    workbench_query = _closure_workbench_query(spec)
    workbench_input: JsonObject = {"query": workbench_query, "max_profiles": 8}
    if audit_mode == "no_network_fqa":
        workbench_input["task_family"] = "provided_context_fqa_finqa,table_ranking_aggregation,finance_transforms,numeric_verification"
        workbench_input["max_profiles"] = 4
    workbench = await active_registry.execute(
        ToolCall(
            tool_call_id="closure-workbench-open",
            name=V4_FINANCE_WORKBENCH_OPEN,
            input=workbench_input,
        ),
        context,
    )
    selected_profiles = _selected_profiles(workbench.content)
    registered = {manifest.name for manifest in active_registry.all_manifests()}
    selected_missing_tools = _missing_tools_for_profiles(selected_profiles, registered=registered)
    status = "ok"
    failure_reasons: list[str] = []
    if toolchain.is_error or not isinstance(toolchain.content, dict) or toolchain.content.get("status") != "ok":
        status = "failed"
        failure_reasons.append("toolchain_audit_not_ok")
    if workbench.is_error or not selected_profiles:
        status = "failed"
        failure_reasons.append("workbench_profiles_unavailable")
    if selected_missing_tools:
        status = "failed"
        failure_reasons.append("selected_profile_tools_missing")
    user_packet = spec.to_user_message()
    return {
        "schema": "holo.kernel_v4.finance_question_closure_audit.v1",
        "status": status,
        "failure_reasons": failure_reasons,
        "audit_mode": audit_mode,
        "allow_network": allow_network,
        "task": _finance_task_summary(spec),
        "packet_summary": {
            "chars": len(user_packet),
            "sha256": _stable_digest(user_packet),
            "gold_reference_material_included": False,
        },
        "toolchain_audit": _safe_tool_content(toolchain.content),
        "workbench": {
            "query_chars": len(workbench_query),
            "query_sha256": _stable_digest(workbench_query),
            "selected_profile_families": [str(profile.get("family")) for profile in selected_profiles],
            "selected_profile_count": len(selected_profiles),
            "selected_missing_tools": selected_missing_tools,
        },
        "gold_reference_material_included": False,
        "capability_claim": False,
        "benchmark_progress_claim": False,
        "host_boundary": "Closure audit checks theoretical contracts and registered tools only; it does not solve or score the task.",
    }


async def run_finance_question(
    spec: FinanceQuestionSpec,
    *,
    model: ModelClient,
    registry: ToolRegistry | None = None,
    allow_network: bool = True,
    config: SingleAgentLoopConfig | None = None,
    thread_key: str | None = None,
    run_id: str | None = None,
    abort_controller: AbortController | None = None,
    workflow_event_handler: WorkflowEventSink | None = None,
) -> LoopResult:
    active_registry = _ensure_finance_registry(registry or build_finance_registry(allow_network=allow_network), allow_network=allow_network)
    loop = SingleAgentLoop(
        model=model,
        tools=active_registry,
        config=config
        or SingleAgentLoopConfig(
            finance_mode=True,
            max_turns=64,
            max_tool_calls=200,
            max_tool_result_chars=12_000,
            model_context_mode="off",
        ),
    )
    return await loop.run(
        spec.to_user_message(),
        thread_key=thread_key or spec.task_id or "kernel-v4-finance-question",
        run_id=run_id,
        initial_metadata=_initial_finance_metadata(spec),
        abort_controller=abort_controller,
        workflow_event_handler=workflow_event_handler,
    )


def _ensure_finance_registry(registry: ToolRegistry, *, allow_network: bool) -> ToolRegistry:
    if any(
        registry.get(name) is None
        for name in (V4_FINANCE_TOOLCHAIN_DESCRIBE, V4_FINANCE_TOOLCHAIN_AUDIT, V4_FINANCE_WORKBENCH_OPEN)
    ):
        register_finance_tool_surface(registry, allow_network=allow_network)
    registry.install_core_tools()
    return registry


def _initial_finance_metadata(spec: FinanceQuestionSpec) -> JsonObject:
    metadata: JsonObject = {
        "task_question": spec.question,
        "task_safe_metadata": dict(spec.metadata),
        "enable_endgame_checkpoint": True,
        "enable_calculation_checkpoint": True,
        "enable_repeated_source_checkpoint": True,
        "endgame_evidence_success_threshold": 32,
        "calculation_evidence_success_threshold": 6,
        "repeated_source_success_threshold": 6,
        "repeated_source_error_threshold": 4,
        "source_saturation_evidence_success_threshold": 20,
    }
    if spec.provided_context:
        metadata["task_provided_context"] = spec.provided_context
        metadata["task_provided_context_format"] = spec.provided_context_format or "auto"
    return metadata


def _finance_task_summary(spec: FinanceQuestionSpec) -> JsonObject:
    return {
        "task_id": spec.task_id,
        "benchmark_family": spec.benchmark_family,
        "source_policy": spec.source_policy,
        "question_chars": len(spec.question),
        "question_sha256": _stable_digest(spec.question),
        "provided_context_chars": len(spec.provided_context or ""),
        "provided_context_sha256": _stable_digest(spec.provided_context or "") if spec.provided_context else "",
        "safe_metadata_keys": sorted(spec.metadata.keys()),
        "excluded_gold_reference_field_count": len(spec.excluded_gold_reference_fields),
    }


def _closure_audit_mode(*, spec: FinanceQuestionSpec, allow_network: bool) -> str:
    family = spec.benchmark_family.casefold()
    if not allow_network and spec.provided_context:
        return "no_network_fqa"
    if spec.provided_context and any(marker in family for marker in ("finqa", "fqa")):
        return "no_network_fqa"
    return "full"


def _closure_workbench_query(spec: FinanceQuestionSpec) -> str:
    pieces = [spec.question, spec.benchmark_family, spec.source_policy]
    if spec.provided_context:
        pieces.append("provided context fqa finqa table paragraph")
    for key in ("company", "ticker", "period", "fiscal_year", "category", "question_type", "doc_type"):
        value = spec.metadata.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            pieces.append(str(value))
    return " ".join(piece for piece in pieces if piece).strip()


def _selected_profiles(content: object) -> list[JsonObject]:
    if not isinstance(content, dict):
        return []
    profiles = content.get("selected_profiles")
    if not isinstance(profiles, list):
        return []
    return [dict(profile) for profile in profiles if isinstance(profile, dict)]


def _missing_tools_for_profiles(profiles: list[JsonObject], *, registered: set[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for profile in profiles:
        tools: set[str] = set()
        for key in ("primary_tools", "support_tools"):
            value = profile.get(key)
            if isinstance(value, list):
                tools.update(str(tool) for tool in value if str(tool))
        absent = sorted(tool for tool in tools if tool not in registered)
        if absent:
            missing[str(profile.get("family") or "unknown")] = absent
    return missing


def _safe_tool_content(content: object) -> JsonObject:
    return dict(content) if isinstance(content, dict) else {"content_preview": str(content)[:1000]}


def _stable_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_gold_reference_key(key: object) -> bool:
    lowered = str(key).casefold()
    if lowered in _GOLD_REFERENCE_EXACT_KEYS:
        return True
    return any(marker in lowered for marker in _GOLD_REFERENCE_KEY_MARKERS)


def _first_text(row: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _first_serialized(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    direct = _first_serialized_from_mapping(row, keys)
    if direct:
        return direct
    for container_key in _NESTED_CONTEXT_CONTAINERS:
        nested = row.get(container_key)
        if not isinstance(nested, Mapping):
            continue
        serialized = _first_serialized_from_mapping(nested, keys)
        if serialized:
            return serialized
    return None


def _first_serialized_from_mapping(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key not in row or _is_gold_reference_key(key):
            continue
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
            continue
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return None


def _safe_metadata(row: Mapping[str, Any]) -> JsonObject:
    metadata: JsonObject = {}
    _copy_safe_metadata_fields(row, metadata)
    nested = row.get("metadata")
    if isinstance(nested, Mapping):
        _copy_safe_metadata_fields(nested, metadata)
    return metadata


def _copy_safe_metadata_fields(row: Mapping[str, Any], metadata: JsonObject) -> None:
    for key, value in row.items():
        if key not in _SAFE_METADATA_KEYS or _is_gold_reference_key(key):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
        elif isinstance(value, (list, tuple)):
            metadata[key] = [item for item in value if isinstance(item, (str, int, float, bool)) or item is None]
