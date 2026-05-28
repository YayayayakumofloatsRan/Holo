from __future__ import annotations

from typing import Protocol

from kernel_v3.contracts import ContextBundle, Feedback, Observation


class Evaluator(Protocol):
    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        ...
