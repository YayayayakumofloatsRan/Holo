from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from .live_crawler_search import run_live_crawler_search
from .market_research_finalization_gate import build_market_research_finalization_gate
from .market_research_report_assembly import assemble_market_research_report
from .market_research_source_promotion import promote_market_research_sources
from .stage169_market_research_pack import build_market_research_pack
from .stage173_market_research_report import build_market_research_report
from .stage212_action_journal import build_action_journal_from_payload, render_action_journal

STAGE214_MARKET_RESEARCH_OPERATOR_RUN_SCHEMA = "holo.stage214.market_research_operator_run.v1"
STAGE214_MARKET_RESEARCH_OPERATOR_RUN_BUNDLE_SCHEMA = "holo.stage214.market_research_operator_run_bundle.v1"
STAGE214_MARKET_RESEARCH_OPERATOR_PHASE_SCHEMA = "holo.stage214.market_research_operator_phase.v1"
STAGE214_MARKET_RESEARCH_OPERATOR_SCORECARD_SCHEMA = "holo.stage214.market_research_operator_scorecard.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage214" / "stage214_market_research_operator_run.html"
WEAK_URL = "https://example.com/ai-capex-hot-take"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm"

_SAMPLE_NVIDIA_10K_TEXT = """
Item 1. Business
NVIDIA Corporation provides accelerated computing platforms for gaming, professional visualization, data center,
automotive, robotics, and AI infrastructure workloads.

Item 1A. Risk Factors
The company is exposed to customer concentration, supply constraints, inventory risk, export controls,
geopolitical uncertainty, demand volatility for AI systems, and intense competition.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Total revenue was $60.9 billion in 2024. Net income was $29.8 billion in 2024. Data Center revenue increased
substantially due to demand for accelerated computing and generative AI infrastructure. Capital expenditures,
purchase obligations, and supply commitments remain important operating considerations.

Item 8. Financial Statements
Cash and cash equivalents were $7.3 billion in 2024. Operating income was $33.0 billion in 2024.
""".strip()


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def default_market_research_operator_run_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage214-nvidia-ai-infrastructure-operator-run",
            "question": "Research NVIDIA AI infrastructure demand using official SEC filing evidence and produce a grounded market note.",
            "search_query": "NVIDIA 2024 10-K AI infrastructure Data Center revenue official SEC filing",
            "expected_source_url": SEC_URL,
            "weak_source_url": WEAK_URL,
        }
    ]


