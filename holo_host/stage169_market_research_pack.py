from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .stage168_source_authority import evaluate_source_authority

STAGE169_ENTITY_SCHEMA = "holo.stage169.market_entity.v1"
STAGE169_FILING_SECTIONS_SCHEMA = "holo.stage169.filing_sections.v1"
STAGE169_FILING_CHECKLIST_SCHEMA = "holo.stage169.filing_checklist.v1"
STAGE169_METRICS_SCHEMA = "holo.stage169.financial_metrics.v1"
STAGE169_METRIC_CONSISTENCY_SCHEMA = "holo.stage169.metric_consistency.v1"
STAGE169_MARKET_RESEARCH_PACK_SCHEMA = "holo.stage169.market_research_pack.v1"
STAGE169_MARKET_RESEARCH_PACK_BUNDLE_SCHEMA = "holo.stage169.market_research_pack_bundle.v1"

_ENTITY_REGISTRY = {
    "aapl": {"canonical_name": "Apple Inc.", "ticker": "AAPL", "cik": "0000320193", "aliases": ("apple", "apple inc", "apple inc.")},
    "msft": {"canonical_name": "Microsoft Corporation", "ticker": "MSFT", "cik": "0000789019", "aliases": ("microsoft", "microsoft corporation")},
    "nvda": {"canonical_name": "NVIDIA Corporation", "ticker": "NVDA", "cik": "0001045810", "aliases": ("nvidia", "nvidia corporation")},
    "tsla": {"canonical_name": "Tesla, Inc.", "ticker": "TSLA", "cik": "0001318605", "aliases": ("tesla", "tesla inc", "tesla, inc.")},
}

_SECTION_REQUIREMENTS = {
    "10-K": ("business", "risk_factors", "mda", "financial_statements"),
    "10-Q": ("risk_factors", "mda", "financial_statements"),
}

_SECTION_HEAD_RE = re.compile(r"(?im)^\s*Item\s+(1A|1|7|8)\.?\s+([^\n\r]+)")
_SECTION_MAP = {
    "1": ("business", "Business"),
    "1A": ("risk_factors", "Risk Factors"),
    "7": ("mda", "Management's Discussion and Analysis"),
    "8": ("financial_statements", "Financial Statements"),
}
_MONEY_RE = re.compile(
    r"(?P<label>net sales|revenue|total revenue|net income|operating income|gross margin|cash and cash equivalents)"
    r"[^.$]{0,90}?\$?(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>billion|million)?"
    r"(?:[^.]{0,80}?\b(?P<period>20\d{2})\b)?",
    re.I,
)


