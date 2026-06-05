import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.context import ContextPackCompiler, ProjectProfile
from kernel_v3.context.compiler import CONTEXT_DURABLE_MEMORY_LIMIT_CAP
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


def test_phase72_context_injects_project_memory_across_threads():
    store = MemoryStore.in_memory(clock_ms=_clock())
    same_project = _memory_item(summary="项目默认中文短答", thread_id="thread-old")
    other_project = _memory_item(summary="other project memory", thread_id="thread-other", project_id="other-project")
    other_user = _memory_item(summary="other user same project memory", thread_id="thread-other-user", user_id="other:user")
    store.commit(same_project)
    store.commit(other_project)
    store.commit(other_user)
    task = _task(thread_id="thread-new")
    profile = ProjectProfile(
        project_id="holo-kernel-v3",
        root="",
        summary="Kernel v3 project.",
        constraints=[],
        redaction_markers=[],
    )

    pack = ContextPackCompiler(durable_memory_store=store, project_profile=profile).compile(
        task,
        JournalStore.in_memory(),
    )

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert [item["memory_id"] for item in durable["items"]] == [same_project.memory_id]
    assert durable["scope"] == {"user_id": "local:user", "project_id": "holo-kernel-v3"}
    access_event = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"][-1]
    assert access_event["payload"]["scope"] == {"user_id": "local:user", "project_id": "holo-kernel-v3"}
    assert access_event["payload"]["memory_ids"] == [same_project.memory_id]


def test_phase72_context_injects_project_and_thread_memory_views_together():
    store = MemoryStore.in_memory(clock_ms=_clock())
    project_item = _memory_item(summary="项目默认使用 kernel-v3 分支", thread_id="thread-old")
    thread_item = _memory_item(summary="当前线程正在审查多轮 loop 衔接", thread_id="thread-current", project_id="local")
    store.commit(project_item)
    store.commit(thread_item)
    profile = ProjectProfile(
        project_id="holo-kernel-v3",
        root="",
        summary="Kernel v3 project.",
        constraints=[],
        redaction_markers=[],
    )

    pack = ContextPackCompiler(durable_memory_store=store, project_profile=profile).compile(
        _task(thread_id="thread-current", input_text="继续审查多轮 loop"),
        JournalStore.in_memory(),
    )

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert durable["views"]["project"]["items"][0]["memory_id"] == project_item.memory_id
    assert durable["views"]["thread"]["items"][0]["memory_id"] == thread_item.memory_id
    assert durable["combined"]["memory_ids"] == [project_item.memory_id, thread_item.memory_id]
    assert [item["memory_id"] for item in durable["items"]] == [project_item.memory_id, thread_item.memory_id]


def test_phase72_context_fallback_thread_memory_is_user_scoped():
    store = MemoryStore.in_memory(clock_ms=_clock())
    current_user = _memory_item(summary="current user thread memory", thread_id="thread-1")
    other_user = _memory_item(summary="other user thread memory", thread_id="thread-1", user_id="other:user")
    store.commit(current_user)
    store.commit(other_user)

    pack = ContextPackCompiler(durable_memory_store=store).compile(_task(thread_id="thread-1"), JournalStore.in_memory())

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert [item["memory_id"] for item in durable["items"]] == [current_user.memory_id]
    assert durable["scope"] == {"user_id": "local:user", "thread_id": "thread-1"}


def test_phase72_context_ranks_durable_memory_by_task_input():
    store = MemoryStore.in_memory(clock_ms=_clock())
    unrelated = _memory_item(summary="Project prefers verbose English reports.", thread_id="thread-old")
    relevant = _memory_item(summary="Finance research should cite primary filings.", thread_id="thread-old")
    store.commit(unrelated)
    store.commit(relevant)
    profile = ProjectProfile(
        project_id="holo-kernel-v3",
        root="",
        summary="Kernel v3 project.",
        constraints=[],
        redaction_markers=[],
    )

    pack = ContextPackCompiler(
        durable_memory_store=store,
        project_profile=profile,
        durable_memory_limit=1,
    ).compile(
        _task(thread_id="thread-new", input_text="continue finance research"),
        JournalStore.in_memory(),
    )

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    assert [item["memory_id"] for item in durable["items"]] == [relevant.memory_id]
    access_event = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"][-1]
    assert access_event["payload"]["memory_ids"] == [relevant.memory_id]
    assert "rank_query_hash" in access_event["payload"]["access_context"]
    assert "continue finance research" not in json.dumps(access_event, ensure_ascii=False)


