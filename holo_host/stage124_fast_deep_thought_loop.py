from __future__ import annotations

import json
import re
from typing import Any

from .common import compact_text

STAGE124_SCHEMA = "holo.stage124.fast_deep_thought_loop.v1"
STAGE124_FAST_MARKER = "Stage124 Fast Packet"
STAGE124_DEEP_MARKER = "Stage124 Deep Packet Context"


def build_stage124_fast_packet_prompt(
    *,
    user_text: str,
    channel: str,
    thread_key: str,
    chat_name: str,
) -> str:
    return "\n".join(
        [
            f"{STAGE124_FAST_MARKER}:",
            "You are Holo's fast first packet. Return compact JSON only.",
            "Judge the external user's intent, scene, and whether a deeper packet is needed.",
            "You may include one optional shallow_reply that is safe as external_speech.",
            "Do not expose raw hidden reasoning.",
            "",
            "Required JSON keys:",
            "- intent: short label",
            "- scene: short label",
            "- deep_packet_needed: boolean",
            "- shallow_reply: string, empty if no immediate surface reply is useful",
            "- speak_now: boolean",
            "- continue_until: short stop condition",
            "",
            f"channel={channel}",
            f"thread_key={thread_key}",
            f"chat_name={chat_name}",
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
    }


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
        "Use this as triage metadata only; do not expose raw hidden reasoning.",
        "Commit external_speech when the answer is sufficient.",
    ]
    return f"{text.rstrip()}\n\n" + "\n".join(lines)
