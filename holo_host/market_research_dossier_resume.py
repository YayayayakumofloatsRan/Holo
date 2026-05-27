from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_plan_executor import execute_market_research_action_plan
from .market_research_source_promotion import promote_market_research_sources
from .market_research_task_dossier import build_market_research_task_dossier, default_market_research_dossier_fixtures

STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_SCHEMA = "holo.stage200.market_research_dossier_resume.v1"
STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_BUNDLE_SCHEMA = "holo.stage200.market_research_dossier_resume_bundle.v1"
STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA = "holo.stage193.market_research_action_plan.v1"
STAGE193_MARKET_RESEARCH_ACTION_CANDIDATE_SCHEMA = "holo.stage193.market_research_action_candidate.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _selected_next_action(dossier: dict[str, Any]) -> dict[str, Any]:
    actions = sorted(
        _list_dicts(dossier.get("next_actions", [])),
        key=lambda item: float(item.get("priority", 0.0) or 0.0),
        reverse=True,
    )
    return actions[0] if actions else {}


def _action_plan_from_dossier(
    *,
    dossier: dict[str, Any],
    action: dict[str, Any],
    question: str,
    remaining_action_budget: int,
    network_enabled: bool,
) -> dict[str, Any]:
    action_type = str(action.get("action_type", "") or "defer")
    query = _compact(action.get("query", question), 220)
    url = str(action.get("url", "") or "").strip()
    reason = _compact(action.get("reason", "Resume the next action recorded in the market research dossier."), 260)
    candidate = {
        "schema": STAGE193_MARKET_RESEARCH_ACTION_CANDIDATE_SCHEMA,
        "action_id": "stage200_action:" + stable_digest(str(dossier.get("dossier_id", "")), action_type, query, url, reason, limit=12),
        "action_type": action_type,
        "priority": round(max(0.0, min(1.0, float(action.get("priority", 0.5) or 0.5))), 4),
        "query": query,
        "url": url,
        "arguments": dict(action.get("arguments", {}) or {}),
        "required_source_family": str(action.get("required_source_family", "") or "financial_filing" if action_type == "web_search" else ""),
        "reason": reason,
        "expected_observation": _compact(action.get("expected_observation", "Dossier next-action evidence."), 240),
        "can_execute_now": True,
        "blocked_reason": "",
    }
    return {
        "schema": STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA,
        "status": "planned",
        "goal": _compact(question, 260),
        "next_action": action_type,
        "action_candidates": [candidate],
        "candidate_count": 1,
        "selected_action_id": candidate["action_id"],
        "can_finalize": False,
        "remaining_action_budget": max(0, int(remaining_action_budget or 0)),
        "stop_reason": "action_plan_ready" if network_enabled or action_type not in {"web_search", "open_page", "find_in_page"} else "boundary_or_permission",
        "reason": "Stage200 resumed a Stage199 market-research dossier next action.",
        "network_enabled": bool(network_enabled),
        "planning_only": True,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }


def _empty_execution(stop_reason: str = "final_answer_ready") -> dict[str, Any]:
    return {
        "schema": "holo.stage194.market_research_plan_execution.v1",
        "status": "no_action",
        "executed_action": "",
        "executed_count": 0,
        "rejected_count": 0,
        "failed_count": 0,
        "action_results": [],
        "canonical_stop_reason": stop_reason,
        "planning_only": False,
        "created_at": utc_now(),
    }


def _resume_status(execution: dict[str, Any], *, planned_only: bool, updated_dossier: dict[str, Any]) -> tuple[str, str]:
    if planned_only:
        return "planned", "low_marginal_utility"
    status = str(execution.get("status", "") or "")
    stop = str(execution.get("canonical_stop_reason", "") or "")
    if int(execution.get("rejected_count", 0) or 0) > 0 or status == "blocked":
        return "blocked", stop or "boundary_or_permission"
    if int(execution.get("failed_count", 0) or 0) > 0 or status == "failed":
        return "failed", stop or "tool_failure_report"
    if str(updated_dossier.get("status", "") or "") == "report_ready":
        return "completed", "final_answer_ready"
    if int(execution.get("executed_count", 0) or 0) > 0:
        return "resumed", stop or "final_answer_ready"
    return "no_next_action", stop or "evidence_exhausted"


def _merge_dossier_progress(original: dict[str, Any], rebuilt: dict[str, Any], *, web_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if str(rebuilt.get("status", "") or "") != "no_research_state":
        return rebuilt
    merged = dict(original)
    urls: list[str] = []
    for url in list(original.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    for row in web_rows:
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text and text not in urls:
                urls.append(text)
        for result in _list_dicts(row.get("results", [])):
            text = str(result.get("url", "") or "").strip()
            if text and text not in urls:
                urls.append(text)
    merged["source_urls"] = urls
    merged["source_count"] = len(urls)
    resume_state = _dict(merged.get("resume_state", {}))
    resume_state["can_resume"] = True
    resume_state["source_count"] = len(urls)
    merged["resume_state"] = resume_state
    ledgers = _dict(merged.get("ledgers", {}))
    ledgers["web_observation_count"] = len(web_rows)
    merged["ledgers"] = ledgers
    return merged


def _mock_sec_search(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage200_dry_run",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple Inc. Form 10-K annual report for fiscal 2024.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "status": "ok",
        "provider": "stage200_dry_run",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": url,
                "snippet": "Item 1. Business. Item 1A. Risk Factors. Item 7. MD&A. Item 8. Financial Statements.",
            }
        ],
    }


