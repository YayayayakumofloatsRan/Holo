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
from typing import Any, Iterable

from .activation_state import ActivationStateStore
from .bionic_memory_scheduler import build_bionic_memory_schedule
from .common import compact_text, utc_now
from .mind_graph import MindGraph, TASK_WORLD_CUE_TO_OBJECT, _normalize_thread_key
from .models import ProcessorTaskRequest
from .operator_bus import build_homeostasis_state
from .policies import MEMORY_BRIDGE_POLICY
from .policy_runtime.action_market import apply_policy_sedimentation_overlay, apply_scene_state_overlay, apply_simulation_overlay, apply_situational_field_overlay
from .policy_runtime.action_simulation import simulate_action_candidate as _simulate_action_candidate_impl
from .policy_runtime.counterfactuals import fast_counterfactual_set as _fast_counterfactual_set_impl
from .policy_runtime.world_calibration_trace import expression_budget_summary
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

GRAPH_MEMORY_LANES = MEMORY_BRIDGE_POLICY.graph_memory_lanes
GRAPH_REPLY_MIN_CONFIDENCE = MEMORY_BRIDGE_POLICY.graph_reply_min_confidence
LOOKUP_HINTS = (
    "search",
    "look up",
    "latest",
    "official",
    "movie",
    "film",
    "actor",
    "director",
    "imdb",
    "wikipedia",
    "查一下",
    "搜一下",
    "搜索",
    "最新",
    "官网",
    "电影",
    "演员",
    "导演",
    "百科",
)
LOCAL_MEMORY_HINTS = (
    "remember",
    "before",
    "earlier",
    "previous",
    "history",
    "memory",
    "mindos",
    "holo",
    "记得",
    "之前",
    "回忆",
    "我们",
    "心智",
    "系统",
)
FAST_PING_HINTS = {"在吗", "你在吗", "嗯", "好", "收到", "说吧", "继续", "接着说", "ok", "okay"}

UNRESOLVED_REFERENCE_HINTS = (
    "that",
    "this",
    "it",
    "above",
    "earlier",
    "刚才",
    "刚刚",
    "那个",
    "这个",
    "那件事",
    "这件事",
    "上面",
    "前面",
)
EXPLICIT_MEMORY_HINTS = (
    "remember",
    "history",
    "before",
    "earlier",
    "previous",
    "你还记得",
    "还记得",
    "聊天记录",
    "之前",
    "前面",
    "刚才",
)

