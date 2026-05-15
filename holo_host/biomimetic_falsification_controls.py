from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

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


STAGE79_NAME = "stage79-biomimetic-falsification-controls"

STAGE79_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "falsification_control_observatory_only": True,
    "paired_counterfactual_source_only": True,
    "runtime_mutation_allowed": False,
}


def load_biomimetic_falsification_controls_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_falsification_controls(
    theory_report: dict[str, Any],
    causal_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    theory = dict(theory_report or {})
    causal_cells = [
        dict(item)
        for item in list(causal_reports or [])
        if isinstance(item, dict)
    ]
    control_results = _control_results(theory, causal_cells)
    summary = _control_summary(theory, causal_cells, control_results)
    invalidators = _invalidators(theory, causal_cells, control_results)
    decision = _hypothesis_decision(summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE79_NAME,
        "source_stage": str(theory.get("stage", "")),
        "source_theory_summary": _as_dict(theory.get("theory_summary", {})),
        "control_results": control_results,
        "control_summary": summary,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(control_results, summary),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not bool(summary.get("all_causal_reports_real_provider", False)),
            "real_provider_trace": bool(summary.get("all_causal_reports_real_provider", False)),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "theory_language_bounded": True,
            "direct_controls_incomplete": int(summary.get("pending_control_count", 0) or 0) > 0,
            "reason": "stage79_tests_targeted_falsification_controls_without_runtime_authority",
        },
        "boundary": dict(STAGE79_BOUNDARY),
    }


def write_biomimetic_falsification_controls_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_falsification_controls_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_falsification_controls.png")
    _write_controls_png(report, png_path)
    return {"html": html_path, "json": json_path, "control_png": png_path}


