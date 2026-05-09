from __future__ import annotations

from typing import Any

from .contracts import SUBJECT_LOOP_PHASES, SubjectLoopTrace


def assemble_subject_loop(
    *,
    adapter: str,
    channel: str,
    thread_key: str,
    record_requested: bool,
    selected_action: dict[str, Any],
    generation: dict[str, Any],
    outcome: dict[str, Any],
    interface_contract: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(selected_action.get("action_type", "") or "")
    generation_mode = str(generation.get("mode", "") or "")
    generated = bool(str(generation.get("text", "") or "").strip())
    transport_side_effect = bool(outcome.get("wechat_transport_used", False))
    allowed_writes = ["operational_trace"] if bool(record_requested) else []
    outcome_appraisal = {
        "selected_action": action_type,
        "generation_mode": generation_mode,
        "generated": generated,
        "delivery_attempted": transport_side_effect,
        "transport_side_effect": transport_side_effect,
        "appraisal_basis": ["selected_action", "generation", "interface_contract"],
        "quality_signal": "observational_only",
    }
    state_update = {
        "allowed_writes": allowed_writes,
        "operational_storage_only": bool(record_requested),
        "self_memory_write": False,
        "policy_write": False,
        "mind_graph_write": False,
        "second_brain_write": False,
        "reason": "Stage30 closes the loop with bounded operational evidence only.",
    }
    invariants = {
        "phase_order_complete": list(SUBJECT_LOOP_PHASES) == [
            "perception",
            "working_field",
            "attention",
            "inhibition",
            "action_market",
            "generation",
            "outcome_appraisal",
            "state_update",
        ],
        "action_market_before_generation": True,
        "generation_downstream_of_action_market": bool(action_type) and bool(generation_mode),
        "transport_is_interface": interface_contract.get("transport_is_interface") is True,
        "transport_has_no_decision_authority": interface_contract.get("transport_decision_authority") is False,
        "no_transport_side_effect": transport_side_effect is False,
        "no_self_memory_mutation": state_update["self_memory_write"] is False,
        "no_policy_mutation": state_update["policy_write"] is False,
        "no_mind_graph_mutation": state_update["mind_graph_write"] is False,
        "no_second_brain": state_update["second_brain_write"] is False,
        "no_unbounded_loop": True,
    }
    return SubjectLoopTrace(
        adapter=str(adapter or ""),
        channel=str(channel or ""),
        thread_key=str(thread_key or ""),
        invariants=invariants,
        outcome_appraisal=outcome_appraisal,
        state_update=state_update,
    ).to_dict()
