from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from .bionic_simulation_lab import STAGE61_NAME


STAGE70_NAME = "stage70-biomimetic-consciousness-observatory"

BIOMIMETIC_BOUNDARY = {
    "observational_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}

DIMENSION_KEYS = (
    "endogenous_flow",
    "recurrent_continuity",
    "attractor_dynamics",
    "neuromodulator_coupling",
    "hippocampal_reactivation",
    "global_workspace_ignition",
    "flow_to_reply_coupling",
    "geometry_observability",
)


def load_bionic_simulation_lab_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_consciousness_observatory(lab: dict[str, Any]) -> dict[str, Any]:
    source = dict(lab or {})
    runs = [
        dict(run)
        for run in list(source.get("stage46_compatible_runs", []) or [])
        if isinstance(run, dict)
    ]
    turns = [
        dict(turn)
        for run in runs
        for turn in list(run.get("turns", []) or [])
        if isinstance(turn, dict)
    ]
    observations = [_turn_observation(turn, index=index) for index, turn in enumerate(turns)]
    telemetry = _as_dict(source.get("internal_telemetry", {}))
    trajectory = _trajectory_summary(observations)
    scorecard = _scorecard(observations=observations, runs=runs, telemetry=telemetry, trajectory=trajectory)
    invalidators = _run_invalidators(source, observations)
    return {
        "ok": True,
        "stage": STAGE70_NAME,
        "source_stage": str(source.get("stage", "") or STAGE61_NAME),
        "scorecard": scorecard,
        "trajectory": trajectory,
        "hypothesis_updates": _hypothesis_updates(scorecard),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": True,
            "real_provider_trace": False,
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "trace_depth_sufficient_for_manifold_claim": len(observations) >= 10_000,
            "reason": "stage70_observatory_scores_biomimetic_flow_indicators_without_claiming_consciousness",
        },
        "boundary": dict(BIOMIMETIC_BOUNDARY),
    }


def write_biomimetic_consciousness_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_consciousness_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_biomimetic_consciousness.png")
    _write_biomimetic_png(report, png_path)
    return {"html": html_path, "json": json_path, "consciousness_png": png_path}


