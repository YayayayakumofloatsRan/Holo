from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_WRITE_TYPES = {"operational_trace"}
FORBIDDEN_WRITE_TYPES = {"self_memory", "policy", "mind_graph", "transport", "scheduler", "second_brain"}


@dataclass(frozen=True, slots=True)
class StateUpdateProposal:
    write_type: str
    target: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)
    bounded: bool = True
    rollback_supported: bool = True


@dataclass(frozen=True, slots=True)
class StateUpdateDecision:
    allowed_writes: list[str]
    rejected_writes: list[str]
    rejection_reasons: dict[str, str]
    operational_storage_only: bool
    rollback_supported: bool
    self_memory_write: bool = False
    policy_write: bool = False
    mind_graph_write: bool = False
    second_brain_write: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": "controlled_state_update_gate",
            "allowed_writes": list(self.allowed_writes),
            "rejected_writes": list(self.rejected_writes),
            "rejection_reasons": dict(self.rejection_reasons),
            "operational_storage_only": self.operational_storage_only,
            "rollback_supported": self.rollback_supported,
            "self_memory_write": self.self_memory_write,
            "policy_write": self.policy_write,
            "mind_graph_write": self.mind_graph_write,
            "second_brain_write": self.second_brain_write,
            "reason": "Only bounded operational trace writes are enabled in the offline subject-loop path.",
        }


class ControlledStateUpdateGate:
    def evaluate(
        self,
        *,
        record_requested: bool,
        proposals: list[StateUpdateProposal] | None = None,
    ) -> StateUpdateDecision:
        candidates = list(proposals or [])
        if record_requested:
            candidates.insert(
                0,
                StateUpdateProposal(
                    write_type="operational_trace",
                    target="queue_store.bionic_agent_traces",
                    reason="record requested for offline bionic capsule review",
                    payload={},
                ),
            )
        allowed: list[str] = []
        rejected: list[str] = []
        rejection_reasons: dict[str, str] = {}
        rollback_supported = True
        for proposal in candidates:
            write_type = str(proposal.write_type or "").strip()
            rollback_supported = rollback_supported and bool(proposal.rollback_supported)
            if write_type in ALLOWED_WRITE_TYPES and proposal.bounded:
                if write_type not in allowed:
                    allowed.append(write_type)
                continue
            rejected.append(write_type)
            if write_type in FORBIDDEN_WRITE_TYPES:
                rejection_reasons[write_type] = f"{write_type} writes are not allowed from the offline subject loop"
            elif not proposal.bounded:
                rejection_reasons[write_type] = "unbounded write proposal rejected"
            else:
                rejection_reasons[write_type] = "write type is not registered for the offline subject loop"
        return StateUpdateDecision(
            allowed_writes=allowed,
            rejected_writes=rejected,
            rejection_reasons=rejection_reasons,
            operational_storage_only=bool(allowed) and all(item == "operational_trace" for item in allowed),
            rollback_supported=rollback_supported,
            self_memory_write=False,
            policy_write=False,
            mind_graph_write=False,
            second_brain_write=False,
        )


controlled_state_update_gate = ControlledStateUpdateGate()
