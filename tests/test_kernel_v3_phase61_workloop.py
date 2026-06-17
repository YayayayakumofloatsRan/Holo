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
    assess_evidence_sufficiency,
    assess_progress,
    decide_termination,
    detect_repetition,
    workloop_state,
)
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import Feedback, Observation
from kernel_v3.journal import JournalStore
from kernel_v3.research import ACADEMIC_RESEARCH_PROFILE_ID
from kernel_v3.research import ResearchCorpusStore, corpus_document_from_retrieval
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.retrieval.providers import FetchResponse
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


def test_phase61_open_academic_research_soft_subgoals_can_finalize_with_limitations():
    journal = JournalStore.in_memory()
    task_id = "task-academic-soft"
    run_id = "run-academic-soft"
    recipe = _academic_research_recipe()
    for index in range(1, 4):
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=f"step-{index}",
            kind="retrieval_evidence",
            data={
                "evidence_id": f"ev-{index}",
                "citation_id": f"cite-{index}",
                "goal_id": "goal-plan-1-1",
                "text": "Recent hyperbolic dynamics paper evidence.",
            },
            state_delta={"retrieval_evidence": "ok"},
        )
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=f"step-{index}",
            kind="retrieval_citation",
            data={
                "citation_id": f"cite-{index}",
                "evidence_id": f"ev-{index}",
                "goal_id": "goal-plan-1-1",
                "uri": f"https://arxiv.org/abs/2601.0000{index}",
            },
            state_delta={"retrieval_citation": "ok"},
        )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-1",
        kind="retrieval_report",
        data={"goal_id": "goal-plan-1-1", "status": "sufficient", "diagnostics": {}},
        state_delta={"retrieval_report": "sufficient"},
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-2",
        kind="retrieval_report",
        data={"goal_id": "goal-plan-1-2", "status": "insufficient_evidence", "diagnostics": {}},
        state_delta={"retrieval_report": "insufficient"},
    )

    evidence = assess_evidence_sufficiency(
        journal,
        task_id=task_id,
        run_id=run_id,
        step_id="step-final",
        recipe=recipe,
    )

    assert evidence.sufficient is True
    assert evidence.reason == "open_research_soft_subgoals_can_be_limited"
    adaptive = evidence.diagnostics["adaptive_retrieval_completion"]
    assert adaptive["soft_incomplete_goal_ids"] == ["goal-plan-1-2"]
    assert "retrieval_subgoal:goal-plan-1-2" not in evidence.missing


def test_phase61_retrieval_without_new_evidence_continues_once_then_fails():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
    )

    result = runtime.run("missing", mode="retrieval")

    assert result.status == "failed"
    assert result.failure_report["reason"] == "repeated_no_progress"
    assert result.failure_report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    decisions = [record.data for record in journal.records(task_id=result.task_id, kind="termination_decision")]
    assert [item["decision"] for item in decisions] == ["continue", "failure_report"]
    assert decisions[0]["reason"] == "insufficient_evidence_retry"
    progress = [record.data for record in journal.records(task_id=result.task_id, kind="progress_assessment")]
    assert progress[0]["made_progress"] is False
    assert progress[0]["progress_type"] == "none"


def test_phase61_retrieval_resume_gets_fresh_repetition_budget_and_unique_action_ids():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
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
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
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
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
    )

    result = runtime.run("repeat", mode="retrieval")

    latest = journal.records(task_id=result.task_id, kind="repetition_signal")[-1].data
    assert latest["repeated"] is True
    assert latest["repeat_type"] == "same_retrieval_query"
    assert latest["repeat_count"] == 2


