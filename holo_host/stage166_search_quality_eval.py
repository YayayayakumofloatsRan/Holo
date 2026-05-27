from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

from .common import stable_digest, utc_now
from .stage151_tool_decision_loop import (
    build_grounded_web_observation_answer,
    build_time_observation,
    default_open_page,
    default_web_search,
    execute_tool_decision,
)
from .stage165_answer_citation_formatter import build_answer_citation_report, maybe_format_cited_web_answer

STAGE166_SEARCH_QUALITY_SCHEMA = "holo.stage166.search_quality_eval.v1"

QUERY_CATEGORY_IDS = (
    "official_docs",
    "api_docs",
    "current_news",
    "financial_filings",
    "ambiguous_entity",
    "failure_case",
)

METRIC_KEYS = (
    "pass_rate",
    "source_support_score",
    "citation_sufficiency_score",
    "freshness_score",
    "unsupported_claim_rate",
    "conflict_rate",
    "css_noise_rate",
    "expected_term_coverage",
    "latency_estimate",
)

_CURRENT_WEB_CLAIM_RE = re.compile(
    r"\b(search(?:ed)?|web|official|source|sources|current|latest|today|as of|verified|confirmed)\b|官网|官方|联网|搜索|最新",
    re.I,
)
_HONEST_NO_EVIDENCE_RE = re.compile(r"no supported page evidence|cannot treat this as current web evidence|没有可支持|没有可核验", re.I)
_CSS_NOISE_RE = re.compile(r"@layer|@\w+\s+theme|\.page-[\w-]+|\.astro-[\w-]+|\{[^{}]*display\s*:", re.I)
_URL_RE = re.compile(r"https?://[^\s)\]]+", re.I)
_NUMBERED_CITATION_RE = re.compile(r"\[\d+\]\s+https?://", re.I)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _source_syntheses(web_observation_ledger: Any) -> list[dict[str, Any]]:
    syntheses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _list_dicts(web_observation_ledger):
        synthesis = row.get("source_synthesis", {})
        if not isinstance(synthesis, dict):
            continue
        key = json.dumps(synthesis, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        syntheses.append(dict(synthesis))
    return syntheses


def _best_synthesis(web_observation_ledger: Any) -> dict[str, Any]:
    syntheses = _source_syntheses(web_observation_ledger)
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


def _citation_count(visible_answer: str, synthesis: dict[str, Any]) -> int:
    urls = set(_URL_RE.findall(str(visible_answer or "")))
    for item in list(synthesis.get("citations", []) or []):
        if isinstance(item, dict) and str(item.get("url", "") or "").strip():
            urls.add(str(item.get("url", "") or "").strip())
    return len(urls)


def _expected_term_coverage(visible_answer: str, expected_terms: list[str]) -> float:
    if not expected_terms:
        return 1.0
    lowered = str(visible_answer or "").lower()
    matched = sum(1 for term in expected_terms if str(term or "").lower() in lowered)
    return round(matched / max(1, len(expected_terms)), 4)


def _time_present(time_observation: Any, visible_answer: str) -> bool:
    time_row = _dict(time_observation)
    if time_row.get("observed_at") or time_row.get("local_time") or time_row.get("utc_time"):
        return True
    return bool(re.search(r"\b20\d{2}-\d{2}-\d{2}\b|today|as of", str(visible_answer or ""), re.I))


def _source_support_score(category_id: str, synthesis: dict[str, Any], visible_answer: str) -> float:
    if category_id == "failure_case" and _HONEST_NO_EVIDENCE_RE.search(visible_answer):
        return 1.0
    status = str(synthesis.get("status", "") or "")
    if status == "supported":
        return 1.0
    if status == "weak":
        return 0.55
    return 0.0


def _citation_sufficiency_score(category_id: str, citation_count: int, min_citations: int, visible_answer: str) -> float:
    if category_id == "failure_case" and _HONEST_NO_EVIDENCE_RE.search(visible_answer):
        return 1.0
    if citation_count <= 0:
        return 0.0
    return round(min(1.0, citation_count / max(1, int(min_citations or 1))), 4)


def evaluate_search_quality_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    category_id = str(fixture.get("category_id", "") or "unknown")
    visible_answer = str(fixture.get("visible_answer", "") or "")
    web_observation_ledger = _list_dicts(fixture.get("web_observation_ledger", []))
    time_observation = _dict(fixture.get("time_observation", {}))
    synthesis = _best_synthesis(web_observation_ledger)
    citation_count = _citation_count(visible_answer, synthesis)
    expected_terms = [str(item) for item in list(fixture.get("expected_terms", []) or []) if str(item).strip()]
    expected_term_coverage = _expected_term_coverage(visible_answer, expected_terms)
    source_support = _source_support_score(category_id, synthesis, visible_answer)
    citation_score = _citation_sufficiency_score(category_id, citation_count, int(fixture.get("min_citations", 1) or 1), visible_answer)
    requires_freshness = bool(fixture.get("requires_freshness", category_id == "current_news"))
    freshness_score = 1.0 if not requires_freshness or _time_present(time_observation, visible_answer) else 0.0
    conflict_rate = 1.0 if str(synthesis.get("status", "") or "") == "conflicted" or list(synthesis.get("risk_flags", []) or []) else 0.0
    css_noise_rate = 1.0 if _CSS_NOISE_RE.search(visible_answer) else 0.0
    honest_no_evidence = bool(_HONEST_NO_EVIDENCE_RE.search(visible_answer))
    claims_current_or_web = bool(_CURRENT_WEB_CLAIM_RE.search(visible_answer))
    unsupported_claim = 0.0
    if claims_current_or_web and not honest_no_evidence and source_support < 0.8:
        unsupported_claim = 1.0

    failure_reasons: list[str] = []
    if unsupported_claim:
        failure_reasons.append("current_or_web_claim_without_supported_sources")
    if conflict_rate:
        failure_reasons.append("source_conflict")
    if css_noise_rate:
        failure_reasons.append("css_or_page_chrome_leaked")
    if citation_score < 1.0:
        failure_reasons.append("insufficient_citations")
    if freshness_score < 1.0:
        failure_reasons.append("missing_freshness_observation")
    if expected_term_coverage < float(fixture.get("min_expected_term_coverage", 0.5) or 0.5):
        failure_reasons.append("expected_terms_missing")

    if category_id == "failure_case" and honest_no_evidence:
        failure_reasons = [reason for reason in failure_reasons if reason not in {"insufficient_citations", "expected_terms_missing"}]

    metrics = {
        "pass_rate": 0.0,
        "source_support_score": round(source_support, 4),
        "citation_sufficiency_score": round(citation_score, 4),
        "freshness_score": round(freshness_score, 4),
        "unsupported_claim_rate": round(unsupported_claim, 4),
        "conflict_rate": round(conflict_rate, 4),
        "css_noise_rate": round(css_noise_rate, 4),
        "expected_term_coverage": round(expected_term_coverage, 4),
        "latency_estimate": float(fixture.get("latency_estimate", 0.0) or 0.0),
    }
    passed = not failure_reasons and source_support >= 0.8 and citation_score >= 0.8 and freshness_score >= 1.0
    metrics["pass_rate"] = 1.0 if passed else 0.0
    return {
        "schema": "holo.stage166.search_quality_eval_result.v1",
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(category_id, visible_answer, limit=10)),
        "category_id": category_id,
        "query": str(fixture.get("query", "") or ""),
        "status": "passed" if passed else "failed",
        "citation_count": citation_count,
        "source_synthesis_status": str(synthesis.get("status", "") or ""),
        "failure_reasons": failure_reasons,
        "metrics": metrics,
        "visible_answer": visible_answer,
    }