def _compact(value: Any, limit: int = 300) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def normalize_market_entity(text: str) -> dict[str, Any]:
    lowered = f" {str(text or '').lower()} "
    for key, data in _ENTITY_REGISTRY.items():
        candidates = {key, data["ticker"].lower(), *(alias.lower() for alias in data["aliases"])}
        if any(re.search(rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", lowered) for candidate in candidates):
            return {
                "schema": STAGE169_ENTITY_SCHEMA,
                "canonical_name": data["canonical_name"],
                "ticker": data["ticker"],
                "cik": data["cik"],
                "matched_aliases": sorted(candidate for candidate in candidates if candidate in lowered),
                "confidence": 0.95,
            }
    ticker_match = re.search(r"\b[A-Z]{1,5}\b", str(text or ""))
    ticker = ticker_match.group(0) if ticker_match else ""
    return {
        "schema": STAGE169_ENTITY_SCHEMA,
        "canonical_name": ticker or "",
        "ticker": ticker,
        "cik": "",
        "matched_aliases": [ticker] if ticker else [],
        "confidence": 0.35 if ticker else 0.0,
    }


def extract_filing_sections(text: str, *, source_url: str = "") -> dict[str, Any]:
    current = str(text or "")
    matches = list(_SECTION_HEAD_RE.finditer(current))
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        item_code = match.group(1).upper()
        if item_code not in _SECTION_MAP:
            continue
        section_id, canonical_title = _SECTION_MAP[item_code]
        if section_id in seen:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(current)
        body = current[start:end].strip()
        seen.add(section_id)
        sections.append(
            {
                "section_id": section_id,
                "item": item_code,
                "title": canonical_title,
                "heading": _compact(match.group(0), 160),
                "snippet": _compact(body, 500),
                "char_start": int(match.start()),
                "char_end": int(end),
                "source_url": str(source_url or ""),
                "evidence_id": "filing_section:" + stable_digest(source_url, section_id, body, limit=12),
            }
        )
    return {
        "schema": STAGE169_FILING_SECTIONS_SCHEMA,
        "section_count": len(sections),
        "sections": sections,
        "source_url": str(source_url or ""),
    }


def evaluate_filing_checklist(sections: list[dict[str, Any]] | Any, *, filing_type: str = "10-K") -> dict[str, Any]:
    required = list(_SECTION_REQUIREMENTS.get(str(filing_type or "10-K").upper(), _SECTION_REQUIREMENTS["10-K"]))
    present = sorted({str(row.get("section_id", "") or "") for row in _list_dicts(sections)})
    covered = [section for section in required if section in present]
    missing = [section for section in required if section not in present]
    score = round(len(covered) / max(1, len(required)), 4)
    return {
        "schema": STAGE169_FILING_CHECKLIST_SCHEMA,
        "filing_type": str(filing_type or "10-K").upper(),
        "required_sections": required,
        "covered_sections": covered,
        "missing_sections": missing,
        "coverage_score": score,
        "status": "complete" if not missing else "incomplete",
    }


def _metric_key(label: str) -> str:
    lowered = str(label or "").lower()
    if "net sales" in lowered or "revenue" in lowered:
        return "net_sales"
    if "net income" in lowered:
        return "net_income"
    if "operating income" in lowered:
        return "operating_income"
    if "gross margin" in lowered:
        return "gross_margin"
    if "cash and cash equivalents" in lowered:
        return "cash_and_cash_equivalents"
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def extract_financial_metrics(text: str, *, source_url: str = "") -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for match in _MONEY_RE.finditer(str(text or "")):
        label = match.group("label")
        raw_value = match.group("value")
        unit_text = str(match.group("unit") or "billion").lower()
        value = float(raw_value.replace(",", ""))
        unit = "million_usd" if unit_text.startswith("million") else "billion_usd"
        period = match.group("period") or ""
        rows.append(
            {
                "metric_id": "metric:" + stable_digest(label, raw_value, period, source_url, limit=12),
                "metric_key": _metric_key(label),
                "label": label.lower(),
                "value": value,
                "unit": unit,
                "period": period,
                "source_url": str(source_url or ""),
                "snippet": _compact(match.group(0), 220),
            }
        )
    return {
        "schema": STAGE169_METRICS_SCHEMA,
        "metric_count": len(rows),
        "metrics": rows,
    }


def _normalized_metric_value(row: dict[str, Any]) -> float:
    value = float(row.get("value", 0.0) or 0.0)
    unit = str(row.get("unit", "") or "")
    if unit == "million_usd":
        return value / 1000.0
    return value


def evaluate_metric_consistency(metrics: list[dict[str, Any]] | Any, *, tolerance_ratio: float = 0.002) -> dict[str, Any]:
    rows = _list_dicts(metrics)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("metric_key", "") or ""), str(row.get("period", "") or "unknown"))
        if key[0]:
            groups.setdefault(key, []).append(row)
    conflicts: list[dict[str, Any]] = []
    for (metric_key, period), group in groups.items():
        if len(group) < 2:
            continue
        values = [_normalized_metric_value(row) for row in group]
        baseline = max(0.001, min(abs(value) for value in values if value is not None))
        if (max(values) - min(values)) / baseline > float(tolerance_ratio or 0.0):
            conflicts.append(
                {
                    "metric_key": metric_key,
                    "period": period,
                    "values": values,
                    "source_urls": [str(row.get("source_url", "") or "") for row in group],
                }
            )
    return {
        "schema": STAGE169_METRIC_CONSISTENCY_SCHEMA,
        "status": "conflicted" if conflicts else "consistent",
        "metric_count": len(rows),
        "group_count": len(groups),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def _first_source_url(web_observation_ledger: Any) -> str:
    for row in _list_dicts(web_observation_ledger):
        for url in list(row.get("source_urls", []) or []):
            if str(url or "").strip():
                return str(url).strip()
        for result in _list_dicts(row.get("results", [])):
            url = str(result.get("url", "") or "").strip()
            if url:
                return url
    return ""


def build_market_research_pack(
    *,
    query: str,
    web_observation_ledger: Any,
    filing_text: str,
    filing_type: str = "10-K",
) -> dict[str, Any]:
    entity = normalize_market_entity(query)
    source_url = _first_source_url(web_observation_ledger)
    source_authority = evaluate_source_authority(
        query,
        web_observation_ledger,
        required_source_family="financial_filing",
        task_type="market_research",
    )
    section_report = extract_filing_sections(filing_text, source_url=source_url)
    checklist = evaluate_filing_checklist(section_report["sections"], filing_type=filing_type)
    metric_report = extract_financial_metrics(filing_text, source_url=source_url)
    consistency = evaluate_metric_consistency(metric_report["metrics"])
    evidence_items = []
    for section in section_report["sections"]:
        evidence_items.append(
            {
                "evidence_id": section["evidence_id"],
                "evidence_type": "filing_section",
                "section_id": section["section_id"],
                "source_url": section["source_url"],
                "snippet": section["snippet"],
            }
        )
    for metric in metric_report["metrics"]:
        evidence_items.append(
            {
                "evidence_id": metric["metric_id"],
                "evidence_type": "financial_metric",
                "metric_key": metric["metric_key"],
                "period": metric["period"],
                "source_url": metric["source_url"],
                "snippet": metric["snippet"],
            }
        )
    failure_reasons: list[str] = []
    if source_authority["status"] != "sufficient":
        failure_reasons.append("source_authority_insufficient")
    if checklist["status"] != "complete":
        failure_reasons.append("filing_checklist_incomplete")
    if consistency["status"] == "conflicted":
        failure_reasons.append("metric_conflict")
    status = "ready" if not failure_reasons else "insufficient"
    return {
        "schema": STAGE169_MARKET_RESEARCH_PACK_SCHEMA,
        "pack_id": "mrpack:" + stable_digest(query, source_url, filing_text, limit=12),
        "query": _compact(query, 180),
        "status": status,
        "failure_reasons": failure_reasons,
        "entity": entity,
        "source_authority": source_authority,
        "filing_sections": section_report,
        "filing_checklist": checklist,
        "financial_metrics": metric_report,
        "metric_consistency": consistency,
        "evidence_items": evidence_items,
        "evidence_item_count": len(evidence_items),
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }


_SAMPLE_10K_TEXT = """
Item 1. Business
Apple designs, manufactures and markets smartphones, personal computers, tablets, wearables and accessories.

Item 1A. Risk Factors
The Company is exposed to intense competition, supply chain disruption, foreign exchange risk and regulatory risks.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Net sales were $391.0 billion in 2024 compared to $383.3 billion in 2023. Net income was $93.7 billion in 2024.

Item 8. Financial Statements and Supplementary Data
The consolidated statements include balance sheets, statements of operations, comprehensive income, shareholders' equity and cash flows.
"""


def default_market_research_pack_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "apple-10k-ready",
            "query": "Apple AAPL 2024 10-K financial analysis",
            "web_observation_ledger": [
                {
                    "status": "ok",
                    "source_urls": ["https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"],
                    "results": [
                        {
                            "title": "Apple Form 10-K",
                            "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                            "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                        }
                    ],
                }
            ],
            "filing_text": _SAMPLE_10K_TEXT,
            "expected_status": "ready",
        },
        {
            "fixture_id": "third-party-source-insufficient",
            "query": "Apple 2024 10-K financial analysis",
            "web_observation_ledger": [
                {
                    "status": "ok",
                    "source_urls": ["https://random.example.com/apple-10k-analysis"],
                    "results": [
                        {
                            "title": "Apple 10-K Analysis",
                            "url": "https://random.example.com/apple-10k-analysis",
                            "snippet": "A third-party summary of Apple financials.",
                        }
                    ],
                }
            ],
            "filing_text": _SAMPLE_10K_TEXT,
            "expected_status": "insufficient",
        },
    ]


