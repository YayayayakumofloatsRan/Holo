from __future__ import annotations

import math
from typing import Any

from .common import stable_digest

STAGE143_SCHEMA = "holo.stage143.packet_budget.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _token_usage(value: Any) -> int:
    usage = _dict(value)
    for key in ("total_tokens", "total_estimated_tokens"):
        total = _int(usage.get(key), 0)
        if total > 0:
            return total
    return max(
        0,
        _int(usage.get("prompt_tokens"), 0)
        + _int(usage.get("completion_tokens"), 0)
        + _int(usage.get("input_tokens"), 0)
        + _int(usage.get("output_tokens"), 0),
    )


def _estimate_tokens_from_chars(char_count: Any, fallback_text: str = "") -> int:
    chars = _int(char_count, 0)
    if chars <= 0 and fallback_text:
        chars = len(str(fallback_text or ""))
    if chars <= 0:
        return 64
    return max(1, int(math.ceil(chars / 4.0)))


def _status(report: Any) -> str:
    return str(_dict(report).get("status", "") or "").strip()


def _memory_need(memory_grounding: Any, memory_alignment: Any, reply_debug: dict[str, Any]) -> bool:
    if _dict(memory_grounding) or _dict(memory_alignment):
        return True
    ledger = reply_debug.get("memory_observation_ledger", [])
    return bool(ledger)


def _tool_need(stream: dict[str, Any], tool_grounding: Any, agent_tool_loop: Any, reply_debug: dict[str, Any]) -> bool:
    if bool(stream.get("tool_loop_expected", False)):
        return True
    if _dict(tool_grounding):
        return True
    loop = _dict(agent_tool_loop)
    if _int(loop.get("round_count"), 0) > 0 or loop.get("executed_tools"):
        return True
    return bool(reply_debug.get("provider_tool_names"))


def _stage142_stop_reason(stage142_semantic_novelty: Any) -> str:
    novelty = _dict(stage142_semantic_novelty)
    status = str(novelty.get("status", "") or "").strip()
    if status and status != "passed":
        return f"stage142:{status}"
    return ""


def _packet(
    *,
    packet_id: str,
    packet_type: str,
    lane: str,
    budget_tag: str,
    sent: bool,
    send_reason: str = "",
    skip_reason: str = "",
    cache_hint: str = "",
    estimated_tokens: int = 0,
    elapsed_ms: int = 0,
    tool_need: bool = False,
    memory_need: bool = False,
    uncertainty: float = 0.0,
    grounding_status: str = "",
    memory_alignment_status: str = "",
    stage142_status: str = "",
    stop_reason: str = "",
) -> dict[str, Any]:
    return {
        "packet_id": packet_id,
        "packet_type": packet_type,
        "lane": lane,
        "budget_tag": budget_tag,
        "sent": bool(sent),
        "send_reason": send_reason,
        "skip_reason": skip_reason,
        "cache_hint": cache_hint,
        "estimated_tokens": max(0, int(estimated_tokens or 0)),
        "elapsed_ms": max(0, int(elapsed_ms or 0)),
        "tool_need": bool(tool_need),
        "memory_need": bool(memory_need),
        "uncertainty": round(max(0.0, min(1.0, float(uncertainty or 0.0))), 4),
        "grounding_status": grounding_status,
        "memory_alignment_status": memory_alignment_status,
        "stage142_status": stage142_status,
        "stop_reason": stop_reason,
    }


