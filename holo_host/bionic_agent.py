from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import compact_text, utc_now
from .config import HostConfig
from .models import ProcessorTaskRequest
from .store import QueueStore


STAGE29_NAME = "stage29-bionic-subject-kernel"
KERNEL_NAME = "bionic_subject_kernel"
CAPSULE_PHASES = (
    "perception",
    "working_field",
    "attention",
    "inhibition",
    "action_market",
    "generation",
    "outcome",
)
SPEECH_ACTIONS = {"reply_once", "reply_multi", "push_back", "continuity_defense"}
BOUNDED_CANDIDATE_KEYS = (
    "action_type",
    "score",
    "reason",
    "why_now",
    "send_allowed",
    "stage28_delta",
    "stage28_rationale",
    "scene_delta",
    "scene_rationale",
    "policy_scenario_bucket",
    "goal_alignment_score",
    "identity_consistency_score",
)
BOUNDED_PREDICTION_KEYS = (
    "predicted_risk",
    "predicted_regret",
    "confidence",
)


def _clip_list(values: Any, *, limit: int = 8) -> list[Any]:
    if not isinstance(values, list):
        return []
    return values[: max(0, int(limit))]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _compact(value: Any, *, limit: int = 320) -> str:
    return compact_text(str(value or ""), limit=limit)


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _bounded_value(
    value: Any,
    *,
    depth: int = 2,
    str_limit: int = 360,
    list_limit: int = 12,
    dict_limit: int = 32,
) -> Any:
    if isinstance(value, str):
        return _compact(value, limit=str_limit)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if depth <= 0:
        return _compact(value, limit=str_limit)
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= dict_limit:
                bounded["_truncated_keys"] = max(0, len(value) - dict_limit)
                break
            bounded[_compact(key, limit=96)] = _bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
        return bounded
    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in value[:list_limit]
        ]
    if isinstance(value, set):
        return [
            _bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in sorted(value, key=lambda item: str(item))[:list_limit]
        ]
    return _compact(value, limit=str_limit)


def _bounded_dict(value: Any, *, depth: int = 2) -> dict[str, Any]:
    bounded = _bounded_value(value, depth=depth)
    return bounded if isinstance(bounded, dict) else {}


def _bounded_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in BOUNDED_CANDIDATE_KEYS:
        if key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, str):
            bounded[key] = _compact(value, limit=220)
        else:
            bounded[key] = value
    bounded["action_type"] = str(bounded.get("action_type", "") or "reply_once")
    bounded["score"] = _safe_float(bounded.get("score", 0.0))
    grounding_order = candidate.get("stage28_grounding_order", [])
    if isinstance(grounding_order, list):
        bounded["stage28_grounding_order"] = [str(item)[:80] for item in grounding_order[:6]]
    prediction = candidate.get("predicted_outcome", {})
    if isinstance(prediction, dict):
        bounded_prediction = {
            key: prediction.get(key)
            for key in BOUNDED_PREDICTION_KEYS
            if key in prediction
        }
        if bounded_prediction:
            bounded["predicted_outcome"] = bounded_prediction
    return bounded


@dataclass(slots=True)
class BionicTurnRequest:
    query: str
    thread_key: str
    chat_name: str
    channel: str = "cli"
    adapter: str = "cli"
    record: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BionicPhase:
    name: str
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class BionicCapsule:
    stage: str
    kernel: str
    adapter: str
    query: str
    channel: str
    thread_key: str
    chat_name: str
    phases: list[BionicPhase]
    perception: dict[str, Any]
    working_field: dict[str, Any]
    attention: dict[str, Any]
    inhibition: dict[str, Any]
    action_market: list[dict[str, Any]]
    selected_action: dict[str, Any]
    generation: dict[str, Any]
    outcome: dict[str, Any]
    metrics: dict[str, Any]
    interface_contract: dict[str, Any]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "kernel": self.kernel,
            "adapter": self.adapter,
            "query": self.query,
            "channel": self.channel,
            "thread_key": self.thread_key,
            "chat_name": self.chat_name,
            "phases": [phase.to_dict() for phase in self.phases],
            "perception": dict(self.perception),
            "working_field": dict(self.working_field),
            "attention": dict(self.attention),
            "inhibition": dict(self.inhibition),
            "action_market": [dict(item) for item in self.action_market],
            "selected_action": dict(self.selected_action),
            "generation": dict(self.generation),
            "outcome": dict(self.outcome),
            "metrics": dict(self.metrics),
            "interface_contract": dict(self.interface_contract),
            "created_at": self.created_at,
        }


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


