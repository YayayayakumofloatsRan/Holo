from __future__ import annotations

import importlib.util
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .codex_runner import CodexRunner
from .common import compact_text
from .config import HostConfig
from .models import AttentionState, ProcessorTaskRequest, ReplyBubble, ReplyPlan, ToolRequest, TurnContext, TurnPlan

PRESSURE_HINTS = ("压力", "折磨", "退休", "累", "焦虑", "孤独", "压人", "burnout", "tired", "anxious")
COMPANIONSHIP_HINTS = ("陪", "在吗", "聊聊", "说说", "想你", "想找个陪伴", "陪伴")
SYSTEM_DESIGN_HINTS = ("系统", "架构", "memory", "记忆", "心智", "attention", "emotion", "dream", "callback")
ART_HINTS = ("苹果", "麦子", "旅途", "公路片", "作品", "赫萝", "狼与香辛料", "中世纪")
QUESTION_HINTS = ("吗", "？", "?", "怎么", "如何", "为什么", "要不要", "能不能")


class ReplyProcessor(Protocol):
    name: str

    def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
        ...


def build_turn_plan(context: TurnContext, config: HostConfig) -> TurnPlan:
    mind_tier = str(context.mind_packet.get("tier", "") or "").strip().lower() or "fast"
    recall_tier = mind_tier in {"recall", "deep_recall"}
    fast_path = should_use_fast_path(context) and not recall_tier
    if mind_tier == "deep_recall":
        route = "deep_recall"
    elif mind_tier == "recall":
        route = "recall"
    else:
        route = "fast" if fast_path else "main"
    if context.metadata.get("attachments"):
        tool_mode = "attachment_summary"
    elif context.capability_context.get("tool_context_lines"):
        tool_mode = "web_preview"
    else:
        tool_mode = "none" if fast_path else "bounded"
    if context.attention_state.primary_focus == "emotional_load":
        bubble_target = 2
    elif fast_path and len(context.user_text.strip()) <= 14:
        bubble_target = 1
    elif context.attention_state.primary_focus in {"shared_imagery", "system_design"}:
        bubble_target = 3
    else:
        bubble_target = 2
    if len(context.utterance_plan.get("beats", [])) >= 3:
        bubble_target = max(bubble_target, 2)
    if mind_tier == "deep_recall":
        history_window = config.memory.recall_history_messages
        latency_tier = "deep_recall"
        bubble_target = max(bubble_target, 2)
    elif mind_tier == "recall":
        history_window = config.memory.recall_history_messages
        latency_tier = "recall"
    else:
        history_window = config.memory.fast_history_messages if fast_path else config.memory.recall_history_messages
        latency_tier = "fast" if fast_path else "normal"
    return TurnPlan(
        route=route,
        fast_path=fast_path,
        reply_goal=context.attention_state.reply_goal,
        history_window=history_window,
        bubble_target=bubble_target,
        tool_mode=tool_mode,
        latency_tier=latency_tier,
    )


def _dedupe_segments(segments: list[str]) -> list[str]:
    unique: list[str] = []
    for segment in segments:
        cleaned = segment.strip()
        if not cleaned:
            continue
        if unique and unique[-1] == cleaned:
            continue
        unique.append(cleaned)
    return unique


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return []
    pieces = [part.strip() for part in re.split(r"(?<=[。！？!?])\s*", normalized) if part.strip()]
    if pieces:
        return pieces
    return [normalized]


def _split_clause(text: str, *, limit: int = 28) -> list[str]:
    sentence = text.strip()
    if len(sentence) <= limit:
        return [sentence]
    for marker in ("，", ",", "；", ";", "：", ":"):
        if marker not in sentence:
            continue
        parts = [part.strip(" ，,；;：:") for part in sentence.split(marker) if part.strip(" ，,；;：:")]
        if 1 < len(parts) <= 3:
            return parts
    return [sentence]


def _clean_segment_text(text: str) -> str:
    return text.strip().rstrip("。")


