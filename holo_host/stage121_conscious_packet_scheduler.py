from __future__ import annotations

import hashlib
import json
import re
from typing import Any

STAGE121_SCHEMA = "holo.stage121.conscious_packet_scheduler.v1"

STAGE121_DEFAULT_CONTEXT_WINDOW_TOKENS = 65536
STAGE121_SAFETY_MARGIN_TOKENS = 2048


def estimate_stage121_tokens(payload: Any) -> int:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return max(1, len(text) // 4)


def _clamp_int(value: Any, default: int, lower: int, upper: int) -> int:
    try:
        current = int(value)
    except (TypeError, ValueError):
        current = default
    return max(lower, min(current, upper))


def _tool_names(tool_requests: Any) -> list[str]:
    names: list[str] = []
    for raw in list(tool_requests or []):
        item = dict(raw) if isinstance(raw, dict) else {}
        name = str(item.get("name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def _complexity_score(
    *,
    query: str,
    prompt_tokens: int,
    tool_count: int,
    uncertainty_level: float,
    selected_action_type: str,
) -> float:
    score = 0.0
    score += min(0.22, prompt_tokens / 20000)
    score += min(0.22, tool_count * 0.04)
    score += max(0.0, min(float(uncertainty_level or 0.0), 1.0)) * 0.32
    if selected_action_type in {"external_lookup", "history_refresh", "visual_recall", "operator_self_fix"}:
        score += 0.12
    if _contains_any(query, ("理论", "意识流", "连续", "研究", "仿生", "架构", "工具", "记忆", "cache", "缓存", "packet")):
        score += 0.24
    if len(query) > 80:
        score += 0.08
    return max(0.0, min(score, 1.0))


def _stream_mode(score: float, tool_count: int) -> str:
    if score >= 0.56 or tool_count >= 4:
        return "continuous_thought"
    if score >= 0.32 or tool_count >= 2:
        return "single_reflective_packet"
    return "compact_reply_packet"


def _stable_prefix_digest(tool_names: list[str], lane_name: str) -> str:
    basis = json.dumps({"lane": lane_name, "tools": tool_names}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()[:12]


def build_stage121_packet_policy(
    *,
    prompt: str,
    query: str,
    tool_requests: Any,
    uncertainty_level: float = 0.0,
    selected_action_type: str = "",
    lane_name: str = "",
    lane_max_output_tokens: int = 0,
    context_window_tokens: int = STAGE121_DEFAULT_CONTEXT_WINDOW_TOKENS,
    previous_cache_hit_tokens: int = 0,
    previous_cache_miss_tokens: int = 0,
) -> dict[str, Any]:
    prompt_tokens = estimate_stage121_tokens(prompt)
    tool_names = _tool_names(tool_requests)
    tool_count = len(tool_names)
    context_window = _clamp_int(context_window_tokens, STAGE121_DEFAULT_CONTEXT_WINDOW_TOKENS, 8192, 262144)
    lane_output_cap = _clamp_int(lane_max_output_tokens, 1800, 512, 8192)
    score = _complexity_score(
        query=query,
        prompt_tokens=prompt_tokens,
        tool_count=tool_count,
        uncertainty_level=uncertainty_level,
        selected_action_type=selected_action_type,
    )
    stream_mode = _stream_mode(score, tool_count)

    output_budget = 1200
    if stream_mode == "single_reflective_packet":
        output_budget = 1600
    elif stream_mode == "continuous_thought":
        output_budget = 2200
    output_budget = min(output_budget, lane_output_cap)

    usable_input_window = max(2048, context_window - output_budget - STAGE121_SAFETY_MARGIN_TOKENS)
    fill_ratio = 0.50 + score * 0.34
    if stream_mode == "continuous_thought":
        fill_ratio = max(fill_ratio, 0.74)
    target_input_tokens = int(usable_input_window * min(fill_ratio, 0.86))
    target_input_tokens = max(prompt_tokens, min(target_input_tokens, usable_input_window))

    cache_total = max(0, int(previous_cache_hit_tokens or 0) + int(previous_cache_miss_tokens or 0))
    cache_hit_ratio = round(float(previous_cache_hit_tokens or 0) / cache_total, 4) if cache_total else 0.0
    expansion_budget = max(0, target_input_tokens - prompt_tokens)
    stable_prefix_target = min(target_input_tokens, max(1024, int(target_input_tokens * 0.62)))

    max_rounds = 2
    max_tool_calls = 8
    if stream_mode == "single_reflective_packet":
        max_rounds = 4
        max_tool_calls = 16
    elif stream_mode == "continuous_thought":
        max_rounds = 6
        max_tool_calls = 24

    phases = ["context_seed"]
    if stream_mode == "continuous_thought":
        phases.extend(["deliberation_delta", "tool_observation_reentry"])
    elif stream_mode == "single_reflective_packet":
        phases.append("tool_observation_reentry")
    phases.append("expression_commit")

    return {
        "schema": STAGE121_SCHEMA,
        "stage": 121,
        "observed_prompt_tokens": prompt_tokens,
        "context_window_tokens": context_window,
        "target_input_tokens": target_input_tokens,
        "expansion_budget_tokens": expansion_budget,
        "output_budget_tokens": output_budget,
        "complexity_score": round(score, 4),
        "cache": {
            "stable_prefix_first": True,
            "stable_prefix_target_tokens": stable_prefix_target,
            "stable_prefix_digest": _stable_prefix_digest(tool_names, lane_name),
            "previous_cache_hit_tokens": int(previous_cache_hit_tokens or 0),
            "previous_cache_miss_tokens": int(previous_cache_miss_tokens or 0),
            "previous_cache_hit_ratio": cache_hit_ratio,
            "ordering_contract": [
                "stable system and identity contract first",
                "stable tool schema working set second",
                "selected memory and attractor summaries third",
                "dynamic_tail_last",
                "volatile user turn and tool observations in dynamic_tail_last",
            ],
        },
        "continuity": {
            "stream_mode": stream_mode,
            "phases": phases,
            "send_next_packet_when": [
                "provider returns tool_calls",
                "local tool observation is available",
                "uncertainty remains high and budget remains",
            ],
            "stop_when": [
                "expression_commit produced final answer",
                "tool loop budget exhausted",
                "no new observation or uncertainty delta remains",
            ],
        },
        "tool_loop": {
            "tool_count": tool_count,
            "tool_names": tool_names,
            "max_rounds": max_rounds,
            "max_tool_calls": max_tool_calls,
        },
        "packet_fill_strategy": {
            "prefer_long_packets": True,
            "fill_order": [
                "stable cacheable prefix",
                "semantic attractor summaries",
                "selected memory evidence",
                "tool observations",
                "current turn volatile tail",
            ],
            "never_fill_with": ["raw full history", "unselected memory", "irrelevant tools"],
        },
    }


def build_stage121_packet_report(**kwargs: Any) -> dict[str, Any]:
    return build_stage121_packet_policy(**kwargs)
