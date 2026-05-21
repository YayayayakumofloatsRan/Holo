from __future__ import annotations

import hashlib
from typing import Any

STAGE107_SCHEMA = "holo.stage107.provider_interaction_loop.v1"


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _compact_text(text: Any, budget_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    limit = max(24, int(budget_chars or 0))
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _tool_calls(provider_return: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(provider_return.get("tool_calls", []) or []) if isinstance(item, dict)]


def compress_provider_delta(provider_return: dict[str, Any], *, budget_chars: int = 220) -> dict[str, Any]:
    text = str(provider_return.get("text", "") or "").strip()
    tool_calls = _tool_calls(provider_return)
    accepted_tool_names = [
        str(item.get("name", "") or "").strip()
        for item in tool_calls
        if bool(item.get("allowed", False)) and str(item.get("name", "") or "").strip()
    ]
    summary_source = text
    if accepted_tool_names:
        summary_source = (summary_source + " " if summary_source else "") + "provider requested tool: " + ", ".join(accepted_tool_names)
    summary = _compact_text(summary_source, budget_chars)
    return {
        "available": bool(summary),
        "summary": summary,
        "digest": _stable_digest(summary, accepted_tool_names),
        "tool_call_count": len(tool_calls),
        "accepted_tool_names": accepted_tool_names,
        "requires_tool": bool(accepted_tool_names),
    }


def _event_id(loop_id: str, index: int, phase: str) -> str:
    return f"{loop_id}:event:{index}:{phase}"


def _event(
    *,
    loop_id: str,
    index: int,
    phase: str,
    packet_id: str = "",
    packet_role: str = "",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "event_id": _event_id(loop_id, index, phase),
        "index": index,
        "phase": phase,
        "packet_id": packet_id,
        "packet_role": packet_role,
        "inputs": dict(inputs or {}),
        "metadata": dict(metadata or {}),
    }
    payload.update(extra)
    return payload


def _provider_return_at(provider_returns: Any, index: int) -> dict[str, Any] | None:
    rows = [dict(item) for item in list(provider_returns or []) if isinstance(item, dict)]
    if index >= len(rows):
        return None
    return rows[index]


def _observation_summary(tool_observations: Any) -> str:
    summaries: list[str] = []
    for item in list(tool_observations or []):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary", "") or item.get("text", "") or "").strip()
        if summary:
            summaries.append(summary)
    return _compact_text(" | ".join(summaries), 360)


def _tool_request_from_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(call.get("name", "") or "").strip(),
        "reason": "provider requested an allowlisted local tool",
        "payload": dict(call.get("arguments", {}) or {}),
        "provider_call_id": str(call.get("id", "") or ""),
    }


def _packet_inputs(packet: dict[str, Any], previous_delta: dict[str, Any], observation_summary: str) -> dict[str, Any]:
    inputs = dict(packet.get("inputs", {})) if isinstance(packet.get("inputs", {}), dict) else {}
    inputs["previous_delta"] = dict(previous_delta)
    if observation_summary:
        inputs["tool_observation_summary"] = observation_summary
    return inputs


def _visualization(events: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {
            "id": event["event_id"],
            "label": event["phase"],
            "kind": "interaction_event",
            "packet_role": event.get("packet_role", ""),
        }
        for event in events
    ]
    edges: list[dict[str, Any]] = []
    for index in range(1, len(events)):
        previous = events[index - 1]
        current = events[index]
        if previous["phase"] == "provider_packet" and current["phase"] == "provider_return":
            label = "provider_return"
        elif previous["phase"] == "provider_return" and current["phase"] == "distill_delta":
            label = "distill_and_repack"
        elif previous["phase"] == "distill_delta" and current["phase"] == "provider_packet":
            label = "next_packet"
        elif previous["phase"] == "tool_request" and current["phase"] == "tool_observation":
            label = "local_tool_result"
        elif previous["phase"] == "tool_observation" and current["phase"] == "provider_packet":
            label = "observation_packet"
        else:
            label = "advance"
        edges.append({"source": previous["event_id"], "target": current["event_id"], "label": label})
    return {"nodes": nodes, "edges": edges}


