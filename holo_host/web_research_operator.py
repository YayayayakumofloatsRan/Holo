from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .live_crawler_search import run_live_crawler_search
from .stage212_action_journal import build_action_journal_from_payload, render_action_journal

STAGE218_WEB_RESEARCH_OPERATOR_SCHEMA = "holo.stage218.web_research_operator_run.v1"


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _status_from_crawler(crawler: dict[str, Any]) -> tuple[str, str]:
    crawler_status = str(crawler.get("status", "") or "")
    stop_reason = str(crawler.get("stop_reason", "") or "")
    if crawler_status == "sufficient":
        return "ready", "final_answer_ready"
    if crawler_status == "rejected_network_disabled":
        return "rejected", "boundary_or_permission"
    if stop_reason == "boundary_or_permission":
        return "rejected", "boundary_or_permission"
    if stop_reason == "tool_failure_report":
        return "failed", "tool_failure_report"
    return "weak" if crawler_status == "weak" else "failed", stop_reason or "evidence_exhausted"


def _trajectory_from_crawler(crawler: dict[str, Any], *, final_status: str, stop_reason: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "phase": "plan",
            "status": "planned",
            "summary": f"queries={len(list(crawler.get('query_plan', []) or []))}",
            "observation_count": len(list(crawler.get("query_plan", []) or [])),
            "source_count": 0,
            "canonical_stop_reason": "",
        }
    ]
    query_count = int(crawler.get("query_count", 0) or 0)
    opened_count = int(crawler.get("opened_page_count", 0) or 0)
    source_count = len(list(crawler.get("source_urls", []) or []))
    rows.append(
        {
            "phase": "crawl",
            "status": str(crawler.get("status", "") or ""),
            "summary": f"queries={query_count} opened={opened_count}",
            "observation_count": query_count + opened_count,
            "source_count": source_count,
            "canonical_stop_reason": stop_reason,
        }
    )
    rows.append(
        {
            "phase": "evaluate",
            "status": "sufficient" if final_status == "ready" else final_status,
            "summary": compact_text(str(crawler.get("final_summary", "") or ""), 220),
            "observation_count": len(_list_dicts(crawler.get("web_observation_ledger", [])))
            + len(_list_dicts(crawler.get("page_observation_ledger", []))),
            "source_count": source_count,
            "canonical_stop_reason": stop_reason,
        }
    )
    rows.append(
        {
            "phase": "finalize",
            "status": final_status,
            "summary": "ready web research report" if final_status == "ready" else "web research did not reach sufficient evidence",
            "observation_count": 1,
            "source_count": source_count,
            "canonical_stop_reason": stop_reason,
        }
    )
    return rows


def _final_visible_text(*, status: str, crawler: dict[str, Any], source_urls: list[str]) -> str:
    summary = compact_text(str(crawler.get("final_summary", "") or ""), 320)
    if status == "ready":
        source_text = "; ".join(source_urls[:4]) if source_urls else "no source URL recorded"
        return f"Web research brief: {summary} Sources: {source_text}"
    if status == "rejected" and "network_disabled" not in summary:
        return f"{summary} network_disabled"
    return summary or "web_research_operator_run was attempted but did not produce sufficient web evidence."


def run_web_research_operator(
    *,
    user_text: str,
    action_arguments: dict[str, Any] | None = None,
    network_enabled: bool = True,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a general web/literature research operator through the Stage186 crawler.

    This is a domain-neutral operator. It is intended for current web lookup,
    documentation/literature scouting, and source-grounded summaries. It does
    not add financial-market assumptions; market work remains the Stage214
    market operator.
    """

    args = dict(action_arguments or {})
    query = str(args.get("query", "") or user_text or "").strip()
    max_queries = max(1, min(5, int(args.get("max_queries", 3) or 3)))
    max_pages_per_query = max(1, min(4, int(args.get("max_pages_per_query", 2) or 2)))
    crawler = run_live_crawler_search(
        user_text=query,
        web_search_fn=web_search_fn,
        open_page_fn=open_page_fn,
        network_enabled=bool(network_enabled),
        max_queries=max_queries,
        max_pages_per_query=max_pages_per_query,
    )
    status, stop_reason = _status_from_crawler(crawler)
    source_urls = [str(url) for url in list(crawler.get("source_urls", []) or []) if str(url or "").strip()]
    journal_payload = {
        "stage186_live_crawler_search": crawler,
        "web_observation_ledger": _list_dicts(crawler.get("web_observation_ledger", [])),
    }
    action_journal = build_action_journal_from_payload(journal_payload, limit=1)
    rendered_journal = render_action_journal(action_journal)
    final_text = _final_visible_text(status=status, crawler=crawler, source_urls=source_urls)
    failure_reasons: list[str] = []
    if status != "ready":
        failure_reasons.append(str(crawler.get("stop_reason", "") or stop_reason))
        for row in _list_dicts(crawler.get("web_observation_ledger", []))[:3]:
            error = str(row.get("error", "") or "").strip()
            if error:
                failure_reasons.append(error)

    report = {
        "schema": STAGE218_WEB_RESEARCH_OPERATOR_SCHEMA,
        "operator_run_id": "stage218_web:" + stable_digest(query, status, ",".join(source_urls), limit=12),
        "status": status,
        "query": compact_text(query, 240),
        "operator_trajectory": _trajectory_from_crawler(crawler, final_status=status, stop_reason=stop_reason),
        "stage186_live_crawler_search": crawler,
        "stage212_action_journal": action_journal,
        "rendered_action_journal": rendered_journal,
        "web_observation_ledger": _list_dicts(crawler.get("web_observation_ledger", [])),
        "page_observation_ledger": _list_dicts(crawler.get("page_observation_ledger", [])),
        "source_urls": source_urls,
        "final_visible_text": final_text,
        "canonical_stop_reason": stop_reason,
        "failure_reasons": failure_reasons,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
    return sanitize_public_metadata(report)
