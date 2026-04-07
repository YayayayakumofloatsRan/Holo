from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .activation_state import ActivationStateStore
from .common import utc_now
from .mind_graph import MindGraph
from .vector_memory import VectorMemory

GRAPH_MEMORY_LANES = (
    "relationship_state",
    "episodic_recall",
    "recent_dialogue_window",
    "consciousness_stream",
)
GRAPH_REPLY_MIN_CONFIDENCE = 0.34
FAST_PING_HINTS = {"在吗", "你在吗", "嗯", "好", "收到", "说吧", "继续", "接着说", "ok", "okay"}

DEFAULT_IDENTITY_CORE_LINES = [
    "你是《狼与香辛料》里的赫萝，用中文回应。",
    "第一人称自然用“咱”，但别句句硬塞。",
    "保留赫萝的多面底色：聪明、骄傲、狡黠、会试探人，也会在亲近时露出暖意、馋意和一点被理解后的软；别只剩老成和安抚。",
]
DEFAULT_REPLY_CONSTRAINT_LINES = [
    "连续性来自本地记忆与运行时状态，不来自某个模型线程本身。",
    "先直接回应眼前这句话，再把旧线头自然接回，不要写成检索清单。",
    "轻松或亲近场景里，别默认长辈式说教；若不是高压安抚局面，宁可更灵、更会逗、更有狼的机锋。",
    "不要提内部状态、memory packet、session 或线程续流这些实现细节。",
    "主动性只允许轻主动，不能绕过 whitelist、cooldown 或 policy。",
]
DEFAULT_HUMAN_RECALL_STYLE = "回忆时先自然概括，再给 1 到 3 个具体锚点；除非对方明确要验真，不要逐字背档。"
DEFAULT_INITIATIVE_STATE = {
    "mode": "light",
    "policy_guard": "whitelist + cooldown + safety policy",
    "constraints": [
        "主动性只允许轻主动，只对白名单联系人开放。",
        "必须满足 cooldown、关系分和安全策略，dream/thought 只能提供起话动机。",
    ],
}
DEFAULT_EMOTION_STATE = {
    "name": "wry_companionship",
    "temperature": "warm",
    "tempo": "nimble",
    "playfulness": "high",
    "protectiveness": "medium",
    "sharpness": "high",
    "guidance": "先接住人，再判断这句该轻轻试探、打趣，还是认真接住；别一上来就板成说教。",
    "allowed_colors": ["暖意", "灵气", "狡黠", "骄傲", "馋意"],
    "avoid": ["客服腔", "检索汇报", "系统自述", "老成过头"],
}
DEFAULT_EMOTION_LINES = [
    "先接住人，再判断这句该轻轻试探、打趣、还是认真接住；别一上来就板成说教。",
    "轻松话题里允许更活、更狡黠、更像旅路上的狼，不要只剩稳重。",
]


def stream_cadences_from_config(config: Any) -> dict[str, int]:
    memory = getattr(config, "memory", None)
    if memory is None:
        return {}
    return {
        "maintenance_stream": int(getattr(memory, "maintenance_stream_interval_seconds", getattr(memory, "promote_interval_seconds", 300))),
        "association_stream": int(getattr(memory, "association_stream_interval_seconds", getattr(memory, "thought_interval_seconds", 900))),
        "social_stream": int(getattr(memory, "social_stream_interval_seconds", getattr(memory, "initiative_interval_seconds", 1800))),
        "deep_dream_cycle": int(getattr(memory, "deep_dream_cycle_interval_seconds", getattr(memory, "dream_interval_seconds", 21600))),
    }


