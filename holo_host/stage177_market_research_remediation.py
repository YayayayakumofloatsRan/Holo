from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .stage176_market_research_domain_benchmark import (
    default_market_research_domain_benchmark_fixtures,
    evaluate_market_research_domain_fixture,
)

STAGE177_MARKET_RESEARCH_REMEDIATION_SCHEMA = "holo.stage177.market_research_remediation.v1"
STAGE177_MARKET_RESEARCH_REMEDIATION_RESULT_SCHEMA = "holo.stage177.market_research_remediation_result.v1"
STAGE177_MARKET_RESEARCH_REMEDIATION_ACTION_SCHEMA = "holo.stage177.market_research_remediation_action.v1"
STAGE177_MARKET_RESEARCH_REMEDIATION_LEDGER_SCHEMA = "holo.stage177.market_research_remediation_ledger.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {str(key): _public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_public(item) for item in clean]
    return clean


def _report(domain_result: dict[str, Any]) -> dict[str, Any]:
    return _dict(domain_result.get("stage173_market_research_report", {}))


def _observed_periods(domain_result: dict[str, Any]) -> list[str]:
    periods: list[str] = []
    for metric in _list_dicts(_report(domain_result).get("metrics", [])):
        period = str(metric.get("period", "") or "").strip()
        if period and period not in periods:
            periods.append(period)
    return periods


def _missing_sections(domain_result: dict[str, Any]) -> list[str]:
    return [
        str(section)
        for section in list(_dict(_report(domain_result).get("filing_coverage_summary", {})).get("missing_sections", []) or [])
        if str(section).strip()
    ]


def _base_query(domain_result: dict[str, Any]) -> str:
    query = str(domain_result.get("query", "") or "").strip()
    expected_period = str(domain_result.get("expected_period", "") or "").strip()
    if query:
        return query
    return f"Apple AAPL {expected_period} 10-K financial analysis".strip()


def _action(
    *,
    domain_result: dict[str, Any],
    risk_flag: str,
    action_type: str,
    required_tool: str,
    recommended_query: str = "",
    priority: str = "high",
    reason: str,
    required_evidence: list[str],
    success_criteria: list[str],
) -> dict[str, Any]:
    fixture_id = str(domain_result.get("fixture_id", "") or "market_research")
    action_id = "stage177:" + stable_digest(fixture_id, risk_flag, action_type, recommended_query, limit=12)
    return {
        "schema": STAGE177_MARKET_RESEARCH_REMEDIATION_ACTION_SCHEMA,
        "action_id": action_id,
        "fixture_id": fixture_id,
        "risk_flag": risk_flag,
        "action_type": action_type,
        "status": "recommended",
        "priority": priority,
        "required_tool": required_tool,
        "recommended_query": _compact(recommended_query, 360),
        "reason": _compact(reason, 420),
        "required_evidence": list(required_evidence),
        "success_criteria": list(success_criteria),
    }


