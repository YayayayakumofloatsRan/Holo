from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from .live_crawler_search import run_live_crawler_search
from .stage212_action_journal import build_action_journal_from_payload, render_action_journal

STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_SMOKE_SCHEMA = "holo.stage213.market_research_action_journal_smoke.v1"
STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_RESULT_SCHEMA = "holo.stage213.market_research_action_journal_result.v1"
STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_SCORECARD_SCHEMA = "holo.stage213.market_research_action_journal_scorecard.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage213" / "stage213_market_research_action_journal.html"
WEAK_URL = "https://example.com/ai-capex-hot-take"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def default_market_research_action_journal_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage213-ai-capex-market-research",
            "user_text": "search Nvidia 2024 10-K AI infrastructure capex official SEC filing with sources",
            "expected_authority_url": SEC_URL,
            "expected_weak_url": WEAK_URL,
            "expected_status": "passed",
        }
    ]


def _dry_market_searcher() -> Any:
    calls = {"count": 0}

    def search(query: str) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "query": query,
                "status": "ok",
                "provider": "stage213_dry_market_search",
                "results": [
                    {
                        "title": "AI capex hot take",
                        "url": WEAK_URL,
                        "snippet": "A commentary post about AI capex without primary filing support.",
                    }
                ],
                "source_urls": [WEAK_URL],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "stage213_dry_market_search",
            "results": [
                {
                    "title": "NVIDIA 2024 Form 10-K",
                    "url": SEC_URL,
                    "snippet": "SEC filing with data center revenue, capital expenditure, risk factors, and liquidity discussion.",
                }
            ],
            "source_urls": [SEC_URL],
        }

    return search


def _dry_market_open_page(url: str) -> dict[str, Any]:
    if "sec.gov" in str(url):
        return {
            "url": str(url),
            "status": "ok",
            "provider": "stage213_dry_market_page",
            "html": (
                "<html><title>NVIDIA 2024 Form 10-K</title><body>"
                "NVIDIA Corporation Form 10-K annual report filed with the SEC. "
                "Data Center revenue increased substantially due to demand for accelerated computing and AI infrastructure. "
                "The filing discusses inventories, purchase obligations, capital expenditures, liquidity, supply constraints, "
                "customer concentration, and risks related to demand for AI systems. "
                "</body></html>"
            ),
        }
    return {
        "url": str(url),
        "status": "ok",
        "provider": "stage213_dry_market_page",
        "html": "<html><title>AI capex hot take</title><body>Opinion commentary with no primary filing text.</body></html>",
    }


def _market_report_from_crawler(crawler: dict[str, Any], *, query: str) -> dict[str, Any]:
    source_urls = [str(url) for url in list(crawler.get("source_urls", []) or []) if str(url or "").strip()]
    grounded = bool(source_urls) and str(crawler.get("status", "") or "") == "sufficient"
    report = {
        "schema": "holo.stage213.market_research_report.v1",
        "status": "grounded" if grounded else "evidence_insufficient",
        "query": _compact(query, 240),
        "source_urls": source_urls,
        "unsupported_claim_count": 0 if grounded else 1,
        "summary": (
            "NVIDIA AI infrastructure demand can be researched from primary SEC filing evidence; "
            "the smoke report only states filing-backed observations and does not infer valuation."
            if grounded
            else "No sufficient primary-source evidence was promoted."
        ),
        "citations": [{"label": "NVIDIA 2024 Form 10-K", "url": url} for url in source_urls],
    }
    return sanitize_public_metadata(report)


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def build_market_research_action_journal_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    crawler = _dict(result.get("stage186_live_crawler_search", {}))
    journal = _dict(result.get("stage212_action_journal", {}))
    rendered = str(result.get("rendered_action_journal", "") or "")
    report = _dict(result.get("market_research_report", {}))
    source_urls = [str(url) for url in list(crawler.get("source_urls", []) or [])]
    ok, private_paths = assert_no_private_reasoning(result)
    checks = {
        "crawler_multistep": _check(
            str(crawler.get("status", "") or "") == "sufficient" and int(crawler.get("query_count", 0) or 0) >= 2,
            score=1.0 if int(crawler.get("query_count", 0) or 0) >= 2 else 0.0,
            reason="crawler_did_not_continue",
        ),
        "authority_source_promoted": _check(
            any(url.startswith("https://www.sec.gov/") for url in source_urls),
            score=1.0 if any(url.startswith("https://www.sec.gov/") for url in source_urls) else 0.0,
            reason="primary_source_missing",
        ),
        "weak_source_not_promoted": _check(
            WEAK_URL not in source_urls,
            score=1.0 if WEAK_URL not in source_urls else 0.0,
            reason="weak_source_promoted",
        ),
        "action_journal_visible": _check(
            int(journal.get("entry_count", 0) or 0) >= 1
            and "[crawl:query]" in rendered
            and "[crawl:open]" in rendered
            and "[feedback]" in rendered,
            score=1.0 if "[action:1]" in rendered and "[feedback]" in rendered else 0.0,
            reason="action_journal_missing",
        ),
        "report_grounded": _check(
            str(report.get("status", "") or "") == "grounded" and int(report.get("unsupported_claim_count", 0) or 0) == 0,
            score=1.0 if report.get("status") == "grounded" else 0.0,
            reason="report_not_grounded",
        ),
        "privacy": _check(ok, score=1.0 if ok else 0.0, reason="private_reasoning:" + ",".join(private_paths[:3])),
    }
    score = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    return {
        "schema": STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_SCORECARD_SCHEMA,
        "score": score,
        "passed": all(bool(row["passed"]) for row in checks.values()),
        "checks": checks,
    }


