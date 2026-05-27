from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now
from .memory_grounding import normalize_memory_observation_ledger

AGENT_LOOP_FSM_SCHEMA = "holo.stage160r.agent_loop_fsm.v1"
LOOP_STEP_SCHEMA = "holo.stage160r.loop_step.v1"

ALLOWED_NEW_STOP_REASONS = {
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


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _step(
    *,
    index: int,
    phase: str,
    goal_id: str,
    selected_action: str = "",
    action_status: str = "",
    skip_reason: str = "",
    required_observations: list[str] | None = None,
    observation_ids: list[str] | None = None,
    new_information_score: float = 0.0,
    unresolved_items: list[str] | None = None,
    stop_candidate: bool = False,
    canonical_stop_reason: str = "",
) -> dict[str, Any]:
    return {
        "schema": LOOP_STEP_SCHEMA,
        "step_id": "stage160r_step:" + stable_digest(goal_id, phase, selected_action, str(index), limit=10),
        "step_index": index,
        "phase": phase,
        "goal_id": goal_id,
        "selected_action": selected_action,
        "action_status": action_status,
        "skip_reason": skip_reason,
        "required_observations": list(required_observations or []),
        "observation_ids": list(observation_ids or []),
        "new_information_score": round(max(0.0, min(1.0, float(new_information_score or 0.0))), 4),
        "unresolved_items": list(unresolved_items or []),
        "stop_candidate": bool(stop_candidate),
        "canonical_stop_reason": canonical_stop_reason,
    }


def build_host_memory_recall_ledger(
    intent_frame: dict[str, Any],
    *,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    tool_observation_ledger: Any = None,
    active_memory_refresh: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    actions = set(str(item) for item in list(intent_frame.get("mandatory_actions", []) or []))
    if "memory_recall" not in actions:
        return []
    rows = normalize_memory_observation_ledger(
        sidecar=sidecar or {},
        reply_debug=reply_debug or {},
        tool_observation_ledger=tool_observation_ledger or [],
        active_memory_refresh=active_memory_refresh or {},
        query=str(intent_frame.get("normalized_goal", "") or intent_frame.get("raw_user_text_exact", "")),
    )
    if rows:
        return rows
    return [
        {
            "schema": "holo.memory_grounding.v1",
            "memory_call_id": "stage160r_memory_unavailable:" + stable_digest(intent_frame.get("goal_id", ""), limit=10),
            "source_family": "none",
            "selected_ids": [],
            "status": "unavailable",
            "summary": "host memory recall was required but no recall surface was available",
            "confidence": 0.0,
            "freshness": "none",
            "grounding_tags": [],
            "contradiction_flags": [],
            "missing_source": True,
        }
    ]


def _memory_status(rows: list[dict[str, Any]]) -> tuple[str, list[str], float]:
    if not rows:
        return "failed", [], 0.0
    ids = [str(row.get("memory_call_id", "") or "") for row in rows if str(row.get("memory_call_id", "") or "")]
    statuses = {str(row.get("status", "") or "") for row in rows}
    if statuses & {"grounded"}:
        return "executed", ids, 0.78
    if statuses & {"weak"}:
        return "executed", ids, 0.35
    return "failed", ids, 0.0


def _web_status(rows: list[dict[str, Any]]) -> tuple[str, str, list[str], float, list[str]]:
    if not rows:
        return "failed", "tool_failure_report", [], 0.0, ["web_action_not_executed"]
    ids = [str(row.get("observation_id", "") or "") for row in rows if str(row.get("observation_id", "") or "")]
    statuses = [str(row.get("status", "") or "") for row in rows]
    if any(status == "ok" for status in statuses):
        return "executed", "final_answer_ready", ids, 0.82, []
    if any(status == "rejected_network_disabled" for status in statuses):
        return "rejected", "boundary_or_permission", ids, 0.0, ["network_disabled"]
    return "failed", "tool_failure_report", ids, 0.0, [str(row.get("error", "") or row.get("status", "") or "web_error") for row in rows[:2]]


def _failure_text(intent_frame: dict[str, Any], action: str, rows: list[dict[str, Any]], stop_reason: str) -> str:
    raw = str(intent_frame.get("raw_user_text_exact", "") or "")
    wants_zh = any("\u4e00" <= char <= "\u9fff" for char in raw)
    if action == "memory_recall":
        if wants_zh:
            return "\u6211\u5df2\u5c1d\u8bd5 memory_recall\uff0c\u4f46\u6ca1\u6709\u627e\u5230\u53ef\u9a8c\u8bc1\u7684\u5148\u524d\u5bf9\u8bdd\u8bc1\u636e\u3002"
        return "I attempted memory_recall but found no grounded prior-conversation evidence."
    if action in {"web_search", "open_page", "find_in_page"}:
        row = rows[0] if rows else {}
        status = str(row.get("status", "not_executed") or "not_executed")
        error = str(row.get("error", "") or status)
        if wants_zh:
            return f"\u6211\u5df2\u7ecf\u5c1d\u8bd5 {action}\uff0c\u4f46\u5931\u8d25\u4e86\uff1a{compact_text(error, 160)}\u3002\u56e0\u6b64\u4e0d\u80fd\u628a\u5b83\u5f53\u6210\u5f53\u524d\u8054\u7f51\u8bc1\u636e\u3002"
        return f"{action} was attempted but failed: {compact_text(error, 160)}. I cannot treat this as current web evidence."
    if stop_reason == "needs_user_clarification":
        return "I need a clarification before continuing this agent task."
    return "The required agent action did not produce enough evidence for a grounded final answer."


def run_agent_loop_fsm(
    *,
    intent_frame: dict[str, Any],
    previous_goal_state: dict[str, Any] | None = None,
    model_arbitration: dict[str, Any] | None = None,
    tool_decision_validation: dict[str, Any] | None = None,
    tool_decision: dict[str, Any] | None = None,
    web_observation_ledger: Any = None,
    memory_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
    final_text: str = "",
) -> dict[str, Any]:
    goal_id = str(intent_frame.get("goal_id", "") or "goal:" + stable_digest(intent_frame, limit=10))
    arbitration = dict(model_arbitration or {})
    selected_action = str(arbitration.get("selected_action", "") or "").strip()
    stage161_model_first = bool(arbitration)
    if stage161_model_first:
        if selected_action in {"", "answer_direct"}:
            mandatory = []
        elif selected_action in {"ask_clarification", "defer"}:
            mandatory = [selected_action]
        else:
            mandatory = [selected_action]
    else:
        mandatory = [str(item) for item in list(intent_frame.get("mandatory_actions", []) or []) if str(item).strip()]
        selected_action = ",".join(mandatory) if mandatory else "answer_direct"
    required_observations = [str(item) for item in list(intent_frame.get("required_observations", []) or []) if str(item).strip()]
    if stage161_model_first:
        for item in list(arbitration.get("required_observations", []) or []):
            text = str(item or "").strip()
            if text and text not in required_observations:
                required_observations.append(text)
    steps: list[dict[str, Any]] = [
        _step(index=0, phase="observe", goal_id=goal_id, required_observations=required_observations, new_information_score=0.1),
    ]
    if stage161_model_first:
        steps.append(
            _step(
                index=1,
                phase="model_decide",
                goal_id=goal_id,
                selected_action=selected_action or "answer_direct",
                required_observations=required_observations,
                new_information_score=float(arbitration.get("confidence", 0.2) or 0.2),
            )
        )
    else:
        steps.append(
            _step(
                index=1,
                phase="decide",
                goal_id=goal_id,
                selected_action=selected_action,
                required_observations=required_observations,
                new_information_score=0.2,
            )
        )
    stop_reason = "final_answer_ready"
    final_override_text = ""
    unresolved: list[str] = []
    web_rows = _list_dicts(web_observation_ledger)
    memory_rows = _list_dicts(memory_observation_ledger)
    index = 2
    for action in mandatory:
        if action == "memory_recall":
            status, ids, info_score = _memory_status(memory_rows)
            local_stop = "final_answer_ready" if status == "executed" and info_score >= 0.45 else "evidence_exhausted"
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                final_override_text = _failure_text(intent_frame, action, memory_rows, local_stop)
                unresolved.append("memory_observation_ledger")
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["memory_observation_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["memory_observation_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action in {"web_search", "open_page", "find_in_page"}:
            relevant = [row for row in web_rows if str(row.get("action_type", "") or "web_search") == action or action == "web_search"]
            status, local_stop, ids, info_score, local_unresolved = _web_status(relevant)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                final_override_text = _failure_text(intent_frame, action, relevant, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["web_observation_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["web_observation_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action in {"ask_clarification", "defer"}:
            stop_reason = "needs_user_clarification"
            reason = str(arbitration.get("fallback_if_failed", "") or arbitration.get("why_this_action", "") or action)
            final_override_text = compact_text(reason, 220) if reason else "I need clarification before continuing this agent task."
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status="skipped", skip_reason=action, required_observations=required_observations, unresolved_items=[action], canonical_stop_reason=stop_reason))
            index += 1
        else:
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status="skipped", skip_reason="host_action_not_implemented", required_observations=required_observations, unresolved_items=[action], canonical_stop_reason="needs_user_clarification"))
            index += 1
            stop_reason = "needs_user_clarification"
    if stop_reason == "unknown":
        stop_reason = "final_answer_ready"
    if stop_reason not in ALLOWED_NEW_STOP_REASONS:
        stop_reason = "final_answer_ready"
    steps.append(
        _step(
            index=index,
            phase="evaluate_stop",
            goal_id=goal_id,
            selected_action="evaluate_stop",
            action_status="executed",
            required_observations=required_observations,
            new_information_score=0.2 if unresolved else 0.7,
            unresolved_items=unresolved,
            stop_candidate=True,
            canonical_stop_reason=stop_reason,
        )
    )
    index += 1
    steps.append(
        _step(
            index=index,
            phase="final",
            goal_id=goal_id,
            selected_action="final",
            action_status="executed",
            required_observations=required_observations,
            new_information_score=0.1,
            unresolved_items=unresolved,
            stop_candidate=True,
            canonical_stop_reason=stop_reason,
        )
    )
    return {
        "schema": AGENT_LOOP_FSM_SCHEMA,
        "status": "completed",
        "goal_id": goal_id,
        "intent_type": str(intent_frame.get("intent_type", "") or ""),
        "stage161_model_first": stage161_model_first,
        "selected_action": selected_action,
        "stage161_model_tool_arbitration": arbitration,
        "stage161_tool_decision_validation": dict(tool_decision_validation or {}),
        "mandatory_actions": mandatory,
        "required_observations": required_observations,
        "step_count": len(steps),
        "steps": steps,
        "canonical_stop_reason": stop_reason,
        "stop_reason": stop_reason,
        "final_override_text": final_override_text,
        "final_text": final_override_text or str(final_text or ""),
        "unresolved_items": unresolved,
        "time_observation_present": bool(time_observation),
        "created_at": utc_now(),
    }


def repair_final_with_fsm(text: str, fsm_report: dict[str, Any], *, channel: str = "") -> str:
    override = str(fsm_report.get("final_override_text", "") or "").strip()
    if override:
        return override
    return str(text or "")
