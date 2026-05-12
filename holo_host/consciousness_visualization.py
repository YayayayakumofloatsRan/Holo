from __future__ import annotations

import html
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


STAGE54_NAME = "stage54-consciousness-flow-visualization"

VISUALIZATION_BOUNDARY = {
    "visualization_only": True,
    "operational_trace_only": True,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}

HEATMAP_AXES = (
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "completion_tokens",
    "latency_ms",
    "provider_prefix_tokens",
    "provider_dynamic_tokens",
    "memory_salience",
    "recall_budget",
    "dynamic_context_lines",
    "dynamic_fusion_saved_lines",
    "consolidation_priority",
    "consciousness_phase_count",
)


def build_consciousness_visualization(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = dict(run_payload or {})
    turns = [dict(turn) for turn in list(run.get("turns", []) or []) if isinstance(turn, dict)]
    rows = [_turn_compute_row(turn, index=index) for index, turn in enumerate(turns)]
    normalized_rows = _normalize_rows(rows)
    attention_blocks = _build_attention_blocks(rows)
    compute_manifold = _build_compute_manifold(normalized_rows, attention_blocks)
    trajectory = _build_attention_trajectory(normalized_rows)
    total_internal = sum(float(row["values"]["internal_tokens"]) for row in rows)
    total_output = sum(float(row["values"]["completion_tokens"]) for row in rows)
    ratio = total_internal / max(1.0, total_output)
    phase_counts = Counter(str(row["dominant_phase"] or "unknown") for row in rows)
    return {
        "stage": STAGE54_NAME,
        "source_stage": str(run.get("stage", "") or ""),
        "suite": str(run.get("suite", "") or ""),
        "run_id": str(run.get("run_id", "") or ""),
        "turn_count": len(rows),
        "summary": {
            "internal_tokens": int(total_internal),
            "output_tokens": int(total_output),
            "internal_output_ratio": round(ratio, 4),
            "internal_token_share": round(total_internal / max(1.0, total_internal + total_output), 4),
            "average_latency_ms": round(_mean([row["values"]["latency_ms"] for row in rows]), 2),
            "average_memory_salience": round(_mean([row["values"]["memory_salience"] for row in rows]), 4),
            "dominant_phases": dict(phase_counts),
        },
        "heatmap": {
            "axes": list(HEATMAP_AXES),
            "rows": normalized_rows,
        },
        "trajectory": trajectory,
        "compute_manifold": compute_manifold,
        "attention_blocks": attention_blocks,
        "scorecard": dict(run.get("scorecard", {})) if isinstance(run.get("scorecard", {}), dict) else {},
        "boundary": dict(VISUALIZATION_BOUNDARY),
    }


def render_consciousness_visualization_html(report: dict[str, Any]) -> str:
    safe_report = dict(report or {})
    title = "Holo Consciousness Flow Map"
    heatmap_svg = _render_heatmap_svg(safe_report)
    trajectory_svg = _render_trajectory_svg(safe_report)
    manifold_svg = _render_compute_manifold_svg(safe_report)
    attention_svg = _render_attention_blocks_svg(safe_report)
    token_svg = _render_token_svg(safe_report)
    summary = dict(safe_report.get("summary", {})) if isinstance(safe_report.get("summary", {}), dict) else {}
    serialized = html.escape(json.dumps(_compact_report_for_html(safe_report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #182026;
      --muted: #5f6c72;
      --line: #d7dddc;
      --panel: #f7f8f5;
      --accent: #2f7d68;
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
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px 24px 36px;
    }}
    section {{
      margin: 22px 0 30px;
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
    <h1>{title}</h1>
    <p class="note">Trace-backed visualization of internal token pressure, memory scheduling, and consciousness-flow movement.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Turns", safe_report.get("turn_count", 0))}
      {_metric("Internal Tokens", summary.get("internal_tokens", 0))}
      {_metric("Output Tokens", summary.get("output_tokens", 0))}
      {_metric("Internal / Output", summary.get("internal_output_ratio", 0))}
      {_metric("Internal Share", summary.get("internal_token_share", 0))}
      {_metric("Avg Latency ms", summary.get("average_latency_ms", 0))}
    </section>
    <section>
      <h2>Compute Distribution Heatmap</h2>
      <p class="note">Rows are dialogue turns; columns are normalized internal compute, cache, memory, and consciousness-flow signals.</p>
      {heatmap_svg}
    </section>
    <section>
      <h2>Attention Vector Trajectory</h2>
      <p class="note">Each point is a deterministic projection of the high-dimensional compute vector for one turn.</p>
      {trajectory_svg}
    </section>
    <section>
      <h2>High-Dimensional Compute Manifold</h2>
      <p class="note">Points preserve the full normalized compute vector in JSON; the SVG is a deterministic 3D projection for inspection.</p>
      {manifold_svg}
    </section>
    <section>
      <h2>Attention Block Allocation</h2>
      <p class="note">Blocks are operational proxies from trace evidence, not provider-native neural attention weights.</p>
      {attention_svg}
    </section>
    <section>
      <h2>Internal Tokens vs Output</h2>
      <p class="note">Large internal-token bars with small output bars are expected for a biomimetic subject kernel.</p>
      {token_svg}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def write_consciousness_visualization_html(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_consciousness_visualization_html(report), encoding="utf-8")
    return path


def write_consciousness_visualization_artifacts(report: dict[str, Any], output_path: str | Path) -> dict[str, Path]:
    html_path = write_consciousness_visualization_html(report, output_path)
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"html": html_path, "json": json_path}


def _turn_compute_row(turn: dict[str, Any], *, index: int) -> dict[str, Any]:
    debug = dict(turn.get("processor_debug", {})) if isinstance(turn.get("processor_debug", {}), dict) else {}
    usage = dict(turn.get("processor_usage", {})) if isinstance(turn.get("processor_usage", {}), dict) else {}
    if not usage:
        usage = dict(debug.get("usage", {})) if isinstance(debug.get("usage", {}), dict) else {}
    partition = dict(debug.get("prompt_partition", {})) if isinstance(debug.get("prompt_partition", {}), dict) else {}
    schedule = dict(debug.get("bionic_memory_schedule", {})) if isinstance(debug.get("bionic_memory_schedule", {}), dict) else {}
    lifecycle = dict(debug.get("bionic_memory_lifecycle", {})) if isinstance(debug.get("bionic_memory_lifecycle", {}), dict) else {}
    flow = dict(debug.get("bionic_consciousness_flow", {})) if isinstance(debug.get("bionic_consciousness_flow", {}), dict) else {}
    prompt_hit = _num(usage.get("prompt_cache_hit_tokens"))
    prompt_miss = _num(usage.get("prompt_cache_miss_tokens"))
    prompt_tokens = _num(usage.get("prompt_tokens")) or prompt_hit + prompt_miss
    prefix_tokens = _num(partition.get("provider_cache_prefix_tokens"))
    dynamic_tokens = _num(partition.get("provider_cache_dynamic_tokens"))
    internal_tokens = max(prompt_tokens, prompt_hit + prompt_miss, prefix_tokens + dynamic_tokens)
    values = {
        "prompt_cache_hit_tokens": prompt_hit,
        "prompt_cache_miss_tokens": prompt_miss,
        "completion_tokens": _num(usage.get("completion_tokens")),
        "latency_ms": _num(turn.get("latency_ms")),
        "provider_prefix_tokens": prefix_tokens,
        "provider_dynamic_tokens": dynamic_tokens,
        "memory_salience": _num(schedule.get("salience_score")),
        "recall_budget": _num(schedule.get("recall_budget")),
        "dynamic_context_lines": _num(schedule.get("dynamic_context_line_count")),
        "dynamic_fusion_saved_lines": _num(schedule.get("dynamic_fusion_saved_line_count")),
        "consolidation_priority": _num(lifecycle.get("consolidation_priority")),
        "consciousness_phase_count": _num(flow.get("phase_count")),
        "internal_tokens": internal_tokens,
    }
    vector = [values[axis] for axis in HEATMAP_AXES]
    return {
        "index": index,
        "turn_id": str(turn.get("turn_id", f"turn_{index + 1}") or f"turn_{index + 1}"),
        "dominant_phase": str(flow.get("dominant_phase", "") or "unknown"),
        "values": values,
        "vector": vector,
    }


def _build_attention_blocks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for row in rows:
        values = dict(row.get("values", {}))
        raw_blocks = [
            (
                "cache_reuse",
                _num(values.get("prompt_cache_hit_tokens")) + _num(values.get("provider_prefix_tokens")),
            ),
            (
                "dynamic_context",
                _num(values.get("prompt_cache_miss_tokens"))
                + _num(values.get("provider_dynamic_tokens"))
                + 32.0 * _num(values.get("dynamic_context_lines")),
            ),
            (
                "memory_control",
                200.0 * _num(values.get("memory_salience"))
                + 80.0 * _num(values.get("recall_budget"))
                + 160.0 * _num(values.get("consolidation_priority"))
                + 30.0 * _num(values.get("consciousness_phase_count"))
                + 24.0 * _num(values.get("dynamic_fusion_saved_lines")),
            ),
            ("latency_pressure", _num(values.get("latency_ms")) / 2.0),
            ("output_surface", _num(values.get("completion_tokens"))),
        ]
        shares = _normalized_shares([value for _name, value in raw_blocks])
        block_rows = [
            {"name": name, "raw": round(float(raw), 4), "share": share}
            for (name, raw), share in zip(raw_blocks, shares)
        ]
        dominant = max(block_rows, key=lambda item: float(item["raw"]))["name"] if block_rows else ""
        internal = _num(values.get("internal_tokens"))
        output = _num(values.get("completion_tokens"))
        blocks.append(
            {
                "turn_id": row.get("turn_id", ""),
                "dominant_phase": row.get("dominant_phase", ""),
                "dominant_block": dominant,
                "internal_share": round(internal / max(1.0, internal + output), 4),
                "blocks": block_rows,
            }
        )
    return blocks


def _build_compute_manifold(rows: list[dict[str, Any]], attention_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    block_by_turn = {str(item.get("turn_id", "")): dict(item) for item in attention_blocks if isinstance(item, dict)}
    for row in rows:
        norm_map = dict(row.get("normalized", {}))
        normalized_vector = [float(norm_map.get(axis, 0.0) or 0.0) for axis in HEATMAP_AXES]
        raw_vector = [float(value or 0.0) for value in row.get("vector", [])]
        x = _clamp01(
            0.28 * norm_map.get("prompt_cache_miss_tokens", 0.0)
            + 0.22 * norm_map.get("provider_dynamic_tokens", 0.0)
            + 0.20 * norm_map.get("memory_salience", 0.0)
            + 0.16 * norm_map.get("recall_budget", 0.0)
            + 0.14 * norm_map.get("dynamic_context_lines", 0.0)
        )
        y = _clamp01(
            0.26 * norm_map.get("prompt_cache_hit_tokens", 0.0)
            + 0.22 * norm_map.get("provider_prefix_tokens", 0.0)
            + 0.20 * norm_map.get("consolidation_priority", 0.0)
            + 0.18 * norm_map.get("dynamic_fusion_saved_lines", 0.0)
            + 0.14 * norm_map.get("consciousness_phase_count", 0.0)
        )
        z = _clamp01(
            0.38 * norm_map.get("latency_ms", 0.0)
            + 0.24 * norm_map.get("completion_tokens", 0.0)
            + 0.20 * norm_map.get("provider_dynamic_tokens", 0.0)
            + 0.18 * norm_map.get("dynamic_context_lines", 0.0)
        )
        block = block_by_turn.get(str(row.get("turn_id", "")), {})
        points.append(
            {
                "turn_id": row.get("turn_id", ""),
                "dominant_phase": row.get("dominant_phase", ""),
                "dominant_block": str(block.get("dominant_block", "") or ""),
                "coordinate": [round(x, 4), round(y, 4), round(z, 4)],
                "raw_vector": [round(value, 4) for value in raw_vector],
                "normalized_vector": [round(value, 4) for value in normalized_vector],
                "raw_norm": round(_vector_norm(raw_vector), 4),
                "normalized_norm": round(_vector_norm(normalized_vector), 4),
            }
        )
    edges: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        prev = points[index - 1]
        curr = points[index]
        prev_vector = [float(value) for value in prev.get("normalized_vector", [])]
        curr_vector = [float(value) for value in curr.get("normalized_vector", [])]
        delta = [curr_value - prev_value for prev_value, curr_value in zip(prev_vector, curr_vector)]
        edges.append(
            {
                "source_turn_id": prev.get("turn_id", ""),
                "target_turn_id": curr.get("turn_id", ""),
                "delta_vector": [round(value, 4) for value in delta],
                "delta_norm": round(_vector_norm(delta), 4),
                "cosine_similarity": round(_cosine_similarity(prev_vector, curr_vector), 4),
                "movement": round(_coordinate_distance(prev.get("coordinate", []), curr.get("coordinate", [])), 4),
            }
        )
    centroid = []
    if points:
        for axis_index in range(len(HEATMAP_AXES)):
            centroid.append(
                round(
                    sum(float(point["normalized_vector"][axis_index]) for point in points) / len(points),
                    4,
                )
            )
    return {
        "projection": "deterministic_stage54_compute_manifold_v1",
        "axes": list(HEATMAP_AXES),
        "points": points,
        "edges": edges,
        "centroid": centroid,
        "note": "Operational trace projection; not provider-native attention weights.",
    }


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mins = {axis: min([row["values"][axis] for row in rows], default=0.0) for axis in HEATMAP_AXES}
    maxs = {axis: max([row["values"][axis] for row in rows], default=0.0) for axis in HEATMAP_AXES}
    normalized: list[dict[str, Any]] = []
    for row in rows:
        norm = {}
        for axis in HEATMAP_AXES:
            low = mins[axis]
            high = maxs[axis]
            norm[axis] = 0.0 if high <= low else round((row["values"][axis] - low) / (high - low), 4)
        normalized.append({**row, "normalized": norm})
    return normalized


def _build_attention_trajectory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    previous: tuple[float, float, float] | None = None
    for row in rows:
        norm = dict(row.get("normalized", {}))
        x = 40 + 660 * min(1.0, max(0.0, 0.35 * norm.get("prompt_cache_miss_tokens", 0.0) + 0.25 * norm.get("provider_dynamic_tokens", 0.0) + 0.25 * norm.get("memory_salience", 0.0) + 0.15 * norm.get("recall_budget", 0.0)))
        y = 260 - 210 * min(1.0, max(0.0, 0.30 * norm.get("prompt_cache_hit_tokens", 0.0) + 0.25 * norm.get("consolidation_priority", 0.0) + 0.25 * norm.get("consciousness_phase_count", 0.0) + 0.20 * norm.get("dynamic_fusion_saved_lines", 0.0)))
        z = min(1.0, max(0.0, 0.45 * norm.get("latency_ms", 0.0) + 0.30 * norm.get("dynamic_context_lines", 0.0) + 0.25 * norm.get("completion_tokens", 0.0)))
        current = (x, y, z)
        movement = 0.0
        if previous is not None:
            movement = ((x - previous[0]) ** 2 + (y - previous[1]) ** 2 + ((z - previous[2]) * 200) ** 2) ** 0.5
        previous = current
        points.append(
            {
                "turn_id": row["turn_id"],
                "dominant_phase": row["dominant_phase"],
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 4),
                "movement": round(movement, 4),
                "vector": [round(float(value), 4) for value in row.get("vector", [])],
            }
        )
    return {"projection": "deterministic_stage54_v1", "points": points}


def _render_heatmap_svg(report: dict[str, Any]) -> str:
    rows = list(dict(report.get("heatmap", {})).get("rows", []) or [])
    axes = list(dict(report.get("heatmap", {})).get("axes", []) or [])
    left = 150
    top = 72
    cell_w = 66
    cell_h = 28
    width = left + len(axes) * cell_w + 30
    height = top + max(1, len(rows)) * cell_h + 42
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Compute Distribution Heatmap">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    for col, axis in enumerate(axes):
        x = left + col * cell_w + 8
        parts.append(f'<text x="{x}" y="18" font-size="9" fill="#314148" transform="rotate(-38 {x} 18)">{_esc(axis)}</text>')
    for row_index, row in enumerate(rows):
        y = top + row_index * cell_h
        parts.append(f'<text x="12" y="{y + 18}" font-size="11" fill="#314148">{_esc(row.get("turn_id", ""))}</text>')
        normalized = dict(row.get("normalized", {}))
        values = dict(row.get("values", {}))
        for col, axis in enumerate(axes):
            value = float(normalized.get(axis, 0.0) or 0.0)
            x = left + col * cell_w
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 3}" height="{cell_h - 3}" rx="2" fill="{_heat_color(value)}"/>')
            raw = values.get(axis, 0)
            label = f"{raw:.1f}" if isinstance(raw, float) and not raw.is_integer() else str(int(raw)) if isinstance(raw, (int, float)) else str(raw)
            parts.append(f'<text x="{x + 5}" y="{y + 17}" font-size="9" fill="{_heat_text_color(value)}">{_esc(label)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_trajectory_svg(report: dict[str, Any]) -> str:
    points = list(dict(report.get("trajectory", {})).get("points", []) or [])
    width = 780
    height = 320
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Attention Vector Trajectory">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<line x1="40" y1="260" x2="730" y2="260" stroke="#b8c5c2" stroke-width="1"/>')
    parts.append('<line x1="40" y1="40" x2="40" y2="260" stroke="#b8c5c2" stroke-width="1"/>')
    for idx in range(1, len(points)):
        prev = points[idx - 1]
        curr = points[idx]
        parts.append(
            f'<line x1="{prev["x"]}" y1="{prev["y"]}" x2="{curr["x"]}" y2="{curr["y"]}" stroke="#2f7d68" stroke-width="2.5"/>'
        )
    for idx, point in enumerate(points):
        radius = 5 + 6 * float(point.get("z", 0.0) or 0.0)
        parts.append(f'<circle cx="{point["x"]}" cy="{point["y"]}" r="{radius:.1f}" fill="#f3c244" stroke="#214e67" stroke-width="1.5"/>')
        parts.append(f'<text x="{point["x"] + 9}" y="{point["y"] - 7}" font-size="11" fill="#182026">{idx + 1}. {_esc(point.get("turn_id", ""))}</text>')
        parts.append(f'<text x="{point["x"] + 9}" y="{point["y"] + 7}" font-size="9" fill="#5f6c72">{_esc(point.get("dominant_phase", ""))}</text>')
    parts.append('<text x="560" y="292" font-size="11" fill="#5f6c72">dynamic pressure / salience</text>')
    parts.append('<text x="50" y="32" font-size="11" fill="#5f6c72">cache reuse / consolidation</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_compute_manifold_svg(report: dict[str, Any]) -> str:
    manifold = dict(report.get("compute_manifold", {})) if isinstance(report.get("compute_manifold", {}), dict) else {}
    points = [dict(point) for point in list(manifold.get("points", []) or []) if isinstance(point, dict)]
    width = 780
    height = 340
    left = 58
    top = 36
    plot_w = 650
    plot_h = 238
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="High-Dimensional Compute Manifold">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#fbfbf8" stroke="#d7dddc"/>')
    parts.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w + 25}" y2="{top + plot_h - 28}" stroke="#b8c5c2" stroke-width="1"/>')
    parts.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left}" y2="{top - 8}" stroke="#b8c5c2" stroke-width="1"/>')
    parts.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#b8c5c2" stroke-width="1"/>')
    plotted = []
    for point in points:
        coord = [float(value or 0.0) for value in list(point.get("coordinate", []) or [])[:3]]
        while len(coord) < 3:
            coord.append(0.0)
        x = left + coord[0] * plot_w + coord[2] * 25
        y = top + plot_h - coord[1] * plot_h - coord[2] * 28
        plotted.append((point, x, y, coord[2]))
    for index in range(1, len(plotted)):
        _prev_point, prev_x, prev_y, _prev_z = plotted[index - 1]
        _curr_point, curr_x, curr_y, _curr_z = plotted[index]
        parts.append(f'<line x1="{prev_x:.1f}" y1="{prev_y:.1f}" x2="{curr_x:.1f}" y2="{curr_y:.1f}" stroke="#314148" stroke-width="2"/>')
    for index, (point, x, y, z) in enumerate(plotted):
        radius = 5.5 + 8.0 * z
        color = _block_color(str(point.get("dominant_block", "") or ""))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" stroke="#172026" stroke-width="1.2"/>')
        parts.append(f'<text x="{x + 10:.1f}" y="{y - 8:.1f}" font-size="11" fill="#182026">{index + 1}. {_esc(point.get("turn_id", ""))}</text>')
        parts.append(f'<text x="{x + 10:.1f}" y="{y + 7:.1f}" font-size="9" fill="#5f6c72">{_esc(point.get("dominant_block", ""))}</text>')
    parts.append('<text x="514" y="314" font-size="11" fill="#5f6c72">dynamic context / salience</text>')
    parts.append('<text x="64" y="24" font-size="11" fill="#5f6c72">cache reuse / consolidation</text>')
    parts.append('<text x="605" y="281" font-size="11" fill="#5f6c72">z: latency / output pressure</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_attention_blocks_svg(report: dict[str, Any]) -> str:
    rows = [dict(row) for row in list(report.get("attention_blocks", []) or []) if isinstance(row, dict)]
    width = 780
    row_h = 42
    height = 62 + max(1, len(rows)) * row_h
    left = 156
    bar_w = 540
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Attention Block Allocation">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text x="156" y="24" font-size="12" fill="#314148">cache</text>')
    parts.append('<text x="260" y="24" font-size="12" fill="#314148">dynamic</text>')
    parts.append('<text x="382" y="24" font-size="12" fill="#314148">memory</text>')
    parts.append('<text x="500" y="24" font-size="12" fill="#314148">latency</text>')
    parts.append('<text x="610" y="24" font-size="12" fill="#314148">output</text>')
    for row_index, row in enumerate(rows):
        y = 48 + row_index * row_h
        parts.append(f'<text x="12" y="{y + 15}" font-size="11" fill="#314148">{_esc(row.get("turn_id", ""))}</text>')
        x = left
        for block in [dict(item) for item in list(row.get("blocks", []) or []) if isinstance(item, dict)]:
            share = min(1.0, max(0.0, float(block.get("share", 0.0) or 0.0)))
            block_w = bar_w * share
            name = str(block.get("name", "") or "")
            parts.append(f'<rect x="{x:.1f}" y="{y}" width="{block_w:.1f}" height="18" rx="2" fill="{_block_color(name)}"/>')
            if block_w >= 52:
                parts.append(f'<text x="{x + 5:.1f}" y="{y + 13}" font-size="9" fill="#ffffff">{_esc(name)} {_esc(round(share, 2))}</text>')
            x += block_w
        parts.append(f'<text x="{left}" y="{y + 34}" font-size="9" fill="#5f6c72">dominant={_esc(row.get("dominant_block", ""))}; internal_share={_esc(row.get("internal_share", 0))}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_token_svg(report: dict[str, Any]) -> str:
    rows = list(dict(report.get("heatmap", {})).get("rows", []) or [])
    width = 780
    row_h = 34
    height = 55 + max(1, len(rows)) * row_h
    max_total = max([float(row["values"]["internal_tokens"] + row["values"]["completion_tokens"]) for row in rows], default=1.0)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Internal Tokens vs Output">']
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text x="150" y="22" font-size="12" fill="#314148">internal prompt/cache/context tokens</text>')
    parts.append('<text x="540" y="22" font-size="12" fill="#314148">output tokens</text>')
    for idx, row in enumerate(rows):
        y = 45 + idx * row_h
        internal = float(row["values"]["internal_tokens"])
        output = float(row["values"]["completion_tokens"])
        internal_w = 520 * internal / max_total
        output_w = 520 * output / max_total
        parts.append(f'<text x="12" y="{y + 15}" font-size="11" fill="#314148">{_esc(row.get("turn_id", ""))}</text>')
        parts.append(f'<rect x="150" y="{y}" width="{internal_w:.1f}" height="14" rx="2" fill="#2f7d68"/>')
        parts.append(f'<rect x="{150 + internal_w:.1f}" y="{y}" width="{output_w:.1f}" height="14" rx="2" fill="#d05f3f"/>')
        parts.append(f'<text x="150" y="{y + 28}" font-size="9" fill="#5f6c72">{int(internal)} / {int(output)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _compact_report_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "suite": report.get("suite", ""),
        "run_id": report.get("run_id", ""),
        "summary": report.get("summary", {}),
        "trajectory": report.get("trajectory", {}),
        "compute_manifold": report.get("compute_manifold", {}),
        "attention_blocks": report.get("attention_blocks", []),
        "boundary": report.get("boundary", {}),
    }


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'


def _heat_color(value: float) -> str:
    value = min(1.0, max(0.0, float(value or 0.0)))
    if value < 0.5:
        ratio = value / 0.5
        return _mix_color((33, 78, 103), (54, 163, 106), ratio)
    return _mix_color((54, 163, 106), (243, 194, 68), (value - 0.5) / 0.5)


def _mix_color(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> str:
    r = int(a[0] + (b[0] - a[0]) * ratio)
    g = int(a[1] + (b[1] - a[1]) * ratio)
    b_val = int(a[2] + (b[2] - a[2]) * ratio)
    return f"#{r:02x}{g:02x}{b_val:02x}"


def _heat_text_color(value: float) -> str:
    return "#ffffff" if float(value or 0.0) < 0.55 else "#172026"


def _block_color(name: str) -> str:
    return {
        "cache_reuse": "#214e67",
        "dynamic_context": "#2f7d68",
        "memory_control": "#b88424",
        "latency_pressure": "#b05243",
        "output_surface": "#65558f",
    }.get(str(name or ""), "#5f6c72")


def _normalized_shares(values: list[float]) -> list[float]:
    cleaned = [max(0.0, float(value or 0.0)) for value in values]
    total = sum(cleaned)
    if total <= 0:
        if not cleaned:
            return []
        return [1.0] + [0.0 for _value in cleaned[1:]]
    shares: list[float] = []
    running = 0.0
    for index, value in enumerate(cleaned):
        if index == len(cleaned) - 1:
            share = round(max(0.0, 1.0 - running), 4)
        else:
            share = round(value / total, 4)
            running += share
        shares.append(share)
    return shares


def _vector_norm(values: list[float]) -> float:
    return math.sqrt(sum(float(value or 0.0) ** 2 for value in values))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    numerator = sum(float(left or 0.0) * float(right or 0.0) for left, right in zip(a, b))
    denominator = _vector_norm(a) * _vector_norm(b)
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _coordinate_distance(a: list[Any], b: list[Any]) -> float:
    left = [float(value or 0.0) for value in list(a or [])[:3]]
    right = [float(value or 0.0) for value in list(b or [])[:3]]
    while len(left) < 3:
        left.append(0.0)
    while len(right) < 3:
        right.append(0.0)
    return math.sqrt(sum((right[index] - left[index]) ** 2 for index in range(3)))


def _clamp01(value: Any) -> float:
    return min(1.0, max(0.0, float(value or 0.0)))


def _num(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    cleaned = [float(value) for value in values if isinstance(value, (int, float))]
    if not cleaned:
        return 0.0
    return sum(cleaned) / len(cleaned)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
