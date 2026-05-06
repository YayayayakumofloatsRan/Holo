from __future__ import annotations

from typing import Any

from ..common import compact_text


def apply_simulation_overlay(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    simulation_by_action: dict[str, dict[str, Any]],
    world_thread: dict[str, Any],
) -> list[dict[str, Any]]:
    updated_market: list[dict[str, Any]] = []
    for candidate in action_market:
        annotated = dict(candidate)
        action_type = str(annotated.get("action_type", "") or "")
        simulation = dict(simulation_by_action.get(action_type, {}))
        rerank_delta = float(simulation.get("recommended_bias", 0.0) or 0.0)
        annotated["world_rationale"] = compact_text(
            f"reply_fit={float(world_thread.get('reply_fit', 0.0) or 0.0):.3f} risk={float(world_thread.get('risk_level', 0.0) or 0.0):.3f} opportunity={float(world_thread.get('opportunity_level', 0.0) or 0.0):.3f}",
            160,
        )
        annotated["simulation_rationale"] = str(simulation.get("simulation_rationale", "") or "")
        annotated["predicted_outcome"] = simulation
        annotated["rerank_delta"] = round(rerank_delta, 4)
        annotated["empirical_overlay_delta"] = round(float(simulation.get("empirical_overlay_delta", 0.0) or 0.0), 4)
        annotated["empirical_calibration"] = dict(simulation.get("empirical_calibration", {}))
        annotated["calibration_bucket"] = dict(simulation.get("calibration_bucket", {}))
        annotated["calibration_confidence"] = round(float(simulation.get("calibration_confidence", 0.0) or 0.0), 4)
        annotated["score"] = round(float(annotated.get("score", 0.0) or 0.0) + rerank_delta, 4)
        updated_market.append(annotated)
    return sorted(updated_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)


def apply_policy_sedimentation_overlay(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    context: dict[str, Any],
    world_state: dict[str, Any],
) -> list[dict[str, Any]]:
    if not hasattr(self, "graph") or not hasattr(self.graph, "promoted_policy_overlays"):
        return action_market
    channel = str(context.get("channel", "wechat") or "wechat")
    thread_key = str(context.get("thread_key", "") or "")
    chat_name = str(context.get("chat_name", "") or thread_key)
    stage19 = dict(context.get("stage19_attention_frontier", {})) if isinstance(context.get("stage19_attention_frontier", {}), dict) else {}
    thread_model = dict(world_state.get("thread_models", {})).get(thread_key, {}) if isinstance(world_state.get("thread_models", {}), dict) else {}
    updated_market: list[dict[str, Any]] = []
    for candidate in action_market:
        annotated = dict(candidate)
        action_type = str(annotated.get("action_type", "") or "")
        predicted = dict(annotated.get("predicted_outcome", {})) if isinstance(annotated.get("predicted_outcome", {}), dict) else {}
        calibration_bucket = dict(annotated.get("calibration_bucket", {})) if isinstance(annotated.get("calibration_bucket", {}), dict) else {}
        scenario = self.graph.policy_scenario_bucket(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            calibration_bucket=calibration_bucket,
            candidate={**annotated, "predicted_outcome": predicted},
            metadata={
                "stage19": stage19,
                "relationship_tension": float(thread_model.get("risk_level", predicted.get("predicted_risk", 0.0)) or 0.0),
                "low_signal": "low_signal" in str(calibration_bucket.get("scenario_bucket", "")),
            },
        )
        scenario_bucket = str(scenario.get("scenario_bucket", "") or "")
        policies = self.graph.promoted_policy_overlays(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            scenario_bucket=scenario_bucket,
            limit=3,
        )
        raw_delta = sum(float(item.get("action_preference_shift", 0.0) or 0.0) for item in policies)
        delta = round(max(-0.18, min(0.18, raw_delta)), 4)
        annotated["policy_scenario_bucket"] = scenario_bucket
        annotated["policy_sedimentation_delta"] = delta
        annotated["policy_sedimentation"] = {
            "applied": bool(policies and abs(delta) > 0.0),
            "available_count": len(policies),
            "policy_ids": [str(item.get("policy_id", "") or "") for item in policies if str(item.get("policy_id", "") or "")],
            "rollback_handles": [str(item.get("rollback_handle", "") or "") for item in policies if str(item.get("rollback_handle", "") or "")],
            "scenario_bucket": scenario_bucket,
            "scenario_features": dict(scenario.get("scenario_features", {})),
            "hard_gate_preserved": True,
            "negotiated_will_mode": "active_soft",
        }
        if policies:
            annotated["score"] = round(float(annotated.get("score", 0.0) or 0.0) + delta, 4)
        updated_market.append(annotated)
    return sorted(updated_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)


