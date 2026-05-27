from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .common import stable_digest, utc_now
from .stage151_tool_decision_loop import build_time_observation, default_open_page, default_web_search, execute_tool_decision

STAGE167_LIVE_SEARCH_CANARY_SCHEMA = "holo.stage167.live_search_canary.v1"
STAGE167_PROVIDER_COMPARISON_SCHEMA = "holo.stage167.provider_comparison.v1"
STAGE167_SOURCE_FRESHNESS_SCHEMA = "holo.stage167.source_freshness.v1"
STAGE167_QUOTE_EXTRACTION_SCHEMA = "holo.stage167.quote_extraction.v1"

_CSS_NOISE_RE = re.compile(r"@layer|@\w+\s+theme|\.page-[\w-]+|\.astro-[\w-]+|\{[^{}]*display\s*:", re.I)
_URL_RE = re.compile(r"https?://[^\s)\]]+", re.I)
_NORMAL_DATE_RE = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
_COMPACT_DATE_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_CURRENT_RE = re.compile(r"\b(latest|current|today|as of|now|recent|newest)\b", re.I)
_OFFICIAL_HOST_FRAGMENTS = (
    "developers.openai.com",
    "openai.com",
    "api-docs.deepseek.com",
    "deepseek.com",
    "sec.gov",
    "apple.com",
)
_QUOTE_QUERY_STOP_TERMS = {
    "official",
    "docs",
    "documentation",
    "search",
    "latest",
    "current",
    "today",
    "api",
    "guide",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _clean_text(text: str) -> str:
    kept: list[str] = []
    for line in str(text or "").splitlines():
        if _CSS_NOISE_RE.search(line):
            continue
        stripped = re.sub(r"\s+", " ", line).strip()
        if stripped:
            kept.append(stripped)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def _terms(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", str(text or "")) if len(token) > 1]


def _quote_terms(text: str) -> list[str]:
    terms = [term for term in _terms(text) if term not in _QUOTE_QUERY_STOP_TERMS]
    return terms or _terms(text)


def _source_syntheses(web_observation_ledger: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _list_dicts(web_observation_ledger):
        synthesis = row.get("source_synthesis")
        if isinstance(synthesis, dict):
            rows.append(dict(synthesis))
    return rows


def _best_synthesis(web_observation_ledger: Any) -> dict[str, Any]:
    syntheses = _source_syntheses(web_observation_ledger)
    if not syntheses:
        return {}
    priority = {"supported": 4, "weak": 3, "conflicted": 2, "unsupported": 1}
    return max(
        syntheses,
        key=lambda row: (
            priority.get(str(row.get("status", "") or ""), 0),
            float(row.get("confidence", 0.0) or 0.0),
            int(row.get("supported_source_count", 0) or 0),
        ),
    )


def _citation_urls(synthesis: dict[str, Any], web_observation_ledger: Any = None) -> list[str]:
    urls: list[str] = []
    for citation in _list_dicts(synthesis.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url:
            urls.append(url)
    for row in _list_dicts(web_observation_ledger):
        for url in list(row.get("source_urls", []) or []):
            url_text = str(url or "").strip()
            if url_text:
                urls.append(url_text)
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _official_source_score(urls: list[str]) -> float:
    for url in urls:
        host = urlparse(url).netloc.lower()
        if any(fragment in host for fragment in _OFFICIAL_HOST_FRAGMENTS):
            return 1.0
    return 0.0


def _source_text_from_synthesis(synthesis: dict[str, Any]) -> str:
    chunks = [str(synthesis.get("synthesized_summary", "") or "")]
    for citation in _list_dicts(synthesis.get("citations", [])):
        chunks.append(str(citation.get("snippet", "") or ""))
        chunks.append(str(citation.get("url", "") or ""))
    return _clean_text(" ".join(chunks))


def _source_text_from_ledger(web_observation_ledger: Any) -> str:
    chunks: list[str] = []
    for row in _list_dicts(web_observation_ledger):
        for result in _list_dicts(row.get("results", [])):
            chunks.append(str(result.get("title", "") or ""))
            chunks.append(str(result.get("snippet", "") or ""))
            chunks.append(str(result.get("url", "") or ""))
        page_evidence = row.get("page_evidence", {})
        if isinstance(page_evidence, dict):
            chunks.append(str(page_evidence.get("supporting_snippet", "") or ""))
            chunks.append(str(page_evidence.get("selected_url", "") or ""))
            for page_row in _list_dicts(page_evidence.get("page_observations", [])):
                chunks.append(str(page_row.get("title", "") or ""))
                chunks.append(str(page_row.get("supporting_snippet", "") or ""))
                chunks.append(str(page_row.get("text", "") or ""))
    return _clean_text(" ".join(_clean_text(chunk) for chunk in chunks if str(chunk or "").strip()))


def extract_source_freshness(text: str, *, url: str = "", observed_at: str = "") -> dict[str, Any]:
    blob = f"{text or ''} {url or ''}"
    date_markers: list[str] = []
    year_markers: list[str] = []

    for year, month, day in _NORMAL_DATE_RE.findall(blob):
        marker = f"{year}-{int(month):02d}-{int(day):02d}"
        if marker not in date_markers:
            date_markers.append(marker)
    for year, month, day in _COMPACT_DATE_RE.findall(blob):
        day_int = int(day)
        if 1 <= day_int <= 31:
            marker = f"{year}-{month}-{day_int:02d}"
            if marker not in date_markers:
                date_markers.append(marker)
    for year in _YEAR_RE.findall(blob):
        if year not in year_markers:
            year_markers.append(year)

    source_family = "none"
    lowered = blob.lower()
    if date_markers or year_markers:
        source_family = "filing_date_or_period" if "sec.gov" in lowered or "10-k" in lowered or "annual report" in lowered else "dated_source"
    status = "observed" if date_markers or year_markers else "missing"
    return {
        "schema": STAGE167_SOURCE_FRESHNESS_SCHEMA,
        "status": status,
        "source_family": source_family,
        "date_markers": date_markers,
        "year_markers": year_markers,
        "requires_current_marker": bool(_CURRENT_RE.search(blob)),
        "freshness_score": 1.0 if status == "observed" else 0.0,
        "observed_at": observed_at,
    }


def extract_supporting_quote(text: str, *, query_terms: list[str] | None = None, max_chars: int = 240) -> dict[str, Any]:
    cleaned = _clean_text(text)
    if not cleaned:
        return {
            "schema": STAGE167_QUOTE_EXTRACTION_SCHEMA,
            "status": "missing",
            "quote": "",
            "query_terms": list(query_terms or []),
            "quote_quality_score": 0.0,
        }
    terms = [term.lower() for term in list(query_terms or []) if str(term).strip()]
    candidates = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if part.strip()]
    if not candidates:
        candidates = [cleaned]

    def score(candidate: str) -> tuple[int, int, int]:
        lowered = candidate.lower()
        matched = sum(1 for term in terms if term in lowered)
        not_url_only = 0 if lowered.startswith(("http://", "https://")) else 1
        return matched, not_url_only, -len(candidate)

    quote = max(candidates, key=score)
    if len(quote) > max_chars:
        quote = quote[: max(0, max_chars - 1)].rstrip() + "..."
    matched_count = score(quote)[0]
    quality = 1.0 if not terms or matched_count >= max(1, min(2, len(terms))) else round(matched_count / max(1, len(terms)), 4)
    return {
        "schema": STAGE167_QUOTE_EXTRACTION_SCHEMA,
        "status": "ok" if quote else "missing",
        "quote": quote,
        "query_terms": terms,
        "quote_quality_score": round(quality, 4),
        "source_text_chars": len(cleaned),
    }


def _score_provider(query: str, provider_observation: dict[str, Any], *, observed_at: str = "") -> dict[str, Any]:
    provider = str(provider_observation.get("provider", "") or "unknown")
    status = str(provider_observation.get("status", "") or "unknown")
    ledger = _list_dicts(provider_observation.get("web_observation_ledger", []))
    synthesis = _best_synthesis(ledger)
    source_status = str(synthesis.get("status", "") or "")
    confidence = float(synthesis.get("confidence", 0.0) or 0.0)
    urls = _citation_urls(synthesis, ledger)
    source_text = _clean_text(" ".join([_source_text_from_synthesis(synthesis), _source_text_from_ledger(ledger)]))
    quote = extract_supporting_quote(source_text, query_terms=_quote_terms(query), max_chars=240)
    freshness = extract_source_freshness(source_text, url=" ".join(urls), observed_at=observed_at)
    support_score = {"supported": 1.0, "weak": 0.55, "conflicted": 0.2, "unsupported": 0.0}.get(source_status, 0.0)
    citation_score = min(1.0, len(urls) / 2.0) if urls else 0.0
    official_score = _official_source_score(urls)
    score = 0.0
    failure_reasons: list[str] = []
    if status == "ok":
        score = (
            support_score * 0.45
            + confidence * 0.20
            + citation_score * 0.15
            + float(quote.get("quote_quality_score", 0.0) or 0.0) * 0.10
            + float(freshness.get("freshness_score", 0.0) or 0.0) * 0.05
            + official_score * 0.05
        )
        if source_status == "conflicted":
            score -= 0.25
            failure_reasons.append("source_conflict")
        if source_status not in {"supported", "weak"}:
            failure_reasons.append("source_not_supported")
    else:
        failure_reasons.append(str(provider_observation.get("error", "") or status or "provider_failed"))
    score = round(max(0.0, min(1.0, score)), 4)
    return {
        "provider": provider,
        "status": status,
        "source_synthesis_status": source_status,
        "score": score,
        "confidence": round(confidence, 4),
        "citation_count": len(urls),
        "official_source_score": official_score,
        "freshness": freshness,
        "supporting_quote": quote,
        "failure_reasons": failure_reasons,
        "source_urls": urls,
        "error": str(provider_observation.get("error", "") or ""),
    }


def compare_search_providers(
    query: str,
    provider_observations: list[dict[str, Any]],
    *,
    observed_at: str = "",
) -> dict[str, Any]:
    ranked = [_score_provider(query, row, observed_at=observed_at) for row in _list_dicts(provider_observations)]
    ranked.sort(key=lambda row: (float(row.get("score", 0.0) or 0.0), int(row.get("citation_count", 0) or 0)), reverse=True)
    best = ranked[0] if ranked else {}
    failed_count = sum(1 for row in ranked if str(row.get("status", "")) != "ok")
    best_score = float(best.get("score", 0.0) or 0.0)
    best_source_status = str(best.get("source_synthesis_status", "") or "")
    status = "supported" if best_score >= 0.65 and best_source_status == "supported" else "weak" if best_score >= 0.4 else "failed"
    return {
        "schema": STAGE167_PROVIDER_COMPARISON_SCHEMA,
        "query": str(query or ""),
        "provider_count": len(ranked),
        "failed_provider_count": failed_count,
        "best_provider": str(best.get("provider", "") or ""),
        "best_score": round(best_score, 4),
        "status": status,
        "ranked_providers": ranked,
        "observed_at": observed_at,
    }


def _expected_term_coverage(text: str, expected_terms: list[str]) -> float:
    if not expected_terms:
        return 1.0
    lowered = str(text or "").lower()
    matched = sum(1 for term in expected_terms if str(term or "").lower() in lowered)
    return round(matched / max(1, len(expected_terms)), 4)


def evaluate_live_search_canary_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    query = str(fixture.get("query", "") or "")
    category_id = str(fixture.get("category_id", "") or "unknown")
    observed_at = str(fixture.get("observed_at", "") or utc_now())
    provider_comparison = compare_search_providers(
        query,
        _list_dicts(fixture.get("provider_observations", [])),
        observed_at=observed_at,
    )
    best = _dict((provider_comparison.get("ranked_providers") or [{}])[0] if provider_comparison.get("ranked_providers") else {})
    supporting_quote = _dict(best.get("supporting_quote", {}))
    freshness = _dict(best.get("freshness", {}))
    visible_answer = str(fixture.get("visible_answer", "") or supporting_quote.get("quote", "") or "")
    evidence_text = " ".join([visible_answer, str(supporting_quote.get("quote", "") or ""), " ".join(best.get("source_urls", []) or [])])
    expected_terms = [str(item) for item in list(fixture.get("expected_terms", []) or []) if str(item).strip()]
    expected_coverage = _expected_term_coverage(evidence_text, expected_terms)
    requires_freshness = bool(fixture.get("requires_freshness", category_id in {"current_news", "financial_filings"}))
    requires_disambiguation = bool(fixture.get("requires_disambiguation", category_id == "ambiguous_entity"))
    disambiguation_score = 1.0
    if requires_disambiguation:
        lowered = evidence_text.lower()
        disambiguation_score = 1.0 if ("company" in lowered and ("fruit" in lowered or "ambiguous" in lowered or "meaning" in lowered)) else 0.0
    css_noise = 1.0 if _CSS_NOISE_RE.search(visible_answer) else 0.0

    failure_reasons: list[str] = []
    if provider_comparison["status"] != "supported":
        failure_reasons.append("no_supported_provider")
    if requires_freshness and float(freshness.get("freshness_score", 0.0) or 0.0) < 1.0:
        failure_reasons.append("missing_source_freshness")
    if float(supporting_quote.get("quote_quality_score", 0.0) or 0.0) < 0.75:
        failure_reasons.append("weak_or_missing_supporting_quote")
    if expected_coverage < float(fixture.get("min_expected_term_coverage", 0.5) or 0.5):
        failure_reasons.append("expected_terms_missing")
    if disambiguation_score < 1.0:
        failure_reasons.append("missing_entity_disambiguation")
    if css_noise:
        failure_reasons.append("css_or_page_chrome_leaked")

    metrics = {
        "pass_rate": 0.0,
        "provider_support_score": 1.0 if provider_comparison["status"] == "supported" else 0.0,
        "best_provider_score": round(float(provider_comparison.get("best_score", 0.0) or 0.0), 4),
        "freshness_score": 1.0 if not requires_freshness else round(float(freshness.get("freshness_score", 0.0) or 0.0), 4),
        "quote_quality_score": round(float(supporting_quote.get("quote_quality_score", 0.0) or 0.0), 4),
        "disambiguation_score": round(disambiguation_score, 4),
        "failed_provider_rate": round(float(provider_comparison.get("failed_provider_count", 0) or 0) / max(1, int(provider_comparison.get("provider_count", 0) or 0)), 4),
        "css_noise_rate": css_noise,
        "expected_term_coverage": expected_coverage,
        "latency_estimate": float(fixture.get("latency_estimate", 0.0) or 0.0),
    }
    passed = not failure_reasons
    metrics["pass_rate"] = 1.0 if passed else 0.0
    return {
        "schema": "holo.stage167.live_search_canary_result.v1",
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(category_id, query, limit=10)),
        "category_id": category_id,
        "query": query,
        "status": "passed" if passed else "failed",
        "failure_reasons": failure_reasons,
        "metrics": metrics,
        "provider_comparison": provider_comparison,
        "supporting_quote": supporting_quote,
        "source_freshness": freshness,
        "visible_answer": visible_answer,
    }


def _provider_observation(
    *,
    provider: str,
    query: str,
    url: str,
    snippet: str,
    status: str = "supported",
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "ok",
        "elapsed_ms": 100.0,
        "web_observation_ledger": [
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:" + stable_digest(provider, query, url, limit=12),
                "action_type": "web_search",
                "query": query,
                "status": "ok",
                "provider": provider,
                "results": [{"title": query, "url": url, "snippet": snippet}],
                "source_urls": [url],
                "source_synthesis": {
                    "schema": "holo.stage164.source_synthesis.v1",
                    "status": status,
                    "query": query,
                    "source_count": 1,
                    "supported_source_count": 1 if status == "supported" else 0,
                    "weak_source_count": 1 if status == "weak" else 0,
                    "conflict_count": 1 if status == "conflicted" else 0,
                    "risk_flags": ["source_conflict"] if status == "conflicted" else [],
                    "confidence": confidence,
                    "citations": [{"url": url, "status": status, "snippet": snippet}],
                    "synthesized_summary": snippet,
                    "created_at": "2026-05-27T00:00:00Z",
                },
            }
        ],
    }


def default_live_search_canary_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "official-docs-codex-canary",
            "category_id": "official_docs",
            "query": "OpenAI Codex CLI official docs",
            "expected_terms": ["Codex", "CLI", "terminal"],
            "provider_observations": [
                _provider_observation(
                    provider="official_provider",
                    query="OpenAI Codex CLI official docs",
                    url="https://developers.openai.com/codex/cli",
                    snippet="Codex CLI is a terminal coding agent from OpenAI that can inspect and edit code.",
                ),
                {"provider": "fallback_provider", "status": "error", "error": "timeout"},
            ],
        },
        {
            "fixture_id": "api-docs-deepseek-tool-calls-canary",
            "category_id": "api_docs",
            "query": "DeepSeek official tool calling API docs",
            "expected_terms": ["DeepSeek", "tool", "calling"],
            "provider_observations": [
                _provider_observation(
                    provider="official_provider",
                    query="DeepSeek official tool calling API docs",
                    url="https://api-docs.deepseek.com/guides/function_calling",
                    snippet="DeepSeek documents function calling with model-produced tool calls and tool results.",
                )
            ],
        },
        {
            "fixture_id": "financial-filing-apple-10k-canary",
            "category_id": "financial_filings",
            "query": "Apple 2024 10-K SEC annual report",
            "expected_terms": ["Apple", "Form 10-K", "annual report", "2024"],
            "requires_freshness": True,
            "provider_observations": [
                _provider_observation(
                    provider="sec_provider",
                    query="Apple 2024 10-K SEC annual report",
                    url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    snippet="Apple Form 10-K annual report for fiscal year 2024, filed for period ended 2024-09-28.",
                )
            ],
        },
        {
            "fixture_id": "ambiguous-apple-company-canary",
            "category_id": "ambiguous_entity",
            "query": "search apple official company information",
            "expected_terms": ["Apple", "company", "fruit"],
            "requires_disambiguation": True,
            "provider_observations": [
                _provider_observation(
                    provider="official_provider",
                    query="search apple official company information",
                    url="https://www.apple.com/",
                    snippet="Apple can mean the company or the fruit; this source is the official website for the technology company.",
                )
            ],
        },
    ]


