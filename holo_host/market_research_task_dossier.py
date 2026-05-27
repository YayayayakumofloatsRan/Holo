from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_finalization_gate import build_market_research_finalization_gate
from .market_research_report_assembly import assemble_market_research_report
from .market_research_source_promotion import promote_market_research_sources
from .stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from .stage173_market_research_report import build_market_research_report

STAGE199_MARKET_RESEARCH_TASK_DOSSIER_SCHEMA = "holo.stage199.market_research_task_dossier.v1"
STAGE199_MARKET_RESEARCH_DOSSIER_BUNDLE_SCHEMA = "holo.stage199.market_research_dossier_bundle.v1"


def _compact(value: Any, limit: int = 300) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _citation_urls(report: dict[str, Any]) -> list[str]:
    return _unique([str(row.get("url", "") or "") for row in _list_dicts(report.get("citations", []))])


def _source_urls(
    *,
    source_promotion: dict[str, Any],
    report: dict[str, Any],
    finalization_gate: dict[str, Any],
    web_observation_ledger: Any,
) -> list[str]:
    urls: list[str] = []
    promoted = str(source_promotion.get("selected_url", "") or "").strip()
    if promoted:
        urls.append(promoted)
    primary = str(finalization_gate.get("primary_source_url", "") or "").strip()
    if primary:
        urls.append(primary)
    urls.extend(_citation_urls(report))
    for row in _list_dicts(web_observation_ledger):
        urls.extend(str(url or "").strip() for url in list(row.get("source_urls", []) or []))
        for result in _list_dicts(row.get("results", [])):
            urls.append(str(result.get("url", "") or ""))
    return _unique(urls)


def _status(*, assembly: dict[str, Any], finalization_gate: dict[str, Any], report: dict[str, Any]) -> str:
    final_status = str(finalization_gate.get("status", "") or "")
    assembly_status = str(assembly.get("status", "") or "")
    if final_status == "finalized" or (assembly_status == "assembled" and report):
        return "report_ready"
    if assembly_status == "citation_mismatch" or final_status == "blocked":
        return "needs_citation_repair"
    if assembly_status == "needs_report":
        return "needs_report"
    if assembly or finalization_gate:
        return "needs_evidence"
    return "no_research_state"


def _open_items(*, status: str, assembly: dict[str, Any], finalization_gate: dict[str, Any], report: dict[str, Any]) -> list[str]:
    items: list[str] = []
    items.extend(str(item) for item in list(assembly.get("missing_requirements", []) or []) if str(item))
    items.extend(str(item) for item in list(report.get("limitations", []) or []) if str(item))
    if status == "needs_citation_repair":
        items.append("report citations must include the promoted authoritative source")
    if status == "needs_report":
        items.append("stage173_market_research_report")
    if status == "needs_evidence" and not items:
        items.append("financial_filing_source")
    if finalization_gate and not bool(finalization_gate.get("final_visible_text_ready", False)):
        stop = str(finalization_gate.get("canonical_stop_reason", "") or "")
        if stop and stop not in items:
            items.append(stop)
    return _unique(items)


