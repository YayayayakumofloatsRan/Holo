from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now

STAGE172_FILING_TEXT_RETRIEVAL_SCHEMA = "holo.stage172.filing_text_retrieval.v1"

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ITEM_RE = re.compile(r"\bItem\s+(1A|1|7|8)\.?", re.IGNORECASE)


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _normalize_filing_text(text: str) -> str:
    current = str(text or "")
    if "<" in current and ">" in current:
        current = _SCRIPT_STYLE_RE.sub(" ", current)
        current = re.sub(r"</(p|div|section|tr|h[1-6]|li|br)>", "\n", current, flags=re.IGNORECASE)
        current = unescape(_TAG_RE.sub(" ", current))
    current = current.replace("\xa0", " ")
    current = re.sub(r"\s+", " ", current).strip()
    current = re.sub(r"\s+(Item\s+(?:1A|1|7|8)\.?)", r"\n\1", current, flags=re.IGNORECASE)
    current = re.sub(r"\n\s+", "\n", current)
    return current[:120000]


def _looks_like_filing_text(text: str) -> bool:
    current = _normalize_filing_text(text)
    items = {match.group(1).upper() for match in _ITEM_RE.finditer(current)}
    return len(items & {"1", "1A", "7", "8"}) >= 3


def _source_urls(web_observation_ledger: Any) -> list[str]:
    urls: list[str] = []
    for row in _list_dicts(web_observation_ledger):
        page = row.get("page_evidence", {})
        if isinstance(page, dict):
            selected = str(page.get("selected_url", "") or "").strip()
            if selected and selected not in urls:
                urls.append(selected)
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text and text not in urls:
                urls.append(text)
        for result in _list_dicts(row.get("results", [])):
            text = str(result.get("url", "") or "").strip()
            if text and text not in urls:
                urls.append(text)
    return urls


def _filing_text_from_page_evidence(web_observation_ledger: Any) -> tuple[str, str]:
    for row in _list_dicts(web_observation_ledger):
        page = row.get("page_evidence", {})
        if not isinstance(page, dict):
            continue
        observations = _list_dicts(page.get("page_observations", []))
        for observation in observations:
            text = str(observation.get("text", "") or observation.get("html", "") or observation.get("snippet", "") or "")
            normalized = _normalize_filing_text(text)
            if _looks_like_filing_text(normalized):
                return normalized, str(observation.get("url", "") or page.get("selected_url", "") or "")
    return "", ""


def _open_page_text(
    url: str,
    *,
    open_page_fn: Callable[[str], dict[str, Any]] | None,
) -> tuple[str, dict[str, Any]]:
    if not callable(open_page_fn):
        return "", {"url": url, "status": "error", "error": "open_page_unavailable"}
    try:
        response = dict(open_page_fn(url))
    except Exception as exc:  # noqa: BLE001
        return "", {"url": url, "status": "error", "error": str(exc)}
    raw = str(response.get("html", "") or "")
    if not raw:
        parts: list[str] = []
        for item in _list_dicts(response.get("results", [])):
            parts.append(str(item.get("title", "") or ""))
            parts.append(str(item.get("snippet", "") or ""))
        raw = " ".join(parts)
    normalized = _normalize_filing_text(raw)
    return normalized, response


def _report(
    *,
    query: str,
    status: str,
    retrieval_source: str,
    filing_text: str = "",
    source_url: str = "",
    failure_reasons: list[str] | None = None,
    opened_count: int = 0,
    provider: str = "",
    error: str = "",
) -> dict[str, Any]:
    text = _normalize_filing_text(filing_text)
    return {
        "schema": STAGE172_FILING_TEXT_RETRIEVAL_SCHEMA,
        "retrieval_id": "stage172_filing_text:" + stable_digest(query, source_url, status, text[:200], limit=12),
        "query": _compact(query, 220),
        "status": status,
        "retrieval_source": retrieval_source,
        "source_url": str(source_url or ""),
        "filing_text": text if status == "ok" else "",
        "filing_text_char_count": len(text) if status == "ok" else 0,
        "opened_count": int(opened_count or 0),
        "provider": str(provider or ""),
        "error": _compact(error, 180),
        "failure_reasons": list(failure_reasons or []),
        "observed_at": utc_now(),
    }


def retrieve_filing_text(
    *,
    query: str,
    web_observation_ledger: Any,
    network_enabled: bool,
    filing_text: str | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provided = _normalize_filing_text(str(filing_text or ""))
    if provided:
        if _looks_like_filing_text(provided):
            return _report(query=query, status="ok", retrieval_source="provided", filing_text=provided)
        return _report(
            query=query,
            status="insufficient",
            retrieval_source="provided",
            failure_reasons=["provided_text_not_filing_like"],
        )

    page_text, page_url = _filing_text_from_page_evidence(web_observation_ledger)
    if page_text:
        return _report(
            query=query,
            status="ok",
            retrieval_source="page_evidence",
            filing_text=page_text,
            source_url=page_url,
        )

    urls = _source_urls(web_observation_ledger)
    if not urls:
        if not network_enabled:
            return _report(
                query=query,
                status="rejected_network_disabled",
                retrieval_source="open_page",
                failure_reasons=["network_disabled"],
            )
        return _report(
            query=query,
            status="missing_source",
            retrieval_source="none",
            failure_reasons=["source_url_missing"],
        )
    if not network_enabled:
        return _report(
            query=query,
            status="rejected_network_disabled",
            retrieval_source="open_page",
            source_url=urls[0],
            failure_reasons=["network_disabled"],
        )

    opened = 0
    last_error = ""
    last_provider = ""
    for url in urls[:3]:
        text, response = _open_page_text(url, open_page_fn=open_page_fn)
        opened += 1
        last_error = str(response.get("error", "") or "")
        last_provider = str(response.get("provider", "") or "")
        if str(response.get("status", "") or "ok") == "ok" and _looks_like_filing_text(text):
            return _report(
                query=query,
                status="ok",
                retrieval_source="open_page",
                filing_text=text,
                source_url=url,
                opened_count=opened,
                provider=last_provider,
            )
    return _report(
        query=query,
        status="insufficient",
        retrieval_source="open_page",
        source_url=urls[0],
        failure_reasons=["filing_text_not_found"],
        opened_count=opened,
        provider=last_provider,
        error=last_error,
    )
