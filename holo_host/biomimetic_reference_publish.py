from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .biomimetic_visualization import render_biomimetic_visualization_html

DEFAULT_SOURCE_DIR = Path("artifacts") / "stage100"
DEFAULT_OUTPUT_DIR = Path("references") / "biomimetic_agent_stage103"
PAYLOAD_NAME = "stage100_biomimetic_system_payload.json"
HTML_NAME = "stage100_biomimetic_system_workbench.html"
DROP_REFERENCE_KEYS = {
    "generated_from",
    "repo_root",
    "path",
    "top_thread_keys",
    "raw_thread_keys",
    "fragmentation_candidates",
    "thread_identity",
    "largest_timing_rows",
}
PATH_PATTERN = re.compile(r"([A-Za-z]:\\[^\s\"']+|/mnt/[^\s\"']+|/home/[^\s\"']+)")


def _resolve_under_repo(repo_root: Path, path: Path | str | None, default: Path) -> Path:
    value = Path(path) if path is not None else default
    if value.is_absolute():
        return value
    return repo_root / value


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing biomimetic visualization payload: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"biomimetic visualization payload must be a JSON object: {path}")
    return payload


def _sanitize_value(value: Any, *, key: str = "") -> Any:
    if key in DROP_REFERENCE_KEYS:
        return None
    if isinstance(value, dict):
        clean_dict: dict[str, Any] = {}
        for child_key, child_value in value.items():
            sanitized = _sanitize_value(child_value, key=str(child_key))
            if sanitized is not None:
                clean_dict[str(child_key)] = sanitized
        return clean_dict
    if isinstance(value, list):
        return [item for item in (_sanitize_value(item) for item in value) if item is not None]
    if isinstance(value, str):
        text = PATH_PATTERN.sub("[redacted_path]", value)
        if text.startswith("wechat:"):
            return "wechat:[redacted]"
        return text
    return value


def _sanitized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _sanitize_value(payload)
    if not isinstance(clean, dict):
        clean = {}
    clean["reference_publish"] = {
        "machine_path_redacted": True,
        "source_payload_schema": str(payload.get("schema", "") or ""),
    }
    return clean


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_entry(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": path.name,
        "size_bytes": int(stat.st_size),
        "sha256": _sha256(path),
    }


def _metrics(payload: dict[str, Any]) -> dict[str, Any]:
    trajectory = payload.get("trajectory") if isinstance(payload.get("trajectory"), dict) else {}
    simulation = payload.get("simulation") if isinstance(payload.get("simulation"), dict) else {}
    topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
    frames = trajectory.get("frames") if isinstance(trajectory.get("frames"), list) else []
    continuity = simulation.get("continuity") if isinstance(simulation.get("continuity"), dict) else {}
    return {
        "trajectory_source": str(trajectory.get("source", "") or ""),
        "batch_id": str(simulation.get("latest_batch_id", "") or ""),
        "frame_count": len(frames),
        "category_count": int(simulation.get("category_count", 0) or 0),
        "topic_count": int(simulation.get("topic_count", 0) or 0),
        "node_count": len(topology.get("nodes", []) if isinstance(topology.get("nodes"), list) else []),
        "edge_count": len(topology.get("edges", []) if isinstance(topology.get("edges"), list) else []),
        "continuity": {
            "frame_count": int(continuity.get("frame_count", len(frames)) or 0),
            "max_delta": float(continuity.get("max_delta", 0.0) or 0.0),
            "mean_delta": float(continuity.get("mean_delta", 0.0) or 0.0),
            "large_jump_threshold": float(continuity.get("large_jump_threshold", 0.22) or 0.22),
            "large_jump_count": int(continuity.get("large_jump_count", 0) or 0),
        },
    }


def _privacy(payload: dict[str, Any]) -> dict[str, Any]:
    source_privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    boundary = payload.get("paper_claim_boundary") if isinstance(payload.get("paper_claim_boundary"), dict) else {}
    return {
        "raw_text_included": bool(source_privacy.get("raw_text_included", False)),
        "machine_paths_redacted": True,
        "runtime_memory_included": False,
        "provider_content_included": False,
        "paper_claim_boundary": {
            "observable_proxy_only": bool(boundary.get("observable_proxy_only", True)),
            "no_hidden_reasoning_claim": bool(boundary.get("no_hidden_reasoning_claim", True)),
            "no_real_emotion_claim": bool(boundary.get("no_real_emotion_claim", True)),
            "no_biological_brain_state_claim": bool(boundary.get("no_biological_brain_state_claim", True)),
        },
    }


