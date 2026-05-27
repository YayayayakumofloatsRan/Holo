from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .market_research_feedback_loop import build_market_research_feedback_loop
from .stage151_tool_decision_loop import execute_tool_decision, web_observations_to_tool_ledger
from .stage171_market_research_action import execute_market_research_pack_action
from .stage172_filing_text_retrieval import retrieve_filing_text
from .stage174_market_research_report_action import execute_market_research_report_action

STAGE194_MARKET_RESEARCH_PLAN_EXECUTION_SCHEMA = "holo.stage194.market_research_plan_execution.v1"
STAGE194_MARKET_RESEARCH_ACTION_RESULT_SCHEMA = "holo.stage194.market_research_action_result.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _extend_unique_rows(target: list[dict[str, Any]], rows: Any) -> None:
    seen = {str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", ""))) or repr(row)) for row in target}
    for row in _list_dicts(rows):
        key = str(row.get("observation_id", row.get("action_id", row.get("provider_call_id", ""))) or repr(row))
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


def _result(
    action: dict[str, Any],
    *,
    status: str,
    observation_count: int = 0,
    canonical_stop_reason: str = "",
    error: str = "",
    blocked_reason: str = "",
) -> dict[str, Any]:
    return {
        "schema": STAGE194_MARKET_RESEARCH_ACTION_RESULT_SCHEMA,
        "action_id": str(action.get("action_id", "") or ""),
        "action_type": str(action.get("action_type", "") or ""),
        "status": status,
        "observation_count": int(max(0, observation_count)),
        "canonical_stop_reason": canonical_stop_reason,
        "error": _compact(error, 260),
        "blocked_reason": _compact(blocked_reason, 180),
    }


def _selected_candidate(plan: dict[str, Any]) -> dict[str, Any]:
    candidates = sorted(
        _list_dicts(plan.get("action_candidates", [])),
        key=lambda item: float(item.get("priority", 0.0) or 0.0),
        reverse=True,
    )
    return candidates[0] if candidates else {}


def _execution_status(results: list[dict[str, Any]]) -> tuple[str, str, int, int, int]:
    executed = sum(1 for row in results if str(row.get("status", "") or "") == "executed")
    rejected = sum(1 for row in results if str(row.get("status", "") or "") in {"rejected", "blocked"})
    failed = sum(1 for row in results if str(row.get("status", "") or "") == "failed")
    stops = [str(row.get("canonical_stop_reason", "") or "") for row in results]
    if not results:
        return "no_action", "final_answer_ready", executed, rejected, failed
    if failed:
        return ("partial" if executed else "failed"), "tool_failure_report", executed, rejected, failed
    if "boundary_or_permission" in stops or rejected:
        return ("partial" if executed else "blocked"), "boundary_or_permission", executed, rejected, failed
    if executed:
        return "executed", "final_answer_ready", executed, rejected, failed
    return "blocked", "boundary_or_permission", executed, rejected, failed


def execute_market_research_action_plan(
    stage193_market_research_action_plan: dict[str, Any] | None,
    *,
    question: str,
    market_research_pack: dict[str, Any] | None = None,
    market_research_report: dict[str, Any] | None = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    web_observation_ledger: Any = None,
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    """Execute the first concrete action from a Stage193 market plan.

    This is still host-bounded: it does not call a provider, write memory, start
    WeChat, or execute arbitrary commands. It only routes Stage193 actions into
    already-ledgered host tools.
    """

    plan = _dict(stage193_market_research_action_plan)
    pack = _dict(market_research_pack) or _first_pack(market_research_pack_ledger)
    report = _dict(market_research_report) or _first_report(market_research_report_ledger)
    web_rows: list[dict[str, Any]] = _list_dicts(web_observation_ledger)
    pack_rows: list[dict[str, Any]] = _list_dicts(market_research_pack_ledger)
    report_rows: list[dict[str, Any]] = _list_dicts(market_research_report_ledger)
    tool_rows: list[dict[str, Any]] = []
    filing_retrieval: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    action = _selected_candidate(plan)

    if not plan or str(plan.get("status", "") or "") in {"no_action_needed", "exhausted"} or not action:
        stop = "final_answer_ready" if bool(plan.get("can_finalize", False)) else str(plan.get("stop_reason", "") or "evidence_exhausted")
        return {
            "schema": STAGE194_MARKET_RESEARCH_PLAN_EXECUTION_SCHEMA,
            "status": "no_action",
            "executed_action": str(plan.get("next_action", "") or ""),
            "executed_count": 0,
            "rejected_count": 0,
            "failed_count": 0,
            "action_results": [],
            "canonical_stop_reason": stop,
            "planning_only": False,
            "created_at": utc_now(),
        }

    if max(0, int(max_actions or 0)) <= 0:
        results.append(
            _result(
                action,
                status="blocked",
                canonical_stop_reason="budget_exhausted",
                blocked_reason="action_budget_exhausted",
            )
        )
    elif not bool(action.get("can_execute_now", True)):
        results.append(
            _result(
                action,
                status="blocked",
                canonical_stop_reason="boundary_or_permission",
                blocked_reason=str(action.get("blocked_reason", "") or "action_blocked"),
            )
        )
    else:
        action_type = str(action.get("action_type", "") or "")
        if action_type in {"web_search", "open_page", "find_in_page"}:
            selected = {
                "action_type": action_type,
                "query": str(action.get("query", "") or ""),
                "url": str(action.get("url", "") or ""),
                "pattern": str(action.get("pattern", "") or ""),
            }
            observations = execute_tool_decision(
                {"user_text": question, "selected_actions": [selected]},
                network_enabled=bool(network_enabled),
                web_search_fn=web_search_fn,
                fallback_search_fns=fallback_search_fns,
                open_page_fn=open_page_fn,
            )
            _extend_unique_rows(web_rows, observations)
            _extend_unique_rows(tool_rows, web_observations_to_tool_ledger(observations))
            if any(str(row.get("status", "") or "") == "ok" for row in observations):
                results.append(_result(action, status="executed", observation_count=len(observations), canonical_stop_reason="final_answer_ready"))
            elif any(str(row.get("status", "") or "") == "rejected_network_disabled" for row in observations):
                results.append(_result(action, status="rejected", observation_count=len(observations), canonical_stop_reason="boundary_or_permission", blocked_reason="network_disabled"))
            else:
                error = next((str(row.get("error", "") or "") for row in observations if str(row.get("error", "") or "")), "web_action_failed")
                results.append(_result(action, status="failed", observation_count=len(observations), canonical_stop_reason="tool_failure_report", error=error))
        elif action_type == "filing_text_retrieval":
            synthetic_web_rows = list(web_rows)
            url = str(action.get("url", "") or _dict(action.get("arguments", {})).get("source_url", "") or "").strip()
            if url and not synthetic_web_rows:
                synthetic_web_rows = [{"status": "ok", "source_urls": [url], "results": [{"title": url, "url": url, "snippet": "planned filing source URL"}]}]
            filing_retrieval = retrieve_filing_text(
                query=question,
                web_observation_ledger=synthetic_web_rows,
                network_enabled=bool(network_enabled),
                filing_text=str(_dict(action.get("arguments", {})).get("filing_text", "") or "") or None,
                open_page_fn=open_page_fn,
            )
            status = str(filing_retrieval.get("status", "") or "")
            if status == "ok":
                results.append(_result(action, status="executed", observation_count=1, canonical_stop_reason="final_answer_ready"))
            elif status == "rejected_network_disabled":
                results.append(_result(action, status="rejected", observation_count=1, canonical_stop_reason="boundary_or_permission", blocked_reason="network_disabled"))
            else:
                results.append(_result(action, status="failed", observation_count=1, canonical_stop_reason="tool_failure_report", error=status or "filing_text_retrieval_failed"))
        elif action_type == "market_research_pack":
            args = {**_dict(action.get("arguments", {})), "query": str(_dict(action.get("arguments", {})).get("query", question) or question)}
            pack_action = execute_market_research_pack_action(
                args,
                network_enabled=bool(network_enabled),
                web_observation_ledger=web_rows,
                open_page_fn=open_page_fn,
            )
            _extend_unique_rows(pack_rows, pack_action.get("market_research_pack_ledger", []))
            _extend_unique_rows(tool_rows, pack_action.get("tool_observation_ledger", []))
            filing_retrieval = _dict(pack_action.get("filing_text_retrieval", {}))
            pack = _dict(pack_action.get("stage169_market_research_pack", pack))
            status = str(pack_action.get("status", "") or "")
            if status == "ok":
                results.append(_result(action, status="executed", observation_count=len(pack_rows), canonical_stop_reason="final_answer_ready"))
            elif status == "rejected":
                results.append(_result(action, status="rejected", observation_count=len(pack_rows), canonical_stop_reason="boundary_or_permission", blocked_reason="network_disabled"))
            else:
                results.append(_result(action, status="failed", observation_count=len(pack_rows), canonical_stop_reason="tool_failure_report", error=status or "market_research_pack_failed"))
        elif action_type == "market_research_report":
            args = {**_dict(action.get("arguments", {})), "query": str(_dict(action.get("arguments", {})).get("question", question) or question)}
            if pack:
                args["market_research_pack"] = pack
            if pack_rows:
                args["market_research_pack_ledger"] = pack_rows
            report_action = execute_market_research_report_action(
                args,
                network_enabled=bool(network_enabled),
                open_page_fn=open_page_fn,
            )
            _extend_unique_rows(pack_rows, report_action.get("market_research_pack_ledger", []))
            _extend_unique_rows(report_rows, report_action.get("market_research_report_ledger", []))
            _extend_unique_rows(tool_rows, report_action.get("tool_observation_ledger", []))
            filing_retrieval = _dict(report_action.get("filing_text_retrieval", {}))
            pack = _dict(report_action.get("stage169_market_research_pack", pack))
            report = _dict(report_action.get("stage173_market_research_report", report))
            status = str(report_action.get("status", "") or "")
            if status == "ok":
                results.append(_result(action, status="executed", observation_count=len(report_rows), canonical_stop_reason="final_answer_ready"))
            elif status == "rejected":
                results.append(_result(action, status="rejected", observation_count=len(report_rows), canonical_stop_reason="boundary_or_permission", blocked_reason="network_disabled"))
            else:
                results.append(_result(action, status="failed", observation_count=len(report_rows), canonical_stop_reason="tool_failure_report", error=status or "market_research_report_failed"))
        elif action_type == "finalize_report":
            results.append(_result(action, status="executed", observation_count=0, canonical_stop_reason="final_answer_ready"))
        else:
            results.append(_result(action, status="rejected", canonical_stop_reason="boundary_or_permission", blocked_reason=f"unsupported_action:{action_type}"))

    status, stop, executed, rejected, failed = _execution_status(results)
    post_feedback = build_market_research_feedback_loop(
        question=question,
        market_research_pack=pack,
        market_research_report=report,
        market_research_pack_ledger=pack_rows,
        market_research_report_ledger=report_rows,
        remaining_action_budget=max(0, int(plan.get("remaining_action_budget", 1) or 1) - max(1, len(results))),
    )
    executed_action = str(action.get("action_type", "") or plan.get("next_action", "") or "")
    return {
        "schema": STAGE194_MARKET_RESEARCH_PLAN_EXECUTION_SCHEMA,
        "status": status,
        "executed_action": executed_action,
        "executed_count": executed,
        "rejected_count": rejected,
        "failed_count": failed,
        "action_results": results,
        "web_observation_ledger": web_rows,
        "tool_observation_ledger": tool_rows,
        "filing_text_retrieval": filing_retrieval,
        "market_research_pack_ledger": pack_rows,
        "market_research_report_ledger": report_rows,
        "stage169_market_research_pack": pack,
        "stage173_market_research_report": report,
        "post_action_stage192_feedback_loop": post_feedback,
        "canonical_stop_reason": stop,
        "planning_only": False,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": bool(network_enabled and web_rows and executed_action in {"web_search", "open_page", "find_in_page", "filing_text_retrieval"}),
            "tool_execution": bool(results),
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
