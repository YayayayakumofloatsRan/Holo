import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.agent.workloop import WorkloopConfig
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
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
