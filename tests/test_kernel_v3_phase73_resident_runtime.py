import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.resident import ResidentQueue, ResidentRuntime


def test_phase73_resident_worker_processes_inbox_to_outbox(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))
    queue.enqueue(thread_id="resident-thread", text="hello resident", message_id="in-1")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-1").run_once()

    assert result.status == "processed"
    assert queue.inbox_messages()[0].status == "completed"
    outbox = queue.outbox_messages()[0]
    assert outbox.in_reply_to == "in-1"
    assert outbox.status == "ready"
    assert "离线 host fallback" in outbox.text
    assert "Direct answer:" not in outbox.text


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


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
