from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage214():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.market_research_operator_run") is not None
    return importlib.import_module("holo_host.market_research_operator_run")


def test_stage214_operator_run_executes_research_pipeline(tmp_path: Path) -> None:
    stage214 = _stage214()

    bundle = stage214.run_market_research_operator_run_bundle(
        output=tmp_path / "stage214_market_research_operator_run.html",
        dry_run=True,
    )
    result = bundle["results"][0]
    phase_names = [row["phase"] for row in result["operator_trajectory"]]

    assert bundle["schema"] == "holo.stage214.market_research_operator_run_bundle.v1"
    assert bundle["status"] == "passed"
    assert result["schema"] == "holo.stage214.market_research_operator_run.v1"
    assert result["status"] == "ready"
    assert phase_names == [
        "plan",
        "crawl",
        "promote_source",
        "build_pack",
        "build_report",
        "assemble_report",
        "finalize",
        "action_journal",
    ]
    assert result["stage186_live_crawler_search"]["query_count"] >= 2
    assert result["stage196_market_research_source_promotion"]["status"] == "promoted"
    assert result["stage196_market_research_source_promotion"]["selected_url"].startswith("https://www.sec.gov/")
    assert result["stage169_market_research_pack"]["status"] == "ready"
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"
    assert result["stage197_market_research_report_assembly"]["status"] == "assembled"
    assert result["stage198_market_research_finalization_gate"]["final_visible_text_ready"] is True
    assert result["stage173_market_research_report"]["unsupported_claim_count"] == 0
    assert "[crawl:query]" in result["rendered_action_journal"]
    assert "[feedback]" in result["rendered_action_journal"]
    assert result["scorecard"]["checks"]["complete_pipeline"]["passed"] is True
    assert result["scorecard"]["checks"]["action_journal_visible"]["passed"] is True
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths


def test_stage214_cli_writes_resumable_operator_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage214_market_research_operator_run.html"

    code = cli.main(
        [
            "run-market-research-operator-run",
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
    jsonl = output.with_suffix(".jsonl").read_text(encoding="utf-8")
    row = payload["results"][0]
    assert payload["schema"] == "holo.stage214.market_research_operator_run_bundle.v1"
    assert payload["status"] == "passed"
    assert row["operator_run_id"] in jsonl
    assert row["stage198_market_research_finalization_gate"]["status"] == "finalized"
    assert row["final_visible_text"].startswith("Market research report:")
