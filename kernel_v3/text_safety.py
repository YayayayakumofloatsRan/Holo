from __future__ import annotations

from kernel_v3.contracts import JsonObject, JsonValue


def replace_lone_surrogates(text: str, *, replacement: str = "?") -> str:
    """Return text that can always be encoded as UTF-8."""

    if not text:
        return text
    return "".join(replacement if 0xD800 <= ord(char) <= 0xDFFF else char for char in text)


def normalize_chat_input(text: str) -> str:
    """Normalize one terminal chat line before routing or journaling it."""

    return _strip_chat_controls(_apply_backspaces(replace_lone_surrogates(text))).strip()


def sanitize_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return replace_lone_surrogates(value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {replace_lone_surrogates(str(key)): sanitize_json_value(item) for key, item in value.items()}
    return value


def sanitize_json_object(value: JsonObject) -> JsonObject:
    sanitized = sanitize_json_value(value)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def _apply_backspaces(text: str) -> str:
    result: list[str] = []
    for char in text:
        if char in {"\b", "\x7f"}:
            if result:
                result.pop()
            continue
        result.append(char)
    return "".join(result)


def _strip_chat_controls(text: str) -> str:
    result: list[str] = []
    for char in text:
        if char in {"\n", "\r", "\t"}:
            result.append(" ")
            continue
        if ord(char) < 32:
            continue
        result.append(char)
    return "".join(result)