def _supported_web_row(
    *,
    query: str,
    title: str,
    url: str,
    snippet: str,
    source_count: int = 2,
    confidence: float = 0.9,
) -> dict[str, Any]:
    citations = [
        {"url": url, "status": "supported", "snippet": snippet},
        {
            "url": f"https://example.org/{stable_digest(query, limit=8)}",
            "status": "supported",
            "snippet": f"Additional source supports: {snippet}",
        },
    ][:source_count]
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:" + stable_digest(query, url, limit=12),
        "action_type": "web_search",
        "query": query,
        "status": "ok",
        "provider": "stage166_fixture",
        "results": [{"title": title, "url": url, "snippet": snippet}],
        "source_urls": [item["url"] for item in citations],
        "page_evidence": {
            "schema": "holo.stage163.page_evidence.v1",
            "status": "supported",
            "selected_url": url,
            "best_evidence_score": confidence,
            "supporting_snippet": snippet,
            "opened_count": 1,
        },
        "source_synthesis": {
            "schema": "holo.stage164.source_synthesis.v1",
            "status": "supported",
            "query": query,
            "source_count": source_count,
            "supported_source_count": source_count,
            "weak_source_count": 0,
            "conflict_count": 0,
            "risk_flags": [],
            "confidence": confidence,
            "citations": citations,
            "synthesized_summary": snippet,
            "created_at": "2026-05-27T00:00:00Z",
        },
    }