def test_phase72_context_durable_memory_limit_is_bounded_and_audited():
    store = MemoryStore.in_memory(clock_ms=_clock())
    for index in range(CONTEXT_DURABLE_MEMORY_LIMIT_CAP + 5):
        store.commit(_memory_item(summary=f"bounded context memory {index}", thread_id="thread-1"))

    requested_limit = CONTEXT_DURABLE_MEMORY_LIMIT_CAP + 99
    pack = ContextPackCompiler(
        durable_memory_store=store,
        durable_memory_limit=requested_limit,
    ).compile(_task(thread_id="thread-1"), JournalStore.in_memory())

    durable = next(section for section in pack.sections if section["name"] == "durable_memory")
    access_event = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"][-1]

    assert len(durable["items"]) == CONTEXT_DURABLE_MEMORY_LIMIT_CAP
    assert durable["limit"] == CONTEXT_DURABLE_MEMORY_LIMIT_CAP
    assert durable["requested_limit"] == requested_limit
    assert durable["limit_cap"] == CONTEXT_DURABLE_MEMORY_LIMIT_CAP
    assert durable["limit_clamped"] is True
    assert access_event["payload"]["limit"] == CONTEXT_DURABLE_MEMORY_LIMIT_CAP
    assert access_event["payload"]["access_context"]["durable_memory_limit"] == CONTEXT_DURABLE_MEMORY_LIMIT_CAP
    assert len(access_event["payload"]["memory_ids"]) == CONTEXT_DURABLE_MEMORY_LIMIT_CAP


def test_phase72_context_injection_audits_memory_access_without_changing_snapshot_hash():
    store = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="偏好中文短答", thread_id="thread-1")
    store.commit(item)
    task = _task(thread_id="thread-1")
    compiler = ContextPackCompiler(durable_memory_store=store)

    first = compiler.compile(task, JournalStore.in_memory())
    second = compiler.compile(task, JournalStore.in_memory())

    access_events = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"]
    first_durable = next(section for section in first.sections if section["name"] == "durable_memory")
    second_durable = next(section for section in second.sections if section["name"] == "durable_memory")
    assert len(access_events) == 2
    assert access_events[0]["payload"]["memory_ids"] == [item.memory_id]
    assert access_events[0]["payload"]["access_context"]["usage"] == "context_pack"
    assert access_events[0]["payload"]["access_context"]["context_id"] == first.context_id
    assert store.get(item.memory_id, include_inactive=True).last_accessed_ms == access_events[-1]["payload"]["accessed_at_ms"]
    assert first_durable["items"][0]["payload_hash"] == second_durable["items"][0]["payload_hash"]
    assert first.payload_hash == second.payload_hash


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
    memory_id = store.recall(query="中文", scope={"thread_id": "thread-memory"}).items[0]["memory_id"]
    exported = chat.receive(f"/memory export {memory_id}", thread_id="thread-memory")
    deleted = chat.receive(f"/memory delete {memory_id} test-delete", thread_id="thread-memory")

    assert first.status == "needs_user_input"
    assert first.pending_question is not None
    assert proposal_id in first.pending_question["question"]
    assert "/memory approve <proposal_id>" in first.pending_question["question"]
    assert first.pending_question["metadata"]["pending_type"] == "memory_review"
    assert first.pending_question["metadata"]["memory_proposal_ids"] == [proposal_id]
    assert listed.status == "completed"
    assert proposal_id in listed.answer
    assert approved.status == "completed"
    assert exported.status == "completed"
    assert deleted.status == "completed"
    assert "中文" in memory_list.answer
    list_events = [event for event in store.audit_records() if event["event_type"] == "memory_items_recalled"]
    assert list_events[-1]["payload"]["memory_ids"] == [memory_id]
    assert list_events[-1]["payload"]["access_context"]["surface"] == "chat"
    assert list_events[-1]["payload"]["access_context"]["thread_id"] == "thread-memory"
    assert list_events[-1]["payload"]["access_context"]["command"] == "/memory list"
    export_events = [event for event in store.audit_records() if event["event_type"] == "memory_item_exported"]
    assert export_events[-1]["payload"]["memory_id"] == memory_id
    assert export_events[-1]["payload"]["access_context"]["surface"] == "chat"
    assert export_events[-1]["payload"]["access_context"]["thread_id"] == "thread-memory"
    assert store.recall(query="中文", scope={"thread_id": "thread-memory"}).total == 0
    delete_records = journal.records(kind="memory_item_deleted")
    assert delete_records[-1].data["memory_id"] == memory_id
    assert delete_records[-1].data["reason"] == "test-delete"


