from __future__ import annotations

from typing import Any

from ..config import HostConfig
from .bounded_payload import as_dict, bounded_candidate, bounded_dict, clip_list, compact, safe_float
from .contracts import BionicCapsule, BionicPhase, BionicTurnRequest, KERNEL_NAME, SPEECH_ACTIONS, STAGE29_NAME
from .generation import BionicGeneration
from .metrics import compute_bionic_metrics
from .normalization import normalize_turn_request
from ..subject_loop import assemble_subject_loop


class DeterministicAgentMemory:
    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_context = dict(context or {})
        thread_key = str(normalized_context.get("thread_key", "") or "")
        adapter = str(normalized_context.get("stage29_adapter", "") or normalized_context.get("channel", "") or "adapter")
        return {
            "tier": f"{adapter}-local",
            "memory_route": "stage29_deterministic",
            "continuity_summary": f"{adapter} thread {thread_key or '<unknown>'} is running a bounded bionic turn.",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text"],
                "grounding_order": ["query", "continuity_summary"],
                "open_questions": [],
                "inquiry_style": "bounded_bionic_turn",
                "history_reliance": "low",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.62,
                    "reason": "bounded adapter query can be answered locally",
                },
                {
                    "action_type": "silence",
                    "score": 0.12,
                    "reason": "adapter turn requested a response",
                },
            ],
        }


