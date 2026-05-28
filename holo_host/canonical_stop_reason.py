from __future__ import annotations

from typing import Any

CANONICAL_STOP_REASON_SCHEMA = "holo.stage159.canonical_stop_reason.v1"

CANONICAL_STOP_REASONS = {
    "final_answer_ready",
    "goal_complete",
    "needs_user_clarification",
    "evidence_exhausted",
    "budget_exhausted",
    "low_marginal_utility",
    "boundary_or_permission",
    "tool_failure_report",
    "model_final_no_tool_calls",
    "unknown",
}

_REASON_MAP = {
    "no_tool_calls": "model_final_no_tool_calls",
    "model_final_no_tool_calls": "model_final_no_tool_calls",
    "tool_call_budget_exceeded": "budget_exhausted",
    "max_rounds_reached": "budget_exhausted",
    "budget_exhausted": "budget_exhausted",
    "stage142_duplicate_suppressed": "low_marginal_utility",
    "suppressed_duplicate": "low_marginal_utility",
    "low_marginal_utility": "low_marginal_utility",
    "needs_clarification": "needs_user_clarification",
    "ask_clarification": "needs_user_clarification",
    "rejected_network_disabled": "boundary_or_permission",
    "permission_denied": "boundary_or_permission",
    "boundary_or_permission": "boundary_or_permission",
    "tool_error": "tool_failure_report",
    "error": "tool_failure_report",
    "failed": "tool_failure_report",
    "tool_failure": "tool_failure_report",
    "ungrounded_web_claim": "evidence_exhausted",
    "evidence_exhausted": "evidence_exhausted",
    "goal_complete": "goal_complete",
    "final": "final_answer_ready",
    "final_answer_ready": "final_answer_ready",
}


def canonicalize_stop_reason(reason: Any) -> str:
    current = str(reason or "").strip().lower()
    return _REASON_MAP.get(current, "unknown" if current else "final_answer_ready")


def map_canonical_stop_reason(
    *,
    stage143: dict[str, Any] | None = None,
    stage151: dict[str, Any] | None = None,
    stage152: dict[str, Any] | None = None,
    stage153: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = (
        ("stage152_deepseek_tool_loop", stage152, "stop_reason"),
        ("stage143_packet_budget", stage143, "stop_reason"),
        ("stage151_tool_decision", stage151, "stop_reason"),
        ("stage153_agent_event_stream", stage153, "stop_reason"),
    )
    raw_reason = ""
    source = "none"
    for source_name, payload, key in sources:
        if not isinstance(payload, dict) or not payload:
            continue
        raw_reason = str(payload.get(key, "") or payload.get("stage152_stop_reason", "") or "")
        if raw_reason:
            source = source_name
            break
        if source_name == "stage151_tool_decision":
            rows = list(payload.get("web_observation_ledger", []) or []) if isinstance(payload.get("web_observation_ledger", []), list) else []
            if any(isinstance(row, dict) and str(row.get("status", "")) == "rejected_network_disabled" for row in rows):
                raw_reason = "rejected_network_disabled"
                source = source_name
                break
            if any(isinstance(row, dict) and str(row.get("status", "")) in {"error", "failed"} for row in rows):
                raw_reason = "tool_error"
                source = source_name
                break
    canonical = canonicalize_stop_reason(raw_reason)
    return {
        "schema": CANONICAL_STOP_REASON_SCHEMA,
        "canonical_stop_reason": canonical,
        "canonical_stop_source": source,
        "raw_stop_reason": raw_reason,
    }
