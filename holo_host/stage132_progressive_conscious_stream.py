from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest
from .models import ReplyBubble

STAGE132_SCHEMA = "holo.stage132.progressive_conscious_stream.v1"
STAGE132_FAST_CONTEXT_MARKER = "Stage132 Fast Context Frame"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _bounded_lines(lines: list[str], *, max_chars: int) -> list[str]:
    kept: list[str] = []
    total = 0
    for line in lines:
        cleaned = compact_text(str(line or ""), 260)
        if not cleaned:
            continue
        projected = total + len(cleaned) + 1
        if projected > max_chars:
            remaining = max(0, max_chars - total - 16)
            if remaining >= 48:
                kept.append(compact_text(cleaned, remaining))
            break
        kept.append(cleaned)
        total = projected
    return kept


def _recent_dialogue_lines(context: Any, *, limit: int = 4) -> list[str]:
    packet = _dict(getattr(context, "mind_packet", {})) or _dict(getattr(context, "sidecar", {}))
    window = _dict(packet.get("recent_dialogue_window", {}))
    lines = [compact_text(str(line), 220) for line in list(window.get("lines", []) or []) if str(line).strip()]
    if lines:
        return lines[-limit:]
    history = list(getattr(context, "history", []) or [])
    rendered: list[str] = []
    for item in history[-limit:]:
        row = _dict(item)
        direction = "user" if str(row.get("direction", "") or "") == "inbound" else "holo"
        text = compact_text(str(row.get("body_text", "") or ""), 200)
        if text:
            rendered.append(f"{direction}: {text}")
    return rendered


def _selected_action_type(context: Any) -> str:
    action = _dict(getattr(context, "selected_action", {}))
    if not action:
        packet = _dict(getattr(context, "mind_packet", {})) or _dict(getattr(context, "sidecar", {}))
        action = _dict(packet.get("selected_action", {}))
    return str(action.get("action_type", "") or "reply_once").strip() or "reply_once"


def build_stage132_fast_context_frame(
    context: Any,
    *,
    short_term_lines: list[str] | None = None,
    max_chars: int = 2800,
) -> dict[str, Any]:
    """Build a bounded high-priority frame for the first provider packet."""

    packet = _dict(getattr(context, "mind_packet", {})) or _dict(getattr(context, "sidecar", {}))
    active_state = _dict(packet.get("active_thread_state", {}))
    scene_state = _dict(active_state.get("scene_state", {}))
    capability = _dict(getattr(context, "capability_context", {}))
    tool_requests = _list_dicts(capability.get("tool_requests", []))
    attention = getattr(context, "attention_state", None)
    pressure = str(getattr(attention, "pressure_level", "") or "")
    focus = str(getattr(attention, "primary_focus", "") or "")
    selected_action = _selected_action_type(context)
    try:
        uncertainty = float(getattr(context, "uncertainty_level", 0.0) or 0.0)
    except (TypeError, ValueError):
        uncertainty = 0.0

    raw_lines = [
        f"{STAGE132_FAST_CONTEXT_MARKER}:",
        "purpose=first packet is a visible first reaction plus intent triage, not conversation termination",
        f"channel={getattr(context, 'channel', '')} thread_key={getattr(context, 'thread_key', '')} chat_name={getattr(context, 'chat_name', '')}",
        f"selected_action={selected_action} uncertainty={uncertainty:.2f} attention={focus or '-'} pressure={pressure or '-'}",
    ]
    continuity = compact_text(str(active_state.get("continuity_summary", "") or ""), 260)
    if continuity:
        raw_lines.append(f"active_continuity: {continuity}")
    shared_frame = compact_text(str(scene_state.get("shared_frame", "") or ""), 220)
    if shared_frame:
        raw_lines.append(f"scene_frame: {shared_frame}")
    for line in list(short_term_lines or [])[:8]:
        if str(line).strip():
            raw_lines.append(f"short_term: {compact_text(str(line), 220)}")
    for line in _recent_dialogue_lines(context):
        raw_lines.append(f"recent_dialogue: {line}")
    for item in tool_requests[:6]:
        name = compact_text(str(item.get("name", "") or ""), 80)
        reason = compact_text(str(item.get("reason", "") or ""), 160)
        if name:
            raw_lines.append(f"tool_request: {name} reason={reason or '-'}")
    raw_lines.append(f"user_text: {compact_text(str(getattr(context, 'user_text', '') or ''), 700)}")

    lines = _bounded_lines(raw_lines, max_chars=max(600, int(max_chars)))
    char_count = sum(len(line) for line in lines)
    cache_hint = "stage132:" + stable_digest(*lines, limit=12)
    return {
        "schema": STAGE132_SCHEMA,
        "marker": STAGE132_FAST_CONTEXT_MARKER,
        "lines": lines,
        "line_count": len(lines),
        "char_count": char_count,
        "cache_hint": cache_hint,
        "selected_action_type": selected_action,
        "tool_request_count": len(tool_requests),
    }


