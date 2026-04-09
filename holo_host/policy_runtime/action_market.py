from __future__ import annotations

from typing import Any

from ..common import compact_text


def apply_simulation_overlay(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    simulation_by_action: dict[str, dict[str, Any]],
    world_thread: dict[str, Any],
) -> list[dict[str, Any]]:
    updated_market: list[dict[str, Any]] = []
    for candidate in action_market:
        annotated = dict(candidate)
        action_type = str(annotated.get("action_type", "") or "")
        simulation = dict(simulation_by_action.get(action_type, {}))
        rerank_delta = float(simulation.get("recommended_bias", 0.0) or 0.0)
        annotated["world_rationale"] = compact_text(
            f"reply_fit={float(world_thread.get('reply_fit', 0.0) or 0.0):.3f} risk={float(world_thread.get('risk_level', 0.0) or 0.0):.3f} opportunity={float(world_thread.get('opportunity_level', 0.0) or 0.0):.3f}",
            160,
        )
        annotated["simulation_rationale"] = str(simulation.get("simulation_rationale", "") or "")
        annotated["predicted_outcome"] = simulation
        annotated["rerank_delta"] = round(rerank_delta, 4)
        annotated["empirical_overlay_delta"] = round(float(simulation.get("empirical_overlay_delta", 0.0) or 0.0), 4)
        annotated["empirical_calibration"] = dict(simulation.get("empirical_calibration", {}))
        annotated["calibration_bucket"] = dict(simulation.get("calibration_bucket", {}))
        annotated["calibration_confidence"] = round(float(simulation.get("calibration_confidence", 0.0) or 0.0), 4)
        annotated["score"] = round(float(annotated.get("score", 0.0) or 0.0) + rerank_delta, 4)
        updated_market.append(annotated)
    return sorted(updated_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
