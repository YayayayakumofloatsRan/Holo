import json
from pathlib import Path

from kernel_v3.agent.contracts import SemanticIntake
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryPipeline, MemoryStore, stable_memory_id
from kernel_v3.processors.testing import fake_fabric


def test_phase71_explicit_memory_intent_creates_pending_proposal_without_commit():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    runtime = AgentRuntime(
        journal=journal,
        memory_store=store,
        processor_fabric=fake_fabric({"semantic.intake": _memory_intake_payload("我偏好中文短答")}, journal=journal),
    )

    result = runtime.run("记住我偏好中文短答", thread_id="phase71-thread", semantic_mode="model")

    assert result.status == "needs_user_input"
    assert [candidate.status for candidate in store.shadow_candidates()] == ["open"]
    proposals = store.proposals()
    assert len(proposals) == 1
    assert proposals[0].approval_policy == "needs_review"
    assert proposals[0].approval_status == "pending"
    assert store.recall(query="中文", scope={"thread_id": "phase71-thread"}).total == 0
    assert {"memory_shadow_candidate", "memory_proposal"}.issubset({record.kind for record in journal.records()})


def test_phase71_model_intake_omitting_memory_write_does_not_create_memory():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "direct_answer",
                "suggested_mode": "direct_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "direct_answer",
                        "text": "remember my preference",
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
            }
        },
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, memory_store=store, processor_fabric=fabric)

    result = runtime.run("remember my preference: concise Chinese replies", semantic_mode="model")

    assert result.status == "completed"
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "direct_answer"
    assert intake["blocked_capabilities"] == []
    assert store.proposals() == []
    assert not {"memory_shadow_candidate", "memory_proposal"}.intersection({record.kind for record in journal.records()})


def test_phase71_model_intake_with_durable_memory_capability_creates_proposal():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    runtime = AgentRuntime(
        journal=journal,
        memory_store=store,
        processor_fabric=fake_fabric(
            {"semantic.intake": _memory_intake_payload("concise Chinese replies")},
            journal=journal,
        ),
    )

    result = runtime.run("remember my preference: concise Chinese replies", semantic_mode="model")

    assert result.status == "needs_user_input"
    intake = journal.records(task_id=result.task_id, kind="semantic_intake")[0].data
    assert intake["primary_intent"] == "memory_write"
    assert intake["blocked_capabilities"] == ["durable_memory:write"]
    assert len(store.proposals()) == 1


def test_phase71_approving_proposal_commits_memory_item():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    pipeline = MemoryPipeline(store=store, journal=journal, clock_ms=_clock())
    result = pipeline.propose_from_semantic_intake(
        _memory_intake("remember my preference: concise Chinese replies"),
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        source_record_ref="ledger-source",
    )

    approved = pipeline.approve_proposal(result.proposals[0].proposal_id, approved_by="user")

    assert approved.committed_items[0].approved_by == "user"
    assert approved.committed_items[0].state == "active"
    assert store.recall(query="Chinese", scope={"thread_id": "thread-1"}).total == 1
    assert {"memory_proposal_approved", "memory_item_committed"}.issubset({record.kind for record in journal.records()})


def test_phase71_rejecting_proposal_leaves_no_recallable_memory():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    pipeline = MemoryPipeline(store=store, journal=journal, clock_ms=_clock())
    result = pipeline.propose_from_semantic_intake(
        _memory_intake("记住我偏好中文短答"),
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        source_record_ref="ledger-source",
    )

    rejected = pipeline.reject_proposal(result.proposals[0].proposal_id, reason="user_declined")

    assert rejected.proposals[0].approval_status == "rejected"
    assert store.recall(query="中文", scope={"thread_id": "thread-1"}).total == 0
    assert journal.records(kind="memory_proposal_rejected")


