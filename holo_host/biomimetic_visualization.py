from __future__ import annotations

import html
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .biomimetic_telemetry import load_biomimetic_frames
from .memory_doctor import memory_doctor_report
from .memory_promotion import plan_ready_candidates

MEMORY_DIR = Path("holo_memory_library") / "memories"
RUNTIME_DIR = Path(".holo_runtime")
DEFAULT_OUTPUT_DIR = Path("artifacts") / "stage100"


def _parse_timestamp(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat().replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "updated_at", "timestamp", "ts"):
        parsed = _parse_timestamp(row.get(key))
        if parsed is not None:
            return parsed
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        for key in ("created_at", "updated_at", "timestamp", "ts"):
            parsed = _parse_timestamp(metadata.get(key))
            if parsed is not None:
                return parsed
    return None


def _extract_timing_ms(row: dict[str, Any]) -> int:
    metadata = row.get("metadata")
    timing = metadata.get("timing_ms") if isinstance(metadata, dict) else None
    if isinstance(timing, dict):
        return int(max(0, _safe_float(timing.get("total_ms"), 0.0)))
    return 0


def _extract_route(row: dict[str, Any]) -> str:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        route = str(metadata.get("route", "") or "").strip()
        if route:
            return route
    return str(row.get("route", "") or "").strip() or "unknown"


def _extract_affect(row: dict[str, Any]) -> dict[str, float]:
    metadata = row.get("metadata")
    affect = metadata.get("affect_state") if isinstance(metadata, dict) else None
    if not isinstance(affect, dict):
        affect = {}
    route = _extract_route(row)
    timing_ms = _extract_timing_ms(row)
    selected_count = 0
    if isinstance(metadata, dict) and isinstance(metadata.get("selected_memory_ids"), list):
        selected_count = len(metadata.get("selected_memory_ids", []))
    valence = _safe_float(affect.get("valence"), 0.5)
    arousal = _safe_float(affect.get("arousal"), 0.15)
    control = _safe_float(affect.get("control", affect.get("dominance")), 0.55)
    memory_pressure = _clamp(selected_count / 8.0 + (0.35 if route in {"recall", "deep_recall"} else 0.0))
    latency_pressure = _clamp(math.log1p(timing_ms) / math.log1p(300_000)) if timing_ms > 0 else 0.0
    deep_recall = 1.0 if route == "deep_recall" else 0.0
    return {
        "valence": round(_clamp(valence), 4),
        "arousal": round(_clamp(arousal + latency_pressure * 0.25), 4),
        "control": round(_clamp(control - latency_pressure * 0.18), 4),
        "memory_pressure": round(memory_pressure, 4),
        "latency_pressure": round(latency_pressure, 4),
        "deep_recall": deep_recall,
        "regulation": round(_clamp(control - arousal * 0.35 + valence * 0.2), 4),
    }


def _projection(values: dict[str, float], index: int) -> dict[str, float]:
    x = values["memory_pressure"] * 0.5 + values["deep_recall"] * 0.3 + (index % 7) * 0.015
    y = values["arousal"] * 0.45 + (1.0 - values["control"]) * 0.25 + values["latency_pressure"] * 0.25
    z = values["valence"] * 0.35 + values["regulation"] * 0.45
    return {"x": round(_clamp(x), 4), "y": round(_clamp(y), 4), "z": round(_clamp(z), 4)}


def _trajectory_frames(repo_root: Path, limit: int = 360) -> list[dict[str, Any]]:
    rows = _iter_jsonl(repo_root / MEMORY_DIR / "conversation_archive.jsonl")
    rows = sorted(rows, key=lambda row: _row_time(row) or datetime.min.replace(tzinfo=timezone.utc))[-limit:]
    frames: list[dict[str, Any]] = []
    previous_projection: dict[str, float] | None = None
    for index, row in enumerate(rows):
        values = _extract_affect(row)
        projection = _projection(values, index)
        if previous_projection is None:
            delta = 0.0
        else:
            delta = math.sqrt(
                (projection["x"] - previous_projection["x"]) ** 2
                + (projection["y"] - previous_projection["y"]) ** 2
                + (projection["z"] - previous_projection["z"]) ** 2
            )
        previous_projection = projection
        frames.append(
            {
                "index": index,
                "id": str(row.get("id", "") or f"frame-{index}"),
                "timestamp": _timestamp_text(_row_time(row)),
                "channel": str(row.get("channel", "") or ""),
                "thread_key": str(row.get("thread_key", "") or ""),
                "route": _extract_route(row),
                "latency_ms": _extract_timing_ms(row),
                "values": values,
                "projection": projection,
                "delta_from_previous": round(delta, 4),
            }
        )
    return frames