def evaluate_market_research_pack_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    pack = build_market_research_pack(
        query=str(fixture.get("query", "") or ""),
        web_observation_ledger=fixture.get("web_observation_ledger", []),
        filing_text=str(fixture.get("filing_text", "") or ""),
    )
    expected_status = str(fixture.get("expected_status", "ready") or "ready")
    return {
        "schema": "holo.stage169.market_research_pack_result.v1",
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(pack["query"], limit=10)),
        "status": "passed" if pack["status"] == expected_status else "failed",
        "expected_status": expected_status,
        "pack": pack,
        "failure_reasons": [] if pack["status"] == expected_status else ["market_research_pack_expectation_mismatch"],
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in results if row["status"] == "passed")
    ready = sum(1 for row in results if row["pack"]["status"] == "ready")
    sections = sum(int(row["pack"]["filing_sections"].get("section_count", 0) or 0) for row in results)
    metrics = sum(int(row["pack"]["financial_metrics"].get("metric_count", 0) or 0) for row in results)
    return {
        "pass_rate": round(passed / max(1, len(results)), 4),
        "ready_pack_rate": round(ready / max(1, len(results)), 4),
        "section_total": sections,
        "metric_total": metrics,
    }


def _html_report(report: dict[str, Any]) -> str:
    rows: list[str] = []
    for result in list(report.get("pack_results", []) or []):
        pack = dict(result.get("pack", {}) if isinstance(result.get("pack", {}), dict) else {})
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(pack.get('status', '')))}</td>"
            f"<td>{html.escape(str(pack.get('entity', {}).get('ticker', '')))}</td>"
            f"<td>{pack.get('filing_checklist', {}).get('coverage_score', 0.0)}</td>"
            f"<td>{pack.get('financial_metrics', {}).get('metric_count', 0)}</td>"
            f"<td>{html.escape(','.join(str(item) for item in list(pack.get('failure_reasons', []) or [])))}</td>"
            "</tr>"
        )
    summary = dict(report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {})
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage169 Market Research Pack</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage169 Market Research Pack</h1>"
        "<p>Filing section coverage, source authority, metric extraction, and consistency checks.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(report.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">ready rate<br><b>{summary.get('ready_pack_rate', 0.0)}</b></div>"
        f"<div class=\"card\">metrics<br><b>{summary.get('metric_total', 0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Audit</th><th>Pack</th><th>Ticker</th><th>Coverage</th><th>Metrics</th><th>Failures</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list(report.get("pack_results", []) or [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_pack_bundle(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_pack_fixtures())
    results = [evaluate_market_research_pack_fixture(row) for row in rows]
    summary = _summary(results)
    failed = [row["fixture_id"] for row in results if row["status"] != "passed"]
    report = {
        "schema": STAGE169_MARKET_RESEARCH_PACK_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if failed else "passed",
        "pack_count": len(results),
        "pack_results": results,
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
