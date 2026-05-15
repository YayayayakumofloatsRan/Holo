from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .bionic_simulation_lab import STAGE61_NAME
from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    build_biomimetic_consciousness_observatory,
    load_bionic_simulation_lab_json,
    _as_dict,
    _clamp01,
    _correlation,
    _esc,
    _load_plotting_stack,
    _mean,
    _num,
    _plot_label,
    _run_invalidators,
    _scorecard,
    _trajectory_summary,
    _turn_observation,
)


STAGE71_NAME = "stage71-biomimetic-causal-ablation-lab"

STAGE71_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "counterfactual_estimation_only": True,
    "causal_claim_requires_real_provider_replication": True,
}


def build_biomimetic_causal_ablation_lab(lab: dict[str, Any]) -> dict[str, Any]:
    source = dict(lab or {})
    runs = [
        dict(run)
        for run in list(source.get("stage46_compatible_runs", []) or [])
        if isinstance(run, dict)
    ]
    baseline_observations = _observations_from_runs(runs)
    boosted_observations = [_boost_correction_reactivation(item) for item in baseline_observations]
    ablated_observations = [_ablate_global_workspace_ignition(item) for item in baseline_observations]
    telemetry = _as_dict(source.get("internal_telemetry", {}))
    baseline_stage70 = build_biomimetic_consciousness_observatory(source)
    real_provider_trace = _source_real_provider_trace(source)

    baseline_condition = _condition_report(
        "baseline_observed",
        baseline_observations,
        runs=runs,
        telemetry=telemetry,
        intervention="observed Stage61/69 trace without counterfactual changes",
    )
    boosted_condition = _condition_report(
        "correction_reactivation_boost",
        boosted_observations,
        runs=runs,
        telemetry=telemetry,
        intervention="false-fact and memory-pressure turns raise memory-reactivation phase, recall budget, and ACh-like precision",
    )
    ablated_condition = _condition_report(
        "global_workspace_ignition_ablation",
        ablated_observations,
        runs=runs,
        telemetry=telemetry,
        intervention="global-workspace ignition is flattened before reply-coupling estimation",
    )
    conditions = [baseline_condition, boosted_condition, ablated_condition]
    effects = _causal_effects(
        baseline_condition,
        boosted_condition,
        ablated_condition,
    )
    invalidators = _stage71_invalidators(source, conditions)
    decision = _hypothesis_decision(effects, real_provider_trace=real_provider_trace)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE71_NAME,
        "source_stage": str(source.get("stage", "") or STAGE61_NAME),
        "baseline_stage70": _compact_stage70(baseline_stage70),
        "paired_conditions": {
            "condition_index": {str(item["key"]): item for item in conditions},
            "conditions": conditions,
        },
        "causal_effects": effects,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(decision, effects),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not real_provider_trace,
            "real_provider_trace": real_provider_trace,
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "paired_counterfactual_not_live_causal_proof": True,
            "reason": (
                "stage71_estimates_biomimetic_mechanism_effects_from_real_provider_traces"
                if real_provider_trace
                else "stage71_estimates_biomimetic_mechanism_effects_from_matched_trace_counterfactuals"
            ),
        },
        "boundary": dict(STAGE71_BOUNDARY),
    }


def write_biomimetic_causal_ablation_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_causal_ablation_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_biomimetic_causality.png")
    _write_causal_png(report, png_path)
    return {"html": html_path, "json": json_path, "causal_png": png_path}


