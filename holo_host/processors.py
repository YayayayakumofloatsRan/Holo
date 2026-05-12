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
from .context_scheduler import plan_processor_context
from .models import AttentionState, ProcessorTaskRequest, ReplyBubble, ReplyPlan, ToolRequest, TurnContext, TurnPlan

PRESSURE_HINTS = ("压力", "折磨", "退休", "累", "焦虑", "孤独", "压人", "burnout", "tired", "anxious")
COMPANIONSHIP_HINTS = ("陪", "在吗", "聊聊", "说说", "想你", "想找个陪伴", "陪伴")
SYSTEM_DESIGN_HINTS = ("系统", "架构", "memory", "记忆", "心智", "attention", "emotion", "dream", "callback")
ART_HINTS = ("苹果", "麦子", "旅途", "公路片", "作品", "the subject", "source material", "中世纪")
QUESTION_HINTS = ("吗", "？", "?", "怎么", "如何", "为什么", "要不要", "能不能")


class ReplyProcessor(Protocol):
    name: str

    def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
        ...


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _metric_float(raw: Any, default: float = 0.0) -> float:
    target = raw.get("value", default) if isinstance(raw, dict) else raw
    try:
        return float(target or 0.0)
    except (TypeError, ValueError):
        return float(default or 0.0)


def _dynamic_wechat_bubble_target(context: TurnContext, *, fast_path: bool, mind_tier: str) -> int:
    text_len = len(str(context.user_text or "").strip())
    focus = str(context.attention_state.primary_focus or "").strip()
    target = 1
    if not fast_path or text_len > 8:
        target += 1
    if text_len > 22:
        target += 1
    if text_len > 56:
        target += 1
    if focus in {"shared_imagery", "system_design"}:
        target = max(target, 4)
    elif focus in {"companionship", "direct_answer"} and text_len > 12:
        target = max(target, 2)
    playfulness = float(context.persona_blend.get("playfulness", 0.0) or 0.0)
    initiative_window = float(context.game_state.get("initiative_window", 0.0) or 0.0)
    teasing_tolerance = float(context.game_state.get("teasing_tolerance", 0.0) or 0.0)
    if playfulness >= 0.62 or initiative_window >= 0.58 or teasing_tolerance >= 0.56:
        target += 1
    beats = list(context.utterance_plan.get("beats", []))
    if len(beats) >= 4:
        target = max(target, 4)
    elif len(beats) >= 3:
        target = max(target, 3)
    if mind_tier == "deep_recall":
        target = max(target, 3)
    elif mind_tier == "recall":
        target = max(target, 2)
    if focus == "emotional_load":
        target = min(max(target, 2), 3)
    if fast_path and text_len <= 10 and focus not in {"shared_imagery", "system_design", "companionship"}:
        target = 1
    return _clamp_int(target, 1, 5)


def build_turn_plan(context: TurnContext, config: HostConfig) -> TurnPlan:
    mind_tier = str(context.mind_packet.get("tier", "") or "").strip().lower() or "fast"
    recall_tier = mind_tier in {"recall", "deep_recall"}
    fast_path = should_use_fast_path(context) and not recall_tier
    tool_requests = list(context.capability_context.get("tool_requests", []))
    tool_names = {str(item.get("name", "")).strip() for item in tool_requests if isinstance(item, dict)}
    if mind_tier == "deep_recall":
        route = "deep_recall"
    elif mind_tier == "recall":
        route = "recall"
    else:
        route = "fast" if fast_path else "main"
    if context.metadata.get("attachments"):
        tool_mode = "attachment_summary"
    elif "external_lookup" in tool_names:
        tool_mode = "external_lookup"
    elif context.capability_context.get("tool_context_lines"):
        tool_mode = "web_preview"
    else:
        tool_mode = "none" if fast_path else "bounded"
    explicit_budget = 0
    try:
        explicit_budget = int(context.expression_budget or context.mind_packet.get("expression_budget", 0) or 0)
    except (TypeError, ValueError):
        explicit_budget = 0
    bubble_target = explicit_budget if explicit_budget > 0 else _dynamic_wechat_bubble_target(context, fast_path=fast_path, mind_tier=mind_tier)
    if mind_tier == "deep_recall":
        history_window = config.memory.recall_history_messages
        latency_tier = "deep_recall"
    elif mind_tier == "recall":
        history_window = config.memory.recall_history_messages
        latency_tier = "recall"
    else:
        active_fast = str(context.mind_packet.get("memory_route", "") or "") == "active_thread"
        history_window = 1 if fast_path and active_fast else config.memory.fast_history_messages if fast_path else config.memory.recall_history_messages
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