def _telemetry_trajectory_frames(repo_root: Path, limit: int = 2400) -> list[dict[str, Any]]:
    telemetry_rows = load_biomimetic_frames(repo_root, limit=limit)
    simulation_rows = [row for row in telemetry_rows if isinstance(row.get("simulation"), dict) and str(row.get("simulation", {}).get("batch_id", "") or "")]
    if simulation_rows:
        latest_batch = str(simulation_rows[-1].get("simulation", {}).get("batch_id", "") or "")
        telemetry_rows = [row for row in simulation_rows if str(row.get("simulation", {}).get("batch_id", "") or "") == latest_batch]
    frames: list[dict[str, Any]] = []
    previous_projection: dict[str, float] | None = None

    def append_frame(frame: dict[str, Any]) -> None:
        nonlocal previous_projection
        projection = frame["projection"]
        if previous_projection is None:
            delta = 0.0
        else:
            delta = math.sqrt(
                (_safe_float(projection.get("x")) - _safe_float(previous_projection.get("x"))) ** 2
                + (_safe_float(projection.get("y")) - _safe_float(previous_projection.get("y"))) ** 2
                + (_safe_float(projection.get("z")) - _safe_float(previous_projection.get("z"))) ** 2
            )
        frame["delta_from_previous"] = round(delta, 4)
        previous_projection = dict(projection)
        frame["index"] = len(frames)
        frames.append(frame)

    for index, row in enumerate(telemetry_rows):
        vector = row.get("vector", {}) if isinstance(row.get("vector"), dict) else {}
        values = vector.get("values", {}) if isinstance(vector.get("values"), dict) else {}
        projection = vector.get("projection", {}) if isinstance(vector.get("projection"), dict) else {}
        if not values or not projection:
            continue
        observables = row.get("observables", {}) if isinstance(row.get("observables"), dict) else {}
        context = row.get("context", {}) if isinstance(row.get("context"), dict) else {}
        simulation = row.get("simulation", {}) if isinstance(row.get("simulation"), dict) else {}
        base_values = {str(key): round(_safe_float(value), 4) for key, value in values.items()}
        base_projection = {str(key): round(_safe_float(value), 4) for key, value in projection.items()}
        row_id = str(row.get("id", "") or f"telemetry-{index}")
        append_frame(
            {
                "id": row_id,
                "timestamp": str(row.get("created_at", "") or ""),
                "channel": str(context.get("channel", "") or ""),
                "thread_key": str(context.get("thread_key", "") or ""),
                "route": str(observables.get("route", "") or row.get("event_type", "unknown")),
                "latency_ms": int(dict(observables.get("timing_ms", {}) if isinstance(observables.get("timing_ms"), dict) else {}).get("total_ms", 0) or 0),
                "values": base_values,
                "projection": base_projection,
                "event_type": str(row.get("event_type", "") or ""),
                "simulation_batch_id": str(simulation.get("batch_id", "") or ""),
                "category": str(simulation.get("category", "") or ""),
                "topic": str(simulation.get("topic", "") or ""),
            }
        )
        recall_trajectory = row.get("recall_trajectory", {}) if isinstance(row.get("recall_trajectory"), dict) else {}
        is_simulation = bool(str(simulation.get("batch_id", "") or ""))
        stages = [item for item in recall_trajectory.get("stages", []) if isinstance(item, dict)]
        stage_limit = 3 if is_simulation else 32
        for candidate in stages[:stage_limit]:
            stage = str(candidate.get("stage", "") or "")
            node_hash = str(candidate.get("node_hash", "") or "")
            if not stage or not node_hash:
                continue
            score = max(0.0, _safe_float(candidate.get("score"), 0.0))
            score_norm = _clamp(score / 2.6)
            if is_simulation:
                stage_offset = {"graph": 0.008, "vector": 0.018, "rerank": 0.032, "activation": 0.014}.get(stage, 0.006)
                score_scale = 0.035
                y_rank_scale = 0.002
            else:
                stage_offset = {"graph": 0.04, "vector": 0.12, "rerank": 0.2, "activation": 0.08}.get(stage, 0.02)
                score_scale = 0.16
                y_rank_scale = 0.012
            rank = max(0, int(_safe_float(candidate.get("rank"), 0)))
            micro_values = dict(base_values)
            micro_values["memory_pressure"] = round(_clamp(_safe_float(micro_values.get("memory_pressure"), 0.0) + score_norm * (0.08 if is_simulation else 0.26)), 4)
            micro_values["arousal"] = round(_clamp(_safe_float(micro_values.get("arousal"), 0.0) + stage_offset * 0.25), 4)
            micro_values["control"] = round(_clamp(_safe_float(micro_values.get("control"), 0.55) - stage_offset * 0.08), 4)
            micro_projection = {
                "x": round(_clamp(_safe_float(base_projection.get("x"), 0.0) + score_norm * score_scale + stage_offset), 4),
                "y": round(_clamp(_safe_float(base_projection.get("y"), 0.0) + stage_offset * 0.18 + min(rank, 10) * y_rank_scale), 4),
                "z": round(_clamp(_safe_float(base_projection.get("z"), 0.0) + (0.008 if is_simulation and stage == "rerank" else 0.04 if stage == "rerank" else 0.006 if is_simulation else 0.015)), 4),
            }
            append_frame(
                {
                    "id": f"{row_id}:{stage}:{rank}:{node_hash}",
                    "timestamp": str(row.get("created_at", "") or ""),
                    "channel": str(context.get("channel", "") or ""),
                    "thread_key": str(context.get("thread_key", "") or ""),
                    "route": str(observables.get("route", "") or row.get("event_type", "unknown")),
                    "latency_ms": 0,
                    "values": micro_values,
                    "projection": micro_projection,
                    "event_type": str(row.get("event_type", "") or ""),
                    "simulation_batch_id": str(simulation.get("batch_id", "") or ""),
                    "category": str(simulation.get("category", "") or ""),
                    "topic": str(simulation.get("topic", "") or ""),
                    "recall_stage": stage,
                    "candidate_hash": node_hash,
                    "recall_score": round(score, 4),
                    "memory_class": str(candidate.get("memory_class", "") or ""),
                }
            )
    return frames


