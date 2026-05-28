from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now
from .live_remediation_loop import build_live_remediation_loop
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


def _market_research_pack_status(rows: list[dict[str, Any]]) -> tuple[str, str, list[str], float, list[str]]:
    if not rows:
        return "failed", "evidence_exhausted", [], 0.0, ["market_research_pack_ledger"]
    ids = [str(row.get("action_id", "") or "") for row in rows if str(row.get("action_id", "") or "")]
    statuses = [str(row.get("status", "") or "") for row in rows]
    if any(status == "ok" for status in statuses):
        return "executed", "final_answer_ready", ids, 0.84, []
    if any(status == "rejected_network_disabled" for status in statuses):
        return "rejected", "boundary_or_permission", ids, 0.0, ["network_disabled"]
    unresolved = [
        str(reason)
        for row in rows[:2]
        for reason in list(row.get("failure_reasons", []) or [row.get("status", "market_research_pack_insufficient")])
        if str(reason)
    ]
    return "failed", "evidence_exhausted", ids, 0.18, unresolved or ["market_research_pack_insufficient"]


def _market_research_report_status(rows: list[dict[str, Any]]) -> tuple[str, str, list[str], float, list[str]]:
    if not rows:
        return "failed", "evidence_exhausted", [], 0.0, ["market_research_report_ledger"]
    ids = [str(row.get("action_id", "") or "") for row in rows if str(row.get("action_id", "") or "")]
    statuses = [str(row.get("status", "") or "") for row in rows]
    if any(status == "ok" for status in statuses):
        return "executed", "final_answer_ready", ids, 0.88, []
    unresolved = [
        str(reason)
        for row in rows[:2]
        for reason in list(row.get("failure_reasons", []) or [row.get("status", "market_research_report_insufficient")])
        if str(reason)
    ]
    return "failed", "evidence_exhausted", ids, 0.2, unresolved or ["market_research_report_insufficient"]


def _market_research_dossier_resume_status(rows: list[dict[str, Any]]) -> tuple[str, str, list[str], float, list[str]]:
    if not rows:
        return "failed", "needs_user_clarification", [], 0.0, ["market_research_dossier_resume_ledger"]
    ids = [str(row.get("action_id", "") or "") for row in rows if str(row.get("action_id", "") or "")]
    statuses = [str(row.get("status", "") or "") for row in rows]
    if any(status in {"resumed", "completed", "already_complete", "no_next_action", "recorded"} for status in statuses):
        return "executed", "final_answer_ready", ids, 0.86, []
    if any(status == "missing" for status in statuses):
        return "failed", "needs_user_clarification", ids, 0.0, ["persisted_market_research_dossier_missing"]
    if any(status == "rejected_network_disabled" for status in statuses):
        return "rejected", "boundary_or_permission", ids, 0.0, ["network_disabled"]
    unresolved = [str(row.get("summary", "") or row.get("status", "market_research_dossier_resume_failed")) for row in rows[:2]]
    return "failed", "evidence_exhausted", ids, 0.18, unresolved or ["market_research_dossier_resume_failed"]


def _market_research_operator_status(
    action_report: dict[str, Any],
    operator_run: dict[str, Any],
) -> tuple[str, str, list[str], float, list[str]]:
    if not action_report and not operator_run:
        return "failed", "evidence_exhausted", [], 0.0, ["stage214_market_research_operator_run"]
    action_status = str(action_report.get("status", "") or "")
    run_status = str(operator_run.get("status", "") or "")
    ids = [
        text
        for text in (
            str(action_report.get("action_id", "") or ""),
            str(action_report.get("operator_run_id", "") or ""),
            str(operator_run.get("operator_run_id", "") or ""),
        )
        if text
    ]
    if action_status == "executed" and run_status == "ready":
        return "executed", "final_answer_ready", ids, 0.92, []
    if not action_report and run_status == "ready":
        return "executed", "final_answer_ready", ids, 0.9, []
    if action_status == "rejected":
        return "rejected", "boundary_or_permission", ids, 0.0, ["market_research_operator_rejected"]
    unresolved = [
        str(reason)
        for reason in list(action_report.get("failure_reasons", []) or operator_run.get("failure_reasons", []) or [])
        if str(reason)
    ]
    if not unresolved:
        unresolved = [run_status or action_status or "market_research_operator_failed"]
    return "failed", "tool_failure_report", ids, 0.2, unresolved