def test_phase61_repeated_failed_fetch_target_sets_repetition_signal():
    journal = JournalStore.in_memory()
    for index in range(2):
        journal.append(
            task_id="task-fetch-repeat",
            run_id="run-1",
            step_id=f"step-{index + 1}",
            kind="retrieval_fetch_attempt",
            data={
                "fetch_id": f"fetch-{index + 1}",
                "source_id": "direct-url-aapl-companyfacts",
                "uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "status": "failed",
            },
        )

    signal = detect_repetition(
        journal,
        task_id="task-fetch-repeat",
        run_id="run-1",
        step_id="step-2",
        config=WorkloopConfig(repeated_failed_fetch_limit=2),
        latest_missing_evidence=[],
    )

    assert signal.repeated is True
    assert signal.repeat_type == "same_failed_fetch_target"
    assert signal.repeat_count == 2


def test_phase61_default_failed_fetch_repetition_limit_allows_deep_retrieval_retry():
    assert WorkloopConfig().repeated_failed_fetch_limit == 64


def test_phase61_repeated_artifact_read_sets_repetition_signal_before_step_limit():
    journal = JournalStore.in_memory()
    for index in range(3):
        journal.append(
            task_id="task-artifact-repeat",
            run_id="run-1",
            step_id=f"step-{index + 1}",
            kind="action",
            data={
                "name": "artifact.read",
                "payload": {
                    "artifact_id": "artifact-sec-financials",
                    "mode": "read",
                    "max_chars": 20000,
                },
            },
        )

    signal = detect_repetition(
        journal,
        task_id="task-artifact-repeat",
        run_id="run-1",
        step_id="step-3",
        config=WorkloopConfig(),
        latest_missing_evidence=[],
    )

    assert signal.repeated is True
    assert signal.repeat_type == "same_artifact_read"
    assert signal.repeat_count == 3
    assert signal.threshold == 3


def test_phase61_retrieval_rejection_diagnostic_counts_as_progress():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-rejection-progress",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_evidence_rejections",
        data={
            "goal_id": "goal-1",
            "rejected_count": 8,
            "items": [],
            "diagnostics": {"reasons": {"target_entity_mismatch": 8}},
        },
    )

    progress = assess_progress(
        journal,
        task_id="task-rejection-progress",
        run_id="run-1",
        step_id="step-1",
        observation=Observation(
            observation_id="obs-rejection-progress",
            run_id="run-1",
            kind="tool_result",
            status="ok",
            source="tool:retrieval.run",
            content={"report": {"status": "insufficient_evidence", "evidence_ids": [], "citation_ids": []}},
            observed_at_ms=1,
            action_id="act-rejection-progress",
            tool_call_id=None,
        ),
    )

    assert progress.made_progress is True
    assert progress.progress_type == "new_retrieval_rejection_diagnostic"
    assert progress.signals[0]["diagnostics"]["reasons"] == {"target_entity_mismatch": 8}


def test_phase61_retrieval_source_rejection_diagnostic_counts_as_progress():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-source-rejection-progress",
        run_id="run-1",
        step_id="step-1",
        kind="retrieval_source_rejections",
        data={
            "goal_id": "goal-1",
            "rejected_count": 3,
            "items": [],
            "diagnostics": {"reasons": {"source_target_entity_mismatch": 3}},
        },
    )

    progress = assess_progress(
        journal,
        task_id="task-source-rejection-progress",
        run_id="run-1",
        step_id="step-1",
        observation=Observation(
            observation_id="obs-source-rejection-progress",
            run_id="run-1",
            kind="tool_result",
            status="ok",
            source="tool:retrieval.run",
            content={"report": {"status": "insufficient_evidence", "evidence_ids": [], "citation_ids": []}},
            observed_at_ms=1,
            action_id="act-source-rejection-progress",
            tool_call_id=None,
        ),
    )

    assert progress.made_progress is True
    assert progress.progress_type == "new_retrieval_rejection_diagnostic"
    assert progress.signals[0]["diagnostics"]["reasons"] == {"source_target_entity_mismatch": 3}


