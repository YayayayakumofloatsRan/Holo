from __future__ import annotations

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


def _is_safe_language_tag(value: str) -> bool:
    if not value or len(value) > 24:
        return False
    return all(char.isalnum() or char == "-" for char in value)
