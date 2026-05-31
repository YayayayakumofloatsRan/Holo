from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class InboundMessage(Contract):
    message_id: str
    thread_id: str
    text: str
    source: str
    status: str
    created_at_ms: int
    lease_owner: str | None
    lease_until_ms: int | None
    attempts: int
    next_attempt_at_ms: int | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class OutboxMessage(Contract):
    outbox_id: str
    in_reply_to: str
    thread_id: str
    text: str
    status: str
    created_at_ms: int
    task_id: str | None
    run_id: str | None
    payload: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class WorkerLease(Contract):
    lease_id: str
    worker_id: str
    acquired_at_ms: int
    expires_at_ms: int
    status: str


@dataclass(frozen=True, kw_only=True)
class ResidentQueueStatus(Contract):
    generated_at_ms: int
    db_path: str
    inbox_counts: dict[str, int]
    outbox_counts: dict[str, int]
    active_lease: JsonObject | None
    claimable_count: int
    stale_running_count: int
    due_retry_count: int
    dead_letter_count: int
    ready_outbox_count: int


@dataclass(frozen=True, kw_only=True)
class ResidentQueueInspection(Contract):
    status: str
    generated_at_ms: int
    issues: list[JsonObject]
    recommended_actions: list[str]
    queue_status: JsonObject
    samples: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResidentRunResult(Contract):
    status: str
    worker_id: str
    message_id: str | None
    outbox_id: str | None
    reason: str | None
    payload: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResidentLoopResult(Contract):
    status: str
    worker_id: str
    iterations: int
    processed_count: int
    failed_count: int
    blocked_count: int
    idle_count: int
    reason: str | None
    results: list[JsonObject] = field(default_factory=list)
    queue_status: JsonObject = field(default_factory=dict)
    schedule_status: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResidentSchedule(Contract):
    schedule_id: str
    thread_id: str
    text: str
    source: str
    status: str
    created_at_ms: int
    next_due_at_ms: int | None
    interval_ms: int | None
    max_runs: int | None
    run_count: int
    last_enqueued_at_ms: int | None
    last_message_id: str | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResidentScheduleTickResult(Contract):
    status: str
    generated_at_ms: int
    due_count: int
    enqueued_count: int
    skipped_count: int
    failed_count: int
    schedules: list[JsonObject] = field(default_factory=list)
    enqueued_messages: list[JsonObject] = field(default_factory=list)
    failures: list[JsonObject] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class ResidentScheduleStatus(Contract):
    generated_at_ms: int
    db_path: str
    schedule_counts: dict[str, int]
    active_count: int
    due_count: int
    recurring_count: int
    unbounded_count: int
    next_due_at_ms: int | None


@dataclass(frozen=True, kw_only=True)
class ResidentScheduleInspection(Contract):
    status: str
    generated_at_ms: int
    issues: list[JsonObject]
    recommended_actions: list[str]
    schedule_status: JsonObject
    samples: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResidentDoctorReport(Contract):
    status: str
    generated_at_ms: int
    configured: JsonObject
    issues: list[JsonObject]
    recommended_actions: list[str]
    queue_inspection: JsonObject
    schedule_inspection: JsonObject
    memory_inspection: JsonObject | None
    corpus_inspection: JsonObject | None