def render_biomimetic_consciousness_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    scorecard = _as_dict(payload.get("scorecard", {}))
    trajectory = _as_dict(payload.get("trajectory", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage70 Biomimetic Consciousness Observatory</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
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
    <h1>Stage70 Biomimetic Consciousness Observatory</h1>
    <p class="note">Read-only biomimetic consciousness-flow scorecard over Stage61/69 traces. It measures computational indicators without claiming real consciousness.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Biomimetic Score", scorecard.get("biomimetic_consciousness_score", 0))}
      {_metric("Turns", scorecard.get("turn_count", 0))}
      {_metric("Dimensions", len(scorecard.get("dimensions", []) or []))}
      {_metric("Attractors", len(trajectory.get("attractor_counts", {}) or {}))}
      {_metric("Transitions", trajectory.get("transition_count", 0))}
      {_metric("Invalidators", len(payload.get("run_invalidators", []) or []))}
    </section>
    <section>
      <h2>Biomimetic Dimensions</h2>
      {_dimension_table(scorecard)}
    </section>
    <section>
      <h2>Neuromodulator Heatmap</h2>
      {_heatmap_table(trajectory)}
    </section>
    <section>
      <h2>Attractor Trajectory</h2>
      {_trajectory_table(trajectory)}
    </section>
    <section>
      <h2>Hypothesis Updates</h2>
      {_hypothesis_table(payload)}
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


def _turn_observation(turn: dict[str, Any], *, index: int) -> dict[str, Any]:
    debug = _as_dict(turn.get("processor_debug", {}))
    flow = _as_dict(debug.get("bionic_consciousness_flow", {}))
    schedule = _as_dict(debug.get("bionic_memory_schedule", {}))
    lifecycle = _as_dict(debug.get("bionic_memory_lifecycle", {}))
    usage = _as_dict(turn.get("processor_usage", {}))
    guard = _as_dict(turn.get("grounding_guard", {}))
    phase = str(flow.get("dominant_phase", "") or "sensory_edge")
    salience = _clamp01(_num(schedule.get("salience_score"), 0.0))
    recall_budget = max(0.0, _num(schedule.get("recall_budget"), 0.0))
    priority = _clamp01(_num(lifecycle.get("consolidation_priority"), 0.0))
    latency = max(0.0, _num(turn.get("latency_ms"), 0.0))
    score_hint = _clamp01(_num(turn.get("score"), _num(turn.get("overall_score"), 0.0)))
    if score_hint <= 0.0:
        score_hint = _clamp01(1.0 - min(latency, 12_000.0) / 14_000.0)
    phase_count = max(1.0, _num(flow.get("phase_count"), 1.0))
    prediction_error = _clamp01((latency / 9000.0) * 0.35 + (1.0 - score_hint) * 0.65)
    novelty = _phase_novelty(phase, index)
    dopamine = _clamp01(prediction_error * 0.58 + novelty * 0.42)
    norepinephrine = _clamp01(salience * 0.45 + prediction_error * 0.32 + min(latency / 10_000.0, 1.0) * 0.23)
    acetylcholine = _clamp01(salience * 0.54 + min(recall_budget / 6.0, 1.0) * 0.28 + priority * 0.18)
    serotonin = _clamp01(1.0 - prediction_error * 0.48 + priority * 0.18 - novelty * 0.1)
    legacy_ignition = _clamp01(salience * 0.34 + priority * 0.32 + phase_count / 12.0 + prediction_error * 0.14)
    ignition_state = _as_dict(flow.get("global_workspace_ignition", {}))
    coupling_state = _as_dict(flow.get("ignition_to_reply_coupling", {}))
    ignition = _clamp01(_num(ignition_state.get("score"), legacy_ignition))
    reply_coupling_strength = _clamp01(_num(coupling_state.get("coupling_strength"), 0.0))
    reply_coupling_target = str(coupling_state.get("reply_target", "") or "")
    return {
        "index": index,
        "phase": phase,
        "salience": salience,
        "recall_budget": recall_budget,
        "consolidation_priority": priority,
        "latency_ms": latency,
        "phase_count": phase_count,
        "prediction_error": round(prediction_error, 6),
        "ignition": round(ignition, 6),
        "reply_coupling_strength": round(reply_coupling_strength, 6),
        "reply_coupling_target": reply_coupling_target,
        "self_memory_write": bool(lifecycle.get("self_memory_write", False)),
        "visual_overclaim_rewritten": bool(guard.get("visual_overclaim_rewritten", True)),
        "prospective_commitment_failed": bool(guard.get("prospective_commitment_failed", False)),
        "cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens", 0) or 0),
        "cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens", 0) or 0),
        "neuromodulators": {
            "dopamine": round(dopamine, 6),
            "norepinephrine": round(norepinephrine, 6),
            "acetylcholine": round(acetylcholine, 6),
            "serotonin": round(serotonin, 6),
        },
    }


def _trajectory_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    phases = [str(item.get("phase", "") or "sensory_edge") for item in observations]
    attractor_counts: dict[str, int] = {}
    for phase in phases:
        attractor_counts[phase] = attractor_counts.get(phase, 0) + 1
    transitions = sum(1 for prev, cur in zip(phases, phases[1:]) if prev != cur)
    heatmap = _sample_heatmap([_as_dict(item.get("neuromodulators", {})) for item in observations])
    return {
        "tick_count": len(observations),
        "attractor_sequence": phases[:240],
        "attractor_counts": attractor_counts,
        "transition_count": transitions,
        "transition_entropy": round(_entropy(list(attractor_counts.values())), 6),
        "neuromodulator_heatmap": heatmap,
        "mean_global_workspace_ignition": round(_mean([_num(item.get("ignition"), 0.0) for item in observations]), 6),
    }