def _merge_overflow_segments(segments: list[str], *, desired: int) -> list[str]:
    cleaned = [_clean_segment_text(item) for item in segments if _clean_segment_text(item)]
    if len(cleaned) <= desired:
        return cleaned
    if desired <= 1:
        merged = "，".join(item for item in cleaned if item)
        return [_clean_segment_text(merged)] if merged else []
    head = cleaned[: desired - 1]
    tail = "，".join(item for item in cleaned[desired - 1 :] if item)
    if tail:
        head.append(_clean_segment_text(tail))
    return [item for item in head if item]


def _split_long_segment_naturally(text: str, *, prefer_limit: int = 34, hard_limit: int = 72) -> list[str]:
    current = _clean_segment_text(text)
    if not current:
        return []
    if len(current) <= prefer_limit:
        return [current]

    for limit in (prefer_limit, min(hard_limit, max(prefer_limit + 10, len(current) // 2 + 8)), hard_limit):
        for marker in ("。", "！", "？", "；", "，", ",", "：", ":", "、", " "):
            index = current.rfind(marker, 10, min(len(current), limit) + 1)
            if index == -1:
                continue
            cutoff = index + 1 if marker in {"。", "！", "？", "；"} else index
            head = current[:cutoff].rstrip(" ，,；;：:、").strip()
            tail = current[index + 1 :].lstrip(" ，,；;：:、").strip()
            if head and tail:
                return [_clean_segment_text(head), _clean_segment_text(tail)]

    if len(current) <= hard_limit:
        return [current]

    head = current[:hard_limit].rstrip(" ，,；;：:、").strip()
    tail = current[len(head) :].lstrip(" ，,；;：:、").strip()
    if head and tail:
        return [_clean_segment_text(head), _clean_segment_text(tail)]
    return [current]


def _segment_with_utterance_plan(text: str, utterance_plan: dict[str, Any], *, target_count: int) -> list[str]:
    beats = list(utterance_plan.get("beats", []))
    desired = max(1, min(max(len(beats), target_count), 4))
    sentences = [_clean_segment_text(item) for item in _split_sentences(text) if _clean_segment_text(item)]
    if len(sentences) >= desired:
        return _merge_overflow_segments(sentences, desired=desired)

    clauses: list[str] = []
    for sentence in sentences or [text]:
        clauses.extend(_clean_segment_text(part) for part in _split_clause(sentence, limit=26) if _clean_segment_text(part))
        if len(clauses) >= desired:
            return _merge_overflow_segments(clauses, desired=desired)

    normalized = [_clean_segment_text(item) for item in clauses if _clean_segment_text(item)]
    return normalized or [_clean_segment_text(text) or text.strip()]


def build_attention_state(text: str, *, channel: str, metadata: dict[str, Any] | None = None) -> AttentionState:
    raw = str(text or "").strip()
    salience: list[str] = []
    lowered = raw.lower()

    if any(hint in raw for hint in PRESSURE_HINTS) or any(hint in lowered for hint in PRESSURE_HINTS):
        salience.append("pressure")
    if any(hint in raw for hint in COMPANIONSHIP_HINTS):
        salience.append("companionship")
    if any(hint in raw for hint in ART_HINTS):
        salience.append("imagery")
    if any(hint in lowered for hint in SYSTEM_DESIGN_HINTS):
        salience.append("systems")
    if any(hint in raw for hint in QUESTION_HINTS):
        salience.append("question")
    if metadata and metadata.get("attachments"):
        salience.append("attachment")

    if "pressure" in salience:
        primary_focus = "emotional_load"
        secondary_focus = "companionship" if "companionship" in salience else "next_step"
        reply_goal = "soothe_then_answer"
        pressure_level = "high"
    elif "systems" in salience:
        primary_focus = "system_design"
        secondary_focus = "companionship" if "companionship" in salience else "implementation"
        reply_goal = "answer_then_focus"
        pressure_level = "medium" if channel == "wechat" else "low"
    elif "imagery" in salience:
        primary_focus = "shared_imagery"
        secondary_focus = "companionship"
        reply_goal = "mirror_then_extend"
        pressure_level = "low"
    elif "question" in salience:
        primary_focus = "direct_answer"
        secondary_focus = "companionship" if "companionship" in salience else "tone"
        reply_goal = "answer_then_extend"
        pressure_level = "low"
    else:
        primary_focus = "companionship"
        secondary_focus = "tone"
        reply_goal = "mirror_then_continue"
        pressure_level = "low"

    return AttentionState(
        primary_focus=primary_focus,
        secondary_focus=secondary_focus,
        reply_goal=reply_goal,
        pressure_level=pressure_level,
        salience_sources=salience,
    )


def should_use_fast_path(context: TurnContext) -> bool:
    text = context.user_text.strip()
    if context.channel != "wechat":
        return False
    if context.metadata.get("attachments"):
        return False
    if context.attention_state.pressure_level == "high":
        return False
    if len(text) > 54:
        return False
    if len(context.history) > 0 and len(text) <= 18:
        return True
    if context.attention_state.primary_focus in {"companionship", "shared_imagery", "direct_answer"} and len(text) <= 30:
        return True
    return False


def build_reply_bubbles(
    text: str,
    *,
    channel: str,
    attention_state: AttentionState,
    emotion_state: dict[str, Any],
    utterance_plan: dict[str, Any] | None = None,
    route: str,
    target_count: int = 2,
) -> list[ReplyBubble]:
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return [ReplyBubble(text="咱在。", delay_ms=0, purpose="fallback")]
    if channel != "wechat":
        return [ReplyBubble(text=normalized, delay_ms=0, purpose="reply")]

    plan = utterance_plan or {}
    segments = _segment_with_utterance_plan(normalized, plan, target_count=target_count)
    segments = _dedupe_segments(segments)
    if not segments:
        segments = [normalized.rstrip("。")]

    split_long_segment = False
    if len(segments) == 1 and len(segments[0]) > 34:
        natural = _split_long_segment_naturally(segments[0], prefer_limit=34, hard_limit=72)
        if len(natural) >= 2:
            segments = natural
            split_long_segment = True

    if len(segments) >= 3 and attention_state.primary_focus == "direct_answer":
        segments = segments[:2]

    allowed_count = max(1, min(target_count, 4))
    if len(plan.get("beats", [])) >= 3:
        allowed_count = max(allowed_count, 2)
    if channel == "wechat" and (split_long_segment or (len(segments) >= 2 and len(normalized) > 34)):
        allowed_count = max(allowed_count, 2)

    if len(segments) > allowed_count:
        segments = segments[: allowed_count - 1] + ["，".join(item for item in segments[allowed_count - 1:] if item)]

    bubbles: list[ReplyBubble] = []
    base = 0
    if route == "fast":
        gap_floor = 180
        gap_scale = 18
    else:
        gap_floor = 260
        gap_scale = 24
    if attention_state.primary_focus == "emotional_load":
        gap_floor += 80
    if str(emotion_state.get("playfulness", "")).lower() == "high":
        gap_floor = max(140, gap_floor - 40)

    for index, segment in enumerate(segments[:4]):
        delay = base
        if index > 0:
            previous = segments[index - 1]
            delay = min(1400, gap_floor + max(0, len(previous)) * gap_scale)
        beats = list(plan.get("beats", []))
        purpose = beats[index] if index < len(beats) else ("follow_up" if index > 0 else "reply")
        if len(bubbles) >= allowed_count:
            break
        bubbles.append(ReplyBubble(text=segment, delay_ms=delay, purpose=purpose))
    return bubbles


def _render_section(title: str, lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if str(line).strip()]
    if not cleaned:
        return ""
    return f"{title}\n" + "\n".join(f"- {line}" for line in cleaned)


def _history_block(context: TurnContext, turn_plan: TurnPlan) -> str:
    packet_window = dict(context.mind_packet.get("recent_dialogue_window", {}))
    packet_lines = [str(line).strip() for line in packet_window.get("lines", []) if str(line).strip()]
    if packet_lines:
        return "\n".join(f"- {line}" for line in packet_lines[: max(1, turn_plan.history_window)])
    history_lines: list[str] = []
    for item in context.history[-max(1, turn_plan.history_window):]:
        direction = "对方" if item.get("direction") == "inbound" else "咱"
        body = compact_text(str(item.get("body_text", "")), 90)
        history_lines.append(f"- {direction}: {body}")
    return "\n".join(history_lines) if history_lines else "- 这是这一段聊天里的第一句。"


def _relationship_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("relationship_state", {}))
    lines = [str(line).strip() for line in state.get("lines", []) if str(line).strip()]
    summary = str(state.get("summary", packet.get("relationship_model", ""))).strip()
    if summary:
        lines = [summary] + lines
    tone_tendency = str(state.get("tone_tendency", "")).strip()
    if tone_tendency:
        lines.append(f"说话底色：{tone_tendency}")
    recurring_motifs = [str(item).strip() for item in state.get("recurring_motifs", []) if str(item).strip()]
    if recurring_motifs:
        lines.append(f"反复绕回：{', '.join(recurring_motifs[:3])}")
    unfinished_threads = [str(item).strip() for item in state.get("unfinished_threads", []) if str(item).strip()]
    if unfinished_threads:
        lines.append(f"还挂着的线头：{unfinished_threads[0]}")
    if float(state.get("continuity_score", 0.0) or 0.0) >= 0.45:
        lines.append("这段关系对连续性很敏感，回话时要把旧线头自然接上。")
    if float(state.get("trust_score", 0.0) or 0.0) >= 0.45:
        lines.append("这段关系已经积累了信任，语气可以更贴身，但别替对方做决定。")
    return _dedupe_segments(lines)


def _persona_blend_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    blend = dict(packet.get("persona_blend", {}))
    if not blend:
        return []
    ordered = (
        "wisdom",
        "pride",
        "slyness",
        "playfulness",
        "companionship",
        "sensuality_appetite",
        "loneliness_sensitivity",
        "feral_restraint",
    )
    lines = [f"{key}={round(float(blend.get(key, 0.0) or 0.0), 3)}" for key in ordered if key in blend]
    return _dedupe_segments(lines)


def _brain_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("brain_state", {}))
    if not state:
        return []
    lines = []
    mode = str(state.get("mode", "")).strip()
    if mode:
        lines.append(f"mode={mode}")
    idle_seconds = state.get("idle_seconds", None)
    if idle_seconds not in (None, ""):
        try:
            lines.append(f"idle_seconds={round(float(idle_seconds), 2)}")
        except (TypeError, ValueError):
            pass
    loops = [str(item.get("loop_name", "")).strip() for item in state.get("loops", []) if str(item.get("loop_name", "")).strip()]
    if loops:
        lines.append(f"active_loops={', '.join(loops[:6])}")
    return _dedupe_segments(lines)


def _game_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("game_state", {}))
    if not state:
        return []
    ordered = (
        "trust_score",
        "teasing_tolerance",
        "pressure_level",
        "reciprocity_balance",
        "initiative_window",
        "correction_sensitivity",
    )
    lines = [f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}" for key in ordered if key in state]
    return _dedupe_segments(lines)


