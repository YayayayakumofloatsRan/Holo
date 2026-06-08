from __future__ import annotations

import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.runtime import _compact_thread_rag_context_for_prompt
from kernel_v3.contracts import CandidateAction, ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryStore
from kernel_v3.memory.operator import MemoryRecallOperator
from kernel_v3.mission import ThreadWorkingMemoryProvider
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.processors.usage import usage_from_text


def test_phase110_memory_recall_operator_reads_workspace_and_thread_scopes():
    store = MemoryStore.in_memory(clock_ms=_clock())
    workspace = _memory_item(
        memory_id="mem-workspace-branch",
        summary="Project default branch is kernel-v3.",
        body="Use kernel-v3 for Holo harness work unless the user says otherwise.",
        scope={"user_id": "local:user", "project_id": "holo-kernel-v3"},
        structured={
            "source": "answer_quality_check",
            "profile_format": "detailed_report",
            "gaps": ["answer_min_chars:1200", "source_quality"],
            "next_possible_action": "repair final answer",
        },
    )
    thread = _memory_item(
        memory_id="mem-thread-language",
        summary="This thread prefers concise Chinese answers.",
        body="The current thread should answer in Chinese by default.",
        scope={"user_id": "local:user", "thread_id": "thread-memory"},
    )
    other_thread = _memory_item(
        memory_id="mem-other-thread",
        summary="Other thread private note.",
        body="This must not appear in thread-memory recall.",
        scope={"user_id": "local:user", "thread_id": "other-thread"},
    )
    store.commit(workspace)
    store.commit(thread)
    store.commit(other_thread)
    operator = MemoryRecallOperator(store=store)
    action = CandidateAction(
        action_id="act-memory",
        kind="tool",
        name="memory.recall",
        description="recall active memory",
        score=1.0,
        payload={
            "query": "branch language",
            "scope_mode": "both",
            "limit": 10,
            "_host_context": {
                "task_id": "task-memory",
                "run_id": "run-1",
                "step_id": "step-1",
                "thread_id": "thread-memory",
            },
        },
        reasons=["test"],
        side_effect_class="read",
    )

    observation = operator.execute(action)

    assert observation.status == "ok"
    results = observation.content["results"]
    assert [item["memory_id"] for item in results["workspace"]["items"]] == [workspace.memory_id]
    structured = results["workspace"]["items"][0]["structured_summary"]
    assert structured["values"]["source"] == "answer_quality_check"
    assert structured["values"]["gaps"] == ["answer_min_chars:1200", "source_quality"]
    assert structured["values"]["next_possible_action"] == "repair final answer"
    assert "hash" in structured
    assert [item["memory_id"] for item in results["thread"]["items"]] == [thread.memory_id]
    assert observation.content["combined"]["memory_ids"] == [workspace.memory_id, thread.memory_id]
    assert "query_hash" in observation.content
    access_events = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"]
    assert len(access_events) == 2
    assert all(event["payload"]["access_context"]["usage"] == "tool:memory.recall" for event in access_events)


