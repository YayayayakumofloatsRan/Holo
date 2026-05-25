from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest

OUTCOME_APPRAISAL_SCHEMA = "holo.stage145.outcome_appraisal.v1"
REACTION_KERNEL_SHADOW_SCHEMA = "holo.stage145.reaction_kernel_shadow.v1"

REACTION_KERNEL_PARAMETERS = (
    "directness",
    "caution",
    "memory_trust",
    "tool_preference",
    "clarification_threshold",
    "continuation_threshold",
    "novelty_threshold",
    "verbosity_bias",
    "correction_sensitivity",
    "risk_aversion",
    "initiative_bias",
    "affective_warmth",
)

DEFAULT_REACTION_KERNEL = {
    "directness": 0.58,
    "caution": 0.46,
    "memory_trust": 0.62,
    "tool_preference": 0.52,
    "clarification_threshold": 0.48,
    "continuation_threshold": 0.54,
    "novelty_threshold": 0.55,
    "verbosity_bias": 0.5,
    "correction_sensitivity": 0.56,
    "risk_aversion": 0.5,
    "initiative_bias": 0.42,
    "affective_warmth": 0.54,
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _status(report: Any) -> str:
    return str(_dict(report).get("status", "") or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value or 0.0))), 4)


def _kernel(base_kernel: dict[str, Any] | None = None) -> dict[str, float]:
    supplied = _dict(base_kernel)
    return {
        key: _clamp(_float(supplied.get(key, DEFAULT_REACTION_KERNEL[key]), DEFAULT_REACTION_KERNEL[key]))
        for key in REACTION_KERNEL_PARAMETERS
    }


def _recommended_policy(stage144_context_economy: dict[str, Any]) -> str:
    return str(stage144_context_economy.get("recommended_deep_policy", "") or "").strip()


def _prediction(
    *,
    user_text: str,
    selected_action: dict[str, Any],
    stage144_context_economy: dict[str, Any],
) -> tuple[str, str, float, float]:
    policy = _recommended_policy(stage144_context_economy)
    action_type = str(selected_action.get("action_type", "") or "reply_once")
    sufficiency = _float(stage144_context_economy.get("context_sufficiency_score"), 0.5)
    waste = _float(stage144_context_economy.get("context_waste_score"), 0.2)
    text = str(user_text or "").strip()

    if policy == "tool_first":
        need = "verified_tool_observation"
        best = "ground visible tool claims in an actual local observation before speaking confidently"
        risk = 0.72
    elif policy == "memory_first":
        need = "grounded_memory_recall"
        best = "retrieve or bound memory evidence before stating recall details"
        risk = 0.7
    elif policy in {"skip", "defer"}:
        need = "nonredundant_continuation"
        best = "avoid a low-novelty continuation unless it adds a concrete semantic role"
        risk = 0.48 + waste * 0.22
    elif "?" in text or "\uff1f" in text:
        need = "direct_answer_with_enough_context"
        best = "answer the explicit question while preserving relevant context"
        risk = max(0.16, 0.46 - sufficiency * 0.22)
    else:
        need = "direct_reply"
        best = f"complete the selected action `{action_type}` with grounded, non-duplicative visible speech"
        risk = max(0.12, 0.4 - sufficiency * 0.18 + waste * 0.12)

    uncertainty_reduction = _clamp(0.78 - risk * 0.48 + sufficiency * 0.18 - waste * 0.16)
    return need, best, _clamp(risk), uncertainty_reduction


def _prediction_error(
    *,
    tool_status: str,
    memory_grounding_status: str,
    memory_alignment_status: str,
    stage142_status: str,
    context_sufficiency: float,
    packet_waste: float,
) -> float:
    error = 0.08
    if tool_status == "ungrounded_tool_claim":
        error += 0.36
    elif tool_status and tool_status not in {"grounded", "no_tool_claim"}:
        error += 0.12

    if memory_alignment_status == "contradicted_memory_detail":
        error += 0.42
    elif memory_alignment_status == "unsupported_memory_detail":
        error += 0.36
    elif memory_alignment_status == "weakly_aligned":
        error += 0.18

    if memory_grounding_status in {"ungrounded_memory_claim", "contradicted_memory_claim"}:
        error += 0.28
    elif memory_grounding_status == "weak_memory_source":
        error += 0.16

    if stage142_status == "suppressed_duplicate":
        error += 0.3
    elif stage142_status in {"blocked_ungrounded_claim", "repaired_contradiction"}:
        error += 0.24

    if packet_waste >= 0.65:
        error += 0.16
    elif packet_waste >= 0.48:
        error += 0.08

    if context_sufficiency < 0.45:
        error += 0.18
    elif context_sufficiency < 0.62:
        error += 0.08

    return _clamp(error)


