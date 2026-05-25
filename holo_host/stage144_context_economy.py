from __future__ import annotations

import math
import re
from typing import Any

from .common import compact_text, stable_digest

STAGE144_SCHEMA = "holo.stage144.context_economy.v1"

SLOT_TYPES = {
    "current_user_constraint",
    "active_task",
    "unresolved_question",
    "recent_correction",
    "memory_anchor",
    "tool_observation",
    "visual_observation",
    "risk_permission",
    "packet_budget",
    "novelty_gate",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value or 0.0))), 4)


def _token_estimate(text: str) -> int:
    current = str(text or "")
    if not current:
        return 0
    return max(1, int(math.ceil(len(current) / 4.0)))


def _slot(
    *,
    slot_type: str,
    summary: str,
    priority: float,
    freshness: str = "current_turn",
    confidence: float = 0.6,
    include_reason: str = "",
    eviction_reason: str = "",
) -> dict[str, Any]:
    cleaned = compact_text(str(summary or ""), 260)
    digest = stable_digest(slot_type, cleaned, freshness, limit=10)
    return {
        "slot_id": f"{slot_type}:{digest}",
        "slot_type": slot_type if slot_type in SLOT_TYPES else "active_task",
        "summary": cleaned,
        "priority": _clamp(priority),
        "freshness": str(freshness or "current_turn"),
        "confidence": _clamp(confidence),
        "token_estimate": _token_estimate(cleaned),
        "include_reason": include_reason or f"{slot_type}_evidence",
        "eviction_reason": eviction_reason,
    }


def _status(report: Any) -> str:
    return str(_dict(report).get("status", "") or "").strip()


