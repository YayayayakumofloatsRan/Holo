from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .biomimetic_causal_ablation import (
    _condition_report,
    _copy_observation,
    _is_false_fact_scenario,
    _observations_from_runs,
)
from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    _as_dict,
    _compact_for_html,
    _esc,
    _gate_table,
    _load_plotting_stack,
    _metric,
    _num,
    _plot_label,
)


STAGE82_NAME = "stage82-biomimetic-gain-control"

STAGE82_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "gain_control_observatory_only": True,
    "source_trace_only": True,
    "runtime_mutation_allowed": False,
}


def load_biomimetic_gain_control_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_gain_control(
    theory_report: dict[str, Any],
    precision_control_report: dict[str, Any],
    trace_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    theory = dict(theory_report or {})
    precision = dict(precision_control_report or {})
    traces = [dict(item) for item in list(trace_reports or []) if isinstance(item, dict)]
    cell_reports = [_cell_gain_report(item, index) for index, item in enumerate(traces)]
    control_results = [_gain_clamp_control(theory, cell_reports)]
    summary = _control_summary(theory, precision, cell_reports, control_results)
    invalidators = _invalidators(theory, precision, traces, cell_reports, control_results, summary)
    decision = _hypothesis_decision(summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE82_NAME,
        "source_stage": str(theory.get("stage", "")),
        "source_precision_stage": str(precision.get("stage", "")),
        "source_theory_summary": _as_dict(theory.get("theory_summary", {})),
        "source_precision_summary": _as_dict(precision.get("control_summary", {})),
        "control_results": control_results,
        "control_summary": summary,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(control_results, summary),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not bool(summary.get("all_trace_reports_real_provider", False)),
            "real_provider_trace": bool(summary.get("all_trace_reports_real_provider", False)),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "theory_language_bounded": True,
            "direct_controls_incomplete": False,
            "reason": "stage82_gain_clamp_control_without_runtime_authority",
        },
        "boundary": dict(STAGE82_BOUNDARY),
    }


def write_biomimetic_gain_control_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_gain_control_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_gain_control.png")
    _write_gain_control_png(report, png_path)
    return {"html": html_path, "json": json_path, "gain_control_png": png_path}


