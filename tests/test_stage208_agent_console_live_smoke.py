from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage208():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.agent_console_live_smoke") is not None
    return importlib.import_module("holo_host.agent_console_live_smoke")


def test_stage208_dry_run_exercises_reply_path_crawler_and_console(tmp_path: Path) -> None:
    stage208 = _stage208()

    bundle = stage208.run_agent_console_live_smoke(
        output=tmp_path / "stage208_agent_console_live_smoke.html",
        state_dir=tmp_path / "state",
        dry_run=True,
    )
    result = bundle["results"][0]
    crawler = result["stage186_live_crawler_search"]
    console = result["rendered_console"]
    final_text = result["final_text"]

    assert bundle["schema"] == "holo.stage208.agent_console_live_smoke.v1"
    assert bundle["status"] == "passed"
    assert result["status"] == "passed"
    assert crawler["status"] == "sufficient"
    assert "https://developers.openai.com/codex/cli" in crawler["source_urls"]
    assert "[crawl:query]" in console
    assert "[crawl:open] status=ok url=https://developers.openai.com/codex/cli" in console
    assert "[crawl:stop] status=sufficient reason=sufficient_evidence" in console
    assert "https://developers.openai.com/codex/cli" in final_text
    assert "will search" not in final_text.lower()
    assert result["canonical_stop_reason"] != "unknown"
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths


def test_stage208_failed_search_reports_attempted_failure_in_console(tmp_path: Path) -> None:
    stage208 = _stage208()
    fixture = dict(stage208.default_agent_console_live_smoke_fixtures()[0])
    fixture["fixture_id"] = "stage208-failing-search"
    fixture["search_mode"] = "fail"
    fixture["expected_status"] = "failed"

    result = stage208.evaluate_agent_console_live_smoke_fixture(
        fixture,
        state_dir=tmp_path / "state",
        dry_run=True,
    )
    final_text = result["final_text"].lower()

    assert result["status"] == "failed"
    assert result["stage186_live_crawler_search"]["status"] == "failed"
    assert "simulated_search_failure" in final_text
    assert "attempted web_search" in final_text
    assert "will search" not in final_text
    assert "[crawl:stop] status=failed reason=tool_failure_report" in result["rendered_console"]
    assert result["canonical_stop_reason"] != "unknown"


def test_stage208_cli_writes_html_json_jsonl_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage208_agent_console_live_smoke.html"

    code = cli.main(
        [
            "run-agent-console-live-smoke",
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
    assert payload["schema"] == "holo.stage208.agent_console_live_smoke.v1"
    assert payload["status"] == "passed"
    assert "stage208-codex-cli-docs" in output.with_suffix(".jsonl").read_text(encoding="utf-8")
