from __future__ import annotations

from kernel_v3.agent import AgentRuntime
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryStore
from kernel_v3.memory.operator import MemoryRecallOperator
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter


def test_phase110_memory_recall_operator_reads_workspace_and_thread_scopes():
    store = MemoryStore.in_memory(clock_ms=_clock())
    workspace = _memory_item(
        memory_id="mem-workspace-branch",
        summary="Project default branch is kernel-v3.",
        body="Use kernel-v3 for Holo harness work unless the user says otherwise.",
        scope={"user_id": "local:user", "project_id": "holo-kernel-v3"},
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


def _clock():
    current = {"value": 1000}

    def tick() -> int:
        current["value"] += 100
        return current["value"]

    return tick


def _memory_item(*, memory_id: str, summary: str, body: str, scope: dict[str, object]) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        kind="project_fact",
        title=summary[:60],
        summary=summary,
        body=body,
        structured={},
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
