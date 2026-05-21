from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TELEMETRY_PATH = Path(".holo_runtime") / "biomimetic_frames.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _hash_text(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def _repo_path(repo_root: Path | str) -> Path:
    return Path(repo_root).resolve()


def telemetry_store_path(repo_root: Path | str) -> Path:
    return _repo_path(repo_root) / TELEMETRY_PATH


def _input_signature(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    text = str(source.get("text", "") or "")
    attachments = source.get("attachments", [])
    if not isinstance(attachments, list):
        attachments = []
    return {
        "channel": str(source.get("channel", "") or ""),
        "thread_key": str(source.get("thread_key", "") or ""),
        "chat_name": str(source.get("chat_name", "") or ""),
        "message_id": str(source.get("message_id", "") or ""),
        "sender_present": bool(str(source.get("sender", "") or "").strip()),
        "text_present": bool(text.strip()),
        "text_chars": len(text),
        "text_hash": _hash_text(text),
        "attachment_count": len([item for item in attachments if isinstance(item, dict)]),
    }


def _timing(payload: dict[str, Any]) -> dict[str, int]:
    timing = payload.get("timing_ms", {})
    if not isinstance(timing, dict):
        timing = {}
    keys = (
        "sidecar_ms",
        "active_history_ms",
        "capability_ms",
        "processor_ms",
        "recall_reconstruct_ms",
        "repair_ms",
        "total_ms",
    )
    return {key: max(0, _safe_int(timing.get(key), 0)) for key in keys if key in timing or key == "total_ms"}


def _route(payload: dict[str, Any]) -> str:
    for key in ("route", "memory_route", "retrieval_mode", "tier"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return "unknown"


def _action(payload: dict[str, Any]) -> str:
    for key in ("semantic_action", "action", "returned_action"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    selected = payload.get("selected_action")
    if isinstance(selected, dict):
        value = str(selected.get("action_type", "") or "").strip()
        if value:
            return value
    return "unknown"


def _health_counts(payload: dict[str, Any]) -> dict[str, int]:
    health = payload.get("biomimetic_health", {})
    if not isinstance(health, dict):
        return {}
    counts: Counter[str] = Counter()
    for item in health.values():
        if isinstance(item, dict):
            status = str(item.get("status", "unknown") or "unknown")
            counts[status] += 1
    return dict(sorted(counts.items()))


def _promotion_observables(payload: dict[str, Any]) -> dict[str, int]:
    would_apply = payload.get("would_apply", [])
    would_skip = payload.get("would_skip", [])
    return {
        "candidate_count": max(0, _safe_int(payload.get("candidate_count"), 0)),
        "durable_count": max(0, _safe_int(payload.get("durable_count"), 0)),
        "promotion_would_apply": len(would_apply) if isinstance(would_apply, list) else 0,
        "promotion_would_skip": len(would_skip) if isinstance(would_skip, list) else 0,
    }


def _output_observables(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    selected_memory_ids = source.get("selected_memory_ids", [])
    if not isinstance(selected_memory_ids, list):
        selected_memory_ids = []
    activation_trace_ids = source.get("activation_trace_ids", [])
    if not isinstance(activation_trace_ids, list):
        activation_trace_ids = []
    timing = _timing(source)
    return {
        "action": _action(source),
        "returned_action": str(source.get("returned_action", "") or ""),
        "delivery_verdict": str(source.get("delivery_verdict", "") or ""),
        "route": _route(source),
        "processor": str(source.get("processor", "") or ""),
        "timing_ms": timing,
        "selected_memory_count": len(selected_memory_ids),
        "activation_trace_count": len(activation_trace_ids),
        "graph_confidence": round(_safe_float(source.get("graph_confidence"), 0.0), 4),
        "expression_budget": max(0, _safe_int(source.get("expression_budget"), 0)),
        "health_status_counts": _health_counts(source),
        **_promotion_observables(source),
    }


def _emotion_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    emotion = source.get("emotion_state", {})
    if not isinstance(emotion, dict):
        emotion = {}
    return emotion


def _vector_values(observables: dict[str, Any], output_payload: dict[str, Any] | None) -> dict[str, float]:
    timing = observables.get("timing_ms", {}) if isinstance(observables.get("timing_ms"), dict) else {}
    total_ms = max(0, _safe_int(timing.get("total_ms"), 0))
    emotion = _emotion_state(output_payload)
    route = str(observables.get("route", "") or "")
    action = str(observables.get("action", "") or "")
    selected_memory_count = max(0, _safe_int(observables.get("selected_memory_count"), 0))
    health_counts = dict(observables.get("health_status_counts", {}) if isinstance(observables.get("health_status_counts"), dict) else {})
    critical_count = max(0, _safe_int(health_counts.get("critical"), 0))
    warn_count = max(0, _safe_int(health_counts.get("warn"), 0))
    promotion_apply = max(0, _safe_int(observables.get("promotion_would_apply"), 0))
    latency_pressure = _clamp(math.log1p(total_ms) / math.log1p(300_000)) if total_ms > 0 else 0.0
    deep_recall = 1.0 if route == "deep_recall" else 0.0
    memory_pressure = _clamp(selected_memory_count / 8.0 + promotion_apply / 12.0 + deep_recall * 0.35)
    valence = _safe_float(emotion.get("valence", emotion.get("pleasantness")), 0.5)
    arousal = _safe_float(emotion.get("arousal"), 0.15)
    control = _safe_float(emotion.get("control", emotion.get("dominance")), 0.55)
    action_pressure = 0.0 if action in {"ignore", "silence"} else 0.35 if action == "defer_reply" else 0.55
    health_pressure = _clamp(critical_count * 0.35 + warn_count * 0.18)
    return {
        "valence": round(_clamp(valence), 4),
        "arousal": round(_clamp(arousal + latency_pressure * 0.25 + action_pressure * 0.1), 4),
        "control": round(_clamp(control - latency_pressure * 0.16), 4),
        "memory_pressure": round(memory_pressure, 4),
        "latency_pressure": round(latency_pressure, 4),
        "deep_recall": deep_recall,
        "health_pressure": round(health_pressure, 4),
        "regulation": round(_clamp(control - arousal * 0.32 - health_pressure * 0.18 + valence * 0.2), 4),
    }


def _projection(values: dict[str, float]) -> dict[str, float]:
    return {
        "x": round(_clamp(values["memory_pressure"] * 0.54 + values["deep_recall"] * 0.24 + values["health_pressure"] * 0.12), 4),
        "y": round(_clamp(values["arousal"] * 0.44 + values["latency_pressure"] * 0.28 + (1.0 - values["control"]) * 0.2), 4),
        "z": round(_clamp(values["valence"] * 0.34 + values["regulation"] * 0.44 + values["control"] * 0.12), 4),
    }


def _topology_refs(event_type: str, context: dict[str, Any], observables: dict[str, Any]) -> dict[str, Any]:
    route = str(observables.get("route", "unknown") or "unknown")
    action = str(observables.get("action", "unknown") or "unknown")
    nodes = [
        f"event:{event_type}",
        f"route:{route}",
        f"action:{action}",
    ]
    if context.get("thread_key"):
        nodes.append(f"thread:{context['thread_key']}")
    if observables.get("selected_memory_count", 0):
        nodes.append("memory:selected")
    if observables.get("health_status_counts"):
        nodes.append("health:doctor")
    return {
        "nodes": nodes,
        "edges": [
            {"source": f"event:{event_type}", "target": f"route:{route}", "type": "selected_route"},
            {"source": f"route:{route}", "target": f"action:{action}", "type": "conditioned_action"},
        ],
    }


def build_biomimetic_frame(
    repo_root: Path | str,
    *,
    event_type: str,
    source: str,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    root = _repo_path(repo_root)
    context = _input_signature(input_payload)
    observables = _output_observables(output_payload)
    if not context["channel"] and isinstance(output_payload, dict):
        context["channel"] = str(output_payload.get("channel", "") or "")
    if not context["thread_key"] and isinstance(output_payload, dict):
        context["thread_key"] = str(output_payload.get("thread_key", "") or "")
    if not context["chat_name"] and isinstance(output_payload, dict):
        context["chat_name"] = str(output_payload.get("chat_name", "") or "")
    if not context["message_id"] and isinstance(output_payload, dict):
        context["message_id"] = str(output_payload.get("message_id", "") or "")
    values = _vector_values(observables, output_payload)
    frame = {
        "schema": "holo.biomimetic_frame.v1",
        "id": f"bf-{uuid.uuid4().hex[:16]}",
        "created_at": created_at or utc_now(),
        "repo_root_hash": _hash_text(str(root)),
        "event_type": str(event_type or "unknown").strip() or "unknown",
        "source": str(source or "unknown").strip() or "unknown",
        "context": context,
        "observables": observables,
        "vector": {
            "component_keys": list(values.keys()),
            "values": values,
            "projection": _projection(values),
        },
        "topology_refs": _topology_refs(str(event_type or "unknown"), context, observables),
        "extra": _safe_extra(extra or {}),
        "privacy": {
            "raw_text_included": False,
            "redaction_policy": "only counts, hashes, route/action ids, timings, and scalar proxy values are emitted",
        },
        "paper_claim_boundary": {
            "observable_proxy_only": True,
            "no_hidden_reasoning_claim": True,
            "no_real_emotion_claim": True,
            "no_biological_brain_state_claim": True,
        },
    }
    return frame


def _safe_extra(extra: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in extra.items():
        key_text = str(key)
        if key_text in {"text", "reply", "bubbles", "raw_text", "prompt", "content"}:
            safe[key_text] = {"redacted": True}
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = value
        elif isinstance(value, list):
            safe[key_text] = {"type": "list", "count": len(value)}
        elif isinstance(value, dict):
            safe[key_text] = {"type": "dict", "keys": sorted(str(item) for item in value.keys())[:24]}
        else:
            safe[key_text] = str(type(value).__name__)
    return safe


def append_biomimetic_frame(repo_root: Path | str, frame: dict[str, Any]) -> dict[str, Any]:
    path = telemetry_store_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(frame, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
    return {"status": "ok", "path": str(path), "frame_id": str(frame.get("id", ""))}


def record_biomimetic_event(
    repo_root: Path | str,
    *,
    event_type: str,
    source: str,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame = build_biomimetic_frame(
        repo_root,
        event_type=event_type,
        source=source,
        input_payload=input_payload,
        output_payload=output_payload,
        extra=extra,
    )
    append_biomimetic_frame(repo_root, frame)
    return frame


def load_biomimetic_frames(repo_root: Path | str, *, limit: int = 200) -> list[dict[str, Any]]:
    path = telemetry_store_path(repo_root)
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
            if isinstance(payload, dict) and payload.get("schema") == "holo.biomimetic_frame.v1":
                rows.append(payload)
    return rows[-max(1, int(limit)) :]


def summarize_biomimetic_telemetry(repo_root: Path | str) -> dict[str, Any]:
    frames = load_biomimetic_frames(repo_root, limit=100000)
    event_counts = Counter(str(frame.get("event_type", "unknown")) for frame in frames)
    route_counts = Counter(str(frame.get("observables", {}).get("route", "unknown")) for frame in frames if isinstance(frame.get("observables"), dict))
    action_counts = Counter(str(frame.get("observables", {}).get("action", "unknown")) for frame in frames if isinstance(frame.get("observables"), dict))
    return {
        "schema": "holo.biomimetic_telemetry_summary.v1",
        "path": str(telemetry_store_path(repo_root)),
        "total_frames": len(frames),
        "event_counts": dict(sorted(event_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "privacy": {"raw_text_included": False},
    }


def telemetry_report(repo_root: Path | str, *, limit: int = 25) -> dict[str, Any]:
    return {
        "summary": summarize_biomimetic_telemetry(repo_root),
        "frames": load_biomimetic_frames(repo_root, limit=limit),
    }
