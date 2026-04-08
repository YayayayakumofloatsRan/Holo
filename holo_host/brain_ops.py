from __future__ import annotations

import json
from typing import Any

from .common import compact_text
from .models import ProcessorTaskRequest

ALLOWED_SELF_REVISION_FIELDS = {
    "persona_blend",
    "stream_cadence_multiplier",
    "recall_rerank_weights",
    "relationship_reweight",
    "game_reweight",
    "initiative_thresholds",
    "prompt_composer_bias",
}
CORRECTION_HINTS = ("别总这么老成", "不要一直顺着", "独立性", "反身性", "不要一直", "别太老成")


def _parse_json_payload(text: str) -> dict[str, Any]:
    current = str(text or "").strip()
    if not current:
        return {}
    try:
        payload = json.loads(current)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def filter_self_revision_patch(patch: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, value in dict(patch or {}).items():
        if key in ALLOWED_SELF_REVISION_FIELDS:
            filtered[key] = value
    return filtered


def collect_self_revision_evidence(
    *,
    memory,
    store,
    thread_key: str,
    chat_name: str,
    channel: str,
    extra_corrections: list[str] | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    snapshot = memory.inspect_mind(
        "别总这么老成",
        context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        include_graph_trace=False,
    )
    relationship_summary = str(snapshot.get("relationship_summary", "") or "").strip()
    if relationship_summary:
        evidence.append({"kind": "relationship_summary", "text": relationship_summary})
    for line in list(snapshot.get("thread_recall_lines", []))[:3]:
        if str(line).strip():
            evidence.append({"kind": "recall_line", "text": str(line).strip()})
    if thread_key:
        thread = store.find_thread(channel=channel, thread_key=thread_key)
        if thread:
            recent = list(reversed(store.recent_thread_messages(int(thread["id"]), limit=12)))
            for row in recent:
                text = str(row.get("body_text", "") or "").strip()
                if not text:
                    continue
                direction = str(row.get("direction", "") or "")
                if any(marker in text for marker in CORRECTION_HINTS):
                    evidence.append({"kind": "user_correction", "direction": direction, "text": compact_text(text, 200)})
                elif direction == "inbound" and len(evidence) < 8:
                    evidence.append({"kind": "recent_inbound", "direction": direction, "text": compact_text(text, 160)})
    for item in extra_corrections or []:
        if str(item).strip():
            evidence.append({"kind": "explicit_correction", "text": compact_text(str(item).strip(), 160)})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:12]


def heuristic_self_observe(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    joined = "\n".join(str(item.get("text", "")) for item in evidence)
    issues: list[str] = []
    if any(marker in joined for marker in CORRECTION_HINTS):
        issues.append("overly_mature")
    if "顺着" in joined or "不要一直" in joined:
        issues.append("over_accommodating")
    if "独立" in joined or "反身" in joined:
        issues.append("insufficient_selfhood")
    return {
        "issues": issues,
        "signal_count": len(evidence),
        "summary": "Need a livelier, more independent and less overly mature balance." if issues else "No strong drift signal.",
    }


def heuristic_self_revision_plan(observe: dict[str, Any]) -> dict[str, Any]:
    issues = {str(item).strip() for item in observe.get("issues", []) if str(item).strip()}
    patch: dict[str, Any] = {}
    if "overly_mature" in issues or "over_accommodating" in issues or "insufficient_selfhood" in issues:
        patch["persona_blend"] = {
            "playfulness": 0.73,
            "slyness": 0.71,
            "pride": 0.64,
            "companionship": 0.69,
            "wisdom": 0.72,
        }
        patch["prompt_composer_bias"] = {"avoid_counselor_register": 0.82, "prefer_lively_wolfish_register": 0.78}
        patch["relationship_reweight"] = {"continuity_guard_bias": 0.88, "playful_teasing_bias": 1.14}
        patch["game_reweight"] = {"teasing_tolerance_gain": 1.1, "correction_sensitivity_gain": 1.12}
    return patch


def heuristic_self_revision_review(patch: dict[str, Any]) -> dict[str, Any]:
    filtered = filter_self_revision_patch(patch)
    return {
        "approved": bool(filtered),
        "reason": "bounded_patch_within_allowed_fields" if filtered else "empty_patch",
        "score_delta": 0.12 if filtered else 0.0,
    }


def run_self_revision(
    *,
    config,
    runner,
    memory,
    store,
    thread_key: str,
    chat_name: str,
    channel: str,
    extra_corrections: list[str] | None = None,
    apply_patch: bool = True,
) -> dict[str, Any]:
    evidence = collect_self_revision_evidence(
        memory=memory,
        store=store,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        extra_corrections=extra_corrections,
    )
    memory.graph.add_self_revision_candidate(
        evidence=evidence,
        prompt_payload={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
    )
    if len(evidence) < int(config.memory.self_revision_min_evidence):
        observe = heuristic_self_observe(evidence)
        run = memory.graph.record_self_revision_run(
            status="skipped",
            evidence=evidence,
            observe=observe,
            plan={},
            review={"approved": False, "reason": "insufficient_evidence"},
            patch={},
        )
        return {
            "status": "skipped",
            "reason": "insufficient_evidence",
            "evidence": evidence,
            "observe": observe,
            "plan": {},
            "review": {"approved": False, "reason": "insufficient_evidence"},
            "patch": {},
            "run_id": run["id"],
        }

    observe_prompt = (
        "Return JSON with keys issues, signal_count, summary. "
        "Detect drift only in bounded form.\n\n"
        f"Evidence:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )
    observe_result = runner.run_task(
        ProcessorTaskRequest(task_type="self_observe", prompt=observe_prompt, output_schema="json")
    )
    observe = _parse_json_payload(observe_result.text) or heuristic_self_observe(evidence)

    plan_prompt = (
        "Return JSON with keys patch and rationale. The patch may only contain these top-level keys: "
        f"{', '.join(sorted(ALLOWED_SELF_REVISION_FIELDS))}.\n\n"
        f"Observed drift:\n{json.dumps(observe, ensure_ascii=False, indent=2)}"
    )
    plan_result = runner.run_task(
        ProcessorTaskRequest(task_type="self_revision_plan", prompt=plan_prompt, output_schema="json")
    )
    plan = _parse_json_payload(plan_result.text)
    heuristic_patch = heuristic_self_revision_plan(observe)
    patch = filter_self_revision_patch(dict(plan.get("patch", {}))) or heuristic_patch

    review_prompt = (
        "Return JSON with keys approved, reason, score_delta. "
        "Approve only if the patch stays within the allowed fields and makes Holo less stiff while keeping continuity.\n\n"
        f"Patch:\n{json.dumps(patch, ensure_ascii=False, indent=2)}"
    )
    review_result = runner.run_task(
        ProcessorTaskRequest(task_type="self_revision_review", prompt=review_prompt, output_schema="json")
    )
    review = _parse_json_payload(review_result.text) or heuristic_self_revision_review(patch)
    approved = bool(review.get("approved")) and bool(filter_self_revision_patch(patch))
    status = "applied" if approved and apply_patch else "reviewed" if approved else "rejected"
    run = memory.graph.record_self_revision_run(
        status=status,
        evidence=evidence,
        observe=observe,
        plan=plan,
        review=review,
        patch=patch,
    )
    applied_state: dict[str, Any] | None = None
    if approved and apply_patch:
        applied_state = memory.graph.apply_self_revision_patch(
            run_id=int(run["id"]),
            patch=patch,
            note=str(review.get("reason", "")),
        )
    return {
        "status": status,
        "evidence": evidence,
        "observe": observe,
        "plan": plan,
        "review": review,
        "patch": patch,
        "run_id": run["id"],
        "applied_state": applied_state or {},
    }


def _initiative_unit(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = float(default)
    return max(0.0, min(1.0, numeric))


def _initiative_gate_mode(config) -> str:
    return str(getattr(config.autonomy, "initiative_gate_mode", "conservative") or "conservative").strip().lower()


def _initiative_soft_gate_weights(config) -> dict[str, float]:
    weights = {
        "trust": max(0.0, float(getattr(config.autonomy, "initiative_soft_trust_weight", 0.26) or 0.26)),
        "initiative_window": max(0.0, float(getattr(config.autonomy, "initiative_soft_window_weight", 0.28) or 0.28)),
        "pressure": max(0.0, float(getattr(config.autonomy, "initiative_soft_pressure_weight", 0.18) or 0.18)),
        "drive": max(0.0, float(getattr(config.autonomy, "initiative_soft_drive_weight", 0.28) or 0.28)),
    }
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def _initiative_soft_gate_score(*, config, game_state: dict[str, Any], drive_pressure: float) -> tuple[float, dict[str, float]]:
    weights = _initiative_soft_gate_weights(config)
    components = {
        "trust": _initiative_unit(game_state.get("trust_score", 0.0)),
        "initiative_window": _initiative_unit(game_state.get("initiative_window", 0.0)),
        "drive_pressure": _initiative_unit(drive_pressure),
        "pressure_penalty": _initiative_unit(game_state.get("pressure_level", 0.0)),
    }
    score = (
        components["trust"] * weights["trust"]
        + components["initiative_window"] * weights["initiative_window"]
        + components["drive_pressure"] * weights["drive"]
        + (1.0 - components["pressure_penalty"]) * weights["pressure"]
    )
    return round(score, 4), components


def _recent_negative_initiative_feedback(outcome_memory: dict[str, Any]) -> bool:
    return bool(outcome_memory.get("was_ignored")) or float(outcome_memory.get("future_initiative_bias", 0.5) or 0.5) < 0.35


def effective_initiative_cooldown_hours(
    *,
    config,
    game_state: dict[str, Any] | None,
    mode: str = "companion",
    override_applied: bool = False,
    recent_negative_feedback: bool = False,
) -> int:
    base = max(1, int(getattr(config.autonomy, "initiative_cooldown_hours", 48) or 48))
    state = dict(game_state or {})
    multiplier = 1.0
    normalized_mode = str(mode or "companion").strip().lower()
    if normalized_mode == "full_brain":
        multiplier *= 0.45
    elif normalized_mode == "companion":
        multiplier *= 0.6
    elif normalized_mode == "dream_only":
        multiplier *= 1.15
    elif normalized_mode == "silent":
        multiplier *= 1.35
    trust_score = float(state.get("trust_score", 0.0) or 0.0)
    initiative_window = float(state.get("initiative_window", 0.0) or 0.0)
    teasing_tolerance = float(state.get("teasing_tolerance", 0.0) or 0.0)
    pressure_level = float(state.get("pressure_level", 0.0) or 0.0)
    if trust_score >= 0.72:
        multiplier *= 0.7
    if initiative_window >= 0.62:
        multiplier *= 0.7
    if teasing_tolerance >= 0.58:
        multiplier *= 0.85
    if pressure_level >= 0.7:
        multiplier *= 1.3
    if pressure_level >= 0.85:
        multiplier *= 1.4
    if override_applied and not recent_negative_feedback:
        multiplier *= 0.8
    effective = int(round(base * multiplier))
    return max(2, min(base, effective))


def initiative_probe(
    *,
    config,
    policy,
    memory,
    store,
    thread_key: str,
    chat_name: str,
    channel: str,
    query: str,
    mode: str = "companion",
    override_applied: bool = False,
    recent_negative_feedback: bool = False,
    ignore_pending_job: bool = False,
) -> dict[str, Any]:
    thread = store.find_thread(channel=channel, thread_key=thread_key) if thread_key else None
    game_state = memory.graph.game_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
    relationship = memory.graph.relationship_snapshot(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=3)
    subject_state = memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
    affect_state = dict(subject_state.get("affect_state", {}))
    drive_state = dict(subject_state.get("drive_state", {}))
    value_state = dict(subject_state.get("value_state", {}))
    conflict_state = dict(subject_state.get("conflict_state", {}))
    outcome_memory = dict(subject_state.get("outcome_memory", {}))
    gate_mode = _initiative_gate_mode(config)
    effective_cooldown_hours = effective_initiative_cooldown_hours(
        config=config,
        game_state=game_state,
        mode=mode,
        override_applied=override_applied,
        recent_negative_feedback=recent_negative_feedback,
    )
    contact = None
    pending_job = False
    cooldown_ready = True
    cooldown_reason = "contact_unavailable"
    if thread:
        contact = store._fetchone("SELECT * FROM contacts WHERE id = ?", (int(thread["contact_id"]),))
        pending_job = False if ignore_pending_job else bool(store.has_pending_initiative(int(thread["id"])))
    if contact:
        cooldown_ready = store.initiative_available(int(contact["id"]), cooldown_hours=effective_cooldown_hours)
        cooldown_reason = "cooldown_ready" if cooldown_ready else "cooldown_active"
    policy_decision = policy.outbound_decision(
        incoming_text=query,
        reply_text="initiative_probe",
        recent_outbound_count=store.count_recent_outbound(int(contact["id"])) if contact else 0,
        is_existing_thread=True,
        is_proactive=True,
        channel=channel,
    )
    drive_pressure = (
        float(drive_state.get("seek_contact", 0.0) or 0.0) * 0.34
        + float(drive_state.get("seek_play", 0.0) or 0.0) * 0.16
        + float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.2
        + float(affect_state.get("attachment_pull", 0.0) or 0.0) * 0.12
        + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.08
        - float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
        - float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) * 0.06
    )
    game_ok = (
        float(game_state.get("trust_score", 0.0) or 0.0) >= 0.42
        and float(game_state.get("initiative_window", 0.0) or 0.0) >= 0.36
        and float(game_state.get("pressure_level", 0.0) or 0.0) <= 0.78
    )
    drive_ok = float(drive_pressure or 0.0) >= 0.34
    soft_gate_score, soft_gate_components = _initiative_soft_gate_score(
        config=config,
        game_state=game_state,
        drive_pressure=float(drive_pressure or 0.0),
    )
    allow_threshold = float(getattr(config.autonomy, "initiative_soft_allow_threshold", 0.62) or 0.62)
    override_floor = float(getattr(config.autonomy, "initiative_soft_override_floor", 0.48) or 0.48)
    hard_block_reasons: list[str] = []
    if not bool(config.autonomy.initiative_probe_enabled):
        hard_block_reasons.append("initiative_probe_disabled")
    if thread and not bool(thread.get("allow_proactive", 1)):
        hard_block_reasons.append("thread_proactive_disabled")
    if not contact:
        hard_block_reasons.append("contact_unavailable")
    if pending_job:
        hard_block_reasons.append("pending_initiative_job")
    if not cooldown_ready:
        hard_block_reasons.append(cooldown_reason or "cooldown_active")
    if not policy_decision.allowed:
        hard_block_reasons.append(str(policy_decision.reason or "policy_blocked"))
    if gate_mode == "conservative":
        if not game_ok:
            hard_block_reasons.append("game_state_cold")
        if not drive_ok:
            hard_block_reasons.append("drive_pressure_low")
    # Keep reason ordering stable for CLI/status aggregation.
    hard_block_reasons = list(dict.fromkeys(item for item in hard_block_reasons if item))
    allowed = False
    gate_level = "hard_block"
    override_eligible = False
    recommended_action = "block"
    if not hard_block_reasons:
        if gate_mode == "conservative":
            allowed = bool(game_ok and drive_ok)
            gate_level = "allowed" if allowed else "hard_block"
            recommended_action = "allow" if allowed else "block"
        elif soft_gate_score >= allow_threshold:
            allowed = True
            gate_level = "allowed"
            recommended_action = "allow"
        else:
            gate_level = "soft_block"
            override_eligible = (
                bool(getattr(config.autonomy, "main_brain_override_enabled", True))
                and str(mode or "").strip().lower() == "full_brain"
                and soft_gate_score >= override_floor
            )
            recommended_action = "allow_with_override" if override_eligible else "block"
    blocked_reason_code = ""
    if hard_block_reasons:
        blocked_reason_code = hard_block_reasons[0]
    elif gate_level == "soft_block":
        blocked_reason_code = "soft_gate_override_available" if override_eligible else "soft_gate_blocked"
    return {
        "allowed": allowed,
        "blocked": not allowed,
        "mode": mode,
        "gate_mode": gate_mode,
        "gate_level": gate_level,
        "hard_block_reasons": hard_block_reasons,
        "soft_gate_score": soft_gate_score,
        "soft_gate_components": soft_gate_components,
        "override_eligible": override_eligible,
        "recommended_action": recommended_action,
        "blocked_reason_code": blocked_reason_code,
        "game_state": game_state,
        "affect_state": affect_state,
        "drive_state": drive_state,
        "value_state": value_state,
        "conflict_state": conflict_state,
        "relationship_state": relationship,
        "outcome_memory": outcome_memory,
        "game_rationale": {
            "trust_score": float(game_state.get("trust_score", 0.0) or 0.0),
            "teasing_tolerance": float(game_state.get("teasing_tolerance", 0.0) or 0.0),
            "initiative_window": float(game_state.get("initiative_window", 0.0) or 0.0),
            "pressure_level": float(game_state.get("pressure_level", 0.0) or 0.0),
            "ok": game_ok if gate_mode == "conservative" else gate_level == "allowed",
        },
        "drive_rationale": {
            "pressure": round(float(drive_pressure or 0.0), 4),
            "seek_contact": float(drive_state.get("seek_contact", 0.0) or 0.0),
            "seek_continuity": float(drive_state.get("seek_continuity", 0.0) or 0.0),
            "seek_play": float(drive_state.get("seek_play", 0.0) or 0.0),
            "avoid_risk": float(drive_state.get("avoid_risk", 0.0) or 0.0),
            "ok": drive_ok if gate_mode == "conservative" else soft_gate_score >= allow_threshold,
        },
        "policy_rationale": {
            "allowed": policy_decision.allowed,
            "reason": policy_decision.reason,
            "initiative_probe_enabled": bool(config.autonomy.initiative_probe_enabled),
            "pending_initiative_job": pending_job,
        },
        "cooldown_rationale": {
            "ready": cooldown_ready,
            "reason": cooldown_reason,
            "cooldown_hours": effective_cooldown_hours,
            "base_cooldown_hours": int(config.autonomy.initiative_cooldown_hours),
            "override_applied": override_applied,
            "recent_negative_feedback": recent_negative_feedback or _recent_negative_initiative_feedback(outcome_memory),
        },
    }


def trace_resistance(
    *,
    memory,
    thread_key: str,
    chat_name: str,
    channel: str,
    query: str = "",
) -> dict[str, Any]:
    subject_state = memory.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
    return {
        "thread_key": str(subject_state.get("thread_key", thread_key)),
        "chat_name": str(subject_state.get("chat_name", chat_name)),
        "channel": channel,
        "query": str(query or ""),
        "affect_state": dict(subject_state.get("affect_state", {})),
        "drive_state": dict(subject_state.get("drive_state", {})),
        "value_state": dict(subject_state.get("value_state", {})),
        "conflict_state": dict(subject_state.get("conflict_state", {})),
        "resistance_posture": dict(subject_state.get("resistance_posture", {})),
        "outcome_memory": dict(subject_state.get("outcome_memory", {})),
    }
