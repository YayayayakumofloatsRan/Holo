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
    memory_lifecycle: dict[str, Any] | None = None,
    consciousness_flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window_class = context_window_class_for(lane_name=lane_name, model=model)
    max_tokens = CONTEXT_WINDOWS[window_class]
    token_estimate = estimate_tokens(prompt)
    pressure = float(token_estimate) / float(max_tokens) if max_tokens else 0.0
    stable, volatile = _split_stable_volatile_prompt(prompt)
    provider_cache_prefix, provider_cache_dynamic = _split_provider_cache_prefix(prompt)
    provider_cache_prefix_tokens = estimate_tokens(provider_cache_prefix)
    provider_cache_dynamic_tokens = estimate_tokens(provider_cache_dynamic)
    schedule = dict(memory_schedule or {}) if isinstance(memory_schedule, dict) else {}
    cache_inheritance = (
        dict(schedule.get("cache_inheritance", {}))
        if isinstance(schedule.get("cache_inheritance", {}), dict)
        else {}
    )
    residual_channel = (
        dict(schedule.get("residual_working_channel", {}))
        if isinstance(schedule.get("residual_working_channel", {}), dict)
        else {}
    )
    tool_scheduler = (
        dict(schedule.get("tool_observation_scheduler", {}))
        if isinstance(schedule.get("tool_observation_scheduler", {}), dict)
        else {}
    )
    dynamic_delta = (
        dict(schedule.get("dynamic_delta_frame", {}))
        if isinstance(schedule.get("dynamic_delta_frame", {}), dict)
        else {}
    )
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
    lifecycle = dict(memory_lifecycle or {}) if isinstance(memory_lifecycle, dict) else {}
    lifecycle_lines = (
        lifecycle.get("prompt_lines", [])
        if isinstance(lifecycle.get("prompt_lines", []), list)
        else []
    )
    lifecycle_prompt = "\n".join(str(line).strip() for line in lifecycle_lines if str(line).strip())
    flow = dict(consciousness_flow or {}) if isinstance(consciousness_flow, dict) else {}
    flow_lines = flow.get("phase_lines", []) if isinstance(flow.get("phase_lines", []), list) else []
    flow_prompt = "\n".join(str(line).strip() for line in flow_lines if str(line).strip())
    fusion = dict(schedule.get("dynamic_fusion", {})) if isinstance(schedule.get("dynamic_fusion", {}), dict) else {}
    fusion_supplement_lines = (
        fusion.get("supplement_lines", [])
        if isinstance(fusion.get("supplement_lines", []), list)
        else []
    )
    fusion_supplement_prompt = "\n".join(str(line).strip() for line in fusion_supplement_lines if str(line).strip())
    fusion_supplement_tokens = estimate_tokens(fusion_supplement_prompt)
    stage51_equivalent_dynamic_tokens = max(
        schedule_dynamic_tokens,
        schedule_dynamic_tokens - fusion_supplement_tokens + estimate_tokens(lifecycle_prompt) + estimate_tokens(flow_prompt),
    )
    cache_inheritance_prefix_share = round(
        provider_cache_prefix_tokens / max(1, provider_cache_prefix_tokens + provider_cache_dynamic_tokens),
        6,
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
        "provider_cache_prefix_tokens": provider_cache_prefix_tokens,
        "provider_cache_dynamic_tokens": provider_cache_dynamic_tokens,
        "cache_inheritance_mode": str(cache_inheritance.get("mode", "") or ""),
        "cache_inheritance_prefix_share": cache_inheritance_prefix_share,
        "cache_inheritance_stable_tokens": int(
            cache_inheritance.get("estimated_stable_prefix_tokens", 0)
            or provider_cache_prefix_tokens
        ),
        "cache_inheritance_dynamic_tokens": int(
            cache_inheritance.get("estimated_dynamic_tokens", 0)
            or provider_cache_dynamic_tokens
        ),
        "cache_spine_line_count": int(cache_inheritance.get("cache_spine_line_count", 0) or 0),
        "residual_channel_mode": str(
            schedule.get("residual_channel_mode", "")
            or residual_channel.get("mode", "")
            or ""
        ),
        "residual_channel_fast_line_count": int(
            schedule.get("residual_channel_fast_line_count", 0)
            or residual_channel.get("fast_line_count", 0)
            or 0
        ),
        "residual_channel_fast_tokens": int(
            schedule.get("residual_channel_fast_tokens", 0)
            or residual_channel.get("fast_tokens", 0)
            or 0
        ),
        "residual_channel_protected_line_dropped": bool(
            schedule.get("residual_channel_protected_line_dropped", False)
            or residual_channel.get("protected_line_dropped", False)
        ),
        "tool_observation_scheduler_mode": str(
            schedule.get("tool_observation_scheduler_mode", "")
            or tool_scheduler.get("mode", "")
            or ""
        ),
        "tool_observation_needed": bool(
            schedule.get("tool_observation_needed", False)
            or tool_scheduler.get("needed", False)
        ),
        "tool_observation_requested_tool_count": int(
            schedule.get("tool_observation_requested_tool_count", 0)
            or tool_scheduler.get("requested_tool_count", 0)
            or 0
        ),
        "tool_observation_budget": int(
            schedule.get("tool_observation_budget", 0)
            or tool_scheduler.get("observation_budget", 0)
            or 0
        ),
        "tool_observation_runtime_decision_authority": bool(
            schedule.get("tool_observation_runtime_decision_authority", False)
            or tool_scheduler.get("runtime_decision_authority", False)
        ),
        "tool_observation_transport_decision_authority": bool(
            schedule.get("tool_observation_transport_decision_authority", False)
            or tool_scheduler.get("transport_decision_authority", False)
        ),
        "dynamic_delta_frame_mode": str(
            schedule.get("dynamic_delta_frame_mode", "")
            or dynamic_delta.get("mode", "")
            or ""
        ),
        "dynamic_delta_saved_tokens": int(
            schedule.get("dynamic_delta_saved_tokens", 0)
            or dynamic_delta.get("estimated_saved_tokens", 0)
            or 0
        ),
        "dynamic_delta_compressed_handle_count": int(
            schedule.get("dynamic_delta_compressed_handle_count", 0)
            or dynamic_delta.get("compressed_handle_count", 0)
            or 0
        ),
        "dynamic_delta_protected_line_dropped": bool(
            schedule.get("dynamic_delta_protected_line_dropped", False)
            or dynamic_delta.get("protected_line_dropped", False)
        ),
        "dynamic_delta_runtime_decision_authority": bool(
            schedule.get("dynamic_delta_runtime_decision_authority", False)
            or dynamic_delta.get("runtime_decision_authority", False)
        ),
        "dynamic_delta_transport_decision_authority": bool(
            schedule.get("dynamic_delta_transport_decision_authority", False)
            or dynamic_delta.get("transport_decision_authority", False)
        ),
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
        "memory_lifecycle_mode": str(lifecycle.get("mode", "") or ""),
        "memory_lifecycle_prompt_lines": len([line for line in lifecycle_lines if str(line).strip()]),
        "memory_lifecycle_prompt_tokens": estimate_tokens(lifecycle_prompt),
        "consciousness_flow_mode": str(flow.get("mode", "") or ""),
        "consciousness_flow_prompt_lines": len([line for line in flow_lines if str(line).strip()]),
        "consciousness_flow_prompt_tokens": estimate_tokens(flow_prompt),
        "dynamic_fusion_mode": str(fusion.get("mode", "") or ""),
        "dynamic_fusion_saved_line_count": int(fusion.get("saved_line_count", 0) or 0),
        "dynamic_fusion_supplement_lines": len([line for line in fusion_supplement_lines if str(line).strip()]),
        "dynamic_fusion_supplement_tokens": fusion_supplement_tokens,
        "stage51_equivalent_dynamic_tokens": stage51_equivalent_dynamic_tokens,
        "dynamic_fusion_saved_tokens": max(0, stage51_equivalent_dynamic_tokens - schedule_dynamic_tokens),
    }