def _readme_text(manifest: dict[str, Any]) -> str:
    metrics = manifest["metrics"]
    continuity = metrics["continuity"]
    return f"""# Holo Biomimetic Agent Stage103 Reference Bundle

This bundle publishes the paper-facing, redacted Stage100/Stage103 visualization artifacts for the Holo biomimetic-agent study.

## Contents

- `{HTML_NAME}`: standalone browser workbench for topology, phase-space trajectory, and slice-proxy visualization.
- `{PAYLOAD_NAME}`: redacted visualization payload used by the workbench.
- `manifest.json`: checksums, metrics, privacy boundary, and reproduction commands.
- `REFERENCE.md`: citable research note for internal papers or prerelease notes.

## Metrics

- trajectory source: `{metrics["trajectory_source"]}`
- simulation batch: `{metrics["batch_id"]}`
- frames: `{metrics["frame_count"]}`
- categories: `{metrics["category_count"]}`
- topics: `{metrics["topic_count"]}`
- topology nodes: `{metrics["node_count"]}`
- topology edges: `{metrics["edge_count"]}`
- max continuity delta: `{continuity["max_delta"]:.4f}`
- large jumps: `{continuity["large_jump_count"]}` over threshold `{continuity["large_jump_threshold"]:.2f}`

## Boundary

The bundle is an observable proxy artifact. It does not publish private runtime memory, provider output, hidden reasoning, real emotion, or biological brain-state claims.
"""


def _reference_text(manifest: dict[str, Any]) -> str:
    metrics = manifest["metrics"]
    continuity = metrics["continuity"]
    return f"""# Reference Note: Stage103 Categorized Biomimetic Semantic-Affective Dynamics

## Citation Label

Holo Stage103 Biomimetic Agent Reference Bundle, generated {manifest["generated_at"]}.

## Research Use

This reference package supports a publishable study of redacted semantic-affective trajectory visualization in a single-subject conversational agent architecture. The experiment uses categorized topic sweeps to create continuous observable proxy motion across affect regulation, autobiographical recall, task-world control, semantic inference, multimodal grounding, and self-model boundary conditions.

## Reproduction

```powershell
python -m holo_host simulate-biomimetic-telemetry --topics-per-category 4 --turns-per-topic 24 --seed 103 --batch-id stage103-categorized-topic-sweep-final
python -m holo_host visualize-biomimetic-system
python -m holo_host publish-biomimetic-reference
```

## Reported Metrics

```text
source={metrics["trajectory_source"]}
batch={metrics["batch_id"]}
frames={metrics["frame_count"]}
categories={metrics["category_count"]}
topics={metrics["topic_count"]}
topology_nodes={metrics["node_count"]}
topology_edges={metrics["edge_count"]}
continuity_max_delta={continuity["max_delta"]:.4f}
continuity_mean_delta={continuity["mean_delta"]:.4f}
large_jumps={continuity["large_jump_count"]}
```

## Claim Boundary

The visualization is suitable for observable process analysis and ablation planning. It is not evidence of human subjective consciousness, private chain-of-thought access, real human emotion, or biological neural activity.
"""


def _write_manifest(output_dir: Path, payload: dict[str, Any], artifact_names: list[str]) -> dict[str, Any]:
    manifest = {
        "schema": "holo.biomimetic_reference_publish.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "stage": "stage103",
        "source_artifact": "stage100_biomimetic_system_workbench",
        "metrics": _metrics(payload),
        "privacy": _privacy(payload),
        "reproduce": [
            "python -m holo_host simulate-biomimetic-telemetry --topics-per-category 4 --turns-per-topic 24 --seed 103 --batch-id stage103-categorized-topic-sweep-final",
            "python -m holo_host visualize-biomimetic-system",
            "python -m holo_host publish-biomimetic-reference",
        ],
        "artifacts": {},
    }
    for name in artifact_names:
        manifest["artifacts"][name] = _artifact_entry(output_dir / name)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def publish_biomimetic_reference(
    repo_root: Path | str,
    *,
    output_dir: Path | str | None = None,
    source_dir: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    source = _resolve_under_repo(root, source_dir, DEFAULT_SOURCE_DIR)
    target = _resolve_under_repo(root, output_dir, DEFAULT_OUTPUT_DIR)
    target.mkdir(parents=True, exist_ok=True)

    payload = _sanitized_payload(_read_payload(source / PAYLOAD_NAME))
    (target / PAYLOAD_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (target / HTML_NAME).write_text(render_biomimetic_visualization_html(payload), encoding="utf-8")

    preliminary_manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "metrics": _metrics(payload),
    }
    (target / "README.md").write_text(_readme_text({"metrics": preliminary_manifest["metrics"]}), encoding="utf-8")
    (target / "REFERENCE.md").write_text(
        _reference_text(
            {
                "generated_at": preliminary_manifest["generated_at"],
                "metrics": preliminary_manifest["metrics"],
            }
        ),
        encoding="utf-8",
    )
    manifest = _write_manifest(target, payload, [HTML_NAME, PAYLOAD_NAME, "README.md", "REFERENCE.md"])
    return {
        "status": "ok",
        "schema": manifest["schema"],
        "output_dir": str(target),
        "manifest_path": str(target / "manifest.json"),
        "html_path": str(target / HTML_NAME),
        "payload_path": str(target / PAYLOAD_NAME),
        "metrics": manifest["metrics"],
        "privacy": manifest["privacy"],
    }
