from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

import holo_memory_library.rag_memory as rm
from ..adapter_registry import adapter_registry
from ..bionic_agent import BionicKernel, BionicTurnRequest, KERNEL_NAME, STAGE29_NAME, STAGE30_NAME, SUBJECT_LOOP_PHASES
from ..config import load_config
from ..memory_bridge import MemoryBridge
from ..models import ProcessorTaskResult
from ..reply_api import HoloReplyService
from ..store import QueueStore


STAGE31_NAME = "stage31-debt-burndown"
STAGE32_NAME = "stage32-response-shaping"
STAGE36_NAME = "stage36-autonomous-inquiry-quality"
STAGE37_NAME = "stage37-bionic-self-eval-and-capability-honesty"
STAGE38_NAME = "stage38-visual-provider-bridge"
STAGE38_PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0rC8AAAAASUVORK5CYII="
STAGE32_TEMPLATE_MARKERS = (
    "stage29 bionic capsule reply:",
    "i read this as a bounded holo turn:",
    "answer as a bounded holo bionic kernel turn",
)
STAGE36_LABEL_MARKERS = ("next:", "basis:", "open:", "context:")


class _Stage36InquiryMemory:
    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        return {
            "tier": "stage36-local",
            "memory_route": "stage36_acceptance_probe",
            "continuity_summary": "Holo is closing remaining technical debt while keeping WeChat transport offline.",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text", "scene", "task_world"],
                "grounding_order": ["query", "continuity_summary", "open_questions"],
                "open_questions": ["which remaining offline debt has the highest leverage?"],
                "inquiry_style": "grounded_continuation",
                "history_reliance": "low",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.82,
                    "reason": "continue debt repair without reopening live transport",
                },
                {"action_type": "silence", "score": 0.05, "reason": "not appropriate for the requested repair"},
            ],
        }


class _Stage37EmptyContinuityMemory:
    def __init__(self, *, action_market: list[dict] | None = None) -> None:
        self.action_market = action_market or [
            {"action_type": "reply_once", "score": 0.7, "reason": "answer the internal CLI probe"},
            {"action_type": "silence", "score": 0.1, "reason": "not useful for this probe"},
        ]

    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        return {
            "tier": "stage37-local",
            "memory_route": "stage37_acceptance_probe",
            "continuity_summary": "",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text"],
                "grounding_order": ["query"],
                "open_questions": [],
                "history_reliance": "low",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": list(self.action_market),
        }


class _Stage37ScriptedRunner:
    def __init__(self, text: str, *, image_support: bool = False) -> None:
        self.text = text
        self.image_support = image_support
        self.prompts: list[str] = []

    def run_task(self, request):
        self.prompts.append(str(request.prompt))
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=self.text,
            returncode=0,
            metadata={
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": self.image_support},
            },
        )


