from __future__ import annotations

import hashlib
import re
from typing import Any

STAGE105_SCHEMA = "holo.stage105.provider_packet_stream.v1"

RECALL_HINTS = (
    "\u56de\u5fc6",
    "\u8bb0\u5f97",
    "\u60f3\u8d77",
    "\u4efb\u4f55\u4e8b\u60c5",
    "remember",
    "recall",
    "memory",
    "earlier",
    "before",
)

LOOKUP_HINTS = (
    "\u67e5",
    "\u641c",
    "\u6700\u65b0",
    "\u7f51\u4e0a",
    "latest",
    "lookup",
    "search",
    "web",
)

NO_SEND_ACTIONS = {"silence", "defer_reply"}


def _stable_id(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _selected_action(packet: dict[str, Any]) -> dict[str, Any]:
    selected = packet.get("selected_action", {})
    return dict(selected) if isinstance(selected, dict) else {}


def _action_type(packet: dict[str, Any]) -> str:
    return str(_selected_action(packet).get("action_type", "") or "").strip()


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for hint in hints:
        normalized = hint.lower()
        if normalized.isascii():
            if re.search(rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])", lowered):
                return True
        elif normalized in lowered:
            return True
    return False


def _is_broad_recall(query: str) -> bool:
    return _contains_any(str(query or ""), RECALL_HINTS)


def _lookup_needed(packet: dict[str, Any], query: str) -> bool:
    if _action_type(packet) == "external_lookup":
        return True
    if str(packet.get("lookup_reason", "") or "").strip():
        return True
    if _contains_any(str(query or ""), LOOKUP_HINTS):
        return True
    return _safe_float(packet.get("uncertainty_level"), 0.0) >= 0.78


def _tool_requests(packet: dict[str, Any], query: str) -> list[dict[str, Any]]:
    if not _lookup_needed(packet, query):
        return []
    reason = str(packet.get("lookup_reason", "") or _selected_action(packet).get("why_now", "") or "provider packet stream requires external evidence").strip()
    return [
        {
            "name": "external_lookup",
            "reason": reason,
            "payload": {
                "query": str(query or ""),
                "source": "stage105.provider_packet_stream",
            },
        }
    ]


def _semantic_attractor_lines(packet: dict[str, Any]) -> list[str]:
    return [str(line).strip() for line in list(packet.get("semantic_attractor_lines", [])) if str(line).strip()]


def _memory_inputs(packet: dict[str, Any]) -> list[str]:
    lines = _semantic_attractor_lines(packet)
    lines.extend(str(line).strip() for line in list(packet.get("thread_recall_lines", []))[:3] if str(line).strip())
    return lines[:6]


def _packet_roles(count: int) -> list[str]:
    if count <= 0:
        return []
    if count == 1:
        return ["context_seed"]
    if count == 2:
        return ["context_seed", "reply_commit"]
    return ["context_seed", "deliberation_delta", "reply_commit"][:count]


def _packet_focus(role: str) -> str:
    return {
        "context_seed": "select compact memory, attractors, current user need, and action state",
        "deliberation_delta": "distill provider output into semantic delta, uncertainty shift, and tool affordance",
        "reply_commit": "commit final answer or stop condition with minimal additional context",
    }.get(role, "continue bounded provider packet stream")


def _compression_rule(role: str) -> str:
    if role == "context_seed":
        return "Compress archive, working memory, Stage104 attractors, and selected action into one finite provider packet."
    if role == "deliberation_delta":
        return "Compress the previous provider response into semantic delta, unresolved uncertainty, and tool affordance."
    if role == "reply_commit":
        return "Compress the final state into a user-facing reply plan and stop unless tool evidence is required."
    return "Keep only information needed for the next bounded provider packet."


