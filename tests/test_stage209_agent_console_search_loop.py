from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage209():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.agent_console_search_loop_smoke") is not None
    return importlib.import_module("holo_host.agent_console_search_loop_smoke")


def test_stage209_reply_path_continues_from_weak_source_to_official_source(tmp_path: Path) -> None:
    stage209 = _stage209()

    bundle = stage209.run_agent_console_search_loop_smoke(
        output=tmp_path / "stage209_agent_console_search_loop.html",
        state_dir=tmp_path / "state",
        dry_run=True,
    )
    result = bundle["results"][0]
    crawler = result["stage186_live_crawler_search"]
    console = result["rendered_console"]

    assert bundle["schema"] == "holo.stage209.agent_console_search_loop_smoke.v1"
    assert bundle["status"] == "passed"
    assert result["status"] == "passed"
    assert crawler["status"] == "sufficient"
    assert crawler["query_count"] >= 2
    assert console.count("[crawl:query]") >= 2
    assert "[model_decide] selected=web_search" in console
    assert "https://developers.openai.com/codex/cli" in result["final_text"]
    assert "https://example.com/codex-overview" not in crawler["source_urls"]
    assert result["scorecard"]["checks"]["continued_after_weak_source"]["passed"] is True
    assert result["scorecard"]["checks"]["model_decision_matches_crawler_action"]["passed"] is True
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths


def test_stage209_cli_writes_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage209_agent_console_search_loop.html"

    code = cli.main(
        [
            "run-agent-console-search-loop-smoke",
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
    assert payload["schema"] == "holo.stage209.agent_console_search_loop_smoke.v1"
    assert payload["status"] == "passed"
    assert "stage209-codex-cli-multistep" in output.with_suffix(".jsonl").read_text(encoding="utf-8")
