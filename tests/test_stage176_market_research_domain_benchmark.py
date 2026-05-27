from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage176():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage176_market_research_domain_benchmark") is not None
    return importlib.import_module("holo_host.stage176_market_research_domain_benchmark")


def _fixture(fixture_id: str) -> dict:
    stage176 = _stage176()
    return next(row for row in stage176.default_market_research_domain_benchmark_fixtures() if row["fixture_id"] == fixture_id)


def test_default_domain_fixtures_cover_core_adversarial_categories() -> None:
    stage176 = _stage176()

    fixtures = stage176.default_market_research_domain_benchmark_fixtures()
    categories = {fixture["category"] for fixture in fixtures}

    assert {
        "primary_filing_ready",
        "third_party_source_pollution",
        "missing_filing_section",
        "metric_conflict",
        "period_mismatch",
        "web_only_no_filing_text",
    }.issubset(categories)


def test_primary_filing_fixture_passes_domain_benchmark() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-2024-primary-ready"))

    assert result["schema"] == "holo.stage176.market_research_domain_result.v1"
    assert result["status"] == "passed"
    assert result["domain_scorecard"]["status"] == "passed"
    assert result["stage175_live_smoke"]["status"] == "passed"
    assert result["domain_scorecard"]["checks"]["primary_source_required"]["passed"] is True
    assert result["domain_scorecard"]["checks"]["period_alignment"]["passed"] is True


def test_third_party_source_pollution_is_blocked() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-third-party-pollution"))

    assert result["status"] == "failed"
    assert "source_authority_insufficient" in result["detected_risk_flags"]
    assert result["domain_scorecard"]["checks"]["primary_source_required"]["passed"] is False
    assert result["naive_web_baseline"]["status"] == "would_answer"


def test_missing_filing_section_is_blocked() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-missing-mda-section"))

    assert result["status"] == "failed"
    assert "filing_checklist_incomplete" in result["detected_risk_flags"]
    assert result["domain_scorecard"]["checks"]["filing_coverage_complete"]["passed"] is False


def test_metric_conflict_is_blocked_and_named() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-conflicting-net-sales"))

    assert result["status"] == "failed"
    assert "metric_conflict" in result["detected_risk_flags"]
    assert result["domain_scorecard"]["checks"]["metric_consistency"]["passed"] is False
    assert result["stage173_market_research_report"]["metric_consistency"]["status"] == "conflicted"


def test_period_mismatch_is_blocked_even_when_report_generator_looks_ready() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-2024-query-2023-filing"))

    assert result["status"] == "failed"
    assert "period_mismatch" in result["detected_risk_flags"]
    assert result["domain_scorecard"]["checks"]["period_alignment"]["passed"] is False
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"


def test_web_only_no_filing_text_is_blocked() -> None:
    stage176 = _stage176()

    result = stage176.evaluate_market_research_domain_fixture(_fixture("apple-web-only-no-filing-text"))

    assert result["status"] == "failed"
    assert "filing_text_missing" in result["detected_risk_flags"]
    assert result["domain_scorecard"]["checks"]["filing_text_present"]["passed"] is False


def test_domain_benchmark_summary_measures_adversarial_detection() -> None:
    stage176 = _stage176()

    bundle = stage176.run_market_research_domain_benchmark(dry_run=True)

    assert bundle["schema"] == "holo.stage176.market_research_domain_benchmark.v1"
    assert bundle["result_count"] >= 6
    assert bundle["summary"]["primary_ready_pass_rate"] == 1.0
    assert bundle["summary"]["adversarial_detection_rate"] >= 0.8
    assert bundle["summary"]["naive_baseline_overclaim_rate"] > 0.0
    assert bundle["summary"]["pass_rate"] < 1.0


def test_cli_dry_run_writes_market_research_domain_benchmark_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage176_market_research_domain_benchmark.html"

    code = cli.main(["run-market-research-domain-bench", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage176.market_research_domain_benchmark.v1"
    assert "apple-conflicting-net-sales" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_domain_benchmark_public_artifacts_are_safe(tmp_path: Path) -> None:
    stage176 = _stage176()
    output = tmp_path / "safe.html"

    bundle = stage176.run_market_research_domain_benchmark(output=output, dry_run=True)
    ok, paths = assert_no_private_reasoning(bundle)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ok, paths
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
