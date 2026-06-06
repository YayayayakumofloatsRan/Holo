import os
from pathlib import Path

import pytest

from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.processors import DeepSeekProvider, ProcessorFabric, deepseek_v4_router
from kernel_v3.resident import ResidentQueue, ResidentRuntime, ResidentScheduler


def test_phase119_live_time_and_resident_scheduler_smoke(tmp_path: Path):
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live resident smoke")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live resident smoke")

    clock = _MutableClock(1_000_000)
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=True)},
        router=deepseek_v4_router(profile="fast", thinking="disabled", reasoning_effort="medium"),
        journal=journal,
    )
    agent = AgentRuntime(journal=journal, processor_fabric=fabric)

    time_result = agent.run("现在是几点？请使用系统时钟回答。", mode="auto", semantic_mode="model")
    assert time_result.status == "completed"
    assert time_result.mode == "system_answer"
    assert any(record.data.get("name") == "system.time" for record in journal.records(task_id=time_result.task_id, kind="action"))
    assert any(
        record.data.get("kind") == "system_time"
        for record in journal.records(task_id=time_result.task_id, kind="observation")
    )

    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=clock)
    scheduler = ResidentScheduler(queue=queue, clock_ms=clock, journal=journal)
    queue.enqueue(thread_id="live-resident", text="十分钟后提醒我检查后台任务", message_id="reminder-live", priority=10)
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=_NoChatRuntime(),
        worker_id="live-worker",
        journal=journal,
        scheduler=scheduler,
    )

    reminder = runtime.run_once()
    assert reminder.status == "processed"
    assert reminder.payload["chat_route"] == "resident_reminder"
    assert scheduler.list_schedules()[0].priority >= 20

    queue.enqueue(thread_id="live-resident", text="low priority background", message_id="low", priority=0)
    queue.enqueue(thread_id="live-resident", text="high priority background", message_id="high", priority=90)
    queue.cancel("low", reason="live_smoke_cancel")
    queue.acquire_lease(worker_id="claim-worker", ttl_ms=30_000)
    claimed = queue.claim_next(worker_id="claim-worker")
    assert claimed is not None
    assert claimed.message_id == "high"

    scheduler.add_schedule(
        schedule_id="repeat-live",
        thread_id="live-resident",
        text="重复定时任务 smoke",
        due_in_ms=0,
        interval_ms=1,
        max_runs=2,
        priority=30,
    )
    first_tick = scheduler.tick(limit=1)
    second_tick = scheduler.tick(limit=1)
    assert first_tick.enqueued_count == 1
    assert second_tick.enqueued_count == 1


class _MutableClock:
    def __init__(self, start: int) -> None:
        self.current = start

    def __call__(self) -> int:
        self.current += 1
        return self.current


class _NoChatRuntime:
    def receive(self, text, *, thread_id=None):
        raise AssertionError("live resident smoke should stay in host scheduler paths")