def test_phase72_chat_memory_admin_unknown_id_is_command_failure():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, memory_store=store),
        memory_store=store,
    )

    result = chat.receive("/memory approve missing-proposal", thread_id="thread-memory")

    assert result.status == "failed"
    assert result.command_result is not None
    assert result.command_result["status"] == "failed"
    assert result.command_result["result"]["error"] == "unknown proposal_id: missing-proposal"
    assert "Memory command failed" in (result.answer or "")
    command = journal.records(kind="chat_command")[-1].data
    assert command["name"] == "/memory"
    assert command["status"] == "failed"


def test_phase72_chat_memory_admin_journals_previews_not_memory_bodies():
    journal = JournalStore.in_memory()
    store = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="safe summary", thread_id="thread-memory")
    store.commit(item)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, memory_store=store),
        memory_store=store,
    )

    listed = chat.receive("/memory list", thread_id="thread-memory")
    exported = chat.receive(f"/memory export {item.memory_id}", thread_id="thread-memory")

    assert listed.status == "completed"
    assert exported.status == "completed"
    assert listed.command_result is not None
    assert listed.command_result["result"]["items"][0]["summary"] == "safe summary"
    assert exported.command_result is not None
    assert exported.command_result["result"]["redaction"] == {"export_payload": "not_journaled"}
    command_dump = json.dumps([record.data for record in journal.records(kind="chat_command")], ensure_ascii=False)
    assert "body should not be injected: safe summary" not in command_dump
    assert '"source": "test"' not in command_dump


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
    list_events = [
        event
        for event in MemoryStore(memory_log, index_path=memory_index).audit_records()
        if event["event_type"] == "memory_items_recalled"
    ]
    assert list_events[-1]["payload"]["memory_ids"] == [memory_id]
    assert list_events[-1]["payload"]["access_context"]["surface"] == "cli"
    assert list_events[-1]["payload"]["access_context"]["command"] == "memory list"
    assert list_events[-1]["payload"]["access_context"]["thread_id"] == "cli-thread"

    assert cli.main([*base, "memory", "export", memory_id]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["export"]["memory_id"] == memory_id
    export_events = [
        event
        for event in MemoryStore(memory_log, index_path=memory_index).audit_records()
        if event["event_type"] == "memory_item_exported"
    ]
    assert export_events[-1]["payload"]["memory_id"] == memory_id
    assert export_events[-1]["payload"]["access_context"]["surface"] == "cli"
    assert export_events[-1]["payload"]["redaction"] == {"export_payload": "not_embedded"}

    assert cli.main([*base, "memory", "delete", memory_id, "--reason", "test"]) == 0
    capsys.readouterr()
    delete_records = JournalStore(journal, index_path=index).records(kind="memory_item_deleted")
    assert delete_records[-1].data["memory_id"] == memory_id
    assert delete_records[-1].data["reason"] == "test"
    assert cli.main([*base, "memory", "list", "--thread", "cli-thread"]) == 0
    listed_after_delete = json.loads(capsys.readouterr().out)
    assert listed_after_delete["result"]["total"] == 0


def test_phase72_cli_memory_admin_unknown_id_is_failed_payload(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    memory_log = tmp_path / "memory.jsonl"
    memory_index = tmp_path / "memory.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--memory-log", str(memory_log), "--memory-index", str(memory_index)]

    status = cli.main([*base, "memory", "delete", "missing-memory", "--reason", "test"])
    payload = json.loads(capsys.readouterr().out)

    assert status == 1
    assert payload["status"] == "failed"
    assert payload["reason"] == "unknown memory_id: missing-memory"
    assert payload["target_id"] == "missing-memory"
    records = JournalStore(journal, index_path=index).records(kind="memory_command_failed")
    assert records[-1].data["command"] == "delete"
    assert records[-1].data["target_id"] == "missing-memory"


def _task(*, thread_id: str, input_text: str = "what should you remember?") -> TaskState:
    return TaskState(
        task_id="task-1",
        run_id="run-1",
        thread_id=thread_id,
        input_text=input_text,
        status="running",
        step_id="step-1",
    )


def _memory_item(
    *,
    summary: str,
    thread_id: str,
    user_id: str = "local:user",
    project_id: str = "holo-kernel-v3",
    expires_at_ms: int | None = None,
    privacy_class: str = "project_internal",
) -> MemoryItem:
    scope = {"user_id": user_id, "project_id": project_id, "thread_id": thread_id}
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