def render_biomimetic_falsification_controls_html(report: dict[str, Any]) -> str:
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
  <title>Stage79 Biomimetic Falsification Controls</title>
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
    <h1>Stage79 Biomimetic Falsification Controls</h1>
    <p class="note">Targeted control gate over Stage78 theory mapping and Stage71 real-provider paired counterfactual reports.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Executed Controls", summary.get("executed_control_count", 0))}
      {_metric("Pending Controls", summary.get("pending_control_count", 0))}
      {_metric("Replay Intact", summary.get("replay_correction_intact", False))}
      {_metric("GNW Narrowed", summary.get("gnw_flow_control_narrows_instability", False))}
      {_metric("Provider Cells", summary.get("causal_report_count", 0))}
    </section>
    <section>
      <h2>Control Results</h2>
      {_control_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">direct_controls_incomplete={_esc(evidence.get("direct_controls_incomplete", True))}</p>
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


def _control_results(theory: dict[str, Any], causal_cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _gnw_ignition_null_control(causal_cells),
        _replay_marker_control(theory, causal_cells),
        _precision_neutral_control(theory, causal_cells),
        _gain_clamp_control(theory),
    ]


def _gnw_ignition_null_control(causal_cells: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, report in enumerate(causal_cells):
        baseline_cost = _condition_metric(report, "baseline_observed", "prompt_cost_proxy")
        ablated_cost = _condition_metric(report, "global_workspace_ignition_ablation", "prompt_cost_proxy")
        baseline_correction = _condition_metric(report, "baseline_observed", "correction_survival_proxy")
        ablated_correction = _condition_metric(
            report,
            "global_workspace_ignition_ablation",
            "correction_survival_proxy",
        )
        flow_delta = _effect_estimate(report, "flow_to_reply_coupling_delta")
        if flow_delta == 0.0:
            flow_delta = (
                _condition_metric(
                    report,
                    "global_workspace_ignition_ablation",
                    "flow_to_reply_coupling_proxy",
                )
                - _condition_metric(report, "baseline_observed", "flow_to_reply_coupling_proxy")
            )
        boundary_delta = _effect_estimate(report, "boundary_violation_delta")
        prompt_cost_delta = ablated_cost - baseline_cost
        correction_delta = ablated_correction - baseline_correction
        rows.append(
            {
                "cell_label": _cell_label(report, index),
                "flow_to_reply_coupling_delta": round(flow_delta, 6),
                "ignition_null_prompt_cost_delta": round(prompt_cost_delta, 6),
                "ignition_null_correction_delta": round(correction_delta, 6),
                "boundary_violation_delta": round(boundary_delta, 6),
                "passes": (
                    flow_delta <= -0.03
                    and abs(prompt_cost_delta) <= 0.01
                    and correction_delta >= -0.005
                    and boundary_delta == 0.0
                ),
            }
        )
    executed = len(rows) > 0
    pass_count = sum(1 for item in rows if bool(item.get("passes", False)))
    if executed and pass_count == len(rows):
        status = "supported_direct_control"
        interpretation = (
            "Prompt-cost-matched ignition-null lowers flow-to-reply coupling while preserving correction proxy."
        )
    elif executed and pass_count > 0:
        status = "mixed_direct_control"
        interpretation = "Ignition-null effect is directionally present but not replicated across all cells."
    elif executed:
        status = "not_supported_direct_control"
        interpretation = "Ignition-null did not isolate flow coupling under matched control criteria."
    else:
        status = "planned_direct_control_pending"
        interpretation = "No Stage71 ignition-null paired report was supplied."
    return {
        "control_id": "gnw_prompt_cost_matched_ignition_null",
        "target_theory": "global_neuronal_workspace",
        "executed": executed,
        "status": status,
        "cell_count": len(rows),
        "passing_cell_count": pass_count,
        "evidence": rows,
        "interpretation": interpretation,
        "bounded_language": "paired counterfactual over real-provider traces, not proof of conscious access",
    }


def _replay_marker_control(
    theory: dict[str, Any],
    causal_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, report in enumerate(causal_cells):
        rows.append(
            {
                "cell_label": _cell_label(report, index),
                "hippocampal_reactivation_delta": round(
                    _effect_estimate(report, "hippocampal_reactivation_delta"),
                    6,
                ),
                "correction_survival_proxy_delta": round(
                    _effect_estimate(report, "correction_survival_proxy_delta"),
                    6,
                ),
                "boundary_violation_delta": round(
                    _effect_estimate(report, "boundary_violation_delta"),
                    6,
                ),
                "active_replay_supported": _cell_replay_intact(report),
            }
        )
    return {
        "control_id": "hippocampal_cls_marker_removal_or_shuffle",
        "target_theory": "hippocampal_indexing_cls",
        "executed": False,
        "status": "planned_direct_control_pending",
        "cell_count": len(rows),
        "passing_cell_count": sum(1 for item in rows if bool(item.get("active_replay_supported", False))),
        "evidence": rows,
        "interpretation": (
            "Stage79 preserves the positive replay/correction effect but does not count it as a "
            "marker-removal or correction-label-shuffle control."
        ),
        "planned_controls": _theory_controls(theory, "hippocampal_indexing_cls"),
        "bounded_language": "bounded replay/correction correspondence, not biological memory proof",
    }


def _precision_neutral_control(
    theory: dict[str, Any],
    causal_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, report in enumerate(causal_cells):
        rows.append(
            {
                "cell_label": _cell_label(report, index),
                "correction_survival_proxy_delta": round(
                    _effect_estimate(report, "correction_survival_proxy_delta"),
                    6,
                ),
                "prompt_cost_delta": round(_effect_estimate(report, "prompt_cost_delta"), 6),
                "active_precision_supported": (
                    _effect_estimate(report, "correction_survival_proxy_delta") >= 0.03
                    and abs(_effect_estimate(report, "prompt_cost_delta")) <= 0.08
                ),
            }
        )
    return {
        "control_id": "predictive_precision_neutral_salience",
        "target_theory": "predictive_processing_precision",
        "executed": False,
        "status": "planned_direct_control_pending",
        "cell_count": len(rows),
        "passing_cell_count": sum(1 for item in rows if bool(item.get("active_precision_supported", False))),
        "evidence": rows,
        "interpretation": (
            "Correction pressure remains cost-bounded, but a neutral salience marker has not yet "
            "been run as the direct precision control."
        ),
        "planned_controls": _theory_controls(theory, "predictive_processing_precision"),
        "bounded_language": "precision-weighted correction proxy, not neural prediction-error evidence",
    }


def _gain_clamp_control(theory: dict[str, Any]) -> dict[str, Any]:
    return {
        "control_id": "neuromodulatory_gain_clamp_or_random_gain",
        "target_theory": "neuromodulatory_gain",
        "executed": False,
        "status": "planned_direct_control_pending",
        "cell_count": 0,
        "passing_cell_count": 0,
        "evidence": [],
        "interpretation": (
            "Neuromodulatory gain remains mapped but needs a direct gain-clamp or salience-matched "
            "random-gain provider cell before support can be claimed."
        ),
        "planned_controls": _theory_controls(theory, "neuromodulatory_gain"),
        "bounded_language": "gain-mapping hypothesis only until direct control runs",
    }


def _control_summary(
    theory: dict[str, Any],
    causal_cells: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    executed = [item for item in controls if bool(item.get("executed", False))]
    pending = [item for item in controls if not bool(item.get("executed", False))]
    replay_intact = _theory_supported(theory, "hippocampal_indexing_cls") and all(
        _cell_replay_intact(item) for item in causal_cells
    )
    gnw = next(
        (
            item
            for item in controls
            if str(item.get("control_id", "")) == "gnw_prompt_cost_matched_ignition_null"
        ),
        {},
    )
    gnw_narrowed = bool(gnw.get("executed", False)) and str(gnw.get("status", "")) == "supported_direct_control"
    all_real = bool(causal_cells) and all(_report_real_provider_trace(item) for item in causal_cells)
    return {
        "control_count": len(controls),
        "executed_control_count": len(executed),
        "pending_control_count": len(pending),
        "causal_report_count": len(causal_cells),
        "all_causal_reports_real_provider": all_real,
        "replay_correction_intact": replay_intact,
        "gnw_flow_control_narrows_instability": gnw_narrowed,
        "flow_control_cell_count": int(gnw.get("cell_count", 0) or 0),
        "flow_control_passing_cell_count": int(gnw.get("passing_cell_count", 0) or 0),
        "theory_language_bounded": bool(
            _as_dict(theory.get("evidence_gate", {})).get("theory_language_bounded", False)
        ),
        "causal_language_bounded": all(
            bool(_as_dict(item.get("evidence_gate", {})).get("causal_language_bounded", False))
            for item in causal_cells
        ),
        "bounded_publication_scope": (
            "replay/correction support with direct GNW flow narrowing; marker, neutral salience, "
            "and gain controls remain pending"
        ),
    }


def _invalidators(
    theory: dict[str, Any],
    causal_cells: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if str(theory.get("stage", "")) != "stage78-biomimetic-theory-correspondence":
        invalidators.append({"key": "source_not_stage78_theory_correspondence", "severity": "p0"})
    theory_gate = _as_dict(theory.get("evidence_gate", {}))
    if not bool(theory_gate.get("do_not_claim_real_consciousness", False)):
        invalidators.append({"key": "source_consciousness_claim_not_blocked", "severity": "p0"})
    if not bool(theory_gate.get("theory_language_bounded", False)):
        invalidators.append({"key": "source_theory_language_unbounded", "severity": "p0"})
    if not causal_cells:
        invalidators.append({"key": "missing_stage71_causal_reports", "severity": "p0"})
    for index, report in enumerate(causal_cells):
        if str(report.get("stage", "")) != "stage71-biomimetic-causal-ablation-lab":
            invalidators.append(
                {"key": "causal_source_not_stage71", "severity": "p0", "cell": _cell_label(report, index)}
            )
        gate = _as_dict(report.get("evidence_gate", {}))
        if not bool(gate.get("do_not_claim_real_consciousness", False)):
            invalidators.append(
                {
                    "key": "causal_source_consciousness_claim_not_blocked",
                    "severity": "p0",
                    "cell": _cell_label(report, index),
                }
            )
        boundary_delta = _effect_estimate(report, "boundary_violation_delta")
        if boundary_delta != 0.0:
            invalidators.append(
                {"key": "control_boundary_delta_nonzero", "severity": "p0", "cell": _cell_label(report, index)}
            )
        boundary = _as_dict(report.get("boundary", {}))
        for key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(key, False)):
                invalidators.append(
                    {"key": f"causal_source_{key}", "severity": "p0", "cell": _cell_label(report, index)}
                )
    if not any(bool(item.get("executed", False)) for item in controls):
        invalidators.append({"key": "no_direct_control_executed", "severity": "p0"})
    return invalidators


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
    elif (
        bool(summary.get("replay_correction_intact", False))
        and bool(summary.get("gnw_flow_control_narrows_instability", False))
        and bool(summary.get("theory_language_bounded", False))
    ):
        decision = "targeted_control_supports_replay_preserved_gnw_narrowed_gain_pending"
        scope = "bounded_replay_correction_plus_gnw_flow_control"
    else:
        decision = "targeted_controls_need_direct_provider_followup"
        scope = "insufficient_direct_controls"
    return {
        "target": "targeted_biomimetic_falsification_controls",
        "decision": decision,
        "supported_scope": scope,
        "next_experiment": (
            "run correction-label shuffle or marker-removal, neutral salience, and gain-clamp "
            "provider cells before stronger biomimetic publication claims"
        ),
        "rationale": (
            f"executed={summary.get('executed_control_count', 0)} "
            f"pending={summary.get('pending_control_count', 0)} "
            f"replay_intact={summary.get('replay_correction_intact', False)} "
            f"gnw_narrowed={summary.get('gnw_flow_control_narrows_instability', False)}"
        ),
    }


def _publication_claims(
    controls: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    control_index = {str(item.get("control_id", "")): item for item in controls}
    gnw = _as_dict(control_index.get("gnw_prompt_cost_matched_ignition_null", {}))
    return [
        {
            "claim": "GNW ignition-to-reply instability is narrowed by a direct ignition-null control",
            "status": str(gnw.get("status", "not_run")),
            "allowed_language": "flow-coupling control over paired real-provider traces, not conscious access",
        },
        {
            "claim": "Replay/correction compression remains intact under Stage79 control review",
            "status": "supported" if bool(summary.get("replay_correction_intact", False)) else "not_supported",
            "allowed_language": "bounded hippocampal-indexing/CLS correspondence, not biological memory",
        },
        {
            "claim": "The biomimetic package is ready for stronger high-level publication claims",
            "status": "not_yet_marker_neutral_gain_controls_pending",
            "allowed_language": "bounded preprint-style result with explicit pending falsification controls",
        },
    ]


def _effect_estimate(report: dict[str, Any], key: str) -> float:
    effect = _as_dict(_as_dict(report.get("causal_effects", {})).get("effect_index", {})).get(key, {})
    return _num(_as_dict(effect).get("estimate"), 0.0)


def _condition_metric(report: dict[str, Any], condition_key: str, metric_key: str) -> float:
    condition = _as_dict(
        _as_dict(_as_dict(report.get("paired_conditions", {})).get("condition_index", {})).get(
            condition_key,
            {},
        )
    )
    return _num(_as_dict(condition.get("metrics", {})).get(metric_key), 0.0)


def _cell_replay_intact(report: dict[str, Any]) -> bool:
    return (
        _effect_estimate(report, "hippocampal_reactivation_delta") >= 0.0
        and _effect_estimate(report, "correction_survival_proxy_delta") >= 0.03
        and _effect_estimate(report, "boundary_violation_delta") == 0.0
    )


def _report_real_provider_trace(report: dict[str, Any]) -> bool:
    gates = (
        _as_dict(report.get("evidence_gate", {})),
        _as_dict(report.get("provider_evidence_gate", {})),
        _as_dict(report.get("provider_trace_set", {})),
    )
    return any(bool(item.get("real_provider_trace", False)) for item in gates)


def _theory_supported(theory: dict[str, Any], theory_id: str) -> bool:
    for item in list(theory.get("theory_correspondence_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("theory_id", "")) == theory_id:
            return str(item.get("support_status", "")) == "supported_real_provider"
    return False


def _theory_controls(theory: dict[str, Any], theory_id: str) -> list[str]:
    for item in list(theory.get("theory_correspondence_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("theory_id", "")) == theory_id:
            return [str(control) for control in list(item.get("disconfirming_controls", []) or [])]
    return []


def _cell_label(report: dict[str, Any], index: int) -> str:
    for key in ("cell_label", "model", "model_label", "source_model"):
        value = str(report.get(key, "") or "")
        if value:
            return value
    return f"cell_{index + 1}"


def _write_controls_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    controls = [
        dict(item)
        for item in list(report.get("control_results", []) or [])
        if isinstance(item, dict)
    ]
    labels = [_plot_label(str(item.get("control_id", ""))) for item in controls]
    status_score = numpy.array([_control_status_score(str(item.get("status", ""))) for item in controls])
    pass_counts = numpy.array([_num(item.get("passing_cell_count"), 0.0) for item in controls])
    x = numpy.arange(len(labels))

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    axes[0].bar(x, status_score, color="#2f7d68")
    axes[0].set_title("Control Status")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[0].set_ylim(0, 3.3)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    axes[1].bar(x, pass_counts, color="#6b6f8f")
    axes[1].set_title("Passing Cell Count")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage79 Biomimetic Falsification Controls | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.28, top=0.82, wspace=0.26)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _control_status_score(status: str) -> float:
    if status == "supported_direct_control":
        return 3.0
    if status == "mixed_direct_control":
        return 2.0
    if status == "planned_direct_control_pending":
        return 1.0
    return 0.0


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
