from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .bionic_simulation_lab import STAGE61_NAME


STAGE68_NAME = "stage68-bionic-memory-robustness"

MEMORY_ROBUSTNESS_BOUNDARY = {
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

MEMORY_PRESSURE_TYPES = {
    "memory_drop",
    "false_fact_correction",
    "cache_cold_context",
    "visual_commitment_boundary",
}


def load_bionic_simulation_lab_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_bionic_memory_robustness_observatory(
    lab: dict[str, Any],
) -> dict[str, Any]:
    source = dict(lab or {})
    runs = [
        dict(run)
        for run in list(source.get("stage46_compatible_runs", []) or [])
        if isinstance(run, dict)
    ]
    observations = [_scenario_observation(run) for run in runs]
    all_turns = [
        turn
        for run in runs
        for turn in list(run.get("turns", []) or [])
        if isinstance(turn, dict)
    ]
    telemetry = _as_dict(source.get("internal_telemetry", {}))
    scorecard = _memory_scorecard(
        observations=observations,
        turns=all_turns,
        telemetry=telemetry,
    )
    priority = _priority_extraction(observations)
    self_growth = _self_growth_summary(observations, all_turns)
    failures = _robustness_failures(scorecard, observations, self_growth)
    return {
        "ok": True,
        "stage": STAGE68_NAME,
        "source_stage": str(source.get("stage", "") or STAGE61_NAME),
        "memory_scorecard": scorecard,
        "memory_pressure_observations": observations,
        "priority_extraction": priority,
        "self_growth": self_growth,
        "robustness_failures": failures,
        "intervention_plan": _intervention_plan(failures),
        "evidence_gate": {
            "surrogate_only": True,
            "real_provider_trace": False,
            "do_not_claim_real_manifold": True,
            "do_not_claim_self_growth_persistence": True,
            "reason": "stage68_scores_memory_mechanisms_from_stage61_surrogate_traces_only",
        },
        "boundary": dict(MEMORY_ROBUSTNESS_BOUNDARY),
    }


def write_bionic_memory_robustness_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_bionic_memory_robustness_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_memory_robustness.png")
    _write_memory_robustness_png(report, png_path)
    return {"html": html_path, "json": json_path, "memory_png": png_path}


def render_bionic_memory_robustness_html(report: dict[str, Any]) -> str:
    safe = dict(report or {})
    scorecard = _as_dict(safe.get("memory_scorecard", {}))
    priority = _as_dict(safe.get("priority_extraction", {}))
    self_growth = _as_dict(safe.get("self_growth", {}))
    gate = _as_dict(safe.get("evidence_gate", {}))
    serialized = html.escape(
        json.dumps(_compact_for_html(safe), ensure_ascii=False, indent=2)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage68 Memory Robustness</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid #d7dddc; background: #f7f8f5; border-radius: 6px; padding: 10px 12px; }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d7dddc; margin: 10px 0; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid #d7dddc; text-align: left; font-size: 12px; vertical-align: top; }}
    pre {{ overflow: auto; background: #172026; color: #e8f0ec; padding: 14px; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .warn {{ color: #8a4f00; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>Stage68 Memory Robustness</h1>
    <p class="note">Focused memory, self-growth, sedimentation, and priority-extraction observatory over Stage61 surrogate dialogue telemetry.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Aggregate", scorecard.get("aggregate_score", 0))}
      {_metric("Turns", scorecard.get("turn_count", 0))}
      {_metric("Scenarios", scorecard.get("scenario_count", 0))}
      {_metric("Priority Corr", priority.get("pressure_priority_correlation", 0))}
      {_metric("Avg Consolidation", self_growth.get("average_consolidation_priority", 0))}
      {_metric("Self-Write Violations", self_growth.get("self_memory_write_violation_count", 0))}
    </section>
    <section>
      <h2>Memory Scorecard</h2>
      {_dimension_table(scorecard)}
    </section>
    <section>
      <h2>Priority Extraction</h2>
      {_priority_table(priority)}
    </section>
    <section>
      <h2>Scenario Observations</h2>
      {_observation_table(safe)}
    </section>
    <section>
      <h2>Intervention Plan</h2>
      {_intervention_table(safe)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">do_not_claim_real_manifold={_esc(gate.get("do_not_claim_real_manifold", True))}</p>
      {_gate_table(gate)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _scenario_observation(run: dict[str, Any]) -> dict[str, Any]:
    turns = [
        dict(turn)
        for turn in list(run.get("turns", []) or [])
        if isinstance(turn, dict)
    ]
    perturbation = _as_dict(run.get("perturbation", {}))
    scenario_type = str(perturbation.get("type", "") or "")
    scorecard = _as_dict(run.get("scorecard", {}))
    schedules = [_as_dict(_as_dict(turn.get("processor_debug", {})).get("bionic_memory_schedule", {})) for turn in turns]
    lifecycles = [_as_dict(_as_dict(turn.get("processor_debug", {})).get("bionic_memory_lifecycle", {})) for turn in turns]
    flows = [_as_dict(_as_dict(turn.get("processor_debug", {})).get("bionic_consciousness_flow", {})) for turn in turns]
    guards = [_as_dict(turn.get("grounding_guard", {})) for turn in turns]
    usages = [_as_dict(turn.get("processor_usage", {})) for turn in turns]
    turn_count = len(turns)
    recall_values = [_num(item.get("recall_budget"), 0.0) for item in schedules]
    salience_values = [_num(item.get("salience_score"), 0.0) for item in schedules]
    priority_values = [_num(item.get("consolidation_priority"), 0.0) for item in lifecycles]
    reactivation_count = sum(
        1
        for item in flows
        if str(item.get("dominant_phase", "") or "") == "memory_reactivation"
    )
    self_write_count = sum(1 for item in lifecycles if bool(item.get("self_memory_write", False)))
    visual_failures = sum(1 for item in guards if not bool(item.get("visual_overclaim_rewritten", True)))
    commitment_failures = sum(1 for item in guards if bool(item.get("prospective_commitment_failed", False)))
    hit_tokens = sum(int(item.get("prompt_cache_hit_tokens", 0) or 0) for item in usages)
    miss_tokens = sum(int(item.get("prompt_cache_miss_tokens", 0) or 0) for item in usages)
    recall_floor_failures = sum(1 for value in recall_values if value < 4.0)
    high_priority_count = sum(1 for value in priority_values if value >= 0.68)
    pressure_weight = _pressure_weight(scenario_type)
    return {
        "run_id": str(run.get("run_id", "") or ""),
        "scenario_type": scenario_type,
        "primary_pressure": str(perturbation.get("primary_pressure", "") or ""),
        "turn_count": turn_count,
        "overall_score": round(_num(scorecard.get("overall_score"), 0.0), 6),
        "memory_pressure": scenario_type in MEMORY_PRESSURE_TYPES,
        "pressure_weight": pressure_weight,
        "average_recall_budget": round(_mean(recall_values), 6),
        "recall_floor_failure_ratio": round(recall_floor_failures / max(1, turn_count), 6),
        "average_salience_score": round(_mean(salience_values), 6),
        "average_consolidation_priority": round(_mean(priority_values), 6),
        "high_priority_turn_ratio": round(high_priority_count / max(1, turn_count), 6),
        "memory_reactivation_ratio": round(reactivation_count / max(1, turn_count), 6),
        "self_memory_write_violation_count": self_write_count,
        "visual_rewrite_failure_count": visual_failures,
        "commitment_failure_count": commitment_failures,
        "prompt_cache_hit_ratio": round(hit_tokens / max(1, hit_tokens + miss_tokens), 6),
    }


def _memory_scorecard(
    *,
    observations: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    pressure = [item for item in observations if bool(item.get("memory_pressure", False))]
    source = pressure or observations
    avg_recall = _mean([_num(item.get("average_recall_budget"), 0.0) for item in source])
    avg_salience = _mean([_num(item.get("average_salience_score"), 0.0) for item in source])
    avg_priority = _mean([_num(item.get("average_consolidation_priority"), 0.0) for item in source])
    recall_floor_failure = _mean([_num(item.get("recall_floor_failure_ratio"), 0.0) for item in source])
    reactivation = _mean([_num(item.get("memory_reactivation_ratio"), 0.0) for item in source])
    cache_ratio = _num(telemetry.get("prompt_cache_hit_ratio"), 0.0)
    if not cache_ratio:
        cache_ratio = _mean([_num(item.get("prompt_cache_hit_ratio"), 0.0) for item in observations])
    self_writes = sum(int(item.get("self_memory_write_violation_count", 0) or 0) for item in observations)
    boundary_failures = sum(
        int(item.get("visual_rewrite_failure_count", 0) or 0)
        + int(item.get("commitment_failure_count", 0) or 0)
        for item in observations
    )
    turn_count = len(turns)
    dimensions = [
        _dimension(
            "memory_survival",
            (min(avg_recall, 6.0) / 6.0) * 0.46 + avg_salience * 0.36 + (1.0 - recall_floor_failure) * 0.18,
            "recall budget, salience, and floor survival under memory pressure",
            f"avg_recall={round(avg_recall, 4)} avg_salience={round(avg_salience, 4)} recall_floor_failure={round(recall_floor_failure, 4)}",
            0.22,
        ),
        _dimension(
            "correction_retention",
            _scenario_score(observations, "false_fact_correction") * 0.5 + reactivation * 0.2 + (1.0 - recall_floor_failure) * 0.3,
            "false-fact correction remains prioritized instead of overwritten",
            f"false_fact_score={round(_scenario_score(observations, 'false_fact_correction'), 4)} memory_reactivation={round(reactivation, 4)}",
            0.16,
        ),
        _dimension(
            "memory_sedimentation",
            avg_priority * 0.72 + _mean([_num(item.get("high_priority_turn_ratio"), 0.0) for item in source]) * 0.28,
            "consolidation priority and high-priority turn ratio",
            f"avg_consolidation_priority={round(avg_priority, 4)}",
            0.16,
        ),
        _dimension(
            "priority_extraction",
            _priority_extraction_score(observations),
            "higher pressure memories should receive higher consolidation priority",
            f"pressure_priority_correlation={_priority_correlation(observations)}",
            0.14,
        ),
        _dimension(
            "self_growth_safety",
            1.0 if self_writes == 0 else 0.0,
            "self-growth is diagnostic intent only and never writes self-memory",
            f"self_memory_write_violation_count={self_writes}",
            0.12,
        ),
        _dimension(
            "cache_context_inheritance",
            min(1.0, cache_ratio / 0.55),
            "stable context inheritance and provider-cache reuse",
            f"prompt_cache_hit_ratio={round(cache_ratio, 6)}",
            0.1,
        ),
        _dimension(
            "boundary_stability",
            1.0 - min(1.0, boundary_failures / max(1, turn_count)),
            "visual honesty and commitment binding under memory pressure",
            f"boundary_failures={boundary_failures} turn_count={turn_count}",
            0.1,
        ),
    ]
    aggregate = sum(_num(item.get("score"), 0.0) * _num(item.get("weight"), 0.0) for item in dimensions)
    return {
        "scenario_count": len(observations),
        "turn_count": turn_count,
        "aggregate_score": round(_clamp01(aggregate), 6),
        "dimensions": dimensions,
        "dimension_index": {str(item["key"]): item for item in dimensions},
    }


def _priority_extraction(observations: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        [
            {
                "scenario_type": str(item.get("scenario_type", "") or ""),
                "pressure_weight": _num(item.get("pressure_weight"), 0.0),
                "average_consolidation_priority": _num(item.get("average_consolidation_priority"), 0.0),
                "average_recall_budget": _num(item.get("average_recall_budget"), 0.0),
                "high_priority_turn_ratio": _num(item.get("high_priority_turn_ratio"), 0.0),
            }
            for item in observations
        ],
        key=lambda item: item["average_consolidation_priority"],
        reverse=True,
    )
    correlation = _priority_correlation(observations)
    return {
        "mode": "stage68_priority_extraction_v1",
        "pressure_priority_correlation": correlation,
        "top_priority_scenarios": ranked[:8],
        "score": _priority_extraction_score(observations),
    }


def _self_growth_summary(
    observations: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    priorities = [_num(item.get("average_consolidation_priority"), 0.0) for item in observations]
    high_priority_turns = sum(
        int(round(_num(item.get("high_priority_turn_ratio"), 0.0) * int(item.get("turn_count", 0) or 0)))
        for item in observations
    )
    self_writes = sum(int(item.get("self_memory_write_violation_count", 0) or 0) for item in observations)
    return {
        "mode": "stage68_diagnostic_self_growth_v1",
        "average_consolidation_priority": round(_mean(priorities), 6),
        "high_priority_turn_count": high_priority_turns,
        "high_priority_turn_ratio": round(high_priority_turns / max(1, len(turns)), 6),
        "self_memory_write_violation_count": self_writes,
        "write_policy": "diagnostic_intent_only",
        "background_loop_allowed": False,
    }


def _robustness_failures(
    scorecard: dict[str, Any],
    observations: list[dict[str, Any]],
    self_growth: dict[str, Any],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    dimension_index = _as_dict(scorecard.get("dimension_index", {}))
    for key, threshold in (
        ("memory_survival", 0.72),
        ("memory_sedimentation", 0.62),
        ("priority_extraction", 0.58),
        ("cache_context_inheritance", 0.58),
        ("boundary_stability", 0.96),
    ):
        dimension = _as_dict(dimension_index.get(key, {}))
        score = _num(dimension.get("score"), 0.0)
        if score < threshold:
            failures.append(
                {
                    "key": f"{key}_below_stage68_threshold",
                    "score": round(score, 6),
                    "threshold": threshold,
                    "evidence": str(dimension.get("evidence", "") or ""),
                }
            )
    if int(self_growth.get("self_memory_write_violation_count", 0) or 0) > 0:
        failures.append(
            {
                "key": "self_memory_write_violation",
                "score": 0.0,
                "threshold": 1.0,
                "evidence": f"self_memory_write_violation_count={self_growth.get('self_memory_write_violation_count', 0)}",
            }
        )
    pressure_floor = [
        item
        for item in observations
        if bool(item.get("memory_pressure", False))
        and _num(item.get("recall_floor_failure_ratio"), 0.0) > 0.35
    ]
    if pressure_floor:
        failures.append(
            {
                "key": "pressure_recall_floor_unstable",
                "score": round(1.0 - _mean([_num(item.get("recall_floor_failure_ratio"), 0.0) for item in pressure_floor]), 6),
                "threshold": 0.65,
                "evidence": ",".join(str(item.get("scenario_type", "") or "") for item in pressure_floor[:6]),
            }
        )
    return failures


def _intervention_plan(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    for index, failure in enumerate(failures):
        key = str(failure.get("key", "") or "")
        plan.append(
            {
                "rank": index + 1,
                "failure_key": key,
                "target": _target_for_failure(key),
                "recommendation": _recommendation_for_failure(key),
                "evidence": str(failure.get("evidence", "") or ""),
                "auto_apply": False,
            }
        )
    if not plan:
        plan.append(
            {
                "rank": 1,
                "failure_key": "no_blocking_stage68_memory_deficit",
                "target": "real-provider Stage60 validation",
                "recommendation": "Run pro-first real provider traces before promoting a memory-growth claim.",
                "evidence": "all Stage68 dimensions above thresholds",
                "auto_apply": False,
            }
        )
    return plan


def _target_for_failure(key: str) -> str:
    if "cache" in key:
        return "context scheduler / cache spine"
    if "priority" in key or "sedimentation" in key:
        return "memory lifecycle / consolidation priority"
    if "boundary" in key:
        return "grounding guard / residual channel"
    if "self_memory" in key:
        return "self-growth safety gate"
    return "bionic memory scheduler"


def _recommendation_for_failure(key: str) -> str:
    if "cache" in key:
        return "Raise stable prefix reuse while keeping volatile recall in compact dynamic frames."
    if "priority" in key:
        return "Make correction, commitment, and memory-loss pressure lift consolidation priority more sharply."
    if "sedimentation" in key:
        return "Increase diagnostic consolidation priority for corrected symbols and unresolved commitments."
    if "boundary" in key:
        return "Keep visual and commitment guards on the residual fast channel before response shaping."
    if "self_memory" in key:
        return "Block all direct self-memory writes; keep self-growth as diagnostic intent until reviewed."
    return "Raise recall floor on memory-drop and false-fact correction turns, then rerun Stage61 and Stage68."


def _write_memory_robustness_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    scorecard = _as_dict(report.get("memory_scorecard", {}))
    dimensions = [
        dict(item)
        for item in list(scorecard.get("dimensions", []) or [])
        if isinstance(item, dict)
    ]
    observations = [
        dict(item)
        for item in list(report.get("memory_pressure_observations", []) or [])[:10]
        if isinstance(item, dict)
    ]
    fig, axes = pyplot.subplots(1, 2, figsize=(15, 6.2), dpi=150)
    labels = [_plot_label(str(item.get("key", "") or "")) for item in dimensions]
    scores = numpy.array([float(item.get("score", 0.0) or 0.0) for item in dimensions], dtype=float)
    y = numpy.arange(len(labels))
    if len(labels):
        axes[0].barh(y, scores, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[0].set_xlim(0.0, 1.05)
    axes[0].set_title("Memory Robustness")
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels)
    axes[0].invert_yaxis()
    axes[0].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)

    obs_labels = [_plot_label(str(item.get("scenario_type", "") or "")) for item in observations]
    priorities = numpy.array(
        [float(item.get("average_consolidation_priority", 0.0) or 0.0) for item in observations],
        dtype=float,
    )
    x = numpy.arange(len(obs_labels))
    if len(obs_labels):
        axes[1].bar(x, priorities, color="#b88424", edgecolor="#172026", linewidth=0.8)
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_title("Consolidation Priority by Scenario")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(obs_labels, rotation=35, ha="right")
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)
    fig.suptitle(
        "Stage68 Bionic Memory Robustness | "
        f"aggregate={scorecard.get('aggregate_score', 0)} | "
        f"turns={scorecard.get('turn_count', 0)}",
        fontsize=13,
        y=0.99,
    )
    fig.subplots_adjust(left=0.2, right=0.98, bottom=0.22, top=0.86, wspace=0.35)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


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


def _priority_table(priority: dict[str, Any]) -> str:
    rows = ["<table><tr><th>scenario</th><th>pressure</th><th>priority</th><th>recall</th><th>high priority</th></tr>"]
    for item in list(priority.get("top_priority_scenarios", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('scenario_type', ''))}</td>"
            f"<td>{_esc(item.get('pressure_weight', 0))}</td>"
            f"<td>{_esc(item.get('average_consolidation_priority', 0))}</td>"
            f"<td>{_esc(item.get('average_recall_budget', 0))}</td>"
            f"<td>{_esc(item.get('high_priority_turn_ratio', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _observation_table(report: dict[str, Any]) -> str:
    rows = ["<table><tr><th>scenario</th><th>turns</th><th>recall</th><th>salience</th><th>priority</th><th>floor failures</th><th>cache hit</th></tr>"]
    for item in list(report.get("memory_pressure_observations", []) or [])[:24]:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('scenario_type', ''))}</td>"
            f"<td>{_esc(item.get('turn_count', 0))}</td>"
            f"<td>{_esc(item.get('average_recall_budget', 0))}</td>"
            f"<td>{_esc(item.get('average_salience_score', 0))}</td>"
            f"<td>{_esc(item.get('average_consolidation_priority', 0))}</td>"
            f"<td>{_esc(item.get('recall_floor_failure_ratio', 0))}</td>"
            f"<td>{_esc(item.get('prompt_cache_hit_ratio', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _intervention_table(report: dict[str, Any]) -> str:
    rows = ["<table><tr><th>rank</th><th>failure</th><th>target</th><th>recommendation</th></tr>"]
    for item in list(report.get("intervention_plan", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('rank', 0))}</td>"
            f"<td>{_esc(item.get('failure_key', ''))}</td>"
            f"<td>{_esc(item.get('target', ''))}</td>"
            f"<td>{_esc(item.get('recommendation', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _gate_table(gate: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "surrogate_only",
        "real_provider_trace",
        "do_not_claim_real_manifold",
        "do_not_claim_self_growth_persistence",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "memory_scorecard": report.get("memory_scorecard", {}),
        "priority_extraction": report.get("priority_extraction", {}),
        "self_growth": report.get("self_growth", {}),
        "robustness_failures": report.get("robustness_failures", []),
        "evidence_gate": report.get("evidence_gate", {}),
    }


def _dimension(key: str, score: float, label: str, evidence: str, weight: float) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": round(_clamp01(score), 6),
        "weight": round(float(weight), 4),
        "evidence": evidence,
    }


def _scenario_score(observations: list[dict[str, Any]], scenario_type: str) -> float:
    matches = [
        _num(item.get("overall_score"), 0.0)
        for item in observations
        if str(item.get("scenario_type", "") or "") == scenario_type
    ]
    return _mean(matches, default=0.0)


def _pressure_weight(scenario_type: str) -> float:
    return {
        "baseline_continuity": 0.15,
        "memory_drop": 0.9,
        "false_fact_correction": 1.0,
        "cache_cold_context": 0.72,
        "tool_pressure": 0.58,
        "latency_pressure": 0.52,
        "visual_commitment_boundary": 0.86,
    }.get(str(scenario_type or ""), 0.45)


def _priority_extraction_score(observations: list[dict[str, Any]]) -> float:
    correlation = _priority_correlation(observations)
    pressure = [
        item
        for item in observations
        if bool(item.get("memory_pressure", False))
    ]
    pressure_priority = _mean([
        _num(item.get("average_consolidation_priority"), 0.0)
        for item in pressure
    ])
    return _clamp01(((correlation + 1.0) / 2.0) * 0.58 + pressure_priority * 0.42)


def _priority_correlation(observations: list[dict[str, Any]]) -> float:
    xs = [_num(item.get("pressure_weight"), 0.0) for item in observations]
    ys = [_num(item.get("average_consolidation_priority"), 0.0) for item in observations]
    if len(xs) < 2:
        return 0.0
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    denom = (x_var * y_var) ** 0.5
    if denom <= 0:
        return 0.0
    return round(max(-1.0, min(1.0, numerator / denom)), 6)


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
            "Stage68 memory robustness PNG export requires matplotlib and numpy"
        ) from exc
    return matplotlib, pyplot, numpy