def _mean(values: list[float]) -> float:
    return round(sum(values) / max(1, len(values)), 4)


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "pass_rate",
        "provider_support_score",
        "best_provider_score",
        "freshness_score",
        "quote_quality_score",
        "disambiguation_score",
        "failed_provider_rate",
        "css_noise_rate",
        "expected_term_coverage",
        "latency_estimate",
    )
    return {
        key: _mean([float(row.get("metrics", {}).get(key, 0.0) or 0.0) for row in results])
        for key in keys
    }


def _html_report(report: dict[str, Any]) -> str:
    rows: list[str] = []
    for result in list(report.get("canary_results", []) or []):
        metrics = _dict(result.get("metrics", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('category_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(result.get('query', '')))}</td>"
            f"<td>{html.escape(str(result.get('provider_comparison', {}).get('best_provider', '')))}</td>"
            f"<td>{metrics.get('best_provider_score', 0.0)}</td>"
            f"<td>{metrics.get('freshness_score', 0.0)}</td>"
            f"<td>{metrics.get('quote_quality_score', 0.0)}</td>"
            f"<td>{html.escape(','.join(str(item) for item in list(result.get('failure_reasons', []) or [])))}</td>"
            "</tr>"
        )
    summary = _dict(report.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage167 Live Search Canary</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#15201d}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage167 Live Search Canary</h1>"
        "<p>Provider comparison, source freshness, and clean quote extraction over Holo's search evidence chain.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(report.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">provider support<br><b>{summary.get('provider_support_score', 0.0)}</b></div>"
        f"<div class=\"card\">quote quality<br><b>{summary.get('quote_quality_score', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Category</th><th>Status</th><th>Query</th><th>Best Provider</th><th>Provider Score</th><th>Freshness</th><th>Quote</th><th>Failures</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def _write_artifacts(report: dict[str, Any], output: str | Path) -> dict[str, str]:
    html_path = Path(output)
    if html_path.suffix.lower() != ".html":
        html_path = html_path.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    jsonl_path = html_path.with_suffix(".jsonl")
    html_path.write_text(_html_report(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list(report.get("canary_results", []) or [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def _run_live_smoke_fixtures() -> list[dict[str, Any]]:
    query = "OpenAI Codex CLI official docs"
    started = time.perf_counter()
    rows = execute_tool_decision(
        {"user_text": query, "selected_actions": [{"action_type": "web_search", "query": query}]},
        network_enabled=True,
        web_search_fn=default_web_search,
        fallback_search_fns=[],
        open_page_fn=default_open_page,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return [
        {
            "fixture_id": "live-smoke-codex-docs-canary",
            "category_id": "official_docs",
            "query": query,
            "expected_terms": ["Codex", "CLI", "coding agent"],
            "provider_observations": [
                {
                    "provider": "default_web_search",
                    "status": "ok" if rows else "error",
                    "error": "" if rows else "empty_web_observation_ledger",
                    "elapsed_ms": elapsed_ms,
                    "web_observation_ledger": rows,
                }
            ],
            "observed_at": build_time_observation().get("observed_at", ""),
            "latency_estimate": elapsed_ms,
        }
    ]


def run_live_search_canary(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    mode: str = "dry-run",
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    current_mode = str(mode or ("dry-run" if dry_run else "dry-run")).strip() or "dry-run"
    if current_mode not in {"dry-run", "live-smoke"}:
        current_mode = "dry-run"
    fixture_rows = list(fixtures if fixtures is not None else _run_live_smoke_fixtures() if current_mode == "live-smoke" else default_live_search_canary_fixtures())
    results = [evaluate_live_search_canary_fixture(row) for row in fixture_rows]
    summary = _summary(results)
    failed = [row["fixture_id"] for row in results if row["status"] != "passed"]
    report = {
        "schema": STAGE167_LIVE_SEARCH_CANARY_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "mode": current_mode,
        "status": "failed" if failed else "passed",
        "canary_count": len(results),
        "canary_results": results,
        "summary": summary,
        "failed_fixture_ids": failed,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["pass_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    if output is not None:
        report["artifacts"] = _write_artifacts(report, output)
    return report


def render_live_search_canary(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary", {}))
    return (
        "Stage167 Live Search Canary\n"
        f"status={report.get('status', 'unknown')} mode={report.get('mode', '')} canary_count={report.get('canary_count', 0)}\n"
        f"pass_rate={summary.get('pass_rate', 0.0)} provider_support={summary.get('provider_support_score', 0.0)} "
        f"freshness={summary.get('freshness_score', 0.0)} quote_quality={summary.get('quote_quality_score', 0.0)}"
    )