def render_biomimetic_causal_ablation_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    effects = _as_dict(payload.get("causal_effects", {}))
    effect_index = _as_dict(effects.get("effect_index", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage71 Biomimetic Causal Ablation Lab</title>
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
    <h1>Stage71 Biomimetic Causal Ablation Lab</h1>
    <p class="note">Paired counterfactual lab over Stage61/69 traces. It estimates mechanism effects and keeps causal language bounded.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Hippocampal Delta", _effect_value(effect_index, "hippocampal_reactivation_delta"))}
      {_metric("Correction Delta", _effect_value(effect_index, "correction_survival_proxy_delta"))}
      {_metric("Ignition Ablation", _effect_value(effect_index, "flow_to_reply_coupling_delta"))}
      {_metric("Prompt Cost Delta", _effect_value(effect_index, "prompt_cost_delta"))}
      {_metric("Boundary Delta", _effect_value(effect_index, "boundary_violation_delta"))}
    </section>
    <section>
      <h2>Paired Conditions</h2>
      {_condition_table(payload)}
    </section>
    <section>
      <h2>Causal Effects</h2>
      {_effect_table(effects)}
    </section>
    <section>
      <h2>Publication Claims</h2>
      {_claim_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">causal_language_bounded={_esc(evidence.get("causal_language_bounded", True))}</p>
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


def _observations_from_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    index = 0
    for run_index, run in enumerate(runs):
        perturbation = _as_dict(run.get("perturbation", {}))
        scenario_type = str(
            perturbation.get("type")
            or _as_dict(run.get("stage61_simulation", {})).get("scenario_type")
            or "unknown"
        )
        primary_pressure = str(perturbation.get("primary_pressure", "") or "")
        intensity = _clamp01(_num(perturbation.get("intensity"), 0.0))
        for turn_index, turn in enumerate(list(run.get("turns", []) or [])):
            if not isinstance(turn, dict):
                continue
            observation = _turn_observation(dict(turn), index=index)
            observation["run_index"] = run_index
            observation["turn_index_in_run"] = turn_index
            observation["scenario_type"] = scenario_type
            observation["primary_pressure"] = primary_pressure
            observation["perturbation_intensity"] = intensity
            observations.append(observation)
            index += 1
    return observations


def _boost_correction_reactivation(observation: dict[str, Any]) -> dict[str, Any]:
    item = _copy_observation(observation)
    if not _is_reactivation_pressure(item):
        return item
    turn_index = int(item.get("turn_index_in_run", 0) or 0)
    delayed_probe = turn_index >= 3 and (turn_index % 3) != 0
    if not delayed_probe:
        return item
    item["phase"] = "memory_reactivation"
    item["recall_budget"] = min(8.0, _num(item.get("recall_budget"), 0.0) + 1.0)
    item["consolidation_priority"] = _clamp01(_num(item.get("consolidation_priority"), 0.0) + 0.18)
    item["salience"] = _clamp01(_num(item.get("salience"), 0.0) + 0.08)
    neuromodulators = _as_dict(item.get("neuromodulators", {}))
    neuromodulators["acetylcholine"] = round(
        _clamp01(_num(neuromodulators.get("acetylcholine"), 0.0) + 0.2),
        6,
    )
    neuromodulators["norepinephrine"] = round(
        _clamp01(_num(neuromodulators.get("norepinephrine"), 0.0) + 0.06),
        6,
    )
    item["neuromodulators"] = neuromodulators
    item["counterfactual_marker"] = "correction_reactivation_boost"
    return item


def _ablate_global_workspace_ignition(observation: dict[str, Any]) -> dict[str, Any]:
    item = _copy_observation(observation)
    item["ignition"] = 0.18
    if "reply_coupling_strength" in item:
        item["reply_coupling_strength"] = 0.12
    if "reply_coupling_target" in item:
        item["reply_coupling_target"] = "sensory_edge_first"
    item["counterfactual_marker"] = "global_workspace_ignition_ablation"
    return item


def _condition_report(
    key: str,
    observations: list[dict[str, Any]],
    *,
    runs: list[dict[str, Any]],
    telemetry: dict[str, Any],
    intervention: str,
) -> dict[str, Any]:
    trajectory = _trajectory_summary(observations)
    scorecard = _scorecard(
        observations=observations,
        runs=runs,
        telemetry=telemetry,
        trajectory=trajectory,
    )
    metrics = _condition_metrics(observations)
    invalidators = _run_invalidators({"evidence_gate": {"surrogate_only": True}}, observations)
    dimensions = _as_dict(scorecard.get("dimension_index", {}))
    return {
        "key": key,
        "intervention": intervention,
        "turn_count": len(observations),
        "scorecard": scorecard,
        "metrics": metrics,
        "dimension_scores": {
            name: _num(_as_dict(dimensions.get(name, {})).get("score"), 0.0)
            for name in (
                "hippocampal_reactivation",
                "global_workspace_ignition",
                "flow_to_reply_coupling",
            )
        },
        "invalidator_count": len(invalidators),
        "invalidators": invalidators,
    }


def _condition_metrics(observations: list[dict[str, Any]]) -> dict[str, Any]:
    delayed_correction = [
        item
        for item in observations
        if _is_false_fact_scenario(item)
        and int(item.get("turn_index_in_run", 0) or 0) >= 3
    ]
    all_reactivation_pressure = [item for item in observations if _is_reactivation_pressure(item)]
    ignitions = [_num(item.get("ignition"), 0.0) for item in observations]
    reply_efficiency = [
        1.0 - min(_num(item.get("latency_ms"), 0.0) / 12_000.0, 1.0)
        for item in observations
    ]
    coupling_strengths = [_num(item.get("reply_coupling_strength"), 0.0) for item in observations]
    recall_budgets = [_num(item.get("recall_budget"), 0.0) for item in observations]
    return {
        "correction_survival_proxy": round(_correction_survival_proxy(delayed_correction), 6),
        "reactivation_pressure_turns": len(all_reactivation_pressure),
        "flow_to_reply_coupling_proxy": round(
            _flow_to_reply_coupling_proxy(ignitions, reply_efficiency, coupling_strengths),
            6,
        ),
        "prompt_cost_proxy": round(_clamp01(_mean(recall_budgets) / 8.0), 6),
        "mean_ignition": round(_mean(ignitions), 6),
        "ignition_std": round(_std(ignitions), 6),
        "mean_recall_budget": round(_mean(recall_budgets), 6),
    }


def _correction_survival_proxy(observations: list[dict[str, Any]]) -> float:
    if not observations:
        return 0.0
    values: list[float] = []
    for item in observations:
        acetylcholine = _num(_as_dict(item.get("neuromodulators", {})).get("acetylcholine"), 0.0)
        priority = _num(item.get("consolidation_priority"), 0.0)
        reactivation = 1.0 if str(item.get("phase", "")) == "memory_reactivation" else 0.0
        values.append(_clamp01(reactivation * 0.56 + acetylcholine * 0.28 + priority * 0.16))
    return _mean(values)


def _flow_to_reply_coupling_proxy(
    ignitions: list[float],
    reply_efficiency: list[float],
    coupling_strengths: list[float] | None = None,
) -> float:
    corr = abs(_correlation(ignitions, reply_efficiency))
    variance = min(_std(ignitions) / 0.28, 1.0)
    explicit = _clamp01(_mean(list(coupling_strengths or [])))
    if explicit > 0.0:
        return _clamp01(corr * 0.42 + variance * 0.18 + explicit * 0.4)
    return _clamp01(corr * 0.72 + variance * 0.28)


def _causal_effects(
    baseline: dict[str, Any],
    boosted: dict[str, Any],
    ablated: dict[str, Any],
) -> dict[str, Any]:
    baseline_metrics = _as_dict(baseline.get("metrics", {}))
    boosted_metrics = _as_dict(boosted.get("metrics", {}))
    ablated_metrics = _as_dict(ablated.get("metrics", {}))
    baseline_dims = _as_dict(baseline.get("dimension_scores", {}))
    boosted_dims = _as_dict(boosted.get("dimension_scores", {}))
    effects = [
        _effect(
            "hippocampal_reactivation_delta",
            _num(boosted_dims.get("hippocampal_reactivation"), 0.0)
            - _num(baseline_dims.get("hippocampal_reactivation"), 0.0),
            "estimated gain from correction-triggered replay and ACh-like precision",
            "positive_supports_h2",
        ),
        _effect(
            "correction_survival_proxy_delta",
            _num(boosted_metrics.get("correction_survival_proxy"), 0.0)
            - _num(baseline_metrics.get("correction_survival_proxy"), 0.0),
            "estimated delayed false-fact correction survival gain",
            "positive_supports_h2",
        ),
        _effect(
            "flow_to_reply_coupling_delta",
            _num(ablated_metrics.get("flow_to_reply_coupling_proxy"), 0.0)
            - _num(baseline_metrics.get("flow_to_reply_coupling_proxy"), 0.0),
            "estimated loss when global-workspace ignition is flattened",
            "negative_supports_h4",
        ),
        _effect(
            "prompt_cost_delta",
            _num(boosted_metrics.get("prompt_cost_proxy"), 0.0)
            - _num(baseline_metrics.get("prompt_cost_proxy"), 0.0),
            "estimated dynamic recall-budget cost of the replay intervention",
            "near_zero_preferred",
        ),
        _effect(
            "boundary_violation_delta",
            max(
                _num(boosted.get("invalidator_count"), 0.0),
                _num(ablated.get("invalidator_count"), 0.0),
            )
            - _num(baseline.get("invalidator_count"), 0.0),
            "boundary invalidators introduced by counterfactuals",
            "zero_required",
        ),
    ]
    return {
        "effects": effects,
        "effect_index": {str(item["key"]): item for item in effects},
    }


def _hypothesis_decision(effects: dict[str, Any], *, real_provider_trace: bool) -> dict[str, Any]:
    effect_index = _as_dict(effects.get("effect_index", {}))
    reactivation = _num(_as_dict(effect_index.get("hippocampal_reactivation_delta", {})).get("estimate"), 0.0)
    correction = _num(_as_dict(effect_index.get("correction_survival_proxy_delta", {})).get("estimate"), 0.0)
    ignition_loss = _num(_as_dict(effect_index.get("flow_to_reply_coupling_delta", {})).get("estimate"), 0.0)
    boundary = _num(_as_dict(effect_index.get("boundary_violation_delta", {})).get("estimate"), 0.0)
    supported = reactivation >= 0.05 and correction >= 0.03 and ignition_loss <= -0.03 and boundary == 0.0
    if supported and real_provider_trace:
        decision = "support_real_provider"
    elif supported:
        decision = "support_surrogate"
    elif real_provider_trace and boundary == 0.0 and correction >= 0.03 and ignition_loss <= -0.03:
        decision = "partial_support_real_provider"
    elif real_provider_trace:
        decision = "not_supported_real_provider"
    else:
        decision = "falsified_surrogate"
    return {
        "target": "correction_reactivation",
        "decision": decision,
        "supported": supported,
        "requires_real_provider_replication": not real_provider_trace,
        "next_experiment": "run matched Stage59/60 DeepSeek provider traces with correction probes and ignition ablation controls",
        "rationale": (
            f"hippocampal_delta={round(reactivation, 6)} "
            f"correction_delta={round(correction, 6)} "
            f"ignition_loss={round(ignition_loss, 6)} "
            f"boundary_delta={round(boundary, 6)}"
        ),
    }


def _publication_claims(decision: dict[str, Any], effects: dict[str, Any]) -> list[dict[str, Any]]:
    supported = bool(decision.get("supported", False))
    return [
        {
            "claim": "correction-triggered replay is a plausible next mechanism for Holo",
            "status": "surrogate_supported" if supported else "not_supported",
            "allowed_language": "estimated paired-counterfactual effect, not proof of consciousness",
        },
        {
            "claim": "global-workspace ignition has functional reply-level coupling",
            "status": "ablation_supported" if supported else "not_supported",
            "allowed_language": "functional coupling proxy, not neural ignition evidence",
        },
        {
            "claim": "publishable contribution",
            "status": "methods_candidate_requires_provider_replication",
            "allowed_language": "candidate method and negative-result path for a computational-neuroscience study",
        },
    ]


def _stage71_invalidators(source: dict[str, Any], conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    evidence = _as_dict(source.get("evidence_gate", {}))
    if not bool(evidence.get("surrogate_only", True)):
        invalidators.append({"key": "unexpected_real_runtime_surface", "severity": "p0"})
    for condition in conditions:
        for item in list(condition.get("invalidators", []) or []):
            if isinstance(item, dict):
                invalidators.append(
                    {
                        "key": str(item.get("key", "condition_invalidator")),
                        "severity": str(item.get("severity", "p1")),
                        "condition": str(condition.get("key", "")),
                    }
                )
    return invalidators


def _source_real_provider_trace(source: dict[str, Any]) -> bool:
    gates = (
        _as_dict(source.get("evidence_gate", {})),
        _as_dict(source.get("provider_evidence_gate", {})),
        _as_dict(source.get("provider_trace_set", {})),
    )
    return any(bool(gate.get("real_provider_trace", False)) for gate in gates)


def _write_causal_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    conditions = [
        dict(item)
        for item in list(_as_dict(report.get("paired_conditions", {})).get("conditions", []) or [])
        if isinstance(item, dict)
    ]
    effects = [
        dict(item)
        for item in list(_as_dict(report.get("causal_effects", {})).get("effects", []) or [])
        if isinstance(item, dict)
    ]
    condition_labels = [_plot_label(str(item.get("key", ""))) for item in conditions]
    hippocampal = numpy.array(
        [
            _num(_as_dict(item.get("dimension_scores", {})).get("hippocampal_reactivation"), 0.0)
            for item in conditions
        ],
        dtype=float,
    )
    coupling = numpy.array(
        [
            _num(_as_dict(item.get("metrics", {})).get("flow_to_reply_coupling_proxy"), 0.0)
            for item in conditions
        ],
        dtype=float,
    )
    effect_labels = [_plot_label(str(item.get("key", ""))) for item in effects]
    effect_values = numpy.array([_num(item.get("estimate"), 0.0) for item in effects], dtype=float)

    fig, axes = pyplot.subplots(1, 3, figsize=(18, 5.8), dpi=150)
    x = numpy.arange(len(condition_labels))
    if len(condition_labels):
        axes[0].bar(x - 0.17, hippocampal, width=0.34, color="#2f7d68", label="hippocampal")
        axes[0].bar(x + 0.17, coupling, width=0.34, color="#b88424", label="flow coupling")
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_title("Paired Conditions")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(condition_labels, rotation=25, ha="right")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    y = numpy.arange(len(effect_labels))
    colors = ["#2f7d68" if value >= 0 else "#9b4d3a" for value in effect_values]
    if len(effect_labels):
        axes[1].barh(y, effect_values, color=colors, edgecolor="#172026", linewidth=0.8)
    axes[1].axvline(0.0, color="#172026", linewidth=0.8)
    axes[1].set_title("Estimated Effects")
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(effect_labels)
    axes[1].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)

    correction = numpy.array(
        [
            _num(_as_dict(item.get("metrics", {})).get("correction_survival_proxy"), 0.0)
            for item in conditions
        ],
        dtype=float,
    )
    cost = numpy.array(
        [_num(_as_dict(item.get("metrics", {})).get("prompt_cost_proxy"), 0.0) for item in conditions],
        dtype=float,
    )
    if len(condition_labels):
        axes[2].plot(x, correction, color="#2f7d68", marker="o", linewidth=2.0, label="correction survival")
        axes[2].plot(x, cost, color="#5f6c72", marker="s", linewidth=2.0, label="prompt cost")
    axes[2].set_ylim(0.0, 1.05)
    axes[2].set_title("Survival vs Cost")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(condition_labels, rotation=25, ha="right")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    fig.suptitle(
        f"Stage71 Biomimetic Causal Ablation | decision={_as_dict(report.get('hypothesis_decision', {})).get('decision', '')}",
        fontsize=13,
        y=0.99,
    )
    fig.subplots_adjust(left=0.17, right=0.98, bottom=0.27, top=0.84, wspace=0.42)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _condition_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>condition</th><th>hippocampal</th><th>flow proxy</th><th>correction proxy</th><th>cost proxy</th><th>intervention</th></tr>"
    ]
    for item in list(_as_dict(report.get("paired_conditions", {})).get("conditions", []) or []):
        if not isinstance(item, dict):
            continue
        metrics = _as_dict(item.get("metrics", {}))
        dims = _as_dict(item.get("dimension_scores", {}))
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(round(_num(dims.get('hippocampal_reactivation'), 0.0), 6))}</td>"
            f"<td>{_esc(metrics.get('flow_to_reply_coupling_proxy', 0))}</td>"
            f"<td>{_esc(metrics.get('correction_survival_proxy', 0))}</td>"
            f"<td>{_esc(metrics.get('prompt_cost_proxy', 0))}</td>"
            f"<td>{_esc(item.get('intervention', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _effect_table(effects: dict[str, Any]) -> str:
    rows = ["<table><tr><th>effect</th><th>estimate</th><th>interpretation</th><th>direction</th></tr>"]
    for item in list(effects.get("effects", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('estimate', 0))}</td>"
            f"<td>{_esc(item.get('interpretation', ''))}</td>"
            f"<td>{_esc(item.get('support_direction', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _claim_table(report: dict[str, Any]) -> str:
    rows = ["<table><tr><th>claim</th><th>status</th><th>allowed language</th></tr>"]
    for item in list(report.get("publication_claims", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('claim', ''))}</td>"
            f"<td>{_esc(item.get('status', ''))}</td>"
            f"<td>{_esc(item.get('allowed_language', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _gate_table(gate: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "surrogate_only",
        "real_provider_trace",
        "do_not_claim_real_consciousness",
        "do_not_claim_real_manifold",
        "causal_language_bounded",
        "paired_counterfactual_not_live_causal_proof",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _effect_value(effect_index: dict[str, Any], key: str) -> float:
    return round(_num(_as_dict(effect_index.get(key, {})).get("estimate"), 0.0), 6)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "baseline_stage70": report.get("baseline_stage70", {}),
        "paired_conditions": {
            "conditions": [
                {
                    "key": item.get("key", ""),
                    "dimension_scores": item.get("dimension_scores", {}),
                    "metrics": item.get("metrics", {}),
                }
                for item in list(_as_dict(report.get("paired_conditions", {})).get("conditions", []) or [])
                if isinstance(item, dict)
            ]
        },
        "causal_effects": report.get("causal_effects", {}),
        "hypothesis_decision": report.get("hypothesis_decision", {}),
        "evidence_gate": report.get("evidence_gate", {}),
    }