DEFAULT_IDENTITY_CORE_LINES = list(MEMORY_BRIDGE_POLICY.default_identity_core_lines)
DEFAULT_REPLY_CONSTRAINT_LINES = list(MEMORY_BRIDGE_POLICY.default_reply_constraint_lines)
DEFAULT_HUMAN_RECALL_STYLE = MEMORY_BRIDGE_POLICY.default_human_recall_style
DEFAULT_INITIATIVE_STATE = dict(MEMORY_BRIDGE_POLICY.default_initiative_state)
DEFAULT_EMOTION_STATE = dict(MEMORY_BRIDGE_POLICY.default_emotion_state)
DEFAULT_EMOTION_LINES = list(MEMORY_BRIDGE_POLICY.default_emotion_lines)
DEFAULT_PERSONA_BLEND = dict(MEMORY_BRIDGE_POLICY.default_persona_blend)
STAGE6_ACTION_TYPES = MEMORY_BRIDGE_POLICY.stage6_action_types
ROADMAP_REGISTRY = {
    "Primary Track": [
        "autobiographical continuity",
        "long-horizon goals",
        "identity/goal-led deliberation",
    ],
    "Secondary Tracks": [
        "richer desire shaping",
        "stronger negotiated will",
    ],
    "Parked Hypotheses": [
        "broader multi-agent social world",
        "deeper imagination beyond current recall",
    ],
    "Deferred Experiments": [
        "open-ended world modeling",
        "explicit multi-step planning",
        "richer subjective report layer",
    ],
    "Constitutional Constraints": [
        "owner shutdown remains final",
        "no self-escalation around secrets, auth, or policy",
        "live repo code is not hot-edited by runtime state loops",
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
        stage25_max_hot_threads_per_cycle: int = 6,
        stage25_per_thread_pulse_budget: int = 2,
        stage25_skip_cold_without_pressure: bool = True,
        stage25_max_dense_working_set_threads: int = 8,
        stage25_cooldown_seconds_by_stream: dict[str, int] | None = None,
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
        self.stage25_budget = {
            "max_hot_threads_per_cycle": max(1, int(stage25_max_hot_threads_per_cycle)),
            "per_thread_pulse_budget": max(1, int(stage25_per_thread_pulse_budget)),
            "skip_cold_without_pressure": bool(stage25_skip_cold_without_pressure),
            "max_dense_working_set_threads": max(1, int(stage25_max_dense_working_set_threads)),
            "cooldown_seconds_by_stream": {
                "maintenance_stream": 600,
                "association_stream": 900,
                "social_stream": 1200,
                "deep_dream_cycle": 3600,
                **{
                    str(key).strip(): max(1, int(value))
                    for key, value in dict(stage25_cooldown_seconds_by_stream or {}).items()
                    if str(key).strip()
                },
            },
        }
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
        packet = dict(cached.get("packet", {}))
        stage19 = dict(packet.get("stage19", {})) if isinstance(packet.get("stage19", {}), dict) else {}
        stale_after = str(stage19.get("stale_after", "") or "")
        if bool(stage19.get("frontier_used_for_thread", False)) and stale_after and stale_after <= utc_now():
            self._packet_cache.pop(key, None)
            self._packet_cache_misses += 1
            return None
        stage20 = dict(packet.get("stage20", {})) if isinstance(packet.get("stage20", {}), dict) else {}
        if bool(stage20.get("temporal_visible", False)):
            self._packet_cache.pop(key, None)
            self._packet_cache_misses += 1
            return None
        self._packet_cache_hits += 1
        return copy.deepcopy(packet)

    def _store_packet_cache(self, query: str, *, context: dict[str, Any], packet: dict[str, Any], ttl_seconds: float = 12.0) -> None:
        key = self._packet_cache_key(query, context=context)
        if len(self._packet_cache) >= 24:
            oldest = min(self._packet_cache.items(), key=lambda item: float(item[1].get("expires_at", 0.0) or 0.0))[0]
            self._packet_cache.pop(oldest, None)
        self._packet_cache[key] = {
            "expires_at": time.time() + max(1.0, float(ttl_seconds)),
            "packet": copy.deepcopy(packet),
        }

    def clear_packet_cache(self) -> None:
        self._packet_cache.clear()

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
        applied_patch_raw = self_revision_state.get("applied_patch", {}) if isinstance(self_revision_state, dict) else {}
        applied_patch = dict(applied_patch_raw) if isinstance(applied_patch_raw, dict) else {}
        persona_patch_raw = applied_patch.get("persona_blend", {})
        persona_patch = dict(persona_patch_raw) if isinstance(persona_patch_raw, dict) else {}
        for key, value in persona_patch.items():
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

    def _autobiographical_state(self) -> dict[str, Any]:
        return self.graph.autobiographical_state()

    def _goal_state(self) -> dict[str, Any]:
        return self.graph.goal_state()

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

    @staticmethod
    def _query_has_unresolved_reference(query: str | None) -> bool:
        text = " ".join(str(query or "").strip().split())
        lowered = text.lower()
        return any(str(hint).lower() in lowered for hint in UNRESOLVED_REFERENCE_HINTS)

    @staticmethod
    def _meaningful_char_count(query: str | None) -> int:
        return sum(1 for ch in str(query or "") if ch.isalnum() or "\u3400" <= ch <= "\u9fff")

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
                "spatial_refs": [],
                "uncertainty_markers": [],
                "revisit_needed": False,
                "perceptual_density": "",
            }
        latest = dict(items[0])
        metadata = dict(latest.get("metadata", {})) if isinstance(latest.get("metadata", {}), dict) else {}
        return {
            "items": items,
            "scene_summary": str(latest.get("scene_summary", "") or ""),
            "objects": list(latest.get("objects", [])),
            "text_ocr": str(latest.get("text_ocr", "") or ""),
            "mood_imagery": str(latest.get("mood_imagery", "") or ""),
            "thread_relevance": float(latest.get("thread_relevance", 0.0) or 0.0),
            "visual_anchors": list(latest.get("visual_anchors", [])),
            "spatial_refs": self._coerce_visual_list(metadata.get("spatial_refs", [])),
            "uncertainty_markers": self._coerce_visual_list(metadata.get("uncertainty_markers", [])),
            "revisit_needed": bool(metadata.get("revisit_needed", False)),
            "perceptual_density": str(metadata.get("perceptual_density", "") or ""),
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

    def _world_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return dict(self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name).get("world_state", {}))

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
            + MindGraph.metric_value(affect_state.get("attachment_pull", 0.0), default=0.0) * 0.12
            + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.08
            - float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
            - float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) * 0.06,
            default=0.0,
        )

    @staticmethod
    def _initiative_gate_hint(confidence: float) -> str:
        if confidence >= 0.62:
            return "warm"
        if confidence >= 0.48:
            return "tentative"
        return "cold"

    @staticmethod
    def _initiative_candidate_fields(confidence: float, *, send_allowed: bool = True) -> dict[str, Any]:
        bounded_confidence = MemoryBridge._clamp(confidence, default=0.0)
        return {
            "send_allowed": bool(send_allowed),
            "initiative_confidence": round(bounded_confidence, 4),
            "gate_hint": MemoryBridge._initiative_gate_hint(bounded_confidence),
            "override_priority": round(bounded_confidence, 4),
        }

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
        search_requested = any(hint in lowered for hint in LOOKUP_HINTS) or any(hint in text for hint in LOOKUP_HINTS)
        local_memory_requested = any(hint in lowered for hint in LOCAL_MEMORY_HINTS) or any(hint in text for hint in LOCAL_MEMORY_HINTS)
        factual_lookup = bool(
            search_requested
            and not local_memory_requested
            and any(
                token in lowered
                for token in (
                    "who",
                    "what",
                    "when",
                    "where",
                    "movie",
                    "film",
                    "actor",
                    "director",
                    "latest",
                    "official",
                    "imdb",
                    "wikipedia",
                    "search",
                    "look up",
                )
            )
        )
        return {
            "text": text,
            "low_signal": low_signal,
            "question_like": question_like,
            "affirmation_like": affirmation_like,
            "defer_requested": MemoryBridge._query_mentions_defer(text),
            "visual_requested": MemoryBridge._query_mentions_visual(text),
            "search_requested": search_requested,
            "local_memory_requested": local_memory_requested,
            "factual_lookup": factual_lookup,
        }

    def _contact_world_model(self, world_state: dict[str, Any], *, chat_name: str, thread_key: str) -> dict[str, Any]:
        contact_models = dict(world_state.get("contact_models", {}))
        return dict(contact_models.get(str(chat_name or thread_key or ""), {}))

    def _thread_world_model(self, world_state: dict[str, Any], *, thread_key: str) -> dict[str, Any]:
        thread_models = dict(world_state.get("thread_models", {}))
        return dict(thread_models.get(str(thread_key or ""), {}))

    def _empirical_action_overlay(
        self,
        *,
        action_type: str,
        channel: str,
        thread_key: str,
        chat_name: str,
        signal: dict[str, Any],
        predicted_outcome: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str], float]:
        bucket = MindGraph.action_calibration_bucket(
            action_type=action_type,
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            metadata={
                "low_signal": signal.get("low_signal", False),
                "question_like": signal.get("question_like", False),
                "defer_requested": signal.get("defer_requested", False),
                "predicted_risk": predicted_outcome.get("predicted_risk", 0.0),
                "relationship_pressure": max(0.0, float(predicted_outcome.get("predicted_relational_delta", 0.0) or 0.0)),
            },
        )
        summary = self.graph.action_calibration_summary(
            channel=channel,
            thread_key=bucket["thread_key_bucket"],
            chat_name=chat_name,
            action_type=action_type,
            scenario_bucket=bucket["scenario_bucket"],
        )
        calibration = dict(summary.get("top", {}))
        if not calibration:
            return {}, bucket, 0.0
        confidence = self._clamp(calibration.get("confidence", 0.0), default=0.0)
        support_scale = min(1.0, float(calibration.get("support_count", 0) or 0) / 6.0)
        response_fit = max(0.0, 1.0 - float(calibration.get("response_quality_mae", 0.0) or 0.0))
        relational_fit = max(0.0, 1.0 - float(calibration.get("relational_delta_mae", 0.0) or 0.0))
        risk_penalty = float(calibration.get("ignored_rate", 0.0) or 0.0) * 0.45 + float(calibration.get("correction_rate", 0.0) or 0.0) * 0.35 + float(calibration.get("risk_mae", 0.0) or 0.0) * 0.2
        positive = (response_fit * 0.5 + relational_fit * 0.3 + max(0.0, 1.0 - float(calibration.get("avg_reply_latency", 0.0) or 0.0) / 3600.0) * 0.2)
        empirical_overlay_delta = round((positive - risk_penalty - 0.45) * confidence * support_scale * 0.35, 4)
        return calibration, bucket, empirical_overlay_delta

    @staticmethod
    def _chapter_keyword_score(text: str, *, current_chapter: str) -> float:
        lowered = str(text or "").lower()
        chapter = str(current_chapter or "").lower()
        if not chapter:
            return 0.0
        hits = 0
        for token in ("continuity", "repair", "lively", "warm", "contact", "goal", "memory", "alive"):
            if token in chapter and token in lowered:
                hits += 1
        return min(0.18, hits * 0.06)

    def _goal_identity_alignment(
        self,
        *,
        action_type: str,
        query: str,
        intent_state: dict[str, Any],
        relationship_state: dict[str, Any],
        world_state: dict[str, Any],
        autobiographical_state: dict[str, Any],
        goal_state: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        active_goals = [dict(item) for item in goal_state.get("active_goals", []) if isinstance(item, dict)]
        current_chapter = str(autobiographical_state.get("current_chapter", "") or "")
        identity_arc = str(autobiographical_state.get("identity_arc", "") or "")
        stable_traits = {str(item).strip().lower() for item in autobiographical_state.get("stable_traits", []) if str(item).strip()}
        unresolved = {str(item).strip().lower() for item in autobiographical_state.get("unresolved_tensions", []) if str(item).strip()}
        thread_key = str(context.get("thread_key", "") or "")
        goal_hits: list[str] = []
        goal_alignment_score = 0.0
        for goal in active_goals:
            goal_type = str(goal.get("goal_type", "") or "")
            target_thread = str(goal.get("target_thread", "") or "")
            priority = self._coerce_float(goal.get("priority", 0.0))
            boost = 0.0
            if goal_type == "identity_maintenance" and action_type in {"reply_once", "history_refresh", "continuity_defense", "operator_self_fix"}:
                boost = 0.12 + priority * 0.08
            elif goal_type == "relationship_continuity" and action_type in {"reply_once", "defer_reply", "history_refresh", "proactive_ping"}:
                boost = 0.14 + priority * 0.08
                if target_thread and target_thread == thread_key:
                    boost += 0.06
            elif goal_type == "recall_quality" and action_type in {"history_refresh", "reply_once", "reply_multi"}:
                boost = 0.1 + priority * 0.06
            elif goal_type == "liveliness_balance" and action_type in {"reply_once", "proactive_ping", "counter_offer"}:
                boost = 0.08 + priority * 0.06
            elif goal_type == "self_repair" and action_type in {"operator_self_fix", "defer_reply"}:
                boost = 0.1 + priority * 0.06
            elif goal_type == "contact_maintenance" and action_type in {"reply_once", "proactive_ping", "defer_reply"}:
                boost = 0.08 + priority * 0.06
            elif goal_type == "cost_discipline" and action_type in {"reply_once", "defer_reply", "operator_self_fix", "history_refresh"}:
                boost = 0.06 + priority * 0.05
            elif goal_type == "routing_resilience" and action_type in {"operator_self_fix", "defer_reply", "external_lookup"}:
                boost = 0.05 + priority * 0.05
            elif goal_type == "cache_warmth" and action_type in {"history_refresh", "reply_once", "defer_reply"}:
                boost = 0.06 + priority * 0.05
            elif goal_type == "expression_calibration" and action_type in {"reply_once", "defer_reply", "operator_self_fix", "continuity_defense"}:
                boost = 0.05 + priority * 0.05
            if action_type == "silence" and goal_type in {"relationship_continuity", "contact_maintenance"}:
                boost -= 0.14
            if action_type == "reply_multi" and str(intent_state.get("low_signal", False)).lower() in {"true", "1"}:
                boost -= 0.16
            if action_type == "reply_multi" and goal_type in {"cost_discipline", "cache_warmth", "expression_calibration"}:
                boost -= 0.08
            if boost > 0.01:
                goal_hits.append(goal_type)
            goal_alignment_score += boost
        goal_alignment_score = self._clamp(goal_alignment_score, lower=-1.0, upper=1.0, default=0.0)

        identity_consistency_score = 0.0
        if "continuity-minded" in stable_traits and action_type in {"reply_once", "history_refresh", "continuity_defense"}:
            identity_consistency_score += 0.14
        if "curious" in stable_traits and action_type in {"external_lookup", "history_refresh"}:
            identity_consistency_score += 0.08
        if "protective" in stable_traits and action_type in {"defer_reply", "continuity_defense", "push_back"}:
            identity_consistency_score += 0.09
        if "wry" in stable_traits and action_type in {"reply_once", "counter_offer", "proactive_ping"}:
            identity_consistency_score += 0.06
        if "stiffness_drift" in unresolved and action_type == "reply_multi":
            identity_consistency_score -= 0.08
        if "cache_coldness" in unresolved and action_type == "history_refresh":
            identity_consistency_score += 0.05
        if "expression_calibration_gap" in unresolved and action_type == "reply_multi":
            identity_consistency_score -= 0.08
        if "cache_reuse_weak" in unresolved and action_type == "history_refresh":
            identity_consistency_score += 0.05
        if str(intent_state.get("low_signal", False)).lower() in {"true", "1"} and action_type == "reply_multi":
            identity_consistency_score -= 0.14
        identity_consistency_score += self._chapter_keyword_score(action_type, current_chapter=current_chapter)
        identity_consistency_score = self._clamp(identity_consistency_score, lower=-1.0, upper=1.0, default=0.0)

        chapter_relevance = compact_text(
            current_chapter
            or ("keeping continuity alive" if float(relationship_state.get("continuity_score", 0.0) or 0.0) >= 0.45 else "staying lively without sprawling"),
            160,
        )
        goal_rationale = compact_text(
            f"{action_type} aligns with goals: {', '.join(goal_hits) if goal_hits else 'no strong goal pull'}",
            180,
        )
        identity_rationale = compact_text(
            f"{action_type} fits the current identity arc because {chapter_relevance or identity_arc or 'it stays inside the same self-shape'}",
            180,
        )
        self_narrative_hint = compact_text(
            f"这一步更像是在 {chapter_relevance} 这一章里继续往前挪，而不是另起炉灶。",
            180,
        )
        return {
            "goal_alignment_score": round(goal_alignment_score, 4),
            "identity_consistency_score": round(identity_consistency_score, 4),
            "goal_rationale": goal_rationale,
            "identity_rationale": identity_rationale,
            "chapter_rationale": chapter_relevance,
            "chapter_relevance": chapter_relevance,
            "self_narrative_hint": self_narrative_hint,
        }

    def _simulate_action_candidate(
        self,
        *,
        action: dict[str, Any],
        query: str,
        intent_state: dict[str, Any],
        relationship_state: dict[str, Any],
        game_state: dict[str, Any],
        affect_state: dict[str, Any],
        drive_state: dict[str, Any],
        value_state: dict[str, Any],
        conflict_state: dict[str, Any],
        world_state: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return _simulate_action_candidate_impl(
            self,
            action=action,
            query=query,
            intent_state=intent_state,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            world_state=world_state,
            context=context,
        )

    def _fast_counterfactual_set(
        self,
        *,
        action_market: list[dict[str, Any]],
        query: str,
        intent_state: dict[str, Any],
        relationship_state: dict[str, Any],
        game_state: dict[str, Any],
        affect_state: dict[str, Any],
        drive_state: dict[str, Any],
        value_state: dict[str, Any],
        conflict_state: dict[str, Any],
        world_state: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return _fast_counterfactual_set_impl(
            self,
            action_market=action_market,
            query=query,
            intent_state=intent_state,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            world_state=world_state,
            context=context,
        )

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
        world_state: dict[str, Any],
        resistance_posture: dict[str, Any],
        visual_memory: dict[str, Any],
    ) -> dict[str, Any]:
        signal = self._query_signal(query)
        capability_context = dict(context.get("capability_context", {})) if isinstance(context.get("capability_context"), dict) else {}
        tool_requests = [dict(item) for item in capability_context.get("tool_requests", []) if isinstance(item, dict)]
        tool_names = {str(item.get("name", "")).strip() for item in tool_requests if str(item.get("name", "")).strip()}
        lookup_ready = "external_lookup" in tool_names or "web_preview" in tool_names or bool(signal["factual_lookup"])
        tier = str(packet.get("tier", "") or "").strip().lower() or "fast"
        query_focus = str(packet.get("query_focus", "") or packet.get("state", {}).get("query_mode", "") or "recent").strip() or "recent"
        if signal["factual_lookup"]:
            query_focus = "external_facts"
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
        stage20_temporal = dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else {}
        temporal_due = bool(stage20_temporal.get("commitment_due", False))
        temporal_resume_cue = compact_text(str(stage20_temporal.get("resume_cue", "") or ""), 180)
        temporal_pressure = self._clamp(stage20_temporal.get("temporal_pressure", 0.0), default=0.0)
        if bool(stage20_temporal.get("temporal_visible", False)) and not signal["factual_lookup"] and not signal["search_requested"]:
            continuity_pull = self._clamp(continuity_pull + temporal_pressure + (0.08 if temporal_due else 0.0), default=continuity_pull)
        expansion_pressure = self._clamp(
            reply_pull * 0.38
            + float(value_state.get("play_priority", 0.0) or 0.0) * 0.12
            + MindGraph.metric_value(affect_state.get("curiosity", 0.0), default=0.0) * 0.12
            + MindGraph.metric_value(affect_state.get("attachment_pull", 0.0), default=0.0) * 0.12
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
        elif signal["factual_lookup"]:
            intent_need = "ground_with_external_facts"
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
            "search_requested": bool(signal["search_requested"]),
            "local_memory_requested": bool(signal["local_memory_requested"]),
            "factual_lookup": bool(signal["factual_lookup"]),
            "lookup_ready": bool(lookup_ready),
            "temporal_resume": bool(stage20_temporal.get("temporal_visible", False)),
            "temporal_due": bool(temporal_due),
            "temporal_resume_cue": temporal_resume_cue,
            "due_followup_keys": list(stage20_temporal.get("due_followup_keys", []))[:8],
            "temporal_pressure": round(temporal_pressure, 4),
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
        world_state: dict[str, Any],
        resistance_posture: dict[str, Any],
        visual_memory: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int, str, str, str, list[dict[str, Any]], dict[str, Any]]:
        signal = self._query_signal(query)
        capability_context = dict(context.get("capability_context", {})) if isinstance(context.get("capability_context"), dict) else {}
        tool_requests = [dict(item) for item in capability_context.get("tool_requests", []) if isinstance(item, dict)]
        planned_lookup = next((item for item in tool_requests if str(item.get("name", "")).strip() == "external_lookup"), {})
        lookup_ready = bool(intent_state.get("lookup_ready", False))
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
        stage20_temporal = dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else dict(packet.get("stage20", {})) if isinstance(packet.get("stage20", {}), dict) else {}
        temporal_due = bool(intent_state.get("temporal_due", False)) and not bool(intent_state.get("factual_lookup", False))
        temporal_resume_cue = compact_text(str(intent_state.get("temporal_resume_cue", "") or stage20_temporal.get("resume_cue", "") or ""), 160)
        temporal_pressure = self._clamp(intent_state.get("temporal_pressure", stage20_temporal.get("temporal_pressure", 0.0)), default=0.0)
        temporal_source_action = str(dict(stage20_temporal.get("resume_candidate", {})).get("source_action_type", "") or "")
        temporal_context = {
            "stage": "stage20",
            "due": bool(temporal_due),
            "resume_cue": temporal_resume_cue,
            "due_followup_keys": list(intent_state.get("due_followup_keys", stage20_temporal.get("due_followup_keys", [])))[:8],
            "source_action_type": temporal_source_action,
        }

        action_market: list[dict[str, Any]] = [
            {
                "action_type": "silence",
                "score": round(
                    (0.92 if signal["low_signal"] and not signal["question_like"] and not signal["defer_requested"] else 0.0)
                    + (0.18 if signal["affirmation_like"] and not signal["question_like"] and not signal["defer_requested"] else 0.0)
                    + float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
                    + (0.04 if temporal_due and temporal_pressure < 0.12 else 0.0)
                    - reply_pull * 0.16,
                    4,
                ),
                "why_now": "low-signal input does not demand an immediate surface reply",
                "drive_source": "avoid_risk + low_signal",
                "value_rationale": "stability can outrank contact for a low-signal turn",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "defer_reply",
                "score": round(
                    (1.08 if signal["defer_requested"] else 0.0)
                    + max(0.0, resistance_pull - reply_pull) * 0.5
                    + game_pressure * 0.08
                    + (0.08 if temporal_due and temporal_pressure >= 0.18 else 0.0),
                    4,
                ),
                "why_now": "the subject wants to delay and re-evaluate instead of answering on the first edge",
                "drive_source": "resistance_pull + avoid_risk",
                "value_rationale": "identity and stability can ask for time before replying",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "reply_once",
                "score": round(
                    reply_pull
                    + (0.08 if signal["question_like"] else 0.0)
                    + (0.02 if signal["affirmation_like"] else 0.0)
                    + (0.18 if temporal_due else 0.0)
                    + min(0.12, temporal_pressure * 0.4)
                    - (0.18 if signal["low_signal"] else 0.0)
                    - (0.24 if signal["defer_requested"] else 0.0),
                    4,
                ),
                "why_now": temporal_resume_cue or "the subject wants to answer, but lightly",
                "drive_source": "seek_contact + seek_continuity",
                "value_rationale": "relational priority is ahead, but not enough to sprawl",
                "send_allowed": True,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "reply_multi",
                "score": round(
                    reply_pull
                    + expansion_pressure * 0.42
                    + (0.18 if tier == "deep_recall" else 0.1 if tier == "recall" else 0.0)
                    + (0.06 if temporal_due and not signal["low_signal"] else 0.0)
                    + max(0.0, relation_need - 0.45) * 0.14
                    - (0.46 if bool(intent_state.get("factual_lookup", False)) else 0.0)
                    - (0.42 if signal["low_signal"] or signal["affirmation_like"] else 0.0)
                    - (0.58 if signal["defer_requested"] else 0.0),
                    4,
                ),
                "why_now": "this turn carries enough pressure, memory weight, or relationship need to unfold",
                "drive_source": "seek_contact + continuity_pull + expansion_pressure",
                "value_rationale": "the subject judges this turn worth more than a quick touch",
                "send_allowed": True,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "external_lookup",
                "score": round(
                    ((1.18 if bool(intent_state.get("factual_lookup", False)) and lookup_ready else 0.0))
                    + ((0.26 if bool(intent_state.get("search_requested", False)) and lookup_ready else 0.0))
                    + max(0.0, 0.4 - float(packet.get("graph_confidence", 0.0) or 0.0)) * 0.24,
                    4,
                ),
                "why_now": compact_text(
                    str(planned_lookup.get("reason", "") or "the subject wants external evidence before speaking"),
                    200,
                ),
                "drive_source": "factual_lookup + curiosity",
                "value_rationale": "factual uncertainty can justify looking outward before language",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "proactive_ping",
                "score": round(initiative_pressure + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.1, 4),
                "why_now": "contact pressure exists, but a proactive action still has to pass whitelist and cooldown",
                "drive_source": "initiative_pressure",
                "value_rationale": "human threads stay first-class in the action market",
                **self._initiative_candidate_fields(
                    initiative_pressure + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.1,
                    send_allowed=bool(initiative_pressure >= 0.28),
                ),
                "temporal_context": temporal_context,
            },
            {
                "action_type": "history_refresh",
                "score": round((0.66 if history_refresh_needed else 0.0) + continuity_pull * 0.16 + (0.22 if temporal_due and temporal_source_action == "history_refresh" else 0.0), 4),
                "why_now": temporal_resume_cue if temporal_source_action == "history_refresh" else "memory depth is worth refreshing before the subject speaks",
                "drive_source": "seek_continuity + recall tier",
                "value_rationale": "continuity can ask for more evidence before language",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "visual_recall",
                "score": round((0.62 if visual_recall_needed else 0.0) + float(visual_memory.get("thread_relevance", 0.0) or 0.0) * 0.2, 4),
                "why_now": "the current turn leans on a visual anchor",
                "drive_source": "visual_requested + visual_memory",
                "value_rationale": "visual anchors should stay inside the same subject state",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "operator_self_fix",
                "score": round(float(drive_state.get("seek_self_repair", 0.0) or 0.0) + float(value_state.get("repair_priority", 0.0) or 0.0) * 0.12, 4),
                "why_now": "the subject still sees a bounded self-fix task nearby",
                "drive_source": "seek_self_repair",
                "value_rationale": "self-repair is part of the same kernel, but not the same speech act",
                "send_allowed": False,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "push_back",
                "score": round(
                    max(0.0, resistance_pull - reply_pull * 0.12)
                    + float(conflict_state.get("resistance_vs_harmony", 0.0) or 0.0) * 0.18,
                    4,
                ),
                "why_now": "the subject wants to answer with friction instead of pure compliance",
                "drive_source": "resistance_pull + identity_priority",
                "value_rationale": "subjectivity allows a small push back when harmony is not the only value",
                "send_allowed": True,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "counter_offer",
                "score": round(
                    float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) * 0.28
                    + float(value_state.get("identity_priority", 0.0) or 0.0) * 0.18,
                    4,
                ),
                "why_now": "the subject leans toward a negotiated alternative instead of a straight yes",
                "drive_source": "conflict + protect_identity",
                "value_rationale": "continuing the relation can still allow a different proposal",
                "send_allowed": True,
                "temporal_context": temporal_context,
            },
            {
                "action_type": "continuity_defense",
                "score": round(
                    float(resistance_posture.get("continuity_defense", 0.0) or 0.0) * 0.72
                    + continuity_pull * 0.18,
                    4,
                ),
                "why_now": "the subject wants to protect continuity before yielding",
                "drive_source": "continuity_defense + seek_continuity",
                "value_rationale": "continuity can outrank short-term compliance",
                "send_allowed": True,
                "temporal_context": temporal_context,
            },
        ]
        action_market = sorted(action_market, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        counterfactual_set = self._fast_counterfactual_set(
            action_market=action_market,
            query=query,
            intent_state=intent_state,
            relationship_state=relationship_state,
            game_state=game_state,
            affect_state=affect_state,
            drive_state=drive_state,
            value_state=value_state,
            conflict_state=conflict_state,
            world_state=world_state,
            context=context,
        )
        simulation_by_action = {str(item.get("action_type", "")): dict(item) for item in counterfactual_set}
        world_thread = self._thread_world_model(world_state, thread_key=str(context.get("thread_key", "") or ""))
        action_market = apply_simulation_overlay(
            self,
            action_market=action_market,
            simulation_by_action=simulation_by_action,
            world_thread=world_thread,
        )
        action_market = apply_scene_state_overlay(
            self,
            action_market=action_market,
            context=context,
        )
        action_market = apply_situational_field_overlay(
            self,
            action_market=action_market,
            context=context,
        )
        action_market = apply_policy_sedimentation_overlay(
            self,
            action_market=action_market,
            context=context,
            world_state=world_state,
        )
        selected = dict(action_market[0]) if action_market else {"action_type": "reply_once", "score": 0.0}
        if bool(intent_state.get("factual_lookup", False)) and lookup_ready and selected["action_type"] not in {"silence", "defer_reply"}:
            lookup_candidate = next((dict(item) for item in action_market if item.get("action_type") == "external_lookup"), None)
            if lookup_candidate and float(lookup_candidate.get("score", 0.0) or 0.0) >= max(0.48, float(selected.get("score", 0.0) or 0.0) - 0.06):
                selected = lookup_candidate
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
        if selected["action_type"] == "external_lookup" and not lookup_ready:
            selected = next((dict(item) for item in action_market if str(item.get("action_type")) in {"reply_once", "reply_multi"}), selected)
        selected_prediction = dict(simulation_by_action.get(str(selected.get("action_type", "")), {}))
        reply_budget_fit, stiffness_risk = expression_budget_summary(self, world_state=world_state)

        expression_budget = 1
        if selected["action_type"] == "silence":
            expression_budget = 0
        elif selected["action_type"] == "defer_reply":
            expression_budget = 0
        elif selected["action_type"] == "reply_once":
            expression_budget = 1
        elif selected["action_type"] == "reply_multi":
            multi_prediction = dict(simulation_by_action.get("reply_multi", {}))
            once_prediction = dict(simulation_by_action.get("reply_once", {}))
            multi_advantage = (
                float(multi_prediction.get("predicted_response_quality", 0.0) or 0.0)
                + float(multi_prediction.get("predicted_relational_delta", 0.0) or 0.0)
                - float(multi_prediction.get("predicted_risk", 0.0) or 0.0)
                - float(multi_prediction.get("predicted_regret", 0.0) or 0.0)
            ) - (
                float(once_prediction.get("predicted_response_quality", 0.0) or 0.0)
                + float(once_prediction.get("predicted_relational_delta", 0.0) or 0.0)
                - float(once_prediction.get("predicted_risk", 0.0) or 0.0)
                - float(once_prediction.get("predicted_regret", 0.0) or 0.0)
            )
            if signal["low_signal"] or signal["affirmation_like"] or multi_advantage < 0.08:
                selected = next((dict(item) for item in action_market if item.get("action_type") == "reply_once"), selected)
                expression_budget = 1
            elif tier == "deep_recall" and expansion_pressure >= 0.74:
                expression_budget = 3
            elif tier == "recall" or expansion_pressure >= 0.72:
                expression_budget = 2
            else:
                expression_budget = 1
        elif selected["action_type"] in {"history_refresh", "visual_recall", "external_lookup"}:
            expression_budget = 1
        elif selected["action_type"] in {"push_back", "counter_offer", "continuity_defense"}:
            expression_budget = 1 if expansion_pressure < 0.68 else 2
        if selected["action_type"] in {"reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"}:
            if stiffness_risk >= 0.58:
                expression_budget = min(expression_budget, 1)
            elif reply_budget_fit >= 0.72 and expansion_pressure >= 0.66:
                expression_budget = min(3, expression_budget + 1)

        silence_reason = ""
        defer_reason = ""
        if selected["action_type"] == "silence":
            silence_reason = "low_signal_turn_with_low_expression_pressure"
        elif selected["action_type"] == "defer_reply":
            defer_reason = "subject_requests_more_time_before_reply"
        action_rationale = compact_text(
            f"{selected.get('action_type', 'reply_once')} because {selected.get('why_now', '')}; sim={selected_prediction.get('simulation_rationale', '')}; expr_fit={reply_budget_fit:.2f} stiffness={stiffness_risk:.2f}",
            240,
        )
        selected["expression_budget"] = int(expression_budget)
        selected["action_rationale"] = action_rationale
        if silence_reason:
            selected["silence_reason"] = silence_reason
        if defer_reason:
            selected["defer_reason"] = defer_reason
        return action_market, selected, int(expression_budget), silence_reason, defer_reason, action_rationale, counterfactual_set, selected_prediction

    def _stage21_policy_trace(self, *, action_market: list[dict[str, Any]], selected_action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        applied: list[dict[str, Any]] = []
        visible = False
        scenario_bucket = ""
        for candidate in action_market:
            sediment = dict(candidate.get("policy_sedimentation", {})) if isinstance(candidate.get("policy_sedimentation", {}), dict) else {}
            if sediment:
                visible = visible or int(sediment.get("available_count", 0) or 0) > 0
            if not scenario_bucket and str(candidate.get("policy_scenario_bucket", "") or ""):
                scenario_bucket = str(candidate.get("policy_scenario_bucket", "") or "")
            if not bool(sediment.get("applied", False)):
                continue
            applied.append(
                {
                    "action_type": str(candidate.get("action_type", "") or ""),
                    "delta": round(float(candidate.get("policy_sedimentation_delta", 0.0) or 0.0), 4),
                    "policy_ids": list(sediment.get("policy_ids", []))[:6],
                    "rollback_handles": list(sediment.get("rollback_handles", []))[:6],
                    "scenario_bucket": str(sediment.get("scenario_bucket", "") or ""),
                }
            )
        return {
            "sediments_visible": bool(visible or applied),
            "sediment_bias_applied": bool(applied),
            "applied_policy_keys": [policy_id for item in applied for policy_id in list(item.get("policy_ids", []))][:8],
            "scenario_bucket": scenario_bucket,
            "hard_gate_preserved": True,
            "negotiated_will_mode": "active_soft",
            "selected_action": str(selected_action.get("action_type", "") or ""),
            "applied": applied,
            "thread_key": str(context.get("thread_key", "") or ""),
            "chat_name": str(context.get("chat_name", "") or ""),
            "channel": str(context.get("channel", "wechat") or "wechat"),
        }

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
        autobiographical_state = self._autobiographical_state()
        goal_state = self._goal_state()
        homeostasis_state = self._homeostasis_state()
        operator_state = self._operator_state()
        visual_memory = self._visual_memory(channel=channel, thread_key=thread_key, chat_name=chat_name)
        subject_state = self._subject_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        affect_state = dict(subject_state.get("affect_state", {}))
        drive_state = dict(subject_state.get("drive_state", {}))
        value_state = dict(subject_state.get("value_state", {}))
        conflict_state = dict(subject_state.get("conflict_state", {}))
        world_state = dict(subject_state.get("world_state", {}))
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
        active_state = dict(packet.get("active_thread_state", {})) if isinstance(packet.get("active_thread_state", {}), dict) else dict(context.get("active_thread_state", {})) if isinstance(context.get("active_thread_state", {}), dict) else {}
        stage20_temporal = dict(packet.get("stage20", {})) if isinstance(packet.get("stage20", {}), dict) else dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else {}
        stage24_scene = dict(packet.get("stage24", {})) if isinstance(packet.get("stage24", {}), dict) else self._stage24_scene_packet(active_state)
        stage25_dense = dict(packet.get("stage25", {})) if isinstance(packet.get("stage25", {}), dict) else dict(context.get("stage25_dense_working_set", {})) if isinstance(context.get("stage25_dense_working_set", {}), dict) else {}
        stage26_task_world = dict(packet.get("stage26", {})) if isinstance(packet.get("stage26", {}), dict) else dict(context.get("stage26_task_world", {})) if isinstance(context.get("stage26_task_world", {}), dict) else {}
        visual_field = self._stage28_visual_field(visual_memory)
        situational_field = self._stage28_situational_field(
            query=query,
            packet=packet,
            context=context,
            active_state=active_state,
            visual_field=visual_field,
            stage20=stage20_temporal,
            stage24=stage24_scene,
            stage25=stage25_dense,
            stage26=stage26_task_world,
            homeostasis_state=homeostasis_state,
            affect_state=affect_state,
            drive_state=drive_state,
        )
        stage28 = self._stage28_packet(situational_field=situational_field, visual_field=visual_field)
        packet["visual_field"] = visual_field
        packet["situational_field"] = situational_field
        packet["stage28"] = stage28
        context = {
            **context,
            "visual_field": visual_field,
            "situational_field": situational_field,
            "stage28_situational_field": situational_field,
        }
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
            world_state=world_state,
            resistance_posture=resistance_posture,
            visual_memory=visual_memory,
        )
        action_market, selected_action, expression_budget, silence_reason, defer_reason, action_rationale, counterfactual_set, selected_prediction = self._action_market_from_packet(
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
            world_state=world_state,
            resistance_posture=resistance_posture,
            visual_memory=visual_memory,
        )
        stage8_market: list[dict[str, Any]] = []
        for candidate in action_market:
            annotated = dict(candidate)
            alignment = self._goal_identity_alignment(
                action_type=str(candidate.get("action_type", "") or ""),
                query=query,
                intent_state=intent_state,
                relationship_state=relationship_state,
                world_state=world_state,
                autobiographical_state=autobiographical_state,
                goal_state=goal_state,
                context=context,
            )
            rerank_delta = round(
                float(candidate.get("rerank_delta", 0.0) or 0.0)
                + float(alignment.get("goal_alignment_score", 0.0) or 0.0) * 0.22
                + float(alignment.get("identity_consistency_score", 0.0) or 0.0) * 0.18,
                4,
            )
            annotated.update(alignment)
            annotated["rerank_delta"] = rerank_delta
            annotated["_stage8_score"] = round(float(candidate.get("score", 0.0) or 0.0) + rerank_delta, 4)
            stage8_market.append(annotated)
        stage8_market.sort(key=lambda item: (float(item.get("_stage8_score", 0.0) or 0.0), float(item.get("score", 0.0) or 0.0)), reverse=True)
        if stage8_market:
            selected_action = dict(stage8_market[0])
            selected_prediction = dict(selected_action.get("predicted_outcome", selected_prediction or {}))
            action_market = [{key: value for key, value in item.items() if key != "_stage8_score"} for item in stage8_market]

        reply_once_candidate = next((dict(item) for item in action_market if str(item.get("action_type", "")) == "reply_once"), {})
        if str(selected_action.get("action_type", "")).strip() == "reply_multi":
            multi_score = float(selected_action.get("goal_alignment_score", 0.0) or 0.0) + float(selected_action.get("identity_consistency_score", 0.0) or 0.0)
            once_score = float(reply_once_candidate.get("goal_alignment_score", 0.0) or 0.0) + float(reply_once_candidate.get("identity_consistency_score", 0.0) or 0.0)
            if multi_score <= once_score + 0.08:
                selected_action = dict(reply_once_candidate or selected_action)
                selected_prediction = dict(selected_action.get("predicted_outcome", selected_prediction or {}))
                expression_budget = 1

        chapter_relevance = str(selected_action.get("chapter_rationale", "") or str(autobiographical_state.get("current_chapter", "") or "")).strip()
        goal_alignment = {
            "selected_action": str(selected_action.get("action_type", "") or ""),
            "score": round(float(selected_action.get("goal_alignment_score", 0.0) or 0.0), 4),
            "rationale": str(selected_action.get("goal_rationale", "") or ""),
            "active_goal_ids": [str(item.get("goal_id", "")) for item in goal_state.get("active_goals", []) if str(item.get("goal_id", ""))],
        }
        identity_consistency = {
            "selected_action": str(selected_action.get("action_type", "") or ""),
            "score": round(float(selected_action.get("identity_consistency_score", 0.0) or 0.0), 4),
            "rationale": str(selected_action.get("identity_rationale", "") or ""),
            "current_chapter": str(autobiographical_state.get("current_chapter", "") or ""),
        }
        self_narrative_hint = str(selected_action.get("self_narrative_hint", "") or "").strip()
        action_rationale = compact_text(
            f"{str(selected_action.get('action_type', '') or 'reply_once')} because {str(selected_action.get('why_now', '') or '')}; "
            f"goal={goal_alignment.get('rationale', '')}; identity={identity_consistency.get('rationale', '')}; "
            f"sim={selected_prediction.get('simulation_rationale', '')}",
            240,
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
        predicted_best_outcome = dict(max(counterfactual_set, key=lambda item: float(item.get("recommended_bias", 0.0) or 0.0))) if counterfactual_set else {}
        predicted_worst_outcome = dict(min(counterfactual_set, key=lambda item: float(item.get("recommended_bias", 0.0) or 0.0))) if counterfactual_set else {}
        uncertainty_level = round(
            1.0 - max((float(item.get("confidence", 0.0) or 0.0) for item in counterfactual_set), default=0.0),
            4,
        )
        stage21_policy = self._stage21_policy_trace(action_market=action_market, selected_action=selected_action, context=context)
        packet["mind_packet_version"] = "v11"
        packet["persona_blend"] = persona_blend
        packet["brain_state"] = brain_state
        packet["game_state"] = game_state
        packet["stream_influence"] = stream_influence
        packet["self_revision_state"] = self_revision_state
        packet["self_model"] = self_model_state
        packet["autobiographical_state"] = autobiographical_state
        packet["goal_state"] = goal_state
        packet["homeostasis_state"] = homeostasis_state
        packet["operator_state"] = operator_state
        packet["visual_memory"] = visual_memory
        packet["affect_state"] = affect_state
        packet["drive_state"] = drive_state
        packet["value_state"] = value_state
        packet["conflict_state"] = conflict_state
        packet["world_state"] = world_state
        packet["initiative_candidates"] = initiative_candidates
        packet["resistance_posture"] = resistance_posture
        packet["outcome_memory"] = outcome_memory
        packet["intent_state"] = intent_state
        packet.setdefault("active_thread_state", dict(context.get("active_thread_state", {})) if isinstance(context.get("active_thread_state", {}), dict) else {})
        packet.setdefault("stage17", {})
        packet.setdefault("stage19", dict(context.get("stage19_attention_frontier", {})) if isinstance(context.get("stage19_attention_frontier", {}), dict) else {})
        packet.setdefault("stage20", dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else {})
        packet.setdefault("stage26", dict(context.get("stage26_task_world", {})) if isinstance(context.get("stage26_task_world", {}), dict) else {})
        packet.setdefault("stage22", dict(context.get("stage22_world_coupling", {})) if isinstance(context.get("stage22_world_coupling", {}), dict) else {})
        packet["visual_field"] = visual_field
        packet["situational_field"] = situational_field
        packet["stage28"] = stage28
        packet["stage21"] = stage21_policy
        packet["action_market"] = action_market
        packet["selected_action"] = selected_action
        packet["selected_prediction"] = selected_prediction
        packet["expression_budget"] = int(expression_budget)
        packet["goal_alignment"] = goal_alignment
        packet["identity_consistency"] = identity_consistency
        packet["chapter_relevance"] = chapter_relevance
        packet["self_narrative_hint"] = self_narrative_hint
        packet["silence_reason"] = silence_reason
        packet["defer_reason"] = defer_reason
        packet["action_rationale"] = action_rationale
        packet["counterfactual_summary"] = {
            "top_actions": [str(item.get("action_type", "") or "") for item in counterfactual_set[:3]],
            "evaluated_count": len(counterfactual_set),
            "selected_action": str(selected_action.get("action_type", "") or ""),
        }
        packet["predicted_best_outcome"] = predicted_best_outcome
        packet["predicted_worst_outcome"] = predicted_worst_outcome
        packet["uncertainty_level"] = uncertainty_level
        packet["intent_state_v2"] = dict(intent_state)
        packet["intent_state_v3"] = {
            **dict(intent_state),
            "world_state": dict(world_state),
            "counterfactual_summary": dict(packet["counterfactual_summary"]),
            "predicted_best_outcome": dict(predicted_best_outcome),
            "predicted_worst_outcome": dict(predicted_worst_outcome),
            "uncertainty_level": float(uncertainty_level),
        }
        packet["intent_state_v4"] = {
            **dict(packet["intent_state_v3"]),
            "autobiographical_state": dict(autobiographical_state),
            "goal_state": dict(goal_state),
            "goal_alignment": dict(goal_alignment),
            "identity_consistency": dict(identity_consistency),
            "chapter_relevance": chapter_relevance,
            "self_narrative_hint": self_narrative_hint,
        }
        packet["action_market_v2"] = list(action_market)
        packet["action_market_v3"] = list(action_market)
        packet["action_market_v4"] = list(action_market)
        packet["expression_budget_v2"] = int(expression_budget)
        packet["expression_budget_v3"] = int(expression_budget)
        packet["expression_budget_v4"] = int(expression_budget)
        packet["lookup_reason"] = (
            str(selected_action.get("why_now", "") or "")
            if str(selected_action.get("action_type", "")).strip() == "external_lookup"
            else ""
        )
        packet["deliberation_trace_id"] = str(context.get("deliberation_trace_id", "") or "")
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
        packet["state"]["autobiographical_state"] = dict(autobiographical_state)
        packet["state"]["goal_state"] = dict(goal_state)
        packet["state"]["homeostasis_state"] = dict(homeostasis_state)
        packet["state"]["operator_state"] = dict(operator_state)
        packet["state"]["visual_memory"] = dict(visual_memory)
        packet["state"]["visual_field"] = dict(visual_field)
        packet["state"]["situational_field"] = dict(situational_field)
        packet["state"]["affect_state"] = dict(affect_state)
        packet["state"]["drive_state"] = dict(drive_state)
        packet["state"]["value_state"] = dict(value_state)
        packet["state"]["conflict_state"] = dict(conflict_state)
        packet["state"]["world_state"] = dict(world_state)
        packet["state"]["resistance_posture"] = dict(resistance_posture)
        packet["state"]["outcome_memory"] = dict(outcome_memory)
        packet["state"]["intent_state"] = dict(packet["intent_state_v4"])
        packet["state"]["active_thread_state"] = dict(packet.get("active_thread_state", {}))
        packet["state"]["stage17"] = dict(packet.get("stage17", {}))
        packet["state"]["stage19"] = dict(packet.get("stage19", {}))
        packet["state"]["stage20"] = dict(packet.get("stage20", {}))
        packet["state"]["stage26"] = dict(packet.get("stage26", {}))
        packet["state"]["stage21"] = dict(packet.get("stage21", {}))
        packet["state"]["stage22"] = dict(packet.get("stage22", {}))
        packet["state"]["stage28"] = dict(packet.get("stage28", {}))
        packet["state"]["action_market"] = list(action_market)
        packet["state"]["selected_action"] = dict(selected_action)
        packet["state"]["selected_prediction"] = dict(selected_prediction)
        packet["state"]["counterfactual_summary"] = dict(packet["counterfactual_summary"])
        packet["state"]["expression_budget"] = int(expression_budget)
        packet["state"]["goal_alignment"] = dict(goal_alignment)
        packet["state"]["identity_consistency"] = dict(identity_consistency)
        packet["state"]["chapter_relevance"] = chapter_relevance
        packet["state"]["self_narrative_hint"] = self_narrative_hint
        packet["state"]["silence_reason"] = silence_reason
        packet["state"]["defer_reason"] = defer_reason
        packet["state"]["action_rationale"] = action_rationale
        packet["reply_constraints"] = {
            **dict(packet.get("reply_constraints", {})),
            "persona_guard": f"persona={persona_blend}",
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(packet, query=query)
        packet["state"]["bionic_memory_schedule"] = dict(packet["bionic_memory_schedule"])
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
            "voice_state": {"preferred_first_person": "I"},
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

    def active_thread_state(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "active_thread_state"):
            return {"present": False, "channel": channel, "thread_key": str(thread_key or ""), "chat_name": str(chat_name or "")}
        return self.graph.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)

    def update_active_thread_state(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        direction: str,
        text: str = "",
        message_id: str = "",
        event_row_id: int | None = None,
        action_type: str = "",
        selected_action: dict[str, Any] | None = None,
        intent_state: dict[str, Any] | None = None,
        attention_focus: str = "",
        active_affect_hint: str = "",
        relationship_tension: float | None = None,
        unresolved_references: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "update_active_thread_state"):
            return {"status": "skipped", "reason": "active_thread_state_unavailable"}
        state = self.graph.update_active_thread_state(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            direction=direction,
            text=text,
            message_id=message_id,
            event_row_id=event_row_id,
            action_type=action_type,
            selected_action=selected_action,
            intent_state=intent_state,
            attention_focus=attention_focus,
            active_affect_hint=active_affect_hint,
            relationship_tension=relationship_tension,
            unresolved_references=unresolved_references,
            metadata=metadata,
        )
        self.clear_packet_cache()
        return state

    @staticmethod
    def _stage19_frontier_empty(*, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return {
            "frontier_visible": False,
            "frontier_used_for_thread": False,
            "canonical_thread_key": str(thread_key or ""),
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "thread_heat": 0.0,
            "thread_warmth": "cold",
            "wake_reason": "",
            "anticipated_next_turn": "",
            "pending_open_loop_count": 0,
            "unresolved_thread_pull": False,
            "reentry_priority": 0.0,
            "stale_after": "",
            "last_stream_touch_at": "",
            "frontier_stale": True,
            "evidence_refs": [],
        }

    def _stage19_frontier_payload(
        self,
        item: dict[str, Any],
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        used: bool,
    ) -> dict[str, Any]:
        if not item or not (item.get("canonical_thread_key") or item.get("thread_key")):
            return self._stage19_frontier_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        pending = int(item.get("pending_open_loop_count", 0) or 0)
        return {
            "frontier_visible": bool(item.get("canonical_thread_key") or item.get("thread_key")),
            "frontier_used_for_thread": bool(used),
            "canonical_thread_key": str(item.get("canonical_thread_key", item.get("thread_key", thread_key)) or thread_key),
            "thread_key": str(item.get("thread_key", item.get("canonical_thread_key", thread_key)) or thread_key),
            "chat_name": str(item.get("chat_name", chat_name) or chat_name),
            "channel": str(item.get("channel", channel) or channel),
            "thread_heat": float(item.get("thread_heat", 0.0) or 0.0),
            "thread_warmth": str(item.get("thread_warmth", "cold") or "cold"),
            "wake_reason": str(item.get("wake_reason", "") or ""),
            "anticipated_next_turn": str(item.get("anticipated_next_turn", "") or ""),
            "pending_open_loop_count": pending,
            "unresolved_thread_pull": bool(pending > 0),
            "reentry_priority": float(item.get("reentry_priority", 0.0) or 0.0),
            "stale_after": str(item.get("stale_after", "") or ""),
            "last_stream_touch_at": str(item.get("last_stream_touch_at", "") or ""),
            "frontier_stale": bool(item.get("stale", True)),
            "evidence_refs": list(item.get("evidence_refs", []))[:3],
        }

    def _hydrate_active_state_from_frontier(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        if not hasattr(self.graph, "attention_frontier_item"):
            return active_state, self._stage19_frontier_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        item = self.graph.attention_frontier_item(channel=channel, thread_key=thread_key, chat_name=chat_name)
        if not bool(item.get("present", False)):
            return active_state, self._stage19_frontier_payload(
                item,
                channel=channel,
                thread_key=thread_key,
                chat_name=chat_name,
                used=False,
            )

        hydrated = dict(active_state)
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        stage19 = self._stage19_frontier_payload(item, channel=channel, thread_key=thread_key, chat_name=chat_name, used=True)
        metadata["stage19_attention_frontier"] = {
            "wake_reason": stage19["wake_reason"],
            "anticipated_next_turn": stage19["anticipated_next_turn"],
            "thread_heat": stage19["thread_heat"],
            "thread_warmth": stage19["thread_warmth"],
            "pending_open_loop_count": stage19["pending_open_loop_count"],
            "unresolved_thread_pull": stage19["unresolved_thread_pull"],
            "last_stream_touch_at": stage19["last_stream_touch_at"],
            "stale_after": stage19["stale_after"],
        }
        hydrated["metadata"] = metadata
        hydrated["present"] = True
        hydrated["channel"] = str(item.get("channel", channel) or channel)
        hydrated["thread_key"] = str(item.get("canonical_thread_key", item.get("thread_key", thread_key)) or thread_key)
        hydrated["chat_name"] = str(item.get("chat_name", chat_name) or chat_name)
        if not str(hydrated.get("continuity_summary", "") or "").strip():
            frontier_line = stage19["anticipated_next_turn"] or stage19["wake_reason"]
            if frontier_line:
                hydrated["continuity_summary"] = compact_text(f"attention_frontier: {frontier_line}", 180)
        if not str(hydrated.get("last_user_intent", "") or "").strip() and stage19["wake_reason"]:
            hydrated["last_user_intent"] = compact_text(stage19["wake_reason"], 120)
        if not str(hydrated.get("attention_focus", "") or "").strip():
            hydrated["attention_focus"] = "attention_frontier"
        if not str(hydrated.get("active_affect_hint", "") or "").strip():
            hydrated["active_affect_hint"] = "continuity_frontier"
        if stage19["thread_heat"] >= 0.36:
            hydrated["cache_warmth"] = "frontier_warm"
        else:
            hydrated["cache_warmth"] = str(hydrated.get("cache_warmth", "") or "seeded")

        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        blockers = bool(
            signal.get("local_memory_requested", False)
            or signal.get("factual_lookup", False)
            or signal.get("search_requested", False)
            or signal.get("visual_requested", False)
        )
        meaningful = self._meaningful_char_count(query)
        reflex_eligible = channel == "wechat" and not blockers and meaningful <= 54 and not list(context.get("attachments", []))
        confidence = max(float(predictive.get("active_prediction_confidence", 0.0) or 0.0), min(0.84, 0.56 + stage19["thread_heat"] * 0.24))
        if not reflex_eligible:
            confidence = min(confidence, 0.54)
        targets = self._unique_strings(
            list(predictive.get("likely_reference_targets", []))
            + [stage19["wake_reason"] or stage19["anticipated_next_turn"]]
        )[:3]
        predictive.update(
            {
                "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or ("low_signal_ping_or_ack" if bool(signal.get("low_signal", False)) else "ordinary_continuation")),
                "predicted_reply_pressure": min(0.42, float(predictive.get("predicted_reply_pressure", 0.18) or 0.18) + (0.04 if stage19["unresolved_thread_pull"] else 0.0)),
                "likely_reference_targets": targets,
                "expected_social_valence": str(predictive.get("expected_social_valence", "") or "neutral"),
                "reflex_eligibility": bool(reflex_eligible),
                "turn_rhythm": {
                    **(dict(predictive.get("turn_rhythm", {})) if isinstance(predictive.get("turn_rhythm", {}), dict) else {}),
                    "frontier_hydrated": True,
                    "short_turn": meaningful <= 18,
                },
                "freshness_at": str(stage19["last_stream_touch_at"] or predictive.get("freshness_at", "")),
                "active_prediction_confidence": self._clamp(confidence),
            }
        )
        hydrated["predictive_continuity"] = predictive
        for key, value in predictive.items():
            hydrated[key] = value
        return hydrated, stage19

    @staticmethod
    def _stage20_temporal_empty(*, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return {
            "temporal_visible": False,
            "temporal_used_for_thread": False,
            "canonical_thread_key": str(thread_key or ""),
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "open_loops": [],
            "commitments": [],
            "deferred_intentions": [],
            "interruption_markers": [],
            "resume_candidates": [],
            "due_followup_keys": [],
            "resume_candidate": {},
            "resume_cue": "",
            "commitment_due": False,
            "interruption_recovered": False,
            "duplicate_recovery_blocked": False,
            "temporal_pressure": 0.0,
        }

    def _stage20_temporal_payload(
        self,
        state: dict[str, Any],
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        used: bool,
    ) -> dict[str, Any]:
        if not isinstance(state, dict) or str(state.get("status", "") or "") != "ok":
            return self._stage20_temporal_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        open_loops = [dict(item) for item in list(state.get("open_loops", [])) if isinstance(item, dict)]
        commitments = [dict(item) for item in list(state.get("commitments", [])) if isinstance(item, dict)]
        deferred = [dict(item) for item in list(state.get("deferred_intentions", [])) if isinstance(item, dict)]
        interruptions = [dict(item) for item in list(state.get("interruption_markers", [])) if isinstance(item, dict)]
        resumes = [dict(item) for item in list(state.get("resume_candidates", [])) if isinstance(item, dict)]
        live_items = open_loops + commitments + deferred + interruptions + resumes
        due_items = [item for item in live_items if bool(item.get("due", False))]
        resume_candidate = (due_items or resumes or interruptions or open_loops or commitments or deferred or [{}])[0]
        resume_cue = compact_text(str(resume_candidate.get("resume_cue", "") if resume_candidate else "") or "", 180)
        due_keys = self._unique_strings(list(state.get("due_followup_keys", [])) + [str(item.get("dedupe_key", "")) for item in due_items])[:8]
        pressure = min(0.42, len(due_items) * 0.12 + len(open_loops) * 0.04 + len(interruptions) * 0.06)
        return {
            "temporal_visible": bool(live_items),
            "temporal_used_for_thread": bool(used and live_items),
            "canonical_thread_key": str(state.get("thread_key", thread_key) or thread_key),
            "thread_key": str(state.get("thread_key", thread_key) or thread_key),
            "chat_name": str(state.get("chat_name", chat_name) or chat_name),
            "channel": str(state.get("channel", channel) or channel),
            "open_loops": open_loops[:6],
            "commitments": commitments[:6],
            "deferred_intentions": deferred[:6],
            "interruption_markers": interruptions[:6],
            "resume_candidates": resumes[:6],
            "due_followup_keys": due_keys,
            "resume_candidate": dict(resume_candidate or {}),
            "resume_cue": resume_cue,
            "commitment_due": bool(due_items),
            "interruption_recovered": False,
            "duplicate_recovery_blocked": bool(len(due_keys) < len(due_items)),
            "temporal_pressure": round(pressure, 4),
        }

    def _hydrate_active_state_from_temporal_state(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        if not hasattr(self.graph, "temporal_state"):
            return active_state, self._stage20_temporal_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        state = self.graph.temporal_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage20 = self._stage20_temporal_payload(state, channel=channel, thread_key=thread_key, chat_name=chat_name, used=True)
        if not bool(stage20.get("temporal_visible", False)):
            return active_state, stage20

        hydrated = dict(active_state)
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        metadata["stage20_temporal_state"] = {
            "resume_cue": stage20["resume_cue"],
            "due_followup_keys": list(stage20["due_followup_keys"])[:8],
            "commitment_due": bool(stage20["commitment_due"]),
            "temporal_pressure": float(stage20["temporal_pressure"]),
        }
        hydrated["metadata"] = metadata
        hydrated["present"] = True
        hydrated["channel"] = channel
        hydrated["thread_key"] = str(stage20.get("thread_key", thread_key) or thread_key)
        hydrated["chat_name"] = str(stage20.get("chat_name", chat_name) or chat_name)
        if stage20["resume_cue"] and not str(hydrated.get("continuity_summary", "") or "").strip():
            hydrated["continuity_summary"] = compact_text(f"temporal_resume: {stage20['resume_cue']}", 220)
        if stage20["resume_cue"] and not str(hydrated.get("last_user_intent", "") or "").strip():
            hydrated["last_user_intent"] = compact_text(stage20["resume_cue"], 140)
        if not str(hydrated.get("attention_focus", "") or "").strip():
            hydrated["attention_focus"] = "temporal_resume"
        if not str(hydrated.get("active_affect_hint", "") or "").strip():
            hydrated["active_affect_hint"] = "temporal_continuity"
        hydrated["cache_warmth"] = str(hydrated.get("cache_warmth", "") or "temporal_warm")
        if hydrated["cache_warmth"] in {"cold", "seeded"} and bool(stage20.get("commitment_due", False)):
            hydrated["cache_warmth"] = "temporal_warm"

        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        blockers = bool(
            signal.get("local_memory_requested", False)
            or signal.get("factual_lookup", False)
            or signal.get("search_requested", False)
            or signal.get("visual_requested", False)
        )
        meaningful = self._meaningful_char_count(query)
        reflex_eligible = channel == "wechat" and not blockers and meaningful <= 54 and not list(context.get("attachments", []))
        confidence = max(float(predictive.get("active_prediction_confidence", 0.0) or 0.0), 0.58 + float(stage20.get("temporal_pressure", 0.0) or 0.0) * 0.2)
        if not reflex_eligible:
            confidence = min(confidence, 0.54)
        targets = self._unique_strings(
            list(predictive.get("likely_reference_targets", []))
            + [stage20["resume_cue"]]
            + list(stage20.get("due_followup_keys", []))
        )[:3]
        predictive.update(
            {
                "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or "resume_or_ack"),
                "predicted_reply_pressure": min(0.48, float(predictive.get("predicted_reply_pressure", 0.2) or 0.2) + float(stage20.get("temporal_pressure", 0.0) or 0.0) * 0.2),
                "likely_reference_targets": targets,
                "expected_social_valence": str(predictive.get("expected_social_valence", "") or "neutral"),
                "reflex_eligibility": bool(reflex_eligible),
                "turn_rhythm": {
                    **(dict(predictive.get("turn_rhythm", {})) if isinstance(predictive.get("turn_rhythm", {}), dict) else {}),
                    "temporal_hydrated": True,
                    "short_turn": meaningful <= 18,
                },
                "freshness_at": str(dict(stage20.get("resume_candidate", {})).get("updated_at", predictive.get("freshness_at", "")) or predictive.get("freshness_at", "")),
                "active_prediction_confidence": self._clamp(confidence),
            }
        )
        hydrated["predictive_continuity"] = predictive
        for key, value in predictive.items():
            hydrated[key] = value
        return hydrated, stage20

    @staticmethod
    def _stage22_world_coupling_empty(*, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return {
            "world_coupling_visible": False,
            "world_coupling_used_for_thread": False,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "signals": [],
            "cue_summary": "",
            "cue_types": [],
            "hard_gate_preserved": True,
        }

    @staticmethod
    def _stage26_task_world_empty(*, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return {
            "task_world_visible": False,
            "task_world_used_for_thread": False,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "object_ids": [],
            "object_types": [],
            "summary": "",
            "linked_commitments": [],
            "cross_thread_links_visible": False,
            "hard_gate_preserved": True,
        }

    def _stage26_task_world_payload(
        self,
        objects: list[dict[str, Any]],
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        used: bool,
    ) -> dict[str, Any]:
        items = [dict(item) for item in list(objects or []) if isinstance(item, dict) and bool(item.get("present", False))][:4]
        summary = compact_text(
            " | ".join(
                self._unique_strings([str(item.get("summary", "") or "") for item in items])
            ),
            360,
        )
        linked_commitments = self._unique_strings(
            [
                str(commitment).strip()
                for item in items
                for commitment in list(item.get("linked_commitments", []))
                if str(commitment).strip()
            ]
        )[:6]
        return {
            "task_world_visible": bool(items),
            "task_world_used_for_thread": bool(used and items),
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "object_ids": [str(item.get("object_id", "") or "") for item in items if str(item.get("object_id", "")).strip()][:4],
            "object_types": self._unique_strings([str(item.get("object_type", "") or "") for item in items])[:4],
            "summary": summary,
            "linked_commitments": linked_commitments,
            "cross_thread_links_visible": any(
                any(str(linked or "") != str(thread_key or "") for linked in list(item.get("linked_threads", [])))
                for item in items
            ),
            "hard_gate_preserved": True,
            "objects": items,
        }

    def _hydrate_active_state_from_task_world(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        if not hasattr(self.graph, "task_world_objects_for_thread"):
            return active_state, self._stage26_task_world_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        objects = self.graph.task_world_objects_for_thread(channel=channel, thread_key=thread_key, chat_name=chat_name, limit=4)
        stage26 = self._stage26_task_world_payload(objects, channel=channel, thread_key=thread_key, chat_name=chat_name, used=True)
        if not bool(stage26.get("task_world_visible", False)):
            return active_state, stage26

        hydrated = dict(active_state)
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        metadata["stage26_task_world"] = {
            "summary": stage26["summary"],
            "object_ids": list(stage26["object_ids"])[:4],
            "object_types": list(stage26["object_types"])[:4],
            "linked_commitments": list(stage26["linked_commitments"])[:6],
            "cross_thread_links_visible": bool(stage26["cross_thread_links_visible"]),
        }
        hydrated["metadata"] = metadata
        hydrated["present"] = True
        hydrated["channel"] = channel
        hydrated["thread_key"] = str(thread_key or chat_name)
        hydrated["chat_name"] = str(chat_name or thread_key)
        if stage26["summary"] and not str(hydrated.get("continuity_summary", "") or "").strip():
            hydrated["continuity_summary"] = compact_text(f"task_world: {stage26['summary']}", 220)
        if not str(hydrated.get("attention_focus", "") or "").strip():
            hydrated["attention_focus"] = "task_world_state"
        if str(hydrated.get("cache_warmth", "") or "") in {"", "cold", "seeded"}:
            hydrated["cache_warmth"] = "world_warm"

        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        blockers = bool(
            signal.get("local_memory_requested", False)
            or signal.get("factual_lookup", False)
            or signal.get("search_requested", False)
            or signal.get("visual_requested", False)
        )
        meaningful = self._meaningful_char_count(query)
        reflex_eligible = channel == "wechat" and not blockers and meaningful <= 54 and not list(context.get("attachments", []))
        confidence = max(float(predictive.get("active_prediction_confidence", 0.0) or 0.0), 0.56 + min(0.18, len(stage26["object_ids"]) * 0.04))
        if not reflex_eligible:
            confidence = min(confidence, 0.54)
        predictive.update(
            {
                "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or "continue_with_task_world"),
                "likely_reference_targets": self._unique_strings(
                    list(predictive.get("likely_reference_targets", []))
                    + [str(item.get("summary", "") or "") for item in list(stage26.get("objects", []))]
                )[:3],
                "reflex_eligibility": bool(reflex_eligible),
                "turn_rhythm": {
                    **(dict(predictive.get("turn_rhythm", {})) if isinstance(predictive.get("turn_rhythm", {}), dict) else {}),
                    "task_world_hydrated": True,
                },
                "freshness_at": str((stage26.get("objects", [{}])[0] if list(stage26.get("objects", [])) else {}).get("updated_at", predictive.get("freshness_at", "")) or predictive.get("freshness_at", "")),
                "active_prediction_confidence": self._clamp(confidence),
            }
        )
        hydrated["predictive_continuity"] = predictive
        for key, value in predictive.items():
            hydrated[key] = value
        return hydrated, stage26

    def _stage22_world_coupling_payload(
        self,
        signals: list[dict[str, Any]],
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        used: bool,
    ) -> dict[str, Any]:
        items = [dict(item) for item in signals if isinstance(item, dict) and bool(item.get("present", False))][:3]
        cue_summary = compact_text(" | ".join(self._unique_strings([str(item.get("summary", "")) for item in items])), 360)
        return {
            "world_coupling_visible": bool(items),
            "world_coupling_used_for_thread": bool(used and items),
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "signals": items,
            "cue_summary": cue_summary,
            "cue_types": self._unique_strings([str(item.get("cue_type", "")) for item in items])[:4],
            "hard_gate_preserved": True,
        }

    def _hydrate_active_state_from_world_coupling(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        if not hasattr(self.graph, "world_coupling_signals"):
            return active_state, self._stage22_world_coupling_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        items = self.graph.world_coupling_signals(channel=channel, thread_key=thread_key, chat_name=chat_name, limit=3)
        stage22 = self._stage22_world_coupling_payload(items, channel=channel, thread_key=thread_key, chat_name=chat_name, used=True)
        if not bool(stage22.get("world_coupling_visible", False)):
            return active_state, stage22

        hydrated = dict(active_state)
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        metadata["stage22_world_coupling"] = {
            "cue_summary": stage22["cue_summary"],
            "cue_types": list(stage22["cue_types"])[:4],
            "signal_ids": [str(item.get("id", "")) for item in stage22["signals"] if str(item.get("id", "")).strip()][:3],
        }
        hydrated["metadata"] = metadata
        hydrated["present"] = True
        hydrated["channel"] = channel
        hydrated["thread_key"] = str(thread_key or chat_name)
        hydrated["chat_name"] = str(chat_name or thread_key)
        if stage22["cue_summary"] and not str(hydrated.get("continuity_summary", "") or "").strip():
            hydrated["continuity_summary"] = compact_text(f"bounded_world_cues: {stage22['cue_summary']}", 220)
        if not str(hydrated.get("attention_focus", "") or "").strip():
            hydrated["attention_focus"] = "bounded_world_coupling"
        if not str(hydrated.get("cache_warmth", "") or "").strip() or hydrated.get("cache_warmth") == "cold":
            hydrated["cache_warmth"] = "frontier_warm"

        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        blockers = bool(
            signal.get("local_memory_requested", False)
            or signal.get("factual_lookup", False)
            or signal.get("search_requested", False)
            or signal.get("visual_requested", False)
        )
        meaningful = self._meaningful_char_count(query)
        reflex_eligible = channel == "wechat" and not blockers and meaningful <= 54 and not list(context.get("attachments", []))
        targets = self._unique_strings(
            list(predictive.get("likely_reference_targets", []))
            + [str(item.get("summary", "")) for item in stage22["signals"]]
        )[:3]
        predictive.update(
            {
                "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or "continue_with_world_cue"),
                "likely_reference_targets": targets,
                "reflex_eligibility": bool(reflex_eligible),
                "turn_rhythm": {
                    **(dict(predictive.get("turn_rhythm", {})) if isinstance(predictive.get("turn_rhythm", {}), dict) else {}),
                    "world_coupling_hydrated": True,
                },
                "freshness_at": str((stage22["signals"][0] if stage22["signals"] else {}).get("updated_at", predictive.get("freshness_at", "")) or predictive.get("freshness_at", "")),
                "active_prediction_confidence": self._clamp(max(float(predictive.get("active_prediction_confidence", 0.0) or 0.0), 0.57 if reflex_eligible else 0.4)),
            }
        )
        hydrated["predictive_continuity"] = predictive
        for key, value in predictive.items():
            hydrated[key] = value
        return hydrated, stage22

    def _recall_escalation_reason(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> str:
        lowered = str(query or "").lower()
        if bool(signal.get("local_memory_requested", False)) or any(str(hint).lower() in lowered for hint in EXPLICIT_MEMORY_HINTS):
            return "explicit_memory_query"
        if bool(signal.get("factual_lookup", False)):
            return "factual_lookup_need"
        has_reference = self._query_has_unresolved_reference(query)
        has_active_summary = bool(str(active_state.get("continuity_summary", "") or "").strip())
        has_last_outbound = bool(dict(active_state.get("last_outbound_action", {})).get("action_type"))
        if has_reference and not (has_active_summary or has_last_outbound):
            return "unresolved_reference"
        if has_reference and float(active_state.get("relationship_tension", 0.0) or 0.0) >= 0.58:
            return "high_risk_continuity_ambiguity"
        if not bool(active_state.get("present", False)) and bool(signal.get("question_like", False)) and self._meaningful_char_count(query) > 18:
            return "cold_thread_insufficient_active_state"
        return ""

    def _hydrate_scene_state_from_runtime_context(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        hydrated = dict(active_state)
        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        scene = dict(hydrated.get("scene_state", {})) if isinstance(hydrated.get("scene_state", {}), dict) else {}
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        stage24_meta = dict(metadata.get("stage24_scene", {})) if isinstance(metadata.get("stage24_scene", {}), dict) else {}
        stage19 = dict(context.get("stage19_attention_frontier", {})) if isinstance(context.get("stage19_attention_frontier", {}), dict) else {}
        stage20 = dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else {}
        stage26 = dict(context.get("stage26_task_world", {})) if isinstance(context.get("stage26_task_world", {}), dict) else {}
        stage22 = dict(context.get("stage22_world_coupling", {})) if isinstance(context.get("stage22_world_coupling", {}), dict) else {}
        scene_topics = self._unique_strings(
            list(scene.get("topic_stack", []))
            + [
                str(hydrated.get("attention_focus", "") or ""),
                str(stage19.get("wake_reason", "") or ""),
                str(stage20.get("resume_cue", "") or ""),
                str(stage26.get("summary", "") or ""),
                str(stage22.get("cue_summary", "") or ""),
            ]
        )[:4]
        scene_objects = self._unique_strings(
            list(scene.get("salient_objects", []))
            + list(predictive.get("likely_reference_targets", []))
            + [str(item.get("summary", "") or "") for item in list(stage26.get("objects", []))]
            + list(stage20.get("due_followup_keys", []))
        )[:4]
        scene_branches = self._unique_strings(
            list(scene.get("predicted_branches", []))
            + ([f"user:{str(predictive.get('predicted_next_user_act', '') or '').strip()}"] if str(predictive.get("predicted_next_user_act", "") or "").strip() else [])
            + ([f"frontier:{str(stage19.get('anticipated_next_turn', '') or '').strip()}"] if str(stage19.get("anticipated_next_turn", "") or "").strip() else [])
            + (["resume_then_continue"] if bool(stage20.get("temporal_visible", False)) else [])
            + (["follow_task_world"] if bool(stage26.get("task_world_visible", False)) else [])
            + (["follow_world_cue"] if bool(stage22.get("world_coupling_visible", False)) else [])
        )[:3]
        shared_frame = compact_text(
            str(scene.get("shared_frame", "") or str(hydrated.get("continuity_summary", "") or "") or str(stage26.get("summary", "") or "") or str(stage22.get("cue_summary", "") or "") or str(stage20.get("resume_cue", "") or "")),
            160,
        )
        response_sketch = compact_text(
            str(scene.get("response_sketch", "") or (f"continue around {scene_topics[0]}" if scene_topics else f"continue {str(predictive.get('predicted_next_user_act', '') or 'the thread')}")),
            140,
        )
        latent_questions = self._unique_strings(
            list(scene.get("latent_questions", []))
            + [
                str(item.get("summary", "") or "")
                for item in list(stage26.get("objects", []))
                if str(item.get("object_type", "") or "") in {"task", "schedule"} and str(item.get("status", "") or "") == "live"
            ]
        )[:3]
        scene.update(
            {
                "shared_frame": shared_frame,
                "topic_stack": scene_topics,
                "salient_objects": scene_objects,
                "latent_questions": latent_questions,
                "predicted_branches": scene_branches,
                "relationship_trajectory": compact_text(str(scene.get("relationship_trajectory", "") or ("holding_open_loop" if bool(stage20.get("temporal_visible", False)) else "ordinary_continuation")), 96),
                "response_sketch": response_sketch,
                "scene_confidence": round(
                    min(
                        1.0,
                        max(float(scene.get("scene_confidence", 0.0) or 0.0), float(predictive.get("active_prediction_confidence", 0.0) or 0.0) * 0.96),
                    ),
                    4,
                ),
                "freshness_at": str(scene.get("freshness_at", "") or predictive.get("freshness_at", "") or stage24_meta.get("updated_at", "")),
            }
        )
        hydrated["scene_state"] = scene
        stage24_meta.setdefault("compression_mode", "heuristic")
        stage24_meta.setdefault("compression_reason", "active_state_scene_hydration")
        stage24_meta.setdefault("last_direction", str(dict(hydrated.get("tempo_state", {})).get("last_direction", "") or "inspect"))
        stage24_meta.setdefault("source_turn_refs", list(hydrated.get("recent_turn_ids", []))[-4:])
        stage24_meta.setdefault("updated_at", str(scene.get("freshness_at", "") or ""))
        metadata["stage24_scene"] = stage24_meta
        hydrated["metadata"] = metadata
        return hydrated

    def _stage24_scene_packet(self, active_state: dict[str, Any]) -> dict[str, Any]:
        scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
        metadata = dict(active_state.get("metadata", {})) if isinstance(active_state.get("metadata", {}), dict) else {}
        trace = dict(metadata.get("stage24_scene", {})) if isinstance(metadata.get("stage24_scene", {}), dict) else {}
        return {
            "scene_visible": bool(scene.get("shared_frame") or scene.get("topic_stack") or scene.get("predicted_branches")),
            "shared_frame": str(scene.get("shared_frame", "") or ""),
            "topic_stack": list(scene.get("topic_stack", []))[:4],
            "predicted_branches": list(scene.get("predicted_branches", []))[:3],
            "relationship_trajectory": str(scene.get("relationship_trajectory", "") or ""),
            "response_sketch": str(scene.get("response_sketch", "") or ""),
            "scene_confidence": float(scene.get("scene_confidence", 0.0) or 0.0),
            "freshness_at": str(scene.get("freshness_at", "") or ""),
            "compression_mode": str(trace.get("compression_mode", "heuristic") or "heuristic"),
            "compression_reason": str(trace.get("compression_reason", "") or ""),
        }

    def _stage28_visual_field(self, visual_memory: dict[str, Any]) -> dict[str, Any]:
        items = [dict(item) for item in list(visual_memory.get("items", [])) if isinstance(item, dict)]
        scene = compact_text(str(visual_memory.get("scene_summary", "") or ""), 220)
        text_ocr = compact_text(str(visual_memory.get("text_ocr", "") or ""), 180)
        objects = [compact_text(str(item).strip(), 64) for item in visual_memory.get("objects", []) if str(item).strip()][:6]
        anchors = [compact_text(str(item).strip(), 80) for item in visual_memory.get("visual_anchors", []) if str(item).strip()][:4]
        spatial_refs = [compact_text(str(item).strip(), 96) for item in visual_memory.get("spatial_refs", []) if str(item).strip()][:4]
        uncertainty_markers = [
            compact_text(str(item).strip(), 96)
            for item in visual_memory.get("uncertainty_markers", [])
            if str(item).strip()
        ][:4]
        latest = items[0] if items else {}
        source_refs = self._unique_strings([str(item.get("artifact_path", "") or "") for item in items if str(item.get("artifact_path", "") or "").strip()])[:4]
        revisit_needed = bool(visual_memory.get("revisit_needed", False) or uncertainty_markers)
        visible = bool(scene or text_ocr or objects or anchors or spatial_refs or uncertainty_markers)
        confidence = self._clamp(float(visual_memory.get("thread_relevance", 0.0) or 0.0), default=0.0)
        return {
            "visual_field_visible": visible,
            "latest_scene": scene,
            "objects": objects,
            "text_ocr": text_ocr,
            "mood_imagery": compact_text(str(visual_memory.get("mood_imagery", "") or ""), 96),
            "visual_anchors": anchors,
            "spatial_refs": spatial_refs,
            "uncertainty_markers": uncertainty_markers,
            "revisit_needed": revisit_needed,
            "perceptual_density": str(visual_memory.get("perceptual_density", "") or ""),
            "source_refs": source_refs,
            "latest_visual_id": str(latest.get("id", "") or ""),
            "confidence": round(confidence, 4),
        }

    def _stage28_situational_field(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        context: dict[str, Any],
        active_state: dict[str, Any],
        visual_field: dict[str, Any],
        stage20: dict[str, Any],
        stage24: dict[str, Any],
        stage25: dict[str, Any],
        stage26: dict[str, Any],
        homeostasis_state: dict[str, Any],
        affect_state: dict[str, Any],
        drive_state: dict[str, Any],
    ) -> dict[str, Any]:
        scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
        scene_shared = compact_text(str(stage24.get("shared_frame", "") or scene.get("shared_frame", "") or ""), 180)
        response_sketch = compact_text(str(stage24.get("response_sketch", "") or scene.get("response_sketch", "") or ""), 140)
        task_summary = compact_text(str(stage26.get("summary", "") or ""), 180)
        dense_hint = compact_text(str(stage25.get("reentry_hint", "") or ""), 140)
        temporal_hint = compact_text(str(stage20.get("resume_cue", "") or ""), 140)
        visual_scene = compact_text(str(visual_field.get("latest_scene", "") or ""), 180)
        modalities = self._unique_strings(
            [
                "visual" if bool(visual_field.get("visual_field_visible", False)) else "",
                "scene" if bool(stage24.get("scene_visible", False) or scene_shared) else "",
                "task_world" if bool(stage26.get("task_world_visible", False) or task_summary) else "",
                "dense_continuity" if bool(stage25.get("dense_working_set_visible", False)) else "",
                "temporal" if bool(stage20.get("temporal_visible", False) or temporal_hint) else "",
                "text" if str(query or "").strip() else "",
            ]
        )
        grounding_order = self._unique_strings(
            [
                "visual_field" if "visual" in modalities else "",
                "scene_state" if "scene" in modalities else "",
                "task_world" if "task_world" in modalities else "",
                "dense_working_set" if "dense_continuity" in modalities else "",
                "temporal_state" if "temporal" in modalities else "",
                "recent_history",
            ]
        )
        visual_uncertainties = [str(item).strip() for item in list(visual_field.get("uncertainty_markers", [])) if str(item).strip()]
        open_questions = self._unique_strings(
            visual_uncertainties
            + list(scene.get("latent_questions", []))
            + ([temporal_hint] if temporal_hint else [])
            + ([f"task_world: {task_summary}"] if task_summary and bool(stage26.get("open_loop_reentry_visible", False)) else [])
        )[:5]
        field_parts = self._unique_strings([visual_scene, scene_shared, task_summary, dense_hint, temporal_hint, response_sketch])[:4]
        field_summary = compact_text(" | ".join(field_parts), 320)
        history_reliance = "low" if bool(active_state.get("present", False) or stage25.get("working_set_used_for_thread", False) or stage26.get("task_world_used_for_thread", False)) else "standard"
        inquiry_style = "none"
        if bool(visual_field.get("revisit_needed", False)):
            inquiry_style = "visual_uncertainty"
        elif open_questions:
            inquiry_style = "open_loop"
        elif response_sketch:
            inquiry_style = "continuation"
        inquiry_hint = ""
        if inquiry_style == "visual_uncertainty":
            marker = visual_uncertainties[0] if visual_uncertainties else open_questions[0] if open_questions else "视觉线索还不够确定"
            inquiry_hint = compact_text(f"先指向具体视觉线索，再问清不确定处：{marker}", 160)
        elif inquiry_style == "open_loop":
            inquiry_hint = compact_text(f"追问必须绑定当前未解线索：{open_questions[0]}", 160)
        elif inquiry_style == "continuation":
            inquiry_hint = compact_text(f"继续当前场景，不用模板化开头：{response_sketch}", 160)
        modality_bonus = min(0.18, len(modalities) * 0.03)
        visual_confidence = float(visual_field.get("confidence", 0.0) or 0.0)
        try:
            scene_confidence = float(stage24.get("scene_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            scene_confidence = 0.0
        confidence = self._clamp(max(visual_confidence, scene_confidence, 0.32 if field_summary else 0.0) + modality_bonus, default=0.0)
        def _pressure_metric(payload: dict[str, Any], key: str) -> float:
            value = payload.get(key, 0.0)
            if isinstance(value, dict):
                value = value.get("value", value.get("level", value.get("score", 0.0)))
            return self._clamp(value, default=0.0)

        return {
            "situational_field_visible": bool(field_summary or modalities),
            "field_summary": field_summary,
            "modalities": modalities,
            "grounding_order": grounding_order,
            "open_questions": open_questions,
            "inquiry_style": inquiry_style,
            "inquiry_hint": inquiry_hint,
            "history_reliance": history_reliance,
            "visual_revisit_needed": bool(visual_field.get("revisit_needed", False)),
            "field_confidence": round(confidence, 4),
            "homeostatic_pressure": round(
                max(
                    _pressure_metric(homeostasis_state, "pressure"),
                    _pressure_metric(affect_state, "curiosity"),
                    _pressure_metric(drive_state, "seek_continuity"),
                ),
                4,
            ),
            "hard_gate_active": bool(str(context.get("recall_escalation_reason", "") or "").strip()),
            "hard_gate_preserved": True,
            "source_layers": {
                "visual_memory": bool(visual_field.get("visual_field_visible", False)),
                "scene_state": "scene" in modalities,
                "task_world": "task_world" in modalities,
                "dense_working_set": "dense_continuity" in modalities,
                "temporal_state": "temporal" in modalities,
            },
        }

    @staticmethod
    def _stage28_packet(*, situational_field: dict[str, Any], visual_field: dict[str, Any]) -> dict[str, Any]:
        return {
            "situational_field_visible": bool(situational_field.get("situational_field_visible", False)),
            "visual_field_visible": bool(visual_field.get("visual_field_visible", False)),
            "modalities": list(situational_field.get("modalities", []))[:6],
            "grounding_order": list(situational_field.get("grounding_order", []))[:6],
            "inquiry_style": str(situational_field.get("inquiry_style", "") or ""),
            "inquiry_ready": bool(list(situational_field.get("open_questions", []))),
            "history_reliance": str(situational_field.get("history_reliance", "") or ""),
            "hard_gate_preserved": True,
            "second_brain_added": False,
            "unbounded_loop_added": False,
        }

    @staticmethod
    def _stage25_dense_empty(*, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        return {
            "dense_working_set_visible": False,
            "working_set_used_for_thread": False,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "wechat"),
            "reentry_hint": "",
            "pending_interpersonal_pressure": 0.0,
            "open_loop_reentry_visible": False,
            "last_pulse_at": "",
            "cooldown_until": "",
            "budget_remaining": 0,
        }

    def _stage25_dense_payload(
        self,
        hint: dict[str, Any],
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        used: bool,
    ) -> dict[str, Any]:
        entry = dict(hint.get("entry", {})) if isinstance(hint.get("entry", {}), dict) else {}
        budget = dict(hint.get("budget", {})) if isinstance(hint.get("budget", {}), dict) else {}
        if not entry:
            return self._stage25_dense_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        pulse_budget = max(0, int(budget.get("per_thread_pulse_budget", 0) or 0))
        pulse_count = max(0, int(entry.get("pulse_count", 0) or 0))
        return {
            "dense_working_set_visible": True,
            "working_set_used_for_thread": bool(used),
            "thread_key": str(entry.get("thread_key", thread_key) or thread_key),
            "chat_name": str(entry.get("chat_name", chat_name) or chat_name),
            "channel": str(channel or "wechat"),
            "reentry_hint": str(entry.get("reentry_hint", "") or ""),
            "pending_interpersonal_pressure": float(entry.get("pending_interpersonal_pressure", 0.0) or 0.0),
            "open_loop_reentry_visible": bool(int(entry.get("pending_open_loop_count", 0) or 0) > 0),
            "last_pulse_at": str(entry.get("last_pulse_at", "") or ""),
            "cooldown_until": str(entry.get("cooldown_until", "") or ""),
            "budget_remaining": max(0, pulse_budget - pulse_count),
        }

    def _hydrate_active_state_from_dense_working_set(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        if not hasattr(self.graph, "dense_working_set_thread_hint"):
            return active_state, self._stage25_dense_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        hint = self.graph.dense_working_set_thread_hint(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage25 = self._stage25_dense_payload(hint, channel=channel, thread_key=thread_key, chat_name=chat_name, used=True)
        if not bool(stage25.get("dense_working_set_visible", False)):
            return active_state, stage25

        hydrated = dict(active_state)
        metadata = dict(hydrated.get("metadata", {})) if isinstance(hydrated.get("metadata", {}), dict) else {}
        metadata["stage25_dense_continuity"] = {
            "reentry_hint": stage25["reentry_hint"],
            "pending_interpersonal_pressure": float(stage25["pending_interpersonal_pressure"]),
            "last_pulse_at": stage25["last_pulse_at"],
            "cooldown_until": stage25["cooldown_until"],
            "budget_remaining": int(stage25["budget_remaining"]),
        }
        hydrated["metadata"] = metadata
        hydrated["present"] = bool(hydrated.get("present", False) or stage25["dense_working_set_visible"])
        hydrated["channel"] = channel
        hydrated["thread_key"] = str(stage25.get("thread_key", thread_key) or thread_key)
        hydrated["chat_name"] = str(stage25.get("chat_name", chat_name) or chat_name)
        weak_summary = not str(hydrated.get("continuity_summary", "") or "").strip()
        weak_scene = not bool(dict(hydrated.get("scene_state", {})).get("shared_frame"))
        if weak_summary and stage25["reentry_hint"]:
            hydrated["continuity_summary"] = compact_text(f"dense_reentry: {stage25['reentry_hint']}", 220)
        if not str(hydrated.get("last_user_intent", "") or "").strip() and stage25["reentry_hint"]:
            hydrated["last_user_intent"] = compact_text(stage25["reentry_hint"], 140)
        if not str(hydrated.get("attention_focus", "") or "").strip():
            hydrated["attention_focus"] = "dense_working_set"
        if not str(hydrated.get("active_affect_hint", "") or "").strip() and float(stage25.get("pending_interpersonal_pressure", 0.0) or 0.0) >= 0.16:
            hydrated["active_affect_hint"] = "pending_interpersonal_pressure"
        if str(hydrated.get("cache_warmth", "") or "") in {"", "cold", "seeded"}:
            hydrated["cache_warmth"] = "working_set_warm"

        predictive = dict(hydrated.get("predictive_continuity", {})) if isinstance(hydrated.get("predictive_continuity", {}), dict) else {}
        blockers = bool(
            signal.get("local_memory_requested", False)
            or signal.get("factual_lookup", False)
            or signal.get("search_requested", False)
            or signal.get("visual_requested", False)
        )
        meaningful = self._meaningful_char_count(query)
        reflex_eligible = channel == "wechat" and not blockers and meaningful <= 54 and not list(context.get("attachments", []))
        confidence = max(
            float(predictive.get("active_prediction_confidence", 0.0) or 0.0),
            min(
                0.78,
                0.58
                + float(stage25.get("pending_interpersonal_pressure", 0.0) or 0.0) * 0.22
                + (0.08 if stage25.get("open_loop_reentry_visible", False) else 0.0)
                + (0.04 if str(stage25.get("last_pulse_at", "") or "").strip() else 0.0),
            ),
        )
        if not reflex_eligible:
            confidence = min(confidence, 0.54)
        predictive.update(
            {
                "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or ("resume_or_ack" if stage25.get("open_loop_reentry_visible", False) else "ordinary_continuation")),
                "predicted_reply_pressure": min(0.46, float(predictive.get("predicted_reply_pressure", 0.16) or 0.16) + float(stage25.get("pending_interpersonal_pressure", 0.0) or 0.0) * 0.18),
                "likely_reference_targets": self._unique_strings(
                    list(predictive.get("likely_reference_targets", [])) + [str(stage25.get("reentry_hint", "") or "")]
                )[:3],
                "reflex_eligibility": bool(reflex_eligible),
                "turn_rhythm": {
                    **(dict(predictive.get("turn_rhythm", {})) if isinstance(predictive.get("turn_rhythm", {}), dict) else {}),
                    "dense_continuity_hydrated": True,
                    "short_turn": meaningful <= 18,
                },
                "freshness_at": str(stage25.get("last_pulse_at", "") or predictive.get("freshness_at", "")),
                "active_prediction_confidence": self._clamp(confidence),
            }
        )
        hydrated["predictive_continuity"] = predictive
        for key, value in predictive.items():
            hydrated[key] = value
        if weak_scene:
            scene = dict(hydrated.get("scene_state", {})) if isinstance(hydrated.get("scene_state", {}), dict) else {}
            scene.setdefault("shared_frame", compact_text(str(stage25.get("reentry_hint", "") or hydrated.get("continuity_summary", "") or ""), 160))
            scene.setdefault("topic_stack", [])
            scene.setdefault("salient_objects", [])
            scene.setdefault("latent_questions", [])
            if not list(scene.get("predicted_branches", [])):
                scene["predicted_branches"] = ["resume_then_continue"] if stage25.get("open_loop_reentry_visible", False) else ["continue_same_frame"]
            if not str(scene.get("relationship_trajectory", "") or "").strip():
                scene["relationship_trajectory"] = "holding_open_loop" if stage25.get("open_loop_reentry_visible", False) else "ordinary_continuation"
            if not str(scene.get("response_sketch", "") or "").strip():
                scene["response_sketch"] = compact_text(str(stage25.get("reentry_hint", "") or ""), 140)
            scene["scene_confidence"] = round(
                max(float(scene.get("scene_confidence", 0.0) or 0.0), float(predictive.get("active_prediction_confidence", 0.0) or 0.0) * 0.94),
                4,
            )
            if not str(scene.get("freshness_at", "") or "").strip():
                scene["freshness_at"] = str(stage25.get("last_pulse_at", "") or "")
            hydrated["scene_state"] = scene
        return hydrated, stage25

    def _active_fast_lane_eligible(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
        recall_escalation_reason: str,
    ) -> bool:
        if str(context.get("channel", "wechat") or "wechat") != "wechat":
            return False
        if list(context.get("attachments", [])):
            return False
        if recall_escalation_reason:
            return False
        if bool(signal.get("search_requested", False)) or bool(signal.get("visual_requested", False)):
            return False
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        if predictive:
            if not bool(predictive.get("reflex_eligibility", False)):
                return False
            try:
                confidence = float(predictive.get("active_prediction_confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < 0.55:
                return False
        active_ready = bool(active_state.get("present", False)) and (
            bool(str(active_state.get("continuity_summary", "") or "").strip())
            or bool(str(active_state.get("last_user_intent", "") or "").strip())
            or bool(dict(active_state.get("last_outbound_action", {})).get("action_type"))
            or bool(list(active_state.get("recent_turn_ids", [])))
        )
        if not active_ready:
            return False
        meaningful = self._meaningful_char_count(query)
        if meaningful > 54:
            return False
        if bool(signal.get("low_signal", False)) or meaningful <= 18:
            return True
        if bool(active_state.get("present", False)) and str(active_state.get("cache_warmth", "") or "") in {"warm", "seeded", "frontier_warm", "temporal_warm", "world_warm"}:
            return meaningful <= 36
        return meaningful <= 24 and not bool(signal.get("question_like", False))

    def _active_thread_fast_packet(
        self,
        query: str,
        *,
        context: dict[str, Any],
        active_state: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        stage19_frontier = dict(context.get("stage19_attention_frontier", {})) if isinstance(context.get("stage19_attention_frontier", {}), dict) else self._stage19_frontier_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage20_temporal = dict(context.get("stage20_temporal_state", {})) if isinstance(context.get("stage20_temporal_state", {}), dict) else self._stage20_temporal_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage26_task_world = dict(context.get("stage26_task_world", {})) if isinstance(context.get("stage26_task_world", {}), dict) else self._stage26_task_world_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage22_world_coupling = dict(context.get("stage22_world_coupling", {})) if isinstance(context.get("stage22_world_coupling", {}), dict) else self._stage22_world_coupling_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        stage25_dense = dict(context.get("stage25_dense_working_set", {})) if isinstance(context.get("stage25_dense_working_set", {}), dict) else self._stage25_dense_empty(channel=channel, thread_key=thread_key, chat_name=chat_name)
        limits = self._mind_limits(context, fast=True)
        summary = str(active_state.get("continuity_summary", "") or "").strip()
        last_intent = str(active_state.get("last_user_intent", "") or "").strip()
        active_lines = self._unique_strings(
            [
                compact_text(summary, 160) if summary else "",
                f"last_intent={compact_text(last_intent, 120)}" if last_intent else "",
                f"last_outbound={dict(active_state.get('last_outbound_action', {})).get('action_type', '')}" if dict(active_state.get("last_outbound_action", {})).get("action_type") else "",
                f"affect={active_state.get('active_affect_hint', '')}" if str(active_state.get("active_affect_hint", "") or "").strip() else "",
            ]
        )[:2]
        packet = self._packet_scaffold(
            query=query,
            tier="fast",
            query_focus="active_thread",
            limits={**limits, "history_messages": 1},
            relationship_state={
                "summary": summary,
                "lines": active_lines[:1],
                "items": [],
                "relationship_score": 0.0,
                "last_message_at": str(dict(active_state.get("tempo_state", {})).get("last_event_at", "") or ""),
                "recurring_motifs": [],
                "unfinished_threads": list(active_state.get("unresolved_references", []))[:3],
                "anchor_lines": active_lines[:2],
                "tone_tendency": str(active_state.get("active_affect_hint", "") or ""),
                "trust_score": 0.0,
                "closeness_score": 0.0,
                "continuity_score": 0.42 if summary else 0.0,
            },
            recent_dialogue_window={"lines": [], "messages": [], "window_size": 0, "source": "active_thread_state"},
            episodic_recall={"lines": [], "items": []},
            consciousness_stream={"thread_summary": summary, "lines": [], "items": []},
            activation_state={
                "heat": float(stage19_frontier.get("thread_heat", 0.0) or 0.0),
                "active_node_ids": [],
                "motifs": self._unique_strings(
                    [
                        str(active_state.get("attention_focus", "") or ""),
                        str(stage19_frontier.get("wake_reason", "") or ""),
                        str(stage20_temporal.get("resume_cue", "") or ""),
                        str(stage26_task_world.get("summary", "") or ""),
                        str(stage22_world_coupling.get("cue_summary", "") or ""),
                    ]
                )[:4],
                "recall_priors": {},
                "contributor_counts": {
                    **({"attention_frontier": 1} if bool(stage19_frontier.get("frontier_used_for_thread", False)) else {}),
                    **({"temporal_state": 1} if bool(stage20_temporal.get("temporal_used_for_thread", False)) else {}),
                    **({"task_world": 1} if bool(stage26_task_world.get("task_world_used_for_thread", False)) else {}),
                    **({"world_coupling": 1} if bool(stage22_world_coupling.get("world_coupling_used_for_thread", False)) else {}),
                    **({"dense_working_set": 1} if bool(stage25_dense.get("working_set_used_for_thread", False)) else {}),
                },
                "recent_events": [],
            },
            graph_confidence=0.0,
            graph_trace_summary=summary,
            activation_trace_ids=[],
            selected_memory_ids=[],
            graph_hits=[],
            vector_hits=[],
            retrieval_trace={
                "route": "active_thread",
                "stage17": {
                    "fast_lane": True,
                    "signal": dict(signal),
                    "cache_warmth": str(active_state.get("cache_warmth", "") or "cold"),
                },
            },
            memory_route="active_thread",
            recall_confidence=0.0,
        )
        packet["retrieval_mode"] = "active-thread-fast"
        packet["active_thread_state"] = dict(active_state)
        packet["stage17"] = {
            "fast_lane": True,
            "recall_escalation_reason": "",
            "history_policy": "continuity_summary_first",
            "max_fast_history_lines": 1,
        }
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        packet["stage18"] = {
            "fast_lane": True,
            "reflex_eligible": bool(predictive.get("reflex_eligibility", False)),
            "prediction_confidence": float(predictive.get("active_prediction_confidence", 0.0) or 0.0),
            "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or ""),
            "predicted_reply_pressure": float(predictive.get("predicted_reply_pressure", 0.0) or 0.0),
            "likely_reference_targets": list(predictive.get("likely_reference_targets", []))[:3],
            "micro_fast_candidate": True,
            "micro_fast_reason": "active_thread_reflex_candidate",
        }
        packet["stage24"] = self._stage24_scene_packet(active_state)
        packet["stage19"] = dict(stage19_frontier)
        packet["stage20"] = dict(stage20_temporal)
        packet["stage26"] = dict(stage26_task_world)
        packet["stage22"] = dict(stage22_world_coupling)
        packet["stage25"] = dict(stage25_dense)
        packet.setdefault("retrieval_trace", {}).setdefault("stage24", dict(packet["stage24"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage18", dict(packet["stage18"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage19", dict(packet["stage19"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage20", dict(packet["stage20"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage26", dict(packet["stage26"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage22", dict(packet["stage22"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage25", dict(packet["stage25"]))
        result = self._finalize_stage2_packet(packet, query=query, context=context)
        if hasattr(self.graph, "update_active_thread_state"):
            self.graph.update_active_thread_state(
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                direction="inspect",
                text="",
                metadata={"_stage17_fast_lane_hit": True},
            )
        return result

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

        channel = str(normalized_context.get("channel", "wechat") or "wechat")
        thread_key = str(normalized_context.get("thread_key", "") or "")
        chat_name = str(normalized_context.get("chat_name", "") or "")
        signal = self._query_signal(query)
        active_state = dict(normalized_context.get("active_thread_state", {})) if isinstance(normalized_context.get("active_thread_state", {}), dict) else {}
        if not active_state:
            active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        active_state, stage19_frontier = self._hydrate_active_state_from_frontier(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["stage19_attention_frontier"] = dict(stage19_frontier)
        active_state, stage20_temporal = self._hydrate_active_state_from_temporal_state(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["stage20_temporal_state"] = dict(stage20_temporal)
        active_state, stage26_task_world = self._hydrate_active_state_from_task_world(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["stage26_task_world"] = dict(stage26_task_world)
        active_state, stage22_world_coupling = self._hydrate_active_state_from_world_coupling(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["stage22_world_coupling"] = dict(stage22_world_coupling)
        active_state = self._hydrate_scene_state_from_runtime_context(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        active_state, stage25_dense = self._hydrate_active_state_from_dense_working_set(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["stage25_dense_working_set"] = dict(stage25_dense)
        recall_escalation_reason = self._recall_escalation_reason(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
        )
        normalized_context["active_thread_state"] = dict(active_state)
        normalized_context["recall_escalation_reason"] = recall_escalation_reason
        if self._active_fast_lane_eligible(
            query,
            context=normalized_context,
            active_state=active_state,
            signal=signal,
            recall_escalation_reason=recall_escalation_reason,
        ):
            return self._active_thread_fast_packet(
                query,
                context=normalized_context,
                active_state=active_state,
                signal=signal,
            )

        if self._is_fast_ping_query(query):
            return self._fast_graph_packet(query, context=normalized_context)

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
        if recall_escalation_reason:
            packet["tier"] = "deep_recall" if recall_escalation_reason == "explicit_memory_query" else "recall"
            packet["recall_reason"] = f"stage17:{recall_escalation_reason}"
            if hasattr(self.graph, "update_active_thread_state"):
                self.graph.update_active_thread_state(
                    channel=channel,
                    thread_key=thread_key or chat_name,
                    chat_name=chat_name or thread_key,
                    direction="inspect",
                    text="",
                    metadata={"_stage17_recall_escalated": True, "recall_escalation_reason": recall_escalation_reason},
                )

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
        packet["active_thread_state"] = dict(active_state)
        packet["stage17"] = {
            "fast_lane": False,
            "recall_escalation_reason": recall_escalation_reason,
            "history_policy": "recall_window" if packet.get("tier") in {"recall", "deep_recall"} else "standard_window",
            "max_fast_history_lines": 1,
        }
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        packet["stage18"] = {
            "fast_lane": False,
            "reflex_eligible": bool(predictive.get("reflex_eligibility", False)),
            "prediction_confidence": float(predictive.get("active_prediction_confidence", 0.0) or 0.0),
            "predicted_next_user_act": str(predictive.get("predicted_next_user_act", "") or ""),
            "predicted_reply_pressure": float(predictive.get("predicted_reply_pressure", 0.0) or 0.0),
            "likely_reference_targets": list(predictive.get("likely_reference_targets", []))[:3],
            "micro_fast_candidate": False,
            "micro_fast_reason": recall_escalation_reason or "not_active_thread_fast",
        }
        packet["stage24"] = self._stage24_scene_packet(active_state)
        packet["stage19"] = dict(stage19_frontier)
        packet["stage20"] = dict(stage20_temporal)
        packet["stage26"] = dict(stage26_task_world)
        packet["stage22"] = dict(stage22_world_coupling)
        packet["stage25"] = dict(stage25_dense)
        packet.setdefault("retrieval_trace", {}).setdefault("stage24", dict(packet["stage24"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage19", dict(packet["stage19"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage20", dict(packet["stage20"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage26", dict(packet["stage26"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage22", dict(packet["stage22"]))
        packet.setdefault("retrieval_trace", {}).setdefault("stage25", dict(packet["stage25"]))
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
            "visual_field": dict(packet.get("visual_field", {})),
            "situational_field": dict(packet.get("situational_field", {})),
            "active_thread_state": dict(packet.get("active_thread_state", {})),
            "stage17": dict(packet.get("stage17", {})),
            "stage18": dict(packet.get("stage18", {})),
            "stage24": dict(packet.get("stage24", {})),
            "stage19": dict(packet.get("stage19", {})),
            "stage20": dict(packet.get("stage20", {})),
            "stage22": dict(packet.get("stage22", {})),
            "stage25": dict(packet.get("stage25", {})),
            "stage28": dict(packet.get("stage28", {})),
            "mind_packet": packet,
        }

    def fast_path_metrics(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        metrics = dict(active_state.get("metrics", {}))
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        samples = [
            int(item)
            for item in list(metrics.get("history_lines_in_prompt_samples", []))
            if str(item).strip().lstrip("-").isdigit()
        ]
        return {
            "thread_key": active_state.get("thread_key", str(thread_key or "")),
            "chat_name": active_state.get("chat_name", str(chat_name or "")),
            "channel": active_state.get("channel", channel),
            "present": bool(active_state.get("present", False)),
            "fast_lane_hits": int(metrics.get("fast_lane_hits", 0) or 0),
            "recall_escalations": int(metrics.get("recall_escalations", 0) or 0),
            "active_history_refreshes": int(metrics.get("active_history_refreshes", 0) or 0),
            "avg_history_lines_in_prompt": round(sum(samples) / len(samples), 4) if samples else 0.0,
            "reflex_eligibility": bool(predictive.get("reflex_eligibility", False)),
            "active_prediction_confidence": float(predictive.get("active_prediction_confidence", 0.0) or 0.0),
            "predicted_reply_pressure": float(predictive.get("predicted_reply_pressure", 0.0) or 0.0),
            "scene_confidence": float(dict(active_state.get("scene_state", {})).get("scene_confidence", 0.0) or 0.0),
            "freshness_at": str(predictive.get("freshness_at", "") or ""),
        }

    def predictive_continuity(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        predictive = dict(active_state.get("predictive_continuity", {})) if isinstance(active_state.get("predictive_continuity", {}), dict) else {}
        return {
            "thread_key": active_state.get("thread_key", str(thread_key or "")),
            "chat_name": active_state.get("chat_name", str(chat_name or "")),
            "channel": active_state.get("channel", channel),
            "present": bool(active_state.get("present", False)),
            "predictive_continuity": predictive,
            "active_thread_state": active_state,
        }

    def scene_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
        return {
            "thread_key": active_state.get("thread_key", str(thread_key or "")),
            "chat_name": active_state.get("chat_name", str(chat_name or "")),
            "channel": active_state.get("channel", channel),
            "present": bool(active_state.get("present", False)),
            "scene_state": scene,
            "predictive_continuity": dict(active_state.get("predictive_continuity", {})),
            "active_thread_state": active_state,
            "stage24": self._stage24_scene_packet(active_state),
            "stage25": self._stage25_dense_payload(
                self.graph.dense_working_set_thread_hint(channel=channel, thread_key=thread_key, chat_name=chat_name)
                if hasattr(self.graph, "dense_working_set_thread_hint")
                else {},
                channel=channel,
                thread_key=str(active_state.get("thread_key", str(thread_key or ""))),
                chat_name=str(active_state.get("chat_name", str(chat_name or ""))),
                used=False,
            ),
        }

    def trace_predicted_branches(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        scene = dict(active_state.get("scene_state", {})) if isinstance(active_state.get("scene_state", {}), dict) else {}
        return {
            "thread_key": active_state.get("thread_key", str(thread_key or "")),
            "chat_name": active_state.get("chat_name", str(chat_name or "")),
            "channel": active_state.get("channel", channel),
            "present": bool(active_state.get("present", False)),
            "predicted_branches": list(scene.get("predicted_branches", []))[:3],
            "scene_confidence": float(scene.get("scene_confidence", 0.0) or 0.0),
            "relationship_trajectory": str(scene.get("relationship_trajectory", "") or ""),
            "response_sketch": str(scene.get("response_sketch", "") or ""),
            "predictive_continuity": dict(active_state.get("predictive_continuity", {})),
            "stage24": self._stage24_scene_packet(active_state),
            "stage25": self._stage25_dense_payload(
                self.graph.dense_working_set_thread_hint(channel=channel, thread_key=thread_key, chat_name=chat_name)
                if hasattr(self.graph, "dense_working_set_thread_hint")
                else {},
                channel=channel,
                thread_key=str(active_state.get("thread_key", str(thread_key or ""))),
                chat_name=str(active_state.get("chat_name", str(chat_name or ""))),
                used=False,
            ),
        }

    def trace_scene_compression(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        metadata = dict(active_state.get("metadata", {})) if isinstance(active_state.get("metadata", {}), dict) else {}
        stage24 = dict(metadata.get("stage24_scene", {})) if isinstance(metadata.get("stage24_scene", {}), dict) else {}
        return {
            "thread_key": active_state.get("thread_key", str(thread_key or "")),
            "chat_name": active_state.get("chat_name", str(chat_name or "")),
            "channel": active_state.get("channel", channel),
            "present": bool(active_state.get("present", False)),
            "scene_state": dict(active_state.get("scene_state", {})),
            "predictive_continuity": dict(active_state.get("predictive_continuity", {})),
            "last_reducer_direction": str(stage24.get("last_direction", "") or ""),
            "last_reducer_at": str(stage24.get("updated_at", "") or ""),
            "compression_mode": str(stage24.get("compression_mode", "heuristic") or "heuristic"),
            "compression_reason": str(stage24.get("compression_reason", "") or ""),
            "bounded_truncation": dict(stage24.get("truncation", {})) if isinstance(stage24.get("truncation", {}), dict) else {},
            "source_turn_refs": list(stage24.get("source_turn_refs", []))[:4] if isinstance(stage24.get("source_turn_refs", []), list) else [],
            "stage24": self._stage24_scene_packet(active_state),
            "stage25": self._stage25_dense_payload(
                self.graph.dense_working_set_thread_hint(channel=channel, thread_key=thread_key, chat_name=chat_name)
                if hasattr(self.graph, "dense_working_set_thread_hint")
                else {},
                channel=channel,
                thread_key=str(active_state.get("thread_key", str(thread_key or ""))),
                chat_name=str(active_state.get("chat_name", str(chat_name or ""))),
                used=False,
            ),
        }

    def upsert_task_world_object(
        self,
        *,
        object_type: str,
        summary: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        source_ref: str = "",
        confidence: float = 0.62,
        stale_after: str = "",
        linked_commitments: list[str] | None = None,
        status: str = "live",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "upsert_task_world_object"):
            return {"status": "unavailable", "present": False}
        payload = self.graph.upsert_task_world_object(
            object_type=object_type,
            summary=summary,
            source_ref=source_ref,
            confidence=confidence,
            stale_after=stale_after,
            linked_threads=[_normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())],
            linked_commitments=linked_commitments or [],
            status=status,
            metadata=metadata or {},
        )
        self.clear_packet_cache()
        return payload

    def show_task_world(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_task_world"):
            return {"status": "unavailable", "present": False, "objects": []}
        payload = self.graph.show_task_world(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            include_inactive=include_inactive,
        )
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        payload["active_thread_state"] = active_state
        payload["stage24"] = self._stage24_scene_packet(active_state)
        payload["stage25"] = self._stage25_dense_payload(
            self.graph.dense_working_set_thread_hint(channel=channel, thread_key=thread_key, chat_name=chat_name)
            if hasattr(self.graph, "dense_working_set_thread_hint")
            else {},
            channel=channel,
            thread_key=str(active_state.get("thread_key", str(thread_key or ""))),
            chat_name=str(active_state.get("chat_name", str(chat_name or ""))),
            used=False,
        )
        return payload

    def trace_world_object(self, *, object_id: str) -> dict[str, Any]:
        if not hasattr(self.graph, "task_world_object"):
            return {"status": "unavailable", "present": False, "object": {}}
        return self.graph.task_world_object(object_id=object_id)

    def trace_thread_object_links(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "trace_thread_object_links"):
            return {"status": "unavailable", "thread_key": str(thread_key or ""), "chat_name": str(chat_name or ""), "channel": channel, "objects": []}
        payload = self.graph.trace_thread_object_links(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )
        payload["active_thread_state"] = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        return payload

    def show_situational_field(
        self,
        *,
        query: str = "",
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip() or "continue"
        packet = self.sidecar_packet(
            normalized_query,
            context={
                "channel": str(channel or "wechat"),
                "thread_key": str(thread_key or chat_name or ""),
                "chat_name": str(chat_name or thread_key or ""),
                "attachments": [],
            },
        )
        return {
            "status": "ok",
            "query": normalized_query,
            "thread_key": str(packet.get("thread_key", thread_key or "") or ""),
            "chat_name": str(packet.get("chat_name", chat_name or "") or ""),
            "channel": str(channel or "wechat"),
            "memory_route": str(packet.get("memory_route", "") or ""),
            "retrieval_mode": str(packet.get("retrieval_mode", "") or ""),
            "tier": str(packet.get("tier", "") or ""),
            "situational_field": dict(packet.get("situational_field", {})),
            "visual_field": dict(packet.get("visual_field", {})),
            "stage28": dict(packet.get("stage28", {})),
            "stage24": dict(packet.get("stage24", {})),
            "stage25": dict(packet.get("stage25", {})),
            "stage26": dict(packet.get("stage26", {})),
        }

    def trace_visual_field(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        visual_memory = self.visual_memory_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        visual_field = self._stage28_visual_field(visual_memory)
        return {
            "status": "ok",
            "thread_key": str(visual_memory.get("thread_key", thread_key or "") or ""),
            "chat_name": str(visual_memory.get("chat_name", chat_name or "") or ""),
            "channel": str(channel or "wechat"),
            "visual_memory": visual_memory,
            "visual_field": visual_field,
            "stage28": {
                "visual_field_visible": bool(visual_field.get("visual_field_visible", False)),
                "revisit_needed": bool(visual_field.get("revisit_needed", False)),
                "uncertainty_count": len(list(visual_field.get("uncertainty_markers", []))),
                "perceptual_density": str(visual_field.get("perceptual_density", "") or ""),
            },
        }

    def trace_inquiry_shaping(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip() or "continue"
        packet = self.sidecar_packet(
            normalized_query,
            context={
                "channel": str(channel or "wechat"),
                "thread_key": str(thread_key or chat_name or ""),
                "chat_name": str(chat_name or thread_key or ""),
                "attachments": [],
            },
        )
        shaped_candidates = []
        for item in list(packet.get("action_market", []))[: max(1, int(limit or 8))]:
            candidate = dict(item)
            shaped_candidates.append(
                {
                    "action_type": str(candidate.get("action_type", "") or ""),
                    "score": float(candidate.get("score", 0.0) or 0.0),
                    "send_allowed": bool(candidate.get("send_allowed", False)),
                    "stage28_delta": float(candidate.get("stage28_delta", 0.0) or 0.0),
                    "stage28_rationale": str(candidate.get("stage28_rationale", "") or ""),
                    "stage28_grounding_order": list(candidate.get("stage28_grounding_order", [])),
                    "scene_delta": float(candidate.get("scene_delta", 0.0) or 0.0),
                    "scene_rationale": str(candidate.get("scene_rationale", "") or ""),
                }
            )
        return {
            "status": "ok",
            "query": normalized_query,
            "thread_key": str(packet.get("thread_key", thread_key or "") or ""),
            "chat_name": str(packet.get("chat_name", chat_name or "") or ""),
            "channel": str(channel or "wechat"),
            "tier": str(packet.get("tier", "") or ""),
            "recall_reason": str(packet.get("recall_reason", "") or ""),
            "memory_route": str(packet.get("memory_route", "") or ""),
            "situational_field": dict(packet.get("situational_field", {})),
            "stage28": dict(packet.get("stage28", {})),
            "selected_action": dict(packet.get("selected_action", {})),
            "action_market": shaped_candidates,
        }

    def show_continuity_budget(self, *, channel: str = "wechat") -> dict[str, Any]:
        snapshot = self.graph.dense_working_set(channel=channel) if hasattr(self.graph, "dense_working_set") else {"dense_working_set": {}}
        current_budget = dict(snapshot.get("dense_working_set", {}).get("budget", {})) if isinstance(snapshot.get("dense_working_set", {}).get("budget", {}), dict) else {}
        return {
            "status": "ok",
            "channel": str(channel or "wechat"),
            "configured_budget": copy.deepcopy(self.stage25_budget),
            "current_budget": current_budget,
            "dense_working_set_updated_at": str(snapshot.get("dense_working_set", {}).get("updated_at", "") or ""),
            "last_stream_name": str(snapshot.get("dense_working_set", {}).get("last_stream_name", "") or ""),
        }

    def show_dense_working_set(self, *, channel: str = "wechat") -> dict[str, Any]:
        if not hasattr(self.graph, "dense_working_set"):
            return {"status": "unavailable", "channel": str(channel or "wechat"), "present": False, "dense_working_set": {}}
        payload = self.graph.dense_working_set(channel=channel)
        payload["configured_budget"] = copy.deepcopy(self.stage25_budget)
        return payload

    def trace_thread_pulse(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "trace_thread_pulse"):
            return {"status": "unavailable", "thread_key": str(thread_key or ""), "chat_name": str(chat_name or ""), "channel": channel, "thread_pulse_trace": []}
        payload = self.graph.trace_thread_pulse(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)
        payload["active_thread_state"] = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        return payload

    def trace_reflex_routing(
        self,
        query: str,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        context = {
            "channel": channel,
            "thread_key": str(thread_key or chat_name or ""),
            "chat_name": str(chat_name or thread_key or ""),
            "attachments": [],
        }
        active_state = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        signal = self._query_signal(query)
        recall_reason = self._recall_escalation_reason(
            query,
            context=context,
            active_state=active_state,
            signal=signal,
        )
        active_fast_eligible = self._active_fast_lane_eligible(
            query,
            context=context,
            active_state=active_state,
            signal=signal,
            recall_escalation_reason=recall_reason,
        )
        packet = self.sidecar_packet(query, context={**context, "active_thread_state": active_state})
        packet_active_state = dict(packet.get("active_thread_state", active_state))
        return {
            "query": query,
            "thread_key": active_state.get("thread_key", context["thread_key"]),
            "chat_name": active_state.get("chat_name", context["chat_name"]),
            "channel": active_state.get("channel", channel),
            "signal": signal,
            "recall_escalation_reason": recall_reason,
            "active_fast_eligible": active_fast_eligible,
            "retrieval_mode": packet.get("retrieval_mode", ""),
            "memory_route": packet.get("memory_route", ""),
            "tier": packet.get("tier", ""),
            "selected_action": dict(packet.get("selected_action", {})),
            "stage17": dict(packet.get("stage17", {})),
            "stage18": dict(packet.get("stage18", {})),
            "stage24": dict(packet.get("stage24", {})),
            "stage19": dict(packet.get("stage19", {})),
            "stage20": dict(packet.get("stage20", {})),
            "stage22": dict(packet.get("stage22", {})),
            "stage25": dict(packet.get("stage25", {})),
            "predictive_continuity": dict(packet_active_state.get("predictive_continuity", {})),
            "scene_state": dict(packet_active_state.get("scene_state", {})),
        }

    def attention_frontier(
        self,
        *,
        channel: str | None = None,
        limit: int = 8,
        include_stale: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "attention_frontier"):
            return {"status": "unavailable", "entry_count": 0, "entries": []}
        return self.graph.attention_frontier(channel=channel, limit=limit, include_stale=include_stale)

    def trace_wake_reasons(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "trace_wake_reasons"):
            return {"status": "unavailable", "thread_key": str(thread_key or ""), "chat_name": str(chat_name or ""), "channel": channel}
        payload = self.graph.trace_wake_reasons(thread_key=thread_key, chat_name=chat_name, channel=channel)
        payload["active_thread_state"] = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        return payload

    def thread_warmth(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "thread_warmth"):
            return {"status": "unavailable", "thread_key": str(thread_key or ""), "chat_name": str(chat_name or ""), "channel": channel, "thread_warmth": "cold"}
        return self.graph.thread_warmth(thread_key=thread_key, chat_name=chat_name, channel=channel)

    def temporal_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "temporal_state"):
            return {"status": "unavailable", "thread_key": str(thread_key or ""), "chat_name": str(chat_name or ""), "channel": channel}
        return self.graph.temporal_state(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def show_open_loops(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_open_loops"):
            return {"status": "unavailable", "items": []}
        return self.graph.show_open_loops(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def show_commitments(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_commitments"):
            return {"status": "unavailable", "items": []}
        return self.graph.show_commitments(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)

    def trace_resume_candidate(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "trace_resume_candidate"):
            return {"status": "unavailable", "resume_available": False}
        payload = self.graph.trace_resume_candidate(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive)
        payload["active_thread_state"] = self.active_thread_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        return payload

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

    def world_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict[str, Any]:
        state = self._subject_state(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))
        world_state = dict(state.get("world_state", {}))
        return {
            "thread_key": str(state.get("thread_key", thread_key or "")),
            "chat_name": str(state.get("chat_name", chat_name or "")),
            "channel": channel,
            "world_state": world_state,
            "response_expectations": dict(world_state.get("response_expectations", {})),
            "updated_at": str(state.get("updated_at", "")),
        }

    def autobiographical_state(self) -> dict[str, Any]:
        return self.graph.autobiographical_state()

    def goal_state(self) -> dict[str, Any]:
        return self.graph.goal_state()

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
                "intent_state_v2": dict(packet.get("intent_state_v2", packet.get("intent_state", {}))),
                "intent_state_v3": dict(packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {})))),
                "intent_state_v4": dict(packet.get("intent_state_v4", packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {}))))),
                "selected_action": dict(packet.get("selected_action", {})),
                "expression_budget": int(packet.get("expression_budget", 0) or 0),
                "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
                "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget", 0)) or 0),
                "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
                "action_rationale": str(packet.get("action_rationale", "") or ""),
                "world_state": dict(packet.get("world_state", {})),
                "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
                "autobiographical_state": dict(packet.get("autobiographical_state", {})),
                "goal_state": dict(packet.get("goal_state", {})),
                "goal_alignment": dict(packet.get("goal_alignment", {})),
                "identity_consistency": dict(packet.get("identity_consistency", {})),
                "chapter_relevance": str(packet.get("chapter_relevance", "") or ""),
                "self_narrative_hint": str(packet.get("self_narrative_hint", "") or ""),
            }
        subject = self._subject_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name)
        metadata = dict(subject.get("metadata", {}))
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": "",
            "intent_state": dict(metadata.get("last_intent_state", {})),
            "intent_state_v2": dict(metadata.get("last_intent_state_v2", metadata.get("last_intent_state", {}))),
            "intent_state_v3": dict(metadata.get("last_intent_state_v3", metadata.get("last_intent_state_v2", metadata.get("last_intent_state", {})))),
            "intent_state_v4": dict(metadata.get("last_intent_state_v4", metadata.get("last_intent_state_v3", metadata.get("last_intent_state_v2", metadata.get("last_intent_state", {}))))),
            "selected_action": dict(metadata.get("last_selected_action", {})),
            "expression_budget": int(metadata.get("last_expression_budget", 0) or 0),
            "expression_budget_v2": int(metadata.get("last_expression_budget_v2", metadata.get("last_expression_budget", 0)) or 0),
            "expression_budget_v3": int(metadata.get("last_expression_budget_v3", metadata.get("last_expression_budget", 0)) or 0),
            "expression_budget_v4": int(metadata.get("last_expression_budget_v4", metadata.get("last_expression_budget_v3", metadata.get("last_expression_budget_v2", metadata.get("last_expression_budget", 0)))) or 0),
            "action_rationale": str(metadata.get("last_action_rationale", "") or ""),
            "last_action_selection": dict(metadata.get("last_action_selection", {})) if isinstance(metadata.get("last_action_selection", {}), dict) else {},
            "world_state": dict(subject.get("world_state", {})),
            "counterfactual_summary": dict(metadata.get("last_counterfactual_summary", {})),
            "autobiographical_state": self.autobiographical_state(),
            "goal_state": self.goal_state(),
            "goal_alignment": dict(metadata.get("last_goal_alignment", {})),
            "identity_consistency": dict(metadata.get("last_identity_consistency", {})),
            "chapter_relevance": str(metadata.get("last_chapter_relevance", "") or ""),
            "self_narrative_hint": str(metadata.get("last_self_narrative_hint", "") or ""),
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
                "action_market_v2": market[: max(1, int(limit))],
                "action_market_v3": market[: max(1, int(limit))],
                "action_market_v4": list(packet.get("action_market_v4", market))[: max(1, int(limit))],
                "selected_action": dict(packet.get("selected_action", {})),
                "expression_budget": int(packet.get("expression_budget", 0) or 0),
                "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
                "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget", 0)) or 0),
                "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
                "goal_alignment": dict(packet.get("goal_alignment", {})),
                "identity_consistency": dict(packet.get("identity_consistency", {})),
                "stage21": dict(packet.get("stage21", {})),
            }
        subject = self._subject_state(channel=channel, thread_key=normalized_thread_key, chat_name=normalized_chat_name)
        metadata = dict(subject.get("metadata", {}))
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": "",
            "action_market": list(metadata.get("last_action_market", []))[: max(1, int(limit))],
            "action_market_v2": list(metadata.get("last_action_market_v2", metadata.get("last_action_market", [])))[: max(1, int(limit))],
            "action_market_v3": list(metadata.get("last_action_market_v3", metadata.get("last_action_market_v2", metadata.get("last_action_market", []))))[: max(1, int(limit))],
            "action_market_v4": list(metadata.get("last_action_market_v4", metadata.get("last_action_market_v3", metadata.get("last_action_market_v2", metadata.get("last_action_market", [])))))[: max(1, int(limit))],
            "selected_action": dict(metadata.get("last_selected_action", {})),
            "expression_budget": int(metadata.get("last_expression_budget", 0) or 0),
            "expression_budget_v2": int(metadata.get("last_expression_budget_v2", metadata.get("last_expression_budget", 0)) or 0),
            "expression_budget_v3": int(metadata.get("last_expression_budget_v3", metadata.get("last_expression_budget", 0)) or 0),
            "expression_budget_v4": int(metadata.get("last_expression_budget_v4", metadata.get("last_expression_budget_v3", metadata.get("last_expression_budget_v2", metadata.get("last_expression_budget", 0)))) or 0),
            "goal_alignment": dict(metadata.get("last_goal_alignment", {})),
            "identity_consistency": dict(metadata.get("last_identity_consistency", {})),
            "stage21": dict(metadata.get("last_stage21_policy", {})),
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
            "intent_state_v2": dict(packet.get("intent_state_v2", packet.get("intent_state", {}))),
            "intent_state_v3": dict(packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {})))),
            "intent_state_v4": dict(packet.get("intent_state_v4", packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {}))))),
            "action_market": list(packet.get("action_market", []))[: max(1, int(limit))],
            "action_market_v2": list(packet.get("action_market_v2", packet.get("action_market", [])))[: max(1, int(limit))],
            "action_market_v3": list(packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", []))))[: max(1, int(limit))],
            "action_market_v4": list(packet.get("action_market_v4", packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", [])))))[: max(1, int(limit))],
            "selected_action": selected_action,
            "expression_budget": int(packet.get("expression_budget", 0) or 0),
            "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
            "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget", 0)) or 0),
            "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
            "silence_reason": str(packet.get("silence_reason", "") or ""),
            "defer_reason": str(packet.get("defer_reason", "") or ""),
            "lookup_reason": str(packet.get("lookup_reason", "") or ""),
            "action_rationale": str(packet.get("action_rationale", "") or ""),
            "deliberation_trace_id": str(packet.get("deliberation_trace_id", "") or ""),
            "world_state": dict(packet.get("world_state", {})),
            "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
            "predicted_best_outcome": dict(packet.get("predicted_best_outcome", {})),
            "predicted_worst_outcome": dict(packet.get("predicted_worst_outcome", {})),
            "selected_prediction": dict(packet.get("selected_prediction", {})),
            "stage21": dict(packet.get("stage21", {})),
            "uncertainty_level": float(packet.get("uncertainty_level", 0.0) or 0.0),
            "resistance_posture": dict(packet.get("resistance_posture", {})),
            "game_state": dict(packet.get("game_state", {})),
            "self_model": dict(packet.get("self_model", {})),
            "autobiographical_state": dict(packet.get("autobiographical_state", {})),
            "goal_state": dict(packet.get("goal_state", {})),
            "goal_alignment": dict(packet.get("goal_alignment", {})),
            "identity_consistency": dict(packet.get("identity_consistency", {})),
            "chapter_relevance": str(packet.get("chapter_relevance", "") or ""),
            "self_narrative_hint": str(packet.get("self_narrative_hint", "") or ""),
            "affect_state": dict(packet.get("affect_state", {})),
            "drive_state": dict(packet.get("drive_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "roadmap_registry": self.roadmap_registry(),
        }

    def trace_counterfactual(
        self,
        *,
        query: str,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 3,
    ) -> dict[str, Any]:
        trace = self.trace_action_selection(query=query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=max(3, int(limit)))
        market = list(trace.get("action_market_v3", trace.get("action_market_v2", trace.get("action_market", []))))[: max(1, int(limit))]
        return {
            "thread_key": trace.get("thread_key", ""),
            "chat_name": trace.get("chat_name", ""),
            "channel": channel,
            "query": query,
            "counterfactual_set": [dict(item.get("predicted_outcome", {})) | {"action_type": str(item.get("action_type", ""))} for item in market],
            "selected_action": dict(trace.get("selected_action", {})),
            "selected_prediction": dict(trace.get("selected_prediction", {})),
            "counterfactual_summary": dict(trace.get("counterfactual_summary", {})),
            "predicted_best_outcome": dict(trace.get("predicted_best_outcome", {})),
            "predicted_worst_outcome": dict(trace.get("predicted_worst_outcome", {})),
            "uncertainty_level": float(trace.get("uncertainty_level", 0.0) or 0.0),
            "lookup_reason": str(trace.get("lookup_reason", "") or ""),
            "action_rationale": str(trace.get("action_rationale", "") or ""),
            "world_state": dict(trace.get("world_state", {})),
            "goal_alignment": dict(trace.get("goal_alignment", {})),
            "identity_consistency": dict(trace.get("identity_consistency", {})),
            "chapter_relevance": str(trace.get("chapter_relevance", "") or ""),
        }

    def trace_self_continuity(self) -> dict[str, Any]:
        autobiographical_state = self.autobiographical_state()
        self_model = self.self_model_state()
        goal_state = self.goal_state()
        recent_changes = list(autobiographical_state.get("recent_changes", []))
        turning_points = list(autobiographical_state.get("turning_points", []))
        explanations = list(autobiographical_state.get("self_explanations", []))
        current_chapter = str(autobiographical_state.get("current_chapter", "") or "")
        identity_arc = str(autobiographical_state.get("identity_arc", "") or "")
        why_changed = explanations[-3:]
        return {
            "autobiographical_state": autobiographical_state,
            "goal_state": goal_state,
            "self_model": self_model,
            "identity_arc": identity_arc,
            "current_chapter": current_chapter,
            "turning_points": turning_points[-6:],
            "recent_changes": recent_changes[-6:],
            "self_explanations": why_changed,
            "why_changed_summary": " | ".join(str(item.get("summary", "") or "") for item in why_changed if isinstance(item, dict) and str(item.get("summary", "")).strip()),
        }

    def trace_goal_arbitration(self) -> dict[str, Any]:
        goal_state = self.goal_state()
        autobio = self.autobiographical_state()
        active_goals = list(goal_state.get("active_goals", []))
        return {
            "goal_state": goal_state,
            "autobiographical_state": autobio,
            "active_goals": active_goals,
            "goal_conflicts": list(goal_state.get("goal_conflicts", [])),
            "goal_commitments": list(goal_state.get("goal_commitments", [])),
            "next_goal_windows": list(goal_state.get("next_goal_windows", [])),
            "current_chapter": str(autobio.get("current_chapter", "") or ""),
        }

    def trace_world_calibration(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        state = self._subject_state(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))
        world_state = dict(state.get("world_state", {}))
        return {
            "thread_key": str(state.get("thread_key", thread_key or "")),
            "chat_name": str(state.get("chat_name", chat_name or "")),
            "channel": channel,
            "world_state": world_state,
            "last_counterfactual_summary": dict(world_state.get("last_counterfactual_summary", {})),
            "last_post_outcome_calibration": dict(world_state.get("last_post_outcome_calibration", {})),
            "recent_outcome_history": list(world_state.get("recent_outcome_history", [])),
            "recent_prediction_errors": list(world_state.get("recent_prediction_errors", [])),
            "action_calibration_summary": dict(world_state.get("action_calibration_summary", {})),
            "response_expectations": dict(world_state.get("response_expectations", {})),
            "updated_at": str(state.get("updated_at", "")),
        }

    def show_action_calibration(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        scenario_bucket: str | None = None,
        limit: int = 24,
    ) -> dict[str, Any]:
        state = self._subject_state(channel=channel, thread_key=str(thread_key or ""), chat_name=str(chat_name or ""))
        rows = self.graph.list_action_calibration(
            channel=channel,
            thread_key=str(state.get("thread_key", thread_key or "")),
            chat_name=str(state.get("chat_name", chat_name or "")),
            action_type=action_type,
            scenario_bucket=scenario_bucket,
            limit=limit,
        )
        return {
            "thread_key": str(state.get("thread_key", thread_key or "")),
            "chat_name": str(state.get("chat_name", chat_name or "")),
            "channel": channel,
            "rows": rows,
        }

    def show_policy_candidates(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_policy_candidates"):
            return {"status": "unavailable", "candidates": [], "count": 0}
        return self.graph.show_policy_candidates(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def show_promoted_policies(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_promoted_policies"):
            return {"status": "unavailable", "promoted_policies": [], "count": 0}
        return self.graph.show_promoted_policies(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def rollback_policy(self, *, policy_id: str, reason: str = "") -> dict[str, Any]:
        if not hasattr(self.graph, "rollback_policy"):
            return {"status": "unavailable", "reason": "policy_sedimentation_unavailable"}
        payload = self.graph.rollback_policy(policy_id=policy_id, reason=reason)
        self.clear_packet_cache()
        return payload

    def trace_policy_influence(
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
                context={"channel": channel, "thread_key": normalized_thread_key, "chat_name": normalized_chat_name},
            )
            market = list(packet.get("action_market", []))[: max(1, int(limit or 8))]
            stage21 = dict(packet.get("stage21", {}))
            selected = dict(packet.get("selected_action", {}))
        else:
            payload = self.action_market(thread_key=thread_key, chat_name=chat_name, channel=channel, query="", limit=limit)
            market = list(payload.get("action_market_v4", payload.get("action_market", [])))[: max(1, int(limit or 8))]
            stage21 = dict(payload.get("stage21", {}))
            selected = dict(payload.get("selected_action", {}))
        promoted = self.show_promoted_policies(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)
        influence_rows = [
            {
                "action_type": str(item.get("action_type", "") or ""),
                "score": float(item.get("score", 0.0) or 0.0),
                "policy_sedimentation_delta": float(item.get("policy_sedimentation_delta", 0.0) or 0.0),
                "policy_scenario_bucket": str(item.get("policy_scenario_bucket", "") or ""),
                "policy_sedimentation": dict(item.get("policy_sedimentation", {})) if isinstance(item.get("policy_sedimentation", {}), dict) else {},
            }
            for item in market
        ]
        return {
            "status": "ok",
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "query": str(query or ""),
            "stage21": stage21,
            "selected_action": selected,
            "policy_influence": influence_rows,
            "promoted_policies": list(promoted.get("promoted_policies", [])),
        }

    def trace_outcome_history(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return self.graph.trace_outcome_history(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            limit=limit,
        )

    def trace_action_prediction_error(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        action_type: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return self.graph.trace_action_prediction_error(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            limit=limit,
        )

    def run_stage14_replay(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
        mode: str = "all",
    ) -> dict[str, Any]:
        from .stage14_replay import Stage14ReplayHarness

        return Stage14ReplayHarness(self).run(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
            mode=mode,
        )

    def replay_calibration_fixture(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self.run_stage14_replay(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
            mode="calibration",
        )

    def replay_policy_regret(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        return self.run_stage14_replay(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
            mode="policy",
        )

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
        world_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_prediction = dict(selected_action.get("predicted_outcome", {}))
        next_world_state = dict(world_state or {})
        goal_alignment = {
            "score": float(selected_action.get("goal_alignment_score", 0.0) or 0.0),
            "rationale": str(selected_action.get("goal_rationale", "") or ""),
        }
        identity_consistency = {
            "score": float(selected_action.get("identity_consistency_score", 0.0) or 0.0),
            "rationale": str(selected_action.get("identity_rationale", "") or ""),
        }
        next_world_state["last_counterfactual_summary"] = {
            "selected_action": str(selected_action.get("action_type", "") or ""),
            "selected_prediction": selected_prediction,
            "evaluated_actions": [str(item.get("action_type", "") or "") for item in action_market[:3]],
            "at": utc_now(),
        }
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
            "last_intent_state_v2": dict(intent_state),
            "last_intent_state_v3": dict(intent_state),
            "last_intent_state_v4": dict(intent_state),
            "last_action_market": list(action_market),
            "last_action_market_v2": list(action_market),
            "last_action_market_v3": list(action_market),
            "last_action_market_v4": list(action_market),
            "last_selected_action": dict(selected_action),
            "last_expression_budget": int(expression_budget),
            "last_expression_budget_v2": int(expression_budget),
            "last_expression_budget_v3": int(expression_budget),
            "last_expression_budget_v4": int(expression_budget),
            "last_silence_reason": str(silence_reason or ""),
            "last_defer_reason": str(defer_reason or ""),
            "last_action_rationale": str(action_rationale or ""),
            "last_counterfactual_summary": selected_prediction,
            "last_goal_alignment": goal_alignment,
            "last_identity_consistency": identity_consistency,
            "last_stage21_policy": self._stage21_policy_trace(action_market=list(action_market), selected_action=dict(selected_action), context={"channel": channel, "thread_key": thread_key, "chat_name": chat_name}),
            "last_chapter_relevance": str(selected_action.get("chapter_relevance", "") or ""),
            "last_self_narrative_hint": str(selected_action.get("self_narrative_hint", "") or ""),
        }
        updated = self.graph.update_subject_state(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            world_state=next_world_state,
            metadata=metadata,
            note=f"action_selection:{selected_action.get('action_type', 'reply_once')}",
            source="stage6_action_selection",
        )
        self.clear_packet_cache()
        return updated

    def record_consciousness_entry(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        message_id: str = "",
        event_row_id: int | None = None,
        entry_type: str,
        selected_action: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.graph.record_consciousness_entry(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            message_id=message_id,
            event_row_id=event_row_id,
            entry_type=entry_type,
            selected_action=selected_action,
            payload=payload,
        )

    def consciousness_ledger(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or chat_name or "").strip()
        normalized_chat_name = str(chat_name or thread_key or normalized_thread_key).strip()
        entries = self.graph.list_consciousness_ledger(
            channel=channel,
            thread_key=normalized_thread_key or None,
            chat_name=normalized_chat_name or None,
            limit=max(1, int(limit)),
        )
        return {
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "channel": channel,
            "entries": entries,
            "count": len(entries),
        }

    def trace_deliberation_ledger(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> dict[str, Any]:
        payload = self.consciousness_ledger(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )
        payload["roadmap_registry"] = self.roadmap_registry()
        return payload

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
        if hasattr(self.graph, "update_dense_working_set_from_stream"):
            report["dense_working_set"] = self.graph.update_dense_working_set_from_stream(
                stream_name,
                report=report,
                max_hot_threads_per_cycle=int(self.stage25_budget.get("max_hot_threads_per_cycle", 6) or 6),
                per_thread_pulse_budget=int(self.stage25_budget.get("per_thread_pulse_budget", 2) or 2),
                cooldown_seconds_by_stream=dict(self.stage25_budget.get("cooldown_seconds_by_stream", {})),
                skip_cold_without_pressure=bool(self.stage25_budget.get("skip_cold_without_pressure", True)),
                max_dense_working_set_threads=int(self.stage25_budget.get("max_dense_working_set_threads", 8) or 8),
            )
        self.clear_packet_cache()
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
        for item in list(dict(report.get("influence", {})).get("frontier_updates", [])):
            if not isinstance(item, dict):
                continue
            frontier_thread_key = str(item.get("canonical_thread_key", item.get("thread_key", "")) or "").strip()
            frontier_channel = str(item.get("channel", "") or "").strip()
            if not frontier_thread_key or not frontier_channel:
                continue
            self.activation.record(
                channel=frontier_channel,
                thread_key=frontier_thread_key,
                chat_name=str(item.get("chat_name", "") or frontier_thread_key),
                contributor=stream_name,
                note=str(item.get("wake_reason", "") or note),
                node_ids=[],
                motifs=[
                    str(item.get("wake_reason", "") or ""),
                    str(item.get("anticipated_next_turn", "") or ""),
                ],
                payload={"stage19_attention_frontier": item},
                heat_delta=min(0.18, 0.05 + float(item.get("thread_heat", 0.0) or 0.0) * 0.12),
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
                    **self._initiative_candidate_fields(
                        pressure * 0.72 + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.28,
                        send_allowed=True,
                    ),
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
                    **self._initiative_candidate_fields(
                        float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.58
                        + float(relationship.get("continuity_score", 0.0) or 0.0) * 0.42,
                        send_allowed=True,
                    ),
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
                    **self._initiative_candidate_fields(
                        float(drive_state.get("seek_play", 0.0) or 0.0) * 0.52
                        + float(relationship.get("trust_score", 0.0) or 0.0) * 0.22
                        + float(initiative_state.get("pressure", 0.0) or 0.0) * 0.26,
                        send_allowed=True,
                    ),
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
                        "initiative_confidence": float(candidate.get("initiative_confidence", 0.0) or 0.0),
                        "gate_hint": str(candidate.get("gate_hint", "") or ""),
                        "override_priority": float(candidate.get("override_priority", 0.0) or 0.0),
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
        graph_rows = self.graph.list_initiative_market(limit=limit, statuses=("candidate", "override_pending", "scheduled", "blocked", "sent"))
        normalized: list[dict[str, Any]] = []
        for row in graph_rows:
            metadata = dict(row.get("metadata", {}))
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
                    "initiative_confidence": float(metadata.get("initiative_confidence", 0.0) or 0.0),
                    "gate_hint": str(metadata.get("gate_hint", "") or ""),
                    "override_priority": float(metadata.get("override_priority", 0.0) or 0.0),
                    "gate_level": str(metadata.get("gate_level", "") or ""),
                    "soft_gate_score": float(metadata.get("soft_gate_score", 0.0) or 0.0),
                    "override_eligible": bool(metadata.get("override_eligible", False)),
                    "main_brain_override_applied": bool(metadata.get("main_brain_override_applied", False)),
                    "blocked_reason_code": str(metadata.get("blocked_reason_code", "") or metadata.get("blocked_reason", "") or ""),
                    "metadata": metadata,
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
            "Return JSON only with keys scene_summary, objects, text_ocr, mood_imagery, thread_relevance, "
            "visual_anchors, spatial_refs, uncertainty_markers, revisit_needed, perceptual_density. "
            "Use concise Chinese. visual_anchors should be 1 to 4 short recallable anchors. "
            "spatial_refs should name visible regions such as left/top/right/center when useful. "
            "uncertainty_markers should list only visual details that need another look or user confirmation.\n\n"
            f"Thread:\nchannel={channel}\nthread_key={thread_key}\nchat_name={chat_name}\n\n"
            f"Artifact report:\n{json.dumps(artifact_report, ensure_ascii=False, indent=2)}\n\n"
            f"Note:\n{str(note or '').strip()}"
        )

    def _run_image_understand(self, *, image_path: str, prompt: str) -> dict[str, Any]:
        if self.runner is None or not hasattr(self.runner, "run_task"):
            return {
                "payload": {},
                "processor": {
                    "status": "unavailable",
                    "provider": "",
                    "capabilities": {},
                    "image_paths": [str(image_path)],
                },
            }
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
        metadata = dict(result.metadata or {}) if isinstance(result.metadata, dict) else {}
        processor = {
            "status": "ok" if int(result.returncode or 0) == 0 else "error",
            "provider": str(metadata.get("provider", "") or ""),
            "lane": str(metadata.get("lane", "") or ""),
            "model": str(metadata.get("model", "") or ""),
            "capabilities": dict(metadata.get("capabilities", {})) if isinstance(metadata.get("capabilities", {}), dict) else {},
            "duration_ms": int(metadata.get("duration_ms", 0) or 0),
            "image_paths": [str(image_path)],
            "returncode": int(result.returncode or 0),
            "stderr": compact_text(str(result.stderr or ""), 240),
        }
        try:
            payload = json.loads(result.text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return {
            "payload": payload if isinstance(payload, dict) else {},
            "processor": processor,
        }

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
        channel: str = "",
        thread_key: str = "",
        chat_name: str = "",
        world_cue_type: str = "",
        due_at: str = "",
    ) -> dict[str, Any]:
        artifact = self.rag.ingest_artifact_result(path, note=note, source=source, tags=tags, dry_run=dry_run)
        cue_type = str(world_cue_type or "").strip()
        task_world_object = {}
        if not dry_run and hasattr(self.graph, "upsert_task_world_object"):
            artifact_metadata = dict(artifact.get("metadata", {})) if isinstance(artifact.get("metadata", {}), dict) else {}
            object_type = (
                "schedule"
                if str(due_at or "").strip()
                else TASK_WORLD_CUE_TO_OBJECT.get(cue_type, "file")
            )
            task_world_object = self.graph.upsert_task_world_object(
                object_type=object_type,
                summary=compact_text(
                    str(artifact.get("summary_text", "") or artifact.get("extracted_excerpt", "") or note or path),
                    240,
                ),
                source_ref=str(path),
                confidence=0.64,
                stale_after=str(due_at or "").strip(),
                linked_threads=[_normalize_thread_key(channel or "wechat", str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())],
                linked_commitments=[],
                status="live",
                metadata={
                    "artifact": artifact,
                    "note": note or "",
                    "source": source,
                    "tags": list(tags),
                    **({"artifact_digest": str(artifact_metadata.get("artifact_digest", "") or "")} if str(artifact_metadata.get("artifact_digest", "") or "").strip() else {}),
                    **({"due_at": str(due_at or "").strip()} if str(due_at or "").strip() else {}),
                },
            )
            if task_world_object.get("present", False):
                artifact["task_world_object"] = task_world_object
        if cue_type and not dry_run and hasattr(self.graph, "upsert_world_coupling_signal"):
            cue_summary = compact_text(
                str(artifact.get("summary_text", "") or artifact.get("extracted_excerpt", "") or note or path),
                240,
            )
            metadata = {
                "artifact": artifact,
                "note": note or "",
                "source": source,
                **({"due_at": str(due_at or "").strip()} if str(due_at or "").strip() else {}),
            }
            artifact_metadata = dict(artifact.get("metadata", {})) if isinstance(artifact.get("metadata", {}), dict) else {}
            artifact["world_coupling_signal"] = self.graph.upsert_world_coupling_signal(
                channel=channel or "wechat",
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                cue_type=cue_type,
                summary=cue_summary,
                source_ref=str(path),
                confidence=0.64,
                evidence_refs=[f"artifact:{str(artifact_metadata.get('artifact_digest', '') or stable_digest(str(path), cue_summary))}"],
                metadata=metadata,
            )
        if not dry_run and (task_world_object or cue_type):
            self.clear_packet_cache()
        return artifact

    def record_world_coupling_signal(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
        cue_type: str,
        summary: str,
        source_ref: str = "",
        confidence: float = 0.62,
        stale_after: str = "",
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "upsert_world_coupling_signal"):
            return {"status": "unavailable", "present": False}
        return self.graph.upsert_world_coupling_signal(
            channel=channel,
            thread_key=str(thread_key or chat_name or ""),
            chat_name=str(chat_name or thread_key or ""),
            cue_type=cue_type,
            summary=summary,
            source_ref=source_ref,
            confidence=confidence,
            stale_after=stale_after,
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
        )

    def show_world_coupling(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        if not hasattr(self.graph, "show_world_coupling"):
            return {"status": "unavailable", "count": 0, "items": []}
        return self.graph.show_world_coupling(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            include_inactive=include_inactive,
        )

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
        understanding_report = self._run_image_understand(
            image_path=str(path),
            prompt=self._visual_understand_prompt(
                artifact_report=artifact,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                channel=channel,
                note=note,
            ),
        )
        understanding = dict(understanding_report.get("payload", {})) if isinstance(understanding_report.get("payload", {}), dict) else {}
        image_understand = dict(understanding_report.get("processor", {})) if isinstance(understanding_report.get("processor", {}), dict) else {}
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
            image_understand["fallback_used"] = True
        else:
            image_understand["fallback_used"] = False
        visual_payload = {
            "scene_summary": str(understanding.get("scene_summary", artifact.get("summary_text", "")) or ""),
            "objects": self._coerce_visual_list(understanding.get("objects")),
            "text_ocr": str(understanding.get("text_ocr", artifact.get("extracted_excerpt", "")) or ""),
            "mood_imagery": str(understanding.get("mood_imagery", "") or ""),
            "thread_relevance": self._coerce_float(understanding.get("thread_relevance", 0.62) or 0.62) or 0.62,
            "visual_anchors": self._coerce_visual_list(understanding.get("visual_anchors")),
            "spatial_refs": self._coerce_visual_list(understanding.get("spatial_refs")),
            "uncertainty_markers": self._coerce_visual_list(understanding.get("uncertainty_markers")),
            "revisit_needed": bool(understanding.get("revisit_needed", False)),
            "perceptual_density": str(understanding.get("perceptual_density", "") or ""),
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
            metadata={
                "artifact": artifact,
                "note": note or "",
                "sync": bool(sync),
                "spatial_refs": list(visual_payload["spatial_refs"]),
                "uncertainty_markers": list(visual_payload["uncertainty_markers"]),
                "revisit_needed": bool(visual_payload["revisit_needed"]),
                "perceptual_density": str(visual_payload["perceptual_density"]),
                "image_understand": image_understand,
            },
            source=source,
        )
        world_signal = {}
        if hasattr(self.graph, "upsert_world_coupling_signal"):
            world_signal = self.graph.upsert_world_coupling_signal(
                channel=channel,
                thread_key=thread_key or chat_name,
                chat_name=chat_name or thread_key,
                cue_type="image_summary",
                summary=visual_payload["scene_summary"] or visual_payload["text_ocr"] or str(note or path),
                source_ref=str(path),
                confidence=float(visual_payload.get("thread_relevance", 0.62) or 0.62),
                evidence_refs=[f"visual_memory:{upsert.get('id', '')}"],
                metadata={"visual_memory": visual_payload, "artifact": artifact, "source": source},
            )
        task_world_object = {}
        if hasattr(self.graph, "upsert_task_world_object"):
            task_world_object = self.graph.upsert_task_world_object(
                object_type="image_summary",
                summary=visual_payload["scene_summary"] or visual_payload["text_ocr"] or str(note or path),
                source_ref=str(path),
                confidence=float(visual_payload.get("thread_relevance", 0.62) or 0.62),
                stale_after="",
                linked_threads=[_normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())],
                linked_commitments=[],
                status="live",
                metadata={"visual_memory": visual_payload, "artifact": artifact, "source": source},
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
        self.clear_packet_cache()
        return {
            "status": "ok",
            "artifact": artifact,
            "image_understand": image_understand,
            "visual_memory": visual_payload,
            "graph_sync": upsert,
            "world_coupling_signal": world_signal,
            "task_world_object": task_world_object,
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