def test_phase71_conflicting_memory_requires_conflict_review():
    store = MemoryStore.in_memory(clock_ms=_clock())
    pipeline = MemoryPipeline(store=store, clock_ms=_clock())
    existing = _memory_item(
        summary="我偏好中文短答",
        body="记住我偏好中文短答",
        dedupe_key="user_preference:response-style",
        scope={"user_id": "local:user", "project_id": "holo-kernel-v3", "thread_id": "thread-1"},
    )
    store.commit(existing)

    result = pipeline.propose_from_semantic_intake(
        _memory_intake("记住我偏好英文短答"),
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        source_record_ref="ledger-source",
    )

    assert result.proposals[0].approval_policy == "conflict_review"
    assert "conflicts_existing" in result.proposals[0].risk_flags
    assert result.proposals[0].metadata["existing_memory_ids"] == [existing.memory_id]


def test_phase71_secret_like_candidate_is_rejected_without_raw_payload_in_memory_audit():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    pipeline = MemoryPipeline(store=store, journal=journal, clock_ms=_clock())
    secret = "remember api_key=sk_12345678901234567890 for later"

    result = pipeline.propose_from_semantic_intake(
        _memory_intake(secret),
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        source_record_ref="ledger-source",
    )

    assert result.rejected[0]["reason"] == "memory_rejected_secret_like_content"
    assert store.shadow_candidates() == []
    assert store.proposals() == []
    assert store.list_items() == []
    dumped = json.dumps([record.to_dict() for record in journal.records()], ensure_ascii=False)
    assert "sk_12345678901234567890" not in dumped
    assert "api_key" not in dumped
    assert "candidate_text_hash" in dumped


def test_phase71_default_agent_runtime_does_not_write_memory_without_store():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal)

    runtime.run("记住我偏好中文短答", thread_id="no-memory-store")

    forbidden = {
        "memory_shadow_candidate",
        "memory_proposal",
        "memory_proposal_approved",
        "memory_item_committed",
    }
    assert not forbidden.intersection({record.kind for record in journal.records()})


def test_phase71_memory_store_replays_proposal_decisions(tmp_path: Path):
    log_path = tmp_path / "memory.jsonl"
    store = MemoryStore(log_path, clock_ms=_clock())
    pipeline = MemoryPipeline(store=store, clock_ms=_clock())
    result = pipeline.propose_from_semantic_intake(
        _memory_intake("remember my preference: concise Chinese replies"),
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        source_record_ref="ledger-source",
    )
    pipeline.reject_proposal(result.proposals[0].proposal_id, reason="user_declined")

    reloaded = MemoryStore(log_path, clock_ms=_clock())

    assert reloaded.proposal(result.proposals[0].proposal_id).approval_status == "rejected"


def _memory_intake(text: str) -> SemanticIntake:
    return SemanticIntake.from_dict(_memory_intake_payload(text))


def _memory_intake_payload(text: str) -> dict:
    return {
        "intake_id": "semantic-intake-1",
        "goal": text,
        "primary_intent": "memory_write",
        "suggested_mode": "clarify_first",
        "compound": False,
        "requires_clarification": True,
        "intents": [
            {
                "kind": "memory_write",
                "text": text,
                "sequence_index": 1,
                "required_capabilities": ["durable_memory:write"],
                "risk": "write",
                "status": "needs_review",
                "metadata": {},
            }
        ],
        "blocked_capabilities": ["durable_memory:write"],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _memory_item(*, summary: str, body: str, dedupe_key: str, scope: dict) -> MemoryItem:
    return MemoryItem(
        memory_id=stable_memory_id(kind="user_preference", scope=scope, dedupe_key=dedupe_key, summary=summary),
        kind="user_preference",
        title=summary,
        summary=summary,
        body=body,
        structured={"source": "test"},
        scope=scope,
        privacy_class="project_internal",
        confidence=0.9,
        ttl_policy="forever",
        expires_at_ms=None,
        dedupe_key=dedupe_key,
        conflict_keys=[dedupe_key],
        provenance_refs=["ledger-source"],
        artifact_refs=[],
        state="active",
        approved_by="user",
        created_at_ms=1,
        updated_at_ms=1,
        last_accessed_ms=None,
        metadata={},
    )


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