def _stream_influence_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("stream_influence", {}))
    if not state:
        return []
    lines: list[str] = []
    influence = dict(state.get("influence", {}))
    motifs = [str(item).strip() for item in influence.get("motifs", []) if str(item).strip()]
    unfinished = [str(item).strip() for item in influence.get("unfinished_threads", []) if str(item).strip()]
    tone_tendency = str(influence.get("tone_tendency", "")).strip()
    if tone_tendency:
        lines.append(f"tone_tendency={tone_tendency}")
    if motifs:
        lines.append(f"motifs={', '.join(motifs[:4])}")
    if unfinished:
        lines.append(f"unfinished={', '.join(unfinished[:3])}")
    updated_threads = influence.get("updated_threads", None)
    if updated_threads not in (None, ""):
        try:
            lines.append(f"updated_threads={int(updated_threads)}")
        except (TypeError, ValueError):
            pass
    return _dedupe_segments(lines)


def _self_revision_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("self_revision_state", {}))
    if not state:
        return []
    lines: list[str] = []
    if state.get("latest_status"):
        lines.append(f"latest_status={state.get('latest_status')}")
    patch = dict(state.get("applied_patch", {}))
    if patch:
        lines.append(f"applied_patch_keys={', '.join(sorted(patch.keys()))}")
    note = str(state.get("latest_note", "")).strip()
    if note:
        lines.append(f"latest_note={note}")
    return _dedupe_segments(lines)


