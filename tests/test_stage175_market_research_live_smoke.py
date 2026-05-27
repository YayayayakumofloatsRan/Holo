from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage175():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage175_market_research_live_smoke") is not None
    return importlib.import_module("holo_host.stage175_market_research_live_smoke")


def _fixture(fixture_id: str) -> dict:
    stage175 = _stage175()
    return next(row for row in stage175.default_market_research_live_smoke_fixtures() if row["fixture_id"] == fixture_id)


def test_ready_fixture_runs_through_stage152_fsm_event_stream_and_topology() -> None:
    stage175 = _stage175()

    result = stage175.evaluate_market_research_live_smoke_fixture(_fixture("apple-10k-ready-live-smoke"))

    assert result["schema"] == "holo.stage175.market_research_live_smoke_result.v1"
    assert result["status"] == "passed"
    assert result["stage152_deepseek_tool_loop"]["market_research_report_ledger"][0]["status"] == "ok"
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"
    assert result["stage160r_agent_loop_fsm"]["canonical_stop_reason"] == "final_answer_ready"
    assert result["stage153_agent_event_stream"]["event_count"] > 0
    assert result["stage135_i_state_topology"]["metrics"]["market_research_report_action_node_count"] >= 1
    assert result["stage135_i_state_topology"]["metrics"]["market_research_report_node_count"] >= 1
    assert result["scorecard"]["overall_score"] >= 0.8


def test_ready_fixture_event_stream_exposes_real_report_action() -> None:
    stage175 = _stage175()

    result = stage175.evaluate_market_research_live_smoke_fixture(_fixture("apple-10k-ready-live-smoke"))
    rendered = result["rendered_event_stream"]

    assert "[model_decide] selected=market_research_report" in rendered
    assert "[act] market_research_report status=executed" in rendered
    assert "[observe] market_research_report status=ok" in rendered
    assert "[stop] final_answer_ready" in rendered


def test_scorecard_requires_citations_and_evidence_ready_report() -> None:
    stage175 = _stage175()

    result = stage175.evaluate_market_research_live_smoke_fixture(_fixture("apple-10k-ready-live-smoke"))
    scorecard = result["scorecard"]

    assert scorecard["schema"] == "holo.stage175.codex_style_market_research_scorecard.v1"
    assert scorecard["checks"]["report_ready"]["passed"] is True
    assert scorecard["checks"]["primary_citations_present"]["passed"] is True
    assert any(url.startswith("https://www.sec.gov/") for url in result["stage173_market_research_report"]["citations"][0].values())


def test_third_party_fixture_is_not_promoted_as_ready_research() -> None:
    stage175 = _stage175()

    result = stage175.evaluate_market_research_live_smoke_fixture(_fixture("third-party-insufficient-live-smoke"))

    assert result["status"] == "failed"
    assert result["stage173_market_research_report"]["status"] != "evidence_ready"
    assert result["scorecard"]["checks"]["report_ready"]["passed"] is False
    assert "report_not_evidence_ready" in result["failure_reasons"]


def test_live_smoke_json_does_not_expose_hidden_reasoning_or_persona_text() -> None:
    stage175 = _stage175()

    result = stage175.evaluate_market_research_live_smoke_fixture(_fixture("apple-10k-ready-live-smoke"))
    ok, paths = assert_no_private_reasoning(result)
    blob = json.dumps(result, ensure_ascii=False).lower()

    assert ok, paths
    assert "reasoning_content" not in blob
    assert "internal market reasoning" not in blob
    assert "微信" not in blob
    assert "打趣" not in blob
    assert "熟人" not in blob


def test_bundle_summary_counts_passed_and_failed_live_smoke_fixtures() -> None:
    stage175 = _stage175()

    bundle = stage175.run_market_research_live_smoke(dry_run=True)

    assert bundle["schema"] == "holo.stage175.market_research_live_smoke.v1"
    assert bundle["result_count"] >= 2
    assert bundle["summary"]["passed_count"] >= 1
    assert bundle["summary"]["failed_count"] >= 1
    assert bundle["summary"]["pass_rate"] < 1.0
    assert bundle["authority_boundary"]["provider_model_calls"] is False
    assert bundle["authority_boundary"]["live_network_required_for_tests"] is False


def test_cli_dry_run_writes_market_research_live_smoke_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage175_market_research_live_smoke.html"

    code = cli.main(["run-market-research-live-smoke", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage175.market_research_live_smoke.v1"
    assert "apple-10k-ready-live-smoke" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_public_artifacts_are_release_safe(tmp_path: Path) -> None:
    stage175 = _stage175()
    output = tmp_path / "safe.html"

    bundle = stage175.run_market_research_live_smoke(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert bundle["status"] == "failed"
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