def _web_research_operator_status(operator_run: dict[str, Any]) -> tuple[str, str, list[str], float, list[str]]:
    if not operator_run:
        return "failed", "evidence_exhausted", [], 0.0, ["stage218_web_research_operator_run"]
    run_status = str(operator_run.get("status", "") or "")
    ids = [text for text in (str(operator_run.get("operator_run_id", "") or ""),) if text]
    if run_status == "ready":
        return "executed", "final_answer_ready", ids, 0.9, []
    if run_status == "rejected":
        reasons = [
            str(reason)
            for reason in list(operator_run.get("failure_reasons", []) or [])
            if str(reason)
        ] or [str(operator_run.get("canonical_stop_reason", "") or "web_research_operator_rejected")]
        return "rejected", "boundary_or_permission", ids, 0.0, reasons
    local_stop = str(operator_run.get("canonical_stop_reason", "") or "tool_failure_report")
    if local_stop not in ALLOWED_NEW_STOP_REASONS:
        local_stop = "tool_failure_report"
    reasons = [
        str(reason)
        for reason in list(operator_run.get("failure_reasons", []) or [])
        if str(reason)
    ] or [run_status or "web_research_operator_failed"]
    return "failed", local_stop, ids, 0.22, reasons


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
    if action == "market_research_pack":
        row = rows[0] if rows else {}
        reasons = ", ".join(str(item) for item in list(row.get("failure_reasons", []) or [])) or str(row.get("status", "") or "no pack")
        if wants_zh:
            return f"\u6211\u5df2\u5c1d\u8bd5 market_research_pack\uff0c\u4f46\u6ca1\u6709\u5f97\u5230\u8db3\u591f\u7684\u6743\u5a01\u8d22\u62a5\u8bc1\u636e\uff1a{compact_text(reasons, 160)}\u3002"
        return f"market_research_pack was attempted but did not produce sufficient filing evidence: {compact_text(reasons, 160)}."
    if action == "market_research_report":
        row = rows[0] if rows else {}
        reasons = ", ".join(str(item) for item in list(row.get("failure_reasons", []) or [])) or str(row.get("status", "") or "no report")
        if wants_zh:
            return f"\u6211\u5df2\u5c1d\u8bd5 market_research_report\uff0c\u4f46\u6ca1\u6709\u751f\u6210\u8db3\u591f\u53ef\u4fe1\u7684\u7814\u7a76\u62a5\u544a\uff1a{compact_text(reasons, 160)}\u3002"
        return f"market_research_report was attempted but did not produce a sufficient filing-grounded report: {compact_text(reasons, 160)}."
    if action == "market_research_dossier_resume":
        row = rows[0] if rows else {}
        detail = str(row.get("summary", "") or row.get("status", "") or "no persisted dossier")
        if wants_zh:
            return f"\u6211\u5df2\u5c1d\u8bd5 market_research_dossier_resume\uff0c\u4f46\u6ca1\u6709\u627e\u5230\u53ef\u7ee7\u7eed\u7684\u5e02\u573a\u7814\u7a76 dossier\uff1a{compact_text(detail, 160)}\u3002"
        return f"market_research_dossier_resume was attempted but no resumable dossier was available: {compact_text(detail, 160)}."
    if action == "market_research_operator_run":
        row = rows[0] if rows else {}
        reasons = ", ".join(str(item) for item in list(row.get("failure_reasons", []) or [])) or str(row.get("status", "") or "operator did not produce a ready run")
        if wants_zh:
            return f"\u6211\u5df2\u5c1d\u8bd5 market_research_operator_run\uff0c\u4f46\u5b8c\u6574\u7814\u7a76\u7b97\u5b50\u672a\u5f97\u5230\u53ef\u4ea4\u4ed8\u7ed3\u679c\uff1a{compact_text(reasons, 160)}\u3002"
        return f"market_research_operator_run was attempted but did not produce a ready research result: {compact_text(reasons, 160)}."
    if action == "web_research_operator_run":
        row = rows[0] if rows else {}
        reasons = ", ".join(str(item) for item in list(row.get("failure_reasons", []) or [])) or str(row.get("status", "") or "operator did not produce sufficient web evidence")
        if wants_zh:
            return f"\u6211\u5df2\u5c1d\u8bd5 web_research_operator_run\uff0c\u4f46\u6ca1\u6709\u5f97\u5230\u8db3\u591f\u8054\u7f51\u8bc1\u636e\uff1a{compact_text(reasons, 160)}\u3002"
        return f"web_research_operator_run was attempted but did not produce sufficient web evidence: {compact_text(reasons, 160)}."
    if stop_reason == "needs_user_clarification":
        return "I need a clarification before continuing this agent task."
    return "The required agent action did not produce enough evidence for a grounded final answer."