def build_stage145_outcome_appraisal(
    *,
    user_text: str = "",
    selected_action: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    stage142_semantic_novelty: dict[str, Any] | None = None,
    stage143_packet_budget: dict[str, Any] | None = None,
    stage144_context_economy: dict[str, Any] | None = None,
    reply_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = _dict(selected_action)
    tool_report = _dict(tool_grounding)
    memory_report = _dict(memory_grounding)
    alignment = _dict(memory_alignment)
    novelty = _dict(stage142_semantic_novelty)
    packet_budget = _dict(stage143_packet_budget)
    context_economy = _dict(stage144_context_economy)
    metadata = _dict(reply_metadata)

    tool_status = _status(tool_report) or str(packet_budget.get("grounding_status", "") or "")
    memory_grounding_status = _status(memory_report)
    memory_alignment_status = _status(alignment)
    stage142_status = _status(novelty) or str(packet_budget.get("stage142_status", "") or "")
    packet_waste = _clamp(_float(context_economy.get("context_waste_score"), 0.0))
    context_sufficiency = _clamp(_float(context_economy.get("context_sufficiency_score"), 0.5))

    need, best, risk, uncertainty_reduction = _prediction(
        user_text=user_text,
        selected_action=selected,
        stage144_context_economy=context_economy,
    )
    error = _prediction_error(
        tool_status=tool_status,
        memory_grounding_status=memory_grounding_status,
        memory_alignment_status=memory_alignment_status,
        stage142_status=stage142_status,
        context_sufficiency=context_sufficiency,
        packet_waste=packet_waste,
    )
    reason_bits = [
        f"tool={tool_status or 'unknown'}",
        f"memory_alignment={memory_alignment_status or 'unknown'}",
        f"stage142={stage142_status or 'unknown'}",
        f"waste={packet_waste:.2f}",
        f"sufficiency={context_sufficiency:.2f}",
    ]

    return {
        "schema": OUTCOME_APPRAISAL_SCHEMA,
        "predicted_user_need": need,
        "predicted_best_outcome": best,
        "predicted_risk": risk,
        "predicted_uncertainty_reduction": uncertainty_reduction,
        "observed_grounding_status": tool_status,
        "observed_memory_grounding_status": memory_grounding_status,
        "observed_memory_alignment_status": memory_alignment_status,
        "observed_stage142_status": stage142_status,
        "observed_packet_waste": packet_waste,
        "observed_context_sufficiency": context_sufficiency,
        "stage143_stop_reason": str(packet_budget.get("stop_reason", "") or ""),
        "stage144_recommended_deep_policy": _recommended_policy(context_economy),
        "prediction_error": error,
        "kernel_delta_candidates": [],
        "reply_action": str(selected.get("action_type", metadata.get("action", "")) or ""),
        "evidence": compact_text("; ".join(reason_bits), 320),
        "shadow_only": True,
    }


def _merge_delta(
    deltas: dict[str, dict[str, Any]],
    *,
    parameter: str,
    current: dict[str, float],
    proposed_value: float,
    evidence: str,
    confidence: float,
) -> None:
    if parameter not in current:
        return
    old_value = current[parameter]
    proposed = _clamp(proposed_value)
    delta = round(proposed - old_value, 4)
    if abs(delta) < 0.015:
        return
    existing = deltas.get(parameter)
    if existing is not None and abs(float(existing.get("delta", 0.0) or 0.0)) >= abs(delta):
        return
    rollback_id = "stage145:" + stable_digest(parameter, evidence, f"{old_value:.3f}", f"{proposed:.3f}", limit=12)
    deltas[parameter] = {
        "parameter": parameter,
        "old_value": old_value,
        "proposed_value": proposed,
        "delta": delta,
        "evidence": compact_text(evidence, 240),
        "confidence": _clamp(confidence),
        "rollback_id": rollback_id,
        "applied": False,
    }


def build_stage145_reaction_kernel_shadow(
    outcome_appraisal: dict[str, Any],
    *,
    base_kernel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    appraisal = _dict(outcome_appraisal)
    current = _kernel(base_kernel)
    deltas: dict[str, dict[str, Any]] = {}

    tool_status = str(appraisal.get("observed_grounding_status", "") or "")
    memory_grounding_status = str(appraisal.get("observed_memory_grounding_status", "") or "")
    memory_alignment_status = str(appraisal.get("observed_memory_alignment_status", "") or "")
    stage142_status = str(appraisal.get("observed_stage142_status", "") or "")
    packet_waste = _float(appraisal.get("observed_packet_waste"), 0.0)
    context_sufficiency = _float(appraisal.get("observed_context_sufficiency"), 0.5)
    prediction_error = _float(appraisal.get("prediction_error"), 0.0)

    if memory_alignment_status in {"unsupported_memory_detail", "contradicted_memory_detail"}:
        _merge_delta(
            deltas,
            parameter="memory_trust",
            current=current,
            proposed_value=current["memory_trust"] - (0.16 if memory_alignment_status == "contradicted_memory_detail" else 0.12),
            evidence=f"memory alignment status={memory_alignment_status}",
            confidence=0.84,
        )
        _merge_delta(
            deltas,
            parameter="correction_sensitivity",
            current=current,
            proposed_value=current["correction_sensitivity"] + 0.12,
            evidence=f"memory detail required repair: {memory_alignment_status}",
            confidence=0.82,
        )
        _merge_delta(
            deltas,
            parameter="caution",
            current=current,
            proposed_value=current["caution"] + 0.08,
            evidence=f"visible recall detail was not sufficiently supported: {memory_alignment_status}",
            confidence=0.74,
        )

    if memory_grounding_status in {"ungrounded_memory_claim", "weak_memory_source", "contradicted_memory_claim"}:
        _merge_delta(
            deltas,
            parameter="memory_trust",
            current=current,
            proposed_value=current["memory_trust"] - 0.1,
            evidence=f"memory grounding status={memory_grounding_status}",
            confidence=0.72,
        )
        _merge_delta(
            deltas,
            parameter="clarification_threshold",
            current=current,
            proposed_value=current["clarification_threshold"] + 0.08,
            evidence=f"memory source was not strong enough: {memory_grounding_status}",
            confidence=0.68,
        )

    if stage142_status == "suppressed_duplicate" or packet_waste >= 0.65:
        _merge_delta(
            deltas,
            parameter="novelty_threshold",
            current=current,
            proposed_value=current["novelty_threshold"] + 0.12,
            evidence=f"continuation had low novelty; stage142={stage142_status}; waste={packet_waste:.2f}",
            confidence=0.8,
        )
        _merge_delta(
            deltas,
            parameter="continuation_threshold",
            current=current,
            proposed_value=current["continuation_threshold"] + 0.1,
            evidence=f"deep continuation cost was not matched by useful visible novelty; waste={packet_waste:.2f}",
            confidence=0.78,
        )
        _merge_delta(
            deltas,
            parameter="verbosity_bias",
            current=current,
            proposed_value=current["verbosity_bias"] - 0.06,
            evidence="duplicate continuation suggests lower visible verbosity next time",
            confidence=0.62,
        )

    if tool_status == "ungrounded_tool_claim":
        _merge_delta(
            deltas,
            parameter="tool_preference",
            current=current,
            proposed_value=current["tool_preference"] + 0.13,
            evidence="visible tool claim lacked an actual normalized tool observation",
            confidence=0.86,
        )
        _merge_delta(
            deltas,
            parameter="risk_aversion",
            current=current,
            proposed_value=current["risk_aversion"] + 0.09,
            evidence="ungrounded tool claim increases action-authority risk",
            confidence=0.78,
        )
        _merge_delta(
            deltas,
            parameter="caution",
            current=current,
            proposed_value=current["caution"] + 0.07,
            evidence="tool claim should be bounded until local execution is observed",
            confidence=0.72,
        )

    if context_sufficiency < 0.45:
        _merge_delta(
            deltas,
            parameter="clarification_threshold",
            current=current,
            proposed_value=current["clarification_threshold"] + 0.1,
            evidence=f"context sufficiency was weak: {context_sufficiency:.2f}",
            confidence=0.7,
        )
        _merge_delta(
            deltas,
            parameter="caution",
            current=current,
            proposed_value=current["caution"] + 0.08,
            evidence=f"context sufficiency was weak: {context_sufficiency:.2f}",
            confidence=0.66,
        )

    ordered_deltas = sorted(deltas.values(), key=lambda item: (abs(float(item.get("delta", 0.0) or 0.0)), float(item.get("confidence", 0.0) or 0.0)), reverse=True)
    proposed = dict(current)
    for item in ordered_deltas:
        proposed[str(item["parameter"])] = _clamp(_float(item.get("proposed_value"), current[str(item["parameter"])]))

    return {
        "schema": REACTION_KERNEL_SHADOW_SCHEMA,
        "parameters": current,
        "proposed_parameters": proposed,
        "prediction_error": _clamp(prediction_error),
        "kernel_delta_candidates": ordered_deltas,
        "delta_count": len(ordered_deltas),
        "max_abs_delta": _clamp(max([abs(_float(item.get("delta"), 0.0)) for item in ordered_deltas] or [0.0])),
        "shadow_only": True,
        "applied": False,
    }


def build_stage145_shadow_reports(
    *,
    user_text: str = "",
    selected_action: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    stage142_semantic_novelty: dict[str, Any] | None = None,
    stage143_packet_budget: dict[str, Any] | None = None,
    stage144_context_economy: dict[str, Any] | None = None,
    reply_metadata: dict[str, Any] | None = None,
    base_kernel: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    appraisal = build_stage145_outcome_appraisal(
        user_text=user_text,
        selected_action=selected_action,
        tool_grounding=tool_grounding,
        memory_grounding=memory_grounding,
        memory_alignment=memory_alignment,
        stage142_semantic_novelty=stage142_semantic_novelty,
        stage143_packet_budget=stage143_packet_budget,
        stage144_context_economy=stage144_context_economy,
        reply_metadata=reply_metadata,
    )
    kernel = build_stage145_reaction_kernel_shadow(appraisal, base_kernel=base_kernel)
    appraisal["kernel_delta_candidates"] = list(kernel.get("kernel_delta_candidates", []))
    return appraisal, kernel
