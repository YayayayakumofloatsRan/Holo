from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.agent_real_use_drill import (
    STAGE184_REAL_USE_DRILL_SCHEMA,
    execute_engineering_real_use_drill,
    execute_search_real_use_drill,
    run_agent_real_use_drill,
)
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "OpenAI Codex CLI",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation for a terminal coding agent.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "mock_page",
        "results": [
            {
                "title": "Codex CLI",
                "url": url,
                "snippet": "Codex CLI is an OpenAI coding agent that can read code, edit files, and run commands.",
            }
        ],
    }


def test_engineering_drill_executes_actual_search_read_patch_test_diff() -> None:
    case = execute_engineering_real_use_drill()

    assert case["schema"] == "holo.stage184.real_use_case.v1"
    assert case["status"] == "passed"
    actions = {row["action_type"]: row["status"] for row in case["engineering_action_ledger"]}
    assert actions["workspace_search"] == "ok"
    assert actions["file_read"] == "ok"
    assert actions["apply_patch"] == "ok"
    assert actions["test_run"] == "ok"
    assert actions["git_diff"] == "ok"
    assert case["engineering_claim_grounding"]["status"] == "grounded"
    assert "[eng:patch] status=ok" in case["rendered_event_stream"]
    assert "[eng:test] status=ok" in case["rendered_event_stream"]


def test_search_drill_executes_web_observation_and_grounding() -> None:
    case = execute_search_real_use_drill(
        query="official Codex CLI documentation",
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        network_enabled=True,
    )

    assert case["status"] == "passed"
    assert case["web_observation_ledger"]
    row = case["web_observation_ledger"][0]
    assert row["status"] == "ok"
    assert row["source_urls"] == ["https://developers.openai.com/codex/cli"]
    assert case["tool_decision_grounding"]["status"] == "grounded"
    assert "[tool_call] web_search" in case["rendered_event_stream"]
    assert "[observation] web_search status=ok" in case["rendered_event_stream"]


def test_network_disabled_search_drill_records_boundary_not_fake_success() -> None:
    case = execute_search_real_use_drill(
        query="official Codex CLI documentation",
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        network_enabled=False,
    )

    assert case["status"] == "passed"
    assert case["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert case["canonical_stop_reason"] == "boundary_or_permission"
    assert "cannot treat this as current web evidence" in case["visible_text"]


def test_real_use_drill_compares_full_loop_against_claim_only_baseline() -> None:
    report = run_agent_real_use_drill(dry_run=True)

    assert report["schema"] == STAGE184_REAL_USE_DRILL_SCHEMA
    assert report["status"] == "passed"
    assert report["summary"]["case_count"] >= 5
    assert report["summary"]["full_loop_score"] > report["summary"]["claim_only_baseline_score"]
    assert "unsupported_engineering_claim" in report["summary"]["baseline_failure_flags"]


def test_market_research_drill_requires_report_ledger_and_citations() -> None:
    report = run_agent_real_use_drill(dry_run=True)
    market_case = next(case for case in report["cases"] if case["case_id"] == "market-research-real-use")

    assert market_case["status"] == "passed"
    assert market_case["market_research_report_ledger"]
    assert market_case["stage173_market_research_report"]["citation_count"] >= 1
    assert market_case["stage173_market_research_report"]["status"] == "evidence_ready"


def test_cli_writes_stage184_real_use_drill_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage184_real_use_agent_drill.html"

    code = cli.main(["run-agent-real-use-drill", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == STAGE184_REAL_USE_DRILL_SCHEMA
    assert payload["status"] == "passed"


def test_stage184_public_payload_has_no_hidden_reasoning() -> None:
    report = run_agent_real_use_drill(dry_run=True)

    ok, paths = assert_no_private_reasoning(report)

    assert ok, paths
    assert "reasoning_content" not in json.dumps(report, ensure_ascii=False)


def test_stage135_topology_includes_stage184_real_use_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="stage184 real use drill",
        stage184_real_use_drill={
            "schema": STAGE184_REAL_USE_DRILL_SCHEMA,
            "status": "passed",
            "summary": {
                "case_count": 5,
                "passed_case_count": 5,
                "full_loop_score": 0.9,
                "claim_only_baseline_score": 0.2,
            },
        },
    )

    assert topology["metrics"]["real_use_drill_node_count"] == 1
    assert topology["metrics"]["real_use_drill_case_count"] == 5
    assert any(node["id"] == "stage184_real_use_drill" for node in topology["nodes"])
