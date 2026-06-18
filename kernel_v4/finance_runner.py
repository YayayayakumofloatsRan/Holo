from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kernel_v4.contracts import JsonObject, LoopResult, ModelClient
from kernel_v4.finance_tools import V4_FINANCE_TOOLCHAIN_DESCRIBE, register_finance_tool_surface
from kernel_v4.loop import SingleAgentLoop, SingleAgentLoopConfig
from kernel_v4.runtime import AbortController, WorkflowEventSink
from kernel_v4.tooling import ToolRegistry

_QUESTION_KEYS = ("question", "query", "prompt", "task", "user_message")
_CONTEXT_KEYS = (
    "provided_context",
    "oracle_context",
    "context",
    "evidence",
    "evidence_text",
    "report_context",
    "table",
    "tables",
)
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
                "When calling tools, include every required input field from the tool schema; never send empty arguments for tools with required fields.",
                "For provided_context.parse use {'context': supplied_context_text}; for calculator.compute use {'expression': arithmetic_expression}; for data.table.query use {'sql': select_query}.",
                "If supplied context exists, inspect it with provided_context.parse before external retrieval unless the task clearly requires public filings.",
                "After a successful parse/retrieval/read observation, do not repeat the same tool call with the same input; use the observed text_blocks, tables, or evidence and move to calculation, verification, or final answer.",
                "If filing evidence is required, use SEC/EDGAR or document tools and cite line items, periods, units, and source/artifact ids.",
                "Use calculator.compute, data.table.query, calendar.days_between, math.sympy.compute, and finance.verify_numeric as needed.",
                "After the needed calculation or verification succeeds, give the final answer instead of calling more tools only to restate the same result.",
                "Do not finalize early while another available tool can resolve missing evidence or arithmetic.",
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
    active_registry = registry or build_finance_registry(allow_network=allow_network)
    if active_registry.get(V4_FINANCE_TOOLCHAIN_DESCRIBE) is None:
        register_finance_tool_surface(active_registry, allow_network=allow_network)
    loop = SingleAgentLoop(
        model=model,
        tools=active_registry,
        config=config
        or SingleAgentLoopConfig(
            finance_mode=True,
            max_turns=24,
            max_tool_calls=80,
        ),
    )
    return await loop.run(
        spec.to_user_message(),
        thread_key=thread_key or spec.task_id or "kernel-v4-finance-question",
        run_id=run_id,
        abort_controller=abort_controller,
        workflow_event_handler=workflow_event_handler,
    )


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
    for key, value in row.items():
        if key not in _SAFE_METADATA_KEYS or _is_gold_reference_key(key):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
        elif isinstance(value, (list, tuple)):
            metadata[key] = [item for item in value if isinstance(item, (str, int, float, bool)) or item is None]
    return metadata
