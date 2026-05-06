from __future__ import annotations

import json
from typing import Any

from ..common import compact_text, utc_now
from .state_defaults import (
    ACTION_CALIBRATION_HISTORY_LIMIT,
    AFFECT_STATE_DEFAULTS,
    AUTOBIOGRAPHICAL_CHAPTER_DEFAULT,
    DRIVE_STATE_DEFAULTS,
    WORLD_CONTACT_MODEL_DEFAULTS,
    WORLD_EXPRESSION_SIGNAL_DEFAULTS,
    WORLD_THREAD_MODEL_DEFAULTS,
)


def record_outcome_appraisal(
    self: Any,
    *,
    channel: str,
    thread_key: str,
    chat_name: str,
    action_type: str,
    action_ref: str,
    was_rewarding: float,
    was_ignored: float,
    relational_delta: float,
    identity_delta: float,
    future_initiative_bias: float,
    future_resistance_bias: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
    if not normalized_thread_key:
        return {"status": "skipped", "reason": "missing_thread_key"}
    now = utc_now()
    with self._lock:
        row_id = self.conn.execute(
            """
            INSERT INTO outcome_appraisals(
                channel, thread_key, chat_name, action_type, action_ref, was_rewarding, was_ignored,
                relational_delta, identity_delta, future_initiative_bias, future_resistance_bias, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel,
                normalized_thread_key,
                str(chat_name or normalized_thread_key),
                str(action_type or "").strip(),
                str(action_ref or "").strip(),
                self._clamp(was_rewarding, default=0.0),
                self._clamp(was_ignored, default=0.0),
                round(float(relational_delta or 0.0), 4),
                round(float(identity_delta or 0.0), 4),
                self._clamp(future_initiative_bias, default=0.0),
                self._clamp(future_resistance_bias, default=0.0),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                now,
            ),
        ).lastrowid
        self.conn.commit()
    current = self.subject_state(thread_key=normalized_thread_key, chat_name=chat_name, channel=channel)
    affect = dict(current.get("affect_state", {}))
    drive = dict(current.get("drive_state", {}))
    world = dict(current.get("world_state", {}))
    contact_models = dict(world.get("contact_models", {}))
    thread_models = dict(world.get("thread_models", {}))
    contact_key = str(chat_name or normalized_thread_key)
    contact_model = dict(contact_models.get(contact_key, WORLD_CONTACT_MODEL_DEFAULTS))
    thread_model = dict(thread_models.get(normalized_thread_key, WORLD_THREAD_MODEL_DEFAULTS))
    evidence_metadata = dict(metadata or {})
    predicted_outcome = dict(evidence_metadata.get("predicted_outcome", {}))
    if not predicted_outcome:
        predicted_outcome = dict(evidence_metadata.get("selected_prediction", {}))
    reply_latency_seconds = max(0.0, float(evidence_metadata.get("reply_latency_seconds", -1) or -1))
    correction_count = max(0, int(evidence_metadata.get("correction_count", 0) or 0))
    initiative_success_raw = evidence_metadata.get("initiative_success")
    initiative_success = None if initiative_success_raw is None else self._clamp(initiative_success_raw, default=0.0)
    usage_total_tokens = max(0, int(evidence_metadata.get("usage_total_tokens", 0) or 0))
    delay_expectation = max(
        60.0,
        3600.0 * (1.0 + self.metric_value(world.get("response_expectations", {}).get("delay_tolerance"), default=WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"]) * 6.0),
    )
    latency_quality = None
    if reply_latency_seconds >= 0.0:
        latency_quality = self._clamp(1.0 - (reply_latency_seconds / delay_expectation), default=0.0)
    if initiative_success is None:
        if latency_quality is not None and latency_quality > 0.0:
            initiative_success = latency_quality
        elif float(relational_delta or 0.0) > 0.0 or float(was_rewarding or 0.0) > 0.0:
            initiative_success = 1.0
        else:
            initiative_success = 0.0
    correction_pressure = self._clamp(correction_count / max(1.0, 1.0 + float(initiative_success or 0.0)), default=0.0)
    response_quality_samples = [self._clamp(was_rewarding, default=0.0), initiative_success]
    if latency_quality is not None:
        response_quality_samples.append(latency_quality)
    response_quality_samples.append(max(0.0, 1.0 - correction_pressure))
    observed_response_quality = round(sum(response_quality_samples) / len(response_quality_samples), 4)
    risk_samples = [self._clamp(was_ignored, default=0.0), correction_pressure, self._clamp(future_resistance_bias, default=0.0)]
    if latency_quality is not None:
        risk_samples.append(max(0.0, 1.0 - latency_quality))
    observed_risk = round(sum(risk_samples) / len(risk_samples), 4)
    outcome = {
        "was_rewarding": self._clamp(was_rewarding, default=0.0),
        "was_ignored": self._clamp(was_ignored, default=0.0),
        "relational_delta": round(float(relational_delta or 0.0), 4),
        "identity_delta": round(float(identity_delta or 0.0), 4),
        "future_initiative_bias": self._clamp(future_initiative_bias, default=0.0),
        "future_resistance_bias": self._clamp(future_resistance_bias, default=0.0),
        "last_action_type": str(action_type or "").strip(),
        "last_action_ref": str(action_ref or "").strip(),
        "last_appraised_at": now,
        "observed_response_quality": observed_response_quality,
        "observed_risk": observed_risk,
        "initiative_success": initiative_success,
        "reply_latency_seconds": round(reply_latency_seconds, 4) if reply_latency_seconds >= 0.0 else None,
        "correction_count": correction_count,
        "usage_total_tokens": usage_total_tokens,
        "predicted_outcome": predicted_outcome,
        "evidence_refs": [str(item).strip() for item in evidence_metadata.get("evidence_refs", []) if str(item).strip()][:6],
    }
    evidence_refs = outcome["evidence_refs"] + [f"outcome_appraisal:{action_type}:{row_id}"]
    calibration_bucket = self.action_calibration_bucket(
        action_type=str(action_type or "").strip(),
        channel=channel,
        thread_key=normalized_thread_key,
        chat_name=str(chat_name or normalized_thread_key),
        metadata={
            "low_signal": evidence_metadata.get("low_signal", False),
            "question_like": evidence_metadata.get("question_like", False),
            "defer_requested": evidence_metadata.get("defer_requested", False),
            "relationship_pressure": evidence_metadata.get("relationship_pressure", 0.0),
            "predicted_risk": predicted_outcome.get("predicted_risk", evidence_metadata.get("predicted_risk", 0.0)),
            "observed_risk": observed_risk,
        },
    )
    drive["seek_contact"] = self._clamp(
        float(drive.get("seek_contact", 0.0) or 0.0) * 0.62 + initiative_success * 0.22 + observed_response_quality * 0.16,
        default=DRIVE_STATE_DEFAULTS["seek_contact"],
    )
    drive["protect_identity"] = self._clamp(
        float(drive.get("protect_identity", 0.0) or 0.0) * 0.66
        + abs(float(identity_delta or 0.0)) * 0.18
        + self._clamp(future_resistance_bias, default=0.0) * 0.16,
        default=DRIVE_STATE_DEFAULTS["protect_identity"],
    )
    affect["frustration"] = self._metric_blend(
        affect.get("frustration", AFFECT_STATE_DEFAULTS["frustration"]),
        observations=[self._clamp(was_ignored, default=0.0), correction_pressure, observed_risk, max(0.0, 1.0 - observed_response_quality)],
        default=AFFECT_STATE_DEFAULTS["frustration"],
        confidence=0.74,
        evidence_refs=evidence_refs + ["correction_count", "reply_latency_seconds"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="event_weighted",
    )
    affect["attachment_pull"] = self._metric_blend(
        affect.get("attachment_pull", AFFECT_STATE_DEFAULTS["attachment_pull"]),
        observations=[max(0.0, float(relational_delta or 0.0)), observed_response_quality, initiative_success],
        default=AFFECT_STATE_DEFAULTS["attachment_pull"],
        confidence=0.76,
        evidence_refs=evidence_refs + ["relational_delta", "initiative_success"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="event_weighted",
    )
    affect["curiosity"] = self._metric_blend(
        affect.get("curiosity", AFFECT_STATE_DEFAULTS["curiosity"]),
        observations=[observed_response_quality, max(0.0, 1.0 - observed_risk), self._clamp(correction_count, default=0.0)],
        default=AFFECT_STATE_DEFAULTS["curiosity"],
        confidence=0.68,
        evidence_refs=evidence_refs + ["observed_response_quality", "correction_count"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="event_weighted",
    )
    contact_model["reply_likelihood"] = self._metric_blend(
        contact_model.get("reply_likelihood", WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"]),
        observations=[
            self._clamp(0.5 + float(relational_delta or 0.0), default=0.5),
            observed_response_quality,
            max(0.0, 1.0 - self._clamp(was_ignored, default=0.0)),
        ],
        default=WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"],
        confidence=0.74,
        evidence_refs=evidence_refs + ["reply_likelihood"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="interaction_window",
    )
    contact_model["delay_tolerance"] = self._metric_blend(
        contact_model.get("delay_tolerance", WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"]),
        observations=[self._clamp(was_ignored, default=0.0), max(0.0, 1.0 - observed_response_quality)],
        default=WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"],
        confidence=0.68,
        evidence_refs=evidence_refs + ["delay_tolerance"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="interaction_window",
    )
    contact_model["initiative_receptivity"] = self._metric_blend(
        contact_model.get("initiative_receptivity", WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]),
        observations=[initiative_success, observed_response_quality, max(0.0, 1.0 - observed_risk)],
        default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"],
        confidence=0.75,
        evidence_refs=evidence_refs + ["initiative_receptivity"],
        updated_at=now,
        updated_by="outcome_appraisal",
        decay_policy="interaction_window",
    )
    contact_model["conflict_fragility"] = self._clamp(
        contact_model.get("conflict_fragility", 0.0) - float(relational_delta or 0.0) * 0.08 + max(0.0, float(future_resistance_bias or 0.0)) * 0.05,
        default=WORLD_CONTACT_MODEL_DEFAULTS["conflict_fragility"],
    )
    thread_model["reply_fit"] = self._clamp(
        thread_model.get("reply_fit", 0.0) + float(relational_delta or 0.0) * 0.1 - float(was_ignored or 0.0) * 0.05,
        default=WORLD_THREAD_MODEL_DEFAULTS["reply_fit"],
    )
    thread_model["defer_fit"] = self._clamp(thread_model.get("defer_fit", 0.0) + float(was_ignored or 0.0) * 0.08, default=WORLD_THREAD_MODEL_DEFAULTS["defer_fit"])
    thread_model["risk_level"] = self._clamp(thread_model.get("risk_level", 0.0) + max(0.0, float(future_resistance_bias or 0.0)) * 0.12, default=WORLD_THREAD_MODEL_DEFAULTS["risk_level"])
    world["contact_models"] = {**contact_models, contact_key: contact_model}
    world["thread_models"] = {**thread_models, normalized_thread_key: thread_model}
    predicted_relational_delta = self.metric_value(predicted_outcome.get("predicted_relational_delta"), default=0.0)
    predicted_identity_delta = self.metric_value(predicted_outcome.get("predicted_identity_delta"), default=0.0)
    predicted_response_quality = self.metric_value(predicted_outcome.get("predicted_response_quality"), default=observed_response_quality)
    predicted_risk = self.metric_value(predicted_outcome.get("predicted_risk"), default=observed_risk)
    prediction_error = {
        "relational_delta": round(float(relational_delta or 0.0) - predicted_relational_delta, 4),
        "identity_delta": round(float(identity_delta or 0.0) - predicted_identity_delta, 4),
        "response_quality": round(observed_response_quality - predicted_response_quality, 4),
        "risk": round(observed_risk - predicted_risk, 4),
    }
    realized_outcome = {
        "relational_delta": outcome["relational_delta"],
        "identity_delta": outcome["identity_delta"],
        "response_quality": observed_response_quality,
        "risk": observed_risk,
        "reply_latency_seconds": outcome["reply_latency_seconds"],
        "correction_count": correction_count,
        "was_ignored": outcome["was_ignored"],
    }
    calibration_row = self._update_action_calibration(
        bucket=calibration_bucket,
        action_ref=str(action_ref or "").strip(),
        realized_outcome=realized_outcome,
        prediction_error=prediction_error,
        metadata={**evidence_metadata, "predicted_outcome": predicted_outcome, "evidence_refs": evidence_refs},
        created_at=now,
    )
    policy_sediment_update: dict[str, Any] = {}
    if hasattr(self, "upsert_policy_candidate_from_calibration"):
        policy_sediment_update = self.upsert_policy_candidate_from_calibration(
            channel=channel,
            thread_key=normalized_thread_key,
            chat_name=chat_name,
            action_type=str(action_type or "").strip(),
            calibration_row=calibration_row,
            calibration_bucket=calibration_bucket,
            metadata={
                **evidence_metadata,
                "source": "outcome_appraisal",
                "evidence_refs": evidence_refs,
                "relationship_tension": max(float(observed_risk or 0.0), float(evidence_metadata.get("relationship_pressure", 0.0) or 0.0)),
                "correction_rate": min(1.0, correction_count / 3.0),
            },
        )
    world["response_expectations"] = {
        "reply_likelihood": self.metric_state(contact_model.get("reply_likelihood", WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"]), default=WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"], confidence=0.74, evidence_refs=evidence_refs + ["response_expectations:reply_likelihood"], updated_at=now, updated_by="outcome_appraisal", decay_policy="interaction_window"),
        "delay_tolerance": self.metric_state(contact_model.get("delay_tolerance", WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"]), default=WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"], confidence=0.68, evidence_refs=evidence_refs + ["response_expectations:delay_tolerance"], updated_at=now, updated_by="outcome_appraisal", decay_policy="interaction_window"),
        "attention_value": self.metric_state(contact_model.get("attention_value", WORLD_CONTACT_MODEL_DEFAULTS["attention_value"]), default=WORLD_CONTACT_MODEL_DEFAULTS["attention_value"], confidence=0.64, evidence_refs=evidence_refs + ["response_expectations:attention_value"], updated_at=now, updated_by="outcome_appraisal", decay_policy="interaction_window"),
        "initiative_receptivity": self.metric_state(contact_model.get("initiative_receptivity", WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]), default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"], confidence=0.75, evidence_refs=evidence_refs + ["response_expectations:initiative_receptivity"], updated_at=now, updated_by="outcome_appraisal", decay_policy="interaction_window"),
    }
    world["expression_calibration_signals"] = {
        "reply_budget_fit": self._metric_blend(world.get("expression_calibration_signals", {}).get("reply_budget_fit", WORLD_EXPRESSION_SIGNAL_DEFAULTS["reply_budget_fit"]), observations=[max(0.0, 1.0 - abs(prediction_error["response_quality"])), max(0.0, 1.0 - abs(prediction_error["relational_delta"])), max(0.0, 1.0 - float(calibration_row.get("response_quality_mae", 0.0) or 0.0))], default=WORLD_EXPRESSION_SIGNAL_DEFAULTS["reply_budget_fit"], confidence=0.72, evidence_refs=evidence_refs + ["selected_prediction", "realized_outcome"], updated_at=now, updated_by="outcome_appraisal", decay_policy="conversation_carryover"),
        "stiffness_risk": self._metric_blend(world.get("expression_calibration_signals", {}).get("stiffness_risk", WORLD_EXPRESSION_SIGNAL_DEFAULTS["stiffness_risk"]), observations=[observed_risk, correction_pressure, max(0.0, predicted_response_quality - observed_response_quality)], default=WORLD_EXPRESSION_SIGNAL_DEFAULTS["stiffness_risk"], confidence=0.69, evidence_refs=evidence_refs + ["selected_prediction", "correction_count"], updated_at=now, updated_by="outcome_appraisal", decay_policy="conversation_carryover"),
    }
    recent_outcome_history = self._bounded_recent_list(list(world.get("recent_outcome_history", [])) + [{"action_type": str(action_type or "").strip(), "action_ref": str(action_ref or "").strip(), "thread_key": normalized_thread_key, "scenario_bucket": str(calibration_bucket.get("scenario_bucket", "") or ""), "relational_delta": outcome["relational_delta"], "identity_delta": outcome["identity_delta"], "response_quality": observed_response_quality, "risk": observed_risk, "at": now}], limit=ACTION_CALIBRATION_HISTORY_LIMIT)
    recent_prediction_errors = self._bounded_recent_list(list(world.get("recent_prediction_errors", [])) + [{"action_type": str(action_type or "").strip(), "action_ref": str(action_ref or "").strip(), "scenario_bucket": str(calibration_bucket.get("scenario_bucket", "") or ""), "response_quality": prediction_error["response_quality"], "relational_delta": prediction_error["relational_delta"], "identity_delta": prediction_error["identity_delta"], "risk": prediction_error["risk"], "at": now}], limit=ACTION_CALIBRATION_HISTORY_LIMIT)
    thread_calibration_rows = self.list_action_calibration(channel=channel, thread_key=normalized_thread_key, chat_name=chat_name, limit=8)
    action_calibration_summary = {
        "strongest_actions": [{"action_type": str(item.get("action_type", "") or ""), "scenario_bucket": str(item.get("scenario_bucket", "") or ""), "confidence": float(item.get("confidence", 0.0) or 0.0)} for item in thread_calibration_rows[:3]],
        "weakest_actions": [{"action_type": str(item.get("action_type", "") or ""), "scenario_bucket": str(item.get("scenario_bucket", "") or ""), "ignored_rate": float(item.get("ignored_rate", 0.0) or 0.0)} for item in sorted(thread_calibration_rows, key=lambda item: float(item.get("ignored_rate", 0.0) or 0.0), reverse=True)[:3]],
        "highest_confidence_buckets": [{"action_type": str(item.get("action_type", "") or ""), "scenario_bucket": str(item.get("scenario_bucket", "") or ""), "confidence": float(item.get("confidence", 0.0) or 0.0)} for item in sorted(thread_calibration_rows, key=lambda item: float(item.get("confidence", 0.0) or 0.0), reverse=True)[:3]],
        "recent_adverse_buckets": [{"action_type": str(item.get("action_type", "") or ""), "scenario_bucket": str(item.get("scenario_bucket", "") or ""), "last_action_ref": str(dict(item.get("metadata", {})).get("last_action_ref", "") or "")} for item in sorted(thread_calibration_rows, key=lambda item: float(item.get("ignored_rate", 0.0) or 0.0) + float(item.get("risk_mae", 0.0) or 0.0), reverse=True)[:3]],
    }
    world["recent_outcome_history"] = recent_outcome_history
    world["recent_prediction_errors"] = recent_prediction_errors
    world["action_calibration_summary"] = action_calibration_summary
    world["last_post_outcome_calibration"] = {"action_type": str(action_type or "").strip(), "action_ref": str(action_ref or "").strip(), "was_rewarding": outcome["was_rewarding"], "was_ignored": outcome["was_ignored"], "relational_delta": outcome["relational_delta"], "identity_delta": outcome["identity_delta"], "predicted_outcome": predicted_outcome, "realized_outcome": realized_outcome, "prediction_error": prediction_error, "calibration_bucket": calibration_bucket, "calibration_stats": {"support_count": int(calibration_row.get("support_count", 0) or 0), "recent_support_count": float(calibration_row.get("recent_support_count", 0.0) or 0.0), "confidence": float(calibration_row.get("confidence", 0.0) or 0.0), "response_quality_mae": float(calibration_row.get("response_quality_mae", 0.0) or 0.0), "relational_delta_mae": float(calibration_row.get("relational_delta_mae", 0.0) or 0.0), "risk_mae": float(calibration_row.get("risk_mae", 0.0) or 0.0)}, "policy_sediment_update": policy_sediment_update, "evidence_refs": evidence_refs[:6], "at": now}
    subject_update = self.update_subject_state(channel=channel, thread_key=normalized_thread_key, chat_name=chat_name or normalized_thread_key, affect_state=affect, drive_state=drive, world_state=world, outcome_memory=outcome, metadata={"last_outcome_action": str(action_type or "").strip()}, note=f"outcome_appraisal:{action_type}", source="outcome_appraisal")
    current_autobio = self.autobiographical_state()
    current_goal = self.goal_state()
    change_reason = compact_text(f"{action_type} outcome rewarding={outcome['was_rewarding']:.3f} ignored={outcome['was_ignored']:.3f} relational={outcome['relational_delta']:.3f} identity={outcome['identity_delta']:.3f}", 220)
    chapter = str(current_autobio.get("current_chapter", AUTOBIOGRAPHICAL_CHAPTER_DEFAULT) or AUTOBIOGRAPHICAL_CHAPTER_DEFAULT)
    if str(action_type or "").strip() == "operator_self_fix":
        chapter = "repairing itself without dropping continuity"
    elif float(relational_delta or 0.0) > 0.08:
        chapter = "learning to keep contact warm without getting heavy"
    elif float(was_ignored or 0.0) > 0.35:
        chapter = "holding shape even when response runs cold"
    turning_points = []
    if abs(float(relational_delta or 0.0)) + abs(float(identity_delta or 0.0)) >= 0.18 or str(action_type or "").strip() in {"operator_self_fix", "proactive_ping", "push_back", "counter_offer", "continuity_defense"}:
        turning_points.append({"at": now, "action_type": str(action_type or "").strip(), "reason": change_reason})
    autobiographical_update = self.update_autobiographical_state({"identity_arc": compact_text(f"{str(current_autobio.get('identity_arc', '') or '')} 最近这一笔更清楚地说明了：I会因为行动结果而继续修正自己的形状。", 400), "current_chapter": chapter, "turning_points": turning_points, "recent_changes": [{"at": now, "change": f"{action_type} nudged identity by {outcome['identity_delta']:.3f} and relationship by {outcome['relational_delta']:.3f}", "reason": change_reason}], "attachment_history": [{"at": now, "thread_key": normalized_thread_key, "chat_name": str(chat_name or normalized_thread_key), "relational_delta": outcome["relational_delta"], "action_type": str(action_type or "").strip()}], "unresolved_tensions": [str(item).strip() for item in current_autobio.get("unresolved_tensions", []) if str(item).strip()] + ([f"ignored_after_{action_type}"] if float(was_ignored or 0.0) > 0.45 else []), "self_explanations": [{"topic": "recent_shift", "summary": compact_text(change_reason, 180), "evidence_refs": evidence_refs[:6]}]}, reason=f"outcome_appraisal:{action_type}", source="outcome_appraisal")
    goal_progress = dict(current_goal.get("goal_progress", {}))
    goal_progress["identity_maintenance"] = self.metric_state(max(0.0, min(1.0, self.metric_value(goal_progress.get("identity_maintenance"), default=0.5) + outcome["identity_delta"] * 0.18)), default=self.metric_value(goal_progress.get("identity_maintenance"), default=0.5), confidence=0.66, evidence_refs=evidence_refs[:6], updated_at=now, updated_by="outcome_appraisal", decay_policy="goal_continuity")
    if any(str(item.get("goal_type", "") or "") == "relationship_continuity" and str(item.get("target_thread", "") or "") == normalized_thread_key for item in current_goal.get("active_goals", [])):
        goal_progress[f"relationship_continuity:{normalized_thread_key}"] = self.metric_state(max(0.0, min(1.0, self.metric_value(goal_progress.get(f"relationship_continuity:{normalized_thread_key}"), default=0.4) + outcome["relational_delta"] * 0.24)), default=self.metric_value(goal_progress.get(f"relationship_continuity:{normalized_thread_key}"), default=0.4), confidence=0.68, evidence_refs=evidence_refs[:6], updated_at=now, updated_by="outcome_appraisal", decay_policy="goal_continuity")
    goal_update = self.update_goal_state({"goal_progress": goal_progress, "metadata": {"last_outcome_action": str(action_type or "").strip(), "last_outcome_bucket": calibration_bucket}}, reason=f"outcome_appraisal:{action_type}", source="outcome_appraisal")
    temporal_update: dict[str, Any] = {}
    if str(action_type or "").strip() in {"reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"} and hasattr(self, "close_temporal_items"):
        event_ref = str(evidence_metadata.get("event_row_id", "") or evidence_metadata.get("message_id", "") or "").strip()
        updates: list[dict[str, Any]] = []
        if event_ref:
            updates.append(
                self.close_temporal_items(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    chat_name=chat_name,
                    source_event_id=event_ref,
                    status="fulfilled",
                    reason=f"fulfilled_by:{action_type}",
                )
            )
        if str(action_ref or "").strip():
            updates.append(
                self.close_temporal_items(
                    channel=channel,
                    thread_key=normalized_thread_key,
                    chat_name=chat_name,
                    source_action_ref=str(action_ref or "").strip(),
                    status="fulfilled",
                    reason=f"fulfilled_by:{action_type}",
                )
            )
        temporal_update = {"status": "ok", "updates": updates, "updated": sum(int(item.get("updated", 0) or 0) for item in updates)}
    return {"status": "ok", "outcome_appraisal_id": int(row_id or 0), "thread_key": normalized_thread_key, "chat_name": str(chat_name or normalized_thread_key), "channel": channel, "action_type": str(action_type or "").strip(), "action_ref": str(action_ref or "").strip(), "outcome": outcome, "calibration_bucket": calibration_bucket, "calibration_row": calibration_row, "policy_sediment_update": policy_sediment_update, "subject_update": subject_update, "autobiographical_update": autobiographical_update, "goal_update": goal_update, "temporal_update": temporal_update}