def _remediation_success_text(intent_frame: dict[str, Any], remediation_execution: dict[str, Any]) -> str:
    raw = str(intent_frame.get("raw_user_text_exact", "") or "")
    wants_zh = any("\u4e00" <= char <= "\u9fff" for char in raw)
    web_rows = _list_dicts(remediation_execution.get("web_observation_ledger", []))
    memory_rows = _list_dicts(remediation_execution.get("memory_observation_ledger", []))
    engineering_rows = _list_dicts(remediation_execution.get("engineering_action_ledger", []))
    if memory_rows:
        grounded = next((row for row in memory_rows if str(row.get("status", "") or "") == "grounded"), memory_rows[0])
        summary = compact_text(str(grounded.get("summary", "") or "memory evidence was retrieved"), 220)
        if wants_zh:
            return f"已执行 memory_recall，并取得可用记忆证据：{summary}"
        return f"memory_recall was executed and produced usable evidence: {summary}"
    if web_rows:
        ok_rows = [row for row in web_rows if str(row.get("status", "") or "") == "ok"]
        source_urls = [
            str(url)
            for row in ok_rows[:3]
            for url in list(row.get("source_urls", []) or [])[:2]
            if str(url)
        ]
        source_text = ", ".join(source_urls[:3]) if source_urls else "no source URL recorded"
        if wants_zh:
            return f"已执行 web_search，并取得联网观察记录。来源：{compact_text(source_text, 220)}"
        return f"web_search was executed and produced web observations. Sources: {compact_text(source_text, 220)}"
    if engineering_rows:
        changed = [
            str(path)
            for row in engineering_rows[:3]
            for path in list(row.get("files_changed", []) or row.get("files_read", []) or [])[:3]
            if str(path)
        ]
        detail = ", ".join(changed[:4]) if changed else "engineering ledger recorded"
        if wants_zh:
            return f"已执行工程补救动作，并记录工程 ledger：{compact_text(detail, 220)}"
        return f"The engineering remediation action was executed and ledgered: {compact_text(detail, 220)}"
    if wants_zh:
        return "已执行补救动作，并记录了可审计观察。"
    return "The remediation action was executed and recorded as auditable observation."


def _remediation_incomplete_text(intent_frame: dict[str, Any], remediation_execution: dict[str, Any], stop_reason: str) -> str:
    raw = str(intent_frame.get("raw_user_text_exact", "") or "")
    wants_zh = any("\u4e00" <= char <= "\u9fff" for char in raw)
    remaining = _list_dicts(remediation_execution.get("remaining_action_candidates", []))
    results = _list_dicts(remediation_execution.get("action_results", []))
    remaining_names = ", ".join(str(action.get("action_type", "") or "") for action in remaining[:4] if str(action.get("action_type", "") or ""))
    first_error = next((str(row.get("error", "") or "") for row in results if str(row.get("error", "") or "")), "")
    if stop_reason == "budget_exhausted":
        detail = remaining_names or "additional remediation actions"
        if wants_zh:
            return f"本轮补救动作预算已用完，仍有待执行动作：{compact_text(detail, 220)}。"
        return f"The remediation action budget is exhausted for this turn; remaining actions: {compact_text(detail, 220)}."
    if stop_reason == "needs_user_clarification":
        detail = first_error or remaining_names or "missing action input"
        if wants_zh:
            return f"补救动作需要进一步澄清才能继续：{compact_text(detail, 220)}。"
        return f"The remediation action needs clarification before continuing: {compact_text(detail, 220)}."
    if stop_reason == "boundary_or_permission":
        detail = first_error or "host boundary"
        if wants_zh:
            return f"补救动作被主机边界拒绝：{compact_text(detail, 220)}。"
        return f"The remediation action was rejected by a host boundary: {compact_text(detail, 220)}."
    if stop_reason == "tool_failure_report":
        detail = first_error or "tool execution failed"
        if wants_zh:
            return f"补救动作已经尝试，但工具失败：{compact_text(detail, 220)}。"
        return f"The remediation action was attempted but the tool failed: {compact_text(detail, 220)}."
    if wants_zh:
        return "补救动作尚未完成，不能把当前结果当作最终完成。"
    return "The remediation action is incomplete, so this turn cannot be treated as fully finalized."


