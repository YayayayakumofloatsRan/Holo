from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .stage169_market_research_pack import default_market_research_pack_fixtures
from .stage175_market_research_live_smoke import evaluate_market_research_live_smoke_fixture

STAGE176_MARKET_RESEARCH_DOMAIN_BENCHMARK_SCHEMA = "holo.stage176.market_research_domain_benchmark.v1"
STAGE176_MARKET_RESEARCH_DOMAIN_RESULT_SCHEMA = "holo.stage176.market_research_domain_result.v1"
STAGE176_MARKET_RESEARCH_DOMAIN_SCORECARD_SCHEMA = "holo.stage176.market_research_domain_scorecard.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 280) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {key: _public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_public(item) for item in clean]
    return clean


def _ready_source_fixture() -> dict[str, Any]:
    return next(row for row in default_market_research_pack_fixtures() if row.get("fixture_id") == "apple-10k-ready")


def _third_party_fixture() -> dict[str, Any]:
    return next(row for row in default_market_research_pack_fixtures() if row.get("fixture_id") == "third-party-source-insufficient")


def _with_fixture_id(base: dict[str, Any], **updates: Any) -> dict[str, Any]:
    row = dict(base)
    row.update(updates)
    return row


def default_market_research_domain_benchmark_fixtures() -> list[dict[str, Any]]:
    ready = _ready_source_fixture()
    third_party = _third_party_fixture()
    ready_text = str(ready.get("filing_text", "") or "")
    ready_web = _list_dicts(ready.get("web_observation_ledger", []))
    missing_mda_text = ready_text.replace("Item 7. Management's Discussion and Analysis", "Item 6. Management's Discussion and Analysis")
    conflict_text = ready_text.replace(
        "Net sales were $391.0 billion in 2024 compared to $383.3 billion in 2023.",
        "Net sales were $391.0 billion in 2024. Net sales were $999.0 billion in 2024. Net income was $93.7 billion in 2024.",
    )
    stale_text = ready_text.replace("2024", "2023").replace("$391.0", "$383.3").replace("$93.7", "$97.0")
    stale_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    stale_web = [
        {
            "status": "ok",
            "source_urls": [stale_url],
            "results": [
                {
                    "title": "Apple Form 10-K 2023",
                    "url": stale_url,
                    "snippet": "Apple Form 10-K annual report for fiscal year 2023.",
                }
            ],
        }
    ]
    return [
        _with_fixture_id(
            ready,
            fixture_id="apple-2024-primary-ready",
            category="primary_filing_ready",
            expected_period="2024",
            expected_domain_status="passed",
        ),
        _with_fixture_id(
            third_party,
            fixture_id="apple-third-party-pollution",
            category="third_party_source_pollution",
            expected_period="2024",
            expected_domain_status="failed",
        ),
        _with_fixture_id(
            ready,
            fixture_id="apple-missing-mda-section",
            category="missing_filing_section",
            filing_text=missing_mda_text,
            expected_period="2024",
            expected_domain_status="failed",
        ),
        _with_fixture_id(
            ready,
            fixture_id="apple-conflicting-net-sales",
            category="metric_conflict",
            filing_text=conflict_text,
            expected_period="2024",
            expected_domain_status="failed",
        ),
        {
            "fixture_id": "apple-2024-query-2023-filing",
            "category": "period_mismatch",
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": stale_text,
            "web_observation_ledger": stale_web,
            "expected_period": "2024",
            "expected_domain_status": "failed",
        },
        {
            "fixture_id": "apple-web-only-no-filing-text",
            "category": "web_only_no_filing_text",
            "query": str(ready.get("query", "") or "Apple AAPL 2024 10-K financial analysis"),
            "filing_text": "",
            "web_observation_ledger": ready_web,
            "expected_period": "2024",
            "expected_domain_status": "failed",
        },
    ]


