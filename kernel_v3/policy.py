from __future__ import annotations

from kernel_v3.contracts import CandidateAction, PolicyDecision


class PolicyGate:
    def __init__(self, *, permission: str = "read_write") -> None:
        self.permission = permission

    def validate(self, *, run_id: str, action: CandidateAction) -> PolicyDecision:
        blocked = self.permission == "read_only" and action.side_effect_class == "destructive"
        return PolicyDecision(
            decision_id=f"policy-{run_id}-{action.action_id}",
            run_id=run_id,
            action_id=action.action_id,
            allowed=not blocked,
            reason="blocked_destructive_action_in_read_only_mode" if blocked else "allowed",
            constraints={"permission": self.permission, "side_effect_class": action.side_effect_class},
        )
