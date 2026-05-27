from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .common import compact_text

STAGE165_ANSWER_CITATION_SCHEMA = "holo.stage165.answer_citation_formatter.v1"
STAGE164_SOURCE_SYNTHESIS_SCHEMA = "holo.stage164.source_synthesis.v1"


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


_CSS_AT_RULE_RE = re.compile(r"@[a-zA-Z-]+\s+[^.;{}]{0,240}[;{}]", re.DOTALL)
_CSS_SELECTOR_RE = re.compile(r"(?:^|\s)[.#][A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?\s*\{[^{}]{0,260}\}", re.DOTALL)
_CSS_BLOCK_RE = re.compile(r"\{[^{}]{0,220}:[^{}]{0,220}\}", re.DOTALL)


def _clean_evidence_text(value: Any, *, limit: int = 240) -> str:
    text = _compact(value, max(limit * 3, 400))
    text = _CSS_AT_RULE_RE.sub(" ", text)
    text = _CSS_SELECTOR_RE.sub(" ", text)
    text = _CSS_BLOCK_RE.sub(" ", text)
    tokens = [
        token
        for token in text.split()
        if "{" not in token
        and "}" not in token
        and not token.startswith((".page-", ".astro-", "#astro-"))
        and not token.startswith(("--", "var("))
    ]
    cleaned = " ".join(tokens)
    return _compact(cleaned, limit)


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _source_syntheses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    syntheses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        synthesis = row.get("source_synthesis", {})
        if not isinstance(synthesis, dict):
            continue
        if str(synthesis.get("schema", "") or "") != STAGE164_SOURCE_SYNTHESIS_SCHEMA:
            continue
        key = repr(
            (
                synthesis.get("status"),
                synthesis.get("query"),
                synthesis.get("confidence"),
                synthesis.get("synthesized_summary"),
                tuple((item.get("url"), item.get("status")) for item in list(synthesis.get("citations", []) or []) if isinstance(item, dict)),
            )
        )
        if key in seen:
            continue
        seen.add(key)
        syntheses.append(dict(synthesis))
    return syntheses


def _select_synthesis(syntheses: list[dict[str, Any]]) -> dict[str, Any]:
    if not syntheses:
        return {}
    priority = {"conflicted": 4, "supported": 3, "weak": 2, "unsupported": 1}
    return max(
        syntheses,
        key=lambda item: (
            priority.get(str(item.get("status", "") or ""), 0),
            float(item.get("confidence", 0.0) or 0.0),
            int(item.get("supported_source_count", 0) or 0),
        ),
    )


