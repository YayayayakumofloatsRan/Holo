import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.agent.runtime import _compact_thread_rag_context_for_prompt
from kernel_v3.agent.workloop import WorkloopConfig
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.mission import MissionRuntime, ThreadWorkingMemoryProvider
from kernel_v3.processors import ProcessorFabric, ProcessorRouter
from kernel_v3.processors.contracts import MISSION_ASSESS_SCHEMA
from kernel_v3.processors.fabric import validate_json_schema
from kernel_v3.processors.usage import usage_from_text
from kernel_v3.research import ResearchCorpusStore, corpus_document_from_retrieval
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator
from kernel_v3.retrieval.contracts import FetchedDocument, SearchGoal, SearchSource


def test_phase109_mission_continues_after_inner_retrieval_failure_then_fails_globally():
    journal = JournalStore.in_memory()
    runtime = MissionRuntime(
        agent_runtime=AgentRuntime(
            journal=journal,
            artifact_store=ArtifactStore.in_memory(),
            retrieval_operator=RetrievalOperator(
                search_provider=FakeSearchProvider({"missing": []}),
                fetch_provider=FakeFetchProvider({}),
            ),
            workloop_config=WorkloopConfig(repeated_action_limit=1, repeated_missing_evidence_limit=1, no_progress_step_limit=1),
        ),
        max_iterations=2,
    )

    result = runtime.run("missing", mode="retrieval")

    assert result.status == "failed"
    assessments = [record.data for record in journal.records(kind="mission_assessment")]
    assert [item["decision"] for item in assessments] == ["continue", "failure_report"]
    assert journal.records(kind="mission_directive")
    assert len({record.run_id for record in journal.records(task_id=result.task_id, kind="run")}) == 2
    assert "sufficient_retrieval_evidence" in result.failure_report["missing_evidence"]


def test_phase109_mission_continuation_keeps_root_goal_stable_in_agent_context():
    journal = JournalStore.in_memory()
    runtime = MissionRuntime(
        agent_runtime=AgentRuntime(
            journal=journal,
            artifact_store=ArtifactStore.in_memory(),
            retrieval_operator=RetrievalOperator(
                search_provider=FakeSearchProvider({"missing": []}),
                fetch_provider=FakeFetchProvider({}),
            ),
            workloop_config=WorkloopConfig(repeated_action_limit=1, repeated_missing_evidence_limit=1, no_progress_step_limit=1),
        ),
        max_iterations=2,
    )

    result = runtime.run("调查一个很难命中的目标", mode="retrieval")

    assert result.status == "failed"
    run2_contexts = [
        record.data["state"]
        for record in journal.records(task_id=result.task_id, kind="context")
        if record.run_id == "run-2"
    ]
    assert run2_contexts
    state = run2_contexts[0]
    assert state["mission_context"]["mission_state"]["root_goal"] == "调查一个很难命中的目标"
    assert state["mission_context"]["current_step"]["is_continuation"] is True
    assert state["semantic_goal"]["root_goal"] == "调查一个很难命中的目标"
    assert state["research_mission"]["root_goal"] == "调查一个很难命中的目标"
    assert "Continue the same global mission" not in state["research_mission"]["root_goal"]


def test_phase109_mission_finalizes_when_inner_loop_covers_goal():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory()
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload="Kernel v3 retrieval has citable evidence and a host-owned report.",
        metadata={"uri": "local://kernel"},
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=FetchedDocument(
                document_id="doc-kernel",
                goal_id="goal-kernel",
                source_id="src-kernel",
                uri="local://kernel",
                title="Kernel v3 retrieval note",
                artifact_id=artifact.artifact_id,
                payload_hash=artifact.payload_hash,
                preview="Kernel v3 retrieval has citable evidence and a host-owned report.",
                size_bytes=64,
                metadata={"mime_type": "text/plain"},
            ),
            source=SearchSource(
                source_id="src-kernel",
                title="Kernel v3 retrieval note",
                uri="local://kernel",
                snippet="Kernel v3 retrieval has citable evidence.",
                provider="fixture",
                metadata={},
            ),
            goal=SearchGoal(goal_id="goal-kernel", query="Kernel v3 retrieval"),
            task_id="task-seed",
            run_id="run-seed",
            fetched_at_ms=1,
        )
    )
    runtime = MissionRuntime(
        agent_runtime=AgentRuntime(journal=journal, artifact_store=artifacts, research_corpus_store=corpus),
        max_iterations=3,
    )

    result = runtime.run("Kernel v3 retrieval", mode="retrieval")

    assert result.status == "completed"
    assert result.final_answer["citation_refs"]
    assessments = [record.data for record in journal.records(kind="mission_assessment")]
    assert assessments[-1]["decision"] == "final_answer"
    assert journal.records(kind="mission_final_answer")


