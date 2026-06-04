from __future__ import annotations

import re

from kernel_v3.contracts import JsonObject


DEFAULT_RESPONSE_LANGUAGE = "zh"


def normalize_response_language(value: object, *, default: str = DEFAULT_RESPONSE_LANGUAGE) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "chinese": "zh",
        "中文": "zh",
        "简体中文": "zh",
        "english": "en",
        "英文": "en",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized == "auto":
        return "auto"
    if not _is_safe_language_tag(normalized):
        return default
    return normalized


def interaction_preferences(*, response_language: object = None) -> JsonObject:
    language = normalize_response_language(response_language)
    return {
        "response_language": language,
        "response_language_instruction": response_language_instruction(language),
    }


def response_language_instruction(language: str) -> str:
    normalized = normalize_response_language(language)
    if normalized == "auto":
        return "Use the user's current turn language when clear; otherwise use the thread's established language."
    if normalized.startswith("zh"):
        return "Default user-visible text to Chinese. If the user explicitly requests another language, follow that request."
    return (
        f"Default user-visible text to language tag '{normalized}'. "
        "If the user explicitly requests another language, follow that request."
    )


def guard_user_visible_text(text: object) -> str:
    """Remove empty agreement prefaces from model-visible user-facing text.

    This is deliberately narrow: it only trims stock agreement/flattery phrases
    when they appear at the beginning of a response. It does not synthesize a
    replacement answer and it leaves quoted phrases elsewhere intact.
    """

    if not isinstance(text, str):
        return ""
    value = text.strip()
    if not value:
        return ""
    for pattern in _GENERIC_AGREEMENT_PREFIXES:
        match = pattern.match(value)
        if not match:
            continue
        remainder = value[match.end() :]
        remainder = re.sub(r"^[\s，,。.!！:：;；、-]+", "", remainder).strip()
        return remainder or _GENERIC_AGREEMENT_EMPTY_FALLBACK
    return value


def _is_safe_language_tag(value: str) -> bool:
    if not value or len(value) > 24:
        return False
    return all(char.isalnum() or char == "-" for char in value)


_GENERIC_AGREEMENT_EMPTY_FALLBACK = "我会直接处理具体问题。"

_GENERIC_AGREEMENT_PREFIXES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^你说得对\b",
        r"^你说的有道理\b",
        r"^你说得有道理\b",
        r"^确实(?:如此|是这样)?\b",
        r"^没错\b",
        r"^you(?:'|’)re right\b",
        r"^you are right\b",
        r"^that makes sense\b",
        r"^agreed\b",
    )
)