def evaluate_market_research_action_journal_fixture(fixture: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    source = dict(fixture or {})
    query = str(source.get("user_text", "") or default_market_research_action_journal_fixtures()[0]["user_text"])
    crawler = run_live_crawler_search(
        user_text=query,
        web_search_fn=_dry_market_searcher(),
        open_page_fn=_dry_market_open_page,
        network_enabled=True,
        max_queries=3,
        max_pages_per_query=2,
    )
    payload = {
        "stage186_live_crawler_search": crawler,
        "stage190_self_feedback_loop": _dict(crawler.get("stage190_self_feedback_loop", {})),
    }
    journal = build_action_journal_from_payload(payload, limit=1)
    rendered = render_action_journal(journal)
    report = _market_report_from_crawler(crawler, query=query)
    result = {
        "schema": STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_RESULT_SCHEMA,
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(query, limit=12)),
        "status": "unknown",
        "dry_run": bool(dry_run),
        "query": _compact(query, 260),
        "stage186_live_crawler_search": crawler,
        "stage212_action_journal": journal,
        "rendered_action_journal": rendered,
        "market_research_report": report,
        "created_at": utc_now(),
    }
    scorecard = build_market_research_action_journal_scorecard(result)
    result["scorecard"] = scorecard
    result["status"] = "passed" if bool(scorecard.get("passed", False)) else "failed"
    result["failure_reasons"] = [
        str(row.get("reason", "") or key)
        for key, row in _dict(scorecard.get("checks", {})).items()
        if isinstance(row, dict) and not bool(row.get("passed", False))
    ]
    return sanitize_public_metadata(result)


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_path.with_suffix(".json")
    jsonl_path = output_path.with_suffix(".jsonl")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in list(bundle.get("results", []) or [])) + "\n",
        encoding="utf-8",
    )
    sections: list[str] = []
    for result in list(bundle.get("results", []) or []):
        sections.append(
            "<section>"
            f"<h2>{html.escape(str(result.get('fixture_id', '')))} - {html.escape(str(result.get('status', '')))}</h2>"
            f"<p><b>Score:</b> {html.escape(str(_dict(result.get('scorecard', {})).get('score', '')))}</p>"
            f"<pre>{html.escape(str(result.get('rendered_action_journal', '') or ''))}</pre>"
            f"<pre>{html.escape(json.dumps(result.get('market_research_report', {}), ensure_ascii=False, indent=2))}</pre>"
            "</section>"
        )
    output_path.write_text(
        "\n".join(
            [
                "<!doctype html><meta charset='utf-8'>",
                "<title>Stage213 Market Research Action Journal Smoke</title>",
                "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:1100px;margin:32px auto;line-height:1.45}"
                "pre{white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;padding:12px;border-radius:6px}"
                "section{border-top:1px solid #d0d7de;padding-top:18px;margin-top:18px}</style>",
                "<h1>Stage213 Market Research Action Journal Smoke</h1>",
                f"<p>Status: <b>{html.escape(str(bundle.get('status', '')))}</b> | Score: {html.escape(str(bundle.get('score', '')))}</p>",
                *sections,
            ]
        ),
        encoding="utf-8",
    )


def run_market_research_action_journal_smoke(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fail_under: float | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_action_journal_fixtures())
    results = [evaluate_market_research_action_journal_fixture(row, dry_run=dry_run) for row in rows]
    score = round(
        sum(float(_dict(result.get("scorecard", {})).get("score", 0.0) or 0.0) for result in results)
        / max(1, len(results)),
        4,
    )
    bundle = {
        "schema": STAGE213_MARKET_RESEARCH_ACTION_JOURNAL_SMOKE_SCHEMA,
        "status": "passed" if all(str(row.get("status", "")) == "passed" for row in results) else "failed",
        "score": score,
        "fixture_count": len(results),
        "results": results,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and score < float(fail_under)),
        "created_at": utc_now(),
    }
    output_path = Path(output) if output is not None else DEFAULT_OUTPUT
    _write_artifacts(sanitize_public_metadata(bundle), output_path)
    return sanitize_public_metadata(bundle)
