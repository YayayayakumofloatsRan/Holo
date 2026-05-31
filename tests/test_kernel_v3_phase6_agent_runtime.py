import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.trace import TraceRenderer


def test_phase6_direct_answer_completes_in_one_loop_and_journals_final_answer():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("explain Holo briefly", mode="direct")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert "离线 host fallback" in result.final_answer["answer"]
    assert "Direct answer:" not in result.final_answer["answer"]
    assert _action_names(journal, result.task_id) == ["respond"]
    assert journal.records(task_id=result.task_id, kind="agent_final_answer")


def test_phase6_retrieval_answer_uses_retrieval_run_then_synthesizer():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    result = AgentRuntime(journal=journal, artifact_store=artifacts).run("Kernel v3 retrieval", mode="retrieval")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert _action_names(journal, result.task_id) == ["retrieval.run"]
    assert journal.records(task_id=result.task_id, kind="retrieval_report")
    assert journal.records(task_id=result.task_id, kind="retrieval_evidence")
    assert journal.records(task_id=result.task_id, kind="retrieval_citation")
    assert journal.records(task_id=result.task_id, kind="processor_request")
    assert result.final_answer["citation_refs"]
    assert result.final_answer["used_evidence"]


def test_phase6_retrieval_answer_refuses_final_when_citations_required_but_absent():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing evidence": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("missing evidence", mode="retrieval", citations_required=True)

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report is not None
    assert result.failure_report["reason"] == "repeated_no_progress"
    assert "sufficient_retrieval_evidence" in result.failure_report["missing_evidence"]
    assert journal.records(task_id=result.task_id, kind="agent_failure_report")


def test_phase6_workspace_answer_searches_reads_and_synthesizes_without_network():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "Holo Kernel v3 workspace grounded answer."},
    )

    result = runtime.run("read README.md and answer", mode="workspace")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert _action_names(journal, result.task_id) == ["workspace.search", "file.read"]
    assert result.final_answer["citation_refs"] == ["workspace-cite-2"]
    assert "workspace grounded answer" in result.final_answer["answer"]
    assert not journal.records(task_id=result.task_id, kind="retrieval_report")


def test_phase6_workspace_resume_does_not_finalize_from_stale_file_observation():
    journal = JournalStore.in_memory()
    first = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "old workspace evidence"},
    ).run("read README.md", mode="workspace")

    second = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": "old workspace evidence"},
    ).resume(first.task_id, "read MISSING.md", mode="workspace")

    assert first.status == "completed"
    assert second.status == "needs_user_input"
    assert second.final_answer is None
    run2_finals = [
        record for record in journal.records(task_id=first.task_id, kind="agent_final_answer")
        if record.run_id == "run-2"
    ]
    assert run2_finals == []
    run2_sufficiency = [
        record.data for record in journal.records(task_id=first.task_id, kind="evidence_sufficiency")
        if record.run_id == "run-2"
    ]
    assert run2_sufficiency
    assert all(item["evidence_count"] == 0 for item in run2_sufficiency)


def test_phase6_ambiguous_workspace_request_asks_user():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("read the file", mode="workspace")

    assert result.status == "needs_user_input"
    assert result.final_answer is None
    assert _action_names(journal, result.task_id) == ["ask_user"]
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.data["status"] == "needs_user_input"


def test_phase6_failed_retrieval_returns_failure_report_not_invented_answer():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"no source": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
    )

    result = runtime.run("no source", mode="retrieval")

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report is not None
    assert result.failure_report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    assert result.failure_report["next_possible_action"] == "refine_query_or_add_sources"


def test_phase6_trace_evidence_artifacts_and_retrieval_trace_render_complete_path():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("Kernel v3 retrieval", mode="retrieval")
    renderer = TraceRenderer(journal)

    trace = renderer.render_task(result.task_id, verbose=True)
    evidence = renderer.render_evidence(result.task_id)
    artifacts = renderer.render_artifacts(result.task_id)
    retrieval_trace = renderer.render_retrieval_trace(result.task_id)

    assert "Trace task-" in trace
    assert "agent_final_answer" in trace
    assert "Evidence task-" in evidence
    assert "Artifacts task-" in artifacts
    assert "Retrieval Trace task-" in retrieval_trace
    assert "report=report-goal-agent-retrieval status=sufficient" in retrieval_trace


def test_phase6_citations_required_blocks_direct_mode_without_citations():
    journal = JournalStore.in_memory()
    result = AgentRuntime(journal=journal).run("answer without evidence", mode="direct", citations_required=True)

    assert result.status == "failed"
    assert result.final_answer is None
    assert result.failure_report["reason"] == "citations_required_but_missing"


def test_phase6_loop_controller_remains_tool_name_agnostic():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for forbidden in ["retrieval.run", "workspace.search", "file.read", "deepseek", "agent_recipe"]:
        assert forbidden not in source


def test_phase6_cli_agent_answer_and_inspect_run(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"

    agent = _run_cli("--journal", str(journal), "--index", str(index), "agent", "Kernel v3 retrieval", "--mode", "retrieval")
    agent_payload = json.loads(agent.stdout)
    assert agent_payload["status"] == "completed"
    assert agent_payload["final_answer"]["citation_refs"]

    answer = _run_cli("--journal", str(journal), "--index", str(index), "answer", "Kernel v3 retrieval", "--citations-required")
    answer_payload = json.loads(answer.stdout)
    assert answer_payload["status"] == "completed"
    assert answer_payload["final_answer"]["citation_refs"]

    inspect = _run_cli("--journal", str(journal), "--index", str(index), "inspect-run", agent_payload["task_id"])
    inspect_payload = json.loads(inspect.stdout)
    assert "Trace " + agent_payload["task_id"] in inspect_payload["trace"]
    assert "Retrieval Trace " + agent_payload["task_id"] in inspect_payload["retrieval_trace"]


def _action_names(journal: JournalStore, task_id: str) -> list[str]:
    names = []
    for record in journal.records(task_id=task_id, kind="action"):
        names.append(str(record.data.get("name") or record.data.get("kind")))
    return names


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
