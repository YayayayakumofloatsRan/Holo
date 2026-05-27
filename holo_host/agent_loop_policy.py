from __future__ import annotations

from typing import Any

from .common import compact_text

AGENT_LOOP_POLICY_SCHEMA = "holo.stage161.agent_loop_policy.v1"

ALLOWED_STOP_REASONS = {
    "final_answer_ready",
    "goal_complete",
    "needs_user_clarification",
    "evidence_exhausted",
    "budget_exhausted",
    "low_marginal_utility",
    "boundary_or_permission",
    "tool_failure_report",
    "model_final_no_tool_calls",
}


def _failure_guidance(action: str, status: str, error: str = "") -> str:
    detail = compact_text(error or status or "unknown error", 160)
    return f"{action} was attempted but failed: {detail}. Report the attempted failure; do not phrase it as a future intent."


def evaluate_stage161_loop_policy(
    *,
    selected_action: str,
    action_status: str,
    retry_count: int = 0,
    retry_budget: int = 0,
    observation_status: str = "",
    error: str = "",
    unsupported_claim: bool = False,
) -> dict[str, Any]:
    action = str(selected_action or "answer_direct")
    status = str(action_status or "")
    observation = str(observation_status or status)
    if unsupported_claim:
        stop_reason = "evidence_exhausted"
        next_step = "final"
        guidance = "Final answer contains unsupported claims; repair or ask for evidence before delivery."
    elif status in {"executed", "ok", "success"} or observation == "ok":
        stop_reason = "final_answer_ready"
        next_step = "final"
        guidance = "Observation is sufficient for a grounded final answer."
    elif status == "rejected" or observation == "rejected_network_disabled":
        stop_reason = "boundary_or_permission"
        next_step = "final"
        guidance = _failure_guidance(action, observation, error or observation)
    elif status in {"failed", "error"} or observation in {"error", "failed"}:
        stop_reason = "tool_failure_report"
        if int(retry_count or 0) < int(retry_budget or 0):
            next_step = "retry"
            guidance = "Tool failed; retry is permitted with revised arguments."
        else:
            next_step = "final"
            guidance = _failure_guidance(action, observation, error or observation)
    elif action in {"ask_clarification", "defer"}:
        stop_reason = "needs_user_clarification"
        next_step = "final"
        guidance = "Ask for clarification or report why the task is deferred."
    else:
        stop_reason = "final_answer_ready"
        next_step = "final"
        guidance = "No additional host action is required."
    if stop_reason not in ALLOWED_STOP_REASONS:
        stop_reason = "final_answer_ready"
    return {
        "schema": AGENT_LOOP_POLICY_SCHEMA,
        "selected_action": action,
        "action_status": status,
        "observation_status": observation,
        "retry_count": int(retry_count or 0),
        "retry_budget": int(retry_budget or 0),
        "next_step": next_step,
        "canonical_stop_reason": stop_reason,
        "final_guidance": guidance,
    }
