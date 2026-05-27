from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .common import compact_text, stable_digest, utc_now

STAGE168_SOURCE_AUTHORITY_SCHEMA = "holo.stage168.source_authority.v1"
STAGE168_SOURCE_AUTHORITY_REPORT_SCHEMA = "holo.stage168.source_authority_report.v1"
STAGE168_SOURCE_AUTHORITY_AUDIT_SCHEMA = "holo.stage168.source_authority_audit.v1"

_FINANCIAL_RE = re.compile(r"\b(10-k|10-q|8-k|annual report|quarterly report|sec|filing|financial|investor|earnings)\b", re.I)
_DOCS_RE = re.compile(r"\b(docs?|documentation|developer|api|cli|sdk|function calling|tool calling)\b", re.I)
_CODE_RE = re.compile(r"\b(github|source code|repository|repo|package|npm|pypi)\b", re.I)

_PRIMARY_TIERS = {"primary", "official"}
_STRONG_FAMILIES = {"financial_filing", "company_ir", "official_docs", "api_docs", "code_repository", "package_registry"}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _host(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower()


def _path(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return f"{parsed.path} {parsed.query}".lower()


def _source_key(url: str, title: str, snippet: str) -> str:
    return stable_digest(url, title, snippet, limit=12)


def _base_report(
    *,
    url: str,
    query: str,
    title: str,
    snippet: str,
    source_family: str,
    authority_tier: str,
    source_role: str,
    is_first_party: bool,
    confidence: float,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": STAGE168_SOURCE_AUTHORITY_SCHEMA,
        "source_id": "srcauth:" + _source_key(url, title, snippet),
        "url": str(url or ""),
        "domain": _host(url),
        "query": _compact(query, 180),
        "title": _compact(title, 180),
        "snippet": _compact(snippet, 260),
        "source_family": source_family,
        "authority_tier": authority_tier,
        "source_role": source_role,
        "is_first_party": bool(is_first_party),
        "risk_flags": list(risk_flags or []),
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 4),
    }


def classify_source_authority(
    url: str,
    *,
    query: str = "",
    title: str = "",
    snippet: str = "",
) -> dict[str, Any]:
    current_url = str(url or "").strip()
    host = _host(current_url)
    path = _path(current_url)
    blob = f"{query} {title} {snippet} {current_url}".lower()
    risk_flags: list[str] = []

    if "sec.gov" in host and ("/archives/edgar/" in path or _FINANCIAL_RE.search(blob)):
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="financial_filing",
            authority_tier="primary",
            source_role="regulatory_filing",
            is_first_party=True,
            confidence=0.96,
        )
    if any(marker in host or marker in path for marker in ("investor.", "investors.", "investor-relations", "/ir/", "ir.")):
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="company_ir",
            authority_tier="primary",
            source_role="company_disclosure",
            is_first_party=True,
            confidence=0.9,
        )
    if "api-docs.deepseek.com" in host or (host.endswith("deepseek.com") and "api" in path):
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="api_docs",
            authority_tier="official",
            source_role="vendor_api_reference",
            is_first_party=True,
            confidence=0.9,
        )
    if "developers.openai.com" in host or (host.endswith("openai.com") and (_DOCS_RE.search(blob) or "docs" in path)):
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="official_docs",
            authority_tier="official",
            source_role="vendor_documentation",
            is_first_party=True,
            confidence=0.9,
        )
    if "github.com" in host:
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="code_repository",
            authority_tier="official" if _CODE_RE.search(blob) else "secondary",
            source_role="source_repository",
            is_first_party=False,
            confidence=0.78,
        )
    if "npmjs.com" in host or "pypi.org" in host:
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="package_registry",
            authority_tier="official" if _CODE_RE.search(blob) else "secondary",
            source_role="package_registry",
            is_first_party=False,
            confidence=0.74,
        )
    if any(marker in host for marker in ("reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "marketwatch.com")):
        return _base_report(
            url=current_url,
            query=query,
            title=title,
            snippet=snippet,
            source_family="news",
            authority_tier="secondary",
            source_role="journalistic_source",
            is_first_party=False,
            confidence=0.62,
        )

    if _FINANCIAL_RE.search(blob):
        risk_flags.append("not_financial_authority")
    risk_flags.append("third_party_or_unclassified")
    return _base_report(
        url=current_url,
        query=query,
        title=title,
        snippet=snippet,
        source_family="unclassified",
        authority_tier="low",
        source_role="third_party_summary",
        is_first_party=False,
        confidence=0.25,
        risk_flags=risk_flags,
    )


def _sources_from_web_rows(web_observation_ledger: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in _list_dicts(web_observation_ledger):
        for result in _list_dicts(row.get("results", [])):
            url = str(result.get("url", "") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "url": url,
                    "title": str(result.get("title", "") or ""),
                    "snippet": str(result.get("snippet", "") or ""),
                }
            )
        page_evidence = row.get("page_evidence", {})
        if isinstance(page_evidence, dict):
            url = str(page_evidence.get("selected_url", "") or "").strip()
            if url and url not in seen:
                seen.add(url)
                sources.append(
                    {
                        "url": url,
                        "title": "",
                        "snippet": str(page_evidence.get("supporting_snippet", "") or ""),
                    }
                )
        for url_value in list(row.get("source_urls", []) or []):
            url = str(url_value or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({"url": url, "title": "", "snippet": ""})
    return sources


def _infer_required_family(query: str, task_type: str = "") -> str:
    lowered = f"{query} {task_type}".lower()
    if _FINANCIAL_RE.search(lowered):
        return "financial_filing"
    if _DOCS_RE.search(lowered):
        return "api_docs" if "api" in lowered or "tool calling" in lowered or "function calling" in lowered else "official_docs"
    if _CODE_RE.search(lowered):
        return "code_repository"
    return ""


def evaluate_source_authority(
    query: str,
    web_observation_ledger: Any,
    *,
    required_source_family: str = "",
    task_type: str = "",
) -> dict[str, Any]:
    required_family = str(required_source_family or "").strip() or _infer_required_family(query, task_type)
    source_rows = [
        classify_source_authority(source["url"], query=query, title=source.get("title", ""), snippet=source.get("snippet", ""))
        for source in _sources_from_web_rows(web_observation_ledger)
    ]
    strong_sources = [
        row
        for row in source_rows
        if row["authority_tier"] in _PRIMARY_TIERS and row["source_family"] in _STRONG_FAMILIES
    ]
    primary_count = sum(1 for row in source_rows if row["authority_tier"] == "primary")
    first_party_count = sum(1 for row in source_rows if row["is_first_party"])
    missing: list[str] = []
    if required_family and not any(row["source_family"] == required_family for row in source_rows):
        missing.append(f"missing_required_source_family:{required_family}")
    if required_family == "financial_filing" and not any(row["source_family"] in {"financial_filing", "company_ir"} for row in source_rows):
        if not any("not_financial_authority" in list(row.get("risk_flags", []) or []) for row in source_rows):
            missing.append("not_financial_authority")
        else:
            missing.append("not_financial_authority")
    blocked_count = sum(1 for row in source_rows if row["authority_tier"] == "blocked")
    best_sources = sorted(
        source_rows,
        key=lambda row: (
            3 if row["authority_tier"] == "primary" else 2 if row["authority_tier"] == "official" else 1 if row["authority_tier"] == "secondary" else 0,
            float(row.get("confidence", 0.0) or 0.0),
        ),
        reverse=True,
    )[:5]
    if blocked_count and not strong_sources:
        status = "blocked"
    elif missing:
        status = "insufficient"
    elif strong_sources:
        status = "sufficient"
    elif any(row["authority_tier"] == "secondary" for row in source_rows):
        status = "weak"
    else:
        status = "insufficient"
    return {
        "schema": STAGE168_SOURCE_AUTHORITY_REPORT_SCHEMA,
        "query": _compact(query, 180),
        "task_type": str(task_type or ""),
        "required_source_family": required_family,
        "status": status,
        "source_count": len(source_rows),
        "primary_source_count": primary_count,
        "first_party_source_count": first_party_count,
        "blocked_source_count": blocked_count,
        "best_sources": best_sources,
        "source_authority_rows": source_rows,
        "missing_authority": sorted(set(missing)),
        "confidence": round(sum(float(row.get("confidence", 0.0) or 0.0) for row in best_sources) / max(1, len(best_sources)), 4) if best_sources else 0.0,
        "created_at": utc_now(),
    }


def attach_source_authority_to_observations(
    observations: list[dict[str, Any]],
    *,
    query: str = "",
    required_source_family: str = "",
    task_type: str = "",
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in observations if isinstance(row, dict)]
    report = evaluate_source_authority(query, rows, required_source_family=required_source_family, task_type=task_type)
    return [{**row, "source_authority": report} for row in rows]


def default_source_authority_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "sec-filing-primary",
            "query": "Apple 2024 10-K SEC annual report",
            "task_type": "market_research",
            "required_source_family": "financial_filing",
            "web_observation_ledger": [
                {
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
        },
        {
            "fixture_id": "company-ir-primary",
            "query": "Apple investor relations annual report",
            "task_type": "market_research",
            "required_source_family": "company_ir",
            "web_observation_ledger": [
                {
                    "source_urls": ["https://investor.apple.com/investor-relations/default.aspx"],
                    "results": [
                        {
                            "title": "Apple Investor Relations",
                            "url": "https://investor.apple.com/investor-relations/default.aspx",
                            "snippet": "Investor relations and annual reports for Apple.",
                        }
                    ],
                }
            ],
        },
        {
            "fixture_id": "third-party-financial-summary-insufficient",
            "query": "Apple 2024 10-K financial analysis",
            "task_type": "market_research",
            "required_source_family": "financial_filing",
            "web_observation_ledger": [
                {
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
        },
        {
            "fixture_id": "openai-docs-official",
            "query": "OpenAI Codex CLI official docs",
            "task_type": "engineering_research",
            "required_source_family": "official_docs",
            "web_observation_ledger": [
                {
                    "source_urls": ["https://developers.openai.com/codex/cli"],
                    "results": [
                        {
                            "title": "CLI - Codex | OpenAI Developers",
                            "url": "https://developers.openai.com/codex/cli",
                            "snippet": "Codex CLI official documentation.",
                        }
                    ],
                }
            ],
        },
    ]


def evaluate_source_authority_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    report = evaluate_source_authority(
        str(fixture.get("query", "") or ""),
        fixture.get("web_observation_ledger", []),
        required_source_family=str(fixture.get("required_source_family", "") or ""),
        task_type=str(fixture.get("task_type", "") or ""),
    )
    passed = report["status"] == "sufficient"
    expected_pass = bool(fixture.get("expected_pass", fixture.get("fixture_id") != "third-party-financial-summary-insufficient"))
    status = "passed" if passed == expected_pass else "failed"
    return {
        "schema": "holo.stage168.source_authority_audit_result.v1",
        "fixture_id": str(fixture.get("fixture_id", "") or stable_digest(report["query"], limit=10)),
        "query": report["query"],
        "status": status,
        "expected_pass": expected_pass,
        "source_authority": report,
        "failure_reasons": [] if status == "passed" else ["source_authority_expectation_mismatch"],
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in results if row["status"] == "passed")
    sufficient = sum(1 for row in results if row["source_authority"]["status"] == "sufficient")
    return {
        "pass_rate": round(passed / max(1, len(results)), 4),
        "sufficient_authority_rate": round(sufficient / max(1, len(results)), 4),
        "primary_source_total": sum(int(row["source_authority"].get("primary_source_count", 0) or 0) for row in results),
        "first_party_source_total": sum(int(row["source_authority"].get("first_party_source_count", 0) or 0) for row in results),
    }


def _html_report(report: dict[str, Any]) -> str:
    rows = []
    for result in list(report.get("audit_results", []) or []):
        authority = _dict(result.get("source_authority", {}))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(authority.get('status', '')))}</td>"
            f"<td>{html.escape(str(authority.get('required_source_family', '')))}</td>"
            f"<td>{authority.get('primary_source_count', 0)}</td>"
            f"<td>{authority.get('first_party_source_count', 0)}</td>"
            f"<td>{html.escape(','.join(str(item) for item in list(authority.get('missing_authority', []) or [])))}</td>"
            "</tr>"
        )
    summary = _dict(report.get("summary", {}))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage168 Source Authority Audit</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage168 Source Authority Audit</h1>"
        "<p>First-party and task-specific source authority checks for engineering and market research.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">status<br><b>{html.escape(str(report.get('status', 'unknown')))}</b></div>"
        f"<div class=\"card\">pass rate<br><b>{summary.get('pass_rate', 0.0)}</b></div>"
        f"<div class=\"card\">primary sources<br><b>{summary.get('primary_source_total', 0)}</b></div>"
        f"<div class=\"card\">first-party sources<br><b>{summary.get('first_party_source_total', 0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Audit</th><th>Authority</th><th>Required</th><th>Primary</th><th>First-party</th><th>Missing</th></tr></thead>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in list(report.get("audit_results", []) or [])) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_source_authority_audit(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_source_authority_fixtures())
    results = [evaluate_source_authority_fixture(row) for row in rows]
    summary = _summary(results)
    failed = [row["fixture_id"] for row in results if row["status"] != "passed"]
    report = {
        "schema": STAGE168_SOURCE_AUTHORITY_AUDIT_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if failed else "passed",
        "audit_count": len(results),
        "audit_results": results,
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
