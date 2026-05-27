from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA = "holo.stage198.market_research_finalization_gate.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _entity_label(report: dict[str, Any], question: str) -> str:
    entity = _dict(report.get("entity", {}))
    name = str(entity.get("canonical_name", "") or "").strip()
    ticker = str(entity.get("ticker", "") or "").strip()
    if name and ticker:
        return f"{name} ({ticker})"
    return name or ticker or _compact(question, 80) or "requested company"


def _metric_lines(report: dict[str, Any], limit: int = 3) -> list[str]:
    rows: list[str] = []
    for metric in _list_dicts(report.get("metrics", []))[:limit]:
        label = str(metric.get("label", "") or metric.get("metric_key", "") or "").strip()
        value = metric.get("value", "")
        unit = str(metric.get("unit", "") or "").strip()
        period = str(metric.get("period", "") or "").strip()
        detail = " ".join(str(item) for item in (value, unit, period) if str(item).strip())
        if label and detail:
            rows.append(f"- {label}: {detail}")
    return rows


def _section_lines(report: dict[str, Any], limit: int = 3) -> list[str]:
    rows: list[str] = []
    for section in _list_dicts(report.get("sections", []))[:limit]:
        title = str(section.get("title", "") or section.get("section_id", "") or "").strip()
        summary = _compact(section.get("summary", ""), 180)
        if title and summary:
            rows.append(f"- {title}: {summary}")
    return rows


def _source_lines(assembly: dict[str, Any], report: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    primary = str(assembly.get("primary_source_url", "") or "").strip()
    if primary:
        urls.append(primary)
    for citation in _list_dicts(report.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return [f"- Source: {url}" for url in urls[:3]]


def _assembled_text(question: str, assembly: dict[str, Any], report: dict[str, Any]) -> str:
    entity = _entity_label(report, question)
    conclusion = _dict(report.get("analyst_conclusion", {}))
    lines = [
        f"Market research report: {entity}",
        f"Status: {report.get('status', 'evidence_ready')}; source boundary: {assembly.get('citation_quality_status', 'sufficient')}.",
    ]
    metric_lines = _metric_lines(report)
    if metric_lines:
        lines.append("Key metrics:")
        lines.extend(metric_lines)
    section_lines = _section_lines(report)
    if section_lines:
        lines.append("Filing evidence:")
        lines.extend(section_lines)
    summary = str(conclusion.get("summary", "") or "").strip()
    recommendation = str(conclusion.get("investment_recommendation", "not_provided") or "not_provided")
    lines.append(f"Conclusion: {_compact(summary, 220) if summary else 'Evidence supports a bounded filing-grounded summary.'}")
    lines.append(f"Investment recommendation: {recommendation}.")
    source_lines = _source_lines(assembly, report)
    if source_lines:
        lines.append("Citations:")
        lines.extend(source_lines)
    return "\n".join(lines)


def _blocked_text(question: str, assembly: dict[str, Any]) -> str:
    status = str(assembly.get("status", "") or "insufficient_evidence")
    if status == "citation_mismatch":
        primary = str(assembly.get("primary_source_url", "") or "").strip()
        return (
            "The market-research report has a citation mismatch: the promoted authoritative source "
            f"{primary or '-'} is not present in the report citations. I should not treat this as final."
        )
    insufficient = _dict(assembly.get("insufficient_evidence_report", {}))
    summary = str(insufficient.get("summary", "") or "").strip()
    recommendation = str(insufficient.get("investment_recommendation", "not_provided") or "not_provided")
    missing = ", ".join(str(item) for item in list(assembly.get("missing_requirements", []) or []) if str(item)) or "authoritative filing evidence"
    return (
        f"{summary or 'Insufficient current filing evidence to finalize the market-research report.'} "
        f"Missing: {missing}. Investment recommendation: {recommendation}."
    )


def build_market_research_finalization_gate(
    *,
    question: str,
    stage197_market_research_report_assembly: dict[str, Any] | None = None,
    candidate_visible_text: str = "",
) -> dict[str, Any]:
    """Convert Stage197 report-readiness into a visible finalization boundary."""

    assembly = _dict(stage197_market_research_report_assembly)
    if not assembly:
        return {
            "schema": STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA,
            "status": "not_applicable",
            "question": _compact(question, 260),
            "final_visible_text_ready": False,
            "should_replace_visible_text": False,
            "visible_text": str(candidate_visible_text or ""),
            "canonical_stop_reason": "final_answer_ready",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }

    report = _dict(assembly.get("stage173_market_research_report", {}))
    assembly_status = str(assembly.get("status", "") or "")
    source_promotion_status = str(assembly.get("source_promotion_status", "") or "")
    if not source_promotion_status and "stage196_market_research_source_promotion" in list(assembly.get("missing_requirements", []) or []):
        return {
            "schema": STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA,
            "status": "not_applicable",
            "question": _compact(question, 260),
            "source_assembly_status": assembly_status,
            "final_visible_text_ready": False,
            "should_replace_visible_text": False,
            "visible_text": str(candidate_visible_text or ""),
            "canonical_stop_reason": "final_answer_ready",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
    ready = bool(assembly.get("final_report_ready", False))
    if assembly_status == "assembled" and ready and report:
        status = "finalized"
        visible = _assembled_text(question, assembly, report)
        final_ready = True
        stop_reason = "final_answer_ready"
    else:
        status = "blocked" if assembly_status in {"citation_mismatch", "blocked"} else "insufficient_evidence"
        visible = _blocked_text(question, assembly)
        final_ready = False
        stop_reason = str(assembly.get("canonical_stop_reason", "") or "evidence_exhausted")

    gate = {
        "schema": STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA,
        "finalization_id": "stage198_report_final:" + stable_digest(question, assembly.get("assembly_id", ""), status, limit=12),
        "status": status,
        "question": _compact(question, 260),
        "source_assembly_status": assembly_status,
        "citation_quality_status": str(assembly.get("citation_quality_status", "") or ""),
        "primary_source_url": str(assembly.get("primary_source_url", "") or ""),
        "final_visible_text_ready": final_ready,
        "should_replace_visible_text": True,
        "visible_text": visible,
        "missing_requirements": list(assembly.get("missing_requirements", []) or []),
        "canonical_stop_reason": stop_reason,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    return sanitize_public_metadata(gate)


def apply_market_research_finalization_gate(text: str, gate: dict[str, Any]) -> str:
    if bool(_dict(gate).get("should_replace_visible_text", False)):
        return str(_dict(gate).get("visible_text", "") or text or "")
    return str(text or "")