def test_phase61_repeated_missing_evidence_item_sets_repetition_signal():
    journal = JournalStore.in_memory()
    for index in range(3):
        journal.append(
            task_id="task-missing-item-repeat",
            run_id="run-1",
            step_id=f"step-{index + 1}",
            kind="feedback",
            data={
                "feedback_id": f"fb-{index + 1}",
                "status": "continue",
                "missing_evidence": ["sufficient_retrieval_evidence", f"unique-gap-{index + 1}"],
            },
        )

    signal = detect_repetition(
        journal,
        task_id="task-missing-item-repeat",
        run_id="run-1",
        step_id="step-3",
        config=WorkloopConfig(repeated_missing_evidence_limit=3),
        latest_missing_evidence=[],
    )

    assert signal.repeated is True
    assert signal.repeat_type == "same_missing_evidence_item"
    assert signal.repeat_count == 3


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


def test_phase61_workspace_directory_listing_is_sufficient_without_file_read():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        workspace_files={
            "README.md": "Holo Kernel v3 readme",
            "docs/loop.md": "Agent loop notes",
        },
    )

    result = runtime.run("list the workspace directory", mode="workspace")

    assert result.status == "completed"
    assert result.final_answer is not None
    assert [record.data["name"] for record in journal.records(task_id=result.task_id, kind="action")] == [
        "workspace.list"
    ]
    sufficiency = journal.records(task_id=result.task_id, kind="evidence_sufficiency")[0].data
    assert sufficiency["sufficient"] is True
    assert sufficiency["reason"] == "sufficient"
    assert sufficiency["diagnostics"]["workspace_listing_count"] == 1
    assert "file_read_observation" not in sufficiency["missing"]
    assert result.final_answer["citation_refs"] == ["workspace-cite-1"]


def test_phase61_processor_failure_cannot_override_sufficient_workspace_evidence():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-processor-failed",
            run_id="run-1",
            status="failed",
            stop_reason="processor_failed",
            answer=None,
            missing_evidence=["model_evaluator_failed", "processor_failed"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=True,
            progress_score=0.8,
            progress_type="new_workspace_listing",
            new_refs=["."],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=True,
            citations_required=False,
            evidence_count=1,
            citation_count=1,
            valid_citation_refs=["workspace-cite-1"],
            missing=[],
            reason="sufficient",
        ),
        recipe=_workspace_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "final_answer"
    assert decision.reason == "evidence_sufficient_overrode_processor_failure"
    assert decision.override is True


def test_phase61_spurious_user_input_after_successful_direct_response_finalizes():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-spurious-ask",
            run_id="run-1",
            status="needs_user_input",
            stop_reason="needs_user_input",
            answer=None,
            missing_evidence=["clarification_required"],
        ),
        observation=Observation(
            observation_id="obs-respond",
            run_id="run-1",
            kind="respond_result",
            status="ok",
            source="respond",
            content={"text": "语言的边界也是思想的边界之一。"},
            observed_at_ms=1,
            action_id="act-respond",
            tool_call_id=None,
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=True,
            progress_score=0.35,
            progress_type="new_artifact",
            new_refs=["artifact-1"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=True,
            citations_required=False,
            evidence_count=0,
            citation_count=0,
            valid_citation_refs=[],
            missing=[],
            reason="sufficient",
        ),
        recipe=_semantic_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "final_answer"
    assert decision.reason == "successful_response_overrode_spurious_user_input"
    assert decision.override is True


def test_phase61_clarify_first_does_not_override_successful_direct_response():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-clarify-spurious-ask",
            run_id="run-1",
            status="needs_user_input",
            stop_reason="needs_user_input",
            answer=None,
            missing_evidence=["clarification_required"],
        ),
        observation=Observation(
            observation_id="obs-respond-clarify",
            run_id="run-1",
            kind="respond_result",
            status="ok",
            source="respond",
            content={"text": "我可以先给出一个有限但有用的回答。"},
            observed_at_ms=1,
            action_id="act-respond",
            tool_call_id=None,
        ),
        progress=ProgressAssessment(
            assessment_id="progress-clarify",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=True,
            progress_score=0.35,
            progress_type="new_artifact",
            new_refs=["artifact-1"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-clarify",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-clarify",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=True,
            citations_required=False,
            evidence_count=0,
            citation_count=0,
            valid_citation_refs=[],
            missing=[],
            reason="sufficient",
        ),
        recipe=_clarify_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "final_answer"
    assert decision.reason == "successful_response_overrode_spurious_user_input"


def test_phase61_evaluator_blocked_without_host_block_retries_when_evidence_missing():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-model-blocked",
            run_id="run-1",
            status="blocked",
            stop_reason="policy_or_tool_blocked",
            answer=None,
            missing_evidence=["retrieval_evidence", "citation_refs"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=False,
            progress_score=0.0,
            progress_type="none",
            new_refs=[],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=False,
            citations_required=True,
            evidence_count=0,
            citation_count=0,
            valid_citation_refs=[],
            missing=["retrieval_evidence"],
            reason="insufficient_evidence",
        ),
        recipe=_retrieval_recipe(),
        no_progress_count=1,
        config=WorkloopConfig(),
    )

    assert decision.decision == "continue"
    assert decision.reason == "blocked_feedback_without_host_block_retry"
    assert decision.override is True


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
        workloop_config=WorkloopConfig(no_progress_step_limit=2),
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