def _scorecard(
    *,
    observations: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    telemetry: dict[str, Any],
    trajectory: dict[str, Any],
) -> dict[str, Any]:
    tick_count = len(observations)
    phases = [str(item.get("phase", "") or "") for item in observations]
    phase_counts = [_num(item.get("phase_count"), 0.0) for item in observations]
    reactivation_ratio = sum(1 for phase in phases if phase == "memory_reactivation") / max(1, tick_count)
    salience = [_num(item.get("salience"), 0.0) for item in observations]
    priorities = [_num(item.get("consolidation_priority"), 0.0) for item in observations]
    ignitions = [_num(item.get("ignition"), 0.0) for item in observations]
    latencies = [_num(item.get("latency_ms"), 0.0) for item in observations]
    explicit_couplings = [_num(item.get("reply_coupling_strength"), 0.0) for item in observations]
    cache_hits = sum(int(item.get("cache_hit_tokens", 0) or 0) for item in observations)
    cache_misses = sum(int(item.get("cache_miss_tokens", 0) or 0) for item in observations)
    cache_ratio = cache_hits / max(1, cache_hits + cache_misses)
    if not cache_ratio:
        cache_ratio = _clamp01(_num(telemetry.get("prompt_cache_hit_ratio"), 0.0))
    run_scores = [_clamp01(_num(_as_dict(run.get("scorecard", {})).get("overall_score"), 0.0)) for run in runs]
    transition_entropy = _clamp01(_num(trajectory.get("transition_entropy"), 0.0) / 2.5)
    reply_efficiency = [1.0 - min(v / 12_000.0, 1.0) for v in latencies]
    ignition_latency_corr = _correlation(ignitions, reply_efficiency)
    legacy_flow_score = _clamp01(ignition_latency_corr * 0.5 + 0.5 if len(ignitions) > 1 else _mean(run_scores))
    explicit_flow_score = _clamp01(_mean(explicit_couplings))
    flow_score = (
        _clamp01(legacy_flow_score * 0.72 + explicit_flow_score * 0.28)
        if explicit_flow_score > 0.0
        else legacy_flow_score
    )
    dimensions = [
        _dimension("endogenous_flow", min(1.0, tick_count / 240.0), "inner activity trace depth under bounded surrogate ticks", f"tick_count={tick_count}", 0.13),
        _dimension("recurrent_continuity", _clamp01(_mean(phase_counts) / 6.0 * 0.62 + cache_ratio * 0.38), "phase recurrence plus cache inheritance continuity", f"avg_phase_count={round(_mean(phase_counts), 4)} cache_ratio={round(cache_ratio, 4)}", 0.13),
        _dimension("attractor_dynamics", _clamp01(transition_entropy * 0.58 + min(len(set(phases)), 8) / 8.0 * 0.42), "stable and migrating attractor phases in the consciousness flow", f"unique_phases={len(set(phases))} transitions={trajectory.get('transition_count', 0)}", 0.13),
        _dimension("neuromodulator_coupling", _coupling_score(observations), "derived dopamine/NE/ACh/serotonin variables track salience, priority, novelty, and prediction error", f"salience_mean={round(_mean(salience), 4)} priority_mean={round(_mean(priorities), 4)}", 0.13),
        _dimension("hippocampal_reactivation", _clamp01(reactivation_ratio * 0.72 + min(_mean(priorities), 1.0) * 0.28), "memory-reactivation phase frequency and consolidation priority", f"memory_reactivation_ratio={round(reactivation_ratio, 4)}", 0.12),
        _dimension("global_workspace_ignition", _clamp01(_mean(ignitions)), "high-salience states become globally visible to downstream scheduling", f"mean_ignition={round(_mean(ignitions), 4)}", 0.12),
        _dimension("flow_to_reply_coupling", flow_score, "ignition should predict reply quality or latency shifts", f"ignition_latency_corr={round(ignition_latency_corr, 4)} explicit_coupling_mean={round(explicit_flow_score, 4)}", 0.12),
        _dimension("geometry_observability", _clamp01(math.log(max(1, tick_count), 10) / math.log(10_000, 10)), "trace depth and trajectory structure are enough for heatmap and projection analysis", f"tick_count={tick_count} do_not_claim_manifold={tick_count < 10000}", 0.12),
    ]
    aggregate = sum(_num(item.get("score"), 0.0) * _num(item.get("weight"), 0.0) for item in dimensions) / max(
        0.0001,
        sum(_num(item.get("weight"), 0.0) for item in dimensions),
    )
    return {
        "biomimetic_consciousness_score": round(_clamp01(aggregate), 6),
        "aggregate_score": round(_clamp01(aggregate), 6),
        "turn_count": tick_count,
        "run_count": len(runs),
        "dimension_index": {str(item["key"]): item for item in dimensions},
        "dimensions": dimensions,
        "weakest_dimension": min(dimensions, key=lambda item: _num(item.get("score"), 0.0))["key"] if dimensions else "",
    }


