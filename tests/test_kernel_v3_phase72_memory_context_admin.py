import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.context import ContextPackCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryStore, stable_memory_id
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.session import TaskState


def test_phase72_context_injects_durable_memory_as_separate_section():
    store = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="偏好中文短答", thread_id="thread-1")
    store.commit(item)
    task = _task(thread_id="thread-1")

    pack = ContextPackCompiler(durable_memory_store=store).compile(task, JournalStore.in_memory())

    section_names = [section["name"] for section in pack.sections]
    assert "durable_memory" in section_names
    assert "memory_refs" in section_names
    assert pack.memory_refs == []
    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert durable["items"][0]["memory_id"] == item.memory_id
    assert durable["items"][0]["summary"] == "偏好中文短答"
    assert "body" not in durable["items"][0]
    assert item.memory_id in pack.source_refs
    assert "ledger-source" in pack.source_refs


def test_phase72_context_does_not_add_durable_section_without_store():
    pack = ContextPackCompiler().compile(_task(thread_id="thread-1"), JournalStore.in_memory())

    assert "durable_memory" not in [section["name"] for section in pack.sections]


def test_phase72_context_excludes_deleted_and_expired_memory():
    store = MemoryStore.in_memory(clock_ms=_clock())
    active = _memory_item(summary="active memory", thread_id="thread-1")
    deleted = _memory_item(summary="deleted memory", thread_id="thread-1")
    expired = _memory_item(summary="expired memory", thread_id="thread-1", expires_at_ms=1)
    store.commit(active)
    store.commit(deleted)
    store.commit(expired)
    store.delete(deleted.memory_id, reason="test")

    pack = ContextPackCompiler(durable_memory_store=store).compile(_task(thread_id="thread-1"), JournalStore.in_memory())

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert [item["memory_id"] for item in durable["items"]] == [active.memory_id]


def test_phase72_context_excludes_sensitive_memory_unless_explicitly_enabled():
    store = MemoryStore.in_memory(clock_ms=_clock())
    sensitive = _memory_item(summary="sensitive memory", thread_id="thread-1", privacy_class="sensitive")
    store.commit(sensitive)

    default_pack = ContextPackCompiler(durable_memory_store=store).compile(
        _task(thread_id="thread-1"),
        JournalStore.in_memory(),
    )
    explicit_pack = ContextPackCompiler(
        durable_memory_store=store,
        include_sensitive_memory=True,
    ).compile(
        _task(thread_id="thread-1"),
        JournalStore.in_memory(),
    )

    default_durable = next(section for section in default_pack.sections if section["name"] == "durable_memory")
    explicit_durable = next(section for section in explicit_pack.sections if section["name"] == "durable_memory")
    assert default_durable["items"] == []
    assert explicit_durable["items"][0]["memory_id"] == sensitive.memory_id


def test_phase72_chat_memory_admin_approves_and_lists_pending_proposal():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    runtime = AgentRuntime(
        journal=journal,
        memory_store=store,
        processor_fabric=fake_fabric({"semantic.intake": _memory_intake_payload("我偏好中文短答")}, journal=journal),
    )
    chat = ChatRuntime(journal=journal, agent_runtime=runtime, memory_store=store, semantic_mode="model")

    first = chat.receive("记住我偏好中文短答", thread_id="thread-memory")
    proposal_id = store.proposals()[0].proposal_id
    listed = chat.receive("/memory proposals", thread_id="thread-memory")
    approved = chat.receive(f"/memory approve {proposal_id}", thread_id="thread-memory")
    memory_list = chat.receive("/memory list", thread_id="thread-memory")

    assert first.status == "needs_user_input"
    assert listed.status == "completed"
    assert proposal_id in listed.answer
    assert approved.status == "completed"
    assert store.recall(query="中文", scope={"thread_id": "thread-memory"}).total == 1
    assert "中文" in memory_list.answer


def test_phase72_cli_memory_propose_approve_list_delete(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    memory_log = tmp_path / "memory.jsonl"
    memory_index = tmp_path / "memory.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--memory-log", str(memory_log), "--memory-index", str(memory_index)]

    assert cli.main([*base, "memory", "propose", "remember my preference: concise Chinese replies", "--thread", "cli-thread"]) == 0
    proposed = json.loads(capsys.readouterr().out)
    proposal_id = proposed["result"]["proposals"][0]["proposal_id"]

    assert cli.main([*base, "memory", "approve", proposal_id]) == 0
    approved = json.loads(capsys.readouterr().out)
    memory_id = approved["result"]["committed_items"][0]["memory_id"]

    assert cli.main([*base, "memory", "approve", proposal_id]) == 0
    approved_again = json.loads(capsys.readouterr().out)
    assert approved_again["result"]["committed_items"][0]["memory_id"] == memory_id

    assert cli.main([*base, "memory", "list", "--thread", "cli-thread"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["result"]["total"] == 1

    assert cli.main([*base, "memory", "delete", memory_id, "--reason", "test"]) == 0
    capsys.readouterr()
    assert cli.main([*base, "memory", "list", "--thread", "cli-thread"]) == 0
    listed_after_delete = json.loads(capsys.readouterr().out)
    assert listed_after_delete["result"]["total"] == 0


def _task(*, thread_id: str) -> TaskState:
    return TaskState(
        task_id="task-1",
        run_id="run-1",
        thread_id=thread_id,
        input_text="what should you remember?",
        status="running",
        step_id="step-1",
    )


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
        body=f"body should not be injected: {summary}",
        structured={"source": "test"},
        scope=scope,
        privacy_class=privacy_class,
        confidence=0.9,
        ttl_policy="expires_at" if expires_at_ms is not None else "forever",
        expires_at_ms=expires_at_ms,
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


def _memory_intake_payload(text: str) -> dict:
    return {
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


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
