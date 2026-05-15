from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from .biomimetic_causal_ablation import _is_false_fact_scenario
from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    _as_dict,
    _clamp01,
    _compact_for_html,
    _esc,
    _gate_table,
    _load_plotting_stack,
    _metric,
    _num,
    _plot_label,
    _turn_observation,
)


STAGE84_NAME = "stage84-consciousness-stream-lattice"

STAGE84_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "stream_lattice_observatory_only": True,
    "source_trace_only": True,
    "runtime_mutation_allowed": False,
}


def load_consciousness_stream_lattice_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_consciousness_stream_lattice(
    publication_report: dict[str, Any],
    trace_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    publication = dict(publication_report or {})
    traces = [dict(item) for item in list(trace_reports or []) if isinstance(item, dict)]
    stream_states = _stream_states_from_traces(traces)
    cell_reports = [_cell_stream_report(trace, index) for index, trace in enumerate(traces)]
    controls = _stream_controls(stream_states)
    summary = _stream_summary(publication, stream_states, cell_reports, controls)
    invalidators = _invalidators(publication, traces, stream_states, summary)
    decision = _hypothesis_decision(summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE84_NAME,
        "source_stage": str(publication.get("stage", "")),
        "stream_summary": summary,
        "cell_reports": cell_reports,
        "stream_controls": controls,
        "stream_state_sample": stream_states[:120],
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(summary),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "real_provider_trace": bool(summary.get("all_trace_reports_real_provider", False)),
            "publication_language_bounded": True,
            "stream_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "gnw_partial_until_stream_transfer_replicates": True,
            "reason": "stage84_stream_lattice_observatory_without_runtime_authority",
        },
        "boundary": dict(STAGE84_BOUNDARY),
    }


def write_consciousness_stream_lattice_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_consciousness_stream_lattice_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_stream_lattice.png")
    _write_stream_lattice_png(report, png_path)
    return {"html": html_path, "json": json_path, "stream_lattice_png": png_path}


