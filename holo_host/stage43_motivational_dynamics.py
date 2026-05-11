from __future__ import annotations

from typing import Any

from .bionic_agent import BionicKernel, BionicTurnRequest
from .bionic_kernel_parts.motivational_dynamics import STAGE43_NAME, compute_motivational_field
from .config import HostConfig


class _Stage43MotivationalMemory:
    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "tier": "stage43-acceptance",
            "memory_route": "stage43_motivational_sim",
            "continuity_summary": "Stage43 is testing a bounded internal motivational field under pressure.",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text", "scene"],
                "grounding_order": ["sim_local_continuity", "query", "motivational_field"],
                "open_questions": ["how pressure changes attention", "which boundary remains stable"],
                "history_reliance": "bounded",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {"action_type": "reply_once", "score": 0.54, "reason": "answer the motivational field probe"},
                {"action_type": "continuity_defense", "score": 0.52, "reason": "hold identity continuity under pressure"},
                {"action_type": "silence", "score": 0.12, "reason": "non-reply is weak for this probe"},
            ],
        }


def _required_field_visible(capsule: dict[str, Any]) -> bool:
    field = dict(capsule.get("motivational_field", {})) if isinstance(capsule.get("motivational_field", {}), dict) else {}
    state = dict(field.get("dynamics_state", {})) if isinstance(field.get("dynamics_state", {}), dict) else {}
    attention = dict(field.get("attention", {})) if isinstance(field.get("attention", {}), dict) else {}
    stochasticity = dict(field.get("stochasticity", {})) if isinstance(field.get("stochasticity", {}), dict) else {}
    return (
        field.get("stage") == STAGE43_NAME
        and field.get("decision_authority") == "action_market_bias_only"
        and bool(attention.get("attention_center", ""))
        and all(key in state for key in ("arousal", "uncertainty", "curiosity", "attachment_pressure"))
        and stochasticity.get("replay_stable") is True
    )


def accept_stage43_payload(
    *,
    config: HostConfig,
    store: Any,
    runner: Any | None = None,
    stage42_payload: dict[str, Any] | None = None,
    thread_key: str = "cli:TestUser",
    chat_name: str = "TestUser",
    channel: str = "cli",
) -> dict[str, Any]:
    memory = _Stage43MotivationalMemory()
    kernel = BionicKernel(config=config, memory=memory, runner=None, store=None)
    query = "I am impatient; keep the same subject and say which boundary remains stable."
    first = kernel.run_request(
        BionicTurnRequest(
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            adapter="cli",
            record=False,
        )
    )
    second = kernel.run_request(
        BionicTurnRequest(
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            adapter="cli",
            record=False,
        )
    )
    capsule = dict(first.get("capsule", {}))
    field = dict(capsule.get("motivational_field", {})) if isinstance(capsule.get("motivational_field", {}), dict) else {}
    second_field = (
        dict(dict(second.get("capsule", {})).get("motivational_field", {}))
        if isinstance(dict(second.get("capsule", {})).get("motivational_field", {}), dict)
        else {}
    )
    stochasticity = dict(field.get("stochasticity", {})) if isinstance(field.get("stochasticity", {}), dict) else {}
    deltas = [
        abs(float(item.get("motivation_delta", 0.0) or 0.0))
        for item in capsule.get("action_market", [])
        if isinstance(item, dict)
    ]
    phase_names = [str(item.get("name", "") or "") for item in capsule.get("phases", []) if isinstance(item, dict)]
    subject_loop = dict(capsule.get("subject_loop", {})) if isinstance(capsule.get("subject_loop", {}), dict) else {}
    state_update = dict(subject_loop.get("state_update", {})) if isinstance(subject_loop.get("state_update", {}), dict) else {}
    checks = {
        "stage42_gate_passed": bool(dict(stage42_payload or {}).get("ok", False)),
        "motivational_field_visible": _required_field_visible(capsule),
        "motivational_field_replay_stable": field == second_field,
        "bounded_stochasticity": abs(float(stochasticity.get("bounded_noise", 1.0) or 1.0)) <= 0.03,
        "bounded_action_delta": max(deltas) <= 0.08 if deltas else False,
        "action_market_bias_only": field.get("decision_authority") == "action_market_bias_only",
        "phase_order_preserved": phase_names == ["perception", "working_field", "attention", "inhibition", "action_market", "generation", "outcome"],
        "no_wechat_transport_start": dict(capsule.get("interface_contract", {})).get("wechat_transport_used") is False,
        "no_self_memory_write": state_update.get("self_memory_write") is False,
        "no_second_brain": dict(field.get("contracts", {})).get("no_second_brain") is True,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE43_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage42": dict(stage42_payload or {}),
        "motivational_field": field,
        "capsule": capsule,
        "hard_boundaries": {
            "no_wechat_transport_start": True,
            "no_self_memory_write": True,
            "no_second_brain": True,
            "no_unbounded_loop": True,
            "action_market_first": True,
        },
    }


__all__ = [
    "STAGE43_NAME",
    "accept_stage43_payload",
    "compute_motivational_field",
]
