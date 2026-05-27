from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .stage171_market_research_action import execute_market_research_pack_action
from .stage173_market_research_report import build_market_research_report

STAGE174_MARKET_RESEARCH_REPORT_ACTION_SCHEMA = "holo.stage174.market_research_report_action.v1"
STAGE174_MARKET_RESEARCH_REPORT_LEDGER_SCHEMA = "holo.stage174.market_research_report_ledger.v1"


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _first_pack_from_ledger(value: Any) -> dict[str, Any]:
    for row in _list_dicts(value):
        pack = row.get("stage169_market_research_pack", {})
        if isinstance(pack, dict) and str(pack.get("schema", "") or "") == "holo.stage169.market_research_pack.v1":
            return dict(pack)
    return {}


def _source_urls_from_report(report: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for citation in _list_dicts(report.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _ledger_row(
    *,
    action_id: str,
    query: str,
    status: str,
    report: dict[str, Any] | None = None,
    pack: dict[str, Any] | None = None,
    failure_reasons: list[str] | None = None,
) -> dict[str, Any]:
    report = dict(report or {})
    pack = dict(pack or {})
    failures = list(failure_reasons or [])
    if report and not failures:
        failures = [str(item) for item in list(report.get("unsupported_claims", []) or []) if str(item)]
    return {
        "schema": STAGE174_MARKET_RESEARCH_REPORT_LEDGER_SCHEMA,
        "action_id": action_id,
        "action_type": "market_research_report",
        "query": _compact(query, 220),
        "status": status,
        "report_id": str(report.get("report_id", "") or ""),
        "report_status": str(report.get("status", "") or ""),
        "pack_id": str(pack.get("pack_id", "") or ""),
        "pack_status": str(pack.get("status", "") or ""),
        "section_count": int(report.get("section_count", 0) or 0),
        "metric_count": int(report.get("metric_count", 0) or 0),
        "citation_count": int(report.get("citation_count", 0) or 0),
        "unsupported_claim_count": int(report.get("unsupported_claim_count", 0) or 0),
        "failure_reasons": failures,
        "source_urls": _source_urls_from_report(report),
        "observed_at": utc_now(),
        **({"stage173_market_research_report": report} if report else {}),
        **({"stage169_market_research_pack": pack} if pack else {}),
    }


def market_research_report_ledger_to_tool_observation(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status", "") or "")
    return {
        "provider_call_id": str(row.get("action_id", "") or ""),
        "tool": "market_research_report",
        "status": "ok" if status == "ok" else status,
        "summary": _compact(
            f"market_research_report {status}: report={row.get('report_status', '')}; "
            f"sections={row.get('section_count', 0)}; metrics={row.get('metric_count', 0)}; citations={row.get('citation_count', 0)}; "
            f"failures={','.join(str(x) for x in list(row.get('failure_reasons', []) or []))}",
            480,
        ),
        "data_keys": ["query", "report_status", "section_count", "metric_count", "citation_count"],
        "grounding_tags": ["market_research", "filing_report"] if status == "ok" else [],
        "source_urls": list(row.get("source_urls", []) or []),
    }


def execute_market_research_report_action(
    arguments: dict[str, Any] | None,
    *,
    network_enabled: bool,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a read-only market-research report host action."""

    args = dict(arguments or {})
    query = str(args.get("query", "") or "").strip()
    action_id = "stage174_market_research_report:" + stable_digest(query, args.get("filing_text", ""), limit=12)
    pack = _dict(args.get("market_research_pack", args.get("stage169_market_research_pack", {})))
    if str(pack.get("schema", "") or "") != "holo.stage169.market_research_pack.v1":
        pack = _first_pack_from_ledger(args.get("market_research_pack_ledger", []))

    pack_action: dict[str, Any] = {}
    if not pack:
        pack_action = execute_market_research_pack_action(
            args,
            network_enabled=network_enabled,
            web_observation_ledger=args.get("web_observation_ledger", []),
            filing_text=str(args.get("filing_text", "") or "") if "filing_text" in args else None,
            open_page_fn=open_page_fn,
        )
        pack = _dict(pack_action.get("stage169_market_research_pack", {}))

    if not pack:
        market_rows = _list_dicts(pack_action.get("market_research_pack_ledger", []))
        primary = market_rows[0] if market_rows else {}
        status = str(primary.get("status", "") or "insufficient")
        failures = [str(item) for item in list(primary.get("failure_reasons", []) or ["market_research_pack_missing"]) if str(item)]
        ledger = _ledger_row(action_id=action_id, query=query, status=status, failure_reasons=failures)
        return {
            "schema": STAGE174_MARKET_RESEARCH_REPORT_ACTION_SCHEMA,
            "status": "rejected" if status == "rejected_network_disabled" else "insufficient",
            "action_id": action_id,
            "market_research_report_ledger": [ledger],
            "tool_observation_ledger": [market_research_report_ledger_to_tool_observation(ledger)],
            **({"market_research_pack_ledger": market_rows} if market_rows else {}),
        }

    report = build_market_research_report(market_research_pack=pack, question=query)
    status = "ok" if str(report.get("status", "") or "") == "evidence_ready" else "insufficient"
    ledger = _ledger_row(action_id=action_id, query=query, status=status, report=report, pack=pack)
    return {
        "schema": STAGE174_MARKET_RESEARCH_REPORT_ACTION_SCHEMA,
        "status": status,
        "action_id": action_id,
        "stage169_market_research_pack": pack,
        "stage173_market_research_report": report,
        "market_research_report_ledger": [ledger],
        "tool_observation_ledger": [market_research_report_ledger_to_tool_observation(ledger)],
        **({"market_research_pack_ledger": _list_dicts(pack_action.get("market_research_pack_ledger", []))} if pack_action else {}),
        **({"filing_text_retrieval": _dict(pack_action.get("filing_text_retrieval", {}))} if pack_action.get("filing_text_retrieval") else {}),
    }
