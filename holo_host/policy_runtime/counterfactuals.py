from __future__ import annotations

from typing import Any


def fast_counterfactual_set(
    self: Any,
    *,
    action_market: list[dict[str, Any]],
    query: str,
    intent_state: dict[str, Any],
    relationship_state: dict[str, Any],
    game_state: dict[str, Any],
    affect_state: dict[str, Any],
    drive_state: dict[str, Any],
    value_state: dict[str, Any],
    conflict_state: dict[str, Any],
    world_state: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    simulations: list[dict[str, Any]] = []
    for candidate in list(action_market)[:3]:
        simulation = self._simulate_action_candidate(
            action=dict(candidate),
            query=query,
            intent_state=intent_state,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            world_state=world_state,
            context=context,
        )
        simulations.append(simulation)
    return simulations
