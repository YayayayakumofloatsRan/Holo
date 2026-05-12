from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from .consciousness_dimensional_lift import build_dimensional_lift_observatory
from .consciousness_manifold import build_consciousness_manifold_observatory
from .consciousness_visualization import build_consciousness_visualization


STAGE57_NAME = "stage57-geometry-calibration"

GEOMETRY_CALIBRATION_BOUNDARY = {
    "observational_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}


def build_geometry_calibration(stage46_runs: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [dict(run) for run in list(stage46_runs or []) if isinstance(run, dict)]
    lifted_runs = [_build_lifted_run(run, index=index) for index, run in enumerate(runs)]
    comparative = _build_comparative_geometry(lifted_runs)
    perturbation = _build_perturbation_response(lifted_runs)
    predictive = _build_predictive_probe(perturbation)
    trace_depth = _build_trace_depth(lifted_runs)
    evidence_gate = _build_evidence_gate(lifted_runs, trace_depth, predictive)
    return {
        "stage": STAGE57_NAME,
        "source_stage": "stage46-bionic-boundary-stress",
        "run_ids": [item["run_id"] for item in lifted_runs],
        "trace_set": {
            "mode": "multi_run_stage46_geometry_calibration_v1",
            "run_count": len(lifted_runs),
            "total_points": sum(int(item["point_count"]) for item in lifted_runs),
            "perturbation_types": sorted({str(item["perturbation_type"]) for item in lifted_runs}),
            "score_min": round(min([float(item["score"]) for item in lifted_runs], default=0.0), 4),
            "score_max": round(max([float(item["score"]) for item in lifted_runs], default=0.0), 4),
        },
        "trace_depth": trace_depth,
        "runs": [_compact_lifted_run(item) for item in lifted_runs],
        "comparative_geometry": comparative,
        "perturbation_response": perturbation,
        "predictive_probe": predictive,
        "evidence_gate": evidence_gate,
        "boundary": dict(GEOMETRY_CALIBRATION_BOUNDARY),
    }


def render_geometry_calibration_html(calibration: dict[str, Any]) -> str:
    report = dict(calibration or {})
    trace_set = dict(report.get("trace_set", {})) if isinstance(report.get("trace_set", {}), dict) else {}
    trace_depth = dict(report.get("trace_depth", {})) if isinstance(report.get("trace_depth", {}), dict) else {}
    comparative = dict(report.get("comparative_geometry", {})) if isinstance(report.get("comparative_geometry", {}), dict) else {}
    perturbation = dict(report.get("perturbation_response", {})) if isinstance(report.get("perturbation_response", {}), dict) else {}
    predictive = dict(report.get("predictive_probe", {})) if isinstance(report.get("predictive_probe", {}), dict) else {}
    evidence = dict(report.get("evidence_gate", {})) if isinstance(report.get("evidence_gate", {}), dict) else {}
    serialized = html.escape(json.dumps(_compact_report_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Geometry Calibration</title>
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
    <h1>Holo Geometry Calibration</h1>
    <p class="note">Multi-run lifted-geometry calibration over Stage46 traces. Geometry is treated as evidence only when it predicts perturbation behavior.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Runs", trace_set.get("run_count", 0))}
      {_metric("Total Points", trace_set.get("total_points", 0))}
      {_metric("Longest Trace", trace_depth.get("longest_trace_points", 0))}
      {_metric("Pair Count", comparative.get("pair_count", 0))}
      {_metric("Geometry / Score Corr", predictive.get("geometry_score_correlation", 0))}
      {_metric("Needs Longer Traces", evidence.get("requires_longer_traces", False))}
    </section>
    <section>
      <h2>Geometry Distance Matrix</h2>
      <p class="note">Centroid distances compare Stage56 lifted spaces across runs, not just one projection.</p>
      {_distance_matrix_svg(report)}
    </section>
    <section>
      <h2>Perturbation Response</h2>
      <p class="note">Each perturbation is measured against the baseline run. Useful geometry should move with score degradation or stability changes.</p>
      {_perturbation_table(perturbation)}
    </section>
    <section>
      <h2>Predictive Probe</h2>
      <p class="note">This is a proxy for whether geometry has explanatory value across perturbations.</p>
      {_predictive_table(predictive)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="note">The gate prevents overclaiming from short or weakly predictive traces.</p>
      {_evidence_table(evidence, trace_depth)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def write_geometry_calibration_artifacts(calibration: dict[str, Any], output_path: str | Path) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_geometry_calibration_html(calibration), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_geometry_calibration.png")
    _write_geometry_calibration_png(calibration, png_path)
    return {"html": html_path, "json": json_path, "geometry_calibration_png": png_path}


def _build_lifted_run(run: dict[str, Any], *, index: int) -> dict[str, Any]:
    stage54 = build_consciousness_visualization(run)
    stage55 = build_consciousness_manifold_observatory(stage54)
    stage56 = build_dimensional_lift_observatory(stage55)
    lifted = dict(stage56.get("lifted_vector_space", {})) if isinstance(stage56.get("lifted_vector_space", {}), dict) else {}
    intrinsic = dict(stage56.get("intrinsic_dimension_probe", {})) if isinstance(stage56.get("intrinsic_dimension_probe", {}), dict) else {}
    sample = dict(stage56.get("sample_adequacy", {})) if isinstance(stage56.get("sample_adequacy", {}), dict) else {}
    section = dict(stage56.get("section_stability", {})) if isinstance(stage56.get("section_stability", {}), dict) else {}
    points = [dict(point) for point in list(lifted.get("points", []) or []) if isinstance(point, dict)]
    vectors = [[float(value or 0.0) for value in list(point.get("vector", []) or [])] for point in points]
    scorecard = dict(run.get("scorecard", {})) if isinstance(run.get("scorecard", {}), dict) else {}
    perturbation = dict(run.get("perturbation", {})) if isinstance(run.get("perturbation", {}), dict) else {}
    perturbation_type = str(perturbation.get("type", "") or "").strip()
    if not perturbation_type:
        perturbation_type = "baseline" if index == 0 else "unknown"
    return {
        "index": index,
        "run_id": str(run.get("run_id", "") or f"run_{index + 1}"),
        "status": str(run.get("status", "") or ""),
        "perturbation_type": perturbation_type,
        "score": float(scorecard.get("overall_score", 0.0) or 0.0),
        "point_count": int(lifted.get("point_count", len(points)) or 0),
        "lifted_dimension": int(lifted.get("lifted_dimension", 0) or 0),
        "effective_rank_proxy": float(intrinsic.get("effective_rank_proxy", 0.0) or 0.0),
        "sample_limited": bool(sample.get("limited_by_trace_length", False)),
        "recommended_min_points": int(sample.get("recommended_min_points", 0) or 0),
        "mean_section_stability": float(section.get("mean_stability_score", 0.0) or 0.0),
        "centroid": _centroid(vectors),
        "path_length": _lifted_path_length(vectors),
        "stage56": stage56,
    }


def _build_trace_depth(lifted_runs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [int(item.get("point_count", 0) or 0) for item in lifted_runs]
    recommended = max([int(item.get("recommended_min_points", 0) or 0) for item in lifted_runs], default=0)
    aggregate = sum(counts)
    longest = max(counts, default=0)
    return {
        "mode": "multi_run_trace_depth_v1",
        "aggregate_points": aggregate,
        "longest_trace_points": longest,
        "minimum_trace_points": min(counts, default=0),
        "recommended_min_points": recommended,
        "aggregate_meets_single_trace_recommendation": bool(recommended and aggregate >= recommended),
        "longest_trace_meets_recommendation": bool(recommended and longest >= recommended),
        "trace_depth_gain_over_single_latest": round(aggregate / max(1, longest), 4),
    }


def _build_comparative_geometry(lifted_runs: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for left_index in range(len(lifted_runs)):
        for right_index in range(left_index + 1, len(lifted_runs)):
            left = lifted_runs[left_index]
            right = lifted_runs[right_index]
            centroid_distance = _distance(left["centroid"], right["centroid"])
            score_delta = float(right["score"]) - float(left["score"])
            pairs.append(
                {
                    "left_run_id": left["run_id"],
                    "right_run_id": right["run_id"],
                    "left_perturbation": left["perturbation_type"],
                    "right_perturbation": right["perturbation_type"],
                    "centroid_distance": round(centroid_distance, 4),
                    "score_delta": round(score_delta, 4),
                    "effective_rank_delta": round(float(right["effective_rank_proxy"]) - float(left["effective_rank_proxy"]), 4),
                    "section_stability_delta": round(float(right["mean_section_stability"]) - float(left["mean_section_stability"]), 4),
                    "path_length_ratio": round(float(right["path_length"]) / max(1e-9, float(left["path_length"])), 4),
                }
            )
    return {
        "mode": "pairwise_lifted_geometry_comparison_v1",
        "pair_count": len(pairs),
        "mean_centroid_distance": round(_mean([float(pair["centroid_distance"]) for pair in pairs]), 4),
        "max_centroid_distance": round(max([float(pair["centroid_distance"]) for pair in pairs], default=0.0), 4),
        "pairs": pairs,
    }


def _build_perturbation_response(lifted_runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not lifted_runs:
        return {"mode": "baseline_relative_perturbation_response_v1", "baseline_run_id": "", "responses": []}
    baseline = next((item for item in lifted_runs if item.get("perturbation_type") == "baseline"), lifted_runs[0])
    responses = []
    for item in lifted_runs:
        if item is baseline:
            continue
        responses.append(
            {
                "run_id": item["run_id"],
                "perturbation_type": item["perturbation_type"],
                "centroid_distance_from_baseline": round(_distance(baseline["centroid"], item["centroid"]), 4),
                "score_delta_from_baseline": round(float(item["score"]) - float(baseline["score"]), 4),
                "effective_rank_delta_from_baseline": round(float(item["effective_rank_proxy"]) - float(baseline["effective_rank_proxy"]), 4),
                "section_stability_delta_from_baseline": round(float(item["mean_section_stability"]) - float(baseline["mean_section_stability"]), 4),
                "path_length_ratio_to_baseline": round(float(item["path_length"]) / max(1e-9, float(baseline["path_length"])), 4),
            }
        )
    return {
        "mode": "baseline_relative_perturbation_response_v1",
        "baseline_run_id": str(baseline.get("run_id", "")),
        "baseline_score": round(float(baseline.get("score", 0.0) or 0.0), 4),
        "responses": responses,
    }


def _build_predictive_probe(perturbation: dict[str, Any]) -> dict[str, Any]:
    responses = [dict(item) for item in list(perturbation.get("responses", []) or []) if isinstance(item, dict)]
    distances = [float(item.get("centroid_distance_from_baseline", 0.0) or 0.0) for item in responses]
    score_drops = [max(0.0, -float(item.get("score_delta_from_baseline", 0.0) or 0.0)) for item in responses]
    correlation = _correlation(distances, score_drops)
    rank_correlation = _correlation(
        [abs(float(item.get("effective_rank_delta_from_baseline", 0.0) or 0.0)) for item in responses],
        score_drops,
    )
    return {
        "mode": "geometry_vs_score_degradation_probe_v1",
        "geometry_score_correlation": round(correlation, 4),
        "rank_score_correlation": round(rank_correlation, 4),
        "sample_count": len(responses),
        "predictive_signal_proxy": bool(len(responses) >= 2 and correlation >= 0.25),
        "interpretation": "geometry_moves_with_score_drop" if correlation >= 0.25 else "geometry_prediction_not_established",
    }


def _build_evidence_gate(lifted_runs: list[dict[str, Any]], trace_depth: dict[str, Any], predictive: dict[str, Any]) -> dict[str, Any]:
    run_count = len(lifted_runs)
    requires_longer = (
        run_count < 5
        or not bool(trace_depth.get("longest_trace_meets_recommendation", False))
        or any(bool(item.get("sample_limited", False)) for item in lifted_runs)
    )
    predictive_signal = bool(predictive.get("predictive_signal_proxy", False))
    return {
        "mode": "geometry_evidence_gate_v1",
        "requires_longer_traces": bool(requires_longer),
        "requires_more_perturbations": bool(run_count < 5),
        "predictive_signal_proxy": predictive_signal,
        "do_not_claim_manifold": bool(requires_longer or not predictive_signal),
        "minimum_next_trace_turns": int(trace_depth.get("recommended_min_points", 0) or 0),
        "reason": "trace_depth_or_prediction_insufficient" if requires_longer or not predictive_signal else "comparative_geometry_ready_for_cautious_review",
    }


def _compact_lifted_run(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": item["run_id"],
        "status": item["status"],
        "perturbation_type": item["perturbation_type"],
        "score": round(float(item["score"]), 4),
        "point_count": item["point_count"],
        "lifted_dimension": item["lifted_dimension"],
        "effective_rank_proxy": round(float(item["effective_rank_proxy"]), 4),
        "sample_limited": bool(item["sample_limited"]),
        "mean_section_stability": round(float(item["mean_section_stability"]), 4),
        "path_length": round(float(item["path_length"]), 4),
    }


def _distance_matrix_svg(report: dict[str, Any]) -> str:
    runs = [dict(item) for item in list(report.get("runs", []) or []) if isinstance(item, dict)]
    comparative = dict(report.get("comparative_geometry", {})) if isinstance(report.get("comparative_geometry", {}), dict) else {}
    pairs = [dict(item) for item in list(comparative.get("pairs", []) or []) if isinstance(item, dict)]
    ids = [str(item.get("run_id", "")) for item in runs]
    size = max(1, len(ids))
    cell = 62
    left = 150
    top = 52
    width = left + cell * size + 40
    height = top + cell * size + 90
    max_distance = max([float(pair.get("centroid_distance", 0.0) or 0.0) for pair in pairs], default=1.0) or 1.0
    matrix = {(str(pair.get("left_run_id", "")), str(pair.get("right_run_id", ""))): float(pair.get("centroid_distance", 0.0) or 0.0) for pair in pairs}
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Geometry Distance Matrix">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    for index, run_id in enumerate(ids):
        label = run_id[-18:] if len(run_id) > 18 else run_id
        parts.append(f'<text x="{left + index * cell + 4}" y="34" font-size="10" fill="#182026" transform="rotate(-30 {left + index * cell + 4},34)">{_esc(label)}</text>')
        parts.append(f'<text x="12" y="{top + index * cell + 34}" font-size="10" fill="#182026">{_esc(label)}</text>')
    for row, left_id in enumerate(ids):
        for col, right_id in enumerate(ids):
            if row == col:
                distance = 0.0
            else:
                distance = matrix.get((left_id, right_id), matrix.get((right_id, left_id), 0.0))
            intensity = min(1.0, distance / max_distance)
            fill = _heat_color(intensity)
            x = left + col * cell
            y = top + row * cell
            parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#d7dddc"/>')
            parts.append(f'<text x="{x + 10}" y="{y + 36}" font-size="11" fill="#172026">{distance:.2f}</text>')
    parts.append('<text x="14" y="{0}" font-size="11" fill="#5f6c72">centroid distance in lifted space</text>'.format(height - 24))
    parts.append("</svg>")
    return "\n".join(parts)


def _perturbation_table(perturbation: dict[str, Any]) -> str:
    rows = []
    for item in list(perturbation.get("responses", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('run_id', ''))}</td>"
            f"<td>{_esc(item.get('perturbation_type', ''))}</td>"
            f"<td>{_esc(item.get('centroid_distance_from_baseline', 0))}</td>"
            f"<td>{_esc(item.get('score_delta_from_baseline', 0))}</td>"
            f"<td>{_esc(item.get('effective_rank_delta_from_baseline', 0))}</td>"
            f"<td>{_esc(item.get('section_stability_delta_from_baseline', 0))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6">no perturbation responses</td></tr>')
    return "<table><tr><th>run</th><th>perturbation</th><th>centroid distance</th><th>score delta</th><th>rank delta</th><th>section stability delta</th></tr>" + "".join(rows) + "</table>"


def _predictive_table(predictive: dict[str, Any]) -> str:
    return (
        "<table><tr><th>geometry_score_correlation</th><th>rank_score_correlation</th><th>sample_count</th><th>predictive_signal_proxy</th><th>interpretation</th></tr>"
        f"<tr><td>{_esc(predictive.get('geometry_score_correlation', 0))}</td>"
        f"<td>{_esc(predictive.get('rank_score_correlation', 0))}</td>"
        f"<td>{_esc(predictive.get('sample_count', 0))}</td>"
        f"<td>{_esc(predictive.get('predictive_signal_proxy', False))}</td>"
        f"<td>{_esc(predictive.get('interpretation', ''))}</td></tr></table>"
    )


def _evidence_table(evidence: dict[str, Any], trace_depth: dict[str, Any]) -> str:
    return (
        "<table><tr><th>requires_longer_traces</th><th>requires_more_perturbations</th><th>do_not_claim_manifold</th><th>minimum_next_trace_turns</th><th>aggregate_points</th><th>reason</th></tr>"
        f"<tr><td>{_esc(evidence.get('requires_longer_traces', False))}</td>"
        f"<td>{_esc(evidence.get('requires_more_perturbations', False))}</td>"
        f"<td>{_esc(evidence.get('do_not_claim_manifold', True))}</td>"
        f"<td>{_esc(evidence.get('minimum_next_trace_turns', 0))}</td>"
        f"<td>{_esc(trace_depth.get('aggregate_points', 0))}</td>"
        f"<td>{_esc(evidence.get('reason', ''))}</td></tr></table>"
    )


def _write_geometry_calibration_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    runs = [dict(item) for item in list(report.get("runs", []) or []) if isinstance(item, dict)]
    perturbation = dict(report.get("perturbation_response", {})) if isinstance(report.get("perturbation_response", {}), dict) else {}
    responses = [dict(item) for item in list(perturbation.get("responses", []) or []) if isinstance(item, dict)]
    comparative = dict(report.get("comparative_geometry", {})) if isinstance(report.get("comparative_geometry", {}), dict) else {}
    pairs = [dict(item) for item in list(comparative.get("pairs", []) or []) if isinstance(item, dict)]
    fig = pyplot.figure(figsize=(14, 9), dpi=150)
    grid = fig.add_gridspec(1, 2, width_ratios=[1.05, 1.0], wspace=0.28)
    matrix_axis = fig.add_subplot(grid[0, 0])
    ids = [str(item.get("run_id", "")) for item in runs]
    matrix = numpy.zeros((len(ids), len(ids)), dtype=float)
    index_by_id = {run_id: index for index, run_id in enumerate(ids)}
    for pair in pairs:
        left = index_by_id.get(str(pair.get("left_run_id", "")))
        right = index_by_id.get(str(pair.get("right_run_id", "")))
        if left is not None and right is not None:
            value = float(pair.get("centroid_distance", 0.0) or 0.0)
            matrix[left, right] = value
            matrix[right, left] = value
    if len(ids):
        image = matrix_axis.imshow(matrix, cmap="magma", aspect="equal")
        labels = [run_id[-12:] if len(run_id) > 12 else run_id for run_id in ids]
        matrix_axis.set_xticks(numpy.arange(len(ids)))
        matrix_axis.set_yticks(numpy.arange(len(ids)))
        matrix_axis.set_xticklabels(labels, rotation=35, ha="right")
        matrix_axis.set_yticklabels(labels)
        fig.colorbar(image, ax=matrix_axis, fraction=0.046, pad=0.04, label="centroid distance")
    matrix_axis.set_title("Lifted Geometry Distance Matrix")

    response_axis = fig.add_subplot(grid[0, 1])
    if responses:
        x_values = numpy.array([float(item.get("centroid_distance_from_baseline", 0.0) or 0.0) for item in responses], dtype=float)
        y_values = numpy.array([-float(item.get("score_delta_from_baseline", 0.0) or 0.0) for item in responses], dtype=float)
        response_axis.scatter(x_values, y_values, s=90, c="#2f7d68", edgecolors="#172026", linewidths=0.8)
        for index, item in enumerate(responses):
            response_axis.annotate(str(item.get("perturbation_type", "")), (x_values[index], y_values[index]), xytext=(6, 4), textcoords="offset points", fontsize=8)
    response_axis.set_xlabel("centroid distance from baseline")
    response_axis.set_ylabel("score drop from baseline")
    response_axis.set_title("Perturbation Geometry vs Score Drop")
    response_axis.grid(True, color="#d7dddc", linewidth=0.7, alpha=0.75)
    predictive = dict(report.get("predictive_probe", {})) if isinstance(report.get("predictive_probe", {}), dict) else {}
    evidence = dict(report.get("evidence_gate", {})) if isinstance(report.get("evidence_gate", {}), dict) else {}
    fig.suptitle(
        "Stage57 Geometry Calibration | "
        f"runs={len(ids)} | "
        f"corr={predictive.get('geometry_score_correlation', 0)} | "
        f"do_not_claim_manifold={evidence.get('do_not_claim_manifold', True)}",
        fontsize=13,
        y=0.992,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _compact_report_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "run_ids": report.get("run_ids", []),
        "trace_set": report.get("trace_set", {}),
        "trace_depth": report.get("trace_depth", {}),
        "runs": report.get("runs", []),
        "comparative_geometry": report.get("comparative_geometry", {}),
        "perturbation_response": report.get("perturbation_response", {}),
        "predictive_probe": report.get("predictive_probe", {}),
        "evidence_gate": report.get("evidence_gate", {}),
        "boundary": report.get("boundary", {}),
    }


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dimension = max(len(vector) for vector in vectors)
    result = []
    for axis in range(dimension):
        result.append(_mean([vector[axis] if axis < len(vector) else 0.0 for vector in vectors]))
    return result


def _lifted_path_length(vectors: list[list[float]]) -> float:
    if len(vectors) <= 1:
        return 0.0
    return sum(_distance(vectors[index - 1], vectors[index]) for index in range(1, len(vectors)))


def _distance(left: list[float], right: list[float]) -> float:
    dimension = max(len(left), len(right))
    total = 0.0
    for index in range(dimension):
        left_value = left[index] if index < len(left) else 0.0
        right_value = right[index] if index < len(right) else 0.0
        total += (right_value - left_value) ** 2
    return math.sqrt(total)


def _correlation(x_values: list[float], y_values: list[float]) -> float:
    if len(x_values) < 2 or len(y_values) < 2 or len(x_values) != len(y_values):
        return 0.0
    mean_x = _mean(x_values)
    mean_y = _mean(y_values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_values))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_values))
    if denom_x <= 1e-12 or denom_y <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, numerator / (denom_x * denom_y)))


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _heat_color(value: float) -> str:
    clamped = min(1.0, max(0.0, float(value or 0.0)))
    red = int(247 * clamped + 250 * (1.0 - clamped))
    green = int(160 * clamped + 250 * (1.0 - clamped))
    blue = int(77 * clamped + 248 * (1.0 - clamped))
    return f"rgb({red},{green},{blue})"


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
        import numpy
    except ImportError as exc:
        raise RuntimeError("Stage57 geometry calibration PNG export requires matplotlib and numpy") from exc
    return matplotlib, pyplot, numpy


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
