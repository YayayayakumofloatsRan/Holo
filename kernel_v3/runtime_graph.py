from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from kernel_v3.contracts import Contract, JsonObject


RUNTIME_GRAPH_SCHEMA = "holo.kernel_v3.runtime_graph_delta.v1"
TOPOLOGY_SCHEMA = "holo.kernel_v3.runtime_topology.v1"


@dataclass(frozen=True, kw_only=True)
class RuntimeGraphDelta(Contract):
    schema: str
    sequence: int
    record_id: str
    task_id: str | None
    run_id: str
    step_id: str | None
    kind: str
    stage: str
    timestamp_ms: int
    node_updates: list[JsonObject] = field(default_factory=list)
    edge_updates: list[JsonObject] = field(default_factory=list)
    terminal: bool = False
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RuntimeTopologyProjection(Contract):
    schema: str
    nodes: list[JsonObject]
    edges: list[JsonObject]
    terminal: bool
    latest_stage: str | None
    diagnostics: JsonObject


STAGE_DEFINITIONS: tuple[tuple[str, frozenset[str], str], ...] = (
    ("Intake", frozenset({"chat_turn", "chat_routing_decision", "semantic_intake", "compiled_task_program"}), "understand task"),
    ("Plan", frozenset({"processor_request", "processor_result", "action", "toolchain_step_proposed"}), "LLM proposes next move"),
    ("Policy", frozenset({"policy_decision"}), "host validates action"),
    (
        "Tools",
        frozenset({"observation", "calculator_result", "retrieval_fetch", "retrieval_fetch_attempt"}),
        "execute bounded tools",
    ),
    (
        "Search",
        frozenset({"retrieval_query_plan", "retrieval_search_attempt", "retrieval_workbench_decision"}),
        "branch over sources",
    ),
    (
        "Evidence",
        frozenset(
            {
                "retrieval_extraction",
                "retrieval_evidence",
                "retrieval_citation",
                "claim_ledger",
                "slot_frame",
                "finance_fact_ledger",
                "finance_slot_bind",
            }
        ),
        "build cited ledger and bind slots",
    ),
    (
        "Verify",
        frozenset(
            {
                "transform_plan",
                "finance_formula_plan",
                "finance_numeric_preflight",
                "finance_numeric_verification",
                "finance_numeric_judge",
                "finance_numeric_judge_repair",
                "finance_synthesis_compaction",
                "verifier_gate_result",
                "synthesis_gate_result",
            }
        ),
        "check numbers and support",
    ),
    (
        "Answer",
        frozenset({"termination_decision", "feedback", "agent_final_answer", "agent_failure_report", "chat_agent_result"}),
        "reply or explain gap",
    ),
)

STAGE_ORDER = tuple(stage for stage, _, _ in STAGE_DEFINITIONS)
STAGE_DETAILS = {stage: detail for stage, _, detail in STAGE_DEFINITIONS}
STAGE_KIND_MAP = {kind: stage for stage, kinds, _ in STAGE_DEFINITIONS for kind in kinds}
CANONICAL_EDGES: tuple[tuple[str, str, str], ...] = (
    ("Intake", "Plan", "forward"),
    ("Plan", "Policy", "forward"),
    ("Policy", "Tools", "forward"),
    ("Tools", "Search", "forward"),
    ("Search", "Evidence", "forward"),
    ("Evidence", "Verify", "forward"),
    ("Verify", "Answer", "forward"),
    ("Answer", "Intake", "loopback"),
)


def runtime_stage_for_kind(kind: str) -> str:
    return STAGE_KIND_MAP.get(kind, "Run")


def is_terminal_record(record: Mapping[str, Any] | Any) -> bool:
    return str(_record_value(record, "kind") or "") in {"agent_final_answer", "agent_failure_report", "chat_agent_result"}


def records_until_terminal(records: list[Mapping[str, Any] | Any]) -> list[Mapping[str, Any] | Any]:
    for index, record in enumerate(records):
        if is_terminal_record(record):
            return records[: index + 1]
    return list(records)


def loop_topology_state(records: list[Mapping[str, Any] | Any]) -> list[JsonObject]:
    return runtime_topology_projection(records).nodes


