import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.chat import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryProposal, MemoryStore, stable_memory_id, stable_proposal_id
from kernel_v3.resident import ResidentQueue, ResidentRuntime


def test_phase75_memory_store_inspect_reports_reviewable_state() -> None:
    store = MemoryStore.in_memory(clock_ms=_clock())
    active = _memory_item(summary="active preference", thread_id="thread-inspect")
    expired = _memory_item(summary="expired preference", thread_id="thread-inspect", expires_at_ms=500)
    deleted = _memory_item(summary="deleted preference", thread_id="thread-inspect")
    sensitive = _memory_item(summary="sensitive preference", thread_id="thread-inspect", privacy_class="sensitive")
    store.commit(active)
    store.commit(expired)
    store.commit(deleted)
    store.commit(sensitive)
    store.delete(deleted.memory_id, reason="test-delete", deleted_at_ms=1_100)
    store.record_proposal(_proposal(active, proposal_id="memprop-pending"))

    inspection = store.inspect(sample_limit=2, now_ms=1_200)

    assert inspection.status == "needs_review"
    assert inspection.active_count == 2
    assert inspection.expired_count == 1
    assert inspection.deleted_count == 1
    assert inspection.sensitive_count == 1
    assert inspection.proposal_counts["pending"] == 1
    assert inspection.tombstone_count == 1
    assert "memory proposals" in inspection.recommended_actions
    assert "memory delete <memory_id> --reason expired" in inspection.recommended_actions
    assert "memory export <memory_id>" in inspection.recommended_actions
    assert len(inspection.samples["active_items"]) == 2
    assert inspection.samples["pending_proposals"][0]["proposal_id"] == "memprop-pending"


def test_phase75_chat_memory_inspect_returns_auditable_summary() -> None:
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="chat preference", thread_id="thread-memory-inspect")
    store.commit(item)
    store.record_proposal(_proposal(item, proposal_id="memprop-chat"))
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, memory_store=store),
        memory_store=store,
    )

    result = chat.receive("/memory inspect", thread_id="thread-memory-inspect")

    assert result.status == "completed"
    assert result.command_result is not None
    assert result.command_result["result"]["status"] == "needs_review"
    assert result.command_result["result"]["proposal_counts"]["pending"] == 1
    assert "Memory status: needs_review" in (result.answer or "")
    assert journal.records(kind="chat_command")[-1].data["name"] == "/memory"


def test_phase75_cli_memory_inspect_reports_store_health(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    memory_log = tmp_path / "memory.jsonl"
    memory_index = tmp_path / "memory.sqlite"
    store = MemoryStore(memory_log, index_path=memory_index, clock_ms=_clock())
    item = _memory_item(summary="cli preference", thread_id="cli-thread")
    store.commit(item)
    store.record_proposal(_proposal(item, proposal_id="memprop-cli"))
    base = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--memory-log",
        str(memory_log),
        "--memory-index",
        str(memory_index),
    ]

    assert cli.main([*base, "memory", "inspect", "--sample-limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "needs_review"
    assert payload["inspection"]["active_count"] == 1
    assert payload["inspection"]["proposal_counts"]["pending"] == 1
    assert payload["inspection"]["samples"]["active_items"][0]["memory_id"] == item.memory_id


def test_phase75_resident_can_surface_memory_inspection(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="resident preference", thread_id="resident-memory")
    store.commit(item)
    store.record_proposal(_proposal(item, proposal_id="memprop-resident"))
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, memory_store=store),
        memory_store=store,
    )
    queue.enqueue(thread_id="resident-memory", text="/memory inspect", message_id="in-memory-inspect")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-memory", journal=journal).run_once()

    outbox = queue.outbox_messages()[0]
    assert result.status == "processed"
    assert outbox.status == "ready"
    assert "Memory status: needs_review" in outbox.text
    assert outbox.payload["command_result"]["result"]["proposal_counts"]["pending"] == 1


def _memory_item(
    *,
    summary: str,
    thread_id: str,
    expires_at_ms: int | None = None,
    privacy_class: str = "project_internal",
) -> MemoryItem:
    scope = {"user_id": "local:user", "project_id": "holo-kernel-v3", "thread_id": thread_id}
    dedupe_key = f"user_preference:{summary}"
    return MemoryItem(
        memory_id=stable_memory_id(kind="user_preference", scope=scope, dedupe_key=dedupe_key, summary=summary),
        kind="user_preference",
        title=summary,
        summary=summary,
        body=summary,
        structured={"source": "test"},
        scope=scope,
        privacy_class=privacy_class,
        confidence=0.9,
        ttl_policy="expires_at" if expires_at_ms is not None else "forever",
        expires_at_ms=expires_at_ms,
        dedupe_key=dedupe_key,
        conflict_keys=[dedupe_key],
        provenance_refs=[],
        artifact_refs=[],
        state="active",
        approved_by="test",
        created_at_ms=1_000,
        updated_at_ms=1_000,
        last_accessed_ms=None,
    )


def _proposal(item: MemoryItem, *, proposal_id: str | None = None) -> MemoryProposal:
    payload = {"memory_id": item.memory_id, "summary": item.summary}
    return MemoryProposal(
        proposal_id=proposal_id or stable_proposal_id(payload),
        candidate_id=None,
        operation="upsert",
        proposed_item=item.to_dict(),
        rationale="test proposal",
        source_task_id="task-memory-inspect",
        source_run_id="run-1",
        source_thread_id=str(item.scope["thread_id"]),
        evidence_record_refs=[],
        artifact_refs=[],
        risk_flags=[],
        approval_policy="needs_review",
        approval_status="pending",
        confidence=0.9,
        created_at_ms=1_001,
        decided_at_ms=None,
    )


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