def run_agent_loop_fsm(
    *,
    intent_frame: dict[str, Any],
    previous_goal_state: dict[str, Any] | None = None,
    model_arbitration: dict[str, Any] | None = None,
    tool_decision_validation: dict[str, Any] | None = None,
    tool_decision: dict[str, Any] | None = None,
    web_observation_ledger: Any = None,
    memory_observation_ledger: Any = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    market_research_dossier_resume_ledger: Any = None,
    stage215_market_research_operator_action: dict[str, Any] | None = None,
    stage214_market_research_operator_run: dict[str, Any] | None = None,
    stage218_web_research_operator_run: dict[str, Any] | None = None,
    stage201_market_research_dossier_registry: dict[str, Any] | None = None,
    stage178_evidence_action_remediation: dict[str, Any] | None = None,
    stage180_live_remediation_execution: dict[str, Any] | None = None,
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
    market_rows = _list_dicts(market_research_pack_ledger)
    market_report_rows = _list_dicts(market_research_report_ledger)
    dossier_resume_rows = _list_dicts(market_research_dossier_resume_ledger)
    market_operator_action = dict(stage215_market_research_operator_action or {})
    market_operator_run = dict(stage214_market_research_operator_run or {})
    web_research_operator_run = dict(stage218_web_research_operator_run or {})
    remediation_report = dict(stage178_evidence_action_remediation or {})
    live_remediation = build_live_remediation_loop(remediation_report, goal_id=goal_id, current_stop_reason=stop_reason) if remediation_report else {}
    remediation_execution = dict(stage180_live_remediation_execution or {})
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
        elif action == "market_research_pack":
            status, local_stop, ids, info_score, local_unresolved = _market_research_pack_status(market_rows)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                final_override_text = _failure_text(intent_frame, action, market_rows, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_pack_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_pack_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action == "market_research_report":
            status, local_stop, ids, info_score, local_unresolved = _market_research_report_status(market_report_rows)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                final_override_text = _failure_text(intent_frame, action, market_report_rows, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_report_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_report_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action == "market_research_dossier_resume":
            status, local_stop, ids, info_score, local_unresolved = _market_research_dossier_resume_status(dossier_resume_rows)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                final_override_text = _failure_text(intent_frame, action, dossier_resume_rows, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_dossier_resume_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["market_research_dossier_resume_ledger"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action == "market_research_operator_run":
            status, local_stop, ids, info_score, local_unresolved = _market_research_operator_status(market_operator_action, market_operator_run)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                rows = [market_operator_action] if market_operator_action else [market_operator_run] if market_operator_run else []
                final_override_text = _failure_text(intent_frame, action, rows, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["stage214_market_research_operator_run"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["stage214_market_research_operator_run"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
        elif action == "web_research_operator_run":
            status, local_stop, ids, info_score, local_unresolved = _web_research_operator_status(web_research_operator_run)
            if local_stop != "final_answer_ready":
                stop_reason = local_stop
                rows = [web_research_operator_run] if web_research_operator_run else []
                final_override_text = _failure_text(intent_frame, action, rows, local_stop)
                unresolved.extend(local_unresolved)
            steps.append(_step(index=index, phase="act_or_skip", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["stage218_web_research_operator_run"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
            index += 1
            steps.append(_step(index=index, phase="observe_result", goal_id=goal_id, selected_action=action, action_status=status, required_observations=["stage218_web_research_operator_run"], observation_ids=ids, new_information_score=info_score, unresolved_items=local_unresolved, canonical_stop_reason=local_stop))
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
    remediation_attempted = bool(remediation_execution) and bool(_list_dicts(remediation_execution.get("action_results", [])))
    remediation_executed = remediation_attempted and str(remediation_execution.get("status", "") or "") in {"executed", "partial"}
    if live_remediation and bool(live_remediation.get("blocked", False)) and not remediation_attempted:
        next_actions = _list_dicts(live_remediation.get("next_action_candidates", []))
        selected_next = dict(next_actions[0]) if next_actions else {}
        selected_type = str(selected_next.get("action_type", "") or live_remediation.get("selected_action_type", "") or "remediation")
        selected_tool = str(selected_next.get("required_tool", "") or live_remediation.get("selected_required_tool", "") or "")
        remediation_stop = str(live_remediation.get("canonical_stop_reason", "") or "evidence_exhausted")
        stop_reason = remediation_stop if remediation_stop in ALLOWED_NEW_STOP_REASONS else "evidence_exhausted"
        final_override_text = str(live_remediation.get("operator_message", "") or remediation_report.get("operator_message", "") or final_override_text)
        unresolved.extend(str(action.get("action_type", "") or action.get("issue_type", "") or "remediation") for action in next_actions)
        steps.append(
            _step(
                index=index,
                phase="remediation_decide",
                goal_id=goal_id,
                selected_action=selected_type,
                action_status="planned",
                required_observations=[selected_tool] if selected_tool else [],
                observation_ids=[str(selected_next.get("action_id", "") or "")] if selected_next else [],
                new_information_score=0.62,
                unresolved_items=[str(action.get("action_type", "") or "") for action in next_actions],
                canonical_stop_reason=stop_reason,
            )
        )
        index += 1
        steps.append(
            _step(
                index=index,
                phase="remediation_plan",
                goal_id=goal_id,
                selected_action=selected_type,
                action_status="planned",
                required_observations=[str(action.get("required_tool", "") or "") for action in next_actions if str(action.get("required_tool", "") or "")],
                observation_ids=[str(action.get("action_id", "") or "") for action in next_actions if str(action.get("action_id", "") or "")],
                new_information_score=0.68,
                unresolved_items=[str(action.get("action_type", "") or "") for action in next_actions],
                canonical_stop_reason=stop_reason,
            )
        )
        index += 1
    elif remediation_attempted:
        exec_results = _list_dicts(remediation_execution.get("action_results", []))
        remaining_actions = _list_dicts(remediation_execution.get("remaining_action_candidates", []))
        exec_stop = str(remediation_execution.get("canonical_stop_reason", "") or "final_answer_ready")
        stop_reason = exec_stop if exec_stop in ALLOWED_NEW_STOP_REASONS else "final_answer_ready"
        if stop_reason == "final_answer_ready":
            unresolved = []
            final_override_text = _remediation_success_text(intent_frame, remediation_execution)
        else:
            final_override_text = _remediation_incomplete_text(intent_frame, remediation_execution, stop_reason)
        if remaining_actions:
            unresolved = [str(action.get("action_type", "") or "") for action in remaining_actions]
        steps.append(
            _step(
                index=index,
                phase="remediation_execute",
                goal_id=goal_id,
                selected_action=str((exec_results[0] if exec_results else {}).get("action_type", "") or "remediation_execute"),
                action_status=str(remediation_execution.get("status", "") or "executed"),
                required_observations=[
                    name
                    for name, rows in (
                        ("web_observation_ledger", _list_dicts(remediation_execution.get("web_observation_ledger", []))),
                        ("memory_observation_ledger", _list_dicts(remediation_execution.get("memory_observation_ledger", []))),
                        ("engineering_action_ledger", _list_dicts(remediation_execution.get("engineering_action_ledger", []))),
                    )
                    if rows
                ],
                observation_ids=[str(row.get("action_id", "") or row.get("memory_call_id", "") or row.get("observation_id", "") or "") for row in exec_results],
                new_information_score=0.76,
                unresolved_items=[] if stop_reason == "final_answer_ready" else [str(action.get("action_type", "") or "") for action in remaining_actions] or [str(row.get("action_type", "") or "") for row in exec_results],
                canonical_stop_reason=stop_reason,
            )
        )
        index += 1
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
        "stage201_market_research_dossier_registry": dict(stage201_market_research_dossier_registry or {}),
        "market_research_dossier_resume_ledger": dossier_resume_rows,
        "stage215_market_research_operator_action": market_operator_action,
        "stage214_market_research_operator_run": market_operator_run,
        "stage218_web_research_operator_run": web_research_operator_run,
        "stage178_evidence_action_remediation": remediation_report,
        "stage179_live_remediation_loop": live_remediation,
        "stage180_live_remediation_execution": remediation_execution,
        "next_action_candidates": (
            []
            if remediation_attempted and stop_reason == "final_answer_ready"
            else _list_dicts(remediation_execution.get("remaining_action_candidates", []))
            if remediation_attempted and _list_dicts(remediation_execution.get("remaining_action_candidates", []))
            else _list_dicts(live_remediation.get("next_action_candidates", []))
            if live_remediation
            else []
        ),
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
