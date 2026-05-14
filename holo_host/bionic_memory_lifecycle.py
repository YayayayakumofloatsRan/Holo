from __future__ import annotations

from typing import Any

from .bionic_memory_scheduler import PROTECTED_DYNAMIC_LABELS
from .common import compact_text


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any, limit: int = 180) -> str:
    return compact_text(str(value or "").strip(), limit)


def _metric(value: Any, default: float = 0.0) -> float:
    target = value.get("value", default) if isinstance(value, dict) else value
    try:
        return max(0.0, min(1.0, float(target or default)))
    except (TypeError, ValueError):
        return default


def _unique(values: list[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _schedule(packet: dict[str, Any]) -> dict[str, Any]:
    schedule = packet.get("bionic_memory_schedule", {})
    return dict(schedule) if isinstance(schedule, dict) else {}


def _schedule_lines(schedule: dict[str, Any], section_name: str) -> list[str]:
    section = _dict(schedule.get(section_name))
    return _unique(_list(section.get("dynamic_lines")), limit=8)


def _target_names(packet: dict[str, Any], schedule: dict[str, Any]) -> list[str]:
    targets = _list(_dict(schedule.get("consolidation_targets")).get("targets"))
    if _list(packet.get("activation_trace_ids")) or _list(packet.get("selected_memory_ids")):
        targets.append("reactivated_index")
    if _text(_dict(packet.get("recall_reconstruction")).get("summary")):
        targets.append("semantic_reconstruction")
    if _text(_dict(packet.get("stage20")).get("resume_cue")):
        targets.append("temporal_open_loop")
    return _unique(targets, limit=8)


def _evidence_lines(packet: dict[str, Any], schedule: dict[str, Any]) -> list[str]:
    recall = _dict(packet.get("recall_reconstruction"))
    active = _dict(packet.get("active_thread_state"))
    lines: list[Any] = [
        _text(recall.get("summary"), 180),
        _text(active.get("summary") or active.get("continuity_summary"), 160),
        *[_text(item, 140) for item in _list(recall.get("anchors"))[:3]],
        *_schedule_lines(schedule, "working_memory")[:3],
        *_schedule_lines(schedule, "hippocampal_index")[:4],
    ]
    return _unique(lines, limit=8)


def _candidate_streams(packet: dict[str, Any], targets: list[str]) -> list[str]:
    streams: list[str] = []
    if "semantic_reconstruction" in targets:
        streams.append("recall_reconstruction")
    if "reactivated_index" in targets or "correction_reactivation_marker" in targets:
        streams.append("hippocampal_index")
    if "correction_reactivation_marker" in targets:
        streams.append("recent_dialogue_window")
    if "temporal_open_loop" in targets:
        streams.append("active_thread_state")
    if "salient_turn" in targets:
        streams.append("recent_dialogue_window")
    if _dict(packet.get("goal_state")).get("active_goals"):
        streams.append("goal_state")
    if _dict(packet.get("affect_state")) or _dict(packet.get("drive_state")):
        streams.append("affect_drive_state")
    return _unique(streams, limit=8)


def _forgetting_candidates(audit: dict[str, Any]) -> list[str]:
    labels = _list(audit.get("dropped_labels"))
    if not labels:
        labels = _list(audit.get("suppressed_labels"))
    protected = set(PROTECTED_DYNAMIC_LABELS)
    return _unique([label for label in labels if str(label) not in protected], limit=10)


def build_bionic_memory_lifecycle(packet: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    source = dict(packet or {})
    schedule = _schedule(source)
    salience_gate = _dict(schedule.get("salience_gate"))
    compression = _dict(schedule.get("dynamic_compression_audit"))
    score = _metric(salience_gate.get("score"), 0.0)
    targets = _target_names(source, schedule)
    evidence = _evidence_lines(source, schedule)
    candidate_streams = _candidate_streams(source, targets)
    dropped_count = int(compression.get("dropped_dynamic_line_count", 0) or 0)
    compression_ratio = float(compression.get("compression_ratio", 1.0) or 1.0)
    protected_labels = _unique(_list(compression.get("protected_labels")), limit=10)
    decay_candidates = _forgetting_candidates(compression)
    semantic_bonus = 0.08 if "semantic_reconstruction" in targets else 0.0
    reactivation_bonus = 0.07 if "reactivated_index" in targets else 0.0
    continuity_bonus = max(
        _metric(_dict(source.get("affect_state")).get("continuity_anxiety"), 0.0),
        _metric(_dict(source.get("drive_state")).get("seek_continuity"), 0.0),
    ) * 0.08
    priority = round(max(0.0, min(1.0, score + semantic_bonus + reactivation_bonus + continuity_bonus)), 4)
    triggered = bool(targets) or score >= 0.55 or bool(evidence)
    replay_sources = _unique(
        [
            *targets,
            *candidate_streams,
            *_list(salience_gate.get("sources")),
        ],
        limit=10,
    )
    replay_budget = max(1, min(6, int(salience_gate.get("recall_budget", 2) or 2)))
    consolidation_intent = {
        "mode": "systems_consolidation_intent_v1",
        "priority": priority,
        "targets": targets,
        "candidate_streams": candidate_streams,
        "evidence_lines": evidence[:6],
        "self_memory_write": False,
        "write_policy": "diagnostic_intent_only",
        "requires_external_memory_writer": True,
    }
    replay_plan = {
        "mode": "hippocampal_reactivation_v1",
        "triggered": triggered,
        "sources": replay_sources,
        "reactivation_lines": evidence[:replay_budget],
        "max_replay_items": replay_budget,
        "sleep_like_replay_intent": "eligible" if triggered and priority >= 0.55 else "idle",
        "dream_replay_allowed": False,
        "background_loop_allowed": False,
    }
    forgetting_gate = {
        "mode": "synaptic_pruning_v1",
        "decay_candidates": decay_candidates,
        "suppressed_low_value_labels": decay_candidates,
        "protected_labels": protected_labels,
        "protected_line_dropped": bool(compression.get("protected_line_dropped", False)),
        "policy": "drop_low_salience_prompt_handles_not_memory_facts",
        "confidence": round(1.0 - min(1.0, max(0.0, compression_ratio)), 4) if dropped_count else 0.0,
    }
    memory_pressure = {
        "salience_score": score,
        "compression_ratio": round(compression_ratio, 4),
        "dropped_dynamic_line_count": dropped_count,
        "protected_line_dropped": bool(compression.get("protected_line_dropped", False)),
        "query_present": bool(_text(query, 80)),
    }
    prompt_lines = _unique(
        [
            f"consolidation_priority={priority}; targets={','.join(targets) or 'none'}; self_memory_write=false",
            f"reactivation={'triggered' if triggered else 'idle'}; sources={','.join(replay_sources) or 'baseline'}; background_loop_allowed=false",
            f"forgetting_gate=prune_prompt_handles; decay_candidates={','.join(decay_candidates) or 'none'}; protected_line_dropped={str(forgetting_gate['protected_line_dropped']).lower()}",
            *[f"evidence={line}" for line in evidence[:3]],
        ],
        limit=8,
    )
    return {
        "mode": "biomimetic_lifecycle_v1",
        "consolidation_intent": consolidation_intent,
        "replay_plan": replay_plan,
        "forgetting_gate": forgetting_gate,
        "memory_pressure": memory_pressure,
        "prompt_lines": prompt_lines,
    }