def _next_actions(*, question: str, status: str, open_items: list[str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if status == "needs_evidence" or any("financial_filing" in item or "source" in item for item in open_items):
        actions.append(
            {
                "action_type": "web_search",
                "priority": 0.92,
                "query": _compact(f"{question} SEC Form 10-K annual report financial filing", 220),
                "reason": "Find a primary financial filing source before report finalization.",
            }
        )
    if status in {"needs_report", "needs_citation_repair"}:
        actions.append(
            {
                "action_type": "market_research_report",
                "priority": 0.84,
                "query": _compact(question, 220),
                "reason": "Regenerate the structured market research report with citation coverage.",
            }
        )
    return actions


def _metric_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in _list_dicts(report.get("metrics", [])):
        rows.append(
            {
                "metric_key": str(metric.get("metric_key", "") or ""),
                "label": str(metric.get("label", "") or ""),
                "value": metric.get("value", ""),
                "unit": str(metric.get("unit", "") or ""),
                "period": str(metric.get("period", "") or ""),
                "source_url": str(metric.get("source_url", "") or ""),
            }
        )
    return rows


def build_market_research_task_dossier(
    *,
    question: str,
    stage196_market_research_source_promotion: dict[str, Any] | None = None,
    stage173_market_research_report: dict[str, Any] | None = None,
    stage197_market_research_report_assembly: dict[str, Any] | None = None,
    stage198_market_research_finalization_gate: dict[str, Any] | None = None,
    stage195_market_research_continuation_loop: dict[str, Any] | None = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    web_observation_ledger: Any = None,
) -> dict[str, Any]:
    """Build a resumable market-research dossier from the audited research stack."""

    question_text = _compact(question, 260)
    source_promotion = _dict(stage196_market_research_source_promotion)
    report = _dict(stage173_market_research_report)
    if not report:
        for row in _list_dicts(market_research_report_ledger):
            nested = _dict(row.get("stage173_market_research_report", {}))
            if nested:
                report = nested
                break
    assembly = _dict(stage197_market_research_report_assembly)
    finalization_gate = _dict(stage198_market_research_finalization_gate)
    continuation = _dict(stage195_market_research_continuation_loop)
    status = _status(assembly=assembly, finalization_gate=finalization_gate, report=report)
    open_items = _open_items(status=status, assembly=assembly, finalization_gate=finalization_gate, report=report)
    next_actions = _next_actions(question=question_text, status=status, open_items=open_items)
    source_urls = _source_urls(
        source_promotion=source_promotion,
        report=report,
        finalization_gate=finalization_gate,
        web_observation_ledger=web_observation_ledger,
    )
    metrics = _metric_rows(report)
    entity = _dict(report.get("entity", {}))
    final_visible = str(finalization_gate.get("visible_text", "") or "")
    dossier = {
        "schema": STAGE199_MARKET_RESEARCH_TASK_DOSSIER_SCHEMA,
        "dossier_id": "stage199_market_dossier:" + stable_digest(question_text, status, "|".join(source_urls[:3]), limit=12),
        "created_at": utc_now(),
        "question": question_text,
        "status": status,
        "entity": {
            "canonical_name": str(entity.get("canonical_name", "") or ""),
            "ticker": str(entity.get("ticker", "") or ""),
            "cik": str(entity.get("cik", "") or ""),
        },
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "metrics": metrics,
        "metric_count": len(metrics),
        "report_id": str(report.get("report_id", "") or ""),
        "report_status": str(report.get("status", "") or ""),
        "report_summary": _compact(_dict(report.get("analyst_conclusion", {})).get("summary", ""), 360),
        "final_answer": {
            "status": str(finalization_gate.get("status", "") or ""),
            "canonical_stop_reason": str(finalization_gate.get("canonical_stop_reason", "") or ""),
            "visible_text": final_visible,
        },
        "open_items": open_items,
        "next_actions": next_actions,
        "resume_state": {
            "can_resume": status != "no_research_state",
            "last_status": status,
            "next_action_count": len(next_actions),
            "round_count": int(continuation.get("round_count", 0) or 0),
            "source_count": len(source_urls),
            "metric_count": len(metrics),
        },
        "ledgers": {
            "web_observation_count": len(_list_dicts(web_observation_ledger)),
            "market_research_pack_count": len(_list_dicts(market_research_pack_ledger)),
            "market_research_report_count": len(_list_dicts(market_research_report_ledger)),
        },
        "hidden_reasoning_exposed": False,
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    clean = sanitize_public_metadata(dossier)
    if isinstance(clean, dict):
        clean.setdefault("source_urls", [])
        clean.setdefault("metrics", [])
        clean.setdefault("open_items", [])
        clean.setdefault("next_actions", [])
    return clean


def _ready_fixture_stack() -> dict[str, Any]:
    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=str(fixture.get("query", "") or ""),
        web_observation_ledger=fixture.get("web_observation_ledger", []),
        filing_text=str(fixture.get("filing_text", "") or ""),
    )
    report = build_market_research_report(market_research_pack=pack, question=str(fixture.get("query", "") or ""))
    source_promotion = promote_market_research_sources(
        question=str(fixture.get("query", "") or ""),
        web_observation_ledger=fixture.get("web_observation_ledger", []),
        network_enabled=False,
    )
    assembly = assemble_market_research_report(
        question=str(fixture.get("query", "") or ""),
        stage196_market_research_source_promotion=source_promotion,
        stage173_market_research_report=report,
    )
    finalization = build_market_research_finalization_gate(
        question=str(fixture.get("query", "") or ""),
        stage197_market_research_report_assembly=assembly,
        candidate_visible_text="",
    )
    return {
        "question": str(fixture.get("query", "") or ""),
        "stage196_market_research_source_promotion": source_promotion,
        "stage173_market_research_report": report,
        "stage197_market_research_report_assembly": assembly,
        "stage198_market_research_finalization_gate": finalization,
        "web_observation_ledger": fixture.get("web_observation_ledger", []),
    }


def _weak_fixture_stack() -> dict[str, Any]:
    question = "Analyze Apple AAPL 2024 10-K."
    assembly = assemble_market_research_report(
        question=question,
        stage196_market_research_source_promotion={
            "status": "weak",
            "authority_status": "insufficient",
            "source_family": "third_party_summary",
            "selected_url": "https://example.com/apple-summary",
            "missing_authority": ["financial_filing"],
            "canonical_stop_reason": "evidence_exhausted",
        },
        stage173_market_research_report={},
    )
    finalization = build_market_research_finalization_gate(
        question=question,
        stage197_market_research_report_assembly=assembly,
        candidate_visible_text="",
    )
    return {
        "question": question,
        "stage197_market_research_report_assembly": assembly,
        "stage198_market_research_finalization_gate": finalization,
    }


def default_market_research_dossier_fixtures() -> list[dict[str, Any]]:
    return [_ready_fixture_stack(), _weak_fixture_stack()]


def _html_report(bundle: dict[str, Any]) -> str:
    cards = []
    for dossier in _list_dicts(bundle.get("dossiers", [])):
        source_items = "".join(f"<li>{html.escape(url)}</li>" for url in list(dossier.get("source_urls", []) or [])[:5])
        action_items = "".join(
            f"<li>{html.escape(str(action.get('action_type', '')))}: {html.escape(str(action.get('query', action.get('reason', ''))))}</li>"
            for action in _list_dicts(dossier.get("next_actions", []))
        )
        cards.append(
            "<section class=\"dossier\">"
            f"<h2>{html.escape(str(dossier.get('question', '')))}</h2>"
            f"<p><b>Status:</b> {html.escape(str(dossier.get('status', '')))} | "
            f"<b>Sources:</b> {dossier.get('source_count', 0)} | <b>Metrics:</b> {dossier.get('metric_count', 0)}</p>"
            f"<p>{html.escape(str(dossier.get('report_summary', '')))}</p>"
            f"<h3>Sources</h3><ul>{source_items}</ul>"
            f"<h3>Next Actions</h3><ul>{action_items or '<li>none</li>'}</ul>"
            "</section>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage199 Market Research Task Dossier</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}.dossier{border:1px solid #ccd6d1;border-radius:6px;padding:14px;margin:14px 0}"
        "h1,h2{margin-bottom:8px}code{background:#eef3f0;padding:2px 4px;border-radius:4px}</style></head><body>"
        "<h1>Stage199 Market Research Task Dossier</h1>"
        "<p>Resumable source, report, finalization, open-item, and next-action state for long-running market research.</p>"
        f"{''.join(cards)}</body></html>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("dossiers", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_dossier_bundle(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_market_research_dossier_fixtures())
    dossiers = [build_market_research_task_dossier(**row) for row in rows]
    ready_count = sum(1 for row in dossiers if str(row.get("status", "") or "") == "report_ready")
    resumable_count = sum(1 for row in dossiers if bool(_dict(row.get("resume_state", {})).get("can_resume", False)))
    next_action_count = sum(len(list(row.get("next_actions", []) or [])) for row in dossiers)
    summary = {
        "ready_rate": round(ready_count / max(1, len(dossiers)), 4),
        "resumable_rate": round(resumable_count / max(1, len(dossiers)), 4),
        "next_action_count": next_action_count,
        "source_count": sum(int(row.get("source_count", 0) or 0) for row in dossiers),
    }
    status = "passed" if resumable_count == len(dossiers) and any(row.get("status") == "report_ready" for row in dossiers) else "failed"
    bundle = {
        "schema": STAGE199_MARKET_RESEARCH_DOSSIER_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": status,
        "dossier_count": len(dossiers),
        "dossiers": dossiers,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["resumable_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    clean = sanitize_public_metadata(bundle)
    if isinstance(clean, dict):
        for dossier in list(clean.get("dossiers", []) or []):
            if isinstance(dossier, dict):
                dossier.setdefault("source_urls", [])
                dossier.setdefault("metrics", [])
                dossier.setdefault("open_items", [])
                dossier.setdefault("next_actions", [])
    return clean