def _dry_market_searcher() -> Callable[[str], dict[str, Any]]:
    calls = {"count": 0}

    def search(query: str) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "query": query,
                "status": "ok",
                "provider": "stage214_dry_market_search",
                "results": [
                    {
                        "title": "AI capex hot take",
                        "url": WEAK_URL,
                        "snippet": "A third-party opinion post about AI capex without primary SEC filing support.",
                    }
                ],
                "source_urls": [WEAK_URL],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "stage214_dry_market_search",
            "results": [
                {
                    "title": "NVIDIA 2024 Form 10-K",
                    "url": SEC_URL,
                    "snippet": (
                        "Official SEC annual report with Data Center revenue, risk factors, capital expenditures, "
                        "purchase obligations, liquidity, and AI infrastructure demand discussion."
                    ),
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
            "provider": "stage214_dry_market_page",
            "html": f"<html><title>NVIDIA 2024 Form 10-K</title><body>{html.escape(_SAMPLE_NVIDIA_10K_TEXT)}</body></html>",
        }
    return {
        "url": str(url),
        "status": "ok",
        "provider": "stage214_dry_market_page",
        "html": "<html><title>AI capex hot take</title><body>Opinion commentary with no primary filing text.</body></html>",
    }


def _source_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in list(row.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    for result in _list_dicts(row.get("results", [])):
        text = str(result.get("url", "") or "").strip()
        if text and text not in urls:
            urls.append(text)
    page = _dict(row.get("page_evidence", {}))
    selected = str(page.get("selected_url", "") or "").strip()
    if selected and selected not in urls:
        urls.insert(0, selected)
    return urls


def _rows_for_url(rows: Any, url: str) -> list[dict[str, Any]]:
    target = str(url or "").strip()
    selected: list[dict[str, Any]] = []
    for row in _list_dicts(rows):
        if target and target in _source_urls(row):
            selected.append(row)
    return selected


def _filing_text_from_crawler(crawler: dict[str, Any], selected_url: str) -> str:
    target = str(selected_url or "").strip()
    for row in _list_dicts(crawler.get("page_observation_ledger", [])):
        if target and str(row.get("url", "") or "") != target:
            continue
        text = str(row.get("text", "") or "").strip()
        if text:
            return _restore_filing_item_boundaries(text)
    for web_row in _list_dicts(crawler.get("web_observation_ledger", [])):
        page = _dict(web_row.get("page_evidence", {}))
        for observation in _list_dicts(page.get("page_observations", [])):
            if target and str(observation.get("url", "") or "") != target:
                continue
            text = str(observation.get("text", "") or "").strip()
            if text:
                return _restore_filing_item_boundaries(text)
    return ""


def _restore_filing_item_boundaries(text: str) -> str:
    current = str(text or "")
    current = re.sub(r"\s+(Item\s+(?:1A|1|7|8)\.)", r"\n\1", current)
    return current.strip()


def _phase(
    phase: str,
    *,
    status: str,
    summary: str = "",
    observation_count: int = 0,
    source_count: int = 0,
    stop_reason: str = "",
) -> dict[str, Any]:
    return {
        "schema": STAGE214_MARKET_RESEARCH_OPERATOR_PHASE_SCHEMA,
        "phase_id": "stage214_phase:" + stable_digest(phase, status, summary, limit=12),
        "phase": str(phase or ""),
        "status": str(status or ""),
        "summary": _compact(summary, 320),
        "observation_count": max(0, int(observation_count or 0)),
        "source_count": max(0, int(source_count or 0)),
        "canonical_stop_reason": str(stop_reason or "final_answer_ready"),
        "created_at": utc_now(),
    }


def _check(passed: bool, *, score: float, reason: str) -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def build_market_research_operator_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    crawler = _dict(result.get("stage186_live_crawler_search", {}))
    promotion = _dict(result.get("stage196_market_research_source_promotion", {}))
    pack = _dict(result.get("stage169_market_research_pack", {}))
    report = _dict(result.get("stage173_market_research_report", {}))
    assembly = _dict(result.get("stage197_market_research_report_assembly", {}))
    final_gate = _dict(result.get("stage198_market_research_finalization_gate", {}))
    rendered = str(result.get("rendered_action_journal", "") or "")
    phases = [str(row.get("phase", "") or "") for row in _list_dicts(result.get("operator_trajectory", []))]
    ok, private_paths = assert_no_private_reasoning(result)
    expected_phases = [
        "plan",
        "crawl",
        "promote_source",
        "build_pack",
        "build_report",
        "assemble_report",
        "finalize",
        "action_journal",
    ]
    checks = {
        "complete_pipeline": _check(phases == expected_phases, score=1.0 if phases == expected_phases else 0.0, reason="operator_pipeline_incomplete"),
        "crawler_multistep": _check(
            str(crawler.get("status", "") or "") == "sufficient" and int(crawler.get("query_count", 0) or 0) >= 2,
            score=1.0 if int(crawler.get("query_count", 0) or 0) >= 2 else 0.0,
            reason="crawler_did_not_continue",
        ),
        "source_promoted": _check(
            str(promotion.get("status", "") or "") == "promoted" and str(promotion.get("selected_url", "") or "").startswith("https://www.sec.gov/"),
            score=1.0 if str(promotion.get("status", "") or "") == "promoted" else 0.0,
            reason="authority_source_not_promoted",
        ),
        "pack_ready": _check(str(pack.get("status", "") or "") == "ready", score=1.0 if pack.get("status") == "ready" else 0.0, reason="pack_not_ready"),
        "report_finalized": _check(
            str(report.get("status", "") or "") == "evidence_ready"
            and str(assembly.get("status", "") or "") == "assembled"
            and str(final_gate.get("status", "") or "") == "finalized"
            and int(report.get("unsupported_claim_count", 0) or 0) == 0,
            score=1.0 if str(final_gate.get("status", "") or "") == "finalized" else 0.0,
            reason="report_not_finalized",
        ),
        "action_journal_visible": _check(
            "[action:1] web_search" in rendered and "[crawl:query]" in rendered and "[feedback]" in rendered,
            score=1.0 if "[feedback]" in rendered else 0.0,
            reason="action_journal_missing",
        ),
        "privacy": _check(ok, score=1.0 if ok else 0.0, reason="private_reasoning:" + ",".join(private_paths[:3])),
    }
    score = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    return {
        "schema": STAGE214_MARKET_RESEARCH_OPERATOR_SCORECARD_SCHEMA,
        "score": score,
        "passed": all(bool(row["passed"]) for row in checks.values()),
        "checks": checks,
    }


def run_market_research_operator_run(
    fixture: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
    network_enabled: bool = True,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = dict(fixture or default_market_research_operator_run_fixtures()[0])
    question = str(source.get("question", "") or default_market_research_operator_run_fixtures()[0]["question"])
    search_query = str(source.get("search_query", "") or question)
    searcher = web_search_fn or (_dry_market_searcher() if dry_run else None)
    opener = open_page_fn or (_dry_market_open_page if dry_run else None)
    phases: list[dict[str, Any]] = [
        _phase(
            "plan",
            status="planned",
            summary="Plan: crawl for official filing evidence, promote the primary source, build pack, assemble report, finalize.",
        )
    ]

    crawler = run_live_crawler_search(
        user_text=f"search {search_query}",
        web_search_fn=searcher,
        open_page_fn=opener,
        network_enabled=bool(network_enabled),
        max_queries=3,
        max_pages_per_query=2,
    )
    phases.append(
        _phase(
            "crawl",
            status=str(crawler.get("status", "") or ""),
            summary=str(crawler.get("final_summary", "") or ""),
            observation_count=len(_list_dicts(crawler.get("web_observation_ledger", []))) + len(_list_dicts(crawler.get("page_observation_ledger", []))),
            source_count=len(list(crawler.get("source_urls", []) or [])),
            stop_reason=str(crawler.get("stop_reason", "") or ""),
        )
    )

    promotion = promote_market_research_sources(
        question=question,
        web_observation_ledger=crawler.get("web_observation_ledger", []),
        network_enabled=bool(network_enabled),
        web_search_fn=searcher,
        open_page_fn=opener,
        max_crawl_queries=0,
    )
    selected_url = str(promotion.get("selected_url", "") or "")
    promoted_rows = _rows_for_url(crawler.get("web_observation_ledger", []), selected_url) or _list_dicts(
        promotion.get("promoted_web_observation_ledger", [])
    )
    phases.append(
        _phase(
            "promote_source",
            status=str(promotion.get("status", "") or ""),
            summary=str(promotion.get("public_summary", "") or ""),
            observation_count=len(promoted_rows),
            source_count=1 if selected_url else 0,
            stop_reason=str(promotion.get("canonical_stop_reason", "") or ""),
        )
    )

    filing_text = _filing_text_from_crawler(crawler, selected_url) or (_SAMPLE_NVIDIA_10K_TEXT if dry_run else "")
    pack = build_market_research_pack(
        query=question,
        web_observation_ledger=promoted_rows,
        filing_text=filing_text,
        filing_type="10-K",
    )
    phases.append(
        _phase(
            "build_pack",
            status=str(pack.get("status", "") or ""),
            summary=f"pack evidence_items={pack.get('evidence_item_count', 0)}",
            observation_count=int(pack.get("evidence_item_count", 0) or 0),
            source_count=len(promoted_rows),
        )
    )

    report = build_market_research_report(market_research_pack=pack, question=question)
    phases.append(
        _phase(
            "build_report",
            status=str(report.get("status", "") or ""),
            summary=f"report sections={report.get('section_count', 0)} metrics={report.get('metric_count', 0)} citations={report.get('citation_count', 0)}",
            observation_count=int(report.get("section_count", 0) or 0) + int(report.get("metric_count", 0) or 0),
            source_count=int(report.get("citation_count", 0) or 0),
        )
    )

    assembly = assemble_market_research_report(
        question=question,
        stage196_market_research_source_promotion=promotion,
        stage173_market_research_report=report,
    )
    phases.append(
        _phase(
            "assemble_report",
            status=str(assembly.get("status", "") or ""),
            summary=f"citation_quality={assembly.get('citation_quality_status', '')}",
            source_count=len(list(assembly.get("ordered_sources", []) or [])),
            stop_reason=str(assembly.get("canonical_stop_reason", "") or ""),
        )
    )

    final_gate = build_market_research_finalization_gate(question=question, stage197_market_research_report_assembly=assembly)
    final_visible_text = str(final_gate.get("visible_text", "") or "")
    phases.append(
        _phase(
            "finalize",
            status=str(final_gate.get("status", "") or ""),
            summary=_compact(final_visible_text, 240),
            source_count=1 if final_gate.get("primary_source_url") else 0,
            stop_reason=str(final_gate.get("canonical_stop_reason", "") or ""),
        )
    )

    journal_payload = {
        "stage186_live_crawler_search": crawler,
        "stage190_self_feedback_loop": _dict(crawler.get("stage190_self_feedback_loop", {})),
    }
    action_journal = build_action_journal_from_payload(journal_payload, limit=1)
    rendered_journal = render_action_journal(action_journal)
    phases.append(
        _phase(
            "action_journal",
            status=str(action_journal.get("status", "") or ""),
            summary=f"journal entries={action_journal.get('entry_count', 0)}",
            observation_count=int(action_journal.get("entry_count", 0) or 0),
        )
    )

    run_id = "stage214_operator:" + stable_digest(question, selected_url, limit=12)
    result: dict[str, Any] = {
        "schema": STAGE214_MARKET_RESEARCH_OPERATOR_RUN_SCHEMA,
        "operator_run_id": run_id,
        "fixture_id": str(source.get("fixture_id", "") or run_id),
        "status": "unknown",
        "dry_run": bool(dry_run),
        "question": _compact(question, 320),
        "operator_trajectory": phases,
        "stage186_live_crawler_search": crawler,
        "stage196_market_research_source_promotion": promotion,
        "stage169_market_research_pack": pack,
        "stage173_market_research_report": report,
        "stage197_market_research_report_assembly": assembly,
        "stage198_market_research_finalization_gate": final_gate,
        "stage212_action_journal": action_journal,
        "rendered_action_journal": rendered_journal,
        "final_visible_text": final_visible_text,
        "created_at": utc_now(),
    }
    scorecard = build_market_research_operator_scorecard(result)
    result["scorecard"] = scorecard
    result["status"] = "ready" if bool(scorecard.get("passed", False)) else "failed"
    result["failure_reasons"] = [
        str(row.get("reason", "") or key)
        for key, row in _dict(scorecard.get("checks", {})).items()
        if isinstance(row, dict) and not bool(row.get("passed", False))
    ]
    return sanitize_public_metadata(result)


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> dict[str, str]:
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
    for result in _list_dicts(bundle.get("results", [])):
        trajectory = "\n".join(
            f"[{row.get('phase')}] status={row.get('status')} stop={row.get('canonical_stop_reason')} summary={row.get('summary')}"
            for row in _list_dicts(result.get("operator_trajectory", []))
        )
        sections.append(
            "<section>"
            f"<h2>{html.escape(str(result.get('fixture_id', '')))} - {html.escape(str(result.get('status', '')))}</h2>"
            f"<p><b>Score:</b> {html.escape(str(_dict(result.get('scorecard', {})).get('score', '')))}</p>"
            f"<h3>Operator trajectory</h3><pre>{html.escape(trajectory)}</pre>"
            f"<h3>Action journal</h3><pre>{html.escape(str(result.get('rendered_action_journal', '') or ''))}</pre>"
            f"<h3>Final</h3><pre>{html.escape(str(result.get('final_visible_text', '') or ''))}</pre>"
            "</section>"
        )
    output_path.write_text(
        "\n".join(
            [
                "<!doctype html><meta charset='utf-8'>",
                "<title>Stage214 Market Research Operator Run</title>",
                "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:1120px;margin:32px auto;line-height:1.45}"
                "pre{white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;padding:12px;border-radius:6px}"
                "section{border-top:1px solid #d0d7de;padding-top:18px;margin-top:18px}</style>",
                "<h1>Stage214 Market Research Operator Run</h1>",
                f"<p>Status: <b>{html.escape(str(bundle.get('status', '')))}</b> | Score: {html.escape(str(bundle.get('score', '')))}</p>",
                *sections,
            ]
        ),
        encoding="utf-8",
    )
    return {"html": str(output_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_operator_run_bundle(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool = True,
    fail_under: float | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_operator_run_fixtures())
    results = [
        run_market_research_operator_run(row, dry_run=dry_run, network_enabled=network_enabled)
        for row in rows
    ]
    score = round(
        sum(float(_dict(result.get("scorecard", {})).get("score", 0.0) or 0.0) for result in results) / max(1, len(results)),
        4,
    )
    bundle: dict[str, Any] = {
        "schema": STAGE214_MARKET_RESEARCH_OPERATOR_RUN_BUNDLE_SCHEMA,
        "status": "passed" if all(str(row.get("status", "") or "") == "ready" for row in results) else "failed",
        "score": score,
        "fixture_count": len(results),
        "results": results,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and score < float(fail_under)),
        "created_at": utc_now(),
    }
    output_path = Path(output) if output is not None else DEFAULT_OUTPUT
    bundle["artifacts"] = _write_artifacts(sanitize_public_metadata(bundle), output_path)
    return sanitize_public_metadata(bundle)
