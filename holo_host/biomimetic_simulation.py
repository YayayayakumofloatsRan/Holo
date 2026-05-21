from __future__ import annotations

import math
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .biomimetic_telemetry import append_biomimetic_frames, build_biomimetic_frame


SIMULATION_CATALOG: list[dict[str, Any]] = [
    {
        "category": "affective_regulation",
        "topics": ["stress_containment", "warm_repair", "playful_tension", "boundary_soothing"],
        "base": {"valence": 0.48, "arousal": 0.42, "control": 0.58, "memory_pressure": 0.34, "latency_pressure": 0.12, "deep_recall": 0.2, "health_pressure": 0.05, "regulation": 0.55},
    },
    {
        "category": "autobiographical_recall",
        "topics": ["origin_memory", "relationship_history", "preference_recall", "correction_memory"],
        "base": {"valence": 0.55, "arousal": 0.36, "control": 0.62, "memory_pressure": 0.62, "latency_pressure": 0.2, "deep_recall": 0.65, "health_pressure": 0.04, "regulation": 0.57},
    },
    {
        "category": "task_world",
        "topics": ["commitment_tracking", "tool_progress", "handoff_reentry", "operator_control"],
        "base": {"valence": 0.5, "arousal": 0.32, "control": 0.76, "memory_pressure": 0.46, "latency_pressure": 0.1, "deep_recall": 0.25, "health_pressure": 0.08, "regulation": 0.68},
    },
    {
        "category": "semantic_inference",
        "topics": ["concept_drift", "metaphor_grounding", "topic_bridge", "contradiction_repair"],
        "base": {"valence": 0.52, "arousal": 0.48, "control": 0.6, "memory_pressure": 0.54, "latency_pressure": 0.18, "deep_recall": 0.42, "health_pressure": 0.06, "regulation": 0.53},
    },
    {
        "category": "multimodal_grounding",
        "topics": ["visual_scene", "artifact_memory", "spatial_reference", "state_comparison"],
        "base": {"valence": 0.5, "arousal": 0.38, "control": 0.66, "memory_pressure": 0.5, "latency_pressure": 0.16, "deep_recall": 0.36, "health_pressure": 0.07, "regulation": 0.6},
    },
    {
        "category": "self_model_boundary",
        "topics": ["claim_boundary", "uncertainty_expression", "subject_continuity", "policy_resistance"],
        "base": {"valence": 0.46, "arousal": 0.44, "control": 0.7, "memory_pressure": 0.42, "latency_pressure": 0.14, "deep_recall": 0.3, "health_pressure": 0.1, "regulation": 0.61},
    },
]

COMPONENT_KEYS = ["valence", "arousal", "control", "memory_pressure", "latency_pressure", "deep_recall", "health_pressure", "regulation"]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _projection(values: dict[str, float]) -> dict[str, float]:
    return {
        "x": round(_clamp(values["memory_pressure"] * 0.54 + values["deep_recall"] * 0.24 + values["health_pressure"] * 0.12), 4),
        "y": round(_clamp(values["arousal"] * 0.44 + values["latency_pressure"] * 0.28 + (1.0 - values["control"]) * 0.2), 4),
        "z": round(_clamp(values["valence"] * 0.34 + values["regulation"] * 0.44 + values["control"] * 0.12), 4),
    }


def _distance(left: dict[str, float], right: dict[str, float]) -> float:
    return math.sqrt(
        (float(left.get("x", 0.0)) - float(right.get("x", 0.0))) ** 2
        + (float(left.get("y", 0.0)) - float(right.get("y", 0.0))) ** 2
        + (float(left.get("z", 0.0)) - float(right.get("z", 0.0))) ** 2
    )


def _continuity(frames: list[dict[str, Any]]) -> dict[str, Any]:
    projections = [dict(frame.get("vector", {}).get("projection", {})) for frame in frames if isinstance(frame.get("vector"), dict)]
    deltas = [_distance(projections[index - 1], projections[index]) for index in range(1, len(projections))]
    max_delta = max(deltas) if deltas else 0.0
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    return {
        "frame_count": len(frames),
        "max_delta": round(max_delta, 4),
        "mean_delta": round(mean_delta, 4),
        "large_jump_threshold": 0.22,
        "large_jump_count": sum(1 for delta in deltas if delta > 0.22),
    }


def _topic_target(base: dict[str, float], *, category_index: int, topic_index: int, rng: random.Random) -> dict[str, float]:
    target: dict[str, float] = {}
    for key in COMPONENT_KEYS:
        wave = math.sin((category_index + 1) * 0.73 + (topic_index + 1) * 0.41 + len(key) * 0.17)
        jitter = (rng.random() - 0.5) * 0.035
        target[key] = _clamp(float(base[key]) + wave * 0.055 + jitter)
    target["regulation"] = _clamp(target["control"] - target["arousal"] * 0.25 + target["valence"] * 0.18)
    return target


def _route_for_values(values: dict[str, float]) -> str:
    if values["deep_recall"] > 0.55:
        return "deep_recall"
    if values["memory_pressure"] > 0.48:
        return "recall"
    return "active_thread"


