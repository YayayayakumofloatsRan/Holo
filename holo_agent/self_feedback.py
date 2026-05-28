from __future__ import annotations

from typing import Any

from .schema import Decision, Observation, short_id


SELF_FEEDBACK_SCHEMA = "holo.stage230.self_feedback.v1"


def _fetch_error_fragment(observation: Observation) -> str:
    fetch = observation.data.get("fetch", {}) if isinstance(observation.data, dict) else {}
    error_type = str(fetch.get("error_type", "") or "")
    status_code = str(fetch.get("status_code", "") or "")
    parts = [part for part in (error_type, status_code, observation.summary) if part]
    return " ".join(parts) or observation.status


def evaluate_self_feedback(
    *,
    user_text: str,
    decision: Decision,
    observation: Observation,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build a public, auditable feedback report for one action result."""

    action = decision.action
    status = observation.status
    required = list(decision.required_observations or [])
    evidence_sufficient = False
    recoverable_failure = False
    recommended_next_action = "answer_direct"
    canonical_stop_reason = "continue"
    evidence_gap = ""
    marginal_utility = 0.5

    if status != "ok":
        evidence_gap = _fetch_error_fragment(observation)
        recoverable_failure = observation.tool == "web_search" and "empty" in evidence_gap.lower()
        canonical_stop_reason = "continue" if recoverable_failure else "tool_failure_report"
        recommended_next_action = "web_search" if recoverable_failure else "answer_direct"
        marginal_utility = 0.35 if recoverable_failure else 0.0
    elif observation.tool == "web_search":
        results = observation.data.get("results", []) if isinstance(observation.data, dict) else []
        if results:
            evidence_gap = "search results need opened page evidence"
            recommended_next_action = "open_page"
            canonical_stop_reason = "continue"
            marginal_utility = 0.8
        else:
            evidence_gap = "no search results"
            recoverable_failure = True
            recommended_next_action = "web_search"
            canonical_stop_reason = "continue"
            marginal_utility = 0.4
    elif observation.tool == "open_page":
        explicit_url_request = "http://" in user_text or "https://" in user_text
        extracted = observation.data.get("extracted_page", {}) if isinstance(observation.data, dict) else {}
        extraction_quality = float(extracted.get("extraction_quality", 0.0) or 0.0)
        evidence_sufficient = explicit_url_request or extraction_quality >= 0.2
        evidence_gap = "" if evidence_sufficient else "opened page extraction is weak"
        recommended_next_action = "answer_direct" if evidence_sufficient else "web_search"
        canonical_stop_reason = "final_answer_ready" if evidence_sufficient else "continue"
        marginal_utility = 0.1 if evidence_sufficient else 0.55
    else:
        evidence_sufficient = status == "ok" and not required
        evidence_gap = "" if evidence_sufficient else "action observation requires model evaluation"
        recommended_next_action = "answer_direct" if evidence_sufficient else "ask_clarification"
        canonical_stop_reason = "final_answer_ready" if evidence_sufficient else "continue"

    return {
        "schema": SELF_FEEDBACK_SCHEMA,
        "feedback_id": short_id("fb"),
        "action": action,
        "observation_id": observation.observation_id,
        "observation_tool": observation.tool,
        "observation_status": observation.status,
        "required_observations": required,
        "evidence_sufficient": evidence_sufficient,
        "recoverable_failure": recoverable_failure,
        "evidence_gap": evidence_gap,
        "recommended_next_action": recommended_next_action,
        "canonical_stop_reason": canonical_stop_reason,
        "marginal_utility": round(max(0.0, min(1.0, marginal_utility)), 4),
        "grounded_summary": observation.summary,
        "context_observation_count": len(context.get("observations", []) or []),
    }
