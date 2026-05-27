from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

from holo_host import cli
from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.evidence_action_remediation import build_evidence_action_remediation
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.live_remediation_loop import build_live_remediation_loop
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _stage180():
    return importlib.import_module("holo_host.live_remediation_executor")


def _stage181():
    assert importlib.util.find_spec("holo_host.live_remediation_stress") is not None
    return importlib.import_module("holo_host.live_remediation_stress")


def _remediation(issues: list[dict]) -> dict:
    return build_evidence_action_remediation(issues)


def test_web_remediation_uses_fallback_success_after_primary_failure() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        [
            {
                "issue_id": "lit-fallback",
                "domain": "literature_research",
                "issue_type": "source_missing",
                "claim": "official source required",
            }
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {"query": query, "status": "error", "error": "primary timeout", "provider": "primary"},
        fallback_search_fns=[
            (
                "fallback",
                lambda query: {
                    "query": query,
                    "status": "ok",
                    "provider": "fallback",
                    "results": [{"title": "official source", "url": "https://example.com/official", "snippet": "official"}],
                },
            )
        ],
    )

    assert report["status"] == "executed"
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert any(row["status"] == "ok" and row["provider"] == "fallback" for row in report["web_observation_ledger"])
    assert report["action_results"][0]["status"] == "executed"


def test_multi_action_budget_keeps_remaining_candidates_instead_of_false_final() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        [
            {
                "issue_id": "src-1",
                "domain": "literature_research",
                "issue_type": "source_missing",
                "claim": "source missing",
            },
            {
                "issue_id": "mem-1",
                "domain": "agent_memory",
                "issue_type": "memory_unsupported",
                "claim": "memory claim unsupported",
            },
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [{"title": "source", "url": "https://example.com/source", "snippet": "source"}],
        },
        memory_recall_fn=lambda query: {
            "memory_call_id": "mem:should-not-run-yet",
            "status": "grounded",
            "summary": "memory",
            "selected_ids": ["m1"],
        },
        max_actions=1,
    )

    assert report["status"] == "partial"
    assert report["executed_count"] == 1
    assert report["skipped_count"] == 1
    assert report["next_action_required"] is True
    assert report["canonical_stop_reason"] == "budget_exhausted"
    assert report["remaining_action_candidates"][0]["action_type"] == "run_memory_recall"


def test_missing_artifact_path_stops_for_clarification_not_boundary() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        [
            {
                "issue_id": "gpu-1",
                "domain": "gpu_experiment",
                "issue_type": "experiment_failed",
                "claim": "training succeeded",
            }
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        repo_root=Path.cwd(),
        max_actions=1,
    )

    assert report["status"] == "blocked"
    assert report["canonical_stop_reason"] == "needs_user_clarification"
    assert report["action_results"][0]["error"] == "artifact_path_required"


def test_fsm_partial_execution_keeps_only_remaining_candidates() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        [
            {"issue_id": "src-1", "domain": "literature_research", "issue_type": "source_missing", "claim": "source"},
            {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "memory"},
        ]
    )
    loop = build_live_remediation_loop(remediation)
    execution = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [{"title": "source", "url": "https://example.com/source", "snippet": "source"}],
        },
        max_actions=1,
    )
    fsm = run_agent_loop_fsm(
        intent_frame=build_intent_frame("continue evidence remediation"),
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=execution,
        final_text="draft",
    )

    assert fsm["canonical_stop_reason"] == "budget_exhausted"
    assert len(fsm["next_action_candidates"]) == 1
    assert fsm["next_action_candidates"][0]["action_type"] == "run_memory_recall"
    assert any(step["phase"] == "remediation_execute" for step in fsm["steps"])
    assert "budget" in fsm["final_text"].lower()
    assert "run_memory_recall" in fsm["final_text"]


def test_event_stream_reports_partial_execution_budget_stop() -> None:
    execution = {
        "schema": "holo.stage180.live_remediation_executor.v1",
        "status": "partial",
        "action_results": [{"action_type": "primary_source_search", "status": "executed", "observation_count": 1}],
        "remaining_action_candidates": [{"action_type": "run_memory_recall"}],
        "canonical_stop_reason": "budget_exhausted",
    }
    stream = build_agent_event_stream(
        {
            "text": "partial",
            "stage160r_agent_loop_fsm": {
                "schema": "holo.stage160r.agent_loop_fsm.v1",
                "canonical_stop_reason": "budget_exhausted",
                "stop_reason": "budget_exhausted",
                "steps": [
                    {"phase": "remediation_execute", "selected_action": "primary_source_search", "action_status": "partial", "required_observations": ["web_observation_ledger"]}
                ],
            },
            "stage180_live_remediation_execution": execution,
        },
        user_text="stress",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[remediation_exec]" in rendered
    assert "[stop] budget_exhausted" in rendered


def test_fsm_uses_rejected_execution_instead_of_reverting_to_plan() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        [{"issue_id": "net-1", "domain": "literature_research", "issue_type": "source_missing", "claim": "needs web"}]
    )
    loop = build_live_remediation_loop(remediation)
    execution = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=False,
        web_search_fn=lambda query: (_ for _ in ()).throw(AssertionError("network should not fetch")),
    )

    fsm = run_agent_loop_fsm(
        intent_frame=build_intent_frame("search evidence"),
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=execution,
        final_text="draft",
    )

    assert fsm["canonical_stop_reason"] == "boundary_or_permission"
    assert any(step["phase"] == "remediation_execute" for step in fsm["steps"])
    assert not any(step["phase"] == "remediation_plan" for step in fsm["steps"])
    assert "network_disabled" in fsm["final_text"]


def test_stage181_stress_simulation_scores_adversarial_cases(tmp_path: Path) -> None:
    stage181 = _stage181()
    output = tmp_path / "stage181_live_remediation_stress.html"

    bundle = stage181.run_live_remediation_stress_simulation(output=output, dry_run=True)

    assert bundle["schema"] == "holo.stage181.live_remediation_stress.v1"
    assert bundle["status"] == "passed"
    assert bundle["summary"]["case_count"] >= 4
    assert bundle["summary"]["fallback_recovery_count"] >= 1
    assert bundle["summary"]["budget_guard_count"] >= 1
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()


def test_cli_writes_stage181_stress_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage181_live_remediation_stress.html"

    code = cli.main(["run-live-remediation-stress", "--output", str(output), "--dry-run"])

    assert code == 0
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage181.live_remediation_stress.v1"
    assert payload["status"] == "passed"


def test_stage135_topology_includes_stage181_stress_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="stage181 stress",
        stage181_live_remediation_stress={
            "schema": "holo.stage181.live_remediation_stress.v1",
            "status": "passed",
            "summary": {"case_count": 4, "fallback_recovery_count": 1, "budget_guard_count": 1},
        },
    )

    assert topology["metrics"]["live_remediation_stress_node_count"] == 1
    assert topology["metrics"]["live_remediation_stress_case_count"] == 4
    assert any(node["id"] == "stage181_live_remediation_stress" for node in topology["nodes"])


def test_stage181_public_payload_has_no_hidden_reasoning() -> None:
    stage181 = _stage181()
    bundle = stage181.run_live_remediation_stress_simulation(dry_run=True)

    ok, paths = assert_no_private_reasoning(bundle)

    assert ok, paths
    assert "reasoning_content" not in json.dumps(bundle, ensure_ascii=False)
