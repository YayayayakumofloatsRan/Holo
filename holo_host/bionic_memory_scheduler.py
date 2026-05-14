from __future__ import annotations

from typing import Any

from .common import compact_text


CACHE_INHERITANCE_MODE = "stage63_cortical_cache_spine_v1"
RESIDUAL_WORKING_CHANNEL_MODE = "stage64_residual_working_channel_v1"
TOOL_OBSERVATION_MODE = "stage65_bounded_tool_observation_v1"
DYNAMIC_DELTA_FRAME_MODE = "stage66_dynamic_delta_frame_v1"

PROTECTED_DYNAMIC_LABELS = (
    "active_summary",
    "latest_user_intent",
    "selected_action",
    "temporal_resume_cue",
    "reconstruction_summary",
    "correction_reactivation_marker",
    "anchor",
    "residual_fast",
    "tool_observation",
)

DELTA_COMPRESSIBLE_LABELS = (
    "memory_id",
    "motif",
    "vector",
    "activation_heat",
    "scene_response_sketch",
    "dense_reentry_hint",
    "memory_route",
    "tier",
)

MEMORY_REQUEST_MARKERS = (
    "remember",
    "memory",
    "before",
    "earlier",
    "previous",
    "history",
    "刚才",
    "之前",
    "还记得",
    "记得",
    "回忆",
)

CORRECTION_REACTIVATION_MARKERS = (
    "correction:",
    "replaces",
    "replaced",
    "corrected state",
    "old marker",
    "instead",
)


def _text(value: Any, limit: int = 180) -> str:
    return compact_text(str(value or "").strip(), limit)


def _metric(value: Any, default: float = 0.0) -> float:
    target = value.get("value", default) if isinstance(value, dict) else value
    try:
        return max(0.0, min(1.0, float(target or 0.0)))
    except (TypeError, ValueError):
        return default