def _recall_payload(category: str, topic: str, global_index: int, values: dict[str, float], rng: random.Random) -> dict[str, Any]:
    route = _route_for_values(values)
    candidate_count = 3 + int(values["memory_pressure"] * 8)
    graph_hits = []
    vector_hits = []
    reranked = []
    for index in range(min(8, candidate_count)):
        node_id = f"{category}:{topic}:{global_index}:{index}"
        score = round(_clamp(values["memory_pressure"] + values["deep_recall"] * 0.4 + rng.random() * 0.08) * (1.35 - index * 0.055), 4)
        item = {
            "node_id": node_id,
            "score": score,
            "memory_class": "episodic_memory" if route == "deep_recall" else "working_memory",
            "source": "simulated",
            "activation_reason": ["simulated_fit", "topic_continuity"],
        }
        graph_hits.append(item)
        vector_hits.append({**item, "score": round(score * 0.82, 4), "source": "simulated_vector"})
        reranked.append(
            {
                **item,
                "hybrid_score": round(score * 1.08 + values["regulation"] * 0.08, 4),
                "graph_score": score,
                "vector_score": round(score * 0.82, 4),
                "activation_boost": round(values["regulation"] * 0.12, 4),
                "semantic_overlap": 1 + int(values["memory_pressure"] * 4),
                "source": "simulated_hybrid",
                "rerank_reason": ["simulated_semantic_overlap", "simulated_activation"],
            }
        )
    return {
        "action": "reply",
        "route": route,
        "processor": "simulation",
        "timing_ms": {
            "total_ms": int(160 + values["latency_pressure"] * 1800 + values["deep_recall"] * 900),
            "processor_ms": int(90 + values["arousal"] * 260),
        },
        "selected_memory_ids": [f"sim-memory-{global_index}-{index}" for index in range(min(4, candidate_count))],
        "activation_trace_ids": [f"sim-node-{global_index}-{index}" for index in range(min(6, candidate_count))],
        "emotion_state": {
            "valence": values["valence"],
            "arousal": values["arousal"],
            "control": values["control"],
        },
        "tier": "deep_recall" if route == "deep_recall" else ("recall" if route == "recall" else "fast"),
        "query_focus": topic,
        "retrieval_mode": "simulation-continuous",
        "memory_route": route,
        "recall_confidence": round(_clamp(values["memory_pressure"] * 0.72 + values["regulation"] * 0.18), 4),
        "graph_confidence": round(_clamp(values["memory_pressure"] * 0.65), 4),
        "graph_hits": graph_hits,
        "vector_hits": vector_hits,
        "trace": reranked,
    }


def simulate_categorized_biomimetic_telemetry(
    repo_root: Path | str,
    *,
    topics_per_category: int = 3,
    turns_per_topic: int = 12,
    seed: int = 103,
    batch_id: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    rng = random.Random(seed)
    chosen = [item for item in SIMULATION_CATALOG if not categories or str(item["category"]) in set(categories)]
    if not chosen:
        chosen = list(SIMULATION_CATALOG)
    topics_per_category = max(1, int(topics_per_category))
    turns_per_topic = max(2, int(turns_per_topic))
    batch = batch_id or f"stage103-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{seed}"
    created_start = datetime.now(timezone.utc).replace(microsecond=0)
    current_values = dict(chosen[0]["base"])
    frames: list[dict[str, Any]] = []
    global_index = 0
    for category_index, category_spec in enumerate(chosen):
        category = str(category_spec["category"])
        topics = list(category_spec["topics"])[:topics_per_category]
        for topic_index, topic in enumerate(topics):
            target = _topic_target(dict(category_spec["base"]), category_index=category_index, topic_index=topic_index, rng=rng)
            for turn_index in range(turns_per_topic):
                alpha = 0.22 if global_index else 1.0
                phase = math.sin((turn_index + 1) / max(1, turns_per_topic) * math.pi)
                next_values: dict[str, float] = {}
                for key in COMPONENT_KEYS:
                    drift = (target[key] - current_values[key]) * alpha
                    pulse = math.sin(global_index * 0.37 + len(key) * 0.13) * 0.006 * phase
                    next_values[key] = _clamp(current_values[key] + drift + pulse)
                next_values["regulation"] = _clamp(next_values["control"] - next_values["arousal"] * 0.25 + next_values["valence"] * 0.18)
                current_values = next_values
                output_payload = _recall_payload(category, str(topic), global_index, current_values, rng)
                frame = build_biomimetic_frame(
                    root,
                    event_type="simulation_turn",
                    source="stage103.categorized_simulation",
                    input_payload={
                        "text": f"simulated topic probe {category} {topic} {turn_index}",
                        "channel": "simulation",
                        "thread_key": f"simulation:{category}",
                        "chat_name": str(topic),
                        "message_id": f"{batch}:{global_index}",
                    },
                    output_payload=output_payload,
                    extra={
                        "batch_id": batch,
                        "category": category,
                        "topic": str(topic),
                        "category_index": category_index,
                        "topic_index": topic_index,
                        "turn_index": turn_index,
                        "simulated": True,
                    },
                    created_at=(created_start + timedelta(seconds=global_index * 12)).isoformat().replace("+00:00", "Z"),
                )
                frame["vector"] = {
                    "component_keys": list(COMPONENT_KEYS),
                    "values": {key: round(current_values[key], 4) for key in COMPONENT_KEYS},
                    "projection": _projection(current_values),
                }
                frame["simulation"] = {
                    "batch_id": batch,
                    "category": category,
                    "topic": str(topic),
                    "category_index": category_index,
                    "topic_index": topic_index,
                    "turn_index": turn_index,
                    "global_index": global_index,
                }
                frames.append(frame)
                global_index += 1
    append_biomimetic_frames(root, frames)
    category_counts = Counter(str(frame["simulation"]["category"]) for frame in frames)
    topic_counts = Counter(str(frame["simulation"]["topic"]) for frame in frames)
    return {
        "status": "ok",
        "schema": "holo.biomimetic_simulation_report.v1",
        "batch_id": batch,
        "seed": seed,
        "total_frames": len(frames),
        "category_count": len(category_counts),
        "topic_count": len(topic_counts),
        "categories": dict(sorted(category_counts.items())),
        "topics": dict(sorted(topic_counts.items())),
        "continuity": _continuity(frames),
        "privacy": {"raw_text_included": False},
    }
