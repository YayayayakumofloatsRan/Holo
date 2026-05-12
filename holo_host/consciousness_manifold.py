from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


STAGE55_NAME = "stage55-consciousness-manifold-observatory"

OBSERVATORY_BOUNDARY = {
    "observational_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}

SECTION_AXIS_GROUPS = {
    "cache_reuse_section": ("prompt_cache_hit_tokens", "provider_prefix_tokens", "dynamic_fusion_saved_lines"),
    "dynamic_context_section": ("prompt_cache_miss_tokens", "provider_dynamic_tokens", "dynamic_context_lines"),
    "memory_control_section": ("memory_salience", "recall_budget", "consolidation_priority", "consciousness_phase_count"),
    "latency_output_section": ("latency_ms", "completion_tokens"),
}


def build_consciousness_manifold_observatory(stage54_report: dict[str, Any]) -> dict[str, Any]:
    source = dict(stage54_report or {})
    axes = [str(axis) for axis in list(dict(source.get("heatmap", {})).get("axes", []) or [])]
    points = _vector_points(source, axes)
    local_dynamics = _build_local_dynamics(points, axes)
    section_family = _build_section_family(points, axes)
    topology_signature = _build_topology_signature(points)
    delay_embedding = _build_delay_embedding(points, axes, section_family)
    hyperbolic_probe = _build_hyperbolic_probe(local_dynamics, axes)
    return {
        "stage": STAGE55_NAME,
        "source_stage": str(source.get("stage", "") or ""),
        "run_id": str(source.get("run_id", "") or ""),
        "suite": str(source.get("suite", "") or ""),
        "vector_space": {
            "mode": "stage54_normalized_compute_space",
            "axes": axes,
            "dimension": len(axes),
            "point_count": len(points),
            "points": points,
        },
        "coordinate_transforms": {
            "primary_projection": "stage54_compute_manifold_coordinates",
            "delay_embedding": "takens_style_windowed_trace_embedding_v1",
            "section_family": "poincare_section_family_v1",
            "topology": "recurrence_graph_cycle_rank_proxy_v1",
        },
        "delay_embedding": delay_embedding,
        "section_family": section_family,
        "local_dynamics": local_dynamics,
        "hyperbolic_probe": hyperbolic_probe,
        "topology_signature": topology_signature,
        "boundary": dict(OBSERVATORY_BOUNDARY),
    }


def render_consciousness_manifold_html(observatory: dict[str, Any]) -> str:
    report = dict(observatory or {})
    vector_space = dict(report.get("vector_space", {})) if isinstance(report.get("vector_space", {}), dict) else {}
    topology = dict(report.get("topology_signature", {})) if isinstance(report.get("topology_signature", {}), dict) else {}
    hyperbolic = dict(report.get("hyperbolic_probe", {})) if isinstance(report.get("hyperbolic_probe", {}), dict) else {}
    sections = [dict(item) for item in list(report.get("section_family", []) or []) if isinstance(item, dict)]
    dynamics = dict(report.get("local_dynamics", {})) if isinstance(report.get("local_dynamics", {}), dict) else {}
    serialized = html.escape(json.dumps(_compact_observatory_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Consciousness Manifold Observatory</title>
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
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
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
    }}
    th, td {{
      padding: 8px 9px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 12px;
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
    <h1>Holo Consciousness Manifold Observatory</h1>
    <p class="note">Trace-backed high-dimensional geometry view over Stage54 compute vectors. This is an observatory, not runtime authority.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Points", vector_space.get("point_count", 0))}
      {_metric("Dimensions", vector_space.get("dimension", 0))}
      {_metric("Betti1 Proxy", topology.get("betti1_proxy", 0))}
      {_metric("Loop Candidates", len(topology.get("loop_candidates", []) or []))}
      {_metric("Lyapunov Proxy", hyperbolic.get("lyapunov_proxy", 0))}
      {_metric("Expansion Events", len(hyperbolic.get("expansion_events", []) or []))}
    </section>
    <section>
      <h2>Manifold Projection</h2>
      <p class="note">The plotted coordinates are a deterministic projection of the normalized Stage54 vector space.</p>
      {_render_manifold_svg(report)}
    </section>
    <section>
      <h2>Topology Signature</h2>
      <p class="note">Cycle rank and loop candidates are recurrence-graph proxies, not mathematical proof of consciousness.</p>
      {_topology_table(topology)}
    </section>
    <section>
      <h2>Poincare Section Family</h2>
      <p class="note">Each section slices the same high-dimensional trace by cache, dynamic context, memory control, or latency/output axes.</p>
      {_section_table(sections)}
    </section>
    <section>
      <h2>Hyperbolic Probe</h2>
      <p class="note">Local expansion and contraction are estimated from adjacent normalized vector deltas.</p>
      {_hyperbolic_table(hyperbolic, dynamics)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def write_consciousness_manifold_artifacts(observatory: dict[str, Any], output_path: str | Path) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_consciousness_manifold_html(observatory), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(observatory, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_manifold.png")
    _write_manifold_png(observatory, png_path)
    return {"html": html_path, "json": json_path, "manifold_png": png_path}


def _vector_points(stage54_report: dict[str, Any], axes: list[str]) -> list[dict[str, Any]]:
    manifold = dict(stage54_report.get("compute_manifold", {})) if isinstance(stage54_report.get("compute_manifold", {}), dict) else {}
    manifold_points = [dict(point) for point in list(manifold.get("points", []) or []) if isinstance(point, dict)]
    if manifold_points:
        points = []
        for index, point in enumerate(manifold_points):
            vector = [float(value or 0.0) for value in list(point.get("normalized_vector", []) or [])]
            if len(vector) < len(axes):
                vector.extend([0.0 for _axis in axes[len(vector) :]])
            coordinate = [float(value or 0.0) for value in list(point.get("coordinate", []) or [])[:3]]
            while len(coordinate) < 3:
                coordinate.append(0.0)
            points.append(
                {
                    "index": index,
                    "turn_id": str(point.get("turn_id", f"turn_{index + 1}") or f"turn_{index + 1}"),
                    "dominant_phase": str(point.get("dominant_phase", "") or ""),
                    "dominant_block": str(point.get("dominant_block", "") or ""),
                    "coordinate": [round(_clamp(value), 4) for value in coordinate],
                    "vector": [round(_clamp(value), 4) for value in vector[: len(axes)]],
                    "norm": round(_vector_norm(vector[: len(axes)]), 4),
                }
            )
        return points
    rows = [dict(row) for row in list(dict(stage54_report.get("heatmap", {})).get("rows", []) or []) if isinstance(row, dict)]
    points = []
    for index, row in enumerate(rows):
        normalized = dict(row.get("normalized", {})) if isinstance(row.get("normalized", {}), dict) else {}
        vector = [_clamp(float(normalized.get(axis, 0.0) or 0.0)) for axis in axes]
        coordinate = _project_vector(vector, axes)
        points.append(
            {
                "index": index,
                "turn_id": str(row.get("turn_id", f"turn_{index + 1}") or f"turn_{index + 1}"),
                "dominant_phase": str(row.get("dominant_phase", "") or ""),
                "dominant_block": "",
                "coordinate": coordinate,
                "vector": [round(value, 4) for value in vector],
                "norm": round(_vector_norm(vector), 4),
            }
        )
    return points


def _build_local_dynamics(points: list[dict[str, Any]], axes: list[str]) -> dict[str, Any]:
    edges = []
    previous_delta: list[float] | None = None
    for index in range(1, len(points)):
        previous = points[index - 1]
        current = points[index]
        prev_vector = [float(value) for value in previous.get("vector", [])]
        curr_vector = [float(value) for value in current.get("vector", [])]
        delta = [curr - prev for prev, curr in zip(prev_vector, curr_vector)]
        delta_norm = _vector_norm(delta)
        coordinate_distance = _coordinate_distance(previous.get("coordinate", []), current.get("coordinate", []))
        curvature = 0.0
        if previous_delta is not None:
            curvature = _angle_between(previous_delta, delta)
        previous_delta = delta
        edge = {
            "source_turn_id": previous.get("turn_id", ""),
            "target_turn_id": current.get("turn_id", ""),
            "delta_vector": [round(value, 4) for value in delta],
            "delta_norm": round(delta_norm, 4),
            "coordinate_distance": round(coordinate_distance, 4),
            "cosine_similarity": round(_cosine_similarity(prev_vector, curr_vector), 4),
            "curvature": round(curvature, 4),
        }
        edges.append(edge)
    axis_delta = []
    for axis_index, axis in enumerate(axes):
        total = sum(abs(float(edge["delta_vector"][axis_index])) for edge in edges if axis_index < len(edge.get("delta_vector", [])))
        axis_delta.append((axis, total))
    axis_delta_sorted = sorted(axis_delta, key=lambda item: item[1], reverse=True)
    return {
        "mode": "adjacent_stage54_vector_dynamics_v1",
        "edges": edges,
        "path_length": round(sum(float(edge.get("coordinate_distance", 0.0) or 0.0) for edge in edges), 4),
        "unstable_axis_proxy": axis_delta_sorted[0][0] if axis_delta_sorted else "",
        "stable_axis_proxy": axis_delta_sorted[-1][0] if axis_delta_sorted else "",
        "axis_delta_energy": {axis: round(value, 4) for axis, value in axis_delta_sorted},
    }


def _build_section_family(points: list[dict[str, Any]], axes: list[str]) -> list[dict[str, Any]]:
    axis_index = {axis: index for index, axis in enumerate(axes)}
    sections = []
    for name, group_axes in SECTION_AXIS_GROUPS.items():
        present_axes = [axis for axis in group_axes if axis in axis_index]
        values = []
        for point in points:
            vector = list(point.get("vector", []))
            if present_axes:
                values.append(sum(float(vector[axis_index[axis]]) for axis in present_axes) / len(present_axes))
            else:
                values.append(0.0)
        center = _mean(values)
        threshold = max(center, 0.5)
        piercings = [
            str(point.get("turn_id", ""))
            for point, value in zip(points, values)
            if value >= threshold
        ]
        upward_crossings = []
        for index in range(1, len(values)):
            if values[index - 1] < threshold <= values[index]:
                upward_crossings.append(str(points[index].get("turn_id", "")))
        sections.append(
            {
                "name": name,
                "axes": present_axes,
                "center": round(center, 4),
                "variance": round(_variance(values), 4),
                "threshold": round(threshold, 4),
                "piercing_turn_ids": piercings,
                "upward_crossing_turn_ids": upward_crossings,
                "trace_values": [round(value, 4) for value in values],
            }
        )
    return sections


def _build_delay_embedding(points: list[dict[str, Any]], axes: list[str], sections: list[dict[str, Any]], *, window: int = 3, lag: int = 1) -> dict[str, Any]:
    embedded = []
    section_by_name = {str(section.get("name", "")): dict(section) for section in sections}
    for end_index in range((window - 1) * lag, len(points)):
        indices = [end_index - offset * lag for offset in reversed(range(window))]
        source_points = [points[index] for index in indices]
        vector: list[float] = []
        for point in source_points:
            vector.extend(float(value) for value in list(point.get("vector", [])))
        coordinate = [
            _section_value_at(section_by_name.get("dynamic_context_section", {}), end_index),
            _section_value_at(section_by_name.get("memory_control_section", {}), end_index),
            _section_value_at(section_by_name.get("cache_reuse_section", {}), end_index),
            _section_value_at(section_by_name.get("latency_output_section", {}), end_index),
        ]
        embedded.append(
            {
                "turn_id": source_points[-1].get("turn_id", ""),
                "source_turn_ids": [point.get("turn_id", "") for point in source_points],
                "coordinate": [round(value, 4) for value in coordinate],
                "vector_dimension": len(vector),
                "norm": round(_vector_norm(vector), 4),
            }
        )
    return {
        "mode": "takens_style_delay_embedding_v1",
        "window": window,
        "lag": lag,
        "base_dimension": len(axes),
        "embedded_dimension": len(axes) * window,
        "points": embedded,
    }


def _build_hyperbolic_probe(local_dynamics: dict[str, Any], axes: list[str]) -> dict[str, Any]:
    edges = [dict(edge) for edge in list(local_dynamics.get("edges", []) or []) if isinstance(edge, dict)]
    ratios = []
    expansion_events = []
    contraction_events = []
    for index in range(1, len(edges)):
        previous = max(float(edges[index - 1].get("delta_norm", 0.0) or 0.0), 1e-9)
        current = max(float(edges[index].get("delta_norm", 0.0) or 0.0), 1e-9)
        ratio = current / previous
        ratios.append(ratio)
        event = {
            "source_turn_id": edges[index].get("source_turn_id", ""),
            "target_turn_id": edges[index].get("target_turn_id", ""),
            "ratio": round(ratio, 4),
        }
        if ratio >= 1.15:
            expansion_events.append(event)
        if ratio <= 0.85:
            contraction_events.append(event)
    lyapunov = _mean([math.log(max(ratio, 1e-9)) for ratio in ratios]) if ratios else 0.0
    return {
        "mode": "local_expansion_contraction_proxy_v1",
        "lyapunov_proxy": round(lyapunov, 4),
        "mean_expansion_ratio": round(_mean(ratios), 4),
        "expansion_events": expansion_events,
        "contraction_events": contraction_events,
        "unstable_axis_proxy": str(local_dynamics.get("unstable_axis_proxy", "") or ""),
        "stable_axis_proxy": str(local_dynamics.get("stable_axis_proxy", "") or ""),
        "interpretation": "positive_proxy_expands_local_trace" if lyapunov > 0 else "nonpositive_proxy_contracts_or_cycles_local_trace",
        "axis_count": len(axes),
    }


def _build_topology_signature(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        return {
            "mode": "recurrence_graph_cycle_rank_proxy_v1",
            "recurrence_threshold": 0.0,
            "recurrence_edges": [],
            "loop_candidates": [],
            "betti0_proxy": len(points),
            "betti1_proxy": 0,
            "torus_candidate": False,
        }
    edge_lengths = [
        _coordinate_distance(points[index - 1].get("coordinate", []), points[index].get("coordinate", []))
        for index in range(1, len(points))
    ]
    median_edge = _median(edge_lengths) or 0.25
    threshold = max(0.18, median_edge * 0.75)
    recurrence_edges = []
    loop_candidates = []
    for left in range(len(points)):
        for right in range(left + 2, len(points)):
            if left == 0 and right == len(points) - 1:
                adjacent_on_closed_path = False
            else:
                adjacent_on_closed_path = right - left <= 1
            if adjacent_on_closed_path:
                continue
            distance = _coordinate_distance(points[left].get("coordinate", []), points[right].get("coordinate", []))
            if distance <= threshold:
                path_length = sum(edge_lengths[left:right])
                recurrence = {
                    "source_turn_id": points[left].get("turn_id", ""),
                    "target_turn_id": points[right].get("turn_id", ""),
                    "distance": round(distance, 4),
                    "path_length": round(path_length, 4),
                }
                recurrence_edges.append(recurrence)
                if path_length >= max(threshold * 3.0, distance * 2.0):
                    loop_candidates.append(
                        {
                            **recurrence,
                            "loop_type": "near_closed_recurrent_trace",
                            "support_turn_count": right - left + 1,
                        }
                    )
    graph_edges = [(index - 1, index) for index in range(1, len(points))]
    for edge in recurrence_edges:
        source = _turn_index(points, str(edge.get("source_turn_id", "")))
        target = _turn_index(points, str(edge.get("target_turn_id", "")))
        if source >= 0 and target >= 0:
            graph_edges.append((source, target))
    components = _component_count(len(points), graph_edges)
    betti1 = max(0, len(graph_edges) - len(points) + components)
    return {
        "mode": "recurrence_graph_cycle_rank_proxy_v1",
        "recurrence_threshold": round(threshold, 4),
        "recurrence_edges": recurrence_edges,
        "loop_candidates": loop_candidates,
        "betti0_proxy": components,
        "betti1_proxy": betti1,
        "torus_candidate": bool(betti1 >= 1 and len(loop_candidates) >= 1),
        "caution": "topology_proxy_requires_more_runs_for_scientific_claims",
    }


def _render_manifold_svg(report: dict[str, Any]) -> str:
    vector_space = dict(report.get("vector_space", {})) if isinstance(report.get("vector_space", {}), dict) else {}
    points = [dict(point) for point in list(vector_space.get("points", []) or []) if isinstance(point, dict)]
    topology = dict(report.get("topology_signature", {})) if isinstance(report.get("topology_signature", {}), dict) else {}
    recurrence_edges = [dict(edge) for edge in list(topology.get("recurrence_edges", []) or []) if isinstance(edge, dict)]
    width = 780
    height = 330
    left = 56
    top = 34
    plot_w = 650
    plot_h = 238
    plotted = []
    for point in points:
        coord = [float(value or 0.0) for value in list(point.get("coordinate", []) or [])[:3]]
        while len(coord) < 3:
            coord.append(0.0)
        x = left + coord[0] * plot_w + coord[2] * 22
        y = top + plot_h - coord[1] * plot_h - coord[2] * 26
        plotted.append((point, x, y, coord[2]))
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Consciousness Manifold Projection">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#fbfbf8" stroke="#d7dddc"/>')
    for index in range(1, len(plotted)):
        _prev_point, prev_x, prev_y, _prev_z = plotted[index - 1]
        _curr_point, curr_x, curr_y, _curr_z = plotted[index]
        parts.append(f'<line x1="{prev_x:.1f}" y1="{prev_y:.1f}" x2="{curr_x:.1f}" y2="{curr_y:.1f}" stroke="#314148" stroke-width="2"/>')
    by_turn = {str(point.get("turn_id", "")): (x, y) for point, x, y, _z in plotted}
    for edge in recurrence_edges:
        start = by_turn.get(str(edge.get("source_turn_id", "")))
        end = by_turn.get(str(edge.get("target_turn_id", "")))
        if start and end:
            parts.append(f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="#b88424" stroke-width="2" stroke-dasharray="5 4"/>')
    for index, (point, x, y, z) in enumerate(plotted):
        radius = 5.5 + 8.0 * z
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{_block_color(point.get("dominant_block", ""))}" stroke="#172026" stroke-width="1.2"/>')
        parts.append(f'<text x="{x + 9:.1f}" y="{y - 7:.1f}" font-size="11" fill="#182026">{index + 1}. {_esc(point.get("turn_id", ""))}</text>')
    parts.append('<text x="510" y="310" font-size="11" fill="#5f6c72">dynamic context / salience</text>')
    parts.append('<text x="60" y="24" font-size="11" fill="#5f6c72">cache / memory control</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _write_manifold_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    vector_space = dict(report.get("vector_space", {})) if isinstance(report.get("vector_space", {}), dict) else {}
    points = [dict(point) for point in list(vector_space.get("points", []) or []) if isinstance(point, dict)]
    topology = dict(report.get("topology_signature", {})) if isinstance(report.get("topology_signature", {}), dict) else {}
    sections = [dict(section) for section in list(report.get("section_family", []) or []) if isinstance(section, dict)]
    coords = numpy.array([list(point.get("coordinate", [0.0, 0.0, 0.0]))[:3] for point in points], dtype=float) if points else numpy.zeros((0, 3))
    fig = pyplot.figure(figsize=(15, 10), dpi=150)
    grid = fig.add_gridspec(2, 1, height_ratios=[1.25, 1.0], hspace=0.42)
    axis = fig.add_subplot(grid[0, 0])
    if len(coords):
        sizes = 90 + coords[:, 2] * 260
        colors = [_block_color(str(point.get("dominant_block", ""))) for point in points]
        axis.plot(coords[:, 0], coords[:, 1], color="#314148", linewidth=1.6, alpha=0.85)
        for edge in topology.get("recurrence_edges", []) or []:
            source = _turn_index(points, str(dict(edge).get("source_turn_id", "")))
            target = _turn_index(points, str(dict(edge).get("target_turn_id", "")))
            if source >= 0 and target >= 0:
                axis.plot([coords[source, 0], coords[target, 0]], [coords[source, 1], coords[target, 1]], color="#b88424", linewidth=1.5, linestyle="--")
        axis.scatter(coords[:, 0], coords[:, 1], s=sizes, c=colors, edgecolors="#172026", linewidths=0.8)
        for index, point in enumerate(points):
            axis.annotate(f"{index + 1}. {point.get('turn_id', '')}", (coords[index, 0], coords[index, 1]), xytext=(6, 4), textcoords="offset points", fontsize=8)
    axis.set_xlim(-0.05, 1.05)
    axis.set_ylim(-0.05, 1.05)
    axis.set_xlabel("dynamic context / salience axis")
    axis.set_ylabel("cache reuse / memory control axis")
    axis.set_title("Stage55 Manifold Projection And Recurrence Edges")
    axis.grid(True, color="#d7dddc", linewidth=0.7, alpha=0.75)

    section_axis = fig.add_subplot(grid[1, 0])
    if sections:
        matrix = numpy.array([list(section.get("trace_values", []) or []) for section in sections], dtype=float)
        image = section_axis.imshow(matrix, aspect="auto", cmap="magma", vmin=0.0, vmax=1.0)
        section_axis.set_yticks(numpy.arange(len(sections)))
        section_axis.set_yticklabels([section.get("name", "") for section in sections])
        section_axis.set_xticks(numpy.arange(len(points)))
        section_axis.set_xticklabels([point.get("turn_id", "") for point in points], rotation=35, ha="right")
        fig.colorbar(image, ax=section_axis, fraction=0.018, pad=0.012, label="section pressure")
    section_axis.set_title("Poincare Section Family")
    fig.suptitle(
        f"Stage55 Consciousness Manifold Observatory | betti1_proxy={topology.get('betti1_proxy', 0)} | loops={len(topology.get('loop_candidates', []) or [])}",
        fontsize=14,
        y=0.992,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _topology_table(topology: dict[str, Any]) -> str:
    loop_rows = []
    for candidate in list(topology.get("loop_candidates", []) or []):
        if isinstance(candidate, dict):
            loop_rows.append(
                f"<tr><td>{_esc(candidate.get('source_turn_id', ''))}</td><td>{_esc(candidate.get('target_turn_id', ''))}</td><td>{_esc(candidate.get('distance', 0))}</td><td>{_esc(candidate.get('path_length', 0))}</td></tr>"
            )
    if not loop_rows:
        loop_rows.append('<tr><td colspan="4">no loop candidates</td></tr>')
    return (
        "<table><tr><th>betti0_proxy</th><th>betti1_proxy</th><th>recurrence_threshold</th><th>torus_candidate</th></tr>"
        f"<tr><td>{_esc(topology.get('betti0_proxy', 0))}</td><td>{_esc(topology.get('betti1_proxy', 0))}</td><td>{_esc(topology.get('recurrence_threshold', 0))}</td><td>{_esc(topology.get('torus_candidate', False))}</td></tr></table>"
        "<table><tr><th>source</th><th>target</th><th>distance</th><th>path_length</th></tr>"
        + "".join(loop_rows)
        + "</table>"
    )


def _section_table(sections: list[dict[str, Any]]) -> str:
    rows = []
    for section in sections:
        rows.append(
            "<tr>"
            f"<td>{_esc(section.get('name', ''))}</td>"
            f"<td>{_esc(', '.join(section.get('axes', []) or []))}</td>"
            f"<td>{_esc(section.get('center', 0))}</td>"
            f"<td>{_esc(section.get('variance', 0))}</td>"
            f"<td>{_esc(', '.join(section.get('piercing_turn_ids', []) or []))}</td>"
            "</tr>"
        )
    return "<table><tr><th>section</th><th>axes</th><th>center</th><th>variance</th><th>piercing turns</th></tr>" + "".join(rows) + "</table>"


def _hyperbolic_table(hyperbolic: dict[str, Any], dynamics: dict[str, Any]) -> str:
    return (
        "<table><tr><th>lyapunov_proxy</th><th>mean_expansion_ratio</th><th>unstable_axis_proxy</th><th>stable_axis_proxy</th><th>path_length</th></tr>"
        f"<tr><td>{_esc(hyperbolic.get('lyapunov_proxy', 0))}</td><td>{_esc(hyperbolic.get('mean_expansion_ratio', 0))}</td><td>{_esc(hyperbolic.get('unstable_axis_proxy', ''))}</td><td>{_esc(hyperbolic.get('stable_axis_proxy', ''))}</td><td>{_esc(dynamics.get('path_length', 0))}</td></tr></table>"
    )


def _compact_observatory_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "vector_space": {key: value for key, value in dict(report.get("vector_space", {})).items() if key != "points"},
        "delay_embedding": {key: value for key, value in dict(report.get("delay_embedding", {})).items() if key != "points"},
        "topology_signature": report.get("topology_signature", {}),
        "hyperbolic_probe": report.get("hyperbolic_probe", {}),
        "boundary": report.get("boundary", {}),
    }


def _project_vector(vector: list[float], axes: list[str]) -> list[float]:
    axis_index = {axis: index for index, axis in enumerate(axes)}

    def group_value(names: tuple[str, ...]) -> float:
        present = [axis_index[name] for name in names if name in axis_index and axis_index[name] < len(vector)]
        if not present:
            return 0.0
        return sum(vector[index] for index in present) / len(present)

    return [
        round(group_value(SECTION_AXIS_GROUPS["dynamic_context_section"]), 4),
        round(group_value(SECTION_AXIS_GROUPS["memory_control_section"]), 4),
        round(group_value(SECTION_AXIS_GROUPS["latency_output_section"]), 4),
    ]


def _section_value_at(section: dict[str, Any], index: int) -> float:
    values = list(section.get("trace_values", []) or [])
    if 0 <= index < len(values):
        return float(values[index] or 0.0)
    return 0.0


def _turn_index(points: list[dict[str, Any]], turn_id: str) -> int:
    for index, point in enumerate(points):
        if str(point.get("turn_id", "")) == turn_id:
            return index
    return -1


def _component_count(node_count: int, edges: list[tuple[int, int]]) -> int:
    if node_count <= 0:
        return 0
    parents = list(range(node_count))

    def find(value: int) -> int:
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parents[root_right] = root_left

    for left, right in edges:
        if 0 <= left < node_count and 0 <= right < node_count:
            union(left, right)
    return len({find(index) for index in range(node_count)})


def _coordinate_distance(a: Any, b: Any) -> float:
    left = [float(value or 0.0) for value in list(a or [])[:3]]
    right = [float(value or 0.0) for value in list(b or [])[:3]]
    while len(left) < 3:
        left.append(0.0)
    while len(right) < 3:
        right.append(0.0)
    return math.sqrt(sum((right[index] - left[index]) ** 2 for index in range(3)))


def _angle_between(a: list[float], b: list[float]) -> float:
    denominator = _vector_norm(a) * _vector_norm(b)
    if denominator <= 0:
        return 0.0
    cosine = max(-1.0, min(1.0, sum(left * right for left, right in zip(a, b)) / denominator))
    return math.acos(cosine)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    denominator = _vector_norm(a) * _vector_norm(b)
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, sum(left * right for left, right in zip(a, b)) / denominator))


def _vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(float(value or 0.0) ** 2 for value in values))


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    center = _mean(values)
    return sum((value - center) ** 2 for value in values) / len(values)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clamp(value: Any) -> float:
    return min(1.0, max(0.0, float(value or 0.0)))


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _block_color(name: Any) -> str:
    return {
        "cache_reuse": "#214e67",
        "dynamic_context": "#2f7d68",
        "memory_control": "#b88424",
        "latency_pressure": "#b05243",
        "output_surface": "#65558f",
    }.get(str(name or ""), "#5f6c72")


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
        import numpy
    except ImportError as exc:
        raise RuntimeError("Stage55 manifold PNG export requires matplotlib and numpy") from exc
    return matplotlib, pyplot, numpy


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