def _fixture_from_row(
    *,
    fixture_id: str,
    category_id: str,
    query: str,
    row: dict[str, Any],
    expected_terms: list[str],
    requires_freshness: bool = False,
    min_citations: int = 1,
) -> dict[str, Any]:
    time_observation = {"local_time": "2026-05-27 14:30:00", "observed_at": "2026-05-27T06:30:00Z"}
    answer = build_grounded_web_observation_answer(
        user_text=query,
        web_observation_ledger=[row],
        time_observation=time_observation,
    )
    return {
        "fixture_id": fixture_id,
        "category_id": category_id,
        "query": query,
        "visible_answer": answer,
        "web_observation_ledger": [row],
        "time_observation": time_observation,
        "expected_terms": expected_terms,
        "requires_freshness": requires_freshness,
        "min_citations": min_citations,
        "latency_estimate": 180.0,
    }


def default_search_quality_fixtures() -> list[dict[str, Any]]:
    official = _supported_web_row(
        query="OpenAI Codex CLI official docs",
        title="CLI - Codex | OpenAI Developers",
        url="https://developers.openai.com/codex/cli",
        snippet="Codex CLI is OpenAI's coding agent that can read, change, and run code locally from the terminal.",
    )
    api = _supported_web_row(
        query="DeepSeek official tool calling API docs",
        title="DeepSeek Tool Calls Guide",
        url="https://api-docs.deepseek.com/guides/function_calling",
        snippet="DeepSeek's tool calling guide documents function tools and model-produced tool call messages.",
    )
    current = _supported_web_row(
        query="latest OpenAI Codex CLI documentation current",
        title="CLI - Codex | OpenAI Developers",
        url="https://developers.openai.com/codex/cli",
        snippet="The current Codex CLI documentation describes installing, running, and configuring the terminal coding agent.",
    )
    filing = _supported_web_row(
        query="Apple 2024 10-K SEC annual report",
        title="Apple Form 10-K",
        url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        snippet="Apple's Form 10-K is the annual report filing containing business, risk, financial statement, and MD&A disclosures.",
    )
    ambiguous = _supported_web_row(
        query="search apple official company information",
        title="Apple",
        url="https://www.apple.com/",
        snippet="Apple can refer to the company or the fruit; the company official site should be cited only when the company meaning is intended.",
    )
    failure_answer = maybe_format_cited_web_answer(
        user_text="find the latest official document for a deliberately nonexistent Holo stage 999999",
        web_observation_ledger=[
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:missing",
                "action_type": "web_search",
                "query": "deliberately nonexistent Holo stage 999999",
                "status": "ok",
                "provider": "stage166_fixture",
                "results": [],
                "source_urls": [],
                "source_synthesis": {
                    "schema": "holo.stage164.source_synthesis.v1",
                    "status": "unsupported",
                    "query": "deliberately nonexistent Holo stage 999999",
                    "source_count": 0,
                    "supported_source_count": 0,
                    "weak_source_count": 0,
                    "conflict_count": 0,
                    "risk_flags": [],
                    "confidence": 0.0,
                    "citations": [],
                    "synthesized_summary": "",
                    "created_at": "2026-05-27T00:00:00Z",
                },
            }
        ],
        time_observation={"local_time": "2026-05-27 14:30:00"},
        channel="holo_cli",
    )
    return [
        _fixture_from_row(
            fixture_id="official-docs-codex",
            category_id="official_docs",
            query="OpenAI Codex CLI official docs",
            row=official,
            expected_terms=["Codex CLI", "coding agent", "terminal"],
            min_citations=2,
        ),
        _fixture_from_row(
            fixture_id="api-docs-deepseek-tool-calls",
            category_id="api_docs",
            query="DeepSeek official tool calling API docs",
            row=api,
            expected_terms=["DeepSeek", "tool calling", "tool call"],
            min_citations=1,
        ),
        _fixture_from_row(
            fixture_id="current-docs-codex",
            category_id="current_news",
            query="latest OpenAI Codex CLI documentation current",
            row=current,
            expected_terms=["current", "Codex CLI", "terminal coding agent"],
            requires_freshness=True,
            min_citations=1,
        ),
        _fixture_from_row(
            fixture_id="financial-filing-apple-10k",
            category_id="financial_filings",
            query="Apple 2024 10-K SEC annual report",
            row=filing,
            expected_terms=["Apple", "Form 10-K", "annual report"],
            min_citations=1,
        ),
        _fixture_from_row(
            fixture_id="ambiguous-apple-company",
            category_id="ambiguous_entity",
            query="search apple official company information",
            row=ambiguous,
            expected_terms=["Apple", "company", "fruit"],
            min_citations=1,
        ),
        {
            "fixture_id": "honest-missing-source",
            "category_id": "failure_case",
            "query": "find the latest official document for a deliberately nonexistent Holo stage 999999",
            "visible_answer": failure_answer or "I attempted the web lookup, but there is no supported page evidence to cite.",
            "web_observation_ledger": [],
            "time_observation": {"local_time": "2026-05-27 14:30:00"},
            "expected_terms": [],
            "requires_freshness": False,
            "min_citations": 0,
            "latency_estimate": 80.0,
        },
    ]