def test_phase61_evidence_sufficiency_does_not_override_required_formula_trace():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-formula-required",
            run_id="run-1",
            status="continue",
            stop_reason=None,
            answer=None,
            missing_evidence=["finance_formula_trace_required"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=True,
            progress_score=1.0,
            progress_type="new_citation",
            new_refs=["cite-1"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=True,
            citations_required=True,
            evidence_count=5,
            citation_count=5,
            valid_citation_refs=["cite-1", "cite-2", "cite-3", "cite-4", "cite-5"],
            missing=[],
            reason="sufficient",
        ),
        recipe=_retrieval_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "continue"
    assert decision.reason == "transform_work_required"
    assert decision.override is False


def test_phase61_evidence_sufficiency_does_not_override_workbench_followup():
    decision = decide_termination(
        feedback=Feedback(
            feedback_id="fb-workbench-followup",
            run_id="run-1",
            status="continue",
            stop_reason=None,
            answer=None,
            missing_evidence=["retrieval_workbench_followup"],
        ),
        progress=ProgressAssessment(
            assessment_id="progress-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            made_progress=True,
            progress_score=1.0,
            progress_type="new_citation",
            new_refs=["cite-1"],
            signals=[],
        ),
        repetition=RepetitionSignal(
            signal_id="repeat-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            repeated=False,
            repeat_type=None,
            repeat_count=0,
            threshold=2,
            repeated_refs=[],
        ),
        evidence=EvidenceSufficiency(
            sufficiency_id="evidence-1",
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            sufficient=True,
            citations_required=True,
            evidence_count=5,
            citation_count=5,
            valid_citation_refs=["cite-1", "cite-2", "cite-3", "cite-4", "cite-5"],
            missing=[],
            reason="sufficient",
        ),
        recipe=_retrieval_recipe(),
        no_progress_count=0,
        config=WorkloopConfig(),
    )

    assert decision.decision == "continue"
    assert decision.reason == "transform_work_required"
    assert decision.override is False


def test_phase61_failure_report_contains_attempts_missing_evidence_observations_and_trace_refs():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(
        journal=journal,
        retrieval_operator=RetrievalOperator(
            search_provider=FakeSearchProvider({"missing": []}),
            fetch_provider=FakeFetchProvider({}),
        ),
        workloop_config=WorkloopConfig(repeated_action_limit=2, repeated_missing_evidence_limit=2, no_progress_step_limit=2),
    )

    result = runtime.run("missing", mode="retrieval")

    report = result.failure_report
    assert report["attempted_actions"] == ["retrieval.run", "retrieval.run"]
    assert report["missing_evidence"] == ["sufficient_retrieval_evidence"]
    assert report["last_observations"]
    assert report["trace_refs"]


def test_phase61_network_budget_does_not_preempt_tool_observation_when_budget_remains():
    journal = JournalStore.in_memory()
    fetch_provider = _LiveFetchProvider()
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=RetrievalOperator(
            search_provider=_LiveSearchProvider(),
            fetch_provider=fetch_provider,
        ),
    )

    result = runtime.run(
        "live retrieval budget guard",
        mode="retrieval",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 12,
                "max_fetches": 3,
                "network_fetch_count": 3,
            }
        },
    )

    assert result.status == "failed"
    assert result.failure_report["reason"] == "max_network_fetches"
    observations = journal.records(task_id=result.task_id, kind="observation")
    assert observations[0].data["status"] == "ok"
    assert observations[1].data["content"]["reason"] == "max_network_fetches"
    assert journal.records(task_id=result.task_id, kind="guard")[-1].data["network_fetches"] == 1
    assert journal.records(task_id=result.task_id, kind="guard")[-1].data["requested_network_fetches"] == 12
    assert journal.records(task_id=result.task_id, kind="guard")[-1].data["projected_network_fetches"] == 13
    decision = journal.records(task_id=result.task_id, kind="termination_decision")[-1].data
    assert decision["decision"] == "failure_report"
    assert journal.records(task_id=result.task_id, kind="progress_assessment")
    assert journal.records(task_id=result.task_id, kind="evidence_sufficiency")


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


