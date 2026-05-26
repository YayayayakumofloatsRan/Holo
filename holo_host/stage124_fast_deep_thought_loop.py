from __future__ import annotations

import json
import re
from typing import Any

from .common import compact_text

STAGE124_SCHEMA = "holo.stage124.fast_deep_thought_loop.v1"
STAGE124_FAST_MARKER = "Stage124 Fast Packet"
STAGE124_DEEP_MARKER = "Stage124 Deep Packet Context"
STAGE130_CONTEXTUAL_FOLLOWUP_HINTS = (
    "\u770b\u4e00\u770b",
    "\u600e\u4e48\u6837",
    "\u600e\u6837",
    "\u7136\u540e\u5462",
    "\u7ee7\u7eed",
    "\uff1f",
    "\uff1f\uff1f",
    "\uff1f\uff1f\uff1f",
)

MEMORY_DEEP_HINTS = (
    "记忆",
    "回忆",
    "记得",
    "最深",
    "什么时候",
    "何时",
    "档案",
    "memory",
    "remember",
    "recall",
    "archive",
)
SELF_DEEP_HINTS = (
    "你是什么",
    "自己是什么",
    "自我",
    "自身",
    "主体",
    "意识",
    "主脑",
    "holo",
    "agent",
    "self",
    "identity",
    "conscious",
)
RUNTIME_DEEP_HINTS = (
    "工具",
    "调用",
    "状态",
    "内部",
    "思考",
    "反思",
    "发包",
    "provider",
    "tool",
    "state",
    "internal",
    "packet",
)
FACTUAL_DEEP_HINTS = ("如实", "事实", "准确", "具体", "不要隐喻", "fact", "factual", "concrete")
CONTEXTUAL_FOLLOWUP_HINTS = ("所以", "答案", "那", "？", "?", "也就是说", "到底")


