from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class StateMetric:
    value: float
    confidence: float = 0.58
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    updated_at: str = ""
    updated_by: str = ""
    decay_policy: str = "event_weighted"


@dataclass(slots=True, frozen=True)
class OutcomeAppraisalInput:
    channel: str
    thread_key: str
    chat_name: str
    action_type: str
    action_ref: str
    was_rewarding: float
    was_ignored: float
    relational_delta: float
    identity_delta: float
    future_initiative_bias: float
    future_resistance_bias: float
