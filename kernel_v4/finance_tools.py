from __future__ import annotations

from dataclasses import replace
from typing import Any

from kernel_v3.context import ArtifactStore as V3ArtifactStore
from kernel_v3.contracts import CandidateAction, PolicyDecision
from kernel_v3.finance.calculator import register_finance_tools
from kernel_v3.finance.open_components import (
    CALENDAR_DAYS_BETWEEN_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    PROVIDED_CONTEXT_PARSE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    register_finance_open_component_tools,
)
from kernel_v3.tools import ToolRegistry as V3ToolRegistry
from kernel_v4.context import ToolUseContext
from kernel_v4.contracts import JsonObject, ToolManifest
from kernel_v4.tooling import ToolRegistry

V4_FINANCE_TOOLCHAIN_DESCRIBE = "finance.toolchain.describe"
FORBIDDEN_LEGACY_TOOLS = {"finance.slot_bind"}


def register_finance_tool_surface(
    registry: ToolRegistry,
    *,
    allow_network: bool = True,
    artifact_store: V3ArtifactStore | None = None,
) -> ToolRegistry:
    """Register finance tools without importing v3's semantic gates."""

    artifact_store = artifact_store or V3ArtifactStore.in_memory()
    v3_registry = V3ToolRegistry.with_builtin_respond()
    register_finance_tools(v3_registry)
    register_finance_open_component_tools(v3_registry, artifact_store=artifact_store)
    registry.register(
        ToolManifest(
            name="artifact.read",
            description="Read a Kernel v4 artifact or a document/tool artifact produced by delegated mature finance tools.",
            input_schema={
                "artifact_id": {"type": "string", "required": True},
                "max_chars": {"type": "integer", "required": False},
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=50_000,
        ),
        _artifact_read_executor(artifact_store),
    )

    for v3_manifest in v3_registry.manifests():
        if v3_manifest.name in {"__respond__", "__ask_user__", "system.time", V4_FINANCE_TOOLCHAIN_DESCRIBE}:
            continue
        if v3_manifest.name in FORBIDDEN_LEGACY_TOOLS:
            continue
        if not allow_network and v3_manifest.side_effect_class == "network":
            continue
        manifest = _from_v3_manifest(v3_manifest)
        registry.register(
            manifest,
            _v3_tool_executor(v3_registry=v3_registry, manifest_name=v3_manifest.name),
        )

    registry.register(
        ToolManifest(
            name=V4_FINANCE_TOOLCHAIN_DESCRIBE,
            description=(
                "Describe the Kernel v4 finance tool surface. This is a tool catalog only; "
                "there is no FactLedger, SlotFrame, or finance.slot_bind gate."
            ),
            input_schema={},
            concurrency_safe=True,
            always_load=True,
            max_result_chars=20_000,
        ),
        _finance_toolchain_describe,
    )
    return registry


def register_calculator_tool_surface(registry: ToolRegistry) -> ToolRegistry:
    """Register only the mature calculator tool for focused tool-loop smoke tests."""

    v3_registry = V3ToolRegistry.with_builtin_respond()
    register_finance_tools(v3_registry)
    for v3_manifest in v3_registry.manifests():
        if v3_manifest.name != "calculator.compute":
            continue
        registry.register(
            _from_v3_manifest(v3_manifest),
            _v3_tool_executor(v3_registry=v3_registry, manifest_name=v3_manifest.name),
        )
    return registry


def finance_tool_names() -> list[str]:
    return [
        V4_FINANCE_TOOLCHAIN_DESCRIBE,
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        PROVIDED_CONTEXT_PARSE_TOOL_NAME,
        MARKET_OPENBB_FETCH_TOOL_NAME,
        DATA_TABLE_QUERY_TOOL_NAME,
        MATH_SYMPY_COMPUTE_TOOL_NAME,
        CALENDAR_DAYS_BETWEEN_TOOL_NAME,
        "calculator.compute",
        "finance.verify_numeric",
    ]


def _from_v3_manifest(manifest: Any) -> ToolManifest:
    runtime = dict(getattr(manifest, "runtime", {}) or {})
    side_effect = str(getattr(manifest, "side_effect_class", "read") or "read")
    return ToolManifest(
        name=str(manifest.name),
        description=str(manifest.description or manifest.name),
        input_schema=dict(manifest.input_schema or {}),
        side_effect_class=side_effect,
        concurrency_safe=bool(runtime.get("concurrency_safe", side_effect in {"read", "network", "none"})),
        enabled=bool(manifest.enabled),
        should_defer=bool(runtime.get("should_defer", False)),
        always_load=bool(runtime.get("always_load", True)),
        timeout_seconds=_int_or_none(runtime.get("timeout_seconds")),
        max_result_chars=_int_or_none(runtime.get("max_result_size_chars")) or 50_000,
    )


def _v3_tool_executor(*, v3_registry: V3ToolRegistry, manifest_name: str):
    async def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        action_id = f"v4-{manifest_name}-{len(context.messages)}"
        action = CandidateAction(
            action_id=action_id,
            kind="tool",
            name=manifest_name,
            description=f"Kernel v4 delegated call to {manifest_name}",
            score=1.0,
            payload=dict(payload),
            reasons=["kernel_v4_model_requested_tool"],
            side_effect_class=_side_effect(v3_registry, manifest_name),
        )
        policy = PolicyDecision(
            decision_id=f"policy-{action_id}",
            run_id=context.run_id,
            action_id=action.action_id,
            allowed=True,
            reason="kernel_v4_tool_policy",
            constraints={"tool_name": manifest_name, "side_effect_class": action.side_effect_class},
        )
        result = v3_registry.execute_with_artifacts(
            action,
            policy_decision=policy,
            execution_context={"run_id": context.run_id, "task_id": context.thread_key},
        )
        for artifact in result.artifact_refs:
            context.metadata.setdefault("v3_artifacts", {})[artifact.artifact_id] = artifact.to_dict()
        observation = result.observation
        return {
            "schema": "holo.kernel_v4.v3_tool_observation.v1",
            "tool": manifest_name,
            "status": observation.status,
            "kind": observation.kind,
            "source": observation.source,
            "content": observation.content,
            "artifact_refs": [artifact.to_dict() for artifact in result.artifact_refs],
            "host_boundary": "v4 delegated execution only; semantic decisions remain with the model",
        }

    return execute


def _finance_toolchain_describe(payload: JsonObject, context: ToolUseContext) -> JsonObject:
    del payload, context
    return {
        "schema": "holo.kernel_v4.finance_toolchain.v1",
        "architecture": "single_agent_reference_style_loop",
        "removed_legacy_gates": ["FactLedger", "SlotFrame", "finance.slot_bind", "host semantic slot completion gate"],
        "one_shot_loop_contract": {
            "decision_owner": "model",
            "host_role": "validate_execute_record_compact_only",
            "tool_use_boundary": (
                "All finance evidence retrieval, parsing, transformation, calculation, and verification must happen "
                "through model-requested tool calls inside this loop; the host does not create hidden finance answers."
            ),
            "benchmark_solvability_policy": (
                "Assume FinanceBench/FQA/FinQA-style tasks are intended to be solvable from public filings, supplied "
                "context, or allowed tools. Continue with another source/tool strategy while budget remains."
            ),
            "no_gold_policy": "Gold/reference answers are not model context and must not be inferred from benchmark ids.",
            "stop_rule": (
                "Finalize only after observed evidence supports the answer, required arithmetic has a calculator/table "
                "observation when tools are available, and final material numeric claims have been verified when "
                "finance.verify_numeric is available; otherwise call the next relevant tool or state a precise blocker."
            ),
            "answer_output_contract": {
                "required_elements": [
                    "direct answer to the exact question",
                    "source-backed inputs with line item labels, periods, units, dates, and artifact/source ids",
                    "formula and methodological choices such as average versus ending balance or fiscal day basis",
                    "calculator.compute or data.table.query observation for derived finance numbers when available",
                    "finance.verify_numeric observation for final material numeric claims when available",
                    "comparison direction and business-context reasoning without hard-coded thresholds",
                ],
                "forbidden_elements": [
                    "generic failure text when partial cited evidence can answer",
                    "hard-coded threshold substituted for finance judgment",
                    "benchmark-id lookup or cached gold answer",
                    "mental arithmetic for material derived finance numbers when calculator.compute is available",
                ],
            },
        },
        "coverage_families": [
            {
                "family": "public_filing_evidence",
                "when": "FinanceBench-style public-company questions requiring filing facts, exact line items, or SEC/XBRL facts.",
                "primary_tools": [
                    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
                    SEC_EDGAR_FINANCIALS_TOOL_NAME,
                    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
                    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
                    "artifact.read",
                ],
            },
            {
                "family": "provided_context_fqa_finqa",
                "when": "FQA/FinQA prompts containing supplied report context, oracle_context, copied tables, CSV, HTML, or markdown snippets.",
                "primary_tools": [PROVIDED_CONTEXT_PARSE_TOOL_NAME, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            },
            {
                "family": "table_ranking_aggregation",
                "when": "Questions requiring joins, filtering, sorting, ranking, grouping, or aggregation over observed rows.",
                "primary_tools": [DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            },
            {
                "family": "finance_transforms",
                "when": "Ratios, margins, DIO/DSO/DPO, growth, bps, averages, multiples, and comparisons.",
                "primary_tools": ["calculator.compute", DATA_TABLE_QUERY_TOOL_NAME, MATH_SYMPY_COMPUTE_TOOL_NAME],
            },
            {
                "family": "fiscal_dates",
                "when": "Actual fiscal day counts, period lengths, and date-difference transforms.",
                "primary_tools": [CALENDAR_DAYS_BETWEEN_TOOL_NAME, "calculator.compute"],
            },
            {
                "family": "market_data",
                "when": "Prices, market data, or allowlisted market/fundamental routes not answered by filings or supplied context.",
                "primary_tools": [MARKET_OPENBB_FETCH_TOOL_NAME],
            },
            {
                "family": "numeric_verification",
                "when": "Final material finance numeric claims before answer delivery.",
                "primary_tools": ["finance.verify_numeric"],
            },
        ],
        "tool_protocol": [
            "Use SEC/EDGAR or retrieval tools for authoritative evidence.",
            "Use document conversion and document.search.hybrid for long filings or tables.",
            "Use provided_context.parse for FinQA/FQA supplied contexts.",
            "Use data.table.query for table filtering, grouping, ranking, and aggregation.",
            "Use calendar.days_between for model-selected fiscal date differences.",
            "Use calculator.compute for deterministic arithmetic once you have observed inputs.",
            "Use finance.verify_numeric before final material finance numeric claims when available.",
            "Use tool.discovery when a needed registered tool is not visible in the current provider tool surface.",
        ],
        "available_tools": finance_tool_names(),
        "decision_owner": "model",
        "host_role": "validate_execute_record_compact_only",
    }


def _artifact_read_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "")
        max_chars = _int_or_none(payload.get("max_chars")) or 20_000
        max_chars = max(1, min(max_chars, 200_000))
        if artifact_id in context.artifacts:
            content = context.read_artifact(artifact_id)
            return {
                "schema": "holo.kernel_v4.artifact_read_result.v1",
                "artifact_id": artifact_id,
                "source": "kernel_v4_context",
                "chars": len(content),
                "text": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        if artifact_store.has_blob(artifact_id):
            raw = artifact_store.read_blob(artifact_id, record_access=True, access_context={"reader": "kernel_v4"})
            content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            return {
                "schema": "holo.kernel_v4.artifact_read_result.v1",
                "artifact_id": artifact_id,
                "source": "delegated_finance_artifact_store",
                "chars": len(content),
                "text": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        raise KeyError(f"unknown artifact: {artifact_id}")

    return execute


def _side_effect(v3_registry: V3ToolRegistry, name: str) -> str:
    dummy = CandidateAction(
        action_id="manifest-probe",
        kind="tool",
        name=name,
        description="manifest probe",
        score=1.0,
        payload={},
        reasons=[],
    )
    manifest = v3_registry.manifest_for_action(dummy)
    return str(manifest.side_effect_class if manifest is not None else "read")


def _int_or_none(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