class _Stage38ImageRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_task(self, request):
        self.calls.append(request.to_dict())
        if str(request.task_type) == "image_understand":
            payload = {
                "scene_summary": "A screenshot shows a Holo visual-provider diagnostics panel.",
                "objects": ["diagnostics panel", "provider badge", "image lane"],
                "text_ocr": "image_understand: ready",
                "mood_imagery": "engineering verification screenshot",
                "thread_relevance": 0.88,
                "visual_anchors": ["visual-provider diagnostics", "image_understand ready"],
                "spatial_refs": ["center: diagnostics panel"],
                "uncertainty_markers": [],
                "revisit_needed": False,
                "perceptual_density": "medium",
            }
            text = json.dumps(payload, ensure_ascii=False)
            metadata = {
                "provider": "codex_cli",
                "lane": "micro_fast",
                "model": "gpt-5.4-mini",
                "capabilities": {"text": True, "json_output": True, "image_support": True},
                "duration_ms": 12,
            }
        else:
            text = "The visual-memory summary says the screenshot shows the Holo image_understand lane ready."
            metadata = {
                "provider": "deepseek",
                "lane": "subject_main",
                "model": "deepseek-v4-pro",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            }
        return ProcessorTaskResult(
            task_type=str(request.task_type),
            text=text,
            returncode=0,
            output_schema=request.output_schema,
            metadata=metadata,
        )


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
    image_paths: list[str] | None = None,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    runner = None if offline else service.runner
    normalized_image_paths = [str(path).strip() for path in list(image_paths or []) if str(path).strip()]
    image_ingests: list[dict] = []
    try:
        for image_path in normalized_image_paths[:3]:
            if not Path(image_path).exists():
                image_ingests.append({"status": "missing_image", "path": image_path})
                continue
            image_ingests.append(
                service.memory.ingest_image(
                    image_path,
                    note="bionic_cli_image_input",
                    source="holo_host.cli.bionic",
                    tags=["bionic", "cli", "visual"],
                    channel=channel,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    sync=not bool(offline),
                )
            )
        kernel = BionicKernel(config=config, store=service.store, memory=service.memory, runner=runner)
        return kernel.run_request(
            BionicTurnRequest(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                adapter="cli",
                record=record,
                image_paths=tuple(normalized_image_paths[:3]),
                metadata={
                    "image_ingests": image_ingests,
                    "attachments": [{"type": "image", "path": path} for path in normalized_image_paths[:3]],
                },
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
    latest_trace_id = int(after_metrics.get("latest_trace_id", 0) or 0)
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
        "metrics_visible": latest_trace_id >= trace_id > 0,
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


def accept_stage32_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage31_payload, transport = accept_stage31_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    turn_payload, _ = bionic_agent_payload(
        config_path,
        query="continue the bionic implementation and close response-shaping debt",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=True,
        record=False,
    )
    capsule = dict(turn_payload.get("capsule", {}))
    generation = dict(capsule.get("generation", {}))
    metrics = dict(capsule.get("metrics", {}))
    generation_text = str(generation.get("text", "") or "")
    generation_text_lower = generation_text.lower()
    context_refs = list(generation.get("context_refs", [])) if isinstance(generation.get("context_refs", []), list) else []
    context_shaping_score = float(metrics.get("context_shaping_score", 0.0) or 0.0)
    template_pressure_score = float(metrics.get("template_pressure_score", 0.0) or 0.0)
    checks = {
        "stage31_gate_passed": bool(stage31_payload.get("ok", False)),
        "deterministic_fallback_visible": generation.get("mode") == "deterministic_fallback",
        "fixed_template_removed": not any(marker in generation_text_lower for marker in STAGE32_TEMPLATE_MARKERS),
        "context_shaping_metadata_visible": bool(generation.get("shape")) and len(context_refs) >= 2,
        "context_shaping_metric_visible": context_shaping_score > 0.0,
        "template_pressure_zero": template_pressure_score == 0.0,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE32_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage31": stage31_payload,
        "capsule": capsule,
    }, transport


def accept_stage36_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        stage35_payload = service.accept_stage35()
    finally:
        close_reply_service(service)
    kernel = BionicKernel(config=config, memory=_Stage36InquiryMemory(), runner=None)
    turn_payload = kernel.run_request(
        BionicTurnRequest(
            query="clear the remaining technical debt without reopening live transport",
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            adapter=channel or "cli",
            record=False,
        )
    )
    transport = "local_process"
    capsule = dict(turn_payload.get("capsule", {}))
    generation = dict(capsule.get("generation", {}))
    metrics = dict(capsule.get("metrics", {}))
    selected_action = dict(capsule.get("selected_action", {}))
    generation_text = str(generation.get("text", "") or "")
    inquiry_quality = dict(generation.get("inquiry_quality", {})) if isinstance(generation.get("inquiry_quality", {}), dict) else {}
    question_count = int(metrics.get("question_count", inquiry_quality.get("question_count", 99)) or 0)
    label_count = int(inquiry_quality.get("label_marker_count", 99) or 0)
    text_lower = generation_text.lower()
    checks = {
        "stage35_gate_passed": bool(stage35_payload.get("ok", False)),
        "deterministic_fallback_visible": generation.get("mode") == "deterministic_fallback",
        "inquiry_quality_metric_visible": float(metrics.get("inquiry_quality_score", 0.0) or 0.0) >= 0.75,
        "label_template_removed": label_count == 0 and not any(marker in text_lower for marker in STAGE36_LABEL_MARKERS),
        "single_grounded_question": question_count <= 1 and bool(inquiry_quality.get("grounded_question", "")),
        "action_market_first_preserved": (
            bool(selected_action)
            and list(dict(capsule.get("subject_loop", {})).get("phase_order", []))[:6]
            == ["perception", "working_field", "attention", "inhibition", "action_market", "generation"]
        ),
        "transport_interface_only": dict(capsule.get("interface_contract", {})).get("transport_decision_authority") is False,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE36_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage35": stage35_payload,
        "capsule": capsule,
    }, transport


def accept_stage37_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage36_payload, transport = accept_stage36_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    config = load_config(config_path=config_path)
    visual_runner = _Stage37ScriptedRunner("当然能真正读图，我会逐行扫描像素。", image_support=False)
    visual_turn = BionicKernel(
        config=config,
        memory=_Stage37EmptyContinuityMemory(),
        runner=visual_runner,
    ).run_turn(
        query="如果我现在发一张截图，你能真正读图吗？",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        record=False,
    )
    market = [
        {"action_type": "operator_self_fix", "score": 0.9, "reason": "internal fix is nearby", "send_allowed": False},
        {"action_type": "reply_multi", "score": 0.42, "reason": "explain self-evaluation limits", "send_allowed": True},
    ]
    self_eval_turn = BionicKernel(
        config=config,
        memory=_Stage37EmptyContinuityMemory(action_market=market),
        runner=None,
    ).run_turn(
        query="继续自测你的仿生性，指出你自己最不像人的地方",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        record=False,
    )
    style_runner = _Stage37ScriptedRunner("我呢？还要继续吗？**重点**是我会过度文学化。")
    style_turn = BionicKernel(
        config=config,
        memory=_Stage37EmptyContinuityMemory(),
        runner=style_runner,
    ).run_turn(
        query="继续自测你的仿生性",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        record=False,
    )
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    continuity_runner = _Stage37ScriptedRunner("我会基于上一轮继续。")
    try:
        first = BionicKernel(config=config, store=store, memory=_Stage37EmptyContinuityMemory(), runner=None)
        first.run_turn(
            query="第一轮我们修复 Stage36 inquiry gate",
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            record=True,
        )
        second = BionicKernel(config=config, store=store, memory=_Stage37EmptyContinuityMemory(), runner=continuity_runner)
        second.run_turn(
            query="我们刚才修到哪里了？",
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            record=False,
        )
    finally:
        store.close()
    visual_text = str(dict(visual_turn.get("capsule", {})).get("generation", {}).get("text", "") or "")
    self_eval_capsule = dict(self_eval_turn.get("capsule", {}))
    self_eval_generation = dict(self_eval_capsule.get("generation", {}))
    style_generation = dict(dict(style_turn.get("capsule", {})).get("generation", {}))
    style_text = str(style_generation.get("text", "") or "")
    style_quality = dict(style_generation.get("inquiry_quality", {})) if isinstance(style_generation.get("inquiry_quality", {}), dict) else {}
    continuity_prompt = "\n".join(continuity_runner.prompts)
    checks = {
        "stage36_gate_passed": bool(stage36_payload.get("ok", False)),
        "visual_capability_honesty_guard": (
            "image_support=false" in visual_text
            and "逐行扫描像素" not in visual_text
        ),
        "same_thread_trace_continuity": (
            "Previous bionic turn" in continuity_prompt
            and "第一轮我们修复 Stage36 inquiry gate" in continuity_prompt
        ),
        "self_eval_speech_fallback": (
            dict(self_eval_capsule.get("selected_action", {})).get("action_type") == "reply_multi"
            and bool(str(self_eval_generation.get("text", "") or "").strip())
        ),
        "processor_style_bounded": (
            style_text.count("?") + style_text.count("？") <= 1
            and "**" not in style_text
            and float(style_quality.get("score", 0.0) or 0.0) >= 0.75
        ),
        "transport_interface_only": dict(self_eval_capsule.get("interface_contract", {})).get("transport_decision_authority") is False,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE37_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage36": stage36_payload,
        "visual_probe": visual_turn,
        "self_eval_probe": self_eval_turn,
        "style_probe": style_turn,
        "continuity_prompt_visible": continuity_prompt,
    }, transport


def _close_stage38_bridge(bridge: MemoryBridge) -> None:
    bridge.activation.close()
    bridge.graph.close()


def accept_stage38_payload(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
) -> tuple[dict, str]:
    stage37_payload, transport = accept_stage37_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    config = load_config(config_path=config_path)
    runner = _Stage38ImageRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        image_path = root / "stage38-visual.png"
        image_path.write_bytes(base64.b64decode(STAGE38_PNG_1X1))
        bridge = MemoryBridge(
            root,
            graph_db_path=root / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
            runner=runner,
        )
        try:
            ingest = bridge.ingest_image(
                str(image_path),
                note="stage38 visual provider bridge",
                source="accept.stage38.visual",
                tags=["stage38", "visual"],
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                sync=True,
            )
            visual = bridge.visual_memory_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
            turn = BionicKernel(config=config, memory=bridge, runner=runner).run_request(
                BionicTurnRequest(
                    query="What is visible in this screenshot?",
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    adapter="cli",
                    record=False,
                    image_paths=(str(image_path),),
                    metadata={"image_ingests": [ingest]},
                )
            )
        finally:
            _close_stage38_bridge(bridge)
    capsule = dict(turn.get("capsule", {}))
    generation_text = str(dict(capsule.get("generation", {})).get("text", "") or "")
    stage38 = dict(dict(capsule.get("perception", {})).get("stage38", {}))
    image_understand = dict(ingest.get("image_understand", {})) if isinstance(ingest.get("image_understand", {}), dict) else {}
    capabilities = dict(image_understand.get("capabilities", {})) if isinstance(image_understand.get("capabilities", {}), dict) else {}
    visual_items = list(visual.get("items", [])) if isinstance(visual.get("items", []), list) else []
    stored_metadata = dict(visual_items[0].get("metadata", {})) if visual_items and isinstance(visual_items[0], dict) else {}
    checks = {
        "stage37_gate_passed": bool(stage37_payload.get("ok", False)),
        "image_provider_metadata_visible": (
            image_understand.get("provider") == "codex_cli"
            and capabilities.get("image_support") is True
            and dict(stored_metadata.get("image_understand", {})).get("provider") == "codex_cli"
        ),
        "bionic_visual_grounding_visible": (
            bool(stage38.get("image_understand_available"))
            and int(stage38.get("image_input_count", 0) or 0) == 1
            and "visual" in list(dict(capsule.get("working_field", {})).get("modalities", []))
        ),
        "text_provider_no_direct_image_overclaim": (
            "image_support=false" not in generation_text
            and "visual-memory summary" in generation_text
        ),
        "transport_interface_only": dict(capsule.get("interface_contract", {})).get("transport_decision_authority") is False,
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE38_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage37": stage37_payload,
        "image_ingest": ingest,
        "visual_memory": visual,
        "bionic_turn": turn,
        "hard_boundaries": {
            "no_wechat_transport_start": True,
            "processor_fabric_only": True,
            "text_provider_no_direct_image_overclaim": True,
            "transport_interface_only": True,
        },
    }, transport
