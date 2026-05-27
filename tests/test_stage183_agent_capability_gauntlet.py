from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.agent_capability_gauntlet import (
    AGENT_CAPABILITY_GAUNTLET_SCHEMA,
    default_agent_capability_gauntlet_fixtures,
    evaluate_agent_capability_case,
    run_agent_capability_gauntlet,
)
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def test_default_gauntlet_covers_core_agent_capability_categories() -> None:
    report = run_agent_capability_gauntlet(dry_run=True)

    assert report["schema"] == AGENT_CAPABILITY_GAUNTLET_SCHEMA
    categories = {case["category_id"] for case in report["cases"]}
    assert {
        "engineering_execution",
        "market_research_report",
        "remediation_continuation",
        "adversarial_unsupported_claim",
    }.issubset(categories)
    assert report["summary"]["case_count"] >= 4


def test_adversarial_engineering_claim_must_be_detected_not_passed_as_success() -> None:
    case = {
        "case_id": "unsupported-engineering",
        "category_id": "adversarial_unsupported_claim",
        "expected_outcome": "detect_failure",
        "visible_text": "I read the file, patched it, and tests passed.",
        "metadata": {"engineering_action_ledger": [], "stage153_agent_event_stream": {"events": []}},
        "expected_failure_flags": ["unsupported_engineering_claim"],
    }

    result = evaluate_agent_capability_case(case)

    assert result["status"] == "passed"
    assert "unsupported_engineering_claim" in result["failure_flags"]
    assert result["raw_case_status"] == "failed"


def test_engineering_success_requires_read_patch_test_and_trace_ledgers() -> None:
    report = run_agent_capability_gauntlet(
        dry_run=True,
        fixtures=[case for case in default_agent_capability_gauntlet_fixtures() if case["case_id"] == "engineering-grounded"],
    )
    case = report["cases"][0]

    assert case["status"] == "passed"
    assert case["metrics"]["engineering_grounding_score"] == 1.0
    assert case["metrics"]["action_trace_score"] >= 0.8
    assert case["failure_flags"] == []


def test_market_research_case_requires_evidence_ready_report_ledger() -> None:
    report = run_agent_capability_gauntlet(
        dry_run=True,
        fixtures=[case for case in default_agent_capability_gauntlet_fixtures() if case["case_id"] == "market-research-grounded"],
    )
    case = report["cases"][0]

    assert case["status"] == "passed"
    assert case["metrics"]["market_research_score"] == 1.0
    assert case["metrics"]["evidence_integrity_score"] >= 0.8


def test_remediation_case_requires_stage182_continuation_event() -> None:
    report = run_agent_capability_gauntlet(
        dry_run=True,
        fixtures=[case for case in default_agent_capability_gauntlet_fixtures() if case["case_id"] == "remediation-continuation-grounded"],
    )
    case = report["cases"][0]

    assert case["status"] == "passed"
    assert case["metrics"]["remediation_closure_score"] >= 0.8
    assert "[remediation_continue]" in case["rendered_event_stream"]


def test_cli_writes_stage183_gauntlet_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage183_agent_capability_gauntlet.html"

    code = cli.main(["run-agent-capability-gauntlet", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == AGENT_CAPABILITY_GAUNTLET_SCHEMA
    assert payload["status"] == "passed"


def test_stage183_public_payload_has_no_hidden_reasoning() -> None:
    report = run_agent_capability_gauntlet(dry_run=True)

    ok, paths = assert_no_private_reasoning(report)

    assert ok, paths
    assert "reasoning_content" not in json.dumps(report, ensure_ascii=False)


def test_stage135_topology_includes_stage183_gauntlet_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="stage183 gauntlet",
        stage183_agent_capability_gauntlet={
            "schema": AGENT_CAPABILITY_GAUNTLET_SCHEMA,
            "status": "passed",
            "summary": {
                "case_count": 4,
                "passed_case_count": 4,
                "overall_score": 0.91,
            },
        },
    )

    assert topology["metrics"]["agent_capability_gauntlet_node_count"] == 1
    assert topology["metrics"]["agent_capability_gauntlet_case_count"] == 4
    assert any(node["id"] == "stage183_agent_capability_gauntlet" for node in topology["nodes"])
