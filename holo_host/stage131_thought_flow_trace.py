from __future__ import annotations

from typing import Any

from .common import compact_text


def _safe_items(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = dict(payload or {}).get(key, [])
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("metadata", {})
    return dict(meta) if isinstance(meta, dict) else {}


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload", {})
    return dict(payload) if isinstance(payload, dict) else {}


def _row_thread_key(row: dict[str, Any]) -> str:
    return str(row.get("thread_key", "") or _metadata(row).get("thread_key", "") or "").strip()


def _matches_thread(row: dict[str, Any], thread_key: str) -> bool:
    wanted = str(thread_key or "").strip()
    if not wanted:
        return True
    found = _row_thread_key(row)
    return not found or found == wanted


def _action_from_entry(entry: dict[str, Any]) -> str:
    selected = str(entry.get("selected_action", "") or "").strip()
    if selected:
        return selected
    payload = _payload(entry)
    action = payload.get("selected_action", {})
    if isinstance(action, dict):
        return str(action.get("action_type", "") or "").strip()
    return ""


def _stage124_flags(entry: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(entry)
    stage124 = payload.get("stage124", {})
    if isinstance(stage124, dict) and stage124:
        return dict(stage124)
    result = payload.get("result", {})
    if isinstance(result, dict):
        nested = result.get("stage124", {})
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def _stage132_stream(entry: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(entry)
    direct = payload.get("stage132_progressive_stream", {})
    if isinstance(direct, dict) and direct:
        return dict(direct)
    result = payload.get("result", {})
    if isinstance(result, dict):
        nested = result.get("stage132_progressive_stream", {})
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def build_stage131_thought_flow_trace(
    *,
    usage_payload: dict[str, Any] | None,
    deliberation_payload: dict[str, Any] | None,
    thread_key: str,
    channel: str,
    chat_name: str,
    limit: int = 12,
) -> dict[str, Any]:
    usage_items = _safe_items(usage_payload, "items")[: max(1, int(limit))]
    deliberation_entries = [
        item
        for item in _safe_items(deliberation_payload, "entries")[: max(1, int(limit))]
        if _matches_thread(item, thread_key)
    ]
    summary = dict(dict(usage_payload or {}).get("summary", {})) if isinstance(dict(usage_payload or {}).get("summary", {}), dict) else {}
    total_tokens = int(summary.get("total_tokens", 0) or sum(int(row.get("total_tokens", 0) or 0) for row in usage_items))
    prompt_tokens = int(summary.get("total_prompt_tokens", 0) or sum(int(row.get("prompt_tokens", 0) or 0) for row in usage_items))
    completion_tokens = int(summary.get("total_completion_tokens", 0) or sum(int(row.get("completion_tokens", 0) or 0) for row in usage_items))
    by_lane = dict(summary.get("by_lane", {})) if isinstance(summary.get("by_lane", {}), dict) else {}

    reply_usage = [
        row
        for row in usage_items
        if str(row.get("task_type", "") or "").strip() == "reply" and _matches_thread(row, thread_key)
    ]
    background_usage = [
        row
        for row in usage_items
        if str(row.get("task_type", "") or "").strip() not in {"reply", "external_lookup", "tool_call"}
        or str(row.get("lane", "") or "").strip() == "background"
    ]

    latest_entry = deliberation_entries[0] if deliberation_entries else {}
    latest_flags = _stage124_flags(latest_entry)
    latest_stage132 = _stage132_stream(latest_entry)
    fast_seen = bool(latest_flags.get("fast_packet_needed", False)) or any(
        str(row.get("lane", "") or "").strip() in {"micro_fast", "fast"} for row in reply_usage
    )
    deep_seen = bool(latest_flags.get("deep_packet_needed", False)) or any(
        str(row.get("lane", "") or "").strip() not in {"micro_fast", "fast", ""} for row in reply_usage
    )

    return {
        "stage": "stage131",
        "thread_key": str(thread_key or "").strip(),
        "channel": str(channel or "").strip(),
        "chat_name": str(chat_name or "").strip(),
        "usage": {
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "calls": len(usage_items),
            "by_lane": by_lane,
            "reply_calls": len(reply_usage),
            "background_calls": len(background_usage),
        },
        "packets": {
            "fast_seen": fast_seen,
            "deep_seen": deep_seen,
            "reply_usage": reply_usage[: max(1, int(limit))],
        },
        "stage132_stream": latest_stage132,
        "actions": [
            {
                "entry_type": str(entry.get("entry_type", "") or "").strip(),
                "selected_action": _action_from_entry(entry),
                "created_at": str(entry.get("created_at", "") or "").strip(),
            }
            for entry in deliberation_entries
        ],
        "background_usage": background_usage[: max(1, int(limit))],
        "deliberation_entries": deliberation_entries,
    }


def render_stage131_cli_ct(trace: dict[str, Any]) -> str:
    payload = dict(trace or {})
    usage = dict(payload.get("usage", {})) if isinstance(payload.get("usage"), dict) else {}
    packets = dict(payload.get("packets", {})) if isinstance(payload.get("packets"), dict) else {}
    lines = [
        "STAGE131 BIOMIMETIC CT",
        f"THREAD channel={payload.get('channel', '-')} thread={payload.get('thread_key', '-')} chat={payload.get('chat_name', '-')}",
        (
            "USAGE "
            f"total_tokens={int(usage.get('total_tokens', 0) or 0)} "
            f"prompt={int(usage.get('prompt_tokens', 0) or 0)} "
            f"completion={int(usage.get('completion_tokens', 0) or 0)} "
            f"calls={int(usage.get('calls', 0) or 0)}"
        ),
    ]
    by_lane = dict(usage.get("by_lane", {})) if isinstance(usage.get("by_lane"), dict) else {}
    if by_lane:
        lane_bits = " ".join(f"{key}={value}" for key, value in sorted(by_lane.items()))
        lines.append(f"LANES {lane_bits}")
    lines.append(
        "FLOW sensory_input -> action_gate -> "
        f"FAST packet={'on' if bool(packets.get('fast_seen', False)) else 'off'} -> "
        f"DEEP packet={'on' if bool(packets.get('deep_seen', False)) else 'off'} -> "
        "tool_loop -> expression"
    )
    stream = dict(payload.get("stage132_stream", {})) if isinstance(payload.get("stage132_stream"), dict) else {}
    if stream:
        lines.append(
            "STAGE132 STREAM "
            f"rounds={int(stream.get('round_count', 0) or 0)} "
            f"cache={compact_text(str(stream.get('cache_hint', '-') or '-'), 32)} "
            f"context_lines={int(stream.get('fast_context_lines', 0) or 0)}"
        )
        for item in [dict(row) for row in stream.get("rounds", []) if isinstance(row, dict)][:5]:
            index = int(item.get("index", 0) or 0)
            lane = str(item.get("lane", "") or "-").strip()
            purpose = str(item.get("purpose", "") or "-").strip()
            visible = "yes" if bool(item.get("visible", False)) else "no"
            lines.append(f"ROUND {index} lane={lane} purpose={purpose} visible={visible}")

    actions = [dict(item) for item in payload.get("actions", []) if isinstance(item, dict)]
    if actions:
        for item in actions[:5]:
            action = str(item.get("selected_action", "") or "-").strip()
            entry_type = str(item.get("entry_type", "") or "-").strip()
            created_at = str(item.get("created_at", "") or "-").strip()
            lines.append(f"ACTION {action} entry={entry_type} at={created_at}")
    else:
        lines.append("ACTION - entry=- at=-")

    for row in [dict(item) for item in packets.get("reply_usage", []) if isinstance(item, dict)][:5]:
        task_type = str(row.get("task_type", "") or "-").strip()
        lane = str(row.get("lane", "") or "-").strip()
        provider = str(row.get("provider", "") or "-").strip()
        model = compact_text(str(row.get("model", "") or "-").strip(), 42)
        tokens = int(row.get("total_tokens", 0) or 0)
        duration_ms = int(row.get("duration_ms", 0) or 0)
        lines.append(f"PACKET {task_type} lane={lane} provider={provider} model={model} tokens={tokens} duration_ms={duration_ms}")

    for row in [dict(item) for item in payload.get("background_usage", []) if isinstance(item, dict)][:5]:
        task_type = str(row.get("task_type", "") or "-").strip()
        tokens = int(row.get("total_tokens", 0) or 0)
        provider = str(row.get("provider", "") or "-").strip()
        created_at = str(row.get("created_at", "") or "-").strip()
        lines.append(f"BACKGROUND {task_type} tokens={tokens} provider={provider} at={created_at}")

    return "\n".join(lines)
