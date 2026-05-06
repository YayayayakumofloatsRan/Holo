from __future__ import annotations

from typing import Any


def expression_budget_summary(self: Any, *, world_state: dict[str, Any]) -> tuple[float, float]:
    expression_signals = dict(world_state.get("expression_calibration_signals", {}))
    reply_budget_fit = self._clamp(self.graph.metric_value(expression_signals.get("reply_budget_fit", 0.56), default=0.56), default=0.56)
    stiffness_risk = self._clamp(self.graph.metric_value(expression_signals.get("stiffness_risk", 0.32), default=0.32), default=0.32)
    return reply_budget_fit, stiffness_risk
