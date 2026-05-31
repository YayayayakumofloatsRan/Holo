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
