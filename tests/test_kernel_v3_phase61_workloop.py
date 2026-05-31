from pathlib import Path
import json
import subprocess
import sys

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.workloop import assess_progress, workloop_state
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import Observation
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator


def test_phase61_retrieval_with_new_citation_finalizes_and_journals_decisions():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory()).run(
        "Kernel v3 retrieval",
        mode="retrieval",
    )

    assert result.status == "completed"
    assert result.final_answer["citation_refs"]
    assert [record.data["decision"] for record in journal.records(task_id=result.task_id, kind="termination_decision")] == [
        "final_answer"
    ]
    assert journal.records(task_id=result.task_id, kind="progress_assessment")
    assert journal.records(task_id=result.task_id, kind="repetition_signal")
    assert journal.records(task_id=result.task_id, kind="evidence_sufficiency")


def test_phase61_retrieval_without_new_evidence_continues_once_then_fails():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("missing", mode="retrieval")

    assert result.status == "failed"
    assert result.failure_report["reason"] == "repeated_no_progress"
    assert result.failure_report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    decisions = [record.data for record in journal.records(task_id=result.task_id, kind="termination_decision")]
    assert [item["decision"] for item in decisions] == ["continue", "failure_report"]
    assert decisions[0]["reason"] == "insufficient_evidence_retry"


def test_phase61_retrieval_resume_gets_fresh_repetition_budget_and_unique_action_ids():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    first = runtime.run("missing", mode="retrieval")
    second = runtime.resume(first.task_id, "still missing", mode="retrieval")

    assert first.status == "failed"
    assert second.status == "failed"
    assert second.run_id == "run-2"
    decisions = [
        record.data
        for record in journal.records(task_id=first.task_id, kind="termination_decision")
        if record.run_id == "run-2"
    ]
    assert [item["decision"] for item in decisions] == ["continue", "failure_report"]
    assert decisions[0]["reason"] == "insufficient_evidence_retry"
    action_ids = [record.data["action_id"] for record in journal.records(task_id=first.task_id, kind="action")]
    assert len(action_ids) == len(set(action_ids))
    assert any(action_id.endswith("-run-1") for action_id in action_ids)
    assert any(action_id.endswith("-run-2") for action_id in action_ids)


def test_phase61_retrieval_resume_does_not_reuse_previous_run_evidence():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    first = AgentRuntime(journal=journal, artifact_store=artifacts).run("grounded topic", mode="retrieval")
    failing_runtime = AgentRuntime(
        journal=journal,
        artifact_store=artifacts,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    second = failing_runtime.resume(first.task_id, "missing", mode="retrieval")

    assert first.status == "completed"
    assert second.status == "failed"
    assert second.run_id == "run-2"
    decisions = [
        record.data
        for record in journal.records(task_id=first.task_id, kind="termination_decision")
        if record.run_id == "run-2"
    ]
    assert [item["decision"] for item in decisions] == ["continue", "failure_report"]
    sufficiency = [
        record.data
        for record in journal.records(task_id=first.task_id, kind="evidence_sufficiency")
        if record.run_id == "run-2"
    ]
    assert all(item["evidence_count"] == 0 for item in sufficiency)
    assert all(item["citation_count"] == 0 for item in sufficiency)
    assert workloop_state(journal, task_id=first.task_id, run_id="run-2").evidence_count == 0
    assert second.failure_report["attempted_actions"] == ["retrieval.run", "retrieval.run"]


def test_phase61_repeated_same_retrieval_query_sets_repetition_signal():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"repeat": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("repeat", mode="retrieval")

    latest = journal.records(task_id=result.task_id, kind="repetition_signal")[-1].data
    assert latest["repeated"] is True
    assert latest["repeat_type"] == "same_retrieval_query"
    assert latest["repeat_count"] == 2


def test_phase61_missing_file_path_asks_user_as_journaled_workloop_outcome():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("read the file", mode="workspace")

    assert result.status == "needs_user_input"
    assert journal.records(task_id=result.task_id, kind="termination_decision")[0].data["decision"] == "ask_user"
    assert journal.records(task_id=result.task_id, kind="observation")[0].data["status"] == "needs_user_input"


def test_phase61_workspace_search_then_file_read_counts_as_progress():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "Holo workspace evidence for progress."},
    )

    result = runtime.run("read README.md", mode="workspace")

    assert result.status == "completed"
    progress_types = [
        record.data["progress_type"]
        for record in journal.records(task_id=result.task_id, kind="progress_assessment")
    ]
    assert "new_file_read" in progress_types


def test_phase61_failed_or_blocked_observation_alone_does_not_count_as_progress():
    journal = JournalStore.in_memory()
    observation = Observation(
        observation_id="obs-failed",
        run_id="run-progress",
        kind="tool_result",
        status="failed",
        source="tool:file.read",
        content={"error": "file_not_found"},
        observed_at_ms=0,
        action_id="act-read",
        tool_call_id=None,
    )

    progress = assess_progress(
        journal,
        task_id="task-progress",
        run_id="run-progress",
        step_id="step-1",
        observation=observation,
    )

    assert progress.made_progress is False
    assert progress.progress_type == "none"


def test_phase61_evaluator_final_answer_ready_is_overridden_without_required_citations():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run("answer without evidence", mode="direct", citations_required=True)

    assert result.status == "failed"
    decision = journal.records(task_id=result.task_id, kind="termination_decision")[0].data
    assert decision["decision"] == "failure_report"
    assert decision["reason"] == "citations_required_but_missing"
    assert decision["override"] is True


def test_phase61_evaluator_continue_is_overridden_at_repeated_no_progress_threshold():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("missing", mode="retrieval")

    latest_decision = journal.records(task_id=result.task_id, kind="termination_decision")[-1].data
    assert latest_decision["decision"] == "failure_report"
    assert latest_decision["reason"] == "repeated_no_progress"
    assert latest_decision["override"] is True


def test_phase61_failure_report_contains_attempts_missing_evidence_observations_and_trace_refs():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("missing", mode="retrieval")

    report = result.failure_report
    assert report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    assert report["missing_evidence"] == ["sufficient_retrieval_evidence"]
    assert report["last_observations"]
    assert report["trace_refs"]


def test_phase61_loop_controller_stays_free_of_workloop_tool_branches():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for forbidden in ["progress_assessment", "repetition_signal", "evidence_sufficiency", "termination_decision"]:
        assert forbidden not in source


def test_phase61_cli_inspect_workloop_final_answer_and_failure_report(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    ok = _run_cli("--journal", str(journal), "--index", str(index), "agent", "Kernel v3 retrieval", "--mode", "retrieval")
    ok_payload = json.loads(ok.stdout)
    workloop = _run_cli("--journal", str(journal), "--index", str(index), "inspect-workloop", ok_payload["task_id"])
    final = _run_cli("--journal", str(journal), "--index", str(index), "final-answer", ok_payload["task_id"])

    workloop_payload = json.loads(workloop.stdout)
    final_payload = json.loads(final.stdout)
    assert workloop_payload["termination_decisions"]
    assert final_payload["citation_refs"]

    failed = _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "agent",
        "answer",
        "--mode",
        "direct",
        "--citations-required",
    )
    failed_payload = json.loads(failed.stdout)
    report = _run_cli("--journal", str(journal), "--index", str(index), "failure-report", failed_payload["task_id"])
    report_payload = json.loads(report.stdout)
    assert report_payload["reason"] == "citations_required_but_missing"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