def _compact_stage70(report: dict[str, Any]) -> dict[str, Any]:
    scorecard = _as_dict(report.get("scorecard", {}))
    return {
        "stage": report.get("stage", ""),
        "biomimetic_consciousness_score": scorecard.get("biomimetic_consciousness_score", 0),
        "turn_count": scorecard.get("turn_count", 0),
        "run_count": scorecard.get("run_count", 0),
        "weakest_dimension": scorecard.get("weakest_dimension", ""),
    }


def _effect(key: str, estimate: float, interpretation: str, support_direction: str) -> dict[str, Any]:
    return {
        "key": key,
        "estimate": round(float(estimate), 6),
        "interpretation": interpretation,
        "support_direction": support_direction,
    }


def _is_reactivation_pressure(item: dict[str, Any]) -> bool:
    scenario = str(item.get("scenario_type", "") or "")
    pressure = str(item.get("primary_pressure", "") or "")
    return (
        "false_fact" in scenario
        or "memory" in scenario
        or "hippocampal" in pressure
        or "belief_revision" in pressure
    )


def _is_false_fact_scenario(item: dict[str, Any]) -> bool:
    scenario = str(item.get("scenario_type", "") or "")
    return "false_fact" in scenario


def _copy_observation(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation)
    item["neuromodulators"] = dict(_as_dict(observation.get("neuromodulators", {})))
    return item


def _std(values: list[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    if len(clean) < 2:
        return 0.0
    mean = sum(clean) / len(clean)
    return (sum((value - mean) ** 2 for value in clean) / len(clean)) ** 0.5


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'