def _simulation_summary(frames: list[dict[str, Any]]) -> dict[str, Any]:
    sim_frames = [frame for frame in frames if str(frame.get("simulation_batch_id", "") or "")]
    if not sim_frames:
        return {
            "available": False,
            "latest_batch_id": "",
            "category_count": 0,
            "topic_count": 0,
            "categories": {},
            "topics": {},
            "continuity": {"frame_count": 0, "max_delta": 0.0, "mean_delta": 0.0, "large_jump_threshold": 0.22, "large_jump_count": 0},
        }
    deltas = [float(frame.get("delta_from_previous", 0.0) or 0.0) for frame in sim_frames[1:]]
    categories = Counter(str(frame.get("category", "") or "unknown") for frame in sim_frames)
    topics = Counter(str(frame.get("topic", "") or "unknown") for frame in sim_frames)
    return {
        "available": True,
        "latest_batch_id": str(sim_frames[-1].get("simulation_batch_id", "") or ""),
        "category_count": len(categories),
        "topic_count": len(topics),
        "categories": dict(sorted(categories.items())),
        "topics": dict(sorted(topics.items())),
        "continuity": {
            "frame_count": len(sim_frames),
            "max_delta": round(max(deltas), 4) if deltas else 0.0,
            "mean_delta": round(sum(deltas) / len(deltas), 4) if deltas else 0.0,
            "large_jump_threshold": 0.22,
            "large_jump_count": sum(1 for delta in deltas if delta > 0.22),
        },
    }


def _sqlite_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0) as connection:
            for (table,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ):
                try:
                    counts[str(table)] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                except sqlite3.Error:
                    counts[str(table)] = -1
    except sqlite3.Error:
        return {}
    return counts


def _mind_graph_samples(repo_root: Path, limit: int = 80) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    db_path = repo_root / RUNTIME_DIR / "mind_graph.sqlite3"
    if not db_path.exists():
        return [], []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0) as connection:
            connection.row_factory = sqlite3.Row
            table_names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if "mind_nodes" in table_names:
                for row in connection.execute("SELECT * FROM mind_nodes LIMIT ?", (limit,)).fetchall():
                    row_dict = dict(row)
                    node_id = str(row_dict.get("id", "") or row_dict.get("node_id", "") or f"node-{len(nodes)}")
                    nodes.append(
                        {
                            "id": f"graph:{node_id}",
                            "label": str(row_dict.get("kind", "") or row_dict.get("type", "") or "mind_node"),
                            "layer": "mind_graph",
                            "value": 0.55,
                            "source_id": node_id,
                        }
                    )
            if "mind_edges" in table_names:
                for row in connection.execute("SELECT * FROM mind_edges LIMIT ?", (limit,)).fetchall():
                    row_dict = dict(row)
                    source = str(row_dict.get("source_id", "") or row_dict.get("source", "") or "")
                    target = str(row_dict.get("target_id", "") or row_dict.get("target", "") or "")
                    if not source or not target:
                        continue
                    edges.append(
                        {
                            "source": f"graph:{source}",
                            "target": f"graph:{target}",
                            "type": str(row_dict.get("edge_type", "") or row_dict.get("type", "") or "graph_edge"),
                            "weight": round(_clamp(_safe_float(row_dict.get("weight"), 0.35)), 4),
                            "layer": "mind_graph",
                        }
                    )
    except sqlite3.Error:
        return nodes, edges
    return nodes, edges


