from __future__ import annotations

from typing import Protocol

from kernel_v3.contracts import ContextBundle, Feedback, Observation
from kernel_v3.processors.adapters import ModelEvaluator


class Evaluator(Protocol):
    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        ...


__all__ = ["Evaluator", "ModelEvaluator"]
