from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import atomic_write_text, compact_text, stable_digest, utc_now

STAGE135_SCHEMA = "holo.stage135.i_state_topology.v1"
STAGE135_PROMPT_MARKER = "Stage135 I-State Frame"
DEFAULT_OUTPUT_DIR = Path("artifacts") / "stage135"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(dict(item))
        else:
            text = getattr(item, "text", None)
            purpose = getattr(item, "purpose", None)
            if text is not None or purpose is not None:
                items.append({"text": text, "role": purpose})
    return items


def _safe_node_suffix(value: Any) -> str:
    text = str(value or "").strip()
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text)
    return cleaned[:80] or stable_digest(text, limit=10)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = 0.0
    return max(low, min(high, current))


def _node(
    node_id: str,
    label: str,
    *,
    channel: str,
    kind: str,
    x: float,
    y: float,
    weight: float = 0.5,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "channel": channel,
        "kind": kind,
        "x": round(_clamp(x), 4),
        "y": round(_clamp(y), 4),
        "weight": round(_clamp(weight), 4),
        "summary": compact_text(summary, 240),
    }


def _edge(
    source: str,
    target: str,
    *,
    relation: str,
    weight: float = 0.5,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "weight": round(_clamp(weight), 4),
        "summary": compact_text(summary, 220),
    }


def _context_field(context: Any, name: str, default: str = "") -> str:
    return str(getattr(context, name, default) or default).strip()


def _context_packet(context: Any) -> dict[str, Any]:
    packet = _dict(getattr(context, "mind_packet", {}))
    if packet:
        return packet
    return _dict(getattr(context, "sidecar", {}))


