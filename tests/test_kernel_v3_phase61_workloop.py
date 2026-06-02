from pathlib import Path
import json
import subprocess
import sys

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.agent.workloop import (
    EvidenceSufficiency,
    ProgressAssessment,
    RepetitionSignal,
    WorkloopConfig,
    assess_progress,
    decide_termination,
    workloop_state,
)
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import Feedback, Observation
from kernel_v3.journal import JournalStore
from kernel_v3.research import ResearchCorpusStore, corpus_document_from_retrieval
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource


def test_phase61_retrieval_with_new_citation_finalizes_and_journals_decisions():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = _corpus_with_document(artifacts, query_text="Kernel v3 retrieval")

    result = AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus).run(
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
    corpus = _corpus_with_document(artifacts, query_text="grounded topic")
    first = AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus).run("grounded topic", mode="retrieval")
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
    sufficiency = journal.records(task_id=result.task_id, kind="evidence_sufficiency")[0].data
    assert sufficiency["sufficient"] is False
    assert sufficiency["reason"] == "user_input_required"
    assert sufficiency["missing"] == ["user_input"]


def test_phase61_workspace_search_then_file_read_counts_as_progress():
    journal = JournalStore.in_memory()
    content = ("Holo workspace evidence for progress. " * 8) + "Artifact body beyond preview is available."
    runtime = AgentRuntime(
        journal=journal,
        workspace_files={"README.md": content},
    )

    result = runtime.run("read README.md", mode="workspace")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert "Artifact body beyond preview" in result.final_answer["answer"]
    progress_types = [
        record.data["progress_type"]
        for record in journal.records(task_id=result.task_id, kind="progress_assessment")
    ]
    assert "new_file_read" in progress_types


def test_phase61_context_budget_can_be_raised_for_large_live_prompts():
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run(
        "explain context budget",
        mode="direct",
        execution_metadata={
            "context_budget": {
                "profile": "large",
                "token_budget": 65536,
                "section_budget": 8192,
            }
        },
    )

    context = journal.records(task_id=result.task_id, kind="context")[0].data
    assert context["state"]["budget"]["token_budget"] == 65536
    assert context["state"]["budget"]["section_limit"] == 8192
    assert context["state"]["agent_recipe"]["metadata"]["execution_metadata"]["context_budget"]["profile"] == "large"


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


def test_phase61_repeated_missing_evidence_stops_even_when_marginal_progress_exists():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-1",
            run_id="run-1",
            status="continue",
            stop_reason=None,
            answer=None,
            missing_evidence=["primary_source"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            made_progress=True,
            progress_score=0.4,
            progress_type="new_citation",
            new_refs=["cite-2"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            repeated=True,
            repeat_type="same_missing_evidence",
            repeat_count=2,
            threshold=2,
            repeated_refs=["fb-0", "latest-feedback"],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            sufficient=False,
            citations_required=True,
            evidence_count=2,
            citation_count=2,
            valid_citation_refs=["cite-1", "cite-2"],
            missing=["primary_source"],
            reason="no_primary_source_for_research_profile",
        ),
        recipe=_retrieval_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "failure_report"
    assert decision.reason == "repeated_missing_evidence"
    assert decision.override is True


def test_phase61_repeated_missing_evidence_does_not_stop_remaining_plan_actions():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-1",
            run_id="run-1",
            status="continue",
            stop_reason=None,
            answer=None,
            missing_evidence=["remaining_plan_actions"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            made_progress=True,
            progress_score=0.4,
            progress_type="new_observation",
            new_refs=["obs-2"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            repeated=True,
            repeat_type="same_missing_evidence",
            repeat_count=2,
            threshold=2,
            repeated_refs=["fb-0", "latest-feedback"],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-2",
            sufficient=False,
            citations_required=False,
            evidence_count=1,
            citation_count=0,
            valid_citation_refs=[],
            missing=["remaining_plan_actions"],
            reason="planned_actions_remaining",
        ),
        recipe=_retrieval_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "continue"
    assert decision.reason == "planned_actions_remaining"


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


def _retrieval_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-test",
        allowed_tools=["retrieval.run"],
        max_steps=8,
        max_tool_calls=8,
        max_network_fetches=4,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=True,
        finalizer="synthesizer",
        context_budget_mode="standard",
        mode="retrieval_answer",
    )


def test_phase61_cli_inspect_workloop_final_answer_and_failure_report(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    artifact_log = tmp_path / "artifacts.jsonl"
    corpus_log = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"

    _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--artifact-log",
        str(artifact_log),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
        str(corpus_index),
        "retrieve",
        "Kernel v3 retrieval",
        "--body",
        "Kernel v3 retrieval corpus evidence from local indexed source.",
        "--index-corpus",
    )

    ok = _run_cli(
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--artifact-log",
        str(artifact_log),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
        str(corpus_index),
        "agent",
        "Kernel v3 retrieval",
        "--mode",
        "retrieval",
    )
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


def _corpus_with_document(artifacts: ArtifactStore, *, query_text: str) -> ResearchCorpusStore:
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 101)
    uri = "local://kernel-v3/workloop-corpus"
    title = "Kernel v3 workloop corpus source"
    body = f"{query_text} corpus evidence from a local indexed source."
    source = SearchSource(
        source_id="src-workloop-corpus",
        uri=uri,
        title=title,
        snippet=query_text,
        provider="local_corpus_seed",
    )
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload=body,
        metadata={"uri": uri, "source_id": source.source_id, "title": title},
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=FetchedDocument(
                document_id="doc-workloop-corpus",
                goal_id="goal-workloop-corpus",
                source_id=source.source_id,
                uri=uri,
                title=title,
                artifact_id=artifact.artifact_id,
                payload_hash=artifact.payload_hash,
                preview=body[:160],
                size_bytes=len(body.encode("utf-8")),
                metadata={"mime_type": "text/plain"},
            ),
            source=source,
            goal=SearchGoal(goal_id="goal-workloop-corpus", query=query_text),
            task_id="task-workloop-corpus",
            run_id="run-workloop-corpus",
            fetched_at_ms=101,
        )
    )
    return corpus
