import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.resident import ResidentQueue, ResidentRuntime
from kernel_v3.trace import TraceRenderer


def test_phase73_resident_worker_processes_inbox_to_outbox(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))
    queue.enqueue(thread_id="resident-thread", text="hello resident", message_id="in-1")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-1", journal=journal).run_once()

    assert result.status == "processed"
    assert queue.inbox_messages()[0].status == "completed"
    outbox = queue.outbox_messages()[0]
    assert outbox.in_reply_to == "in-1"
    assert outbox.status == "ready"
    assert "离线 host fallback" in outbox.text
    assert "Direct answer:" not in outbox.text
    resident_kinds = [record.kind for record in journal.records() if record.kind.startswith("resident_")]
    assert resident_kinds == [
        "resident_lease_acquired",
        "resident_inbox_claimed",
        "resident_outbox_appended",
        "resident_inbox_completed",
        "resident_lease_released",
    ]
    assert "resident_outbox_appended" in TraceRenderer(journal).render_resident_trace()


def test_phase73_worker_lease_prevents_duplicate_ownership(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())

    first = queue.acquire_lease(worker_id="worker-1", ttl_ms=30_000)
    second = queue.acquire_lease(worker_id="worker-2", ttl_ms=30_000)

    assert first is not None
    assert second is None


