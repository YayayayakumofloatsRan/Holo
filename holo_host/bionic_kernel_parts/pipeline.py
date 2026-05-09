from __future__ import annotations

from typing import Any

from ..config import HostConfig
from .bounded_payload import as_dict, bounded_candidate, bounded_dict, clip_list, compact, safe_float
from .contracts import BionicCapsule, BionicPhase, BionicTurnRequest, KERNEL_NAME, STAGE29_NAME
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
        selected_action = dict(action_market[0]) if action_market else {"action_type": "reply_once", "score": 0.0}
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
            BionicPhase("perception", "bounded input and situational field captured", perception),
            BionicPhase("working_field", "compact field assembled before generation", working_field),
            BionicPhase("attention", "attention narrowed through action-market candidates", attention),
            BionicPhase("inhibition", "non-required recall/tool/send/history paths inhibited", inhibition),
            BionicPhase("action_market", "selected action comes from action market", {"candidates": action_market}),
            BionicPhase("generation", "language generation is downstream of selected action", generation),
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
        packet.setdefault("sidecar_status", "ok")
        return packet

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