def build_stage143_packet_budget(
    *,
    stage132_stream_plan: dict[str, Any] | None = None,
    stage132_fast_context_frame: dict[str, Any] | None = None,
    stage124_thought_loop: dict[str, Any] | None = None,
    stage121_packet_policy: dict[str, Any] | None = None,
    stage142_semantic_novelty: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    timing_ms: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    agent_tool_loop: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    channel: str = "",
) -> dict[str, Any]:
    """Report packet-chain budget and stop reasons without changing execution.

    Stage143 consumes existing debug metadata only. It does not call a provider,
    execute tools, write memory, or decide whether continuation should happen.
    """

    debug = _dict(reply_debug)
    stream = _dict(stage132_stream_plan) or _dict(debug.get("stage132_progressive_stream", {}))
    fast_frame = _dict(stage132_fast_context_frame) or _dict(debug.get("stage132_fast_context_frame", {}))
    thought = _dict(stage124_thought_loop) or _dict(debug.get("stage124_thought_loop", {}))
    policy = _dict(stage121_packet_policy) or _dict(debug.get("stage121_packet_policy", {}))
    novelty = _dict(stage142_semantic_novelty) or _dict(debug.get("stage142_semantic_novelty", {}))
    loop = _dict(agent_tool_loop) or _dict(debug.get("agent_tool_loop", {}))
    timings = _dict(timing_ms) or _dict(debug.get("timing_ms", {}))
    main_usage = _dict(usage) or _dict(debug.get("usage", {}))
    fast_metadata = _dict(thought.get("fast_packet_metadata", {}))
    fast_usage = _dict(fast_metadata.get("usage", {}))

    rounds = _list_dicts(stream.get("rounds", []))
    round0 = rounds[0] if rounds else {
        "purpose": "fast_reaction",
        "lane": "micro_fast",
        "budget_tag": "stage124_fast_packet",
        "condition": "always_run_first_packet",
    }
    deep_round = next((item for item in rounds if str(item.get("purpose", "")) == "deep_continuation"), None)
    deep_needed = bool(stream.get("deep_packet_needed", False))
    deep_sent = bool(thought.get("deep_packet_sent", deep_needed and deep_round is not None))
    fast_elapsed = _int(thought.get("fast_packet_ms", timings.get("stage124_fast_packet_ms")), 0)
    processor_elapsed = _int(timings.get("processor_ms"), 0)
    deep_elapsed = max(0, processor_elapsed - fast_elapsed - _int(timings.get("recall_reconstruct_ms"), 0)) if processor_elapsed else 0
    stage142_status = _status(novelty)
    memory_alignment_status = _status(memory_alignment) or _status(debug.get("memory_alignment", {}))
    tool_status = _status(tool_grounding) or _status(debug.get("tool_grounding", {}))
    memory_status = _status(memory_grounding) or _status(debug.get("memory_grounding", {}))
    grounding_status = ";".join(part for part in [f"tool:{tool_status}" if tool_status else "", f"memory:{memory_status}" if memory_status else ""] if part)
    uncertainty = _float(stream.get("uncertainty_level", debug.get("uncertainty_level", 0.0)), 0.0)
    cache_hint = str(fast_frame.get("cache_hint", "") or stream.get("cache_hint", "") or "")
    tool_need = _tool_need(stream, tool_grounding, loop, debug)
    memory_need = _memory_need(memory_grounding, memory_alignment, debug)

    packets: list[dict[str, Any]] = []
    fast_tokens = _token_usage(fast_usage)
    if fast_tokens <= 0 and not deep_sent:
        fast_tokens = _token_usage(main_usage)
    if fast_tokens <= 0:
        fast_tokens = _estimate_tokens_from_chars(fast_frame.get("char_count", stream.get("fast_context_chars", 0)), debug.get("prompt_excerpt", ""))
    packets.append(
        _packet(
            packet_id="packet_0_fast",
            packet_type="fast",
            lane=str(round0.get("lane", "") or "micro_fast"),
            budget_tag=str(round0.get("budget_tag", "") or "stage124_fast_packet"),
            sent=True,
            send_reason=str(round0.get("condition", "") or "always_run_first_packet"),
            cache_hint=cache_hint,
            estimated_tokens=fast_tokens,
            elapsed_ms=fast_elapsed,
            tool_need=tool_need,
            memory_need=memory_need,
            uncertainty=uncertainty,
            grounding_status=grounding_status,
            memory_alignment_status=memory_alignment_status,
            stage142_status=stage142_status,
        )
    )

    stop_reason = _stage142_stop_reason(novelty)
    if deep_sent:
        deep = deep_round or {
            "purpose": "deep_continuation",
            "lane": str(debug.get("lane", "") or "subject_main"),
            "budget_tag": "chat_reply",
            "condition": "fast_packet_deep_packet_needed",
        }
        deep_tokens = _token_usage(main_usage)
        if deep_tokens <= 0:
            deep_tokens = _int(policy.get("target_input_tokens"), 0) + _int(policy.get("output_budget_tokens"), 0)
        if deep_tokens <= 0:
            deep_tokens = _estimate_tokens_from_chars(stream.get("fast_context_chars", 0), debug.get("prompt_excerpt", ""))
        if not stop_reason:
            stop_reason = "deep_packet_completed"
        packets.append(
            _packet(
                packet_id="packet_1_deep",
                packet_type="deep",
                lane=str(deep.get("lane", "") or "subject_main"),
                budget_tag=str(deep.get("budget_tag", "") or "chat_reply"),
                sent=True,
                send_reason=str(deep.get("condition", "") or "fast_packet_deep_packet_needed"),
                cache_hint=cache_hint,
                estimated_tokens=deep_tokens,
                elapsed_ms=deep_elapsed,
                tool_need=tool_need,
                memory_need=memory_need,
                uncertainty=uncertainty,
                grounding_status=grounding_status,
                memory_alignment_status=memory_alignment_status,
                stage142_status=stage142_status,
                stop_reason=stop_reason,
            )
        )
    else:
        skip_reason = str(stream.get("stop_reason", "") or "deep_packet_not_requested")
        if not stop_reason:
            stop_reason = skip_reason
        packets.append(
            _packet(
                packet_id="packet_1_deep_skipped",
                packet_type="skipped",
                lane=str((deep_round or {}).get("lane", "") or "subject_main"),
                budget_tag=str((deep_round or {}).get("budget_tag", "") or "chat_reply"),
                sent=False,
                skip_reason=skip_reason,
                cache_hint=cache_hint,
                estimated_tokens=0,
                elapsed_ms=0,
                tool_need=tool_need,
                memory_need=memory_need,
                uncertainty=uncertainty,
                grounding_status=grounding_status,
                memory_alignment_status=memory_alignment_status,
                stage142_status=stage142_status,
                stop_reason=stop_reason,
            )
        )

    tool_rounds = _int(loop.get("round_count"), 0)
    if tool_rounds > 0 and loop.get("executed_tools"):
        packets.append(
            _packet(
                packet_id="packet_tool_followup_" + stable_digest(str(loop.get("executed_tools", "")), limit=8),
                packet_type="tool_followup",
                lane=str(debug.get("lane", "") or channel or "subject_main"),
                budget_tag="tool_followup",
                sent=True,
                send_reason="provider_tool_loop_observed",
                cache_hint=cache_hint,
                estimated_tokens=_estimate_tokens_from_chars(len(str(loop)) * 2),
                elapsed_ms=_int(loop.get("elapsed_ms"), 0),
                tool_need=True,
                memory_need=memory_need,
                uncertainty=uncertainty,
                grounding_status=grounding_status,
                memory_alignment_status=memory_alignment_status,
                stage142_status=stage142_status,
                stop_reason=stop_reason,
            )
        )

    sent_count = sum(1 for item in packets if bool(item.get("sent", False)))
    skipped_count = sum(1 for item in packets if not bool(item.get("sent", False)))
    continued_count = sum(1 for item in packets if bool(item.get("sent", False)) and item.get("packet_type") != "fast")
    total_estimated_tokens = sum(_int(item.get("estimated_tokens"), 0) for item in packets)
    total_elapsed_ms = sum(_int(item.get("elapsed_ms"), 0) for item in packets)
    if processor_elapsed:
        total_elapsed_ms = max(total_elapsed_ms, processor_elapsed)

    return {
        "schema": STAGE143_SCHEMA,
        "packet_count": len(packets),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "continued_count": continued_count,
        "stop_reason": stop_reason or "completed",
        "total_estimated_tokens": total_estimated_tokens,
        "total_elapsed_ms": total_elapsed_ms,
        "packets": packets,
    }


def build_stage143_packet_budget_report(**kwargs: Any) -> dict[str, Any]:
    return build_stage143_packet_budget(**kwargs)
