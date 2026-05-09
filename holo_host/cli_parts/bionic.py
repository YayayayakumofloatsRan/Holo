from __future__ import annotations

import json

from ..adapter_registry import adapter_registry
from ..bionic_agent import BionicKernel, BionicTurnRequest, KERNEL_NAME, STAGE29_NAME, STAGE30_NAME, SUBJECT_LOOP_PHASES
from ..config import load_config
from ..reply_api import HoloReplyService
from ..store import QueueStore


STAGE31_NAME = "stage31-debt-burndown"


def close_reply_service(service: HoloReplyService) -> None:
    service.store.close()
    if hasattr(service.memory, "activation"):
        service.memory.activation.close()
    if hasattr(service.memory, "graph"):
        service.memory.graph.close()


def bionic_agent_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    record: bool,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    runner = None if offline else service.runner
    try:
        kernel = BionicKernel(config=config, store=service.store, memory=service.memory, runner=runner)
        return kernel.run_request(
            BionicTurnRequest(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                adapter="cli",
                record=record,
            )
        ), "local_process"
    finally:
        close_reply_service(service)


def bionic_trace_payload(config_path: str | None, *, trace_id: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        rows = store.list_bionic_agent_traces(limit=1, trace_id=trace_id)
        if not rows:
            return {"ok": False, "stage": STAGE29_NAME, "trace_id": trace_id, "error": "trace_not_found"}, "local_process"
        row = dict(rows[0])
        try:
            row["capsule"] = json.loads(str(row.get("capsule_json", "{}") or "{}"))
        except json.JSONDecodeError:
            row["capsule"] = {}
        try:
            row["metrics"] = json.loads(str(row.get("metrics_json", "{}") or "{}"))
        except json.JSONDecodeError:
            row["metrics"] = {}
        return {"ok": True, "stage": STAGE29_NAME, "trace": row}, "local_process"
    finally:
        store.close()


def bionic_metrics_payload(config_path: str | None, *, limit: int = 100) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return store.latest_bionic_metrics(limit=limit), "local_process"
    finally:
        store.close()


def subject_loop_trace_payload(config_path: str | None, *, trace_id: int) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return store.trace_subject_loop(trace_id=trace_id), "local_process"
    finally:
        store.close()


def subject_loop_metrics_payload(config_path: str | None, *, limit: int = 100) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        return store.latest_subject_loop_metrics(limit=limit), "local_process"
    finally:
        store.close()


def export_bionic_trace_payload(config_path: str | None, *, trace_id: int, output: str) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        kernel = BionicKernel(config=config, store=store)
        return kernel.export_trace(trace_id=trace_id, output=output), "local_process"
    finally:
        store.close()


def accept_stage29_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    before_metrics = service.store.latest_bionic_metrics()
    provider_status = service.provider_status()
    agent = BionicKernel(config=config, store=service.store, memory=service.memory, runner=None)
    try:
        turn = agent.run_turn(
            query="accept stage29 bounded bionic cli turn",
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            record=True,
        )
        synthetic_wechat = agent.run_request(
            BionicTurnRequest(
                query="accept stage29 synthetic wechat adapter turn",
                thread_key="wechat:Stage29Accept",
                chat_name="Stage29Accept",
                channel="wechat",
                adapter="wechat",
                record=False,
            )
        )
        trace_id = int(turn.get("trace_id", 0) or 0)
        trace_rows = service.store.list_bionic_agent_traces(limit=1, trace_id=trace_id)
        after_metrics = service.store.latest_bionic_metrics()
    finally:
        close_reply_service(service)
    capsule = dict(turn.get("capsule", {}))
    wechat_capsule = dict(synthetic_wechat.get("capsule", {}))
    phase_names = [str(phase.get("name", "") or "") for phase in list(capsule.get("phases", []))]
    interface_contract = dict(capsule.get("interface_contract", {}))
    wechat_interface_contract = dict(wechat_capsule.get("interface_contract", {}))
    checks = {
        "stage28_available": bool(dict(capsule.get("perception", {})).get("stage28", {}).get("situational_field_visible", False)),
        "deepseek_provider_visible": "deepseek" in dict(provider_status.get("providers", {})),
        "kernel_first_contract": capsule.get("kernel") == KERNEL_NAME and wechat_capsule.get("kernel") == KERNEL_NAME,
        "adapter_provenance_visible": capsule.get("adapter") == str(channel or "cli").strip() and wechat_capsule.get("adapter") == "wechat",
        "transport_interface_only": (
            interface_contract.get("transport_is_interface") is True
            and interface_contract.get("transport_decision_authority") is False
            and wechat_interface_contract.get("transport_is_interface") is True
            and wechat_interface_contract.get("transport_decision_authority") is False
        ),
        "synthetic_wechat_uses_same_kernel": (
            wechat_capsule.get("channel") == "wechat"
            and dict(wechat_capsule.get("outcome", {})).get("wechat_transport_used") is False
        ),
        "full_capsule_phases": phase_names == [
            "perception",
            "working_field",
            "attention",
            "inhibition",
            "action_market",
            "generation",
            "outcome",
        ],
        "trace_persistence_works": trace_id > 0 and len(trace_rows) == 1,
        "metrics_visible": int(after_metrics.get("trace_count", 0) or 0) >= int(before_metrics.get("trace_count", 0) or 0) + 1,
        "wechat_transport_not_required": bool(dict(capsule.get("outcome", {})).get("wechat_transport_used") is False),
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE29_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "trace_id": trace_id,
        "metrics": after_metrics,
        "provider_status": provider_status,
        "capsule": capsule,
        "synthetic_wechat_capsule": wechat_capsule,
    }, "local_process"


def accept_stage30_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage29_payload, transport = accept_stage29_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    capsule = dict(stage29_payload.get("capsule", {}))
    synthetic_capsule = dict(stage29_payload.get("synthetic_wechat_capsule", {}))
    subject_loop = dict(capsule.get("subject_loop", {}))
    synthetic_subject_loop = dict(synthetic_capsule.get("subject_loop", {}))
    invariants = dict(subject_loop.get("invariants", {}))
    synthetic_invariants = dict(synthetic_subject_loop.get("invariants", {}))
    state_update = dict(subject_loop.get("state_update", {}))
    checks = {
        "stage29_gate_passed": bool(stage29_payload.get("ok", False)),
        "subject_loop_visible": subject_loop.get("stage") == STAGE30_NAME,
        "phase_order_complete": list(subject_loop.get("phase_order", [])) == list(SUBJECT_LOOP_PHASES),
        "hard_invariants_pass": bool(invariants) and all(bool(value) for value in invariants.values()),
        "synthetic_wechat_loop_adapter_only": (
            synthetic_subject_loop.get("stage") == STAGE30_NAME
            and synthetic_subject_loop.get("adapter") == "wechat"
            and all(bool(value) for value in synthetic_invariants.values())
        ),
        "state_update_bounded": (
            state_update.get("self_memory_write") is False
            and state_update.get("policy_write") is False
            and state_update.get("mind_graph_write") is False
            and list(state_update.get("allowed_writes", [])) == ["operational_trace"]
        ),
        "no_new_autonomy_path": (
            dict(capsule.get("interface_contract", {})).get("transport_decision_authority") is False
            and state_update.get("second_brain_write") is False
        ),
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE30_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage29": stage29_payload,
        "subject_loop": subject_loop,
        "synthetic_wechat_subject_loop": synthetic_subject_loop,
    }, transport


def accept_stage31_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage30_payload, transport = accept_stage30_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    trace_id = int(dict(stage30_payload.get("stage29", {})).get("trace_id", 0) or 0)
    trace_payload, _ = subject_loop_trace_payload(config_path, trace_id=trace_id)
    metrics_payload, _ = subject_loop_metrics_payload(config_path, limit=100)
    adapter_spec = adapter_registry.resolve(adapter="cli", channel="cli")
    checks = {
        "stage30_gate_passed": bool(stage30_payload.get("ok", False)),
        "adapter_registry_visible": adapter_spec.transport_is_interface and not adapter_spec.transport_decision_authority,
        "state_update_gate_visible": dict(stage30_payload.get("subject_loop", {})).get("state_update", {}).get("gate") == "controlled_state_update_gate",
        "subject_loop_diagnostics_visible": bool(trace_payload.get("ok", False)) and int(metrics_payload.get("trace_count", 0) or 0) >= 1,
        "cli_payload_helpers_extracted": __name__ == "holo_host.cli_parts.bionic",
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE31_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage30": stage30_payload,
        "subject_loop_trace": trace_payload,
        "subject_loop_metrics": metrics_payload,
        "adapter_contract": adapter_spec.to_contract(),
    }, transport