def plan_stage132_progressive_stream(
    *,
    fast_packet: dict[str, Any],
    continuation_lane: str,
    continuation_lane_reason: str,
    selected_action_type: str,
    uncertainty_level: float,
    channel: str,
    expression_budget: int,
    agent_tool_requests: list[dict[str, Any]],
    fast_context_frame: dict[str, Any],
) -> dict[str, Any]:
    packet = dict(fast_packet or {})
    shallow = compact_text(str(packet.get("shallow_reply", "") or ""), 360)
    speak_now = bool(packet.get("speak_now", bool(shallow)))
    deep_needed = bool(packet.get("deep_packet_needed", not bool(shallow)))
    visible_first = bool(shallow and speak_now)
    tool_loop_expected = bool(agent_tool_requests)
    lane = str(continuation_lane or "subject_main").strip() or "subject_main"

    rounds: list[dict[str, Any]] = [
        {
            "index": 0,
            "purpose": "fast_reaction",
            "lane": "micro_fast",
            "budget_tag": "stage124_fast_packet",
            "model_tier": "flash",
            "visible": visible_first,
            "emits_external_speech": visible_first,
        }
    ]
    if deep_needed:
        rounds.append(
            {
                "index": 1,
                "purpose": "deep_continuation",
                "lane": lane,
                "budget_tag": "chat_reply",
                "model_tier": "flash" if lane in {"micro_fast", "fast"} else "pro",
                "visible": True,
                "emits_external_speech": True,
                "tool_loop_expected": tool_loop_expected,
            }
        )

    cache_hint = str(dict(fast_context_frame or {}).get("cache_hint", "") or "")
    return {
        "schema": STAGE132_SCHEMA,
        "stage": 132,
        "round_count": len(rounds),
        "rounds": rounds,
        "visible_first_reaction": visible_first,
        "deep_packet_needed": deep_needed,
        "tool_loop_expected": tool_loop_expected,
        "selected_action_type": str(selected_action_type or "").strip(),
        "uncertainty_level": float(uncertainty_level or 0.0),
        "channel": str(channel or "").strip(),
        "expression_budget": int(expression_budget or 0),
        "continue_until": compact_text(str(packet.get("continue_until", "") or "answer is sufficient"), 200),
        "continuation_lane_reason": str(continuation_lane_reason or "").strip(),
        "cache_hint": cache_hint,
        "fast_context_lines": int(dict(fast_context_frame or {}).get("line_count", 0) or 0),
        "fast_context_chars": int(dict(fast_context_frame or {}).get("char_count", 0) or 0),
        "preserve_bubbles": True,
    }


def _remove_leading_duplicate(deep_text: str, first_reaction: str) -> str:
    deep = str(deep_text or "").strip()
    first = str(first_reaction or "").strip()
    if not deep or not first:
        return deep
    if deep == first:
        return ""
    if deep.startswith(first):
        return deep[len(first) :].lstrip(" \n\r\t,.;:!?")
    return deep


def merge_stage132_reply_bubbles(
    *,
    first_reaction: str,
    deep_text: str,
    stream_plan: dict[str, Any],
    channel: str,
) -> list[ReplyBubble]:
    plan = dict(stream_plan or {})
    first = compact_text(str(first_reaction or ""), 600)
    deep = _remove_leading_duplicate(str(deep_text or "").strip(), first)
    bubbles: list[ReplyBubble] = []
    if bool(plan.get("visible_first_reaction", False)) and first:
        bubbles.append(ReplyBubble(text=first, delay_ms=0, purpose="fast_reaction"))
    if deep:
        delay = 420 if str(channel or "") != "wechat" else 520
        if bubbles:
            delay = max(delay, 520)
        bubbles.append(ReplyBubble(text=deep, delay_ms=delay if bubbles else 0, purpose="deep_continuation"))
    if not bubbles and first:
        bubbles.append(ReplyBubble(text=first, delay_ms=0, purpose="fast_reaction"))
    return bubbles[:5]
