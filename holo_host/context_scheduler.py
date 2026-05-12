from __future__ import annotations

import hashlib
from typing import Any


CONTEXT_WINDOWS = {
    "8k": 8_000,
    "128k": 128_000,
    "1m": 1_000_000,
}


def estimate_tokens(text: str) -> int:
    value = str(text or "")
    if not value:
        return 0
    ascii_chars = sum(1 for char in value if ord(char) < 128)
    non_ascii_chars = len(value) - ascii_chars
    return max(1, ((ascii_chars + 3) // 4) + non_ascii_chars)


def _digest(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def context_window_class_for(*, lane_name: str, model: str) -> str:
    lane = str(lane_name or "").strip()
    model_name = str(model or "").strip().lower()
    if lane == "micro_fast" or "flash" in model_name:
        return "8k"
    if "1m" in model_name or "1000k" in model_name:
        return "1m"
    return "128k"


def _split_stable_volatile_prompt(prompt: str) -> tuple[str, str]:
    text = str(prompt or "")
    markers = (
        "Current User Turn:",
        "Recent Thread Window:",
        "Thread Origin Window:",
    )
    split_at = len(text)
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            split_at = min(split_at, index)
    return text[:split_at], text[split_at:]


def _split_provider_cache_prefix(prompt: str) -> tuple[str, str]:
    text = str(prompt or "")
    markers = (
        "\u804a\u5929\u540d\uff1a",
        "\u53d1\u9001\u8005\uff1a",
        "\u7ebf\u7a0b\u952e\uff1a",
        "Current User Turn:",
        "Recent Thread Window:",
        "Thread Origin Window:",
    )
    split_at = len(text)
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            split_at = min(split_at, index)
    return text[:split_at], text[split_at:]


def split_provider_cache_prompt(prompt: str) -> tuple[str, str]:
    return _split_provider_cache_prefix(prompt)


def _history_limit(*, pressure: float, current: int) -> int:
    current_limit = max(0, int(current or 0))
    if pressure >= 0.72:
        return min(current_limit, 2)
    if pressure >= 0.55:
        return min(current_limit, 4)
    return current_limit


def plan_processor_context(
    *,
    prompt: str,
    lane_name: str,
    model: str,
    current_session_id: str = "",
    history_messages: int = 0,
    memory_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window_class = context_window_class_for(lane_name=lane_name, model=model)
    max_tokens = CONTEXT_WINDOWS[window_class]
    token_estimate = estimate_tokens(prompt)
    pressure = float(token_estimate) / float(max_tokens) if max_tokens else 0.0
    stable, volatile = _split_stable_volatile_prompt(prompt)
    provider_cache_prefix, provider_cache_dynamic = _split_provider_cache_prefix(prompt)
    schedule = dict(memory_schedule or {}) if isinstance(memory_schedule, dict) else {}
    schedule_stable = "\n".join(str(line).strip() for line in schedule.get("provider_prefix_lines", []) if str(line).strip())
    prompt_dynamic_lines = (
        schedule.get("prompt_dynamic_lines", [])
        if isinstance(schedule.get("prompt_dynamic_lines", []), list)
        else schedule.get("dynamic_context_lines", [])
    )
    schedule_dynamic = "\n".join(str(line).strip() for line in prompt_dynamic_lines if str(line).strip())
    schedule_dynamic_tokens = estimate_tokens(schedule_dynamic)
    compression = (
        dict(schedule.get("dynamic_compression_audit", {}))
        if isinstance(schedule.get("dynamic_compression_audit", {}), dict)
        else {}
    )
    start_new_session = bool(current_session_id and pressure >= 0.72)
    reason = "context_pressure" if start_new_session else "reuse_session"
    max_history_messages = _history_limit(pressure=pressure, current=int(history_messages or 0))
    return {
        "context_window_class": window_class,
        "max_context_tokens": max_tokens,
        "token_estimate": token_estimate,
        "context_pressure": round(pressure, 4),
        "start_new_session": start_new_session,
        "effective_session_id": "" if start_new_session else str(current_session_id or ""),
        "reason": reason,
        "max_history_messages": max_history_messages,
        "stable_context_digest": _digest(stable),
        "volatile_context_digest": _digest(volatile),
        "provider_cache_prefix_digest": _digest(provider_cache_prefix),
        "provider_cache_prefix_tokens": estimate_tokens(provider_cache_prefix),
        "provider_cache_dynamic_tokens": estimate_tokens(provider_cache_dynamic),
        "memory_schedule_mode": str(schedule.get("mode", "") or ""),
        "memory_schedule_stable_tokens": estimate_tokens(schedule_stable),
        "memory_schedule_dynamic_tokens": schedule_dynamic_tokens,
        "memory_dynamic_pressure": round(float(schedule_dynamic_tokens) / float(max_tokens), 4) if max_tokens else 0.0,
        "memory_compression_mode": str(compression.get("mode", "") or ""),
        "memory_prompt_dynamic_lines": int(compression.get("prompt_dynamic_line_count", 0) or len(prompt_dynamic_lines)),
        "memory_dropped_dynamic_lines": int(compression.get("dropped_dynamic_line_count", 0) or 0),
        "memory_compression_ratio": float(compression.get("compression_ratio", 1.0) or 1.0),
        "memory_protected_line_dropped": bool(compression.get("protected_line_dropped", False)),
        "memory_prompt_dynamic_tokens": schedule_dynamic_tokens,
    }
