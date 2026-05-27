from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE190_SELF_FEEDBACK_SCHEMA = "holo.stage190.self_feedback_loop.v1"
STAGE190_FEEDBACK_STEP_SCHEMA = "holo.stage190.feedback_step.v1"


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _score_page_status(status: str, score: float) -> float:
    if status == "supported":
        return max(0.72, min(1.0, float(score or 0.0)))
    if status == "weak":
        return max(0.35, min(0.68, float(score or 0.0)))
    if status in {"error", "rejected_network_disabled"}:
        return 0.0
    return max(0.0, min(0.34, float(score or 0.0)))


def _score_authority(status: str, required_family: str = "") -> float:
    if not required_family:
        return 0.65
    if status == "sufficient":
        return 1.0
    if status == "weak":
        return 0.45
    return 0.0


def evaluate_crawler_feedback_step(
    *,
    goal: str,
    query: str,
    action: str,
    page_evidence: dict[str, Any] | None = None,
    source_authority: dict[str, Any] | None = None,
    remaining_query_budget: int = 0,
    prior_best_score: float = 0.0,
) -> dict[str, Any]:
    """Evaluate one public, auditable action/observation feedback step."""

    page = _dict(page_evidence)
    authority = _dict(source_authority)
    page_status = str(page.get("status", "") or "")
    page_score = float(page.get("best_evidence_score", page.get("evidence_score", 0.0)) or 0.0)
    required_family = str(authority.get("required_source_family", "") or "")
    authority_status = str(authority.get("status", "") or ("not_required" if not required_family else "missing"))
    evidence_score = _score_page_status(page_status, page_score)
    authority_score = _score_authority(authority_status, required_family)
    combined_score = round(evidence_score * 0.62 + authority_score * 0.28 + min(0.1, max(0.0, evidence_score - prior_best_score) * 0.2), 4)
    marginal_utility = round(max(0.0, combined_score - float(prior_best_score or 0.0)), 4)
    unresolved: list[str] = []
    if page_status != "supported":
        unresolved.append("page_evidence")
    if required_family and authority_status != "sufficient":
        unresolved.append(f"source_authority:{required_family}")

    if not unresolved and combined_score >= 0.70:
        next_action = "finalize"
        stop_decision = "stop"
        stop_reason = "sufficient_evidence"
    elif remaining_query_budget > 0 and marginal_utility >= 0.0:
        next_action = "continue_search"
        stop_decision = "continue"
        stop_reason = "continue_for_missing_evidence"
    else:
        next_action = "report_insufficient_evidence"
        stop_decision = "stop"
        stop_reason = "evidence_exhausted"
    if required_family and authority_status != "sufficient" and remaining_query_budget > 0:
        next_action = "continue_search"
        stop_decision = "continue"
        stop_reason = "authority_insufficient"

    return {
        "schema": STAGE190_FEEDBACK_STEP_SCHEMA,
        "feedback_id": "stage190_feedback:" + stable_digest(goal, query, action, page_status, authority_status, limit=12),
        "goal": _compact(goal, 220),
        "action": str(action or ""),
        "query": _compact(query, 180),
        "observation_status": page_status or "missing",
        "evidence_score": round(evidence_score, 4),
        "authority_status": authority_status,
        "authority_required_family": required_family,
        "authority_score": round(authority_score, 4),
        "combined_sufficiency_score": combined_score,
        "marginal_utility": marginal_utility,
        "unresolved_items": unresolved,
        "remaining_query_budget": max(0, int(remaining_query_budget or 0)),
        "next_action": next_action,
        "stop_decision": stop_decision,
        "stop_reason": stop_reason,
        "public_summary": _compact(
            f"evidence={page_status or 'missing'}; authority={authority_status}; next={next_action}; stop={stop_reason}",
            240,
        ),
        "created_at": utc_now(),
    }


def build_self_feedback_report(
    *,
    goal: str,
    steps: list[dict[str, Any]],
    final_stop_reason: str = "",
) -> dict[str, Any]:
    rows = _list_dicts(steps)
    stop_rows = [row for row in rows if str(row.get("stop_decision", "") or "") == "stop"]
    continue_rows = [row for row in rows if str(row.get("stop_decision", "") or "") == "continue"]
    final_reason = str(final_stop_reason or (stop_rows[-1].get("stop_reason", "") if stop_rows else "") or "evidence_exhausted")
    final_score = max([float(row.get("combined_sufficiency_score", 0.0) or 0.0) for row in rows] or [0.0])
    return {
        "schema": STAGE190_SELF_FEEDBACK_SCHEMA,
        "status": "recorded",
        "goal": _compact(goal, 240),
        "step_count": len(rows),
        "continue_count": len(continue_rows),
        "stop_count": len(stop_rows),
        "final_stop_reason": final_reason,
        "best_sufficiency_score": round(final_score, 4),
        "steps": rows,
        "public_loop_summary": _compact(
            f"{len(rows)} feedback steps; continued {len(continue_rows)} times; final_stop={final_reason}; best_score={round(final_score, 4)}",
            260,
        ),
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
