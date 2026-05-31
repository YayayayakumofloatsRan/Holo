import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.resident import ResidentQueue, ResidentRuntime, ResidentScheduler
from kernel_v3.resident.scheduler import (
    RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP,
    RESIDENT_SCHEDULE_TICK_LIMIT_CAP,
)
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


def test_phase76_schedule_journal_and_inspection_use_manifests(tmp_path: Path):
    clock = _clock(start=2_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    marker = "RAW_SCHEDULE_MARKER_SHOULD_NOT_APPEAR"
    text = ("scheduled-manifest-" * 20) + marker
    scheduler.add_schedule(
        schedule_id="sched-manifest",
        thread_id="resident-scheduled",
        text=text,
        due_in_ms=0,
        metadata={"operator_note": marker},
    )

    scheduler.tick()
    inspection = scheduler.inspect(sample_limit=1)
    schedule_records = [record.data for record in journal.records() if record.kind.startswith("resident_schedule")]
    serialized_records = json.dumps(schedule_records, ensure_ascii=False)
    serialized_samples = json.dumps(inspection.samples, ensure_ascii=False)

    assert marker not in serialized_records
    assert marker not in serialized_samples
    added = journal.records(kind="resident_schedule_added")[-1].data
    enqueued = journal.records(kind="resident_schedule_enqueued")[-1].data
    tick = journal.records(kind="resident_schedule_tick")[-1].data
    sample = inspection.samples["schedules"][0]
    assert added["text_length"] == len(text)
    assert added["redaction"] == {"text": "preview_hash_only", "metadata": "manifest_only"}
    assert enqueued["schedule"]["text_length"] == len(text)
    assert enqueued["message"]["text_length"] == len(text)
    assert tick["schedules"][0]["text_length"] == len(text)
    assert tick["enqueued_messages"][0]["text_length"] == len(text)
    assert sample["text_length"] == len(text)
    assert sample["redaction"] == {"text": "preview_hash_only", "metadata": "manifest_only"}


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
    marker = "RAW_WORKER_SCHEDULE_MARKER_SHOULD_NOT_APPEAR"
    text = ("worker-schedule-" * 20) + marker
    scheduler.add_schedule(
        schedule_id="sched-worker",
        thread_id="resident-worker-scheduled",
        text=text,
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
    assert marker not in json.dumps(result.payload["schedule_tick"], ensure_ascii=False)
    assert queue.inbox_messages()[0].status == "completed"
    assert queue.outbox_messages()[0].in_reply_to == "scheduled-sched-worker-30001"
    loop_records = journal.records(kind="resident_loop_result")
    if loop_records:
        assert marker not in json.dumps(loop_records[-1].data, ensure_ascii=False)
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


def test_phase76_scheduler_status_and_inspect_report_due_and_unbounded(tmp_path: Path):
    clock = _clock(start=5_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock)
    scheduler.add_schedule(
        schedule_id="sched-visible",
        thread_id="resident-visible",
        text="visible due schedule",
        due_in_ms=0,
        interval_ms=10,
        max_runs=None,
    )

    status = scheduler.status()
    inspection = scheduler.inspect(sample_limit=1)

    assert status.active_count == 1
    assert status.due_count == 1
    assert status.recurring_count == 1
    assert status.unbounded_count == 1
    assert inspection.status == "attention"
    assert [issue["code"] for issue in inspection.issues] == [
        "due_schedules",
        "unbounded_recurring_schedules",
    ]
    assert "resident run --tick-schedules --max-iterations <n>" in inspection.recommended_actions


def test_phase76_scheduler_tick_and_inspection_limits_are_bounded(tmp_path: Path):
    clock = _clock(start=90_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock)
    for index in range(RESIDENT_SCHEDULE_TICK_LIMIT_CAP + 5):
        scheduler.add_schedule(
            schedule_id=f"sched-bounded-{index}",
            thread_id="resident-bounded",
            text=f"bounded scheduled work {index}",
            due_at_ms=0,
        )

    requested_tick_limit = RESIDENT_SCHEDULE_TICK_LIMIT_CAP + 99
    tick = scheduler.tick(limit=requested_tick_limit)

    assert tick.status == "completed"
    assert tick.due_count == RESIDENT_SCHEDULE_TICK_LIMIT_CAP
    assert tick.enqueued_count == RESIDENT_SCHEDULE_TICK_LIMIT_CAP
    assert len(queue.inbox_messages()) == RESIDENT_SCHEDULE_TICK_LIMIT_CAP
    assert tick.diagnostics["limit"] == RESIDENT_SCHEDULE_TICK_LIMIT_CAP
    assert tick.diagnostics["requested_limit"] == requested_tick_limit
    assert tick.diagnostics["limit_cap"] == RESIDENT_SCHEDULE_TICK_LIMIT_CAP
    assert tick.diagnostics["limit_clamped"] is True

    requested_sample_limit = RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP + 99
    inspection = scheduler.inspect(sample_limit=requested_sample_limit)

    assert len(inspection.samples["schedules"]) == RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP
    assert inspection.samples["requested_sample_limit"] == requested_sample_limit
    assert inspection.samples["sample_limit"] == RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP
    assert inspection.samples["sample_limit_cap"] == RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP
    assert inspection.samples["sample_limit_clamped"] is True


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


def test_phase76_run_loop_reports_waiting_for_future_schedule(tmp_path: Path):
    clock = _clock(start=70_000)
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    journal = JournalStore.in_memory()
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    scheduler.add_schedule(
        schedule_id="sched-future",
        thread_id="resident-future",
        text="future resident work",
        due_in_ms=100,
    )

    loop = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-waiting-schedule",
        journal=journal,
        scheduler=scheduler,
    ).run_loop(max_iterations=2)

    assert loop.status == "waiting_for_schedule"
    assert loop.reason == "next_schedule_pending"
    assert loop.idle_count == 1
    assert loop.schedule_status["active_count"] == 1
    assert loop.schedule_status["next_due_at_ms"] == 70101
    assert not queue.inbox_messages()


def test_phase76_run_loop_reports_failed_when_schedule_tick_fails(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    scheduler = _FailingTickScheduler()

    loop = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-schedule-tick-failure",
        journal=journal,
        scheduler=scheduler,
    ).run_loop(max_iterations=1)

    assert loop.status == "failed"
    assert loop.reason == "resident_schedule_tick_failed"
    assert loop.results[0]["status"] == "idle"
    assert loop.results[0]["payload"]["schedule_tick"]["status"] == "failed"
    assert journal.records(kind="resident_schedule_tick_failed")
    assert journal.records(kind="resident_loop_result")[-1].data["status"] == "failed"


def test_phase76_run_loop_reports_failed_when_schedule_status_fails(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    scheduler = _FailingStatusScheduler()

    loop = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-schedule-status-failure",
        journal=journal,
        scheduler=scheduler,
    ).run_loop(max_iterations=1)

    assert loop.status == "failed"
    assert loop.reason == "resident_schedule_status_failed"
    assert loop.schedule_status == {"status": "failed", "reason": "RuntimeError"}


def test_phase76_cli_run_reports_schedule_status_when_waiting(tmp_path: Path, capsys):
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
                "future cli resident work",
                "--thread",
                "resident-cli-future",
                "--schedule-id",
                "sched-cli-future",
                "--due-at-ms",
                "999999999999",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main([*base, "resident", "run", "--tick-schedules", "--max-iterations", "2"]) == 0
    loop = json.loads(capsys.readouterr().out)

    assert loop["status"] == "waiting_for_schedule"
    assert loop["reason"] == "next_schedule_pending"
    assert loop["schedule_status"]["active_count"] == 1
    assert loop["schedule_status"]["next_due_at_ms"] == 999999999999


def test_phase76_cli_status_and_inspect_include_schedule_health(tmp_path: Path, capsys):
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
                "unbounded resident work",
                "--thread",
                "resident-cli-health",
                "--schedule-id",
                "sched-health",
                "--due-at-ms",
                "0",
                "--interval-ms",
                "1",
                "--unbounded",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["schedule"]["max_runs"] is None

    assert cli.main([*base, "resident", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["schedules"]["due_count"] == 1
    assert status["schedules"]["unbounded_count"] == 1

    assert cli.main([*base, "resident", "inspect", "--sample-limit", "1"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["status"] == "attention"
    assert inspected["schedule_inspection"]["issues"][0]["code"] == "due_schedules"
    assert (
        "resident run --tick-schedules --max-iterations <n>"
        in inspected["schedule_inspection"]["recommended_actions"]
    )


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick


class _DictResult:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _FailingTickScheduler:
    def tick(self, *, limit: int = 20):
        raise RuntimeError("simulated schedule tick failure")

    def status(self):
        return _DictResult({"active_count": 0, "next_due_at_ms": None})


class _FailingStatusScheduler:
    def tick(self, *, limit: int = 20):
        return _DictResult({"status": "idle", "due_count": 0, "enqueued_count": 0, "failed_count": 0})

    def status(self):
        raise RuntimeError("simulated schedule status failure")
