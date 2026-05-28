from __future__ import annotations

from typing import Protocol

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback


class Planner(Protocol):
    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        ...