def build_stage124_fast_packet_prompt(
    *,
    user_text: str,
    channel: str,
    thread_key: str,
    chat_name: str,
    short_term_lines: list[str] | None = None,
) -> str:
    short_term = [compact_text(str(line), 240) for line in list(short_term_lines or []) if str(line).strip()]
    short_term_block = (
        ["", "Short Term Working Memory:", *[f"- {line}" for line in short_term[:8]]]
        if short_term
        else []
    )
    return "\n".join(
        [
            f"{STAGE124_FAST_MARKER}:",
            "You are Holo's fast first packet. Return compact JSON only.",
            "Judge the external user's intent, scene, user directives, tool need, and whether a deeper packet is needed.",
            "You may include one optional shallow_reply that is safe as external_speech.",
            "A shallow_reply is only the first reaction, not proof that internal thought is complete.",
            "Use Short Term Working Memory as higher-priority local context than generic persona habits.",
            "Infer semantic intent from the full context; do not rely only on fixed trigger words.",
            "If the user states a preference or constraint, add user_directives with directive_type, scope, confidence, hard, and summary.",
            "Known directive_type examples: visible_no_emoji, identity_not_roleplay, concise_reply, preserve_context, tool_permission, memory_preference, current_turn_only.",
            "If the user appears to need tools or evidence, add tool_intent with need, tool_families, confidence, and reason.",
            "Set deep_packet_needed=true for memory, self-model, identity, runtime/tool/state, or unclear short follow-up turns.",
            "Do not expose raw hidden reasoning.",
            "",
            "Required JSON keys:",
            "- intent: short label",
            "- scene: short label",
            "- deep_packet_needed: boolean",
            "- shallow_reply: string, empty if no immediate surface reply is useful",
            "- speak_now: boolean",
            "- continue_until: short stop condition",
            "- user_directives: array, empty if none",
            "- tool_intent: object with need boolean, tool_families array, confidence number, reason string",
            "",
            f"channel={channel}",
            f"thread_key={thread_key}",
            f"chat_name={chat_name}",
            *short_term_block,
            f"user_text={compact_text(user_text, 1200)}",
        ]
    )


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _json_object_fragment(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    return match.group(0) if match else ""


def _clamp_float(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return max(0.0, min(1.0, numeric))


def _list_dicts(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def _normalize_user_directives(value: Any) -> list[dict[str, Any]]:
    directives: list[dict[str, Any]] = []
    for item in _list_dicts(value, limit=8):
        directive_type = compact_text(str(item.get("directive_type", "") or ""), 80)
        summary = compact_text(str(item.get("summary", "") or item.get("reason", "") or ""), 180)
        if not directive_type or directive_type in {"none", "unknown"}:
            continue
        directives.append(
            {
                "directive_type": directive_type,
                "summary": summary,
                "scope": compact_text(str(item.get("scope", "") or "unclear"), 60),
                "confidence": round(_clamp_float(item.get("confidence"), default=0.0), 4),
                "hard": _coerce_bool(item.get("hard"), default=False),
                "source_quote": compact_text(str(item.get("source_quote", "") or ""), 160),
            }
        )
    return directives


def _normalize_tool_intent(value: Any) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    families = [
        compact_text(str(item), 60)
        for item in list(payload.get("tool_families", []) or [])[:8]
        if str(item).strip()
    ]
    return {
        "need": _coerce_bool(payload.get("need"), default=False),
        "tool_families": families,
        "confidence": round(_clamp_float(payload.get("confidence"), default=0.0), 4),
        "reason": compact_text(str(payload.get("reason", "") or ""), 180),
    }


def parse_stage124_fast_packet(text: str) -> dict[str, Any]:
    fragment = _json_object_fragment(text)
    payload: dict[str, Any] = {}
    if fragment:
        try:
            decoded = json.loads(fragment)
            if isinstance(decoded, dict):
                payload = dict(decoded)
        except json.JSONDecodeError:
            payload = {}
    if not payload:
        fallback_text = compact_text(text, 400)
        payload = {
            "intent": "unstructured_fast_packet",
            "scene": "unknown",
            "deep_packet_needed": True,
            "shallow_reply": fallback_text,
            "speak_now": bool(fallback_text),
            "continue_until": "structured fast packet unavailable",
        }

    shallow_reply = compact_text(str(payload.get("shallow_reply", "") or ""), 600)
    deep_needed = _coerce_bool(payload.get("deep_packet_needed"), default=not bool(shallow_reply))
    return {
        "schema": STAGE124_SCHEMA,
        "stage": 124,
        "intent": compact_text(str(payload.get("intent", "") or "unknown"), 120),
        "scene": compact_text(str(payload.get("scene", "") or "unknown"), 160),
        "deep_packet_needed": deep_needed,
        "shallow_reply": shallow_reply,
        "speak_now": _coerce_bool(payload.get("speak_now"), default=bool(shallow_reply)),
        "continue_until": compact_text(str(payload.get("continue_until", "") or "external answer is sufficient"), 200),
        "user_directives": _normalize_user_directives(payload.get("user_directives", [])),
        "tool_intent": _normalize_tool_intent(payload.get("tool_intent", {})),
    }


def stage124_deep_packet_guard(user_text: str, fast_packet: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(user_text or "").strip()
    lowered = text.lower()
    packet = dict(fast_packet or {})
    shallow_reply = str(packet.get("shallow_reply", "") or "").strip()
    meaningful_len = len(re.sub(r"\s+", "", text))
    if any(hint in lowered or hint in text for hint in MEMORY_DEEP_HINTS):
        return {"required": True, "reason": "memory_or_temporal_recall"}
    if any(hint in lowered or hint in text for hint in SELF_DEEP_HINTS):
        return {"required": True, "reason": "self_model_or_identity"}
    if any(hint in lowered or hint in text for hint in RUNTIME_DEEP_HINTS):
        return {"required": True, "reason": "runtime_tool_or_state"}
    if any(hint in lowered or hint in text for hint in FACTUAL_DEEP_HINTS):
        return {"required": True, "reason": "factual_answer_requested"}
    followup_hints = tuple(CONTEXTUAL_FOLLOWUP_HINTS) + tuple(STAGE130_CONTEXTUAL_FOLLOWUP_HINTS)
    if meaningful_len <= 16 and any(hint in text or hint in lowered for hint in followup_hints):
        return {"required": True, "reason": "short_contextual_followup"}
    return {"required": False, "reason": ""}


def append_stage124_deep_packet_context(prompt: str, fast_packet: dict[str, Any]) -> str:
    text = str(prompt or "")
    if STAGE124_DEEP_MARKER in text:
        return text
    lines = [
        STAGE124_DEEP_MARKER + ":",
        f"intent={compact_text(str(fast_packet.get('intent', '') or ''), 120)}",
        f"scene={compact_text(str(fast_packet.get('scene', '') or ''), 160)}",
        f"deep_packet_needed={bool(fast_packet.get('deep_packet_needed', False))}",
        f"shallow_reply={compact_text(str(fast_packet.get('shallow_reply', '') or ''), 300)}",
        f"continue_until={compact_text(str(fast_packet.get('continue_until', '') or ''), 200)}",
        f"user_directives={json.dumps(fast_packet.get('user_directives', []), ensure_ascii=False, sort_keys=True)}",
        f"tool_intent={json.dumps(fast_packet.get('tool_intent', {}), ensure_ascii=False, sort_keys=True)}",
        "Use this as triage metadata only; do not expose raw hidden reasoning.",
        "Commit external_speech when the answer is sufficient.",
    ]
    return f"{text.rstrip()}\n\n" + "\n".join(lines)
