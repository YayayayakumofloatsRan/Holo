from __future__ import annotations

from typing import Any

from .common import compact_text, utc_now

GOAL_STATE_SCHEMA = "holo.stage160r.goal_state.v1"


def coerce_goal_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema") == GOAL_STATE_SCHEMA:
        return dict(value)
    if isinstance(value, dict):
        nested = value.get("stage160r_goal_state") or value.get("agent_goal_state")
        if isinstance(nested, dict):
            return coerce_goal_state(nested)
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            nested = metadata.get("stage160r_goal_state") or metadata.get("agent_goal_state")
            if isinstance(nested, dict):
                return coerce_goal_state(nested)
    return {
        "schema": GOAL_STATE_SCHEMA,
        "last_goal_id": "",
        "last_goal_text": "",
        "last_intent_type": "",
        "last_required_actions": [],
        "last_required_observations": [],
        "last_observation_summary": "",
        "last_answer_summary": "",
        "last_stop_reason": "",
        "open_followup": False,
        "pending_clarification": False,
        "updated_at": "",
    }


def update_goal_state(
    previous_goal_state: dict[str, Any] | None,
    intent_frame: dict[str, Any],
    fsm_report: dict[str, Any],
    *,
    final_text: str = "",
) -> dict[str, Any]:
    previous = coerce_goal_state(previous_goal_state)
    goal_id = str(intent_frame.get("goal_id", "") or previous.get("last_goal_id", "") or "")
    goal_text = str(intent_frame.get("normalized_goal", "") or previous.get("last_goal_text", "") or "")
    stop_reason = str(fsm_report.get("canonical_stop_reason", "") or fsm_report.get("stop_reason", "") or "final_answer_ready")
    observations = []
    for step in list(fsm_report.get("steps", []) or []):
        if isinstance(step, dict) and step.get("observation_ids"):
            observations.extend(str(item) for item in list(step.get("observation_ids", []) or []) if str(item).strip())
    intent_type = str(intent_frame.get("intent_type", "") or previous.get("last_intent_type", "") or "")
    return {
        "schema": GOAL_STATE_SCHEMA,
        "last_goal_id": goal_id,
        "last_goal_text": compact_text(goal_text, 260),
        "last_intent_type": intent_type,
        "last_required_actions": [str(item) for item in list(intent_frame.get("mandatory_actions", []) or [])],
        "last_required_observations": [str(item) for item in list(intent_frame.get("required_observations", []) or [])],
        "last_observation_summary": compact_text("; ".join(observations), 300),
        "last_answer_summary": compact_text(final_text, 300),
        "last_stop_reason": stop_reason,
        "open_followup": intent_type in {"memory_recall", "web_lookup", "followup"} or stop_reason not in {"final_answer_ready", "goal_complete"},
        "pending_clarification": stop_reason == "needs_user_clarification",
        "updated_at": utc_now(),
    }
