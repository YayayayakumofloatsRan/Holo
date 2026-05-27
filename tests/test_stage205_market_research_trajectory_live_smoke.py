from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage205():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.market_research_trajectory_live_smoke") is not None
    return importlib.import_module("holo_host.market_research_trajectory_live_smoke")


def test_stage205_dry_run_runs_full_market_research_trajectory(tmp_path: Path) -> None:
    stage205 = _stage205()

    bundle = stage205.run_market_research_trajectory_live_smoke(
        output=tmp_path / "stage205_trajectory_live_smoke.html",
        state_dir=tmp_path / "state",
        dry_run=True,
    )
    result = bundle["results"][0]
    trajectory = result["stage204_market_research_agent_trajectory"]

    assert bundle["schema"] == "holo.stage205.market_research_trajectory_live_smoke.v1"
    assert bundle["status"] == "passed"
    assert result["status"] == "passed"
    assert trajectory["status"] == "ready"
    assert trajectory["action_sequence"] == ["web_search", "market_research_pack", "market_research_report"]
    assert result["scorecard"]["checks"]["trajectory_ready"]["passed"] is True
    assert result["scorecard"]["checks"]["source_evidence_present"]["passed"] is True


def test_stage205_renders_public_action_trace_without_hidden_reasoning(tmp_path: Path) -> None:
    stage205 = _stage205()

    bundle = stage205.run_market_research_trajectory_live_smoke(state_dir=tmp_path / "state", dry_run=True)
    result = bundle["results"][0]
    rendered = result["rendered_event_stream"]
    blob = json.dumps(result, ensure_ascii=False) + rendered

    assert "[goal]" in rendered
    assert "[market_registry]" in rendered
    assert "[market_trajectory] step=1 action=web_search" in rendered
    assert "[market_trajectory] step=2 action=market_research_pack" in rendered
    assert "[market_trajectory] step=3 action=market_research_report" in rendered
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths
    assert "reasoning_content" not in blob
    assert "hidden chain" not in blob.lower()


def test_stage205_network_disabled_records_rejection_without_overclaim(tmp_path: Path) -> None:
    stage205 = _stage205()

    bundle = stage205.run_market_research_trajectory_live_smoke(
        state_dir=tmp_path / "state",
        dry_run=False,
        network_enabled=False,
    )
    result = bundle["results"][0]
    rows = result["stage204_market_research_agent_trajectory"]["web_observation_ledger"]
    statuses = {row["status"] for row in rows}

    assert "rejected_network_disabled" in statuses
    assert result["status"] == "failed"
    assert result["scorecard"]["checks"]["no_success_overclaim"]["passed"] is True
    assert "network_disabled" in " ".join(result["failure_reasons"])


def test_stage205_cli_writes_html_json_jsonl_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage205_trajectory_live_smoke.html"

    code = cli.main(
        [
            "run-market-research-trajectory-live-smoke",
            "--output",
            str(output),
            "--dry-run",
        ]
    )

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage205.market_research_trajectory_live_smoke.v1"
    assert "stage205-apple-trajectory" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_stage205_failing_search_reports_attempted_failure(tmp_path: Path) -> None:
    stage205 = _stage205()

    def failing_search(query: str) -> dict:
        return {
            "query": query,
            "status": "error",
            "provider": "stage205_failing_search",
            "results": [],
            "error": "simulated search failure",
        }

    result = stage205.evaluate_market_research_trajectory_live_smoke_fixture(
        stage205.default_market_research_trajectory_live_smoke_fixtures()[0],
        state_dir=tmp_path / "state",
        dry_run=False,
        network_enabled=True,
        web_search_fn=failing_search,
    )
    rendered = result["rendered_event_stream"]

    assert result["status"] == "failed"
    assert result["scorecard"]["checks"]["no_success_overclaim"]["passed"] is True
    assert any(row["status"] == "error" for row in result["stage204_market_research_agent_trajectory"]["web_observation_ledger"])
    assert "simulated search failure" in json.dumps(result, ensure_ascii=False)
    assert "ready" not in result["final_summary"].lower()
    assert "[market_trajectory] step=1 action=web_search" in rendered