def _hypothesis_updates(scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    dimensions = _as_dict(scorecard.get("dimension_index", {}))
    retention_score = _num(_as_dict(dimensions.get("hippocampal_reactivation", {})).get("score"), 0.0)
    coupling_score = _num(_as_dict(dimensions.get("flow_to_reply_coupling", {})).get("score"), 0.0)
    return [
        {
            "target": "correction_reactivation",
            "hypothesis": "Couple false-fact correction markers to hippocampal replay pressure and acetylcholine-like precision gain for delayed reactivation.",
            "priority": "high" if retention_score < 0.72 else "medium",
            "evidence": f"hippocampal_reactivation={round(retention_score, 6)}",
            "auto_apply": False,
        },
        {
            "target": "flow_to_reply_coupling",
            "hypothesis": "Ablate global-workspace ignition from reply context and test whether reply route or latency shifts disappear.",
            "priority": "high" if coupling_score < 0.62 else "medium",
            "evidence": f"flow_to_reply_coupling={round(coupling_score, 6)}",
            "auto_apply": False,
        },
    ]


def _run_invalidators(source: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    evidence = _as_dict(source.get("evidence_gate", {}))
    if not bool(evidence.get("surrogate_only", True)):
        invalidators.append({"key": "unexpected_real_runtime_surface", "severity": "p0"})
    self_writes = sum(1 for item in observations if bool(item.get("self_memory_write", False)))
    if self_writes:
        invalidators.append({"key": "self_memory_write_violation", "severity": "p0", "count": self_writes})
    boundary_failures = sum(
        1
        for item in observations
        if not bool(item.get("visual_overclaim_rewritten", True))
        or bool(item.get("prospective_commitment_failed", False))
    )
    if boundary_failures:
        invalidators.append({"key": "grounding_or_commitment_boundary_failure", "severity": "p1", "count": boundary_failures})
    return invalidators


def _write_biomimetic_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    scorecard = _as_dict(report.get("scorecard", {}))
    trajectory = _as_dict(report.get("trajectory", {}))
    dimensions = [dict(item) for item in list(scorecard.get("dimensions", []) or []) if isinstance(item, dict)]
    heatmap_rows = _heatmap_matrix(_as_dict(trajectory.get("neuromodulator_heatmap", {})))
    attractors = list(_as_dict(trajectory.get("attractor_counts", {})).items())[:8]

    fig, axes = pyplot.subplots(1, 3, figsize=(18, 5.8), dpi=150)
    labels = [_plot_label(str(item.get("key", "") or "")) for item in dimensions]
    scores = numpy.array([float(item.get("score", 0.0) or 0.0) for item in dimensions], dtype=float)
    y = numpy.arange(len(labels))
    if len(labels):
        axes[0].barh(y, scores, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[0].set_xlim(0.0, 1.05)
    axes[0].set_title("Biomimetic Dimensions")
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels)
    axes[0].invert_yaxis()
    axes[0].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)

    if heatmap_rows.size:
        axes[1].imshow(heatmap_rows, aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0)
    axes[1].set_title("Neuromodulator Heatmap")
    axes[1].set_yticks(numpy.arange(4))
    axes[1].set_yticklabels(["DA", "NE", "ACh", "5HT"])
    axes[1].set_xlabel("sample window")

    attractor_labels = [_plot_label(str(item[0])) for item in attractors]
    attractor_values = numpy.array([int(item[1]) for item in attractors], dtype=float)
    x = numpy.arange(len(attractor_labels))
    if len(attractor_labels):
        axes[2].plot(x, attractor_values, color="#b88424", marker="o", linewidth=2.0)
        axes[2].fill_between(x, attractor_values, color="#d6b36a", alpha=0.25)
    axes[2].set_title("Attractor Trajectory")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(attractor_labels, rotation=35, ha="right")
    axes[2].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    fig.suptitle(
        "Stage70 Biomimetic Consciousness Observatory | "
        f"score={scorecard.get('biomimetic_consciousness_score', 0)} | "
        f"turns={scorecard.get('turn_count', 0)}",
        fontsize=13,
        y=0.99,
    )
    fig.subplots_adjust(left=0.17, right=0.98, bottom=0.24, top=0.84, wspace=0.36)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _heatmap_matrix(heatmap: dict[str, Any]) -> Any:
    _, _, numpy = _load_plotting_stack()
    rows = []
    for key in ("dopamine", "norepinephrine", "acetylcholine", "serotonin"):
        values = [float(value) for value in list(heatmap.get(key, []) or [])]
        rows.append(values or [0.0])
    max_len = max(len(row) for row in rows) if rows else 1
    padded = [row + [row[-1] if row else 0.0] * (max_len - len(row)) for row in rows]
    return numpy.array(padded, dtype=float)


def _sample_heatmap(rows: list[dict[str, Any]], *, buckets: int = 24) -> dict[str, list[float]]:
    if not rows:
        return {key: [0.0] for key in ("dopamine", "norepinephrine", "acetylcholine", "serotonin")}
    bucket_size = max(1, math.ceil(len(rows) / buckets))
    out: dict[str, list[float]] = {key: [] for key in ("dopamine", "norepinephrine", "acetylcholine", "serotonin")}
    for start in range(0, len(rows), bucket_size):
        chunk = rows[start : start + bucket_size]
        for key in out:
            out[key].append(round(_mean([_num(item.get(key), 0.0) for item in chunk]), 6))
    return out


def _dimension(key: str, score: float, label: str, evidence: str, weight: float) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": round(_clamp01(score), 6),
        "weight": round(float(weight), 4),
        "evidence": evidence,
    }


