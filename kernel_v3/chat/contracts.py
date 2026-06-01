from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class ChatThread(Contract):
    thread_id: str
    active_task_id: str | None
    status: str
    turn_count: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ChatTurn(Contract):
    turn_id: str
    thread_id: str
    role: str
    text: str
    task_id: str | None
    run_id: str | None
    linked_turn_id: str | None
    created_at_ms: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class PendingUserInput(Contract):
    pending_id: str
    thread_id: str
    task_id: str
    run_id: str
    question: str
    source_ref: str | None
    created_at_ms: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ThreadState(Contract):
    thread_id: str
    active_task_id: str | None
    pending_question: JsonObject | None
    recent_turn_refs: list[str]
    recent_task_refs: list[str]
    last_result_status: str | None
    thread_summary_ref: str | None


@dataclass(frozen=True, kw_only=True)
class ThreadSummary(Contract):
    summary_id: str
    thread_id: str
    active_task_id: str | None
    pending_question: JsonObject | None
    last_result_status: str | None
    last_answer_preview: str | None
    last_failure_reason: str | None
    recent_turns: list[JsonObject]
    recent_task_refs: list[str]


@dataclass(frozen=True, kw_only=True)
class TurnRoutingDecision(Contract):
    decision_id: str
    thread_id: str
    turn_id: str
    route: str
    task_id: str | None
    command: str | None
    reasons: list[str]


@dataclass(frozen=True, kw_only=True)
class TurnRouteProposal(Contract):
    route: str
    command: str | None
    target_task_id: str | None
    confidence: float
    reasons: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ChatCommand(Contract):
    command_id: str
    thread_id: str
    turn_id: str
    name: str
    args: list[str]
    status: str
    result: JsonObject


@dataclass(frozen=True, kw_only=True)
class ChatRuntimeResult(Contract):
    status: str
    thread_id: str
    turn_id: str
    route: str
    task_id: str | None
    run_id: str | None
    answer: str | None
    final_answer: JsonObject | None
    failure_report: JsonObject | None
    pending_question: JsonObject | None
    command_result: JsonObject | None
    summary: JsonObject | None
    trace_refs: list[str]