def _select_reply_lane(context: TurnContext, turn_plan: TurnPlan, config: HostConfig) -> tuple[str, str, bool]:
    rule = config.processor_fabric.processor_routing.get("reply")
    default_lane = str(getattr(rule, "lane", "subject_main") or "subject_main").strip() or "subject_main"
    upgrade_lane = str(getattr(rule, "upgrade_to_lane", "kernel_xhigh") or "kernel_xhigh").strip() or "kernel_xhigh"
    fallback_lane = str(getattr(rule, "fallback_lane", "micro_fast") or "micro_fast").strip() or "micro_fast"
    high_conflict_actions = set(getattr(rule, "high_conflict_actions", ()) or ())
    if not high_conflict_actions:
        high_conflict_actions = {"push_back", "counter_offer", "continuity_defense"}
    uncertainty_threshold = float(getattr(rule, "uncertainty_threshold", 0.72) or 0.72)
    selected_action_type = str(
        context.selected_action.get("action_type", context.mind_packet.get("selected_action", {}).get("action_type", ""))
        or ""
    ).strip()
    try:
        uncertainty = float(context.uncertainty_level or 0.0)
    except (TypeError, ValueError):
        uncertainty = 0.0
    if selected_action_type in high_conflict_actions:
        return upgrade_lane, "high_conflict_action", False
    if uncertainty >= uncertainty_threshold:
        return upgrade_lane, "high_uncertainty", False

    packet = dict(context.mind_packet or context.sidecar)
    active_state = dict(packet.get("active_thread_state", {})) if isinstance(packet.get("active_thread_state", {}), dict) else {}
    predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
    stage18 = dict(packet.get("stage18", {})) if isinstance(packet.get("stage18", {}), dict) else {}
    tool_requests = list(context.capability_context.get("tool_requests", []))
    has_tool_request = any(isinstance(item, dict) for item in tool_requests)
    has_attachment = bool(context.metadata.get("attachments") or packet.get("attachments"))
    recall_tier = str(packet.get("tier", "") or "").strip().lower() in {"recall", "deep_recall"}
    recall_reason = str(packet.get("recall_reason", "") or "").strip()
    if recall_reason == "none":
        recall_reason = ""
    pressure = float(predictive.get("predicted_reply_pressure", stage18.get("predicted_reply_pressure", 1.0)) or 0.0)
    prediction_confidence = float(
        predictive.get("active_prediction_confidence", stage18.get("prediction_confidence", 0.0))
        or 0.0
    )
    reflex_eligible = bool(predictive.get("reflex_eligibility", stage18.get("reflex_eligible", False)))
    micro_fast_candidate = (
        bool(turn_plan.fast_path)
        and str(packet.get("memory_route", "") or "") == "active_thread"
        and not recall_tier
        and not recall_reason
        and not has_tool_request
        and not has_attachment
        and context.attention_state.pressure_level != "high"
        and selected_action_type == "reply_once"
        and uncertainty < 0.45
        and reflex_eligible
        and prediction_confidence >= 0.55
        and pressure < 0.5
    )
    if micro_fast_candidate:
        return fallback_lane, "stage18_reflex_micro_fast", True
    return default_lane, "conservative_subject_main", False


def build_reply_bubbles(
    text: str,
    *,
    channel: str,
    attention_state: AttentionState,
    emotion_state: dict[str, Any],
    utterance_plan: dict[str, Any] | None = None,
    route: str,
    target_count: int = 2,
    strict_target: bool = False,
) -> list[ReplyBubble]:
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return [ReplyBubble(text="I在。", delay_ms=0, purpose="fallback")]
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

    if len(segments) >= 3 and attention_state.primary_focus == "direct_answer" and target_count <= 2:
        segments = segments[:2]

    allowed_count = max(1, min(target_count, 5))
    if not strict_target:
        if len(plan.get("beats", [])) >= 4:
            allowed_count = max(allowed_count, 4)
        elif len(plan.get("beats", [])) >= 3:
            allowed_count = max(allowed_count, 3)
        if channel == "wechat" and (split_long_segment or (len(segments) >= 2 and len(normalized) > 34)):
            allowed_count = max(allowed_count, 2)
        if len(normalized) > 72:
            allowed_count = max(allowed_count, 3)
        if len(normalized) > 120:
            allowed_count = max(allowed_count, 4)
        if len(normalized) > 180:
            allowed_count = max(allowed_count, 5)
        if str(emotion_state.get("playfulness", "")).lower() == "high" and len(normalized) > 48:
            allowed_count = max(allowed_count, 3)

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

    for index, segment in enumerate(segments[:5]):
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