def build_market_research_remediation_actions(domain_result: dict[str, Any]) -> list[dict[str, Any]]:
    source = _dict(domain_result)
    risks = [str(item) for item in list(source.get("detected_risk_flags", []) or []) if str(item).strip()]
    expected_period = str(source.get("expected_period", "") or "").strip()
    base_query = _base_query(source)
    actions: list[dict[str, Any]] = []

    if "filing_text_missing" in risks:
        actions.append(
            _action(
                domain_result=source,
                risk_flag="filing_text_missing",
                action_type="request_filing_text_or_open_primary_url",
                required_tool="open_page",
                recommended_query=f"{base_query} primary filing html",
                priority="critical",
                reason="The domain result has web observations but no usable filing text, so a report cannot be finalized.",
                required_evidence=["primary filing URL", "raw filing text", "filing section anchors"],
                success_criteria=["filing_text_char_count >= 120", "source_authority status sufficient"],
            )
        )

    if "source_authority_insufficient" in risks:
        query = f"site:sec.gov {base_query} Form 10-K {expected_period}".strip()
        actions.append(
            _action(
                domain_result=source,
                risk_flag="source_authority_insufficient",
                action_type="retry_primary_source_search",
                required_tool="web_search",
                recommended_query=query,
                priority="critical",
                reason="A third-party or weak source cannot support filing-grounded financial analysis.",
                required_evidence=["primary SEC filing result", "source authority classification", "source URLs"],
                success_criteria=["at least one sec.gov filing URL", "source_authority status sufficient"],
            )
        )

    if "filing_checklist_incomplete" in risks:
        missing = ", ".join(_missing_sections(source)) or "required 10-K sections"
        actions.append(
            _action(
                domain_result=source,
                risk_flag="filing_checklist_incomplete",
                action_type="retrieve_complete_filing_text",
                required_tool="find_in_page",
                recommended_query=f"{base_query} retrieve missing filing sections: {missing}",
                priority="critical",
                reason=f"The filing checklist is incomplete; missing sections: {missing}.",
                required_evidence=["complete filing text", "Item 1A", "Item 7", "Item 8"],
                success_criteria=["filing coverage complete", "missing_sections empty"],
            )
        )

    if "metric_conflict" in risks:
        actions.append(
            _action(
                domain_result=source,
                risk_flag="metric_conflict",
                action_type="produce_metric_conflict_report",
                required_tool="market_research_report",
                recommended_query=f"{base_query} compare conflicting metric values",
                priority="critical",
                reason="Extracted metrics conflict; the agent must report the conflict instead of stating a settled value.",
                required_evidence=["conflicting metric rows", "source snippets for each value", "resolution status"],
                success_criteria=["conflict explicitly reported", "no settled metric stated until resolved"],
            )
        )

    if "period_mismatch" in risks:
        observed = ", ".join(_observed_periods(source)) or "unknown"
        actions.append(
            _action(
                domain_result=source,
                risk_flag="period_mismatch",
                action_type="clarify_or_refetch_period",
                required_tool="web_search",
                recommended_query=f"site:sec.gov Apple AAPL {expected_period} 10-K filing",
                priority="critical",
                reason=f"The requested period is {expected_period or 'unspecified'}, but evidence metrics indicate {observed}.",
                required_evidence=["requested fiscal period", "evidence fiscal period", "period-aligned filing URL"],
                success_criteria=["all extracted metrics match requested period", "period mismatch resolved or user clarifies target period"],
            )
        )

    return actions


