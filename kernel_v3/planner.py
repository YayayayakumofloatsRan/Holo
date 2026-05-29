from __future__ import annotations

from typing import Protocol

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback
from kernel_v3.processors.adapters import ModelPlanner


class Planner(Protocol):
    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        ...


__all__ = ["Planner", "ModelPlanner"]