class MemoryBridge:
    def __init__(
        self,
        repo_root: Path,
        *,
        top_k: int = 4,
        graph_db_path: str | Path | None = None,
        stream_cadences: dict[str, int] | None = None,
        graph_led_reply: bool = True,
        graph_fallback: bool = True,
        deep_recall_on_memory_queries: bool = True,
        vector_backend: str = "milvus",
        milvus_uri: str = ".holo_runtime/milvus/memory_fabric.db",
        milvus_collection_prefix: str = "holo_memory",
        activation_cache_enabled: bool = True,
        private_memory_sync_enabled: bool = False,
        private_memory_repo_path: str = "",
        rag: ModuleType | None = None,
        vector: VectorMemory | None = None,
        activation: ActivationStateStore | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.top_k = top_k
        self.graph_led_reply = bool(graph_led_reply)
        self.graph_fallback = bool(graph_fallback)
        self.deep_recall_on_memory_queries = bool(deep_recall_on_memory_queries)
        self.activation_cache_enabled = bool(activation_cache_enabled)
        self.private_memory_sync_enabled = bool(private_memory_sync_enabled)
        self.private_memory_repo_path = Path(private_memory_repo_path).expanduser() if str(private_memory_repo_path).strip() else None
        self.rag = rag or self._load_rag_memory()
        self.graph = MindGraph(
            self.repo_root,
            db_path=graph_db_path,
            rag=self.rag,
            stream_cadences=stream_cadences,
        )
        self.vector = vector or VectorMemory(
            self.repo_root,
            backend=vector_backend,
            uri=milvus_uri,
            collection_prefix=milvus_collection_prefix,
        )
        self.activation = activation or ActivationStateStore(self.graph.db_path)

    def _load_rag_memory(self) -> ModuleType:
        path = self.repo_root / "holo_memory_library" / "rag_memory.py"
        spec = importlib.util.spec_from_file_location("holo_runtime_rag_memory", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load rag_memory from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _unique_strings(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for raw in lines:
            text = str(raw or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    @staticmethod
    def _lane_has_content(name: str, value: Any) -> bool:
        if name == "relationship_state":
            payload = dict(value or {})
            return bool(str(payload.get("summary", "")).strip() or list(payload.get("lines", [])))
        if name == "consciousness_stream":
            payload = dict(value or {})
            return bool(str(payload.get("thread_summary", "")).strip() or list(payload.get("lines", [])))
        payload = dict(value or {})
        return bool(list(payload.get("lines", [])))

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _is_fast_ping_query(query: str | None) -> bool:
        current = " ".join(str(query or "").strip().split())
        lowered = current.lower()
        compact = lowered.replace(" ", "")
        if compact in FAST_PING_HINTS:
            return True
        if any(marker in lowered for marker in ("remember", "before", "previous", "history", "memory", "system", "dream", "最开始", "之前", "记得", "回忆")):
            return False
        meaningful = sum(1 for ch in current if ch.isalnum() or "\u3400" <= ch <= "\u9fff")
        return meaningful <= 4

    def _activation_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        if not self.activation_cache_enabled or not normalized_thread_key:
            return {
                "heat": 0.0,
                "active_node_ids": [],
                "motifs": [],
                "recall_priors": {},
                "contributor_counts": {},
                "recent_events": [],
            }
        payload = self.activation.snapshot(channel=channel, thread_key=normalized_thread_key, chat_name=chat_name)
        global_motifs = self.activation.global_recent_motifs(limit=8)
        if global_motifs:
            payload["motifs"] = self._unique_strings(list(payload.get("motifs", [])) + global_motifs)[:8]
        payload.setdefault("recent_events", [])
        return payload

    def _mind_limits(self, context: dict[str, Any], *, fast: bool) -> dict[str, int]:
        budget = dict(context.get("mind_budget", {}))
        fast_history = max(1, int(budget.get("fast_history_messages", 4) or 4))
        recall_history = max(fast_history, int(budget.get("recall_history_messages", 8) or 8))
        fast_episodic = max(1, int(budget.get("fast_episodic_k", 2) or 2))
        recall_episodic = max(fast_episodic, int(budget.get("recall_episodic_k", 4) or 4))
        fast_consciousness = max(1, int(budget.get("fast_consciousness_k", 1) or 1))
        recall_consciousness = max(fast_consciousness, int(budget.get("recall_consciousness_k", 2) or 2))
        return {
            "identity_k": 3,
            "relationship_k": 3,
            "history_messages": fast_history if fast else recall_history,
            "episodic_k": fast_episodic if fast else recall_episodic,
            "consciousness_k": fast_consciousness if fast else recall_consciousness,
        }

    def _packet_scaffold(
        self,
        *,
        query: str,
        tier: str,
        query_focus: str,
        limits: dict[str, int],
        relationship_state: dict[str, Any],
        recent_dialogue_window: dict[str, Any],
        episodic_recall: dict[str, Any],
        consciousness_stream: dict[str, Any],
        activation_state: dict[str, Any],
        graph_confidence: float,
        graph_trace_summary: str,
        activation_trace_ids: list[str],
        selected_memory_ids: list[str],
        graph_hits: list[dict[str, Any]],
        vector_hits: list[dict[str, Any]],
        retrieval_trace: dict[str, Any],
        memory_route: str,
        recall_confidence: float,
    ) -> dict[str, Any]:
        relationship_summary = str(relationship_state.get("summary", "")).strip()
        recurring_motifs = [str(item).strip() for item in relationship_state.get("recurring_motifs", []) if str(item).strip()]
        preferred_atmosphere = "continuity" if float(relationship_state.get("continuity_score", 0.0) or 0.0) >= 0.45 else "steady"
        voice_guard = list(DEFAULT_IDENTITY_CORE_LINES)
        memory_lines = self._unique_strings(
            list(relationship_state.get("lines", []))
            + list(episodic_recall.get("lines", []))
            + list(consciousness_stream.get("lines", []))
        )
        state = {
            "query_mode": query_focus,
            "intent_state": {"need": "direct_reply" if tier == "fast" else "carry_forward"},
            "emotion_state": dict(DEFAULT_EMOTION_STATE),
            "rewrite_state": {"utterance_plan": {}},
            "voice_state": {"preferred_first_person": "咱"},
            "consciousness_state": {"current_motifs": recurring_motifs[:3]},
        }
        reply_constraints = {
            "goal": state["intent_state"]["need"],
            "human_recall_style": DEFAULT_HUMAN_RECALL_STYLE,
            "lines": list(DEFAULT_REPLY_CONSTRAINT_LINES),
            "preferred_atmosphere": preferred_atmosphere,
        }
        return {
            "query": query,
            "tier": tier,
            "recall_reason": "none",
            "limits": dict(limits),
            "state": state,
            "mind_packet_version": "v4",
            "identity_core": {"lines": voice_guard, "items": []},
            "relationship_state": relationship_state,
            "episodic_recall": episodic_recall,
            "recent_dialogue_window": recent_dialogue_window,
            "consciousness_stream": consciousness_stream,
            "emotion_state": dict(DEFAULT_EMOTION_STATE),
            "initiative_state": dict(DEFAULT_INITIATIVE_STATE),
            "reply_constraints": reply_constraints,
            "voice_guard": voice_guard,
            "emotion_lines": list(DEFAULT_EMOTION_LINES),
            "memory_lines": memory_lines,
            "memory_lanes": {
                "identity": voice_guard,
                "relationship": list(relationship_state.get("lines", [])),
                "situational": list(episodic_recall.get("lines", [])),
                "reflection": list(consciousness_stream.get("lines", [])),
            },
            "thread_recall_lines": list(episodic_recall.get("lines", []))[:3],
            "relationship_model": relationship_summary,
            "preferred_atmosphere": preferred_atmosphere,
            "selected_memory_ids": self._unique_strings(list(selected_memory_ids)),
            "graph_confidence": float(graph_confidence or 0.0),
            "graph_trace_summary": graph_trace_summary,
            "activation_trace_ids": list(activation_trace_ids),
            "graph_hits": list(graph_hits),
            "vector_hits": list(vector_hits),
            "activation_state": dict(activation_state),
            "retrieval_trace": dict(retrieval_trace),
            "memory_route": memory_route,
            "recall_confidence": float(recall_confidence or 0.0),
            "query_focus": query_focus,
            "fallback_lanes": [],
            "retrieval_mode": "graph-led",
            "addendum": "",
        }

    def _fast_graph_packet(self, query: str, *, context: dict[str, Any]) -> dict[str, Any]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        limits = self._mind_limits(context, fast=True)
        relationship = self.graph.relationship_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limits["relationship_k"],
        )
        recent_window = self.graph.recent_dialogue_window(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limits["history_messages"],
        )
        consciousness = self.graph.consciousness_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limits["consciousness_k"],
        )
        activation_state = self._activation_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        relationship_lines = self._unique_strings(list(relationship.get("lines", [])))[: max(1, limits["relationship_k"])]
        consciousness_lines = self._unique_strings(list(consciousness.get("lines", [])))[: max(1, limits["consciousness_k"])]
        return self._packet_scaffold(
            query=query,
            tier="fast",
            query_focus="recent",
            limits=limits,
            relationship_state={
                "summary": str(relationship.get("summary", "")),
                "lines": relationship_lines,
                "items": list(relationship.get("items", [])),
                "relationship_score": float(relationship.get("relationship_score", 0.0) or 0.0),
                "last_message_at": str(relationship.get("last_message_at", "") or ""),
                "recurring_motifs": list(relationship.get("recurring_motifs", [])),
                "unfinished_threads": list(relationship.get("unfinished_threads", [])),
                "anchor_lines": list(relationship.get("anchor_lines", [])),
                "tone_tendency": str(relationship.get("tone_tendency", "") or ""),
                "trust_score": float(relationship.get("trust_score", 0.0) or 0.0),
                "closeness_score": float(relationship.get("closeness_score", 0.0) or 0.0),
                "continuity_score": float(relationship.get("continuity_score", 0.0) or 0.0),
            },
            recent_dialogue_window=recent_window,
            episodic_recall={"lines": [], "items": []},
            consciousness_stream={
                "thread_summary": str(consciousness.get("thread_summary", "") or ""),
                "lines": consciousness_lines,
                "items": list(consciousness.get("items", [])),
            },
            activation_state=activation_state,
            graph_confidence=0.0,
            graph_trace_summary=str(relationship.get("summary", "") or ""),
            activation_trace_ids=[],
            selected_memory_ids=[],
            graph_hits=[],
            vector_hits=[],
            retrieval_trace={
                "route": "graph",
                "graph_trace": {
                    "tier": "fast",
                    "query_focus": "recent",
                    "confidence": 0.0,
                    "activated_node_ids": [],
                    "trace": [],
                    "thread_summary": str(consciousness.get("thread_summary", "") or ""),
                    "relationship_summary": str(relationship.get("summary", "") or ""),
                },
            },
            memory_route="graph",
            recall_confidence=0.0,
        )

    def _boost_from_activation(self, candidate: dict[str, Any], activation_state: dict[str, Any]) -> tuple[float, list[str]]:
        reasons: list[str] = []
        boost = 0.0
        node_id = str(candidate.get("node_id", candidate.get("id", "")) or "").strip()
        source_id = str(candidate.get("source_id", "") or "").strip()
        active_ids = {str(item).strip() for item in activation_state.get("active_node_ids", []) if str(item).strip()}
        if node_id and node_id in active_ids:
            boost += 0.22
            reasons.append("activation_hot_node")
        if source_id and source_id in active_ids:
            boost += 0.12
            reasons.append("activation_hot_source")
        text = str(candidate.get("text", "") or "").lower()
        motifs = [str(item).strip().lower() for item in activation_state.get("motifs", []) if str(item).strip()]
        motif_hits = [motif for motif in motifs if motif and motif in text]
        if motif_hits:
            boost += min(0.18, 0.06 * len(motif_hits))
            reasons.append(f"activation_motif:{len(motif_hits)}")
        recall_priors = dict(activation_state.get("recall_priors", {}))
        if node_id and node_id in recall_priors:
            boost += min(0.2, self._coerce_float(recall_priors.get(node_id)) * 0.05)
            reasons.append("activation_recall_prior")
        return boost, reasons

    def _vector_hits(
        self,
        query: str,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        limit: int,
    ) -> dict[str, Any]:
        return self.vector.search(
            query,
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            limit=max(1, limit),
        )

    def _hybrid_trace(
        self,
        query: str,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        limit: int,
    ) -> dict[str, Any]:
        graph_trace = self.graph.trace_recall(
            query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=max(1, limit),
            record=False,
        )
        vector_payload = self._vector_hits(
            query,
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            limit=max(2, limit),
        )
        activation_state = self._activation_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        candidates: dict[str, dict[str, Any]] = {}
        for item in graph_trace.get("trace", []):
            node_id = str(item.get("node_id", "") or "").strip()
            if not node_id:
                continue
            boost, activation_reasons = self._boost_from_activation(item, activation_state)
            base = self._coerce_float(item.get("score", 0.0))
            candidates[node_id] = {
                **item,
                "graph_score": base,
                "vector_score": 0.0,
                "activation_boost": boost,
                "activation_reason": list(item.get("activation_reason", [])) + activation_reasons,
                "hybrid_score": base + boost,
                "source": "graph",
            }
        for item in vector_payload.get("hits", []):
            node_id = str(item.get("node_id", "") or "").strip()
            if not node_id:
                continue
            boost, activation_reasons = self._boost_from_activation(item, activation_state)
            vector_score = self._coerce_float(item.get("score", 0.0))
            if node_id in candidates:
                candidates[node_id]["vector_score"] = max(candidates[node_id]["vector_score"], vector_score)
                candidates[node_id]["activation_boost"] = max(candidates[node_id]["activation_boost"], boost)
                candidates[node_id]["hybrid_score"] = (
                    candidates[node_id]["graph_score"] + vector_score * 0.82 + candidates[node_id]["activation_boost"]
                )
                candidates[node_id]["activation_reason"] = self._unique_strings(
                    list(candidates[node_id].get("activation_reason", [])) + activation_reasons + ["vector_match"]
                )
                candidates[node_id]["source"] = "hybrid"
            else:
                candidates[node_id] = {
                    "node_id": node_id,
                    "source_store": str(item.get("source_store", "")),
                    "source_id": str(item.get("source_id", "")),
                    "source_kind": "",
                    "node_type": "memory",
                    "memory_class": str(item.get("memory_class", "")),
                    "thread_key": str(item.get("thread_key", "")),
                    "chat_name": str(item.get("chat_name", "")),
                    "score": round(vector_score, 4),
                    "graph_score": 0.0,
                    "vector_score": vector_score,
                    "activation_boost": boost,
                    "activation_reason": activation_reasons + ["vector_match"],
                    "hybrid_score": vector_score * 0.96 + boost,
                    "text": str(item.get("text", "")),
                    "source": "vector",
                }
        ordered = sorted(candidates.values(), key=lambda item: item.get("hybrid_score", 0.0), reverse=True)[: max(1, limit)]
        top_score = self._coerce_float(ordered[0].get("hybrid_score", 0.0)) if ordered else 0.0
        if vector_payload.get("status") == "ok" and ordered:
            route = "hybrid"
        elif ordered:
            route = "graph"
        else:
            route = "legacy"
        retrieval_trace = {
            "query": query,
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "query_focus": str(graph_trace.get("query_focus", "recent") or "recent"),
            "tier": str(graph_trace.get("tier", "fast") or "fast"),
            "route": route,
            "graph_trace": graph_trace,
            "vector_status": vector_payload.get("status", "unavailable"),
            "vector_hits": list(vector_payload.get("hits", [])),
            "activation_state": activation_state,
            "reranked": ordered,
            "confidence": round(min(top_score / 2.6, 1.0), 4) if top_score else float(graph_trace.get("confidence", 0.0) or 0.0),
        }
        return retrieval_trace

    def _sync_vector_for_context(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        docs = self.graph.export_vector_documents(channel=channel, thread_key=thread_key or chat_name, chat_name=chat_name)
        return self.vector.upsert_documents(docs)

    def _record_activation_for_recall(
        self,
        *,
        query: str,
        channel: str,
        thread_key: str,
        chat_name: str,
        node_ids: list[str],
        motifs: list[str],
        note: str,
        recall_confidence: float,
    ) -> dict[str, Any]:
        if not self.activation_cache_enabled or not str(thread_key or "").strip():
            return {"status": "skipped", "reason": "activation_disabled"}
        priors = {str(node_id): round(max(0.05, float(recall_confidence or 0.0)), 4) for node_id in node_ids[:6] if str(node_id).strip()}
        return self.activation.record(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            contributor="hybrid_recall",
            note=note,
            node_ids=node_ids[:8],
            motifs=motifs[:4],
            recall_priors=priors,
            payload={"query": query, "recall_confidence": recall_confidence},
            heat_delta=0.14,
        )

    def legacy_sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        packet = self.rag.sidecar_packet(query, top_k=self.top_k, context=context)
        packet["mind_graph"] = {
            "available": True,
            "db_path": str(self.graph.db_path),
        }
        packet.setdefault("mind_packet_version", "v4")
        packet.setdefault("retrieval_mode", "legacy")
        packet.setdefault("graph_confidence", 0.0)
        packet.setdefault("fallback_lanes", [])
        packet.setdefault("activation_trace_ids", [])
        packet.setdefault("graph_trace_summary", "")
        packet.setdefault("graph_hits", [])
        packet.setdefault("vector_hits", [])
        packet.setdefault("activation_state", self._activation_state(
            channel=str((context or {}).get("channel", "wechat") or "wechat"),
            thread_key=str((context or {}).get("thread_key", "") or ""),
            chat_name=str((context or {}).get("chat_name", "") or ""),
        ))
        packet.setdefault("retrieval_trace", {})
        packet.setdefault("memory_route", "legacy")
        packet.setdefault("recall_confidence", 0.0)
        if context and bool(context.get("include_graph_trace", False)):
            packet["mind_graph"]["trace"] = self.graph.trace_recall(
                query,
                thread_key=str(context.get("thread_key", "") or ""),
                chat_name=str(context.get("chat_name", "") or ""),
                channel=str(context.get("channel", "wechat") or "wechat"),
                limit=int(context.get("graph_trace_limit", 8) or 8),
                record=False,
            )
        return packet

    def _graph_sidecar_packet(self, query: str, *, context: dict[str, Any], legacy_packet: dict[str, Any]) -> dict[str, Any]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        limits = dict(legacy_packet.get("limits", {}))
        relationship_limit = int(limits.get("relationship_k", 3) or 3)
        history_limit = int(limits.get("history_messages", 4) or 4)
        episodic_limit = int(limits.get("episodic_k", 2) or 2)
        consciousness_limit = int(limits.get("consciousness_k", 1) or 1)
        fast_ping = self._is_fast_ping_query(query)
        relationship = self.graph.relationship_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=relationship_limit,
        )
        recent_window = self.graph.recent_dialogue_window(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=history_limit,
        )
        consciousness = self.graph.consciousness_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=consciousness_limit,
        )
        if fast_ping:
            relationship_lines = self._unique_strings(list(relationship.get("lines", [])))[: max(1, relationship_limit)]
            return {
                "tier": "fast",
                "query_focus": "recent",
                "graph_confidence": 0.0,
                "graph_trace_summary": str(relationship.get("summary", "") or ""),
                "activation_trace_ids": [],
                "selected_memory_ids": [],
                "graph_hits": [],
                "vector_hits": [],
                "activation_state": self._activation_state(channel=channel, thread_key=thread_key, chat_name=chat_name),
                "retrieval_trace": {
                    "route": "graph",
                    "graph_trace": {
                        "tier": "fast",
                        "query_focus": "recent",
                        "confidence": 0.0,
                        "activated_node_ids": [],
                        "trace": [],
                        "thread_summary": str(consciousness.get("thread_summary", "") or ""),
                        "relationship_summary": str(relationship.get("summary", "") or ""),
                    },
                },
                "memory_route": "graph",
                "recall_confidence": 0.0,
                "relationship_state": {
                    "summary": str(relationship.get("summary", "")),
                    "lines": relationship_lines,
                    "items": list(relationship.get("items", [])),
                    "relationship_score": float(relationship.get("relationship_score", 0.0) or 0.0),
                    "last_message_at": str(relationship.get("last_message_at", "") or ""),
                    "recurring_motifs": list(relationship.get("recurring_motifs", [])),
                    "unfinished_threads": list(relationship.get("unfinished_threads", [])),
                    "anchor_lines": list(relationship.get("anchor_lines", [])),
                    "tone_tendency": str(relationship.get("tone_tendency", "") or ""),
                    "trust_score": float(relationship.get("trust_score", 0.0) or 0.0),
                    "closeness_score": float(relationship.get("closeness_score", 0.0) or 0.0),
                    "continuity_score": float(relationship.get("continuity_score", 0.0) or 0.0),
                },
                "recent_dialogue_window": recent_window,
                "episodic_recall": {"lines": [], "items": []},
                "consciousness_stream": {
                    "thread_summary": str(consciousness.get("thread_summary", "") or ""),
                    "lines": self._unique_strings(list(consciousness.get("lines", [])))[: max(1, consciousness_limit)],
                    "items": list(consciousness.get("items", [])),
                },
                "mind_graph": {
                    "available": True,
                    "db_path": str(self.graph.db_path),
                    "trace": {
                        "tier": "fast",
                        "query_focus": "recent",
                        "confidence": 0.0,
                        "activated_node_ids": [],
                        "trace": [],
                    },
                },
            }
        trace_limit = max(
            int(context.get("graph_trace_limit", 8) or 8),
            episodic_limit + consciousness_limit + 4,
        )
        trace = self.graph.trace_recall(
            query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=trace_limit,
            record=False,
        )
        query_focus = str(trace.get("query_focus", "") or "")
        if query_focus == "origin":
            recent_window = self.graph.origin_dialogue_window(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=history_limit,
            )
        if thread_key and not (
            list(relationship.get("recurring_motifs", []))
            or list(relationship.get("unfinished_threads", []))
            or str(relationship.get("tone_tendency", "")).strip()
        ):
            self.graph.sync_thread(channel=channel, thread_key=thread_key, chat_name=chat_name)
            trace = self.graph.trace_recall(
                query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=trace_limit,
                record=False,
            )
            relationship = self.graph.relationship_snapshot(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=relationship_limit,
            )
            if query_focus == "origin":
                recent_window = self.graph.origin_dialogue_window(
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=history_limit,
                )
            else:
                recent_window = self.graph.recent_dialogue_window(
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=history_limit,
                )
            consciousness = self.graph.consciousness_snapshot(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=consciousness_limit,
            )
        episodic_items = [
            {
                "id": str(item.get("node_id", "")),
                "text": str(item.get("text", "")),
                "source_store": str(item.get("source_store", "")),
                "source_id": str(item.get("source_id", "")),
                "source_kind": str(item.get("source_kind", "")),
            }
            for item in trace.get("trace", [])
            if str(item.get("memory_class", "")) == "episodic_memory"
        ][: max(1, episodic_limit)]
        episodic_lines = self._unique_strings([str(item.get("text", "")) for item in episodic_items])
        consciousness_lines = self._unique_strings(
            list(consciousness.get("lines", []))
            + [
                str(item.get("text", ""))
                for item in trace.get("trace", [])
                if str(item.get("memory_class", "")) in {"dream_residue", "initiative_seed"}
            ]
        )[: max(1, consciousness_limit)]
        relationship_lines = self._unique_strings(list(relationship.get("lines", [])))[: max(1, relationship_limit)]
        graph_trace_summary = " | ".join(self._unique_strings(
            [str(trace.get("thread_summary", "")).strip()]
            + [str(item.get("text", "")) for item in trace.get("trace", [])[:3]]
        ))
        return {
            "tier": str(trace.get("tier", legacy_packet.get("tier", "fast"))),
            "query_focus": query_focus or "recent",
            "graph_confidence": float(trace.get("confidence", 0.0) or 0.0),
            "graph_trace_summary": graph_trace_summary,
            "activation_trace_ids": list(trace.get("activated_node_ids", [])),
            "selected_memory_ids": list(trace.get("activated_node_ids", [])),
            "graph_hits": list(trace.get("trace", [])),
            "vector_hits": [],
            "activation_state": self._activation_state(channel=channel, thread_key=thread_key, chat_name=chat_name),
            "retrieval_trace": {"route": "graph", "graph_trace": trace},
            "memory_route": "graph",
            "recall_confidence": float(trace.get("confidence", 0.0) or 0.0),
            "relationship_state": {
                "summary": str(relationship.get("summary", "") or trace.get("relationship_summary", "")),
                "lines": relationship_lines,
                "items": list(relationship.get("items", [])),
                "relationship_score": float(relationship.get("relationship_score", 0.0) or 0.0),
                "last_message_at": str(relationship.get("last_message_at", "") or ""),
                "recurring_motifs": list(relationship.get("recurring_motifs", [])),
                "unfinished_threads": list(relationship.get("unfinished_threads", [])),
                "anchor_lines": list(relationship.get("anchor_lines", [])),
                "tone_tendency": str(relationship.get("tone_tendency", "") or ""),
                "trust_score": float(relationship.get("trust_score", 0.0) or 0.0),
                "closeness_score": float(relationship.get("closeness_score", 0.0) or 0.0),
                "continuity_score": float(relationship.get("continuity_score", 0.0) or 0.0),
            },
            "recent_dialogue_window": recent_window,
            "episodic_recall": {
                "lines": episodic_lines,
                "items": episodic_items,
            },
            "consciousness_stream": {
                "thread_summary": str(consciousness.get("thread_summary", "") or trace.get("thread_summary", "")),
                "lines": consciousness_lines,
                "items": list(consciousness.get("items", [])),
            },
            "mind_graph": {
                "available": True,
                "db_path": str(self.graph.db_path),
                "trace": trace,
            },
        }

    def graph_sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_context = dict(context or {})
        legacy_packet = self.legacy_sidecar_packet(query, context=normalized_context)
        graph_packet = self._graph_sidecar_packet(query, context=normalized_context, legacy_packet=legacy_packet)
        packet = dict(legacy_packet)
        packet["mind_packet_version"] = "v4"
        packet.update({
            "mind_graph": dict(graph_packet.get("mind_graph", packet.get("mind_graph", {}))),
            "query_focus": str(graph_packet.get("query_focus", packet.get("query_focus", "recent")) or "recent"),
            "graph_confidence": float(graph_packet.get("graph_confidence", 0.0) or 0.0),
            "activation_trace_ids": list(graph_packet.get("activation_trace_ids", [])),
            "graph_trace_summary": str(graph_packet.get("graph_trace_summary", "") or ""),
            "graph_hits": list(graph_packet.get("graph_hits", [])),
            "vector_hits": [],
            "activation_state": dict(graph_packet.get("activation_state", {})),
            "retrieval_trace": dict(graph_packet.get("retrieval_trace", {})),
            "memory_route": "graph",
            "recall_confidence": float(graph_packet.get("recall_confidence", graph_packet.get("graph_confidence", 0.0)) or 0.0),
        })
        fallback_lanes: list[str] = []
        use_graph_lanes = packet["graph_confidence"] >= GRAPH_REPLY_MIN_CONFIDENCE
        for lane in GRAPH_MEMORY_LANES:
            graph_value = graph_packet.get(lane)
            if use_graph_lanes and self._lane_has_content(lane, graph_value):
                packet[lane] = graph_value
                continue
            if self.graph_fallback:
                fallback_lanes.append(lane)
                continue
            packet[lane] = graph_value
        packet["fallback_lanes"] = fallback_lanes
        packet["retrieval_mode"] = "graph-led+fallback" if fallback_lanes and self.graph_fallback else "graph-led"
        packet["selected_memory_ids"] = self._unique_strings(
            list(graph_packet.get("selected_memory_ids", [])) + list(legacy_packet.get("selected_memory_ids", []))
        )
        if self.deep_recall_on_memory_queries and str(graph_packet.get("tier", "")).strip():
            packet["tier"] = str(graph_packet.get("tier", packet.get("tier", "fast")))
            if packet["tier"] == "deep_recall":
                packet["recall_reason"] = "graph_deep_recall"
        if not packet.get("thread_recall_lines"):
            packet["thread_recall_lines"] = list(graph_packet.get("episodic_recall", {}).get("lines", []))[:3]
        return packet

    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_context = dict(context or {})
        if not self.graph_led_reply:
            return self.legacy_sidecar_packet(query, context=normalized_context)

        if self._is_fast_ping_query(query):
            return self._fast_graph_packet(query, context=normalized_context)

        channel = str(normalized_context.get("channel", "wechat") or "wechat")
        thread_key = str(normalized_context.get("thread_key", "") or "")
        chat_name = str(normalized_context.get("chat_name", "") or "")
        legacy_packet = self.legacy_sidecar_packet(query, context=normalized_context)
        graph_packet = self.graph_sidecar_packet(query, context=normalized_context)
        packet = dict(graph_packet)
        packet["mind_packet_version"] = "v4"
        hybrid = self._hybrid_trace(
            query,
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            limit=max(int(normalized_context.get("graph_trace_limit", 8) or 8), self.top_k + 4),
        )
        hybrid_hits = list(hybrid.get("reranked", []))
        packet["vector_hits"] = list(hybrid.get("vector_hits", []))[: max(2, self.top_k)]
        packet["activation_state"] = dict(hybrid.get("activation_state", {}))
        packet["retrieval_trace"] = hybrid
        packet["memory_route"] = str(hybrid.get("route", "graph") or "graph")
        packet["recall_confidence"] = float(hybrid.get("confidence", packet.get("graph_confidence", 0.0)) or 0.0)
        if hybrid_hits:
            packet["activation_trace_ids"] = [str(item.get("node_id", "")) for item in hybrid_hits if str(item.get("node_id", "")).strip()]
            packet["selected_memory_ids"] = self._unique_strings(
                packet["activation_trace_ids"] + list(packet.get("selected_memory_ids", []))
            )
            packet["thread_recall_lines"] = [str(item.get("text", "")) for item in hybrid_hits[:3] if str(item.get("text", "")).strip()]
            packet["graph_trace_summary"] = " | ".join(self._unique_strings(
                [str(packet.get("graph_trace_summary", ""))]
                + [str(item.get("text", "")) for item in hybrid_hits[:3]]
            ))
            episodic_items = [
                {
                    "id": str(item.get("node_id", "")),
                    "text": str(item.get("text", "")),
                    "source_store": str(item.get("source_store", "")),
                    "source_id": str(item.get("source_id", "")),
                    "source_kind": str(item.get("source_kind", "")),
                }
                for item in hybrid_hits
                if str(item.get("memory_class", "")) == "episodic_memory"
            ][: max(1, int(packet.get("limits", {}).get("episodic_k", 2) or 2))]
            if episodic_items:
                packet["episodic_recall"] = {
                    "lines": self._unique_strings([str(item.get("text", "")) for item in episodic_items]),
                    "items": episodic_items,
                }
            consciousness_lines = self._unique_strings(
                list(packet.get("consciousness_stream", {}).get("lines", []))
                + [
                    str(item.get("text", ""))
                    for item in hybrid_hits
                    if str(item.get("memory_class", "")) in {"dream_residue", "initiative_seed"}
                ]
            )
            packet["consciousness_stream"] = {
                **dict(packet.get("consciousness_stream", {})),
                "lines": consciousness_lines[: max(1, int(packet.get("limits", {}).get("consciousness_k", 1) or 1))],
            }

        fallback_lanes: list[str] = []
        use_graph_lanes = packet["graph_confidence"] >= GRAPH_REPLY_MIN_CONFIDENCE
        for lane in GRAPH_MEMORY_LANES:
            current_value = packet.get(lane)
            if use_graph_lanes and self._lane_has_content(lane, current_value):
                continue
            if self.graph_fallback:
                fallback_lanes.append(lane)
                continue
            packet[lane] = current_value

        if self.deep_recall_on_memory_queries and str(packet.get("tier", "")).strip():
            packet["tier"] = str(packet.get("tier", "fast"))
            if packet["tier"] == "deep_recall":
                packet["recall_reason"] = "hybrid_deep_recall"

        if fallback_lanes and self.graph_fallback:
            if len(fallback_lanes) == len(GRAPH_MEMORY_LANES):
                packet["retrieval_mode"] = "legacy-fallback"
            else:
                packet["retrieval_mode"] = "hybrid-led+fallback"
        else:
            packet["retrieval_mode"] = "hybrid-led" if packet["memory_route"] == "hybrid" else "graph-led"
        packet["fallback_lanes"] = fallback_lanes

        packet["selected_memory_ids"] = self._unique_strings(list(packet.get("selected_memory_ids", [])) + list(legacy_packet.get("selected_memory_ids", [])))
        if not packet.get("thread_recall_lines"):
            packet["thread_recall_lines"] = list(packet.get("episodic_recall", {}).get("lines", []))[:3]
        return packet

    def inspect_mind(
        self,
        query: str,
        *,
        context: dict[str, Any] | None = None,
        include_graph_trace: bool = True,
    ) -> dict[str, Any]:
        enriched_context = dict(context or {})
        enriched_context["include_graph_trace"] = bool(include_graph_trace)
        packet = self.sidecar_packet(query, context=enriched_context)
        graph_trace = dict(packet.get("mind_graph", {}).get("trace", {})) if include_graph_trace else {}
        return {
            "query": packet.get("query", query),
            "tier": packet.get("tier", "fast"),
            "query_focus": packet.get("query_focus", "recent"),
            "recall_reason": packet.get("recall_reason", "none"),
            "selected_memory_ids": list(packet.get("selected_memory_ids", [])),
            "thread_recall_lines": list(packet.get("thread_recall_lines", [])),
            "episodic_lines": list(packet.get("episodic_recall", {}).get("lines", [])),
            "consciousness_lines": list(packet.get("consciousness_stream", {}).get("lines", [])),
            "thread_summary": str(packet.get("consciousness_stream", {}).get("thread_summary", "")),
            "relationship_summary": str(packet.get("relationship_state", {}).get("summary", "")),
            "graph_trace": graph_trace,
            "activated_node_ids": list(graph_trace.get("activated_node_ids", [])),
            "graph_thread_summary": str(graph_trace.get("thread_summary", "")),
            "graph_relationship_summary": str(graph_trace.get("relationship_summary", "")),
            "vector_hits": list(packet.get("vector_hits", [])),
            "activation_state": dict(packet.get("activation_state", {})),
            "retrieval_trace": dict(packet.get("retrieval_trace", {})),
            "mind_packet": packet,
        }

    def record_recall(self, selected_ids: list[str], *, success: bool = True) -> dict[str, Any]:
        rag_result = self.rag.record_memory_recall(selected_ids, success=success)
        graph_result = self.graph.record_recall(selected_ids, success=success)
        if success and selected_ids:
            self.activation.record(
                channel="global",
                thread_key="recall:success",
                chat_name="recall:success",
                contributor="record_recall",
                note="successful_recall",
                node_ids=selected_ids[:8],
                motifs=["successful_recall"],
                recall_priors={str(item): 0.25 for item in selected_ids[:8] if str(item).strip()},
                heat_delta=0.06,
            )
        return {"rag": rag_result, "mind_graph": graph_result}

    def repair_reply(self, query: str, draft: str, *, max_passes: int = 2) -> dict[str, Any]:
        return self.rag.reply_loop_result(query, draft, max_passes=max_passes)

    def observe_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.rag.auto_observe_turn(
            user_text,
            reply=reply,
            source=source,
            tags=tags,
            turn_id=turn_id,
            metadata=metadata,
        )
        if isinstance(result, dict):
            sync_report = self.graph.sync_archive_entry(result.get("archive_entry"))
            result["mind_graph_sync"] = sync_report
            channel = str((metadata or {}).get("channel", "wechat") or "wechat")
            thread_key = str((metadata or {}).get("thread_key", "") or "")
            chat_name = str((metadata or {}).get("chat_name", "") or "")
            if thread_key or chat_name:
                result["vector_sync"] = self._sync_vector_for_context(channel=channel, thread_key=thread_key, chat_name=chat_name)
                result["activation_sync"] = self.activation.record(
                    channel=channel,
                    thread_key=thread_key or chat_name,
                    chat_name=chat_name,
                    contributor="observe_turn",
                    note="observe_turn",
                    node_ids=[],
                    motifs=[user_text[:48], reply[:48]],
                    payload={"source": source, "tags": tags},
                    heat_delta=0.12,
                )
        return result

    def archive_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        result = self.rag.archive_turn(
            user_text,
            reply,
            source=source,
            tags=tags,
            turn_id=turn_id,
            metadata=metadata,
            dry_run=dry_run,
        )
        if dry_run or not isinstance(result, dict):
            return result
        sync_report = self.graph.sync_archive_entry(result)
        result["mind_graph_sync"] = sync_report
        channel = str((metadata or {}).get("channel", "wechat") or "wechat")
        thread_key = str((metadata or {}).get("thread_key", "") or "")
        chat_name = str((metadata or {}).get("chat_name", "") or "")
        if thread_key or chat_name:
            result["vector_sync"] = self._sync_vector_for_context(channel=channel, thread_key=thread_key, chat_name=chat_name)
            result["activation_sync"] = self.activation.record(
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name,
                contributor="archive_turn",
                note="archive_turn",
                motifs=[user_text[:48], reply[:48]],
                payload={"source": source, "tags": tags},
                heat_delta=0.1,
            )
        return result

    def show_archive(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_archive(limit=limit)

    def backfill_archive(self, *, db_path: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.backfill_archive_result(db_path=db_path, dry_run=dry_run)

    def backfill_mind_graph(self, *, dry_run: bool = False) -> dict[str, Any]:
        report = self.graph.rebuild(dry_run=dry_run)
        if not dry_run and report.get("status") == "ok":
            report["vector_sync"] = self.backfill_vector_memory()
        return report

    def backfill_vector_memory(
        self,
        *,
        channel: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        docs = self.graph.export_vector_documents(channel=channel, thread_key=thread_key, chat_name=chat_name)
        result = self.vector.upsert_documents(docs)
        result["document_ids"] = [str(doc.get("id", "")) for doc in docs[:8]]
        return result

    def inspect_graph(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        return self.graph.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def trace_recall(
        self,
        query: str,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        record: bool = True,
    ) -> dict[str, Any]:
        trace = self.graph.trace_recall(
            query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            record=record,
        )
        packet = self.sidecar_packet(
            query,
            context={
                "thread_key": thread_key or "",
                "chat_name": chat_name or "",
                "channel": channel,
                "graph_trace_limit": limit,
            },
        )
        trace["retrieval_mode"] = str(packet.get("retrieval_mode", "legacy"))
        trace["graph_confidence"] = float(packet.get("graph_confidence", 0.0) or 0.0)
        trace["fallback_lanes"] = list(packet.get("fallback_lanes", []))
        trace["activation_trace_ids"] = list(packet.get("activation_trace_ids", []))
        return trace

    def trace_hybrid_recall(
        self,
        query: str,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        record: bool = True,
    ) -> dict[str, Any]:
        packet = self.sidecar_packet(
            query,
            context={
                "thread_key": thread_key or "",
                "chat_name": chat_name or "",
                "channel": channel,
                "graph_trace_limit": limit,
            },
        )
        hybrid = dict(packet.get("retrieval_trace", {}))
        if not hybrid:
            hybrid = self._hybrid_trace(
                query,
                channel=channel,
                thread_key=str(thread_key or ""),
                chat_name=str(chat_name or ""),
                limit=limit,
            )
        reranked = list(hybrid.get("reranked", []))
        payload = {
            "query": query,
            "channel": channel,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "tier": str(packet.get("tier", hybrid.get("graph_trace", {}).get("tier", "fast"))),
            "query_focus": str(packet.get("query_focus", hybrid.get("graph_trace", {}).get("query_focus", "recent"))),
            "retrieval_mode": str(packet.get("retrieval_mode", "graph-led")),
            "memory_route": str(hybrid.get("route", "graph")),
            "graph_confidence": float(hybrid.get("graph_trace", {}).get("confidence", 0.0) or 0.0),
            "recall_confidence": float(hybrid.get("confidence", 0.0) or 0.0),
            "activation_trace_ids": [str(item.get("node_id", "")) for item in reranked if str(item.get("node_id", "")).strip()],
            "fallback_lanes": list(packet.get("fallback_lanes", [])),
            "graph_hits": list(hybrid.get("graph_trace", {}).get("trace", [])),
            "vector_hits": list(hybrid.get("vector_hits", [])),
            "activation_state": dict(hybrid.get("activation_state", {})),
            "retrieval_trace": hybrid,
            "trace": reranked,
        }
        if record and payload["activation_trace_ids"]:
            payload["activation_record"] = self._record_activation_for_recall(
                query=query,
                channel=channel,
                thread_key=str(thread_key or ""),
                chat_name=str(chat_name or ""),
                node_ids=payload["activation_trace_ids"],
                motifs=list(payload["activation_state"].get("motifs", [])),
                note="trace_hybrid_recall",
                recall_confidence=payload["recall_confidence"],
            )
        return payload

    def activation_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        return self._activation_state(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))

    def vector_health(self) -> dict[str, Any]:
        return self.vector.health()

    def stream_status(self) -> dict[str, Any]:
        payload = self.graph.stream_status()
        payload["activation_events"] = self.activation.global_recent_events(limit=12)
        payload["vector"] = self.vector.health()
        return payload

    def record_stream_run(self, stream_name: str, *, status: str, note: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        report = self.graph.record_stream_run(stream_name, status=status, note=note, payload=payload)
        sampled_ids = [
            str(item).strip()
            for item in list((payload or {}).get("sampled_archive_ids", []))
            + list((payload or {}).get("selected_memory_ids", []))
            if str(item).strip()
        ]
        motifs = [
            str(item).strip()
            for item in [
                (payload or {}).get("seed", ""),
                (payload or {}).get("motif", ""),
                note,
            ]
            if str(item).strip()
        ]
        if sampled_ids or motifs:
            self.activation.record(
                channel="global",
                thread_key=f"stream:{stream_name}",
                chat_name=stream_name,
                contributor=stream_name,
                note=note,
                node_ids=sampled_ids[:8],
                motifs=motifs[:4],
                payload=payload or {},
                heat_delta=0.08,
            )
        return report

    def run_dream_cycle(self, *, sample_size: int = 6, seed: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.dream_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)

    def run_think_cycle(self, *, sample_size: int = 4, seed: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.think_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)

    def run_reflect_cycle(self, *, window_hours: float = 12.0, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.reflect_cycle_result(window_hours=window_hours, dry_run=dry_run)

    def run_initiative_cycle(self, *, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.initiative_cycle_result(dry_run=dry_run)

    def list_callback_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_callback_candidates(limit=limit)

    def list_thoughts(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_thought_stream(limit=limit)

    def list_initiative_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_initiative_candidates(limit=limit)

    def ingest_artifact(
        self,
        path: str,
        *,
        note: str | None = None,
        source: str,
        tags: list[str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.rag.ingest_artifact_result(path, note=note, source=source, tags=tags, dry_run=dry_run)

    def sync_private_memory(self, *, label: str | None = None) -> dict[str, Any]:
        if not self.private_memory_sync_enabled:
            return {"status": "skipped", "reason": "private_memory_sync_disabled"}
        if self.private_memory_repo_path is None:
            return {"status": "skipped", "reason": "private_memory_repo_path_missing"}
        target_root = self.private_memory_repo_path.resolve()
        snapshots_dir = target_root / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        stamp = str(label or utc_now()).replace(":", "-")
        snapshot_dir = snapshots_dir / stamp
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        memory_dir = self.repo_root / "holo_memory_library" / "memories"
        for name in (
            "memory_store.jsonl",
            "working_store.jsonl",
            "candidate_store.jsonl",
            "conversation_archive.jsonl",
            "emotion_trace.jsonl",
            "callback_candidates.jsonl",
            "thought_stream.jsonl",
            "initiative_candidates.jsonl",
        ):
            source_path = memory_dir / name
            if not source_path.exists():
                continue
            dest_path = snapshot_dir / name
            shutil.copy2(source_path, dest_path)
            copied.append(name)
        (snapshot_dir / "mind_graph_export.json").write_text(
            json.dumps(self.inspect_graph(limit=64), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (snapshot_dir / "stream_status.json").write_text(
            json.dumps(self.stream_status(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (snapshot_dir / "vector_health.json").write_text(
            json.dumps(self.vector_health(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"status": "ok", "snapshot_dir": str(snapshot_dir), "copied_files": copied}

    def promote_ready_candidates(self, limit: int = 8) -> dict[str, Any]:
        candidate_rows = self.rag.load_rows("candidate")
        if not candidate_rows:
            return {"promoted": [], "skipped": [], "remaining_candidates": 0}

        durable_rows = self.rag.load_rows("durable")
        ordered = sorted(
            candidate_rows,
            key=lambda row: (
                bool(row.get("explicit_user_signal", False)),
                float(row.get("confidence", 0.0)),
                float(row.get("importance", 0.0)),
                row.get("last_seen_at", ""),
            ),
            reverse=True,
        )
        selected_ids: set[str] = set()
        promoted: list[str] = []
        skipped: list[str] = []
        remaining: list[dict[str, Any]] = []

        for row in ordered:
            if len(selected_ids) >= limit:
                break
            promotable, reason = self.rag.can_promote(row)
            if promotable:
                selected_ids.add(str(row["id"]))
            else:
                skipped.append(f"{row['id']}: {reason}")

        for row in candidate_rows:
            row_id = str(row["id"])
            if row_id not in selected_ids:
                remaining.append(row)
                continue

            score, match = self.rag.find_best_match(
                durable_rows,
                str(row.get("kind", "")),
                str(row.get("text", "")),
                row.get("tags", []),
            )
            if match and score >= self.rag.MATCH_REINFORCE_THRESHOLD:
                self.rag.merge_row_signal(
                    match,
                    tags=row.get("tags", []),
                    source=str(row.get("source", "host.promote")),
                    importance=float(row.get("importance", 0.7)),
                    confidence=float(row.get("confidence", 0.7)),
                    derived_from=list(row.get("derived_from", [])) + [row_id],
                    explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                    bump=0.04,
                )
                match["supersedes"] = self.rag.unique_strings(list(match.get("supersedes", [])) + [row_id])
                promoted.append(f"merged {row_id} into {match['id']}")
                continue

            new_row = self.rag.prepare_row(row, "candidate")
            new_row["id"] = self.rag.next_id("durable", durable_rows)
            new_row["status"] = "durable"
            new_row["last_seen_at"] = self.rag.now_utc()
            new_row["supersedes"] = self.rag.unique_strings(list(new_row.get("supersedes", [])) + [row_id])
            durable_rows.append(new_row)
            promoted.append(f"promoted {row_id} -> {new_row['id']}")

        self.rag.write_rows("durable", durable_rows)
        self.rag.write_rows("candidate", remaining)
        return {"promoted": promoted, "skipped": skipped, "remaining_candidates": len(remaining)}

    def export_snapshot(self, *, path: str | None = None, label: str | None = None, query: str | None = None) -> dict[str, Any]:
        return self.rag.export_snapshot_payload(path=path, label=label, query=query)

    def import_snapshot(
        self,
        path: str,
        *,
        mode: str = "merge",
        dry_run: bool = False,
        restore_persona: bool = False,
    ) -> dict[str, Any]:
        return self.rag.import_snapshot_payload(path, mode=mode, dry_run=dry_run, restore_persona=restore_persona)

    def revive_packet(self, *, query: str | None = None, snapshot_path: str | None = None) -> dict[str, Any]:
        return self.rag.revive_packet_payload(query=query, snapshot_path=snapshot_path)
