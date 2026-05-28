from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def short_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@dataclass(slots=True)
class Event:
    kind: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: short_id("evt"))
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Observation:
    tool: str
    status: str
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=lambda: short_id("obs"))
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Decision:
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    can_answer: bool = False
    required_observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentResult:
    final: str
    status: str
    stop_reason: str
    events: list[Event] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final": self.final,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "events": [event.to_dict() for event in self.events],
            "observations": [obs.to_dict() for obs in self.observations],
            "metadata": dict(self.metadata),
        }