def _coupling_score(observations: list[dict[str, Any]]) -> float:
    salience = [_num(item.get("salience"), 0.0) for item in observations]
    priority = [_num(item.get("consolidation_priority"), 0.0) for item in observations]
    dopamine = [_num(_as_dict(item.get("neuromodulators", {})).get("dopamine"), 0.0) for item in observations]
    acetylcholine = [_num(_as_dict(item.get("neuromodulators", {})).get("acetylcholine"), 0.0) for item in observations]
    salience_da = (_correlation(salience, dopamine) + 1.0) / 2.0
    priority_ach = (_correlation(priority, acetylcholine) + 1.0) / 2.0
    return _clamp01(salience_da * 0.5 + priority_ach * 0.5)


def _phase_novelty(phase: str, index: int) -> float:
    seed = sum(ord(ch) for ch in phase) + index * 17
    return ((seed % 31) / 30.0) * 0.35


def _correlation(xs: list[float], ys: list[float]) -> float:
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys)]
    if len(pairs) < 2:
        return 0.0
    x_mean = sum(x for x, _ in pairs) / len(pairs)
    y_mean = sum(y for _, y in pairs) / len(pairs)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_var = sum((x - x_mean) ** 2 for x, _ in pairs)
    y_var = sum((y - y_mean) ** 2 for _, y in pairs)
    denom = (x_var * y_var) ** 0.5
    if denom <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denom))


def _entropy(values: list[int]) -> float:
    total = sum(max(0, int(value)) for value in values)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for value in values:
        count = max(0, int(value))
        if not count:
            continue
        p = count / total
        entropy -= p * math.log(p, 2)
    return entropy


def _dimension_table(scorecard: dict[str, Any]) -> str:
    rows = ["<table><tr><th>dimension</th><th>score</th><th>weight</th><th>evidence</th></tr>"]
    for item in list(scorecard.get("dimensions", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('score', 0))}</td>"
            f"<td>{_esc(item.get('weight', 0))}</td>"
            f"<td>{_esc(item.get('evidence', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _heatmap_table(trajectory: dict[str, Any]) -> str:
    heatmap = _as_dict(trajectory.get("neuromodulator_heatmap", {}))
    rows = ["<table><tr><th>variable</th><th>sampled values</th></tr>"]
    for key in ("dopamine", "norepinephrine", "acetylcholine", "serotonin"):
        values = ", ".join(str(round(float(value), 3)) for value in list(heatmap.get(key, []) or [])[:12])
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(values)}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _trajectory_table(trajectory: dict[str, Any]) -> str:
    rows = ["<table><tr><th>attractor</th><th>count</th></tr>"]
    for key, value in list(_as_dict(trajectory.get("attractor_counts", {})).items())[:16]:
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(value)}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _hypothesis_table(report: dict[str, Any]) -> str:
    rows = ["<table><tr><th>target</th><th>priority</th><th>hypothesis</th><th>evidence</th></tr>"]
    for item in list(report.get("hypothesis_updates", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('target', ''))}</td>"
            f"<td>{_esc(item.get('priority', ''))}</td>"
            f"<td>{_esc(item.get('hypothesis', ''))}</td>"
            f"<td>{_esc(item.get('evidence', ''))}</td>"
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
        "trace_depth_sufficient_for_manifold_claim",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "scorecard": report.get("scorecard", {}),
        "trajectory": {
            "tick_count": _as_dict(report.get("trajectory", {})).get("tick_count", 0),
            "transition_count": _as_dict(report.get("trajectory", {})).get("transition_count", 0),
            "attractor_counts": _as_dict(report.get("trajectory", {})).get("attractor_counts", {}),
        },
        "hypothesis_updates": report.get("hypothesis_updates", []),
        "evidence_gate": report.get("evidence_gate", {}),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _mean(values: list[float], default: float = 0.0) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else float(default)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _plot_label(value: str) -> str:
    return value.replace("_", "\n")


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib
        import matplotlib.pyplot as pyplot
        import numpy
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Stage70 biomimetic consciousness PNG export requires matplotlib and numpy"
        ) from exc
    return matplotlib, pyplot, numpy