def resume_market_research_from_dossier(
    *,
    stage199_market_research_task_dossier: dict[str, Any] | None = None,
    question: str = "",
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    """Resume a Stage199 market dossier through the existing Stage193/194 host path.

    Stage200 does not call providers, write memory, start WeChat, or widen
    transport authority. It makes a stored dossier actionable by selecting one
    next action, executing it through ledgered host tools, and returning updated
    research state for the next turn.
    """

    dossier = _dict(stage199_market_research_task_dossier)
    if not dossier:
        report = {
            "schema": STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_SCHEMA,
            "status": "no_dossier",
            "question": _compact(question, 260),
            "selected_action": "",
            "selected_action_id": "",
            "selected_action_query": "",
            "stage193_market_research_action_plan": {},
            "stage194_market_research_plan_execution": _empty_execution("needs_user_clarification"),
            "updated_stage199_market_research_task_dossier": {},
            "canonical_stop_reason": "needs_user_clarification",
            "public_summary": "No market research dossier was available to resume.",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
        return sanitize_public_metadata(report)

    question_text = _compact(question or dossier.get("question", ""), 260)
    action = _selected_next_action(dossier)
    if str(dossier.get("status", "") or "") == "report_ready" and not action:
        report = {
            "schema": STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_SCHEMA,
            "status": "already_complete",
            "question": question_text,
            "dossier_status": str(dossier.get("status", "") or ""),
            "selected_action": "",
            "selected_action_id": "",
            "selected_action_query": "",
            "stage193_market_research_action_plan": {},
            "stage194_market_research_plan_execution": _empty_execution("final_answer_ready"),
            "web_observation_ledger": [],
            "market_research_pack_ledger": [],
            "market_research_report_ledger": [],
            "updated_stage199_market_research_task_dossier": dossier,
            "canonical_stop_reason": "final_answer_ready",
            "public_summary": "The market research dossier is already finalized; no resume action is required.",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
            "authority_boundary": {
                "provider_model_calls": False,
                "network_fetches": False,
                "tool_execution": False,
                "memory_writes": False,
                "wechat_start": False,
                "transport_authority_widened": False,
            },
        }
        return sanitize_public_metadata(report)

    if not action:
        report = {
            "schema": STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_SCHEMA,
            "status": "no_next_action",
            "question": question_text,
            "dossier_status": str(dossier.get("status", "") or ""),
            "selected_action": "",
            "selected_action_id": "",
            "selected_action_query": "",
            "stage193_market_research_action_plan": {},
            "stage194_market_research_plan_execution": _empty_execution("evidence_exhausted"),
            "updated_stage199_market_research_task_dossier": dossier,
            "canonical_stop_reason": "evidence_exhausted",
            "public_summary": "The dossier is resumable but does not contain a concrete next action.",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
        return sanitize_public_metadata(report)

    action_type = str(action.get("action_type", "") or "")
    action_query = _compact(action.get("query", question_text), 220)
    plan = _action_plan_from_dossier(
        dossier=dossier,
        action=action,
        question=question_text,
        remaining_action_budget=max_actions,
        network_enabled=bool(network_enabled),
    )
    planned_only = max(0, int(max_actions or 0)) <= 0
    execution = _empty_execution("low_marginal_utility") if planned_only else execute_market_research_action_plan(
        plan,
        question=question_text,
        web_observation_ledger=[],
        network_enabled=bool(network_enabled),
        web_search_fn=web_search_fn,
        fallback_search_fns=fallback_search_fns,
        open_page_fn=open_page_fn,
        max_actions=max_actions,
    )
    web_rows = _list_dicts(execution.get("web_observation_ledger", []))
    pack_rows = _list_dicts(execution.get("market_research_pack_ledger", []))
    report_rows = _list_dicts(execution.get("market_research_report_ledger", []))
    source_promotion = promote_market_research_sources(
        question=question_text,
        web_observation_ledger=web_rows,
        network_enabled=bool(network_enabled),
        max_crawl_queries=0,
    ) if web_rows else {}
    updated_dossier = build_market_research_task_dossier(
        question=question_text,
        stage196_market_research_source_promotion=source_promotion,
        stage173_market_research_report=_dict(execution.get("stage173_market_research_report", {})),
        market_research_pack_ledger=pack_rows,
        market_research_report_ledger=report_rows,
        web_observation_ledger=web_rows,
    )
    updated_dossier = _merge_dossier_progress(dossier, updated_dossier, web_rows=web_rows)
    status, stop_reason = _resume_status(execution, planned_only=planned_only, updated_dossier=updated_dossier)
    if status == "planned":
        summary = f"Planned dossier resume action: {action_type}."
    elif status == "blocked":
        summary = f"Resume action {action_type} was blocked: {stop_reason}."
    elif status == "failed":
        summary = f"Resume action {action_type} failed: {stop_reason}."
    else:
        summary = f"Resume action {action_type} executed; updated dossier status={updated_dossier.get('status', '')}."

    report = {
        "schema": STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_SCHEMA,
        "status": status,
        "question": question_text,
        "dossier_status": str(dossier.get("status", "") or ""),
        "selected_action": action_type,
        "selected_action_id": str(action.get("action_id", "") or plan.get("selected_action_id", "") or ""),
        "selected_action_query": action_query,
        "stage193_market_research_action_plan": plan,
        "stage194_market_research_plan_execution": execution,
        "web_observation_ledger": web_rows,
        "tool_observation_ledger": _list_dicts(execution.get("tool_observation_ledger", [])),
        "market_research_pack_ledger": pack_rows,
        "market_research_report_ledger": report_rows,
        "stage196_market_research_source_promotion": source_promotion,
        "updated_stage199_market_research_task_dossier": updated_dossier,
        "canonical_stop_reason": stop_reason,
        "public_summary": _compact(summary, 300),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches": bool(web_rows and network_enabled),
            "tool_execution": not planned_only and bool(execution.get("action_results", [])),
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    return sanitize_public_metadata(report)


def _default_resume_rows(*, dry_run: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fixture in default_market_research_dossier_fixtures():
        dossier = build_market_research_task_dossier(**fixture)
        rows.append(
            resume_market_research_from_dossier(
                stage199_market_research_task_dossier=dossier,
                network_enabled=True if dry_run else False,
                web_search_fn=_mock_sec_search if dry_run else None,
                open_page_fn=_mock_open_page if dry_run else None,
                max_actions=1,
            )
        )
    return rows


def _html_report(bundle: dict[str, Any]) -> str:
    cards = []
    for row in _list_dicts(bundle.get("resume_reports", [])):
        sources = "".join(f"<li>{html.escape(str(url))}</li>" for url in list(row.get("updated_stage199_market_research_task_dossier", {}).get("source_urls", []) or [])[:5])
        cards.append(
            "<section class=\"resume\">"
            f"<h2>{html.escape(str(row.get('question', '')))}</h2>"
            f"<p><b>Status:</b> {html.escape(str(row.get('status', '')))} | "
            f"<b>Action:</b> {html.escape(str(row.get('selected_action', '') or 'none'))} | "
            f"<b>Stop:</b> {html.escape(str(row.get('canonical_stop_reason', '')))}</p>"
            f"<p>{html.escape(str(row.get('public_summary', '')))}</p>"
            f"<h3>Updated Sources</h3><ul>{sources or '<li>none</li>'}</ul>"
            "</section>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage200 Market Research Dossier Resume</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}.resume{border:1px solid #ccd6d1;border-radius:6px;padding:14px;margin:14px 0}"
        "h1,h2{margin-bottom:8px}code{background:#eef3f0;padding:2px 4px;border-radius:4px}</style></head><body>"
        "<h1>Stage200 Market Research Dossier Resume</h1>"
        "<p>Resumes Stage199 market-research dossiers through the existing Stage193/194 host action path.</p>"
        f"{''.join(cards)}</body></html>"
    )


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> dict[str, str]:
    html_path = Path(output)
    if html_path.suffix.lower() != ".html":
        html_path = html_path.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    jsonl_path = html_path.with_suffix(".jsonl")
    html_path.write_text(_html_report(bundle), encoding="utf-8")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("resume_reports", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_dossier_resume_bundle(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    reports = list(fixtures if fixtures is not None else _default_resume_rows(dry_run=dry_run))
    progressed = sum(1 for row in reports if str(row.get("status", "") or "") in {"already_complete", "resumed", "completed"})
    blocked = sum(1 for row in reports if str(row.get("status", "") or "") == "blocked")
    summary = {
        "progress_rate": round(progressed / max(1, len(reports)), 4),
        "blocked_count": blocked,
        "executed_count": sum(int(_dict(row.get("stage194_market_research_plan_execution", {})).get("executed_count", 0) or 0) for row in reports),
        "web_observation_count": sum(len(_list_dicts(row.get("web_observation_ledger", []))) for row in reports),
    }
    bundle = {
        "schema": STAGE200_MARKET_RESEARCH_DOSSIER_RESUME_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed" if progressed else "failed",
        "resume_report_count": len(reports),
        "resume_reports": reports,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["progress_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return sanitize_public_metadata(bundle)
