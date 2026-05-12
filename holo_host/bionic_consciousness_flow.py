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
    phases = [
        "sensory_edge",
        "affective_tone",
        "memory_reactivation",
        "goal_pressure",
        "response_intention",
        "uncertainty_monitor",
    ]
    legacy_lines = _legacy_stream_lines(source)
    phase_lines = _unique(
        [
            f"sensory_edge={current_edge}",
            f"affective_tone={affective_tone}",
            f"memory_reactivation={memory_line or 'none'}",
            f"goal_pressure={goal_line}",
            f"response_intention={response_intention}",
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
        "continuity_state": continuity_state,
        "leakage_guard": {
            "user_visible": False,
            "prompt_only": True,
            "surface_policy": "do_not_name_internal_flow_to_user",
        },
    }