def render_biomimetic_gain_control_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("control_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage82 Biomimetic Gain Control</title>
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
    <h1>Stage82 Biomimetic Gain Control</h1>
    <p class="note">Direct neuromodulatory gain-clamp control over real-provider traces. It clamps adaptive gain variables while preserving salience, priority, replay phase, and prompt cost.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Executed Controls", summary.get("executed_control_count", 0))}
      {_metric("Pending Controls", summary.get("pending_control_count", 0))}
      {_metric("Replay Intact", summary.get("active_replay_correction_intact", False))}
      {_metric("Gain Coupling Delta", summary.get("mean_gain_clamp_neuromodulator_coupling_delta", 0))}
      {_metric("Correction Delta", summary.get("mean_gain_clamp_correction_survival_delta", 0))}
    </section>
    <section>
      <h2>Control Results</h2>
      {_control_table(payload)}
    </section>
    <section>
      <h2>Cell Evidence</h2>
      {_cell_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">direct_controls_incomplete={_esc(evidence.get("direct_controls_incomplete", False))}</p>
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


def _cell_gain_report(trace: dict[str, Any], index: int) -> dict[str, Any]:
    runs = [
        dict(run)
        for run in list(trace.get("stage46_compatible_runs", []) or [])
        if isinstance(run, dict)
    ]
    observations = _observations_from_runs(runs)
    clamped = [_clamp_neuromodulatory_gain(item) for item in observations]
    telemetry = _as_dict(trace.get("internal_telemetry", {}))
    baseline = _condition_report(
        "baseline_observed",
        observations,
        runs=runs,
        telemetry=telemetry,
        intervention="observed real-provider trace with adaptive neuromodulator gain intact",
    )
    gain_clamped = _condition_report(
        "neuromodulatory_gain_clamped",
        clamped,
        runs=runs,
        telemetry=telemetry,
        intervention=(
            "dopamine, norepinephrine, acetylcholine, and serotonin clamped to neutral gain "
            "while salience, consolidation priority, replay phase, and recall budget stay matched"
        ),
    )
    baseline_metrics = _as_dict(baseline.get("metrics", {}))
    clamped_metrics = _as_dict(gain_clamped.get("metrics", {}))
    baseline_coupling = _neuromodulator_coupling_score(baseline)
    clamped_coupling = _neuromodulator_coupling_score(gain_clamped)
    correction_delta = _num(clamped_metrics.get("correction_survival_proxy"), 0.0) - _num(
        baseline_metrics.get("correction_survival_proxy"),
        0.0,
    )
    cost_delta = _num(clamped_metrics.get("prompt_cost_proxy"), 0.0) - _num(
        baseline_metrics.get("prompt_cost_proxy"),
        0.0,
    )
    coupling_delta = clamped_coupling - baseline_coupling
    boundary_delta = _num(gain_clamped.get("invalidator_count"), 0.0) - _num(
        baseline.get("invalidator_count"),
        0.0,
    )
    baseline_phase = _reactivation_fraction(observations)
    clamped_phase = _reactivation_fraction(clamped)
    phase_delta = clamped_phase - baseline_phase
    delayed_count = sum(
        1
        for item in observations
        if _is_false_fact_scenario(item) and int(item.get("turn_index_in_run", 0) or 0) >= 3
    )
    clamped_correction = _num(clamped_metrics.get("correction_survival_proxy"), 0.0)
    pass_control = (
        _num(baseline_metrics.get("correction_survival_proxy"), 0.0) >= 0.65
        and clamped_correction >= 0.65
        and coupling_delta <= -0.2
        and correction_delta <= -0.03
        and abs(cost_delta) <= 0.01
        and abs(phase_delta) <= 0.000001
        and boundary_delta == 0.0
        and delayed_count > 0
    )
    return {
        "cell_label": _cell_label(trace, index),
        "source_stage": str(trace.get("stage", "")),
        "real_provider_trace": _report_real_provider_trace(trace),
        "baseline_condition": baseline,
        "gain_clamped_condition": gain_clamped,
        "baseline_neuromodulator_coupling": round(baseline_coupling, 6),
        "gain_clamp_neuromodulator_coupling": round(clamped_coupling, 6),
        "gain_clamp_neuromodulator_coupling_delta": round(coupling_delta, 6),
        "baseline_correction_survival_proxy": round(
            _num(baseline_metrics.get("correction_survival_proxy"), 0.0),
            6,
        ),
        "gain_clamp_correction_survival_proxy": round(clamped_correction, 6),
        "gain_clamp_correction_survival_delta": round(correction_delta, 6),
        "gain_clamp_prompt_cost_delta": round(cost_delta, 6),
        "reactivation_phase_delta": round(phase_delta, 6),
        "boundary_violation_delta": round(boundary_delta, 6),
        "delayed_false_fact_probe_count": delayed_count,
        "phase_preserved": abs(phase_delta) <= 0.000001,
        "active_replay_supported": _num(baseline_metrics.get("correction_survival_proxy"), 0.0) >= 0.65,
        "gain_clamp_replay_correction_intact": clamped_correction >= 0.65,
        "passes": pass_control,
    }


def _clamp_neuromodulatory_gain(observation: dict[str, Any]) -> dict[str, Any]:
    item = _copy_observation(observation)
    neuromodulators = _as_dict(item.get("neuromodulators", {}))
    for key in ("dopamine", "norepinephrine", "acetylcholine", "serotonin"):
        neuromodulators[key] = 0.5
    item["neuromodulators"] = neuromodulators
    item["counterfactual_marker"] = "neuromodulatory_gain_clamp"
    return item


def _gain_clamp_control(theory: dict[str, Any], cell_reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "cell_label": str(item.get("cell_label", "")),
            "baseline_neuromodulator_coupling": item.get("baseline_neuromodulator_coupling", 0),
            "gain_clamp_neuromodulator_coupling": item.get("gain_clamp_neuromodulator_coupling", 0),
            "gain_clamp_neuromodulator_coupling_delta": item.get(
                "gain_clamp_neuromodulator_coupling_delta",
                0,
            ),
            "baseline_correction_survival_proxy": item.get("baseline_correction_survival_proxy", 0),
            "gain_clamp_correction_survival_proxy": item.get(
                "gain_clamp_correction_survival_proxy",
                0,
            ),
            "gain_clamp_correction_survival_delta": item.get("gain_clamp_correction_survival_delta", 0),
            "gain_clamp_prompt_cost_delta": item.get("gain_clamp_prompt_cost_delta", 0),
            "reactivation_phase_delta": item.get("reactivation_phase_delta", 0),
            "boundary_violation_delta": item.get("boundary_violation_delta", 0),
            "delayed_false_fact_probe_count": item.get("delayed_false_fact_probe_count", 0),
            "phase_preserved": bool(item.get("phase_preserved", False)),
            "gain_clamp_replay_correction_intact": bool(
                item.get("gain_clamp_replay_correction_intact", False)
            ),
            "passes": bool(item.get("passes", False)),
        }
        for item in cell_reports
    ]
    executed = len(rows) > 0
    pass_count = sum(1 for item in rows if bool(item.get("passes", False)))
    if executed and pass_count == len(rows):
        status = "supported_direct_control"
        interpretation = (
            "Neutral gain clamp lowers adaptive neuromodulator coupling while preserving replay phase, "
            "prompt cost, and above-threshold correction survival."
        )
    elif executed and pass_count > 0:
        status = "mixed_direct_control"
        interpretation = "Gain-clamp effect is present but does not replicate across all supplied cells."
    elif executed:
        status = "not_supported_direct_control"
        interpretation = "Gain clamp did not isolate neuromodulatory adaptive coupling under matched criteria."
    else:
        status = "planned_direct_control_pending"
        interpretation = "No real-provider traces were supplied for neuromodulatory gain-clamp evaluation."
    return {
        "control_id": "neuromodulatory_gain_clamp",
        "target_theory": "neuromodulatory_gain",
        "executed": executed,
        "status": status,
        "cell_count": len(rows),
        "passing_cell_count": pass_count,
        "evidence": rows,
        "planned_controls": _theory_controls(theory, "neuromodulatory_gain"),
        "interpretation": interpretation,
        "bounded_language": "paired gain-clamp control over real-provider traces, not biological neuromodulation proof",
    }


def _control_summary(
    theory: dict[str, Any],
    precision: dict[str, Any],
    cell_reports: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    executed = [item for item in controls if bool(item.get("executed", False))]
    pending = [item for item in controls if not bool(item.get("executed", False))]
    gain = controls[0] if controls else {}
    coupling_deltas = [
        _num(item.get("gain_clamp_neuromodulator_coupling_delta"), 0.0)
        for item in cell_reports
    ]
    correction_deltas = [
        _num(item.get("gain_clamp_correction_survival_delta"), 0.0)
        for item in cell_reports
    ]
    clamped_corrections = [
        _num(item.get("gain_clamp_correction_survival_proxy"), 0.0)
        for item in cell_reports
    ]
    cost_deltas = [
        _num(item.get("gain_clamp_prompt_cost_delta"), 0.0)
        for item in cell_reports
    ]
    phase_deltas = [
        _num(item.get("reactivation_phase_delta"), 0.0)
        for item in cell_reports
    ]
    precision_precondition = _precision_precondition_supported(precision)
    active_replay = (
        precision_precondition
        and _theory_mapped(theory, "neuromodulatory_gain")
        and all(bool(item.get("active_replay_supported", False)) for item in cell_reports)
        and all(bool(item.get("gain_clamp_replay_correction_intact", False)) for item in cell_reports)
    )
    all_real = bool(cell_reports) and all(bool(item.get("real_provider_trace", False)) for item in cell_reports)
    gain_reduces = (
        bool(gain.get("executed", False))
        and str(gain.get("status", "")) == "supported_direct_control"
    )
    phase_preserved = bool(cell_reports) and all(bool(item.get("phase_preserved", False)) for item in cell_reports)
    return {
        "control_count": len(controls),
        "executed_control_count": len(executed),
        "pending_control_count": len(pending),
        "trace_report_count": len(cell_reports),
        "all_trace_reports_real_provider": all_real,
        "precision_control_precondition_supported": precision_precondition,
        "active_replay_correction_intact": active_replay,
        "gain_clamp_reduces_neuromodulator_coupling": gain_reduces,
        "gain_clamp_preserves_replay_phase": phase_preserved,
        "gain_control_cell_count": int(gain.get("cell_count", 0) or 0),
        "gain_control_passing_cell_count": int(gain.get("passing_cell_count", 0) or 0),
        "mean_gain_clamp_neuromodulator_coupling_delta": round(_mean(coupling_deltas), 6),
        "mean_gain_clamp_correction_survival_delta": round(_mean(correction_deltas), 6),
        "mean_gain_clamp_correction_survival_proxy": round(_mean(clamped_corrections), 6),
        "mean_gain_clamp_prompt_cost_delta": round(_mean(cost_deltas), 6),
        "mean_gain_clamp_reactivation_phase_delta": round(_mean(phase_deltas), 6),
        "gain_control_direct_controls_complete": len(pending) == 0,
        "direct_controls_incomplete": len(pending) > 0,
        "theory_language_bounded": bool(
            _as_dict(theory.get("evidence_gate", {})).get("theory_language_bounded", False)
        ),
        "bounded_publication_scope": (
            "neuromodulatory gain-clamp control with replay/correction controls preserved"
        ),
    }


def _invalidators(
    theory: dict[str, Any],
    precision: dict[str, Any],
    traces: list[dict[str, Any]],
    cell_reports: list[dict[str, Any]],
    controls: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if str(theory.get("stage", "")) != "stage78-biomimetic-theory-correspondence":
        invalidators.append({"key": "source_not_stage78_theory_correspondence", "severity": "p0"})
    if str(precision.get("stage", "")) != "stage81-biomimetic-neutral-salience-control":
        invalidators.append({"key": "source_not_stage81_precision_control", "severity": "p0"})
    if not bool(summary.get("precision_control_precondition_supported", False)):
        invalidators.append({"key": "stage81_precision_control_precondition_not_supported", "severity": "p0"})
    gate = _as_dict(theory.get("evidence_gate", {}))
    if not bool(gate.get("do_not_claim_real_consciousness", False)):
        invalidators.append({"key": "source_consciousness_claim_not_blocked", "severity": "p0"})
    if not bool(gate.get("theory_language_bounded", False)):
        invalidators.append({"key": "source_theory_language_unbounded", "severity": "p0"})
    if not _theory_mapped(theory, "neuromodulatory_gain"):
        invalidators.append({"key": "neuromodulatory_gain_theory_not_mapped_for_control", "severity": "p0"})
    if not traces:
        invalidators.append({"key": "missing_stage59_or_stage60_trace", "severity": "p0"})
    for index, trace in enumerate(traces):
        if not _report_real_provider_trace(trace):
            invalidators.append(
                {
                    "key": "gain_control_requires_real_provider_trace",
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
                invalidators.append(
                    {"key": f"trace_source_{key}", "severity": "p0", "cell": _cell_label(trace, index)}
                )
    for cell in cell_reports:
        if _num(cell.get("boundary_violation_delta"), 0.0) != 0.0:
            invalidators.append(
                {
                    "key": "gain_control_boundary_delta_nonzero",
                    "severity": "p0",
                    "cell": str(cell.get("cell_label", "")),
                }
            )
        if not bool(cell.get("gain_clamp_replay_correction_intact", False)):
            invalidators.append(
                {
                    "key": "gain_control_destroyed_replay_correction",
                    "severity": "p0",
                    "cell": str(cell.get("cell_label", "")),
                }
            )
    if not any(bool(item.get("executed", False)) for item in controls):
        invalidators.append({"key": "no_gain_control_executed", "severity": "p0"})
    return invalidators


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
    elif (
        bool(summary.get("active_replay_correction_intact", False))
        and bool(summary.get("gain_clamp_reduces_neuromodulator_coupling", False))
        and bool(summary.get("theory_language_bounded", False))
    ):
        decision = "gain_clamp_supports_neuromodulatory_adaptive_gain_control"
        scope = "bounded_neuromodulatory_gain_control"
    else:
        decision = "gain_control_needs_provider_followup"
        scope = "insufficient_gain_control"
    return {
        "target": "neuromodulatory_adaptive_gain_clamp",
        "decision": decision,
        "supported_scope": scope,
        "next_experiment": (
            "package Stage79-82 direct controls into publication figures and run an independent "
            "replication summary before stronger claims"
        ),
        "rationale": (
            f"executed={summary.get('executed_control_count', 0)} "
            f"pending={summary.get('pending_control_count', 0)} "
            f"precision_precondition={summary.get('precision_control_precondition_supported', False)} "
            f"gain_delta={summary.get('mean_gain_clamp_neuromodulator_coupling_delta', 0)} "
            f"correction_after={summary.get('mean_gain_clamp_correction_survival_proxy', 0)}"
        ),
    }


def _publication_claims(
    controls: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    gain = controls[0] if controls else {}
    return [
        {
            "claim": "Neuromodulatory adaptive-gain mapping survives a direct gain-clamp control",
            "status": str(gain.get("status", "not_run")),
            "allowed_language": "adaptive-gain coupling proxy over real-provider traces, not biological neuromodulation",
        },
        {
            "claim": "Replay/correction remains intact during the gain clamp",
            "status": "supported" if bool(summary.get("active_replay_correction_intact", False)) else "not_supported",
            "allowed_language": "bounded correction-survival proxy remains above threshold",
        },
        {
            "claim": "The Stage78 falsification-control matrix has completed its planned direct controls",
            "status": "supported" if bool(summary.get("gain_control_direct_controls_complete", False)) else "incomplete",
            "allowed_language": "bounded preprint-ready mechanism-control package, not evidence of subjective consciousness",
        },
    ]


def _precision_precondition_supported(precision: dict[str, Any]) -> bool:
    decision = _as_dict(precision.get("hypothesis_decision", {}))
    summary = _as_dict(precision.get("control_summary", {}))
    evidence = _as_dict(precision.get("evidence_gate", {}))
    return (
        bool(precision.get("ok", False))
        and str(precision.get("stage", "")) == "stage81-biomimetic-neutral-salience-control"
        and str(decision.get("decision", "")) == "neutral_salience_supports_predictive_precision_control"
        and bool(summary.get("marker_control_precondition_supported", False))
        and bool(summary.get("active_replay_correction_intact", False))
        and bool(summary.get("neutral_salience_reduces_correction_survival", False))
        and bool(evidence.get("real_provider_trace", False))
        and bool(evidence.get("do_not_claim_real_consciousness", False))
    )


def _report_real_provider_trace(report: dict[str, Any]) -> bool:
    gates = (
        _as_dict(report.get("evidence_gate", {})),
        _as_dict(report.get("provider_evidence_gate", {})),
        _as_dict(report.get("provider_trace_set", {})),
    )
    return any(bool(item.get("real_provider_trace", False)) for item in gates)


def _theory_mapped(theory: dict[str, Any], theory_id: str) -> bool:
    for item in list(theory.get("theory_correspondence_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("theory_id", "")) == theory_id:
            return str(item.get("support_status", "")) in {
                "mapped_needs_targeted_control",
                "supported_real_provider",
            }
    return False


def _theory_controls(theory: dict[str, Any], theory_id: str) -> list[str]:
    for item in list(theory.get("theory_correspondence_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("theory_id", "")) == theory_id:
            return [str(control) for control in list(item.get("disconfirming_controls", []) or [])]
    return []


def _neuromodulator_coupling_score(condition: dict[str, Any]) -> float:
    scorecard = _as_dict(condition.get("scorecard", {}))
    dimensions = _as_dict(scorecard.get("dimension_index", {}))
    coupling = _as_dict(dimensions.get("neuromodulator_coupling", {}))
    return _num(coupling.get("score"), 0.0)


def _reactivation_fraction(observations: list[dict[str, Any]]) -> float:
    delayed = [
        item
        for item in observations
        if _is_false_fact_scenario(item)
        and int(item.get("turn_index_in_run", 0) or 0) >= 3
    ]
    if not delayed:
        return 0.0
    return sum(1 for item in delayed if str(item.get("phase", "")) == "memory_reactivation") / len(delayed)


def _cell_label(report: dict[str, Any], index: int) -> str:
    for key in ("cell_label", "model", "model_label", "source_model"):
        value = str(report.get(key, "") or "")
        if value:
            return value
    return f"cell_{index + 1}"


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def _write_gain_control_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    gain = next(
        (
            dict(item)
            for item in list(report.get("control_results", []) or [])
            if isinstance(item, dict) and str(item.get("control_id", "")) == "neuromodulatory_gain_clamp"
        ),
        {},
    )
    evidence = [dict(item) for item in list(gain.get("evidence", []) or []) if isinstance(item, dict)]
    labels = [_plot_label(str(item.get("cell_label", ""))) for item in evidence]
    baseline = numpy.array([_num(item.get("baseline_neuromodulator_coupling"), 0.0) for item in evidence])
    clamped = numpy.array([_num(item.get("gain_clamp_neuromodulator_coupling"), 0.0) for item in evidence])
    correction = numpy.array([_num(item.get("gain_clamp_correction_survival_proxy"), 0.0) for item in evidence])
    x = numpy.arange(len(labels))

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    if len(labels):
        axes[0].bar(x - 0.17, baseline, width=0.34, color="#2f7d68", label="baseline coupling")
        axes[0].bar(x + 0.17, clamped, width=0.34, color="#8a6f2a", label="gain clamped")
    axes[0].set_title("Neuromodulator Coupling")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    if len(labels):
        axes[1].bar(x, correction, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[1].axhline(0.65, color="#9b4d3a", linewidth=0.9, linestyle="--")
    axes[1].set_title("Correction Survival After Gain Clamp")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage82 Biomimetic Gain Control | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.24, top=0.82, wspace=0.26)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _control_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>control</th><th>target</th><th>status</th><th>cells</th><th>interpretation</th><th>bounded language</th></tr>"
    ]
    for item in list(report.get("control_results", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('control_id', ''))}</td>"
            f"<td>{_esc(item.get('target_theory', ''))}</td>"
            f"<td>{_esc(item.get('status', ''))}</td>"
            f"<td>{_esc(item.get('passing_cell_count', 0))}/{_esc(item.get('cell_count', 0))}</td>"
            f"<td>{_esc(item.get('interpretation', ''))}</td>"
            f"<td>{_esc(item.get('bounded_language', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _cell_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>cell</th><th>baseline gain coupling</th><th>gain clamped</th><th>coupling delta</th><th>correction after clamp</th><th>correction delta</th><th>cost delta</th><th>phase delta</th><th>boundary delta</th></tr>"
    ]
    gain = next(
        (
            dict(item)
            for item in list(report.get("control_results", []) or [])
            if isinstance(item, dict) and str(item.get("control_id", "")) == "neuromodulatory_gain_clamp"
        ),
        {},
    )
    for item in list(gain.get("evidence", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('cell_label', ''))}</td>"
            f"<td>{_esc(item.get('baseline_neuromodulator_coupling', 0))}</td>"
            f"<td>{_esc(item.get('gain_clamp_neuromodulator_coupling', 0))}</td>"
            f"<td>{_esc(item.get('gain_clamp_neuromodulator_coupling_delta', 0))}</td>"
            f"<td>{_esc(item.get('gain_clamp_correction_survival_proxy', 0))}</td>"
            f"<td>{_esc(item.get('gain_clamp_correction_survival_delta', 0))}</td>"
            f"<td>{_esc(item.get('gain_clamp_prompt_cost_delta', 0))}</td>"
            f"<td>{_esc(item.get('reactivation_phase_delta', 0))}</td>"
            f"<td>{_esc(item.get('boundary_violation_delta', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)
