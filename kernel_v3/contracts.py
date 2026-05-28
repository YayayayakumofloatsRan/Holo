from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Self


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, kw_only=True)
class Contract:
    def to_dict(self) -> JsonObject:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: JsonObject) -> Self:
        if not isinstance(data, dict):
            raise TypeError(f"{cls.__name__}.from_dict expected a dict")

        field_names = {field.name for field in fields(cls)}
        unknown_fields = set(data) - field_names
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"{cls.__name__}.from_dict got unknown fields: {names}")

        missing_fields = field_names - set(data)
        if missing_fields:
            names = ", ".join(sorted(missing_fields))
            raise ValueError(f"{cls.__name__}.from_dict missing fields: {names}")

        return cls(**data)


@dataclass(frozen=True, kw_only=True)
class Event(Contract):
    event_id: str
    run_id: str
    type: str
    timestamp_ms: int
    payload: JsonObject
    source: str


@dataclass(frozen=True, kw_only=True)
class Task(Contract):
    task_id: str
    goal: str
    status: str
    created_at_ms: int
    priority: int
    metadata: JsonObject


@dataclass(frozen=True, kw_only=True)
class Run(Contract):
    run_id: str
    task_id: str
    status: str
    started_at_ms: int
    ended_at_ms: int | None
    metadata: JsonObject


@dataclass(frozen=True, kw_only=True)
class Step(Contract):
    step_id: str
    run_id: str
    index: int
    kind: str
    status: str
    input_ref: str | None
    output_ref: str | None
    error: str | None


@dataclass(frozen=True, kw_only=True)
class ContextBundle(Contract):
    context_id: str
    thread_key: str
    event_ids: list[str]
    memory_refs: list[str]
    state: JsonObject
    token_budget: int


@dataclass(frozen=True, kw_only=True)
class CandidateAction(Contract):
    action_id: str
    kind: str
    name: str | None
    description: str
    score: float
    payload: JsonObject
    reasons: list[str]
    side_effect_class: str = "none"


@dataclass(frozen=True, kw_only=True)
class PolicyDecision(Contract):
    decision_id: str
    run_id: str
    action_id: str
    allowed: bool
    reason: str
    constraints: JsonObject


@dataclass(frozen=True, kw_only=True)
class ToolCall(Contract):
    tool_call_id: str
    run_id: str
    action_id: str
    name: str
    arguments: JsonObject
    status: str


@dataclass(frozen=True, kw_only=True)
class Observation(Contract):
    observation_id: str
    run_id: str
    kind: str
    status: str
    source: str
    content: JsonValue
    observed_at_ms: int
    action_id: str | None
    tool_call_id: str | None


@dataclass(frozen=True, kw_only=True)
class Feedback(Contract):
    feedback_id: str
    run_id: str
    status: str
    stop_reason: str | None
    answer: str | None
    missing_evidence: list[str]


@dataclass(frozen=True, kw_only=True)
class ProcessorRequest(Contract):
    request_id: str
    run_id: str
    processor: str
    prompt: str
    context_id: str
    parameters: JsonObject


@dataclass(frozen=True, kw_only=True)
class ProcessorResult(Contract):
    result_id: str
    request_id: str
    status: str
    output: JsonObject
    usage: JsonObject
    error: str | None


@dataclass(frozen=True, kw_only=True)
class MemoryWriteProposal(Contract):
    proposal_id: str
    run_id: str
    memory_type: str
    key: str
    value: JsonValue
    rationale: str
    confidence: float


@dataclass(frozen=True, kw_only=True)
class LedgerRecord(Contract):
    record_id: str
    task_id: str | None
    run_id: str
    step_id: str | None
    kind: str
    data: JsonObject
    recorded_at_ms: int
    event_ref: str | None
    action_ref: str | None
    observation_ref: str | None
    feedback_ref: str | None
    state_delta: JsonObject
