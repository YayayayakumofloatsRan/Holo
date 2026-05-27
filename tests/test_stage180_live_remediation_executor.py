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
    assert importlib.util.find_spec("holo_host.live_remediation_executor") is not None
    return importlib.import_module("holo_host.live_remediation_executor")


def _remediation(issue: dict) -> dict:
    return build_evidence_action_remediation([issue])


def test_web_search_remediation_executes_with_mocked_provider_and_records_ledgers() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        {
            "issue_id": "lit-1",
            "domain": "literature_research",
            "issue_type": "source_missing",
            "claim": "interactive world model paper evidence missing",
            "required_evidence": ["primary paper"],
        }
    )
    loop = build_live_remediation_loop(remediation, goal_id="goal:test")

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [{"title": "Interactive World Model", "url": "https://arxiv.org/abs/0000.00000", "snippet": "paper"}],
        },
    )

    assert report["schema"] == "holo.stage180.live_remediation_executor.v1"
    assert report["status"] == "executed"
    assert report["executed_count"] == 1
    assert report["web_observation_ledger"][0]["status"] == "ok"
    assert report["web_observation_ledger"][0]["source_urls"] == ["https://arxiv.org/abs/0000.00000"]
    assert report["action_results"][0]["action_type"] == "primary_literature_search"


def test_network_disabled_rejects_web_remediation_without_fetching() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        {
            "issue_id": "src-1",
            "domain": "literature_research",
            "issue_type": "source_missing",
            "claim": "needs source",
        }
    )
    loop = build_live_remediation_loop(remediation)

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=False,
        web_search_fn=lambda query: (_ for _ in ()).throw(AssertionError("network should not be called")),
    )

    assert report["status"] == "blocked"
    assert report["rejected_count"] == 1
    assert report["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert report["canonical_stop_reason"] == "boundary_or_permission"


def test_file_read_remediation_executes_for_explicit_artifact_path(tmp_path: Path) -> None:
    stage180 = _stage180()
    log_path = tmp_path / "runs" / "train.log"
    log_path.parent.mkdir()
    log_path.write_text("epoch=1 loss=nan\nerror=diverged\n", encoding="utf-8")
    remediation = _remediation(
        {
            "issue_id": "gpu-1",
            "domain": "gpu_experiment",
            "issue_type": "experiment_failed",
            "claim": "training converged",
            "artifact_paths": ["runs/train.log"],
        }
    )
    loop = build_live_remediation_loop(remediation)

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        repo_root=tmp_path,
        network_enabled=False,
        max_actions=1,
    )

    assert report["status"] == "partial"
    assert report["canonical_stop_reason"] == "budget_exhausted"
    assert report["remaining_action_candidates"][0]["action_type"] == "plan_experiment_retry"
    assert report["engineering_action_ledger"][0]["action_type"] == "file_read"
    assert report["engineering_action_ledger"][0]["status"] == "ok"
    assert "loss=nan" in report["engineering_action_ledger"][0]["stdout_summary"]


def test_memory_recall_remediation_uses_injected_host_recall() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        {
            "issue_id": "mem-1",
            "domain": "agent_memory",
            "issue_type": "memory_unsupported",
            "claim": "user prefers no emoji",
        }
    )
    loop = build_live_remediation_loop(remediation, goal_id="goal:memory")

    report = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        memory_recall_fn=lambda query: {
            "memory_call_id": "mem:test",
            "query": query,
            "status": "grounded",
            "selected_ids": ["m1"],
            "summary": "user directive: avoid emoji",
            "confidence": 0.92,
        },
    )

    assert report["status"] == "executed"
    assert report["memory_observation_ledger"][0]["status"] == "grounded"
    assert report["memory_observation_ledger"][0]["selected_ids"] == ["m1"]


def test_fsm_accepts_executed_remediation_and_exposes_execution_metadata() -> None:
    stage180 = _stage180()
    remediation = _remediation(
        {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "preference"}
    )
    loop = build_live_remediation_loop(remediation)
    execution = stage180.execute_live_remediation_actions(
        loop,
        stage178_evidence_action_remediation=remediation,
        memory_recall_fn=lambda query: {
            "memory_call_id": "mem:test",
            "status": "grounded",
            "selected_ids": ["m1"],
            "summary": "grounded memory",
            "confidence": 0.9,
        },
    )
    frame = build_intent_frame("recall preference")

    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        stage178_evidence_action_remediation=remediation,
        stage180_live_remediation_execution=execution,
        final_text="grounded after remediation",
    )

    assert fsm["stage180_live_remediation_execution"]["status"] == "executed"
    assert fsm["canonical_stop_reason"] == "final_answer_ready"
    assert fsm["next_action_candidates"] == []
    assert any(step["phase"] == "remediation_execute" for step in fsm["steps"])
    assert "grounded memory" in fsm["final_text"]
    assert "found no grounded" not in fsm["final_text"]


def test_event_stream_renders_remediation_execution() -> None:
    stage180 = _stage180()
    execution = {
        "schema": "holo.stage180.live_remediation_executor.v1",
        "status": "executed",
        "action_results": [{"action_type": "run_memory_recall", "status": "executed", "observation_count": 1}],
        "canonical_stop_reason": "final_answer_ready",
    }
    stream = build_agent_event_stream(
        {"text": "done", "stage180_live_remediation_execution": execution},
        user_text="test",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[remediation_exec]" in rendered
    assert "run_memory_recall" in rendered


def test_cli_dry_run_writes_live_remediation_execution_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage180_live_remediation_execution.html"

    code = cli.main(["run-live-remediation-execution", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage180.live_remediation_execution_simulation.v1"
    assert payload["summary"]["executed_case_count"] >= 2


def test_stage135_topology_includes_live_remediation_executor_node() -> None:
    stage180 = _stage180()
    execution = {
        "schema": "holo.stage180.live_remediation_executor.v1",
        "status": "executed",
        "executed_count": 1,
        "action_results": [{"action_type": "run_memory_recall", "status": "executed"}],
    }
    topology = build_stage135_i_state_topology(
        user_text="simulate execution",
        stage180_live_remediation_execution=execution,
    )

    assert topology["metrics"]["live_remediation_executor_node_count"] == 1
    assert topology["metrics"]["live_remediation_executed_count"] == 1
    assert any(node["id"] == "stage180_live_remediation_executor" for node in topology["nodes"])


def test_live_remediation_execution_public_payload_has_no_hidden_reasoning() -> None:
    stage180 = _stage180()
    bundle = stage180.run_live_remediation_execution_simulation(dry_run=True)

    ok, paths = assert_no_private_reasoning(bundle)

    assert ok, paths
    assert "reasoning_content" not in json.dumps(bundle, ensure_ascii=False)