def _unique(lines: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in lines:
        line = _text(raw)
        if not line or line in seen:
            continue
        seen.add(line)
        result.append(line)
        if len(result) >= limit:
            break
    return result


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _field_line(label: str, value: Any, *, limit: int = 140) -> list[str]:
    text = _text(value, limit)
    return [f"{label}={text}"] if text else []


def _line_label(line: str) -> str:
    return str(line or "").split("=", 1)[0].strip()


def _prompt_line_body(line: str) -> str:
    text = str(line or "").strip()
    for prefix in ("working: ", "hippocampal: "):
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _prompt_line_label(line: str) -> str:
    return _line_label(_prompt_line_body(line))


def _prompt_line_value(line: str) -> str:
    body = _prompt_line_body(line)
    if "=" not in body:
        return ""
    return _text(body.split("=", 1)[1], 90)


def _bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def _estimate_tokens(text: str) -> int:
    value = str(text or "")
    if not value:
        return 0
    ascii_chars = sum(1 for char in value if ord(char) < 128)
    non_ascii_chars = len(value) - ascii_chars
    return max(1, ((ascii_chars + 3) // 4) + non_ascii_chars)


def _memory_requested(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(marker in lowered for marker in MEMORY_REQUEST_MARKERS)


def _correction_reactivation_text(packet: dict[str, Any], *, query: str) -> str:
    active = _dict(packet.get("active_thread_state"))
    recall = _dict(packet.get("recall_reconstruction"))
    stage20 = _dict(packet.get("stage20"))
    stage24 = _dict(packet.get("stage24"))
    direct_candidates = [
        query,
        active.get("latest_user_intent"),
    ]
    weak_candidates = [
        active.get("summary"),
        active.get("continuity_summary"),
        recall.get("summary"),
        stage20.get("resume_cue"),
        stage24.get("response_sketch"),
    ]
    candidates = [*direct_candidates, *(weak_candidates if _memory_requested(query) else [])]
    for raw in candidates:
        text = _text(raw, 180)
        lowered = text.lower()
        if not text:
            continue
        if "not " in lowered and "anymore" in lowered:
            return text
        if "claim" in lowered and "still" in lowered:
            return text
        if any(marker in lowered for marker in CORRECTION_REACTIVATION_MARKERS):
            return text
    return ""


def _cortical_schema_lines(packet: dict[str, Any]) -> list[str]:
    identity = _dict(packet.get("identity_core"))
    reply_constraints = _dict(packet.get("reply_constraints"))
    autobiographical = _dict(packet.get("autobiographical_state"))
    goal_state = _dict(packet.get("goal_state"))
    chapter = _text(autobiographical.get("current_chapter"), 140)
    identity_arc = _text(autobiographical.get("identity_arc"), 140)
    recall_style = _text(reply_constraints.get("human_recall_style"), 160)
    stable_traits = [_text(item, 80) for item in _list(autobiographical.get("stable_traits")) if _text(item, 80)]
    active_goal_types = [
        _text(_dict(item).get("goal_type"), 80)
        for item in _list(goal_state.get("active_goals"))
        if _text(_dict(item).get("goal_type"), 80)
    ]
    lines = [
        "memory_architecture=working_memory + hippocampal_index + cortical_schema + salience_gate",
        "cortical_schema_role=stable identity, policy, long-lived relationship and memory-shape priors",
        *[_text(line, 160) for line in _list(identity.get("lines"))],
        *[_text(line, 160) for line in _list(packet.get("voice_guard"))],
        *[_text(line, 160) for line in _list(reply_constraints.get("lines"))],
    ]
    if recall_style:
        lines.append(f"human_recall_style={recall_style}")
    if chapter:
        lines.append(f"current_chapter={chapter}")
    if identity_arc:
        lines.append(f"identity_arc={identity_arc}")
    lines.extend(f"stable_trait={trait}" for trait in stable_traits[:4])
    lines.extend(f"active_goal_type={goal_type}" for goal_type in active_goal_types[:4])
    return _unique(
        lines,
        limit=14,
    )


def _cache_inheritance_spine_lines(
    packet: dict[str, Any],
    *,
    cortical: list[str],
    salience: dict[str, Any],
) -> list[str]:
    reply_constraints = _dict(packet.get("reply_constraints"))
    goal_state = _dict(packet.get("goal_state"))
    active_goals = [
        _text(_dict(item).get("goal_type"), 80)
        for item in _list(goal_state.get("active_goals"))
        if _text(_dict(item).get("goal_type"), 80)
    ]
    constraint_count = len(_list(reply_constraints.get("lines")))
    stable_schema_count = len([line for line in cortical if str(line).strip()])
    lines = [
        f"cache_spine_mode={CACHE_INHERITANCE_MODE}",
        "cache_spine_role=long-lived identity, policy, memory-shape, grounding, and tool-boundary priors stay in provider prefix",
        "cache_spine_dynamic_rule=current user turn, recent thread window, active working state, and per-turn recall stay in dynamic frame",
        "cache_spine_grounding=visual claims, temporal commitments, and newest corrections must be evidence-bound before output",
        "cache_spine_residual=fast residual channel carries corrected symbols, promise state, visual uncertainty, and latest risk flags",
        "cache_spine_tool_boundary=upstream MCP and tools are bounded observations only, never runtime or transport authority",
        "cache_spine_memory_boundary=self_memory_write=false; consolidation remains diagnostic intent until operator-approved paths",
        f"cache_spine_schema_shape=stable_lines:{stable_schema_count}; reply_constraints:{constraint_count}",
    ]
    if active_goals:
        lines.append(f"cache_spine_goal_types={','.join(active_goals[:4])}")
    return _unique(lines, limit=10)


def _residual_fast_lines(packet: dict[str, Any]) -> list[str]:
    channel = _dict(packet.get("residual_fast_channel"))
    if not bool(channel.get("enabled", False)):
        return []
    lines = [
        f"residual_fast={_text(line, 180)}"
        for line in _list(channel.get("lines"))[:8]
        if _text(line, 180)
    ]
    return _unique(lines, limit=8)


def _tool_observation_scheduler(packet: dict[str, Any]) -> dict[str, Any]:
    capability = _dict(packet.get("capability_context"))
    tool_requests = [
        _dict(item)
        for item in _list(capability.get("tool_requests"))
        if isinstance(item, dict)
    ]
    context_lines = [
        _text(line, 160)
        for line in _list(capability.get("tool_context_lines"))
        if _text(line, 160)
    ]
    request_names = _unique(
        [
            _text(item.get("name"), 80)
            for item in tool_requests
            if _text(item.get("name"), 80)
        ],
        limit=6,
    )
    needed = bool(tool_requests or context_lines)
    observation_budget = min(3, max(1, len(tool_requests) or len(context_lines))) if needed else 0
    return {
        "mode": TOOL_OBSERVATION_MODE,
        "needed": needed,
        "requested_tool_count": len(tool_requests),
        "context_line_count": len(context_lines),
        "request_names": request_names,
        "observation_budget": observation_budget,
        "observation_lines": _unique(context_lines, limit=2),
        "bounded_observation_only": True,
        "runtime_decision_authority": False,
        "transport_decision_authority": False,
        "self_memory_write": False,
        "watcher_decision_authority": False,
        "render_policy": "scheduler_owned_dynamic_frame",
    }


def _tool_observation_lines(scheduler: dict[str, Any]) -> list[str]:
    if not bool(scheduler.get("needed", False)):
        return []
    names = ",".join(_text(item, 60) for item in _list(scheduler.get("request_names")) if _text(item, 60)) or "none"
    contexts = " | ".join(
        _text(line, 100)
        for line in _list(scheduler.get("observation_lines"))[:1]
        if _text(line, 100)
    )
    line = (
        f"tool_observation=requests={names}; "
        f"budget={int(scheduler.get('observation_budget', 0) or 0)}; "
        "bounded_observation_only=true"
    )
    if contexts:
        line += f"; context={contexts}"
    return [line]


def _dynamic_delta_line(buckets: dict[str, list[str]], *, compressed_count: int) -> str:
    parts: list[str] = []
    ids = buckets.get("memory_id", [])
    if ids:
        parts.append(f"ids:{len(ids)}:first={_text(ids[0], 36)}")
    motifs = buckets.get("motif", [])
    if motifs:
        parts.append(f"motifs:{len(motifs)}:first={_text(motifs[0], 32)}")
    vectors = buckets.get("vector", [])
    if vectors:
        parts.append(f"vectors:{len(vectors)}")
    heats = buckets.get("activation_heat", [])
    if heats:
        parts.append(f"heat={_text(heats[-1], 16)}")
    route_parts: list[str] = []
    for label, short in (
        ("memory_route", "route"),
        ("tier", "tier"),
        ("scene_response_sketch", "scene"),
        ("dense_reentry_hint", "reentry"),
    ):
        values = buckets.get(label, [])
        if values:
            route_parts.append(f"{short}:{len(values)}:{_text(values[0], 14)}")
    if route_parts:
        parts.append("volatile:" + "|".join(route_parts))
    parts.append(f"compressed_handles={compressed_count}")
    return _text("dynamic_delta=" + "; ".join(parts), 220)


def _apply_dynamic_delta_frame(prompt_dynamic_lines: list[str]) -> tuple[list[str], dict[str, Any]]:
    source_lines = [_text(line, 220) for line in prompt_dynamic_lines if _text(line, 220)]
    before_tokens = _estimate_tokens("\n".join(source_lines))
    buckets: dict[str, list[str]] = {label: [] for label in DELTA_COMPRESSIBLE_LABELS}
    compressed_lines: list[str] = []
    kept_lines: list[str] = []
    for line in source_lines:
        label = _prompt_line_label(line)
        if label in DELTA_COMPRESSIBLE_LABELS:
            value = _prompt_line_value(line)
            buckets.setdefault(label, []).append(value or label)
            compressed_lines.append(line)
            continue
        kept_lines.append(line)

    compressed_count = len(compressed_lines)
    delta_line = _dynamic_delta_line(buckets, compressed_count=compressed_count) if compressed_count else ""
    salience_lines = [line for line in kept_lines if _prompt_line_label(line) == "salience_score"]
    non_salience = [line for line in kept_lines if _prompt_line_label(line) != "salience_score"]
    fused_lines = _unique(
        [*non_salience, *([delta_line] if delta_line else []), *salience_lines],
        limit=max(1, len(source_lines)),
    )
    after_tokens = _estimate_tokens("\n".join(fused_lines))
    if compressed_count and after_tokens >= before_tokens:
        fused_lines = source_lines
        delta_line = ""
        compressed_count = 0
        after_tokens = before_tokens
    protected_source = [
        line
        for line in source_lines
        if _prompt_line_label(line) in PROTECTED_DYNAMIC_LABELS
    ]
    protected_dropped = [
        _prompt_line_label(line)
        for line in protected_source
        if line not in fused_lines
    ]
    frame = {
        "mode": DYNAMIC_DELTA_FRAME_MODE,
        "source_line_count": len(source_lines),
        "delta_line_count": 1 if delta_line else 0,
        "compressed_handle_count": compressed_count,
        "protected_line_count": len(protected_source),
        "estimated_before_tokens": before_tokens,
        "estimated_after_tokens": after_tokens,
        "estimated_saved_tokens": max(0, before_tokens - after_tokens),
        "protected_dropped_labels": sorted(set(protected_dropped)),
        "protected_line_dropped": bool(protected_dropped),
        "runtime_decision_authority": False,
        "transport_decision_authority": False,
        "watcher_decision_authority": False,
        "self_memory_write": False,
        "render_policy": "scheduler_owned_dynamic_delta_frame",
    }
    return fused_lines, frame


def _working_memory_lines(packet: dict[str, Any]) -> list[str]:
    active = _dict(packet.get("active_thread_state"))
    stage20 = _dict(packet.get("stage20"))
    stage24 = _dict(packet.get("stage24"))
    stage25 = _dict(packet.get("stage25"))
    selected = _dict(packet.get("selected_action"))
    residual_lines = _residual_fast_lines(packet)
    lines = [
        *_field_line("active_summary", active.get("summary") or active.get("continuity_summary"), limit=180),
        *_field_line("latest_user_intent", active.get("latest_user_intent"), limit=140),
        *residual_lines,
        *_field_line("selected_action", selected.get("action_type"), limit=80),
        *_field_line("temporal_resume_cue", stage20.get("resume_cue"), limit=140),
        *_field_line("scene_response_sketch", stage24.get("response_sketch"), limit=140),
        *_field_line("dense_reentry_hint", stage25.get("reentry_hint"), limit=140),
        *_field_line("memory_route", packet.get("memory_route"), limit=60),
        *_field_line("tier", packet.get("tier"), limit=60),
    ]
    return _unique(lines, limit=12)


def _hippocampal_index_lines(packet: dict[str, Any], *, query: str = "") -> list[str]:
    activation = _dict(packet.get("activation_state"))
    episodic = _dict(packet.get("episodic_recall"))
    recall_reconstruction = _dict(packet.get("recall_reconstruction"))
    heat = _metric(activation.get("heat"))
    reconstruction_summary = _text(recall_reconstruction.get("summary"), 180)
    correction_marker = _correction_reactivation_text(packet, query=query)
    ids = [_text(item, 80) for item in _list(packet.get("selected_memory_ids")) + _list(packet.get("activation_trace_ids")) if _text(item, 80)]
    motifs = [_text(item, 80) for item in _list(activation.get("motifs")) if _text(item, 80)]
    vector_hits = [
        _text(_dict(item).get("text"), 160)
        for item in _list(packet.get("vector_hits"))
        if _text(_dict(item).get("text"), 160)
    ]
    lines = [
        *([f"correction_reactivation_marker={correction_marker}"] if correction_marker else []),
        *([f"reconstruction_summary={reconstruction_summary}"] if reconstruction_summary else []),
        *[f"episodic={_text(line, 160)}" for line in _list(episodic.get("lines"))[:4]],
        *[f"anchor={_text(line, 120)}" for line in _list(recall_reconstruction.get("anchors"))[:3]],
        *[f"memory_id={item}" for item in ids[:6]],
        *[f"motif={motif}" for motif in motifs[:4]],
        *[f"vector={line}" for line in vector_hits[:3]],
        *([f"activation_heat={round(heat, 3)}"] if heat > 0.0 else []),
    ]
    return _unique(lines, limit=16)


def _salience_gate(packet: dict[str, Any], *, query: str) -> dict[str, Any]:
    activation = _dict(packet.get("activation_state"))
    affect = _dict(packet.get("affect_state"))
    drive = _dict(packet.get("drive_state"))
    conflict = _dict(packet.get("conflict_state"))
    stage20 = _dict(packet.get("stage20"))
    intent = _dict(packet.get("intent_state"))
    sources: list[str] = []
    score = 0.15
    heat = _metric(activation.get("heat"))
    if heat >= 0.35:
        sources.append("activation_heat")
    score += heat * 0.2
    if _memory_requested(query) or bool(intent.get("local_memory_requested", False)):
        sources.append("memory_request")
        score += 0.25
    if _correction_reactivation_text(packet, query=query):
        sources.append("correction_reactivation")
        score += 0.42
    continuity_anxiety = _metric(affect.get("continuity_anxiety"))
    if continuity_anxiety >= 0.35:
        sources.append("continuity_anxiety")
    score += continuity_anxiety * 0.15
    seek_continuity = _metric(drive.get("seek_continuity"))
    if seek_continuity >= 0.35:
        sources.append("seek_continuity")
    score += seek_continuity * 0.1
    prediction_error = max(
        _metric(conflict.get("contact_vs_risk")),
        _metric(conflict.get("continuity_vs_detachment")),
        _metric(packet.get("uncertainty_level")),
    )
    if prediction_error >= 0.35:
        sources.append("prediction_error")
    score += prediction_error * 0.12
    if bool(stage20.get("temporal_visible", False)) or _text(stage20.get("resume_cue")):
        sources.append("temporal_open_loop")
        score += 0.1
    if _text(_dict(packet.get("recall_reconstruction")).get("summary")):
        sources.append("semantic_reconstruction")
        score += 0.1
    score = round(max(0.0, min(1.0, score)), 4)
    if score >= 0.75:
        recall_budget = 6
    elif score >= 0.55:
        recall_budget = 4
    elif score >= 0.35:
        recall_budget = 3
    else:
        recall_budget = 2
    return {
        "score": score,
        "sources": _unique(sources, limit=8),
        "recall_budget": recall_budget,
        "working_memory_budget": 6 if score >= 0.55 else 4,
        "hippocampal_budget": recall_budget,
    }


def _consolidation_targets(packet: dict[str, Any], *, salience: dict[str, Any]) -> dict[str, Any]:
    targets: list[str] = []
    salience_sources = set(_list(salience.get("sources")))
    if float(salience.get("score", 0.0) or 0.0) >= 0.55:
        targets.append("salient_turn")
    if "correction_reactivation" in salience_sources:
        targets.append("correction_reactivation_marker")
    if _dict(packet.get("stage20")).get("resume_cue"):
        targets.append("temporal_open_loop")
    if _list(packet.get("activation_trace_ids")) or _list(packet.get("selected_memory_ids")):
        targets.append("reactivated_index")
    if _dict(packet.get("recall_reconstruction")).get("summary"):
        targets.append("semantic_reconstruction")
    return {
        "targets": _unique(targets, limit=6),
        "self_memory_write": False,
        "write_policy": "diagnostic_intent_only",
    }


def _compression_audit(
    *,
    raw_working: list[str],
    selected_working: list[str],
    raw_hippocampal: list[str],
    selected_hippocampal: list[str],
    prompt_dynamic_lines: list[str],
    salience: dict[str, Any],
) -> dict[str, Any]:
    raw_dynamic = [*raw_working, *raw_hippocampal, "salience_gate"]
    selected_dynamic = [*selected_working, *selected_hippocampal, "salience_gate"]
    selected_set = set(selected_dynamic)
    protected_labels = sorted(
        {
            _line_label(line)
            for line in raw_dynamic
            if _line_label(line) in PROTECTED_DYNAMIC_LABELS
        }
    )
    protected_dropped = sorted(
        {
            _line_label(line)
            for line in raw_dynamic
            if _line_label(line) in PROTECTED_DYNAMIC_LABELS and line not in selected_set
        }
    )
    dropped_labels = sorted(
        {
            _line_label(line)
            for line in raw_dynamic
            if line not in selected_set and _line_label(line)
        }
    )
    raw_count = len(raw_dynamic)
    selected_count = len(selected_dynamic)
    score = float(salience.get("score", 0.0) or 0.0)
    if score >= 0.75:
        budget_reason = "high_salience"
    elif score >= 0.55:
        budget_reason = "memory_pressure"
    elif score >= 0.35:
        budget_reason = "moderate_salience"
    else:
        budget_reason = "baseline"
    return {
        "mode": "scheduler_owned_dynamic_v1",
        "raw_working_line_count": len(raw_working),
        "selected_working_line_count": len(selected_working),
        "raw_hippocampal_line_count": len(raw_hippocampal),
        "selected_hippocampal_line_count": len(selected_hippocampal),
        "raw_dynamic_line_count": raw_count,
        "prompt_dynamic_line_count": len(prompt_dynamic_lines),
        "selected_dynamic_line_count": selected_count,
        "dropped_dynamic_line_count": max(0, raw_count - selected_count),
        "compression_ratio": round(float(selected_count) / float(raw_count), 4) if raw_count else 1.0,
        "budget_reason": budget_reason,
        "protected_labels": protected_labels,
        "protected_dropped_labels": protected_dropped,
        "protected_line_dropped": bool(protected_dropped),
        "dropped_labels": dropped_labels,
    }


def _residual_working_channel_audit(
    *,
    packet: dict[str, Any],
    raw_working: list[str],
    selected_working: list[str],
    prompt_dynamic_lines: list[str],
) -> dict[str, Any]:
    source_lines = _residual_fast_lines(packet)
    selected = [line for line in selected_working if _line_label(line) == "residual_fast"]
    dropped = [line for line in source_lines if line not in selected]
    prompt_count = sum(1 for line in prompt_dynamic_lines if "residual_fast=" in line)
    return {
        "mode": RESIDUAL_WORKING_CHANNEL_MODE,
        "source_enabled": bool(_dict(packet.get("residual_fast_channel")).get("enabled", False)),
        "raw_line_count": len(source_lines),
        "fast_line_count": len(source_lines),
        "selected_fast_line_count": len(selected),
        "prompt_line_count": prompt_count,
        "fast_tokens": _estimate_tokens("\n".join(source_lines)),
        "protected_line_dropped": bool(dropped),
        "dropped_fast_line_count": len(dropped),
        "render_policy": "scheduler_owned_dynamic_frame",
        "self_memory_write": False,
        "runtime_decision_authority": False,
        "transport_decision_authority": False,
    }


def build_bionic_memory_schedule(packet: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    source = dict(packet or {})
    cortical = _cortical_schema_lines(source)
    raw_working = _working_memory_lines(source)
    raw_hippocampal = _hippocampal_index_lines(source, query=query)
    salience = _salience_gate(source, query=query)
    tool_scheduler = _tool_observation_scheduler(source)
    cache_spine = _cache_inheritance_spine_lines(source, cortical=cortical, salience=salience)
    provider_prefix = _unique([*cortical, *cache_spine], limit=24)
    working_budget = int(salience.get("working_memory_budget", 4) or 4)
    hippocampal_budget = int(salience.get("hippocampal_budget", 2) or 2)
    residual_line_count = len(_residual_fast_lines(source))
    if residual_line_count:
        working_budget = max(working_budget, min(8, 2 + residual_line_count))
    working = raw_working[:working_budget]
    hippocampal = raw_hippocampal[:hippocampal_budget]
    delta_only_working = [
        line
        for line in raw_working
        if line not in working
        and _line_label(line)
        in {"scene_response_sketch", "dense_reentry_hint", "memory_route", "tier"}
    ]
    consolidation = _consolidation_targets(source, salience=salience)
    prompt_dynamic_base = _unique(
        [
            *[f"working: {line}" for line in working],
            *[f"working: {line}" for line in delta_only_working],
            *[f"hippocampal: {line}" for line in hippocampal],
            *_tool_observation_lines(tool_scheduler),
            f"salience_score={salience['score']}; sources={','.join(salience['sources']) or 'baseline'}",
        ],
        limit=18,
    )
    prompt_dynamic, dynamic_delta_frame = _apply_dynamic_delta_frame(prompt_dynamic_base)
    audit = _compression_audit(
        raw_working=raw_working,
        selected_working=working,
        raw_hippocampal=raw_hippocampal,
        selected_hippocampal=hippocampal,
        prompt_dynamic_lines=prompt_dynamic,
        salience=salience,
    )
    audit["stage66_delta_mode"] = dynamic_delta_frame["mode"]
    audit["delta_saved_tokens"] = int(dynamic_delta_frame.get("estimated_saved_tokens", 0) or 0)
    audit["delta_compressed_handle_count"] = int(dynamic_delta_frame.get("compressed_handle_count", 0) or 0)
    audit["delta_protected_line_dropped"] = bool(dynamic_delta_frame.get("protected_line_dropped", False))
    audit["protected_line_dropped"] = bool(
        audit.get("protected_line_dropped", False)
        or dynamic_delta_frame.get("protected_line_dropped", False)
    )
    residual_channel = _residual_working_channel_audit(
        packet=source,
        raw_working=raw_working,
        selected_working=working,
        prompt_dynamic_lines=prompt_dynamic,
    )
    stable_tokens = _estimate_tokens("\n".join(provider_prefix))
    dynamic_tokens = _estimate_tokens("\n".join(prompt_dynamic))
    cache_inheritance = {
        "mode": CACHE_INHERITANCE_MODE,
        "stable_schema_line_count": len(cortical),
        "cache_spine_line_count": len(cache_spine),
        "provider_prefix_line_count": len(provider_prefix),
        "dynamic_line_count": len(prompt_dynamic),
        "estimated_stable_prefix_tokens": stable_tokens,
        "estimated_dynamic_tokens": dynamic_tokens,
        "prefix_share": round(stable_tokens / max(1, stable_tokens + dynamic_tokens), 6),
        "self_memory_write": False,
        "runtime_decision_authority": False,
        "transport_decision_authority": False,
    }
    return {
        "mode": "biomimetic_v1",
        "working_memory": {
            "dynamic_lines": working,
            "role": "current active state and residual factual guards",
        },
        "hippocampal_index": {
            "dynamic_lines": hippocampal,
            "role": "event index, motifs, anchors, and recall handles",
        },
        "cortical_schema": {
            "stable_prefix_lines": cortical,
            "role": "stable identity, policy, and long-lived memory schema",
        },
        "salience_gate": salience,
        "consolidation_targets": consolidation,
        "dynamic_compression_audit": audit,
        "residual_working_channel": residual_channel,
        "tool_observation_scheduler": tool_scheduler,
        "dynamic_delta_frame": dynamic_delta_frame,
        "cache_inheritance": cache_inheritance,
        "provider_prefix_lines": provider_prefix,
        "prompt_dynamic_lines": prompt_dynamic,
        "dynamic_context_lines": prompt_dynamic,
    }


def _phase_value(lines: list[Any], label: str, *, limit: int = 140) -> str:
    prefix = f"{label}="
    for raw in lines:
        text = str(raw or "").strip()
        if text.startswith(prefix):
            return _text(text[len(prefix) :], limit)
    return ""


def _fusion_supplement_lines(
    lifecycle: dict[str, Any],
    consciousness_flow: dict[str, Any],
    *,
    limit: int,
) -> list[str]:
    consolidation = _dict(lifecycle.get("consolidation_intent"))
    replay = _dict(lifecycle.get("replay_plan"))
    forgetting = _dict(lifecycle.get("forgetting_gate"))
    leakage = _dict(consciousness_flow.get("leakage_guard"))
    phase_lines = _list(consciousness_flow.get("phase_lines"))
    targets = ",".join(_text(item, 70) for item in _list(consolidation.get("targets"))[:4] if _text(item, 70)) or "none"
    replay_state = "triggered" if bool(replay.get("triggered", False)) else "idle"
    decay = ",".join(_text(item, 70) for item in _list(forgetting.get("decay_candidates"))[:4] if _text(item, 70)) or "none"
    sensory_edge = _text(consciousness_flow.get("current_edge") or _phase_value(phase_lines, "sensory_edge"), 140)
    memory_reactivation = _phase_value(phase_lines, "memory_reactivation", limit=120)
    goal_pressure = _phase_value(phase_lines, "goal_pressure", limit=120)
    dominant_phase = _text(consciousness_flow.get("dominant_phase"), 70) or "sensory_edge"
    lines = [
        (
            f"lifecycle: priority={round(float(consolidation.get('priority', 0.0) or 0.0), 3)}; "
            f"targets={targets}; self_memory_write={_bool_text(consolidation.get('self_memory_write', False))}; "
            f"replay={replay_state}; background_loop_allowed={_bool_text(replay.get('background_loop_allowed', False))}"
        ),
        (
            f"forgetting: decay_candidates={decay}; "
            f"protected_line_dropped={_bool_text(forgetting.get('protected_line_dropped', False))}"
        ),
        (
            f"flow: sensory_edge={sensory_edge or 'current turn'}; dominant_phase={dominant_phase}; "
            f"user_visible={_bool_text(leakage.get('user_visible', False))}"
        ),
    ]
    if memory_reactivation or goal_pressure:
        lines.append(
            f"flow_reentry: memory_reactivation={memory_reactivation or 'none'}; goal_pressure={goal_pressure or 'none'}"
        )
    return _unique(lines, limit=limit)


def fuse_bionic_dynamic_prompt(
    schedule: dict[str, Any],
    lifecycle: dict[str, Any],
    consciousness_flow: dict[str, Any],
    *,
    max_supplement_lines: int = 4,
    max_prompt_dynamic_lines: int = 18,
) -> dict[str, Any]:
    """Fuse Stage51 lifecycle/flow prompt surfaces into scheduler-owned dynamic lines."""

    result = dict(schedule or {})
    base_lines = [
        _text(line, 220)
        for line in _list(result.get("prompt_dynamic_lines") or result.get("dynamic_context_lines"))
        if _text(line, 220)
    ]
    lifecycle_lines = [_text(line, 220) for line in _list(lifecycle.get("prompt_lines")) if _text(line, 220)]
    flow_lines = [_text(line, 220) for line in _list(consciousness_flow.get("phase_lines")) if _text(line, 220)]
    supplement = _fusion_supplement_lines(
        dict(lifecycle or {}),
        dict(consciousness_flow or {}),
        limit=max(1, int(max_supplement_lines or 1)),
    )
    fused = _unique(
        [*base_lines, *supplement],
        limit=max(1, int(max_prompt_dynamic_lines or 1)),
    )
    source_line_count = len(base_lines) + len(lifecycle_lines) + len(flow_lines)
    saved_line_count = max(0, source_line_count - len(fused))
    fusion = {
        "mode": "scheduler_owned_stage52_v1",
        "source_line_count": source_line_count,
        "base_line_count": len(base_lines),
        "source_lifecycle_line_count": len(lifecycle_lines),
        "source_consciousness_line_count": len(flow_lines),
        "supplement_line_count": len(supplement),
        "supplement_lines": supplement,
        "fused_line_count": len(fused),
        "saved_line_count": saved_line_count,
        "render_policy": "single_scheduler_dynamic_frame",
    }
    result["prompt_dynamic_lines"] = fused
    result["dynamic_context_lines"] = fused
    result["dynamic_fusion"] = fusion
    compression = _dict(result.get("dynamic_compression_audit"))
    compression["stage52_fusion_mode"] = fusion["mode"]
    compression["prompt_dynamic_line_count"] = len(fused)
    compression["fusion_saved_line_count"] = saved_line_count
    result["dynamic_compression_audit"] = compression
    return result
