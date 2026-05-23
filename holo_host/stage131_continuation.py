from __future__ import annotations

from typing import Any


ACK_CONTINUATION_HINTS = {
    "ok",
    "okay",
    "\u884c",
    "\u597d",
    "\u53ef\u4ee5",
    "\u55ef",
    "\u55ef\u55ef",
    "\u5bf9",
    "\u7ee7\u7eed",
    "\u63a5\u7740",
    "\u63a5\u7740\u8bf4",
}

CHINESE_QUESTION_HINTS = (
    "\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u600e\u6837",
    "\u5982\u4f55",
    "\u4e3a\u4ec0\u4e48",
    "\u54ea",
    "\u80fd\u5426",
    "\u53ef\u5426",
    "\u662f\u5426",
    "\u5417",
    "\u5462",
    "\u8bb0\u5f97",
    "\u56de\u5fc6",
    "\u4e4b\u524d",
    "\u521a\u624d",
)

OPEN_LOOP_HINTS = (
    "?",
    "\uff1f",
    "\u7ee7\u7eed",
    "\u63a5\u7740",
    "\u5f80\u4e0b",
    "\u8d70\u5b8c",
    "\u6d41\u7a0b",
    "\u4e0b\u4e00\u6b65",
    "\u8981\u4e0d\u8981",
    "\u80fd\u4e0d\u80fd",
    "\u53ef\u4ee5",
)


def meaningful_char_count(text: str | None) -> int:
    return sum(1 for ch in str(text or "") if ch.isalnum() or "\u3400" <= ch <= "\u9fff")


def compact_text_key(text: str | None) -> str:
    return "".join(str(text or "").strip().lower().split())


def chinese_question_like(text: str | None) -> bool:
    current = str(text or "").strip()
    if any(marker in current for marker in ("?", "\uff1f")):
        return True
    return any(hint in current for hint in CHINESE_QUESTION_HINTS)


def recent_dialogue_lines_from_packet(packet: dict[str, Any] | None, *, limit: int = 8) -> list[str]:
    payload = dict(packet or {})
    window = dict(payload.get("recent_dialogue_window", {})) if isinstance(payload.get("recent_dialogue_window"), dict) else {}
    lines = [str(line).strip() for line in window.get("lines", []) if str(line).strip()]
    return lines[-max(1, int(limit)) :]


def stage131_short_turn_requires_reply(query: str | None, packet: dict[str, Any] | None) -> bool:
    current = compact_text_key(query)
    if not current:
        return False
    if meaningful_char_count(current) > 6 and current not in ACK_CONTINUATION_HINTS:
        return False
    if current not in ACK_CONTINUATION_HINTS and not chinese_question_like(query):
        return False

    recent_lines = recent_dialogue_lines_from_packet(packet, limit=8)
    if not recent_lines:
        return False
    last_holo = ""
    for line in reversed(recent_lines):
        lowered = line.lower()
        if lowered.startswith("holo:") or lowered.startswith("assistant:"):
            last_holo = line
            break
    if not last_holo:
        return False
    return any(hint in last_holo for hint in OPEN_LOOP_HINTS)