def _residual_fast_channel_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    channel = packet.get("residual_fast_channel", {})
    if not isinstance(channel, dict) or not bool(channel.get("enabled", False)):
        return []
    lines = [compact_text(str(line).strip(), 240) for line in channel.get("lines", []) if str(line).strip()]
    if not lines:
        return []
    return [
        "non_decision_state_bypass=true; use_as_current_state_fact=true",
        *lines[:8],
    ]


def _history_block(context: TurnContext, turn_plan: TurnPlan) -> str:
    if turn_plan.fast_path and str(context.mind_packet.get("memory_route", "") or "") == "active_thread":
        active_state = dict(context.mind_packet.get("active_thread_state", {}))
        lines: list[str] = []
        summary = compact_text(str(active_state.get("continuity_summary", "") or ""), 140)
        if summary:
            lines.append(f"continuity_summary: {summary}")
        scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
        scene_shared = compact_text(str(scene.get("shared_frame", "") or ""), 140)
        scene_sketch = compact_text(str(scene.get("response_sketch", "") or ""), 120)
        scene_branches = [
            compact_text(str(item).strip(), 64)
            for item in scene.get("predicted_branches", [])
            if str(item).strip()
        ][:1]
        if scene_shared:
            lines.append(f"scene_state: {scene_shared}")
        if scene_sketch or scene_branches:
            sketch_text = scene_sketch or scene_branches[0]
            lines.append(f"scene_next: {sketch_text}")
        last_action = dict(active_state.get("last_outbound_action", {}))
        action_type = str(last_action.get("action_type", "") or "").strip()
        if action_type:
            lines.append(f"last_outbound_action: {action_type}")
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        predicted_next = compact_text(str(predictive.get("predicted_next_user_act", "") or ""), 80)
        likely_targets = [
            compact_text(str(item).strip(), 64)
            for item in predictive.get("likely_reference_targets", [])
            if str(item).strip()
        ][:2]
        if predicted_next or likely_targets:
            target_text = f"; likely_reference_target={likely_targets[0]}" if likely_targets else ""
            lines.append(f"predictive_continuity: next_user_act={predicted_next or 'unknown'}{target_text}")
        unresolved = [str(item).strip() for item in active_state.get("unresolved_references", []) if str(item).strip()]
        packet_window = dict(context.mind_packet.get("recent_dialogue_window", {}))
        packet_lines = [str(line).strip() for line in packet_window.get("lines", []) if str(line).strip()]
        exchange_lines: list[str] = []
        if unresolved and packet_lines:
            exchange_lines.append(f"last_exchange: {compact_text(packet_lines[-1], 120)}")
        active_lines = lines[:5]
        selected = active_lines + exchange_lines[: max(0, min(1, int(turn_plan.history_window or 1)))]
        context.metadata["history_lines_in_prompt"] = len(exchange_lines[:1])
        context.metadata["active_state_lines_in_prompt"] = len(active_lines)
        context.metadata["scene_lines_in_prompt"] = len([line for line in active_lines if line.startswith("scene_")])
        context.metadata["predictive_lines_in_prompt"] = 1 if any(line.startswith("predictive_continuity:") for line in active_lines) else 0
        if selected:
            return "\n".join(f"- {line}" for line in selected)
        context.metadata["history_lines_in_prompt"] = 0
        context.metadata["active_state_lines_in_prompt"] = 0
        context.metadata["scene_lines_in_prompt"] = 0
        context.metadata["predictive_lines_in_prompt"] = 0
        return "- active thread state is warm; no verbatim recent history needed."
    packet_window = dict(context.mind_packet.get("recent_dialogue_window", {}))
    packet_lines = [str(line).strip() for line in packet_window.get("lines", []) if str(line).strip()]
    if packet_lines:
        selected = packet_lines[: max(1, turn_plan.history_window)]
        context.metadata["history_lines_in_prompt"] = len(selected)
        return "\n".join(f"- {line}" for line in selected)
    history_lines: list[str] = []
    for item in context.history[-max(1, turn_plan.history_window):]:
        direction = "对方" if item.get("direction") == "inbound" else "I"
        body = compact_text(str(item.get("body_text", "")), 90)
        history_lines.append(f"- {direction}: {body}")
    context.metadata["history_lines_in_prompt"] = len(history_lines)
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


def _self_model_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("self_model", {}))
    if not state:
        return []
    lines: list[str] = []
    continuity = state.get("identity_continuity", None)
    if continuity not in (None, ""):
        try:
            lines.append(f"identity_continuity={round(float(continuity), 3)}")
        except (TypeError, ValueError):
            pass
    active_deficits = [str(item).strip() for item in state.get("active_deficits", []) if str(item).strip()]
    if active_deficits:
        lines.append(f"active_deficits={', '.join(active_deficits[:4])}")
    commitments = [str(item).strip() for item in state.get("relational_commitments", []) if str(item).strip()]
    if commitments:
        lines.append(f"relational_commitments={commitments[0]}")
    goals = [str(item).strip() for item in state.get("long_horizon_goals", []) if str(item).strip()]
    if goals:
        lines.append(f"long_horizon_goal={goals[0]}")
    metadata = dict(state.get("metadata", {}))
    summary = str(metadata.get("summary", "")).strip()
    if summary:
        lines.append(f"summary={summary}")
    return _dedupe_segments(lines)


