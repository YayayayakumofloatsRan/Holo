from __future__ import annotations

from typing import Any

from ..common import compact_text
from ..mind_graph import MindGraph


def simulate_action_candidate(
    self: Any,
    *,
    action: dict[str, Any],
    query: str,
    intent_state: dict[str, Any],
    relationship_state: dict[str, Any],
    game_state: dict[str, Any],
    affect_state: dict[str, Any],
    drive_state: dict[str, Any],
    value_state: dict[str, Any],
    conflict_state: dict[str, Any],
    world_state: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(action.get("action_type", "") or "")
    channel = str(context.get("channel", "wechat") or "wechat")
    thread_key = str(context.get("thread_key", "") or "")
    chat_name = str(context.get("chat_name", "") or thread_key)
    signal = self._query_signal(query)
    contact_model = self._contact_world_model(world_state, chat_name=chat_name, thread_key=thread_key)
    thread_model = self._thread_world_model(world_state, thread_key=thread_key)
    reply_likelihood = self._clamp(contact_model.get("reply_likelihood", 0.56), default=0.56)
    delay_tolerance = self._clamp(contact_model.get("delay_tolerance", 0.44), default=0.44)
    initiative_receptivity = self._clamp(MindGraph.metric_value(contact_model.get("initiative_receptivity", 0.46), default=0.46), default=0.46)
    conflict_fragility = self._clamp(contact_model.get("conflict_fragility", 0.34), default=0.34)
    continuity_sensitivity = self._clamp(contact_model.get("continuity_sensitivity", 0.58), default=0.58)
    risk_level = self._clamp(thread_model.get("risk_level", 0.22), default=0.22)
    opportunity_level = self._clamp(thread_model.get("opportunity_level", 0.42), default=0.42)
    unfinished_pull = self._clamp(thread_model.get("unfinished_pull", 0.34), default=0.34)
    reply_pull = float(intent_state.get("reply_pull", 0.0) or 0.0)
    resistance_pull = float(intent_state.get("resistance_pull", 0.0) or 0.0)
    continuity_pull = float(intent_state.get("continuity_pull", 0.0) or 0.0)
    internal_pressure = float(intent_state.get("internal_pressure", 0.0) or 0.0)

    predicted_relational_delta = 0.0
    predicted_identity_delta = 0.0
    predicted_response_quality = 0.0
    predicted_risk = 0.0
    predicted_regret = 0.0
    confidence = 0.58
    recommended_bias = 0.0
    rationale = ""

    if action_type == "silence":
        predicted_relational_delta = -0.12 if signal["question_like"] else -0.02 + delay_tolerance * 0.05
        predicted_identity_delta = 0.05 + float(value_state.get("stability_priority", 0.0) or 0.0) * 0.04
        predicted_response_quality = 0.08 if signal["low_signal"] else -0.08
        predicted_risk = max(0.0, 0.12 + continuity_sensitivity * 0.08 - delay_tolerance * 0.06)
        predicted_regret = max(0.0, reply_pull * 0.12 + continuity_pull * 0.08 - delay_tolerance * 0.04)
        recommended_bias = -predicted_risk * 0.25 + (0.12 if signal["low_signal"] else -0.04)
        rationale = "silence is safer only when the turn is low-signal and the social cost stays low"
    elif action_type == "defer_reply":
        predicted_relational_delta = -0.04 + delay_tolerance * 0.1
        predicted_identity_delta = 0.08 + resistance_pull * 0.08
        predicted_response_quality = 0.18 + delay_tolerance * 0.12
        predicted_risk = max(0.0, 0.08 + continuity_sensitivity * 0.04)
        predicted_regret = max(0.0, reply_pull * 0.08 - delay_tolerance * 0.05)
        recommended_bias = 0.08 + delay_tolerance * 0.1 - continuity_sensitivity * 0.04
        rationale = "defer helps when delay is socially tolerable and the subject wants a cleaner later reply"
    elif action_type == "reply_once":
        predicted_relational_delta = 0.12 + reply_likelihood * 0.16 + opportunity_level * 0.08
        predicted_identity_delta = 0.05 + float(value_state.get("identity_priority", 0.0) or 0.0) * 0.04
        predicted_response_quality = 0.28 + reply_likelihood * 0.18
        predicted_risk = max(0.0, risk_level * 0.3 + conflict_fragility * 0.1)
        predicted_regret = max(0.0, continuity_pull * 0.06 - predicted_relational_delta * 0.08)
        recommended_bias = 0.12 + predicted_relational_delta * 0.2 - predicted_risk * 0.14
        rationale = "a short reply is the default social move when contact matters but pressure stays low"
    elif action_type == "reply_multi":
        predicted_relational_delta = 0.14 + reply_likelihood * 0.18 + unfinished_pull * 0.08
        predicted_identity_delta = 0.04 + float(value_state.get("play_priority", 0.0) or 0.0) * 0.04
        predicted_response_quality = 0.22 + reply_likelihood * 0.12 + float(intent_state.get("expansion_pressure", 0.0) or 0.0) * 0.12
        predicted_risk = max(0.0, risk_level * 0.34 + conflict_fragility * 0.16 + (0.14 if signal["low_signal"] else 0.0))
        predicted_regret = max(0.0, predicted_risk * 0.5 + (0.14 if signal["low_signal"] else 0.0))
        recommended_bias = predicted_relational_delta * 0.18 - predicted_risk * 0.28 - predicted_regret * 0.22
        rationale = "longer unfolding only pays when the relationship need clearly outweighs the social risk"
    elif action_type == "external_lookup":
        predicted_relational_delta = 0.02
        predicted_identity_delta = 0.08 + float(value_state.get("repair_priority", 0.0) or 0.0) * 0.02
        predicted_response_quality = 0.26 + float(intent_state.get("factual_lookup", 0.0) or 0.0) * 0.18
        predicted_risk = max(0.0, 0.06 + continuity_sensitivity * 0.02)
        predicted_regret = max(0.0, 0.03 if signal["factual_lookup"] else 0.14)
        recommended_bias = (0.18 if signal["factual_lookup"] else -0.08) + predicted_response_quality * 0.08
        rationale = "looking outward helps only when factual uncertainty is real enough to justify the delay"
    elif action_type == "history_refresh":
        predicted_relational_delta = 0.06 + continuity_sensitivity * 0.12 + unfinished_pull * 0.08
        predicted_identity_delta = 0.04 + float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.04
        predicted_response_quality = 0.22 + continuity_pull * 0.16
        predicted_risk = max(0.0, 0.04 + risk_level * 0.12)
        predicted_regret = max(0.0, 0.04 if intent_state.get("tier", "fast") in {"recall", "deep_recall"} else 0.16)
        recommended_bias = 0.14 + continuity_pull * 0.12 - predicted_risk * 0.08
        rationale = "refreshing local memory helps when continuity and old anchors matter more than immediate speech"
    elif action_type == "proactive_ping":
        predicted_relational_delta = 0.08 + initiative_receptivity * 0.14
        predicted_identity_delta = 0.04 + internal_pressure * 0.06
        predicted_response_quality = 0.18 + initiative_receptivity * 0.12
        predicted_risk = max(0.0, risk_level * 0.24 + (1.0 - initiative_receptivity) * 0.12)
        predicted_regret = max(0.0, predicted_risk * 0.42)
        recommended_bias = predicted_relational_delta * 0.16 - predicted_risk * 0.18
        rationale = "a ping is worth it only when the social window feels genuinely open"
    elif action_type in {"push_back", "counter_offer", "continuity_defense"}:
        predicted_relational_delta = -0.04 + continuity_sensitivity * 0.06 + float(value_state.get("identity_priority", 0.0) or 0.0) * 0.05
        predicted_identity_delta = 0.1 + resistance_pull * 0.08
        predicted_response_quality = 0.14 + float(conflict_state.get("resistance_vs_harmony", 0.0) or 0.0) * 0.12
        predicted_risk = max(0.0, conflict_fragility * 0.26 + risk_level * 0.18)
        predicted_regret = max(0.0, continuity_pull * 0.06 - predicted_identity_delta * 0.05)
        recommended_bias = predicted_identity_delta * 0.14 - predicted_risk * 0.16
        rationale = "soft resistance helps when identity protection matters and the relationship can carry a little friction"
    else:
        predicted_response_quality = 0.12
        predicted_risk = risk_level * 0.2
        predicted_regret = 0.08
        confidence = 0.42
        rationale = "fallback simulation for auxiliary action"

    predicted_outcome = {
        "predicted_relational_delta": round(predicted_relational_delta, 4),
        "predicted_identity_delta": round(predicted_identity_delta, 4),
        "predicted_response_quality": round(predicted_response_quality, 4),
        "predicted_risk": round(predicted_risk, 4),
        "predicted_regret": round(predicted_regret, 4),
    }
    empirical_calibration, calibration_bucket, empirical_overlay_delta = self._empirical_action_overlay(
        action_type=action_type,
        channel=channel,
        thread_key=thread_key,
        chat_name=chat_name,
        signal=signal,
        predicted_outcome=predicted_outcome,
    )
    recommended_bias += empirical_overlay_delta

    return {
        "action_type": action_type,
        **predicted_outcome,
        "confidence": round(confidence, 4),
        "recommended_bias": round(recommended_bias, 4),
        "empirical_overlay_delta": round(empirical_overlay_delta, 4),
        "empirical_calibration": empirical_calibration,
        "calibration_bucket": calibration_bucket,
        "calibration_confidence": round(float(empirical_calibration.get("confidence", 0.0) or 0.0), 4),
        "simulation_rationale": compact_text(rationale, 220),
    }