def _workspace_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-workspace-test",
        allowed_tools=["workspace.list", "workspace.search", "file.read"],
        max_steps=4,
        max_tool_calls=3,
        max_network_fetches=0,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=False,
        finalizer="workspace_synthesizer",
        context_budget_mode="standard",
        mode="workspace_answer",
    )


def _semantic_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-semantic-test",
        allowed_tools=[],
        max_steps=4,
        max_tool_calls=0,
        max_network_fetches=0,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=False,
        finalizer="direct",
        context_budget_mode="standard",
        mode="semantic_answer",
    )


def _clarify_recipe() -> TaskRecipe:
    return TaskRecipe(
        recipe_id="recipe-clarify-test",
        allowed_tools=[],
        max_steps=4,
        max_tool_calls=0,
        max_network_fetches=0,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=False,
        finalizer="direct",
        context_budget_mode="standard",
        mode="clarify_first",
    )


class _LiveSearchProvider:
    live_network = True

    def search(self, query, *, goal, plan):
        return [SearchSource(source_id="src-live", uri="https://example.test/live", title="Live source", snippet="live")]


class _LiveFetchProvider:
    live_network = True

    def __init__(self) -> None:
        self.called = False

    def fetch(self, source):
        self.called = True
        return FetchResponse(status="ok", body="live evidence")


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
            "--offline",
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
            "--offline",
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


def _academic_research_recipe() -> TaskRecipe:
    payloads = [
        {
            "query": "hyperbolic dynamics recent papers",
            "metadata": {
                "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                "research_task_kind": "frontier_research",
                "subgoal_required": True,
            },
        },
        {
            "query": "hyperbolic dynamics Chinese survey",
            "metadata": {
                "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                "research_task_kind": "frontier_research",
                "subgoal_required": True,
            },
        },
    ]
    return TaskRecipe(
        recipe_id="recipe-academic-workloop",
        allowed_tools=["retrieval.run"],
        max_steps=8,
        max_tool_calls=8,
        max_network_fetches=100,
        max_total_artifact_bytes=10_000_000,
        permission_profile="read_only",
        citations_required=True,
        finalizer="synthesizer.answer",
        context_budget_mode="balanced",
        mode="retrieval_answer",
        metadata={
            "task_execution_plan": {
                "steps": [
                    {
                        "status": "ready",
                        "tool_name": "retrieval.run",
                        "sequence_index": 1,
                        "metadata": {"capability_args": {"retrieval.run": payloads}},
                    }
                ]
            }
        },
    )
