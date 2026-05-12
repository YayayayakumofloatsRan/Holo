from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


STAGE56_NAME = "stage56-dimensional-lift-observatory"

DIMENSIONAL_LIFT_BOUNDARY = {
    "observational_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}


def build_dimensional_lift_observatory(stage55_observatory: dict[str, Any]) -> dict[str, Any]:
    source = dict(stage55_observatory or {})
    vector_space = dict(source.get("vector_space", {})) if isinstance(source.get("vector_space", {}), dict) else {}
    axes = [str(axis) for axis in list(vector_space.get("axes", []) or [])]
    points = [dict(point) for point in list(vector_space.get("points", []) or []) if isinstance(point, dict)]
    lifted = _build_lifted_vector_space(points, axes)
    projection_family = _build_projection_family(points, lifted, source)
    intrinsic_probe = _build_intrinsic_dimension_probe(lifted)
    sample_adequacy = _build_sample_adequacy(lifted, intrinsic_probe)
    section_stability = _build_section_stability(source)
    return {
        "stage": STAGE56_NAME,
        "source_stage": str(source.get("stage", "") or ""),
        "run_id": str(source.get("run_id", "") or ""),
        "suite": str(source.get("suite", "") or ""),
        "lifted_vector_space": lifted,
        "coordinate_transforms": {
            "base_space": str(vector_space.get("mode", "") or ""),
            "lift": "residual_velocity_acceleration_delay_cross_term_lift_v1",
            "projection_family": "multi_plane_section_and_dynamics_projection_v1",
            "intrinsic_dimension": "gram_spectrum_effective_rank_proxy_v1",
        },
        "residual_fast_channels": {
            "mode": "residual_fast_channels_v1",
            "base_vector_preserved": True,
            "base_feature_count": len(axes),
            "compressed_projection_authority": False,
            "channels": [
                "base_axis_residual",
                "turn_velocity",
                "turn_acceleration",
                "lagged_context",
                "section_pressure_projection",
            ],
        },
        "projection_family": projection_family,
        "intrinsic_dimension_probe": intrinsic_probe,
        "sample_adequacy": sample_adequacy,
        "section_stability": section_stability,
        "topology_context": _topology_context(source),
        "boundary": dict(DIMENSIONAL_LIFT_BOUNDARY),
    }


def render_dimensional_lift_html(observatory: dict[str, Any]) -> str:
    report = dict(observatory or {})
    lifted = dict(report.get("lifted_vector_space", {})) if isinstance(report.get("lifted_vector_space", {}), dict) else {}
    intrinsic = dict(report.get("intrinsic_dimension_probe", {})) if isinstance(report.get("intrinsic_dimension_probe", {}), dict) else {}
    sample = dict(report.get("sample_adequacy", {})) if isinstance(report.get("sample_adequacy", {}), dict) else {}
    residual = dict(report.get("residual_fast_channels", {})) if isinstance(report.get("residual_fast_channels", {}), dict) else {}
    projections = [dict(item) for item in list(report.get("projection_family", []) or []) if isinstance(item, dict)]
    sections = [dict(item) for item in list(dict(report.get("section_stability", {})).get("sections", []) or []) if isinstance(item, dict)]
    serialized = html.escape(json.dumps(_compact_report_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Dimensional Lift Observatory</title>
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
    <h1>Holo Dimensional Lift Observatory</h1>
    <p class="note">Residual high-dimensional lift over Stage55 manifold evidence. This expands observability; it does not create runtime authority.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Points", lifted.get("point_count", 0))}
      {_metric("Base Dimensions", lifted.get("base_dimension", 0))}
      {_metric("Lifted Dimensions", lifted.get("lifted_dimension", 0))}
      {_metric("Effective Rank", intrinsic.get("effective_rank_proxy", 0))}
      {_metric("Max Observable Rank", dict(intrinsic.get("rank_bounds", {})).get("max_observable_rank", 0))}
      {_metric("Sample Limited", sample.get("limited_by_trace_length", False))}
    </section>
    <section>
      <h2>Projection Family</h2>
      <p class="note">Multiple planes are rendered from the same lifted vectors so a single 2D projection cannot dominate the interpretation.</p>
      {_render_projection_family_svg(projections)}
    </section>
    <section>
      <h2>Intrinsic Dimension Probe</h2>
      <p class="note">Effective rank is estimated from the centered lifted-vector Gram spectrum. With seven points, observable rank is inherently capped.</p>
      {_intrinsic_table(intrinsic, sample)}
    </section>
    <section>
      <h2>Residual Fast Channels</h2>
      <p class="note">The original Stage55 vector is preserved as a direct channel instead of being replaced by a compressed plot coordinate.</p>
      {_residual_table(residual)}
    </section>
    <section>
      <h2>Section Stability</h2>
      <p class="note">The same Poincare-style section family is rechecked for variance, derivative pressure, and crossing stability.</p>
      {_section_stability_table(sections)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def write_dimensional_lift_artifacts(observatory: dict[str, Any], output_path: str | Path) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_dimensional_lift_html(observatory), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(observatory, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_dimensional_lift.png")
    _write_dimensional_lift_png(observatory, png_path)
    return {"html": html_path, "json": json_path, "dimensional_lift_png": png_path}


def _build_lifted_vector_space(points: list[dict[str, Any]], axes: list[str]) -> dict[str, Any]:
    base_dimension = len(axes)
    pair_indices = [(left, right) for left in range(base_dimension) for right in range(left + 1, base_dimension)]
    feature_labels = (
        [f"residual:{axis}" for axis in axes]
        + [f"velocity:{axis}" for axis in axes]
        + [f"acceleration:{axis}" for axis in axes]
        + [f"lag1:{axis}" for axis in axes]
        + [f"lag2:{axis}" for axis in axes]
        + [f"energy:{axis}" for axis in axes]
        + [f"cross:{axes[left]}*{axes[right]}" for left, right in pair_indices]
    )
    base_vectors = [_point_vector(point, base_dimension) for point in points]
    lifted_points = []
    previous_velocity = [0.0 for _axis in axes]
    for index, point in enumerate(points):
        base = base_vectors[index]
        prev = base_vectors[index - 1] if index >= 1 else [0.0 for _axis in axes]
        prev2 = base_vectors[index - 2] if index >= 2 else [0.0 for _axis in axes]
        velocity = [base[axis_index] - prev[axis_index] for axis_index in range(base_dimension)]
        acceleration = [velocity[axis_index] - previous_velocity[axis_index] for axis_index in range(base_dimension)]
        previous_velocity = velocity
        energy = [value * value for value in base]
        cross_terms = [base[left] * base[right] for left, right in pair_indices]
        lifted_vector = base + velocity + acceleration + prev + prev2 + energy + cross_terms
        coordinate = [float(value or 0.0) for value in list(point.get("coordinate", []) or [])[:3]]
        while len(coordinate) < 3:
            coordinate.append(0.0)
        lifted_points.append(
            {
                "index": index,
                "turn_id": str(point.get("turn_id", f"turn_{index + 1}") or f"turn_{index + 1}"),
                "dominant_phase": str(point.get("dominant_phase", "") or ""),
                "base_coordinate": [round(_clamp01(value), 4) for value in coordinate],
                "base_norm": round(_vector_norm(base), 4),
                "velocity_norm": round(_vector_norm(velocity), 4),
                "acceleration_norm": round(_vector_norm(acceleration), 4),
                "lifted_norm": round(_vector_norm(lifted_vector), 4),
                "vector": [round(value, 4) for value in lifted_vector],
            }
        )
    return {
        "mode": "residual_velocity_acceleration_delay_cross_term_lift_v1",
        "base_dimension": base_dimension,
        "lifted_dimension": len(feature_labels),
        "point_count": len(lifted_points),
        "feature_labels": feature_labels,
        "feature_families": {
            "residual": base_dimension,
            "velocity": base_dimension,
            "acceleration": base_dimension,
            "lag1": base_dimension,
            "lag2": base_dimension,
            "energy": base_dimension,
            "cross_terms": len(pair_indices),
        },
        "points": lifted_points,
    }


def _build_projection_family(
    base_points: list[dict[str, Any]],
    lifted: dict[str, Any],
    stage55: dict[str, Any],
) -> list[dict[str, Any]]:
    lifted_points = [dict(point) for point in list(lifted.get("points", []) or []) if isinstance(point, dict)]
    sections = {str(section.get("name", "")): dict(section) for section in list(stage55.get("section_family", []) or []) if isinstance(section, dict)}
    dynamics = dict(stage55.get("local_dynamics", {})) if isinstance(stage55.get("local_dynamics", {}), dict) else {}
    edges = [dict(edge) for edge in list(dynamics.get("edges", []) or []) if isinstance(edge, dict)]
    curvature_values = [0.0]
    curvature_values.extend(float(edge.get("curvature", 0.0) or 0.0) for edge in edges)
    while len(curvature_values) < len(lifted_points):
        curvature_values.append(0.0)
    projection_specs = [
        (
            "residual_section_plane",
            "dynamic context",
            "memory control",
            [float(list(point.get("base_coordinate", [0.0, 0.0]))[0] or 0.0) for point in lifted_points],
            [float(list(point.get("base_coordinate", [0.0, 0.0]))[1] or 0.0) for point in lifted_points],
        ),
        (
            "velocity_acceleration_plane",
            "velocity norm",
            "acceleration norm",
            [float(point.get("velocity_norm", 0.0) or 0.0) for point in lifted_points],
            [float(point.get("acceleration_norm", 0.0) or 0.0) for point in lifted_points],
        ),
        (
            "cache_memory_section_plane",
            "cache reuse section",
            "memory control section",
            _section_values(sections.get("cache_reuse_section", {}), len(lifted_points)),
            _section_values(sections.get("memory_control_section", {}), len(lifted_points)),
        ),
        (
            "dynamic_latency_section_plane",
            "dynamic context section",
            "latency output section",
            _section_values(sections.get("dynamic_context_section", {}), len(lifted_points)),
            _section_values(sections.get("latency_output_section", {}), len(lifted_points)),
        ),
        (
            "curvature_energy_plane",
            "curvature",
            "lifted norm",
            curvature_values[: len(lifted_points)],
            [float(point.get("lifted_norm", 0.0) or 0.0) for point in lifted_points],
        ),
    ]
    family = []
    for name, x_label, y_label, raw_x, raw_y in projection_specs:
        x_values = _normalize_series(raw_x)
        y_values = _normalize_series(raw_y)
        plane_points = []
        for index, point in enumerate(lifted_points):
            plane_points.append(
                {
                    "turn_id": str(point.get("turn_id", "")),
                    "x": round(x_values[index], 4) if index < len(x_values) else 0.0,
                    "y": round(y_values[index], 4) if index < len(y_values) else 0.0,
                }
            )
        family.append(
            {
                "name": name,
                "x_label": x_label,
                "y_label": y_label,
                "points": plane_points,
                "spread": round(_projection_spread(plane_points), 4),
                "source": "stage55_sections_and_lifted_dynamics",
            }
        )
    return family


def _build_intrinsic_dimension_probe(lifted: dict[str, Any]) -> dict[str, Any]:
    points = [dict(point) for point in list(lifted.get("points", []) or []) if isinstance(point, dict)]
    matrix = [[float(value or 0.0) for value in list(point.get("vector", []) or [])] for point in points]
    point_count = len(matrix)
    dimension = int(lifted.get("lifted_dimension", 0) or 0)
    if point_count <= 1 or dimension <= 0:
        return {
            "mode": "gram_spectrum_effective_rank_proxy_v1",
            "effective_rank_proxy": 0.0,
            "participation_ratio": 0.0,
            "nonzero_eigenvalue_count": 0,
            "eigenvalue_energy": [],
            "rank_bounds": {
                "max_observable_rank": max(0, point_count - 1),
                "lifted_dimension": dimension,
                "point_count": point_count,
            },
        }
    centered = _center_matrix(matrix)
    gram = _gram_matrix(centered)
    eigenvalues = [value for value in _jacobi_eigenvalues(gram) if value > 1e-9]
    total = sum(eigenvalues)
    if total <= 0.0:
        effective_rank = 0.0
        participation = 0.0
        energy = []
    else:
        probabilities = [value / total for value in eigenvalues]
        entropy = -sum(probability * math.log(max(probability, 1e-12)) for probability in probabilities)
        effective_rank = math.exp(entropy)
        participation = (total * total) / sum(value * value for value in eigenvalues)
        energy = [round(probability, 4) for probability in probabilities[:12]]
    return {
        "mode": "gram_spectrum_effective_rank_proxy_v1",
        "effective_rank_proxy": round(effective_rank, 4),
        "participation_ratio": round(participation, 4),
        "nonzero_eigenvalue_count": len(eigenvalues),
        "eigenvalue_energy": energy,
        "rank_bounds": {
            "max_observable_rank": min(max(0, point_count - 1), dimension),
            "lifted_dimension": dimension,
            "point_count": point_count,
        },
        "interpretation": "rank_is_sample_limited_when_points_are_fewer_than_lifted_dimensions",
    }


def _build_sample_adequacy(lifted: dict[str, Any], intrinsic: dict[str, Any]) -> dict[str, Any]:
    point_count = int(lifted.get("point_count", 0) or 0)
    dimension = int(lifted.get("lifted_dimension", 0) or 0)
    base_dimension = int(lifted.get("base_dimension", 0) or 0)
    recommended_min_points = max(30, min(600, dimension * 3))
    limited = point_count < recommended_min_points or point_count <= dimension
    rank_bounds = dict(intrinsic.get("rank_bounds", {})) if isinstance(intrinsic.get("rank_bounds", {}), dict) else {}
    return {
        "mode": "trace_length_vs_lifted_dimension_v1",
        "point_count": point_count,
        "base_dimension": base_dimension,
        "lifted_dimension": dimension,
        "recommended_min_points": recommended_min_points,
        "limited_by_trace_length": bool(limited),
        "max_observable_rank": int(rank_bounds.get("max_observable_rank", max(0, point_count - 1)) or 0),
        "reason": "trace_length_far_below_lifted_dimension" if limited else "trace_length_sufficient_for_current_lift",
    }


def _build_section_stability(stage55: dict[str, Any]) -> dict[str, Any]:
    sections = [dict(section) for section in list(stage55.get("section_family", []) or []) if isinstance(section, dict)]
    rows = []
    for section in sections:
        values = [float(value or 0.0) for value in list(section.get("trace_values", []) or [])]
        derivatives = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
        variance = _variance(values)
        derivative_pressure = _mean(derivatives)
        upward = list(section.get("upward_crossing_turn_ids", []) or [])
        piercings = list(section.get("piercing_turn_ids", []) or [])
        stability = 1.0 / (1.0 + variance + derivative_pressure + len(upward) * 0.05)
        rows.append(
            {
                "name": str(section.get("name", "") or ""),
                "variance": round(variance, 4),
                "derivative_pressure": round(derivative_pressure, 4),
                "piercing_count": len(piercings),
                "upward_crossing_count": len(upward),
                "stability_score": round(stability, 4),
            }
        )
    return {
        "mode": "poincare_section_stability_v1",
        "section_count": len(rows),
        "mean_stability_score": round(_mean([float(row.get("stability_score", 0.0) or 0.0) for row in rows]), 4),
        "sections": rows,
    }


def _topology_context(stage55: dict[str, Any]) -> dict[str, Any]:
    topology = dict(stage55.get("topology_signature", {})) if isinstance(stage55.get("topology_signature", {}), dict) else {}
    return {
        "source_mode": str(topology.get("mode", "") or ""),
        "betti0_proxy": int(topology.get("betti0_proxy", 0) or 0),
        "betti1_proxy": int(topology.get("betti1_proxy", 0) or 0),
        "loop_candidate_count": len(topology.get("loop_candidates", []) or []),
        "torus_candidate": bool(topology.get("torus_candidate", False)),
        "stage56_interpretation": "lift_expands_observation_space_but_does_not_override_stage55_topology",
    }


def _render_projection_family_svg(projections: list[dict[str, Any]]) -> str:
    width = 920
    height = 620
    panel_w = 400
    panel_h = 240
    gap_x = 44
    gap_y = 56
    left = 54
    top = 48
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Dimensional Lift Projection Family">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    for index, projection in enumerate(projections[:4]):
        col = index % 2
        row = index // 2
        panel_x = left + col * (panel_w + gap_x)
        panel_y = top + row * (panel_h + gap_y)
        parts.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" fill="#fbfbf8" stroke="#d7dddc"/>')
        parts.append(f'<text x="{panel_x}" y="{panel_y - 14}" font-size="13" font-weight="700" fill="#182026">{_esc(projection.get("name", ""))}</text>')
        points = [dict(point) for point in list(projection.get("points", []) or []) if isinstance(point, dict)]
        plotted = []
        for point in points:
            x = panel_x + _clamp01(point.get("x", 0.0)) * panel_w
            y = panel_y + panel_h - _clamp01(point.get("y", 0.0)) * panel_h
            plotted.append((point, x, y))
        for point_index in range(1, len(plotted)):
            _previous, prev_x, prev_y = plotted[point_index - 1]
            _current, curr_x, curr_y = plotted[point_index]
            parts.append(f'<line x1="{prev_x:.1f}" y1="{prev_y:.1f}" x2="{curr_x:.1f}" y2="{curr_y:.1f}" stroke="#314148" stroke-width="1.7"/>')
        for point_index, (point, x, y) in enumerate(plotted):
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.2" fill="#2f7d68" stroke="#172026" stroke-width="1"/>')
            parts.append(f'<text x="{x + 7:.1f}" y="{y - 6:.1f}" font-size="10" fill="#182026">{point_index + 1}</text>')
        parts.append(f'<text x="{panel_x + panel_w - 150}" y="{panel_y + panel_h + 22}" font-size="10" fill="#5f6c72">{_esc(projection.get("x_label", ""))}</text>')
        parts.append(f'<text x="{panel_x}" y="{panel_y - 2}" font-size="10" fill="#5f6c72">{_esc(projection.get("y_label", ""))}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _write_dimensional_lift_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    lifted = dict(report.get("lifted_vector_space", {})) if isinstance(report.get("lifted_vector_space", {}), dict) else {}
    projections = [dict(item) for item in list(report.get("projection_family", []) or []) if isinstance(item, dict)]
    sample = dict(report.get("sample_adequacy", {})) if isinstance(report.get("sample_adequacy", {}), dict) else {}
    intrinsic = dict(report.get("intrinsic_dimension_probe", {})) if isinstance(report.get("intrinsic_dimension_probe", {}), dict) else {}
    fig, axes = pyplot.subplots(2, 2, figsize=(14, 10), dpi=150)
    flat_axes = list(axes.flatten())
    for axis_index, axis in enumerate(flat_axes):
        if axis_index >= len(projections):
            axis.axis("off")
            continue
        projection = projections[axis_index]
        points = [dict(point) for point in list(projection.get("points", []) or []) if isinstance(point, dict)]
        if points:
            x_values = numpy.array([float(point.get("x", 0.0) or 0.0) for point in points], dtype=float)
            y_values = numpy.array([float(point.get("y", 0.0) or 0.0) for point in points], dtype=float)
            axis.plot(x_values, y_values, color="#314148", linewidth=1.5, alpha=0.85)
            axis.scatter(x_values, y_values, s=70, c="#2f7d68", edgecolors="#172026", linewidths=0.8)
            for point_index, point in enumerate(points):
                axis.annotate(str(point_index + 1), (x_values[point_index], y_values[point_index]), xytext=(5, 4), textcoords="offset points", fontsize=8)
        axis.set_xlim(-0.05, 1.05)
        axis.set_ylim(-0.05, 1.05)
        axis.set_xlabel(str(projection.get("x_label", "")))
        axis.set_ylabel(str(projection.get("y_label", "")))
        axis.set_title(str(projection.get("name", "")))
        axis.grid(True, color="#d7dddc", linewidth=0.7, alpha=0.75)
    fig.suptitle(
        "Stage56 Dimensional Lift | "
        f"base_dim={lifted.get('base_dimension', 0)} | "
        f"lifted_dim={lifted.get('lifted_dimension', 0)} | "
        f"effective_rank={intrinsic.get('effective_rank_proxy', 0)} | "
        f"sample_limited={sample.get('limited_by_trace_length', False)}",
        fontsize=13,
        y=0.992,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _intrinsic_table(intrinsic: dict[str, Any], sample: dict[str, Any]) -> str:
    rank_bounds = dict(intrinsic.get("rank_bounds", {})) if isinstance(intrinsic.get("rank_bounds", {}), dict) else {}
    return (
        "<table><tr><th>effective_rank_proxy</th><th>participation_ratio</th><th>nonzero_eigenvalues</th><th>max_observable_rank</th><th>recommended_min_points</th><th>reason</th></tr>"
        f"<tr><td>{_esc(intrinsic.get('effective_rank_proxy', 0))}</td>"
        f"<td>{_esc(intrinsic.get('participation_ratio', 0))}</td>"
        f"<td>{_esc(intrinsic.get('nonzero_eigenvalue_count', 0))}</td>"
        f"<td>{_esc(rank_bounds.get('max_observable_rank', 0))}</td>"
        f"<td>{_esc(sample.get('recommended_min_points', 0))}</td>"
        f"<td>{_esc(sample.get('reason', ''))}</td></tr></table>"
    )


def _residual_table(residual: dict[str, Any]) -> str:
    return (
        "<table><tr><th>base_vector_preserved</th><th>base_feature_count</th><th>compressed_projection_authority</th><th>channels</th></tr>"
        f"<tr><td>{_esc(residual.get('base_vector_preserved', False))}</td>"
        f"<td>{_esc(residual.get('base_feature_count', 0))}</td>"
        f"<td>{_esc(residual.get('compressed_projection_authority', False))}</td>"
        f"<td>{_esc(', '.join(residual.get('channels', []) or []))}</td></tr></table>"
    )


def _section_stability_table(sections: list[dict[str, Any]]) -> str:
    rows = []
    for section in sections:
        rows.append(
            "<tr>"
            f"<td>{_esc(section.get('name', ''))}</td>"
            f"<td>{_esc(section.get('variance', 0))}</td>"
            f"<td>{_esc(section.get('derivative_pressure', 0))}</td>"
            f"<td>{_esc(section.get('piercing_count', 0))}</td>"
            f"<td>{_esc(section.get('upward_crossing_count', 0))}</td>"
            f"<td>{_esc(section.get('stability_score', 0))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6">no section stability evidence</td></tr>')
    return "<table><tr><th>section</th><th>variance</th><th>derivative pressure</th><th>piercings</th><th>upward crossings</th><th>stability</th></tr>" + "".join(rows) + "</table>"


def _compact_report_for_html(report: dict[str, Any]) -> dict[str, Any]:
    lifted = dict(report.get("lifted_vector_space", {})) if isinstance(report.get("lifted_vector_space", {}), dict) else {}
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "lifted_vector_space": {key: value for key, value in lifted.items() if key not in {"points", "feature_labels"}},
        "residual_fast_channels": report.get("residual_fast_channels", {}),
        "intrinsic_dimension_probe": report.get("intrinsic_dimension_probe", {}),
        "sample_adequacy": report.get("sample_adequacy", {}),
        "section_stability": report.get("section_stability", {}),
        "topology_context": report.get("topology_context", {}),
        "boundary": report.get("boundary", {}),
    }


def _point_vector(point: dict[str, Any], dimension: int) -> list[float]:
    vector = [float(value or 0.0) for value in list(point.get("vector", []) or [])[:dimension]]
    while len(vector) < dimension:
        vector.append(0.0)
    return vector


def _section_values(section: dict[str, Any], count: int) -> list[float]:
    values = [float(value or 0.0) for value in list(section.get("trace_values", []) or [])[:count]]
    while len(values) < count:
        values.append(0.0)
    return values


def _projection_spread(points: list[dict[str, Any]]) -> float:
    if len(points) <= 1:
        return 0.0
    total = 0.0
    for index in range(1, len(points)):
        prev = points[index - 1]
        curr = points[index]
        total += math.sqrt((float(curr.get("x", 0.0) or 0.0) - float(prev.get("x", 0.0) or 0.0)) ** 2 + (float(curr.get("y", 0.0) or 0.0) - float(prev.get("y", 0.0) or 0.0)) ** 2)
    return total


def _normalize_series(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if abs(maximum - minimum) <= 1e-12:
        return [0.5 for _value in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def _center_matrix(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    column_count = max(len(row) for row in matrix)
    means = []
    for column in range(column_count):
        means.append(_mean([row[column] if column < len(row) else 0.0 for row in matrix]))
    centered = []
    for row in matrix:
        centered.append([(row[column] if column < len(row) else 0.0) - means[column] for column in range(column_count)])
    return centered


def _gram_matrix(matrix: list[list[float]]) -> list[list[float]]:
    count = len(matrix)
    if count == 0:
        return []
    scale = 1.0 / max(1, len(matrix[0]))
    gram = [[0.0 for _col in range(count)] for _row in range(count)]
    for row in range(count):
        for col in range(row, count):
            value = sum(matrix[row][index] * matrix[col][index] for index in range(min(len(matrix[row]), len(matrix[col])))) * scale
            gram[row][col] = value
            gram[col][row] = value
    return gram


def _jacobi_eigenvalues(matrix: list[list[float]], *, sweeps: int = 80) -> list[float]:
    size = len(matrix)
    if size == 0:
        return []
    values = [[float(matrix[row][col]) for col in range(size)] for row in range(size)]
    for _sweep in range(sweeps):
        pivot_row = 0
        pivot_col = 1 if size > 1 else 0
        pivot_value = 0.0
        for row in range(size):
            for col in range(row + 1, size):
                candidate = abs(values[row][col])
                if candidate > pivot_value:
                    pivot_value = candidate
                    pivot_row = row
                    pivot_col = col
        if pivot_value <= 1e-10:
            break
        diagonal_delta = values[pivot_col][pivot_col] - values[pivot_row][pivot_row]
        angle = 0.5 * math.atan2(2.0 * values[pivot_row][pivot_col], diagonal_delta)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        app = values[pivot_row][pivot_row]
        aqq = values[pivot_col][pivot_col]
        apq = values[pivot_row][pivot_col]
        values[pivot_row][pivot_row] = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq
        values[pivot_col][pivot_col] = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq
        values[pivot_row][pivot_col] = 0.0
        values[pivot_col][pivot_row] = 0.0
        for index in range(size):
            if index in {pivot_row, pivot_col}:
                continue
            aip = values[index][pivot_row]
            aiq = values[index][pivot_col]
            values[index][pivot_row] = cosine * aip - sine * aiq
            values[pivot_row][index] = values[index][pivot_row]
            values[index][pivot_col] = sine * aip + cosine * aiq
            values[pivot_col][index] = values[index][pivot_col]
    return sorted([max(0.0, values[index][index]) for index in range(size)], reverse=True)


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    center = _mean(values)
    return sum((value - center) ** 2 for value in values) / len(values)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(float(value or 0.0) ** 2 for value in values))


def _clamp01(value: Any) -> float:
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
        raise RuntimeError("Stage56 dimensional lift PNG export requires matplotlib and numpy") from exc
    return matplotlib, pyplot, numpy


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