def test_phase109_mission_and_thread_rag_are_in_model_planner_packet():
    journal = JournalStore.in_memory()
    provider = _CapturingProvider(
        {
            "planner.propose": {
                "action_id": "act-direct",
                "kind": "respond",
                "name": None,
                "description": "answer",
                "payload": {"text": "这是带 mission context 的回答。"},
                "score": 0.9,
                "reasons": ["context is sufficient"],
                "side_effect_class": "none",
            },
            "evaluator.assess": {
                "status": "final_answer_ready",
                "answer": "这是带 mission context 的回答。",
                "stop_reason": "completed",
                "missing_evidence": [],
            },
        }
    )
    fabric = ProcessorFabric(
        providers={"capture": provider},
        router=ProcessorRouter(default_provider="capture", default_model="capture-model"),
        journal=journal,
    )
    runtime = MissionRuntime(
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        max_iterations=2,
    )

    result = runtime.run(
        "解释一下全局任务监督闭环",
        mode="semantic",
        planner_mode="model",
        evaluator_mode="model",
    )

    assert result.status == "completed"
    planner_prompt = next(prompt for task_type, prompt in provider.prompts if task_type == "planner.propose")
    payload = json.loads(planner_prompt)
    state = payload["context"]["state"]
    assert state["mission_context"]["mission_state"]["root_goal"] == "解释一下全局任务监督闭环"
    assert state["thread_rag_context"]["kind"] == "thread_rag_context"
    assert journal.records(task_id=result.task_id, kind="mission_assessment")


def test_phase109_mission_schema_accepts_null_next_directive_for_terminal_decisions():
    assert (
        validate_json_schema(
            {
                "decision": "failure_report",
                "coverage_score": 0.0,
                "covered_requirements": [],
                "missing_requirements": ["target evidence"],
                "unsupported_claims": [],
                "next_directive": None,
                "confidence": 0.8,
                "reason_summary": "No safe continuation remains.",
            },
            MISSION_ASSESS_SCHEMA,
        )
        is None
    )


def test_phase109_mission_does_not_finalize_low_confidence_failure_answer():
    journal = JournalStore.in_memory()
    supervisor = MissionRuntime(
        agent_runtime=AgentRuntime(journal=journal),
        max_iterations=2,
    ).supervisor
    mission = supervisor.start(root_goal="Find Citadel Security scale and operations", thread_id="thread-citadel")
    result = AgentRuntimeResult(
        status="completed",
        task_id="task-mission-fixture",
        run_id="run-mission-fixture",
        mode="retrieval_answer",
        recipe_id="recipe-mission-fixture",
        final_answer={
            "answer": "The available evidence does not identify Citadel Security.",
            "citation_refs": [],
            "used_evidence": [],
            "limitations": ["No matching target evidence was found."],
            "confidence": 0.0,
        },
        failure_report=None,
        trace_refs=[],
    )

    _updated, assessment = supervisor.assess(mission, result, index=1)

    assert assessment.decision == "continue"
    assert "supported_final_answer" in assessment.missing_requirements
    assert assessment.next_directive is not None


