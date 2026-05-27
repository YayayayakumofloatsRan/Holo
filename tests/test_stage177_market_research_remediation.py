from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage176_market_research_domain_benchmark import (
    default_market_research_domain_benchmark_fixtures,
    evaluate_market_research_domain_fixture,
)


def _stage177():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage177_market_research_remediation") is not None
    return importlib.import_module("holo_host.stage177_market_research_remediation")


def _domain_result(fixture_id: str) -> dict:
    fixture = next(row for row in default_market_research_domain_benchmark_fixtures() if row["fixture_id"] == fixture_id)
    return evaluate_market_research_domain_fixture(fixture)


def _action_types(result: dict) -> set[str]:
    return {str(row.get("action_type", "") or "") for row in result.get("remediation_actions", [])}


def test_source_authority_insufficient_recommends_primary_source_retry() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-third-party-pollution"))

    assert result["schema"] == "holo.stage177.market_research_remediation_result.v1"
    assert result["can_finalize"] is False
    assert result["recommended_stop_reason"] == "needs_source_retry"
    assert "source_authority_insufficient" in result["risk_flags"]
    assert "retry_primary_source_search" in _action_types(result)
    retry = next(row for row in result["remediation_actions"] if row["action_type"] == "retry_primary_source_search")
    assert retry["required_tool"] == "web_search"
    assert "site:sec.gov" in retry["recommended_query"].lower()


def test_period_mismatch_recommends_period_refetch_or_clarification() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-2024-query-2023-filing"))

    assert result["can_finalize"] is False
    assert "period_mismatch" in result["risk_flags"]
    assert "clarify_or_refetch_period" in _action_types(result)
    assert "2024" in result["operator_message"]
    assert "2023" in result["operator_message"]


def test_metric_conflict_requires_conflict_report_without_settled_metric() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-conflicting-net-sales"))

    assert result["can_finalize"] is False
    assert "metric_conflict" in result["risk_flags"]
    assert "produce_metric_conflict_report" in _action_types(result)
    assert "conflict" in result["operator_message"].lower()
    assert "$391.0 billion" not in result["operator_message"]
    assert "$999.0 billion" not in result["operator_message"]


def test_missing_filing_section_recommends_complete_filing_text_retrieval() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-missing-mda-section"))

    assert result["can_finalize"] is False
    assert "filing_checklist_incomplete" in result["risk_flags"]
    assert "retrieve_complete_filing_text" in _action_types(result)


def test_missing_filing_text_recommends_text_or_primary_url_request() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-web-only-no-filing-text"))

    assert result["can_finalize"] is False
    assert "filing_text_missing" in result["risk_flags"]
    assert "request_filing_text_or_open_primary_url" in _action_types(result)
    assert "cannot finalize" in result["operator_message"].lower()


def test_primary_ready_result_is_finalizable_without_remediation() -> None:
    stage177 = _stage177()

    result = stage177.build_market_research_remediation_result(_domain_result("apple-2024-primary-ready"))

    assert result["can_finalize"] is True
    assert result["status"] == "ready_to_finalize"
    assert result["recommended_stop_reason"] == "final_answer_ready"
    assert result["remediation_actions"] == []


def test_remediation_bundle_counts_required_and_finalizable_cases() -> None:
    stage177 = _stage177()

    bundle = stage177.run_market_research_remediation(dry_run=True)

    assert bundle["schema"] == "holo.stage177.market_research_remediation.v1"
    assert bundle["result_count"] >= 6
    assert bundle["summary"]["remediation_required_count"] >= 5
    assert bundle["summary"]["finalizable_count"] >= 1
    assert bundle["summary"]["critical_action_count"] >= 5


def test_cli_dry_run_writes_market_research_remediation_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage177_market_research_remediation.html"

    code = cli.main(["run-market-research-remediation", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage177.market_research_remediation.v1"
    assert "retry_primary_source_search" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_remediation_artifacts_are_public_safe(tmp_path: Path) -> None:
    stage177 = _stage177()
    output = tmp_path / "safe.html"

    bundle = stage177.run_market_research_remediation(output=output, dry_run=True)
    ok, paths = assert_no_private_reasoning(bundle)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ok, paths
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob


def test_stage135_topology_includes_market_research_remediation_node() -> None:
    stage177 = _stage177()
    remediation = stage177.build_market_research_remediation_result(_domain_result("apple-conflicting-net-sales"))

    topology = build_stage135_i_state_topology(
        user_text="repair market research result",
        stage177_market_research_remediation=remediation,
    )

    assert topology["metrics"]["market_research_remediation_node_count"] == 1
    assert topology["metrics"]["market_research_remediation_required_count"] == 1
    assert any(node["id"] == "stage177_market_research_remediation" for node in topology["nodes"])
