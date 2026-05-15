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


STAGE78_NAME = "stage78-biomimetic-theory-correspondence"

STAGE78_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "theory_correspondence_observatory_only": True,
    "provider_progress_reports_only": True,
    "runtime_mutation_allowed": False,
}


def load_biomimetic_theory_correspondence_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_theory_correspondence(
    model_family_report: dict[str, Any],
) -> dict[str, Any]:
    source = dict(model_family_report or {})
    summary = _as_dict(source.get("model_family_summary", {}))
    rows = _theory_rows(summary)
    theory_summary = _theory_summary(rows, summary)
    invalidators = _invalidators(source, rows)
    decision = _hypothesis_decision(theory_summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE78_NAME,
        "source_stage": str(source.get("stage", "")),
        "source_hypothesis_decision": _as_dict(source.get("hypothesis_decision", {})),
        "source_model_family_summary": summary,
        "theory_correspondence_matrix": rows,
        "theory_summary": theory_summary,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(rows, theory_summary),
        "falsification_controls": _falsification_controls(rows),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not bool(summary.get("all_real_provider_cells", False)),
            "real_provider_trace": bool(summary.get("all_real_provider_cells", False)),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "theory_language_bounded": True,
            "requires_falsification_controls": True,
            "reason": "stage78_maps_provider_evidence_to_falsifiable_theory_without_runtime_authority",
        },
        "boundary": dict(STAGE78_BOUNDARY),
    }


def write_biomimetic_theory_correspondence_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_theory_correspondence_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_theory_correspondence.png")
    _write_theory_png(report, png_path)
    return {"html": html_path, "json": json_path, "theory_png": png_path}


