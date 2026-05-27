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
from holo_host.stage177_market_research_remediation import build_market_research_remediation_result


def _stage178():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.evidence_action_remediation") is not None
    return importlib.import_module("holo_host.evidence_action_remediation")


def test_literature_source_gap_recommends_primary_literature_search() -> None:
    stage178 = _stage178()

    report = stage178.build_evidence_action_remediation(
        [
            {
                "issue_id": "lit-1",
                "domain": "literature_research",
                "issue_type": "source_missing",
                "claim": "JEPA is the best real-time world-model method",
                "required_evidence": ["primary paper", "publication metadata"],
            }
        ]
    )

    assert report["schema"] == "holo.stage178.evidence_action_remediation.v1"
    assert report["can_finalize"] is False
    assert report["recommended_stop_reason"] == "needs_evidence_action"
    assert report["actions"][0]["action_type"] == "primary_literature_search"
    assert report["actions"][0]["required_tool"] == "web_search"


def test_math_derivation_gap_recommends_assumption_derivation_before_final() -> None:
    stage178 = _stage178()

    report = stage178.build_evidence_action_remediation(
        [
            {
                "issue_id": "math-1",
                "domain": "math_research",
                "issue_type": "derivation_gap",
                "claim": "The bound follows from compactness",
                "required_evidence": ["assumptions", "intermediate lemma"],
            }
        ]
    )

    assert report["can_finalize"] is False
    assert report["actions"][0]["action_type"] == "derive_or_request_assumptions"
    assert "assumptions" in report["operator_message"].lower()


def test_gpu_experiment_failure_recommends_artifact_inspection_and_retry_plan() -> None:
    stage178 = _stage178()

    report = stage178.build_evidence_action_remediation(
        [
            {
                "issue_id": "gpu-1",
                "domain": "gpu_experiment",
                "issue_type": "experiment_failed",
                "claim": "The training job converged",
                "required_evidence": ["logs", "metrics", "checkpoint"],
            }
        ]
    )

    action_types = {row["action_type"] for row in report["actions"]}
    assert "inspect_experiment_artifacts" in action_types
    assert "plan_experiment_retry" in action_types
    assert report["canonical_stop_reason"] == "tool_failure_report"


def test_unsupported_memory_claim_recommends_memory_recall_before_answer() -> None:
    stage178 = _stage178()

    report = stage178.build_evidence_action_remediation(
        [
            {
                "issue_id": "mem-1",
                "domain": "agent_memory",
                "issue_type": "memory_unsupported",
                "claim": "I remember the user's preference",
                "required_evidence": ["memory_observation_ledger"],
            }
        ]
    )

    assert report["actions"][0]["action_type"] == "run_memory_recall"
    assert report["actions"][0]["required_tool"] == "memory_recall"
    assert report["can_finalize"] is False


def test_no_issue_report_is_finalizable() -> None:
    stage178 = _stage178()

    report = stage178.build_evidence_action_remediation([])

    assert report["can_finalize"] is True
    assert report["status"] == "ready_to_finalize"
    assert report["actions"] == []
    assert report["recommended_stop_reason"] == "final_answer_ready"


def test_stage177_result_can_be_promoted_to_generic_remediation_actions() -> None:
    stage178 = _stage178()
    fixture = next(row for row in default_market_research_domain_benchmark_fixtures() if row["fixture_id"] == "apple-conflicting-net-sales")
    stage176_result = evaluate_market_research_domain_fixture(fixture)
    stage177_result = build_market_research_remediation_result(stage176_result)

    report = stage178.build_evidence_action_remediation_from_stage177(stage177_result)

    assert report["can_finalize"] is False
    assert report["source_stage"] == "stage177"
    assert any(row["action_type"] == "compare_conflicting_evidence" for row in report["actions"])


def test_cli_dry_run_writes_evidence_action_remediation_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage178_evidence_action_remediation.html"

    code = cli.main(["run-evidence-action-remediation", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage178.evidence_action_remediation_bundle.v1"
    assert "gpu_experiment" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_evidence_action_remediation_artifacts_are_public_safe(tmp_path: Path) -> None:
    stage178 = _stage178()
    output = tmp_path / "safe.html"

    bundle = stage178.run_evidence_action_remediation(output=output, dry_run=True)
    ok, paths = assert_no_private_reasoning(bundle)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ok, paths
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob


def test_stage135_topology_includes_evidence_action_remediation_node() -> None:
    stage178 = _stage178()
    report = stage178.build_evidence_action_remediation(
        [{"issue_id": "tool-1", "domain": "engineering", "issue_type": "tool_unexecuted", "claim": "tests passed"}]
    )

    topology = build_stage135_i_state_topology(
        user_text="repair missing tool evidence",
        stage178_evidence_action_remediation=report,
    )

    assert topology["metrics"]["evidence_action_remediation_node_count"] == 1
    assert topology["metrics"]["evidence_action_remediation_action_count"] >= 1
    assert any(node["id"] == "stage178_evidence_action_remediation" for node in topology["nodes"])
