from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    _as_dict,
    _esc,
    _load_plotting_stack,
    _num,
    _plot_label,
)


STAGE76_NAME = "stage76-biomimetic-model-family-stability"

STAGE76_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "model_family_observatory_only": True,
    "provider_progress_reports_only": True,
    "runtime_mutation_allowed": False,
}


def load_biomimetic_model_family_progress(value: str | Path) -> tuple[str, dict[str, Any]]:
    text = str(value)
    if "=" not in text:
        raise ValueError("model progress input must be formatted as model=path")
    model, path = text.split("=", 1)
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return model.strip(), dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_model_family_stability(
    model_progress_reports: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    cells = [
        _cell_result(model, report, index=index)
        for index, (model, report) in enumerate(model_progress_reports)
        if isinstance(report, dict)
    ]
    models = _model_results(cells)
    summary = _model_family_summary(cells, models)
    invalidators = _invalidators(model_progress_reports, cells, models)
    decision = _hypothesis_decision(summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE76_NAME,
        "source_stage": "stage73-biomimetic-provider-progress",
        "cell_results": cells,
        "model_results": models,
        "model_family_summary": summary,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(summary),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not bool(summary.get("all_real_provider_cells", False)),
            "real_provider_trace": bool(summary.get("all_real_provider_cells", False)),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "model_family_language_bounded": True,
            "requires_repeated_model_family_cells": True,
            "reason": "stage76_tests_model_labeled_provider_progress_reports_without_runtime_authority",
        },
        "boundary": dict(STAGE76_BOUNDARY),
    }


def write_biomimetic_model_family_stability_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_model_family_stability_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_model_family_stability.png")
    _write_model_family_png(report, png_path)
    return {"html": html_path, "json": json_path, "model_family_png": png_path}