def runtime_topology_projection(records: list[Mapping[str, Any] | Any]) -> RuntimeTopologyProjection:
    visible = records_until_terminal(records)
    ignored_post_terminal = records[len(visible) :] if len(visible) < len(records) else []
    latest_kind = str(_record_value(visible[-1], "kind") or "") if visible else ""
    latest_stage = runtime_stage_for_kind(latest_kind) if latest_kind else None
    terminal = any(is_terminal_record(record) for record in visible)
    terminal_record = visible[-1] if terminal and visible else None
    has_failure = any(_record_is_failure(record) for record in visible)
    nodes: list[JsonObject] = []
    stage_counts: dict[str, int] = {}
    for stage, kinds, detail in STAGE_DEFINITIONS:
        count = sum(1 for record in visible if str(_record_value(record, "kind") or "") in kinds)
        stage_counts[stage] = count
        state = "idle"
        if count:
            state = "active" if stage == latest_stage and not terminal else "ok"
        if terminal and stage == "Answer" and count and not has_failure:
            state = "closed"
        if has_failure and stage in {"Verify", "Answer"} and count:
            state = "warn"
        nodes.append(
            {
                "label": stage,
                "state": state,
                "value": count,
                "count": count,
                "detail": detail,
                "last_at": max(
                    (
                        int(_record_value(record, "recorded_at_ms") or 0)
                        for record in visible
                        if str(_record_value(record, "kind") or "") in kinds
                    ),
                    default=0,
                ),
                "latest": bool(stage == latest_stage and count and not terminal),
            }
        )
    edges = _canonical_edge_rows(nodes)
    return RuntimeTopologyProjection(
        schema=TOPOLOGY_SCHEMA,
        nodes=nodes,
        edges=edges,
        terminal=terminal,
        latest_stage=latest_stage,
        diagnostics={
            "raw_record_count": len(records),
            "record_count": len(visible),
            "terminal": terminal,
            "has_failure": has_failure,
            "latest_kind": latest_kind,
            "frozen_at_record_id": str(_record_value(terminal_record, "record_id") or "") if terminal_record is not None else None,
            "frozen_at_ms": int(_record_value(terminal_record, "recorded_at_ms") or 0) if terminal_record is not None else None,
            "ignored_post_terminal_record_count": len(ignored_post_terminal),
            "ignored_post_terminal_record_kind_counts": _kind_counts(ignored_post_terminal),
            "stage_counts": stage_counts,
        },
    )


def runtime_graph_delta_stream(records: list[Mapping[str, Any] | Any]) -> list[JsonObject]:
    deltas: list[JsonObject] = []
    visible = records_until_terminal(records)
    previous_stage: str | None = None
    counts = {stage: 0 for stage in STAGE_ORDER}
    for sequence, record in enumerate(visible, start=1):
        kind = str(_record_value(record, "kind") or "")
        stage = runtime_stage_for_kind(kind)
        if stage not in counts:
            continue
        counts[stage] += 1
        terminal = is_terminal_record(record)
        status = _status_for_record(record)
        state = "closed" if terminal and stage == "Answer" and status != "failed" else status
        stage_index = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1
        node_update = {
            "node_id": f"stage:{stage.lower()}",
            "label": stage,
            "node_type": "agent_loop_stage",
            "state": state,
            "count": counts[stage],
            "latest_kind": kind,
            "detail": STAGE_DETAILS.get(stage, ""),
            "stage_index": stage_index,
            "loop_iteration": _loop_iteration_for_record(record),
        }
        observation_diagnostics = _tool_observation_diagnostics(record)
        if observation_diagnostics:
            node_update["observation_diagnostics"] = observation_diagnostics
        edge_updates: list[JsonObject] = []
        if previous_stage is not None and previous_stage != stage:
            edge_updates.append(
                {
                    "source": f"stage:{previous_stage.lower()}",
                    "target": f"stage:{stage.lower()}",
                    "edge_type": "runtime_transition",
                    "state": "active",
                    "loop_iteration": _loop_iteration_for_record(record),
                }
            )
        previous_stage = stage
        delta = RuntimeGraphDelta(
            schema=RUNTIME_GRAPH_SCHEMA,
            sequence=sequence,
            record_id=str(_record_value(record, "record_id") or ""),
            task_id=_optional_text(_record_value(record, "task_id")),
            run_id=str(_record_value(record, "run_id") or ""),
            step_id=_optional_text(_record_value(record, "step_id")),
            kind=kind,
            stage=stage,
            timestamp_ms=int(_record_value(record, "recorded_at_ms") or 0),
            node_updates=[node_update],
            edge_updates=edge_updates,
            terminal=terminal,
            metadata={
                **_record_metadata(record),
                **({"observation_diagnostics": observation_diagnostics} if observation_diagnostics else {}),
                "stage_index": stage_index,
                "loop_iteration": _loop_iteration_for_record(record),
            },
        )
        deltas.append(delta.to_dict())
        if terminal:
            break
    return deltas