def render_biomimetic_theory_correspondence_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("theory_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage78 Biomimetic Theory Correspondence</title>
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
    <h1>Stage78 Biomimetic Theory Correspondence</h1>
    <p class="note">Read-only neuroscience mapping and falsification matrix over Stage77 model-family evidence.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Readiness", summary.get("publication_readiness", ""))}
      {_metric("Theories", summary.get("theory_count", 0))}
      {_metric("Falsifiable", summary.get("falsifiable_theory_count", 0))}
      {_metric("Supported", summary.get("supported_theory_count", 0))}
      {_metric("Partial", summary.get("partial_theory_count", 0))}
    </section>
    <section>
      <h2>Theory Correspondence Matrix</h2>
      {_theory_table(payload)}
    </section>
    <section>
      <h2>Falsification Controls</h2>
      {_controls_table(payload)}
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


def _theory_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    cell_count = int(_num(summary.get("cell_count"), 0.0))
    replay_count = int(_num(summary.get("replay_correction_compression_cell_count"), 0.0))
    flow_count = int(_num(summary.get("flow_loss_reduction_cell_count"), 0.0))
    all_real = bool(summary.get("all_real_provider_cells", False))
    flow_assessment = str(summary.get("flow_instability_assessment", ""))
    mean_correction = _num(summary.get("mean_correction_survival_headroom_change"), 0.0)
    if all_real and cell_count > 0 and flow_count == cell_count:
        gnw_status = "supported_real_provider"
    elif all_real and flow_count > 0:
        gnw_status = "partial_support_flow_unstable"
    else:
        gnw_status = "needs_mechanism_control"
    replay_supported = all_real and cell_count > 0 and replay_count == cell_count
    predictive_supported = replay_supported and mean_correction < 0.0
    return [
        {
            "theory_id": "global_neuronal_workspace",
            "neuroscience_theory": "global neuronal workspace ignition and broadcast",
            "literature_anchor": {
                "short_citation": "Dehaene and Changeux, 2011",
                "url": "https://doi.org/10.1016/j.neuron.2011.03.018",
            },
            "holo_variables": [
                "global_workspace_ignition.score",
                "ignition_to_reply_coupling.coupling_strength",
                "flow_to_reply_coupling_loss_reduction",
                "flow_instability_assessment",
            ],
            "measurable_predictions": [
                "higher explicit ignition should precede reply-target commitment",
                "ignition-null controls should reduce flow-to-reply coupling without harming replay/correction",
            ],
            "disconfirming_controls": [
                "global_workspace_ignition_ablation",
                "prompt-cost-matched ignition-null cell",
            ],
            "support_status": gnw_status,
            "falsifiable": True,
            "evidence_summary": (
                f"flow_loss_reduction_cell_count={flow_count}/{cell_count}; "
                f"flow_instability_assessment={flow_assessment}"
            ),
        },
        {
            "theory_id": "hippocampal_indexing_cls",
            "neuroscience_theory": "hippocampal indexing and complementary learning systems replay",
            "literature_anchor": {
                "short_citation": "McClelland, McNaughton, and O'Reilly, 1995",
                "url": "https://doi.org/10.1037/0033-295X.102.3.419",
            },
            "holo_variables": [
                "correction_reactivation_marker",
                "hippocampal_reactivation_delta",
                "hippocampal_reactivation_headroom_change",
                "correction_survival_headroom_change",
            ],
            "measurable_predictions": [
                "explicit correction markers should raise delayed replay pressure",
                "replay/correction residual headroom should compress across repeated provider cells",
            ],
            "disconfirming_controls": [
                "shuffle correction labels before Stage71 evaluation",
                "remove correction_reactivation_marker while keeping prompt token cost matched",
            ],
            "support_status": "supported_real_provider" if replay_supported else "not_supported",
            "falsifiable": True,
            "evidence_summary": f"replay_correction_compression_cell_count={replay_count}/{cell_count}",
        },
        {
            "theory_id": "predictive_processing_precision",
            "neuroscience_theory": "predictive processing precision-weighted correction",
            "literature_anchor": {
                "short_citation": "Friston, 2005",
                "url": "https://doi.org/10.1098/rstb.2005.1622",
            },
            "holo_variables": [
                "correction_reactivation_marker",
                "acetylcholine_like_precision_pressure",
                "correction_survival_proxy_delta",
                "prompt_cost_delta",
            ],
            "measurable_predictions": [
                "false-fact corrections should increase correction survival more than neutral salience controls",
                "precision-like correction pressure should preserve bounded prompt cost",
            ],
            "disconfirming_controls": [
                "neutral salience marker with identical token cost",
                "correction marker with delayed probe labels hidden from evaluator",
            ],
            "support_status": "supported_real_provider" if predictive_supported else "needs_precision_control",
            "falsifiable": True,
            "evidence_summary": f"mean_correction_survival_headroom_change={mean_correction:.6f}",
        },
        {
            "theory_id": "neuromodulatory_gain",
            "neuroscience_theory": "neuromodulatory adaptive gain over salience and control mode",
            "literature_anchor": {
                "short_citation": "Aston-Jones and Cohen, 2005",
                "url": "https://doi.org/10.1146/annurev.neuro.28.061604.135709",
            },
            "holo_variables": [
                "neuromodulator_coupling",
                "salience_gate.priority",
                "thalamic_gain",
                "uncertainty_monitor",
            ],
            "measurable_predictions": [
                "gain-clamped controls should reduce adaptive selection under uncertainty",
                "gain-randomized controls should weaken the link between salience and reply target",
            ],
            "disconfirming_controls": [
                "neuromodulatory_gain_clamp",
                "salience-matched random-gain cell",
            ],
            "support_status": "mapped_needs_targeted_control",
            "falsifiable": True,
            "evidence_summary": "Stage77 uses gain variables in the field, but no dedicated gain-clamp provider control has run",
        },
    ]


def _theory_summary(rows: list[dict[str, Any]], source_summary: dict[str, Any]) -> dict[str, Any]:
    supported = sum(1 for item in rows if str(item.get("support_status", "")) == "supported_real_provider")
    partial = sum(1 for item in rows if str(item.get("support_status", "")).startswith("partial"))
    needs = sum(1 for item in rows if "needs" in str(item.get("support_status", "")))
    falsifiable = sum(1 for item in rows if bool(item.get("falsifiable", False)))
    all_real = bool(source_summary.get("all_real_provider_cells", False))
    if all_real and supported >= 2 and partial >= 1 and falsifiable == len(rows):
        readiness = "bounded_preprint_candidate"
    elif falsifiable == len(rows):
        readiness = "needs_targeted_controls"
    else:
        readiness = "not_publishable"
    return {
        "theory_count": len(rows),
        "falsifiable_theory_count": falsifiable,
        "supported_theory_count": supported,
        "partial_theory_count": partial,
        "needs_control_theory_count": needs,
        "publication_readiness": readiness,
        "source_cell_count": int(_num(source_summary.get("cell_count"), 0.0)),
        "source_observed_total_tokens": int(_num(source_summary.get("observed_total_tokens"), 0.0)),
    }


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
    elif str(summary.get("publication_readiness", "")) == "bounded_preprint_candidate":
        decision = "publishable_bounded_replay_correction_with_partial_flow"
        scope = "replay_correction_with_partial_gnw_flow"
    elif int(summary.get("falsifiable_theory_count", 0) or 0) == int(summary.get("theory_count", 0) or 0):
        decision = "theory_matrix_ready_needs_targeted_controls"
        scope = "falsifiable_matrix"
    else:
        decision = "theory_matrix_not_ready"
        scope = "none"
    return {
        "target": "neuroscience_theory_correspondence_and_falsification",
        "decision": decision,
        "supported_scope": scope,
        "next_experiment": (
            "run prompt-cost-matched ignition-null, correction-shuffle, and gain-clamp controls "
            "before another broad provider repeat"
        ),
        "rationale": (
            f"theories={summary.get('theory_count', 0)} "
            f"supported={summary.get('supported_theory_count', 0)} "
            f"partial={summary.get('partial_theory_count', 0)} "
            f"readiness={summary.get('publication_readiness', '')}"
        ),
    }


def _publication_claims(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    statuses = {str(item.get("theory_id", "")): str(item.get("support_status", "")) for item in rows}
    return [
        {
            "claim": "Holo replay/correction behavior has a bounded hippocampal-indexing/CLS correspondence",
            "status": statuses.get("hippocampal_indexing_cls", "not_supported"),
            "allowed_language": "cross-cell real-provider replay/correction compression, not biological memory",
        },
        {
            "claim": "Holo ignition-to-reply behavior has a bounded GNW correspondence",
            "status": statuses.get("global_neuronal_workspace", "not_supported"),
            "allowed_language": "partial flow-coupling support, not proof of conscious access",
        },
        {
            "claim": "The Stage78 package is ready for a bounded preprint-style result section",
            "status": str(summary.get("publication_readiness", "")),
            "allowed_language": "falsifiable computational-neuroscience prototype evidence",
        },
    ]


def _falsification_controls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for row in rows:
        theory_id = str(row.get("theory_id", ""))
        for index, control in enumerate(list(row.get("disconfirming_controls", []) or [])):
            controls.append(
                {
                    "control_id": f"{theory_id}_control_{index + 1}",
                    "target_theory": theory_id,
                    "control": str(control),
                    "would_disconfirm_if": _disconfirmation_rule(theory_id),
                }
            )
    return controls


def _invalidators(source: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if str(source.get("stage", "")) != "stage76-biomimetic-model-family-stability":
        invalidators.append({"key": "source_not_model_family_stability", "severity": "p0"})
    evidence = _as_dict(source.get("evidence_gate", {}))
    if not bool(evidence.get("do_not_claim_real_consciousness", False)):
        invalidators.append({"key": "source_consciousness_claim_not_blocked", "severity": "p0"})
    if not bool(evidence.get("causal_language_bounded", False)):
        invalidators.append({"key": "source_unbounded_causal_language", "severity": "p0"})
    boundary = _as_dict(source.get("boundary", {}))
    for key in (
        "runtime_decision_authority",
        "transport_decision_authority",
        "self_memory_write_allowed",
        "policy_mutation_allowed",
        "unbounded_loop_allowed",
    ):
        if bool(boundary.get(key, False)):
            invalidators.append({"key": f"source_{key}", "severity": "p0"})
    for row in rows:
        if not bool(row.get("falsifiable", False)):
            invalidators.append({"key": f"{row.get('theory_id')}_not_falsifiable", "severity": "p0"})
        if len(list(row.get("disconfirming_controls", []) or [])) < 2:
            invalidators.append({"key": f"{row.get('theory_id')}_insufficient_controls", "severity": "p0"})
    return invalidators


def _disconfirmation_rule(theory_id: str) -> str:
    rules = {
        "global_neuronal_workspace": "flow coupling remains unchanged after ignition is ablated with token cost matched",
        "hippocampal_indexing_cls": "correction survival remains equally strong after correction labels or markers are removed",
        "predictive_processing_precision": "neutral salience controls match correction survival despite lacking prediction-error semantics",
        "neuromodulatory_gain": "gain-clamped or randomized cells preserve the same salience-to-reply relationship",
    }
    return rules.get(theory_id, "control matches the active mechanism under matched evidence conditions")


def _write_theory_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    rows = [dict(item) for item in list(report.get("theory_correspondence_matrix", []) or []) if isinstance(item, dict)]
    labels = [_plot_label(str(item.get("theory_id", ""))) for item in rows]
    status_score = numpy.array([_status_score(str(item.get("support_status", ""))) for item in rows])
    controls = numpy.array([len(list(item.get("disconfirming_controls", []) or [])) for item in rows])
    x = numpy.arange(len(labels))

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    axes[0].bar(x, status_score, color="#2f7d68")
    axes[0].set_title("Theory Support Status")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=15, ha="right")
    axes[0].set_ylim(0, 3.4)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    axes[1].bar(x, controls, color="#6b6f8f")
    axes[1].set_title("Disconfirming Controls per Theory")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=15, ha="right")
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage78 Biomimetic Theory Correspondence | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.24, top=0.82, wspace=0.26)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _status_score(status: str) -> float:
    if status == "supported_real_provider":
        return 3.0
    if status.startswith("partial"):
        return 2.0
    if "needs" in status or status.startswith("mapped"):
        return 1.0
    return 0.0


def _theory_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>theory</th><th>status</th><th>variables</th><th>predictions</th><th>controls</th><th>evidence</th></tr>"
    ]
    for item in list(report.get("theory_correspondence_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('theory_id', ''))}</td>"
            f"<td>{_esc(item.get('support_status', ''))}</td>"
            f"<td>{_esc('; '.join(str(v) for v in list(item.get('holo_variables', []) or [])))}</td>"
            f"<td>{_esc('; '.join(str(v) for v in list(item.get('measurable_predictions', []) or [])))}</td>"
            f"<td>{_esc('; '.join(str(v) for v in list(item.get('disconfirming_controls', []) or [])))}</td>"
            f"<td>{_esc(item.get('evidence_summary', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _controls_table(report: dict[str, Any]) -> str:
    rows = ["<table><tr><th>control</th><th>target</th><th>would disconfirm if</th></tr>"]
    for item in list(report.get("falsification_controls", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('control', ''))}</td>"
            f"<td>{_esc(item.get('target_theory', ''))}</td>"
            f"<td>{_esc(item.get('would_disconfirm_if', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)
