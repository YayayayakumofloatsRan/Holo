from __future__ import annotations

from kernel_v3.contracts import JsonObject


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def usage_from_text(*, prompt: str, completion: str) -> JsonObject:
    prompt_tokens = estimate_text_tokens(prompt)
    completion_tokens = estimate_text_tokens(completion)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated": True,
    }


def coerce_usage(value: object, *, prompt: str = "", completion: str = "") -> JsonObject:
    if isinstance(value, dict):
        prompt_tokens = _int(value.get("prompt_tokens"))
        completion_tokens = _int(value.get("completion_tokens"))
        total_tokens = _int(value.get("total_tokens"))
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated": bool(value.get("estimated", False)),
        }
    return usage_from_text(prompt=prompt, completion=completion)


def _int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