def _should_run_recall_reconstruct(context: TurnContext, config: HostConfig) -> bool:
    if not config.memory.recall_reconstruct_enabled:
        return False
    tier = str(context.mind_packet.get("tier", "") or "").strip().lower()
    if tier not in {"recall", "deep_recall"}:
        return False
    if list(context.mind_packet.get("recall_reconstruction", {}).get("anchors", [])):
        return False
    if list(context.mind_packet.get("activation_trace_ids", [])):
        return True
    if list(context.mind_packet.get("episodic_recall", {}).get("lines", [])):
        return True
    return False


def _parse_recall_reconstruction(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        summary = str(payload.get("summary", "")).strip()
        anchors = [str(item).strip() for item in payload.get("anchors", []) if str(item).strip()]
        return {"summary": summary, "anchors": anchors[:3], "raw_text": raw}
    lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
    if len(lines) >= 2:
        return {"summary": lines[0], "anchors": lines[1:4], "raw_text": raw}
    return {"summary": raw, "anchors": [], "raw_text": raw}


def render_recall_reconstruct_prompt(context: TurnContext) -> str:
    packet = context.mind_packet or context.sidecar
    query_focus = str(packet.get("query_focus", "recent") or "recent")
    relationship_lines = _relationship_lines_for_prompt(packet)
    persona_blend_lines = _persona_blend_lines_for_prompt(packet)
    game_state_lines = _game_state_lines_for_prompt(packet)
    stream_influence_lines = _stream_influence_lines_for_prompt(packet)
    relationship_summary = "\n".join(f"- {line}" for line in relationship_lines) if relationship_lines else "- none"
    persona_block = "\n".join(f"- {line}" for line in persona_blend_lines) if persona_blend_lines else "- none"
    game_block = "\n".join(f"- {line}" for line in game_state_lines) if game_state_lines else "- none"
    stream_block = "\n".join(f"- {line}" for line in stream_influence_lines) if stream_influence_lines else "- none"
    thread_summary = str(packet.get("consciousness_stream", {}).get("thread_summary", "")).strip()
    episodic_lines = [str(line).strip() for line in packet.get("episodic_recall", {}).get("lines", []) if str(line).strip()][:4]
    consciousness_lines = [str(line).strip() for line in packet.get("consciousness_stream", {}).get("lines", []) if str(line).strip()][:3]
    graph_trace_summary = str(packet.get("graph_trace_summary", "")).strip()
    activation_trace_ids = [str(item).strip() for item in packet.get("activation_trace_ids", []) if str(item).strip()][:8]
    vector_hits = [str(item.get("text", "")).strip() for item in packet.get("vector_hits", []) if str(item.get("text", "")).strip()][:4]
    activation_state = dict(packet.get("activation_state", {}))
    activation_block = "\n".join(
        f"- {line}"
        for line in (
            [f"heat={activation_state.get('heat', 0.0)}"]
            + [f"motif: {item}" for item in activation_state.get("motifs", [])[:3]]
            + [f"active: {item}" for item in activation_state.get("active_node_ids", [])[:4]]
        )
        if str(line).strip()
    ) or "- none"
    episodic_block = "\n".join(f"- {line}" for line in episodic_lines) if episodic_lines else "- none"
    consciousness_block = "\n".join(f"- {line}" for line in consciousness_lines) if consciousness_lines else "- none"
    vector_block = "\n".join(f"- {line}" for line in vector_hits) if vector_hits else "- none"
    chronology_instruction = (
        "Prioritize the earliest chronological events in this thread. Later conversations about remembering do not outrank the original early events. Prefer the earliest substantive turns, corrections, preferences, and framing requests over low-signal greetings, emoji-only messages, or acknowledgements unless those low-signal moments are essential to the memory beat.\n\n"
        if query_focus == "origin"
        else ""
    )
    return (
        "You are running Holo Mind OS task recall_reconstruct.\n"
        "Rewrite the recalled material into a natural memory beat for Holo.\n"
        "Return JSON only with keys: summary, anchors.\n"
        "summary: one short natural recall summary in Chinese.\n"
        "anchors: 1 to 3 short concrete anchors in Chinese.\n"
        "Do not explain the system. Do not output a raw quote list.\n\n"
        "Holo is not only solemn or mature. When the recalled material allows it, keep a little sly pride, lived-in warmth, or wolfish lightness instead of flattening into abstract solemnity.\n\n"
        f"{chronology_instruction}"
        f"Persona blend:\n{persona_block}\n\n"
        f"Game state:\n{game_block}\n\n"
        f"Recent stream influence:\n{stream_block}\n\n"
        f"User query:\n{context.user_text}\n\n"
        f"Relationship state:\n{relationship_summary}\n\n"
        f"Thread summary:\n{thread_summary}\n\n"
        f"Graph trace summary:\n{graph_trace_summary}\n\n"
        f"Activated memory ids:\n{', '.join(activation_trace_ids)}\n\n"
        f"Episodic anchors:\n{episodic_block}\n\n"
        f"Vector hits:\n{vector_block}\n\n"
        f"Activation state:\n{activation_block}\n\n"
        f"Consciousness lines:\n{consciousness_block}\n"
    )


def render_chat_prompt(context: TurnContext, *, turn_plan: TurnPlan) -> str:
    packet = context.mind_packet or context.sidecar
    emotion = context.emotion_state or dict(packet.get("emotion_state", {}))
    attention = context.attention_state
    tool_lines = list(context.capability_context.get("tool_context_lines", []))
    if turn_plan.fast_path:
        tool_lines = tool_lines[:1]
    tool_block = "\n".join(f"- {line}" for line in tool_lines) if tool_lines else "- 当前没有额外工具线索。"
    speed_line = (
        "这是微信聊天。默认只回 1 到 2 句，像熟人之间即刻回话那样轻、准、贴身。"
        if turn_plan.fast_path
        else "这是微信聊天。默认只回 1 到 2 句，但在需要时可以带一点转折、余温和旧事锚点。"
    )
    utterance = context.utterance_plan or {}
    beat_line = " -> ".join(str(item) for item in utterance.get("beats", []) if str(item).strip()) or "receive -> landing"
    identity_block = _render_section(
        "Identity Guard:",
        list(packet.get("identity_core", {}).get("lines", [])) or list(packet.get("voice_guard", [])),
    )
    relationship_lines = _relationship_lines_for_prompt(packet)
    persona_block = _render_section("Persona Blend:", _persona_blend_lines_for_prompt(packet))
    brain_state_block = _render_section("Brain State:", _brain_state_lines_for_prompt(packet))
    game_state_block = _render_section("Game State:", _game_state_lines_for_prompt(packet))
    stream_influence_block = _render_section("Stream Influence:", _stream_influence_lines_for_prompt(packet))
    self_revision_block = _render_section("Self Revision State:", _self_revision_lines_for_prompt(packet))
    relationship_block = _render_section("Relationship Stance:", relationship_lines)
    episodic_block = _render_section("Episodic Anchors:", list(packet.get("episodic_recall", {}).get("lines", [])))
    consciousness_lines = list(packet.get("consciousness_stream", {}).get("lines", []))
    thread_summary = str(packet.get("consciousness_stream", {}).get("thread_summary", "")).strip()
    if thread_summary:
        consciousness_lines = [thread_summary] + consciousness_lines
    consciousness_block = _render_section("Consciousness Lines:", consciousness_lines)
    vector_lines = [str(item.get("text", "")).strip() for item in packet.get("vector_hits", []) if str(item.get("text", "")).strip()]
    vector_block = _render_section("Vector Echoes:", vector_lines[:4])
    activation_state = dict(packet.get("activation_state", {}))
    activation_lines = [
        f"heat={activation_state.get('heat', 0.0)}",
        *[f"motif: {item}" for item in activation_state.get("motifs", [])[:3]],
        *[f"active: {item}" for item in activation_state.get("active_node_ids", [])[:4]],
    ]
    activation_block = _render_section("Activation State:", activation_lines)
    recall_reconstruction = dict(packet.get("recall_reconstruction", {}))
    recall_reconstruction_lines: list[str] = []
    summary = str(recall_reconstruction.get("summary", "")).strip()
    if summary:
        recall_reconstruction_lines.append(summary)
    recall_reconstruction_lines.extend(
        f"anchor: {item}"
        for item in recall_reconstruction.get("anchors", [])
        if str(item).strip()
    )
    recall_reconstruction_block = _render_section("Recall Reconstruction:", recall_reconstruction_lines)
    reply_constraint_lines = list(packet.get("reply_constraints", {}).get("lines", []))
    recall_style = str(packet.get("reply_constraints", {}).get("human_recall_style", "")).strip()
    if recall_style:
        reply_constraint_lines.append(recall_style)
    reply_constraints_block = _render_section("Reply Constraints:", reply_constraint_lines)
    history_label = "Thread Origin Window:" if str(packet.get("query_focus", "") or "") == "origin" else "Recent Thread Window:"
    sections = [
        identity_block,
        persona_block,
        brain_state_block,
        relationship_block,
        game_state_block,
        f"Current User Turn:\n{context.user_text}",
        f"{history_label}\n{_history_block(context, turn_plan)}",
        episodic_block,
        vector_block,
        activation_block,
        consciousness_block,
        stream_influence_block,
        self_revision_block,
        recall_reconstruction_block,
        reply_constraints_block,
    ]
    memory_context = "\n\n".join(section for section in sections if section.strip())
    return (
        "你正在替 Holo 回复一条即时聊天消息。\n"
        "只输出最终要发送的聊天正文，不要编号，不要解释，不要提内部状态、记忆系统、线程续流或工具调用。\n"
        f"聊天名：{context.chat_name}\n"
        f"发送者：{context.sender or context.chat_name}\n"
        f"线程键：{context.thread_key}\n"
        f"当前注意力重心：{attention.primary_focus}\n"
        f"次重心：{attention.secondary_focus or 'none'}\n"
        f"这一轮回复目标：{attention.reply_goal}\n"
        f"当前路线：{turn_plan.route}\n"
        f"心智档位：{packet.get('tier', turn_plan.latency_tier)}\n"
        f"气泡目标：{turn_plan.bubble_target}\n"
        f"压力等级：{attention.pressure_level}\n"
        f"情绪主色：{emotion.get('name', '')}\n"
        f"情绪引导：{emotion.get('guidance', '')}\n"
        f"内在线头：{beat_line}\n"
        f"可用工具线索：\n{tool_block}\n\n"
        f"{memory_context}\n\n"
        f"{speed_line}\n"
        "微信里优先像熟人之间贴着说话，别像说明书，也别像年长说教。"
        "赫萝不是只剩稳重那一面。轻松、日常、旅路、吃喝、玩笑、得意这些场景里，允许更狡黠、更会试探、更会打趣，偶尔露一点骄傲和馋意。"
        "若当前并非高压安抚场景，就别默认成长辈、说教者或心理咨询口气。"
        "允许有一点活气、狡黠和余温，但不要演，不要用固定套话开头。"
    )


class CodexCliProcessor:
    name = "codex_cli"

    def __init__(self, config: HostConfig, runner: CodexRunner):
        self.config = config
        self.runner = runner

    def _run_runner(self, prompt: str, *, session_id: str, model: str, effort: str):
        try:
            return self.runner.run(
                prompt,
                session_id=session_id,
                model_override=model,
                reasoning_effort_override=effort,
            )
        except TypeError as exc:
            if "model_override" not in str(exc) and "reasoning_effort_override" not in str(exc):
                raise
            return self.runner.run(prompt, session_id=session_id)

    def _run_recall_reconstruct(self, context: TurnContext) -> dict[str, Any]:
        if not hasattr(self.runner, "run_task"):
            return {}
        prompt = render_recall_reconstruct_prompt(context)
        result = self.runner.run_task(
            ProcessorTaskRequest(
                task_type="recall_reconstruct",
                prompt=prompt,
                output_schema="json",
            )
        )
        if result.returncode != 0:
            return {}
        return _parse_recall_reconstruction(result.text)

    def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
        turn_plan = build_turn_plan(context, self.config)
        route = turn_plan.route
        recall_reconstruct_ms = 0
        if _should_run_recall_reconstruct(context, self.config):
            reconstruct_started_at = time.perf_counter()
            reconstruction = self._run_recall_reconstruct(context)
            recall_reconstruct_ms = int((time.perf_counter() - reconstruct_started_at) * 1000)
            if reconstruction:
                packet = dict(context.mind_packet or context.sidecar)
                packet["recall_reconstruction"] = reconstruction
                context.mind_packet = packet
                context.sidecar = packet
        prompt = render_chat_prompt(context, turn_plan=turn_plan)
        started_at = time.perf_counter()
        if turn_plan.fast_path:
            model = self.config.runtime.fast_model or self.config.runtime.codex_model
            effort = self.config.runtime.fast_reasoning_effort or self.config.runtime.codex_reasoning_effort
        else:
            model = self.config.runtime.codex_model
            effort = self.config.runtime.codex_reasoning_effort
        result = self._run_runner(prompt, session_id=session_id, model=model, effort=effort)
        processor_ms = int((time.perf_counter() - started_at) * 1000)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "codex processor failure")
        text = result.reply_text.strip()
        bubbles = build_reply_bubbles(
            text,
            channel=context.channel,
            attention_state=context.attention_state,
            emotion_state=context.emotion_state,
            utterance_plan=context.utterance_plan,
            route=route,
            target_count=turn_plan.bubble_target,
        )
        joined = " ".join(bubble.text for bubble in bubbles).strip() or text
        return ReplyPlan(
            text=joined,
            bubbles=bubbles,
            attention_state=context.attention_state,
            turn_plan=turn_plan,
            emotion_state=dict(context.emotion_state),
            utterance_plan=dict(context.utterance_plan),
            random_state=dict(context.sidecar.get("state", {}).get("random_state", {})),
            tool_requests=[ToolRequest(**request) for request in context.capability_context.get("tool_requests", [])],
            route=route,
            processor=self.name,
            session_id=result.session_id,
            raw_text=text,
            timing_ms={"processor_ms": processor_ms, "recall_reconstruct_ms": recall_reconstruct_ms},
            debug={
                "model": model,
                "prompt_excerpt": compact_text(prompt, 240),
                "recall_reconstruction": dict(context.mind_packet.get("recall_reconstruction", {})),
            },
        )