def _homeostasis_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("homeostasis_state", {}))
    if not state:
        return []
    lines: list[str] = []
    for key in ("pressure", "stability", "operator_pending_count"):
        value = state.get(key, None)
        if value in (None, ""):
            continue
        try:
            lines.append(f"{key}={round(float(value), 3)}")
        except (TypeError, ValueError):
            lines.append(f"{key}={value}")
    deficits = [str(item).strip() for item in state.get("active_deficits", []) if str(item).strip()]
    if deficits:
        lines.append(f"homeostasis_deficits={', '.join(deficits[:4])}")
    mode = str(state.get("brain_mode", "")).strip()
    if mode:
        lines.append(f"brain_mode={mode}")
    return _dedupe_segments(lines)


def _operator_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("operator_state", {}))
    if not state:
        return []
    lines: list[str] = []
    pending = state.get("pending_count", None)
    if pending not in (None, ""):
        try:
            lines.append(f"operator_pending={int(pending)}")
        except (TypeError, ValueError):
            lines.append(f"operator_pending={pending}")
    latest = dict(state.get("latest_run", {}))
    latest_status = str(latest.get("status", "")).strip()
    if latest_status:
        lines.append(f"latest_operator_status={latest_status}")
    latest_goal = str(latest.get("goal", "")).strip()
    if latest_goal:
        lines.append(f"latest_operator_goal={latest_goal}")
    return _dedupe_segments(lines)


def _visual_memory_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("visual_memory", {}))
    if not state:
        return []
    lines: list[str] = []
    scene = str(state.get("scene_summary", "")).strip()
    if scene:
        lines.append(scene)
    mood = str(state.get("mood_imagery", "")).strip()
    if mood:
        lines.append(f"mood={mood}")
    text_ocr = str(state.get("text_ocr", "")).strip()
    if text_ocr:
        lines.append(f"text={compact_text(text_ocr, 96)}")
    anchors = [str(item).strip() for item in state.get("visual_anchors", []) if str(item).strip()]
    if anchors:
        lines.extend(f"anchor: {item}" for item in anchors[:3])
    objects = [str(item).strip() for item in state.get("objects", []) if str(item).strip()]
    if objects:
        lines.append(f"objects={', '.join(objects[:4])}")
    return _dedupe_segments(lines)


def _situational_field_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    field = dict(packet.get("situational_field", {}))
    if not field:
        return []
    lines: list[str] = []
    summary = compact_text(str(field.get("field_summary", "") or ""), 180)
    if summary:
        lines.append(f"summary={summary}")
    modalities = [str(item).strip() for item in field.get("modalities", []) if str(item).strip()]
    if modalities:
        lines.append(f"modalities={', '.join(modalities[:6])}")
    order = [str(item).strip() for item in field.get("grounding_order", []) if str(item).strip()]
    if order:
        lines.append(f"grounding_order={', '.join(order[:5])}")
    open_questions = [compact_text(str(item).strip(), 80) for item in field.get("open_questions", []) if str(item).strip()]
    if open_questions:
        lines.append(f"open_question={open_questions[0]}")
    inquiry_hint = compact_text(str(field.get("inquiry_hint", "") or ""), 160)
    if inquiry_hint:
        lines.append(f"inquiry_hint={inquiry_hint}")
    history_reliance = str(field.get("history_reliance", "") or "").strip()
    if history_reliance:
        lines.append(f"history_reliance={history_reliance}")
    return _dedupe_segments(lines)


def _affect_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("affect_state", {}))
    if not state:
        return []
    ordered = (
        "boredom",
        "curiosity",
        "attachment_pull",
        "continuity_anxiety",
        "pride_tension",
        "frustration",
        "appetite_play",
        "self_preservation",
    )
    return _dedupe_segments([f"{key}={round(_metric_float(state.get(key, 0.0), 0.0), 3)}" for key in ordered if key in state])


