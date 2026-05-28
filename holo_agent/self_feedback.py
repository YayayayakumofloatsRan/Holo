from __future__ import annotations

from typing import Any

from .schema import Decision, Observation, short_id


SELF_FEEDBACK_SCHEMA = "holo.stage230.self_feedback.v1"
MODEL_SELF_FEEDBACK_SCHEMA = "holo.stage232.model_self_feedback.v1"


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


def _bounded_float(value: Any, default: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return default


def _normalize_model_feedback(raw: Any, host_feedback: dict[str, Any]) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "evidence_sufficient": bool(data.get("evidence_sufficient", host_feedback.get("evidence_sufficient", False))),
        "recoverable_failure": bool(data.get("recoverable_failure", host_feedback.get("recoverable_failure", False))),
        "evidence_gap": str(data.get("evidence_gap", host_feedback.get("evidence_gap", "")) or ""),
        "recommended_next_action": str(data.get("recommended_next_action", host_feedback.get("recommended_next_action", "answer_direct")) or "answer_direct"),
        "canonical_stop_reason": str(data.get("canonical_stop_reason", host_feedback.get("canonical_stop_reason", "continue")) or "continue"),
        "marginal_utility": _bounded_float(data.get("marginal_utility", host_feedback.get("marginal_utility", 0.5)), host_feedback.get("marginal_utility", 0.5)),
        "reason": str(data.get("reason", "") or ""),
    }


def _merge_model_feedback(
    *,
    host_feedback: dict[str, Any],
    model_feedback: dict[str, Any],
    observation: Observation,
) -> dict[str, Any]:
    guardrail_flags: list[str] = []
    merged = dict(host_feedback)
    merged.update(
        {
            "schema": MODEL_SELF_FEEDBACK_SCHEMA,
            "evaluator": "model",
            "model_feedback": model_feedback,
            "host_feedback": host_feedback,
            "evidence_sufficient": model_feedback["evidence_sufficient"],
            "recoverable_failure": model_feedback["recoverable_failure"],
            "evidence_gap": model_feedback["evidence_gap"],
            "recommended_next_action": model_feedback["recommended_next_action"],
            "canonical_stop_reason": model_feedback["canonical_stop_reason"],
            "marginal_utility": model_feedback["marginal_utility"],
        }
    )
    if observation.status != "ok" and merged["evidence_sufficient"]:
        guardrail_flags.extend(["host_guardrail", "failed_observation_not_sufficient"])
        merged["evidence_sufficient"] = False
        merged["recoverable_failure"] = host_feedback.get("recoverable_failure", False)
        merged["evidence_gap"] = host_feedback.get("evidence_gap", "") or "tool failed"
        merged["recommended_next_action"] = host_feedback.get("recommended_next_action", "answer_direct")
        merged["canonical_stop_reason"] = host_feedback.get("canonical_stop_reason", "tool_failure_report")
    if observation.tool == "web_search" and observation.status == "ok" and merged["canonical_stop_reason"] == "final_answer_ready":
        guardrail_flags.extend(["host_guardrail", "search_result_needs_page_evidence"])
        merged["evidence_sufficient"] = False
        merged["evidence_gap"] = host_feedback.get("evidence_gap", "") or "search results need opened page evidence"
        merged["recommended_next_action"] = host_feedback.get("recommended_next_action", "open_page")
        merged["canonical_stop_reason"] = "continue"
    merged["evaluator"] = "model_guarded" if guardrail_flags else "model"
    merged["guardrail_flags"] = guardrail_flags
    return merged


def evaluate_self_feedback_with_model(
    *,
    model: Any,
    user_text: str,
    decision: Decision,
    observation: Observation,
    context: dict[str, Any],
) -> dict[str, Any]:
    host_feedback = evaluate_self_feedback(
        user_text=user_text,
        decision=decision,
        observation=observation,
        context=context,
    )
    evaluator = getattr(model, "evaluate_action_feedback", None)
    if not callable(evaluator):
        report = dict(host_feedback)
        report["schema"] = MODEL_SELF_FEEDBACK_SCHEMA
        report["evaluator"] = "host"
        report["host_feedback"] = host_feedback
        report["model_feedback"] = {}
        report["guardrail_flags"] = []
        return report
    try:
        raw_feedback = evaluator(
            user_text=user_text,
            decision=decision.to_dict(),
            observation=observation.to_dict(),
            context=context,
            host_feedback=host_feedback,
        )
    except Exception as exc:  # noqa: BLE001
        report = dict(host_feedback)
        report["schema"] = MODEL_SELF_FEEDBACK_SCHEMA
        report["evaluator"] = "host_after_model_error"
        report["host_feedback"] = host_feedback
        report["model_feedback"] = {"error": str(exc), "error_type": exc.__class__.__name__}
        report["guardrail_flags"] = ["model_feedback_error"]
        return report
    return _merge_model_feedback(
        host_feedback=host_feedback,
        model_feedback=_normalize_model_feedback(raw_feedback, host_feedback),
        observation=observation,
    )