def build_stage107_interaction_loop(
    stage105_plan: dict[str, Any],
    *,
    provider_returns: list[dict[str, Any]] | None = None,
    tool_observations: list[dict[str, Any]] | None = None,
    delta_budget_chars: int = 220,
) -> dict[str, Any]:
    query = str(stage105_plan.get("query", "") or "")
    loop_id = f"stage107:{_stable_digest(query, stage105_plan.get('stop_reason', ''), stage105_plan.get('packet_count', 0))}"
    packets = [dict(item) for item in list(stage105_plan.get("packets", []) or []) if isinstance(item, dict)]
    tool_requests = [dict(item) for item in list(stage105_plan.get("tool_requests", []) or []) if isinstance(item, dict)]
    events: list[dict[str, Any]] = []
    previous_delta = {"available": False, "summary": "", "digest": "", "tool_call_count": 0, "requires_tool": False}
    observation_summary = _observation_summary(tool_observations)
    event_index = 1

    if str(stage105_plan.get("next_action", "") or "") == "no_send":
        reason = str(stage105_plan.get("stop_reason", "") or "no_send_selected")
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="stop",
                reason=reason,
                metadata={"send_provider_packet": False},
            )
        )
        return {
            "schema": STAGE107_SCHEMA,
            "stage": 107,
            "loop_id": loop_id,
            "query": query,
            "status": "complete",
            "next_action": "stop",
            "events": events,
            "visualization": _visualization(events),
            "stage105": {
                "packet_count": int(stage105_plan.get("packet_count", 0) or 0),
                "next_action": stage105_plan.get("next_action", ""),
                "stop_reason": stage105_plan.get("stop_reason", ""),
            },
        }

    if str(stage105_plan.get("next_action", "") or "") == "tool_request" and tool_requests:
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="tool_request",
                source="stage105_tool_first",
                tool_requests=tool_requests,
                metadata={"provider_may_execute_tools": False},
            )
        )
        event_index += 1
        if not observation_summary:
            return {
                "schema": STAGE107_SCHEMA,
                "stage": 107,
                "loop_id": loop_id,
                "query": query,
                "status": "awaiting_tool_observation",
                "next_action": "execute_tool_locally",
                "events": events,
                "visualization": _visualization(events),
                "stage105": {
                    "packet_count": int(stage105_plan.get("packet_count", 0) or 0),
                    "next_action": stage105_plan.get("next_action", ""),
                    "stop_reason": stage105_plan.get("stop_reason", ""),
                },
            }
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="tool_observation",
                inputs={"tool_observation_summary": observation_summary},
                observations=[dict(item) for item in list(tool_observations or []) if isinstance(item, dict)],
            )
        )
        event_index += 1

    provider_return_index = 0
    for packet in packets:
        packet_id = str(packet.get("packet_id", "") or "")
        packet_role = str(packet.get("packet_role", "") or "")
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="provider_packet",
                packet_id=packet_id,
                packet_role=packet_role,
                inputs=_packet_inputs(packet, previous_delta, observation_summary),
                metadata={
                    "enable_provider_tools": False,
                    "budget_tokens": int(packet.get("budget_tokens", 0) or 0),
                    "timing": str(packet.get("timing", "") or ""),
                },
            )
        )
        event_index += 1

        returned = _provider_return_at(provider_returns, provider_return_index)
        if returned is None:
            break
        provider_return_index += 1
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="provider_return",
                packet_id=packet_id,
                packet_role=packet_role,
                output=_compact_text(returned.get("text", ""), 360),
                tool_calls=_tool_calls(returned),
            )
        )
        event_index += 1

        previous_delta = compress_provider_delta(returned, budget_chars=delta_budget_chars)
        if previous_delta.get("requires_tool"):
            local_tool_requests = [_tool_request_from_call(call) for call in _tool_calls(returned) if bool(call.get("allowed", False))]
            events.append(
                _event(
                    loop_id=loop_id,
                    index=event_index,
                    phase="tool_request",
                    source="provider_tool_call",
                    tool_requests=local_tool_requests,
                    metadata={"provider_may_execute_tools": False},
                )
            )
            return {
                "schema": STAGE107_SCHEMA,
                "stage": 107,
                "loop_id": loop_id,
                "query": query,
                "status": "awaiting_tool_execution",
                "next_action": "execute_tool_locally",
                "events": events,
                "visualization": _visualization(events),
                "stage105": {
                    "packet_count": int(stage105_plan.get("packet_count", 0) or 0),
                    "next_action": stage105_plan.get("next_action", ""),
                    "stop_reason": stage105_plan.get("stop_reason", ""),
                },
            }
        events.append(
            _event(
                loop_id=loop_id,
                index=event_index,
                phase="distill_delta",
                packet_id=packet_id,
                packet_role=packet_role,
                delta=previous_delta,
                metadata={"delta_budget_chars": int(delta_budget_chars)},
            )
        )
        event_index += 1

    complete = bool(packets) and provider_returns is not None and provider_return_index >= len(packets)
    status = "complete" if complete and packets and packets[-1].get("packet_role") == "reply_commit" else "ready_to_continue"
    return {
        "schema": STAGE107_SCHEMA,
        "stage": 107,
        "loop_id": loop_id,
        "query": query,
        "status": status,
        "next_action": "stop" if status == "complete" else "send_provider_packet",
        "events": events,
        "visualization": _visualization(events),
        "stage105": {
            "packet_count": int(stage105_plan.get("packet_count", 0) or 0),
            "next_action": stage105_plan.get("next_action", ""),
            "stop_reason": stage105_plan.get("stop_reason", ""),
        },
        "compression": {
            "delta_budget_chars": int(delta_budget_chars),
            "latest_delta": previous_delta,
            "observation_summary": observation_summary,
        },
    }
