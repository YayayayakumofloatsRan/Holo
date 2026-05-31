import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.resident import ResidentQueue, ResidentRuntime, ResidentScheduler
from kernel_v3.trace import TraceRenderer


def test_phase76_due_schedule_enqueues_once_and_journals(tmp_path: Path):
    clock = _clock(start=1_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)

    schedule = scheduler.add_schedule(
        schedule_id="sched-once",
        thread_id="resident-scheduled",
        text="scheduled hello",
        due_in_ms=0,
    )
    first = scheduler.tick()
    second = scheduler.tick()

    assert schedule.status == "active"
    assert first.status == "completed"
    assert first.enqueued_count == 1
    assert second.status == "idle"
    assert [message.message_id for message in queue.inbox_messages()] == ["scheduled-sched-once-1001"]
    assert scheduler.list_schedules(include_inactive=True)[0].status == "completed"
    assert [record.kind for record in journal.records() if record.kind.startswith("resident_schedule")] == [
        "resident_schedule_added",
        "resident_schedule_enqueued",
        "resident_schedule_tick",
        "resident_schedule_tick",
    ]
    assert "resident_schedule_enqueued" in TraceRenderer(journal).render_resident_trace()


def test_phase76_recurring_schedule_advances_and_worker_consumes_inbox(tmp_path: Path):
    clock = _clock(start=10_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    scheduler.add_schedule(
        schedule_id="sched-twice",
        thread_id="resident-recurring",
        text="recurring resident work",
        due_in_ms=0,
        interval_ms=1,
        max_runs=2,
    )

    first = scheduler.tick()
    second = scheduler.tick()
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-scheduled",
        journal=journal,
    )
    loop = runtime.run_loop(max_iterations=3)

    assert first.enqueued_count == 1
    assert second.enqueued_count == 1
    assert scheduler.list_schedules(include_inactive=True)[0].status == "completed"
    assert loop.status == "completed"
    assert loop.processed_count == 2
    assert [message.status for message in queue.inbox_messages()] == ["completed", "completed"]
    assert [outbox.in_reply_to for outbox in queue.outbox_messages()] == [
        "scheduled-sched-twice-10001",
        "scheduled-sched-twice-10002",
    ]


def test_phase76_worker_can_tick_schedules_before_claiming_inbox(tmp_path: Path):
    clock = _clock(start=30_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    scheduler.add_schedule(
        schedule_id="sched-worker",
        thread_id="resident-worker-scheduled",
        text="worker should tick this schedule",
        due_in_ms=0,
    )
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-with-scheduler",
        journal=journal,
        scheduler=scheduler,
    )

    result = runtime.run_once()

    assert result.status == "processed"
    assert result.payload["schedule_tick"]["enqueued_count"] == 1
    assert queue.inbox_messages()[0].status == "completed"
    assert queue.outbox_messages()[0].in_reply_to == "scheduled-sched-worker-30001"
    assert [record.kind for record in journal.records() if record.kind.startswith("resident_schedule")] == [
        "resident_schedule_added",
        "resident_schedule_enqueued",
        "resident_schedule_tick",
    ]


def test_phase76_disabled_schedule_does_not_enqueue(tmp_path: Path):
    clock = _clock(start=1_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock)
    scheduler.add_schedule(
        schedule_id="sched-disabled",
        thread_id="resident-disabled",
        text="do not enqueue",
        due_in_ms=0,
    )

    disabled = scheduler.disable_schedule("sched-disabled", reason="test_disabled")
    result = scheduler.tick()

    assert disabled is not None
    assert disabled.status == "disabled"
    assert disabled.metadata["disabled_reason"] == "test_disabled"
    assert result.status == "idle"
    assert not queue.inbox_messages()


def test_phase76_repeating_schedule_requires_interval(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    scheduler = ResidentScheduler(queue=queue, clock_ms=_clock())

    try:
        scheduler.add_schedule(
            schedule_id="sched-invalid",
            thread_id="resident-invalid",
            text="invalid",
            max_runs=2,
        )
    except ValueError as exc:
        assert "resident_schedule_repeating_requires_positive_interval" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("repeating schedule without interval was accepted")


def test_phase76_cli_schedule_tick_then_run_worker(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert (
        cli.main(
            [
                *base,
                "resident",
                "schedule-add",
                "scheduled cli work",
                "--thread",
                "resident-cli-schedule",
                "--schedule-id",
                "sched-cli",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["schedule"]["schedule_id"] == "sched-cli"

    assert cli.main([*base, "resident", "schedule-tick"]) == 0
    ticked = json.loads(capsys.readouterr().out)
    assert ticked["tick"]["enqueued_count"] == 1

    assert cli.main([*base, "resident", "run", "--worker-id", "worker-cli-schedule", "--max-iterations", "2"]) == 0
    loop = json.loads(capsys.readouterr().out)
    assert loop["processed_count"] == 1
    assert loop["queue_status"]["inbox_counts"]["completed"] == 1

    assert cli.main([*base, "resident", "schedule-list", "--include-inactive"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["schedules"][0]["status"] == "completed"


def test_phase76_cli_run_can_tick_schedules_before_worker_loop(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert (
        cli.main(
            [
                *base,
                "resident",
                "schedule-add",
                "scheduled cli run work",
                "--thread",
                "resident-cli-run-schedule",
                "--schedule-id",
                "sched-cli-run",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        cli.main(
            [
                *base,
                "resident",
                "run",
                "--worker-id",
                "worker-cli-run-schedule",
                "--max-iterations",
                "2",
                "--tick-schedules",
            ]
        )
        == 0
    )
    loop = json.loads(capsys.readouterr().out)

    assert loop["processed_count"] == 1
    assert loop["results"][0]["payload"]["schedule_tick"]["enqueued_count"] == 1
    assert loop["queue_status"]["inbox_counts"]["completed"] == 1


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