def test_phase73_restart_picks_pending_inbox_item(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello after restart", message_id="in-restart")
    restarted = ResidentQueue(db_path, clock_ms=_clock(start=2_000))
    journal = JournalStore.in_memory()

    result = ResidentRuntime(
        queue=restarted,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-restart",
    ).run_once()

    assert result.status == "processed"
    assert restarted.inbox_messages()[0].status == "completed"
    assert restarted.outbox_messages()[0].in_reply_to == "in-restart"


def test_phase73_restart_after_partial_outbox_write_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello after partial crash", message_id="in-partial")
    assert queue.acquire_lease(worker_id="crashed-worker", ttl_ms=10) is not None
    claimed = queue.claim_next(worker_id="crashed-worker", lease_ttl_ms=1)
    assert claimed is not None
    queue.append_outbox(
        in_reply_to=claimed.message_id,
        thread_id=claimed.thread_id,
        text="previous outbox already written",
        status="ready",
        task_id="task-crash",
        run_id="run-crash",
        payload={"partial": True},
    )

    restarted = ResidentQueue(db_path, clock_ms=_clock(start=10_000))
    journal = JournalStore.in_memory()
    result = ResidentRuntime(
        queue=restarted,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-restart",
    ).run_once()

    inbox = restarted.inbox_messages()[0]
    outbox = restarted.outbox_messages()
    assert result.status == "processed"
    assert inbox.status == "completed"
    assert inbox.attempts == 2
    assert len(outbox) == 1
    assert outbox[0].in_reply_to == "in-partial"
    assert outbox[0].text == "previous outbox already written"


def test_phase73_claim_requires_active_worker_lease(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello without lease", message_id="in-no-lease")

    assert queue.claim_next(worker_id="worker-without-lease") is None
    inbox = queue.inbox_messages()[0]
    assert inbox.status == "pending"
    assert inbox.attempts == 0


def test_phase73_stale_worker_cannot_complete_message_after_reclaim(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello reclaim", message_id="in-reclaim")
    assert queue.acquire_lease(worker_id="worker-old", ttl_ms=10) is not None
    first = queue.claim_next(worker_id="worker-old", lease_ttl_ms=1)
    assert first is not None

    restarted = ResidentQueue(db_path, clock_ms=_clock(start=10_000))
    assert restarted.acquire_lease(worker_id="worker-new", ttl_ms=30_000) is not None
    second = restarted.claim_next(worker_id="worker-new", lease_ttl_ms=30_000)
    assert second is not None

    assert restarted.complete("in-reclaim", worker_id="worker-old") is False
    inbox = restarted.inbox_messages()[0]
    assert inbox.status == "running"
    assert inbox.lease_owner == "worker-new"

    assert restarted.complete("in-reclaim", worker_id="worker-new") is True
    assert restarted.inbox_messages()[0].status == "completed"


def test_phase73_renew_lease_extends_running_message_claim(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello renew", message_id="in-renew")
    assert queue.acquire_lease(worker_id="worker-1", ttl_ms=10) is not None
    claimed = queue.claim_next(worker_id="worker-1", lease_ttl_ms=10)
    assert claimed is not None
    before = queue.inbox_messages()[0].lease_until_ms

    renewed = queue.renew_lease(worker_id="worker-1", ttl_ms=50)
    after = queue.inbox_messages()[0].lease_until_ms

    assert renewed is not None
    assert before is not None
    assert after is not None
    assert after > before


def test_phase73_needs_user_input_writes_pending_outbox_without_self_continuation(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    queue.enqueue(thread_id="resident-thread", text="read the file", message_id="in-question")

    result = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-1",
    ).run_once()

    outbox = queue.outbox_messages()[0]
    assert result.status == "processed"
    assert outbox.status == "pending_user_input"
    assert "请明确" in outbox.text
    assert len(queue.outbox_messages()) == 1


def test_phase73_bounded_run_loop_processes_until_idle(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    queue.enqueue(thread_id="resident-thread", text="first loop item", message_id="in-loop-1")
    queue.enqueue(thread_id="resident-thread", text="second loop item", message_id="in-loop-2")

    result = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-loop",
    ).run_loop(max_iterations=5)

    assert result.status == "completed"
    assert result.iterations == 3
    assert result.processed_count == 2
    assert result.idle_count == 1
    assert [message.status for message in queue.inbox_messages()] == ["completed", "completed"]
    assert [message.in_reply_to for message in queue.outbox_messages()] == ["in-loop-1", "in-loop-2"]


def test_phase73_worker_failure_retries_then_dead_letters(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="will fail", message_id="in-fail")
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=_RaisingChatRuntime(),
        worker_id="worker-fail",
        max_attempts=2,
        retry_backoff_ms=0,
    )

    first = runtime.run_once()
    first_inbox = queue.inbox_messages()[0]
    second = runtime.run_once()
    second_inbox = queue.inbox_messages()[0]
    third = runtime.run_once()

    assert first.status == "failed"
    assert first.payload["failure_recorded"] is True
    assert first_inbox.status == "retry_wait"
    assert first_inbox.attempts == 1
    assert first_inbox.next_attempt_at_ms is not None
    assert second.status == "failed"
    assert second_inbox.status == "dead_letter"
    assert second_inbox.attempts == 2
    assert second_inbox.metadata["failure_reason"] == "RuntimeError"
    assert third.status == "idle"
    assert not queue.outbox_messages()


def test_phase73_cli_resident_enqueue_run_once_and_outbox(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert cli.main([*base, "resident", "enqueue", "hello cli", "--thread", "resident-cli"]) == 0
    enqueued = json.loads(capsys.readouterr().out)
    assert enqueued["message"]["thread_id"] == "resident-cli"

    assert cli.main([*base, "resident", "run-once", "--worker-id", "worker-cli"]) == 0
    processed = json.loads(capsys.readouterr().out)
    assert processed["status"] == "processed"

    assert cli.main([*base, "resident", "outbox"]) == 0
    outbox = json.loads(capsys.readouterr().out)
    assert outbox["messages"][0]["status"] == "ready"
    assert "离线 host fallback" in outbox["messages"][0]["text"]
    assert "Direct answer:" not in outbox["messages"][0]["text"]
    outbox_id = outbox["messages"][0]["outbox_id"]

    assert cli.main([*base, "resident", "ack", outbox_id, "--status", "acknowledged"]) == 0
    acked = json.loads(capsys.readouterr().out)
    assert acked["outbox"]["status"] == "acknowledged"

    assert cli.main([*base, "resident", "run", "--worker-id", "worker-cli", "--max-iterations", "2"]) == 0
    loop = json.loads(capsys.readouterr().out)
    assert loop["status"] == "idle"

    assert cli.main([*base, "resident-trace"]) == 0
    trace = capsys.readouterr().out
    assert "Resident Trace" in trace
    assert "resident_inbox_enqueued" in trace
    assert "resident_outbox_ack" in trace
    assert outbox_id in trace


class _RaisingChatRuntime:
    def receive(self, text: str, *, thread_id: str):
        raise RuntimeError("simulated failure")


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