def _tool_names_from_context(context: Any) -> list[str]:
    capability = _dict(getattr(context, "capability_context", {}))
    names: list[str] = []
    for item in _list_dicts(capability.get("tool_requests", [])):
        name = str(item.get("name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _tool_names_from_loop(tool_loop: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("executed_tools", "tool_names", "tools"):
        raw = tool_loop.get(key, [])
        if isinstance(raw, list):
            for value in raw:
                name = str(value.get("name", "") if isinstance(value, dict) else value or "").strip()
                if name and name not in names:
                    names.append(name)
    return names


def _visible_segment_role(item: dict[str, Any], index: int) -> str:
    role = str(item.get("role", "") or item.get("purpose", "") or "").strip()
    if role:
        return role
    return "fast_reaction" if index == 0 else "deep_continuation"


def _channel_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        channel = str(node.get("channel", "") or "")
        counts[channel] = counts.get(channel, 0) + 1
    return dict(sorted(counts.items()))


def build_stage135_i_state_prompt_frame(context: Any) -> dict[str, Any]:
    packet = _context_packet(context)
    active_state = _dict(packet.get("active_thread_state", {}))
    scene_state = _dict(active_state.get("scene_state", {}))
    continuity = compact_text(str(active_state.get("continuity_summary", "") or ""), 240)
    shared_frame = compact_text(str(scene_state.get("shared_frame", "") or ""), 200)
    lines = [
        f"{STAGE135_PROMPT_MARKER}:",
        "subject_id=holo; first_person_anchor=I am the single Holo host state for this thread",
        "external_user_input=the operator/user text; holo_inner=local planning summary; holo_visible=only speech emitted to the user",
        "provider_return_contract=parse every return as a semantic state event before deciding whether to continue",
        "continuation_rule=continue only when new state, memory, tool, or uncertainty reduction remains useful",
        "tool_boundary=provider may propose tools; WSL Holo host validates and executes locally",
        f"channel={_context_field(context, 'channel', 'holo_cli')} thread_key={_context_field(context, 'thread_key', 'holo_cli:main')} chat_name={_context_field(context, 'chat_name', 'Holo')}",
    ]
    if continuity:
        lines.append(f"current_i_state_continuity={continuity}")
    if shared_frame:
        lines.append(f"current_world_frame={shared_frame}")
    return {
        "schema": STAGE135_SCHEMA,
        "marker": STAGE135_PROMPT_MARKER,
        "lines": lines,
        "line_count": len(lines),
        "char_count": sum(len(line) for line in lines),
        "cache_hint": "stage135:" + stable_digest(*lines, limit=12),
    }


def append_stage135_i_state_contract(prompt: str, prompt_frame: dict[str, Any] | None = None) -> str:
    frame = _dict(prompt_frame)
    lines = list(frame.get("lines", []) or [])
    if not lines:
        lines = [
            f"{STAGE135_PROMPT_MARKER}:",
            "subject_id=holo; provider returns are semantic state events before visible speech",
        ]
    contract = "\n".join(str(line) for line in lines if str(line).strip())
    return "\n\nStage135 I-State Contract:\n" + contract if not prompt else prompt.rstrip() + "\n\nStage135 I-State Contract:\n" + contract


def build_stage135_i_state_topology(
    *,
    context: Any | None = None,
    turn_id: str | None = None,
    user_text: str | None = None,
    channel: str | None = None,
    thread_key: str | None = None,
    chat_name: str | None = None,
    fast_packet: dict[str, Any] | None = None,
    stream_plan: dict[str, Any] | None = None,
    packet_policy: dict[str, Any] | None = None,
    channel_frame: dict[str, Any] | None = None,
    internal_tool_flow: dict[str, Any] | None = None,
    tool_loop: dict[str, Any] | None = None,
    visible_segments: list[Any] | None = None,
    memory_delta: dict[str, Any] | None = None,
    memory_observation_ledger: list[dict[str, Any]] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    stage142_semantic_novelty: dict[str, Any] | None = None,
    stage143_packet_budget: dict[str, Any] | None = None,
    stage144_context_economy: dict[str, Any] | None = None,
    stage145_outcome_appraisal: dict[str, Any] | None = None,
    stage145_reaction_kernel_shadow: dict[str, Any] | None = None,
    stage148_react_state: dict[str, Any] | None = None,
    visual_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a redacted topology of Holo's current I-state flow.

    This is observability metadata. It does not execute tools, decide transport
    sends, or expose raw hidden provider reasoning.
    """

    packet = _context_packet(context) if context is not None else {}
    active_state = _dict(packet.get("active_thread_state", {}))
    scene_state = _dict(active_state.get("scene_state", {}))
    fast = _dict(fast_packet)
    stream = _dict(stream_plan)
    policy = _dict(packet_policy)
    tool_flow = _dict(internal_tool_flow)
    loop = _dict(tool_loop)
    memory = _dict(memory_delta)
    memory_ledger = _list_dicts(memory_observation_ledger)
    if not memory_ledger:
        memory_ledger = _list_dicts(loop.get("memory_observation_ledger", []))
    alignment = _dict(memory_alignment)
    novelty = _dict(stage142_semantic_novelty)
    packet_budget = _dict(stage143_packet_budget)
    context_economy = _dict(stage144_context_economy)
    outcome_appraisal = _dict(stage145_outcome_appraisal)
    reaction_kernel = _dict(stage145_reaction_kernel_shadow)
    react_state = _dict(stage148_react_state or packet.get("stage148_react_state", {}))
    user_directives = _dict(packet.get("stage149_user_directives", {}))
    visual = _dict(visual_delta)
    visible = _list_dicts(visible_segments)

    current_user_text = compact_text(str(user_text if user_text is not None else _context_field(context, "user_text")), 320)
    current_channel = str(channel if channel is not None else _context_field(context, "channel", "holo_cli") or "holo_cli").strip()
    current_thread = str(thread_key if thread_key is not None else _context_field(context, "thread_key", "holo_cli:main") or "holo_cli:main").strip()
    current_chat = str(chat_name if chat_name is not None else _context_field(context, "chat_name", "Holo") or "Holo").strip()
    event_id = str(turn_id or _dict(getattr(context, "metadata", {})).get("event_id", "") or stable_digest(current_thread, current_user_text, limit=12))
    try:
        uncertainty = float(getattr(context, "uncertainty_level", 0.0) or 0.0) if context is not None else 0.0
    except (TypeError, ValueError):
        uncertainty = 0.0

    deep_needed = bool(stream.get("deep_packet_needed", fast.get("deep_packet_needed", False)))
    gate_decision = "continue" if deep_needed else "stop"
    stream_mode = str(_dict(policy.get("continuity", {})).get("stream_mode", "") or "")
    if not stream_mode:
        stream_mode = "continuous_thought" if deep_needed else "compact_reply_packet"

    tool_names = _tool_names_from_loop(loop)
    if not tool_names and context is not None:
        tool_names = _tool_names_from_context(context)
    if not tool_names:
        for item in _list_dicts(tool_flow.get("tool_requests", [])):
            name = str(item.get("name", "") or "").strip()
            if name and name not in tool_names:
                tool_names.append(name)

    continuity = compact_text(str(active_state.get("continuity_summary", "") or ""), 220)
    scene = compact_text(str(scene_state.get("shared_frame", "") or ""), 180)
    memory_summary = compact_text(
        str(memory.get("summary", "") or continuity or "working state plus selected memory are compressed into this turn delta"),
        220,
    )
    visual_summary = compact_text(str(visual.get("summary", "") or scene), 180)

    nodes: list[dict[str, Any]] = [
        _node("external_user_input", "external user input", channel="external_user", kind="input", x=0.08, y=0.5, weight=0.72, summary=current_user_text),
        _node("holo_self", "I-state / Holo self", channel="i_state", kind="subject_state", x=0.26, y=0.5, weight=0.92, summary=continuity or "single subject state"),
        _node("fast_packet", "first reaction packet", channel="holo_inner", kind="provider_packet", x=0.43, y=0.28, weight=0.76, summary=str(fast.get("intent", "") or "intent triage")),
        _node("state_delta", "provider return state delta", channel="state_delta", kind="semantic_event", x=0.58, y=0.5, weight=max(0.42, _clamp(uncertainty)), summary=str(fast.get("continue_until", "") or "provider return updates local state")),
        _node("continue_gate", "continue gate", channel="holo_inner", kind="gate", x=0.72, y=0.5, weight=0.78 if deep_needed else 0.38, summary=f"decision={gate_decision}; stream_mode={stream_mode}"),
        _node("memory_delta", "memory delta", channel="memory_delta", kind="memory", x=0.45, y=0.76, weight=0.62, summary=memory_summary),
    ]
    edges: list[dict[str, Any]] = [
        _edge("external_user_input", "holo_self", relation="observed_by", weight=0.82, summary="external speech enters the single subject"),
        _edge("holo_self", "fast_packet", relation="builds_packet", weight=0.78, summary="I-state composes the fast provider packet"),
        _edge("fast_packet", "state_delta", relation="provider_return", weight=0.72, summary="return is parsed as a semantic event"),
        _edge("state_delta", "memory_delta", relation="writes_delta", weight=0.58, summary="salient update becomes working or candidate memory"),
        _edge("state_delta", "continue_gate", relation="updates_gate", weight=0.74, summary="local gate observes the new state"),
    ]

    if visual_summary:
        nodes.append(_node("visual_delta", "visual / world delta", channel="visual_delta", kind="sensor_state", x=0.45, y=0.9, weight=0.46, summary=visual_summary))
        edges.append(_edge("visual_delta", "holo_self", relation="grounds_state", weight=0.42, summary="sensor-derived world state feeds the same subject"))

    if user_directives:
        directive_count = int(user_directives.get("hard_directive_count", 0) or 0)
        directive_status = str(user_directives.get("status", "") or "base_only")
        identity = _dict(user_directives.get("core_identity", {}))
        nodes.append(
            _node(
                "user_directive_kernel",
                "user directive kernel",
                channel="user_directive",
                kind="constraint",
                x=0.31,
                y=0.08,
                weight=0.78 if directive_count else 0.44,
                summary=f"status={directive_status}; hard_directives={directive_count}; identity={str(identity.get('mode', '') or 'subject_runtime_not_roleplay')}",
            )
        )
        edges.append(_edge("holo_self", "user_directive_kernel", relation="maintains_visible_constraints", weight=0.62, summary="durable user corrections constrain visible expression"))
        edges.append(_edge("user_directive_kernel", "fast_packet", relation="constrains_provider_packet", weight=0.68, summary="user directives are included before persona and reply style"))
        edges.append(_edge("user_directive_kernel", "memory_delta", relation="separates_preference_from_log", weight=0.44, summary="user correction becomes reusable state rather than raw chat text only"))

    if deep_needed:
        nodes.append(
            _node("deep_packet", "deep continuation packet", channel="holo_inner", kind="provider_packet", x=0.87, y=0.34, weight=0.82, summary="continuation is provider-decided and locally gated")
        )
        edges.append(_edge("continue_gate", "deep_packet", relation="continues_to", weight=0.72, summary="next packet is allowed because new state remains useful"))
        edges.append(_edge("deep_packet", "state_delta", relation="next_return_updates", weight=0.48, summary="future returns re-enter the same state delta node"))

    if novelty:
        novelty_status = str(novelty.get("status", "") or "unknown")
        suppressed_count = int(novelty.get("suppressed_count", 0) or 0)
        candidate_count = int(novelty.get("candidate_count", 0) or 0)
        emitted_count = int(novelty.get("emitted_count", 0) or 0)
        nodes.append(
            _node(
                "semantic_novelty_gate",
                "semantic novelty gate",
                channel="semantic_novelty",
                kind="gate",
                x=0.78,
                y=0.58,
                weight=0.68 if novelty_status == "passed" else 0.36,
                summary=f"status={novelty_status}; emitted={emitted_count}/{candidate_count}; suppressed={suppressed_count}",
            )
        )
        edges.append(_edge("continue_gate", "semantic_novelty_gate", relation="gates_visible_continuation", weight=0.56, summary="A-prime to A-double-prime visible stream is checked for useful novelty"))

    if packet_budget:
        packet_count = int(packet_budget.get("packet_count", 0) or 0)
        sent_count = int(packet_budget.get("sent_count", 0) or 0)
        skipped_count = int(packet_budget.get("skipped_count", 0) or 0)
        stop_reason = str(packet_budget.get("stop_reason", "") or "unknown")
        nodes.append(
            _node(
                "packet_budget_gate",
                "packet budget gate",
                channel="packet_budget",
                kind="observability",
                x=0.78,
                y=0.42,
                weight=0.66 if skipped_count == 0 else 0.44,
                summary=f"packets={packet_count}; sent={sent_count}; skipped={skipped_count}; stop={stop_reason}",
            )
        )
        edges.append(_edge("fast_packet", "packet_budget_gate", relation="reports_packet_cost", weight=0.48, summary="fast packet timing and budget are observed"))
        edges.append(_edge("continue_gate", "packet_budget_gate", relation="reports_stop_reason", weight=0.52, summary="continuation stop reason is recorded without changing the gate"))
        if novelty:
            edges.append(_edge("semantic_novelty_gate", "packet_budget_gate", relation="reports_visible_gate_result", weight=0.44, summary="Stage142 outcome is linked to packet stop reason"))

    if context_economy:
        recommendation = str(context_economy.get("recommended_deep_policy", "") or context_economy.get("packet_policy_recommendation", "") or "keep")
        try:
            sufficiency = float(context_economy.get("context_sufficiency_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            sufficiency = 0.0
        try:
            waste = float(context_economy.get("context_waste_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            waste = 0.0
        shadow_only = bool(context_economy.get("shadow_only", True))
        weight = 0.36 + min(0.34, max(sufficiency, 1.0 - waste) * 0.34)
        nodes.append(
            _node(
                "context_economy_gate",
                "context economy gate",
                channel="context_economy",
                kind="observability",
                x=0.86,
                y=0.5,
                weight=weight,
                summary=f"policy={recommendation}; sufficiency={sufficiency:.2f}; waste={waste:.2f}; shadow_only={shadow_only}",
            )
        )
        if packet_budget:
            edges.append(_edge("packet_budget_gate", "context_economy_gate", relation="feeds_shadow_policy", weight=0.54, summary="packet budget evidence informs diagnostic context policy"))
        else:
            edges.append(_edge("continue_gate", "context_economy_gate", relation="feeds_shadow_policy", weight=0.36, summary="continuation state informs diagnostic context policy"))
        if novelty:
            edges.append(_edge("semantic_novelty_gate", "context_economy_gate", relation="feeds_context_waste_estimate", weight=0.46, summary="visible novelty outcome informs context waste estimate"))
        if alignment:
            edges.append(_edge("memory_alignment_gate", "context_economy_gate", relation="feeds_context_sufficiency", weight=0.42, summary="memory sufficiency informs context policy recommendation"))
        edges.append(_edge("context_economy_gate", "continue_gate", relation="shadow_recommendation_only", weight=0.28, summary="diagnostic recommendation is not enforced by Stage144"))

    if outcome_appraisal or reaction_kernel:
        prediction_error = 0.0
        try:
            prediction_error = float((outcome_appraisal or reaction_kernel).get("prediction_error", 0.0) or 0.0)
        except (TypeError, ValueError):
            prediction_error = 0.0
        delta_count = int(reaction_kernel.get("delta_count", len(_list_dicts(reaction_kernel.get("kernel_delta_candidates", [])))) or 0) if reaction_kernel else 0
        shadow_only = bool(reaction_kernel.get("shadow_only", outcome_appraisal.get("shadow_only", True)))
        applied = bool(reaction_kernel.get("applied", False))
        predicted_need = str(outcome_appraisal.get("predicted_user_need", "") or "")
        nodes.append(
            _node(
                "reaction_kernel_shadow",
                "reaction kernel shadow",
                channel="reaction_kernel",
                kind="observability",
                x=0.92,
                y=0.52,
                weight=0.34 + min(0.42, max(0.0, prediction_error) * 0.42),
                summary=f"prediction_error={prediction_error:.2f}; deltas={delta_count}; need={predicted_need}; shadow_only={shadow_only}; applied={applied}",
            )
        )
        if context_economy:
            edges.append(_edge("context_economy_gate", "reaction_kernel_shadow", relation="feeds_prediction_error", weight=0.54, summary="context economy is appraised against observed outcome"))
        if packet_budget:
            edges.append(_edge("packet_budget_gate", "reaction_kernel_shadow", relation="feeds_packet_outcome", weight=0.48, summary="packet cost and stop reason feed prediction-error appraisal"))
        if novelty:
            edges.append(_edge("semantic_novelty_gate", "reaction_kernel_shadow", relation="feeds_visible_outcome", weight=0.46, summary="visible novelty outcome feeds reaction-kernel shadow deltas"))
        if alignment:
            edges.append(_edge("memory_alignment_gate", "reaction_kernel_shadow", relation="feeds_memory_outcome", weight=0.42, summary="memory sufficiency affects reaction-kernel shadow deltas"))
        edges.append(_edge("reaction_kernel_shadow", "holo_self", relation="shadow_reaction_delta", weight=0.26, summary="shadow deltas are observed but not applied to durable policy"))

    if react_state:
        react_loop = _dict(react_state.get("react_loop", {}))
        plan = _dict(react_loop.get("plan", {}))
        event_log = _dict(react_state.get("event_log", {}))
        reusable = _dict(react_state.get("reusable_state_memory", {}))
        plan_action = str(plan.get("selected_action_hint", "") or "direct_answer")
        slot_count = int(reusable.get("slot_count", len(_list_dicts(reusable.get("slots", [])))) or 0)
        event_count = int(event_log.get("event_count", len(_list_dicts(event_log.get("events", [])))) or 0)
        nodes.append(
            _node(
                "stage148_react_loop",
                "perception-plan-action-observe loop",
                channel="react_loop",
                kind="agent_loop",
                x=0.34,
                y=0.22,
                weight=0.76,
                summary=f"plan={plan_action}; reusable_slots={slot_count}; recent_events={event_count}; authority=host_gated",
            )
        )
        edges.append(_edge("external_user_input", "stage148_react_loop", relation="perceives_event", weight=0.72, summary="raw event log enters reusable state memory"))
        edges.append(_edge("stage148_react_loop", "fast_packet", relation="builds_state_packet", weight=0.68, summary="ReAct state frames the provider packet"))
        edges.append(_edge("stage148_react_loop", "memory_delta", relation="separates_state_from_log", weight=0.58, summary="chat events are raw evidence; memory is reusable state"))
        if packet_budget:
            edges.append(_edge("packet_budget_gate", "stage148_react_loop", relation="observes_packet_outcome", weight=0.42, summary="packet stop reasons feed the next loop observation"))
        if context_economy:
            edges.append(_edge("context_economy_gate", "stage148_react_loop", relation="observes_context_policy", weight=0.4, summary="shadow context policy informs the next plan without direct enforcement"))

    ledger_nodes: set[str] = set()
    for index, item in enumerate(_list_dicts(loop.get("tool_observation_ledger", []))[:10]):
        call_id = str(item.get("provider_call_id", "") or item.get("tool", "") or f"tool_{index + 1}")
        tool_name = str(item.get("tool", "") or "tool")
        node_id = "tool_observation_" + _safe_node_suffix(call_id)
        ledger_nodes.add(node_id)
        y = 0.12 + (index % 5) * 0.1
        status = str(item.get("status", "") or "")
        summary = str(item.get("summary", "") or "")
        nodes.append(
            _node(
                node_id,
                tool_name,
                channel="tool_observation",
                kind="tool_observation",
                x=0.69,
                y=y,
                weight=0.66 if status not in {"rejected", "skipped", "denied"} else 0.34,
                summary=summary,
            )
        )
        edges.append(_edge("continue_gate", node_id, relation="local_tool_execution", weight=0.5, summary="Holo validates and executes provider-proposed tools"))
        edges.append(_edge(node_id, "state_delta", relation="tool_observation_reentry", weight=0.62, summary="actual tool observation re-enters the same I-state"))

    memory_observation_node_ids: list[str] = []
    for index, item in enumerate(memory_ledger[:10]):
        call_id = str(item.get("memory_call_id", "") or item.get("source_family", "") or f"memory_{index + 1}")
        source_family = str(item.get("source_family", "") or "memory")
        node_id = "memory_observation_" + _safe_node_suffix(call_id)
        memory_observation_node_ids.append(node_id)
        status = str(item.get("status", "") or "")
        summary = str(item.get("summary", "") or "")
        y = 0.62 + (index % 5) * 0.06
        nodes.append(
            _node(
                node_id,
                source_family,
                channel="memory_observation",
                kind="memory_observation",
                x=0.33,
                y=y,
                weight=0.68 if status == "grounded" else 0.42 if status == "weak" else 0.24,
                summary=summary or f"status={status}",
            )
        )
        edges.append(_edge(node_id, "holo_self", relation="memory_source_selected", weight=0.56, summary="selected memory evidence enters the current I-state"))
        edges.append(_edge(node_id, "memory_delta", relation="grounds_memory_delta", weight=0.62, summary="memory observation grounds visible recall claims"))

    if alignment:
        alignment_status = str(alignment.get("status", "") or "unknown")
        claim_count = int(alignment.get("claim_count", 0) or 0)
        unsupported_count = int(alignment.get("unsupported_claim_count", 0) or 0)
        contradicted_count = int(alignment.get("contradicted_claim_count", 0) or 0)
        if alignment_status == "aligned":
            alignment_weight = 0.74
        elif alignment_status == "weakly_aligned":
            alignment_weight = 0.48
        elif alignment_status == "no_memory_claim":
            alignment_weight = 0.32
        else:
            alignment_weight = 0.26
        nodes.append(
            _node(
                "memory_alignment_gate",
                "memory alignment gate",
                channel="memory_alignment",
                kind="gate",
                x=0.52,
                y=0.68,
                weight=alignment_weight,
                summary=f"status={alignment_status}; claims={claim_count}; unsupported={unsupported_count}; contradicted={contradicted_count}",
            )
        )
        if memory_observation_node_ids:
            for node_id in memory_observation_node_ids[:6]:
                edges.append(_edge(node_id, "memory_alignment_gate", relation="feeds_memory_alignment", weight=0.5, summary="memory evidence is checked against visible recall detail"))
        else:
            edges.append(_edge("memory_delta", "memory_alignment_gate", relation="memory_alignment_without_source", weight=0.32, summary="alignment gate saw no concrete memory observation node"))
        edges.append(_edge("memory_alignment_gate", "memory_delta", relation="aligns_memory_claims", weight=0.58, summary="source sufficiency gates visible memory claims"))
        for index, claim in enumerate(_list_dicts(alignment.get("claims", []))[:5]):
            claim_status = str(claim.get("status", "") or "")
            node_id = "claim_" + _safe_node_suffix(claim.get("claim_id", "") or f"{index + 1}")
            nodes.append(
                _node(
                    node_id,
                    str(claim.get("claim_family", "") or "memory claim"),
                    channel="memory_alignment",
                    kind="memory_claim",
                    x=0.61,
                    y=0.76 + min(index, 4) * 0.04,
                    weight=0.62 if claim_status == "aligned" else 0.42 if claim_status == "weak" else 0.24,
                    summary=str(claim.get("claim_text", "") or ""),
                )
            )
            edges.append(_edge(node_id, "memory_alignment_gate", relation="claim_checked_by", weight=0.44, summary=f"claim status={claim_status}"))

    for index, name in enumerate(tool_names[:8]):
        node_id = "tool_" + _safe_node_suffix(name)
        if node_id in ledger_nodes:
            continue
        y = 0.18 + (index % 4) * 0.12
        nodes.append(_node(node_id, name, channel="tool_result", kind="tool", x=0.7, y=y, weight=0.5, summary="local WSL-authorized tool observation"))
        edges.append(_edge("continue_gate", node_id, relation="may_request_tool", weight=0.42, summary="provider may propose, Holo validates and executes locally"))
        edges.append(_edge(node_id, "state_delta", relation="tool_observation_reentry", weight=0.56, summary="tool observation re-enters the next packet context"))

    if not visible and fast.get("shallow_reply"):
        visible.append({"role": "fast_reaction", "text": fast.get("shallow_reply", "")})
    for index, item in enumerate(visible[:5]):
        role = _visible_segment_role(item, index)
        text = compact_text(str(item.get("text", "") or ""), 260)
        if role == "fast_reaction":
            node_id = "visible_fast_reaction"
            x, y = 0.62, 0.18
        elif role == "deep_continuation":
            node_id = "visible_deep_continuation"
            x, y = 0.92, 0.66
        else:
            node_id = f"visible_segment_{index}"
            x, y = 0.78, 0.78 + index * 0.04
        nodes.append(_node(node_id, role, channel="holo_visible", kind="expression", x=x, y=y, weight=0.64, summary=text))
        source = "fast_packet" if role == "fast_reaction" else "deep_packet" if deep_needed else "continue_gate"
        if source in {node["id"] for node in nodes}:
            edges.append(_edge(source, node_id, relation="expresses_as", weight=0.64, summary="visible speech segment"))
        if novelty and node_id != "visible_fast_reaction":
            edges.append(_edge("semantic_novelty_gate", node_id, relation="allows_visible_segment", weight=0.48, summary="continuation passed deterministic novelty gate"))

    channel_counts = _channel_counts(nodes)
    return {
        "schema": STAGE135_SCHEMA,
        "stage": 135,
        "generated_at": utc_now(),
        "turn_id": event_id,
        "subject": {
            "subject_id": "holo",
            "thread_key": current_thread,
            "chat_name": current_chat,
            "channel": current_channel,
            "self_node": "holo_self",
        },
        "single_brain_boundary": {
            "decision_authority": "wsl_holo_host",
            "transport_role": "eyes_and_hands_only",
            "provider_role": "language_processing_module",
            "tool_execution_authority": "wsl_holo_host",
        },
        "continue_gate": {
            "decision": gate_decision,
            "deep_packet_needed": deep_needed,
            "stream_mode": stream_mode,
            "decision_source": str(stream.get("continuation_decision_source", "provider_fast_packet") or "provider_fast_packet"),
            "stop_reason": str(stream.get("stop_reason", "") or ""),
        },
        "nodes": nodes,
        "edges": edges,
        "metrics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "channel_count": len(channel_counts),
            "channels": channel_counts,
            "tool_node_count": sum(1 for node in nodes if node["channel"] == "tool_result"),
            "memory_observation_node_count": sum(1 for node in nodes if node["channel"] == "memory_observation"),
            "memory_alignment_node_count": sum(1 for node in nodes if node["channel"] == "memory_alignment"),
            "memory_alignment_claim_count": int(alignment.get("claim_count", 0) or 0) if alignment else 0,
            "memory_alignment_unsupported_count": int(alignment.get("unsupported_claim_count", 0) or 0) if alignment else 0,
            "memory_alignment_status": str(alignment.get("status", "") or "") if alignment else "",
            "semantic_novelty_node_count": sum(1 for node in nodes if node["channel"] == "semantic_novelty"),
            "semantic_novelty_status": str(novelty.get("status", "") or "") if novelty else "",
            "semantic_novelty_suppressed_count": int(novelty.get("suppressed_count", 0) or 0) if novelty else 0,
            "packet_budget_node_count": sum(1 for node in nodes if node["channel"] == "packet_budget"),
            "packet_budget_packet_count": int(packet_budget.get("packet_count", 0) or 0) if packet_budget else 0,
            "packet_budget_stop_reason": str(packet_budget.get("stop_reason", "") or "") if packet_budget else "",
            "context_economy_node_count": sum(1 for node in nodes if node["channel"] == "context_economy"),
            "context_economy_recommended_deep_policy": str(context_economy.get("recommended_deep_policy", "") or "") if context_economy else "",
            "context_economy_waste_score": float(context_economy.get("context_waste_score", 0.0) or 0.0) if context_economy else 0.0,
            "context_economy_sufficiency_score": float(context_economy.get("context_sufficiency_score", 0.0) or 0.0) if context_economy else 0.0,
            "context_economy_shadow_only": bool(context_economy.get("shadow_only", True)) if context_economy else False,
            "reaction_kernel_node_count": sum(1 for node in nodes if node["channel"] == "reaction_kernel"),
            "reaction_kernel_prediction_error": float(outcome_appraisal.get("prediction_error", reaction_kernel.get("prediction_error", 0.0)) or 0.0) if (outcome_appraisal or reaction_kernel) else 0.0,
            "reaction_kernel_delta_count": int(reaction_kernel.get("delta_count", 0) or 0) if reaction_kernel else 0,
            "reaction_kernel_shadow_only": bool(reaction_kernel.get("shadow_only", outcome_appraisal.get("shadow_only", True))) if (outcome_appraisal or reaction_kernel) else False,
            "react_loop_node_count": sum(1 for node in nodes if node["channel"] == "react_loop"),
            "react_loop_plan_action": str(_dict(_dict(react_state.get("react_loop", {})).get("plan", {})).get("selected_action_hint", "") or "") if react_state else "",
            "react_loop_event_count": int(_dict(react_state.get("event_log", {})).get("event_count", 0) or 0) if react_state else 0,
            "reusable_state_slot_count": int(_dict(react_state.get("reusable_state_memory", {})).get("slot_count", 0) or 0) if react_state else 0,
            "user_directive_node_count": sum(1 for node in nodes if node["channel"] == "user_directive"),
            "user_directive_count": int(user_directives.get("hard_directive_count", 0) or 0) if user_directives else 0,
            "user_directive_status": str(user_directives.get("status", "") or "") if user_directives else "",
            "visible_node_count": sum(1 for node in nodes if node["channel"] == "holo_visible"),
            "topology_digest": "stage135:" + stable_digest(json.dumps(nodes, ensure_ascii=False, sort_keys=True), json.dumps(edges, ensure_ascii=False, sort_keys=True), limit=12),
        },
        "privacy": {
            "raw_provider_content_included": False,
            "raw_hidden_reasoning_included": False,
            "raw_memory_text_included": False,
        },
    }


def render_stage135_i_state_topology_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage135 I-State Topology</title>
  <style>
    body {{ margin:0; background:#f7f8f5; color:#16201d; font:14px/1.45 system-ui, -apple-system, "Microsoft YaHei", sans-serif; }}
    header {{ padding:16px 20px; background:#ffffff; border-bottom:1px solid #d8ded9; }}
    h1 {{ margin:0 0 5px; font-size:23px; }}
    main {{ display:grid; grid-template-columns:300px 1fr; min-height:calc(100vh - 72px); }}
    aside {{ padding:14px; border-right:1px solid #d8ded9; background:#ffffff; overflow:auto; }}
    section {{ padding:14px; display:grid; gap:12px; grid-template-rows:minmax(430px, 1fr) auto; }}
    .panel {{ background:#ffffff; border:1px solid #d8ded9; border-radius:6px; padding:12px; min-width:0; }}
    canvas {{ display:block; width:100%; min-height:420px; background:#fbfcfa; border:1px solid #d8ded9; border-radius:5px; }}
    .metric {{ display:grid; grid-template-columns:1fr auto; gap:8px; padding:7px 0; border-bottom:1px solid #edf0ee; }}
    .small {{ color:#63706b; font-size:12px; }}
    .legend {{ display:grid; grid-template-columns:18px 1fr; gap:8px; align-items:center; margin:6px 0; }}
    .swatch {{ width:14px; height:14px; border-radius:3px; border:1px solid rgba(0,0,0,.14); }}
    pre {{ white-space:pre-wrap; max-height:260px; overflow:auto; background:#f3f6f4; border:1px solid #d8ded9; padding:10px; border-radius:4px; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns:1fr; }} aside {{ border-right:0; border-bottom:1px solid #d8ded9; }} }}
  </style>
</head>
<body>
<header>
  <h1>Stage135 I-State Topology</h1>
  <div class="small">external input -> Holo I-state -> provider packets -> state delta -> continue gate -> tools / memory / visible speech</div>
</header>
<main>
  <aside>
    <div id="metrics"></div>
    <h3>Channels</h3>
    <div id="legend"></div>
  </aside>
  <section>
    <div class="panel"><canvas id="topology" width="1280" height="620"></canvas></div>
    <div class="panel"><pre id="selected"></pre></div>
  </section>
</main>
<script>
window.stage135Topology = {data};
const payload = window.stage135Topology;
const colors = {{
  external_user: "#6f8f9e",
  i_state: "#b6534f",
  holo_inner: "#6d5d9a",
  state_delta: "#3c8065",
  memory_delta: "#b78232",
  memory_alignment: "#8b5a38",
  semantic_novelty: "#5a6b78",
  packet_budget: "#6c7a2a",
  context_economy: "#8a6f2a",
  reaction_kernel: "#a45d55",
  react_loop: "#5268b2",
  visual_delta: "#458080",
  tool_result: "#7f8a3f",
  holo_visible: "#2f6f91"
}};
let selected = "";
function scaleCanvas(canvas) {{
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.width;
  const height = Math.max(420, Math.round(width * 0.48));
  canvas.style.height = height + "px";
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return {{ ctx, width, height }};
}}
function nodeAt(x, y, width, height) {{
  const nodes = payload.nodes || [];
  for (let i = nodes.length - 1; i >= 0; i--) {{
    const n = nodes[i];
    const nx = 34 + Number(n.x || 0) * (width - 68);
    const ny = 34 + Number(n.y || 0) * (height - 68);
    const r = 8 + Number(n.weight || 0.5) * 18;
    if (Math.hypot(nx - x, ny - y) <= r + 4) return n.id;
  }}
  return "";
}}
function draw() {{
  const canvas = document.getElementById("topology");
  const {{ ctx, width, height }} = scaleCanvas(canvas);
  const nodes = payload.nodes || [];
  const edges = payload.edges || [];
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  ctx.clearRect(0, 0, width, height);
  ctx.lineWidth = 1.4;
  edges.forEach(e => {{
    const a = byId[e.source], b = byId[e.target];
    if (!a || !b) return;
    const ax = 34 + Number(a.x || 0) * (width - 68);
    const ay = 34 + Number(a.y || 0) * (height - 68);
    const bx = 34 + Number(b.x || 0) * (width - 68);
    const by = 34 + Number(b.y || 0) * (height - 68);
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.strokeStyle = `rgba(42,55,51,${{0.18 + Number(e.weight || 0.4) * 0.38}})`;
    ctx.stroke();
  }});
  nodes.forEach(n => {{
    const x = 34 + Number(n.x || 0) * (width - 68);
    const y = 34 + Number(n.y || 0) * (height - 68);
    const r = 8 + Number(n.weight || 0.5) * 18;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = colors[n.channel] || "#777";
    ctx.globalAlpha = n.id === selected ? 1 : 0.78;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.lineWidth = n.id === selected ? 3 : 1;
    ctx.strokeStyle = n.id === selected ? "#16201d" : "rgba(0,0,0,.18)";
    ctx.stroke();
    ctx.fillStyle = "#16201d";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(n.label || n.id, x + r + 6, y + 4);
  }});
  const active = byId[selected] || byId.holo_self || nodes[0] || {{}};
  document.getElementById("selected").textContent = JSON.stringify(active, null, 2);
}}
document.getElementById("topology").addEventListener("click", ev => {{
  const rect = ev.currentTarget.getBoundingClientRect();
  selected = nodeAt(ev.clientX - rect.left, ev.clientY - rect.top, rect.width, rect.height);
  draw();
}});
function renderSide() {{
  const m = payload.metrics || {{}};
  document.getElementById("metrics").innerHTML = `
    <div class="metric"><span>turn</span><strong>${{payload.turn_id || "-"}}</strong></div>
    <div class="metric"><span>gate</span><strong>${{(payload.continue_gate || {{}}).decision || "-"}}</strong></div>
    <div class="metric"><span>nodes</span><strong>${{m.node_count || 0}}</strong></div>
    <div class="metric"><span>edges</span><strong>${{m.edge_count || 0}}</strong></div>
    <div class="metric"><span>tools</span><strong>${{m.tool_node_count || 0}}</strong></div>
    <div class="metric"><span>visible</span><strong>${{m.visible_node_count || 0}}</strong></div>`;
  document.getElementById("legend").innerHTML = Object.entries(colors).map(([key, value]) =>
    `<div class="legend"><span class="swatch" style="background:${{value}}"></span><span>${{key}}</span></div>`
  ).join("");
}}
window.addEventListener("resize", draw);
renderSide();
selected = "holo_self";
draw();
</script>
</body>
</html>
"""


def write_stage135_i_state_topology_artifacts(
    repo_root: Path | str,
    *,
    output_dir: Path | str | None = None,
    sample_query: str = "show Holo's I-state topology",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    target = Path(output_dir) if output_dir is not None else root / DEFAULT_OUTPUT_DIR
    if not target.is_absolute():
        target = root / target
    target.mkdir(parents=True, exist_ok=True)
    sample_stream = {
        "deep_packet_needed": True,
        "continuation_decision_source": "provider_fast_packet",
        "stop_reason": "",
    }
    payload = build_stage135_i_state_topology(
        user_text=sample_query,
        channel="holo_cli",
        thread_key="holo_cli:stage135",
        chat_name="Stage135",
        fast_packet={
            "intent": "i_state_topology",
            "scene": "research_visualization",
            "deep_packet_needed": True,
            "shallow_reply": "I first map the input onto my current state.",
            "continue_until": "the topology has a useful state delta",
        },
        stream_plan=sample_stream,
        packet_policy={"continuity": {"stream_mode": "continuous_thought"}, "target_input_tokens": 48000},
        tool_loop={"round_count": 1, "executed_tools": ["memory_recall", "workspace_inspect"]},
        visible_segments=[
            {"role": "fast_reaction", "text": "I first map the input onto my current state."},
            {"role": "deep_continuation", "text": "Then I continue only when the state delta remains useful."},
        ],
        memory_delta={"summary": "working memory, selected long memory, and the new provider event are compressed into state"},
        visual_delta={"summary": "future camera or visual algorithms enter as world-state deltas"},
    )
    json_path = target / "stage135_i_state_topology_payload.json"
    html_path = target / "stage135_i_state_topology.html"
    atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(html_path, render_stage135_i_state_topology_html(payload))
    return {
        "status": "ok",
        "schema": STAGE135_SCHEMA,
        "stage": 135,
        "html_path": str(html_path),
        "payload_path": str(json_path),
        "node_count": payload["metrics"]["node_count"],
        "edge_count": payload["metrics"]["edge_count"],
        "privacy": payload["privacy"],
    }