def _title_by_url(rows: list[dict[str, Any]]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for row in rows:
        for result in list(row.get("results", []) or []):
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", "") or "").strip()
            title = _compact(result.get("title", "") or "", 100)
            if url and title and url not in titles:
                titles[url] = title
    return titles


def _snippet_by_url(rows: list[dict[str, Any]]) -> dict[str, str]:
    snippets: dict[str, str] = {}
    for row in rows:
        for result in list(row.get("results", []) or []):
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", "") or "").strip()
            snippet = _clean_evidence_text(result.get("snippet", ""), limit=280)
            if url and snippet and url not in snippets:
                snippets[url] = snippet
    return snippets


def _looks_low_information(text: str, title: str = "") -> bool:
    cleaned = _clean_evidence_text(text, limit=280).lower()
    if len(cleaned) < 80:
        return True
    tokens = [token.strip(".,:;()[]").lower() for token in cleaned.split() if len(token.strip(".,:;()[]")) > 2]
    unique_tokens = set(tokens)
    if len(unique_tokens) < 8:
        return True
    title_clean = _clean_evidence_text(title, limit=140).lower()
    if title_clean and cleaned.replace(title_clean, "").strip(" .,:;|-") == "":
        return True
    return False


def _fallback_title(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or url
    path = parsed.path.strip("/")
    if path:
        return _compact(f"{host}/{path}", 100)
    return _compact(host, 100)


def _citation_rows(synthesis: dict[str, Any], rows: list[dict[str, Any]], *, max_citations: int) -> list[dict[str, Any]]:
    titles = _title_by_url(rows)
    result_snippets = _snippet_by_url(rows)
    citations: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(list(synthesis.get("citations", []) or []), start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = titles.get(url) or _fallback_title(url)
        snippet = _clean_evidence_text(item.get("snippet", ""), limit=280)
        fallback_snippet = result_snippets.get(url, "")
        if fallback_snippet and _looks_low_information(snippet, title):
            snippet = fallback_snippet
        citations.append(
            {
                "index": len(citations) + 1,
                "title": title,
                "url": url,
                "status": str(item.get("status", "") or ""),
                "snippet": snippet,
            }
        )
        if len(citations) >= max(1, int(max_citations or 1)):
            break
    return citations


def _freshness_note(time_observation: dict[str, Any] | None) -> str:
    if not isinstance(time_observation, dict):
        return ""
    return _compact(time_observation.get("local_time", "") or time_observation.get("observed_at", ""), 80)


def build_answer_citation_report(
    web_observation_ledger: Any,
    *,
    user_text: str = "",
    time_observation: dict[str, Any] | None = None,
    max_citations: int = 4,
) -> dict[str, Any]:
    rows = _rows(web_observation_ledger)
    synthesis = _select_synthesis(_source_syntheses(rows))
    status = str(synthesis.get("status", "") or "unsupported") if synthesis else "unsupported"
    citations = _citation_rows(synthesis, rows, max_citations=max_citations) if synthesis else []
    if status == "supported" and not citations:
        status = "weak"
    if status in {"", "ok"}:
        status = "supported" if citations else "unsupported"
    summary = _clean_evidence_text(synthesis.get("synthesized_summary", ""), limit=620) if synthesis else ""
    if (not summary or _looks_low_information(summary)) and citations:
        summary = _clean_evidence_text(" ".join(str(item.get("snippet", "") or "") for item in citations), limit=620)
    confidence = float(synthesis.get("confidence", 0.0) or 0.0) if synthesis else 0.0
    report = {
        "schema": STAGE165_ANSWER_CITATION_SCHEMA,
        "status": status if status in {"supported", "weak", "unsupported", "conflicted"} else "unsupported",
        "query": _compact(synthesis.get("query", "") or user_text, 180) if synthesis else _compact(user_text, 180),
        "citation_count": len(citations),
        "citations": citations,
        "freshness_note": _freshness_note(time_observation),
        "risk_flags": list(synthesis.get("risk_flags", []) or []) if synthesis else [],
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "answer_summary": summary,
    }
    report["visible_answer"] = render_cited_web_answer(report)
    return report


def render_cited_web_answer(
    citation_report: dict[str, Any],
    *,
    channel: str = "",
) -> str:
    report = dict(citation_report or {})
    status = str(report.get("status", "") or "unsupported")
    query = _compact(report.get("query", ""), 140)
    summary = _compact(report.get("answer_summary", ""), 700)
    citations = [dict(item) for item in list(report.get("citations", []) or []) if isinstance(item, dict)]
    compact_channel = str(channel or "").startswith("wechat")

    if status == "conflicted":
        lines = ["I found source-page evidence, but it contains a conflict, so I cannot state it as settled."]
    elif status == "supported":
        lines = ["I completed the web search and verified source pages."]
    elif status == "weak":
        lines = ["I found weak source-page evidence, so the answer should be treated as tentative."]
    else:
        return "I attempted the web lookup, but there is no supported page evidence to cite."

    if query:
        lines.append(f"Query: {query}")
    freshness = _compact(report.get("freshness_note", ""), 80)
    if freshness:
        lines.append(f"Observed at: {freshness}")
    if summary:
        lines.append(f"Summary: {summary}")
    if citations:
        lines.append("Sources:")
        for item in citations[:2 if compact_channel else len(citations)]:
            url = str(item.get("url", "") or "")
            title = _compact(item.get("title", ""), 100)
            snippet = _compact(item.get("snippet", ""), 220)
            label = f"[{int(item.get('index', 0) or 0)}] {url}"
            if title:
                label += f" ({title})"
            lines.append(label)
            if snippet and not compact_channel:
                lines.append(f"    {snippet}")
    return "\n".join(lines)


def maybe_format_cited_web_answer(
    *,
    user_text: str = "",
    web_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
    channel: str = "",
) -> str:
    rows = _rows(web_observation_ledger)
    if not _source_syntheses(rows):
        return ""
    report = build_answer_citation_report(rows, user_text=user_text, time_observation=time_observation)
    return render_cited_web_answer(report, channel=channel)