class BionicKernel:
    def __init__(
        self,
        *,
        config: HostConfig,
        memory: Any | None = None,
        runner: Any | None = None,
        store: Any | None = None,
    ) -> None:
        self.config = config
        self.memory = memory or DeterministicAgentMemory()
        self.runner = runner
        self.store = store

    def run_turn(
        self,
        *,
        query: str,
        thread_key: str,
        chat_name: str,
        channel: str = "cli",
        record: bool = True,
    ) -> dict[str, Any]:
        return self.run_request(
            BionicTurnRequest(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                adapter=channel or "cli",
                record=record,
            )
        )

    def run_request(self, request: BionicTurnRequest) -> dict[str, Any]:
        query = str(request.query or "")
        chat_name = str(request.chat_name or "")
        channel = str(request.channel or "cli").strip() or "cli"
        adapter = str(request.adapter or channel).strip() or channel
        thread_key = QueueStore._normalize_wechat_thread_key(
            channel,
            str(request.thread_key or ""),
            subject=chat_name,
            display_name=chat_name,
        )
        record = bool(request.record)
        context = dict(request.metadata or {})
        context.update({
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "sender": chat_name or thread_key,
            "stage29_kernel": True,
            "stage29_adapter": adapter,
            "transport_is_interface": True,
            "transport_decision_authority": False,
        })
        packet = self._sidecar_packet(query, context=context)
        situational_field = _bounded_dict(packet.get("situational_field", {}), depth=3)
        stage28 = _bounded_dict(packet.get("stage28", {}), depth=3)
        action_market = self._action_market(packet)
        selected_action = dict(action_market[0]) if action_market else {"action_type": "reply_once", "score": 0.0}
        inhibition = self._inhibition(packet=packet, selected_action=selected_action, situational_field=situational_field)
        generation = self._generation(
            query=query,
            packet=packet,
            selected_action=selected_action,
            channel=channel,
            adapter=adapter,
            thread_key=thread_key,
        )
        metrics = self._metrics(
            query=query,
            packet=packet,
            action_market=action_market,
            situational_field=situational_field,
            inhibition=inhibition,
            generation=generation,
        )
        perception = {
            "query": _compact(query, limit=480),
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "situational_field": situational_field,
            "stage28": stage28,
        }
        working_field = {
            "continuity_summary": _compact(packet.get("continuity_summary", ""), limit=360),
            "memory_route": str(packet.get("memory_route", "") or ""),
            "tier": str(packet.get("tier", "") or ""),
            "sidecar_status": str(packet.get("sidecar_status", "") or "ok"),
            "sidecar_error": str(packet.get("sidecar_error", "") or ""),
            "modalities": _clip_list(situational_field.get("modalities", []), limit=8),
            "grounding_order": _clip_list(situational_field.get("grounding_order", []), limit=8),
            "open_questions": _clip_list(situational_field.get("open_questions", []), limit=6),
        }
        attention = {
            "selected_grounding": _clip_list(working_field.get("grounding_order", []), limit=4),
            "selected_action_type": str(selected_action.get("action_type", "") or ""),
            "top_score": _safe_float(selected_action.get("score", 0.0)),
        }
        outcome = {
            "transport": adapter,
            "wechat_transport_used": False,
            "record_requested": bool(record),
            "generated": bool(str(generation.get("text", "") or "").strip()),
        }
        interface_contract = {
            "transport_is_interface": True,
            "transport_decision_authority": False,
            "wechat_transport_used": False,
        }
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
            adapter=adapter,
            query=query,
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
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
        ).to_dict()
        trace_id = 0
        if record and self.store is not None:
            trace = self.store.record_bionic_agent_trace(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                query_text=query,
                capsule=capsule,
                metrics=metrics,
            )
            trace_id = int(trace.get("id", 0) or 0)
        return {
            "stage": STAGE29_NAME,
            "ok": True,
            "trace_id": trace_id,
            "capsule": capsule,
        }

    def export_trace(self, *, trace_id: int, output: str | Path) -> dict[str, Any]:
        if self.store is None:
            raise ValueError("store is required to export a bionic trace")
        rows = self.store.list_bionic_agent_traces(limit=1, trace_id=int(trace_id))
        if not rows:
            return {"ok": False, "stage": STAGE29_NAME, "trace_id": int(trace_id), "error": "trace_not_found"}
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rows[0]["capsule_json"], encoding="utf-8")
        return {"ok": True, "stage": STAGE29_NAME, "trace_id": int(trace_id), "output": str(output_path)}

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
            selected = _as_dict(packet.get("selected_action", {}))
            raw_market = [selected] if selected else []
        candidates: list[dict[str, Any]] = []
        for item in raw_market:
            if not isinstance(item, dict):
                continue
            candidate = _bounded_candidate(dict(item))
            candidate["action_type"] = str(candidate.get("action_type", "") or "reply_once")
            candidate["score"] = _safe_float(candidate.get("score", 0.0))
            candidates.append(candidate)
        if not candidates:
            candidates = [
                {"action_type": "reply_once", "score": 0.5, "reason": "fallback adapter reply candidate"},
                {"action_type": "silence", "score": 0.0, "reason": "fallback non-reply candidate"},
            ]
        return sorted(candidates, key=lambda item: _safe_float(item.get("score", 0.0)), reverse=True)[:6]

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

    def _generation(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        selected_action: dict[str, Any],
        channel: str,
        adapter: str,
        thread_key: str,
    ) -> dict[str, Any]:
        action_type = str(selected_action.get("action_type", "") or "")
        if action_type not in SPEECH_ACTIONS:
            return {
                "mode": "action_no_generation",
                "text": "",
                "provider": "",
                "model": "",
                "reason": f"selected action {action_type or '<unknown>'} is not a speech action",
            }
        if self.runner is None:
            return {
                "mode": "deterministic_fallback",
                "text": f"I read this as a bounded Holo turn: {_compact(query, limit=220)}",
                "provider": "deterministic",
                "model": "",
            }
        prompt = "\n".join(
            [
                "Answer as a bounded Holo bionic kernel turn.",
                f"Selected action: {selected_action.get('action_type', 'reply_once')}",
                f"Continuity: {_compact(packet.get('continuity_summary', ''), limit=280)}",
                f"User query: {query}",
            ]
        )
        request = ProcessorTaskRequest(
            task_type="reply",
            prompt=prompt,
            provider_hint=str(self.config.runtime.processor_backend or ""),
            metadata={"stage": STAGE29_NAME, "channel": channel, "adapter": adapter, "thread_key": thread_key},
        )
        result = self.runner.run_task(request)
        metadata = _bounded_dict(result.metadata or {}, depth=3)
        return {
            "mode": "processor_fabric",
            "text": str(result.text or ""),
            "provider": str(metadata.get("provider", "") or ""),
            "model": str(metadata.get("model", "") or ""),
            "metadata": metadata,
        }

    def _metrics(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        action_market: list[dict[str, Any]],
        situational_field: dict[str, Any],
        inhibition: dict[str, Any],
        generation: dict[str, Any],
    ) -> dict[str, Any]:
        field_units = [
            packet.get("continuity_summary", ""),
            *list(situational_field.get("modalities", []) if isinstance(situational_field.get("modalities", []), list) else []),
            *list(situational_field.get("open_questions", []) if isinstance(situational_field.get("open_questions", []), list) else []),
        ]
        scores = [_safe_float(item.get("score", 0.0)) for item in action_market[:2]]
        top_margin = scores[0] - scores[1] if len(scores) >= 2 else (scores[0] if scores else 0.0)
        generation_text = str(generation.get("text", "") or "")
        template_markers = (
            "stage29 bionic capsule reply:",
            "i read this as a bounded holo turn:",
            "answer as a bounded holo bionic kernel turn",
        )
        marker_hits = sum(1 for marker in template_markers if marker in generation_text.lower())
        template_pressure = min(1.0, marker_hits / max(1, len(template_markers)))
        return {
            "working_field_density": round(min(1.0, sum(1 for item in field_units if str(item or "").strip()) / 8.0), 4),
            "inhibition_count": len(list(inhibition.get("reasons", []))),
            "grounding_modalities": len(_clip_list(situational_field.get("modalities", []), limit=16)),
            "history_reread_avoided": bool(inhibition.get("history_reread_inhibited", False)),
            "action_market_top_margin": round(top_margin, 4),
            "template_pressure_score": round(template_pressure, 4),
            "query_chars": len(str(query or "")),
        }


class BionicAgent(BionicKernel):
    """Backward-compatible name for the Stage29 bionic subject kernel."""

    pass
