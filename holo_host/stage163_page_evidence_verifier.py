from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now

STAGE163_PAGE_EVIDENCE_SCHEMA = "holo.stage163.page_evidence.v1"
STAGE163_PAGE_EVIDENCE_SCORE_SCHEMA = "holo.stage163.page_evidence_score.v1"

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "api",
    "as",
    "docs",
    "documentation",
    "for",
    "guide",
    "in",
    "is",
    "latest",
    "official",
    "of",
    "on",
    "page",
    "search",
    "source",
    "the",
    "to",
    "with",
}


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _strip_tags(value: str, *, limit: int = 4000) -> str:
    without_code = _SCRIPT_STYLE_RE.sub(" ", str(value or ""))
    text = unescape(_TAG_RE.sub(" ", without_code))
    return _compact(text, limit)


def _query_terms(query: str, user_text: str = "") -> list[str]:
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", " ", f"{query} {user_text}".lower())
    terms: list[str] = []
    for item in raw.split():
        token = item.strip("._-:/")
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms[:16]


def _term_present(term: str, text: str) -> bool:
    if term in text:
        return True
    if term == "docs" and "documentation" in text:
        return True
    if term == "documentation" and "docs" in text:
        return True
    if term.endswith("s") and len(term) > 4 and term[:-1] in text:
        return True
    return False


def _best_snippet(text: str, terms: list[str], *, limit: int = 260) -> str:
    cleaned = _compact(text, 4000)
    lowered = cleaned.lower()
    if not cleaned:
        return ""
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return _compact(cleaned, limit)
    start = max(0, min(positions) - 80)
    end = min(len(cleaned), max(positions) + 180)
    return _compact(cleaned[start:end], limit)


def extract_page_evidence_text(html_text: str, *, url: str = "") -> dict[str, Any]:
    title_match = _TITLE_RE.search(str(html_text or ""))
    title = _strip_tags(title_match.group(1), limit=180) if title_match else ""
    text = _strip_tags(html_text, limit=6000)
    if title and text.lower().startswith(title.lower()):
        text = _compact(text[len(title) :], 6000)
    return {
        "schema": STAGE163_PAGE_EVIDENCE_SCHEMA,
        "url": str(url or ""),
        "title": title,
        "text": text,
        "extracted_at": utc_now(),
    }


def _page_text_from_response(page_response: dict[str, Any]) -> dict[str, Any]:
    response = dict(page_response or {})
    url = str(response.get("url", "") or "")
    if response.get("html"):
        extracted = extract_page_evidence_text(str(response.get("html", "") or ""), url=url)
        return {"url": url, "status": str(response.get("status", "ok") or "ok"), **extracted}
    results = [dict(item) for item in list(response.get("results", []) or []) if isinstance(item, dict)]
    title = ""
    parts: list[str] = []
    if results:
        title = str(results[0].get("title", "") or "")
        if not url:
            url = str(results[0].get("url", "") or "")
        for item in results:
            parts.append(str(item.get("title", "") or ""))
            parts.append(str(item.get("snippet", "") or ""))
    return {
        "schema": STAGE163_PAGE_EVIDENCE_SCHEMA,
        "url": url,
        "status": str(response.get("status", "") or ("ok" if parts else "empty")),
        "title": _compact(title, 180),
        "text": _compact(" ".join(parts), 6000),
        "error": _compact(response.get("error", ""), 180),
        "provider": str(response.get("provider", "host_open_page") or "host_open_page"),
        "extracted_at": utc_now(),
    }


def score_page_evidence(
    page_observation: dict[str, Any],
    *,
    query: str,
    user_text: str = "",
) -> dict[str, Any]:
    row = dict(page_observation or {})
    status = str(row.get("status", "") or "ok")
    url = str(row.get("url", "") or "")
    title = str(row.get("title", "") or "")
    text = str(row.get("text", "") or row.get("snippet", "") or "")
    blob = f"{url} {title} {text}".lower()
    terms = _query_terms(query, user_text)
    covered = [term for term in terms if _term_present(term, blob)]
    coverage = len(covered) / max(1, len(terms)) if terms else 0.0
    url_score = 0.12 if url.startswith("https://") else 0.04 if url else 0.0
    title_score = 0.16 if any(_term_present(term, title.lower()) for term in terms) else 0.0
    coverage_score = coverage * 0.62
    status_score = 0.10 if status == "ok" else -0.30 if status in {"error", "failed", "rejected_network_disabled"} else -0.10
    score = max(0.0, min(1.0, coverage_score + title_score + url_score + status_score))
    missing: list[str] = []
    if status != "ok":
        missing.append("successful_status")
    if coverage < 0.50:
        missing.append("query_term_coverage")
    if not text:
        missing.append("page_text")
    evidence_status = "supported" if status == "ok" and coverage >= 0.65 and score >= 0.68 else "weak" if status == "ok" and coverage >= 0.35 else "unsupported"
    if status in {"error", "failed"}:
        evidence_status = "error"
    if status == "rejected_network_disabled":
        evidence_status = "rejected_network_disabled"
    return {
        "schema": STAGE163_PAGE_EVIDENCE_SCORE_SCHEMA,
        "status": evidence_status,
        "evidence_score": round(score, 4),
        "term_coverage": round(coverage, 4),
        "covered_terms": covered,
        "missing_evidence": missing,
        "source_url": url,
        "title": _compact(title, 180),
        "supporting_snippet": _best_snippet(f"{title} {text}", covered or terms, limit=300),
    }


