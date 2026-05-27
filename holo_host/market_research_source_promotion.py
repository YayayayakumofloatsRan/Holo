from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .live_crawler_search import run_live_crawler_search
from .stage168_source_authority import evaluate_source_authority

STAGE196_MARKET_RESEARCH_SOURCE_PROMOTION_SCHEMA = "holo.stage196.market_research_source_promotion.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _unique_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _list_dicts(rows):
        key = str(row.get("observation_id", "") or repr(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _rejected_network_row(question: str) -> dict[str, Any]:
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:stage196:" + stable_digest("network_disabled", question, limit=12),
        "action_type": "web_search",
        "query": _compact(question, 180),
        "status": "rejected_network_disabled",
        "provider": "network_gate",
        "results": [],
        "source_urls": [],
        "fetched_at": utc_now(),
        "error": "network_disabled",
        "confidence": 0.0,
    }


def _source_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in list(row.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    for result in _list_dicts(row.get("results", [])):
        text = str(result.get("url", "") or "").strip()
        if text and text not in urls:
            urls.append(text)
    page = _dict(row.get("page_evidence", {}))
    selected = str(page.get("selected_url", "") or "").strip()
    if selected and selected not in urls:
        urls.insert(0, selected)
    return urls


def _best_source(authority_report: dict[str, Any]) -> dict[str, Any]:
    best = _list_dicts(authority_report.get("best_sources", []))
    return best[0] if best else {}


def _row_for_url(rows: list[dict[str, Any]], url: str) -> dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        return {}
    for row in rows:
        if target in _source_urls(row):
            return dict(row)
    return {}


def _page_text_available(row: dict[str, Any]) -> bool:
    page = _dict(row.get("page_evidence", {}))
    for observation in _list_dicts(page.get("page_observations", [])):
        if str(observation.get("text", "") or observation.get("html", "") or observation.get("snippet", "") or "").strip():
            return True
    return False


def _status_from_authority(rows: list[dict[str, Any]], authority_report: dict[str, Any], *, network_enabled: bool) -> tuple[str, str]:
    authority_status = str(authority_report.get("status", "") or "")
    if authority_status == "sufficient":
        return "promoted", "final_answer_ready"
    if rows and all(str(row.get("status", "") or "") == "rejected_network_disabled" for row in rows):
        return "blocked", "boundary_or_permission"
    if rows:
        return "weak", "evidence_exhausted"
    if not network_enabled:
        return "blocked", "boundary_or_permission"
    return "missing", "evidence_exhausted"


def promote_market_research_sources(
    *,
    question: str,
    web_observation_ledger: Any = None,
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_crawl_queries: int = 0,
) -> dict[str, Any]:
    """Promote authoritative financial-filing web/page evidence into pack-ready source state."""

    question_text = str(question or "").strip()
    rows = _unique_rows(web_observation_ledger)
    crawler_report: dict[str, Any] = {}
    crawler_used = False

    initial_authority = evaluate_source_authority(
        question_text,
        rows,
        required_source_family="financial_filing",
        task_type="market_research",
    )
    if str(initial_authority.get("status", "") or "") != "sufficient" and int(max_crawl_queries or 0) > 0:
        if not network_enabled:
            if not rows:
                rows = [_rejected_network_row(question_text)]
            authority = evaluate_source_authority(
                question_text,
                rows,
                required_source_family="financial_filing",
                task_type="market_research",
            )
            status, stop = _status_from_authority(rows, authority, network_enabled=network_enabled)
            return _report(
                question=question_text,
                rows=rows,
                authority_report=authority,
                status=status,
                canonical_stop_reason=stop,
                crawler_report={},
                crawler_used=False,
            )
        crawler_report = run_live_crawler_search(
            user_text=f"search {question_text} SEC Form 10-K annual report financial filing",
            web_search_fn=web_search_fn,
            open_page_fn=open_page_fn,
            network_enabled=True,
            max_queries=max(1, int(max_crawl_queries or 1)),
            max_pages_per_query=2,
        )
        crawler_used = True
        rows = _unique_rows([*rows, *_list_dicts(crawler_report.get("web_observation_ledger", []))])

    if not rows and not network_enabled:
        rows = [_rejected_network_row(question_text)]

    authority = evaluate_source_authority(
        question_text,
        rows,
        required_source_family="financial_filing",
        task_type="market_research",
    )
    status, stop = _status_from_authority(rows, authority, network_enabled=network_enabled)
    if crawler_report and str(crawler_report.get("status", "") or "") == "failed" and status != "promoted":
        status = "failed"
        stop = "tool_failure_report"
    return _report(
        question=question_text,
        rows=rows,
        authority_report=authority,
        status=status,
        canonical_stop_reason=stop,
        crawler_report=crawler_report,
        crawler_used=crawler_used,
    )


def _report(
    *,
    question: str,
    rows: list[dict[str, Any]],
    authority_report: dict[str, Any],
    status: str,
    canonical_stop_reason: str,
    crawler_report: dict[str, Any],
    crawler_used: bool,
) -> dict[str, Any]:
    best = _best_source(authority_report)
    selected_url = str(best.get("url", "") or "")
    selected_row = _row_for_url(rows, selected_url)
    if not selected_row and rows:
        selected_row = rows[0]
        selected_url = _source_urls(selected_row)[0] if _source_urls(selected_row) else selected_url
    page = _dict(selected_row.get("page_evidence", {}))
    page_status = str(page.get("status", "") or "")
    if page.get("selected_url"):
        selected_url = str(page.get("selected_url", "") or selected_url)
    filing_text_available = _page_text_available(selected_row)
    can_build_pack = str(authority_report.get("status", "") or "") == "sufficient" and bool(selected_url)
    missing = [str(item) for item in list(authority_report.get("missing_authority", []) or []) if str(item)]
    return {
        "schema": STAGE196_MARKET_RESEARCH_SOURCE_PROMOTION_SCHEMA,
        "promotion_id": "stage196_source_promotion:" + stable_digest(question, selected_url, status, limit=12),
        "status": status,
        "question": _compact(question, 260),
        "authority_status": str(authority_report.get("status", "") or ""),
        "source_family": str(best.get("source_family", "") or ""),
        "authority_tier": str(best.get("authority_tier", "") or ""),
        "selected_url": selected_url,
        "page_evidence_status": page_status,
        "filing_text_available": filing_text_available,
        "can_build_market_research_pack": can_build_pack,
        "missing_authority": missing,
        "source_count": int(authority_report.get("source_count", 0) or 0),
        "primary_source_count": int(authority_report.get("primary_source_count", 0) or 0),
        "promoted_web_observation_ledger": rows,
        "source_authority_report": authority_report,
        "stage186_live_crawler_search": crawler_report,
        "crawler_used": bool(crawler_used),
        "canonical_stop_reason": canonical_stop_reason,
        "public_summary": _compact(
            f"source promotion status={status}; authority={authority_report.get('status', '')}; "
            f"source={selected_url or '-'}; page={page_status or '-'}; can_build_pack={can_build_pack}",
            300,
        ),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
