from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .market_research_action_planner import build_market_research_action_plan
from .market_research_feedback_loop import build_market_research_feedback_loop
from .market_research_plan_executor import execute_market_research_action_plan
from .stage168_source_authority import evaluate_source_authority

STAGE195_MARKET_RESEARCH_CONTINUATION_LOOP_SCHEMA = "holo.stage195.market_research_continuation_loop.v1"
STAGE195_MARKET_RESEARCH_CONTINUATION_ROUND_SCHEMA = "holo.stage195.market_research_continuation_round.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _extend_unique_rows(target: list[dict[str, Any]], rows: Any) -> None:
    seen = {
        str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", row.get("retrieval_id", "")))) or repr(row))
        for row in target
    }
    for row in _list_dicts(rows):
        key = str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", row.get("retrieval_id", "")))) or repr(row))
        if key in seen:
            continue
        seen.add(key)
        target.append(row)


def _first_pack(rows: Any) -> dict[str, Any]:
    for row in _list_dicts(rows):
        pack = row.get("stage169_market_research_pack", {})
        if isinstance(pack, dict) and str(pack.get("schema", "") or "") == "holo.stage169.market_research_pack.v1":
            return dict(pack)
    return {}


def _first_report(rows: Any) -> dict[str, Any]:
    for row in _list_dicts(rows):
        report = row.get("stage173_market_research_report", {})
        if isinstance(report, dict) and str(report.get("schema", "") or "") == "holo.stage173.market_research_report.v1":
            return dict(report)
    return {}


