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


STAGE83_NAME = "stage83-biomimetic-publication-bundle"

STAGE83_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "publication_bundle_observatory_only": True,
    "source_report_only": True,
    "runtime_mutation_allowed": False,
}


THEORY_SCOPE_BY_CONTROL = {
    "gnw_prompt_cost_matched_ignition_null": "partial",
    "hippocampal_cls_marker_removal": "supported",
    "predictive_precision_neutral_salience": "supported",
    "neuromodulatory_gain_clamp": "supported",
}


def load_biomimetic_publication_bundle_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_publication_bundle(
    theory_report: dict[str, Any],
    falsification_report: dict[str, Any],
    marker_control_report: dict[str, Any],
    precision_control_report: dict[str, Any],
    gain_control_report: dict[str, Any],
    replication_report: dict[str, Any],
    model_family_report: dict[str, Any],
) -> dict[str, Any]:
    sources = {
        "stage78": dict(theory_report or {}),
        "stage79": dict(falsification_report or {}),
        "stage80": dict(marker_control_report or {}),
        "stage81": dict(precision_control_report or {}),
        "stage82": dict(gain_control_report or {}),
        "replication": dict(replication_report or {}),
        "model_family": dict(model_family_report or {}),
    }
    control_matrix = _publication_control_matrix(sources)
    summary = _publication_summary(sources, control_matrix)
    invalidators = _invalidators(sources, control_matrix, summary)
    decision = _hypothesis_decision(summary, invalidators)
    narrative = _publication_narrative(summary, control_matrix)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE83_NAME,
        "source_stages": {key: str(value.get("stage", "")) for key, value in sources.items()},
        "publication_summary": summary,
        "publication_control_matrix": control_matrix,
        "hypothesis_decision": decision,
        "publication_narrative": narrative,
        "manuscript_outline": _manuscript_outline(summary, control_matrix),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "real_provider_trace": bool(summary.get("real_provider_trace", False)),
            "publication_language_bounded": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "direct_controls_complete": bool(summary.get("direct_controls_complete", False)),
            "gnw_partial_flow_cell_unstable": bool(
                summary.get("gnw_partial_flow_cell_unstable", False)
            ),
            "reason": "stage83_publication_bundle_without_runtime_authority",
        },
        "boundary": dict(STAGE83_BOUNDARY),
    }


def write_biomimetic_publication_bundle_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_publication_bundle_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_control_matrix.png")
    _write_control_matrix_png(report, png_path)
    manuscript_path = html_path.with_name(f"{html_path.stem}_manuscript.md")
    manuscript_path.write_text(render_biomimetic_publication_manuscript(report), encoding="utf-8")
    return {
        "html": html_path,
        "json": json_path,
        "control_matrix_png": png_path,
        "manuscript_markdown": manuscript_path,
    }


def render_biomimetic_publication_bundle_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("publication_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage83 Biomimetic Publication Bundle</title>
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
    <h1>Stage83 Biomimetic Publication Bundle</h1>
    <p class="note">Publication-bounded matrix over Stage79-82 direct controls. It packages evidence only; it does not call providers or mutate runtime state.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Readiness", summary.get("publication_readiness", ""))}
      {_metric("Supported Controls", summary.get("supported_direct_control_count", 0))}
      {_metric("Control Count", summary.get("control_count", 0))}
      {_metric("Replay Cells", summary.get("replay_correction_replication_cell_count", 0))}
      {_metric("Flow Cells", summary.get("flow_loss_reduction_cell_count", 0))}
    </section>
    <section>
      <h2>Control Matrix</h2>
      {_control_matrix_table(payload)}
    </section>
    <section>
      <h2>Publication Narrative</h2>
      {_narrative_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">gnw_partial_flow_cell_unstable={_esc(evidence.get("gnw_partial_flow_cell_unstable", False))}</p>
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


def render_biomimetic_publication_manuscript(report: dict[str, Any]) -> str:
    summary = _as_dict(report.get("publication_summary", {}))
    narrative = _as_dict(report.get("publication_narrative", {}))
    rows = [
        "| control | theory | scope | status | cells | primary result |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in list(report.get("publication_control_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    str(item.get("control_id", "")),
                    str(item.get("target_theory", "")),
                    str(item.get("theory_scope", "")),
                    str(item.get("status", "")),
                    f"{item.get('passing_cell_count', 0)}/{item.get('cell_count', 0)}",
                    str(item.get("primary_result", "")),
                ]
            )
            + " |"
        )
    return "\n".join(
        [
            "# Bounded Biomimetic Mechanism Controls",
            "",
            "## Result",
            "",
            str(narrative.get("result", "")),
            "",
            "## Control Matrix",
            "",
            *rows,
            "",
            "## Evidence Summary",
            "",
            f"- Publication readiness: `{summary.get('publication_readiness', '')}`",
            f"- Real-provider cells: `{summary.get('source_real_provider_cell_count', 0)}`",
            f"- Observed total tokens: `{summary.get('observed_total_tokens', 0)}`",
            f"- Replay/correction replicated cells: `{summary.get('replay_correction_replication_cell_count', 0)}`",
            f"- Flow-loss reduction cells: `{summary.get('flow_loss_reduction_cell_count', 0)}`",
            "",
            "## Claim Boundary",
            "",
            str(narrative.get("limitations", "")),
            "",
            "This is not evidence of subjective consciousness, biological neural tissue, or provider-native neural dynamics.",
        ]
    )


