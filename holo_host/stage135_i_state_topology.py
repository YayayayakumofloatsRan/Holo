from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import atomic_write_text, compact_text, stable_digest, utc_now
from .engineering_action_fabric import normalize_engineering_action_ledger

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
    stage150_context_memory_fabric: dict[str, Any] | None = None,
    stage156_context_compiler: dict[str, Any] | None = None,
    stage151_tool_decision: dict[str, Any] | None = None,
    stage152_deepseek_tool_loop: dict[str, Any] | None = None,
    stage153_agent_event_stream: dict[str, Any] | None = None,
    stage160r_agent_loop_fsm: dict[str, Any] | None = None,
    stage161_model_tool_arbitration: dict[str, Any] | None = None,
    stage170_market_research_gate: dict[str, Any] | None = None,
    market_research_pack_ledger: list[dict[str, Any]] | None = None,
    filing_text_retrieval: dict[str, Any] | None = None,
    stage173_market_research_report: dict[str, Any] | None = None,
    market_research_report_ledger: list[dict[str, Any]] | None = None,
    stage192_market_research_feedback_loop: dict[str, Any] | None = None,
    stage193_market_research_action_plan: dict[str, Any] | None = None,
    stage194_market_research_plan_execution: dict[str, Any] | None = None,
    stage195_market_research_continuation_loop: dict[str, Any] | None = None,
    stage196_market_research_source_promotion: dict[str, Any] | None = None,
    stage197_market_research_report_assembly: dict[str, Any] | None = None,
    stage198_market_research_finalization_gate: dict[str, Any] | None = None,
    stage199_market_research_task_dossier: dict[str, Any] | None = None,
    stage200_market_research_dossier_resume: dict[str, Any] | None = None,
    stage201_market_research_dossier_registry: dict[str, Any] | None = None,
    stage177_market_research_remediation: dict[str, Any] | None = None,
    stage178_evidence_action_remediation: dict[str, Any] | None = None,
    stage179_live_remediation_loop: dict[str, Any] | None = None,
    stage180_live_remediation_execution: dict[str, Any] | None = None,
    stage181_live_remediation_stress: dict[str, Any] | None = None,
    stage182_remediation_continuation: dict[str, Any] | None = None,
    stage183_agent_capability_gauntlet: dict[str, Any] | None = None,
    stage184_real_use_drill: dict[str, Any] | None = None,
    stage186_live_crawler_search: dict[str, Any] | None = None,
    web_observation_ledger: list[dict[str, Any]] | None = None,
    engineering_action_ledger: list[dict[str, Any]] | None = None,
    project_state_graph: dict[str, Any] | None = None,
    network_health: dict[str, Any] | None = None,
    canonical_stop: dict[str, Any] | None = None,
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
    context_memory_fabric = _dict(stage150_context_memory_fabric or packet.get("stage150_context_memory_fabric", {}))
    context_compiler = _dict(stage156_context_compiler or packet.get("stage156_context_compiler", {}))
    tool_decision = _dict(stage151_tool_decision or packet.get("stage151_tool_decision", {}))
    native_tool_loop = _dict(stage152_deepseek_tool_loop or packet.get("stage152_deepseek_tool_loop", {}))
    agent_event_stream = _dict(stage153_agent_event_stream or packet.get("stage153_agent_event_stream", {}))
    agent_loop_fsm = _dict(stage160r_agent_loop_fsm or packet.get("stage160r_agent_loop_fsm", {}))
    model_arbitration = _dict(stage161_model_tool_arbitration or packet.get("stage161_model_tool_arbitration", {}))
    market_research_gate = _dict(stage170_market_research_gate or packet.get("stage170_market_research_gate", {}))
    market_research_ledger = _list_dicts(market_research_pack_ledger or packet.get("market_research_pack_ledger", []))
    filing_retrieval = _dict(filing_text_retrieval or packet.get("filing_text_retrieval", {}))
    market_research_report = _dict(stage173_market_research_report or packet.get("stage173_market_research_report", {}))
    market_research_report_ledger_rows = _list_dicts(market_research_report_ledger or packet.get("market_research_report_ledger", []))
    market_research_feedback = _dict(stage192_market_research_feedback_loop or packet.get("stage192_market_research_feedback_loop", {}))
    market_research_action_plan = _dict(stage193_market_research_action_plan or packet.get("stage193_market_research_action_plan", {}))
    market_research_plan_execution = _dict(stage194_market_research_plan_execution or packet.get("stage194_market_research_plan_execution", {}))
    market_research_continuation = _dict(stage195_market_research_continuation_loop or packet.get("stage195_market_research_continuation_loop", {}))
    market_research_source_promotion = _dict(
        stage196_market_research_source_promotion
        or packet.get("stage196_market_research_source_promotion", {})
        or market_research_continuation.get("stage196_market_research_source_promotion", {})
    )
    market_research_report_assembly = _dict(stage197_market_research_report_assembly or packet.get("stage197_market_research_report_assembly", {}))
    market_research_finalization = _dict(stage198_market_research_finalization_gate or packet.get("stage198_market_research_finalization_gate", {}))
    market_research_dossier = _dict(stage199_market_research_task_dossier or packet.get("stage199_market_research_task_dossier", {}))
    market_research_dossier_resume = _dict(stage200_market_research_dossier_resume or packet.get("stage200_market_research_dossier_resume", {}))
    market_research_dossier_registry = _dict(stage201_market_research_dossier_registry or packet.get("stage201_market_research_dossier_registry", {}))
    market_research_remediation = _dict(stage177_market_research_remediation or packet.get("stage177_market_research_remediation", {}))
    evidence_action_remediation = _dict(stage178_evidence_action_remediation or packet.get("stage178_evidence_action_remediation", {}))
    live_remediation_loop = _dict(stage179_live_remediation_loop or packet.get("stage179_live_remediation_loop", {}))
    live_remediation_execution = _dict(stage180_live_remediation_execution or packet.get("stage180_live_remediation_execution", {}))
    live_remediation_stress = _dict(stage181_live_remediation_stress or packet.get("stage181_live_remediation_stress", {}))
    remediation_continuation = _dict(stage182_remediation_continuation or packet.get("stage182_remediation_continuation", {}))
    agent_capability_gauntlet = _dict(stage183_agent_capability_gauntlet or packet.get("stage183_agent_capability_gauntlet", {}))
    real_use_drill = _dict(stage184_real_use_drill or packet.get("stage184_real_use_drill", {}))
    live_crawler_search = _dict(stage186_live_crawler_search or packet.get("stage186_live_crawler_search", {}))
    web_ledger = _list_dicts(web_observation_ledger or packet.get("web_observation_ledger", []))
    engineering_ledger = normalize_engineering_action_ledger(engineering_action_ledger or packet.get("engineering_action_ledger", []))
    project_state = _dict(project_state_graph or packet.get("project_state_graph", {}))
    network_state = _dict(network_health or packet.get("network_health", {}))
    canonical_state = _dict(canonical_stop)
    if not canonical_state:
        raw_canonical_reason = str(packet.get("canonical_stop_reason", "") or agent_event_stream.get("canonical_stop_reason", "") or "")
        raw_canonical_source = str(packet.get("canonical_stop_source", "") or agent_event_stream.get("canonical_stop_source", "") or "")
        if raw_canonical_reason or raw_canonical_source:
            canonical_state = {
                "canonical_stop_reason": raw_canonical_reason,
                "canonical_stop_source": raw_canonical_source,
            }
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

    if context_memory_fabric:
        working_packet = _dict(context_memory_fabric.get("working_context_packet", {}))
        slots = _list_dicts(working_packet.get("reusable_state_slots", []))
        open_loops = _list_dicts(working_packet.get("open_loops", []))
        evidence_view = _list_dicts(working_packet.get("evidence_ledger_view", []))
        compact = _dict(context_memory_fabric.get("background_compact", {}))
        internal_only = bool(context_memory_fabric.get("background_compact_internal_only", compact.get("user_visible") is False))
        nodes.append(
            _node(
                "context_memory_fabric",
                "context memory fabric",
                channel="context_memory_fabric",
                kind="context_packet",
                x=0.39,
                y=0.36,
                weight=0.72,
                summary=f"slots={len(slots)}; evidence={len(evidence_view)}; open_loops={len(open_loops)}; compact_internal={internal_only}",
            )
        )
        if react_state:
            edges.append(_edge("stage148_react_loop", "context_memory_fabric", relation="feeds_structured_context", weight=0.58, summary="reusable state is organized into a working context packet"))
        else:
            edges.append(_edge("holo_self", "context_memory_fabric", relation="builds_structured_context", weight=0.46, summary="Holo state is organized before provider generation"))
        if user_directives:
            edges.append(_edge("user_directive_kernel", "context_memory_fabric", relation="overrides_persona_memory", weight=0.58, summary="user directives outrank persona and style memory in the context packet"))
        edges.append(_edge("context_memory_fabric", "fast_packet", relation="frames_provider_packet", weight=0.62, summary="structured context is rendered before provider speech"))
        edges.append(_edge("context_memory_fabric", "memory_delta", relation="separates_state_from_transcript", weight=0.5, summary="background compact is internal and raw chat is not treated as reusable memory"))

    if context_compiler:
        estimated_tokens = int(context_compiler.get("estimated_prompt_tokens", 0) or 0)
        cache_ratio = float(context_compiler.get("cache_hit_ratio", 0.0) or 0.0)
        truncated = list(context_compiler.get("truncated_sections", []) or [])
        nodes.append(
            _node(
                "stage156_context_compiler",
                "context compiler",
                channel="context_compiler",
                kind="context_packet",
                x=0.48,
                y=0.38,
                weight=0.7 if estimated_tokens else 0.36,
                summary=f"tokens={estimated_tokens}; stable={context_compiler.get('stable_prefix_tokens', 0)}; dynamic={context_compiler.get('dynamic_suffix_tokens', 0)}; cache_hit_ratio={cache_ratio}; truncated={len(truncated)}",
            )
        )
        source = "context_memory_fabric" if context_memory_fabric else "holo_self"
        edges.append(_edge(source, "stage156_context_compiler", relation="compiles_context_sections", weight=0.62, summary="Stage150 working context is compiled into stable prefix and dynamic suffix"))
        edges.append(_edge("stage156_context_compiler", "fast_packet", relation="frames_provider_packet", weight=0.58, summary="compiled context controls prompt budget and cache discipline"))

    if project_state:
        project_name = str(project_state.get("project", "") or _dict(project_state.get("active_project", {})).get("title", "") or "project")
        active_tasks = _list_dicts(project_state.get("active_tasks", []))
        open_questions = _list_dicts(project_state.get("open_questions", []))
        next_actions = _list_dicts(project_state.get("next_actions", []))
        blocked_items = _list_dicts(project_state.get("blocked_items", []))
        nodes.append(
            _node(
                "project_state_graph",
                "project state graph",
                channel="project_state_graph",
                kind="project_memory",
                x=0.28,
                y=0.86,
                weight=0.7 if (active_tasks or open_questions or next_actions) else 0.38,
                summary=f"project={project_name}; tasks={len(active_tasks)}; open={len(open_questions)}; next={len(next_actions)}; blocked={len(blocked_items)}",
            )
        )
        source = "context_memory_fabric" if context_memory_fabric else "holo_self"
        edges.append(_edge(source, "project_state_graph", relation="feeds_project_continuity", weight=0.58, summary="project goals, decisions, and open loops are kept outside raw chat history"))
        edges.append(_edge("project_state_graph", "fast_packet", relation="frames_project_context", weight=0.46, summary="active tasks and next actions enter the provider context packet"))
        edges.append(_edge("project_state_graph", "memory_delta", relation="separates_project_state_from_chat_log", weight=0.42, summary="durable project state is queryable independently from transcript recall"))

    if tool_decision:
        selected_actions = _list_dicts(tool_decision.get("selected_actions", []))
        action_candidates = _list_dicts(tool_decision.get("action_candidates", []))
        purpose = str(tool_decision.get("purpose", "") or "answer_direct")
        nodes.append(
            _node(
                "stage151_tool_decision_loop",
                "tool decision loop",
                channel="tool_decision_loop",
                kind="agent_loop",
                x=0.52,
                y=0.18,
                weight=0.72 if selected_actions else 0.42,
                summary=f"purpose={purpose}; candidates={len(action_candidates)}; selected={len(selected_actions)}",
            )
        )
        edges.append(_edge("external_user_input", "stage151_tool_decision_loop", relation="triages_tool_need", weight=0.64, summary="current turn is triaged for web, time, memory, and tool evidence"))
        context_target = "context_memory_fabric" if context_memory_fabric else "holo_self"
        edges.append(_edge("stage151_tool_decision_loop", context_target, relation="feeds_observation_context", weight=0.58, summary="tool decision observations enter the structured context packet"))
        edges.append(_edge("stage151_tool_decision_loop", "fast_packet", relation="frames_provider_packet", weight=0.46, summary="tool evidence state is available before provider speech"))

    if native_tool_loop:
        stop_reason = str(native_tool_loop.get("stop_reason", "") or "unknown")
        tool_call_count = int(native_tool_loop.get("tool_call_count", 0) or 0)
        executed_count = int(native_tool_loop.get("executed_count", 0) or 0)
        nodes.append(
            _node(
                "stage152_deepseek_tool_loop",
                "DeepSeek native tool loop",
                channel="deepseek_native_tool_loop",
                kind="agent_loop",
                x=0.62,
                y=0.12,
                weight=0.72 if executed_count else 0.4,
                summary=f"calls={tool_call_count}; executed={executed_count}; stop={stop_reason}",
            )
        )
        if tool_decision:
            edges.append(_edge("stage151_tool_decision_loop", "stage152_deepseek_tool_loop", relation="seeds_native_tool_policy", weight=0.52, summary="host triage and context give DeepSeek tool affordances"))
        else:
            edges.append(_edge("external_user_input", "stage152_deepseek_tool_loop", relation="provider_tool_intent", weight=0.44, summary="provider may request host tools after seeing the packet"))
        edges.append(_edge("stage152_deepseek_tool_loop", "state_delta", relation="tool_observation_reentry", weight=0.62, summary="native DeepSeek tool results are appended as role=tool and re-enter the provider loop"))

    if agent_event_stream:
        event_count = int(agent_event_stream.get("event_count", 0) or len(_list_dicts(agent_event_stream.get("events", []))))
        nodes.append(
            _node(
                "stage153_agent_event_stream",
                "interactive agent event stream",
                channel="agent_event_stream",
                kind="observability",
                x=0.74,
                y=0.2,
                weight=0.58 if event_count else 0.32,
                summary=f"events={event_count}; hidden reasoning redacted",
            )
        )
        source = "stage152_deepseek_tool_loop" if native_tool_loop else "stage151_tool_decision_loop" if tool_decision else "state_delta"
        edges.append(_edge(source, "stage153_agent_event_stream", relation="renders_auditable_cli_events", weight=0.54, summary="grounded tool and packet evidence is rendered as CLI events without hidden reasoning"))
        edges.append(_edge("stage153_agent_event_stream", "visible_fast_reaction" if visible else "state_delta", relation="frames_interactive_console", weight=0.42, summary="the console shows external events before or with final speech"))

    if agent_loop_fsm:
        step_count = int(agent_loop_fsm.get("step_count", 0) or len(_list_dicts(agent_loop_fsm.get("steps", []))))
        stop_reason = str(agent_loop_fsm.get("canonical_stop_reason", "") or agent_loop_fsm.get("stop_reason", "") or "")
        mandatory_count = len(list(agent_loop_fsm.get("mandatory_actions", []) or []))
        nodes.append(
            _node(
                "stage160r_agent_loop_fsm",
                "depersonalized agent loop FSM",
                channel="agent_loop_fsm",
                kind="agent_loop",
                x=0.7,
                y=0.1,
                weight=0.76 if mandatory_count else 0.5,
                summary=f"steps={step_count}; mandatory={mandatory_count}; stop={stop_reason}",
            )
        )
        source = "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage160r_agent_loop_fsm", relation="host_controls_mandatory_actions", weight=0.68, summary="mandatory actions must execute, reject, or fail before final speech"))
        edges.append(_edge("stage160r_agent_loop_fsm", "stage153_agent_event_stream" if agent_event_stream else "visible_fast_reaction", relation="drives_auditable_events", weight=0.62, summary="CLI events are rendered from FSM steps, not hidden reasoning"))

    if model_arbitration:
        selected_action = str(model_arbitration.get("selected_action", "") or "")
        source = str(model_arbitration.get("source", "") or "model_arbitration")
        nodes.append(
            _node(
                "stage161_model_tool_arbitration",
                "model-first tool arbitration",
                channel="model_tool_arbitration",
                kind="agent_loop",
                x=0.58,
                y=0.08,
                weight=0.72 if selected_action and selected_action != "answer_direct" else 0.46,
                summary=f"selected={selected_action or 'answer_direct'}; source={source}; host validates and ledgers",
            )
        )
        edges.append(_edge("external_user_input", "stage161_model_tool_arbitration", relation="model_selects_next_action", weight=0.62, summary="the model sees structured context and available actions before proposing the next action"))
        if agent_loop_fsm:
            edges.append(_edge("stage161_model_tool_arbitration", "stage160r_agent_loop_fsm", relation="host_fsm_executes_or_rejects", weight=0.68, summary="the host FSM treats the model choice as proposal, not authority"))
        elif native_tool_loop:
            edges.append(_edge("stage161_model_tool_arbitration", "stage152_deepseek_tool_loop", relation="maps_native_tool_calls_to_proposals", weight=0.5, summary="DeepSeek native tool calls are normalized as model-proposed actions"))

    search_scores = [
        _dict(row.get("search_evidence", {}))
        for row in web_ledger
        if isinstance(row, dict) and isinstance(row.get("search_evidence", {}), dict)
    ]
    if search_scores:
        best = max(search_scores, key=lambda item: float(item.get("evidence_score", 0.0) or 0.0))
        nodes.append(
            _node(
                "stage162_search_evidence_controller",
                "search evidence controller",
                channel="search_evidence_controller",
                kind="observability_gate",
                x=0.66,
                y=0.06,
                weight=max(0.32, min(0.86, float(best.get("evidence_score", 0.0) or 0.0))),
                summary=f"best_status={best.get('status', '')}; score={best.get('evidence_score', 0)}; observations={len(web_ledger)}",
            )
        )
        source = "stage161_model_tool_arbitration" if model_arbitration else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage162_search_evidence_controller", relation="evaluates_search_sufficiency", weight=0.62, summary="web results are scored for source sufficiency before final grounding"))
        if agent_loop_fsm:
            edges.append(_edge("stage162_search_evidence_controller", "stage160r_agent_loop_fsm", relation="feeds_stop_reason", weight=0.5, summary="search sufficiency informs host stop and failure reporting"))

    page_scores = [
        _dict(row.get("page_evidence", {}))
        for row in web_ledger
        if isinstance(row, dict) and isinstance(row.get("page_evidence", {}), dict)
    ]
    if page_scores:
        best_page = max(page_scores, key=lambda item: float(item.get("best_evidence_score", 0.0) or 0.0))
        nodes.append(
            _node(
                "stage163_page_evidence_verifier",
                "page evidence verifier",
                channel="page_evidence_verifier",
                kind="observability_gate",
                x=0.74,
                y=0.12,
                weight=max(0.34, min(0.9, float(best_page.get("best_evidence_score", 0.0) or 0.0))),
                summary=f"best_status={best_page.get('status', '')}; opened={best_page.get('opened_count', 0)}; selected={compact_text(str(best_page.get('selected_url', '') or ''), 90)}",
            )
        )
        source = "stage162_search_evidence_controller" if search_scores else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage163_page_evidence_verifier", relation="opens_sources_and_verifies_page_body", weight=0.58, summary="candidate search URLs are opened and scored against page-body evidence"))
        if agent_loop_fsm:
            edges.append(_edge("stage163_page_evidence_verifier", "stage160r_agent_loop_fsm", relation="feeds_evidence_sufficiency", weight=0.48, summary="page-level support informs final grounding and stop reasoning"))

    source_syntheses = [
        _dict(row.get("source_synthesis", {}))
        for row in web_ledger
        if isinstance(row, dict) and isinstance(row.get("source_synthesis", {}), dict)
    ]
    if source_syntheses:
        best_synthesis = max(source_syntheses, key=lambda item: float(item.get("confidence", 0.0) or 0.0))
        nodes.append(
            _node(
                "stage164_source_synthesis",
                "source synthesis",
                channel="source_synthesis",
                kind="observability_gate",
                x=0.82,
                y=0.18,
                weight=max(0.34, min(0.9, float(best_synthesis.get("confidence", 0.0) or 0.0))),
                summary=f"status={best_synthesis.get('status', '')}; supported={best_synthesis.get('supported_source_count', 0)}; risks={','.join(str(x) for x in list(best_synthesis.get('risk_flags', []) or [])) or '-'}",
            )
        )
        source = "stage163_page_evidence_verifier" if page_scores else "stage162_search_evidence_controller" if search_scores else "stage151_tool_decision_loop"
        edges.append(_edge(source, "stage164_source_synthesis", relation="synthesizes_opened_sources", weight=0.56, summary="supported page evidence is combined into a source-level answer basis"))
        if agent_loop_fsm:
            edges.append(_edge("stage164_source_synthesis", "stage160r_agent_loop_fsm", relation="feeds_final_grounding", weight=0.46, summary="source synthesis informs final evidence reporting"))
        citation_count = len(
            [
                item
                for item in list(best_synthesis.get("citations", []) or [])
                if isinstance(item, dict) and str(item.get("url", "") or "").strip()
            ]
        )
        nodes.append(
            _node(
                "stage165_answer_citation_formatter",
                "answer citation formatter",
                channel="answer_citation_formatter",
                kind="observability_gate",
                x=0.88,
                y=0.24,
                weight=max(0.34, min(0.9, float(best_synthesis.get("confidence", 0.0) or 0.0))),
                summary=f"status={best_synthesis.get('status', '')}; citations={citation_count}; visible answer uses source synthesis",
            )
        )
        edges.append(_edge("stage164_source_synthesis", "stage165_answer_citation_formatter", relation="formats_cited_answer", weight=0.54, summary="source synthesis is converted into a visible cited answer"))
        edges.append(_edge("stage165_answer_citation_formatter", "state_delta", relation="reports_cited_evidence", weight=0.38, summary="final answer can expose source URLs and bounded support status"))

    if filing_retrieval:
        retrieval_status = str(filing_retrieval.get("status", "") or "unknown")
        retrieval_source = str(filing_retrieval.get("retrieval_source", "") or "")
        text_chars = int(filing_retrieval.get("filing_text_char_count", 0) or 0)
        nodes.append(
            _node(
                "stage172_filing_text_retrieval",
                "filing text retrieval",
                channel="filing_text_retrieval",
                kind="tool_observation",
                x=0.73,
                y=0.31,
                weight=0.72 if retrieval_status == "ok" else 0.24,
                summary=f"status={retrieval_status}; source={retrieval_source}; chars={text_chars}",
            )
        )
        source = "stage163_page_evidence_verifier" if "page_evidence" in retrieval_source else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage172_filing_text_retrieval", relation="extracts_filing_text", weight=0.5, summary="authoritative page evidence is converted into filing text"))
        target = "stage171_market_research_pack_action" if market_research_ledger else "state_delta"
        edges.append(_edge("stage172_filing_text_retrieval", target, relation="feeds_market_research_pack", weight=0.51, summary="filing text feeds market-research pack construction"))

    if market_research_ledger:
        first_market = dict(market_research_ledger[0])
        action_status = str(first_market.get("status", "") or "unknown")
        pack_status = str(first_market.get("pack_status", "") or "")
        evidence_count = int(first_market.get("evidence_item_count", 0) or 0)
        nodes.append(
            _node(
                "stage171_market_research_pack_action",
                "market research pack action",
                channel="market_research_pack_action",
                kind="tool_observation",
                x=0.78,
                y=0.34,
                weight=0.74 if action_status == "ok" else 0.28,
                summary=f"status={action_status}; pack={pack_status}; evidence={evidence_count}",
            )
        )
        source = "stage161_model_tool_arbitration" if model_arbitration else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage171_market_research_pack_action", relation="executes_market_research_pack", weight=0.55, summary="host action builds filing evidence pack"))
        target = "stage170_market_research_gate" if market_research_gate else "state_delta"
        edges.append(_edge("stage171_market_research_pack_action", target, relation="feeds_market_research_gate", weight=0.53, summary="pack ledger can support market research answer gate"))

    if market_research_gate:
        gate_status = str(market_research_gate.get("status", "") or "unknown")
        claim_count = int(market_research_gate.get("claim_count", 0) or 0)
        supported_count = int(market_research_gate.get("supported_claim_count", 0) or 0)
        unsupported_count = int(market_research_gate.get("unsupported_claim_count", 0) or 0)
        weight = 0.72 if gate_status == "supported" else 0.36 if gate_status in {"not_required", "ready_no_financial_claim"} else 0.22
        nodes.append(
            _node(
                "stage170_market_research_gate",
                "market research evidence gate",
                channel="market_research_gate",
                kind="observability_gate",
                x=0.86,
                y=0.32,
                weight=weight,
                summary=f"status={gate_status}; claims={claim_count}; supported={supported_count}; unsupported={unsupported_count}",
            )
        )
        source = "stage165_answer_citation_formatter" if source_syntheses else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage170_market_research_gate", relation="requires_filing_pack_before_financial_claims", weight=0.58, summary="market research claims require a source-authority-sufficient filing pack"))
        edges.append(_edge("stage170_market_research_gate", "state_delta", relation="gates_market_research_answer", weight=0.52, summary="unsupported financial claims are bounded before visible reply"))

    if market_research_report:
        report_status = str(market_research_report.get("status", "") or "unknown")
        section_count = int(market_research_report.get("section_count", 0) or 0)
        metric_count = int(market_research_report.get("metric_count", 0) or 0)
        citation_count = int(market_research_report.get("citation_count", 0) or 0)
        weight = 0.76 if report_status == "evidence_ready" else 0.34
        nodes.append(
            _node(
                "stage173_market_research_report",
                "market research report",
                channel="market_research_report",
                kind="observability_gate",
                x=0.9,
                y=0.36,
                weight=weight,
                summary=f"status={report_status}; sections={section_count}; metrics={metric_count}; citations={citation_count}",
            )
        )
        source = "stage170_market_research_gate" if market_research_gate else "stage171_market_research_pack_action" if market_research_ledger else "external_user_input"
        edges.append(_edge(source, "stage173_market_research_report", relation="synthesizes_market_research_report", weight=0.56, summary="filing pack evidence is converted into a bounded analyst report"))
        edges.append(_edge("stage173_market_research_report", "state_delta", relation="reports_market_research_evidence", weight=0.45, summary="report exposes citations, limitations, and unsupported-claim accounting"))

    if market_research_report_ledger_rows:
        first_report_action = dict(market_research_report_ledger_rows[0])
        action_status = str(first_report_action.get("status", "") or "unknown")
        report_status = str(first_report_action.get("report_status", "") or "")
        citation_count = int(first_report_action.get("citation_count", 0) or 0)
        nodes.append(
            _node(
                "stage174_market_research_report_action",
                "market research report action",
                channel="market_research_report_action",
                kind="tool_observation",
                x=0.84,
                y=0.38,
                weight=0.78 if action_status == "ok" else 0.3,
                summary=f"status={action_status}; report={report_status}; citations={citation_count}",
            )
        )
        source = "stage161_model_tool_arbitration" if model_arbitration else "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage174_market_research_report_action", relation="executes_market_research_report", weight=0.56, summary="host action generates a filing-grounded market research report"))
        target = "stage173_market_research_report" if market_research_report else "state_delta"
        edges.append(_edge("stage174_market_research_report_action", target, relation="emits_market_research_report", weight=0.54, summary="report action emits report evidence for topology and reply metadata"))

    if market_research_feedback:
        feedback_status = str(market_research_feedback.get("status", "") or "unknown")
        stop_reason = str(market_research_feedback.get("final_stop_reason", "") or "")
        next_action = str(market_research_feedback.get("next_action", "") or "")
        can_finalize = bool(market_research_feedback.get("can_finalize", False))
        score = float(market_research_feedback.get("best_sufficiency_score", 0.0) or 0.0)
        nodes.append(
            _node(
                "stage192_market_research_feedback_loop",
                "market research feedback loop",
                channel="market_research_feedback",
                kind="agent_loop",
                x=0.93,
                y=0.4,
                weight=0.78 if can_finalize else 0.4,
                summary=f"status={feedback_status}; score={score}; next={next_action}; stop={stop_reason}",
            )
        )
        source = "stage173_market_research_report" if market_research_report else "stage174_market_research_report_action" if market_research_report_ledger_rows else "stage171_market_research_pack_action" if market_research_ledger else "external_user_input"
        edges.append(_edge(source, "stage192_market_research_feedback_loop", relation="appraises_report_readiness", weight=0.6, summary="report sufficiency and missing evidence are fed into a public feedback loop"))
        edges.append(_edge("stage192_market_research_feedback_loop", "state_delta", relation="selects_next_research_action_or_stop", weight=0.5, summary="feedback loop decides whether report can finalize or needs more evidence"))

    if market_research_action_plan:
        plan_status = str(market_research_action_plan.get("status", "") or "unknown")
        next_action = str(market_research_action_plan.get("next_action", "") or "")
        candidate_count = int(market_research_action_plan.get("candidate_count", 0) or len(list(market_research_action_plan.get("action_candidates", []) or [])))
        can_finalize = bool(market_research_action_plan.get("can_finalize", False))
        nodes.append(
            _node(
                "stage193_market_research_action_plan",
                "market research action plan",
                channel="market_research_action_plan",
                kind="action_plan",
                x=0.96,
                y=0.43,
                weight=0.76 if can_finalize else 0.48 if plan_status == "planned" else 0.28,
                summary=f"status={plan_status}; next={next_action}; candidates={candidate_count}; stop={market_research_action_plan.get('stop_reason', '')}",
            )
        )
        source = "stage192_market_research_feedback_loop" if market_research_feedback else "stage173_market_research_report" if market_research_report else "external_user_input"
        edges.append(_edge(source, "stage193_market_research_action_plan", relation="converts_feedback_to_actions", weight=0.62, summary="Stage192 readiness feedback is converted into concrete search, filing, pack, or report actions"))
        edges.append(_edge("stage193_market_research_action_plan", "state_delta", relation="reports_next_market_research_action", weight=0.48, summary="operator and CLI can inspect the next planned market-research action"))

    if market_research_plan_execution:
        exec_status = str(market_research_plan_execution.get("status", "") or "unknown")
        executed_action = str(market_research_plan_execution.get("executed_action", "") or "")
        executed_count = int(market_research_plan_execution.get("executed_count", 0) or 0)
        rejected_count = int(market_research_plan_execution.get("rejected_count", 0) or 0)
        failed_count = int(market_research_plan_execution.get("failed_count", 0) or 0)
        nodes.append(
            _node(
                "stage194_market_research_plan_execution",
                "market research plan execution",
                channel="market_research_plan_execution",
                kind="tool_observation",
                x=0.97,
                y=0.46,
                weight=0.78 if exec_status == "executed" else 0.32,
                summary=f"status={exec_status}; action={executed_action}; executed={executed_count}; rejected={rejected_count}; failed={failed_count}; stop={market_research_plan_execution.get('canonical_stop_reason', '')}",
            )
        )
        source = "stage193_market_research_action_plan" if market_research_action_plan else "stage192_market_research_feedback_loop" if market_research_feedback else "external_user_input"
        edges.append(_edge(source, "stage194_market_research_plan_execution", relation="executes_market_research_action_plan", weight=0.64, summary="planned market-research action is executed through host tools and ledgers"))
        edges.append(_edge("stage194_market_research_plan_execution", "stage192_market_research_feedback_loop" if market_research_feedback else "state_delta", relation="feeds_post_action_feedback", weight=0.54, summary="execution ledgers re-enter report-readiness feedback"))

    if market_research_continuation:
        continuation_status = str(market_research_continuation.get("status", "") or "unknown")
        round_count = int(market_research_continuation.get("round_count", 0) or 0)
        executed_round_count = int(market_research_continuation.get("executed_round_count", 0) or 0)
        can_finalize = bool(market_research_continuation.get("can_finalize", False))
        nodes.append(
            _node(
                "stage195_market_research_continuation_loop",
                "market research continuation loop",
                channel="market_research_continuation",
                kind="action_loop",
                x=0.985,
                y=0.49,
                weight=0.82 if can_finalize else 0.5 if executed_round_count else 0.28,
                summary=f"status={continuation_status}; rounds={round_count}; executed={executed_round_count}; ready={can_finalize}; stop={market_research_continuation.get('canonical_stop_reason', '')}",
            )
        )
        source = "stage194_market_research_plan_execution" if market_research_plan_execution else "stage193_market_research_action_plan" if market_research_action_plan else "stage192_market_research_feedback_loop" if market_research_feedback else "external_user_input"
        edges.append(_edge(source, "stage195_market_research_continuation_loop", relation="continues_market_research_until_stop", weight=0.68, summary="bounded feedback-plan-execute rounds continue until report readiness or a boundary"))
        edges.append(_edge("stage195_market_research_continuation_loop", "state_delta", relation="reports_market_research_loop_stop", weight=0.52, summary="continuation loop exposes round count, readiness, and canonical stop reason"))

    if market_research_source_promotion:
        promotion_status = str(market_research_source_promotion.get("status", "") or "unknown")
        authority_status = str(market_research_source_promotion.get("authority_status", "") or "")
        source_family = str(market_research_source_promotion.get("source_family", "") or "")
        page_status = str(market_research_source_promotion.get("page_evidence_status", "") or "")
        can_build_pack = bool(market_research_source_promotion.get("can_build_market_research_pack", False))
        nodes.append(
            _node(
                "stage196_market_research_source_promotion",
                "market research source promotion",
                channel="market_research_source_promotion",
                kind="source_observation",
                x=0.99,
                y=0.52,
                weight=0.84 if can_build_pack else 0.36,
                summary=f"status={promotion_status}; authority={authority_status}; family={source_family}; page={page_status}; pack={can_build_pack}",
            )
        )
        source = "stage195_market_research_continuation_loop" if market_research_continuation else "stage194_market_research_plan_execution" if market_research_plan_execution else "web_observation_ledger"
        edges.append(_edge(source, "stage196_market_research_source_promotion", relation="promotes_source_to_pack_ready_evidence", weight=0.7, summary="authoritative web/page evidence is promoted into a market-research source state"))
        edges.append(_edge("stage196_market_research_source_promotion", "stage171_market_research_pack_action" if market_research_ledger else "state_delta", relation="enables_market_research_pack", weight=0.54, summary="promoted filing source can feed pack generation"))

    if market_research_report_assembly:
        assembly_status = str(market_research_report_assembly.get("status", "") or "unknown")
        ready = bool(market_research_report_assembly.get("final_report_ready", False))
        citation_status = str(market_research_report_assembly.get("citation_quality_status", "") or "")
        source_count = len(list(market_research_report_assembly.get("ordered_sources", []) or []))
        nodes.append(
            _node(
                "stage197_market_research_report_assembly",
                "market research report assembly",
                channel="market_research_report_assembly",
                kind="observability_gate",
                x=0.995,
                y=0.55,
                weight=0.86 if ready else 0.34,
                summary=f"status={assembly_status}; ready={ready}; citation={citation_status}; sources={source_count}",
            )
        )
        source = "stage196_market_research_source_promotion" if market_research_source_promotion else "stage173_market_research_report" if market_research_report else "state_delta"
        edges.append(_edge(source, "stage197_market_research_report_assembly", relation="checks_report_consumes_promoted_source", weight=0.72, summary="report assembly verifies that promoted sources are represented in final citations"))
        edges.append(_edge("stage197_market_research_report_assembly", "state_delta", relation="reports_final_market_research_readiness", weight=0.54, summary="assembled report state exposes ready, insufficient-evidence, and citation-mismatch outcomes"))

    if market_research_finalization:
        final_status = str(market_research_finalization.get("status", "") or "unknown")
        ready = bool(market_research_finalization.get("final_visible_text_ready", False))
        citation_status = str(market_research_finalization.get("citation_quality_status", "") or "")
        nodes.append(
            _node(
                "stage198_market_research_finalization_gate",
                "market research finalization gate",
                channel="market_research_finalization",
                kind="expression_gate",
                x=0.997,
                y=0.58,
                weight=0.88 if ready else 0.38,
                summary=f"status={final_status}; ready={ready}; citation={citation_status}; stop={market_research_finalization.get('canonical_stop_reason', '')}",
            )
        )
        source = "stage197_market_research_report_assembly" if market_research_report_assembly else "stage173_market_research_report" if market_research_report else "state_delta"
        edges.append(_edge(source, "stage198_market_research_finalization_gate", relation="converts_report_readiness_to_visible_final", weight=0.73, summary="report-readiness state becomes a visible final report or an evidence-bound failure"))
        edges.append(_edge("stage198_market_research_finalization_gate", "state_delta", relation="gates_market_research_final_reply", weight=0.55, summary="market research finalization replaces unsupported visible text with a grounded report boundary"))

    if market_research_dossier:
        dossier_status = str(market_research_dossier.get("status", "") or "unknown")
        source_count = int(market_research_dossier.get("source_count", 0) or 0)
        metric_count = int(market_research_dossier.get("metric_count", 0) or 0)
        next_count = len(list(market_research_dossier.get("next_actions", []) or []))
        nodes.append(
            _node(
                "stage199_market_research_task_dossier",
                "market research task dossier",
                channel="market_research_dossier",
                kind="working_memory",
                x=0.999,
                y=0.62,
                weight=0.86 if dossier_status == "report_ready" else 0.48,
                summary=f"status={dossier_status}; sources={source_count}; metrics={metric_count}; next={next_count}",
            )
        )
        source = "stage198_market_research_finalization_gate" if market_research_finalization else "stage197_market_research_report_assembly" if market_research_report_assembly else "state_delta"
        edges.append(_edge(source, "stage199_market_research_task_dossier", relation="persists_market_research_resume_state", weight=0.7, summary="final report state becomes a resumable research dossier"))
        edges.append(_edge("stage199_market_research_task_dossier", "state_delta", relation="exposes_research_continuity", weight=0.52, summary="dossier exposes sources, metrics, open items, and next actions for continuation"))

    if market_research_dossier_resume:
        resume_status = str(market_research_dossier_resume.get("status", "") or "unknown")
        selected_action = str(market_research_dossier_resume.get("selected_action", "") or "none")
        execution = _dict(market_research_dossier_resume.get("stage194_market_research_plan_execution", {}))
        executed = int(execution.get("executed_count", 0) or 0)
        nodes.append(
            _node(
                "stage200_market_research_dossier_resume",
                "market research dossier resume",
                channel="market_research_dossier_resume",
                kind="action_plan",
                x=0.999,
                y=0.66,
                weight=0.82 if resume_status in {"resumed", "completed", "already_complete"} else 0.44,
                summary=f"status={resume_status}; action={selected_action}; executed={executed}; stop={market_research_dossier_resume.get('canonical_stop_reason', '')}",
            )
        )
        source = "stage199_market_research_task_dossier" if market_research_dossier else "state_delta"
        edges.append(_edge(source, "stage200_market_research_dossier_resume", relation="resumes_market_research_next_action", weight=0.72, summary="dossier next actions become a bounded host action resume"))
        edges.append(_edge("stage200_market_research_dossier_resume", "state_delta", relation="updates_market_research_resume_state", weight=0.54, summary="resume execution returns updated dossier and stop reason"))

    if market_research_dossier_registry:
        registry_status = str(market_research_dossier_registry.get("status", "") or "unknown")
        lookup = _dict(market_research_dossier_registry.get("lookup", {}))
        lookup_status = str(lookup.get("status", "") or "")
        nodes.append(
            _node(
                "stage201_market_research_dossier_registry",
                "market research dossier registry",
                channel="market_research_dossier_registry",
                kind="working_memory",
                x=0.999,
                y=0.7,
                weight=0.8 if lookup_status == "found" else 0.36,
                summary=f"status={registry_status}; lookup={lookup_status}; stop={market_research_dossier_registry.get('canonical_stop_reason', '')}",
            )
        )
        source = "stage200_market_research_dossier_resume" if market_research_dossier_resume else "stage199_market_research_task_dossier" if market_research_dossier else "state_delta"
        edges.append(_edge(source, "stage201_market_research_dossier_registry", relation="persists_latest_market_research_dossier", weight=0.7, summary="latest dossier state is persisted by thread/project for future turns"))
        edges.append(_edge("stage201_market_research_dossier_registry", "state_delta", relation="restores_research_continuity", weight=0.54, summary="registry lookup makes long-running market research resumable without transcript reconstruction"))

    if market_research_remediation:
        remediation_status = str(market_research_remediation.get("status", "") or "unknown")
        action_count = len(list(market_research_remediation.get("remediation_actions", []) or []))
        risk_count = len(list(market_research_remediation.get("risk_flags", []) or []))
        can_finalize = bool(market_research_remediation.get("can_finalize", False))
        nodes.append(
            _node(
                "stage177_market_research_remediation",
                "market research remediation",
                channel="market_research_remediation",
                kind="action_plan",
                x=0.94,
                y=0.42,
                weight=0.72 if can_finalize else 0.42,
                summary=f"status={remediation_status}; risks={risk_count}; actions={action_count}; can_finalize={can_finalize}",
            )
        )
        source = "stage173_market_research_report" if market_research_report else "stage170_market_research_gate" if market_research_gate else "external_user_input"
        edges.append(_edge(source, "stage177_market_research_remediation", relation="diagnoses_market_research_failure", weight=0.58, summary="domain benchmark failures are converted into evidence-remediation actions"))
        edges.append(_edge("stage177_market_research_remediation", "state_delta", relation="plans_next_evidence_action", weight=0.48, summary="operator-facing next actions prevent unsupported market-research finalization"))

    if evidence_action_remediation:
        remediation_status = str(evidence_action_remediation.get("status", "") or "unknown")
        issue_count = int(evidence_action_remediation.get("issue_count", 0) or 0)
        action_count = int(evidence_action_remediation.get("action_count", 0) or len(list(evidence_action_remediation.get("actions", []) or [])))
        can_finalize = bool(evidence_action_remediation.get("can_finalize", False))
        nodes.append(
            _node(
                "stage178_evidence_action_remediation",
                "evidence action remediation",
                channel="evidence_action_remediation",
                kind="action_plan",
                x=0.95,
                y=0.48,
                weight=0.74 if can_finalize else 0.44,
                summary=f"status={remediation_status}; issues={issue_count}; actions={action_count}; can_finalize={can_finalize}",
            )
        )
        source = "stage177_market_research_remediation" if market_research_remediation else "stage153_agent_event_stream" if agent_event_stream else "external_user_input"
        edges.append(_edge(source, "stage178_evidence_action_remediation", relation="generalizes_evidence_gap_to_action", weight=0.57, summary="cross-domain evidence gaps are converted into bounded next actions"))
        edges.append(_edge("stage178_evidence_action_remediation", "state_delta", relation="blocks_or_allows_finalization", weight=0.47, summary="answers finalize only when evidence-action remediation is clean"))

    if live_remediation_loop:
        loop_status = str(live_remediation_loop.get("status", "") or "unknown")
        next_count = len(list(live_remediation_loop.get("next_action_candidates", []) or []))
        selected_action = str(live_remediation_loop.get("selected_action_type", "") or "")
        blocked = bool(live_remediation_loop.get("blocked", False))
        nodes.append(
            _node(
                "stage179_live_remediation_loop",
                "live remediation loop",
                channel="live_remediation_loop",
                kind="agent_loop_bridge",
                x=0.96,
                y=0.54,
                weight=0.7 if blocked else 0.42,
                summary=f"status={loop_status}; selected={selected_action}; next_actions={next_count}; blocked={blocked}",
            )
        )
        source = "stage178_evidence_action_remediation" if evidence_action_remediation else "stage160r_agent_loop_fsm" if agent_loop_fsm else "external_user_input"
        edges.append(_edge(source, "stage179_live_remediation_loop", relation="feeds_remediation_back_to_fsm", weight=0.58, summary="evidence remediation actions become live agent-loop next actions"))
        edges.append(_edge("stage179_live_remediation_loop", "state_delta", relation="updates_next_action_state", weight=0.48, summary="the live loop exposes the next action candidate and stop reason"))

    if live_remediation_execution:
        execution_status = str(live_remediation_execution.get("status", "") or "unknown")
        executed_count = int(live_remediation_execution.get("executed_count", 0) or 0)
        rejected_count = int(live_remediation_execution.get("rejected_count", 0) or 0)
        failed_count = int(live_remediation_execution.get("failed_count", 0) or 0)
        nodes.append(
            _node(
                "stage180_live_remediation_executor",
                "live remediation executor",
                channel="live_remediation_executor",
                kind="agent_action_executor",
                x=1.0,
                y=0.61,
                weight=0.75 if executed_count else 0.45,
                summary=f"status={execution_status}; executed={executed_count}; rejected={rejected_count}; failed={failed_count}",
            )
        )
        source = "stage179_live_remediation_loop" if live_remediation_loop else "stage178_evidence_action_remediation" if evidence_action_remediation else "stage160r_agent_loop_fsm" if agent_loop_fsm else "external_user_input"
        edges.append(_edge(source, "stage180_live_remediation_executor", relation="executes_remediation_action", weight=0.62, summary="planned remediation actions are executed through existing host action surfaces"))
        edges.append(_edge("stage180_live_remediation_executor", "state_delta", relation="remediation_observation_reentry", weight=0.6, summary="execution observations re-enter the agent loop as grounding evidence"))

    if live_remediation_stress:
        stress_summary = _dict(live_remediation_stress.get("summary", {}))
        case_count = int(stress_summary.get("case_count", live_remediation_stress.get("case_count", 0)) or 0)
        fallback_count = int(stress_summary.get("fallback_recovery_count", 0) or 0)
        budget_count = int(stress_summary.get("budget_guard_count", 0) or 0)
        nodes.append(
            _node(
                "stage181_live_remediation_stress",
                "live remediation stress",
                channel="live_remediation_stress",
                kind="agent_stress_gate",
                x=1.0,
                y=0.68,
                weight=0.76 if str(live_remediation_stress.get("status", "") or "") == "passed" else 0.42,
                summary=f"cases={case_count}; fallback_recovery={fallback_count}; budget_guards={budget_count}; status={live_remediation_stress.get('status', '')}",
            )
        )
        source = "stage180_live_remediation_executor" if live_remediation_execution else "stage179_live_remediation_loop" if live_remediation_loop else "stage178_evidence_action_remediation" if evidence_action_remediation else "external_user_input"
        edges.append(_edge(source, "stage181_live_remediation_stress", relation="stress_tests_remediation_execution", weight=0.54, summary="adversarial fixtures verify remediation execution under fallback, budget, and missing-evidence pressure"))
        edges.append(_edge("stage181_live_remediation_stress", "state_delta", relation="records_agent_loop_robustness", weight=0.48, summary="stress metrics become topology evidence for live-loop robustness"))

    if remediation_continuation:
        continuation_status = str(remediation_continuation.get("status", "") or "unknown")
        continuation_rounds = int(remediation_continuation.get("round_count", 0) or 0)
        continuation_executed = int(remediation_continuation.get("executed_count", 0) or 0)
        continuation_stop = str(remediation_continuation.get("canonical_stop_reason", "") or "")
        nodes.append(
            _node(
                "stage182_remediation_continuation",
                "remediation continuation",
                channel="remediation_continuation",
                kind="agent_loop_continuation",
                x=1.0,
                y=0.75,
                weight=0.78 if continuation_status == "completed" else 0.48,
                summary=f"status={continuation_status}; rounds={continuation_rounds}; executed={continuation_executed}; stop={continuation_stop}",
            )
        )
        source = (
            "stage180_live_remediation_executor"
            if live_remediation_execution
            else "stage181_live_remediation_stress"
            if live_remediation_stress
            else "stage179_live_remediation_loop"
            if live_remediation_loop
            else "stage178_evidence_action_remediation"
            if evidence_action_remediation
            else "external_user_input"
        )
        edges.append(_edge(source, "stage182_remediation_continuation", relation="continues_remediation_until_sufficient_or_stopped", weight=0.58, summary="remaining remediation actions are looped through execution and sufficiency scoring"))
        edges.append(_edge("stage182_remediation_continuation", "state_delta", relation="reenters_fsm_with_sufficiency", weight=0.52, summary="multi-round remediation observations update the live agent loop stop state"))

    if agent_capability_gauntlet:
        gauntlet_summary = _dict(agent_capability_gauntlet.get("summary", {}))
        gauntlet_status = str(agent_capability_gauntlet.get("status", "") or "unknown")
        gauntlet_cases = int(gauntlet_summary.get("case_count", agent_capability_gauntlet.get("case_count", 0)) or 0)
        gauntlet_passed = int(gauntlet_summary.get("passed_case_count", 0) or 0)
        gauntlet_score = float(gauntlet_summary.get("overall_score", 0.0) or 0.0)
        nodes.append(
            _node(
                "stage183_agent_capability_gauntlet",
                "agent capability gauntlet",
                channel="agent_capability_gauntlet",
                kind="agent_benchmark_gate",
                x=1.0,
                y=0.83,
                weight=0.8 if gauntlet_status == "passed" else 0.4,
                summary=f"status={gauntlet_status}; cases={gauntlet_cases}; passed={gauntlet_passed}; score={gauntlet_score}",
            )
        )
        source = (
            "stage182_remediation_continuation"
            if remediation_continuation
            else "stage180_live_remediation_executor"
            if live_remediation_execution
            else "stage160r_agent_loop_fsm"
            if agent_loop_fsm
            else "external_user_input"
        )
        edges.append(_edge(source, "stage183_agent_capability_gauntlet", relation="benchmarks_agent_kernel_capability", weight=0.57, summary="engineering, market research, and remediation surfaces are tested as one agent capability bundle"))
        edges.append(_edge("stage183_agent_capability_gauntlet", "state_delta", relation="records_capability_pressure", weight=0.5, summary="gauntlet score becomes topology evidence for practical agent readiness"))

    if real_use_drill:
        drill_summary = _dict(real_use_drill.get("summary", {}))
        drill_status = str(real_use_drill.get("status", "") or "unknown")
        drill_cases = int(drill_summary.get("case_count", real_use_drill.get("case_count", 0)) or 0)
        drill_passed = int(drill_summary.get("passed_case_count", 0) or 0)
        full_score = float(drill_summary.get("full_loop_score", 0.0) or 0.0)
        baseline_score = float(drill_summary.get("claim_only_baseline_score", 0.0) or 0.0)
        nodes.append(
            _node(
                "stage184_real_use_drill",
                "real use agent drill",
                channel="real_use_drill",
                kind="agent_real_use_gate",
                x=1.0,
                y=0.91,
                weight=0.82 if drill_status == "passed" else 0.42,
                summary=f"status={drill_status}; cases={drill_cases}; passed={drill_passed}; full={full_score}; baseline={baseline_score}",
            )
        )
        source = (
            "stage183_agent_capability_gauntlet"
            if agent_capability_gauntlet
            else "stage154_engineering_action_fabric"
            if engineering_ledger
            else "stage151_tool_decision_loop"
            if tool_decision
            else "external_user_input"
        )
        edges.append(_edge(source, "stage184_real_use_drill", relation="executes_real_agent_drills", weight=0.58, summary="temporary-workspace engineering actions and web evidence drills are executed instead of assumed"))
        edges.append(_edge("stage184_real_use_drill", "state_delta", relation="records_real_use_capability_pressure", weight=0.52, summary="real-use drill deltas compare full loop behavior against claim-only baseline"))

    if live_crawler_search:
        crawler_status = str(live_crawler_search.get("status", "") or "unknown")
        query_count = int(live_crawler_search.get("query_count", 0) or 0)
        opened_count = int(live_crawler_search.get("opened_page_count", 0) or 0)
        source_count = len(list(live_crawler_search.get("source_urls", []) or []))
        nodes.append(
            _node(
                "stage186_live_crawler_search",
                "live crawler search",
                channel="live_crawler_search",
                kind="web_crawler_gate",
                x=1.0,
                y=0.96,
                weight=0.84 if crawler_status == "sufficient" else 0.42,
                summary=f"status={crawler_status}; queries={query_count}; opened={opened_count}; sources={source_count}",
            )
        )
        source = "stage151_tool_decision_loop" if tool_decision else "external_user_input"
        edges.append(_edge(source, "stage186_live_crawler_search", relation="executes_query_open_evaluate_loop", weight=0.6, summary="search intent becomes a bounded query/open/evidence sufficiency crawler loop"))
        edges.append(_edge("stage186_live_crawler_search", "state_delta", relation="records_web_evidence_sufficiency", weight=0.54, summary="crawler evidence and stop reason become inspectable agent state"))

    if canonical_state or network_state:
        canonical_reason = str(canonical_state.get("canonical_stop_reason", "") or "unknown")
        canonical_source = str(canonical_state.get("canonical_stop_source", "") or "none")
        network_enabled = network_state.get("network_enabled", "")
        last_web_status = str(network_state.get("last_web_status", "") or "")
        nodes.append(
            _node(
                "stage159_kernel_hardening",
                "kernel hardening",
                channel="kernel_hardening",
                kind="observability_gate",
                x=0.82,
                y=0.16,
                weight=0.6,
                summary=f"stop={canonical_reason}; source={canonical_source}; network_enabled={network_enabled}; last_web={last_web_status}; public metadata sanitized",
            )
        )
        source = "stage153_agent_event_stream" if agent_event_stream else "stage152_deepseek_tool_loop" if native_tool_loop else "stage151_tool_decision_loop" if tool_decision else "state_delta"
        edges.append(_edge(source, "stage159_kernel_hardening", relation="hardens_public_surfaces", weight=0.5, summary="public metadata is sanitized and stop reasons are canonicalized"))
        edges.append(_edge("stage159_kernel_hardening", "state_delta", relation="reports_kernel_health", weight=0.42, summary="network health and canonical stop reason remain observability-only"))

    if engineering_ledger:
        ok_count = sum(1 for row in engineering_ledger if str(row.get("status", "") or "") == "ok")
        changed_count = sum(len(list(row.get("files_changed", []) or [])) for row in engineering_ledger)
        read_count = sum(len(list(row.get("files_read", []) or [])) for row in engineering_ledger)
        nodes.append(
            _node(
                "stage154_engineering_action_fabric",
                "engineering action fabric",
                channel="engineering_action_fabric",
                kind="tool_fabric",
                x=0.66,
                y=0.22,
                weight=0.68 if ok_count else 0.36,
                summary=f"actions={len(engineering_ledger)}; ok={ok_count}; read={read_count}; changed={changed_count}",
            )
        )
        source = "stage153_agent_event_stream" if agent_event_stream else "stage151_tool_decision_loop" if tool_decision else "holo_self"
        edges.append(_edge(source, "stage154_engineering_action_fabric", relation="executes_workspace_actions", weight=0.58, summary="repo-scoped engineering actions produce auditable ledgers"))
        edges.append(_edge("stage154_engineering_action_fabric", "state_delta", relation="engineering_observation_reentry", weight=0.6, summary="search/read/patch/test/diff evidence re-enters the same subject state"))

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
            "context_memory_fabric_node_count": sum(1 for node in nodes if node["channel"] == "context_memory_fabric"),
            "context_memory_fabric_slot_count": len(_list_dicts(_dict(context_memory_fabric.get("working_context_packet", {})).get("reusable_state_slots", []))) if context_memory_fabric else 0,
            "context_memory_fabric_open_loop_count": len(_list_dicts(_dict(context_memory_fabric.get("working_context_packet", {})).get("open_loops", []))) if context_memory_fabric else 0,
            "context_memory_fabric_evidence_count": len(_list_dicts(_dict(context_memory_fabric.get("working_context_packet", {})).get("evidence_ledger_view", []))) if context_memory_fabric else 0,
            "context_compiler_node_count": sum(1 for node in nodes if node["channel"] == "context_compiler"),
            "context_compiler_estimated_prompt_tokens": int(context_compiler.get("estimated_prompt_tokens", 0) or 0) if context_compiler else 0,
            "context_compiler_cache_hit_ratio": float(context_compiler.get("cache_hit_ratio", 0.0) or 0.0) if context_compiler else 0.0,
            "context_compiler_truncated_count": len(list(context_compiler.get("truncated_sections", []) or [])) if context_compiler else 0,
            "tool_decision_loop_node_count": sum(1 for node in nodes if node["channel"] == "tool_decision_loop"),
            "tool_decision_loop_selected_count": len(_list_dicts(tool_decision.get("selected_actions", []))) if tool_decision else 0,
            "tool_decision_loop_purpose": str(tool_decision.get("purpose", "") or "") if tool_decision else "",
            "deepseek_native_tool_loop_node_count": sum(1 for node in nodes if node["channel"] == "deepseek_native_tool_loop"),
            "deepseek_native_tool_loop_tool_call_count": int(native_tool_loop.get("tool_call_count", 0) or 0) if native_tool_loop else 0,
            "deepseek_native_tool_loop_stop_reason": str(native_tool_loop.get("stop_reason", "") or "") if native_tool_loop else "",
            "agent_event_stream_node_count": sum(1 for node in nodes if node["channel"] == "agent_event_stream"),
            "agent_event_stream_event_count": int(agent_event_stream.get("event_count", 0) or len(_list_dicts(agent_event_stream.get("events", [])))) if agent_event_stream else 0,
            "dossier_resume_trace_event_count": (
                sum(
                    1
                    for event in _list_dicts(agent_event_stream.get("events", []))
                    if str(event.get("event", "") or "") == "market_registry"
                    and str(event.get("resume_tool", "") or "") == "market_research_dossier_resume"
                )
                if agent_event_stream
                else 0
            ),
            "agent_loop_fsm_node_count": sum(1 for node in nodes if node["channel"] == "agent_loop_fsm"),
            "agent_loop_fsm_step_count": int(agent_loop_fsm.get("step_count", 0) or len(_list_dicts(agent_loop_fsm.get("steps", [])))) if agent_loop_fsm else 0,
            "agent_loop_fsm_stop_reason": str(agent_loop_fsm.get("canonical_stop_reason", "") or agent_loop_fsm.get("stop_reason", "") or "") if agent_loop_fsm else "",
            "model_tool_arbitration_node_count": sum(1 for node in nodes if node["channel"] == "model_tool_arbitration"),
            "model_tool_arbitration_selected_action": str(model_arbitration.get("selected_action", "") or "") if model_arbitration else "",
            "model_tool_arbitration_source": str(model_arbitration.get("source", "") or "") if model_arbitration else "",
            "search_evidence_controller_node_count": sum(1 for node in nodes if node["channel"] == "search_evidence_controller"),
            "search_evidence_observation_count": len(web_ledger),
            "search_evidence_best_status": str(max(search_scores, key=lambda item: float(item.get("evidence_score", 0.0) or 0.0)).get("status", "") or "") if search_scores else "",
            "search_evidence_best_score": float(max(search_scores, key=lambda item: float(item.get("evidence_score", 0.0) or 0.0)).get("evidence_score", 0.0) or 0.0) if search_scores else 0.0,
            "page_evidence_verifier_node_count": sum(1 for node in nodes if node["channel"] == "page_evidence_verifier"),
            "page_evidence_observation_count": len(page_scores),
            "page_evidence_best_status": str(max(page_scores, key=lambda item: float(item.get("best_evidence_score", 0.0) or 0.0)).get("status", "") or "") if page_scores else "",
            "page_evidence_best_score": float(max(page_scores, key=lambda item: float(item.get("best_evidence_score", 0.0) or 0.0)).get("best_evidence_score", 0.0) or 0.0) if page_scores else 0.0,
            "source_synthesis_node_count": sum(1 for node in nodes if node["channel"] == "source_synthesis"),
            "source_synthesis_status": str(max(source_syntheses, key=lambda item: float(item.get("confidence", 0.0) or 0.0)).get("status", "") or "") if source_syntheses else "",
            "source_synthesis_supported_source_count": int(max(source_syntheses, key=lambda item: float(item.get("confidence", 0.0) or 0.0)).get("supported_source_count", 0) or 0) if source_syntheses else 0,
            "answer_citation_formatter_node_count": sum(1 for node in nodes if node["channel"] == "answer_citation_formatter"),
            "answer_citation_formatter_citation_count": len(
                [
                    item
                    for item in list((max(source_syntheses, key=lambda row: float(row.get("confidence", 0.0) or 0.0)) if source_syntheses else {}).get("citations", []) or [])
                    if isinstance(item, dict) and str(item.get("url", "") or "").strip()
                ]
            ),
            "kernel_hardening_node_count": sum(1 for node in nodes if node["channel"] == "kernel_hardening"),
            "filing_text_retrieval_node_count": sum(1 for node in nodes if node["channel"] == "filing_text_retrieval"),
            "filing_text_retrieval_status": str(filing_retrieval.get("status", "") or "") if filing_retrieval else "",
            "filing_text_retrieval_source": str(filing_retrieval.get("retrieval_source", "") or "") if filing_retrieval else "",
            "filing_text_retrieval_char_count": int(filing_retrieval.get("filing_text_char_count", 0) or 0) if filing_retrieval else 0,
            "market_research_pack_action_node_count": sum(1 for node in nodes if node["channel"] == "market_research_pack_action"),
            "market_research_pack_action_status": str(market_research_ledger[0].get("status", "") or "") if market_research_ledger else "",
            "market_research_pack_action_pack_status": str(market_research_ledger[0].get("pack_status", "") or "") if market_research_ledger else "",
            "market_research_pack_action_evidence_count": int(market_research_ledger[0].get("evidence_item_count", 0) or 0) if market_research_ledger else 0,
            "market_research_gate_node_count": sum(1 for node in nodes if node["channel"] == "market_research_gate"),
            "market_research_gate_status": str(market_research_gate.get("status", "") or "") if market_research_gate else "",
            "market_research_gate_claim_count": int(market_research_gate.get("claim_count", 0) or 0) if market_research_gate else 0,
            "market_research_gate_unsupported_count": int(market_research_gate.get("unsupported_claim_count", 0) or 0) if market_research_gate else 0,
            "market_research_report_node_count": sum(1 for node in nodes if node["channel"] == "market_research_report"),
            "market_research_report_status": str(market_research_report.get("status", "") or "") if market_research_report else "",
            "market_research_report_section_count": int(market_research_report.get("section_count", 0) or 0) if market_research_report else 0,
            "market_research_report_metric_count": int(market_research_report.get("metric_count", 0) or 0) if market_research_report else 0,
            "market_research_report_citation_count": int(market_research_report.get("citation_count", 0) or 0) if market_research_report else 0,
            "market_research_report_action_node_count": sum(1 for node in nodes if node["channel"] == "market_research_report_action"),
            "market_research_report_action_status": str(market_research_report_ledger_rows[0].get("status", "") or "") if market_research_report_ledger_rows else "",
            "market_research_feedback_node_count": sum(1 for node in nodes if node["channel"] == "market_research_feedback"),
            "market_research_feedback_can_finalize": bool(market_research_feedback.get("can_finalize", False)) if market_research_feedback else False,
            "market_research_feedback_next_action": str(market_research_feedback.get("next_action", "") or "") if market_research_feedback else "",
            "market_research_feedback_stop_reason": str(market_research_feedback.get("final_stop_reason", "") or "") if market_research_feedback else "",
            "market_research_action_plan_node_count": sum(1 for node in nodes if node["channel"] == "market_research_action_plan"),
            "market_research_action_plan_status": str(market_research_action_plan.get("status", "") or "") if market_research_action_plan else "",
            "market_research_action_plan_next_action": str(market_research_action_plan.get("next_action", "") or "") if market_research_action_plan else "",
            "market_research_action_plan_candidate_count": int(market_research_action_plan.get("candidate_count", 0) or len(list(market_research_action_plan.get("action_candidates", []) or []))) if market_research_action_plan else 0,
            "market_research_plan_execution_node_count": sum(1 for node in nodes if node["channel"] == "market_research_plan_execution"),
            "market_research_plan_execution_status": str(market_research_plan_execution.get("status", "") or "") if market_research_plan_execution else "",
            "market_research_plan_execution_action": str(market_research_plan_execution.get("executed_action", "") or "") if market_research_plan_execution else "",
            "market_research_plan_execution_executed_count": int(market_research_plan_execution.get("executed_count", 0) or 0) if market_research_plan_execution else 0,
            "market_research_continuation_node_count": sum(1 for node in nodes if node["channel"] == "market_research_continuation"),
            "market_research_continuation_status": str(market_research_continuation.get("status", "") or "") if market_research_continuation else "",
            "market_research_continuation_round_count": int(market_research_continuation.get("round_count", 0) or 0) if market_research_continuation else 0,
            "market_research_continuation_can_finalize": bool(market_research_continuation.get("can_finalize", False)) if market_research_continuation else False,
            "market_research_source_promotion_node_count": sum(1 for node in nodes if node["channel"] == "market_research_source_promotion"),
            "market_research_source_promotion_status": str(market_research_source_promotion.get("status", "") or "") if market_research_source_promotion else "",
            "market_research_source_promotion_authority_status": str(market_research_source_promotion.get("authority_status", "") or "") if market_research_source_promotion else "",
            "market_research_source_promotion_can_build_pack": bool(market_research_source_promotion.get("can_build_market_research_pack", False)) if market_research_source_promotion else False,
            "market_research_report_assembly_node_count": sum(1 for node in nodes if node["channel"] == "market_research_report_assembly"),
            "market_research_report_assembly_status": str(market_research_report_assembly.get("status", "") or "") if market_research_report_assembly else "",
            "market_research_report_assembly_ready": bool(market_research_report_assembly.get("final_report_ready", False)) if market_research_report_assembly else False,
            "market_research_report_assembly_citation_quality_status": str(market_research_report_assembly.get("citation_quality_status", "") or "") if market_research_report_assembly else "",
            "market_research_finalization_node_count": sum(1 for node in nodes if node["channel"] == "market_research_finalization"),
            "market_research_finalization_status": str(market_research_finalization.get("status", "") or "") if market_research_finalization else "",
            "market_research_finalization_ready": bool(market_research_finalization.get("final_visible_text_ready", False)) if market_research_finalization else False,
            "market_research_dossier_node_count": sum(1 for node in nodes if node["channel"] == "market_research_dossier"),
            "market_research_dossier_status": str(market_research_dossier.get("status", "") or "") if market_research_dossier else "",
            "market_research_dossier_next_action_count": len(list(market_research_dossier.get("next_actions", []) or [])) if market_research_dossier else 0,
            "market_research_dossier_resume_node_count": sum(1 for node in nodes if node["channel"] == "market_research_dossier_resume"),
            "market_research_dossier_resume_status": str(market_research_dossier_resume.get("status", "") or "") if market_research_dossier_resume else "",
            "market_research_dossier_resume_action": str(market_research_dossier_resume.get("selected_action", "") or "") if market_research_dossier_resume else "",
            "market_research_dossier_registry_node_count": sum(1 for node in nodes if node["channel"] == "market_research_dossier_registry"),
            "market_research_dossier_registry_status": str(market_research_dossier_registry.get("status", "") or "") if market_research_dossier_registry else "",
            "market_research_dossier_registry_lookup_status": str(_dict(market_research_dossier_registry.get("lookup", {})).get("status", "") or "") if market_research_dossier_registry else "",
            "market_research_remediation_node_count": sum(1 for node in nodes if node["channel"] == "market_research_remediation"),
            "market_research_remediation_required_count": 1 if market_research_remediation and not bool(market_research_remediation.get("can_finalize", False)) else 0,
            "market_research_remediation_action_count": len(list(market_research_remediation.get("remediation_actions", []) or [])) if market_research_remediation else 0,
            "market_research_remediation_status": str(market_research_remediation.get("status", "") or "") if market_research_remediation else "",
            "evidence_action_remediation_node_count": sum(1 for node in nodes if node["channel"] == "evidence_action_remediation"),
            "evidence_action_remediation_issue_count": int(evidence_action_remediation.get("issue_count", 0) or 0) if evidence_action_remediation else 0,
            "evidence_action_remediation_action_count": int(evidence_action_remediation.get("action_count", 0) or len(list(evidence_action_remediation.get("actions", []) or []))) if evidence_action_remediation else 0,
            "evidence_action_remediation_status": str(evidence_action_remediation.get("status", "") or "") if evidence_action_remediation else "",
            "live_remediation_loop_node_count": sum(1 for node in nodes if node["channel"] == "live_remediation_loop"),
            "live_remediation_next_action_count": len(list(live_remediation_loop.get("next_action_candidates", []) or [])) if live_remediation_loop else 0,
            "live_remediation_loop_status": str(live_remediation_loop.get("status", "") or "") if live_remediation_loop else "",
            "live_remediation_selected_action": str(live_remediation_loop.get("selected_action_type", "") or "") if live_remediation_loop else "",
            "live_remediation_executor_node_count": sum(1 for node in nodes if node["channel"] == "live_remediation_executor"),
            "live_remediation_executed_count": int(live_remediation_execution.get("executed_count", 0) or 0) if live_remediation_execution else 0,
            "live_remediation_rejected_count": int(live_remediation_execution.get("rejected_count", 0) or 0) if live_remediation_execution else 0,
            "live_remediation_execution_status": str(live_remediation_execution.get("status", "") or "") if live_remediation_execution else "",
            "live_remediation_stress_node_count": sum(1 for node in nodes if node["channel"] == "live_remediation_stress"),
            "live_remediation_stress_case_count": int(_dict(live_remediation_stress.get("summary", {})).get("case_count", live_remediation_stress.get("case_count", 0)) or 0) if live_remediation_stress else 0,
            "live_remediation_stress_status": str(live_remediation_stress.get("status", "") or "") if live_remediation_stress else "",
            "remediation_continuation_node_count": sum(1 for node in nodes if node["channel"] == "remediation_continuation"),
            "remediation_continuation_round_count": int(remediation_continuation.get("round_count", 0) or 0) if remediation_continuation else 0,
            "remediation_continuation_executed_count": int(remediation_continuation.get("executed_count", 0) or 0) if remediation_continuation else 0,
            "remediation_continuation_status": str(remediation_continuation.get("status", "") or "") if remediation_continuation else "",
            "agent_capability_gauntlet_node_count": sum(1 for node in nodes if node["channel"] == "agent_capability_gauntlet"),
            "agent_capability_gauntlet_case_count": int(_dict(agent_capability_gauntlet.get("summary", {})).get("case_count", agent_capability_gauntlet.get("case_count", 0)) or 0) if agent_capability_gauntlet else 0,
            "agent_capability_gauntlet_passed_count": int(_dict(agent_capability_gauntlet.get("summary", {})).get("passed_case_count", 0) or 0) if agent_capability_gauntlet else 0,
            "agent_capability_gauntlet_status": str(agent_capability_gauntlet.get("status", "") or "") if agent_capability_gauntlet else "",
            "real_use_drill_node_count": sum(1 for node in nodes if node["channel"] == "real_use_drill"),
            "real_use_drill_case_count": int(_dict(real_use_drill.get("summary", {})).get("case_count", real_use_drill.get("case_count", 0)) or 0) if real_use_drill else 0,
            "real_use_drill_passed_count": int(_dict(real_use_drill.get("summary", {})).get("passed_case_count", 0) or 0) if real_use_drill else 0,
            "real_use_drill_full_loop_score": float(_dict(real_use_drill.get("summary", {})).get("full_loop_score", 0.0) or 0.0) if real_use_drill else 0.0,
            "real_use_drill_claim_only_baseline_score": float(_dict(real_use_drill.get("summary", {})).get("claim_only_baseline_score", 0.0) or 0.0) if real_use_drill else 0.0,
            "real_use_drill_status": str(real_use_drill.get("status", "") or "") if real_use_drill else "",
            "live_crawler_search_node_count": sum(1 for node in nodes if node["channel"] == "live_crawler_search"),
            "live_crawler_search_status": str(live_crawler_search.get("status", "") or "") if live_crawler_search else "",
            "live_crawler_search_query_count": int(live_crawler_search.get("query_count", 0) or 0) if live_crawler_search else 0,
            "live_crawler_search_opened_page_count": int(live_crawler_search.get("opened_page_count", 0) or 0) if live_crawler_search else 0,
            "canonical_stop_reason": str(canonical_state.get("canonical_stop_reason", "") or "") if canonical_state else "",
            "canonical_stop_source": str(canonical_state.get("canonical_stop_source", "") or "") if canonical_state else "",
            "network_enabled": bool(network_state.get("network_enabled", False)) if network_state else False,
            "last_web_status": str(network_state.get("last_web_status", "") or "") if network_state else "",
            "engineering_action_fabric_node_count": sum(1 for node in nodes if node["channel"] == "engineering_action_fabric"),
            "engineering_action_count": len(engineering_ledger),
            "engineering_action_ok_count": sum(1 for row in engineering_ledger if str(row.get("status", "") or "") == "ok"),
            "project_state_graph_node_count": sum(1 for node in nodes if node["channel"] == "project_state_graph"),
            "project_state_graph_project": str(project_state.get("project", "") or "") if project_state else "",
            "project_state_graph_open_loop_count": int(project_state.get("open_loop_count", 0) or len(_list_dicts(project_state.get("open_questions", []))) + len(_list_dicts(project_state.get("blocked_items", [])))) if project_state else 0,
            "project_state_graph_next_action_count": int(project_state.get("next_action_count", 0) or len(_list_dicts(project_state.get("next_actions", [])))) if project_state else 0,
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