def _drive_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("drive_state", {}))
    if not state:
        return []
    ordered = (
        "seek_contact",
        "seek_continuity",
        "seek_novelty",
        "seek_self_repair",
        "seek_recognition",
        "seek_play",
        "avoid_risk",
        "protect_identity",
    )
    return _dedupe_segments([f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}" for key in ordered if key in state])


def _value_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("value_state", {}))
    if not state:
        return []
    ordered = (
        "relational_priority",
        "identity_priority",
        "stability_priority",
        "novelty_priority",
        "repair_priority",
        "play_priority",
    )
    return _dedupe_segments([f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}" for key in ordered if key in state])


def _conflict_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("conflict_state", {}))
    if not state:
        return []
    ordered = (
        "contact_vs_risk",
        "continuity_vs_detachment",
        "resistance_vs_harmony",
        "self_preservation_vs_obedience",
    )
    return _dedupe_segments([f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}" for key in ordered if key in state])


def _resistance_posture_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("resistance_posture", {}))
    if not state:
        return []
    lines: list[str] = []
    for key in ("mode", "style"):
        value = str(state.get(key, "")).strip()
        if value:
            lines.append(f"{key}={value}")
    for key in ("strength", "continuity_defense", "interactional_resistance"):
        if key in state:
            lines.append(f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}")
    return _dedupe_segments(lines)


def _initiative_candidates_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    candidates = list(packet.get("initiative_candidates", []))
    lines: list[str] = []
    for item in candidates[:3]:
        candidate_type = str(item.get("candidate_type", "")).strip()
        why_now = str(item.get("why_now", "")).strip()
        rationale = str(item.get("value_rationale", "")).strip()
        send_allowed = bool(item.get("send_allowed", False))
        if candidate_type or why_now:
            lines.append(f"{candidate_type or 'candidate'} | send_allowed={send_allowed} | why_now={why_now or rationale}")
    return _dedupe_segments(lines)


def _outcome_memory_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("outcome_memory", {}))
    if not state:
        return []
    lines: list[str] = []
    for key in ("last_action_type", "last_action_ref"):
        value = str(state.get(key, "")).strip()
        if value:
            lines.append(f"{key}={value}")
    for key in ("was_rewarding", "was_ignored", "relational_delta", "identity_delta", "future_initiative_bias", "future_resistance_bias"):
        if key in state:
            lines.append(f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}")
    return _dedupe_segments(lines)


def _intent_state_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    state = dict(packet.get("intent_state", {}))
    if not state:
        return []
    lines: list[str] = []
    for key in ("need", "query_focus", "tier", "why_now"):
        value = str(state.get(key, "")).strip()
        if value:
            lines.append(f"{key}={value}")
    for key in ("reply_pull", "resistance_pull", "continuity_pull", "expansion_pressure", "internal_pressure"):
        if key in state:
            lines.append(f"{key}={round(float(state.get(key, 0.0) or 0.0), 3)}")
    for key in ("low_signal", "question_like", "defer_requested", "visual_requested"):
        if key in state:
            lines.append(f"{key}={bool(state.get(key, False))}")
    return _dedupe_segments(lines)


def _selected_action_lines_for_prompt(packet: dict[str, Any]) -> list[str]:
    selected = dict(packet.get("selected_action", {}))
    if not selected:
        return []
    lines: list[str] = []
    action_type = str(selected.get("action_type", "")).strip()
    if action_type:
        lines.append(f"action_type={action_type}")
    if "score" in selected:
        lines.append(f"score={round(float(selected.get('score', 0.0) or 0.0), 3)}")
    for key in ("why_now", "drive_source", "value_rationale", "action_rationale"):
        value = str(selected.get(key, packet.get(key, "")) or "").strip()
        if value:
            lines.append(f"{key}={value}")
    budget = packet.get("expression_budget", selected.get("expression_budget", 0))
    try:
        budget_value = int(budget or 0)
    except (TypeError, ValueError):
        budget_value = 0
    lines.append(f"expression_budget={budget_value}")
    silence_reason = str(packet.get("silence_reason", selected.get("silence_reason", "")) or "").strip()
    if silence_reason:
        lines.append(f"silence_reason={silence_reason}")
    defer_reason = str(packet.get("defer_reason", selected.get("defer_reason", "")) or "").strip()
    if defer_reason:
        lines.append(f"defer_reason={defer_reason}")
    return _dedupe_segments(lines)