def test_phase110_agent_loop_can_actively_recall_memory_before_answering():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    store.commit(
        _memory_item(
            memory_id="mem-workspace-branch",
            summary="Project default branch is kernel-v3.",
            body="Use kernel-v3 for Holo harness work.",
            scope={"user_id": "local:user", "project_id": "holo-kernel-v3"},
            structured={
                "source": "answer_quality_check",
                "profile_format": "detailed_report",
                "gaps": ["answer_min_chars:1200"],
            },
        )
    )
    store.commit(
        _memory_item(
            memory_id="mem-thread-language",
            summary="This thread prefers concise Chinese answers.",
            body="Answer in Chinese by default in this thread.",
            scope={"user_id": "local:user", "thread_id": "thread-memory"},
        )
    )
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "semantic.intake": {
                        "primary_intent": "memory_recall",
                        "suggested_mode": "semantic_answer",
                        "compound": False,
                        "requires_clarification": False,
                        "intents": [
                            {
                                "kind": "memory_recall",
                                "text": "你还记得什么？",
                                "sequence_index": 1,
                                "required_capabilities": ["durable_memory.search"],
                                "risk": "none",
                                "status": "ready",
                                "metadata": {
                                    "capability_args": {
                                        "memory.recall": {
                                            "query": "project branch and thread language preference",
                                            "scope_mode": "both",
                                        }
                                    }
                                },
                            }
                        ],
                        "blocked_capabilities": [],
                        "warnings": [],
                        "response_hint": None,
                        "clarification_question": None,
                    },
                    "planner.propose": [
                        {
                            "action_id": "act-memory",
                            "kind": "tool",
                            "name": "memory.recall",
                            "description": "recall relevant durable memory",
                            "payload": {"query": "project branch and thread language preference", "scope_mode": "both"},
                            "score": 0.9,
                            "reasons": ["prior memory is needed before answering"],
                            "side_effect_class": "read",
                        },
                        {
                            "action_id": "act-answer",
                            "kind": "respond",
                            "name": None,
                            "description": "answer from recalled memory",
                            "payload": {"text": "我记得：项目默认使用 kernel-v3 分支；这个线程偏好中文、简洁回答。"},
                            "score": 0.9,
                            "reasons": ["memory.recall observation is available"],
                            "side_effect_class": "none",
                        },
                    ],
                    "evaluator.assess": [
                        {
                            "status": "continue",
                            "answer": None,
                            "stop_reason": None,
                            "missing_evidence": ["respond_from_memory_recall"],
                        },
                        {
                            "status": "final_answer_ready",
                            "answer": "我记得：项目默认使用 kernel-v3 分支；这个线程偏好中文、简洁回答。",
                            "stop_reason": "completed",
                            "missing_evidence": [],
                        },
                    ],
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric, memory_store=store)

    result = runtime.run(
        "你还记得什么？",
        thread_id="thread-memory",
        mode="auto",
        planner_mode="model",
        evaluator_mode="model",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.final_answer is not None
    assert result.final_answer["answer"] == "我记得：项目默认使用 kernel-v3 分支；这个线程偏好中文、简洁回答。"
    action_names = [
        record.data["name"] or record.data["kind"]
        for record in journal.records(task_id=result.task_id, kind="action")
    ]
    assert action_names == ["memory.recall", "respond"]
    memory_observation = [
        record.data for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("source") == "tool:memory.recall"
    ][0]
    assert memory_observation["content"]["combined"]["memory_ids"] == [
        "mem-workspace-branch",
        "mem-thread-language",
    ]
    progress = [record.data["progress_type"] for record in journal.records(task_id=result.task_id, kind="progress_assessment")]
    assert "new_memory_recall" in progress
    thread_context = ThreadWorkingMemoryProvider().compile(
        journal,
        thread_id="thread-memory",
        task_id=result.task_id,
    )
    recalled = thread_context["active_memory_recalls"][-1]
    prompt_context = _compact_thread_rag_context_for_prompt(thread_context)
    assert recalled["combined_total"] == 2
    assert recalled["memory_ids"] == ["mem-workspace-branch", "mem-thread-language"]
    assert recalled["scopes"]["workspace"]["items"][0]["summary"] == "Project default branch is kernel-v3."
    assert recalled["scopes"]["thread"]["items"][0]["summary"] == "This thread prefers concise Chinese answers."
    assert prompt_context["active_memory_recalls"][-1]["memory_ids"] == [
        "mem-workspace-branch",
        "mem-thread-language",
    ]
    assert (
        prompt_context["active_memory_recalls"][-1]["scopes"]["workspace"]["items"][0]["structured_summary"]["values"]["source"]
        == "answer_quality_check"
    )


def test_phase110_model_planner_packet_includes_durable_memory_context():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    store.commit(
        _memory_item(
            memory_id="mem-project-primary-sources",
            summary="Research reports should prefer primary sources.",
            body="Prefer filings, official docs, and primary sources when researching.",
            scope={"user_id": "local:user", "project_id": "holo-kernel-v3"},
        )
    )
    provider = _CapturingProvider(
        {
            "semantic.intake": {
                "primary_intent": "semantic_answer",
                "suggested_mode": "semantic_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "answer",
                        "text": "怎么做调研？",
                        "sequence_index": 1,
                        "required_capabilities": [],
                        "risk": "none",
                        "status": "ready",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            },
            "planner.propose": {
                "action_id": "act-answer",
                "kind": "respond",
                "name": None,
                "description": "answer from context",
                "payload": {"text": "做调研时应优先使用一手来源。"},
                "score": 0.9,
                "reasons": ["durable memory context is sufficient"],
                "side_effect_class": "none",
            },
            "workmethod.frame": {
                "work_frame": {
                    "user_goal": "怎么做调研？",
                    "inferred_goal": "说明调研工作方法",
                    "work_type": "direct_answer",
                    "difficulty": "medium",
                    "risk_level": "low",
                    "expected_output": {"format": "answer", "detail": "concise", "language": "zh"},
                    "done_criteria": ["use relevant memory", "answer clearly"],
                    "tool_needs": [],
                    "memory_needs": ["project research preference"],
                    "assumptions": [],
                },
                "work_method": {
                    "method_name": "memory_grounded_direct_answer",
                    "first_moves": ["use paged durable memory when sufficient"],
                    "evidence_strategy": ["do not invent memory not in context"],
                    "failure_moves": ["use memory.recall if context is sparse"],
                    "stop_policy": ["stop after clear answer"],
                    "user_interaction_policy": ["do not ask user for non-critical detail"],
                    "notes": [],
                },
                "thread_working_set": {
                    "active_goal": "怎么做调研？",
                    "current_method": "memory_grounded_direct_answer",
                    "successful_findings": [],
                    "failed_attempts": [],
                    "open_gaps": [],
                    "user_preferences": {},
                    "next_intent": None,
                    "trace_refs": [],
                },
            },
            "evaluator.assess": {
                "status": "final_answer_ready",
                "answer": "做调研时应优先使用一手来源。",
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
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric, memory_store=store)

    result = runtime.run(
        "怎么做调研？",
        thread_id="thread-memory-context",
        mode="auto",
        planner_mode="model",
        evaluator_mode="model",
        semantic_mode="model",
    )

    assert result.status == "completed"
    planner_prompt = next(prompt for task_type, prompt in provider.prompts if task_type == "planner.propose")
    payload = json.loads(planner_prompt)
    memory_context = payload["context"]["state"]["durable_memory_context"]
    assert memory_context["enabled"] is True
    assert memory_context["combined_memory_ids"] == ["mem-project-primary-sources"]
    assert memory_context["views"]["project"]["total"] == 1
    assert memory_context["top_items"][0]["summary"] == "Research reports should prefer primary sources."
    assert "body" not in memory_context["top_items"][0]


def _clock():
    current = {"value": 1000}

    def tick() -> int:
        current["value"] += 100
        return current["value"]

    return tick


def _memory_item(*, memory_id: str, summary: str, body: str, scope: dict[str, object], structured: dict[str, object] | None = None) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        kind="project_fact",
        title=summary[:60],
        summary=summary,
        body=body,
        structured=dict(structured or {}),
        scope=scope,
        privacy_class="project_internal",
        confidence=0.9,
        ttl_policy="forever",
        expires_at_ms=None,
        dedupe_key=memory_id,
        conflict_keys=[],
        provenance_refs=["ledger-memory-test"],
        artifact_refs=[],
        state="active",
        approved_by="host_auto",
        created_at_ms=1000,
        updated_at_ms=1000,
        last_accessed_ms=None,
        metadata={},
    )


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
