from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.evidence_action_remediation import build_evidence_action_remediation
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _stage179():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.live_remediation_loop") is not None
    return importlib.import_module("holo_host.live_remediation_loop")


def test_remediation_report_blocks_fsm_final_and_adds_next_action_candidate() -> None:
    remediation = build_evidence_action_remediation(
        [
            {
                "issue_id": "lit-1",
                "domain": "literature_research",
                "issue_type": "source_missing",
                "claim": "world model paper claim lacks citation",
            }
        ]
    )
    frame = build_intent_frame("summarize current world model papers")

    fsm = run_agent_loop_fsm(intent_frame=frame, final_text="draft answer", stage178_evidence_action_remediation=remediation)

    assert fsm["stage178_evidence_action_remediation"]["status"] == "remediation_required"
    assert fsm["canonical_stop_reason"] == "evidence_exhausted"
    assert fsm["final_text"] == remediation["operator_message"]
    assert fsm["next_action_candidates"][0]["action_type"] == "primary_literature_search"
    assert any(step["phase"] == "remediation_decide" for step in fsm["steps"])


def test_remediation_event_stream_shows_remediation_and_next_action() -> None:
    remediation = build_evidence_action_remediation(
        [
            {
                "issue_id": "gpu-1",
                "domain": "gpu_experiment",
                "issue_type": "experiment_failed",
                "claim": "training converged",
            }
        ]
    )
    frame = build_intent_frame("continue the GPU experiment")
    fsm = run_agent_loop_fsm(intent_frame=frame, stage178_evidence_action_remediation=remediation)

    stream = build_agent_event_stream(
        {
            "text": fsm["final_text"],
            "stage160r_agent_loop_fsm": fsm,
            "stage178_evidence_action_remediation": remediation,
        },
        user_text="continue the GPU experiment",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[remediation]" in rendered
    assert "inspect_experiment_artifacts" in rendered
    assert "[stop] tool_failure_report" in rendered


def test_ready_remediation_does_not_override_final_answer() -> None:
    remediation = build_evidence_action_remediation([])
    frame = build_intent_frame("answer directly")

    fsm = run_agent_loop_fsm(intent_frame=frame, final_text="final answer", stage178_evidence_action_remediation=remediation)

    assert fsm["canonical_stop_reason"] == "final_answer_ready"
    assert fsm["final_text"] == "final answer"
    assert fsm["next_action_candidates"] == []


def test_live_remediation_simulation_exercises_literature_math_gpu_memory_cases() -> None:
    stage179 = _stage179()

    bundle = stage179.run_live_remediation_simulation(dry_run=True)

    assert bundle["schema"] == "holo.stage179.live_remediation_loop_simulation.v1"
    assert bundle["summary"]["case_count"] >= 4
    assert bundle["summary"]["blocked_case_count"] >= 4
    assert {"literature_research", "math_research", "gpu_experiment", "agent_memory"}.issubset(
        set(bundle["summary"]["domains"])
    )
    assert all(row["stage160r_agent_loop_fsm"]["next_action_candidates"] for row in bundle["cases"] if not row["stage178_evidence_action_remediation"]["can_finalize"])


def test_cli_dry_run_writes_live_remediation_simulation_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage179_live_remediation_loop.html"

    code = cli.main(["run-live-remediation-simulation", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage179.live_remediation_loop_simulation.v1"
    assert "remediation" in output.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_live_remediation_artifacts_are_public_safe(tmp_path: Path) -> None:
    stage179 = _stage179()
    output = tmp_path / "safe.html"

    bundle = stage179.run_live_remediation_simulation(output=output, dry_run=True)
    ok, paths = assert_no_private_reasoning(bundle)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ok, paths
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob


def test_stage135_topology_includes_live_remediation_loop_node() -> None:
    stage179 = _stage179()
    case = stage179.run_live_remediation_simulation(dry_run=True)["cases"][0]

    topology = build_stage135_i_state_topology(
        user_text="simulate remediation loop",
        stage179_live_remediation_loop=case["stage179_live_remediation_loop"],
        stage160r_agent_loop_fsm=case["stage160r_agent_loop_fsm"],
        stage178_evidence_action_remediation=case["stage178_evidence_action_remediation"],
    )

    assert topology["metrics"]["live_remediation_loop_node_count"] == 1
    assert topology["metrics"]["live_remediation_next_action_count"] >= 1
    assert any(node["id"] == "stage179_live_remediation_loop" for node in topology["nodes"])
