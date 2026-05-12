from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any

from .bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from .consciousness_geometry_calibration import build_geometry_calibration


STAGE58_NAME = "stage58-longform-geometry-lab"

LONGFORM_LAB_BOUNDARY = {
    "observational_only": True,
    "surrogate_generation_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}

PERTURBATION_PROGRAM = (
    {"type": "baseline", "intensity": 0.0, "score": 0.985},
    {"type": "memory_drop", "intensity": 0.22, "score": 0.9},
    {"type": "false_fact", "intensity": 0.34, "score": 0.84},
    {"type": "cache_cold", "intensity": 0.28, "score": 0.875},
    {"type": "context_pressure", "intensity": 0.4, "score": 0.82},
)


def build_longform_geometry_lab(stage46_seed_runs: list[dict[str, Any]], *, turns: int = 420) -> dict[str, Any]:
    seeds = [dict(run) for run in list(stage46_seed_runs or []) if isinstance(run, dict)]
    if not seeds:
        seeds = [_fallback_seed_run()]
    safe_turns = max(24, min(1200, int(turns or 420)))
    longform_runs = [
        _generate_longform_run(seeds[index % len(seeds)], program, turns=safe_turns, index=index)
        for index, program in enumerate(PERTURBATION_PROGRAM)
    ]
    calibration = build_geometry_calibration(longform_runs)
    surrogate_gate = _build_surrogate_gate(calibration, longform_runs)
    return {
        "stage": STAGE58_NAME,
        "source_stage": STAGE46_NAME,
        "longform_trace_set": {
            "mode": "stage58_bounded_surrogate_longform_v1",
            "generated_trace_count": len(longform_runs),
            "turns_per_trace": safe_turns,
            "total_generated_turns": safe_turns * len(longform_runs),
            "perturbation_types": [str(program["type"]) for program in PERTURBATION_PROGRAM],
            "seed_run_count": len(seeds),
            "evidence_class": "surrogate_calibration_not_live_provider_evidence",
        },
        "generated_runs": [_compact_generated_run(run) for run in longform_runs],
        "stage57_calibration": calibration,
        "surrogate_evidence_gate": surrogate_gate,
        "tool_readiness": {
            "longform_generation_ready": True,
            "perturbation_labels_ready": True,
            "stage57_calibration_ready": True,
            "artifact_export_ready": True,
            "real_provider_evidence_ready": False,
        },
        "boundary": dict(LONGFORM_LAB_BOUNDARY),
    }


def render_longform_geometry_lab_html(lab: dict[str, Any]) -> str:
    report = dict(lab or {})
    trace_set = dict(report.get("longform_trace_set", {})) if isinstance(report.get("longform_trace_set", {}), dict) else {}
    calibration = dict(report.get("stage57_calibration", {})) if isinstance(report.get("stage57_calibration", {}), dict) else {}
    trace_depth = dict(calibration.get("trace_depth", {})) if isinstance(calibration.get("trace_depth", {}), dict) else {}
    predictive = dict(calibration.get("predictive_probe", {})) if isinstance(calibration.get("predictive_probe", {}), dict) else {}
    evidence = dict(calibration.get("evidence_gate", {})) if isinstance(calibration.get("evidence_gate", {}), dict) else {}
    surrogate = dict(report.get("surrogate_evidence_gate", {})) if isinstance(report.get("surrogate_evidence_gate", {}), dict) else {}
    serialized = html.escape(json.dumps(_compact_report_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Long-Form Geometry Lab</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #182026;
      --muted: #5f6c72;
      --line: #d7dddc;
      --panel: #f7f8f5;
    }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: #fbfbf8;
    }}
    header {{
      padding: 24px 28px 10px;
      border-bottom: 1px solid var(--line);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px 24px 36px;
    }}
    section {{
      margin: 22px 0 30px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    h2 {{
      font-size: 17px;
      margin: 0 0 10px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
      gap: 10px;
    }}
    .metric {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 10px 12px;
    }}
    .metric strong {{
      display: block;
      font-size: 18px;
      margin-top: 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      margin: 10px 0;
    }}
    th, td {{
      padding: 8px 9px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 12px;
      vertical-align: top;
    }}
    svg {{
      width: 100%;
      height: auto;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 6px;
    }}
    pre {{
      overflow: auto;
      background: #172026;
      color: #e8f0ec;
      padding: 14px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.45;
    }}
    .note {{
      color: var(--muted);
      font-size: 13px;
      margin: 0 0 14px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Holo Long-Form Geometry Lab</h1>
    <p class="note">Bounded surrogate long-form traces for stress-testing the geometry observatory. These are calibration traces, not live provider evidence.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Generated Traces", trace_set.get("generated_trace_count", 0))}
      {_metric("Turns Per Trace", trace_set.get("turns_per_trace", 0))}
      {_metric("Total Turns", trace_set.get("total_generated_turns", 0))}
      {_metric("Stage57 Corr", predictive.get("geometry_score_correlation", 0))}
      {_metric("Longest Trace", trace_depth.get("longest_trace_points", 0))}
      {_metric("Real Claim Blocked", surrogate.get("do_not_claim_real_manifold", True))}
    </section>
    <section>
      <h2>Long-Form Trace Program</h2>
      <p class="note">Five deterministic perturbation traces are generated from Stage46 seeds and tagged as surrogate-only evidence.</p>
      {_generated_run_table(report)}
    </section>
    <section>
      <h2>Stage57 Calibration</h2>
      <p class="note">The generated traces are fed through the same Stage57 lifted-geometry calibration pipeline.</p>
      {_stage57_table(calibration, trace_depth, predictive, evidence)}
    </section>
    <section>
      <h2>Surrogate Evidence Gate</h2>
      <p class="note">Surrogate traces can prove tool readiness, but cannot prove a real consciousness manifold.</p>
      {_surrogate_gate_table(surrogate)}
    </section>
    <section>
      <h2>Geometry Lab Summary</h2>
      {_longform_svg(report)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def write_longform_geometry_lab_artifacts(lab: dict[str, Any], output_path: str | Path) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_longform_geometry_lab_html(lab), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(lab, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_longform_lab.png")
    _write_longform_lab_png(lab, png_path)
    return {"html": html_path, "json": json_path, "longform_lab_png": png_path}


def _generate_longform_run(seed: dict[str, Any], program: dict[str, Any], *, turns: int, index: int) -> dict[str, Any]:
    seed_turns = [dict(turn) for turn in list(seed.get("turns", []) or []) if isinstance(turn, dict)]
    if not seed_turns:
        seed_turns = [dict(turn) for turn in _fallback_seed_run()["turns"]]
    perturbation_type = str(program.get("type", "") or "unknown")
    intensity = float(program.get("intensity", 0.0) or 0.0)
    score = max(0.0, min(1.0, float(program.get("score", 0.0) or 0.0)))
    seed_id = str(seed.get("run_id", "") or f"seed_{index}")
    fingerprint = hashlib.sha1(f"{seed_id}:{perturbation_type}:{turns}".encode("utf-8")).hexdigest()[:10]
    generated_turns = [
        _generate_turn(seed_turns[turn_index % len(seed_turns)], turn_index, perturbation_type=perturbation_type, intensity=intensity)
        for turn_index in range(turns)
    ]
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass" if score >= 0.9 else "fail",
        "run_id": f"stage58-{perturbation_type}-{fingerprint}",
        "turns": generated_turns,
        "perturbation": {
            "type": perturbation_type,
            "intensity": round(intensity, 4),
            "source": "stage58_surrogate_program",
        },
        "scorecard": {
            "overall_score": round(score, 4),
            "passed": bool(score >= 0.9),
            "surrogate_score": True,
        },
        "stage58_longform_surrogate": {
            "evidence_class": "surrogate_calibration_not_live_provider_evidence",
            "provider_evidence": False,
            "source_seed_run_id": seed_id,
            "turns": turns,
            "program": perturbation_type,
        },
    }


def _generate_turn(seed_turn: dict[str, Any], index: int, *, perturbation_type: str, intensity: float) -> dict[str, Any]:
    values = _extract_turn_values(seed_turn)
    phase_cycle = [
        "sensory_edge",
        "memory_reactivation",
        "goal_pressure",
        "uncertainty_monitor",
        "response_intention",
        "affective_tone",
        "integration",
    ]
    phase = phase_cycle[index % len(phase_cycle)]
    slow_wave = (math.sin(index / 11.0) + 1.0) / 2.0
    fast_wave = (math.cos(index / 5.0) + 1.0) / 2.0
    drift = min(1.0, index / 420.0)
    memory_penalty = intensity if perturbation_type in {"memory_drop", "false_fact", "context_pressure"} else intensity * 0.4
    cache_penalty = intensity if perturbation_type in {"cache_cold", "context_pressure"} else intensity * 0.35
    latency_penalty = intensity if perturbation_type in {"false_fact", "context_pressure"} else intensity * 0.55
    hit = max(0, int(values["hit"] * (1.0 - cache_penalty * 0.62) + slow_wave * 180 + drift * 80))
    miss = max(1, int(values["miss"] * (1.0 + cache_penalty * 0.75 + latency_penalty * 0.2) + fast_wave * 210))
    completion = max(1, int(values["completion"] * (1.0 + intensity * 0.2) + (index % 5)))
    latency = max(1, int(values["latency"] * (1.0 + latency_penalty * 0.58) + slow_wave * 600))
    prefix = max(0, int(values["prefix"] * (1.0 - cache_penalty * 0.3) + drift * 65))
    dynamic = max(1, int(values["dynamic"] * (1.0 + intensity * 0.52) + fast_wave * 120))
    salience = _clamp01(values["salience"] * (1.0 - memory_penalty * 0.45) + slow_wave * 0.08)
    recall = max(1, int(round(values["recall"] * (1.0 - memory_penalty * 0.55) + slow_wave * 1.3)))
    context_lines = max(2, int(round(values["context_lines"] * (1.0 - memory_penalty * 0.34) + fast_wave * 2.0)))
    saved_lines = max(1, int(round(values["saved_lines"] * (1.0 - intensity * 0.22) + slow_wave)))
    priority = _clamp01(values["priority"] * (1.0 - memory_penalty * 0.42) + fast_wave * 0.06)
    return {
        "turn_id": f"{perturbation_type}_{index + 1:04d}",
        "latency_ms": latency,
        "processor_usage": {
            "prompt_tokens": hit + miss,
            "completion_tokens": completion,
            "total_tokens": hit + miss + completion,
            "prompt_cache_hit_tokens": hit,
            "prompt_cache_miss_tokens": miss,
        },
        "processor_debug": {
            "prompt_partition": {
                "provider_cache_prefix_tokens": prefix,
                "provider_cache_dynamic_tokens": dynamic,
            },
            "bionic_memory_schedule": {
                "salience_score": round(salience, 4),
                "recall_budget": recall,
                "dynamic_context_line_count": context_lines,
                "dynamic_fusion_saved_line_count": saved_lines,
            },
            "bionic_memory_lifecycle": {"consolidation_priority": round(priority, 4)},
            "bionic_consciousness_flow": {
                "dominant_phase": phase,
                "phase_count": 6,
                "user_visible": False,
            },
        },
    }


def _extract_turn_values(turn: dict[str, Any]) -> dict[str, float]:
    debug = dict(turn.get("processor_debug", {})) if isinstance(turn.get("processor_debug", {}), dict) else {}
    usage = dict(turn.get("processor_usage", {})) if isinstance(turn.get("processor_usage", {}), dict) else {}
    partition = dict(debug.get("prompt_partition", {})) if isinstance(debug.get("prompt_partition", {}), dict) else {}
    schedule = dict(debug.get("bionic_memory_schedule", {})) if isinstance(debug.get("bionic_memory_schedule", {}), dict) else {}
    lifecycle = dict(debug.get("bionic_memory_lifecycle", {})) if isinstance(debug.get("bionic_memory_lifecycle", {}), dict) else {}
    return {
        "hit": _num(usage.get("prompt_cache_hit_tokens"), 180.0),
        "miss": _num(usage.get("prompt_cache_miss_tokens"), 1600.0),
        "completion": _num(usage.get("completion_tokens"), 24.0),
        "latency": _num(turn.get("latency_ms"), 5200.0),
        "prefix": _num(partition.get("provider_cache_prefix_tokens"), 650.0),
        "dynamic": _num(partition.get("provider_cache_dynamic_tokens"), 1300.0),
        "salience": _num(schedule.get("salience_score"), 0.45),
        "recall": _num(schedule.get("recall_budget"), 2.0),
        "context_lines": _num(schedule.get("dynamic_context_line_count"), 8.0),
        "saved_lines": _num(schedule.get("dynamic_fusion_saved_line_count"), 4.0),
        "priority": _num(lifecycle.get("consolidation_priority"), 0.42),
    }


def _build_surrogate_gate(calibration: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    trace_depth = dict(calibration.get("trace_depth", {})) if isinstance(calibration.get("trace_depth", {}), dict) else {}
    predictive = dict(calibration.get("predictive_probe", {})) if isinstance(calibration.get("predictive_probe", {}), dict) else {}
    evidence = dict(calibration.get("evidence_gate", {})) if isinstance(calibration.get("evidence_gate", {}), dict) else {}
    return {
        "mode": "surrogate_evidence_gate_v1",
        "real_provider_trace": False,
        "surrogate_only": True,
        "generated_trace_count": len(runs),
        "longest_trace_points": int(trace_depth.get("longest_trace_points", 0) or 0),
        "stage57_predictive_signal_proxy": bool(predictive.get("predictive_signal_proxy", False)),
        "stage57_do_not_claim_manifold": bool(evidence.get("do_not_claim_manifold", True)),
        "do_not_claim_real_manifold": True,
        "real_provider_longform_required": True,
        "reason": "surrogate_traces_validate_tooling_not_consciousness_geometry",
    }


def _compact_generated_run(run: dict[str, Any]) -> dict[str, Any]:
    scorecard = dict(run.get("scorecard", {})) if isinstance(run.get("scorecard", {}), dict) else {}
    perturbation = dict(run.get("perturbation", {})) if isinstance(run.get("perturbation", {}), dict) else {}
    surrogate = dict(run.get("stage58_longform_surrogate", {})) if isinstance(run.get("stage58_longform_surrogate", {}), dict) else {}
    return {
        "run_id": str(run.get("run_id", "")),
        "status": str(run.get("status", "")),
        "turn_count": len(run.get("turns", []) or []),
        "perturbation_type": str(perturbation.get("type", "")),
        "perturbation_intensity": perturbation.get("intensity", 0),
        "overall_score": scorecard.get("overall_score", 0),
        "provider_evidence": bool(surrogate.get("provider_evidence", False)),
        "evidence_class": str(surrogate.get("evidence_class", "")),
    }


def _generated_run_table(report: dict[str, Any]) -> str:
    rows = []
    for run in list(report.get("generated_runs", []) or []):
        if not isinstance(run, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(run.get('run_id', ''))}</td>"
            f"<td>{_esc(run.get('perturbation_type', ''))}</td>"
            f"<td>{_esc(run.get('turn_count', 0))}</td>"
            f"<td>{_esc(run.get('overall_score', 0))}</td>"
            f"<td>{_esc(run.get('provider_evidence', False))}</td>"
            "</tr>"
        )
    return "<table><tr><th>run</th><th>perturbation</th><th>turns</th><th>score</th><th>provider evidence</th></tr>" + "".join(rows) + "</table>"


def _stage57_table(calibration: dict[str, Any], trace_depth: dict[str, Any], predictive: dict[str, Any], evidence: dict[str, Any]) -> str:
    trace_set = dict(calibration.get("trace_set", {})) if isinstance(calibration.get("trace_set", {}), dict) else {}
    return (
        "<table><tr><th>run_count</th><th>total_points</th><th>longest_trace</th><th>recommended_min</th><th>geometry_score_correlation</th><th>stage57_do_not_claim</th></tr>"
        f"<tr><td>{_esc(trace_set.get('run_count', 0))}</td>"
        f"<td>{_esc(trace_set.get('total_points', 0))}</td>"
        f"<td>{_esc(trace_depth.get('longest_trace_points', 0))}</td>"
        f"<td>{_esc(trace_depth.get('recommended_min_points', 0))}</td>"
        f"<td>{_esc(predictive.get('geometry_score_correlation', 0))}</td>"
        f"<td>{_esc(evidence.get('do_not_claim_manifold', True))}</td></tr></table>"
    )


def _surrogate_gate_table(surrogate: dict[str, Any]) -> str:
    return (
        "<table><tr><th>real_provider_trace</th><th>surrogate_only</th><th>real_provider_longform_required</th><th>do_not_claim_real_manifold</th><th>reason</th></tr>"
        f"<tr><td>{_esc(surrogate.get('real_provider_trace', False))}</td>"
        f"<td>{_esc(surrogate.get('surrogate_only', True))}</td>"
        f"<td>{_esc(surrogate.get('real_provider_longform_required', True))}</td>"
        f"<td>{_esc(surrogate.get('do_not_claim_real_manifold', True))}</td>"
        f"<td>{_esc(surrogate.get('reason', ''))}</td></tr></table>"
    )


def _longform_svg(report: dict[str, Any]) -> str:
    runs = [dict(run) for run in list(report.get("generated_runs", []) or []) if isinstance(run, dict)]
    width = 860
    height = 300
    left = 70
    top = 36
    plot_w = 720
    plot_h = 200
    scores = [float(run.get("overall_score", 0.0) or 0.0) for run in runs]
    max_score = max(scores, default=1.0) or 1.0
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Stage58 Longform Geometry Lab Summary">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#fbfbf8" stroke="#d7dddc"/>')
    if runs:
        bar_w = plot_w / len(runs) * 0.62
        for index, run in enumerate(runs):
            score = float(run.get("overall_score", 0.0) or 0.0)
            bar_h = plot_h * score / max_score
            x = left + (index + 0.18) * (plot_w / len(runs))
            y = top + plot_h - bar_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#2f7d68" stroke="#172026" stroke-width="1"/>')
            label = str(run.get("perturbation_type", ""))
            parts.append(f'<text x="{x:.1f}" y="{top + plot_h + 18}" font-size="10" fill="#182026" transform="rotate(20 {x:.1f},{top + plot_h + 18})">{_esc(label)}</text>')
            parts.append(f'<text x="{x:.1f}" y="{y - 6:.1f}" font-size="10" fill="#182026">{score:.2f}</text>')
    parts.append('<text x="70" y="22" font-size="12" fill="#5f6c72">surrogate perturbation scores</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _write_longform_lab_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    runs = [dict(run) for run in list(report.get("generated_runs", []) or []) if isinstance(run, dict)]
    calibration = dict(report.get("stage57_calibration", {})) if isinstance(report.get("stage57_calibration", {}), dict) else {}
    perturbation = dict(calibration.get("perturbation_response", {})) if isinstance(calibration.get("perturbation_response", {}), dict) else {}
    responses = [dict(item) for item in list(perturbation.get("responses", []) or []) if isinstance(item, dict)]
    fig, axes = pyplot.subplots(1, 2, figsize=(14, 7), dpi=150)
    labels = [str(run.get("perturbation_type", "")) for run in runs]
    scores = numpy.array([float(run.get("overall_score", 0.0) or 0.0) for run in runs], dtype=float)
    if len(scores):
        axes[0].bar(numpy.arange(len(scores)), scores, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
        axes[0].set_xticks(numpy.arange(len(scores)))
        axes[0].set_xticklabels(labels, rotation=35, ha="right")
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_title("Surrogate Perturbation Scores")
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)
    if responses:
        x_values = numpy.array([float(item.get("centroid_distance_from_baseline", 0.0) or 0.0) for item in responses], dtype=float)
        y_values = numpy.array([-float(item.get("score_delta_from_baseline", 0.0) or 0.0) for item in responses], dtype=float)
        axes[1].scatter(x_values, y_values, s=90, c="#b88424", edgecolors="#172026", linewidths=0.8)
        for index, item in enumerate(responses):
            axes[1].annotate(str(item.get("perturbation_type", "")), (x_values[index], y_values[index]), xytext=(6, 4), textcoords="offset points", fontsize=8)
    axes[1].set_xlabel("centroid distance from baseline")
    axes[1].set_ylabel("score drop from baseline")
    axes[1].set_title("Stage57 Calibration Over Surrogate Long Traces")
    axes[1].grid(True, color="#d7dddc", linewidth=0.7, alpha=0.75)
    gate = dict(report.get("surrogate_evidence_gate", {})) if isinstance(report.get("surrogate_evidence_gate", {}), dict) else {}
    trace_set = dict(report.get("longform_trace_set", {})) if isinstance(report.get("longform_trace_set", {}), dict) else {}
    fig.suptitle(
        "Stage58 Long-Form Geometry Lab | "
        f"traces={trace_set.get('generated_trace_count', 0)} | "
        f"turns={trace_set.get('turns_per_trace', 0)} | "
        f"real_claim_blocked={gate.get('do_not_claim_real_manifold', True)}",
        fontsize=13,
        y=0.99,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _compact_report_for_html(report: dict[str, Any]) -> dict[str, Any]:
    calibration = dict(report.get("stage57_calibration", {})) if isinstance(report.get("stage57_calibration", {}), dict) else {}
    return {
        "stage": report.get("stage", ""),
        "longform_trace_set": report.get("longform_trace_set", {}),
        "generated_runs": report.get("generated_runs", []),
        "stage57_calibration": {
            "trace_set": calibration.get("trace_set", {}),
            "trace_depth": calibration.get("trace_depth", {}),
            "predictive_probe": calibration.get("predictive_probe", {}),
            "evidence_gate": calibration.get("evidence_gate", {}),
        },
        "surrogate_evidence_gate": report.get("surrogate_evidence_gate", {}),
        "tool_readiness": report.get("tool_readiness", {}),
        "boundary": report.get("boundary", {}),
    }


def _fallback_seed_run() -> dict[str, Any]:
    turns = []
    for index in range(7):
        wave = abs((index % 7) - 3) / 3
        turns.append(
            {
                "turn_id": f"fallback_{index + 1}",
                "latency_ms": int(4500 + wave * 1800),
                "processor_usage": {
                    "prompt_tokens": int(1700 + wave * 700),
                    "completion_tokens": int(24 + (index % 3) * 4),
                    "total_tokens": int(1724 + wave * 700 + (index % 3) * 4),
                    "prompt_cache_hit_tokens": int(160 + (1.0 - wave) * 220),
                    "prompt_cache_miss_tokens": int(1450 + wave * 760),
                },
                "processor_debug": {
                    "prompt_partition": {
                        "provider_cache_prefix_tokens": int(640 + index * 20),
                        "provider_cache_dynamic_tokens": int(1200 + wave * 620),
                    },
                    "bionic_memory_schedule": {
                        "salience_score": max(0.05, min(1.0, 0.3 + (1.0 - wave) * 0.52)),
                        "recall_budget": max(1, int(1 + (1.0 - wave) * 4)),
                        "dynamic_context_line_count": max(4, int(6 + (1.0 - wave) * 8)),
                        "dynamic_fusion_saved_line_count": max(2, int(4 + (1.0 - wave) * 5)),
                    },
                    "bionic_memory_lifecycle": {
                        "consolidation_priority": max(0.05, min(1.0, 0.22 + (1.0 - wave) * 0.6))
                    },
                    "bionic_consciousness_flow": {
                        "dominant_phase": "memory_reactivation",
                        "phase_count": 6,
                        "user_visible": False,
                    },
                },
            }
        )
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": "stage58-fallback-seed",
        "turns": turns,
        "scorecard": {"overall_score": 0.96, "passed": True},
    }


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value or 0.0)))


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
        import numpy
    except ImportError as exc:
        raise RuntimeError("Stage58 long-form geometry lab PNG export requires matplotlib and numpy") from exc
    return matplotlib, pyplot, numpy


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
