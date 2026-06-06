from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.resident import ResidentQueue, ResidentRuntime, ResidentScheduler, compile_reminder


def test_phase119_time_query_alias_routes_to_system_answer():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "time_query",
                "suggested_mode": "semantic_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "time_query",
                        "text": "current time in UTC",
                        "sequence_index": 1,
                        "required_capabilities": ["system.time"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {"capability_args": {"system.time": {"timezone": "UTC"}}},
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

    result = AgentRuntime(journal=journal, processor_fabric=fabric).run(
        "现在 UTC 是几点？",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    assert result.mode == "system_answer"
    assert [record.data["name"] for record in journal.records(task_id=result.task_id, kind="action")] == ["system.time"]
    graph = journal.records(task_id=result.task_id, kind="semantic_task_graph")[0].data
    assert graph["proposal"]["nodes"][0]["kind"] == "system_time"
    assert graph["proposal"]["nodes"][0]["suggested_mode"] == "system_answer"


def test_phase119_queue_claims_highest_priority_first(tmp_path: Path):
    clock = _MutableClock(1_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    queue.enqueue(thread_id="t", text="low", message_id="low", priority=0)
    queue.enqueue(thread_id="t", text="high", message_id="high", priority=50)
    queue.acquire_lease(worker_id="worker", ttl_ms=30_000)

    claimed = queue.claim_next(worker_id="worker")

    assert claimed is not None
    assert claimed.message_id == "high"
    assert claimed.priority == 50


def test_phase119_scheduler_ticks_highest_priority_due_schedule_first(tmp_path: Path):
    clock = _MutableClock(10_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock)
    scheduler.add_schedule(schedule_id="low", thread_id="t", text="low", due_in_ms=0, priority=0)
    scheduler.add_schedule(schedule_id="high", thread_id="t", text="high", due_in_ms=0, priority=80)

    tick = scheduler.tick(limit=1)

    assert tick.enqueued_count == 1
    assert tick.enqueued_messages[0]["message_id"].startswith("scheduled-high-")
    assert queue.inbox_messages()[0].priority == 80


def test_phase119_relative_reminder_compiler_and_worker_schedule(tmp_path: Path):
    clock = _MutableClock(100_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    message = queue.enqueue(thread_id="thread-reminder", text="十分钟后提醒我喝水", message_id="remind-1", priority=5)
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=_UnusedChatRuntime(),
        worker_id="worker-reminder",
        journal=journal,
        scheduler=scheduler,
    )

    result = runtime.run_once()

    schedules = scheduler.list_schedules(include_inactive=True)
    assert result.status == "processed"
    assert result.payload["chat_route"] == "resident_reminder"
    assert queue.inbox_message(message.message_id).status == "completed"
    assert schedules[0].schedule_id == "reminder-remind-1"
    assert schedules[0].text == "提醒：喝水"
    assert schedules[0].priority >= 20
    assert queue.outbox_messages()[0].status == "ready"
    assert journal.records(kind="resident_reminder_compiled")

    clock.advance(600_000)
    tick = scheduler.tick()
    assert tick.enqueued_count == 1
    assert tick.enqueued_messages[0]["text"] == "提醒：喝水"


def test_phase119_resident_human_status_mentions_operational_surfaces(tmp_path: Path, capsys):
    resident_db = tmp_path / "resident.sqlite"
    exit_code = cli.main(["--resident-db", str(resident_db), "resident", "enqueue", "hello", "--priority", "12"])
    assert exit_code == 0
    exit_code = cli.main(
        [
            "--resident-db",
            str(resident_db),
            "resident",
            "--output",
            "human",
            "schedule-add",
            "scheduled hello",
            "--due-in-ms",
            "0",
            "--priority",
            "3",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = cli.main(["--resident-db", str(resident_db), "resident", "--output", "human", "status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "queue" in output
    assert "claimable:" in output
    assert "outbox ready:" in output
    assert "pending input:" in output
    assert "schedules" in output
    assert "due:" in output


def test_phase119_compile_reminder_returns_relative_schedule_directive():
    directive = compile_reminder("in 10 minutes remind me to stretch")

    assert directive is not None
    assert directive.due_in_ms == 600_000
    assert directive.priority >= 20
    assert directive.reminder_text == "提醒：stretch"


class _MutableClock:
    def __init__(self, start: int) -> None:
        self.current = start

    def __call__(self) -> int:
        self.current += 1
        return self.current

    def advance(self, amount_ms: int) -> None:
        self.current += amount_ms


class _UnusedChatRuntime:
    def receive(self, text, *, thread_id=None):
        raise AssertionError("reminder compilation should not call chat runtime")