def verify_page_evidence_for_search(
    web_observation: dict[str, Any],
    *,
    open_page_fn: Callable[[str], dict[str, Any]],
    network_enabled: bool,
    query: str = "",
    user_text: str = "",
    max_pages: int = 2,
) -> dict[str, Any]:
    row = dict(web_observation or {})
    source_urls = [str(url).strip() for url in list(row.get("source_urls", []) or []) if str(url).strip()]
    if not source_urls:
        for result in list(row.get("results", []) or []):
            if isinstance(result, dict) and str(result.get("url", "") or "").strip():
                source_urls.append(str(result.get("url", "") or "").strip())
    query_text = str(query or row.get("query", "") or "")
    if not network_enabled:
        rejected = {
            "schema": STAGE163_PAGE_EVIDENCE_SCHEMA,
            "observation_id": "page:" + stable_digest("network_disabled", query_text, limit=12),
            "url": source_urls[0] if source_urls else "",
            "status": "rejected_network_disabled",
            "error": "network_disabled",
            "fetched_at": utc_now(),
        }
        return {
            "schema": STAGE163_PAGE_EVIDENCE_SCHEMA,
            "status": "rejected_network_disabled",
            "query": _compact(query_text, 180),
            "opened_count": 0,
            "selected_url": "",
            "best_evidence_score": 0.0,
            "page_observations": [rejected],
            "stop_reason": "network_disabled",
        }
    observations: list[dict[str, Any]] = []
    best_score: dict[str, Any] = {}
    selected_url = ""
    for url in source_urls[: max(1, int(max_pages or 1))]:
        try:
            response = dict(open_page_fn(url))
        except Exception as exc:  # noqa: BLE001
            response = {"url": url, "status": "error", "results": [], "error": str(exc), "provider": "host_open_page"}
        page = _page_text_from_response({**response, "url": str(response.get("url", "") or url)})
        score = score_page_evidence(page, query=query_text, user_text=user_text)
        page.update(
            {
                "observation_id": "page:" + stable_digest(url, page.get("status", ""), page.get("title", ""), limit=12),
                "page_evidence_score": score,
                "fetched_at": utc_now(),
            }
        )
        observations.append(page)
        if not best_score or float(score.get("evidence_score", 0.0) or 0.0) > float(best_score.get("evidence_score", 0.0) or 0.0):
            best_score = score
            selected_url = url
        if score["status"] == "supported":
            break
    status = str(best_score.get("status", "") or "unsupported")
    return {
        "schema": STAGE163_PAGE_EVIDENCE_SCHEMA,
        "status": status,
        "query": _compact(query_text, 180),
        "opened_count": len(observations),
        "selected_url": selected_url if status in {"supported", "weak"} else "",
        "best_evidence_score": float(best_score.get("evidence_score", 0.0) or 0.0),
        "term_coverage": float(best_score.get("term_coverage", 0.0) or 0.0),
        "supporting_snippet": str(best_score.get("supporting_snippet", "") or ""),
        "missing_evidence": list(best_score.get("missing_evidence", []) or []),
        "page_observations": observations,
        "stop_reason": "page_supported" if status == "supported" else "page_weak" if status == "weak" else "page_evidence_exhausted",
    }


def attach_page_evidence_to_web_observation(
    web_observation: dict[str, Any],
    *,
    open_page_fn: Callable[[str], dict[str, Any]],
    network_enabled: bool,
    query: str = "",
    user_text: str = "",
    max_pages: int = 2,
) -> dict[str, Any]:
    row = dict(web_observation or {})
    if str(row.get("status", "") or "") != "ok":
        return row
    if not list(row.get("source_urls", []) or []) and not list(row.get("results", []) or []):
        return row
    row["page_evidence"] = verify_page_evidence_for_search(
        row,
        open_page_fn=open_page_fn,
        network_enabled=network_enabled,
        query=query or str(row.get("query", "") or ""),
        user_text=user_text,
        max_pages=max_pages,
    )
    return row