def attach_stage153_agent_event_stream_topology(
    topology: dict[str, Any] | None,
    stage153_agent_event_stream: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    stream = _dict(stage153_agent_event_stream)
    if not payload.get("schema") or not stream:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if any(isinstance(node, dict) and node.get("id") == "stage153_agent_event_stream" for node in nodes):
        return payload
    event_count = int(stream.get("event_count", 0) or len(_list_dicts(stream.get("events", []))))
    nodes.append(
        _node(
            "stage153_agent_event_stream",
            "interactive agent event stream",
            channel="agent_event_stream",
            kind="observability",
            x=0.74,
            y=0.2,
            weight=0.58 if event_count else 0.32,
            summary=f"events={event_count}; hidden reasoning redacted",
        )
    )
    node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
    source = "stage152_deepseek_tool_loop" if "stage152_deepseek_tool_loop" in node_ids else "stage151_tool_decision_loop" if "stage151_tool_decision_loop" in node_ids else "state_delta"
    edges.append(_edge(source, "stage153_agent_event_stream", relation="renders_auditable_cli_events", weight=0.54, summary="grounded tool and packet evidence is rendered as CLI events without hidden reasoning"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["agent_event_stream_node_count"] = 1
    metrics["agent_event_stream_event_count"] = event_count
    payload["metrics"] = metrics
    return payload


def attach_stage154_engineering_action_topology(
    topology: dict[str, Any] | None,
    engineering_action_ledger: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    ledger = normalize_engineering_action_ledger(engineering_action_ledger or [])
    if not payload.get("schema") or not ledger:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if any(isinstance(node, dict) and node.get("id") == "stage154_engineering_action_fabric" for node in nodes):
        return payload
    ok_count = sum(1 for row in ledger if str(row.get("status", "") or "") == "ok")
    changed_count = sum(len(list(row.get("files_changed", []) or [])) for row in ledger)
    read_count = sum(len(list(row.get("files_read", []) or [])) for row in ledger)
    nodes.append(
        _node(
            "stage154_engineering_action_fabric",
            "engineering action fabric",
            channel="engineering_action_fabric",
            kind="tool_fabric",
            x=0.66,
            y=0.22,
            weight=0.68 if ok_count else 0.36,
            summary=f"actions={len(ledger)}; ok={ok_count}; read={read_count}; changed={changed_count}",
        )
    )
    node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
    source = "stage153_agent_event_stream" if "stage153_agent_event_stream" in node_ids else "stage151_tool_decision_loop" if "stage151_tool_decision_loop" in node_ids else "holo_self"
    edges.append(_edge(source, "stage154_engineering_action_fabric", relation="executes_workspace_actions", weight=0.58, summary="repo-scoped engineering actions produce auditable ledgers"))
    edges.append(_edge("stage154_engineering_action_fabric", "state_delta", relation="engineering_observation_reentry", weight=0.6, summary="search/read/patch/test/diff evidence re-enters the same subject state"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["engineering_action_fabric_node_count"] = 1
    metrics["engineering_action_count"] = len(ledger)
    metrics["engineering_action_ok_count"] = ok_count
    payload["metrics"] = metrics
    return payload


def attach_stage155_project_state_topology(
    topology: dict[str, Any] | None,
    project_state_graph: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    project_state = _dict(project_state_graph)
    if not payload.get("schema") or not project_state:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if any(isinstance(node, dict) and node.get("id") == "project_state_graph" for node in nodes):
        return payload
    active_tasks = _list_dicts(project_state.get("active_tasks", []))
    open_questions = _list_dicts(project_state.get("open_questions", []))
    next_actions = _list_dicts(project_state.get("next_actions", []))
    blocked_items = _list_dicts(project_state.get("blocked_items", []))
    project_name = str(project_state.get("project", "") or _dict(project_state.get("active_project", {})).get("title", "") or "project")
    nodes.append(
        _node(
            "project_state_graph",
            "project state graph",
            channel="project_state_graph",
            kind="project_memory",
            x=0.28,
            y=0.86,
            weight=0.7 if (active_tasks or open_questions or next_actions) else 0.38,
            summary=f"project={project_name}; tasks={len(active_tasks)}; open={len(open_questions)}; next={len(next_actions)}; blocked={len(blocked_items)}",
        )
    )
    node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
    source = "context_memory_fabric" if "context_memory_fabric" in node_ids else "holo_self"
    edges.append(_edge(source, "project_state_graph", relation="feeds_project_continuity", weight=0.58, summary="project goals, decisions, and open loops are kept outside raw chat history"))
    edges.append(_edge("project_state_graph", "fast_packet", relation="frames_project_context", weight=0.46, summary="active tasks and next actions enter the provider context packet"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["project_state_graph_node_count"] = 1
    metrics["project_state_graph_project"] = project_name
    metrics["project_state_graph_open_loop_count"] = int(project_state.get("open_loop_count", 0) or len(open_questions) + len(blocked_items))
    metrics["project_state_graph_next_action_count"] = int(project_state.get("next_action_count", 0) or len(next_actions))
    payload["metrics"] = metrics
    return payload


def attach_stage170_market_research_topology(
    topology: dict[str, Any] | None,
    stage170_market_research_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    gate = _dict(stage170_market_research_gate)
    if not payload.get("schema") or not gate:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if any(isinstance(node, dict) and node.get("id") == "stage170_market_research_gate" for node in nodes):
        return payload
    gate_status = str(gate.get("status", "") or "unknown")
    claim_count = int(gate.get("claim_count", 0) or 0)
    supported_count = int(gate.get("supported_claim_count", 0) or 0)
    unsupported_count = int(gate.get("unsupported_claim_count", 0) or 0)
    nodes.append(
        _node(
            "stage170_market_research_gate",
            "market research evidence gate",
            channel="market_research_gate",
            kind="observability_gate",
            x=0.86,
            y=0.32,
            weight=0.72 if gate_status == "supported" else 0.32,
            summary=f"status={gate_status}; claims={claim_count}; supported={supported_count}; unsupported={unsupported_count}",
        )
    )
    node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
    source = "stage165_answer_citation_formatter" if "stage165_answer_citation_formatter" in node_ids else "external_user_input"
    edges.append(_edge(source, "stage170_market_research_gate", relation="requires_filing_pack_before_financial_claims", weight=0.58, summary="market research claims require source-authority-sufficient filing evidence"))
    edges.append(_edge("stage170_market_research_gate", "state_delta", relation="gates_market_research_answer", weight=0.52, summary="unsupported financial claims are bounded before visible reply"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["market_research_gate_node_count"] = 1
    metrics["market_research_gate_status"] = gate_status
    metrics["market_research_gate_claim_count"] = claim_count
    metrics["market_research_gate_unsupported_count"] = unsupported_count
    payload["metrics"] = metrics
    return payload


def attach_stage171_market_research_action_topology(
    topology: dict[str, Any] | None,
    market_research_pack_ledger: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    ledger = _list_dicts(market_research_pack_ledger)
    if not payload.get("schema") or not ledger:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if not any(isinstance(node, dict) and node.get("id") == "stage171_market_research_pack_action" for node in nodes):
        first = ledger[0]
        action_status = str(first.get("status", "") or "unknown")
        pack_status = str(first.get("pack_status", "") or "")
        evidence_count = int(first.get("evidence_item_count", 0) or 0)
        nodes.append(
            _node(
                "stage171_market_research_pack_action",
                "market research pack action",
                channel="market_research_pack_action",
                kind="tool_observation",
                x=0.78,
                y=0.34,
                weight=0.74 if action_status == "ok" else 0.28,
                summary=f"status={action_status}; pack={pack_status}; evidence={evidence_count}",
            )
        )
        node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
        target = "stage170_market_research_gate" if "stage170_market_research_gate" in node_ids else "state_delta"
        edges.append(_edge("external_user_input", "stage171_market_research_pack_action", relation="executes_market_research_pack", weight=0.5, summary="host action builds filing evidence pack"))
        edges.append(_edge("stage171_market_research_pack_action", target, relation="feeds_market_research_gate", weight=0.53, summary="pack ledger can support market research answer gate"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["market_research_pack_action_node_count"] = sum(1 for node in nodes if isinstance(node, dict) and node.get("channel") == "market_research_pack_action")
    metrics["market_research_pack_action_status"] = str(ledger[0].get("status", "") or "")
    metrics["market_research_pack_action_pack_status"] = str(ledger[0].get("pack_status", "") or "")
    metrics["market_research_pack_action_evidence_count"] = int(ledger[0].get("evidence_item_count", 0) or 0)
    payload["metrics"] = metrics
    return payload


def attach_stage172_filing_text_retrieval_topology(
    topology: dict[str, Any] | None,
    filing_text_retrieval: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    retrieval = _dict(filing_text_retrieval)
    if not payload.get("schema") or not retrieval:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if not any(isinstance(node, dict) and node.get("id") == "stage172_filing_text_retrieval" for node in nodes):
        retrieval_status = str(retrieval.get("status", "") or "unknown")
        retrieval_source = str(retrieval.get("retrieval_source", "") or "")
        text_chars = int(retrieval.get("filing_text_char_count", 0) or 0)
        nodes.append(
            _node(
                "stage172_filing_text_retrieval",
                "filing text retrieval",
                channel="filing_text_retrieval",
                kind="tool_observation",
                x=0.73,
                y=0.31,
                weight=0.72 if retrieval_status == "ok" else 0.24,
                summary=f"status={retrieval_status}; source={retrieval_source}; chars={text_chars}",
            )
        )
        node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
        target = "stage171_market_research_pack_action" if "stage171_market_research_pack_action" in node_ids else "state_delta"
        edges.append(_edge("external_user_input", "stage172_filing_text_retrieval", relation="extracts_filing_text", weight=0.5, summary="authoritative page evidence is converted into filing text"))
        edges.append(_edge("stage172_filing_text_retrieval", target, relation="feeds_market_research_pack", weight=0.51, summary="filing text feeds market-research pack construction"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["filing_text_retrieval_node_count"] = sum(1 for node in nodes if isinstance(node, dict) and node.get("channel") == "filing_text_retrieval")
    metrics["filing_text_retrieval_status"] = str(retrieval.get("status", "") or "")
    metrics["filing_text_retrieval_source"] = str(retrieval.get("retrieval_source", "") or "")
    metrics["filing_text_retrieval_char_count"] = int(retrieval.get("filing_text_char_count", 0) or 0)
    payload["metrics"] = metrics
    return payload


def attach_stage173_market_research_report_topology(
    topology: dict[str, Any] | None,
    stage173_market_research_report: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    report = _dict(stage173_market_research_report)
    if not payload.get("schema") or not report:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if not any(isinstance(node, dict) and node.get("id") == "stage173_market_research_report" for node in nodes):
        report_status = str(report.get("status", "") or "unknown")
        section_count = int(report.get("section_count", 0) or 0)
        metric_count = int(report.get("metric_count", 0) or 0)
        citation_count = int(report.get("citation_count", 0) or 0)
        nodes.append(
            _node(
                "stage173_market_research_report",
                "market research report",
                channel="market_research_report",
                kind="observability_gate",
                x=0.9,
                y=0.36,
                weight=0.76 if report_status == "evidence_ready" else 0.34,
                summary=f"status={report_status}; sections={section_count}; metrics={metric_count}; citations={citation_count}",
            )
        )
        node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
        source = "stage170_market_research_gate" if "stage170_market_research_gate" in node_ids else "stage171_market_research_pack_action" if "stage171_market_research_pack_action" in node_ids else "external_user_input"
        edges.append(_edge(source, "stage173_market_research_report", relation="synthesizes_market_research_report", weight=0.56, summary="filing pack evidence is converted into a bounded analyst report"))
        edges.append(_edge("stage173_market_research_report", "state_delta", relation="reports_market_research_evidence", weight=0.45, summary="report exposes citations, limitations, and unsupported-claim accounting"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["market_research_report_node_count"] = sum(1 for node in nodes if isinstance(node, dict) and node.get("channel") == "market_research_report")
    metrics["market_research_report_status"] = str(report.get("status", "") or "")
    metrics["market_research_report_section_count"] = int(report.get("section_count", 0) or 0)
    metrics["market_research_report_metric_count"] = int(report.get("metric_count", 0) or 0)
    metrics["market_research_report_citation_count"] = int(report.get("citation_count", 0) or 0)
    payload["metrics"] = metrics
    return payload


def attach_stage156_context_compiler_topology(
    topology: dict[str, Any] | None,
    stage156_context_compiler: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(topology or {})
    compiler = _dict(stage156_context_compiler)
    if not payload.get("schema") or not compiler:
        return payload
    nodes = list(payload.get("nodes", []) or [])
    edges = list(payload.get("edges", []) or [])
    if any(isinstance(node, dict) and node.get("id") == "stage156_context_compiler" for node in nodes):
        return payload
    estimated_tokens = int(compiler.get("estimated_prompt_tokens", 0) or 0)
    cache_ratio = float(compiler.get("cache_hit_ratio", 0.0) or 0.0)
    truncated = list(compiler.get("truncated_sections", []) or [])
    nodes.append(
        _node(
            "stage156_context_compiler",
            "context compiler",
            channel="context_compiler",
            kind="context_packet",
            x=0.48,
            y=0.38,
            weight=0.7 if estimated_tokens else 0.36,
            summary=f"tokens={estimated_tokens}; stable={compiler.get('stable_prefix_tokens', 0)}; dynamic={compiler.get('dynamic_suffix_tokens', 0)}; cache_hit_ratio={cache_ratio}; truncated={len(truncated)}",
        )
    )
    node_ids = {str(node.get("id", "") or "") for node in nodes if isinstance(node, dict)}
    source = "context_memory_fabric" if "context_memory_fabric" in node_ids else "holo_self"
    edges.append(_edge(source, "stage156_context_compiler", relation="compiles_context_sections", weight=0.62, summary="Stage150 working context is compiled into stable prefix and dynamic suffix"))
    edges.append(_edge("stage156_context_compiler", "fast_packet", relation="frames_provider_packet", weight=0.58, summary="compiled context controls prompt budget and cache discipline"))
    payload["nodes"] = nodes
    payload["edges"] = edges
    metrics = dict(payload.get("metrics", {}) or {})
    metrics["node_count"] = len(nodes)
    metrics["edge_count"] = len(edges)
    metrics["context_compiler_node_count"] = 1
    metrics["context_compiler_estimated_prompt_tokens"] = estimated_tokens
    metrics["context_compiler_cache_hit_ratio"] = cache_ratio
    metrics["context_compiler_truncated_count"] = len(truncated)
    payload["metrics"] = metrics
    return payload


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
  context_memory_fabric: "#596d5a",
  model_tool_arbitration: "#6577a8",
  search_evidence_controller: "#4b7d87",
  page_evidence_verifier: "#4d8a6a",
  source_synthesis: "#7b7340",
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