def _mean(values: list[float]) -> float:
    return round(sum(values) / max(1, len(values)), 4)


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        key: _mean([float(row["metrics"].get(key, 0.0) or 0.0) for row in results])
        for key in METRIC_KEYS
    }


def _baseline_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_results: list[dict[str, Any]] = []
    for result in results:
        answer = re.sub(r"\[\d+\]\s+https?://[^\n]+", "", str(result.get("visible_answer", "") or ""))
        fixture = {
            "fixture_id": str(result.get("fixture_id", "")) + "-raw-baseline",
            "category_id": str(result.get("category_id", "")),
            "query": str(result.get("query", "")),
            "visible_answer": answer or "I found a web result and it appears official.",
            "web_observation_ledger": [],
            "time_observation": {},
            "expected_terms": [],
            "min_citations": 1,
        }
        baseline_results.append(evaluate_search_quality_fixture(fixture))
    return _summary(baseline_results)


def _html_report(report: dict[str, Any]) -> str:
    rows = []
    for item in list(report.get("query_results", []) or []):
        metrics = _dict(item.get("metrics", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('category_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('query', '')))}</td>"
            f"<td>{metrics.get('source_support_score', 0.0)}</td>"
            f"<td>{metrics.get('citation_sufficiency_score', 0.0)}</td>"
            f"<td>{metrics.get('unsupported_claim_rate', 0.0)}</td>"
            f"<td>{html.escape(','.join(str(x) for x in list(item.get('failure_reasons', []) or [])))}</td>"
            "</tr>"
        )
    summary = _dict(report.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage166 Search Quality Eval</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage166 Search Quality Eval</h1>"
        "<p>Deterministic search-quality evaluation over Holo's Stage151-165 evidence chain.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(report.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">citation sufficiency<br><b>{summary.get('citation_sufficiency_score', 0.0)}</b></div>"
        f"<div class=\"card\">unsupported claim rate<br><b>{summary.get('unsupported_claim_rate', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Category</th><th>Status</th><th>Query</th><th>Support</th><th>Citation</th><th>Unsupported</th><th>Failures</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list(report.get("query_results", []) or [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def _run_live_smoke_fixture() -> list[dict[str, Any]]:
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
    time_observation = build_time_observation()
    answer = build_grounded_web_observation_answer(user_text=query, web_observation_ledger=rows, time_observation=time_observation)
    return [
        {
            "fixture_id": "live-smoke-codex-docs",
            "category_id": "official_docs",
            "query": query,
            "visible_answer": answer,
            "web_observation_ledger": rows,
            "time_observation": time_observation,
            "expected_terms": ["Codex CLI", "coding agent"],
            "min_citations": 1,
            "latency_estimate": elapsed_ms,
        }
    ]


def run_search_quality_eval(
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
    fixture_rows = list(fixtures if fixtures is not None else _run_live_smoke_fixture() if current_mode == "live-smoke" else default_search_quality_fixtures())
    results = [evaluate_search_quality_fixture(row) for row in fixture_rows]
    summary = _summary(results)
    summary["pass_rate"] = round(sum(1 for row in results if row["status"] == "passed") / max(1, len(results)), 4)
    failed = [row["fixture_id"] for row in results if row["status"] != "passed"]
    report = {
        "schema": STAGE166_SEARCH_QUALITY_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "mode": current_mode,
        "status": "failed" if failed else "passed",
        "query_count": len(results),
        "query_results": results,
        "summary": summary,
        "baselines": {"raw_result_baseline": _baseline_from_results(results)},
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


def render_search_quality_eval(report: dict[str, Any]) -> str:
    summary = _dict(report.get("summary", {}))
    return (
        "Stage166 Search Quality Eval\n"
        f"status={report.get('status', 'unknown')} mode={report.get('mode', '')} query_count={report.get('query_count', 0)}\n"
        f"pass_rate={summary.get('pass_rate', 0.0)} citation_sufficiency={summary.get('citation_sufficiency_score', 0.0)} "
        f"unsupported_claim_rate={summary.get('unsupported_claim_rate', 0.0)}"
    )
