from __future__ import annotations

from kernel_v3.deep_loop import DeepAgentLoopController, ModelAssistantTurnPlanner


class MatureSingleAgentLoopController(DeepAgentLoopController):
    """Reference-style single-agent loop boundary for Kernel v3.

    This controller intentionally exposes the mature loop semantics used by the
    live runtime: full model-visible tool surface, tool results/errors returned
    as observations, bounded provider tool-result continuation, and host guards
    represented as recoverable feedback where possible.
    """

    runtime_backend = "mature_single_agent_loop"


__all__ = ["MatureSingleAgentLoopController", "ModelAssistantTurnPlanner"]