def render_biomimetic_model_family_stability_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("model_family_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage76 Biomimetic Model-Family Stability</title>
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
    <h1>Stage76 Biomimetic Model-Family Stability</h1>
    <p class="note">Read-only model-labeled stability check over Stage73 real-provider progress reports.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Flow Assessment", summary.get("flow_instability_assessment", ""))}
      {_metric("Models", summary.get("model_count", 0))}
      {_metric("Cells", summary.get("cell_count", 0))}
      {_metric("Replay/Correction Cells", summary.get("replay_correction_compression_cell_count", 0))}
      {_metric("Flow Cells", summary.get("flow_loss_reduction_cell_count", 0))}
    </section>
    <section>
      <h2>Model-Family Summary</h2>
      {_summary_table(summary)}
    </section>
    <section>
      <h2>Model Results</h2>
      {_model_table(payload)}
    </section>
    <section>
      <h2>Cell Results</h2>
      {_cell_table(payload)}
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


def _cell_result(model: str, report: dict[str, Any], *, index: int) -> dict[str, Any]:
    absolute = _as_dict(report.get("absolute_progress", {}))
    residual = _as_dict(report.get("residual_headroom", {}))
    noise = _as_dict(report.get("provider_noise", {}))
    evidence = _as_dict(report.get("evidence_gate", {}))
    decision = _as_dict(report.get("hypothesis_decision", {}))
    h_abs = _num(absolute.get("baseline_hippocampal_reactivation_delta"), 0.0)
    c_abs = _num(absolute.get("baseline_correction_survival_proxy_delta"), 0.0)
    score_abs = _num(absolute.get("baseline_biomimetic_score_delta"), 0.0)
    h_residual = _num(residual.get("hippocampal_reactivation_headroom_change"), 0.0)
    c_residual = _num(residual.get("correction_survival_headroom_change"), 0.0)
    flow_reduction = _num(residual.get("flow_to_reply_coupling_loss_reduction"), 0.0)
    return {
        "cell_index": index,
        "model": str(model).strip(),
        "decision": str(decision.get("decision", "")),
        "real_provider_trace": bool(evidence.get("real_provider_trace", False))
        and not bool(evidence.get("surrogate_only", True)),
        "absolute_improved": h_abs > 0.0 and c_abs > 0.0 and score_abs >= 0.0,
        "replay_correction_compressed": h_residual < 0.0 and c_residual < 0.0,
        "flow_loss_reduced": flow_reduction > 0.0,
        "baseline_hippocampal_reactivation_delta": round(h_abs, 6),
        "baseline_correction_survival_proxy_delta": round(c_abs, 6),
        "baseline_biomimetic_score_delta": round(score_abs, 6),
        "hippocampal_reactivation_headroom_change": round(h_residual, 6),
        "correction_survival_headroom_change": round(c_residual, 6),
        "flow_to_reply_coupling_loss_reduction": round(flow_reduction, 6),
        "after_observed_total_tokens": int(_num(noise.get("after_observed_total_tokens"), 0.0)),
        "after_latency_outlier": bool(noise.get("after_latency_outlier", False)),
    }


def _model_results(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        grouped[str(cell.get("model", ""))].append(cell)
    results: list[dict[str, Any]] = []
    for model in sorted(grouped):
        items = grouped[model]
        count = len(items)
        flow_count = sum(1 for item in items if bool(item.get("flow_loss_reduced", False)))
        replay_count = sum(1 for item in items if bool(item.get("replay_correction_compressed", False)))
        real_count = sum(1 for item in items if bool(item.get("real_provider_trace", False)))
        results.append(
            {
                "model": model,
                "cell_count": count,
                "real_provider_cell_count": real_count,
                "absolute_improved_cell_count": sum(
                    1 for item in items if bool(item.get("absolute_improved", False))
                ),
                "replay_correction_compression_cell_count": replay_count,
                "flow_loss_reduction_cell_count": flow_count,
                "all_real_provider_cells": count > 0 and real_count == count,
                "replay_correction_all_cells": count > 0 and replay_count == count,
                "flow_loss_reduced_all_cells": count > 0 and flow_count == count,
                "flow_loss_reduced_any_cell": flow_count > 0,
                "mean_hippocampal_reactivation_headroom_change": _mean_field(
                    items, "hippocampal_reactivation_headroom_change"
                ),
                "mean_correction_survival_headroom_change": _mean_field(
                    items, "correction_survival_headroom_change"
                ),
                "mean_flow_to_reply_coupling_loss_reduction": _mean_field(
                    items, "flow_to_reply_coupling_loss_reduction"
                ),
                "observed_total_tokens": sum(
                    int(_num(item.get("after_observed_total_tokens"), 0.0)) for item in items
                ),
            }
        )
    return results


def _model_family_summary(
    cells: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    cell_count = len(cells)
    model_count = len(models)
    real_cell_count = sum(1 for item in cells if bool(item.get("real_provider_trace", False)))
    absolute_count = sum(1 for item in cells if bool(item.get("absolute_improved", False)))
    replay_count = sum(1 for item in cells if bool(item.get("replay_correction_compressed", False)))
    flow_count = sum(1 for item in cells if bool(item.get("flow_loss_reduced", False)))
    all_real = cell_count > 0 and real_cell_count == cell_count
    replay_survives = (
        model_count >= 2
        and all_real
        and all(bool(item.get("replay_correction_all_cells", False)) for item in models)
    )
    flow_all = (
        model_count >= 2
        and all_real
        and all(bool(item.get("flow_loss_reduced_all_cells", False)) for item in models)
    )
    any_flow_model_count = sum(1 for item in models if bool(item.get("flow_loss_reduced_any_cell", False)))
    if model_count < 2:
        flow_assessment = "needs_model_family_cells"
    elif flow_all:
        flow_assessment = "model_family_stable"
    elif any_flow_model_count == 0:
        flow_assessment = "mechanism_level_unstable"
    elif any_flow_model_count < model_count:
        flow_assessment = "model_specific"
    else:
        flow_assessment = "within_model_replication_unstable_not_model_specific"
    return {
        "model_count": model_count,
        "cell_count": cell_count,
        "real_provider_cell_count": real_cell_count,
        "real_provider_model_count": sum(
            1 for item in models if bool(item.get("all_real_provider_cells", False))
        ),
        "absolute_improved_cell_count": absolute_count,
        "replay_correction_compression_cell_count": replay_count,
        "flow_loss_reduction_cell_count": flow_count,
        "all_real_provider_cells": all_real,
        "replay_correction_survives_model_variation": replay_survives,
        "flow_coupling_survives_all_cells": flow_all,
        "flow_positive_model_count": any_flow_model_count,
        "flow_instability_assessment": flow_assessment,
        "mean_hippocampal_reactivation_headroom_change": _mean_field(
            cells, "hippocampal_reactivation_headroom_change"
        ),
        "mean_correction_survival_headroom_change": _mean_field(
            cells, "correction_survival_headroom_change"
        ),
        "mean_flow_to_reply_coupling_loss_reduction": _mean_field(
            cells, "flow_to_reply_coupling_loss_reduction"
        ),
        "observed_total_tokens": sum(
            int(_num(item.get("after_observed_total_tokens"), 0.0)) for item in cells
        ),
    }


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    p0 = any(str(item.get("severity", "")) == "p0" for item in invalidators)
    replay = bool(summary.get("replay_correction_survives_model_variation", False))
    flow = str(summary.get("flow_instability_assessment", ""))
    if p0:
        decision = "invalidated"
        scope = "none"
    elif int(summary.get("model_count", 0) or 0) < 2:
        decision = "needs_model_family_cells"
        scope = "none"
    elif not bool(summary.get("all_real_provider_cells", False)):
        decision = "needs_real_provider_model_family"
        scope = "none"
    elif replay and flow == "model_family_stable":
        decision = "model_family_replay_correction_and_flow_supported"
        scope = "replay_correction_and_flow"
    elif replay and flow == "within_model_replication_unstable_not_model_specific":
        decision = "model_family_replay_correction_supported_flow_cell_unstable"
        scope = "replay_correction_with_flow_cell_instability"
    elif replay and flow == "model_specific":
        decision = "model_family_replay_correction_supported_flow_model_specific"
        scope = "replay_correction_with_model_specific_flow"
    elif replay and flow == "mechanism_level_unstable":
        decision = "model_family_replay_correction_supported_flow_mechanism_unstable"
        scope = "replay_correction_only"
    elif replay:
        decision = "model_family_replay_correction_supported_flow_unresolved"
        scope = "replay_correction_only"
    else:
        decision = "model_family_replay_correction_not_supported"
        scope = "none"
    return {
        "target": "model_family_provider_headroom_compression",
        "decision": decision,
        "supported_scope": scope,
        "flow_instability_assessment": flow,
        "next_experiment": (
            "run another model-family campaign only after changing the flow-coupling mechanism or "
            "adding an explicit ignition-to-reply intervention"
        ),
        "rationale": (
            f"models={summary.get('model_count', 0)} "
            f"cells={summary.get('cell_count', 0)} "
            f"replay_correction={summary.get('replay_correction_compression_cell_count', 0)} "
            f"flow={summary.get('flow_loss_reduction_cell_count', 0)} "
            f"flow_assessment={flow}"
        ),
    }


def _publication_claims(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "claim": "replay/correction residual headroom compression survives DeepSeek model-family variation",
            "status": "supported"
            if bool(summary.get("replay_correction_survives_model_variation", False))
            else "not_supported",
            "allowed_language": "model-labeled real-provider progress reports, not proof of consciousness",
        },
        {
            "claim": "flow-coupling compression is stable across all repeated model-family cells",
            "status": "supported"
            if bool(summary.get("flow_coupling_survives_all_cells", False))
            else str(summary.get("flow_instability_assessment", "not_supported")),
            "allowed_language": "flow stability classification, not a full mechanism solve",
        },
    ]


def _invalidators(
    reports: list[tuple[str, dict[str, Any]]],
    cells: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if len(models) < 2:
        invalidators.append({"key": "fewer_than_two_models", "severity": "p0"})
    if len(cells) < 2:
        invalidators.append({"key": "fewer_than_two_cells", "severity": "p0"})
    for index, (model, report) in enumerate(reports):
        if not str(model).strip():
            invalidators.append({"key": f"cell_{index}_missing_model_label", "severity": "p0"})
        if str(report.get("stage", "")) != "stage73-biomimetic-provider-progress":
            invalidators.append({"key": f"cell_{index}_not_stage73_progress", "severity": "p0"})
        evidence = _as_dict(report.get("evidence_gate", {}))
        if not bool(evidence.get("do_not_claim_real_consciousness", False)):
            invalidators.append({"key": f"cell_{index}_consciousness_claim_not_blocked", "severity": "p0"})
        if not bool(evidence.get("causal_language_bounded", False)):
            invalidators.append({"key": f"cell_{index}_unbounded_causal_language", "severity": "p0"})
        boundary = _as_dict(report.get("boundary", {}))
        for key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(key, False)):
                invalidators.append({"key": f"cell_{index}_{key}", "severity": "p0"})
    return invalidators


def _write_model_family_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    models = [dict(item) for item in list(report.get("model_results", []) or []) if isinstance(item, dict)]
    labels = [_plot_label(str(item.get("model", ""))) for item in models]
    x = numpy.arange(len(labels))
    h = numpy.array([_num(item.get("mean_hippocampal_reactivation_headroom_change"), 0.0) for item in models])
    c = numpy.array([_num(item.get("mean_correction_survival_headroom_change"), 0.0) for item in models])
    f = numpy.array([_num(item.get("mean_flow_to_reply_coupling_loss_reduction"), 0.0) for item in models])
    replay = numpy.array([_num(item.get("replay_correction_compression_cell_count"), 0.0) for item in models])
    flow = numpy.array([_num(item.get("flow_loss_reduction_cell_count"), 0.0) for item in models])

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    width = 0.25
    axes[0].bar(x - width, h, width=width, color="#2f7d68", label="hippocampal headroom")
    axes[0].bar(x, c, width=width, color="#b88424", label="correction headroom")
    axes[0].bar(x + width, f, width=width, color="#6b6f8f", label="flow reduction")
    axes[0].axhline(0.0, color="#172026", linewidth=0.8)
    axes[0].set_title("Mean Residual Changes by Model")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].legend(loc="best", fontsize=8)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    axes[1].bar(x - 0.16, replay, width=0.32, color="#2f7d68", label="replay/correction cells")
    axes[1].bar(x + 0.16, flow, width=0.32, color="#6b6f8f", label="flow cells")
    axes[1].set_title("Compressed Cells by Model")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].legend(loc="best", fontsize=8)
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage76 Biomimetic Model-Family Stability | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.16, top=0.82, wspace=0.28)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _summary_table(summary: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "model_count",
        "cell_count",
        "real_provider_cell_count",
        "replay_correction_compression_cell_count",
        "flow_loss_reduction_cell_count",
        "replay_correction_survives_model_variation",
        "flow_coupling_survives_all_cells",
        "flow_instability_assessment",
        "observed_total_tokens",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(summary.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _model_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>model</th><th>cells</th><th>replay/correction</th><th>flow</th><th>mean h headroom</th><th>mean correction headroom</th><th>mean flow reduction</th></tr>"
    ]
    for item in list(report.get("model_results", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('model', ''))}</td>"
            f"<td>{_esc(item.get('cell_count', 0))}</td>"
            f"<td>{_esc(item.get('replay_correction_compression_cell_count', 0))}</td>"
            f"<td>{_esc(item.get('flow_loss_reduction_cell_count', 0))}</td>"
            f"<td>{_esc(item.get('mean_hippocampal_reactivation_headroom_change', 0))}</td>"
            f"<td>{_esc(item.get('mean_correction_survival_headroom_change', 0))}</td>"
            f"<td>{_esc(item.get('mean_flow_to_reply_coupling_loss_reduction', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _cell_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>cell</th><th>model</th><th>h headroom</th><th>correction headroom</th><th>flow reduction</th><th>tokens</th></tr>"
    ]
    for item in list(report.get("cell_results", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('cell_index', ''))}</td>"
            f"<td>{_esc(item.get('model', ''))}</td>"
            f"<td>{_esc(item.get('hippocampal_reactivation_headroom_change', 0))}</td>"
            f"<td>{_esc(item.get('correction_survival_headroom_change', 0))}</td>"
            f"<td>{_esc(item.get('flow_to_reply_coupling_loss_reduction', 0))}</td>"
            f"<td>{_esc(item.get('after_observed_total_tokens', 0))}</td>"
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
        "model_family_language_bounded",
        "requires_repeated_model_family_cells",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "model_family_summary": report.get("model_family_summary", {}),
        "hypothesis_decision": report.get("hypothesis_decision", {}),
        "model_results": report.get("model_results", []),
        "cell_results": report.get("cell_results", []),
        "evidence_gate": report.get("evidence_gate", {}),
    }


def _mean_field(cells: list[dict[str, Any]], key: str) -> float:
    if not cells:
        return 0.0
    return round(sum(_num(item.get(key), 0.0) for item in cells) / len(cells), 6)


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'