def _canonical_edge_rows(nodes: list[JsonObject]) -> list[JsonObject]:
    node_state = {str(node.get("label") or ""): str(node.get("state") or "idle") for node in nodes}
    rows: list[JsonObject] = []
    for source, target, edge_type in CANONICAL_EDGES:
        visited = node_state.get(source, "idle") != "idle" and node_state.get(target, "idle") != "idle"
        active = node_state.get(target) == "active"
        rows.append(
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "state": "active" if active else ("visited" if visited else "idle"),
            }
        )
    return rows


def _record_is_failure(record: Mapping[str, Any] | Any) -> bool:
    kind = str(_record_value(record, "kind") or "")
    if kind == "agent_failure_report":
        return True
    data = _record_data(record)
    return kind == "chat_agent_result" and isinstance(data.get("failure_report"), dict)


def _kind_counts(records: list[Mapping[str, Any] | Any]) -> JsonObject:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(_record_value(record, "kind") or "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _loop_iteration_for_record(record: Mapping[str, Any] | Any) -> int | None:
    step_id = _optional_text(_record_value(record, "step_id"))
    if not step_id:
        return None
    prefix = "step-"
    if step_id.startswith(prefix):
        suffix = step_id[len(prefix) :]
        if suffix.isdigit():
            return int(suffix)
    return None


def _status_for_record(record: Mapping[str, Any] | Any) -> str:
    if _record_is_failure(record):
        return "failed"
    kind = str(_record_value(record, "kind") or "")
    if kind == "processor_request":
        return "running"
    data = _record_data(record)
    status = str(data.get("status") or data.get("decision") or "").lower()
    if status in {"failed", "error", "blocked"}:
        return "failed"
    if is_terminal_record(record):
        return "completed"
    return "completed"


def _record_metadata(record: Mapping[str, Any] | Any) -> JsonObject:
    data = _record_data(record)
    metadata: JsonObject = {}
    for key in (
        "request_id",
        "processor",
        "task_type",
        "action_id",
        "tool",
        "tool_name",
        "observation_id",
        "status",
        "decision",
        "stop_reason",
    ):
        value = data.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is not None and value != "":
                metadata[key] = value
    return metadata


def _tool_observation_diagnostics(record: Mapping[str, Any] | Any) -> JsonObject:
    data = _record_data(record)
    if str(_record_value(record, "kind") or "") != "observation":
        return {}
    if not str(data.get("source") or "").startswith("tool:") and data.get("kind") != "finance_numeric_verification":
        return {}
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    if not content:
        return {}
    result: JsonObject = {}
    for key in ("verifier_status", "issue_count", "matched_value_count", "missing_value_count"):
        value = content.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is not None:
                result[key] = value
    guidance = content.get("repair_guidance") if isinstance(content.get("repair_guidance"), dict) else {}
    guidance_source = guidance if guidance else content
    schema = guidance_source.get("schema") if isinstance(guidance_source, dict) else None
    if isinstance(schema, str) and schema:
        result["guidance_schema"] = _bounded_text(schema, limit=96)
    issue_codes = _string_list(guidance_source.get("issue_codes") if isinstance(guidance_source, dict) else [])[:8]
    if issue_codes:
        result["issue_codes"] = issue_codes
    repair_options = _string_list(guidance_source.get("repair_options") if isinstance(guidance_source, dict) else [])[:4]
    if repair_options:
        result["repair_options"] = repair_options
    missing_examples = _compact_missing_value_examples(
        guidance_source.get("missing_value_examples") if isinstance(guidance_source, dict) else []
    )
    if missing_examples:
        result["missing_value_examples"] = missing_examples
    boundary = guidance_source.get("host_boundary") if isinstance(guidance_source, dict) else None
    if isinstance(boundary, str) and boundary:
        result["host_boundary"] = _bounded_text(boundary, limit=180)
    error = content.get("error") or content.get("reason")
    if isinstance(error, (str, int, float, bool)):
        result["error"] = _bounded_text(error, limit=160)
    return result


def _compact_missing_value_examples(values: Any) -> list[JsonObject]:
    items = values if isinstance(values, list) else []
    result: list[JsonObject] = []
    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "raw": _bounded_text(item.get("raw"), limit=64),
                "value": _bounded_text(item.get("value"), limit=48),
                "unit": _bounded_text(item.get("unit"), limit=32),
                "slot": _bounded_text(item.get("slot") or item.get("metric") or item.get("name"), limit=80),
            }
        )
    return result


def _string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    result: list[str] = []
    for item in items:
        if isinstance(item, str) and item:
            result.append(item)
    return result


def _bounded_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _record_value(record: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key)
    return getattr(record, key, None)


def _record_data(record: Mapping[str, Any] | Any) -> JsonObject:
    value = _record_value(record, "data")
    return dict(value) if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
