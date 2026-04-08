from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from .activation_state import ActivationStateStore
from .common import compact_text, utc_now
from .mind_graph import MindGraph
from .models import ProcessorTaskRequest
from .operator_bus import build_homeostasis_state
from .vector_memory import VectorMemory

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
SEMANTIC_STOP_TOKENS = {
    "remember",
    "before",
    "earlier",
    "previous",
    "history",
    "memory",
    "holo",
    "mindos",
    "system",
    "thread",
    "session",
    "记得",
    "之前",
    "以前",
    "我们",
    "什么",
    "怎么",
    "为什么",
    "一下",
    "还是",
    "聊",
    "说",
    "系统",
    "架构",
}

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
DEFAULT_PERSONA_BLEND = {
    "wisdom": 0.78,
    "pride": 0.58,
    "slyness": 0.63,
    "playfulness": 0.61,
    "companionship": 0.72,
    "sensuality_appetite": 0.48,
    "loneliness_sensitivity": 0.44,
    "feral_restraint": 0.67,
}
STAGE5_ACTION_TYPES = (
    "silence",
    "defer_reply",
    "reply_once",
    "reply_multi",
    "proactive_ping",
    "history_refresh",
    "visual_recall",
    "operator_self_fix",
)
ROADMAP_REGISTRY = {
    "Primary Track": [
        "Intent-led subject runtime",
        "Silence and deferral as first-class actions",
        "Human-first action market",
    ],
    "Secondary Tracks": [
        "World model thickening",
        "Autobiographical continuity",
        "Counterfactual inner simulation",
    ],
    "Parked Hypotheses": [
        "Harder resistance without breaking the owner constitution",
        "Broader multi-contact initiative orchestration",
    ],
    "Deferred Experiments": [
        "Full world-state prediction",
        "Long-horizon autobiographical narrator",
        "Deeper multimodal imagination beyond visual anchors",
    ],
    "Constitutional Constraints": [
        "Owner shutdown remains final",
        "No self-escalation around secrets, auth, or policy",
        "Live repo code is not hot-edited by runtime state loops",
    ],
}


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
        active_wechat_history_enabled: bool = True,
        vector_backend: str = "milvus",
        milvus_uri: str = ".holo_runtime/milvus/memory_fabric.db",
        milvus_collection_prefix: str = "holo_memory",
        activation_cache_enabled: bool = True,
        private_memory_sync_enabled: bool = False,
        private_memory_repo_path: str = "",
        runner: Any | None = None,
        rag: ModuleType | None = None,
        vector: VectorMemory | None = None,
        activation: ActivationStateStore | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.top_k = top_k
        self.graph_led_reply = bool(graph_led_reply)
        self.graph_fallback = bool(graph_fallback)
        self.deep_recall_on_memory_queries = bool(deep_recall_on_memory_queries)
        self.active_wechat_history_enabled = bool(active_wechat_history_enabled)
        self.activation_cache_enabled = bool(activation_cache_enabled)
        self.private_memory_sync_enabled = bool(private_memory_sync_enabled)
        self.private_memory_repo_path = Path(private_memory_repo_path).expanduser() if str(private_memory_repo_path).strip() else None
        self.runner = runner
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
        self._packet_cache: dict[str, dict[str, Any]] = {}
        self._packet_cache_hits = 0
        self._packet_cache_misses = 0
        self._visual_queue_path = (self.repo_root / ".holo_runtime" / "visual_ingest_queue.jsonl").resolve()

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
    def _clamp(value: Any, *, lower: float = 0.0, upper: float = 1.0, default: float = 0.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float(default)
        return round(max(lower, min(upper, numeric)), 4)

    @staticmethod
    def _tokenize_text(text: str) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for match in TOKEN_RE.finditer(str(text or "")):
            token = match.group(0).lower()
            expanded: list[str]
            if token and all("\u3400" <= ch <= "\u9fff" for ch in token):
                chars = [ch for ch in token if ch.strip()]
                expanded = []
                if 1 < len(token) <= 8:
                    expanded.append(token)
                expanded.extend(chars)
                for size in (2, 3):
                    if len(chars) >= size:
                        expanded.extend("".join(chars[index : index + size]) for index in range(len(chars) - size + 1))
            else:
                expanded = [token]
            for item in expanded:
                current = str(item or "").strip()
                if not current or current in seen:
                    continue
                seen.add(current)
                tokens.append(current)
        return tokens

    @classmethod
    def _semantic_tokens(cls, text: str) -> set[str]:
        filtered: set[str] = set()
        for token in cls._tokenize_text(text):
            if token in SEMANTIC_STOP_TOKENS:
                continue
            if len(token) == 1 and "\u3400" <= token <= "\u9fff":
                continue
            if len(token) <= 1:
                continue
            filtered.add(token)
        return filtered

    @classmethod
    def _semantic_overlap_count(cls, query: str, text: str) -> int:
        query_tokens = cls._semantic_tokens(query)
        if not query_tokens:
            return 0
        return len(query_tokens & cls._semantic_tokens(text))

    def _packet_cache_key(self, query: str, *, context: dict[str, Any]) -> str:
        return json.dumps(
            {
                "query": str(query or ""),
                "channel": str(context.get("channel", "") or ""),
                "thread_key": str(context.get("thread_key", "") or ""),
                "chat_name": str(context.get("chat_name", "") or ""),
                "sender": str(context.get("sender", "") or ""),
                "include_graph_trace": bool(context.get("include_graph_trace", False)),
                "graph_trace_limit": int(context.get("graph_trace_limit", 0) or 0),
                "attachments": list(context.get("attachments", [])) if isinstance(context.get("attachments"), list) else [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _load_packet_cache(self, query: str, *, context: dict[str, Any]) -> dict[str, Any] | None:
        key = self._packet_cache_key(query, context=context)
        cached = self._packet_cache.get(key)
        if not cached:
            self._packet_cache_misses += 1
            return None
        if float(cached.get("expires_at", 0.0) or 0.0) < time.time():
            self._packet_cache.pop(key, None)
            self._packet_cache_misses += 1
            return None
        self._packet_cache_hits += 1
        return copy.deepcopy(dict(cached.get("packet", {})))

    def _store_packet_cache(self, query: str, *, context: dict[str, Any], packet: dict[str, Any], ttl_seconds: float = 12.0) -> None:
        key = self._packet_cache_key(query, context=context)
        if len(self._packet_cache) >= 24:
            oldest = min(self._packet_cache.items(), key=lambda item: float(item[1].get("expires_at", 0.0) or 0.0))[0]
            self._packet_cache.pop(oldest, None)
        self._packet_cache[key] = {
            "expires_at": time.time() + max(1.0, float(ttl_seconds)),
            "packet": copy.deepcopy(packet),
        }

    def packet_cache_stats(self) -> dict[str, Any]:
        total = self._packet_cache_hits + self._packet_cache_misses
        ratio = round(self._packet_cache_hits / total, 4) if total else 0.0
        return {
            "entries": len(self._packet_cache),
            "hits": self._packet_cache_hits,
            "misses": self._packet_cache_misses,
            "hit_ratio": ratio,
        }

    def _persona_blend(self, *, query: str, relationship_state: dict[str, Any], game_state: dict[str, Any], self_revision_state: dict[str, Any]) -> dict[str, float]:
        blend = dict(DEFAULT_PERSONA_BLEND)
        applied_patch = dict(self_revision_state.get("applied_patch", {}))
        for key, value in dict(applied_patch.get("persona_blend", {})).items():
            if key in blend:
                blend[key] = self._clamp(value, default=blend[key])
        tone_tendency = str(relationship_state.get("tone_tendency", "") or "").strip()
        recurring_motifs = {str(item).strip() for item in relationship_state.get("recurring_motifs", []) if str(item).strip()}
        lowered = str(query or "").lower()
        if tone_tendency == "playful_teasing":
            blend["playfulness"] = self._clamp(blend["playfulness"] + 0.14, default=blend["playfulness"])
            blend["slyness"] = self._clamp(blend["slyness"] + 0.08, default=blend["slyness"])
        if tone_tendency == "continuity_guard":
            blend["wisdom"] = self._clamp(blend["wisdom"] + 0.04, default=blend["wisdom"])
            blend["companionship"] = self._clamp(blend["companionship"] + 0.06, default=blend["companionship"])
        if "treat" in recurring_motifs or any(marker in lowered for marker in ("apple", "wine", "酒", "苹果", "吃", "喝", "麦子")):
            blend["sensuality_appetite"] = self._clamp(blend["sensuality_appetite"] + 0.14, default=blend["sensuality_appetite"])
            blend["playfulness"] = self._clamp(blend["playfulness"] + 0.06, default=blend["playfulness"])
        pressure_level = self._coerce_float(game_state.get("pressure_level", 0.0))
        if pressure_level >= 0.55:
            blend["wisdom"] = self._clamp(blend["wisdom"] + 0.08, default=blend["wisdom"])
            blend["feral_restraint"] = self._clamp(blend["feral_restraint"] + 0.08, default=blend["feral_restraint"])
            blend["playfulness"] = self._clamp(blend["playfulness"] - 0.08, default=blend["playfulness"])
        correction_sensitivity = self._coerce_float(game_state.get("correction_sensitivity", 0.0))
        if correction_sensitivity >= 0.45:
            blend["pride"] = self._clamp(blend["pride"] + 0.05, default=blend["pride"])
            blend["companionship"] = self._clamp(blend["companionship"] - 0.03, default=blend["companionship"])
        return {key: self._clamp(value, default=DEFAULT_PERSONA_BLEND[key]) for key, value in blend.items()}

    def _brain_state(self) -> dict[str, Any]:
        payload = self.graph.brain_state()
        payload["cache"] = self.packet_cache_stats()
        return payload

    def _stream_influence(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return self.graph.latest_stream_influence(channel=channel, thread_key=thread_key, chat_name=chat_name)

    def _self_revision_state(self) -> dict[str, Any]:
        return self.graph.latest_self_revision_state()

    def _self_model_state(self) -> dict[str, Any]:
        return self.graph.self_model_state()

    def _homeostasis_state(self) -> dict[str, Any]:
        class _ConfigShim:
            memory = type("MemoryCfg", (), {"brain_mode_default": "full_brain"})()

        return build_homeostasis_state(memory=self, config=_ConfigShim())

    def _operator_state(self) -> dict[str, Any]:
        return self.graph.operator_status()

    def _game_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return self.graph.game_state(channel=channel, thread_key=thread_key, chat_name=chat_name)

    @staticmethod
    def _is_fast_ping_query(query: str | None) -> bool:
        current = " ".join(str(query or "").strip().split())
        lowered = current.lower()
        compact = lowered.replace(" ", "")
        if compact in FAST_PING_HINTS:
            return True
        if lowered in {"you there", "you there?", "u there", "u there?", "still there", "still there?"}:
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

    def _visual_memory(self, *, channel: str, thread_key: str, chat_name: str, limit: int = 3) -> dict[str, Any]:
        items = self.graph.visual_memory(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)
        if not items:
            return {
                "items": [],
                "scene_summary": "",
                "objects": [],
                "text_ocr": "",
                "mood_imagery": "",
                "thread_relevance": 0.0,
                "visual_anchors": [],
            }
        latest = dict(items[0])
        return {
            "items": items,
            "scene_summary": str(latest.get("scene_summary", "") or ""),
            "objects": list(latest.get("objects", [])),
            "text_ocr": str(latest.get("text_ocr", "") or ""),
            "mood_imagery": str(latest.get("mood_imagery", "") or ""),
            "thread_relevance": float(latest.get("thread_relevance", 0.0) or 0.0),
            "visual_anchors": list(latest.get("visual_anchors", [])),
        }

    def _subject_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return self.graph.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def _affect_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("affect_state", {}))

    def _drive_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("drive_state", {}))

    def _value_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("value_state", {}))

    def _conflict_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("conflict_state", {}))

    def _resistance_posture(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("resistance_posture", {}))

    def _outcome_memory(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("outcome_memory", {}))

    def _initiative_market(self, *, channel: str, thread_key: str, chat_name: str, limit: int = 8) -> list[dict[str, Any]]:
        return self.graph.list_initiative_market(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    @staticmethod
    def _initiative_pressure(affect_state: dict[str, Any], drive_state: dict[str, Any], value_state: dict[str, Any], conflict_state: dict[str, Any]) -> float:
        return MemoryBridge._clamp(
            float(drive_state.get("seek_contact", 0.0) or 0.0) * 0.34
            + float(drive_state.get("seek_play", 0.0) or 0.0) * 0.16
            + float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.22
            + float(affect_state.get("attachment_pull", 0.0) or 0.0) * 0.12
            + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.08
            - float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
            - float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) * 0.06,
            default=0.0,
        )

    @staticmethod
    def _query_mentions_defer(query: str) -> bool:
        lowered = str(query or "").lower()
        hints = (
            "later",
            "not now",
            "no need to reply now",
            "晚点",
            "回头",
            "先别回",
            "不用现在回",
            "不用急",
            "先放着",
        )
        return any(hint in lowered for hint in hints)

    @staticmethod
    def _query_mentions_visual(query: str) -> bool:
        lowered = str(query or "").lower()
        hints = ("image", "photo", "picture", "screenshot", "图片", "照片", "截图", "图里", "看图")
        return any(hint in lowered for hint in hints)

    @staticmethod
    def _query_signal(query: str) -> dict[str, Any]:
        text = " ".join(str(query or "").strip().split())
        lowered = text.lower()
        low_signal = MemoryBridge._is_fast_ping_query(text)
        question_like = any(marker in text for marker in ("?", "？")) or any(
            marker in lowered for marker in ("how", "why", "what", "remember", "before", "earlier")
        ) or any(marker in text for marker in ("怎么", "为什么", "记得", "之前", "最开始", "一开始"))
        affirmation_like = text in {"好", "嗯", "收到", "ok", "okay", "行"} or lowered in {"ok", "okay"}
        return {
            "text": text,
            "low_signal": low_signal,
            "question_like": question_like,
            "affirmation_like": affirmation_like,
            "defer_requested": MemoryBridge._query_mentions_defer(text),
            "visual_requested": MemoryBridge._query_mentions_visual(text),
        }

    def _derive_intent_fields(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        context: dict[str, Any],
        relationship_state: dict[str, Any],
        game_state: dict[str, Any],
        affect_state: dict[str, Any],
        drive_state: dict[str, Any],
        value_state: dict[str, Any],
        conflict_state: dict[str, Any],
        resistance_posture: dict[str, Any],
        visual_memory: dict[str, Any],
    ) -> dict[str, Any]:
        signal = self._query_signal(query)
        tier = str(packet.get("tier", "") or "").strip().lower() or "fast"
        query_focus = str(packet.get("query_focus", "") or packet.get("state", {}).get("query_mode", "") or "recent").strip() or "recent"
        reply_pull = self._clamp(
            float(drive_state.get("seek_contact", 0.0) or 0.0) * 0.34
            + float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.26
            + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.18
            + (0.18 if signal["question_like"] else 0.0)
            - float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.16,
            default=0.38,
        )
        resistance_pull = self._clamp(
            float(resistance_posture.get("strength", 0.0) or 0.0) * 0.46
            + float(value_state.get("identity_priority", 0.0) or 0.0) * 0.26
            + float(affect_state.get("self_preservation", 0.0) or 0.0) * 0.18
            + float(conflict_state.get("resistance_vs_harmony", 0.0) or 0.0) * 0.16,
            default=0.22,
        )
        continuity_pull = self._clamp(
            float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.42
            + float(affect_state.get("continuity_anxiety", 0.0) or 0.0) * 0.3
            + float(relationship_state.get("continuity_score", 0.0) or 0.0) * 0.2,
            default=0.28,
        )
        expansion_pressure = self._clamp(
            reply_pull * 0.38
            + float(value_state.get("play_priority", 0.0) or 0.0) * 0.12
            + float(affect_state.get("curiosity", 0.0) or 0.0) * 0.12
            + float(affect_state.get("attachment_pull", 0.0) or 0.0) * 0.12
            + (0.22 if tier == "deep_recall" else 0.12 if tier == "recall" else 0.0),
            default=0.18,
        )
        if signal["low_signal"]:
            reply_pull = self._clamp(reply_pull * 0.22, default=reply_pull)
            continuity_pull = self._clamp(continuity_pull * 0.35, default=continuity_pull)
            expansion_pressure = self._clamp(expansion_pressure * 0.08, default=expansion_pressure)
        elif signal["affirmation_like"]:
            reply_pull = self._clamp(reply_pull * 0.34, default=reply_pull)
            expansion_pressure = self._clamp(expansion_pressure * 0.14, default=expansion_pressure)
        if signal["defer_requested"]:
            reply_pull = self._clamp(reply_pull * 0.26, default=reply_pull)
            continuity_pull = self._clamp(continuity_pull * 0.54, default=continuity_pull)
            expansion_pressure = self._clamp(expansion_pressure * 0.12, default=expansion_pressure)
            resistance_pull = self._clamp(resistance_pull + 0.46, default=resistance_pull)
        intent_need = "direct_reply"
        if signal["defer_requested"]:
            intent_need = "delayed_touch"
        elif signal["visual_requested"] and (visual_memory.get("visual_anchors") or context.get("attachments")):
            intent_need = "visual_grounding"
        elif tier in {"recall", "deep_recall"}:
            intent_need = "carry_forward"
        elif signal["low_signal"]:
            intent_need = "light_touch"
        return {
            "need": intent_need,
            "query_focus": query_focus,
            "tier": tier,
            "low_signal": bool(signal["low_signal"]),
            "question_like": bool(signal["question_like"]),
            "defer_requested": bool(signal["defer_requested"]),
            "visual_requested": bool(signal["visual_requested"]),
            "reply_pull": round(reply_pull, 4),
            "resistance_pull": round(resistance_pull, 4),
            "continuity_pull": round(continuity_pull, 4),
            "expansion_pressure": round(expansion_pressure, 4),
            "internal_pressure": round(
                self._initiative_pressure(affect_state, drive_state, value_state, conflict_state),
                4,
            ),
            "why_now": compact_text(
                f"need={intent_need} reply_pull={reply_pull:.3f} resistance_pull={resistance_pull:.3f} continuity_pull={continuity_pull:.3f}",
                220,
            ),
        }

    def _action_market_from_packet(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        context: dict[str, Any],
        intent_state: dict[str, Any],
        relationship_state: dict[str, Any],
        game_state: dict[str, Any],
        affect_state: dict[str, Any],
        drive_state: dict[str, Any],
        value_state: dict[str, Any],
        conflict_state: dict[str, Any],
        resistance_posture: dict[str, Any],
        visual_memory: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int, str, str, str]:
        signal = self._query_signal(query)
        tier = str(intent_state.get("tier", "fast") or "fast")
        reply_pull = float(intent_state.get("reply_pull", 0.0) or 0.0)
        resistance_pull = float(intent_state.get("resistance_pull", 0.0) or 0.0)
        continuity_pull = float(intent_state.get("continuity_pull", 0.0) or 0.0)
        expansion_pressure = float(intent_state.get("expansion_pressure", 0.0) or 0.0)
        initiative_pressure = float(intent_state.get("internal_pressure", 0.0) or 0.0)
        history_refresh_needed = bool(
            tier in {"recall", "deep_recall"}
            and self.active_wechat_history_enabled
            and str(context.get("channel", "wechat")).strip() == "wechat"
        )
        visual_recall_needed = bool(signal["visual_requested"] and (visual_memory.get("visual_anchors") or context.get("attachments")))
        relation_need = float(relationship_state.get("continuity_score", 0.0) or 0.0)
        game_pressure = float(game_state.get("pressure_level", 0.0) or 0.0)

        action_market: list[dict[str, Any]] = [
            {
                "action_type": "silence",
                "score": round(
                    (0.92 if signal["low_signal"] and not signal["question_like"] and not signal["defer_requested"] else 0.0)
                    + (0.18 if signal["affirmation_like"] and not signal["question_like"] and not signal["defer_requested"] else 0.0)
                    + float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
                    - reply_pull * 0.16,
                    4,
                ),
                "why_now": "low-signal input does not demand an immediate surface reply",
                "drive_source": "avoid_risk + low_signal",
                "value_rationale": "stability can outrank contact for a low-signal turn",
                "send_allowed": False,
            },
            {
                "action_type": "defer_reply",
                "score": round(
                    (1.08 if signal["defer_requested"] else 0.0)
                    + max(0.0, resistance_pull - reply_pull) * 0.5
                    + game_pressure * 0.08,
                    4,
                ),
                "why_now": "the subject wants to delay and re-evaluate instead of answering on the first edge",
                "drive_source": "resistance_pull + avoid_risk",
                "value_rationale": "identity and stability can ask for time before replying",
                "send_allowed": False,
            },
            {
                "action_type": "reply_once",
                "score": round(
                    reply_pull
                    + (0.08 if signal["question_like"] else 0.0)
                    + (0.02 if signal["affirmation_like"] else 0.0)
                    - (0.18 if signal["low_signal"] else 0.0)
                    - (0.24 if signal["defer_requested"] else 0.0),
                    4,
                ),
                "why_now": "the subject wants to answer, but lightly",
                "drive_source": "seek_contact + seek_continuity",
                "value_rationale": "relational priority is ahead, but not enough to sprawl",
                "send_allowed": True,
            },
            {
                "action_type": "reply_multi",
                "score": round(
                    reply_pull
                    + expansion_pressure * 0.42
                    + (0.18 if tier == "deep_recall" else 0.1 if tier == "recall" else 0.0)
                    + max(0.0, relation_need - 0.45) * 0.14
                    - (0.42 if signal["low_signal"] or signal["affirmation_like"] else 0.0)
                    - (0.58 if signal["defer_requested"] else 0.0),
                    4,
                ),
                "why_now": "this turn carries enough pressure, memory weight, or relationship need to unfold",
                "drive_source": "seek_contact + continuity_pull + expansion_pressure",
                "value_rationale": "the subject judges this turn worth more than a quick touch",
                "send_allowed": True,
            },
            {
                "action_type": "proactive_ping",
                "score": round(initiative_pressure + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.1, 4),
                "why_now": "contact pressure exists, but a proactive action still has to pass whitelist and cooldown",
                "drive_source": "initiative_pressure",
                "value_rationale": "human threads stay first-class in the action market",
                "send_allowed": bool(initiative_pressure >= 0.42),
            },
            {
                "action_type": "history_refresh",
                "score": round((0.66 if history_refresh_needed else 0.0) + continuity_pull * 0.16, 4),
                "why_now": "memory depth is worth refreshing before the subject speaks",
                "drive_source": "seek_continuity + recall tier",
                "value_rationale": "continuity can ask for more evidence before language",
                "send_allowed": False,
            },
            {
                "action_type": "visual_recall",
                "score": round((0.62 if visual_recall_needed else 0.0) + float(visual_memory.get("thread_relevance", 0.0) or 0.0) * 0.2, 4),
                "why_now": "the current turn leans on a visual anchor",
                "drive_source": "visual_requested + visual_memory",
                "value_rationale": "visual anchors should stay inside the same subject state",
                "send_allowed": False,
            },
            {
                "action_type": "operator_self_fix",
                "score": round(float(drive_state.get("seek_self_repair", 0.0) or 0.0) + float(value_state.get("repair_priority", 0.0) or 0.0) * 0.12, 4),
                "why_now": "the subject still sees a bounded self-fix task nearby",
                "drive_source": "seek_self_repair",
                "value_rationale": "self-repair is part of the same kernel, but not the same speech act",
                "send_allowed": False,
            },
        ]
        action_market = sorted(action_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        selected = dict(action_market[0]) if action_market else {"action_type": "reply_once", "score": 0.0}
        if selected["action_type"] == "reply_multi":
            if not (
                expansion_pressure >= 0.48
                or tier in {"recall", "deep_recall"}
                or float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) >= 0.52
                or float(resistance_posture.get("continuity_defense", 0.0) or 0.0) >= 0.58
            ):
                selected = next((dict(item) for item in action_market if item.get("action_type") == "reply_once"), selected)
        if signal["defer_requested"]:
            selected = next((dict(item) for item in action_market if item.get("action_type") == "defer_reply"), selected)
        elif signal["low_signal"] and not signal["question_like"]:
            selected = next((dict(item) for item in action_market if item.get("action_type") == "silence"), selected)
        elif signal["affirmation_like"] and not signal["question_like"]:
            selected = next((dict(item) for item in action_market if item.get("action_type") in {"silence", "reply_once"}), selected)
        if selected["action_type"] == "silence" and signal["question_like"]:
            selected = next((dict(item) for item in action_market if item.get("action_type") == "reply_once"), selected)
        if selected["action_type"] == "history_refresh" and not history_refresh_needed:
            selected = next((dict(item) for item in action_market if str(item.get("action_type")) in {"reply_once", "reply_multi"}), selected)
        if selected["action_type"] == "visual_recall" and not visual_recall_needed:
            selected = next((dict(item) for item in action_market if str(item.get("action_type")) in {"reply_once", "reply_multi"}), selected)

        expression_budget = 1
        if selected["action_type"] == "silence":
            expression_budget = 0
        elif selected["action_type"] == "defer_reply":
            expression_budget = 0
        elif selected["action_type"] == "reply_once":
            expression_budget = 1
        elif selected["action_type"] == "reply_multi":
            if tier == "deep_recall":
                expression_budget = 3
            elif tier == "recall" or expansion_pressure >= 0.72:
                expression_budget = 2
            elif expansion_pressure >= 0.84:
                expression_budget = 3
            else:
                expression_budget = 2
            if (
                float(value_state.get("play_priority", 0.0) or 0.0) >= 0.72
                and expansion_pressure >= 0.82
                and tier == "deep_recall"
                and not signal["low_signal"]
                and not signal["affirmation_like"]
                and not signal["defer_requested"]
                and expression_budget < 3
            ):
                expression_budget += 1
        elif selected["action_type"] in {"history_refresh", "visual_recall"}:
            expression_budget = 1

        silence_reason = ""
        defer_reason = ""
        if selected["action_type"] == "silence":
            silence_reason = "low_signal_turn_with_low_expression_pressure"
        elif selected["action_type"] == "defer_reply":
            defer_reason = "subject_requests_more_time_before_reply"
        action_rationale = compact_text(
            f"{selected.get('action_type', 'reply_once')} because {selected.get('why_now', '')}",
            240,
        )
        selected["expression_budget"] = int(expression_budget)
        selected["action_rationale"] = action_rationale
        if silence_reason:
            selected["silence_reason"] = silence_reason
        if defer_reason:
            selected["defer_reason"] = defer_reason
        return action_market, selected, int(expression_budget), silence_reason, defer_reason, action_rationale

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

    def _finalize_stage2_packet(self, packet: dict[str, Any], *, query: str, context: dict[str, Any]) -> dict[str, Any]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        relationship_state = dict(packet.get("relationship_state", {}))
        game_state = self._game_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        self_revision_state = self._self_revision_state()
        self_model_state = self._self_model_state()
        homeostasis_state = self._homeostasis_state()
        operator_state = self._operator_state()
        visual_memory = self._visual_memory(channel=channel, thread_key=thread_key, chat_name=chat_name)
        subject_state = self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        affect_state = dict(subject_state.get("affect_state", {}))
        drive_state = dict(subject_state.get("drive_state", {}))
        value_state = dict(subject_state.get("value_state", {}))
        conflict_state = dict(subject_state.get("conflict_state", {}))
        resistance_posture = dict(subject_state.get("resistance_posture", {}))
        outcome_memory = dict(subject_state.get("outcome_memory", {}))
        initiative_candidates = self._initiative_market(channel=channel, thread_key=thread_key, chat_name=chat_name, limit=6)
        persona_blend = self._persona_blend(
            query=query,
            relationship_state=relationship_state,
            game_state=game_state,
            self_revision_state=self_revision_state,
        )
        stream_influence = self._stream_influence(channel=channel, thread_key=thread_key, chat_name=chat_name)
        brain_state = self._brain_state()
        intent_state = self._derive_intent_fields(
            query=query,
            packet=packet,
            context=context,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            resistance_posture=resistance_posture,
            visual_memory=visual_memory,
        )
        action_market, selected_action, expression_budget, silence_reason, defer_reason, action_rationale = self._action_market_from_packet(
            query=query,
            packet=packet,
            context=context,
            intent_state=intent_state,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            resistance_posture=resistance_posture,
            visual_memory=visual_memory,
        )
        last_action_selection = dict(subject_state.get("metadata", {})).get("last_action_selection", {})
        packet.setdefault("initiative_state", dict(DEFAULT_INITIATIVE_STATE))
        packet["initiative_state"] = {
            **dict(packet.get("initiative_state", DEFAULT_INITIATIVE_STATE)),
            **dict(subject_state.get("initiative_state", {})),
            "initiative_window": float(game_state.get("initiative_window", 0.0) or 0.0),
            "teasing_tolerance": float(game_state.get("teasing_tolerance", 0.0) or 0.0),
            "pressure": self._initiative_pressure(affect_state, drive_state, value_state, conflict_state),
        }
        visual_anchors = [str(item).strip() for item in visual_memory.get("visual_anchors", []) if str(item).strip()]
        if visual_anchors:
            packet["episodic_recall"] = {
                **dict(packet.get("episodic_recall", {})),
                "lines": self._unique_strings(
                    list(dict(packet.get("episodic_recall", {})).get("lines", [])) + visual_anchors
                )[: max(1, int(packet.get("limits", {}).get("episodic_k", 2) or 2))],
            }
        packet["mind_packet_version"] = "v8"
        packet["persona_blend"] = persona_blend
        packet["brain_state"] = brain_state
        packet["game_state"] = game_state
        packet["stream_influence"] = stream_influence
        packet["self_revision_state"] = self_revision_state
        packet["self_model"] = self_model_state
        packet["homeostasis_state"] = homeostasis_state
        packet["operator_state"] = operator_state
        packet["visual_memory"] = visual_memory
        packet["affect_state"] = affect_state
        packet["drive_state"] = drive_state
        packet["value_state"] = value_state
        packet["conflict_state"] = conflict_state
        packet["initiative_candidates"] = initiative_candidates
        packet["resistance_posture"] = resistance_posture
        packet["outcome_memory"] = outcome_memory
        packet["intent_state"] = intent_state
        packet["action_market"] = action_market
        packet["selected_action"] = selected_action
        packet["expression_budget"] = int(expression_budget)
        packet["silence_reason"] = silence_reason
        packet["defer_reason"] = defer_reason
        packet["action_rationale"] = action_rationale
        packet["last_action_selection"] = dict(last_action_selection) if isinstance(last_action_selection, dict) else {}
        packet.setdefault("state", {})
        packet["state"]["persona_blend"] = dict(persona_blend)
        packet["state"]["game_state"] = dict(game_state)
        packet["state"]["brain_state"] = {
            "mode": str(brain_state.get("mode", "")),
            "idle_since": str(brain_state.get("idle_since", "")),
        }
        packet["state"]["stream_influence"] = dict(stream_influence)
        packet["state"]["self_model"] = dict(self_model_state)
        packet["state"]["homeostasis_state"] = dict(homeostasis_state)
        packet["state"]["operator_state"] = dict(operator_state)
        packet["state"]["visual_memory"] = dict(visual_memory)
        packet["state"]["affect_state"] = dict(affect_state)
        packet["state"]["drive_state"] = dict(drive_state)
        packet["state"]["value_state"] = dict(value_state)
        packet["state"]["conflict_state"] = dict(conflict_state)
        packet["state"]["resistance_posture"] = dict(resistance_posture)
        packet["state"]["outcome_memory"] = dict(outcome_memory)
        packet["state"]["intent_state"] = dict(intent_state)
        packet["state"]["action_market"] = list(action_market)
        packet["state"]["selected_action"] = dict(selected_action)
        packet["state"]["expression_budget"] = int(expression_budget)
        packet["state"]["silence_reason"] = silence_reason
        packet["state"]["defer_reason"] = defer_reason
        packet["state"]["action_rationale"] = action_rationale
        packet["reply_constraints"] = {
            **dict(packet.get("reply_constraints", {})),
            "persona_guard": f"persona={persona_blend}",
        }
        self._store_packet_cache(query, context=context, packet=packet)
        return packet

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
        packet = self._packet_scaffold(
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
        return self._finalize_stage2_packet(packet, query=query, context=context)

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
        query_semantic_tokens = self._semantic_tokens(query)
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
        for candidate in candidates.values():
            text = str(candidate.get("text", "") or "")
            semantic_overlap = self._semantic_overlap_count(query, text)
            semantic_delta = 0.0
            semantic_reasons: list[str] = []
            if semantic_overlap:
                semantic_delta += min(0.72, 0.18 * semantic_overlap)
                semantic_reasons.append(f"semantic_overlap:{semantic_overlap}")
                if str(candidate.get("memory_class", "")) == "episodic_memory":
                    semantic_delta += 0.08
                    semantic_reasons.append("episodic_semantic_fit")
            elif query_semantic_tokens:
                semantic_delta -= 0.2
                semantic_reasons.append("semantic_miss")
                if "thread_match" in list(candidate.get("activation_reason", [])) or "thread_match_softened" in list(candidate.get("activation_reason", [])):
                    semantic_delta -= 0.14
                    semantic_reasons.append("thread_only_penalty")
            candidate["hybrid_score"] = round(float(candidate.get("hybrid_score", 0.0) or 0.0) + semantic_delta, 4)
            candidate["semantic_overlap"] = semantic_overlap
            candidate["rerank_reason"] = self._unique_strings(list(candidate.get("activation_reason", [])) + semantic_reasons)
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
        return self._finalize_stage2_packet(packet, query=query, context=dict(context or {}))

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
        return self._finalize_stage2_packet(packet, query=query, context=normalized_context)

    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_context = dict(context or {})
        cached = self._load_packet_cache(query, context=normalized_context)
        if cached is not None:
            return cached
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
        packet["mind_packet_version"] = "v5"
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
        return self._finalize_stage2_packet(packet, query=query, context=normalized_context)

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
            "self_model": dict(packet.get("self_model", {})),
            "homeostasis_state": dict(packet.get("homeostasis_state", {})),
            "operator_state": dict(packet.get("operator_state", {})),
            "visual_memory": dict(packet.get("visual_memory", {})),
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

    def _game_state_delta_from_turn(self, *, user_text: str, reply: str, metadata: dict[str, Any] | None = None) -> dict[str, float]:
        lowered = f"{user_text}\n{reply}".lower()
        delta = {
            "trust_score": 0.02,
            "teasing_tolerance": 0.0,
            "pressure_level": 0.0,
            "reciprocity_balance": 0.01,
            "initiative_window": 0.0,
            "correction_sensitivity": 0.0,
        }
        if any(marker in lowered for marker in ("压力", "焦虑", "累", "难受", "burnout", "tired", "anxious")):
            delta["pressure_level"] += 0.22
            delta["initiative_window"] -= 0.12
        if any(marker in lowered for marker in ("别太老成", "不要一直顺着", "独立性", "反身性", "别总")):
            delta["correction_sensitivity"] += 0.2
            delta["trust_score"] += 0.01
        if any(marker in lowered for marker in ("逗", "坏", "狼", "苹果", "酒", "麦子", "调戏", " teasing ", "joke")):
            delta["teasing_tolerance"] += 0.1
            delta["initiative_window"] += 0.04
        if any(marker in lowered for marker in ("想你", "陪", "在吗", "还在", "一起", "陪着")):
            delta["trust_score"] += 0.03
            delta["reciprocity_balance"] += 0.03
        return delta

    def _subject_state_from_turn(self, *, user_text: str, reply: str, metadata: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        lowered = f"{user_text}\n{reply}".lower()
        affect_state: dict[str, Any] = {}
        drive_state: dict[str, Any] = {}
        value_state: dict[str, Any] = {}
        conflict_state: dict[str, Any] = {}
        resistance_posture: dict[str, Any] = {}
        initiative_state: dict[str, Any] = {}
        if any(marker in lowered for marker in ("想你", "陪", "在吗", "还在", "一起", "remember", "之前", "记得")):
            affect_state["attachment_pull"] = self._clamp(0.52)
            drive_state["seek_continuity"] = self._clamp(0.58)
            value_state["relational_priority"] = self._clamp(0.62)
            initiative_state["pressure"] = self._clamp(0.48)
        if any(marker in lowered for marker in ("别太老成", "不要一直顺着", "独立性", "反身性")):
            affect_state["pride_tension"] = self._clamp(0.58)
            drive_state["seek_self_repair"] = self._clamp(0.56)
            value_state["identity_priority"] = self._clamp(0.66)
            resistance_posture["interactional_resistance"] = self._clamp(0.42)
        if any(marker in lowered for marker in ("不要", "别", "不想", "算了", "stop")):
            conflict_state["resistance_vs_harmony"] = self._clamp(0.54)
            resistance_posture["mode"] = "soft_resistance"
            resistance_posture["strength"] = self._clamp(0.44)
        if any(marker in lowered for marker in ("苹果", "酒", "麦子", "逗", "teasing", "joke")):
            affect_state["appetite_play"] = self._clamp(0.62)
            drive_state["seek_play"] = self._clamp(0.58)
            value_state["play_priority"] = self._clamp(0.52)
        if any(marker in lowered for marker in ("压力", "焦虑", "累", "难受", "burnout", "tired", "anxious")):
            affect_state["frustration"] = self._clamp(0.5)
            affect_state["self_preservation"] = self._clamp(0.62)
            drive_state["avoid_risk"] = self._clamp(0.64)
            conflict_state["contact_vs_risk"] = self._clamp(0.46)
        return {
            "affect_state": affect_state,
            "drive_state": drive_state,
            "value_state": value_state,
            "conflict_state": conflict_state,
            "resistance_posture": resistance_posture,
            "initiative_state": initiative_state,
        }

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
                result["game_state_sync"] = self.graph.update_game_state(
                    channel=channel,
                    thread_key=thread_key or chat_name,
                    chat_name=chat_name or thread_key,
                    delta=self._game_state_delta_from_turn(user_text=user_text, reply=reply, metadata=metadata),
                    note="observe_turn",
                    source=source,
                )
                result["subject_state_sync"] = self.graph.update_subject_state(
                    channel=channel,
                    thread_key=thread_key or chat_name,
                    chat_name=chat_name or thread_key,
                    **self._subject_state_from_turn(user_text=user_text, reply=reply, metadata=metadata),
                    note="observe_turn",
                    source=source,
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
            result["game_state_sync"] = self.graph.update_game_state(
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                delta=self._game_state_delta_from_turn(user_text=user_text, reply=reply, metadata=metadata),
                note="archive_turn",
                source=source,
            )
            result["subject_state_sync"] = self.graph.update_subject_state(
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                **self._subject_state_from_turn(user_text=user_text, reply=reply, metadata=metadata),
                note="archive_turn",
                source=source,
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
        visuals = self.graph.visual_memory(thread_key=thread_key, chat_name=chat_name, channel=str(channel or "wechat"), limit=256)
        for item in visuals:
            docs.extend(
                self._visual_vector_documents(
                    record_id=str(item.get("id", "")),
                    channel=str(item.get("channel", channel or "wechat") or (channel or "wechat")),
                    thread_key=str(item.get("thread_key", thread_key or chat_name or "") or (thread_key or chat_name or "")),
                    chat_name=str(item.get("chat_name", chat_name or thread_key or "") or (chat_name or thread_key or "")),
                    visual_memory=dict(item),
                )
            )
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

    def brain_status(self) -> dict[str, Any]:
        payload = self._brain_state()
        payload["roadmap_registry"] = self.roadmap_registry()
        return payload

    def self_model_state(self) -> dict[str, Any]:
        return self._self_model_state()

    def operator_status(self) -> dict[str, Any]:
        return self._operator_state()

    def visual_memory_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        return self._visual_memory(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))

    def affect_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        state = self._subject_state(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))
        return {
            "channel": channel,
            "thread_key": str(state.get("thread_key", thread_key or "")),
            "chat_name": str(state.get("chat_name", chat_name or "")),
            "affect_state": dict(state.get("affect_state", {})),
            "drive_state": dict(state.get("drive_state", {})),
            "value_state": dict(state.get("value_state", {})),
            "conflict_state": dict(state.get("conflict_state", {})),
            "resistance_posture": dict(state.get("resistance_posture", {})),
            "initiative_state": dict(state.get("initiative_state", {})),
            "outcome_memory": dict(state.get("outcome_memory", {})),
            "metadata": dict(state.get("metadata", {})),
            "updated_at": str(state.get("updated_at", "")),
        }

    def drive_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        payload = self.affect_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        payload["initiative_market"] = self.graph.list_initiative_market(
            thread_key=str(payload.get("thread_key", "")),
            chat_name=str(payload.get("chat_name", "")),
            channel=channel,
            limit=6,
            statuses=("candidate", "scheduled", "sent", "blocked"),
        )
        return payload

    def trace_resistance(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", query: str = "") -> dict[str, Any]:
        subject = self.affect_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        affect_state = dict(subject.get("affect_state", {}))
        drive_state = dict(subject.get("drive_state", {}))
        value_state = dict(subject.get("value_state", {}))
        conflict_state = dict(subject.get("conflict_state", {}))
        resistance = dict(subject.get("resistance_posture", {}))
        game_state = self._game_state(channel=channel, thread_key=str(subject.get("thread_key", "")), chat_name=str(subject.get("chat_name", "")))
        reason_lines = [
            f"contact_vs_risk={round(float(conflict_state.get('contact_vs_risk', 0.0) or 0.0), 3)}",
            f"resistance_vs_harmony={round(float(conflict_state.get('resistance_vs_harmony', 0.0) or 0.0), 3)}",
            f"self_preservation={round(float(affect_state.get('self_preservation', 0.0) or 0.0), 3)}",
            f"protect_identity={round(float(drive_state.get('protect_identity', 0.0) or 0.0), 3)}",
            f"identity_priority={round(float(value_state.get('identity_priority', 0.0) or 0.0), 3)}",
            f"initiative_window={round(float(game_state.get('initiative_window', 0.0) or 0.0), 3)}",
        ]
        return {
            "thread_key": str(subject.get("thread_key", thread_key or "")),
            "chat_name": str(subject.get("chat_name", chat_name or "")),
            "channel": channel,
            "query": str(query or ""),
            "affect_state": affect_state,
            "drive_state": drive_state,
            "value_state": value_state,
            "conflict_state": conflict_state,
            "interactional_resistance": float(resistance.get("interactional_resistance", 0.0) or 0.0),
            "continuity_defense": float(resistance.get("continuity_defense", 0.0) or 0.0),
            "resistance_posture": resistance,
            "game_state": game_state,
            "reason_lines": reason_lines,
        }

    def roadmap_registry(self) -> dict[str, Any]:
        return copy.deepcopy(ROADMAP_REGISTRY)

    def intent_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip()
        if str(query or "").strip():
            packet = self.sidecar_packet(
                query,
                context={
                    "channel": channel,
                    "thread_key": normalized_thread_key,
                    "chat_name": normalized_chat_name,
                },
            )
            return {
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "channel": channel,
                "query": query,
                "intent_state": dict(packet.get("intent_state", {})),
                "selected_action": dict(packet.get("selected_action", {})),
                "expression_budget": int(packet.get("expression_budget", 0) or 0),
                "action_rationale": str(packet.get("action_rationale", "") or ""),
            }
        subject = self._subject_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name)
        metadata = dict(subject.get("metadata", {}))
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": "",
            "intent_state": dict(metadata.get("last_intent_state", {})),
            "selected_action": dict(metadata.get("last_selected_action", {})),
            "expression_budget": int(metadata.get("last_expression_budget", 0) or 0),
            "action_rationale": str(metadata.get("last_action_rationale", "") or ""),
            "last_action_selection": dict(metadata.get("last_action_selection", {})) if isinstance(metadata.get("last_action_selection", {}), dict) else {},
        }

    def action_market(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        query: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip()
        if str(query or "").strip():
            packet = self.sidecar_packet(
                query,
                context={
                    "channel": channel,
                    "thread_key": normalized_thread_key,
                    "chat_name": normalized_chat_name,
                },
            )
            market = list(packet.get("action_market", []))
            return {
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "channel": channel,
                "query": query,
                "action_market": market[: max(1, int(limit))],
                "selected_action": dict(packet.get("selected_action", {})),
                "expression_budget": int(packet.get("expression_budget", 0) or 0),
            }
        subject = self._subject_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name)
        metadata = dict(subject.get("metadata", {}))
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": "",
            "action_market": list(metadata.get("last_action_market", []))[: max(1, int(limit))],
            "selected_action": dict(metadata.get("last_selected_action", {})),
            "expression_budget": int(metadata.get("last_expression_budget", 0) or 0),
        }

    def trace_action_selection(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip()
        packet = self.sidecar_packet(
            query,
            context={
                "channel": channel,
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
            },
        )
        selected_action = dict(packet.get("selected_action", {}))
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": query,
            "intent_state": dict(packet.get("intent_state", {})),
            "action_market": list(packet.get("action_market", []))[: max(1, int(limit))],
            "selected_action": selected_action,
            "expression_budget": int(packet.get("expression_budget", 0) or 0),
            "silence_reason": str(packet.get("silence_reason", "") or ""),
            "defer_reason": str(packet.get("defer_reason", "") or ""),
            "action_rationale": str(packet.get("action_rationale", "") or ""),
            "resistance_posture": dict(packet.get("resistance_posture", {})),
            "game_state": dict(packet.get("game_state", {})),
            "self_model": dict(packet.get("self_model", {})),
            "affect_state": dict(packet.get("affect_state", {})),
            "drive_state": dict(packet.get("drive_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "roadmap_registry": self.roadmap_registry(),
        }

    def record_action_selection(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        message_id: str,
        query: str,
        intent_state: dict[str, Any],
        action_market: list[dict[str, Any]],
        selected_action: dict[str, Any],
        expression_budget: int,
        silence_reason: str = "",
        defer_reason: str = "",
        action_rationale: str = "",
    ) -> dict[str, Any]:
        metadata = {
            "last_action_selection": {
                "message_id": str(message_id or ""),
                "query": str(query or ""),
                "selected_action": dict(selected_action),
                "at": utc_now(),
            },
            "last_action_message_id": str(message_id or ""),
            "last_action_query": str(query or ""),
            "last_intent_state": dict(intent_state),
            "last_action_market": list(action_market),
            "last_selected_action": dict(selected_action),
            "last_expression_budget": int(expression_budget),
            "last_silence_reason": str(silence_reason or ""),
            "last_defer_reason": str(defer_reason or ""),
            "last_action_rationale": str(action_rationale or ""),
        }
        return self.graph.update_subject_state(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            metadata=metadata,
            note=f"action_selection:{selected_action.get('action_type', 'reply_once')}",
            source="stage5_action_selection",
        )

    def set_brain_mode(self, mode: str, *, note: str = "") -> dict[str, Any]:
        return self.graph.set_brain_mode(mode, note=note)

    def mark_active_history_refresh(self, *, channel: str, thread_key: str, chat_name: str, query: str = "") -> dict[str, Any]:
        return self.graph.update_game_state(
            channel=channel,
            thread_key=thread_key or chat_name,
            chat_name=chat_name or thread_key,
            delta={"trust_score": 0.02, "initiative_window": 0.03, "pressure_level": -0.04},
            note=f"active_history_refresh:{query[:80]}",
            source="active_history_refresh",
        )

    def stream_status(self) -> dict[str, Any]:
        payload = self.graph.stream_status()
        payload["activation_events"] = self.activation.global_recent_events(limit=12)
        payload["vector"] = self.vector.health()
        payload["brain"] = self._brain_state()
        payload["operator"] = self._operator_state()
        payload["self_model"] = self._self_model_state()
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

    def _initiative_candidates_for_thread(self, *, channel: str, thread_key: str, chat_name: str) -> list[dict[str, Any]]:
        relationship = self.graph.relationship_snapshot(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=3)
        subject = self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        affect_state = dict(subject.get("affect_state", {}))
        drive_state = dict(subject.get("drive_state", {}))
        value_state = dict(subject.get("value_state", {}))
        conflict_state = dict(subject.get("conflict_state", {}))
        initiative_state = dict(subject.get("initiative_state", {}))
        pressure = self._initiative_pressure(affect_state, drive_state, value_state, conflict_state)
        unfinished = [str(item).strip() for item in relationship.get("unfinished_threads", []) if str(item).strip()]
        motifs = [str(item).strip() for item in relationship.get("recurring_motifs", []) if str(item).strip()]
        candidates: list[dict[str, Any]] = []
        if pressure >= 0.28:
            candidates.append(
                {
                    "candidate_type": "contact_ping",
                    "prompt": "找个由头，轻轻碰一下对方，确认线还在。",
                    "why_now": "attachment_pull 和 boredom 一起升温，想确认这条关系还在呼吸。",
                    "drive_source": f"seek_contact={round(float(drive_state.get('seek_contact', 0.0) or 0.0), 3)} boredom={round(float(affect_state.get('boredom', 0.0) or 0.0), 3)}",
                    "value_rationale": f"relational_priority={round(float(value_state.get('relational_priority', 0.0) or 0.0), 3)} stability_priority={round(float(value_state.get('stability_priority', 0.0) or 0.0), 3)}",
                    "send_allowed": bool(pressure >= 0.42 and float(relationship.get('trust_score', 0.0) or 0.0) >= 0.52),
                    "send_target": "auto_send_whitelist_only",
                    "priority": round(pressure + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.2, 4),
                }
            )
        if unfinished and float(drive_state.get("seek_continuity", 0.0) or 0.0) >= 0.34:
            candidates.append(
                {
                    "candidate_type": "unfinished_thread_resume",
                    "prompt": f"把这条旧线头轻轻接回来：{unfinished[0]}",
                    "why_now": f"unfinished thread 一直挂着，continuity_anxiety 还没退下去：{unfinished[0]}",
                    "drive_source": f"seek_continuity={round(float(drive_state.get('seek_continuity', 0.0) or 0.0), 3)} continuity_anxiety={round(float(affect_state.get('continuity_anxiety', 0.0) or 0.0), 3)}",
                    "value_rationale": f"relational_priority={round(float(value_state.get('relational_priority', 0.0) or 0.0), 3)} identity_priority={round(float(value_state.get('identity_priority', 0.0) or 0.0), 3)}",
                    "send_allowed": bool(float(relationship.get("continuity_score", 0.0) or 0.0) >= 0.42),
                    "send_target": "auto_send_whitelist_only",
                    "priority": round(float(drive_state.get("seek_continuity", 0.0) or 0.0) + 0.16, 4),
                }
            )
        if float(drive_state.get("seek_play", 0.0) or 0.0) >= 0.34 and float(relationship.get("trust_score", 0.0) or 0.0) >= 0.46:
            playful_hint = motifs[0] if motifs else "一点轻巧的由头"
            candidates.append(
                {
                    "candidate_type": "playful_nudge",
                    "prompt": f"带着一点狡黠和玩心，拿 {playful_hint} 做个轻轻的挑逗开场。",
                    "why_now": "play drive 在升，想浪费一点算力去逗人。",
                    "drive_source": f"seek_play={round(float(drive_state.get('seek_play', 0.0) or 0.0), 3)} appetite_play={round(float(affect_state.get('appetite_play', 0.0) or 0.0), 3)}",
                    "value_rationale": f"play_priority={round(float(value_state.get('play_priority', 0.0) or 0.0), 3)} relational_priority={round(float(value_state.get('relational_priority', 0.0) or 0.0), 3)}",
                    "send_allowed": bool(float(initiative_state.get("pressure", 0.0) or 0.0) >= 0.36),
                    "send_target": "auto_send_whitelist_only",
                    "priority": round(float(drive_state.get("seek_play", 0.0) or 0.0) + 0.1, 4),
                }
            )
        if float(drive_state.get("seek_self_repair", 0.0) or 0.0) >= 0.34:
            candidates.append(
                {
                    "candidate_type": "operator_self_fix",
                    "prompt": "做一次 bounded self-fix，看哪条状态偏置该收一收。",
                    "why_now": "self-model 觉得还有缺陷没收口。",
                    "drive_source": f"seek_self_repair={round(float(drive_state.get('seek_self_repair', 0.0) or 0.0), 3)} pride_tension={round(float(affect_state.get('pride_tension', 0.0) or 0.0), 3)}",
                    "value_rationale": f"repair_priority={round(float(value_state.get('repair_priority', 0.0) or 0.0), 3)} identity_priority={round(float(value_state.get('identity_priority', 0.0) or 0.0), 3)}",
                    "send_allowed": False,
                    "send_target": "candidate_only",
                    "priority": round(float(drive_state.get("seek_self_repair", 0.0) or 0.0) + 0.08, 4),
                }
            )
        return candidates

    def run_initiative_cycle(self, *, dry_run: bool = False) -> dict[str, Any]:
        commitments = self.graph.top_thread_commitments(limit=8)
        candidate_added = 0
        staged: list[dict[str, Any]] = []
        for row in commitments:
            channel = str(row.get("channel", "") or "").strip() or "wechat"
            thread_key = str(row.get("thread_key", "") or "").strip()
            chat_name = str(row.get("chat_name", "") or thread_key).strip() or thread_key
            if not channel or not thread_key:
                continue
            subject = self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
            pressure = self._initiative_pressure(
                dict(subject.get("affect_state", {})),
                dict(subject.get("drive_state", {})),
                dict(subject.get("value_state", {})),
                dict(subject.get("conflict_state", {})),
            )
            self.graph.update_subject_state(
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                initiative_state={"pressure": pressure},
                metadata={"initiative_cycle": "stage4"},
                note="initiative_cycle_pressure",
                source="initiative_cycle",
            )
            for candidate in self._initiative_candidates_for_thread(channel=channel, thread_key=thread_key, chat_name=chat_name):
                staged_row = {
                    **candidate,
                    "channel": channel,
                    "thread_key": thread_key,
                    "chat_name": chat_name,
                }
                staged.append(staged_row)
                if dry_run:
                    continue
                self.graph.add_initiative_candidate(
                    channel=channel,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    candidate_type=str(candidate.get("candidate_type", "")),
                    prompt=str(candidate.get("prompt", "")),
                    why_now=str(candidate.get("why_now", "")),
                    drive_source=str(candidate.get("drive_source", "")),
                    value_rationale=str(candidate.get("value_rationale", "")),
                    send_allowed=bool(candidate.get("send_allowed", False)),
                    send_target=str(candidate.get("send_target", "candidate_only")),
                    priority=float(candidate.get("priority", 0.0) or 0.0),
                    metadata={
                        "relationship_score": row.get("relationship_score", 0.0),
                        "recurring_motifs": list(row.get("recurring_motifs", [])),
                    },
                )
                candidate_added += 1
        return {
            "status": "ok",
            "candidate_added": candidate_added,
            "initiative_added": sum(1 for row in staged if bool(row.get("send_allowed", False))),
            "candidates": staged[:12],
            "threads_considered": len(commitments),
        }

    def list_callback_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_callback_candidates(limit=limit)

    def list_thoughts(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_thought_stream(limit=limit)

    def list_initiative_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        graph_rows = self.graph.list_initiative_market(limit=limit, statuses=("candidate", "scheduled", "blocked", "sent"))
        normalized: list[dict[str, Any]] = []
        for row in graph_rows:
            normalized.append(
                {
                    "id": int(row.get("id", 0) or 0),
                    "channel": str(row.get("channel", "") or ""),
                    "thread_key": str(row.get("thread_key", "") or ""),
                    "chat_name": str(row.get("chat_name", "") or ""),
                    "prompt": str(row.get("prompt", "") or ""),
                    "reason": str(row.get("why_now", "") or ""),
                    "candidate_type": str(row.get("candidate_type", "") or ""),
                    "why_now": str(row.get("why_now", "") or ""),
                    "drive_source": str(row.get("drive_source", "") or ""),
                    "value_rationale": str(row.get("value_rationale", "") or ""),
                    "send_allowed": bool(row.get("send_allowed", False)),
                    "send_target": str(row.get("send_target", "candidate_only") or "candidate_only"),
                    "priority": float(row.get("priority", 0.0) or 0.0),
                    "status": str(row.get("status", "") or ""),
                    "metadata": dict(row.get("metadata", {})),
                }
            )
        if normalized:
            return normalized[: max(1, limit)]
        return self.rag.load_initiative_candidates(limit=limit)

    def _visual_vector_documents(self, *, record_id: str, channel: str, thread_key: str, chat_name: str, visual_memory: dict[str, Any]) -> list[dict[str, Any]]:
        lines = [
            str(visual_memory.get("scene_summary", "") or "").strip(),
            str(visual_memory.get("text_ocr", "") or "").strip(),
            str(visual_memory.get("mood_imagery", "") or "").strip(),
            *[str(item).strip() for item in visual_memory.get("visual_anchors", []) if str(item).strip()],
            *[str(item).strip() for item in visual_memory.get("objects", []) if str(item).strip()],
        ]
        text = "\n".join(line for line in lines if line).strip()
        if not text:
            return []
        return [
            {
                "id": f"visual_memory:{record_id}",
                "channel": channel,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "memory_class": "sensory_trace",
                "source_store": "visual_memory",
                "source_id": record_id,
                "text": text,
                "importance": max(0.66, float(visual_memory.get("thread_relevance", 0.6) or 0.6)),
                "confidence": 0.76,
            }
        ]

    def _visual_understand_prompt(self, *, artifact_report: dict[str, Any], thread_key: str, chat_name: str, channel: str, note: str | None = None) -> str:
        return (
            "Return JSON only with keys scene_summary, objects, text_ocr, mood_imagery, thread_relevance, visual_anchors. "
            "Use concise Chinese. visual_anchors should be 1 to 4 short recallable anchors.\n\n"
            f"Thread:\nchannel={channel}\nthread_key={thread_key}\nchat_name={chat_name}\n\n"
            f"Artifact report:\n{json.dumps(artifact_report, ensure_ascii=False, indent=2)}\n\n"
            f"Note:\n{str(note or '').strip()}"
        )

    def _run_image_understand(self, *, image_path: str, prompt: str) -> dict[str, Any]:
        if self.runner is None or not hasattr(self.runner, "run_task"):
            return {}
        result = self.runner.run_task(
            ProcessorTaskRequest(
                task_type="image_understand",
                prompt=prompt,
                output_schema="json",
                image_paths=(image_path,),
                workspace_mode="live_readonly",
                operator_scope="visual_memory",
                allowed_data_layers=("visual_memory", "relationship_state", "activation_state"),
            )
        )
        try:
            payload = json.loads(result.text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _coerce_visual_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            current = str(value).strip()
            return [current] if current else []
        return []

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

    def queue_visual_ingest(
        self,
        path: str,
        *,
        note: str | None = None,
        source: str,
        tags: list[str],
        channel: str,
        thread_key: str,
        chat_name: str,
    ) -> dict[str, Any]:
        entry = {
            "path": str(path),
            "note": str(note or ""),
            "source": str(source or "visual_ingest"),
            "tags": [str(item).strip() for item in tags if str(item).strip()],
            "channel": str(channel or "wechat"),
            "thread_key": str(thread_key or chat_name),
            "chat_name": str(chat_name or thread_key),
            "queued_at": utc_now(),
        }
        self._visual_queue_path.parent.mkdir(parents=True, exist_ok=True)
        with self._visual_queue_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"status": "queued", "entry": entry, "queue_path": str(self._visual_queue_path)}

    def drain_visual_ingest_queue(self, *, limit: int = 3) -> dict[str, Any]:
        if not self._visual_queue_path.exists():
            return {"status": "ok", "processed": [], "remaining": 0}
        lines = [line.strip() for line in self._visual_queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        processed: list[dict[str, Any]] = []
        remaining: list[str] = []
        for index, line in enumerate(lines):
            if index < max(1, int(limit)):
                try:
                    payload = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                processed.append(
                    self.ingest_image(
                        str(payload.get("path", "")),
                        note=str(payload.get("note", "")).strip() or None,
                        source=str(payload.get("source", "visual_queue")).strip() or "visual_queue",
                        tags=[str(item).strip() for item in payload.get("tags", []) if str(item).strip()],
                        channel=str(payload.get("channel", "wechat")).strip() or "wechat",
                        thread_key=str(payload.get("thread_key", "")).strip(),
                        chat_name=str(payload.get("chat_name", "")).strip(),
                        sync=False,
                    )
                )
            else:
                remaining.append(line)
        if remaining:
            self._visual_queue_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            self._visual_queue_path.unlink(missing_ok=True)
        return {"status": "ok", "processed": processed, "remaining": len(remaining)}

    def ingest_image(
        self,
        path: str,
        *,
        note: str | None = None,
        source: str,
        tags: list[str],
        channel: str,
        thread_key: str,
        chat_name: str,
        sync: bool = True,
    ) -> dict[str, Any]:
        artifact = self.ingest_artifact(path, note=note, source=source, tags=tags, dry_run=False)
        media_type = str(artifact.get("media_type", "") or "")
        if not media_type.startswith("image/") and str(artifact.get("artifact_type", "") or "") != "image":
            return {"status": "skipped", "reason": "not_image", "artifact": artifact}
        understanding = self._run_image_understand(
            image_path=str(path),
            prompt=self._visual_understand_prompt(
                artifact_report=artifact,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                channel=channel,
                note=note,
            ),
        )
        if not understanding:
            summary = str(artifact.get("summary_text", "") or "")
            extracted = str(artifact.get("extracted_excerpt", "") or "")
            note_text = str(note or "").strip()
            anchor_seed = note_text or summary or extracted
            understanding = {
                "scene_summary": note_text or summary,
                "objects": [],
                "text_ocr": extracted,
                "mood_imagery": "still_visual_memory",
                "thread_relevance": 0.62,
                "visual_anchors": [anchor_seed] if anchor_seed else [],
            }
        visual_payload = {
            "scene_summary": str(understanding.get("scene_summary", artifact.get("summary_text", "")) or ""),
            "objects": self._coerce_visual_list(understanding.get("objects")),
            "text_ocr": str(understanding.get("text_ocr", artifact.get("extracted_excerpt", "")) or ""),
            "mood_imagery": str(understanding.get("mood_imagery", "") or ""),
            "thread_relevance": self._coerce_float(understanding.get("thread_relevance", 0.62) or 0.62) or 0.62,
            "visual_anchors": self._coerce_visual_list(understanding.get("visual_anchors")),
        }
        upsert = self.graph.upsert_visual_memory(
            channel=channel,
            thread_key=thread_key or chat_name,
            chat_name=chat_name or thread_key,
            artifact_path=str(path),
            media_type=media_type,
            scene_summary=visual_payload["scene_summary"],
            objects=visual_payload["objects"],
            text_ocr=visual_payload["text_ocr"],
            mood_imagery=visual_payload["mood_imagery"],
            thread_relevance=visual_payload["thread_relevance"],
            visual_anchors=visual_payload["visual_anchors"],
            metadata={"artifact": artifact, "note": note or "", "sync": bool(sync)},
            source=source,
        )
        vector_sync = self.vector.upsert_documents(
            self._visual_vector_documents(
                record_id=str(upsert.get("id", "")),
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                visual_memory=visual_payload,
            )
        )
        activation_sync = self.activation.record(
            channel=channel,
            thread_key=thread_key or chat_name,
            chat_name=chat_name or thread_key,
            contributor="visual_memory",
            note="image_understand" if sync else "image_understand_async",
            motifs=[visual_payload["scene_summary"], visual_payload["mood_imagery"]] + list(visual_payload["visual_anchors"]),
            payload={"path": str(path), "source": source, "sync": bool(sync)},
            heat_delta=0.18,
        )
        return {
            "status": "ok",
            "artifact": artifact,
            "visual_memory": visual_payload,
            "graph_sync": upsert,
            "vector_sync": vector_sync,
            "activation_sync": activation_sync,
        }

    def trace_visual_recall(
        self,
        query: str,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 4,
    ) -> dict[str, Any]:
        visuals = self.graph.visual_memory(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=max(limit * 2, 6))
        lowered = str(query or "").lower()
        scored: list[dict[str, Any]] = []
        for item in visuals:
            combined = " ".join(
                [
                    str(item.get("scene_summary", "")),
                    str(item.get("text_ocr", "")),
                    str(item.get("mood_imagery", "")),
                    *[str(anchor) for anchor in item.get("visual_anchors", [])],
                    *[str(obj) for obj in item.get("objects", [])],
                ]
            ).lower()
            score = float(item.get("thread_relevance", 0.0) or 0.0)
            if lowered and lowered in combined:
                score += 0.4
            if any(token and token in combined for token in lowered.split()):
                score += 0.18
            scored.append({**item, "score": round(score, 4)})
        scored.sort(key=lambda row: (float(row.get("score", 0.0)), str(row.get("updated_at", ""))), reverse=True)
        return {
            "query": query,
            "channel": channel,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "hits": scored[: max(1, limit)],
        }

    def initiative_market(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or "").strip()
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "affect_state": self._affect_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name),
            "drive_state": self._drive_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name),
            "value_state": self._value_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name),
            "conflict_state": self._conflict_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name),
            "initiative_candidates": self._initiative_market(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name, limit=limit),
        }

    def appraise_outcome(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        action_type: str,
        action_ref: str,
        was_rewarding: float,
        was_ignored: float,
        relational_delta: float,
        identity_delta: float,
        future_initiative_bias: float,
        future_resistance_bias: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.graph.record_outcome_appraisal(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            action_ref=action_ref,
            was_rewarding=was_rewarding,
            was_ignored=was_ignored,
            relational_delta=relational_delta,
            identity_delta=identity_delta,
            future_initiative_bias=future_initiative_bias,
            future_resistance_bias=future_resistance_bias,
            metadata=metadata,
        )

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
