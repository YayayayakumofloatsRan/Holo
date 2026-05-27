from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .stage169_market_research_pack import (
    build_market_research_pack,
    default_market_research_pack_fixtures,
)

STAGE173_MARKET_RESEARCH_REPORT_SCHEMA = "holo.stage173.market_research_report.v1"
STAGE173_MARKET_RESEARCH_REPORT_BUNDLE_SCHEMA = "holo.stage173.market_research_report_bundle.v1"
STAGE173_MARKET_RESEARCH_BASELINE_SCHEMA = "holo.stage173.market_research_baseline_comparison.v1"


def _compact(value: Any, limit: int = 320) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            rows.append(text)
    return rows


def _section_report(pack: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in _list_dicts(_dict(pack.get("filing_sections", {})).get("sections", [])):
        rows.append(
            {
                "section_id": str(section.get("section_id", "") or ""),
                "title": str(section.get("title", "") or ""),
                "summary": _compact(section.get("snippet", ""), 420),
                "source_url": str(section.get("source_url", "") or ""),
                "evidence_id": str(section.get("evidence_id", "") or ""),
            }
        )
    return rows


def _metric_report(pack: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in _list_dicts(_dict(pack.get("financial_metrics", {})).get("metrics", [])):
        rows.append(
            {
                "metric_key": str(metric.get("metric_key", "") or ""),
                "label": str(metric.get("label", "") or ""),
                "value": metric.get("value", 0.0),
                "unit": str(metric.get("unit", "") or ""),
                "period": str(metric.get("period", "") or ""),
                "source_url": str(metric.get("source_url", "") or ""),
                "evidence_id": str(metric.get("metric_id", "") or ""),
                "snippet": _compact(metric.get("snippet", ""), 220),
            }
        )
    return rows


def _citations(pack: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    authority = _dict(pack.get("source_authority", {}))
    best_sources = _list_dicts(authority.get("best_sources", []))
    family_by_url = {str(row.get("url", "") or ""): str(row.get("source_family", "") or "") for row in best_sources}
    for index, url in enumerate(_unique([str(row.get("source_url", "") or "") for row in _list_dicts(pack.get("evidence_items", []))])):
        citations.append(
            {
                "citation_id": f"citation:{index + 1}",
                "url": url,
                "source_family": family_by_url.get(url) or str(authority.get("required_source_family", "") or ""),
                "supports": "filing sections and financial metrics",
            }
        )
    return citations


def _limitations(pack: dict[str, Any], *, metrics: list[dict[str, Any]]) -> list[str]:
    limitations: list[str] = []
    checklist = _dict(pack.get("filing_checklist", {}))
    missing_sections = [str(item) for item in list(checklist.get("missing_sections", []) or []) if str(item)]
    if missing_sections:
        limitations.append("missing filing sections: " + ", ".join(missing_sections))
    if not metrics:
        limitations.append("no normalized financial metrics were extracted")
    if _dict(pack.get("metric_consistency", {})).get("status") == "conflicted":
        limitations.append("metric consistency conflict present")
    if _dict(pack.get("source_authority", {})).get("status") != "sufficient":
        limitations.append("source authority is insufficient for a publication-grade financial answer")
    return limitations


def _report_status(pack: dict[str, Any], limitations: list[str]) -> str:
    if str(pack.get("status", "") or "") == "ready" and not limitations:
        return "evidence_ready"
    if pack:
        return "evidence_insufficient"
    return "unsupported"


def _support_score(report: dict[str, Any]) -> float:
    score = 0.0
    if str(report.get("status", "") or "") == "evidence_ready":
        score += 0.35
    score += min(0.2, 0.05 * int(report.get("section_count", 0) or 0))
    score += min(0.18, 0.06 * int(report.get("metric_count", 0) or 0))
    score += min(0.17, 0.06 * int(report.get("citation_count", 0) or 0))
    if not report.get("unsupported_claims"):
        score += 0.1
    return round(min(1.0, score), 4)


def build_market_research_report(
    *,
    market_research_pack: dict[str, Any],
    question: str = "",
    audience: str = "operator",
) -> dict[str, Any]:
    """Create a deterministic analyst-style report from a Stage169 evidence pack."""

    pack = _dict(market_research_pack)
    sections = _section_report(pack)
    metrics = _metric_report(pack)
    citations = _citations(pack)
    limitations = _limitations(pack, metrics=metrics)
    unsupported = _unique([str(item) for item in list(pack.get("failure_reasons", []) or []) if str(item)])
    status = _report_status(pack, limitations)
    entity = _dict(pack.get("entity", {}))
    metric_consistency = _dict(pack.get("metric_consistency", {}))
    checklist = _dict(pack.get("filing_checklist", {}))
    source_authority = _dict(pack.get("source_authority", {}))
    report_id = "stage173_report:" + stable_digest(pack.get("pack_id", ""), question, audience, limit=12)
    conclusion_status = "evidence_ready" if status == "evidence_ready" else "evidence_insufficient"
    report: dict[str, Any] = {
        "schema": STAGE173_MARKET_RESEARCH_REPORT_SCHEMA,
        "report_id": report_id,
        "generated_at": utc_now(),
        "question": _compact(question, 260),
        "audience": str(audience or "operator"),
        "status": status,
        "entity": {
            "canonical_name": str(entity.get("canonical_name", "") or ""),
            "ticker": str(entity.get("ticker", "") or ""),
            "cik": str(entity.get("cik", "") or ""),
        },
        "source_authority_summary": {
            "status": str(source_authority.get("status", "") or ""),
            "source_family": str((_list_dicts(source_authority.get("best_sources", []))[:1] or [{}])[0].get("source_family", "") or source_authority.get("required_source_family", "") or ""),
            "confidence": float(source_authority.get("confidence", 0.0) or 0.0),
        },
        "filing_coverage_summary": {
            "filing_type": str(checklist.get("filing_type", "") or ""),
            "coverage_score": float(checklist.get("coverage_score", 0.0) or 0.0),
            "covered_sections": list(checklist.get("covered_sections", []) or []),
            "missing_sections": list(checklist.get("missing_sections", []) or []),
        },
        "sections": sections,
        "metrics": metrics,
        "metric_consistency": {
            "status": str(metric_consistency.get("status", "") or ""),
            "conflict_count": int(metric_consistency.get("conflict_count", 0) or 0),
        },
        "citations": citations,
        "unsupported_claims": unsupported,
        "limitations": limitations,
        "analyst_conclusion": {
            "status": conclusion_status,
            "summary": (
                "Evidence is sufficient for a bounded filing-grounded company summary."
                if status == "evidence_ready"
                else "Evidence is insufficient for a settled filing-grounded company summary."
            ),
            "investment_recommendation": "not_provided",
        },
        "section_count": len(sections),
        "metric_count": len(metrics),
        "citation_count": len(citations),
        "unsupported_claim_count": len(unsupported),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    report["evidence_support_score"] = _support_score(report)
    return report


def compare_market_research_baselines(
    *,
    report: dict[str, Any],
    weak_web_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = _dict(report)
    baseline = _dict(weak_web_baseline)
    if not baseline:
        baseline = {
            "label": "weak_web_only",
            "citation_count": 1,
            "section_count": 0,
            "metric_count": 0,
            "unsupported_claims": ["no_filing_sections", "no_metric_table", "source_authority_unverified"],
        }
    full_score = _support_score(current)
    weak_score = round(
        min(1.0, 0.04 * int(baseline.get("citation_count", 0) or 0) + 0.05 * int(baseline.get("metric_count", 0) or 0))
        - min(0.2, 0.04 * len(list(baseline.get("unsupported_claims", []) or []))),
        4,
    )
    weak_score = max(0.0, weak_score)
    return {
        "schema": STAGE173_MARKET_RESEARCH_BASELINE_SCHEMA,
        "full_stack_score": full_score,
        "weak_web_baseline_score": weak_score,
        "score_delta": round(full_score - weak_score, 4),
        "verdict": "full_stack_stronger" if full_score > weak_score else "baseline_not_beaten",
        "baseline_label": str(baseline.get("label", "weak_web_only") or "weak_web_only"),
    }


def default_market_research_report_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": fixture["fixture_id"],
            "question": fixture["query"],
            "market_research_pack": build_market_research_pack(
                query=str(fixture.get("query", "") or ""),
                web_observation_ledger=fixture.get("web_observation_ledger", []),
                filing_text=str(fixture.get("filing_text", "") or ""),
            ),
            "expected_status": "evidence_ready" if fixture.get("expected_status") == "ready" else "evidence_insufficient",
        }
        for fixture in default_market_research_pack_fixtures()
    ]


def evaluate_market_research_report_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    report = build_market_research_report(
        market_research_pack=_dict(fixture.get("market_research_pack", {})),
        question=str(fixture.get("question", "") or ""),
    )
    comparison = compare_market_research_baselines(report=report)
    expected = str(fixture.get("expected_status", "") or "evidence_ready")
    return {
        "schema": "holo.stage173.market_research_report_result.v1",
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(report.get("report_id", ""), limit=10)),
        "status": "passed" if report["status"] == expected else "failed",
        "expected_status": expected,
        "report": report,
        "baseline_comparison": comparison,
        "failure_reasons": [] if report["status"] == expected else ["market_research_report_expectation_mismatch"],
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in results if row["status"] == "passed")
    ready = sum(1 for row in results if row["report"]["status"] == "evidence_ready")
    citations = sum(int(row["report"].get("citation_count", 0) or 0) for row in results)
    unsupported = sum(int(row["report"].get("unsupported_claim_count", 0) or 0) for row in results)
    beaten = sum(1 for row in results if row["baseline_comparison"]["verdict"] == "full_stack_stronger")
    return {
        "pass_rate": round(passed / max(1, len(results)), 4),
        "ready_report_rate": round(ready / max(1, len(results)), 4),
        "baseline_win_rate": round(beaten / max(1, len(results)), 4),
        "citation_count": citations,
        "unsupported_claim_rate": round(unsupported / max(1, len(results)), 4),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    rows: list[str] = []
    for result in list(bundle.get("report_results", []) or []):
        report = _dict(result.get("report", {}))
        comparison = _dict(result.get("baseline_comparison", {}))
        entity = _dict(report.get("entity", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(report.get('status', '')))}</td>"
            f"<td>{html.escape(str(entity.get('ticker', '')))}</td>"
            f"<td>{report.get('section_count', 0)}</td>"
            f"<td>{report.get('metric_count', 0)}</td>"
            f"<td>{report.get('citation_count', 0)}</td>"
            f"<td>{html.escape(str(comparison.get('verdict', '')))}</td>"
            "</tr>"
        )
    summary = _dict(bundle.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage173 Market Research Report</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage173 Market Research Report</h1>"
        "<p>Deterministic filing-grounded analyst report generation from Stage169-172 evidence packs.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(bundle.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">ready rate<br><b>{summary.get('ready_report_rate', 0.0)}</b></div>"
        f"<div class=\"card\">baseline wins<br><b>{summary.get('baseline_win_rate', 0.0)}</b></div>"
        f"<div class=\"card\">citations<br><b>{summary.get('citation_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Audit</th><th>Report</th><th>Ticker</th><th>Sections</th><th>Metrics</th><th>Citations</th><th>Baseline</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list(bundle.get("report_results", []) or [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_report_bundle(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_report_fixtures())
    results = [evaluate_market_research_report_fixture(row) for row in rows]
    summary = _summary(results)
    failed = [row["fixture_id"] for row in results if row["status"] != "passed"]
    bundle = {
        "schema": STAGE173_MARKET_RESEARCH_REPORT_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if failed else "passed",
        "report_count": len(results),
        "report_results": results,
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
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return bundle