def _candidate(
    *,
    action_type: str,
    priority: float,
    reason: str,
    expected_observation: str,
    query: str = "",
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    digest = stable_digest(action_type, query, repr(arguments or {}), reason, limit=12)
    return {
        "schema": "holo.stage193.market_research_action_candidate.v1",
        "action_id": f"stage195_action:{digest}",
        "action_type": action_type,
        "priority": round(max(0.0, min(1.0, float(priority or 0.0))), 4),
        "query": _compact(query, 220),
        "url": "",
        "arguments": dict(arguments or {}),
        "required_source_family": "financial_filing",
        "reason": _compact(reason, 260),
        "expected_observation": _compact(expected_observation, 240),
        "can_execute_now": True,
        "blocked_reason": "",
    }


def _web_authority_sufficient(question: str, web_rows: list[dict[str, Any]]) -> bool:
    if not web_rows:
        return False
    report = evaluate_source_authority(
        question,
        web_rows,
        required_source_family="financial_filing",
        task_type="market_research",
    )
    return str(report.get("status", "") or "") == "sufficient"


def _pack_plan_from_web(question: str, remaining_action_budget: int) -> dict[str, Any]:
    candidate = _candidate(
        action_type="market_research_pack",
        priority=0.93,
        query=question,
        arguments={"query": question, "requires_filing_text": True},
        reason="A financial-filing web observation is available; build a structured market-research pack before further report synthesis.",
        expected_observation="market research pack with filing checklist, extracted metrics, and source-authority evidence.",
    )
    return {
        "schema": "holo.stage193.market_research_action_plan.v1",
        "status": "planned",
        "goal": _compact(question, 260),
        "next_action": "market_research_pack",
        "action_candidates": [candidate],
        "candidate_count": 1,
        "selected_action_id": candidate["action_id"],
        "can_finalize": False,
        "remaining_action_budget": max(0, int(remaining_action_budget or 0)),
        "stop_reason": "action_plan_ready",
        "reason": "Stage195 converted authoritative web evidence into a pack-building action.",
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }


def _selected_action(plan: dict[str, Any]) -> str:
    candidates = _list_dicts(plan.get("action_candidates", []))
    if candidates:
        candidates.sort(key=lambda item: float(item.get("priority", 0.0) or 0.0), reverse=True)
        return str(candidates[0].get("action_type", "") or "")
    return str(plan.get("next_action", "") or "")


def _merge_execution_state(
    execution: dict[str, Any],
    *,
    web_rows: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    pack_rows: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
    pack: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _extend_unique_rows(web_rows, execution.get("web_observation_ledger", []))
    _extend_unique_rows(tool_rows, execution.get("tool_observation_ledger", []))
    _extend_unique_rows(pack_rows, execution.get("market_research_pack_ledger", []))
    _extend_unique_rows(report_rows, execution.get("market_research_report_ledger", []))
    if isinstance(execution.get("stage169_market_research_pack", {}), dict) and execution.get("stage169_market_research_pack"):
        pack = dict(execution.get("stage169_market_research_pack", {}))
    elif not pack:
        pack = _first_pack(pack_rows)
    if isinstance(execution.get("stage173_market_research_report", {}), dict) and execution.get("stage173_market_research_report"):
        report = dict(execution.get("stage173_market_research_report", {}))
    elif not report:
        report = _first_report(report_rows)
    return pack, report


def _round(
    *,
    question: str,
    round_index: int,
    feedback: dict[str, Any],
    plan: dict[str, Any],
    execution: dict[str, Any],
    reused_initial_execution: bool = False,
) -> dict[str, Any]:
    selected_action = _selected_action(plan)
    status = str(execution.get("status", "") or "no_action")
    post_feedback = _dict(execution.get("post_action_stage192_feedback_loop", {}))
    unresolved = post_feedback.get("unresolved_items", feedback.get("unresolved_items", []))
    return {
        "schema": STAGE195_MARKET_RESEARCH_CONTINUATION_ROUND_SCHEMA,
        "round_id": "stage195_round:" + stable_digest(question, str(round_index), selected_action, status, limit=12),
        "round_index": int(round_index),
        "feedback": feedback,
        "action_plan": plan,
        "execution": execution,
        "selected_action": selected_action,
        "execution_status": status,
        "executed_count": int(execution.get("executed_count", 0) or 0),
        "rejected_count": int(execution.get("rejected_count", 0) or 0),
        "failed_count": int(execution.get("failed_count", 0) or 0),
        "post_action_feedback": post_feedback,
        "new_information_score": round(float(post_feedback.get("best_sufficiency_score", feedback.get("best_sufficiency_score", 0.0)) or 0.0), 4),
        "unresolved_items": [str(item) for item in list(unresolved or []) if str(item or "").strip()],
        "stop_candidate": bool(post_feedback.get("can_finalize", False)) or status in {"blocked", "failed"},
        "canonical_stop_reason": str(execution.get("canonical_stop_reason", "") or "final_answer_ready"),
        "reused_initial_execution": bool(reused_initial_execution),
        "created_at": utc_now(),
    }


def _loop_status(
    *,
    can_finalize: bool,
    executed: int,
    blocked: int,
    failed: int,
    exhausted: bool,
    stop_reason: str,
) -> str:
    if can_finalize:
        return "ready"
    if failed:
        return "failed"
    if blocked:
        return "blocked"
    if exhausted or stop_reason == "budget_exhausted":
        return "exhausted"
    if executed:
        return "continued"
    return "no_action"


def run_market_research_continuation_loop(
    *,
    question: str,
    initial_stage192_feedback_loop: dict[str, Any] | None = None,
    initial_stage193_action_plan: dict[str, Any] | None = None,
    initial_stage194_execution: dict[str, Any] | None = None,
    market_research_pack: dict[str, Any] | None = None,
    market_research_report: dict[str, Any] | None = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    web_observation_ledger: Any = None,
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """Run a bounded feedback -> plan -> execute -> feedback market-research loop.

    Stage195 does not call provider models, write memory, start WeChat, or widen
    transport authority. It only repeats the existing Stage192/193/194 host
    path until the report is ready, a tool/boundary stops progress, or the round
    budget is exhausted.
    """

    question_text = str(question or "").strip()
    rounds: list[dict[str, Any]] = []
    web_rows = _list_dicts(web_observation_ledger)
    tool_rows: list[dict[str, Any]] = []
    pack_rows = _list_dicts(market_research_pack_ledger)
    report_rows = _list_dicts(market_research_report_ledger)
    pack = _dict(market_research_pack) or _first_pack(pack_rows)
    report = _dict(market_research_report) or _first_report(report_rows)
    remaining = max(0, int(max_rounds or 0))
    feedback = _dict(initial_stage192_feedback_loop)
    plan = _dict(initial_stage193_action_plan)
    execution = _dict(initial_stage194_execution)
    stop_reason = "budget_exhausted" if remaining <= 0 else "final_answer_ready"

    if execution and remaining > 0:
        if not feedback:
            feedback = build_market_research_feedback_loop(
                question=question_text,
                market_research_pack=pack,
                market_research_report=report,
                market_research_pack_ledger=pack_rows,
                market_research_report_ledger=report_rows,
                remaining_action_budget=remaining,
            )
        if not plan:
            plan = build_market_research_action_plan(
                question=question_text,
                stage192_market_research_feedback_loop=feedback,
                market_research_pack=pack,
                market_research_report=report,
                market_research_pack_ledger=pack_rows,
                market_research_report_ledger=report_rows,
                remaining_action_budget=remaining,
                network_enabled=bool(network_enabled),
            )
        pack, report = _merge_execution_state(
            execution,
            web_rows=web_rows,
            tool_rows=tool_rows,
            pack_rows=pack_rows,
            report_rows=report_rows,
            pack=pack,
            report=report,
        )
        rounds.append(
            _round(
                question=question_text,
                round_index=1,
                feedback=feedback,
                plan=plan,
                execution=execution,
                reused_initial_execution=True,
            )
        )
        remaining -= 1
        feedback = _dict(execution.get("post_action_stage192_feedback_loop", {}))
        plan = {}
        execution = {}
        stop_reason = str(rounds[-1].get("canonical_stop_reason", "") or "final_answer_ready")
        if rounds[-1]["execution_status"] in {"blocked", "failed"}:
            remaining = 0

    while remaining > 0:
        if not feedback:
            feedback = build_market_research_feedback_loop(
                question=question_text,
                market_research_pack=pack,
                market_research_report=report,
                market_research_pack_ledger=pack_rows,
                market_research_report_ledger=report_rows,
                remaining_action_budget=remaining,
            )
        if bool(feedback.get("can_finalize", False)):
            stop_reason = "final_answer_ready"
            break

        if not plan:
            unresolved = [str(item) for item in list(feedback.get("unresolved_items", []) or []) if str(item)]
            if any(item.startswith("source_authority:") for item in unresolved) and _web_authority_sufficient(question_text, web_rows):
                plan = _pack_plan_from_web(question_text, remaining)
            else:
                plan = build_market_research_action_plan(
                    question=question_text,
                    stage192_market_research_feedback_loop=feedback,
                    market_research_pack=pack,
                    market_research_report=report,
                    market_research_pack_ledger=pack_rows,
                    market_research_report_ledger=report_rows,
                    remaining_action_budget=remaining,
                    network_enabled=bool(network_enabled),
                )
        if str(plan.get("status", "") or "") in {"no_action_needed", "exhausted"}:
            stop_reason = "final_answer_ready" if bool(plan.get("can_finalize", False)) else str(plan.get("stop_reason", "") or "evidence_exhausted")
            break

        execution = execute_market_research_action_plan(
            plan,
            question=question_text,
            market_research_pack=pack,
            market_research_report=report,
            market_research_pack_ledger=pack_rows,
            market_research_report_ledger=report_rows,
            web_observation_ledger=web_rows,
            network_enabled=bool(network_enabled),
            web_search_fn=web_search_fn,
            fallback_search_fns=fallback_search_fns,
            open_page_fn=open_page_fn,
            max_actions=1,
        )
        pack, report = _merge_execution_state(
            execution,
            web_rows=web_rows,
            tool_rows=tool_rows,
            pack_rows=pack_rows,
            report_rows=report_rows,
            pack=pack,
            report=report,
        )
        rounds.append(
            _round(
                question=question_text,
                round_index=len(rounds) + 1,
                feedback=feedback,
                plan=plan,
                execution=execution,
            )
        )
        remaining -= 1
        stop_reason = str(execution.get("canonical_stop_reason", "") or "final_answer_ready")
        if str(execution.get("status", "") or "") in {"blocked", "failed"}:
            break
        feedback = _dict(execution.get("post_action_stage192_feedback_loop", {}))
        plan = {}
        execution = {}

    final_feedback = feedback or build_market_research_feedback_loop(
        question=question_text,
        market_research_pack=pack,
        market_research_report=report,
        market_research_pack_ledger=pack_rows,
        market_research_report_ledger=report_rows,
        remaining_action_budget=remaining,
    )
    if not bool(final_feedback.get("can_finalize", False)) and rounds:
        last_post = _dict(rounds[-1].get("post_action_feedback", {}))
        if last_post:
            final_feedback = last_post
    can_finalize = bool(final_feedback.get("can_finalize", False))
    if can_finalize:
        stop_reason = "final_answer_ready"
    elif not rounds and remaining <= 0:
        stop_reason = "budget_exhausted"
    elif remaining <= 0 and stop_reason == "final_answer_ready":
        stop_reason = "budget_exhausted"

    executed_count = sum(1 for row in rounds if int(row.get("executed_count", 0) or 0) > 0)
    blocked_count = sum(1 for row in rounds if int(row.get("rejected_count", 0) or 0) > 0 or str(row.get("execution_status", "") or "") == "blocked")
    failed_count = sum(1 for row in rounds if int(row.get("failed_count", 0) or 0) > 0 or str(row.get("execution_status", "") or "") == "failed")
    status = _loop_status(
        can_finalize=can_finalize,
        executed=executed_count,
        blocked=blocked_count,
        failed=failed_count,
        exhausted=remaining <= 0 and not can_finalize,
        stop_reason=stop_reason,
    )

    return {
        "schema": STAGE195_MARKET_RESEARCH_CONTINUATION_LOOP_SCHEMA,
        "status": status,
        "question": _compact(question_text, 260),
        "round_count": len(rounds),
        "executed_round_count": executed_count,
        "blocked_round_count": blocked_count,
        "failed_round_count": failed_count,
        "remaining_round_budget": max(0, int(remaining)),
        "rounds": rounds,
        "final_stage192_feedback_loop": final_feedback,
        "final_stage193_action_plan": _dict(plan),
        "final_stage194_market_research_plan_execution": _dict(rounds[-1].get("execution", {})) if rounds else {},
        "web_observation_ledger": web_rows,
        "tool_observation_ledger": tool_rows,
        "market_research_pack_ledger": pack_rows,
        "market_research_report_ledger": report_rows,
        "stage169_market_research_pack": pack,
        "stage173_market_research_report": report,
        "can_finalize": can_finalize,
        "canonical_stop_reason": stop_reason,
        "public_loop_summary": _compact(
            f"market continuation: status={status}; rounds={len(rounds)}; executed={executed_count}; "
            f"can_finalize={can_finalize}; stop={stop_reason}",
            300,
        ),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "tool_execution": bool(rounds),
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