def _publication_control_matrix(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source_key in ("stage79", "stage80", "stage81", "stage82"):
        for control in list(sources[source_key].get("control_results", []) or []):
            if not isinstance(control, dict) or not bool(control.get("executed", False)):
                continue
            control_id = str(control.get("control_id", ""))
            evidence = [dict(item) for item in list(control.get("evidence", []) or []) if isinstance(item, dict)]
            items.append(
                {
                    "control_id": control_id,
                    "target_theory": str(control.get("target_theory", "")),
                    "source_stage": str(sources[source_key].get("stage", "")),
                    "theory_scope": THEORY_SCOPE_BY_CONTROL.get(control_id, "unmapped"),
                    "status": str(control.get("status", "")),
                    "cell_count": int(control.get("cell_count", len(evidence)) or 0),
                    "passing_cell_count": int(control.get("passing_cell_count", 0) or 0),
                    "primary_result": _primary_result(control_id, evidence),
                    "bounded_language": str(control.get("bounded_language", "")),
                }
            )
    return sorted(items, key=lambda item: _control_order(str(item.get("control_id", ""))))


def _publication_summary(
    sources: dict[str, dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    executed = [item for item in controls if int(item.get("cell_count", 0) or 0) > 0]
    supported = [
        item
        for item in executed
        if str(item.get("status", "")) == "supported_direct_control"
        and int(item.get("passing_cell_count", 0) or 0) == int(item.get("cell_count", 0) or 0)
    ]
    replication = _as_dict(sources["replication"].get("replication_summary", {}))
    model_family = _as_dict(sources["model_family"].get("model_family_summary", {}))
    observed_tokens = max(
        int(_num(replication.get("observed_total_tokens"), 0.0)),
        int(_num(model_family.get("observed_total_tokens"), 0.0)),
        int(
            _num(
                _as_dict(sources["stage78"].get("theory_summary", {})).get(
                    "source_observed_total_tokens",
                ),
                0.0,
            )
        ),
    )
    replay_cells = max(
        int(_num(replication.get("replay_correction_compression_cell_count"), 0.0)),
        int(_num(model_family.get("replay_correction_compression_cell_count"), 0.0)),
    )
    flow_cells = max(
        int(_num(replication.get("flow_loss_reduction_cell_count"), 0.0)),
        int(_num(model_family.get("flow_loss_reduction_cell_count"), 0.0)),
    )
    source_cells = max(
        int(_num(replication.get("real_provider_cell_count"), 0.0)),
        int(_num(model_family.get("real_provider_cell_count"), 0.0)),
        int(_num(_as_dict(sources["stage78"].get("theory_summary", {})).get("source_cell_count"), 0.0)),
    )
    direct_complete = len(executed) == 4 and len(supported) == 4
    gnw_partial = (
        any(str(item.get("control_id", "")) == "gnw_prompt_cost_matched_ignition_null" for item in supported)
        and bool(model_family.get("flow_coupling_survives_all_cells", False)) is False
    )
    readiness = (
        "bounded_methods_preprint_ready"
        if direct_complete and replay_cells >= 2 and gnw_partial
        else "needs_more_control_evidence"
    )
    return {
        "publication_readiness": readiness,
        "control_count": len(controls),
        "executed_control_count": len(executed),
        "supported_direct_control_count": len(supported),
        "direct_controls_complete": direct_complete,
        "real_provider_trace": _all_source_gates_true(sources, "real_provider_trace"),
        "gnw_partial_flow_cell_unstable": gnw_partial,
        "source_real_provider_cell_count": source_cells,
        "replay_correction_replication_cell_count": replay_cells,
        "flow_loss_reduction_cell_count": flow_cells,
        "observed_total_tokens": observed_tokens,
        "model_count": int(_num(model_family.get("model_count"), 0.0)),
        "flow_instability_assessment": str(
            model_family.get("flow_instability_assessment", "within_model_replication_unstable")
        ),
        "theory_language_bounded": _all_source_gates_true(sources, "theory_language_bounded")
        or _all_source_gates_true(sources, "model_family_language_bounded")
        or _all_source_gates_true(sources, "replication_language_bounded"),
        "bounded_publication_scope": "bounded biomimetic mechanism controls over real-provider traces",
    }


def _invalidators(
    sources: dict[str, dict[str, Any]],
    controls: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    expected = {
        "stage78": "stage78-biomimetic-theory-correspondence",
        "stage79": "stage79-biomimetic-falsification-controls",
        "stage80": "stage80-biomimetic-marker-removal-control",
        "stage81": "stage81-biomimetic-neutral-salience-control",
        "stage82": "stage82-biomimetic-gain-control",
    }
    for key, stage in expected.items():
        if str(sources[key].get("stage", "")) != stage:
            invalidators.append({"key": f"{key}_source_stage_mismatch", "severity": "p0"})
    for key, source in sources.items():
        if not bool(source.get("ok", False)):
            invalidators.append({"key": f"{key}_source_not_ok", "severity": "p0"})
        if not bool(_as_dict(source.get("evidence_gate", {})).get("do_not_claim_real_consciousness", False)):
            invalidators.append({"key": f"{key}_consciousness_claim_not_blocked", "severity": "p0"})
        boundary = _as_dict(source.get("boundary", {}))
        for boundary_key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(boundary_key, False)):
                invalidators.append(
                    {"key": f"{key}_{boundary_key}", "severity": "p0"}
                )
    stage82_summary = _as_dict(sources["stage82"].get("control_summary", {}))
    stage82_gate = _as_dict(sources["stage82"].get("evidence_gate", {}))
    if bool(stage82_summary.get("direct_controls_incomplete", False)) or bool(
        stage82_gate.get("direct_controls_incomplete", False)
    ):
        invalidators.append({"key": "stage82_gain_controls_incomplete", "severity": "p0"})
    if len(controls) != 4:
        invalidators.append({"key": "publication_control_matrix_incomplete", "severity": "p0"})
    if not bool(summary.get("real_provider_trace", False)):
        invalidators.append({"key": "publication_sources_not_real_provider", "severity": "p0"})
    if not bool(summary.get("gnw_partial_flow_cell_unstable", False)):
        invalidators.append({"key": "gnw_partial_boundary_not_preserved", "severity": "p0"})
    return invalidators


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
    elif str(summary.get("publication_readiness", "")) == "bounded_methods_preprint_ready":
        decision = "bounded_publication_bundle_ready"
        scope = "methods_preprint_ready_bounded_biomimetic_controls"
    else:
        decision = "publication_bundle_needs_more_evidence"
        scope = "insufficient_publication_package"
    return {
        "target": "stage78_82_biomimetic_direct_control_matrix",
        "decision": decision,
        "supported_scope": scope,
        "next_experiment": (
            "Stage84 should add a stream-of-consciousness latent-dynamics observatory before broad "
            "provider repeats"
        ),
        "rationale": (
            f"controls={summary.get('supported_direct_control_count', 0)}/4 "
            f"replay_cells={summary.get('replay_correction_replication_cell_count', 0)} "
            f"flow_cells={summary.get('flow_loss_reduction_cell_count', 0)} "
            f"gnw_partial={summary.get('gnw_partial_flow_cell_unstable', False)}"
        ),
    }


def _publication_narrative(
    summary: dict[str, Any],
    controls: list[dict[str, Any]],
) -> dict[str, str]:
    control_names = ", ".join(str(item.get("control_id", "")) for item in controls)
    return {
        "result": (
            "The completed Stage79-82 matrix supports a bounded biomimetic mechanism-control "
            f"package across {summary.get('source_real_provider_cell_count', 0)} real-provider cells: "
            f"{control_names}. Replay/correction controls replicate more strongly than "
            "ignition-to-reply flow coupling."
        ),
        "interpretation": (
            "Hippocampal/CLS-style reactivation, predictive precision, and adaptive gain are "
            "supported as operational correspondences. GNW remains partial because flow coupling "
            "improves under intervention but remains cell-unstable."
        ),
        "limitations": (
            "The evidence is an operational mechanism-control bundle over LLM-agent traces; it is "
            "not evidence of subjective consciousness, biological neuromodulation, or provider-native "
            "neural dynamics."
        ),
    }


def _manuscript_outline(
    summary: dict[str, Any],
    controls: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "section": "Introduction",
            "content": "Frame Holo as a bounded biomimetic cognition testbed, not as a consciousness claim.",
        },
        {
            "section": "Methods",
            "content": "Describe Stage59/60 provider traces and Stage79-82 matched counterfactual controls.",
        },
        {
            "section": "Results",
            "content": f"Report {len(controls)} direct controls and {summary.get('observed_total_tokens', 0)} observed provider tokens.",
        },
        {
            "section": "Discussion",
            "content": "Keep GNW partial and motivate Stage84 latent stream dynamics.",
        },
    ]


def _primary_result(control_id: str, evidence: list[dict[str, Any]]) -> str:
    if control_id == "gnw_prompt_cost_matched_ignition_null":
        values = [_num(item.get("flow_to_reply_coupling_delta"), 0.0) for item in evidence]
        return f"mean flow delta {_mean(values):.6f}"
    if control_id == "hippocampal_cls_marker_removal":
        values = [_num(item.get("marker_removal_correction_survival_delta"), 0.0) for item in evidence]
        return f"mean correction delta {_mean(values):.6f}"
    if control_id == "predictive_precision_neutral_salience":
        values = [_num(item.get("neutral_salience_correction_survival_delta"), 0.0) for item in evidence]
        return f"mean correction delta {_mean(values):.6f}"
    if control_id == "neuromodulatory_gain_clamp":
        values = [_num(item.get("gain_clamp_neuromodulator_coupling_delta"), 0.0) for item in evidence]
        return f"mean gain delta {_mean(values):.6f}"
    return "no primary result"


def _all_source_gates_true(sources: dict[str, dict[str, Any]], key: str) -> bool:
    values: list[bool] = []
    for source in sources.values():
        gate = _as_dict(source.get("evidence_gate", {}))
        if key in gate:
            values.append(bool(gate.get(key, False)))
    return bool(values) and all(values)


def _control_order(control_id: str) -> int:
    order = {
        "gnw_prompt_cost_matched_ignition_null": 0,
        "hippocampal_cls_marker_removal": 1,
        "predictive_precision_neutral_salience": 2,
        "neuromodulatory_gain_clamp": 3,
    }
    return order.get(control_id, 99)


def _mean(values: list[float]) -> float:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def _write_control_matrix_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    controls = [
        dict(item)
        for item in list(report.get("publication_control_matrix", []) or [])
        if isinstance(item, dict)
    ]
    labels = [_plot_label(str(item.get("control_id", ""))) for item in controls]
    passing = numpy.array([_num(item.get("passing_cell_count"), 0.0) for item in controls])
    total = numpy.array([max(_num(item.get("cell_count"), 0.0), 1.0) for item in controls])
    ratio = passing / total
    colors = ["#8a6f2a" if str(item.get("theory_scope", "")) == "partial" else "#2f7d68" for item in controls]
    x = numpy.arange(len(labels))

    fig, ax = pyplot.subplots(1, 1, figsize=(12, 5.2), dpi=150)
    if len(labels):
        ax.bar(x, ratio, color=colors, edgecolor="#172026", linewidth=0.8)
    ax.set_title("Stage83 Direct-Control Matrix")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=22, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("passing cell ratio")
    ax.grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.31, top=0.86)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _control_matrix_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>control</th><th>theory</th><th>scope</th><th>status</th><th>cells</th><th>primary result</th><th>bounded language</th></tr>"
    ]
    for item in list(report.get("publication_control_matrix", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('control_id', ''))}</td>"
            f"<td>{_esc(item.get('target_theory', ''))}</td>"
            f"<td>{_esc(item.get('theory_scope', ''))}</td>"
            f"<td>{_esc(item.get('status', ''))}</td>"
            f"<td>{_esc(item.get('passing_cell_count', 0))}/{_esc(item.get('cell_count', 0))}</td>"
            f"<td>{_esc(item.get('primary_result', ''))}</td>"
            f"<td>{_esc(item.get('bounded_language', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _narrative_table(report: dict[str, Any]) -> str:
    narrative = _as_dict(report.get("publication_narrative", {}))
    rows = ["<table><tr><th>field</th><th>text</th></tr>"]
    for key in ("result", "interpretation", "limitations"):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(narrative.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)
