from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..common import utc_now


STAGE29_NAME = "stage29-bionic-subject-kernel"
KERNEL_NAME = "bionic_subject_kernel"
CAPSULE_PHASES = (
    "perception",
    "working_field",
    "attention",
    "inhibition",
    "action_market",
    "generation",
    "outcome",
)
SPEECH_ACTIONS = {"reply_once", "reply_multi", "push_back", "continuity_defense"}


@dataclass(slots=True)
class BionicTurnRequest:
    query: str
    thread_key: str
    chat_name: str
    channel: str = "cli"
    adapter: str = "cli"
    record: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BionicPhase:
    name: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class BionicCapsule:
    stage: str
    kernel: str
    adapter: str
    query: str
    channel: str
    thread_key: str
    chat_name: str
    phases: list[BionicPhase]
    perception: dict[str, Any]
    working_field: dict[str, Any]
    attention: dict[str, Any]
    inhibition: dict[str, Any]
    action_market: list[dict[str, Any]]
    selected_action: dict[str, Any]
    generation: dict[str, Any]
    outcome: dict[str, Any]
    metrics: dict[str, Any]
    interface_contract: dict[str, Any]
    subject_loop: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "kernel": self.kernel,
            "adapter": self.adapter,
            "query": self.query,
            "channel": self.channel,
            "thread_key": self.thread_key,
            "chat_name": self.chat_name,
            "phases": [phase.to_dict() for phase in self.phases],
            "perception": dict(self.perception),
            "working_field": dict(self.working_field),
            "attention": dict(self.attention),
            "inhibition": dict(self.inhibition),
            "action_market": [dict(item) for item in self.action_market],
            "selected_action": dict(self.selected_action),
            "generation": dict(self.generation),
            "outcome": dict(self.outcome),
            "metrics": dict(self.metrics),
            "interface_contract": dict(self.interface_contract),
            "subject_loop": dict(self.subject_loop),
            "created_at": self.created_at,
        }
