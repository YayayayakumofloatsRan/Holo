from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .stage169_market_research_pack import build_market_research_pack
from .stage172_filing_text_retrieval import retrieve_filing_text

STAGE171_MARKET_RESEARCH_ACTION_SCHEMA = "holo.stage171.market_research_pack_action.v1"
STAGE171_MARKET_RESEARCH_LEDGER_SCHEMA = "holo.stage171.market_research_pack_ledger.v1"


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _source_urls(web_observation_ledger: Any) -> list[str]:
    urls: list[str] = []
    for row in _list_dicts(web_observation_ledger):
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text and text not in urls:
                urls.append(text)
        for result in _list_dicts(row.get("results", [])):
            text = str(result.get("url", "") or "").strip()
            if text and text not in urls:
                urls.append(text)
    return urls


def _coerce_web_observation_ledger(arguments: dict[str, Any], web_observation_ledger: Any) -> list[dict[str, Any]]:
    rows = _list_dicts(arguments.get("web_observation_ledger", []))
    rows.extend(_list_dicts(web_observation_ledger))
    if rows:
        return rows
    source_url = str(arguments.get("source_url", "") or "").strip()
    if not source_url:
        return []
    return [
        {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:stage171:" + stable_digest(source_url, limit=10),
            "action_type": "open_page",
            "status": "ok",
            "provider": "stage171_supplied_source",
            "query": str(arguments.get("query", "") or ""),
            "url": source_url,
            "results": [{"title": source_url, "url": source_url, "snippet": "source URL supplied to market_research_pack"}],
            "source_urls": [source_url],
            "fetched_at": utc_now(),
            "error": "",
            "confidence": 0.75,
        }
    ]


def _ledger_row(
    *,
    action_id: str,
    query: str,
    filing_type: str,
    status: str,
    pack: dict[str, Any] | None = None,
    failure_reasons: list[str] | None = None,
    source_urls: list[str] | None = None,
    filing_text_retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = dict(pack or {})
    retrieval = dict(filing_text_retrieval or {})
    return {
        "schema": STAGE171_MARKET_RESEARCH_LEDGER_SCHEMA,
        "action_id": action_id,
        "action_type": "market_research_pack",
        "query": _compact(query, 220),
        "filing_type": str(filing_type or "10-K").upper(),
        "status": status,
        "pack_id": str(pack.get("pack_id", "") or ""),
        "pack_status": str(pack.get("status", "") or ""),
        "failure_reasons": list(failure_reasons if failure_reasons is not None else pack.get("failure_reasons", []) or []),
        "evidence_item_count": int(pack.get("evidence_item_count", 0) or 0),
        "source_urls": list(source_urls or []),
        "filing_text_retrieval_id": str(retrieval.get("retrieval_id", "") or ""),
        "filing_text_retrieval_status": str(retrieval.get("status", "") or ""),
        "filing_text_retrieval_source": str(retrieval.get("retrieval_source", "") or ""),
        "filing_text_char_count": int(retrieval.get("filing_text_char_count", 0) or 0),
        "observed_at": utc_now(),
        **({"stage169_market_research_pack": pack} if pack else {}),
        **({"filing_text_retrieval": retrieval} if retrieval else {}),
    }


def execute_market_research_pack_action(
    arguments: dict[str, Any] | None,
    *,
    network_enabled: bool,
    web_observation_ledger: Any = None,
    filing_text: str | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute the read-only market-research pack host action.

    Stage171 does not call a provider and does not write memory. It converts
    already observed authoritative filing evidence plus filing text into a
    Stage169 pack, then records a compact execution ledger.
    """

    args = dict(arguments or {})
    query = str(args.get("query", "") or "").strip()
    filing_type = str(args.get("filing_type", "10-K") or "10-K").upper()
    text = str(filing_text if filing_text is not None else args.get("filing_text", "") or "")
    web_rows = _coerce_web_observation_ledger(args, web_observation_ledger)
    action_id = "stage171_market_research_pack:" + stable_digest(query, filing_type, text[:200], limit=12)
    source_urls = _source_urls(web_rows)

    retrieval = retrieve_filing_text(
        query=query,
        web_observation_ledger=web_rows,
        network_enabled=network_enabled,
        filing_text=text,
        open_page_fn=open_page_fn,
    )
    text = str(retrieval.get("filing_text", "") or "")
    if retrieval.get("source_url") and retrieval["source_url"] not in source_urls:
        source_urls.insert(0, retrieval["source_url"])

    if str(retrieval.get("status", "") or "") != "ok":
        rejected = str(retrieval.get("status", "") or "") == "rejected_network_disabled"
        reasons = [str(item) for item in list(retrieval.get("failure_reasons", []) or []) if str(item)]
        ledger = _ledger_row(
            action_id=action_id,
            query=query,
            filing_type=filing_type,
            status="rejected_network_disabled" if rejected else str(retrieval.get("status", "") or "missing_filing_text"),
            failure_reasons=reasons or ["filing_text_missing"],
            source_urls=source_urls,
            filing_text_retrieval=retrieval,
        )
        return {
            "schema": STAGE171_MARKET_RESEARCH_ACTION_SCHEMA,
            "status": "rejected" if rejected else "insufficient",
            "action_id": action_id,
            "filing_text_retrieval": retrieval,
            "market_research_pack_ledger": [ledger],
            "tool_observation_ledger": [market_research_pack_ledger_to_tool_observation(ledger)],
        }

    pack = build_market_research_pack(
        query=query,
        web_observation_ledger=web_rows,
        filing_text=text,
        filing_type=filing_type,
    )
    status = "ok" if str(pack.get("status", "") or "") == "ready" else "insufficient"
    ledger = _ledger_row(
        action_id=action_id,
        query=query,
        filing_type=filing_type,
        status=status,
        pack=pack,
        source_urls=source_urls,
        filing_text_retrieval=retrieval,
    )
    return {
        "schema": STAGE171_MARKET_RESEARCH_ACTION_SCHEMA,
        "status": status,
        "action_id": action_id,
        "filing_text_retrieval": retrieval,
        "stage169_market_research_pack": pack,
        "market_research_pack_ledger": [ledger],
        "tool_observation_ledger": [market_research_pack_ledger_to_tool_observation(ledger)],
    }


def market_research_pack_ledger_to_tool_observation(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status", "") or "")
    return {
        "provider_call_id": str(row.get("action_id", "") or ""),
        "tool": "market_research_pack",
        "status": "ok" if status == "ok" else status,
        "summary": _compact(
            f"market_research_pack {status}: pack={row.get('pack_status', '')}; "
            f"evidence={row.get('evidence_item_count', 0)}; failures={','.join(str(x) for x in list(row.get('failure_reasons', []) or []))}",
            420,
        ),
        "data_keys": ["query", "filing_type", "pack_status", "evidence_item_count"],
        "grounding_tags": ["market_research", "filing_pack"] if status == "ok" else [],
        "source_urls": list(row.get("source_urls", []) or []),
    }


def first_stage171_market_research_pack(value: Any) -> dict[str, Any]:
    for row in _list_dicts(value):
        pack = row.get("stage169_market_research_pack", {})
        if isinstance(pack, dict) and str(pack.get("schema", "") or "") == "holo.stage169.market_research_pack.v1":
            return dict(pack)
    return {}