def _recent_lines(sidecar: dict[str, Any], reply_debug: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for source in (
        _dict(sidecar.get("recent_dialogue_window", {})).get("lines", []),
        _dict(reply_debug.get("recent_dialogue_window", {})).get("lines", []),
        reply_debug.get("thread_recall_lines", []),
    ):
        if isinstance(source, list):
            lines.extend(compact_text(str(item), 220) for item in source if str(item).strip())
    return lines[-6:]


def _correction_lines(lines: list[str], user_text: str) -> list[str]:
    markers = (
        "correction",
        "correct",
        "don't",
        "do not",
        "less emoji",
        "fewer emoji",
        "\u4e0d\u8981",
        "\u522b",
        "\u5c11\u7528",
        "\u4fee\u6b63",
        "\u66f4\u6b63",
        "emoji",
    )
    candidates = [str(user_text or "")] + list(lines or [])
    return [compact_text(line, 220) for line in candidates if any(marker in line.lower() for marker in markers)]


def _selected_action_summary(selected_action: Any, sidecar: dict[str, Any]) -> str:
    action = _dict(selected_action) or _dict(sidecar.get("selected_action", {}))
    if not action:
        return ""
    action_type = str(action.get("action_type", "") or "reply_once")
    score = action.get("score", action.get("confidence", ""))
    return f"selected_action={action_type}; score={score}"


def _active_state_summary(active_thread_state: Any, sidecar: dict[str, Any]) -> str:
    state = _dict(active_thread_state) or _dict(sidecar.get("active_thread_state", {}))
    continuity = compact_text(str(state.get("continuity_summary", "") or ""), 180)
    scene = compact_text(str(_dict(state.get("scene_state", {})).get("shared_frame", "") or ""), 160)
    return "; ".join(part for part in [continuity, scene] if part)


def _visual_summary(visual_memory: Any, sidecar: dict[str, Any], reply_debug: dict[str, Any]) -> str:
    visual = _dict(visual_memory) or _dict(sidecar.get("visual_memory", {})) or _dict(sidecar.get("visual_field", {})) or _dict(reply_debug.get("visual_ingest", {}))
    return compact_text(str(visual.get("summary", "") or visual.get("caption", "") or visual.get("status", "") or ""), 220)


def _risk_summary(risk_permission: Any, sidecar: dict[str, Any], reply_debug: dict[str, Any]) -> str:
    risk = _dict(risk_permission)
    if not risk:
        risk = {
            "risk_tags": list(sidecar.get("risk_tags", []) or reply_debug.get("risk_tags", []) or []),
            "approved_tool_permissions": list(sidecar.get("approved_tool_permissions", []) or reply_debug.get("approved_tool_permissions", []) or []),
            "tool_permission_grants": list(sidecar.get("tool_permission_grants", []) or reply_debug.get("tool_permission_grants", []) or []),
        }
    parts: list[str] = []
    for key in ("risk_tags", "approved_tool_permissions", "tool_permission_grants"):
        value = risk.get(key)
        if value:
            parts.append(f"{key}={compact_text(str(value), 120)}")
    return "; ".join(parts)


def _bounded_slots(slots: list[dict[str, Any]], max_slots: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for slot in slots:
        if not slot.get("summary"):
            continue
        key = f"{slot.get('slot_type')}:{slot.get('summary')}"
        current = unique.get(key)
        if current is None or float(slot.get("priority", 0.0) or 0.0) > float(current.get("priority", 0.0) or 0.0):
            unique[key] = slot
    ordered = sorted(unique.values(), key=lambda item: (float(item.get("priority", 0.0) or 0.0), float(item.get("confidence", 0.0) or 0.0)), reverse=True)
    kept = ordered[: max(1, int(max_slots or 12))]
    return kept


def _packet_deep_sent(packet_budget: dict[str, Any]) -> bool:
    return any(str(packet.get("packet_type", "")) == "deep" and bool(packet.get("sent", False)) for packet in _list_dicts(packet_budget.get("packets", [])))


def _recommend_policy(
    *,
    tool_grounding: dict[str, Any],
    memory_alignment: dict[str, Any],
    memory_grounding: dict[str, Any],
    novelty: dict[str, Any],
    packet_budget: dict[str, Any],
    uncertainty: float,
) -> tuple[str, str, float]:
    tool_status = _status(tool_grounding)
    memory_alignment_status = _status(memory_alignment)
    memory_grounding_status = _status(memory_grounding)
    novelty_status = _status(novelty)
    stop_reason = str(packet_budget.get("stop_reason", "") or "")

    if tool_status == "ungrounded_tool_claim":
        return "tool_first", "tool_first: collect an actual tool observation before allowing visible tool claims.", 0.86
    if memory_alignment_status in {"unsupported_memory_detail", "contradicted_memory_detail"} or memory_grounding_status in {
        "ungrounded_memory_claim",
        "weak_memory_source",
        "contradicted_memory_claim",
    }:
        return "memory_first", "memory_first: retrieve or bound memory evidence before stating recall details.", 0.84
    if novelty_status == "suppressed_duplicate" or stop_reason == "stage142:suppressed_duplicate":
        return "skip", "skip/defer: deep packet produced low-novelty duplicate visible content.", 0.78
    if novelty_status in {"blocked_ungrounded_claim", "repaired_contradiction"} or stop_reason.startswith("stage142:"):
        return "defer", "defer: continuation was blocked or repaired by visible-expression gates.", 0.72
    if uncertainty >= 0.72 and not _packet_deep_sent(packet_budget):
        return "defer", "defer: uncertainty is high and current evidence is insufficient for confident deep continuation.", 0.64
    if _packet_deep_sent(packet_budget) and novelty_status in {"", "passed"}:
        return "keep", "keep: deep continuation appears useful and non-suppressed in this turn.", 0.68
    return "keep", "keep: current packet policy has no strong diagnostic reason to change.", 0.55


def _scores(
    *,
    slots: list[dict[str, Any]],
    tool_grounding: dict[str, Any],
    memory_grounding: dict[str, Any],
    memory_alignment: dict[str, Any],
    novelty: dict[str, Any],
    packet_budget: dict[str, Any],
) -> tuple[float, float]:
    sufficiency = 0.48
    waste = 0.18
    slot_types = {str(slot.get("slot_type", "")) for slot in slots}
    if "current_user_constraint" in slot_types:
        sufficiency += 0.08
    if "tool_observation" in slot_types or _status(tool_grounding) == "grounded":
        sufficiency += 0.13
    if "memory_anchor" in slot_types or _status(memory_grounding) == "grounded" or _status(memory_alignment) == "aligned":
        sufficiency += 0.13
    if _status(novelty) == "passed":
        sufficiency += 0.08
    if _status(tool_grounding) == "ungrounded_tool_claim":
        sufficiency -= 0.22
        waste += 0.12
    if _status(memory_alignment) in {"unsupported_memory_detail", "contradicted_memory_detail"}:
        sufficiency -= 0.22
        waste += 0.1
    if _status(memory_grounding) in {"ungrounded_memory_claim", "weak_memory_source", "contradicted_memory_claim"}:
        sufficiency -= 0.18
        waste += 0.08
    if _status(novelty) == "suppressed_duplicate" or str(packet_budget.get("stop_reason", "")) == "stage142:suppressed_duplicate":
        waste += 0.52
        sufficiency -= 0.08
    if _packet_deep_sent(packet_budget):
        waste += 0.08
    if int(packet_budget.get("skipped_count", 0) or 0) > 0:
        waste -= 0.06
    if len(slots) > 9:
        waste += 0.06
    return _clamp(sufficiency), _clamp(waste)


def build_stage144_context_economy(
    *,
    user_text: str = "",
    selected_action: dict[str, Any] | None = None,
    active_thread_state: dict[str, Any] | None = None,
    recent_dialogue_window: dict[str, Any] | None = None,
    tool_observation_ledger: list[dict[str, Any]] | None = None,
    memory_observation_ledger: list[dict[str, Any]] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    stage142_semantic_novelty: dict[str, Any] | None = None,
    stage143_packet_budget: dict[str, Any] | None = None,
    visual_memory: dict[str, Any] | None = None,
    risk_permission: dict[str, Any] | None = None,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    max_slots: int = 12,
) -> dict[str, Any]:
    """Build a shadow-only context economy recommendation.

    Stage144 is diagnostic. It never changes packet policy, sends, memory, tools,
    provider calls, or transport behavior by itself.
    """

    packet = _dict(sidecar)
    debug = _dict(reply_debug)
    selected = _dict(selected_action) or _dict(packet.get("selected_action", {}))
    active = _dict(active_thread_state) or _dict(packet.get("active_thread_state", {}))
    recent = _dict(recent_dialogue_window) or _dict(packet.get("recent_dialogue_window", {}))
    tools = _list_dicts(tool_observation_ledger if tool_observation_ledger is not None else debug.get("tool_observation_ledger", []))
    memories = _list_dicts(memory_observation_ledger if memory_observation_ledger is not None else debug.get("memory_observation_ledger", []))
    memory_report = _dict(memory_grounding) or _dict(debug.get("memory_grounding", {}))
    alignment = _dict(memory_alignment) or _dict(debug.get("memory_alignment", {}))
    tool_report = _dict(tool_grounding) or _dict(debug.get("tool_grounding", {}))
    novelty = _dict(stage142_semantic_novelty) or _dict(debug.get("stage142_semantic_novelty", {}))
    packet_budget = _dict(stage143_packet_budget) or _dict(debug.get("stage143_packet_budget", {}))
    uncertainty = 0.0
    if packet_budget:
        packet_uncertainties = [_float(item.get("uncertainty"), 0.0) for item in _list_dicts(packet_budget.get("packets", []))]
        uncertainty = max(packet_uncertainties or [0.0])

    slots: list[dict[str, Any]] = []
    if user_text:
        slots.append(
            _slot(
                slot_type="current_user_constraint",
                summary=user_text,
                priority=0.96,
                confidence=0.92,
                include_reason="current external input must anchor the packet",
            )
        )
    action_summary = _selected_action_summary(selected, packet)
    if action_summary:
        slots.append(_slot(slot_type="active_task", summary=action_summary, priority=0.82, confidence=0.74, include_reason="selected action constrains response shape"))
    active_summary = _active_state_summary(active, packet)
    if active_summary:
        slots.append(_slot(slot_type="active_task", summary=active_summary, priority=0.72, freshness="thread_state", confidence=0.68, include_reason="thread continuity is bounded working context"))
    if str(user_text or "").strip().endswith("?") or str(user_text or "").strip().endswith("\uff1f"):
        slots.append(_slot(slot_type="unresolved_question", summary=user_text, priority=0.78, confidence=0.82, include_reason="current turn asks for an answer"))
    recent_lines = _recent_lines({**packet, "recent_dialogue_window": recent}, debug)
    for line in _correction_lines(recent_lines, user_text)[:3]:
        slots.append(_slot(slot_type="recent_correction", summary=line, priority=0.88, freshness="recent_dialogue", confidence=0.76, include_reason="recent correction should bias expression and retrieval"))
    for item in tools[:4]:
        summary = str(item.get("summary", "") or item.get("tool", "") or item.get("status", ""))
        slots.append(_slot(slot_type="tool_observation", summary=summary, priority=0.84, freshness="current_turn", confidence=0.8, include_reason="actual tool observations ground tool claims"))
    for item in memories[:5]:
        summary = str(item.get("summary", "") or item.get("source_family", "") or item.get("status", ""))
        confidence = _float(item.get("confidence"), 0.62)
        priority = 0.82 if str(item.get("status", "")) == "grounded" else 0.64
        slots.append(_slot(slot_type="memory_anchor", summary=summary, priority=priority, freshness=str(item.get("freshness", "") or "memory_ledger"), confidence=confidence, include_reason="memory observation can ground recall claims"))
    if alignment:
        slots.append(
            _slot(
                slot_type="memory_anchor",
                summary=f"memory_alignment status={alignment.get('status', '')}; unsupported={alignment.get('unsupported_claim_count', 0)}; contradicted={alignment.get('contradicted_claim_count', 0)}",
                priority=0.86 if _status(alignment) not in {"aligned", "no_memory_claim"} else 0.62,
                confidence=0.8,
                include_reason="memory claim sufficiency affects packet policy",
            )
        )
    if novelty:
        slots.append(
            _slot(
                slot_type="novelty_gate",
                summary=f"stage142 status={novelty.get('status', '')}; candidates={novelty.get('candidate_count', 0)}; suppressed={novelty.get('suppressed_count', 0)}",
                priority=0.78,
                confidence=0.78,
                include_reason="visible continuation novelty determines context waste",
            )
        )
    if packet_budget:
        slots.append(
            _slot(
                slot_type="packet_budget",
                summary=f"stage143 stop={packet_budget.get('stop_reason', '')}; packets={packet_budget.get('packet_count', 0)}; tokens={packet_budget.get('total_estimated_tokens', 0)}",
                priority=0.8,
                confidence=0.78,
                include_reason="packet budget exposes cost and stop reason",
            )
        )
    visual_summary = _visual_summary(visual_memory, packet, debug)
    if visual_summary:
        slots.append(_slot(slot_type="visual_observation", summary=visual_summary, priority=0.56, freshness="turn_or_sidecar", confidence=0.58, include_reason="visual context may ground multimodal claims"))
    risk_summary = _risk_summary(risk_permission, packet, debug)
    if risk_summary:
        slots.append(_slot(slot_type="risk_permission", summary=risk_summary, priority=0.74, confidence=0.72, include_reason="risk and permission state constrains tool policy"))

    bounded = _bounded_slots(slots, max_slots=max_slots)
    sufficiency, waste = _scores(
        slots=bounded,
        tool_grounding=tool_report,
        memory_grounding=memory_report,
        memory_alignment=alignment,
        novelty=novelty,
        packet_budget=packet_budget,
    )
    recommended, reason, confidence = _recommend_policy(
        tool_grounding=tool_report,
        memory_alignment=alignment,
        memory_grounding=memory_report,
        novelty=novelty,
        packet_budget=packet_budget,
        uncertainty=uncertainty,
    )
    recommendation = f"{recommended}: {reason}"
    return {
        "schema": STAGE144_SCHEMA,
        "working_set_slots": bounded,
        "context_sufficiency_score": sufficiency,
        "context_waste_score": waste,
        "packet_policy_recommendation": recommendation,
        "recommended_deep_policy": recommended,
        "confidence": _clamp(confidence),
        "reason": reason,
        "shadow_only": True,
    }


def build_stage144_context_economy_report(**kwargs: Any) -> dict[str, Any]:
    return build_stage144_context_economy(**kwargs)
