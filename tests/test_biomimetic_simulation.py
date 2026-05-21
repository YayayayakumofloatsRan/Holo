from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.biomimetic_simulation import simulate_categorized_biomimetic_telemetry
from holo_host.biomimetic_telemetry import load_biomimetic_frames
from holo_host.biomimetic_visualization import build_biomimetic_visualization_payload


def test_categorized_simulation_generates_continuous_topic_batches(tmp_path: Path) -> None:
    report = simulate_categorized_biomimetic_telemetry(
        tmp_path,
        topics_per_category=2,
        turns_per_topic=8,
        seed=103,
    )

    frames = load_biomimetic_frames(tmp_path, limit=1000)
    serialized = json.dumps(frames, ensure_ascii=False)

    assert report["status"] == "ok"
    assert report["total_frames"] >= 80
    assert report["category_count"] >= 5
    assert report["topic_count"] >= 10
    assert report["continuity"]["max_delta"] <= 0.22
    assert report["continuity"]["large_jump_count"] == 0
    assert all(frame["event_type"] == "simulation_turn" for frame in frames)
    assert all(frame.get("simulation", {}).get("category") for frame in frames)
    assert all(frame.get("simulation", {}).get("topic") for frame in frames)
    assert "private" not in serialized.lower()
    assert "simulated topic probe" not in serialized


def test_visualization_prefers_latest_simulation_batch_and_exposes_topic_summary(tmp_path: Path) -> None:
    report = simulate_categorized_biomimetic_telemetry(
        tmp_path,
        topics_per_category=2,
        turns_per_topic=8,
        seed=104,
        batch_id="stage103-test",
    )

    payload = build_biomimetic_visualization_payload(tmp_path)

    assert payload["trajectory"]["source"] == "biomimetic_simulation"
    assert payload["simulation"]["latest_batch_id"] == "stage103-test"
    assert payload["simulation"]["category_count"] == report["category_count"]
    assert payload["simulation"]["topic_count"] == report["topic_count"]
    assert payload["simulation"]["continuity"]["max_delta"] <= 0.22
    assert len({frame["category"] for frame in payload["trajectory"]["frames"]}) >= 5
    assert len({frame["topic"] for frame in payload["trajectory"]["frames"]}) >= 10
    assert "topic" in render_keys(payload["topology"])


def test_simulate_biomimetic_telemetry_cli(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(
        [
            "simulate-biomimetic-telemetry",
            "--topics-per-category",
            "1",
            "--turns-per-topic",
            "4",
            "--seed",
            "105",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["total_frames"] >= 20
    assert payload["continuity"]["max_delta"] <= 0.22


def render_keys(topology: dict) -> set[str]:
    return {str(node.get("layer", "")) for node in topology.get("nodes", []) if isinstance(node, dict)}