def apply_scene_state_overlay(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    active_state = dict(context.get("active_thread_state", {})) if isinstance(context.get("active_thread_state", {}), dict) else {}
    scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
    predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
    shared_frame = str(scene.get("shared_frame", "") or "").strip()
    response_sketch = str(scene.get("response_sketch", "") or "").strip()
    topic_stack = [str(item).strip() for item in scene.get("topic_stack", []) if str(item).strip()]
    latent_questions = [str(item).strip() for item in scene.get("latent_questions", []) if str(item).strip()]
    predicted_branches = [str(item).strip() for item in scene.get("predicted_branches", []) if str(item).strip()]
    trajectory = str(scene.get("relationship_trajectory", "") or "").strip()
    try:
        scene_confidence = float(scene.get("scene_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        scene_confidence = 0.0
    if not (shared_frame or topic_stack or latent_questions or predicted_branches):
        return [
            {
                **dict(candidate),
                "scene_delta": 0.0,
                "scene_rationale": "",
            }
            for candidate in action_market
        ]
    recall_reason = str(context.get("recall_escalation_reason", "") or "").strip()
    hard_block = recall_reason in {"explicit_memory_query", "factual_lookup_need"} or bool(context.get("attachments", []))
    updated_market: list[dict[str, Any]] = []
    for candidate in action_market:
        annotated = dict(candidate)
        action_type = str(annotated.get("action_type", "") or "")
        delta = 0.0
        rationale_parts: list[str] = []
        if not hard_block:
            if action_type == "reply_once" and shared_frame and response_sketch:
                delta += 0.06 + min(0.03, scene_confidence * 0.04)
                rationale_parts.append("scene says a compact continuation is available")
            if action_type == "reply_multi" and (len(predicted_branches) >= 2 or len(topic_stack) >= 2):
                delta += 0.04 + min(0.03, len(predicted_branches) * 0.01)
                rationale_parts.append("scene shows real unfolding pressure")
            if action_type == "defer_reply" and latent_questions and scene_confidence < 0.58:
                delta += 0.05
                rationale_parts.append("scene still has unresolved branches with low confidence")
            if action_type == "silence" and latent_questions and trajectory in {"supportive_continuation", "light_continuation", "ordinary_continuation"}:
                delta -= 0.06
                rationale_parts.append("scene still carries unanswered continuity pressure")
        delta = round(max(-0.12, min(0.12, delta)), 4)
        annotated["scene_delta"] = delta
        annotated["scene_rationale"] = compact_text(" | ".join(rationale_parts), 180) if rationale_parts else ""
        annotated["score"] = round(float(annotated.get("score", 0.0) or 0.0) + delta, 4)
        updated_market.append(annotated)
    return sorted(updated_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)


def apply_situational_field_overlay(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    field = dict(context.get("stage28_situational_field", {})) if isinstance(context.get("stage28_situational_field", {}), dict) else {}
    if not field and isinstance(context.get("situational_field", {}), dict):
        field = dict(context.get("situational_field", {}))
    if not field:
        return [
            {
                **dict(candidate),
                "stage28_delta": 0.0,
                "stage28_rationale": "",
                "stage28_grounding_order": [],
            }
            for candidate in action_market
        ]

    open_questions = [str(item).strip() for item in field.get("open_questions", []) if str(item).strip()]
    modalities = {str(item).strip() for item in field.get("modalities", []) if str(item).strip()}
    grounding_order = [str(item).strip() for item in field.get("grounding_order", []) if str(item).strip()]
    inquiry_style = str(field.get("inquiry_style", "") or "").strip()
    history_reliance = str(field.get("history_reliance", "") or "").strip()
    recall_reason = str(context.get("recall_escalation_reason", "") or "").strip()
    hard_block = bool(field.get("hard_gate_active", False)) or recall_reason in {
        "explicit_memory_query",
        "factual_lookup_need",
        "search_request",
        "visual_request",
    }

    updated_market: list[dict[str, Any]] = []
    for candidate in action_market:
        annotated = dict(candidate)
        action_type = str(annotated.get("action_type", "") or "")
        delta = 0.0
        rationale_parts: list[str] = []
        if not hard_block:
            if action_type == "reply_once" and open_questions:
                delta += 0.05
                rationale_parts.append("grounded_inquiry_available")
                if inquiry_style == "visual_uncertainty" or "visual" in modalities:
                    delta += 0.04
                    rationale_parts.append("visual_uncertainty")
            elif action_type == "reply_once" and inquiry_style == "visual_uncertainty":
                delta += 0.04
                rationale_parts.append("visual_uncertainty")
            if action_type == "silence" and open_questions:
                delta -= 0.06
                rationale_parts.append("open_question_should_not_disappear")
            if action_type == "reply_multi" and inquiry_style == "visual_uncertainty":
                delta -= 0.03
                rationale_parts.append("ask_compactly_before_expanding")
            if action_type == "history_refresh" and history_reliance == "low":
                delta -= 0.04
                rationale_parts.append("bounded_field_before_reread_history")
            if action_type == "visual_recall" and "visual" in modalities and inquiry_style == "visual_uncertainty":
                delta += 0.04
                rationale_parts.append("visual_state_is_relevant")
        elif action_type == "reply_once" and inquiry_style == "visual_uncertainty":
            rationale_parts.append("visual_uncertainty_hard_gate_preserved")
        delta = round(max(-0.14, min(0.14, delta)), 4)
        annotated["stage28_delta"] = delta
        annotated["stage28_rationale"] = compact_text(" | ".join(rationale_parts), 180) if rationale_parts else ""
        annotated["stage28_grounding_order"] = grounding_order[:5]
        annotated["score"] = round(float(annotated.get("score", 0.0) or 0.0) + delta, 4)
        updated_market.append(annotated)
    return sorted(updated_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