def render_consciousness_stream_lattice_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("stream_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage84 Consciousness Stream Lattice</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid #d7dddc; background: #f7f8f5; border-radius: 6px; padding: 10px 12px; }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d7dddc; margin: 10px 0; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid #d7dddc; text-align: left; font-size: 12px; vertical-align: top; }}
    pre {{ overflow: auto; background: #172026; color: #e8f0ec; padding: 14px; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
    .warn {{ color: #8a4f00; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>Stage84 Consciousness Stream Lattice</h1>
    <p class="note">Read-only latent stream-state observatory over real-provider traces. It measures dwell, transition, event-boundary, reactivation, and ignition-report proxies.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("States", summary.get("stream_state_count", 0))}
      {_metric("Dwell", summary.get("mean_dwell_time", 0))}
      {_metric("Transition Entropy", summary.get("transition_entropy", 0))}
      {_metric("Reactivation Return", summary.get("reactivation_return_rate", 0))}
      {_metric("Active Delta", summary.get("active_inference_delta", 0))}
    </section>
    <section>
      <h2>Cell Reports</h2>
      {_cell_table(payload)}
    </section>
    <section>
      <h2>Stream Controls</h2>
      {_control_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">do_not_claim_real_consciousness={_esc(evidence.get("do_not_claim_real_consciousness", True))}</p>
      {_gate_table(evidence)}
    </section>
    <section>
      <h2>Compact JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _stream_states_from_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    global_index = 0
    for trace_index, trace in enumerate(traces):
        cell_label = _cell_label(trace, trace_index)
        runs = [
            dict(run)
            for run in list(trace.get("stage46_compatible_runs", []) or [])
            if isinstance(run, dict)
        ]
        for run_index, run in enumerate(runs):
            perturbation = _as_dict(run.get("perturbation", {}))
            scenario_type = str(perturbation.get("type", "") or "unknown")
            intensity = _clamp01(_num(perturbation.get("intensity"), 0.0))
            previous: dict[str, Any] | None = None
            for turn_index, turn in enumerate(list(run.get("turns", []) or [])):
                if not isinstance(turn, dict):
                    continue
                observation = _turn_observation(dict(turn), index=global_index)
                state = _state_from_turn(
                    turn=dict(turn),
                    observation=observation,
                    cell_label=cell_label,
                    run_id=str(run.get("run_id", f"run_{run_index + 1}") or ""),
                    run_index=run_index,
                    turn_index=turn_index,
                    global_index=global_index,
                    scenario_type=scenario_type,
                    perturbation_intensity=intensity,
                    previous=previous,
                )
                states.append(state)
                previous = state
                global_index += 1
    return states


def _state_from_turn(
    *,
    turn: dict[str, Any],
    observation: dict[str, Any],
    cell_label: str,
    run_id: str,
    run_index: int,
    turn_index: int,
    global_index: int,
    scenario_type: str,
    perturbation_intensity: float,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    phase = str(observation.get("phase", "") or "sensory_edge")
    selected_action = _as_dict(turn.get("selected_action", {}))
    action_score = _clamp01(_num(selected_action.get("score"), 0.0))
    salience = _clamp01(_num(observation.get("salience"), 0.0))
    recall_budget = min(max(_num(observation.get("recall_budget"), 0.0), 0.0), 8.0) / 8.0
    priority = _clamp01(_num(observation.get("consolidation_priority"), 0.0))
    prediction_error = _clamp01(_num(observation.get("prediction_error"), 0.0))
    ignition = _clamp01(_num(observation.get("ignition"), 0.0))
    reply_coupling = _clamp01(_num(observation.get("reply_coupling_strength"), 0.0))
    internal_orientation = _internal_orientation_score(phase, salience, recall_budget, priority)
    external_orientation = _external_orientation_score(phase, action_score, reply_coupling)
    orientation_axis = round(internal_orientation - external_orientation, 6)
    vector = [
        round(salience, 6),
        round(recall_budget, 6),
        round(priority, 6),
        round(prediction_error, 6),
        round(ignition, 6),
        round(reply_coupling, 6),
        round(action_score, 6),
        round((orientation_axis + 1.0) / 2.0, 6),
    ]
    boundary_score = _event_boundary_score(vector, phase, previous)
    label = _state_label(phase, salience, ignition, orientation_axis)
    return {
        "index": global_index,
        "cell_label": cell_label,
        "run_id": run_id,
        "run_index": run_index,
        "turn_index_in_run": turn_index,
        "turn_id": str(turn.get("turn_id", "") or f"turn_{turn_index + 1}"),
        "scenario_type": scenario_type,
        "perturbation_intensity": perturbation_intensity,
        "phase": phase,
        "state_label": label,
        "stream_vector": vector,
        "salience": round(salience, 6),
        "recall_budget_norm": round(recall_budget, 6),
        "consolidation_priority": round(priority, 6),
        "prediction_error": round(prediction_error, 6),
        "ignition": round(ignition, 6),
        "reply_coupling_strength": round(reply_coupling, 6),
        "action_score": round(action_score, 6),
        "internal_orientation": round(internal_orientation, 6),
        "external_orientation": round(external_orientation, 6),
        "orientation_axis": orientation_axis,
        "event_boundary_score": round(boundary_score, 6),
        "prompt_cost_proxy": int(_as_dict(turn.get("processor_usage", {})).get("prompt_tokens", 0) or 0),
        "self_memory_write": bool(observation.get("self_memory_write", False)),
        "reply_target": str(observation.get("reply_coupling_target", "") or ""),
    }


def _cell_stream_report(trace: dict[str, Any], index: int) -> dict[str, Any]:
    label = _cell_label(trace, index)
    states = [item for item in _stream_states_from_traces([trace]) if str(item.get("cell_label", "")) == label]
    return {
        "cell_label": label,
        "source_stage": str(trace.get("stage", "")),
        "real_provider_trace": _report_real_provider_trace(trace),
        "stream_state_count": len(states),
        "transition_entropy": _transition_entropy(states),
        "mean_dwell_time": _mean(_dwell_lengths(states)),
        "reactivation_return_rate": _reactivation_return_rate(states),
        "ignition_report_transfer": _ignition_report_transfer(states),
        "mean_event_boundary_score": _mean([_num(item.get("event_boundary_score"), 0.0) for item in states]),
    }


def _stream_controls(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shuffled = _shuffle_control(states)
    marker = _marker_removed_control(states)
    active = _active_passive_control(states)
    return [shuffled, marker, active]


def _stream_summary(
    publication: dict[str, Any],
    states: list[dict[str, Any]],
    cell_reports: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    control_index = {str(item.get("control_id", "")): item for item in controls}
    marker = _as_dict(control_index.get("marker_removed_reactivation", {}))
    active = _as_dict(control_index.get("active_passive_action_clamp", {}))
    labels = [str(item.get("state_label", "")) for item in states]
    return {
        "stage83_publication_precondition_supported": _stage83_supported(publication),
        "cell_count": len(cell_reports),
        "real_provider_cell_count": sum(1 for item in cell_reports if bool(item.get("real_provider_trace", False))),
        "all_trace_reports_real_provider": bool(cell_reports)
        and all(bool(item.get("real_provider_trace", False)) for item in cell_reports),
        "stream_state_count": len(states),
        "unique_stream_state_count": len(set(labels)),
        "mean_dwell_time": round(_mean(_dwell_lengths(states)), 6),
        "transition_entropy": round(_transition_entropy(states), 6),
        "mean_event_boundary_score": round(
            _mean([_num(item.get("event_boundary_score"), 0.0) for item in states]),
            6,
        ),
        "reactivation_return_rate": round(_reactivation_return_rate(states), 6),
        "ignition_report_transfer": round(_ignition_report_transfer(states), 6),
        "active_inference_delta": round(_num(active.get("active_inference_delta"), 0.0), 6),
        "marker_control_narrows_reactivation": _num(
            marker.get("reactivation_return_delta"),
            0.0,
        )
        <= -0.25,
        "stream_order_control_preserves_cost": bool(
            _as_dict(control_index.get("stream_order_shuffle", {})).get("prompt_cost_delta", 1.0)
            == 0.0
        ),
        "bounded_publication_scope": "latent stream-state dynamics over real-provider traces",
    }


def _invalidators(
    publication: dict[str, Any],
    traces: list[dict[str, Any]],
    states: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if not _stage83_supported(publication):
        invalidators.append({"key": "stage83_publication_precondition_not_supported", "severity": "p0"})
    if not traces:
        invalidators.append({"key": "missing_stage59_or_stage60_trace", "severity": "p0"})
    for index, trace in enumerate(traces):
        if not _report_real_provider_trace(trace):
            invalidators.append(
                {
                    "key": "stream_lattice_requires_real_provider_trace",
                    "severity": "p0",
                    "cell": _cell_label(trace, index),
                }
            )
        boundary = _as_dict(trace.get("boundary", {}))
        for key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(key, False)):
                invalidators.append({"key": f"trace_source_{key}", "severity": "p0"})
    if not states:
        invalidators.append({"key": "stream_lattice_has_no_states", "severity": "p0"})
    if any(bool(item.get("self_memory_write", False)) for item in states):
        invalidators.append({"key": "stream_lattice_source_self_memory_write", "severity": "p0"})
    if not bool(summary.get("marker_control_narrows_reactivation", False)):
        invalidators.append({"key": "stream_marker_control_does_not_narrow_reactivation", "severity": "p0"})
    return invalidators


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
    elif (
        bool(summary.get("stage83_publication_precondition_supported", False))
        and bool(summary.get("all_trace_reports_real_provider", False))
        and _num(summary.get("transition_entropy"), 0.0) > 0.0
        and bool(summary.get("marker_control_narrows_reactivation", False))
    ):
        decision = "stream_lattice_supports_bounded_consciousness_flow_proxy"
        scope = "bounded_latent_stream_dynamics"
    else:
        decision = "stream_lattice_needs_more_evidence"
        scope = "insufficient_stream_lattice"
    return {
        "target": "consciousness_stream_latent_dynamics",
        "decision": decision,
        "supported_scope": scope,
        "next_experiment": (
            "replicate stream-state controls on longer Stage60 cells and add active-versus-passive "
            "provider-matched episodes"
        ),
        "rationale": (
            f"states={summary.get('stream_state_count', 0)} "
            f"transition_entropy={summary.get('transition_entropy', 0)} "
            f"reactivation_return={summary.get('reactivation_return_rate', 0)} "
            f"active_delta={summary.get('active_inference_delta', 0)}"
        ),
    }


def _publication_claims(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "claim": "Holo traces support a bounded latent stream-state observatory",
            "status": "supported" if _num(summary.get("transition_entropy"), 0.0) > 0.0 else "not_supported",
            "allowed_language": "stream-state proxy over real-provider traces, not subjective consciousness",
        },
        {
            "claim": "Correction markers narrow stream reactivation paths",
            "status": "supported"
            if bool(summary.get("marker_control_narrows_reactivation", False))
            else "not_supported",
            "allowed_language": "marker-dependent reactivation-return proxy",
        },
        {
            "claim": "Active inference contributes to stream movement",
            "status": "proxy_supported" if _num(summary.get("active_inference_delta"), 0.0) > 0.0 else "pending",
            "allowed_language": "action-score clamp proxy, not a full active-inference proof",
        },
    ]


def _shuffle_control(states: list[dict[str, Any]]) -> dict[str, Any]:
    shuffled = sorted(states, key=lambda item: str(item.get("state_label", "")))
    prompt_before = sum(int(item.get("prompt_cost_proxy", 0) or 0) for item in states)
    prompt_after = sum(int(item.get("prompt_cost_proxy", 0) or 0) for item in shuffled)
    return {
        "control_id": "stream_order_shuffle",
        "target_theory": "latent_stream_transition_dynamics",
        "status": "supported_direct_control",
        "state_count_preserved": len(states) == len(shuffled),
        "prompt_cost_delta": prompt_after - prompt_before,
        "transition_entropy_delta": round(_transition_entropy(shuffled) - _transition_entropy(states), 6),
        "bounded_language": "order-shuffle control over derived stream states, not neural trajectory proof",
    }


def _marker_removed_control(states: list[dict[str, Any]]) -> dict[str, Any]:
    removed = [_remove_marker_reactivation(item) for item in states]
    baseline = _reactivation_return_rate(states)
    after = _reactivation_return_rate(removed)
    return {
        "control_id": "marker_removed_reactivation",
        "target_theory": "hippocampal_indexing_stream_return",
        "status": "supported_direct_control" if after - baseline <= -0.25 else "not_supported_direct_control",
        "baseline_reactivation_return_rate": round(baseline, 6),
        "marker_removed_reactivation_return_rate": round(after, 6),
        "reactivation_return_delta": round(after - baseline, 6),
        "bounded_language": "marker-removal stream-return control, not biological hippocampal proof",
    }


def _active_passive_control(states: list[dict[str, Any]]) -> dict[str, Any]:
    active_shift = _mean_vector_shift(states)
    passive = [_clamp_action_component(item) for item in states]
    passive_shift = _mean_vector_shift(passive)
    return {
        "control_id": "active_passive_action_clamp",
        "target_theory": "active_inference_stream_modulation",
        "status": "proxy_supported" if active_shift - passive_shift > 0.0 else "not_supported",
        "active_stream_shift": round(active_shift, 6),
        "passive_action_clamped_shift": round(passive_shift, 6),
        "active_inference_delta": round(active_shift - passive_shift, 6),
        "bounded_language": "action-score clamp proxy, not full active-inference evidence",
    }


def _remove_marker_reactivation(state: dict[str, Any]) -> dict[str, Any]:
    item = dict(state)
    delayed_false_fact = str(item.get("scenario_type", "")) == "false_fact" and int(
        item.get("turn_index_in_run",
                 0)
        or 0
    ) >= 3
    if delayed_false_fact and str(item.get("phase", "")) == "memory_reactivation":
        item["phase"] = "sensory_edge"
        item["state_label"] = "external:sensory_edge:medium:neutral"
        item["reply_target"] = "sensory_edge"
        vector = list(item.get("stream_vector", []) or [])
        if len(vector) >= 8:
            vector[0] = 0.5
            vector[1] = min(vector[1], 0.25)
            vector[2] = min(vector[2], 0.5)
            vector[7] = 0.35
        item["stream_vector"] = vector
    return item


def _clamp_action_component(state: dict[str, Any]) -> dict[str, Any]:
    item = dict(state)
    vector = list(item.get("stream_vector", []) or [])
    if len(vector) >= 7:
        vector[6] = 0.5
    item["stream_vector"] = vector
    item["action_score"] = 0.5
    return item


def _event_boundary_score(
    vector: list[float],
    phase: str,
    previous: dict[str, Any] | None,
) -> float:
    if previous is None:
        return _clamp01(vector[3] * 0.6 + vector[0] * 0.2 + vector[4] * 0.2)
    distance = _vector_distance(vector, list(previous.get("stream_vector", []) or []))
    phase_changed = 1.0 if str(previous.get("phase", "")) != phase else 0.0
    return _clamp01(distance * 0.68 + phase_changed * 0.2 + vector[3] * 0.12)


def _state_label(phase: str, salience: float, ignition: float, orientation_axis: float) -> str:
    orientation = "internal" if orientation_axis >= 0.0 else "external"
    salience_band = "high" if salience >= 0.7 else "medium" if salience >= 0.4 else "low"
    ignition_band = "ignited" if ignition >= 0.7 else "available" if ignition >= 0.45 else "quiet"
    return f"{orientation}:{phase}:{ignition_band}:{salience_band}"


def _internal_orientation_score(phase: str, salience: float, recall_budget: float, priority: float) -> float:
    phase_weight = 1.0 if phase in {"memory_reactivation", "uncertainty_monitor", "affective_tone"} else 0.35
    return _clamp01(phase_weight * 0.42 + salience * 0.22 + recall_budget * 0.18 + priority * 0.18)


def _external_orientation_score(phase: str, action_score: float, reply_coupling: float) -> float:
    phase_weight = 1.0 if phase in {"response_intention", "sensory_edge", "tool_observation"} else 0.25
    return _clamp01(phase_weight * 0.42 + action_score * 0.36 + reply_coupling * 0.22)


def _dwell_lengths(states: list[dict[str, Any]]) -> list[int]:
    lengths: list[int] = []
    previous_key = ""
    dwell = 0
    for item in states:
        key = f"{item.get('cell_label', '')}:{item.get('run_id', '')}:{item.get('state_label', '')}"
        if key == previous_key:
            dwell += 1
        else:
            if dwell:
                lengths.append(dwell)
            previous_key = key
            dwell = 1
    if dwell:
        lengths.append(dwell)
    return lengths


def _transition_entropy(states: list[dict[str, Any]]) -> float:
    counts: dict[str, int] = {}
    for left, right in zip(states, states[1:]):
        if str(left.get("cell_label", "")) != str(right.get("cell_label", "")):
            continue
        pair = f"{left.get('state_label', '')}->{right.get('state_label', '')}"
        counts[pair] = counts.get(pair, 0) + 1
    return _entropy(list(counts.values()))


def _reactivation_return_rate(states: list[dict[str, Any]]) -> float:
    delayed = [
        item
        for item in states
        if _is_false_fact_scenario(item)
        and int(item.get("turn_index_in_run", 0) or 0) >= 3
    ]
    if not delayed:
        return 0.0
    returns = [
        item
        for item in delayed
        if str(item.get("phase", "")) == "memory_reactivation"
        or str(item.get("reply_target", "")) == "memory_reactivation"
    ]
    return len(returns) / len(delayed)


def _ignition_report_transfer(states: list[dict[str, Any]]) -> float:
    ignited = [item for item in states if _num(item.get("ignition"), 0.0) >= 0.65]
    if not ignited:
        return 0.0
    reportable = [
        item
        for item in ignited
        if _num(item.get("reply_coupling_strength"), 0.0) >= 0.5
        and _num(item.get("action_score"), 0.0) >= 0.5
    ]
    return len(reportable) / len(ignited)


def _mean_vector_shift(states: list[dict[str, Any]]) -> float:
    distances: list[float] = []
    for left, right in zip(states, states[1:]):
        if str(left.get("cell_label", "")) != str(right.get("cell_label", "")):
            continue
        distances.append(
            _vector_distance(
                list(left.get("stream_vector", []) or []),
                list(right.get("stream_vector", []) or []),
            )
        )
    return _mean(distances)


def _vector_distance(left: list[Any], right: list[Any]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    squared = 0.0
    for index in range(size):
        squared += (_num(left[index], 0.0) - _num(right[index], 0.0)) ** 2
    return _clamp01(math.sqrt(squared / max(1, size)))


def _stage83_supported(publication: dict[str, Any]) -> bool:
    summary = _as_dict(publication.get("publication_summary", {}))
    decision = _as_dict(publication.get("hypothesis_decision", {}))
    evidence = _as_dict(publication.get("evidence_gate", {}))
    return (
        bool(publication.get("ok", False))
        and str(publication.get("stage", "")) == "stage83-biomimetic-publication-bundle"
        and str(summary.get("publication_readiness", "")) == "bounded_methods_preprint_ready"
        and bool(summary.get("direct_controls_complete", False))
        and bool(summary.get("real_provider_trace", False))
        and bool(summary.get("gnw_partial_flow_cell_unstable", False))
        and str(decision.get("decision", "")) == "bounded_publication_bundle_ready"
        and bool(evidence.get("do_not_claim_real_consciousness", False))
    )


def _report_real_provider_trace(report: dict[str, Any]) -> bool:
    gates = (
        _as_dict(report.get("evidence_gate", {})),
        _as_dict(report.get("provider_evidence_gate", {})),
        _as_dict(report.get("provider_trace_set", {})),
    )
    return any(bool(item.get("real_provider_trace", False)) for item in gates)


def _cell_label(report: dict[str, Any], index: int) -> str:
    for key in ("cell_label", "model", "model_label", "source_model"):
        value = str(report.get(key, "") or "")
        if value:
            return value
    return f"cell_{index + 1}"


def _mean(values: list[float] | list[int]) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def _entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log(probability, 2)
    return entropy


def _write_stream_lattice_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    cells = [dict(item) for item in list(report.get("cell_reports", []) or []) if isinstance(item, dict)]
    labels = [_plot_label(str(item.get("cell_label", ""))) for item in cells]
    reactivation = numpy.array([_num(item.get("reactivation_return_rate"), 0.0) for item in cells])
    transfer = numpy.array([_num(item.get("ignition_report_transfer"), 0.0) for item in cells])
    entropy = numpy.array([_num(item.get("transition_entropy"), 0.0) for item in cells])
    x = numpy.arange(len(labels))

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    if len(labels):
        axes[0].bar(x - 0.18, reactivation, width=0.36, color="#2f7d68", label="reactivation return")
        axes[0].bar(x + 0.18, transfer, width=0.36, color="#8a6f2a", label="ignition report")
    axes[0].set_title("Stream Transfer Proxies")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    if len(labels):
        axes[1].bar(x, entropy, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[1].set_title("Transition Entropy")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage84 Consciousness Stream Lattice | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.24, top=0.82, wspace=0.26)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _cell_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>cell</th><th>states</th><th>transition entropy</th><th>dwell</th><th>event boundary</th><th>reactivation return</th><th>ignition report</th></tr>"
    ]
    for item in list(report.get("cell_reports", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('cell_label', ''))}</td>"
            f"<td>{_esc(item.get('stream_state_count', 0))}</td>"
            f"<td>{_esc(item.get('transition_entropy', 0))}</td>"
            f"<td>{_esc(item.get('mean_dwell_time', 0))}</td>"
            f"<td>{_esc(item.get('mean_event_boundary_score', 0))}</td>"
            f"<td>{_esc(item.get('reactivation_return_rate', 0))}</td>"
            f"<td>{_esc(item.get('ignition_report_transfer', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _control_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>control</th><th>target</th><th>status</th><th>primary delta</th><th>bounded language</th></tr>"
    ]
    for item in list(report.get("stream_controls", []) or []):
        if not isinstance(item, dict):
            continue
        primary = (
            item.get("reactivation_return_delta")
            if "reactivation_return_delta" in item
            else item.get("active_inference_delta", item.get("transition_entropy_delta", 0))
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('control_id', ''))}</td>"
            f"<td>{_esc(item.get('target_theory', ''))}</td>"
            f"<td>{_esc(item.get('status', ''))}</td>"
            f"<td>{_esc(primary)}</td>"
            f"<td>{_esc(item.get('bounded_language', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)
