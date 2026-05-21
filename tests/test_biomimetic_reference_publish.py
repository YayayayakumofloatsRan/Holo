from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.biomimetic_reference_publish import publish_biomimetic_reference


def _seed_stage100_artifacts(root: Path) -> None:
    artifact_dir = root / "artifacts" / "stage100"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "stage100_biomimetic_system_workbench.html").write_text(
        "<!doctype html><title>Holo Biomimetic Memory Dynamics Workbench</title>",
        encoding="utf-8",
    )
    payload = {
        "schema": "holo.biomimetic_visualization.v1",
        "title": "Holo Biomimetic Memory Dynamics Workbench",
        "generated_from": str(root),
        "privacy": {"raw_text_included": False},
        "trajectory": {
            "source": "biomimetic_simulation",
            "component_keys": ["valence", "arousal", "control"],
            "frames": [
                {
                    "index": 0,
                    "category": "affective_regulation",
                    "topic": "stress_containment",
                    "delta_from_previous": 0.0,
                },
                {
                    "index": 1,
                    "category": "semantic_inference",
                    "topic": "topic_bridge",
                    "delta_from_previous": 0.05,
                },
            ],
        },
        "simulation": {
            "available": True,
            "latest_batch_id": "stage103-test",
            "category_count": 2,
            "topic_count": 2,
            "categories": {"affective_regulation": 1, "semantic_inference": 1},
            "topics": {"stress_containment": 1, "topic_bridge": 1},
            "continuity": {
                "frame_count": 2,
                "max_delta": 0.05,
                "mean_delta": 0.025,
                "large_jump_threshold": 0.22,
                "large_jump_count": 0,
            },
        },
        "topology": {"nodes": [{"id": "subject"}], "edges": [{"source": "subject", "target": "topic"}]},
        "doctor": {
            "repo_root": str(root),
            "jsonl_stores": {
                "conversation_archive.jsonl": {
                    "path": str(root / "holo_memory_library" / "memories" / "conversation_archive.jsonl"),
                    "valid_rows": 2,
                    "top_thread_keys": [{"key": "wechat:PrivateThread", "count": 2}],
                }
            },
            "thread_identity": {
                "fragmentation_candidates": [
                    {
                        "canonical_key": "wechat:PrivateThread",
                        "raw_thread_keys": [{"key": "PrivateThread", "count": 2}],
                    }
                ]
            },
            "biomimetic_health": {"substrate_integrity": {"status": "ok"}},
        },
        "paper_claim_boundary": {
            "observable_proxy_only": True,
            "no_hidden_reasoning_claim": True,
            "no_real_emotion_claim": True,
            "no_biological_brain_state_claim": True,
        },
    }
    (artifact_dir / "stage100_biomimetic_system_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_publish_biomimetic_reference_writes_reproducible_reference_bundle(tmp_path: Path) -> None:
    _seed_stage100_artifacts(tmp_path)

    report = publish_biomimetic_reference(tmp_path, output_dir=tmp_path / "references" / "stage103")

    output_dir = Path(report["output_dir"])
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    published_payload = json.loads((output_dir / "stage100_biomimetic_system_payload.json").read_text(encoding="utf-8"))
    serialized_payload = json.dumps(published_payload, ensure_ascii=False)

    assert report["status"] == "ok"
    assert manifest["schema"] == "holo.biomimetic_reference_publish.v1"
    assert manifest["metrics"]["trajectory_source"] == "biomimetic_simulation"
    assert manifest["metrics"]["batch_id"] == "stage103-test"
    assert manifest["metrics"]["category_count"] == 2
    assert manifest["metrics"]["topic_count"] == 2
    assert manifest["metrics"]["frame_count"] == 2
    assert manifest["metrics"]["continuity"]["max_delta"] == 0.05
    assert manifest["metrics"]["continuity"]["large_jump_count"] == 0
    assert manifest["privacy"]["raw_text_included"] is False
    assert "generated_from" not in published_payload
    assert str(tmp_path) not in serialized_payload
    assert "PrivateThread" not in serialized_payload
    assert "top_thread_keys" not in serialized_payload
    assert "thread_identity" not in serialized_payload
    assert (output_dir / "README.md").exists()
    assert (output_dir / "REFERENCE.md").exists()
    assert "stage100_biomimetic_system_workbench.html" in manifest["artifacts"]
    assert len(manifest["artifacts"]["stage100_biomimetic_system_workbench.html"]["sha256"]) == 64


def test_publish_biomimetic_reference_cli_dispatches(monkeypatch, capsys, tmp_path: Path) -> None:
    _seed_stage100_artifacts(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(["publish-biomimetic-reference", "--output-dir", str(tmp_path / "references" / "stage103")])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["metrics"]["batch_id"] == "stage103-test"
