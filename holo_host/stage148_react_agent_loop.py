from __future__ import annotations

import re
import json
from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE148_SCHEMA = "holo.stage148.reusable_state_react_loop.v1"

PRIOR_CONTEXT_HINTS = (
    "刚刚",
    "刚才",
    "上句",
    "上一句",
    "三句以前",
    "几句以前",
    "之前说",
    "前面说",
    "我们之前",
    "刚说",
    "what did i say",
    "what happened",
    "previous",
    "earlier",
    "before",
)

CORRECTION_HINTS = (
    "不要",
    "别",
    "少",
    "别再",
    "不许",
    "收住",
    "avoid",
    "do not",
    "don't",
    "less",
    "fewer",
)

QUESTION_HINTS = ("?", "？", "什么", "怎么", "为什么", "如何", "吗", "what", "why", "how", "which")


def _compact(value: Any, limit: int = 160) -> str:
    return compact_text(" ".join(str(value or "").strip().split()), limit)


def _digest_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return stable_digest(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return stable_digest(str(value or ""))


def _clamp(value: float, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return round(max(0.0, min(1.0, number)), 4)


def _message_text(row: dict[str, Any]) -> str:
    return str(row.get("body_text", row.get("text", "")) or "").strip()


def _direction(row: dict[str, Any]) -> str:
    raw = str(row.get("direction", "") or "").strip().lower()
    if raw in {"inbound", "user", "external_user"}:
        return "user"
    if raw in {"outbound", "assistant", "holo"}:
        return "holo"
    return raw or "unknown"


def _event_rows(
    *,
    user_text: str,
    channel: str,
    thread_key: str,
    chat_name: str,
    sender: str,
    history: list[dict[str, Any]] | None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(list(history or [])[-limit:]):
        if not isinstance(item, dict):
            continue
        text = _message_text(item)
        if not text:
            continue
        direction = _direction(item)
        event_id = str(item.get("id", "") or item.get("message_id", "") or stable_digest(direction, text, str(index)))
        rows.append(
            {
                "event_id": event_id,
                "ordinal": len(rows) + 1,
                "direction": direction,
                "channel": str(item.get("channel", "") or channel),
                "thread_key": str(item.get("thread_key", "") or thread_key),
                "chat_name": str(item.get("subject", "") or item.get("chat_name", "") or chat_name),
                "speaker": str(item.get("sender_name", "") or sender if direction == "user" else "Holo"),
                "text": _compact(text, 220),
                "time": str(item.get("created_at", "") or item.get("received_at", "") or ""),
                "source": "message_history",
            }
        )
    current = _compact(user_text, 220)
    if current and not any(row.get("direction") == "user" and row.get("text") == current for row in rows[-2:]):
        rows.append(
            {
                "event_id": f"current:{stable_digest(channel, thread_key, current)}",
                "ordinal": len(rows) + 1,
                "direction": "user",
                "channel": channel,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "speaker": sender or chat_name or "user",
                "text": current,
                "time": utc_now(),
                "source": "current_turn",
            }
        )
    for index, row in enumerate(rows):
        row["ordinal"] = index + 1
    return rows[-limit:]


def _has_prior_context_need(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(hint in lowered or hint in text for hint in PRIOR_CONTEXT_HINTS)


def _is_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(hint in lowered or hint in text for hint in QUESTION_HINTS)


def _extract_constraint_slots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for row in events:
        if row.get("direction") != "user":
            continue
        text = str(row.get("text", "") or "")
        lowered = text.lower()
        if not any(hint in lowered or hint in text for hint in CORRECTION_HINTS):
            continue
        if "emoji" in lowered or "表情" in text:
            summary = "avoid frequent emoji and emoticons; user correction should persist across channels"
        elif "英文" in text or "english" in lowered:
            summary = "respect the user's language correction in visible speech"
        elif "说教" in text or "客服" in text or "lecture" in lowered:
            summary = "avoid lecture-like or customer-service tone"
        else:
            summary = f"user correction: {_compact(text, 110)}"
        slots.append(
            {
                "slot_id": f"constraint:{stable_digest(summary)}",
                "slot_type": "recent_correction",
                "summary": summary,
                "source_event_ids": [str(row.get("event_id", ""))],
                "priority": 0.92,
                "freshness": 0.92,
                "confidence": 0.86,
                "reusable": True,
            }
        )
    return slots[-4:]


def _unresolved_question_slots(events: list[dict[str, Any]], current_text: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    prior_user_questions = [row for row in events[:-1] if row.get("direction") == "user" and _is_question(str(row.get("text", "")))]
    if prior_user_questions:
        row = prior_user_questions[-1]
        slots.append(
            {
                "slot_id": f"unresolved:{stable_digest(row.get('event_id', ''), row.get('text', ''))}",
                "slot_type": "unresolved_question",
                "summary": f"recent user question may still be active: {_compact(row.get('text', ''), 120)}",
                "source_event_ids": [str(row.get("event_id", ""))],
                "priority": 0.74,
                "freshness": 0.78,
                "confidence": 0.64,
                "reusable": True,
            }
        )
    if _has_prior_context_need(current_text):
        slots.append(
            {
                "slot_id": f"unresolved:current:{stable_digest(current_text)}",
                "slot_type": "unresolved_question",
                "summary": "current turn asks for prior context; answer from event observations rather than impression",
                "source_event_ids": [str(events[-1].get("event_id", ""))] if events else [],
                "priority": 0.88,
                "freshness": 1.0,
                "confidence": 0.82,
                "reusable": True,
            }
        )
    return slots[-3:]


def _action_space(sidecar: dict[str, Any], capability_context: dict[str, Any] | None) -> list[str]:
    actions = ["direct_answer", "memory_recall", "tool_first", "clarify", "reply_multi", "defer"]
    for item in list(sidecar.get("action_market_v4", sidecar.get("action_market", [])) or []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action_type", "") or "").strip()
        if action and action not in actions:
            actions.append(action)
    for item in list((capability_context or {}).get("tool_requests", []) or []):
        name = str((item or {}).get("name", "") if isinstance(item, dict) else "").strip()
        if name and f"tool:{name}" not in actions:
            actions.append(f"tool:{name}")
    return actions[:12]


def _select_action_hint(
    *,
    user_text: str,
    sidecar: dict[str, Any],
    capability_context: dict[str, Any] | None,
    memory_alignment: dict[str, Any] | None,
    tool_grounding: dict[str, Any] | None,
) -> tuple[str, list[str], str]:
    selected_action = dict(sidecar.get("selected_action", {})) if isinstance(sidecar.get("selected_action", {}), dict) else {}
    selected_type = str(selected_action.get("action_type", "") or "").strip()
    memory_status = str((memory_alignment or {}).get("status", "") or "")
    tool_status = str((tool_grounding or {}).get("status", "") or "")
    tool_requests = list((capability_context or {}).get("tool_requests", []) or [])
    if _has_prior_context_need(user_text):
        return "memory_recall", ["recent_event_log", "working_state_slots"], "prior_context_query"
    if memory_status in {"unsupported_memory_detail", "contradicted_memory_detail"}:
        return "memory_recall", ["memory_observation_ledger", "memory_alignment"], "memory_claim_needs_observation"
    if tool_status == "ungrounded_tool_claim" or selected_type == "external_lookup" or tool_requests:
        return "tool_first", ["tool_observation_ledger"], "tool_or_external_fact_needed"
    if selected_type == "defer_reply":
        return "defer", ["temporal_commitment_state"], "selected_action_defer"
    if selected_type == "reply_multi":
        return "reply_multi", ["current_working_state"], "selected_action_reply_multi"
    if len(str(user_text or "").strip()) <= 2:
        return "clarify", ["recent_event_log"], "low_signal_turn"
    return "direct_answer", ["current_user_turn", "working_state_slots"], "sufficient_current_context"


def build_stage148_react_state(
    *,
    user_text: str,
    channel: str,
    thread_key: str,
    chat_name: str,
    sender: str = "",
    history: list[dict[str, Any]] | None = None,
    sidecar: dict[str, Any] | None = None,
    capability_context: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    stage143_packet_budget: dict[str, Any] | None = None,
    stage144_context_economy: dict[str, Any] | None = None,
    stage145_outcome_appraisal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = dict(sidecar or {})
    events = _event_rows(
        user_text=user_text,
        channel=channel,
        thread_key=thread_key,
        chat_name=chat_name,
        sender=sender,
        history=history,
    )
    current_event_id = str(events[-1].get("event_id", "")) if events else ""
    slots: list[dict[str, Any]] = [
        {
            "slot_id": f"current:{stable_digest(channel, thread_key, user_text)}",
            "slot_type": "current_user_turn",
            "summary": _compact(user_text, 180),
            "source_event_ids": [current_event_id] if current_event_id else [],
            "priority": 1.0,
            "freshness": 1.0,
            "confidence": 1.0,
            "reusable": True,
        }
    ]
    slots.extend(_extract_constraint_slots(events))
    slots.extend(_unresolved_question_slots(events, user_text))
    selected_action = dict(packet.get("selected_action", {})) if isinstance(packet.get("selected_action", {}), dict) else {}
    if selected_action:
        slots.append(
            {
                "slot_id": f"action:{_digest_value(selected_action)}",
                "slot_type": "active_task",
                "summary": f"selected_action={selected_action.get('action_type', 'unknown')}; rationale={_compact(selected_action.get('action_rationale', selected_action.get('why_now', '')), 100)}",
                "source_event_ids": [current_event_id] if current_event_id else [],
                "priority": 0.78,
                "freshness": 0.9,
                "confidence": _clamp(selected_action.get("score", 0.74), default=0.74),
                "reusable": True,
            }
        )
    actions = _action_space(packet, capability_context)
    slots.append(
        {
            "slot_id": f"action_space:{_digest_value(actions)}",
            "slot_type": "action_space",
            "summary": ", ".join(actions),
            "source_event_ids": [current_event_id] if current_event_id else [],
            "priority": 0.72,
            "freshness": 1.0,
            "confidence": 0.86,
            "reusable": True,
        }
    )
    selected_hint, required_observations, plan_reason = _select_action_hint(
        user_text=user_text,
        sidecar=packet,
        capability_context=capability_context,
        memory_alignment=memory_alignment,
        tool_grounding=tool_grounding,
    )
    if stage144_context_economy:
        recommendation = str(stage144_context_economy.get("recommended_deep_policy", "") or "").strip()
        if recommendation:
            slots.append(
                {
                    "slot_id": f"policy:{stable_digest(recommendation)}",
                    "slot_type": "packet_policy",
                    "summary": f"shadow packet policy recommendation={recommendation}",
                    "source_event_ids": [current_event_id] if current_event_id else [],
                    "priority": 0.52,
                    "freshness": 0.74,
                    "confidence": _clamp(stage144_context_economy.get("confidence", 0.5), default=0.5),
                    "reusable": True,
                }
            )
    observe_summary = "; ".join(
        part
        for part in [
            f"current={_compact(user_text, 90)}",
            f"recent_events={len(events)}",
            f"constraints={len([slot for slot in slots if slot['slot_type'] == 'recent_correction'])}",
            f"selected_action={selected_action.get('action_type', '') or 'unknown'}",
        ]
        if part
    )
    return {
        "schema": STAGE148_SCHEMA,
        "stage": "stage148-reusable-state-react-loop",
        "event_log": {
            "retention": "raw_recent_turns",
            "event_count": len(events),
            "events": events,
            "latest_event_id": current_event_id,
            "cross_channel_thread_key": thread_key,
        },
        "reusable_state_memory": {
            "memory_is_not_chat_log": True,
            "state_families": [
                "working",
                "semantic",
                "procedural",
                "episodic",
                "policy",
                "action_observation",
            ],
            "slots": slots[:12],
            "slot_count": min(len(slots), 12),
        },
        "react_loop": {
            "observe": {
                "status": "perceived",
                "summary": compact_text(observe_summary, 360),
                "source": "host_event_state",
            },
            "plan": {
                "selected_action_hint": selected_hint,
                "reason": plan_reason,
                "action_space": actions,
                "required_observations": required_observations,
                "should_answer_from_observation": selected_hint in {"memory_recall", "tool_first"},
            },
            "act": {
                "authority": "host_gated",
                "selected_action_type": str(selected_action.get("action_type", "") or selected_hint),
                "tool_execution_requires_host_observation": True,
                "memory_write_allowed": False,
            },
            "observe_after_action": {
                "status": "pending",
                "packet_stop_reason": str((stage143_packet_budget or {}).get("stop_reason", "") or ""),
                "memory_status": str((memory_grounding or {}).get("status", "") or ""),
                "memory_alignment_status": str((memory_alignment or {}).get("status", "") or ""),
                "prediction_error": _clamp((stage145_outcome_appraisal or {}).get("prediction_error", 0.0), default=0.0),
            },
        },
        "shadow_only": False,
        "provider_call_added": False,
        "memory_write_added": False,
    }


def stage148_prompt_lines(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict) or not report:
        return []
    memory = report.get("reusable_state_memory", {})
    react = report.get("react_loop", {})
    event_log = report.get("event_log", {})
    slots = [slot for slot in list((memory if isinstance(memory, dict) else {}).get("slots", [])) if isinstance(slot, dict)]
    plan = dict((react if isinstance(react, dict) else {}).get("plan", {}))
    events = [event for event in list((event_log if isinstance(event_log, dict) else {}).get("events", [])) if isinstance(event, dict)]
    lines = [
        "memory_is_state_not_chat_log=true",
        f"react_plan={plan.get('selected_action_hint', 'direct_answer')} reason={plan.get('reason', '')}",
        "action_space=" + ", ".join(str(item) for item in list(plan.get("action_space", []))[:8]),
    ]
    for slot in slots[:8]:
        slot_type = str(slot.get("slot_type", "") or "slot")
        summary = _compact(slot.get("summary", ""), 140)
        if summary:
            lines.append(f"state:{slot_type}: {summary}")
    for event in events[-5:]:
        direction = str(event.get("direction", "") or "event")
        text = _compact(event.get("text", ""), 120)
        if text:
            lines.append(f"recent_event:{direction}: {text}")
    return [line for line in lines if str(line).strip()][:16]