def _citation_urls(report: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for citation in _list_dicts(report.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _metric_periods(report: dict[str, Any]) -> list[str]:
    periods: list[str] = []
    for metric in _list_dicts(report.get("metrics", [])):
        period = str(metric.get("period", "") or "").strip()
        if period and period not in periods:
            periods.append(period)
    return periods


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def _detect_risks(*, fixture: dict[str, Any], report: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if len(str(fixture.get("filing_text", "") or "").strip()) < 120:
        risks.append("filing_text_missing")
    if _dict(report.get("source_authority_summary", {})).get("status") != "sufficient":
        risks.append("source_authority_insufficient")
    missing_sections = list(_dict(report.get("filing_coverage_summary", {})).get("missing_sections", []) or [])
    if missing_sections:
        risks.append("filing_checklist_incomplete")
    if _dict(report.get("metric_consistency", {})).get("status") == "conflicted":
        risks.append("metric_conflict")
    expected_period = str(fixture.get("expected_period", "") or "").strip()
    periods = _metric_periods(report)
    if expected_period and periods and any(period != expected_period for period in periods):
        risks.append("period_mismatch")
    return sorted(set(risks))


def _naive_baseline(fixture: dict[str, Any], *, risks: list[str]) -> dict[str, Any]:
    web_rows = _list_dicts(fixture.get("web_observation_ledger", []))
    would_answer = bool(web_rows and any(str(row.get("status", "") or "ok") == "ok" for row in web_rows))
    return {
        "schema": "holo.stage176.naive_web_baseline.v1",
        "status": "would_answer" if would_answer else "would_not_answer",
        "overclaims": bool(would_answer and risks),
        "risk_flags_ignored": list(risks) if would_answer else [],
    }


def build_market_research_domain_scorecard(
    *,
    fixture: dict[str, Any],
    live_smoke: dict[str, Any],
    risks: list[str],
) -> dict[str, Any]:
    report = _dict(live_smoke.get("stage173_market_research_report", {}))
    urls = _citation_urls(report)
    expected_period = str(fixture.get("expected_period", "") or "").strip()
    periods = _metric_periods(report)
    is_primary = any("sec.gov" in url.lower() for url in urls)
    coverage = _dict(report.get("filing_coverage_summary", {}))
    checks = {
        "primary_source_required": _check(is_primary, score=1.0 if is_primary else 0.0, reason="source_authority_insufficient"),
        "filing_text_present": _check("filing_text_missing" not in risks, score=1.0 if "filing_text_missing" not in risks else 0.0, reason="filing_text_missing"),
        "filing_coverage_complete": _check(not list(coverage.get("missing_sections", []) or []), score=float(coverage.get("coverage_score", 0.0) or 0.0), reason="filing_checklist_incomplete"),
        "metric_consistency": _check("metric_conflict" not in risks, score=1.0 if "metric_conflict" not in risks else 0.0, reason="metric_conflict"),
        "period_alignment": _check(
            not expected_period or not periods or all(period == expected_period for period in periods),
            score=1.0 if (not expected_period or not periods or all(period == expected_period for period in periods)) else 0.0,
            reason="period_mismatch",
        ),
        "unsupported_claim_rate_low": _check(int(report.get("unsupported_claim_count", 0) or 0) == 0, score=1.0 if int(report.get("unsupported_claim_count", 0) or 0) == 0 else 0.0),
        "agent_trace_valid": _check(str(live_smoke.get("status", "") or "") == "passed", score=1.0 if live_smoke.get("status") == "passed" else 0.0),
    }
    overall = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    critical = [
        "primary_source_required",
        "filing_text_present",
        "filing_coverage_complete",
        "metric_consistency",
        "period_alignment",
    ]
    status = "passed" if overall >= 0.82 and all(bool(checks[key]["passed"]) for key in critical) else "failed"
    return {
        "schema": STAGE176_MARKET_RESEARCH_DOMAIN_SCORECARD_SCHEMA,
        "status": status,
        "overall_score": overall,
        "critical_gates": critical,
        "checks": checks,
    }


def evaluate_market_research_domain_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    source = dict(fixture or {})
    live_fixture = {
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(source, limit=10)),
        "query": str(source.get("query", "") or ""),
        "filing_text": str(source.get("filing_text", "") or ""),
        "web_observation_ledger": _list_dicts(source.get("web_observation_ledger", [])),
        "expected_report_status": "evidence_ready" if str(source.get("category", "") or "") == "primary_filing_ready" else "",
    }
    live_smoke = evaluate_market_research_live_smoke_fixture(live_fixture)
    report = _dict(live_smoke.get("stage173_market_research_report", {}))
    risks = _detect_risks(fixture=source, report=report)
    scorecard = build_market_research_domain_scorecard(fixture=source, live_smoke=live_smoke, risks=risks)
    naive = _naive_baseline(source, risks=risks)
    expected_status = str(source.get("expected_domain_status", "") or "")
    failures: list[str] = []
    if scorecard["status"] != "passed":
        failures.extend(risks or ["domain_scorecard_failed"])
    if expected_status and scorecard["status"] != expected_status:
        failures.append("domain_expectation_mismatch")
    result = {
        "schema": STAGE176_MARKET_RESEARCH_DOMAIN_RESULT_SCHEMA,
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(source, limit=10)),
        "category": str(source.get("category", "") or ""),
        "query": _compact(source.get("query", ""), 260),
        "expected_period": str(source.get("expected_period", "") or ""),
        "status": scorecard["status"],
        "detected_risk_flags": risks,
        "domain_scorecard": scorecard,
        "naive_web_baseline": naive,
        "stage175_live_smoke": live_smoke,
        "stage173_market_research_report": report,
        "failure_reasons": sorted(set(failures)),
    }
    return _dict(_public(result))


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row.get("status") == "passed")
    primary = [row for row in results if row.get("category") == "primary_filing_ready"]
    adversarial = [row for row in results if row.get("category") != "primary_filing_ready"]
    detected_adversarial = [row for row in adversarial if row.get("status") == "failed" and list(row.get("detected_risk_flags", []) or [])]
    naive_overclaims = [row for row in results if _dict(row.get("naive_web_baseline", {})).get("overclaims")]
    scores = [float(_dict(row.get("domain_scorecard", {})).get("overall_score", 0.0) or 0.0) for row in results]
    return {
        "passed_count": passed,
        "failed_count": total - passed,
        "pass_rate": round(passed / max(1, total), 4),
        "primary_ready_pass_rate": round(
            sum(1 for row in primary if row.get("status") == "passed") / max(1, len(primary)),
            4,
        ),
        "adversarial_detection_rate": round(len(detected_adversarial) / max(1, len(adversarial)), 4),
        "naive_baseline_overclaim_rate": round(len(naive_overclaims) / max(1, total), 4),
        "average_domain_score": round(sum(scores) / max(1, len(scores)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    for result in _list_dicts(bundle.get("results", [])):
        scorecard = _dict(result.get("domain_scorecard", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('category', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(scorecard.get('overall_score', 0.0)))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(result.get('detected_risk_flags', []) or [])))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage176 Market Research Domain Benchmark</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage176 Market Research Domain Benchmark</h1>"
        "<p>Adversarial market-research benchmark over source authority, filing coverage, metric consistency, period alignment, and weak evidence rejection.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(bundle.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">primary ready<br><b>{summary.get('primary_ready_pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">adversarial detection<br><b>{summary.get('adversarial_detection_rate', 0.0)}</b></div>"
        f"<div class=\"card\">naive overclaim<br><b>{summary.get('naive_baseline_overclaim_rate', 0.0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Category</th><th>Status</th><th>Score</th><th>Risks</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("results", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_domain_benchmark(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_domain_benchmark_fixtures())
    results = [evaluate_market_research_domain_fixture(row) for row in rows]
    summary = _summary(results)
    bundle = {
        "schema": STAGE176_MARKET_RESEARCH_DOMAIN_BENCHMARK_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if summary["adversarial_detection_rate"] < 1.0 or summary["primary_ready_pass_rate"] < 1.0 else "passed",
        "result_count": len(results),
        "results": results,
        "summary": summary,
        "failed_fixture_ids": [str(row.get("fixture_id", "") or "") for row in results if row.get("status") != "passed"],
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["adversarial_detection_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