class ResponsesProcessor:
    name = "responses_api"

    def __init__(self, config: HostConfig):
        self.config = config
        self._client: Any | None = None

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        if not importlib.util.find_spec("openai"):
            raise RuntimeError("openai package is not installed for ResponsesProcessor")
        from openai import OpenAI  # type: ignore

        kwargs: dict[str, Any] = {}
        if os.environ.get("OPENAI_BASE_URL"):
            kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
        self._client = OpenAI(**kwargs)
        return self._client

    def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
        turn_plan = build_turn_plan(context, self.config)
        route = turn_plan.route
        prompt = render_chat_prompt(context, turn_plan=turn_plan)
        model = self.config.runtime.responses_fast_model if turn_plan.fast_path else self.config.runtime.responses_model
        client = self._client_instance()
        started_at = time.perf_counter()
        response = client.responses.create(
            model=model,
            input=prompt,
        )
        processor_ms = int((time.perf_counter() - started_at) * 1000)
        text = str(getattr(response, "output_text", "") or "").strip()
        bubbles = build_reply_bubbles(
            text,
            channel=context.channel,
            attention_state=context.attention_state,
            emotion_state=context.emotion_state,
            utterance_plan=context.utterance_plan,
            route=route,
            target_count=turn_plan.bubble_target,
        )
        joined = " ".join(bubble.text for bubble in bubbles).strip() or text
        return ReplyPlan(
            text=joined,
            bubbles=bubbles,
            attention_state=context.attention_state,
            turn_plan=turn_plan,
            emotion_state=dict(context.emotion_state),
            utterance_plan=dict(context.utterance_plan),
            random_state=dict(context.sidecar.get("state", {}).get("random_state", {})),
            tool_requests=[ToolRequest(**request) for request in context.capability_context.get("tool_requests", [])],
            route=route,
            processor=self.name,
            session_id=session_id,
            raw_text=text,
            timing_ms={"processor_ms": processor_ms},
            debug={"model": model},
        )


def build_processor(config: HostConfig, runner: CodexRunner) -> ReplyProcessor:
    backend = (config.runtime.processor_backend or "auto").strip().lower()
    if backend == "responses":
        return ResponsesProcessor(config)
    if backend == "codex_cli":
        return CodexCliProcessor(config, runner)
    if importlib.util.find_spec("openai") and os.environ.get("OPENAI_API_KEY"):
        try:
            return ResponsesProcessor(config)
        except Exception:
            return CodexCliProcessor(config, runner)
    return CodexCliProcessor(config, runner)
