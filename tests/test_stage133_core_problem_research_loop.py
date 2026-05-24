from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.stage133_core_problem_research_loop import (
    STAGE133_SCHEMA,
    build_stage133_research_payload,
    write_stage133_research_artifacts,
)


def test_stage133_covers_v2_core_problem_and_all_subproblems() -> None:
    payload = build_stage133_research_payload(probes_per_subproblem=2)

    assert payload["schema"] == STAGE133_SCHEMA
    assert payload["stage"] == 133
    assert "finite provider calls" in payload["core_problem"]
    assert payload["metrics"]["subproblem_count"] == 7
    assert payload["metrics"]["probe_count"] == 14
    assert payload["scorecard"]["checks"]["covers_all_v2_subproblems"] is True
    assert payload["scorecard"]["status"] == "pass"


def test_stage133_has_fast_only_deep_tool_visual_and_memory_paths() -> None:
    payload = build_stage133_research_payload(probes_per_subproblem=2)
    probes = payload["probes"]

    assert payload["metrics"]["route_counts"]["fast_only"] >= 1
    assert payload["metrics"]["route_counts"]["deep"] >= 1
    assert any(probe["continuation_decision"]["tool_loop_expected"] for probe in probes)
    assert any(probe["state_values"]["visual_need"] >= 0.5 for probe in probes)
    assert any(probe["state_values"]["long_memory"] >= 0.75 for probe in probes)
    assert all(probe["continuation_decision"]["fast_packet_always_first"] is True for probe in probes)
    assert all(probe["stage121_packet_policy"]["cache"]["stable_prefix_first"] is True for probe in probes)


def test_stage133_research_artifacts_are_redacted_and_interactive(tmp_path: Path) -> None:
    report = write_stage133_research_artifacts(tmp_path, output_dir=tmp_path / "artifacts" / "stage133")

    html_path = Path(report["html_path"])
    payload_path = Path(report["payload_path"])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")

    assert html_path.exists()
    assert payload_path.exists()
    assert report["probe_count"] == 14
    assert payload["privacy"]["raw_provider_content_included"] is False
    assert payload["privacy"]["raw_memory_text_included"] is False
    assert "<canvas id=\"trajectory\"" in html
    assert "<canvas id=\"slice\"" in html
    assert "Stage133 V2 Core Problem Research Loop" in html


def test_stage133_cli_dispatches_and_writes_artifacts(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(
        [
            "stage133-core-problem-loop",
            "--output-dir",
            str(tmp_path / "artifacts" / "stage133"),
            "--probes-per-subproblem",
            "1",
        ]
    )

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == 133
    assert report["probe_count"] == 7
    assert Path(report["html_path"]).exists()
    assert Path(report["payload_path"]).exists()