def _build_packets(
    *,
    count: int,
    query: str,
    packet: dict[str, Any],
    packet_budget_tokens: int,
    timing: str,
) -> list[dict[str, Any]]:
    roles = _packet_roles(count)
    if not roles:
        return []
    per_packet_budget = max(384, int(packet_budget_tokens) // max(1, len(roles)))
    memory_inputs = _memory_inputs(packet)
    selected = _selected_action(packet)
    packets: list[dict[str, Any]] = []
    for index, role in enumerate(roles, start=1):
        packets.append(
            {
                "packet_id": f"stage105:{index}:{_stable_id(query, role, index)}",
                "index": index,
                "packet_role": role,
                "budget_tokens": per_packet_budget,
                "timing": timing,
                "focus": _packet_focus(role),
                "compression_rule": _compression_rule(role),
                "inputs": {
                    "query": str(query or ""),
                    "semantic_attractor_lines": memory_inputs[:4] if role == "context_seed" else [],
                    "selected_action": dict(selected) if role == "context_seed" else {},
                    "previous_output_required": role != "context_seed",
                },
                "output_contract": {
                    "semantic_delta": role != "context_seed",
                    "tool_affordance": role == "deliberation_delta",
                    "reply_commit": role == "reply_commit",
                    "must_distill_for_next_packet": role != "reply_commit",
                },
            }
        )
    return packets


def stage105_packet_stream_plan(
    packet: dict[str, Any],
    *,
    query: str,
    max_packets: int = 4,
    packet_budget_tokens: int = 2400,
    deadline_ms: int | None = None,
) -> dict[str, Any]:
    max_count = max(0, int(max_packets))
    action_type = _action_type(packet)
    uncertainty = max(0.0, min(1.0, _safe_float(packet.get("uncertainty_level"), 0.0)))
    attractor_count = len(_semantic_attractor_lines(packet))
    broad_recall = _is_broad_recall(query)
    tool_requests = _tool_requests(packet, query)
    deadline = _safe_int(deadline_ms, 0) if deadline_ms is not None else 0

    if action_type in NO_SEND_ACTIONS:
        packet_count = 0
        next_action = "no_send"
        stop_reason = f"{action_type}_selected"
        send_decision = "do_not_send"
        timing = "deferred" if action_type == "defer_reply" else "silent"
    elif tool_requests:
        packet_count = min(1, max_count)
        next_action = "tool_request"
        stop_reason = "tool_first"
        send_decision = "tool_first"
        timing = "tool_first"
    elif deadline and deadline <= 1200:
        packet_count = min(1, max_count)
        next_action = "provider_packet"
        stop_reason = "deadline_pressure"
        send_decision = "send_punctual"
        timing = "punctual"
    elif uncertainty <= 0.25 and not broad_recall:
        packet_count = min(1, max_count)
        next_action = "provider_packet"
        stop_reason = "sufficient_context"
        send_decision = "send_once"
        timing = "normal"
    elif broad_recall or uncertainty >= 0.55 or attractor_count >= 2:
        packet_count = min(3, max_count)
        next_action = "provider_packet"
        stop_reason = "bounded_stream_ready"
        send_decision = "send_multi" if packet_count > 1 else "send_once"
        timing = "normal"
    else:
        packet_count = min(2, max_count)
        next_action = "provider_packet"
        stop_reason = "moderate_uncertainty"
        send_decision = "send_multi" if packet_count > 1 else "send_once"
        timing = "normal"

    packets = _build_packets(
        count=packet_count,
        query=query,
        packet=packet,
        packet_budget_tokens=packet_budget_tokens,
        timing=timing,
    )
    return {
        "schema": STAGE105_SCHEMA,
        "stage": 105,
        "query": str(query or ""),
        "packet_count": len(packets),
        "packets": packets,
        "next_action": next_action,
        "stop_reason": stop_reason,
        "tool_requests": tool_requests,
        "policy": {
            "send_decision": send_decision,
            "max_packets": max_count,
            "packet_budget_tokens": int(packet_budget_tokens),
            "uncertainty_level": uncertainty,
            "semantic_attractor_count": attractor_count,
            "broad_recall": broad_recall,
            "deadline_ms": deadline,
            "action_type": action_type,
        },
        "visualization": {
            "nodes": [
                {"id": item["packet_id"], "label": item["packet_role"], "kind": "provider_packet"}
                for item in packets
            ],
            "edges": [
                {
                    "source": packets[index - 1]["packet_id"],
                    "target": packets[index]["packet_id"],
                    "label": "distill_and_repack",
                }
                for index in range(1, len(packets))
            ],
        },
    }


def inject_stage105_packet_stream(packet: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    injected = dict(packet)
    summary = {
        "schema": str(plan.get("schema", STAGE105_SCHEMA)),
        "stage": 105,
        "packet_count": int(plan.get("packet_count", 0) or 0),
        "next_action": str(plan.get("next_action", "")),
        "stop_reason": str(plan.get("stop_reason", "")),
        "send_decision": str(dict(plan.get("policy", {})).get("send_decision", "")),
        "tool_requests": list(plan.get("tool_requests", [])),
    }
    injected["stage105"] = summary
    injected["provider_packet_stream"] = plan
    state = dict(injected.get("state", {})) if isinstance(injected.get("state", {}), dict) else {}
    state["stage105"] = summary
    injected["state"] = state
    return injected