def test_phase109_thread_working_memory_is_thread_scoped():
    journal = JournalStore.in_memory()
    journal.append(
        task_id=None,
        run_id="chat-a",
        step_id=None,
        kind="chat_turn",
        data={"thread_id": "a", "turn_id": "turn-a-1", "role": "user", "text": "A thread private topic"},
    )
    journal.append(
        task_id=None,
        run_id="chat-b",
        step_id=None,
        kind="chat_turn",
        data={"thread_id": "b", "turn_id": "turn-b-1", "role": "user", "text": "B thread private topic"},
    )

    context = ThreadWorkingMemoryProvider().compile(journal, thread_id="a")

    text = json.dumps(context, ensure_ascii=False)
    assert "A thread private topic" in text
    assert "B thread private topic" not in text


def test_phase109_thread_working_memory_exposes_attention_blocks():
    journal = JournalStore.in_memory()
    task_id = "task-attention"
    journal.append(
        task_id=task_id,
        run_id="run-attention",
        step_id="step-1",
        kind="retrieval_evidence",
        data={"evidence_id": "ev-attention", "text": "Important evidence."},
    )
    journal.append(
        task_id=task_id,
        run_id="run-attention",
        step_id="step-1",
        kind="retrieval_citation",
        data={"citation_id": "cite-attention", "evidence_id": "ev-attention"},
    )
    journal.append(
        task_id=task_id,
        run_id="run-attention",
        step_id=None,
        kind="agent_failure_report",
        data={
            "reason": "missing_source",
            "missing_evidence": ["source_authority"],
            "attempted_actions": ["retrieval.run"],
            "user_help_needed": False,
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-attention",
        step_id="step-1",
        kind="retrieval_report",
        data={
            "report_id": "report-attention",
            "status": "insufficient_evidence",
            "goal_id": "goal-attention",
            "preview": "search did not find authority evidence",
            "diagnostics": {
                "search_summaries": [{"query": "weak repeated query"}],
                "source_quality": {"recommended_next_source_action": "switch_source_family"},
            },
        },
    )

    context = ThreadWorkingMemoryProvider().compile(journal, thread_id="thread-attention", task_id=task_id)
    blocks = context["attention_blocks"]
    prompt_context = _compact_thread_rag_context_for_prompt(context)

    assert [block["kind"] for block in blocks[:2]] == ["recent_failure", "current_evidence"]
    assert blocks[0]["priority"] > blocks[1]["priority"]
    assert "ev-attention" in blocks[1]["refs"]
    assert "cite-attention" in blocks[1]["refs"]
    assert context["self_iteration"]["status"] == "recover_from_failure"
    assert context["self_iteration"]["latest_failure_reason"] == "missing_source"
    assert context["self_iteration"]["avoid_repeating_queries"] == ["weak repeated query"]
    assert context["self_iteration"]["recommended_next_actions"] == ["switch_source_family"]
    assert prompt_context["attention_blocks"][0]["kind"] == "recent_failure"
    assert prompt_context["self_iteration"]["status"] == "recover_from_failure"
    assert prompt_context["self_iteration"]["avoid_repeating_queries"] == ["weak repeated query"]


def test_phase109_thread_working_memory_exposes_task_continuity_from_mission_records():
    journal = JournalStore.in_memory()
    task_id = "task-continuity"
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id=None,
        kind="chat_turn",
        data={
            "thread_id": "thread-continuity",
            "turn_id": "turn-continuity-1",
            "role": "user",
            "text": "调查一个跨领域研究任务",
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id="step-1",
        kind="action",
        data={
            "action_id": "act-continuity-1",
            "kind": "tool",
            "name": "retrieval.run",
            "side_effect_class": "network",
            "payload": {"query": "weak repeated query"},
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id="step-1",
        kind="retrieval_report",
        data={
            "report_id": "report-continuity",
            "status": "insufficient_evidence",
            "diagnostics": {
                "search_summaries": [{"query": "weak repeated query"}],
                "missing_query_facets": ["frontier_sources"],
            },
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id="step-1",
        kind="feedback",
        data={
            "status": "continue",
            "missing_evidence": ["scholarly_source"],
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id=None,
        kind="mission_assessment",
        data={
            "assessment_id": "assess-continuity",
            "mission_id": "mission-continuity",
            "task_id": task_id,
            "run_id": "run-continuity",
            "decision": "continue",
            "coverage_score": 0.34,
            "covered_requirements": ["basic_definition"],
            "missing_requirements": ["frontier_research", "source_diversity"],
            "unsupported_claims": [],
            "next_directive": None,
            "confidence": 0.8,
            "reason_summary": "Need a different source family and better frontier coverage.",
        },
    )
    journal.append(
        task_id=task_id,
        run_id="run-continuity",
        step_id=None,
        kind="mission_directive",
        data={
            "directive_id": "directive-continuity",
            "mission_id": "mission-continuity",
            "root_goal": "调查一个跨领域研究任务",
            "strategy": "switch_source_family",
            "next_subgoal": "Find authoritative frontier research sources.",
            "missing_requirements": ["frontier_research"],
            "avoid_repeating": ["weak repeated query"],
            "suggested_actions": [
                {
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "Search scholarly indexes.",
                    "payload": {"query": "frontier research scholarly index"},
                }
            ],
            "stop_conditions": ["frontier source coverage is sufficient"],
            "reason": "Prior query found weak coverage.",
        },
    )

    context = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-continuity",
        task_id=task_id,
        mission_id="mission-continuity",
    )
    prompt_context = _compact_thread_rag_context_for_prompt(context)

    mission_trace = [item for item in context["recent_task_trace"] if item["kind"] == "mission_assessment"]
    directive_trace = [item for item in context["recent_task_trace"] if item["kind"] == "mission_directive"]
    assert mission_trace[-1]["missing_requirements"] == ["frontier_research", "source_diversity"]
    assert directive_trace[-1]["strategy"] == "switch_source_family"
    assert context["task_continuity"]["current_objective"] == "调查一个跨领域研究任务"
    assert context["task_continuity"]["latest_decision"] == "continue"
    assert context["task_continuity"]["coverage_score"] == 0.34
    assert "frontier_research" in context["task_continuity"]["open_requirements"]
    assert "scholarly_source" in context["task_continuity"]["open_requirements"]
    assert "weak repeated query" in context["task_continuity"]["avoid_repeating"]
    assert context["task_continuity"]["suggested_actions"][0]["name"] == "retrieval.run"
    assert prompt_context["task_continuity"]["strategy"] == "switch_source_family"
    assert prompt_context["task_continuity"]["open_requirements"][:2] == [
        "frontier_research",
        "source_diversity",
    ]


def test_phase109_thread_rag_carries_nonblocking_learning_across_tasks_in_same_thread():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory()
    pipeline = MemoryPipeline(store=store, journal=journal)
    result = pipeline.propose_from_task_reflection(
        root_goal="调查一个来源质量不稳定的目标",
        outcome="failed",
        task_id="task-old",
        run_id="run-old",
        thread_id="thread-learning",
        source_record_ref="ledger-old-failure",
        failure_report={
            "reason": "retrieval_source_quality_insufficient",
            "attempted_actions": ["retrieval.run"],
            "missing_evidence": ["authoritative source"],
            "next_possible_action": "switch_source_family",
        },
    )

    same_thread = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-learning",
        task_id="task-new",
    )
    other_thread = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-other",
        task_id="task-new",
    )

    assert same_thread["memory_learning"][0]["proposal_id"] == result.proposals[0].proposal_id
    assert same_thread["memory_learning"][0]["review_nonblocking"] is True
    assert any(block["kind"] == "memory_learning_signal" for block in same_thread["attention_blocks"])
    assert other_thread["memory_learning"] == []
    assert store.recall(query="source quality", scope={"thread_id": "thread-learning"}).total == 0


class _CapturingProvider:
    name = "capture"
    model = "capture-model"

    def __init__(self, responses):
        self.responses = responses
        self.prompts = []

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        task_type = str(request.parameters.get("task_type"))
        self.prompts.append((task_type, request.prompt))
        payload = self.responses[task_type]
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": self.model},
            usage=usage_from_text(prompt=request.prompt, completion=text),
            error=None,
        )