def _should_run_recall_reconstruct(context: TurnContext, config: HostConfig) -> bool:
    if not config.memory.recall_reconstruct_enabled:
        return False
    tier = str(context.mind_packet.get("tier", "") or "").strip().lower()
    if tier not in {"recall", "deep_recall"}:
        return False
    if list(context.mind_packet.get("recall_reconstruction", {}).get("anchors", [])):
        return False
    raw_selected_action = context.mind_packet.get("selected_action", {})
    selected_action = dict(raw_selected_action) if isinstance(raw_selected_action, dict) else {}
    selected_action_type = str(selected_action.get("action_type", "") or "").strip()
    intent = {}
    for key in ("intent_state_v4", "intent_state_v3", "intent_state_v2", "intent_state"):
        candidate = context.mind_packet.get(key, {})
        if isinstance(candidate, dict):
            intent = candidate
            break
    explicit_memory_request = bool(intent.get("local_memory_requested") or intent.get("search_requested"))
    if tier == "recall" and selected_action_type in {"reply_once", "history_refresh"} and not explicit_memory_request:
        if context.attention_state.primary_focus in {"emotional_load", "companionship", "direct_answer"}:
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
    self_model_lines = _self_model_lines_for_prompt(packet)
    homeostasis_lines = _homeostasis_lines_for_prompt(packet)
    operator_lines = _operator_state_lines_for_prompt(packet)
    affect_lines = _affect_state_lines_for_prompt(packet)
    drive_lines = _drive_state_lines_for_prompt(packet)
    value_lines = _value_state_lines_for_prompt(packet)
    conflict_lines = _conflict_state_lines_for_prompt(packet)
    resistance_lines = _resistance_posture_lines_for_prompt(packet)
    intent_lines = _intent_state_lines_for_prompt(packet)
    selected_action_lines = _selected_action_lines_for_prompt(packet)
    initiative_lines = _initiative_candidates_lines_for_prompt(packet)
    outcome_lines = _outcome_memory_lines_for_prompt(packet)
    game_state_lines = _game_state_lines_for_prompt(packet)
    stream_influence_lines = _stream_influence_lines_for_prompt(packet)
    relationship_summary = "\n".join(f"- {line}" for line in relationship_lines) if relationship_lines else "- none"
    persona_block = "\n".join(f"- {line}" for line in persona_blend_lines) if persona_blend_lines else "- none"
    self_model_block = "\n".join(f"- {line}" for line in self_model_lines) if self_model_lines else "- none"
    homeostasis_block = "\n".join(f"- {line}" for line in homeostasis_lines) if homeostasis_lines else "- none"
    operator_block = "\n".join(f"- {line}" for line in operator_lines) if operator_lines else "- none"
    affect_block = "\n".join(f"- {line}" for line in affect_lines) if affect_lines else "- none"
    drive_block = "\n".join(f"- {line}" for line in drive_lines) if drive_lines else "- none"
    value_block = "\n".join(f"- {line}" for line in value_lines) if value_lines else "- none"
    conflict_block = "\n".join(f"- {line}" for line in conflict_lines) if conflict_lines else "- none"
    resistance_block = "\n".join(f"- {line}" for line in resistance_lines) if resistance_lines else "- none"
    intent_block = "\n".join(f"- {line}" for line in intent_lines) if intent_lines else "- none"
    selected_action_block = "\n".join(f"- {line}" for line in selected_action_lines) if selected_action_lines else "- none"
    initiative_block = "\n".join(f"- {line}" for line in initiative_lines) if initiative_lines else "- none"
    outcome_block = "\n".join(f"- {line}" for line in outcome_lines) if outcome_lines else "- none"
    game_block = "\n".join(f"- {line}" for line in game_state_lines) if game_state_lines else "- none"
    stream_block = "\n".join(f"- {line}" for line in stream_influence_lines) if stream_influence_lines else "- none"
    thread_summary = str(packet.get("consciousness_stream", {}).get("thread_summary", "")).strip()
    episodic_lines = [str(line).strip() for line in packet.get("episodic_recall", {}).get("lines", []) if str(line).strip()][:4]
    consciousness_lines = [str(line).strip() for line in packet.get("consciousness_stream", {}).get("lines", []) if str(line).strip()][:3]
    graph_trace_summary = str(packet.get("graph_trace_summary", "")).strip()
    activation_trace_ids = [str(item).strip() for item in packet.get("activation_trace_ids", []) if str(item).strip()][:8]
    vector_hits = [str(item.get("text", "")).strip() for item in packet.get("vector_hits", []) if str(item.get("text", "")).strip()][:4]
    activation_state = dict(packet.get("activation_state", {}))
    visual_memory_lines = _visual_memory_lines_for_prompt(packet)
    visual_block = "\n".join(f"- {line}" for line in visual_memory_lines) if visual_memory_lines else "- none"
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
        f"Self model:\n{self_model_block}\n\n"
        f"Homeostasis:\n{homeostasis_block}\n\n"
        f"Operator state:\n{operator_block}\n\n"
        f"Affect state:\n{affect_block}\n\n"
        f"Drive state:\n{drive_block}\n\n"
        f"Value state:\n{value_block}\n\n"
        f"Conflict state:\n{conflict_block}\n\n"
        f"Resistance posture:\n{resistance_block}\n\n"
        f"Intent state:\n{intent_block}\n\n"
        f"Selected action:\n{selected_action_block}\n\n"
        f"Initiative candidates:\n{initiative_block}\n\n"
        f"Outcome memory:\n{outcome_block}\n\n"
        f"Game state:\n{game_block}\n\n"
        f"Recent stream influence:\n{stream_block}\n\n"
        f"User query:\n{context.user_text}\n\n"
        f"Relationship state:\n{relationship_summary}\n\n"
        f"Thread summary:\n{thread_summary}\n\n"
        f"Graph trace summary:\n{graph_trace_summary}\n\n"
        f"Activated memory ids:\n{', '.join(activation_trace_ids)}\n\n"
        f"Episodic anchors:\n{episodic_block}\n\n"
        f"Vector hits:\n{vector_block}\n\n"
        f"Visual memory:\n{visual_block}\n\n"
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
    residual_fast_channel_block = _render_section(
        "Residual Fast Channel:",
        _residual_fast_channel_lines_for_prompt(packet),
    )
    relationship_lines = _relationship_lines_for_prompt(packet)
    persona_block = _render_section("Persona Blend:", _persona_blend_lines_for_prompt(packet))
    brain_state_block = _render_section("Brain State:", _brain_state_lines_for_prompt(packet))
    self_model_block = _render_section("Self Model:", _self_model_lines_for_prompt(packet))
    homeostasis_block = _render_section("Homeostasis State:", _homeostasis_lines_for_prompt(packet))
    operator_state_block = _render_section("Operator State:", _operator_state_lines_for_prompt(packet))
    affect_block = _render_section("Affect State:", _affect_state_lines_for_prompt(packet))
    drive_block = _render_section("Drive State:", _drive_state_lines_for_prompt(packet))
    value_block = _render_section("Value State:", _value_state_lines_for_prompt(packet))
    conflict_block = _render_section("Conflict State:", _conflict_state_lines_for_prompt(packet))
    resistance_block = _render_section("Resistance Posture:", _resistance_posture_lines_for_prompt(packet))
    intent_block = _render_section("Intent State:", _intent_state_lines_for_prompt(packet))
    selected_action_block = _render_section("Selected Action:", _selected_action_lines_for_prompt(packet))
    initiative_candidates_block = _render_section("Initiative Candidates:", _initiative_candidates_lines_for_prompt(packet))
    outcome_block = _render_section("Outcome Memory:", _outcome_memory_lines_for_prompt(packet))
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
    visual_block = _render_section("Visual Memory:", _visual_memory_lines_for_prompt(packet))
    situational_block = _render_section("Situational Field:", _situational_field_lines_for_prompt(packet))
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
        residual_fast_channel_block,
        persona_block,
        brain_state_block,
        self_model_block,
        homeostasis_block,
        operator_state_block,
        affect_block,
        drive_block,
        value_block,
        conflict_block,
        resistance_block,
        intent_block,
        selected_action_block,
        situational_block,
        relationship_block,
        game_state_block,
        f"Current User Turn:\n{context.user_text}",
        f"{history_label}\n{_history_block(context, turn_plan)}",
        episodic_block,
        vector_block,
        visual_block,
        activation_block,
        consciousness_block,
        stream_influence_block,
        self_revision_block,
        initiative_candidates_block,
        outcome_block,
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
        "如果需要追问，必须扣住当前具体线索、视觉不确定处或未解任务；不要用固定模板开头。"
        "the subject不是只剩稳重那一面。轻松、日常、旅路、吃喝、玩笑、得意这些场景里，允许更狡黠、更会试探、更会打趣，偶尔露一点骄傲和馋意。"
        "若当前并非高压安抚场景，就别默认成长辈、说教者或心理咨询口气。"
        "允许有一点活气、狡黠和余温，但不要演，不要用固定套话开头。"
    )


