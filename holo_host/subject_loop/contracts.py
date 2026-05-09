from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STAGE30_NAME = "stage30-unified-subject-loop"
SUBJECT_LOOP_NAME = "unified_bionic_subject_loop"
SUBJECT_LOOP_PHASES = (
    "perception",
    "working_field",
    "attention",
    "inhibition",
    "action_market",
    "generation",
    "outcome_appraisal",
    "state_update",
)


@dataclass(slots=True)
class SubjectLoopTrace:
    stage: str = STAGE30_NAME
    loop_name: str = SUBJECT_LOOP_NAME
    phase_order: list[str] = field(default_factory=lambda: list(SUBJECT_LOOP_PHASES))
    adapter: str = ""
    channel: str = ""
    thread_key: str = ""
    invariants: dict[str, bool] = field(default_factory=dict)
    outcome_appraisal: dict[str, Any] = field(default_factory=dict)
    state_update: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "loop_name": self.loop_name,
            "phase_order": list(self.phase_order),
            "phase_count": len(self.phase_order),
            "adapter": self.adapter,
            "channel": self.channel,
            "thread_key": self.thread_key,
            "invariants": dict(self.invariants),
            "outcome_appraisal": dict(self.outcome_appraisal),
            "state_update": dict(self.state_update),
        }