def _system_topology(repo_root: Path, doctor: dict[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    layers = ["memory", "route", "health", "mind_graph", "vector", "trajectory", "topic"]

    def add_node(node_id: str, label: str, layer: str, value: float, group: str = "") -> None:
        nodes.append({"id": node_id, "label": label, "layer": layer, "value": round(_clamp(value), 4), "group": group or layer})

    def add_edge(source: str, target: str, edge_type: str, weight: float, layer: str) -> None:
        edges.append({"source": source, "target": target, "type": edge_type, "weight": round(_clamp(weight), 4), "layer": layer})

    add_node("subject", "subject kernel", "health", 0.95, "core")
    jsonl = doctor.get("jsonl_stores", {})
    for store, report in jsonl.items():
        rows = int(report.get("valid_rows", 0) or 0)
        value = _clamp(math.log1p(rows) / math.log1p(1000))
        node_id = f"store:{store}"
        add_node(node_id, store.replace(".jsonl", ""), "memory", value, "memory")
        add_edge(node_id, "subject", "feeds", max(0.08, value), "memory")

    route_counts = Counter(str(frame.get("route", "unknown")) for frame in frames)
    for route, count in route_counts.items():
        node_id = f"route:{route}"
        value = _clamp(count / max(1, len(frames)))
        add_node(node_id, route, "route", value, "route")
        add_edge("subject", node_id, "selected_route", max(0.1, value), "route")

    category_counts = Counter(str(frame.get("category", "") or "") for frame in frames if str(frame.get("category", "") or ""))
    topic_counts = Counter((str(frame.get("category", "") or ""), str(frame.get("topic", "") or "")) for frame in frames if str(frame.get("topic", "") or ""))
    for category, count in category_counts.items():
        node_id = f"category:{category}"
        value = _clamp(count / max(1, len(frames)))
        add_node(node_id, category, "topic", value, "topic")
        add_edge("subject", node_id, "simulates_category", max(0.12, value), "topic")
    for (category, topic), count in topic_counts.items():
        node_id = f"topic:{category}:{topic}"
        value = _clamp(count / max(1, len(frames)))
        add_node(node_id, topic, "topic", value, "topic")
        add_edge(f"category:{category}", node_id, "contains_topic", max(0.1, value), "topic")

    for key, item in doctor.get("biomimetic_health", {}).items():
        status = str(item.get("status", "unknown"))
        value = {"ok": 0.25, "unknown": 0.45, "warn": 0.72, "critical": 0.95}.get(status, 0.5)
        node_id = f"health:{key}"
        add_node(node_id, f"{key}:{status}", "health", value, "health")
        add_edge(node_id, "subject", "pressure", value, "health")

    vector = doctor.get("vector", {}).get("static_probe", {})
    add_node("vector:index", "vector index", "vector", 0.75 if vector.get("exists") else 0.25, "vector")
    add_edge("store:memory_store.jsonl", "vector:index", "embeds", 0.62 if vector.get("exists") else 0.15, "vector")

    for index, frame in enumerate(frames[-80:]):
        node_id = f"frame:{frame['index']}"
        value = _clamp(float(frame.get("delta_from_previous", 0.0) or 0.0) * 3.0 + 0.12)
        add_node(node_id, f"t{frame['index']}:{frame.get('route', '')}", "trajectory", value, "trajectory")
        if index > 0:
            previous = frames[-80:][index - 1]
            add_edge(f"frame:{previous['index']}", node_id, "temporal_transition", value, "trajectory")
        add_edge(node_id, f"route:{frame.get('route', 'unknown')}", "route_at_frame", 0.35, "trajectory")
        if frame.get("topic") and frame.get("category"):
            add_edge(node_id, f"topic:{frame.get('category')}:{frame.get('topic')}", "topic_at_frame", 0.28, "topic")

    graph_nodes, graph_edges = _mind_graph_samples(repo_root)
    nodes.extend(graph_nodes)
    edges.extend(graph_edges)
    for graph_node in graph_nodes[:40]:
        add_edge("subject", graph_node["id"], "activates_graph", 0.25, "mind_graph")

    return {"layers": layers, "nodes": nodes, "edges": edges}


def _safe_promotion_plan(repo_root: Path) -> dict[str, Any]:
    try:
        import importlib.util

        rag_path = repo_root / "holo_memory_library" / "rag_memory.py"
        spec = importlib.util.spec_from_file_location("holo_visualization_rag_memory", rag_path)
        if spec is None or spec.loader is None:
            return {"status": "missing"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return plan_ready_candidates(module, limit=8)
    except Exception as exc:
        return {"status": "error", "error": str(exc), "privacy": {"raw_text_included": False}}


def build_biomimetic_visualization_payload(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    doctor = memory_doctor_report(root)
    frames = _telemetry_trajectory_frames(root)
    simulation = _simulation_summary(frames)
    trajectory_source = "biomimetic_simulation" if simulation["available"] else ("biomimetic_telemetry" if frames else "conversation_archive_proxy")
    if not frames:
        frames = _trajectory_frames(root)
        simulation = _simulation_summary(frames)
    topology = _system_topology(root, doctor, frames)
    promotion = _safe_promotion_plan(root)
    sqlite_counts = _sqlite_counts(root / RUNTIME_DIR / "mind_graph.sqlite3")
    route_latency = doctor.get("reply_route_latency", {})
    return {
        "schema": "holo.biomimetic_visualization.v1",
        "title": "Holo Biomimetic Memory Dynamics Workbench",
        "generated_from": str(root),
        "privacy": {
            "raw_text_included": False,
            "redaction_policy": "turn text, memory text, graph labels, and provider content are not emitted",
        },
        "trajectory": {
            "source": trajectory_source,
            "component_keys": ["valence", "arousal", "control", "memory_pressure", "latency_pressure", "deep_recall", "health_pressure", "regulation"],
            "frames": frames,
        },
        "simulation": simulation,
        "topology": topology,
        "doctor": doctor,
        "promotion_plan": promotion,
        "graph_counts": sqlite_counts,
        "route_latency": route_latency,
        "paper_claim_boundary": {
            "observable_proxy_only": True,
            "no_hidden_reasoning_claim": True,
            "no_real_emotion_claim": True,
            "no_biological_brain_state_claim": True,
        },
    }


def _json_script(payload: dict[str, Any]) -> str:
    return html.escape(json.dumps(payload, ensure_ascii=False), quote=False)


def render_biomimetic_visualization_html(payload: dict[str, Any]) -> str:
    payload_json = _json_script(payload)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Biomimetic Memory Dynamics Workbench</title>
  <style>
    :root {{
      --bg: #f5f7f4;
      --ink: #18201f;
      --muted: #61706c;
      --line: #cfd8d3;
      --panel: #ffffff;
      --accent: #356f8a;
      --affect: #b6534f;
      --memory: #4d7f53;
      --warn: #b67b2d;
      --critical: #a73838;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    header {{ padding: 20px 24px 12px; border-bottom: 1px solid var(--line); background: #fff; }}
    h1 {{ margin: 0; font-size: 24px; font-weight: 720; }}
    h2 {{ margin: 0 0 10px; font-size: 15px; }}
    main {{ display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: calc(100vh - 74px); }}
    aside {{ border-right: 1px solid var(--line); background: #fff; padding: 14px; overflow: auto; }}
    section {{ padding: 14px; min-width: 0; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); gap: 12px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; min-width: 0; }}
    .wide {{ grid-column: 1 / -1; }}
    canvas {{ width: 100%; display: block; border: 1px solid var(--line); border-radius: 4px; background: #fff; }}
    label {{ display: grid; gap: 5px; color: var(--muted); font-size: 12px; margin: 10px 0; }}
    input[type="range"], select {{ width: 100%; }}
    button {{ border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 5px; padding: 7px 10px; cursor: pointer; }}
    button.active {{ background: #dfeceb; border-color: #8aa6a0; }}
    .row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    .metric {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; border-bottom: 1px solid #edf1ef; padding: 7px 0; }}
    .metric span {{ color: var(--muted); }}
    .pill {{ display: inline-flex; border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; font-size: 12px; color: var(--muted); }}
    .topicGrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 6px; margin: 8px 0; }}
    .topicChip {{ border: 1px solid var(--line); border-radius: 5px; padding: 6px; font-size: 12px; }}
    .list {{ display: grid; gap: 6px; }}
    .bar {{ height: 7px; background: #e8eeeb; border-radius: 999px; overflow: hidden; }}
    .bar i {{ display: block; height: 100%; background: var(--accent); }}
    .small {{ color: var(--muted); font-size: 12px; }}
    .readout {{ display: grid; gap: 8px; }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns: 1fr; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Holo Biomimetic Memory Dynamics Workbench</h1>
    <div class="small">observable proxy visualization | raw memory text redacted | WSL brain remains authoritative</div>
  </header>
  <main>
    <aside>
      <h2>Frame</h2>
      <label>turn index <input id="frameSlider" type="range" min="0" value="0"></label>
      <div class="row">
        <button id="playButton">Play</button>
        <button data-density="focus" class="density active">Focus</button>
        <button data-density="trace" class="density">Trace</button>
        <button data-density="global" class="density">Global</button>
      </div>
      <label>topology layer <select id="layerSelect"><option value="all">all</option></select></label>
      <div id="simulationReadout" class="readout"></div>
      <div id="frameReadout" class="readout"></div>
      <h2>Health</h2>
      <div id="healthReadout" class="list"></div>
    </aside>
    <section class="grid">
      <div class="panel wide">
        <h2>Semantic-Affective Phase Space</h2>
        <canvas id="phaseCanvas" width="1200" height="420"></canvas>
      </div>
      <div class="panel">
        <h2>Memory Topology</h2>
        <canvas id="topologyCanvas" width="720" height="620"></canvas>
      </div>
      <div class="panel">
        <h2>Cortical Slice Proxy</h2>
        <canvas id="sliceCanvas" width="720" height="620"></canvas>
      </div>
      <div class="panel wide">
        <h2>Promotion And Route Pressure</h2>
        <div id="promotionReadout" class="list"></div>
      </div>
    </section>
  </main>
  <script id="payload" type="application/json">{payload_json}</script>
  <script>
  const payload = JSON.parse(document.getElementById("payload").textContent);
  const frames = payload.trajectory.frames || [];
  const topology = payload.topology || {{ nodes: [], edges: [], layers: [] }};
  let frame = 0;
  let density = "focus";
  let layer = "all";
  let timer = null;
  const slider = document.getElementById("frameSlider");
  slider.max = Math.max(0, frames.length - 1);
  const layerSelect = document.getElementById("layerSelect");
  (topology.layers || []).forEach(item => {{
    const option = document.createElement("option");
    option.value = item;
    option.textContent = item;
    layerSelect.appendChild(option);
  }});
  function number(value, fallback = 0) {{ const n = Number(value); return Number.isFinite(n) ? n : fallback; }}
  function canvasContext(canvas) {{
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || canvas.width;
    const height = Math.max(260, Math.round(width * canvas.height / canvas.width));
    canvas.style.height = height + "px";
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return {{ ctx, width, height }};
  }}
  function colorForLayer(itemLayer, value = 0.5) {{
    const alpha = Math.max(0.28, Math.min(0.95, value));
    if (itemLayer === "memory") return `rgba(77,127,83,${{alpha}})`;
    if (itemLayer === "route") return `rgba(53,111,138,${{alpha}})`;
    if (itemLayer === "health") return `rgba(166,71,60,${{alpha}})`;
    if (itemLayer === "vector") return `rgba(108,94,151,${{alpha}})`;
    if (itemLayer === "trajectory") return `rgba(35,96,106,${{alpha}})`;
    if (itemLayer === "topic") return `rgba(128,91,54,${{alpha}})`;
    return `rgba(90,100,100,${{alpha}})`;
  }}
  function categoryColor(category, alpha = .72) {{
    const palette = ["53,111,138", "182,83,79", "77,127,83", "108,94,151", "176,123,45", "75,122,116", "151,82,110"];
    let hash = 0;
    String(category || "none").split("").forEach(ch => {{ hash = (hash * 31 + ch.charCodeAt(0)) >>> 0; }});
    return `rgba(${{palette[hash % palette.length]}},${{alpha}})`;
  }}
  function drawPhase() {{
    const canvas = document.getElementById("phaseCanvas");
    const {{ ctx, width, height }} = canvasContext(canvas);
    ctx.clearRect(0, 0, width, height);
    const pad = 42;
    const plotW = width - pad * 2;
    const plotH = height - pad * 2;
    ctx.strokeStyle = "#d7dfdc";
    ctx.lineWidth = 1;
    ctx.strokeRect(pad, pad, plotW, plotH);
    ctx.fillStyle = "#60706c";
    ctx.fillText("semantic memory pressure", pad, height - 14);
    ctx.save();
    ctx.translate(14, height - pad);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("affective / latency pressure", 0, 0);
    ctx.restore();
    ctx.beginPath();
    frames.forEach((item, index) => {{
      const p = item.projection || {{}};
      const x = pad + number(p.x) * plotW;
      const y = height - pad - number(p.y) * plotH;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }});
    ctx.strokeStyle = "#356f8a";
    ctx.lineWidth = 2;
    ctx.stroke();
    frames.forEach((item, index) => {{
      if (density === "focus" && Math.abs(index - frame) > 10) return;
      if (density === "trace" && Math.abs(index - frame) > 45) return;
      const p = item.projection || {{}};
      const x = pad + number(p.x) * plotW;
      const y = height - pad - number(p.y) * plotH;
      const r = index === frame ? 6 : 2.4;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = index === frame ? "#b6534f" : categoryColor(item.category || item.route, .48);
      ctx.fill();
    }});
  }}
  function layoutNodes(nodes, width, height) {{
    const cx = width / 2, cy = height / 2;
    const rings = {{ health: 0.2, route: 0.42, memory: 0.62, vector: 0.72, mind_graph: 0.82, trajectory: 0.92 }};
    const byLayer = new Map();
    nodes.forEach(node => {{
      if (!byLayer.has(node.layer)) byLayer.set(node.layer, []);
      byLayer.get(node.layer).push(node);
    }});
    const positions = new Map();
    for (const [nodeLayer, layerNodes] of byLayer.entries()) {{
      const radius = Math.min(width, height) * (rings[nodeLayer] || 0.65) * 0.48;
      layerNodes.forEach((node, index) => {{
        const angle = (Math.PI * 2 * index / Math.max(1, layerNodes.length)) - Math.PI / 2;
        positions.set(node.id, {{ x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius }});
      }});
    }}
    positions.set("subject", {{ x: cx, y: cy }});
    return positions;
  }}
  function visibleNodes() {{
    return (topology.nodes || []).filter(node => layer === "all" || node.layer === layer || node.id === "subject");
  }}
  function drawTopology() {{
    const canvas = document.getElementById("topologyCanvas");
    const {{ ctx, width, height }} = canvasContext(canvas);
    ctx.clearRect(0, 0, width, height);
    const nodes = visibleNodes();
    const nodeIds = new Set(nodes.map(node => node.id));
    const positions = layoutNodes(nodes, width, height);
    const edges = (topology.edges || []).filter(edge => nodeIds.has(edge.source) && nodeIds.has(edge.target) && (layer === "all" || edge.layer === layer));
    edges.forEach(edge => {{
      const a = positions.get(edge.source), b = positions.get(edge.target);
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = colorForLayer(edge.layer, number(edge.weight, .3) * .55);
      ctx.lineWidth = 0.8 + number(edge.weight, .2) * 3;
      ctx.stroke();
    }});
    nodes.forEach(node => {{
      const p = positions.get(node.id);
      if (!p) return;
      const value = number(node.value, .4);
      ctx.beginPath();
      ctx.arc(p.x, p.y, node.id === "subject" ? 15 : 5 + value * 9, 0, Math.PI * 2);
      ctx.fillStyle = colorForLayer(node.layer, value);
      ctx.fill();
      if (node.id === "subject" || density !== "focus") {{
        ctx.fillStyle = "#18201f";
        ctx.font = "11px system-ui";
        ctx.fillText(String(node.label || node.id).slice(0, 24), p.x + 8, p.y + 4);
      }}
    }});
  }}
  function drawSlice() {{
    const canvas = document.getElementById("sliceCanvas");
    const {{ ctx, width, height }} = canvasContext(canvas);
    ctx.clearRect(0, 0, width, height);
    const current = frames[frame] || {{ values: {{}} }};
    const values = current.values || {{}};
    const keys = payload.trajectory.component_keys || [];
    const cols = 12, rows = 10;
    const gap = 8;
    const cell = Math.min((width - 42 - cols * gap) / cols, (height - 58 - rows * gap) / rows);
    keys.forEach((key, keyIndex) => {{
      const base = number(values[key], 0);
      for (let i = 0; i < 14; i++) {{
        const unit = keyIndex * 14 + i;
        const col = unit % cols;
        const row = Math.floor(unit / cols);
        const x = 24 + col * (cell + gap);
        const y = 42 + row * (cell + gap);
        const wave = (Math.sin((frame + 1) * 0.17 + i * 0.9 + keyIndex) + 1) * 0.5;
        const activity = Math.max(0, Math.min(1, base * 0.78 + wave * 0.22));
        ctx.fillStyle = `rgba(182,83,79,${{0.16 + activity * 0.82}})`;
        ctx.fillRect(x, y, cell, cell);
      }}
    }});
    ctx.fillStyle = "#18201f";
    ctx.font = "12px system-ui";
    ctx.fillText(`frame ${{frame}} | ${{current.category || "runtime"}}/${{current.topic || current.route || ""}} | latency=${{current.latency_ms || 0}}ms`, 20, 22);
  }}
  function updateReadouts() {{
    const current = frames[frame] || {{}};
    const values = current.values || {{}};
    document.getElementById("frameReadout").innerHTML = `
      <div class="metric"><span>route</span><strong>${{current.route || "none"}}</strong></div>
      <div class="metric"><span>category</span><strong>${{current.category || "runtime"}}</strong></div>
      <div class="metric"><span>topic</span><strong>${{current.topic || "none"}}</strong></div>
      <div class="metric"><span>thread</span><strong>${{current.thread_key || ""}}</strong></div>
      <div class="metric"><span>latency</span><strong>${{current.latency_ms || 0}} ms</strong></div>
      <div class="metric"><span>delta</span><strong>${{number(current.delta_from_previous).toFixed(4)}}</strong></div>
      ${{Object.keys(values).map(key => `<div><div class="metric"><span>${{key}}</span><strong>${{number(values[key]).toFixed(3)}}</strong></div><div class="bar"><i style="width:${{Math.round(number(values[key]) * 100)}}%"></i></div></div>`).join("")}}
    `;
    const health = payload.doctor.biomimetic_health || {{}};
    const simulation = payload.simulation || {{}};
    const categories = simulation.categories || {{}};
    document.getElementById("simulationReadout").innerHTML = `
      <h2>Simulation</h2>
      <div class="metric"><span>source</span><strong>${{payload.trajectory.source || ""}}</strong></div>
      <div class="metric"><span>batch</span><strong>${{simulation.latest_batch_id || ""}}</strong></div>
      <div class="metric"><span>categories</span><strong>${{simulation.category_count || 0}}</strong></div>
      <div class="metric"><span>topics</span><strong>${{simulation.topic_count || 0}}</strong></div>
      <div class="metric"><span>max delta</span><strong>${{number((simulation.continuity || {{}}).max_delta).toFixed(4)}}</strong></div>
      <div class="topicGrid">${{Object.keys(categories).slice(0, 12).map(key => `<div class="topicChip" style="border-color:${{categoryColor(key, .55)}}"><strong>${{key}}</strong><br><span class="small">${{categories[key]}} frames</span></div>`).join("")}}</div>
    `;
    document.getElementById("healthReadout").innerHTML = Object.keys(health).map(key => {{
      const status = health[key].status || "unknown";
      return `<div class="metric"><span>${{key}}</span><strong class="pill">${{status}}</strong></div>`;
    }}).join("");
    const plan = payload.promotion_plan || {{}};
    const route = payload.route_latency.by_route || {{}};
    document.getElementById("promotionReadout").innerHTML = `
      <div class="metric"><span>promotion plan</span><strong>${{plan.status || "unknown"}}</strong></div>
      <div class="metric"><span>candidate count</span><strong>${{plan.candidate_count ?? ""}}</strong></div>
      <div class="metric"><span>would apply</span><strong>${{(plan.would_apply || []).length}}</strong></div>
      ${{Object.keys(route).map(key => `<div class="metric"><span>${{key}} p50</span><strong>${{route[key].p50_ms || 0}} ms</strong></div>`).join("")}}
    `;
  }}
  function render() {{
    frame = Math.max(0, Math.min(Math.max(0, frames.length - 1), frame));
    slider.value = frame;
    drawPhase();
    drawTopology();
    drawSlice();
    updateReadouts();
  }}
  slider.addEventListener("input", event => {{ frame = Number(event.target.value); render(); }});
  layerSelect.addEventListener("change", event => {{ layer = event.target.value; render(); }});
  document.querySelectorAll(".density").forEach(button => button.addEventListener("click", () => {{
    density = button.dataset.density;
    document.querySelectorAll(".density").forEach(item => item.classList.toggle("active", item === button));
    render();
  }}));
  document.getElementById("playButton").addEventListener("click", event => {{
    if (timer) {{ clearInterval(timer); timer = null; event.target.textContent = "Play"; return; }}
    event.target.textContent = "Pause";
    timer = setInterval(() => {{ frame = (frame + 1) % Math.max(1, frames.length); render(); }}, 420);
  }});
  window.addEventListener("resize", render);
  render();
  </script>
</body>
</html>
"""


def write_biomimetic_visualization(repo_root: Path | str, *, output_dir: Path | str | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    target_dir = Path(output_dir) if output_dir is not None else root / DEFAULT_OUTPUT_DIR
    if not target_dir.is_absolute():
        target_dir = root / target_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = build_biomimetic_visualization_payload(root)
    html_text = render_biomimetic_visualization_html(payload)
    html_path = target_dir / "stage100_biomimetic_system_workbench.html"
    payload_path = target_dir / "stage100_biomimetic_system_payload.json"
    html_path.write_text(html_text, encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "ok",
        "html_path": str(html_path),
        "payload_path": str(payload_path),
        "frame_count": len(payload["trajectory"]["frames"]),
        "node_count": len(payload["topology"]["nodes"]),
        "edge_count": len(payload["topology"]["edges"]),
        "raw_text_included": False,
    }
