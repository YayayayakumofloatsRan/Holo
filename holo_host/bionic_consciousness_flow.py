from __future__ import annotations

from typing import Any

from .common import compact_text


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any, limit: int = 180) -> str:
    return compact_text(str(value or "").strip(), limit)


def _metric(value: Any, default: float = 0.0) -> float:
    target = value.get("value", default) if isinstance(value, dict) else value
    try:
        return max(0.0, min(1.0, float(target or default)))
    except (TypeError, ValueError):
        return default


def _unique(values: list[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _active_goal_types(goal_state: dict[str, Any]) -> list[str]:
    goals = []
    for item in _list(goal_state.get("active_goals")):
        goal = _dict(item)
        text = _text(goal.get("goal_type") or goal.get("goal_id"), 80)
        if text:
            goals.append(text)
    return _unique(goals, limit=4)


def _schedule(packet: dict[str, Any]) -> dict[str, Any]:
    return _dict(packet.get("bionic_memory_schedule"))


def _lifecycle(packet: dict[str, Any]) -> dict[str, Any]:
    return _dict(packet.get("bionic_memory_lifecycle"))


def _affective_tone(packet: dict[str, Any]) -> str:
    affect = _dict(packet.get("affect_state"))
    drive = _dict(packet.get("drive_state"))
    candidates = [
        ("curiosity", _metric(affect.get("curiosity"), 0.0)),
        ("continuity_anxiety", _metric(affect.get("continuity_anxiety"), 0.0)),
        ("seek_continuity", _metric(drive.get("seek_continuity"), 0.0)),
        ("approach", _metric(drive.get("approach"), 0.0)),
    ]
    active = [f"{name}:{round(value, 2)}" for name, value in candidates if value >= 0.35]
    return ", ".join(active[:4]) if active else "baseline"


def _memory_reactivation(packet: dict[str, Any]) -> str:
    recall = _dict(packet.get("recall_reconstruction"))
    summary = _text(recall.get("summary"), 160)
    if summary:
        return summary
    schedule = _dict(packet.get("bionic_memory_schedule"))
    hippocampal = _dict(schedule.get("hippocampal_index"))
    lines = [_text(line, 140) for line in _list(hippocampal.get("dynamic_lines")) if _text(line, 140)]
    if lines:
        return lines[0]
    stream = _dict(packet.get("consciousness_stream"))
    return _text(stream.get("thread_summary"), 160)


def _goal_pressure(packet: dict[str, Any]) -> str:
    goals = _active_goal_types(_dict(packet.get("goal_state")))
    selected = _dict(packet.get("selected_action"))
    action = _text(selected.get("action_type"), 80)
    why = _text(selected.get("why_now"), 120)
    parts = []
    if goals:
        parts.append(f"goals={','.join(goals)}")
    if action:
        parts.append(f"selected_action={action}")
    if why:
        parts.append(f"why_now={why}")
    return "; ".join(parts) if parts else "reply_goal=answer_current_edge"


def _legacy_stream_lines(packet: dict[str, Any]) -> list[str]:
    stream = _dict(packet.get("consciousness_stream"))
    lines = [_text(stream.get("thread_summary"), 160)]
    lines.extend(_text(line, 140) for line in _list(stream.get("lines"))[:3])
    return _unique(lines, limit=4)


def _has_correction_reactivation(packet: dict[str, Any], *, memory_line: str) -> bool:
    schedule = _schedule(packet)
    salience = _dict(schedule.get("salience_gate"))
    hippocampal = _dict(schedule.get("hippocampal_index"))
    sources = {str(item) for item in _list(salience.get("sources"))}
    if "correction_reactivation" in sources:
        return True
    if "correction_reactivation_marker=" in str(memory_line or ""):
        return True
    for line in _list(hippocampal.get("dynamic_lines")):
        if "correction_reactivation_marker=" in str(line or ""):
            return True
    return False


def _global_workspace_ignition(
    packet: dict[str, Any],
    *,
    memory_line: str,
    response_intention: str,
    uncertainty: float,
) -> dict[str, Any]:
    schedule = _schedule(packet)
    lifecycle = _lifecycle(packet)
    salience = _metric(_dict(schedule.get("salience_gate")).get("score"), 0.0)
    priority = _metric(_dict(lifecycle.get("consolidation_intent")).get("priority"), 0.0)
    recall_budget = max(0.0, float(_dict(schedule.get("salience_gate")).get("recall_budget", 0) or 0.0))
    recall_norm = max(0.0, min(1.0, recall_budget / 6.0))
    correction_active = _has_correction_reactivation(packet, memory_line=memory_line)
    uncertainty_gate = max(0.0, min(1.0, 1.0 - uncertainty * 0.45))
    goal_alignment = 1.0 if response_intention == "reply_once" else 0.76 if response_intention else 0.58
    sources: list[str] = []
    if salience >= 0.35:
        sources.append("salience_gate")
    if priority >= 0.35:
        sources.append("consolidation_priority")
    if recall_norm >= 0.5:
        sources.append("recall_budget")
    if correction_active:
        sources.append("correction_reactivation")
    if memory_line and memory_line != "none":
        sources.append("memory_reactivation")
    if uncertainty_gate >= 0.7:
        sources.append("low_uncertainty_expression_gate")
    score = max(
        0.0,
        min(
            1.0,
            salience * 0.36
            + priority * 0.24
            + recall_norm * 0.1
            + goal_alignment * 0.14
            + uncertainty_gate * 0.1
            + (0.2 if correction_active else 0.0),
        ),
    )
    return {
        "mode": "stage77_global_workspace_ignition_v1",
        "score": round(score, 6),
        "sources": _unique(sources, limit=6),
        "uncertainty_gate": round(uncertainty_gate, 6),
        "correction_priority": correction_active,
    }


def _ignition_to_reply_coupling(
    packet: dict[str, Any],
    *,
    memory_line: str,
    goal_line: str,
    response_intention: str,
    uncertainty: float,
    ignition: dict[str, Any],
) -> dict[str, Any]:
    score = _metric(ignition.get("score"), 0.0)
    salience = _metric(_dict(_schedule(packet).get("salience_gate")).get("score"), 0.0)
    priority = _metric(_dict(_lifecycle(packet).get("consolidation_intent")).get("priority"), 0.0)
    correction_active = bool(ignition.get("correction_priority", False))
    if correction_active and memory_line and memory_line != "none":
        reply_target = "memory_reactivation_first"
    elif uncertainty >= 0.58:
        reply_target = "sensory_edge_with_uncertainty_guard"
    elif goal_line and goal_line != "reply_goal=answer_current_edge":
        reply_target = "goal_pressure_first"
    else:
        reply_target = "sensory_edge_first"
    coupling_strength = max(
        0.0,
        min(
            1.0,
            score * 0.58
            + salience * 0.16
            + priority * 0.12
            + (0.16 if correction_active else 0.0)
            - uncertainty * 0.08,
        ),
    )
    return {
        "mode": "stage77_ignition_reply_coupling_v1",
        "reply_target": reply_target,
        "coupling_strength": round(coupling_strength, 6),
        "selected_action": response_intention,
        "correction_priority": correction_active,
        "expression_mode": "direct_grounded_reply" if coupling_strength >= 0.55 else "bounded_reply",
    }


def build_bionic_consciousness_flow(packet: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    source = dict(packet or {})
    active = _dict(source.get("active_thread_state"))
    selected = _dict(source.get("selected_action"))
    current_edge = _text(query or active.get("latest_user_intent") or active.get("summary"), 180)
    if not current_edge:
        current_edge = "current turn"
    affective_tone = _affective_tone(source)
    memory_line = _memory_reactivation(source)
    goal_line = _goal_pressure(source)
    uncertainty = _metric(source.get("uncertainty_level"), 0.0)
    response_intention = _text(selected.get("action_type") or "reply_once", 100)
    ignition = _global_workspace_ignition(
        source,
        memory_line=memory_line,
        response_intention=response_intention,
        uncertainty=uncertainty,
    )
    coupling = _ignition_to_reply_coupling(
        source,
        memory_line=memory_line,
        goal_line=goal_line,
        response_intention=response_intention,
        uncertainty=uncertainty,
        ignition=ignition,
    )
    phases = [
        "sensory_edge",
        "affective_tone",
        "memory_reactivation",
        "goal_pressure",
        "response_intention",
        "uncertainty_monitor",
    ]
    legacy_lines = [line for line in _legacy_stream_lines(source) if _text(line, 160) != _text(memory_line, 160)]
    phase_lines = _unique(
        [
            f"sensory_edge={current_edge}",
            f"affective_tone={affective_tone}",
            f"memory_reactivation={memory_line or 'none'}",
            f"goal_pressure={goal_line}",
            "global_workspace_ignition="
            + f"{round(_metric(ignition.get('score'), 0.0), 3)}; sources="
            + f"{','.join(_list(ignition.get('sources'))[:4]) or 'baseline'}",
            "ignition_to_reply_coupling="
            + f"reply_target={_text(coupling.get('reply_target'), 80)}; "
            + f"coupling_strength={round(_metric(coupling.get('coupling_strength'), 0.0), 3)}; "
            + f"selected_action={response_intention}; "
            + f"correction_priority={'true' if bool(coupling.get('correction_priority', False)) else 'false'}",
            f"uncertainty_monitor={round(uncertainty, 3)}",
            *[f"legacy_stream={line}" for line in legacy_lines],
        ],
        limit=8,
    )
    dominant_phase = "memory_reactivation" if memory_line else "sensory_edge"
    stream = _dict(source.get("consciousness_stream"))
    continuity_state = {
        "thread_summary": _text(stream.get("thread_summary"), 180),
        "latest_user_intent": _text(active.get("latest_user_intent"), 140),
        "attention_center": current_edge,
        "active_goal_type": _active_goal_types(_dict(source.get("goal_state"))),
        "salience": _metric(_dict(_dict(source.get("bionic_memory_schedule")).get("salience_gate")).get("score"), 0.0),
    }
    return {
        "mode": "consciousness_flow_v1",
        "phases": phases,
        "dominant_phase": dominant_phase,
        "current_edge": current_edge,
        "phase_lines": phase_lines,
        "phase_count": len(phases),
        "global_workspace_ignition": ignition,
        "ignition_to_reply_coupling": coupling,
        "continuity_state": continuity_state,
        "leakage_guard": {
            "user_visible": False,
            "prompt_only": True,
            "surface_policy": "do_not_name_internal_flow_to_user",
        },
    }
