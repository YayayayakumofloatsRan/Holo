from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE192_MARKET_RESEARCH_FEEDBACK_SCHEMA = "holo.stage192.market_research_feedback_loop.v1"
STAGE192_MARKET_RESEARCH_FEEDBACK_STEP_SCHEMA = "holo.stage192.market_research_feedback_step.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_str(value: Any) -> list[str]:
    return [str(item) for item in list(value or []) if str(item or "").strip()] if isinstance(value, list) else []


def _source_authority(pack: dict[str, Any]) -> dict[str, Any]:
    authority = _dict(pack.get("source_authority", {}))
    if authority:
        return authority
    return {"status": "missing", "required_source_family": "financial_filing", "confidence": 0.0}


def _score_report(pack: dict[str, Any], report: dict[str, Any]) -> tuple[float, list[str]]:
    unresolved: list[str] = []
    authority = _source_authority(pack)
    authority_status = str(authority.get("status", "") or "missing")
    required_family = str(authority.get("required_source_family", "") or "financial_filing")
    if authority_status != "sufficient":
        unresolved.append(f"source_authority:{required_family}")
    report_status = str(report.get("status", "") or "")
    if report_status != "evidence_ready":
        unresolved.append("report_status:evidence_ready")
    checklist = _dict(pack.get("filing_checklist", {}))
    if str(checklist.get("status", "") or "") != "complete":
        unresolved.append("filing_checklist")
    if int(report.get("metric_count", 0) or 0) <= 0:
        unresolved.append("financial_metrics")
    if int(report.get("citation_count", 0) or 0) <= 0:
        unresolved.append("citations")
    if int(report.get("unsupported_claim_count", 0) or 0) > 0:
        unresolved.append("unsupported_claims")

    authority_score = 0.32 if authority_status == "sufficient" else 0.0
    coverage_score = 0.18 * float(checklist.get("coverage_score", 0.0) or 0.0)
    metric_score = min(0.18, 0.06 * int(report.get("metric_count", 0) or 0))
    citation_score = min(0.16, 0.08 * int(report.get("citation_count", 0) or 0))
    support_score = float(report.get("evidence_support_score", 0.0) or 0.0) * 0.16
    penalty = min(0.25, 0.04 * len(unresolved))
    return round(max(0.0, min(1.0, authority_score + coverage_score + metric_score + citation_score + support_score - penalty)), 4), unresolved


def build_market_research_feedback_loop(
    *,
    question: str,
    market_research_pack: dict[str, Any] | None = None,
    market_research_report: dict[str, Any] | None = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    remaining_action_budget: int = 1,
) -> dict[str, Any]:
    """Evaluate whether a financial research report is ready or needs more evidence."""

    pack = _dict(market_research_pack)
    report = _dict(market_research_report)
    if not pack:
        for row in list(market_research_pack_ledger or []):
            if isinstance(row, dict) and isinstance(row.get("stage169_market_research_pack", {}), dict):
                pack = dict(row.get("stage169_market_research_pack", {}))
                break
    if not report:
        for row in list(market_research_report_ledger or []):
            if isinstance(row, dict) and isinstance(row.get("stage173_market_research_report", {}), dict):
                report = dict(row.get("stage173_market_research_report", {}))
                break

    score, unresolved = _score_report(pack, report)
    authority = _source_authority(pack)
    authority_status = str(authority.get("status", "") or "missing")
    required_family = str(authority.get("required_source_family", "") or "financial_filing")
    budget = max(0, int(remaining_action_budget or 0))
    can_finalize = not unresolved and score >= 0.75
    if can_finalize:
        next_action = "finalize_report"
        stop_decision = "stop"
        stop_reason = "report_ready"
    elif budget > 0 and authority_status != "sufficient":
        next_action = "market_research_pack"
        stop_decision = "continue"
        stop_reason = "source_authority_insufficient"
    elif budget > 0:
        next_action = "market_research_report"
        stop_decision = "continue"
        stop_reason = "report_insufficient"
    else:
        next_action = "report_insufficient_evidence"
        stop_decision = "stop"
        stop_reason = "evidence_exhausted"

    step = {
        "schema": STAGE192_MARKET_RESEARCH_FEEDBACK_STEP_SCHEMA,
        "feedback_id": "stage192_feedback:" + stable_digest(question, report.get("report_id", ""), stop_reason, limit=12),
        "action": "market_research_report",
        "question": _compact(question, 240),
        "report_status": str(report.get("status", "") or "missing"),
        "pack_status": str(pack.get("status", "") or "missing"),
        "authority_status": authority_status,
        "authority_required_family": required_family,
        "section_count": int(report.get("section_count", 0) or 0),
        "metric_count": int(report.get("metric_count", 0) or 0),
        "citation_count": int(report.get("citation_count", 0) or 0),
        "unsupported_claim_count": int(report.get("unsupported_claim_count", 0) or 0),
        "combined_sufficiency_score": score,
        "marginal_utility": score,
        "unresolved_items": unresolved,
        "remaining_action_budget": budget,
        "next_action": next_action,
        "stop_decision": stop_decision,
        "stop_reason": stop_reason,
        "public_summary": _compact(
            f"report={report.get('status', 'missing')}; authority={authority_status}; score={score}; next={next_action}; stop={stop_reason}",
            260,
        ),
        "created_at": utc_now(),
    }
    return {
        "schema": STAGE192_MARKET_RESEARCH_FEEDBACK_SCHEMA,
        "status": "recorded",
        "question": _compact(question, 260),
        "step_count": 1,
        "continue_count": 1 if stop_decision == "continue" else 0,
        "stop_count": 1 if stop_decision == "stop" else 0,
        "can_finalize": can_finalize,
        "next_action": next_action,
        "final_stop_reason": stop_reason,
        "best_sufficiency_score": score,
        "unresolved_items": unresolved,
        "steps": [step],
        "public_loop_summary": _compact(
            f"market report feedback: can_finalize={can_finalize}; score={score}; next={next_action}; stop={stop_reason}",
            260,
        ),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