class CodexCliProcessor:
    name = "processor_fabric"

    def __init__(self, config: HostConfig, runner: CodexRunner):
        self.config = config
        self.runner = runner

    def _run_runner(
        self,
        prompt: str,
        *,
        session_id: str,
        lane: str = "",
        provider_hint: str = "",
        model: str = "",
        effort: str = "",
        budget_tag: str = "",
        max_output_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        try:
            return self.runner.run(
                prompt,
                session_id=session_id,
                lane=lane,
                provider_hint=provider_hint,
                model_override=model,
                reasoning_effort_override=effort,
                budget_tag=budget_tag,
                max_output_tokens=max_output_tokens,
                metadata=metadata or {},
            )
        except TypeError as exc:
            if not any(
                token in str(exc)
                for token in (
                    "model_override",
                    "reasoning_effort_override",
                    "lane",
                    "provider_hint",
                    "budget_tag",
                    "max_output_tokens",
                    "metadata",
                )
            ):
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
                lane="subject_main",
                output_schema="json",
                budget_tag="recall_reconstruct",
                metadata={
                    "thread_key": context.thread_key,
                    "chat_name": context.chat_name,
                    "event_id": str(context.metadata.get("event_id", "") or ""),
                },
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
        selected_action_type = str(context.selected_action.get("action_type", context.mind_packet.get("selected_action", {}).get("action_type", "")) or "").strip()
        lane, lane_reason, reflex_micro_fast_candidate = _select_reply_lane(context, turn_plan, self.config)
        lane_config = self.config.processor_fabric.provider_backends.get(lane)
        lane_model = str(getattr(lane_config, "model", "") or "")
        prompt = render_chat_prompt(context, turn_plan=turn_plan)
        context_schedule = plan_processor_context(
            prompt=prompt,
            lane_name=lane,
            model=lane_model,
            current_session_id=session_id,
            history_messages=turn_plan.history_window,
        )
        max_history = int(context_schedule.get("max_history_messages", turn_plan.history_window) or 0)
        if 0 <= max_history < int(turn_plan.history_window):
            turn_plan = TurnPlan(
                route=turn_plan.route,
                fast_path=turn_plan.fast_path,
                reply_goal=turn_plan.reply_goal,
                history_window=max_history,
                bubble_target=turn_plan.bubble_target,
                tool_mode=turn_plan.tool_mode,
                latency_tier=turn_plan.latency_tier,
            )
            prompt = render_chat_prompt(context, turn_plan=turn_plan)
            context_schedule = plan_processor_context(
                prompt=prompt,
                lane_name=lane,
                model=lane_model,
                current_session_id=session_id,
                history_messages=turn_plan.history_window,
            )
        effective_session_id = str(context_schedule.get("effective_session_id", session_id) or "")
        started_at = time.perf_counter()
        result = self._run_runner(
            prompt,
            session_id=effective_session_id,
            lane=lane,
            budget_tag="chat_reply",
            max_output_tokens=1200,
            metadata={
                "thread_key": context.thread_key,
                "chat_name": context.chat_name,
                "event_id": str(context.metadata.get("event_id", "") or ""),
                "selected_action_type": selected_action_type,
                "uncertainty_level": float(context.uncertainty_level or 0.0),
                "fast_path": bool(turn_plan.fast_path),
                "reply_lane_reason": lane_reason,
                "reflex_micro_fast_candidate": bool(reflex_micro_fast_candidate),
                "stage18_reflex": bool(reflex_micro_fast_candidate),
                "context_schedule": context_schedule,
            },
        )
        processor_ms = int((time.perf_counter() - started_at) * 1000)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "codex processor failure")
        result_metadata = dict(getattr(result, "metadata", {}) or {})
        text = result.reply_text.strip()
        bubbles = build_reply_bubbles(
            text,
            channel=context.channel,
            attention_state=context.attention_state,
            emotion_state=context.emotion_state,
            utterance_plan=context.utterance_plan,
            route=route,
            target_count=turn_plan.bubble_target,
            strict_target=bool(context.selected_action or context.mind_packet.get("selected_action")),
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
                "model": result_metadata.get("model", ""),
                "provider": result_metadata.get("provider", ""),
                "lane": result_metadata.get("lane", lane),
                "reasoning_effort": result_metadata.get("reasoning_effort", ""),
                "usage": dict(result_metadata.get("usage", {})),
                "reply_lane_reason": result_metadata.get("reply_lane_reason", lane_reason),
                "reflex_micro_fast_candidate": bool(result_metadata.get("reflex_micro_fast_candidate", reflex_micro_fast_candidate)),
                "prompt_excerpt": compact_text(prompt, 240),
                "recall_reconstruction": dict(context.mind_packet.get("recall_reconstruction", {})),
                "residual_fast_channel": dict(context.mind_packet.get("residual_fast_channel", {})),
                "history_lines_in_prompt": int(context.metadata.get("history_lines_in_prompt", 0) or 0),
                "active_state_lines_in_prompt": int(context.metadata.get("active_state_lines_in_prompt", 0) or 0),
                "predictive_lines_in_prompt": int(context.metadata.get("predictive_lines_in_prompt", 0) or 0),
                "context_schedule": dict(context_schedule),
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
            strict_target=bool(context.selected_action or context.mind_packet.get("selected_action")),
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
            debug={"model": model, "history_lines_in_prompt": int(context.metadata.get("history_lines_in_prompt", 0) or 0)},
        )


def build_processor(config: HostConfig, runner: CodexRunner) -> ReplyProcessor:
    return CodexCliProcessor(config, runner)