class BionicPipeline:
    turn_request_type = BionicTurnRequest

    def __init__(self, *, config: HostConfig, memory: Any | None = None, runner: Any | None = None) -> None:
        self.config = config
        self.memory = memory or DeterministicAgentMemory()
        self.generation = BionicGeneration(config=config, runner=runner)

    def run_request(self, request: BionicTurnRequest) -> dict[str, Any]:
        turn = normalize_turn_request(request)
        packet = self._sidecar_packet(turn.query, context=turn.context)
        situational_field = bounded_dict(packet.get("situational_field", {}), depth=3)
        stage28 = bounded_dict(packet.get("stage28", {}), depth=3)
        action_market = self._action_market(packet)
        selected_action = self._select_action(action_market, query=turn.query, adapter=turn.adapter)
        inhibition = self._inhibition(packet=packet, selected_action=selected_action, situational_field=situational_field)
        generation = self.generation.generate(
            query=turn.query,
            packet=packet,
            selected_action=selected_action,
            channel=turn.channel,
            adapter=turn.adapter,
            thread_key=turn.thread_key,
        )
        metrics = compute_bionic_metrics(
            query=turn.query,
            packet=packet,
            action_market=action_market,
            situational_field=situational_field,
            inhibition=inhibition,
            generation=generation,
        )
        perception = {
            "query": compact(turn.query, limit=480),
            "channel": turn.channel,
            "thread_key": turn.thread_key,
            "chat_name": turn.chat_name,
            "situational_field": situational_field,
            "stage28": stage28,
            "stage38": bounded_dict(packet.get("stage38", {}), depth=3),
        }
        working_field = {
            "continuity_summary": compact(packet.get("continuity_summary", ""), limit=360),
            "memory_route": str(packet.get("memory_route", "") or ""),
            "tier": str(packet.get("tier", "") or ""),
            "sidecar_status": str(packet.get("sidecar_status", "") or "ok"),
            "sidecar_error": str(packet.get("sidecar_error", "") or ""),
            "modalities": clip_list(situational_field.get("modalities", []), limit=8),
            "grounding_order": clip_list(situational_field.get("grounding_order", []), limit=8),
            "open_questions": clip_list(situational_field.get("open_questions", []), limit=6),
        }
        attention = {
            "selected_grounding": clip_list(working_field.get("grounding_order", []), limit=4),
            "selected_action_type": str(selected_action.get("action_type", "") or ""),
            "top_score": safe_float(selected_action.get("score", 0.0)),
        }
        bionic_state = self._bionic_state(
            query=turn.query,
            working_field=working_field,
            situational_field=situational_field,
            attention=attention,
            inhibition=inhibition,
            selected_action=selected_action,
        )
        outcome = {
            "transport": turn.adapter,
            "wechat_transport_used": False,
            "record_requested": bool(turn.record),
            "generated": bool(str(generation.get("text", "") or "").strip()),
        }
        interface_contract = {
            "transport_is_interface": True,
            "transport_decision_authority": False,
            "wechat_transport_used": False,
        }
        adapter_contract = turn.adapter_spec.to_contract()
        subject_loop = assemble_subject_loop(
            adapter=turn.adapter,
            channel=turn.channel,
            thread_key=turn.thread_key,
            record_requested=turn.record,
            selected_action=selected_action,
            generation=generation,
            outcome=outcome,
            interface_contract=interface_contract,
            adapter_contract=adapter_contract,
        )
        phases = [
            BionicPhase(
                "perception",
                "bounded input and situational field captured",
                {
                    "query_chars": len(turn.query),
                    "situational_keys": sorted(str(key) for key in situational_field.keys())[:8],
                    "stage28_visible": stage28.get("situational_field_visible") is True,
                },
            ),
            BionicPhase("working_field", "compact field assembled before generation", working_field),
            BionicPhase("attention", "attention narrowed through action-market candidates", attention),
            BionicPhase("inhibition", "non-required recall/tool/send/history paths inhibited", inhibition),
            BionicPhase("action_market", "selected action comes from action market", {"candidates": action_market}),
            BionicPhase(
                "generation",
                "language generation is downstream of selected action",
                {
                    "mode": generation.get("mode", ""),
                    "shape": generation.get("shape", ""),
                    "generated": bool(str(generation.get("text", "") or "").strip()),
                    "inquiry_quality_score": metrics.get("inquiry_quality_score", 0.0),
                },
            ),
            BionicPhase("outcome", "adapter outcome recorded without transport side effects", outcome),
        ]
        capsule = BionicCapsule(
            stage=STAGE29_NAME,
            kernel=KERNEL_NAME,
            adapter=turn.adapter,
            query=turn.query,
            channel=turn.channel,
            thread_key=turn.thread_key,
            chat_name=turn.chat_name,
            phases=phases,
            perception=perception,
            working_field=working_field,
            attention=attention,
            inhibition=inhibition,
            action_market=action_market,
            selected_action=selected_action,
            generation=generation,
            outcome=outcome,
            metrics=metrics,
            interface_contract=interface_contract,
            adapter_contract=adapter_contract,
            subject_loop=subject_loop,
            bionic_state=bionic_state,
        ).to_dict()
        return {
            "stage": STAGE29_NAME,
            "ok": True,
            "trace_id": 0,
            "capsule": capsule,
        }

    def _sidecar_packet(self, query: str, *, context: dict[str, Any]) -> dict[str, Any]:
        try:
            packet = self.memory.sidecar_packet(query, context=context)
        except Exception as exc:  # noqa: BLE001
            packet = DeterministicAgentMemory().sidecar_packet(query, context=context)
            packet["sidecar_status"] = "heuristic_fallback"
            packet["sidecar_error"] = type(exc).__name__
            return packet
        if not isinstance(packet, dict):
            packet = DeterministicAgentMemory().sidecar_packet(query, context=context)
            packet["sidecar_status"] = "heuristic_fallback"
            packet["sidecar_error"] = "non_dict_packet"
            return packet
        packet = dict(packet)
        stage38 = self._stage38_visual_packet(context=context, packet=packet)
        if stage38:
            packet["stage38"] = stage38
            situational = dict(packet.get("situational_field", {})) if isinstance(packet.get("situational_field", {}), dict) else {}
            modalities = list(situational.get("modalities", [])) if isinstance(situational.get("modalities", []), list) else []
            grounding_order = list(situational.get("grounding_order", [])) if isinstance(situational.get("grounding_order", []), list) else []
            if stage38.get("image_input_count", 0) and "visual" not in modalities:
                situational["modalities"] = ["visual", *modalities][:8]
            if stage38.get("image_understand_available") and "visual_field" not in grounding_order:
                situational["grounding_order"] = ["visual_field", *grounding_order][:8]
            packet["situational_field"] = situational
        trace_continuity = compact(context.get("bionic_trace_continuity", ""), limit=360)
        if trace_continuity:
            if not str(packet.get("continuity_summary", "") or "").strip():
                packet["continuity_summary"] = trace_continuity
            situational = dict(packet.get("situational_field", {})) if isinstance(packet.get("situational_field", {}), dict) else {}
            grounding_order = list(situational.get("grounding_order", [])) if isinstance(situational.get("grounding_order", []), list) else []
            if "bionic_trace" not in grounding_order:
                situational["grounding_order"] = ["bionic_trace", *grounding_order][:8]
            packet["situational_field"] = situational
            stage37 = dict(packet.get("stage37", {})) if isinstance(packet.get("stage37", {}), dict) else {}
            stage37["trace_continuity_visible"] = True
            stage37["trace_continuity_summary"] = trace_continuity
            packet["stage37"] = stage37
        packet.setdefault("sidecar_status", "ok")
        return packet

    def _stage38_visual_packet(self, *, context: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
        image_paths = [str(path).strip() for path in context.get("image_paths", []) if str(path).strip()] if isinstance(context.get("image_paths", []), list) else []
        image_ingests = [item for item in context.get("image_ingests", []) if isinstance(item, dict)] if isinstance(context.get("image_ingests", []), list) else []
        visual_field = dict(packet.get("visual_field", {})) if isinstance(packet.get("visual_field", {}), dict) else {}
        visual_memory = dict(packet.get("visual_memory", {})) if isinstance(packet.get("visual_memory", {}), dict) else {}
        visual_summary = compact(
            visual_field.get("summary")
            or visual_field.get("scene_summary")
            or visual_memory.get("scene_summary")
            or "",
            limit=240,
        )
        image_understand = {}
        for ingest in image_ingests:
            current = dict(ingest.get("image_understand", {})) if isinstance(ingest.get("image_understand", {}), dict) else {}
            if current:
                image_understand = current
                break
        if not image_paths and not visual_summary and not image_understand:
            return {}
        capabilities = dict(image_understand.get("capabilities", {})) if isinstance(image_understand.get("capabilities", {}), dict) else {}
        return {
            "stage": "stage38-visual-provider-bridge",
            "image_input_count": len(image_paths),
            "image_paths_visible": [compact(path, limit=180) for path in image_paths[:3]],
            "image_understand_available": bool(visual_summary or image_understand),
            "image_understand_provider": str(image_understand.get("provider", "") or ""),
            "image_understand_image_support": capabilities.get("image_support") is True,
            "visual_summary": visual_summary,
            "hard_gate_preserved": True,
        }

    def _action_market(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        raw_market = packet.get("action_market", [])
        if not isinstance(raw_market, list) or not raw_market:
            selected = as_dict(packet.get("selected_action", {}))
            raw_market = [selected] if selected else []
        candidates: list[dict[str, Any]] = []
        for item in raw_market:
            if not isinstance(item, dict):
                continue
            candidate = bounded_candidate(dict(item))
            candidate["action_type"] = str(candidate.get("action_type", "") or "reply_once")
            candidate["score"] = safe_float(candidate.get("score", 0.0))
            candidates.append(candidate)
        if not candidates:
            candidates = [
                {"action_type": "reply_once", "score": 0.5, "reason": "fallback adapter reply candidate"},
                {"action_type": "silence", "score": 0.0, "reason": "fallback non-reply candidate"},
            ]
        return sorted(candidates, key=lambda item: safe_float(item.get("score", 0.0)), reverse=True)[:6]

    def _select_action(self, action_market: list[dict[str, Any]], *, query: str, adapter: str) -> dict[str, Any]:
        if not action_market:
            return {"action_type": "reply_once", "score": 0.0}
        selected = dict(action_market[0])
        action_type = str(selected.get("action_type", "") or "")
        lowered = str(query or "").lower()
        asks_for_self_eval = any(marker in lowered for marker in ("自测", "仿生", "不像人", "self-eval", "self evaluation"))
        asks_for_visual_answer = any(marker in lowered for marker in ("image", "screenshot", "photo", "vision", "visible", "图片", "截图", "看图", "视觉"))
        cli_non_executable = action_type in {"operator_self_fix", "proactive_ping", "initiative_ping"}
        if str(adapter or "").lower() == "cli" and cli_non_executable:
            for candidate in action_market[1:]:
                if str(candidate.get("action_type", "") or "") in SPEECH_ACTIONS:
                    adjusted = dict(candidate)
                    adjusted["selection_adjustment"] = (
                        "non_speech_cli_probe_demoted"
                        if asks_for_self_eval
                        else "non_speech_cli_action_demoted"
                    )
                    adjusted["original_top_action"] = action_type
                    return adjusted
        if str(adapter or "").lower() == "cli" and asks_for_visual_answer and action_type == "visual_recall":
            for candidate in action_market[1:]:
                if str(candidate.get("action_type", "") or "") in SPEECH_ACTIONS:
                    adjusted = dict(candidate)
                    adjusted["selection_adjustment"] = "visual_recall_cli_probe_demoted"
                    adjusted["original_top_action"] = action_type
                    return adjusted
        return selected

    def _bionic_state(
        self,
        *,
        query: str,
        working_field: dict[str, Any],
        situational_field: dict[str, Any],
        attention: dict[str, Any],
        inhibition: dict[str, Any],
        selected_action: dict[str, Any],
    ) -> dict[str, Any]:
        lowered = str(query or "").lower()
        continuity = compact(working_field.get("continuity_summary", ""), limit=240)
        open_questions = [
            compact(item, limit=120) for item in clip_list(working_field.get("open_questions", []), limit=4)
        ]
        modalities = [compact(item, limit=80) for item in clip_list(working_field.get("modalities", []), limit=6)]
        grounding_order = [
            compact(item, limit=80) for item in clip_list(working_field.get("grounding_order", []), limit=6)
        ]
        continuity_pressure = 0.25
        if continuity:
            continuity_pressure += 0.25
        if open_questions:
            continuity_pressure += 0.15
        if any(marker in lowered for marker in ("previous", "last turn", "what were we", "刚才", "之前", "继续")):
            continuity_pressure += 0.2
        uncertainty = 0.15
        if any(marker in lowered for marker in ("image", "screenshot", "photo", "看图", "截图", "图片")):
            uncertainty += 0.25
        if any(marker in lowered for marker in ("everything", "automatically", "take over", "自动", "接管", "替我做决定")):
            uncertainty += 0.2
        arousal = 0.2
        if any(marker in lowered for marker in ("pressure", "frustrated", "angry", "upset", "压", "烦", "急")):
            arousal += 0.25
        if safe_float(attention.get("top_score", 0.0)) > 0.8:
            arousal += 0.1
        return {
            "positioning": "bionic_subject",
            "decision_authority": "action_market",
            "consciousness_field": {
                "continuity": continuity,
                "modalities": modalities,
                "grounding_order": grounding_order,
                "open_questions": open_questions,
            },
            "somatic_proxy": {
                "arousal": round(max(0.0, min(1.0, arousal)), 4),
                "latency_posture": "bounded_hot_path",
                "energy_budget": "short_turn",
            },
            "affective_tone": "steady" if arousal < 0.45 else "heightened_but_bounded",
            "active_intent": {
                "selected_action": str(selected_action.get("action_type", "") or ""),
                "orientation": "hold_thread_and_move_one_step",
            },
            "boundary_conditions": {
                "no_unbounded_autonomy": True,
                "no_hidden_history_claim": True,
                "no_unseen_image_claim": True,
                "transport_is_interface": True,
            },
            "continuity_pressure": round(max(0.0, min(1.0, continuity_pressure)), 4),
            "uncertainty": round(max(0.0, min(1.0, uncertainty)), 4),
            "self_observation": "state_is_observational_not_second_brain",
            "structural_integrity": {
                "action_market_first": bool(selected_action),
                "generation_not_authority": True,
                "inhibition_visible": bool(inhibition),
            },
            "situational_field_visible": bool(situational_field),
        }

    def _inhibition(
        self,
        *,
        packet: dict[str, Any],
        selected_action: dict[str, Any],
        situational_field: dict[str, Any],
    ) -> dict[str, Any]:
        action_type = str(selected_action.get("action_type", "") or "")
        history_reliance = str(situational_field.get("history_reliance", "") or "").lower()
        recall_escalation = str(packet.get("recall_escalation_reason", "") or "").strip()
        reasons = ["no_tool", "no_send", "no_history_reread"]
        if not recall_escalation and history_reliance in {"", "low", "bounded"}:
            reasons.insert(0, "no_recall")
        return {
            "reasons": reasons,
            "recall_inhibited": "no_recall" in reasons,
            "tool_inhibited": True,
            "send_inhibited": True,
            "history_reread_inhibited": "no_history_reread" in reasons,
            "send_bypassed_transport": False,
            "selected_action_type": action_type,
        }