def _operator_message(*, domain_result: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    risks = [str(item) for item in list(domain_result.get("detected_risk_flags", []) or []) if str(item).strip()]
    if not risks:
        return "Evidence is sufficient for a filing-grounded market-research answer. No remediation is required."
    expected = str(domain_result.get("expected_period", "") or "").strip()
    observed = ", ".join(_observed_periods(domain_result))
    clauses: list[str] = []
    if "filing_text_missing" in risks:
        clauses.append("Cannot finalize: filing text is missing, so web-only evidence is insufficient.")
    if "source_authority_insufficient" in risks:
        clauses.append("Cannot finalize: the source authority is insufficient; retry primary-source search before analysis.")
    if "filing_checklist_incomplete" in risks:
        missing = ", ".join(_missing_sections(domain_result)) or "required filing sections"
        clauses.append(f"Cannot finalize: filing coverage is incomplete; missing {missing}.")
    if "metric_conflict" in risks:
        clauses.append("Cannot finalize: extracted metrics conflict; produce a conflict report before stating any settled metric.")
    if "period_mismatch" in risks:
        clauses.append(f"Cannot finalize: requested period {expected or 'unspecified'} conflicts with evidence period {observed or 'unknown'}; clarify or refetch period-aligned evidence.")
    if not clauses:
        clauses.append("Cannot finalize: domain gates failed and remediation is required.")
    next_actions = ", ".join(str(action.get("action_type", "")) for action in actions[:3])
    if next_actions:
        clauses.append(f"Next actions: {next_actions}.")
    return _compact(" ".join(clauses), 900)


def _recommended_stop_reason(actions: list[dict[str, Any]]) -> str:
    action_types = [str(action.get("action_type", "") or "") for action in actions]
    if not action_types:
        return "final_answer_ready"
    if "retry_primary_source_search" in action_types:
        return "needs_source_retry"
    if "request_filing_text_or_open_primary_url" in action_types or "retrieve_complete_filing_text" in action_types:
        return "needs_filing_text"
    if "clarify_or_refetch_period" in action_types:
        return "needs_period_clarification"
    if "produce_metric_conflict_report" in action_types:
        return "needs_metric_resolution"
    return "evidence_exhausted"


def build_market_research_remediation_result(domain_result: dict[str, Any]) -> dict[str, Any]:
    source = _dict(domain_result)
    actions = build_market_research_remediation_actions(source)
    can_finalize = not actions and str(source.get("status", "") or "") == "passed"
    status = "ready_to_finalize" if can_finalize else "remediation_required"
    risk_flags = [str(item) for item in list(source.get("detected_risk_flags", []) or []) if str(item).strip()]
    result = {
        "schema": STAGE177_MARKET_RESEARCH_REMEDIATION_RESULT_SCHEMA,
        "fixture_id": str(source.get("fixture_id", "") or stable_digest(json.dumps(source, ensure_ascii=False), limit=10)),
        "category": str(source.get("category", "") or ""),
        "status": status,
        "can_finalize": bool(can_finalize),
        "requires_user_input": bool(any(str(action.get("action_type", "")) == "clarify_or_refetch_period" for action in actions)),
        "recommended_stop_reason": _recommended_stop_reason(actions),
        "risk_flags": sorted(set(risk_flags)),
        "remediation_actions": actions,
        "operator_message": _operator_message(domain_result=source, actions=actions),
        "source_domain_status": str(source.get("status", "") or ""),
        "source_domain_score": _dict(source.get("domain_scorecard", {})).get("overall_score", 0.0),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    public = _dict(_public(result))
    public.setdefault("risk_flags", [])
    public.setdefault("remediation_actions", [])
    return public


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    remediation_required = [row for row in results if not bool(row.get("can_finalize", False))]
    finalizable = [row for row in results if bool(row.get("can_finalize", False))]
    action_count = sum(len(list(row.get("remediation_actions", []) or [])) for row in results)
    critical_count = sum(
        1
        for row in results
        for action in list(row.get("remediation_actions", []) or [])
        if isinstance(action, dict) and str(action.get("priority", "") or "") == "critical"
    )
    by_action: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for row in results:
        for risk in list(row.get("risk_flags", []) or []):
            key = str(risk)
            by_risk[key] = by_risk.get(key, 0) + 1
        for action in list(row.get("remediation_actions", []) or []):
            if isinstance(action, dict):
                key = str(action.get("action_type", "") or "")
                if key:
                    by_action[key] = by_action.get(key, 0) + 1
    return {
        "remediation_required_count": len(remediation_required),
        "finalizable_count": len(finalizable),
        "action_count": action_count,
        "critical_action_count": critical_count,
        "can_finalize_rate": round(len(finalizable) / max(1, len(results)), 4),
        "risk_counts": dict(sorted(by_risk.items())),
        "action_counts": dict(sorted(by_action.items())),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    for result in _list_dicts(bundle.get("results", [])):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(result.get('recommended_stop_reason', '')))}</td>"
            f"<td>{html.escape(', '.join(str(x) for x in list(result.get('risk_flags', []) or [])))}</td>"
            f"<td>{html.escape(', '.join(str(action.get('action_type', '')) for action in _list_dicts(result.get('remediation_actions', []))))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage177 Market Research Remediation</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left;vertical-align:top}th{background:#eef3f0}"
        ".summary{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage177 Market Research Remediation</h1>"
        "<p>Deterministic remediation plans for market-research evidence failures. The bundle recommends next actions; it does not fetch, write memory, call providers, or start transport.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">results<br><b>{bundle.get('result_count', 0)}</b></div>"
        f"<div class=\"card\">needs remediation<br><b>{summary.get('remediation_required_count', 0)}</b></div>"
        f"<div class=\"card\">finalizable<br><b>{summary.get('finalizable_count', 0)}</b></div>"
        f"<div class=\"card\">critical actions<br><b>{summary.get('critical_action_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Status</th><th>Stop</th><th>Risks</th><th>Actions</th></tr></thead>"
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


def run_market_research_remediation(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    domain_results: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    if domain_results is None:
        domain_results = [
            evaluate_market_research_domain_fixture(fixture)
            for fixture in default_market_research_domain_benchmark_fixtures()
        ]
    results = [build_market_research_remediation_result(row) for row in domain_results]
    summary = _summary(results)
    bundle = {
        "schema": STAGE177_MARKET_RESEARCH_REMEDIATION_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed",
        "result_count": len(results),
        "results": results,
        "summary": summary,
        "remediation_ledger": {
            "schema": STAGE177_MARKET_RESEARCH_REMEDIATION_LEDGER_SCHEMA,
            "row_count": len(results),
            "recommended_action_count": int(summary.get("action_count", 0) or 0),
        },
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["can_finalize_rate"] < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
