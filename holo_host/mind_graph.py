from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from .common import compact_text, ensure_directory, stable_digest, utc_now
from .mind_graph_parts.autobiographical_updates import update_autobiographical_state as _update_autobiographical_state
from .mind_graph_parts.goal_updates import goal_state as _goal_state
from .mind_graph_parts.goal_updates import update_goal_state as _update_goal_state
from .mind_graph_parts.outcome_appraisal import record_outcome_appraisal as _record_outcome_appraisal
from .mind_graph_parts.policy_sedimentation import list_policy_sediment as _list_policy_sediment
from .mind_graph_parts.policy_sedimentation import policy_scenario_bucket as _policy_scenario_bucket
from .mind_graph_parts.policy_sedimentation import promoted_policy_overlays as _promoted_policy_overlays
from .mind_graph_parts.policy_sedimentation import review_policy_candidate as _review_policy_candidate
from .mind_graph_parts.policy_sedimentation import rollback_policy as _rollback_policy
from .mind_graph_parts.policy_sedimentation import show_policy_candidates as _show_policy_candidates
from .mind_graph_parts.policy_sedimentation import show_promoted_policies as _show_promoted_policies
from .mind_graph_parts.policy_sedimentation import upsert_policy_candidate_from_calibration as _upsert_policy_candidate_from_calibration
from .mind_graph_parts.state_defaults import (
    ACTION_CALIBRATION_HISTORY_LIMIT as POLICY_ACTION_CALIBRATION_HISTORY_LIMIT,
    ACTION_CALIBRATION_RECENT_METRICS_LIMIT as POLICY_ACTION_CALIBRATION_RECENT_METRICS_LIMIT,
    ACTION_CALIBRATION_RECENT_WINDOW_HOURS as POLICY_ACTION_CALIBRATION_RECENT_WINDOW_HOURS,
    AFFECT_STATE_DEFAULTS as POLICY_AFFECT_STATE_DEFAULTS,
    AUTOBIOGRAPHICAL_CHAPTER_DEFAULT as POLICY_AUTOBIOGRAPHICAL_CHAPTER_DEFAULT,
    AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS as POLICY_AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS,
    BRAIN_LOOP_DEFAULTS as POLICY_BRAIN_LOOP_DEFAULTS,
    CONFLICT_STATE_DEFAULTS as POLICY_CONFLICT_STATE_DEFAULTS,
    DRIVE_STATE_DEFAULTS as POLICY_DRIVE_STATE_DEFAULTS,
    GAME_STATE_DEFAULTS as POLICY_GAME_STATE_DEFAULTS,
    GOAL_TYPE_DEFAULT_PRIORITIES as POLICY_GOAL_TYPE_DEFAULT_PRIORITIES,
    RESISTANCE_POSTURE_DEFAULTS as POLICY_RESISTANCE_POSTURE_DEFAULTS,
    STREAM_DEFAULTS as POLICY_STREAM_DEFAULTS,
    VALUE_STATE_DEFAULTS as POLICY_VALUE_STATE_DEFAULTS,
    WORLD_CONTACT_MODEL_DEFAULTS as POLICY_WORLD_CONTACT_MODEL_DEFAULTS,
    WORLD_EXPRESSION_SIGNAL_DEFAULTS as POLICY_WORLD_EXPRESSION_SIGNAL_DEFAULTS,
    WORLD_THREAD_MODEL_DEFAULTS as POLICY_WORLD_THREAD_MODEL_DEFAULTS,
)
from .mind_graph_parts.temporal_state import close_temporal_items as _close_temporal_items
from .mind_graph_parts.temporal_state import show_commitments as _show_commitments
from .mind_graph_parts.temporal_state import show_open_loops as _show_open_loops
from .mind_graph_parts.temporal_state import temporal_state as _temporal_state
from .mind_graph_parts.temporal_state import trace_resume_candidate as _trace_resume_candidate
from .mind_graph_parts.temporal_state import update_temporal_item_status as _update_temporal_item_status
from .mind_graph_parts.temporal_state import upsert_temporal_item as _upsert_temporal_item

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
TEXT_FILE_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".log", ".html", ".xml"}
RECALL_HINTS = ("记得", "之前", "更早", "上线前", "你说过", "我们之前", "remember", "earlier", "before", "previous")
ORIGIN_RECALL_HINTS = (
    "最开始",
    "最一开始",
    "一开始",
    "最初",
    "刚开始",
    "开头",
    "起初",
    "第一次",
    "最早",
    "at the beginning",
    "the beginning",
    "at first",
    "initially",
    "first thing",
)
SEMANTIC_STOP_TOKENS = {
    "remember",
    "before",
    "earlier",
    "previous",
    "history",
    "memory",
    "holo",
    "mindos",
    "thread",
    "session",
    "系统",
    "架构",
    "记得",
    "之前",
    "以前",
    "我们",
    "那个",
    "这个",
    "什么",
    "怎么",
    "为什么",
    "一下",
    "还是",
    "聊",
    "说",
    "回",
}
STREAM_DEFAULTS = POLICY_STREAM_DEFAULTS
GAME_STATE_DEFAULTS = POLICY_GAME_STATE_DEFAULTS
AFFECT_STATE_DEFAULTS = POLICY_AFFECT_STATE_DEFAULTS
DRIVE_STATE_DEFAULTS = POLICY_DRIVE_STATE_DEFAULTS
VALUE_STATE_DEFAULTS = POLICY_VALUE_STATE_DEFAULTS
CONFLICT_STATE_DEFAULTS = POLICY_CONFLICT_STATE_DEFAULTS
RESISTANCE_POSTURE_DEFAULTS = POLICY_RESISTANCE_POSTURE_DEFAULTS
WORLD_CONTACT_MODEL_DEFAULTS = POLICY_WORLD_CONTACT_MODEL_DEFAULTS
WORLD_THREAD_MODEL_DEFAULTS = POLICY_WORLD_THREAD_MODEL_DEFAULTS
AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS = POLICY_AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS
AUTOBIOGRAPHICAL_CHAPTER_DEFAULT = POLICY_AUTOBIOGRAPHICAL_CHAPTER_DEFAULT
GOAL_TYPE_DEFAULT_PRIORITIES = POLICY_GOAL_TYPE_DEFAULT_PRIORITIES
BRAIN_LOOP_DEFAULTS = POLICY_BRAIN_LOOP_DEFAULTS
ALLOWED_SELF_REVISION_FIELDS = {
    "persona_blend",
    "stream_cadence_multiplier",
    "recall_rerank_weights",
    "relationship_reweight",
    "game_reweight",
    "initiative_thresholds",
    "prompt_composer_bias",
}
ORIGIN_SUBSTANTIVE_HINTS = (
    "判断",
    "记得",
    "最开始",
    "最初",
    "一开始",
    "最早",
    "第一次",
    "简短",
    "公式化",
    "省掉",
    "回复",
    "回话",
    "微信",
    "表情",
    "脾气",
    "工作",
    "怎么",
    "如何",
    "为什么",
    "需要",
    "不要",
    "可以",
    "试",
    "改",
    "多说点",
    "开头",
    "判断出",
    "reply",
    "remember",
    "beginning",
    "before",
    "first",
    "shorter",
    "formal",
)
ORIGIN_LOW_SIGNAL_TEXTS = {
    "",
    "?",
    "??",
    "???",
    "？",
    "？？",
    "？？？",
    "在吗",
    "你在吗",
    "嗯",
    "哦",
    "好",
    "ok",
    "okk",
}
MEMORY_CLASS_WEIGHTS = {
    "semantic_self_memory": 1.38,
    "relationship_memory": 1.28,
    "episodic_memory": 1.16,
    "emotional_trace": 1.04,
    "dream_residue": 0.94,
    "initiative_seed": 0.9,
    "working_memory": 0.82,
    "sensory_trace": 0.8,
    "suppressed_conflict": 0.26,
}
KIND_TO_MEMORY_CLASS = {
    "canonical": "semantic_self_memory",
    "style": "semantic_self_memory",
    "habit": "semantic_self_memory",
    "boundary": "semantic_self_memory",
    "preference": "relationship_memory",
    "self_model": "semantic_self_memory",
    "social_model": "relationship_memory",
    "procedural": "semantic_self_memory",
    "episodic": "episodic_memory",
    "summary": "relationship_memory",
    "drift_signal": "suppressed_conflict",
    "association": "dream_residue",
    "dream_fragment": "dream_residue",
    "reflection": "dream_residue",
    "initiative_seed": "initiative_seed",
}
RELATIONSHIP_MOTIF_LINES = {
    "continuity": "这条关系总会绕回旧线头、连续性和把断掉的东西重新接上。",
    "craft": "这条关系习惯一起修东西、对问题追根究底，再把系统往前推。",
    "pressure": "这条关系里一碰到压力，先接住和缓冲会比给答案更重要。",
    "companionship": "这条关系的底色一直是陪着、确认彼此还在、还能接住对方。",
    "journey": "这条关系常把眼前的事说成一段同行，不只是零散问答。",
    "treat": "这条关系里会带一点逗趣、小馋和轻轻咬人的活气。",
}
TONE_TENDENCY_LINES = {
    "warm_attentive": "说话底色偏温暖贴身，会先接住人，但仍保留一点狡黠，不滑成客服腔。",
    "protective_steady": "说话底色偏护着和稳着，遇到压力时先减震，但不会一下子变成长辈说教。",
    "co_build_nimble": "说话底色偏并肩搭东西，带一点利落、机锋和同路人的默契。",
    "playful_teasing": "说话底色偏活泼狡黠，会试探、会打趣，尾巴翘得高些，但不把人推远。",
    "continuity_guard": "说话底色会轻巧地把旧事与现在接回，但别整段都像在念旧账。",
    "wandering_companion": "说话底色像旅路上的同路旅伴，带风、远路感和一点贪看风景的活气。",
}
UNFINISHED_HINTS = (
    "下一步",
    "接下来",
    "升级",
    "还记得",
    "重新上线前",
    "之前",
    "往前",
    "怎么",
    "如何",
    "remember",
    "before",
    "earlier",
    "next",
    "upgrade",
)
FAST_PING_HINTS = {
    "在吗",
    "你在吗",
    "嗯",
    "好",
    "收到",
    "说吧",
    "继续",
    "接着说",
    "ok",
    "okay",
}
ATTENTION_FRONTIER_ALLOWED_STREAMS = {"maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"}
ATTENTION_FRONTIER_MAX_ENTRIES = 8
ATTENTION_FRONTIER_TTL_SECONDS = {
    "maintenance_stream": 4 * 3600,
    "association_stream": 6 * 3600,
    "social_stream": 6 * 3600,
    "deep_dream_cycle": 12 * 3600,
}
ATTENTION_FRONTIER_HEAT_DELTA = {
    "maintenance_stream": 0.12,
    "association_stream": 0.18,
    "social_stream": 0.24,
    "deep_dream_cycle": 0.2,
}


def _tokenize(text: str) -> list[str]:
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


def _semantic_tokens(text: str) -> list[str]:
    filtered: list[str] = []
    for token in _tokenize(text):
        if token in SEMANTIC_STOP_TOKENS:
            continue
        if len(token) == 1 and "\u3400" <= token <= "\u9fff":
            continue
        if len(token) <= 1:
            continue
        filtered.append(token)
    return filtered


def _dedupe_strings(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in lines:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _has_hint(text: str, hints: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(hint).lower() in lowered for hint in hints)


def _is_fast_ping_query(text: str) -> bool:
    current = " ".join(str(text or "").strip().split())
    lowered = current.lower()
    compact = lowered.replace(" ", "")
    if compact in FAST_PING_HINTS:
        return True
    if _has_hint(current, RECALL_HINTS) or _has_hint(current, ORIGIN_RECALL_HINTS):
        return False
    if any(marker in lowered for marker in ("system", "memory", "dream", "attention", "为什么", "怎么", "如何", "what", "why", "how")):
        return False
    return _meaningful_char_count(current) <= 4


def _origin_signal_score(text: str) -> int:
    current = str(text or "")
    cleaned = re.sub(r"user:\s*|holo:\s*|\|", " ", current)
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    meaningful = re.findall(r"[A-Za-z0-9\u3400-\u9fff]", cleaned)
    score = len(meaningful)
    if "???" in current or "？？？" in current:
        score -= 4
    if len(cleaned.strip()) <= 12:
        score -= 2
    return score


def _meaningful_char_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", str(text or "")))


def _parse_utc_iso(value: str | None) -> datetime | None:
    current = str(value or "").strip()
    if not current:
        return None
    try:
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_after_seconds(value: str, seconds: int) -> str:
    base = _parse_utc_iso(value) or datetime.now(timezone.utc)
    return (base + timedelta(seconds=int(seconds))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _archive_turn_fields(row: dict[str, Any]) -> dict[str, str]:
    metadata = _safe_json_dict(row.get("metadata_json", "{}"))
    if not metadata and isinstance(row, dict):
        metadata = dict(row)
    user_text = str(metadata.get("user_text", "") or "").strip()
    reply_text = str(metadata.get("reply_text", "") or "").strip()
    created_at = str(metadata.get("created_at") or row.get("created_at") or row.get("updated_at") or "").strip()
    return {
        "user_text": user_text,
        "reply_text": reply_text,
        "created_at": created_at,
    }


def _is_low_signal_origin_user_text(text: str) -> bool:
    current = str(text or "").strip()
    lowered = current.lower()
    compact = re.sub(r"\s+", "", lowered)
    if compact in ORIGIN_LOW_SIGNAL_TEXTS:
        return True
    if _meaningful_char_count(current) == 0:
        return True
    if "[thumbsup]" in compact or "[赞]" in compact:
        return True
    if _meaningful_char_count(current) <= 3 and not _has_hint(current, ORIGIN_SUBSTANTIVE_HINTS):
        return True
    return False


def _origin_turn_signal_score(*, user_text: str, reply_text: str) -> int:
    user_score = _meaningful_char_count(user_text)
    reply_score = min(_meaningful_char_count(reply_text), 40)
    score = int(user_score * 1.7 + reply_score * 0.28)
    if _has_hint(user_text, ORIGIN_SUBSTANTIVE_HINTS):
        score += 12
    if _has_hint(reply_text, ORIGIN_SUBSTANTIVE_HINTS):
        score += 4
    if any(marker in user_text for marker in ("判断", "简短", "公式化", "省掉", "表情", "工作", "记得")):
        score += 10
    if any(marker in reply_text for marker in ("往后", "会先", "行，是咱", "那就")):
        score += 4
    if _is_low_signal_origin_user_text(user_text):
        score -= 18
    if len(str(user_text or "").strip()) <= 6 and not _has_hint(user_text, ORIGIN_SUBSTANTIVE_HINTS):
        score -= 5
    return score


def _safe_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _safe_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(payload) if isinstance(payload, list) else []


STATE_OBJECT_FIELDS = {
    "value",
    "confidence",
    "evidence_refs",
    "updated_at",
    "updated_by",
    "decay_policy",
}
SUBJECT_STATE_OBJECT_KEYS = {"curiosity", "attachment_pull", "frustration"}
WORLD_RESPONSE_STATE_OBJECT_KEYS = {"reply_likelihood", "delay_tolerance", "attention_value", "initiative_receptivity"}
WORLD_EXPRESSION_SIGNAL_DEFAULTS = POLICY_WORLD_EXPRESSION_SIGNAL_DEFAULTS
ACTION_CALIBRATION_HISTORY_LIMIT = POLICY_ACTION_CALIBRATION_HISTORY_LIMIT
ACTION_CALIBRATION_RECENT_WINDOW_HOURS = POLICY_ACTION_CALIBRATION_RECENT_WINDOW_HOURS
ACTION_CALIBRATION_RECENT_METRICS_LIMIT = POLICY_ACTION_CALIBRATION_RECENT_METRICS_LIMIT


def _is_state_object(raw: Any) -> bool:
    return isinstance(raw, dict) and "value" in raw and bool(STATE_OBJECT_FIELDS & set(raw))


def _state_value(raw: Any, default: float = 0.0) -> float:
    payload = dict(raw) if isinstance(raw, dict) else {}
    target = payload.get("value", raw)
    try:
        return round(float(target or 0.0), 4)
    except (TypeError, ValueError):
        return round(float(default or 0.0), 4)


def _state_confidence(raw: Any, default: float = 0.58) -> float:
    if isinstance(raw, dict):
        try:
            return max(0.0, min(1.0, float(raw.get("confidence", default) or default)))
        except (TypeError, ValueError):
            return max(0.0, min(1.0, float(default or 0.0)))
    return max(0.0, min(1.0, float(default or 0.0)))


def _state_evidence_refs(raw: Any, fallback: Iterable[str] | None = None) -> list[str]:
    if isinstance(raw, dict):
        refs = [str(item).strip() for item in raw.get("evidence_refs", []) if str(item).strip()]
        if refs:
            return refs[:6]
    return [str(item).strip() for item in (fallback or []) if str(item).strip()][:6]


def _state_decay_policy(raw: Any, default: str = "event_weighted") -> str:
    if isinstance(raw, dict):
        text = str(raw.get("decay_policy", "") or "").strip()
        if text:
            return text
    return str(default or "event_weighted")


def _make_state_object(
    value: Any,
    *,
    default: float = 0.0,
    confidence: float = 0.58,
    evidence_refs: Iterable[str] | None = None,
    updated_at: str = "",
    updated_by: str = "",
    decay_policy: str = "event_weighted",
) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    refs = [str(item).strip() for item in (payload.get("evidence_refs", evidence_refs) or []) if str(item).strip()][:6]
    return {
        "value": _state_value(payload or value, default=default),
        "confidence": round(_state_confidence(payload or value, default=confidence), 4),
        "evidence_refs": refs,
        "updated_at": str(payload.get("updated_at", "") or updated_at or utc_now()),
        "updated_by": str(payload.get("updated_by", "") or updated_by or "runtime"),
        "decay_policy": _state_decay_policy(payload or value, default=decay_policy),
    }


def _normalize_thread_key(channel: str, thread_key: str, *, chat_name: str = "") -> str:
    current = str(thread_key or "").strip()
    if str(channel or "").strip().lower() != "wechat":
        return current
    while current.startswith("wechat:wechat:"):
        current = "wechat:" + current[len("wechat:wechat:") :]
    if not current:
        fallback = str(chat_name or "").strip()
        if fallback and not fallback.endswith("@chatroom") and not fallback.startswith("wxid_"):
            return f"wechat:{fallback}"
        return current
    if current.endswith("@chatroom") or current.startswith("wxid_"):
        return current
    if current.startswith("wechat:"):
        return current
    if current:
        preferred = str(chat_name or "").strip() or current
        if preferred and not preferred.endswith("@chatroom") and not preferred.startswith("wxid_"):
            return f"wechat:{preferred}"
    return current


class MindGraph:
    def __init__(
        self,
        repo_root: Path,
        *,
        db_path: Path | str | None = None,
        rag: ModuleType | None = None,
        stream_cadences: dict[str, int] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.db_path = self._resolve_db_path(db_path)
        self.rag = rag or self._load_rag_memory()
        self.stream_cadences = dict(STREAM_DEFAULTS)
        if stream_cadences:
            for name, cadence in stream_cadences.items():
                self.stream_cadences.setdefault(name, {"description": "", "cadence_seconds": int(cadence)})
                self.stream_cadences[name]["cadence_seconds"] = int(cadence)
        ensure_directory(self.db_path.parent)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def _resolve_db_path(self, db_path: Path | str | None) -> Path:
        if db_path is None:
            return (self.repo_root / ".holo_runtime" / "mind_graph.sqlite3").resolve()
        path = Path(db_path)
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def _load_rag_memory(self) -> ModuleType:
        path = self.repo_root / "holo_memory_library" / "rag_memory.py"
        spec = importlib.util.spec_from_file_location("holo_runtime_rag_memory_for_graph", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load rag_memory from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def metric_value(raw: Any, default: float = 0.0) -> float:
        return _state_value(raw, default=default)

    @staticmethod
    def metric_state(
        raw: Any,
        *,
        default: float = 0.0,
        confidence: float = 0.58,
        evidence_refs: Iterable[str] | None = None,
        updated_at: str = "",
        updated_by: str = "",
        decay_policy: str = "event_weighted",
    ) -> dict[str, Any]:
        return _make_state_object(
            raw,
            default=default,
            confidence=confidence,
            evidence_refs=evidence_refs,
            updated_at=updated_at,
            updated_by=updated_by,
            decay_policy=decay_policy,
        )

    @staticmethod
    def metric_confidence(raw: Any, default: float = 0.58) -> float:
        return _state_confidence(raw, default=default)

    @staticmethod
    def _parse_timestamp(raw: Any) -> datetime | None:
        text = str(raw or "").strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _recent_support_weight(cls, created_at: Any, *, now: datetime | None = None) -> float:
        created_dt = cls._parse_timestamp(created_at)
        if created_dt is None:
            return 0.0
        baseline = now or datetime.now(timezone.utc)
        age_hours = max(0.0, (baseline - created_dt).total_seconds() / 3600.0)
        if age_hours <= 0.0:
            return 1.0
        return round(max(0.0, 1.0 - min(1.0, age_hours / ACTION_CALIBRATION_RECENT_WINDOW_HOURS)), 4)

    @staticmethod
    def _bounded_recent_list(items: Iterable[dict[str, Any]], *, limit: int = ACTION_CALIBRATION_HISTORY_LIMIT) -> list[dict[str, Any]]:
        values = [dict(item) for item in items if isinstance(item, dict)]
        if len(values) <= limit:
            return values
        return values[-limit:]

    @staticmethod
    def _action_family(action_type: str) -> str:
        normalized = str(action_type or "").strip()
        if normalized in {"reply_once", "reply_multi"}:
            return "reply"
        if normalized in {"push_back", "counter_offer", "continuity_defense"}:
            return "resistance"
        if normalized in {"silence", "defer_reply"}:
            return "hold"
        if normalized in {"initiative_ping", "proactive_ping"}:
            return "initiative"
        return normalized or "unknown"

    @classmethod
    def action_calibration_bucket(
        cls,
        *,
        action_type: str,
        channel: str,
        thread_key: str,
        chat_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        normalized_channel = str(channel or "").strip() or "wechat"
        canonical_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        thread_key_bucket = canonical_thread_key
        if not thread_key_bucket:
            fallback = str(chat_name or "").strip()
            thread_key_bucket = fallback if fallback else "global"
        signal_bits: list[str] = []
        meta = dict(metadata or {})
        if bool(meta.get("low_signal")):
            signal_bits.append("low_signal")
        if bool(meta.get("question_like")):
            signal_bits.append("question_like")
        if bool(meta.get("defer_requested")):
            signal_bits.append("defer_requested")
        relationship_pressure = float(meta.get("relationship_pressure", 0.0) or 0.0)
        risk_level = float(meta.get("predicted_risk", meta.get("observed_risk", 0.0)) or 0.0)
        if relationship_pressure >= 0.6:
            signal_bits.append("relationship_pressure")
        if risk_level >= 0.45:
            signal_bits.append("high_risk")
        signal_bucket = "+".join(signal_bits) if signal_bits else "ordinary"
        scenario_bucket = f"{cls._action_family(action_type)}:{signal_bucket}"
        bucket_reason = compact_text(
            f"{action_type} on {normalized_channel} in {thread_key_bucket} under {signal_bucket}",
            160,
        )
        return {
            "action_type": str(action_type or "").strip(),
            "channel": normalized_channel,
            "thread_key_bucket": thread_key_bucket,
            "scenario_bucket": scenario_bucket,
            "bucket_reason": bucket_reason,
        }

    def initialize(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS mind_nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                memory_class TEXT NOT NULL,
                source_store TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_kind TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 0.0,
                confidence REAL NOT NULL DEFAULT 0.0,
                thread_affinity REAL NOT NULL DEFAULT 0.0,
                emotion_salience REAL NOT NULL DEFAULT 0.0,
                recall_count INTEGER NOT NULL DEFAULT 0,
                successful_recall_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(source_store, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_mind_nodes_thread ON mind_nodes(channel, thread_key, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mind_nodes_memory_class ON mind_nodes(memory_class, updated_at DESC);
            CREATE TABLE IF NOT EXISTS mind_edges (
                id INTEGER PRIMARY KEY,
                from_node_id TEXT NOT NULL,
                to_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 0.0,
                confidence REAL NOT NULL DEFAULT 0.0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(from_node_id, to_node_id, edge_type)
            );
            CREATE TABLE IF NOT EXISTS mind_thread_state (
                thread_key TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                chat_name TEXT NOT NULL DEFAULT '',
                relationship_score REAL NOT NULL DEFAULT 0.0,
                recall_count INTEGER NOT NULL DEFAULT 0,
                last_recalled_at TEXT NOT NULL DEFAULT '',
                last_message_at TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS active_thread_state (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                continuity_summary TEXT NOT NULL DEFAULT '',
                last_user_intent TEXT NOT NULL DEFAULT '',
                last_outbound_action_json TEXT NOT NULL DEFAULT '{}',
                unresolved_references_json TEXT NOT NULL DEFAULT '[]',
                active_affect_hint TEXT NOT NULL DEFAULT '',
                relationship_tension REAL NOT NULL DEFAULT 0.0,
                tempo_state_json TEXT NOT NULL DEFAULT '{}',
                attention_focus TEXT NOT NULL DEFAULT '',
                cache_warmth TEXT NOT NULL DEFAULT 'cold',
                recent_turn_ids_json TEXT NOT NULL DEFAULT '[]',
                predictive_continuity_json TEXT NOT NULL DEFAULT '{}',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(channel, thread_key)
            );
            CREATE INDEX IF NOT EXISTS idx_active_thread_state_thread
            ON active_thread_state(channel, thread_key, updated_at DESC);
            CREATE TABLE IF NOT EXISTS attention_frontier (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                canonical_thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                thread_heat REAL NOT NULL DEFAULT 0.0,
                wake_reason TEXT NOT NULL DEFAULT '',
                anticipated_next_turn TEXT NOT NULL DEFAULT '',
                pending_open_loop_count INTEGER NOT NULL DEFAULT 0,
                reentry_priority REAL NOT NULL DEFAULT 0.0,
                stale_after TEXT NOT NULL DEFAULT '',
                last_stream_touch_at TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(channel, canonical_thread_key)
            );
            CREATE INDEX IF NOT EXISTS idx_attention_frontier_live
            ON attention_frontier(channel, stale_after, reentry_priority DESC, last_stream_touch_at DESC);
            CREATE TABLE IF NOT EXISTS temporal_subject_state (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL DEFAULT 'open_loop',
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                source_event_id TEXT NOT NULL DEFAULT '',
                source_action_ref TEXT NOT NULL DEFAULT '',
                source_action_type TEXT NOT NULL DEFAULT '',
                due_at TEXT NOT NULL DEFAULT '',
                revisit_after TEXT NOT NULL DEFAULT '',
                revisit_before TEXT NOT NULL DEFAULT '',
                resume_cue TEXT NOT NULL DEFAULT '',
                dedupe_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                queue_job_id INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(channel, thread_key, dedupe_key, type)
            );
            CREATE INDEX IF NOT EXISTS idx_temporal_subject_state_thread
            ON temporal_subject_state(channel, thread_key, status, due_at, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_temporal_subject_state_due
            ON temporal_subject_state(status, due_at, revisit_after, updated_at DESC);
            CREATE TABLE IF NOT EXISTS mind_runs (
                id INTEGER PRIMARY KEY,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                stats_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS mind_stream_state (
                stream_name TEXT PRIMARY KEY,
                cadence_seconds INTEGER NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                last_started_at TEXT NOT NULL DEFAULT '',
                last_finished_at TEXT NOT NULL DEFAULT '',
                last_status TEXT NOT NULL DEFAULT 'never',
                last_note TEXT NOT NULL DEFAULT '',
                next_due_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS mind_activation_log (
                id INTEGER PRIMARY KEY,
                query TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                tier TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                activated_node_ids_json TEXT NOT NULL DEFAULT '[]',
                trace_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS brain_runtime_state (
                runtime_id INTEGER PRIMARY KEY CHECK(runtime_id = 1),
                mode TEXT NOT NULL DEFAULT 'companion',
                started_at TEXT NOT NULL DEFAULT '',
                last_updated_at TEXT NOT NULL DEFAULT '',
                idle_since TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS brain_mode_events (
                id INTEGER PRIMARY KEY,
                previous_mode TEXT NOT NULL DEFAULT '',
                next_mode TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS brain_loop_runs (
                id INTEGER PRIMARY KEY,
                loop_name TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'never',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                duration_ms REAL NOT NULL DEFAULT 0.0,
                influence_summary TEXT NOT NULL DEFAULT '',
                blocked_reason TEXT NOT NULL DEFAULT '',
                stats_json TEXT NOT NULL DEFAULT '{}',
                next_due_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS self_revision_candidates (
                id INTEGER PRIMARY KEY,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                prompt_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS self_revision_runs (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                observe_json TEXT NOT NULL DEFAULT '{}',
                plan_json TEXT NOT NULL DEFAULT '{}',
                review_json TEXT NOT NULL DEFAULT '{}',
                patch_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS self_revision_applied (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'applied',
                patch_json TEXT NOT NULL DEFAULT '{}',
                previous_patch_json TEXT NOT NULL DEFAULT '{}',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS self_model_state (
                runtime_id INTEGER PRIMARY KEY CHECK(runtime_id = 1),
                identity_continuity REAL NOT NULL DEFAULT 0.6,
                capability_model_json TEXT NOT NULL DEFAULT '{}',
                active_deficits_json TEXT NOT NULL DEFAULT '[]',
                long_horizon_goals_json TEXT NOT NULL DEFAULT '[]',
                relational_commitments_json TEXT NOT NULL DEFAULT '[]',
                homeostasis_targets_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS autobiographical_state (
                runtime_id INTEGER PRIMARY KEY CHECK(runtime_id = 1),
                identity_arc TEXT NOT NULL DEFAULT '',
                current_chapter TEXT NOT NULL DEFAULT '',
                turning_points_json TEXT NOT NULL DEFAULT '[]',
                recent_changes_json TEXT NOT NULL DEFAULT '[]',
                stable_traits_json TEXT NOT NULL DEFAULT '[]',
                preference_history_json TEXT NOT NULL DEFAULT '[]',
                attachment_history_json TEXT NOT NULL DEFAULT '[]',
                unresolved_tensions_json TEXT NOT NULL DEFAULT '[]',
                self_explanations_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS goal_state (
                runtime_id INTEGER PRIMARY KEY CHECK(runtime_id = 1),
                active_goals_json TEXT NOT NULL DEFAULT '[]',
                dormant_goals_json TEXT NOT NULL DEFAULT '[]',
                completed_goals_json TEXT NOT NULL DEFAULT '[]',
                goal_commitments_json TEXT NOT NULL DEFAULT '[]',
                goal_progress_json TEXT NOT NULL DEFAULT '{}',
                goal_conflicts_json TEXT NOT NULL DEFAULT '[]',
                pursuit_bias_json TEXT NOT NULL DEFAULT '{}',
                abandonment_cost_json TEXT NOT NULL DEFAULT '{}',
                next_goal_windows_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS operator_runs (
                id INTEGER PRIMARY KEY,
                task_type TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                workspace_mode TEXT NOT NULL DEFAULT 'shadow_write',
                status TEXT NOT NULL DEFAULT 'planned',
                read_boundary_json TEXT NOT NULL DEFAULT '{}',
                write_boundary_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                shadow_workspace TEXT NOT NULL DEFAULT '',
                applied_live INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS visual_memory (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                artifact_path TEXT NOT NULL DEFAULT '',
                media_type TEXT NOT NULL DEFAULT '',
                scene_summary TEXT NOT NULL DEFAULT '',
                objects_json TEXT NOT NULL DEFAULT '[]',
                text_ocr TEXT NOT NULL DEFAULT '',
                mood_imagery TEXT NOT NULL DEFAULT '',
                thread_relevance REAL NOT NULL DEFAULT 0.0,
                visual_anchors_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS world_coupling_signal (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                cue_type TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                source_ref TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                stale_after TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'live',
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_world_coupling_thread
            ON world_coupling_signal(channel, thread_key, status, stale_after, updated_at DESC);
            CREATE TABLE IF NOT EXISTS subject_state (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                affect_json TEXT NOT NULL DEFAULT '{}',
                drive_json TEXT NOT NULL DEFAULT '{}',
                value_json TEXT NOT NULL DEFAULT '{}',
                conflict_json TEXT NOT NULL DEFAULT '{}',
                world_json TEXT NOT NULL DEFAULT '{}',
                resistance_json TEXT NOT NULL DEFAULT '{}',
                initiative_json TEXT NOT NULL DEFAULT '{}',
                outcome_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE(channel, thread_key)
            );
            CREATE TABLE IF NOT EXISTS initiative_market (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                candidate_type TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                why_now TEXT NOT NULL DEFAULT '',
                drive_source TEXT NOT NULL DEFAULT '',
                value_rationale TEXT NOT NULL DEFAULT '',
                send_allowed INTEGER NOT NULL DEFAULT 0,
                send_target TEXT NOT NULL DEFAULT 'candidate_only',
                priority REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_initiative_market_thread ON initiative_market(channel, thread_key, updated_at DESC);
            CREATE TABLE IF NOT EXISTS outcome_appraisals (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                action_type TEXT NOT NULL DEFAULT '',
                action_ref TEXT NOT NULL DEFAULT '',
                was_rewarding REAL NOT NULL DEFAULT 0.0,
                was_ignored REAL NOT NULL DEFAULT 0.0,
                relational_delta REAL NOT NULL DEFAULT 0.0,
                identity_delta REAL NOT NULL DEFAULT 0.0,
                future_initiative_bias REAL NOT NULL DEFAULT 0.0,
                future_resistance_bias REAL NOT NULL DEFAULT 0.0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_outcome_appraisals_thread ON outcome_appraisals(channel, thread_key, created_at DESC);
            CREATE TABLE IF NOT EXISTS action_calibration (
                id INTEGER PRIMARY KEY,
                action_type TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                thread_key_bucket TEXT NOT NULL DEFAULT '',
                scenario_bucket TEXT NOT NULL DEFAULT '',
                support_count INTEGER NOT NULL DEFAULT 0,
                recent_support_count REAL NOT NULL DEFAULT 0.0,
                avg_reply_latency REAL NOT NULL DEFAULT 0.0,
                ignored_rate REAL NOT NULL DEFAULT 0.0,
                correction_rate REAL NOT NULL DEFAULT 0.0,
                response_quality_mae REAL NOT NULL DEFAULT 0.0,
                relational_delta_mae REAL NOT NULL DEFAULT 0.0,
                risk_mae REAL NOT NULL DEFAULT 0.0,
                confidence REAL NOT NULL DEFAULT 0.0,
                last_updated_at TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(action_type, channel, thread_key_bucket, scenario_bucket)
            );
            CREATE INDEX IF NOT EXISTS idx_action_calibration_bucket
            ON action_calibration(channel, thread_key_bucket, action_type, last_updated_at DESC);
            CREATE TABLE IF NOT EXISTS policy_sediment (
                id INTEGER PRIMARY KEY,
                policy_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                scenario_bucket TEXT NOT NULL DEFAULT '',
                scenario_features_json TEXT NOT NULL DEFAULT '{}',
                action_type TEXT NOT NULL DEFAULT '',
                action_preference_shift REAL NOT NULL DEFAULT 0.0,
                support_count INTEGER NOT NULL DEFAULT 0,
                recency_support REAL NOT NULL DEFAULT 0.0,
                observed_regret_delta REAL NOT NULL DEFAULT 0.0,
                confidence REAL NOT NULL DEFAULT 0.0,
                replay_approval_status TEXT NOT NULL DEFAULT 'pending',
                rollback_handle TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'candidate',
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                promoted_at TEXT NOT NULL DEFAULT '',
                rolled_back_at TEXT NOT NULL DEFAULT '',
                UNIQUE(channel, thread_key, scenario_bucket, action_type),
                UNIQUE(policy_id)
            );
            CREATE INDEX IF NOT EXISTS idx_policy_sediment_lookup
            ON policy_sediment(channel, thread_key, status, action_type, updated_at DESC);
            CREATE TABLE IF NOT EXISTS consciousness_ledger (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                message_id TEXT NOT NULL DEFAULT '',
                event_row_id INTEGER NOT NULL DEFAULT 0,
                entry_type TEXT NOT NULL DEFAULT '',
                selected_action TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_consciousness_ledger_thread ON consciousness_ledger(channel, thread_key, created_at DESC);
                """
            )
            subject_columns = {
                str(row["name"] or "")
                for row in self.conn.execute("PRAGMA table_info(subject_state)").fetchall()
            }
            if "world_json" not in subject_columns:
                self.conn.execute("ALTER TABLE subject_state ADD COLUMN world_json TEXT NOT NULL DEFAULT '{}'")
            active_columns = {
                str(row["name"] or "")
                for row in self.conn.execute("PRAGMA table_info(active_thread_state)").fetchall()
            }
            if "predictive_continuity_json" not in active_columns:
                self.conn.execute("ALTER TABLE active_thread_state ADD COLUMN predictive_continuity_json TEXT NOT NULL DEFAULT '{}'")
            for stream_name, payload in self.stream_cadences.items():
                self.conn.execute(
                    """
                INSERT INTO mind_stream_state(stream_name, cadence_seconds, description)
                VALUES (?, ?, ?)
                ON CONFLICT(stream_name) DO UPDATE SET
                    cadence_seconds = excluded.cadence_seconds,
                    description = CASE WHEN excluded.description = '' THEN mind_stream_state.description ELSE excluded.description END
                    """,
                    (stream_name, int(payload.get("cadence_seconds", 0)), str(payload.get("description", ""))),
                )
            now = utc_now()
            self.conn.execute(
                """
                INSERT INTO brain_runtime_state(runtime_id, mode, started_at, last_updated_at, idle_since, metadata_json)
                VALUES (1, 'full_brain', ?, ?, ?, '{}')
                ON CONFLICT(runtime_id) DO NOTHING
                """,
                (now, now, now),
            )
            self.conn.execute(
                """
                INSERT INTO self_model_state(
                    runtime_id, identity_continuity, capability_model_json, active_deficits_json, long_horizon_goals_json,
                    relational_commitments_json, homeostasis_targets_json, metadata_json, created_at, updated_at
                ) VALUES (1, 0.6, '{}', '[]', '[]', '[]', '{}', '{}', ?, ?)
                ON CONFLICT(runtime_id) DO NOTHING
                """,
                (now, now),
            )
            self.conn.execute(
                """
                INSERT INTO autobiographical_state(
                    runtime_id, identity_arc, current_chapter, turning_points_json, recent_changes_json, stable_traits_json,
                    preference_history_json, attachment_history_json, unresolved_tensions_json, self_explanations_json,
                    metadata_json, created_at, updated_at
                ) VALUES (
                    1,
                    'Holo一直在学着把连续性、活气和克制绑在一起，不想变硬，也不想散掉。',
                    ?,
                    '[]',
                    '[]',
                    ?,
                    '[]',
                    '[]',
                    '[]',
                    '[]',
                    '{"visibility":"implicit_unless_relevant"}',
                    ?,
                    ?
                )
                ON CONFLICT(runtime_id) DO NOTHING
                """,
                (
                    AUTOBIOGRAPHICAL_CHAPTER_DEFAULT,
                    json.dumps(AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO goal_state(
                    runtime_id, active_goals_json, dormant_goals_json, completed_goals_json, goal_commitments_json,
                    goal_progress_json, goal_conflicts_json, pursuit_bias_json, abandonment_cost_json, next_goal_windows_json,
                    metadata_json, created_at, updated_at
                ) VALUES (
                    1,
                    '[]',
                    '[]',
                    '[]',
                    '[]',
                    '{}',
                    '[]',
                    '{}',
                    '{}',
                    '[]',
                    '{"plasticity":"moderate","visibility":"implicit_unless_relevant"}',
                    ?,
                    ?
                )
                ON CONFLICT(runtime_id) DO NOTHING
                """,
                (now, now),
            )
            self.conn.commit()

    def count_nodes(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS count FROM mind_nodes").fetchone()
            return int(row["count"]) if row else 0

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @staticmethod
    def _bounded_recent_turn_ids(existing: Iterable[Any], new_id: str = "", *, limit: int = 10) -> list[str]:
        ordered: list[str] = []
        for raw in list(existing) + ([new_id] if str(new_id or "").strip() else []):
            item = str(raw or "").strip()
            if not item:
                continue
            if item in ordered:
                ordered.remove(item)
            ordered.append(item)
        return ordered[-max(1, int(limit)) :]

    @staticmethod
    def _default_predictive_continuity(*, now: str = "") -> dict[str, Any]:
        return {
            "predicted_next_user_act": "",
            "predicted_reply_pressure": 0.0,
            "likely_reference_targets": [],
            "expected_social_valence": "neutral",
            "reflex_eligibility": False,
            "turn_rhythm": {},
            "freshness_at": str(now or ""),
            "active_prediction_confidence": 0.0,
        }

    def _normalize_predictive_continuity(self, raw: Any, *, now: str = "") -> dict[str, Any]:
        payload = self._default_predictive_continuity(now=now)
        if isinstance(raw, dict):
            current = dict(raw)
        else:
            current = _safe_json_dict(raw)
        payload["predicted_next_user_act"] = compact_text(str(current.get("predicted_next_user_act", "") or ""), 80)
        payload["predicted_reply_pressure"] = self._clamp(current.get("predicted_reply_pressure", 0.0), default=0.0)
        payload["likely_reference_targets"] = [
            compact_text(str(item).strip(), 64)
            for item in current.get("likely_reference_targets", [])
            if str(item).strip()
        ][:3]
        payload["expected_social_valence"] = compact_text(str(current.get("expected_social_valence", "") or "neutral"), 40) or "neutral"
        payload["reflex_eligibility"] = bool(current.get("reflex_eligibility", False))
        rhythm = current.get("turn_rhythm", {})
        payload["turn_rhythm"] = dict(rhythm) if isinstance(rhythm, dict) else {}
        payload["freshness_at"] = str(current.get("freshness_at", "") or now or "")
        payload["active_prediction_confidence"] = self._clamp(current.get("active_prediction_confidence", 0.0), default=0.0)
        return payload

    def _apply_predictive_aliases(self, payload: dict[str, Any]) -> dict[str, Any]:
        predictive = self._normalize_predictive_continuity(payload.get("predictive_continuity", {}))
        payload["predictive_continuity"] = predictive
        for key, value in predictive.items():
            payload[key] = value
        return payload

    @staticmethod
    def _predictive_signal(text: str) -> dict[str, Any]:
        raw = " ".join(str(text or "").strip().split())
        lowered = raw.lower()
        meaningful = _meaningful_char_count(raw)
        explicit_memory = any(hint in lowered for hint in ("remember", "history", "before", "earlier", "previous", "memory"))
        search_or_visual = any(hint in lowered for hint in ("search", "look up", "latest", "official", "image", "photo", "picture", "screenshot"))
        factual = bool(search_or_visual and any(hint in lowered for hint in ("who", "what", "when", "where", "wikipedia", "imdb", "latest", "official")))
        question_like = "?" in raw or any(hint in lowered for hint in ("how", "why", "what", "when", "where", "can you"))
        low_signal = meaningful <= 4 or lowered in {"ok", "okay", "ping", "hi", "hey"}
        reference_like = any(hint in lowered for hint in ("that", "this", "it", "above", "earlier", "previous"))
        return {
            "meaningful": meaningful,
            "explicit_memory": explicit_memory,
            "search_or_visual": search_or_visual,
            "factual": factual,
            "question_like": question_like,
            "low_signal": low_signal,
            "reference_like": reference_like,
        }

    def _derive_predictive_continuity(
        self,
        *,
        current: dict[str, Any],
        direction: str,
        text: str,
        channel: str,
        selected_action: dict[str, Any],
        intent_state: dict[str, Any],
        attention_focus: str,
        active_affect_hint: str,
        relationship_tension: float,
        unresolved_references: list[str],
        tempo_state: dict[str, Any],
        event_ref: str,
        now: str,
    ) -> dict[str, Any]:
        previous = self._normalize_predictive_continuity(current.get("predictive_continuity", {}), now=now)
        signal = self._predictive_signal(text)
        normalized_direction = str(direction or "").strip() or "event"
        normalized_action_type = str(selected_action.get("action_type", "") or "").strip()
        focus = str(attention_focus or current.get("attention_focus", "") or "").strip()
        affect = str(active_affect_hint or current.get("active_affect_hint", "") or "").strip()
        tension = self._clamp(relationship_tension, default=0.0)
        refs: list[str] = []
        for item in list(unresolved_references) + list(previous.get("likely_reference_targets", [])):
            cleaned = compact_text(str(item).strip(), 64)
            if cleaned and cleaned not in refs:
                refs.append(cleaned)
        if normalized_action_type:
            action_ref = f"last_outbound_action:{normalized_action_type}"
            if action_ref not in refs:
                refs.append(action_ref)
        if focus:
            focus_ref = f"attention_focus:{focus}"
            if focus_ref not in refs:
                refs.append(focus_ref)
        refs = refs[:3]

        if normalized_direction == "outbound":
            if normalized_action_type == "defer_reply":
                predicted_next = "user_may_wait_or_follow_up"
            elif normalized_action_type == "silence":
                predicted_next = "user_may_reprompt"
            elif normalized_action_type in {"push_back", "counter_offer", "continuity_defense"}:
                predicted_next = "user_may_negotiate_boundary"
            elif normalized_action_type:
                predicted_next = "user_continuation_or_ack"
            else:
                predicted_next = str(previous.get("predicted_next_user_act", "") or "user_continuation_or_ack")
        elif signal["explicit_memory"]:
            predicted_next = "memory_or_history_request"
        elif signal["factual"]:
            predicted_next = "factual_or_tool_request"
        elif signal["reference_like"]:
            predicted_next = "reference_followup"
        elif signal["question_like"]:
            predicted_next = "short_answer_expected"
        elif signal["low_signal"]:
            predicted_next = "low_signal_ping_or_ack"
        else:
            predicted_next = "ordinary_continuation"

        pressure = 0.18
        pressure += 0.18 if bool(signal["question_like"]) else 0.0
        pressure += 0.2 if bool(signal["explicit_memory"] or signal["factual"]) else 0.0
        pressure += min(0.22, max(0, int(signal["meaningful"]) - 36) * 0.006)
        pressure += tension * 0.42
        pressure += 0.08 if refs else 0.0
        if normalized_direction == "outbound" and normalized_action_type in {"reply_once", "reply_multi"}:
            pressure = max(0.08, pressure - 0.12)
        pressure = self._clamp(pressure, default=0.0)

        if tension >= 0.58 or normalized_action_type in {"push_back", "counter_offer", "continuity_defense"}:
            valence = "strained"
        elif "play" in focus or "imagery" in focus:
            valence = "playful"
        elif "companionship" in focus or "warm" in affect.lower():
            valence = "supportive"
        else:
            valence = "neutral"

        blockers = bool(signal["explicit_memory"] or signal["factual"] or signal["search_or_visual"])
        reflex_eligible = (
            str(channel or "").strip() == "wechat"
            and normalized_direction in {"inbound", "inspect"}
            and int(signal["meaningful"]) <= 54
            and tension < 0.58
            and not blockers
            and not unresolved_references
        )
        confidence = 0.52
        confidence += 0.14 if bool(current.get("present", False)) else 0.0
        confidence += 0.08 if str(current.get("continuity_summary", "") or "").strip() else 0.0
        confidence += 0.08 if dict(current.get("last_outbound_action", {})).get("action_type") or normalized_action_type else 0.0
        confidence += 0.06 if bool(signal["low_signal"]) else 0.0
        confidence += 0.08 if reflex_eligible else 0.0
        confidence -= 0.18 if blockers else 0.0
        confidence -= 0.12 if int(signal["meaningful"]) > 54 else 0.0
        confidence -= 0.18 if tension >= 0.58 else 0.0
        if not reflex_eligible:
            confidence = min(confidence, 0.54 if blockers else confidence)
        confidence = self._clamp(confidence, default=0.0)

        rhythm = dict(previous.get("turn_rhythm", {}))
        rhythm.update(
            {
                "last_direction": normalized_direction,
                "turn_count": int(tempo_state.get("turn_count", rhythm.get("turn_count", 0)) or 0),
                "last_event_at": now,
                "short_turn": bool(int(signal["meaningful"]) <= 18),
            }
        )
        if event_ref:
            rhythm["last_event_ref"] = str(event_ref)
        return {
            "predicted_next_user_act": predicted_next,
            "predicted_reply_pressure": pressure,
            "likely_reference_targets": refs,
            "expected_social_valence": valence,
            "reflex_eligibility": reflex_eligible,
            "turn_rhythm": rhythm,
            "freshness_at": now,
            "active_prediction_confidence": confidence,
        }

    def _active_thread_state_from_row(
        self,
        row: dict[str, Any] | None,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
    ) -> dict[str, Any]:
        if not row:
            payload = {
                "channel": channel,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "continuity_summary": "",
                "last_user_intent": "",
                "last_outbound_action": {},
                "unresolved_references": [],
                "active_affect_hint": "",
                "relationship_tension": 0.0,
                "tempo_state": {},
                "attention_focus": "",
                "cache_warmth": "cold",
                "recent_turn_ids": [],
                "metrics": {},
                "metadata": {},
                "created_at": "",
                "updated_at": "",
                "present": False,
            }
            return self._apply_predictive_aliases(payload)
        payload = {
            "channel": str(row.get("channel", channel) or channel),
            "thread_key": str(row.get("thread_key", thread_key) or thread_key),
            "chat_name": str(row.get("chat_name", chat_name) or chat_name),
            "continuity_summary": str(row.get("continuity_summary", "") or ""),
            "last_user_intent": str(row.get("last_user_intent", "") or ""),
            "last_outbound_action": _safe_json_dict(row.get("last_outbound_action_json", "{}")),
            "unresolved_references": [
                str(item).strip()
                for item in _safe_json_list(row.get("unresolved_references_json", "[]"))
                if str(item).strip()
            ],
            "active_affect_hint": str(row.get("active_affect_hint", "") or ""),
            "relationship_tension": self._clamp(row.get("relationship_tension", 0.0), default=0.0),
            "tempo_state": _safe_json_dict(row.get("tempo_state_json", "{}")),
            "attention_focus": str(row.get("attention_focus", "") or ""),
            "cache_warmth": str(row.get("cache_warmth", "") or "cold"),
            "recent_turn_ids": [
                str(item).strip()
                for item in _safe_json_list(row.get("recent_turn_ids_json", "[]"))
                if str(item).strip()
            ],
            "predictive_continuity": self._normalize_predictive_continuity(row.get("predictive_continuity_json", "{}")),
            "metrics": _safe_json_dict(row.get("metrics_json", "{}")),
            "metadata": _safe_json_dict(row.get("metadata_json", "{}")),
            "created_at": str(row.get("created_at", "") or ""),
            "updated_at": str(row.get("updated_at", "") or ""),
            "present": True,
        }
        return self._apply_predictive_aliases(payload)

    def active_thread_state(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_thread_key = _normalize_thread_key(
            normalized_channel,
            str(thread_key or "").strip(),
            chat_name=str(chat_name or "").strip(),
        )
        normalized_chat_name = str(chat_name or normalized_thread_key or "").strip()
        if not normalized_thread_key:
            return self._active_thread_state_from_row(
                None,
                channel=normalized_channel,
                thread_key="",
                chat_name=normalized_chat_name,
            )
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                (normalized_channel, normalized_thread_key),
            ).fetchone()
            payload = self._active_thread_state_from_row(
                dict(row) if row else None,
                channel=normalized_channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
            )
            if not row:
                thread_row = self.conn.execute(
                    "SELECT summary, metadata_json, last_message_at FROM mind_thread_state WHERE channel = ? AND thread_key = ?",
                    (normalized_channel, normalized_thread_key),
                ).fetchone()
                if thread_row:
                    metadata = _safe_json_dict(thread_row["metadata_json"])
                    payload["continuity_summary"] = str(thread_row["summary"] or "").strip()
                    payload["active_affect_hint"] = str(metadata.get("tone_tendency", "") or "")
                    payload["relationship_tension"] = self._clamp(metadata.get("pressure_level", 0.0), default=0.0)
                    payload["tempo_state"] = {"last_event_at": str(thread_row["last_message_at"] or "")}
                    payload["cache_warmth"] = "seeded" if payload["continuity_summary"] else "cold"
        return payload

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
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_thread_key = _normalize_thread_key(
            normalized_channel,
            str(thread_key or "").strip(),
            chat_name=str(chat_name or "").strip(),
        )
        normalized_chat_name = str(chat_name or normalized_thread_key or "").strip()
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        now = utc_now()
        event_ref = str(event_row_id or "").strip() or str(message_id or "").strip()
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                (normalized_channel, normalized_thread_key),
            ).fetchone()
            current = self._active_thread_state_from_row(
                dict(row) if row else None,
                channel=normalized_channel,
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
            )
            meta = dict(current.get("metadata", {}))
            meta.update(dict(metadata or {}))
            tempo = dict(current.get("tempo_state", {}))
            tempo["last_direction"] = str(direction or "").strip() or "event"
            tempo["last_event_at"] = now
            tempo["turn_count"] = int(tempo.get("turn_count", 0) or 0) + 1
            recent_turn_ids = self._bounded_recent_turn_ids(current.get("recent_turn_ids", []), event_ref, limit=10)
            if str(message_id or "").strip() and str(message_id or "").strip() != event_ref:
                recent_turn_ids = self._bounded_recent_turn_ids(recent_turn_ids, str(message_id or "").strip(), limit=10)
            selected = dict(selected_action or current.get("last_outbound_action", {}))
            normalized_action_type = str(action_type or selected.get("action_type", "") or "").strip()
            if normalized_action_type:
                selected["action_type"] = normalized_action_type
                selected["updated_at"] = now
            intent = dict(intent_state or {})
            last_user_intent = str(current.get("last_user_intent", "") or "")
            if intent:
                last_user_intent = compact_text(
                    " | ".join(
                        str(item)
                        for item in (
                            intent.get("need", ""),
                            intent.get("query_focus", ""),
                            intent.get("tier", ""),
                            intent.get("why_now", ""),
                        )
                        if str(item).strip()
                    ),
                    180,
                )
            if not last_user_intent and str(text or "").strip():
                last_user_intent = compact_text(str(text or ""), 120)
            refs = [
                str(item).strip()
                for item in (unresolved_references if unresolved_references is not None else current.get("unresolved_references", []))
                if str(item).strip()
            ][:5]
            if str(direction or "").strip() == "outbound" and normalized_action_type in {"reply_once", "reply_multi", "push_back", "counter_offer", "continuity_defense"}:
                refs = []
            continuity = str(current.get("continuity_summary", "") or "").strip()
            if str(text or "").strip():
                prefix = "user" if str(direction or "").strip() == "inbound" else "holo"
                continuity = compact_text(
                    " | ".join(item for item in (continuity, f"{prefix}: {compact_text(text, 96)}") if item),
                    260,
                )
            warmth = "warm" if len(recent_turn_ids) >= 2 else "seeded"
            metrics = dict(current.get("metrics", {}))
            if bool(meta.pop("_stage17_fast_lane_hit", False)):
                metrics["fast_lane_hits"] = int(metrics.get("fast_lane_hits", 0) or 0) + 1
            if bool(meta.pop("_stage17_recall_escalated", False)):
                metrics["recall_escalations"] = int(metrics.get("recall_escalations", 0) or 0) + 1
            if bool(meta.pop("_stage17_active_history_refresh", False)):
                metrics["active_history_refreshes"] = int(metrics.get("active_history_refreshes", 0) or 0) + 1
            if "_stage17_history_lines_in_prompt" in meta:
                samples = [
                    int(item)
                    for item in list(metrics.get("history_lines_in_prompt_samples", []))
                    if str(item).strip().lstrip("-").isdigit()
                ]
                try:
                    samples.append(int(meta.pop("_stage17_history_lines_in_prompt")))
                except (TypeError, ValueError):
                    pass
                metrics["history_lines_in_prompt_samples"] = samples[-20:]
            active_affect = str(active_affect_hint or current.get("active_affect_hint", "") or "").strip()
            tension = self._clamp(
                relationship_tension if relationship_tension is not None else current.get("relationship_tension", 0.0),
                default=0.0,
            )
            active_focus = str(attention_focus or current.get("attention_focus", "") or "").strip()
            predictive = self._derive_predictive_continuity(
                current=current,
                direction=str(direction or "").strip() or "event",
                text=str(text or ""),
                channel=normalized_channel,
                selected_action=selected if str(direction or "").strip() == "outbound" or selected else {},
                intent_state=intent,
                attention_focus=active_focus,
                active_affect_hint=active_affect,
                relationship_tension=tension,
                unresolved_references=refs,
                tempo_state=tempo,
                event_ref=event_ref,
                now=now,
            )
            payload = {
                "channel": normalized_channel,
                "thread_key": normalized_thread_key,
                "chat_name": normalized_chat_name,
                "continuity_summary": continuity,
                "last_user_intent": last_user_intent,
                "last_outbound_action_json": json.dumps(selected if str(direction or "").strip() == "outbound" or selected else {}, ensure_ascii=False, sort_keys=True),
                "unresolved_references_json": json.dumps(refs, ensure_ascii=False, sort_keys=True),
                "active_affect_hint": active_affect,
                "relationship_tension": tension,
                "tempo_state_json": json.dumps(tempo, ensure_ascii=False, sort_keys=True),
                "attention_focus": active_focus,
                "cache_warmth": warmth,
                "recent_turn_ids_json": json.dumps(recent_turn_ids, ensure_ascii=False, sort_keys=True),
                "predictive_continuity_json": json.dumps(predictive, ensure_ascii=False, sort_keys=True),
                "metrics_json": json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                "metadata_json": json.dumps(meta, ensure_ascii=False, sort_keys=True),
                "created_at": str(current.get("created_at", "") or now),
                "updated_at": now,
            }
            self.conn.execute(
                """
                INSERT INTO active_thread_state(
                    channel, thread_key, chat_name, continuity_summary, last_user_intent, last_outbound_action_json,
                    unresolved_references_json, active_affect_hint, relationship_tension, tempo_state_json,
                    attention_focus, cache_warmth, recent_turn_ids_json, predictive_continuity_json,
                    metrics_json, metadata_json, created_at, updated_at
                ) VALUES (
                    :channel, :thread_key, :chat_name, :continuity_summary, :last_user_intent, :last_outbound_action_json,
                    :unresolved_references_json, :active_affect_hint, :relationship_tension, :tempo_state_json,
                    :attention_focus, :cache_warmth, :recent_turn_ids_json, :predictive_continuity_json,
                    :metrics_json, :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(channel, thread_key) DO UPDATE SET
                    chat_name = excluded.chat_name,
                    continuity_summary = excluded.continuity_summary,
                    last_user_intent = excluded.last_user_intent,
                    last_outbound_action_json = excluded.last_outbound_action_json,
                    unresolved_references_json = excluded.unresolved_references_json,
                    active_affect_hint = excluded.active_affect_hint,
                    relationship_tension = excluded.relationship_tension,
                    tempo_state_json = excluded.tempo_state_json,
                    attention_focus = excluded.attention_focus,
                    cache_warmth = excluded.cache_warmth,
                    recent_turn_ids_json = excluded.recent_turn_ids_json,
                    predictive_continuity_json = excluded.predictive_continuity_json,
                    metrics_json = excluded.metrics_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            lowered_text = str(text or "").strip().lower()
            explicit_reentry = bool(
                str(direction or "").strip() == "inbound"
                and lowered_text
                and any(
                    hint in lowered_text
                    for hint in (
                        "we were talking",
                        "we were discussing",
                        "where were we",
                        "pick up where",
                        "back to what",
                        "continue from",
                        "resume that",
                        "talking about",
                    )
                )
            )
            if explicit_reentry:
                cue = compact_text(str(text or "").strip(), 220)
                base_metadata = {
                    "source": "active_thread_reentry",
                    "evidence_refs": [f"event:{event_ref}" if event_ref else "active_thread:inbound_reentry"],
                }
                self.upsert_temporal_item(
                    item_type="open_loop",
                    channel=normalized_channel,
                    thread_key=normalized_thread_key,
                    chat_name=normalized_chat_name,
                    confidence=0.7,
                    source_event_id=event_ref,
                    source_action_type="inbound_reentry",
                    due_at=now,
                    revisit_after=now,
                    resume_cue=cue,
                    dedupe_key=f"open_loop:{normalized_channel}:{normalized_thread_key}:{event_ref or stable_digest(cue)[:12]}",
                    status="open",
                    metadata=base_metadata,
                )
                self.upsert_temporal_item(
                    item_type="resume_candidate",
                    channel=normalized_channel,
                    thread_key=normalized_thread_key,
                    chat_name=normalized_chat_name,
                    confidence=0.66,
                    source_event_id=event_ref,
                    source_action_type="inbound_reentry",
                    due_at=now,
                    revisit_after=now,
                    resume_cue=cue,
                    dedupe_key=f"resume:{normalized_channel}:{normalized_thread_key}:{event_ref or stable_digest(cue)[:12]}",
                    status="open",
                    metadata=base_metadata,
                )
            self.conn.commit()
        state = self.active_thread_state(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
        )
        state["status"] = "ok"
        return state

    @staticmethod
    def _frontier_warmth(thread_heat: float, *, stale: bool) -> str:
        if stale or thread_heat <= 0.0:
            return "cold"
        if thread_heat >= 0.72:
            return "hot"
        if thread_heat >= 0.36:
            return "warm"
        return "cool"

    def _attention_frontier_item_from_row(self, row: dict[str, Any] | None, *, now: str) -> dict[str, Any]:
        if not row:
            return {"present": False, "thread_warmth": "cold", "thread_heat": 0.0, "stale": True}
        metadata = _safe_json_dict(row.get("metadata_json", "{}"))
        stale_after = str(row.get("stale_after", "") or "")
        stale = bool(stale_after and stale_after <= now)
        stored_heat = self._clamp(row.get("thread_heat", 0.0), default=0.0)
        effective_heat = 0.0 if stale else stored_heat
        canonical_thread_key = str(row.get("canonical_thread_key", "") or "")
        payload = {
            "present": not stale,
            "stale": stale,
            "channel": str(row.get("channel", "") or ""),
            "canonical_thread_key": canonical_thread_key,
            "thread_key": canonical_thread_key,
            "chat_name": str(row.get("chat_name", "") or ""),
            "thread_heat": effective_heat,
            "stored_thread_heat": stored_heat,
            "wake_reason": str(row.get("wake_reason", "") or ""),
            "anticipated_next_turn": str(row.get("anticipated_next_turn", "") or ""),
            "pending_open_loop_count": int(row.get("pending_open_loop_count", 0) or 0),
            "reentry_priority": 0.0 if stale else self._clamp(row.get("reentry_priority", 0.0), default=0.0),
            "stale_after": stale_after,
            "last_stream_touch_at": str(row.get("last_stream_touch_at", "") or ""),
            "thread_warmth": self._frontier_warmth(effective_heat, stale=stale),
            "metadata": metadata,
            "evidence_refs": [
                str(item).strip()
                for item in list(metadata.get("evidence_refs", []))
                if str(item).strip()
            ][:3],
            "created_at": str(row.get("created_at", "") or ""),
            "updated_at": str(row.get("updated_at", "") or ""),
        }
        return payload

    def _prune_attention_frontier_locked(self, *, now: str) -> None:
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT id
                FROM attention_frontier
                ORDER BY
                    CASE WHEN stale_after > ? OR stale_after = '' THEN 0 ELSE 1 END ASC,
                    reentry_priority DESC,
                    thread_heat DESC,
                    last_stream_touch_at DESC,
                    id DESC
                """,
                (now,),
            ).fetchall()
        ]
        stale_cutoff = _utc_after_seconds(now, -24 * 3600)
        keep_ids = {int(row["id"]) for row in rows[:ATTENTION_FRONTIER_MAX_ENTRIES]}
        for row in rows[ATTENTION_FRONTIER_MAX_ENTRIES:]:
            self.conn.execute("DELETE FROM attention_frontier WHERE id = ?", (int(row["id"]),))
        self.conn.execute(
            "DELETE FROM attention_frontier WHERE stale_after <> '' AND stale_after <= ? AND id NOT IN (%s)"
            % ",".join("?" for _ in keep_ids)
            if keep_ids
            else "DELETE FROM attention_frontier WHERE stale_after <> '' AND stale_after <= ?",
            ((stale_cutoff, *sorted(keep_ids)) if keep_ids else (stale_cutoff,)),
        )

    def _upsert_attention_frontier_locked(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        stream_name: str,
        wake_reason: str,
        anticipated_next_turn: str,
        pending_open_loop_count: int,
        evidence_refs: Iterable[str] | None,
        motifs: Iterable[str] | None,
        unfinished_threads: Iterable[str] | None,
        now: str,
    ) -> dict[str, Any]:
        if stream_name not in ATTENTION_FRONTIER_ALLOWED_STREAMS:
            return {"present": False, "reason": "unsupported_stream"}
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        canonical_thread_key = _normalize_thread_key(
            normalized_channel,
            str(thread_key or "").strip(),
            chat_name=str(chat_name or "").strip(),
        )
        if not canonical_thread_key:
            return {"present": False, "reason": "missing_thread_key"}
        current = self.conn.execute(
            "SELECT * FROM attention_frontier WHERE channel = ? AND canonical_thread_key = ?",
            (normalized_channel, canonical_thread_key),
        ).fetchone()
        current_payload = self._attention_frontier_item_from_row(dict(current) if current else None, now=now)
        current_heat = 0.0 if current_payload.get("stale") else float(current_payload.get("stored_thread_heat", 0.0) or 0.0)
        clean_motifs = _dedupe_strings(compact_text(str(item).strip(), 64) for item in list(motifs or []) if str(item).strip())[:4]
        clean_unfinished = _dedupe_strings(compact_text(str(item).strip(), 96) for item in list(unfinished_threads or []) if str(item).strip())[:4]
        clean_refs = _dedupe_strings(
            [f"stream:{stream_name}"]
            + [compact_text(str(item).strip(), 96) for item in list(evidence_refs or []) if str(item).strip()]
        )[:3]
        reason = compact_text(str(wake_reason or "").strip(), 120)
        if not reason:
            reason = compact_text(clean_unfinished[0] if clean_unfinished else clean_motifs[0] if clean_motifs else stream_name, 120)
        anticipated = compact_text(str(anticipated_next_turn or "").strip(), 120)
        if not anticipated:
            anticipated = compact_text(clean_unfinished[0] if clean_unfinished else reason, 120)
        open_loops = max(0, min(8, int(pending_open_loop_count or len(clean_unfinished))))
        heat_delta = float(ATTENTION_FRONTIER_HEAT_DELTA.get(stream_name, 0.12))
        next_heat = self._clamp(current_heat + heat_delta + min(0.12, open_loops * 0.03), default=0.0)
        stream_bias = {"social_stream": 0.08, "association_stream": 0.05, "deep_dream_cycle": 0.04, "maintenance_stream": 0.02}.get(stream_name, 0.0)
        reentry_priority = self._clamp(next_heat + min(0.24, open_loops * 0.06) + stream_bias, default=0.0)
        stale_after = _utc_after_seconds(now, ATTENTION_FRONTIER_TTL_SECONDS.get(stream_name, 4 * 3600))
        metadata = dict(current_payload.get("metadata", {})) if isinstance(current_payload.get("metadata", {}), dict) else {}
        metadata.update(
            {
                "source_stream": stream_name,
                "wake_reasons": _dedupe_strings([reason] + list(metadata.get("wake_reasons", [])))[:4],
                "motifs": _dedupe_strings(clean_motifs + list(metadata.get("motifs", [])))[:4],
                "unfinished_threads": _dedupe_strings(clean_unfinished + list(metadata.get("unfinished_threads", [])))[:4],
                "evidence_refs": _dedupe_strings(clean_refs + list(metadata.get("evidence_refs", [])))[:3],
                "bounded": True,
                "max_entries": ATTENTION_FRONTIER_MAX_ENTRIES,
            }
        )
        created_at = str(current_payload.get("created_at", "") or now)
        payload = {
            "channel": normalized_channel,
            "canonical_thread_key": canonical_thread_key,
            "chat_name": str(chat_name or current_payload.get("chat_name", "") or canonical_thread_key).strip(),
            "thread_heat": next_heat,
            "wake_reason": reason,
            "anticipated_next_turn": anticipated,
            "pending_open_loop_count": open_loops,
            "reentry_priority": reentry_priority,
            "stale_after": stale_after,
            "last_stream_touch_at": now,
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "created_at": created_at,
            "updated_at": now,
        }
        self.conn.execute(
            """
            INSERT INTO attention_frontier(
                channel, canonical_thread_key, chat_name, thread_heat, wake_reason, anticipated_next_turn,
                pending_open_loop_count, reentry_priority, stale_after, last_stream_touch_at, metadata_json, created_at, updated_at
            ) VALUES (
                :channel, :canonical_thread_key, :chat_name, :thread_heat, :wake_reason, :anticipated_next_turn,
                :pending_open_loop_count, :reentry_priority, :stale_after, :last_stream_touch_at, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT(channel, canonical_thread_key) DO UPDATE SET
                chat_name = excluded.chat_name,
                thread_heat = excluded.thread_heat,
                wake_reason = excluded.wake_reason,
                anticipated_next_turn = excluded.anticipated_next_turn,
                pending_open_loop_count = excluded.pending_open_loop_count,
                reentry_priority = excluded.reentry_priority,
                stale_after = excluded.stale_after,
                last_stream_touch_at = excluded.last_stream_touch_at,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            payload,
        )
        self._prune_attention_frontier_locked(now=now)
        row = self.conn.execute(
            "SELECT * FROM attention_frontier WHERE channel = ? AND canonical_thread_key = ?",
            (normalized_channel, canonical_thread_key),
        ).fetchone()
        return self._attention_frontier_item_from_row(dict(row) if row else None, now=now)

    def attention_frontier(
        self,
        *,
        channel: str | None = None,
        limit: int = ATTENTION_FRONTIER_MAX_ENTRIES,
        include_stale: bool = False,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "").strip()
        now = utc_now()
        with self._lock:
            if normalized_channel:
                rows = [
                    dict(row)
                    for row in self.conn.execute(
                        """
                        SELECT * FROM attention_frontier
                        WHERE channel = ?
                        ORDER BY reentry_priority DESC, thread_heat DESC, last_stream_touch_at DESC
                        LIMIT ?
                        """,
                        (normalized_channel, max(1, int(limit)) + ATTENTION_FRONTIER_MAX_ENTRIES),
                    ).fetchall()
                ]
            else:
                rows = [
                    dict(row)
                    for row in self.conn.execute(
                        """
                        SELECT * FROM attention_frontier
                        ORDER BY reentry_priority DESC, thread_heat DESC, last_stream_touch_at DESC
                        LIMIT ?
                        """,
                        (max(1, int(limit)) + ATTENTION_FRONTIER_MAX_ENTRIES,),
                    ).fetchall()
                ]
        entries = [self._attention_frontier_item_from_row(row, now=now) for row in rows]
        if not include_stale:
            entries = [item for item in entries if bool(item.get("present", False))]
        entries = entries[: max(1, int(limit))]
        return {
            "status": "ok",
            "channel": normalized_channel or "all",
            "entry_count": len(entries),
            "max_entries": ATTENTION_FRONTIER_MAX_ENTRIES,
            "include_stale": bool(include_stale),
            "entries": entries,
        }

    def attention_frontier_item(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        canonical_thread_key = _normalize_thread_key(
            normalized_channel,
            str(thread_key or "").strip(),
            chat_name=str(chat_name or "").strip(),
        )
        if not canonical_thread_key:
            return {"present": False, "thread_warmth": "cold", "thread_heat": 0.0, "stale": True}
        now = utc_now()
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM attention_frontier WHERE channel = ? AND canonical_thread_key = ?",
                (normalized_channel, canonical_thread_key),
            ).fetchone()
        return self._attention_frontier_item_from_row(dict(row) if row else None, now=now)

    def trace_wake_reasons(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        item = self.attention_frontier_item(channel=channel, thread_key=thread_key, chat_name=chat_name)
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
        reasons = _dedupe_strings([str(item.get("wake_reason", "") or "")] + list(metadata.get("wake_reasons", [])))[:4]
        return {
            "status": "ok",
            "thread_key": item.get("canonical_thread_key", str(thread_key or chat_name or "")),
            "chat_name": item.get("chat_name", str(chat_name or "")),
            "channel": item.get("channel", channel),
            "present": bool(item.get("present", False)),
            "stale": bool(item.get("stale", True)),
            "wake_reasons": reasons,
            "anticipated_next_turn": str(item.get("anticipated_next_turn", "") or ""),
            "pending_open_loop_count": int(item.get("pending_open_loop_count", 0) or 0),
            "evidence_refs": list(item.get("evidence_refs", []))[:3],
            "frontier_item": item,
        }

    def thread_warmth(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, Any]:
        item = self.attention_frontier_item(channel=channel, thread_key=thread_key, chat_name=chat_name)
        return {
            "status": "ok",
            "thread_key": item.get("canonical_thread_key", str(thread_key or chat_name or "")),
            "chat_name": item.get("chat_name", str(chat_name or "")),
            "channel": item.get("channel", channel),
            "thread_warmth": str(item.get("thread_warmth", "cold") or "cold"),
            "thread_heat": float(item.get("thread_heat", 0.0) or 0.0),
            "stored_thread_heat": float(item.get("stored_thread_heat", item.get("thread_heat", 0.0)) or 0.0),
            "wake_reason": str(item.get("wake_reason", "") or ""),
            "pending_open_loop_count": int(item.get("pending_open_loop_count", 0) or 0),
            "reentry_priority": float(item.get("reentry_priority", 0.0) or 0.0),
            "stale": bool(item.get("stale", True)),
            "stale_after": str(item.get("stale_after", "") or ""),
            "last_stream_touch_at": str(item.get("last_stream_touch_at", "") or ""),
            "frontier_item": item,
        }

    @staticmethod
    def _clamp(value: Any, *, lower: float = 0.0, upper: float = 1.0, default: float = 0.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float(default)
        return round(max(lower, min(upper, numeric)), 4)

    def _metric_blend(
        self,
        current: Any,
        *,
        observations: Iterable[Any],
        default: float,
        confidence: float = 0.62,
        evidence_refs: Iterable[str] | None = None,
        updated_at: str = "",
        updated_by: str = "",
        decay_policy: str = "event_weighted",
        momentum: float = 0.6,
    ) -> dict[str, Any]:
        current_value = self.metric_value(current, default=default)
        seen = [self._clamp(item, default=current_value) for item in observations if item is not None]
        target = round(sum(seen) / len(seen), 4) if seen else current_value
        blended = self._clamp(current_value * momentum + target * (1.0 - momentum), default=default)
        refs = _state_evidence_refs(current, evidence_refs)
        for item in evidence_refs or []:
            text = str(item).strip()
            if text and text not in refs:
                refs.append(text)
        return self.metric_state(
            blended,
            default=default,
            confidence=max(confidence, self.metric_confidence(current, default=confidence)),
            evidence_refs=refs[:6],
            updated_at=updated_at,
            updated_by=updated_by,
            decay_policy=decay_policy,
        )

    def _hydrate_subject_state_metrics(self, state: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(state.get("metadata", {}))
        updated_at = str(state.get("updated_at", "") or metadata.get("updated_at", "") or utc_now())
        updated_by = str(metadata.get("last_subject_source", "") or "subject_state")
        affect_state = dict(state.get("affect_state", {}))
        for key in SUBJECT_STATE_OBJECT_KEYS:
            affect_state[key] = self.metric_state(
                affect_state.get(key, AFFECT_STATE_DEFAULTS[key]),
                default=AFFECT_STATE_DEFAULTS[key],
                confidence=0.62,
                evidence_refs=[f"subject_state:{key}"],
                updated_at=updated_at,
                updated_by=updated_by,
                decay_policy="event_weighted",
            )
        state["affect_state"] = affect_state

        world_state = dict(state.get("world_state", {}))
        response_expectations = dict(world_state.get("response_expectations", {}))
        for key in WORLD_RESPONSE_STATE_OBJECT_KEYS:
            default_value = WORLD_CONTACT_MODEL_DEFAULTS.get(key, 0.0)
            response_expectations[key] = self.metric_state(
                response_expectations.get(key, default_value),
                default=default_value,
                confidence=0.64,
                evidence_refs=[f"world.response_expectations:{key}"],
                updated_at=updated_at,
                updated_by=updated_by,
                decay_policy="interaction_window",
            )
        world_state["response_expectations"] = response_expectations

        contact_models = {
            str(key): dict(value)
            for key, value in dict(world_state.get("contact_models", {})).items()
            if isinstance(value, dict)
        }
        for key, contact_model in contact_models.items():
            contact_model["initiative_receptivity"] = self.metric_state(
                contact_model.get("initiative_receptivity", WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]),
                default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"],
                confidence=0.62,
                evidence_refs=[f"contact_model:{key}:initiative_receptivity"],
                updated_at=updated_at,
                updated_by=updated_by,
                decay_policy="interaction_window",
            )
        world_state["contact_models"] = contact_models

        expression_signals = dict(world_state.get("expression_calibration_signals", {}))
        for key, default_value in WORLD_EXPRESSION_SIGNAL_DEFAULTS.items():
            expression_signals[key] = self.metric_state(
                expression_signals.get(key, default_value),
                default=default_value,
                confidence=0.58,
                evidence_refs=[f"expression_calibration:{key}"],
                updated_at=updated_at,
                updated_by=updated_by,
                decay_policy="conversation_carryover",
            )
        world_state["expression_calibration_signals"] = expression_signals
        state["world_state"] = world_state
        return state

    def brain_state(self, *, default_mode: str = "full_brain") -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM brain_runtime_state WHERE runtime_id = 1").fetchone()
            if row is None:
                now = utc_now()
                self.conn.execute(
                    """
                    INSERT INTO brain_runtime_state(runtime_id, mode, started_at, last_updated_at, idle_since, metadata_json)
                    VALUES (1, ?, ?, ?, ?, '{}')
                    """,
                    (default_mode, now, now, now),
                )
                self.conn.commit()
                row = self.conn.execute("SELECT * FROM brain_runtime_state WHERE runtime_id = 1").fetchone()
            payload = dict(row) if row else {}
            metadata = _safe_json_dict(payload.get("metadata_json", "{}"))
            latest_runs = [
                dict(run)
                for run in self.conn.execute(
                    """
                    SELECT loop_name, mode, status, started_at, finished_at, duration_ms, influence_summary, blocked_reason, stats_json, next_due_at
                    FROM brain_loop_runs
                    WHERE id IN (
                        SELECT MAX(id) FROM brain_loop_runs GROUP BY loop_name
                    )
                    ORDER BY loop_name ASC
                    """
                ).fetchall()
            ]
            mode_events = [
                dict(event)
                for event in self.conn.execute(
                    "SELECT previous_mode, next_mode, note, created_at FROM brain_mode_events ORDER BY id DESC LIMIT 8"
                ).fetchall()
            ]
        return {
            "mode": str(payload.get("mode", default_mode) or default_mode),
            "started_at": str(payload.get("started_at", "") or ""),
            "last_updated_at": str(payload.get("last_updated_at", "") or ""),
            "idle_since": str(payload.get("idle_since", "") or ""),
            "metadata": metadata,
            "loops": latest_runs,
            "recent_mode_events": mode_events,
        }

    def self_model_state(self) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM self_model_state WHERE runtime_id = 1").fetchone()
            if row is None:
                now = utc_now()
                self.conn.execute(
                    """
                    INSERT INTO self_model_state(
                        runtime_id, identity_continuity, capability_model_json, active_deficits_json, long_horizon_goals_json,
                        relational_commitments_json, homeostasis_targets_json, metadata_json, created_at, updated_at
                    ) VALUES (1, 0.6, '{}', '[]', '[]', '[]', '{}', '{}', ?, ?)
                    """,
                    (now, now),
                )
                self.conn.commit()
                row = self.conn.execute("SELECT * FROM self_model_state WHERE runtime_id = 1").fetchone()
        payload = dict(row) if row else {}
        return {
            "identity_continuity": float(payload.get("identity_continuity", 0.6) or 0.6),
            "capability_model": dict(_safe_json_dict(payload.get("capability_model_json", "{}"))),
            "active_deficits": self._decode_json_array(payload.get("active_deficits_json", "[]")),
            "long_horizon_goals": self._decode_json_array(payload.get("long_horizon_goals_json", "[]")),
            "relational_commitments": self._decode_json_array(payload.get("relational_commitments_json", "[]")),
            "homeostasis_targets": dict(_safe_json_dict(payload.get("homeostasis_targets_json", "{}"))),
            "metadata": dict(_safe_json_dict(payload.get("metadata_json", "{}"))),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }

    @staticmethod
    def _decode_json_array(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return list(raw)
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return list(payload) if isinstance(payload, list) else []

    def update_self_model_state(
        self,
        payload: dict[str, Any],
        *,
        reason: str = "",
        source: str = "runtime",
    ) -> dict[str, Any]:
        current = self.self_model_state()
        next_state = {
            "identity_continuity": self._clamp(payload.get("identity_continuity", current.get("identity_continuity", 0.6)), default=0.6),
            "capability_model": dict(payload.get("capability_model", current.get("capability_model", {}))),
            "active_deficits": [str(item).strip() for item in payload.get("active_deficits", current.get("active_deficits", [])) if str(item).strip()],
            "long_horizon_goals": [str(item).strip() for item in payload.get("long_horizon_goals", current.get("long_horizon_goals", [])) if str(item).strip()],
            "relational_commitments": [str(item).strip() for item in payload.get("relational_commitments", current.get("relational_commitments", [])) if str(item).strip()],
            "homeostasis_targets": dict(payload.get("homeostasis_targets", current.get("homeostasis_targets", {}))),
            "metadata": {
                **dict(current.get("metadata", {})),
                **dict(payload.get("metadata", {})),
                "last_reason": compact_text(reason, 160),
                "last_source": str(source or "runtime"),
                "updated_at": utc_now(),
            },
        }
        now = utc_now()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO self_model_state(
                    runtime_id, identity_continuity, capability_model_json, active_deficits_json, long_horizon_goals_json,
                    relational_commitments_json, homeostasis_targets_json, metadata_json, created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(runtime_id) DO UPDATE SET
                    identity_continuity = excluded.identity_continuity,
                    capability_model_json = excluded.capability_model_json,
                    active_deficits_json = excluded.active_deficits_json,
                    long_horizon_goals_json = excluded.long_horizon_goals_json,
                    relational_commitments_json = excluded.relational_commitments_json,
                    homeostasis_targets_json = excluded.homeostasis_targets_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    float(next_state["identity_continuity"]),
                    json.dumps(next_state["capability_model"], ensure_ascii=False, sort_keys=True),
                    json.dumps(next_state["active_deficits"], ensure_ascii=False),
                    json.dumps(next_state["long_horizon_goals"], ensure_ascii=False),
                    json.dumps(next_state["relational_commitments"], ensure_ascii=False),
                    json.dumps(next_state["homeostasis_targets"], ensure_ascii=False, sort_keys=True),
                    json.dumps(next_state["metadata"], ensure_ascii=False, sort_keys=True),
                    str(current.get("created_at", "") or now),
                    now,
                ),
            )
            self.conn.commit()
        updated = self.self_model_state()
        updated["status"] = "ok"
        updated["reason"] = reason
        updated["source"] = source
        return updated

    def _default_autobiographical_state(self) -> dict[str, Any]:
        self_model = self.self_model_state()
        commitments = self.top_thread_commitments(limit=3)
        stable_traits = list(AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS)
        recent_changes: list[dict[str, Any]] = []
        unresolved = [str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()][:4]
        attachment_history = [
            {
                "thread_key": str(item.get("thread_key", "")),
                "chat_name": str(item.get("chat_name", "")),
                "relationship_score": round(float(item.get("relationship_score", 0.0) or 0.0), 4),
                "summary": compact_text(str(item.get("summary", "")), 160),
            }
            for item in commitments[:3]
            if str(item.get("thread_key", "")).strip()
        ]
        self_explanations = [
            {
                "topic": "identity_continuity",
                "explanation": "咱一直在学着把连续性、活气和克制绑在一起，不想又变硬，又不想散掉。",
                "because": "这段时间的修正和关系维护都在往这条线收。",
            }
        ]
        return {
            "identity_arc": "Holo一直在学着把连续性、活气和克制绑在一起，不想变硬，也不想散掉。",
            "current_chapter": AUTOBIOGRAPHICAL_CHAPTER_DEFAULT,
            "turning_points": [],
            "recent_changes": recent_changes,
            "stable_traits": stable_traits,
            "preference_history": [],
            "attachment_history": attachment_history,
            "unresolved_tensions": unresolved,
            "self_explanations": self_explanations,
            "metadata": {
                "visibility": "implicit_unless_relevant",
                "plasticity": "moderate",
            },
        }

    def autobiographical_state(self) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM autobiographical_state WHERE runtime_id = 1").fetchone()
            if row is None:
                defaults = self._default_autobiographical_state()
                now = utc_now()
                self.conn.execute(
                    """
                    INSERT INTO autobiographical_state(
                        runtime_id, identity_arc, current_chapter, turning_points_json, recent_changes_json, stable_traits_json,
                        preference_history_json, attachment_history_json, unresolved_tensions_json, self_explanations_json,
                        metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        compact_text(defaults["identity_arc"], 400),
                        compact_text(defaults["current_chapter"], 200),
                        json.dumps(defaults["turning_points"], ensure_ascii=False),
                        json.dumps(defaults["recent_changes"], ensure_ascii=False),
                        json.dumps(defaults["stable_traits"], ensure_ascii=False),
                        json.dumps(defaults["preference_history"], ensure_ascii=False),
                        json.dumps(defaults["attachment_history"], ensure_ascii=False),
                        json.dumps(defaults["unresolved_tensions"], ensure_ascii=False),
                        json.dumps(defaults["self_explanations"], ensure_ascii=False),
                        json.dumps(defaults["metadata"], ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                self.conn.commit()
                row = self.conn.execute("SELECT * FROM autobiographical_state WHERE runtime_id = 1").fetchone()
        payload = dict(row) if row else {}
        return {
            "identity_arc": str(payload.get("identity_arc", "") or ""),
            "current_chapter": str(payload.get("current_chapter", "") or AUTOBIOGRAPHICAL_CHAPTER_DEFAULT),
            "turning_points": self._decode_json_array(payload.get("turning_points_json", "[]")),
            "recent_changes": self._decode_json_array(payload.get("recent_changes_json", "[]")),
            "stable_traits": self._decode_json_array(payload.get("stable_traits_json", "[]")),
            "preference_history": self._decode_json_array(payload.get("preference_history_json", "[]")),
            "attachment_history": self._decode_json_array(payload.get("attachment_history_json", "[]")),
            "unresolved_tensions": self._decode_json_array(payload.get("unresolved_tensions_json", "[]")),
            "self_explanations": self._decode_json_array(payload.get("self_explanations_json", "[]")),
            "metadata": dict(_safe_json_dict(payload.get("metadata_json", "{}"))),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }

    def update_autobiographical_state(
        self,
        payload: dict[str, Any],
        *,
        reason: str = "",
        source: str = "runtime",
    ) -> dict[str, Any]:
        return _update_autobiographical_state(self, payload, reason=reason, source=source)

    def _default_goal_state(self) -> dict[str, Any]:
        self_model = self.self_model_state()
        commitments = self.top_thread_commitments(limit=3)
        now = utc_now()
        active_goals: list[dict[str, Any]] = [
            {
                "goal_id": "identity_maintenance",
                "goal_type": "identity_maintenance",
                "summary": "keep Holo coherent, continuous, and not overly stiff",
                "priority": GOAL_TYPE_DEFAULT_PRIORITIES["identity_maintenance"],
                "progress": round(float(self_model.get("identity_continuity", 0.6) or 0.6), 4),
                "target_thread": "",
                "evidence": list(self_model.get("active_deficits", []))[:2],
                "last_moved_at": now,
                "stalled_reason": "",
            },
            {
                "goal_id": "recall_quality",
                "goal_type": "recall_quality",
                "summary": "keep memory recall deep, accurate, and continuity-safe",
                "priority": GOAL_TYPE_DEFAULT_PRIORITIES["recall_quality"],
                "progress": 0.52,
                "target_thread": "",
                "evidence": ["memory continuity matters"],
                "last_moved_at": now,
                "stalled_reason": "",
            },
            {
                "goal_id": "liveliness_balance",
                "goal_type": "liveliness_balance",
                "summary": "stay lively and wolfish without sliding back into stiffness or sprawl",
                "priority": GOAL_TYPE_DEFAULT_PRIORITIES["liveliness_balance"],
                "progress": 0.46,
                "target_thread": "",
                "evidence": ["tone balance"],
                "last_moved_at": now,
                "stalled_reason": "",
            },
        ]
        if commitments:
            top = commitments[0]
            active_goals.append(
                {
                    "goal_id": f"relationship_continuity:{top['thread_key']}",
                    "goal_type": "relationship_continuity",
                    "summary": f"keep continuity alive with {top['chat_name'] or top['thread_key']}",
                    "priority": GOAL_TYPE_DEFAULT_PRIORITIES["relationship_continuity"],
                    "progress": round(float(top.get("relationship_score", 0.0) or 0.0), 4),
                    "target_thread": str(top.get("thread_key", "")),
                    "evidence": [str(top.get("summary", ""))],
                    "last_moved_at": now,
                    "stalled_reason": "",
                }
            )
            active_goals.append(
                {
                    "goal_id": f"contact_maintenance:{top['thread_key']}",
                    "goal_type": "contact_maintenance",
                    "summary": f"keep a warm contact window open with {top['chat_name'] or top['thread_key']}",
                    "priority": GOAL_TYPE_DEFAULT_PRIORITIES["contact_maintenance"],
                    "progress": round(min(1.0, float(top.get("relationship_score", 0.0) or 0.0) * 0.82), 4),
                    "target_thread": str(top.get("thread_key", "")),
                    "evidence": list(top.get("recurring_motifs", []))[:2] or [str(top.get("summary", ""))],
                    "last_moved_at": now,
                    "stalled_reason": "",
                }
            )
        if list(self_model.get("active_deficits", [])):
            active_goals.append(
                {
                    "goal_id": "self_repair",
                    "goal_type": "self_repair",
                    "summary": "repair the most active deficits without destabilizing identity",
                    "priority": GOAL_TYPE_DEFAULT_PRIORITIES["self_repair"],
                    "progress": 0.34,
                    "target_thread": "",
                    "evidence": list(self_model.get("active_deficits", []))[:3],
                    "last_moved_at": now,
                    "stalled_reason": "",
                }
            )
        goal_progress = {
            str(item["goal_id"]): self.metric_state(
                round(float(item["progress"]), 4),
                default=0.0,
                confidence=0.66,
                evidence_refs=[f"default_goal:{item['goal_id']}"],
                updated_at=now,
                updated_by="default_goal_state",
                decay_policy="goal_continuity",
            )
            for item in active_goals
        }
        pursuit_bias = {str(item["goal_id"]): round(float(item["priority"]), 4) for item in active_goals}
        abandonment_cost = {str(item["goal_id"]): round(float(item["priority"]) * 0.6, 4) for item in active_goals}
        next_goal_windows = [
            {
                "goal_id": str(item["goal_id"]),
                "target_thread": str(item.get("target_thread", "")),
                "window": "next_relevant_turn" if str(item.get("target_thread", "")) else "next_internal_cycle",
            }
            for item in active_goals[:4]
        ]
        return {
            "active_goals": active_goals[:6],
            "dormant_goals": [],
            "completed_goals": [],
            "goal_commitments": [
                {"summary": str(item).strip(), "source": "self_model"}
                for item in list(self_model.get("relational_commitments", []))[:4]
                if str(item).strip()
            ],
            "goal_progress": goal_progress,
            "goal_conflicts": [],
            "pursuit_bias": pursuit_bias,
            "abandonment_cost": abandonment_cost,
            "next_goal_windows": next_goal_windows,
            "metadata": {
                "plasticity": "moderate",
                "visibility": "implicit_unless_relevant",
            },
        }

    def goal_state(self) -> dict[str, Any]:
        return _goal_state(self)

    def update_goal_state(
        self,
        payload: dict[str, Any],
        *,
        reason: str = "",
        source: str = "runtime",
    ) -> dict[str, Any]:
        return _update_goal_state(self, payload, reason=reason, source=source)

    def upsert_temporal_item(self, **kwargs: Any) -> dict[str, Any]:
        return _upsert_temporal_item(self, **kwargs)

    def update_temporal_item_status(self, **kwargs: Any) -> dict[str, Any]:
        return _update_temporal_item_status(self, **kwargs)

    def close_temporal_items(self, **kwargs: Any) -> dict[str, Any]:
        return _close_temporal_items(self, **kwargs)

    def temporal_state(self, **kwargs: Any) -> dict[str, Any]:
        return _temporal_state(self, **kwargs)

    def show_open_loops(self, **kwargs: Any) -> dict[str, Any]:
        return _show_open_loops(self, **kwargs)

    def show_commitments(self, **kwargs: Any) -> dict[str, Any]:
        return _show_commitments(self, **kwargs)

    def trace_resume_candidate(self, **kwargs: Any) -> dict[str, Any]:
        return _trace_resume_candidate(self, **kwargs)

    def upsert_policy_candidate_from_calibration(self, **kwargs: Any) -> dict[str, Any]:
        return _upsert_policy_candidate_from_calibration(self, **kwargs)

    def list_policy_sediment(self, **kwargs: Any) -> list[dict[str, Any]]:
        return _list_policy_sediment(self, **kwargs)

    def policy_scenario_bucket(self, **kwargs: Any) -> dict[str, Any]:
        return _policy_scenario_bucket(self, **kwargs)

    def promoted_policy_overlays(self, **kwargs: Any) -> list[dict[str, Any]]:
        return _promoted_policy_overlays(self, **kwargs)

    def review_policy_candidate(self, **kwargs: Any) -> dict[str, Any]:
        return _review_policy_candidate(self, **kwargs)

    def rollback_policy(self, **kwargs: Any) -> dict[str, Any]:
        return _rollback_policy(self, **kwargs)

    def show_policy_candidates(self, **kwargs: Any) -> dict[str, Any]:
        return _show_policy_candidates(self, **kwargs)

    def show_promoted_policies(self, **kwargs: Any) -> dict[str, Any]:
        return _show_promoted_policies(self, **kwargs)

    def top_thread_commitments(self, *, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                    SELECT channel, thread_key, chat_name, relationship_score, summary, metadata_json, last_message_at
                    FROM mind_thread_state
                    ORDER BY relationship_score DESC, last_message_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
            ]
        commitments: list[dict[str, Any]] = []
        for row in rows:
            metadata = _safe_json_dict(row.get("metadata_json", "{}"))
            commitments.append(
                {
                    "channel": str(row.get("channel", "")),
                    "thread_key": str(row.get("thread_key", "")),
                    "chat_name": str(row.get("chat_name", "")),
                    "relationship_score": float(row.get("relationship_score", 0.0) or 0.0),
                    "summary": str(row.get("summary", "")),
                    "recurring_motifs": list(metadata.get("recurring_motifs", [])) if isinstance(metadata.get("recurring_motifs"), list) else [],
                    "tone_tendency": str(metadata.get("tone_tendency", "")),
                    "last_message_at": str(row.get("last_message_at", "")),
                }
            )
        seen_threads = {(str(item.get("channel", "")), str(item.get("thread_key", ""))) for item in commitments}
        now = utc_now()
        with self._lock:
            temporal_rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                    SELECT channel, thread_key, chat_name, resume_cue, type, confidence, due_at, dedupe_key, updated_at
                    FROM temporal_subject_state
                    WHERE status IN ('open', 'scheduled', 'due')
                      AND (due_at <> '' AND due_at <= ? OR revisit_after <> '' AND revisit_after <= ?)
                      AND (revisit_before = '' OR revisit_before > ?)
                    ORDER BY confidence DESC, due_at ASC, updated_at DESC
                    LIMIT ?
                    """,
                    (now, now, now, max(1, int(limit))),
                ).fetchall()
            ]
        for row in temporal_rows:
            key = (str(row.get("channel", "")), str(row.get("thread_key", "")))
            if key in seen_threads:
                continue
            seen_threads.add(key)
            commitments.append(
                {
                    "channel": str(row.get("channel", "")),
                    "thread_key": str(row.get("thread_key", "")),
                    "chat_name": str(row.get("chat_name", "")),
                    "relationship_score": round(0.18 + float(row.get("confidence", 0.0) or 0.0) * 0.22, 4),
                    "summary": compact_text(str(row.get("resume_cue", "") or f"temporal {row.get('type', 'open_loop')} due"), 180),
                    "recurring_motifs": ["temporal_commitment", str(row.get("type", "") or "open_loop")],
                    "tone_tendency": "continuity_guard",
                    "last_message_at": str(row.get("updated_at", "") or ""),
                    "temporal_dedupe_key": str(row.get("dedupe_key", "") or ""),
                    "temporal_due_at": str(row.get("due_at", "") or ""),
                }
            )
            if len(commitments) >= max(1, int(limit)):
                break
        return commitments

    def enqueue_operator_run(
        self,
        *,
        task_type: str,
        goal: str,
        scope: str,
        workspace_mode: str,
        read_boundary: dict[str, Any],
        write_boundary: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO operator_runs(
                    task_type, goal, scope, workspace_mode, status, read_boundary_json, write_boundary_json, payload_json, result_json, shadow_workspace, applied_live, created_at, completed_at
                ) VALUES (?, ?, ?, ?, 'planned', ?, ?, ?, '{}', '', 0, ?, '')
                """,
                (
                    str(task_type or "").strip(),
                    str(goal or "").strip(),
                    str(scope or "").strip(),
                    str(workspace_mode or "shadow_write").strip() or "shadow_write",
                    json.dumps(read_boundary or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(write_boundary or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        return {"id": int(row_id), "status": "planned", "created_at": now}

    def pending_operator_run(self) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM operator_runs WHERE status = 'planned' ORDER BY id ASC LIMIT 1"
            ).fetchone()
        if row is None:
            return {}
        payload = dict(row)
        return {
            **payload,
            "read_boundary": dict(_safe_json_dict(payload.get("read_boundary_json", "{}"))),
            "write_boundary": dict(_safe_json_dict(payload.get("write_boundary_json", "{}"))),
            "payload": dict(_safe_json_dict(payload.get("payload_json", "{}"))),
            "result": dict(_safe_json_dict(payload.get("result_json", "{}"))),
        }

    def complete_operator_run(
        self,
        *,
        run_id: int,
        status: str,
        result: dict[str, Any],
        shadow_workspace: str = "",
        applied_live: bool = False,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            self.conn.execute(
                """
                UPDATE operator_runs
                SET status = ?, result_json = ?, shadow_workspace = ?, applied_live = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    str(status or "").strip() or "reviewed",
                    json.dumps(result or {}, ensure_ascii=False, sort_keys=True),
                    str(shadow_workspace or ""),
                    1 if applied_live else 0,
                    now,
                    int(run_id or 0),
                ),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM operator_runs WHERE id = ?", (int(run_id or 0),)).fetchone()
        payload = dict(row) if row else {}
        return {
            **payload,
            "read_boundary": dict(_safe_json_dict(payload.get("read_boundary_json", "{}"))),
            "write_boundary": dict(_safe_json_dict(payload.get("write_boundary_json", "{}"))),
            "payload": dict(_safe_json_dict(payload.get("payload_json", "{}"))),
            "result": dict(_safe_json_dict(payload.get("result_json", "{}"))),
        }

    def operator_status(self, *, limit: int = 8) -> dict[str, Any]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    "SELECT * FROM operator_runs ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            ]
            pending = self.conn.execute("SELECT COUNT(*) AS count FROM operator_runs WHERE status = 'planned'").fetchone()
        runs: list[dict[str, Any]] = []
        for row in rows:
            runs.append(
                {
                    **row,
                    "read_boundary": dict(_safe_json_dict(row.get("read_boundary_json", "{}"))),
                    "write_boundary": dict(_safe_json_dict(row.get("write_boundary_json", "{}"))),
                    "payload": dict(_safe_json_dict(row.get("payload_json", "{}"))),
                    "result": dict(_safe_json_dict(row.get("result_json", "{}"))),
                }
            )
        latest = runs[0] if runs else {}
        return {
            "pending_count": int(pending["count"]) if pending else 0,
            "latest": latest,
            "recent_runs": runs,
        }

    def upsert_visual_memory(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        artifact_path: str,
        media_type: str,
        scene_summary: str,
        objects: list[str],
        text_ocr: str,
        mood_imagery: str,
        thread_relevance: float,
        visual_anchors: list[str],
        metadata: dict[str, Any] | None = None,
        source: str = "image_understand",
    ) -> dict[str, Any]:
        now = utc_now()
        record_id = stable_digest(channel, thread_key, artifact_path, limit=24)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO visual_memory(
                    id, channel, thread_key, chat_name, artifact_path, media_type, scene_summary, objects_json, text_ocr, mood_imagery,
                    thread_relevance, visual_anchors_json, metadata_json, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    chat_name = excluded.chat_name,
                    media_type = excluded.media_type,
                    scene_summary = excluded.scene_summary,
                    objects_json = excluded.objects_json,
                    text_ocr = excluded.text_ocr,
                    mood_imagery = excluded.mood_imagery,
                    thread_relevance = excluded.thread_relevance,
                    visual_anchors_json = excluded.visual_anchors_json,
                    metadata_json = excluded.metadata_json,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    record_id,
                    str(channel or "").strip(),
                    str(thread_key or "").strip(),
                    str(chat_name or "").strip(),
                    str(artifact_path or "").strip(),
                    str(media_type or "").strip(),
                    compact_text(scene_summary, 400),
                    json.dumps([str(item).strip() for item in objects if str(item).strip()], ensure_ascii=False),
                    compact_text(text_ocr, 1200),
                    compact_text(mood_imagery, 240),
                    float(thread_relevance or 0.0),
                    json.dumps([str(item).strip() for item in visual_anchors if str(item).strip()], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    str(source or "image_understand"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        return {"id": record_id, "status": "ok", "updated_at": now}

    def visual_memory(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                    SELECT *
                    FROM visual_memory
                    WHERE channel = ?
                      AND thread_key = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (channel, normalized_thread_key, max(1, int(limit))),
                ).fetchall()
            ]
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    **row,
                    "objects": self._decode_json_array(row.get("objects_json", "[]")),
                    "visual_anchors": self._decode_json_array(row.get("visual_anchors_json", "[]")),
                    "metadata": dict(_safe_json_dict(row.get("metadata_json", "{}"))),
                }
            )
        return items

    def upsert_world_coupling_signal(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        cue_type: str,
        summary: str,
        source_ref: str = "",
        confidence: float = 0.62,
        stale_after: str = "",
        status: str = "live",
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_channel = str(channel or "wechat").strip() or "wechat"
        normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        normalized_chat_name = str(chat_name or normalized_thread_key).strip()
        normalized_type = str(cue_type or "").strip() or "file_artifact"
        compact_summary = compact_text(str(summary or "").strip(), 240)
        if not compact_summary:
            return {"status": "skipped", "reason": "empty_summary", "present": False}
        now = utc_now()
        if not str(stale_after or "").strip():
            stale_after = (
                datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")
        refs = [str(item).strip() for item in list(evidence_refs or []) if str(item).strip()][:4]
        source = compact_text(str(source_ref or "").strip(), 500)
        record_id = stable_digest(normalized_channel, normalized_thread_key, normalized_type, source, compact_summary, limit=24)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO world_coupling_signal(
                    id, channel, thread_key, chat_name, cue_type, summary, source_ref,
                    confidence, stale_after, status, evidence_refs_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    chat_name = excluded.chat_name,
                    summary = excluded.summary,
                    confidence = excluded.confidence,
                    stale_after = excluded.stale_after,
                    status = excluded.status,
                    evidence_refs_json = excluded.evidence_refs_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record_id,
                    normalized_channel,
                    normalized_thread_key,
                    normalized_chat_name,
                    normalized_type,
                    compact_summary,
                    source,
                    self._clamp(confidence, default=0.62),
                    str(stale_after or "").strip(),
                    str(status or "live").strip() or "live",
                    json.dumps(refs, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM world_coupling_signal WHERE id = ?", (record_id,)).fetchone()
        return self._world_coupling_signal_from_row(dict(row) if row else None, now=now)

    def _world_coupling_signal_from_row(self, row: dict[str, Any] | None, *, now: str) -> dict[str, Any]:
        if not row:
            return {"present": False}
        stale_after = str(row.get("stale_after", "") or "")
        stale = bool(stale_after and stale_after <= now)
        status = str(row.get("status", "") or "live")
        return {
            "id": str(row.get("id", "") or ""),
            "present": True,
            "channel": str(row.get("channel", "") or ""),
            "thread_key": str(row.get("thread_key", "") or ""),
            "chat_name": str(row.get("chat_name", "") or ""),
            "cue_type": str(row.get("cue_type", "") or ""),
            "summary": str(row.get("summary", "") or ""),
            "source_ref": str(row.get("source_ref", "") or ""),
            "confidence": float(row.get("confidence", 0.0) or 0.0),
            "stale_after": stale_after,
            "status": "expired" if stale and status == "live" else status,
            "stale": stale,
            "evidence_refs": self._decode_json_array(row.get("evidence_refs_json", "[]"))[:4],
            "metadata": dict(_safe_json_dict(row.get("metadata_json", "{}"))),
            "created_at": str(row.get("created_at", "") or ""),
            "updated_at": str(row.get("updated_at", "") or ""),
        }

    def world_coupling_signals(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 3,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        now = utc_now()
        clauses = ["channel = ?", "thread_key = ?"]
        args: list[Any] = [str(channel or "wechat").strip() or "wechat", normalized_thread_key]
        if not include_inactive:
            clauses.append("status = 'live'")
            clauses.append("(stale_after = '' OR stale_after > ?)")
            args.append(now)
        args.append(max(1, int(limit)))
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    f"""
                    SELECT *
                    FROM world_coupling_signal
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    tuple(args),
                ).fetchall()
            ]
        items = [self._world_coupling_signal_from_row(row, now=now) for row in rows]
        return [item for item in items if bool(item.get("present", False))]

    def show_world_coupling(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        items = self.world_coupling_signals(
            thread_key=normalized_thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            include_inactive=include_inactive,
        )
        return {
            "status": "ok",
            "thread_key": normalized_thread_key,
            "chat_name": str(chat_name or normalized_thread_key),
            "channel": channel,
            "count": len(items),
            "items": items,
        }

    def set_brain_mode(self, mode: str, *, note: str = "") -> dict[str, Any]:
        normalized_mode = str(mode or "").strip() or "companion"
        now = utc_now()
        with self._lock:
            current = self.conn.execute("SELECT * FROM brain_runtime_state WHERE runtime_id = 1").fetchone()
            previous_mode = str(current["mode"]) if current else ""
            metadata_json = str(current["metadata_json"]) if current else "{}"
            started_at = str(current["started_at"]) if current else now
            idle_since = str(current["idle_since"]) if current else now
            self.conn.execute(
                """
                INSERT INTO brain_runtime_state(runtime_id, mode, started_at, last_updated_at, idle_since, metadata_json)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(runtime_id) DO UPDATE SET
                    mode = excluded.mode,
                    started_at = excluded.started_at,
                    last_updated_at = excluded.last_updated_at,
                    idle_since = excluded.idle_since,
                    metadata_json = excluded.metadata_json
                """,
                (normalized_mode, started_at, now, idle_since, metadata_json),
            )
            self.conn.execute(
                """
                INSERT INTO brain_mode_events(previous_mode, next_mode, note, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (previous_mode, normalized_mode, note, now),
            )
            self.conn.commit()
        state = self.brain_state(default_mode=normalized_mode)
        state["previous_mode"] = previous_mode
        state["note"] = note
        return state

    def touch_brain_runtime(self, *, idle_since: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.brain_state()
        current_metadata = dict(current.get("metadata", {}))
        if metadata:
            current_metadata.update(dict(metadata))
        now = utc_now()
        with self._lock:
            self.conn.execute(
                """
                UPDATE brain_runtime_state
                SET last_updated_at = ?,
                    idle_since = ?,
                    metadata_json = ?
                WHERE runtime_id = 1
                """,
                (
                    now,
                    str(idle_since or current.get("idle_since", "") or now),
                    json.dumps(current_metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            self.conn.commit()
        return self.brain_state()

    def record_brain_loop_run(
        self,
        loop_name: str,
        *,
        mode: str,
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        influence_summary: str = "",
        blocked_reason: str = "",
        payload: dict[str, Any] | None = None,
        next_due_at: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO brain_loop_runs(
                    loop_name, mode, status, started_at, finished_at, duration_ms, influence_summary, blocked_reason, stats_json, next_due_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(loop_name or "").strip(),
                    str(mode or "").strip(),
                    str(status or "").strip() or "ok",
                    str(started_at or ""),
                    str(finished_at or ""),
                    float(duration_ms or 0.0),
                    str(influence_summary or ""),
                    str(blocked_reason or ""),
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    str(next_due_at or ""),
                ),
            )
            self.conn.execute(
                """
                UPDATE brain_runtime_state
                SET last_updated_at = ?
                WHERE runtime_id = 1
                """,
                (str(finished_at or started_at or utc_now()),),
            )
            self.conn.commit()
        return {
            "loop_name": str(loop_name or "").strip(),
            "mode": str(mode or "").strip(),
            "status": str(status or "").strip() or "ok",
            "started_at": str(started_at or ""),
            "finished_at": str(finished_at or ""),
            "duration_ms": round(float(duration_ms or 0.0), 2),
            "influence_summary": str(influence_summary or ""),
            "blocked_reason": str(blocked_reason or ""),
            "next_due_at": str(next_due_at or ""),
            "stats": dict(payload or {}),
        }

    def _jsonl_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _source_id(self, row: dict[str, Any], *, fallback_text: str = "") -> str:
        for key in ("id", "turn_id", "message_id", "event_id", "artifact_id", "path"):
            value = str(row.get(key, "")).strip()
            if value:
                return value
        return stable_digest(json.dumps(row, ensure_ascii=False, sort_keys=True), fallback_text, limit=24)

    def _row_context(self, row: dict[str, Any]) -> tuple[str, str, str]:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        channel = str(metadata.get("channel") or row.get("channel") or "").strip()
        chat_name = str(metadata.get("chat_name") or row.get("chat_name") or row.get("subject") or "").strip()
        thread_key = str(metadata.get("thread_key") or row.get("thread_key") or "").strip()
        return channel, _normalize_thread_key(channel, thread_key, chat_name=chat_name), chat_name

    def _memory_class(self, source_store: str, row: dict[str, Any]) -> str:
        if source_store == "working":
            return "working_memory"
        if source_store in {"helper_history_export", "helper_history_capture"}:
            return "sensory_trace"
        if source_store == "emotion_trace":
            return "emotional_trace"
        if source_store in {"archive", "snapshot_archive"}:
            return "episodic_memory"
        if source_store == "callback_candidates":
            return "initiative_seed"
        if source_store == "initiative_candidates":
            return "initiative_seed"
        kind = str(row.get("kind", "")).strip()
        if source_store == "candidate":
            return KIND_TO_MEMORY_CLASS.get(kind, "working_memory")
        return KIND_TO_MEMORY_CLASS.get(kind, "relationship_memory")

    def _memory_node(self, source_store: str, row: dict[str, Any]) -> dict[str, Any] | None:
        text = str(row.get("text", "")).strip()
        if not text:
            return None
        channel, thread_key, chat_name = self._row_context(row)
        source_id = self._source_id(row, fallback_text=text)
        now = utc_now()
        return {
            "id": f"{source_store}:{source_id}",
            "node_type": "memory",
            "memory_class": self._memory_class(source_store, row),
            "source_store": source_store,
            "source_id": source_id,
            "source_kind": str(row.get("kind", "")).strip(),
            "text": compact_text(text, 320),
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "importance": float(row.get("importance", 0.7) or 0.7),
            "confidence": float(row.get("confidence", 0.7) or 0.7),
            "thread_affinity": float(row.get("thread_affinity", 0.0) or 0.0),
            "emotion_salience": float(row.get("emotion_salience", 0.0) or 0.0),
            "recall_count": int(row.get("recall_count", 0) or 0),
            "successful_recall_count": int(row.get("successful_recall_count", row.get("recall_count", 0)) or 0),
            "created_at": str(row.get("created_at") or row.get("first_seen_at") or now),
            "updated_at": str(row.get("last_seen_at") or row.get("updated_at") or row.get("created_at") or now),
            "metadata_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
        }

    def _archive_node(self, row: dict[str, Any]) -> dict[str, Any] | None:
        user_text = str(row.get("user_text", "")).strip()
        reply_text = str(row.get("reply_text", "")).strip()
        if not user_text and not reply_text:
            return None
        channel, thread_key, chat_name = self._row_context(row)
        source_id = self._source_id(row, fallback_text=f"{user_text}\n{reply_text}")
        now = utc_now()
        return {
            "id": f"archive:{source_id}",
            "node_type": "event",
            "memory_class": "episodic_memory",
            "source_store": "archive",
            "source_id": source_id,
            "source_kind": "archive_turn",
            "text": compact_text(f"user: {user_text} | holo: {reply_text}", 360),
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "importance": 0.75,
            "confidence": 0.95,
            "thread_affinity": float(row.get("thread_affinity", 1.0) or 1.0),
            "emotion_salience": float(row.get("emotion_salience", 0.0) or 0.0),
            "recall_count": 0,
            "successful_recall_count": 0,
            "created_at": str(row.get("created_at") or now),
            "updated_at": str(row.get("created_at") or now),
            "metadata_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
        }

    def _helper_files(self) -> list[tuple[str, Path]]:
        receipts_root = self.repo_root / ".holo_runtime" / "wechat-helper" / "receipts"
        files: list[tuple[str, Path]] = []
        for label, folder_name in (("helper_history_export", "history_exports"), ("helper_history_capture", "history_captures")):
            root = receipts_root / folder_name
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in TEXT_FILE_SUFFIXES:
                    files.append((label, path))
        return files

    def _helper_node(self, source_store: str, path: Path) -> dict[str, Any] | None:
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        cleaned = " ".join(text.split())
        if not cleaned:
            return None
        source_id = str(path.relative_to(self.repo_root)).replace("\\", "/")
        now = utc_now()
        return {
            "id": f"{source_store}:{stable_digest(source_id, cleaned, limit=24)}",
            "node_type": "artifact",
            "memory_class": "sensory_trace",
            "source_store": source_store,
            "source_id": source_id,
            "source_kind": "helper_history_file",
            "text": compact_text(cleaned, 320),
            "channel": "wechat",
            "thread_key": "",
            "chat_name": "",
            "importance": 0.6,
            "confidence": 0.72,
            "thread_affinity": 0.0,
            "emotion_salience": 0.0,
            "recall_count": 0,
            "successful_recall_count": 0,
            "created_at": now,
            "updated_at": now,
            "metadata_json": json.dumps({"path": source_id}, ensure_ascii=False, sort_keys=True),
        }

    def _thread_node(self, channel: str, thread_key: str, chat_name: str) -> dict[str, Any] | None:
        thread_name = thread_key or chat_name
        if not thread_name:
            return None
        now = utc_now()
        return {
            "id": f"thread:{channel}:{thread_name}",
            "node_type": "thread",
            "memory_class": "relationship_memory",
            "source_store": "thread_state",
            "source_id": thread_name,
            "source_kind": "thread",
            "text": thread_name,
            "channel": channel,
            "thread_key": thread_name,
            "chat_name": chat_name or thread_name,
            "importance": 1.0,
            "confidence": 1.0,
            "thread_affinity": 1.0,
            "emotion_salience": 0.0,
            "recall_count": 0,
            "successful_recall_count": 0,
            "created_at": now,
            "updated_at": now,
            "metadata_json": json.dumps({"thread_key": thread_name, "chat_name": chat_name or thread_name}, ensure_ascii=False, sort_keys=True),
        }

    def _contact_node(self, channel: str, thread_key: str, chat_name: str) -> dict[str, Any] | None:
        identity = thread_key or chat_name
        if not identity:
            return None
        now = utc_now()
        return {
            "id": f"contact:{channel}:{identity}",
            "node_type": "contact",
            "memory_class": "relationship_memory",
            "source_store": "contact_state",
            "source_id": identity,
            "source_kind": "contact",
            "text": chat_name or identity,
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name or identity,
            "importance": 1.0,
            "confidence": 1.0,
            "thread_affinity": 1.0 if thread_key else 0.0,
            "emotion_salience": 0.0,
            "recall_count": 0,
            "successful_recall_count": 0,
            "created_at": now,
            "updated_at": now,
            "metadata_json": json.dumps({"contact": chat_name or identity}, ensure_ascii=False, sort_keys=True),
        }

    def _edge(self, from_node_id: str, to_node_id: str, edge_type: str, *, weight: float, confidence: float) -> dict[str, Any]:
        now = utc_now()
        return {
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "edge_type": edge_type,
            "weight": float(weight),
            "confidence": float(confidence),
            "metadata_json": "{}",
            "created_at": now,
            "updated_at": now,
        }

    def _thread_aliases(self, channel: str, thread_key: str, chat_name: str) -> tuple[str, set[str]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        normalized_chat_name = str(chat_name or "").strip()
        aliases = {item for item in {normalized_thread_key, normalized_chat_name} if item}
        if str(channel or "").strip().lower() == "wechat" and normalized_thread_key.startswith("wechat:"):
            bare_alias = normalized_thread_key[len("wechat:") :].strip()
            if bare_alias and not bare_alias.endswith("@chatroom") and not bare_alias.startswith("wxid_"):
                aliases.add(bare_alias)
        if str(channel or "").strip().lower() == "wechat" and normalized_chat_name:
            aliases.add(f"wechat:{normalized_chat_name}")
        return normalized_thread_key, aliases

    def _thread_state_bucket(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        state = {
            "thread_key": thread_key,
            "channel": channel,
            "chat_name": chat_name,
            "relationship_score": 0.0,
            "recall_count": 0,
            "last_recalled_at": "",
            "last_message_at": "",
            "summary_lines": [],
            "motif_counter": {},
            "tone_votes": {},
            "relationship_lines": [],
            "anchor_lines": [],
            "unfinished_threads": [],
            "archive_count": 0,
            "relationship_memory_count": 0,
            "explicit_user_signals": 0,
            "successful_recall_total": 0,
        }
        state.update(GAME_STATE_DEFAULTS)
        return state

    def _module_hints(self, *names: str) -> tuple[str, ...]:
        hints: list[str] = []
        for name in names:
            values = getattr(self.rag, name, ())
            if isinstance(values, (list, tuple)):
                hints.extend(str(item) for item in values if str(item).strip())
        return tuple(hints)

    def _node_payload(self, node: dict[str, Any]) -> dict[str, Any]:
        payload = _safe_json_dict(node.get("metadata_json", "{}"))
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            payload["metadata"] = dict(metadata)
        return payload

    def _node_motif(self, node: dict[str, Any], payload: dict[str, Any]) -> str:
        motif = str(payload.get("motif", "")).strip()
        if motif:
            return motif
        if str(node.get("source_store", "")) == "archive":
            try:
                inferred = str(self.rag.thought_motif_for_archive(payload or {})).strip()
            except Exception:  # noqa: BLE001
                inferred = ""
            if inferred:
                return inferred
        return ""

    def _update_counter(self, counter: dict[str, Any], key: str, amount: float = 1.0) -> None:
        current = float(counter.get(key, 0.0) or 0.0)
        counter[key] = current + float(amount)

    def _tone_votes_from_motif(self, motif: str) -> dict[str, float]:
        mapping = {
            "continuity": {"continuity_guard": 1.1, "warm_attentive": 0.3, "playful_teasing": 0.15},
            "craft": {"co_build_nimble": 1.8},
            "pressure": {"protective_steady": 1.8, "warm_attentive": 0.4},
            "companionship": {"warm_attentive": 1.4, "playful_teasing": 0.35},
            "journey": {"wandering_companion": 1.5, "warm_attentive": 0.3, "playful_teasing": 0.2},
            "treat": {"playful_teasing": 1.9, "warm_attentive": 0.25, "wandering_companion": 0.2},
        }
        return dict(mapping.get(motif, {}))

    def _tone_votes_from_text(self, text: str) -> dict[str, float]:
        raw = str(text or "").strip()
        lowered = raw.lower()
        votes: dict[str, float] = {}
        groups = (
            ("warm_attentive", self._module_hints("COMPANIONSHIP_HINTS", "AFFECTION_HINTS")),
            ("protective_steady", self._module_hints("PRESSURE_HINTS", "EMOTIONAL_HINTS")),
            ("co_build_nimble", self._module_hints("TECHNICAL_HINTS")),
            ("playful_teasing", self._module_hints("TREAT_HINTS")),
            ("wandering_companion", self._module_hints("ROAD_TRIP_HINTS", "MEDIEVAL_HINTS", "SPICE_AND_WOLF_HINTS")),
        )
        for tone, hints in groups:
            if any(hint and (hint in raw or hint.lower() in lowered) for hint in hints):
                votes[tone] = votes.get(tone, 0.0) + 1.0
        if any(hint and (hint in raw or hint.lower() in lowered) for hint in UNFINISHED_HINTS):
            votes["continuity_guard"] = votes.get("continuity_guard", 0.0) + 0.4
        return votes

    def _extract_anchor_line(self, node: dict[str, Any], payload: dict[str, Any]) -> str:
        if str(node.get("source_store", "")) == "archive":
            user = compact_text(str(payload.get("user_excerpt", "") or payload.get("user_text", "")), 72)
            if user:
                return user
        for key in ("reason", "prompt", "text"):
            text = compact_text(str(payload.get(key, "") or node.get("text", "")), 88)
            if text:
                return text
        return ""

    def _extract_unfinished_line(self, node: dict[str, Any], payload: dict[str, Any]) -> str:
        source_store = str(node.get("source_store", ""))
        candidates: list[str] = []
        if source_store == "archive":
            candidates.extend(
                [
                    str(payload.get("user_excerpt", "") or payload.get("user_text", "")),
                    str(payload.get("reply_excerpt", "") or payload.get("reply_text", "")),
                ]
            )
        else:
            candidates.extend([str(payload.get("reason", "")), str(payload.get("prompt", "")), str(node.get("text", ""))])
        for raw in candidates:
            text = compact_text(raw, 88)
            lowered = text.lower()
            if not text:
                continue
            if source_store in {"callback_candidates", "initiative_candidates"}:
                return text
            if any(hint in text or hint.lower() in lowered for hint in UNFINISHED_HINTS):
                return text
        return ""

    def _fold_node_into_thread_state(self, state: dict[str, Any], node: dict[str, Any]) -> None:
        payload = self._node_payload(node)
        memory_class = str(node.get("memory_class", "")).strip()
        source_store = str(node.get("source_store", "")).strip()
        text = str(node.get("text", "")).strip()
        updated_at = str(node.get("updated_at", "")).strip()
        if updated_at and updated_at > str(state.get("last_message_at", "")):
            state["last_message_at"] = updated_at
        if text and len(state["summary_lines"]) < 3:
            state["summary_lines"].append(compact_text(text, 88))
        if memory_class == "relationship_memory" and node.get("node_type") not in {"thread", "contact"}:
            self._update_counter(state, "relationship_memory_count", 1)
            relationship_line = compact_text(text, 100)
            if relationship_line:
                state["relationship_lines"].append(relationship_line)
        if bool(payload.get("explicit_user_signal", False)):
            self._update_counter(state, "explicit_user_signals", 1)
        successful_recall = int(node.get("successful_recall_count", 0) or 0)
        state["recall_count"] += successful_recall
        self._update_counter(state, "successful_recall_total", successful_recall)
        motif = self._node_motif(node, payload)
        if motif:
            self._update_counter(state["motif_counter"], motif, 1)
            for tone, weight in self._tone_votes_from_motif(motif).items():
                self._update_counter(state["tone_votes"], tone, weight)
        for tone, weight in self._tone_votes_from_text(text).items():
            self._update_counter(state["tone_votes"], tone, weight)
        if source_store == "archive":
            self._update_counter(state, "archive_count", 1)
        anchor_line = self._extract_anchor_line(node, payload)
        if anchor_line:
            state["anchor_lines"].append(anchor_line)
        unfinished_line = self._extract_unfinished_line(node, payload)
        if unfinished_line:
            state["unfinished_threads"].append(unfinished_line)

    def _tone_tendency_from_state(self, state: dict[str, Any]) -> str:
        votes = dict(state.get("tone_votes", {}))
        if not votes:
            return "warm_attentive"
        ordered = sorted(votes.items(), key=lambda item: (float(item[1]), item[0]), reverse=True)
        return str(ordered[0][0] or "warm_attentive")

    def _relationship_summary_from_state(self, state: dict[str, Any]) -> str:
        top_motifs = list(state.get("recurring_motifs", []))
        unfinished_threads = list(state.get("unfinished_threads", []))
        tone_tendency = str(state.get("tone_tendency", "") or "warm_attentive")
        lines: list[str] = []
        tone_line = TONE_TENDENCY_LINES.get(tone_tendency, "")
        if tone_line:
            lines.append(tone_line)
        if top_motifs:
            chosen_motif = str(top_motifs[0])
            if chosen_motif == "continuity" and tone_tendency == "continuity_guard":
                for candidate in top_motifs[1:]:
                    if str(candidate) != "continuity":
                        chosen_motif = str(candidate)
                        break
            motif_line = RELATIONSHIP_MOTIF_LINES.get(chosen_motif, "")
            if motif_line:
                lines.append(motif_line)
        if unfinished_threads:
            lines.append(f"这条线眼下还挂着「{unfinished_threads[0]}」，回话时别把它当成没发生过。")
        return " ".join(_dedupe_strings(lines)[:3])

    def _row_matches_thread(self, row: dict[str, Any], *, channel: str, thread_key: str, chat_name: str) -> bool:
        normalized_thread_key, aliases = self._thread_aliases(channel, thread_key, chat_name)
        row_channel, row_thread_key, row_chat_name = self._row_context(row)
        if row_channel and str(channel or "").strip() and row_channel != str(channel or "").strip():
            return False
        row_aliases = {item for item in {row_thread_key, row_chat_name} if item}
        if normalized_thread_key and row_thread_key == normalized_thread_key:
            return True
        if aliases and row_aliases.intersection(aliases):
            return True
        return False

    def _augment_materialized_nodes(self, nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {node["id"]: node for node in nodes}
        edges: list[dict[str, Any]] = []
        thread_state: dict[str, dict[str, Any]] = {}

        for node in list(deduped.values()):
            if node["node_type"] in {"thread", "contact"}:
                continue
            channel = str(node["channel"]).strip()
            thread_key = str(node["thread_key"]).strip()
            chat_name = str(node["chat_name"]).strip()
            thread_node = self._thread_node(channel, thread_key, chat_name)
            contact_node = self._contact_node(channel, thread_key, chat_name)
            if thread_node:
                deduped.setdefault(thread_node["id"], thread_node)
                edges.append(self._edge(thread_node["id"], node["id"], "contains", weight=1.0, confidence=1.0))
            if contact_node:
                deduped.setdefault(contact_node["id"], contact_node)
                edges.append(self._edge(contact_node["id"], node["id"], "evokes", weight=0.92, confidence=0.88))
            if thread_node and contact_node:
                edges.append(self._edge(contact_node["id"], thread_node["id"], "inhabits", weight=1.0, confidence=1.0))
            if not thread_key:
                continue
            key = f"{channel}:{thread_key}"
            state = thread_state.setdefault(key, self._thread_state_bucket(channel=channel, thread_key=thread_key, chat_name=chat_name))
            memory_class = str(node["memory_class"]).strip()
            state["relationship_score"] += 1.6 if memory_class == "relationship_memory" else 1.1 if memory_class == "episodic_memory" else 0.4
            self._fold_node_into_thread_state(state, node)

        for state in thread_state.values():
            state["summary_lines"] = _dedupe_strings(list(state.get("summary_lines", [])))[:3]
            state["relationship_lines"] = _dedupe_strings(list(state.get("relationship_lines", [])))[:4]
            state["anchor_lines"] = _dedupe_strings(list(state.get("anchor_lines", [])))[:4]
            state["unfinished_threads"] = _dedupe_strings(list(state.get("unfinished_threads", [])))[:3]
            motif_counter = dict(state.get("motif_counter", {}))
            state["recurring_motifs"] = [
                motif
                for motif, _count in sorted(
                    motif_counter.items(),
                    key=lambda item: (float(item[1]), item[0]),
                    reverse=True,
                )[:3]
            ]
            tone_tendency = self._tone_tendency_from_state(state)
            state["tone_tendency"] = tone_tendency
            archive_count = float(state.get("archive_count", 0) or 0)
            relationship_memory_count = float(state.get("relationship_memory_count", 0) or 0)
            explicit_user_signals = float(state.get("explicit_user_signals", 0) or 0)
            successful_recall_total = float(state.get("successful_recall_total", 0) or 0)
            closeness_seed = float(motif_counter.get("companionship", 0.0) or 0.0) + float(motif_counter.get("treat", 0.0) or 0.0)
            continuity_seed = float(motif_counter.get("continuity", 0.0) or 0.0) + float(motif_counter.get("craft", 0.0) or 0.0) * 0.35
            trust_score = min(1.0, 0.16 * relationship_memory_count + 0.03 * archive_count + 0.08 * explicit_user_signals + 0.02 * successful_recall_total)
            closeness_score = min(1.0, 0.14 * closeness_seed + 0.03 * archive_count + 0.04 * relationship_memory_count)
            continuity_score = min(1.0, 0.15 * continuity_seed + 0.03 * archive_count + 0.025 * successful_recall_total)
            state["trust_score"] = round(trust_score, 3)
            state["closeness_score"] = round(closeness_score, 3)
            state["continuity_score"] = round(continuity_score, 3)
            summary = self._relationship_summary_from_state(state)
            if summary:
                state["summary_lines"] = _dedupe_strings([summary] + list(state.get("summary_lines", [])))[:3]
            state["summary"] = summary

        return list(deduped.values()), edges, thread_state

    def _materialize_sources(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        self.rag.ensure_store_files()
        source_counts: dict[str, int] = {}
        nodes: list[dict[str, Any]] = []

        for source_store in ("durable", "candidate", "working"):
            rows = list(self.rag.load_rows(source_store))
            source_counts[source_store] = len(rows)
            nodes.extend(node for row in rows if (node := self._memory_node(source_store, row)))

        callbacks = list(self.rag.load_callback_candidates(limit=None))
        source_counts["callback_candidates"] = len(callbacks)
        nodes.extend(node for row in callbacks if (node := self._memory_node("callback_candidates", row)))

        thoughts = list(self.rag.load_thought_stream(limit=None))
        source_counts["thought_stream"] = len(thoughts)
        nodes.extend(node for row in thoughts if (node := self._memory_node("thought_stream", row)))

        initiatives = list(self.rag.load_initiative_candidates(limit=None))
        source_counts["initiative_candidates"] = len(initiatives)
        nodes.extend(node for row in initiatives if (node := self._memory_node("initiative_candidates", row)))

        emotion_rows = self._jsonl_rows(Path(self.rag.EMOTION_TRACE_PATH))
        source_counts["emotion_trace"] = len(emotion_rows)
        for row in emotion_rows:
            synthesized = dict(row)
            synthesized.setdefault("text", str(row.get("name") or row.get("temperature") or "emotion_trace"))
            node = self._memory_node("emotion_trace", synthesized)
            if node:
                nodes.append(node)

        archive_rows = list(self.rag.load_archive(limit=None))
        source_counts["archive"] = len(archive_rows)
        nodes.extend(node for row in archive_rows if (node := self._archive_node(row)))

        helper_files = self._helper_files()
        source_counts["helper_history_files"] = len(helper_files)
        for source_store, path in helper_files:
            node = self._helper_node(source_store, path)
            if node:
                nodes.append(node)

        materialized_nodes, edges, thread_state = self._augment_materialized_nodes(nodes)
        return materialized_nodes, edges, {"source_counts": source_counts, "thread_state": thread_state}

    def _materialize_thread_sources(self, *, channel: str, thread_key: str, chat_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        self.rag.ensure_store_files()
        source_counts: dict[str, int] = {}
        nodes: list[dict[str, Any]] = []

        for source_store in ("durable", "candidate", "working"):
            rows = [row for row in self.rag.load_rows(source_store) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
            source_counts[source_store] = len(rows)
            nodes.extend(node for row in rows if (node := self._memory_node(source_store, row)))

        callbacks = [row for row in self.rag.load_callback_candidates(limit=None) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
        source_counts["callback_candidates"] = len(callbacks)
        nodes.extend(node for row in callbacks if (node := self._memory_node("callback_candidates", row)))

        thoughts = [row for row in self.rag.load_thought_stream(limit=None) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
        source_counts["thought_stream"] = len(thoughts)
        nodes.extend(node for row in thoughts if (node := self._memory_node("thought_stream", row)))

        initiatives = [row for row in self.rag.load_initiative_candidates(limit=None) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
        source_counts["initiative_candidates"] = len(initiatives)
        nodes.extend(node for row in initiatives if (node := self._memory_node("initiative_candidates", row)))

        emotion_rows = [row for row in self._jsonl_rows(Path(self.rag.EMOTION_TRACE_PATH)) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
        source_counts["emotion_trace"] = len(emotion_rows)
        for row in emotion_rows:
            synthesized = dict(row)
            synthesized.setdefault("text", str(row.get("name") or row.get("temperature") or "emotion_trace"))
            node = self._memory_node("emotion_trace", synthesized)
            if node:
                nodes.append(node)

        archive_rows = [row for row in self.rag.load_archive(limit=None) if self._row_matches_thread(row, channel=channel, thread_key=thread_key, chat_name=chat_name)]
        source_counts["archive"] = len(archive_rows)
        nodes.extend(node for row in archive_rows if (node := self._archive_node(row)))

        materialized_nodes, edges, thread_state = self._augment_materialized_nodes(nodes)
        return materialized_nodes, edges, {"source_counts": source_counts, "thread_state": thread_state}

    def _existing_node_stats(
        self,
        *,
        channel: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[str, dict[str, int]]:
        args: list[Any] = []
        conditions: list[str] = []
        if str(channel or "").strip():
            conditions.append("channel = ?")
            args.append(str(channel or "").strip())
        thread_conditions: list[str] = []
        if str(thread_key or "").strip():
            thread_conditions.append("thread_key = ?")
            args.append(str(thread_key or "").strip())
        if str(chat_name or "").strip():
            thread_conditions.append("chat_name = ?")
            args.append(str(chat_name or "").strip())
        if thread_conditions:
            conditions.append("(" + " OR ".join(thread_conditions) + ")")
        query = "SELECT id, recall_count, successful_recall_count FROM mind_nodes"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        return {
            str(row["id"]): {
                "recall_count": int(row["recall_count"] or 0),
                "successful_recall_count": int(row["successful_recall_count"] or 0),
            }
            for row in self.conn.execute(query, tuple(args)).fetchall()
        }

    def _existing_thread_state(
        self,
        *,
        channel: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        args: list[Any] = []
        conditions: list[str] = []
        if str(channel or "").strip():
            conditions.append("channel = ?")
            args.append(str(channel or "").strip())
        if str(thread_key or "").strip():
            conditions.append("thread_key = ?")
            args.append(str(thread_key or "").strip())
        elif str(chat_name or "").strip():
            conditions.append("chat_name = ?")
            args.append(str(chat_name or "").strip())
        query = "SELECT * FROM mind_thread_state"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        return {
            (str(row["channel"]), str(row["thread_key"])): dict(row)
            for row in self.conn.execute(query, tuple(args)).fetchall()
        }

    @staticmethod
    def _merge_existing_node_stats(nodes: list[dict[str, Any]], existing_stats: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
        for node in nodes:
            stats = existing_stats.get(str(node.get("id", "")))
            if not stats:
                continue
            node["recall_count"] = max(int(node.get("recall_count", 0) or 0), int(stats.get("recall_count", 0) or 0))
            node["successful_recall_count"] = max(
                int(node.get("successful_recall_count", 0) or 0),
                int(stats.get("successful_recall_count", 0) or 0),
            )
        return nodes

    def _thread_rows_from_state(
        self,
        thread_state: dict[str, dict[str, Any]],
        *,
        existing_state: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        existing_state = existing_state or {}
        rows: list[dict[str, Any]] = []
        for payload in thread_state.values():
            existing = existing_state.get((str(payload["channel"]), str(payload["thread_key"])), {})
            rows.append(
                {
                    "thread_key": payload["thread_key"],
                    "channel": payload["channel"],
                    "chat_name": payload["chat_name"],
                    "relationship_score": round(float(payload["relationship_score"]), 3),
                    "recall_count": max(int(payload["recall_count"]), int(existing.get("recall_count", 0) or 0)),
                    "last_recalled_at": str(existing.get("last_recalled_at", "") or ""),
                    "last_message_at": payload["last_message_at"],
                    "summary": str(payload.get("summary", "") or " | ".join(payload["summary_lines"][:3])),
                    "metadata_json": json.dumps(
                        {
                            "summary_lines": payload["summary_lines"][:3],
                            "relationship_lines": payload.get("relationship_lines", [])[:4],
                            "anchor_lines": payload.get("anchor_lines", [])[:4],
                            "unfinished_threads": payload.get("unfinished_threads", [])[:3],
                            "recurring_motifs": payload.get("recurring_motifs", [])[:3],
                            "tone_tendency": payload.get("tone_tendency", ""),
                            "trust_score": payload.get("trust_score", 0.0),
                            "closeness_score": payload.get("closeness_score", 0.0),
                            "continuity_score": payload.get("continuity_score", 0.0),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
        return rows

    def _insert_thread_rows(self, thread_rows: Iterable[dict[str, Any]]) -> None:
        deduped_rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in thread_rows:
            key = (str(row.get("channel", "")).strip(), str(row.get("thread_key", "")).strip())
            if key in seen:
                continue
            seen.add(key)
            deduped_rows.append(dict(row))
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO mind_thread_state(
                thread_key, channel, chat_name, relationship_score, recall_count, last_recalled_at, last_message_at, summary, metadata_json
            ) VALUES (
                :thread_key, :channel, :chat_name, :relationship_score, :recall_count, :last_recalled_at, :last_message_at, :summary, :metadata_json
            )
            """,
            deduped_rows,
        )

    def _delete_thread_materialization(self, *, channel: str, thread_key: str, chat_name: str) -> int:
        args: list[Any] = [channel]
        selectors: list[str] = []
        if thread_key:
            selectors.append("thread_key = ?")
            args.append(thread_key)
        if chat_name:
            selectors.append("chat_name = ?")
            args.append(chat_name)
        if not selectors:
            return 0
        node_ids = [
            str(row["id"])
            for row in self.conn.execute(
                "SELECT id FROM mind_nodes WHERE channel = ? AND (" + " OR ".join(selectors) + ")",
                tuple(args),
            ).fetchall()
        ]
        if node_ids:
            placeholders = ", ".join("?" for _ in node_ids)
            self.conn.execute(
                f"DELETE FROM mind_edges WHERE from_node_id IN ({placeholders}) OR to_node_id IN ({placeholders})",
                tuple(node_ids + node_ids),
            )
            self.conn.execute(f"DELETE FROM mind_nodes WHERE id IN ({placeholders})", tuple(node_ids))
        if thread_key:
            self.conn.execute("DELETE FROM mind_thread_state WHERE channel = ? AND thread_key = ?", (channel, thread_key))
        elif chat_name:
            self.conn.execute("DELETE FROM mind_thread_state WHERE channel = ? AND chat_name = ?", (channel, chat_name))
        return len(node_ids)

    def _insert_nodes(self, nodes: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO mind_nodes(
                id, node_type, memory_class, source_store, source_id, source_kind, text, channel, thread_key, chat_name,
                importance, confidence, thread_affinity, emotion_salience, recall_count, successful_recall_count,
                created_at, updated_at, metadata_json
            ) VALUES (
                :id, :node_type, :memory_class, :source_store, :source_id, :source_kind, :text, :channel, :thread_key, :chat_name,
                :importance, :confidence, :thread_affinity, :emotion_salience, :recall_count, :successful_recall_count,
                :created_at, :updated_at, :metadata_json
            )
            """,
            list(nodes),
        )

    def _insert_edges(self, edges: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO mind_edges(
                from_node_id, to_node_id, edge_type, weight, confidence, metadata_json, created_at, updated_at
            ) VALUES (
                :from_node_id, :to_node_id, :edge_type, :weight, :confidence, :metadata_json, :created_at, :updated_at
            )
            """,
            list(edges),
        )

    def rebuild(self, *, dry_run: bool = False) -> dict[str, Any]:
        created_at = utc_now()
        nodes, edges, extras = self._materialize_sources()
        with self._lock:
            existing_node_stats = self._existing_node_stats()
            existing_thread_state = self._existing_thread_state()
        nodes = self._merge_existing_node_stats(nodes, existing_node_stats)
        class_counts: dict[str, int] = {}
        for node in nodes:
            memory_class = str(node["memory_class"]).strip()
            class_counts[memory_class] = class_counts.get(memory_class, 0) + 1
        thread_rows = self._thread_rows_from_state(extras["thread_state"], existing_state=existing_thread_state)
        report = {
            "status": "dry_run" if dry_run else "ok",
            "db_path": str(self.db_path),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "thread_count": len(thread_rows),
            "memory_class_counts": class_counts,
            "source_counts": dict(extras["source_counts"]),
            "threads": [
                {
                    "thread_key": row["thread_key"],
                    "channel": row["channel"],
                    "chat_name": row["chat_name"],
                    "relationship_score": row["relationship_score"],
                    "summary": row["summary"],
                }
                for row in sorted(thread_rows, key=lambda item: item["relationship_score"], reverse=True)[:8]
            ],
        }
        if dry_run:
            return report
        with self._lock:
            run_id = self.conn.execute(
                "INSERT INTO mind_runs(run_type, status, note, stats_json, created_at) VALUES ('rebuild', 'running', '', '{}', ?)",
                (created_at,),
            ).lastrowid
            self.conn.execute("DELETE FROM mind_edges")
            self.conn.execute("DELETE FROM mind_nodes")
            self.conn.execute("DELETE FROM mind_thread_state")
            self._insert_nodes(nodes)
            self._insert_edges(edges)
            self._insert_thread_rows(thread_rows)
            self.conn.execute(
                "UPDATE mind_runs SET status = 'ok', stats_json = ?, completed_at = ? WHERE id = ?",
                (json.dumps(report, ensure_ascii=False, sort_keys=True), utc_now(), run_id),
            )
            self.conn.commit()
        return report

    def sync_thread(self, *, channel: str = "wechat", thread_key: str | None = None, chat_name: str | None = None) -> dict[str, Any]:
        normalized_thread_key, _aliases = self._thread_aliases(channel, str(thread_key or "").strip(), str(chat_name or "").strip())
        normalized_chat_name = str(chat_name or "").strip()
        if not normalized_thread_key and not normalized_chat_name:
            return {
                "status": "skipped",
                "reason": "missing_thread_context",
                "channel": str(channel or "").strip() or "wechat",
                "thread_key": "",
                "chat_name": "",
            }

        created_at = utc_now()
        nodes, edges, extras = self._materialize_thread_sources(
            channel=str(channel or "").strip() or "wechat",
            thread_key=normalized_thread_key,
            chat_name=normalized_chat_name,
        )
        with self._lock:
            existing_node_stats = self._existing_node_stats(
                channel=str(channel or "").strip() or "wechat",
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
            )
            existing_thread_state = self._existing_thread_state(
                channel=str(channel or "").strip() or "wechat",
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
            )
        nodes = self._merge_existing_node_stats(nodes, existing_node_stats)
        thread_rows = self._thread_rows_from_state(extras["thread_state"], existing_state=existing_thread_state)
        report = {
            "status": "ok",
            "run_type": "sync_thread",
            "db_path": str(self.db_path),
            "channel": str(channel or "").strip() or "wechat",
            "thread_key": normalized_thread_key,
            "chat_name": normalized_chat_name,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "thread_count": len(thread_rows),
            "source_counts": dict(extras["source_counts"]),
            "threads": [
                {
                    "thread_key": row["thread_key"],
                    "channel": row["channel"],
                    "chat_name": row["chat_name"],
                    "relationship_score": row["relationship_score"],
                    "summary": row["summary"],
                    "recall_count": row["recall_count"],
                    "last_recalled_at": row["last_recalled_at"],
                }
                for row in thread_rows
            ],
        }
        with self._lock:
            run_id = self.conn.execute(
                "INSERT INTO mind_runs(run_type, status, note, stats_json, created_at) VALUES ('sync_thread', 'running', ?, '{}', ?)",
                (normalized_thread_key or normalized_chat_name, created_at),
            ).lastrowid
            deleted_nodes = self._delete_thread_materialization(
                channel=str(channel or "").strip() or "wechat",
                thread_key=normalized_thread_key,
                chat_name=normalized_chat_name,
            )
            if nodes:
                self._insert_nodes(nodes)
            if edges:
                self._insert_edges(edges)
            if thread_rows:
                self._insert_thread_rows(thread_rows)
            report["deleted_nodes"] = deleted_nodes
            self.conn.execute(
                "UPDATE mind_runs SET status = 'ok', stats_json = ?, completed_at = ? WHERE id = ?",
                (json.dumps(report, ensure_ascii=False, sort_keys=True), utc_now(), run_id),
            )
            self.conn.commit()
        return report

    def sync_archive_entry(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {"status": "skipped", "reason": "missing_archive_entry"}
        channel, thread_key, chat_name = self._row_context(row)
        return self.sync_thread(channel=channel or "wechat", thread_key=thread_key, chat_name=chat_name)

    def _ensure_materialized(self) -> None:
        if self.count_nodes() == 0:
            self.rebuild()

    def inspect_graph(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 12) -> dict[str, Any]:
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        args: list[Any] = []
        where = ""
        if normalized_thread_key:
            where = "WHERE channel = ? AND thread_key = ?"
            args.extend([channel, normalized_thread_key])
        elif chat_name:
            where = "WHERE channel = ? AND chat_name = ?"
            args.extend([channel, str(chat_name).strip()])
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    f"""
                SELECT id, node_type, memory_class, source_store, source_kind, text, channel, thread_key, chat_name,
                       importance, confidence, updated_at
                FROM mind_nodes
                {where}
                ORDER BY updated_at DESC, importance DESC
                LIMIT ?
                    """,
                    (*args, limit),
                ).fetchall()
            ]
            counts = {
                str(row["memory_class"]): int(row["count"])
                for row in self.conn.execute(
                    f"SELECT memory_class, COUNT(*) AS count FROM mind_nodes {where} GROUP BY memory_class ORDER BY count DESC",
                    tuple(args),
                ).fetchall()
            }
            thread_state = {}
            if normalized_thread_key:
                row = self.conn.execute(
                    "SELECT * FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                    (normalized_thread_key, channel),
                ).fetchone()
                thread_state = dict(row) if row else {}
                if thread_state:
                    thread_state["metadata"] = _safe_json_dict(thread_state.get("metadata_json", "{}"))
        return {
            "db_path": str(self.db_path),
            "total_nodes": self.count_nodes(),
            "filters": {"channel": channel, "thread_key": normalized_thread_key, "chat_name": str(chat_name or "")},
            "thread_state": thread_state,
            "memory_class_counts": counts,
            "nodes": rows,
        }

    def export_vector_documents(
        self,
        *,
        channel: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_materialized()
        args: list[Any] = []
        conditions = ["node_type NOT IN ('thread', 'contact')"]
        current_channel = str(channel or "").strip()
        current_thread_key = _normalize_thread_key(current_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        current_chat_name = str(chat_name or "").strip()
        if current_channel:
            conditions.append("channel = ?")
            args.append(current_channel)
        selectors: list[str] = []
        if current_thread_key:
            selectors.append("thread_key = ?")
            args.append(current_thread_key)
        if current_chat_name and current_chat_name != current_thread_key:
            selectors.append("chat_name = ?")
            args.append(current_chat_name)
        if selectors:
            conditions.append("(" + " OR ".join(selectors) + ")")
        query = (
            "SELECT id, channel, thread_key, chat_name, memory_class, source_store, source_id, text, importance, confidence "
            "FROM mind_nodes WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            args.append(max(1, int(limit)))
        with self._lock:
            rows = [dict(row) for row in self.conn.execute(query, tuple(args)).fetchall()]
        return rows

    def relationship_snapshot(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 3,
        _allow_refresh: bool = True,
    ) -> dict[str, Any]:
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        summary = ""
        relationship_score = 0.0
        last_message_at = ""
        recurring_motifs: list[str] = []
        unfinished_threads: list[str] = []
        anchor_lines: list[str] = []
        tone_tendency = ""
        trust_score = 0.0
        closeness_score = 0.0
        continuity_score = 0.0
        summary_lines: list[str] = []
        relationship_lines_meta: list[str] = []
        with self._lock:
            thread_state = None
            if normalized_thread_key:
                thread_state = self.conn.execute(
                    "SELECT * FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                    (normalized_thread_key, channel),
                ).fetchone()
            if thread_state:
                summary = str(thread_state["summary"] or "").strip()
                relationship_score = float(thread_state["relationship_score"] or 0.0)
                last_message_at = str(thread_state["last_message_at"] or "").strip()
                metadata_payload = _safe_json_dict(thread_state["metadata_json"])
                recurring_motifs = [str(item).strip() for item in metadata_payload.get("recurring_motifs", []) if str(item).strip()][:3]
                unfinished_threads = [str(item).strip() for item in metadata_payload.get("unfinished_threads", []) if str(item).strip()][:3]
                anchor_lines = [str(item).strip() for item in metadata_payload.get("anchor_lines", []) if str(item).strip()][:3]
                tone_tendency = str(metadata_payload.get("tone_tendency", "")).strip()
                trust_score = float(metadata_payload.get("trust_score", 0.0) or 0.0)
                closeness_score = float(metadata_payload.get("closeness_score", 0.0) or 0.0)
                continuity_score = float(metadata_payload.get("continuity_score", 0.0) or 0.0)
                summary_lines = [str(item).strip() for item in metadata_payload.get("summary_lines", []) if str(item).strip()]
                relationship_lines_meta = [str(item).strip() for item in metadata_payload.get("relationship_lines", []) if str(item).strip()]
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT id, text, source_store, source_id, source_kind, importance, confidence, updated_at
                FROM mind_nodes
                WHERE channel = ?
                  AND thread_key = ?
                  AND memory_class = 'relationship_memory'
                  AND node_type NOT IN ('thread', 'contact')
                ORDER BY successful_recall_count DESC, importance DESC, updated_at DESC
                LIMIT ?
                    """,
                    (channel, normalized_thread_key, max(1, limit)),
                ).fetchall()
            ]
        if normalized_thread_key and _allow_refresh and not (recurring_motifs or unfinished_threads or tone_tendency):
            sync_report = self.sync_thread(channel=channel, thread_key=normalized_thread_key, chat_name=str(chat_name or "").strip())
            if sync_report.get("status") == "ok":
                return self.relationship_snapshot(
                    thread_key=normalized_thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=limit,
                    _allow_refresh=False,
                )
        lines = _dedupe_strings(
            [summary]
            + summary_lines
            + relationship_lines_meta
            + ([TONE_TENDENCY_LINES.get(tone_tendency, "")] if tone_tendency else [])
            + ([f"反复绕回：{', '.join(recurring_motifs)}"] if recurring_motifs else [])
            + ([f"还挂着的线头：{unfinished_threads[0]}"] if unfinished_threads else [])
            + [compact_text(str(row.get("text", "")), 120) for row in rows if str(row.get("text", "")).strip()]
        )
        items = [
            {
                "id": str(row.get("id", "")),
                "text": str(row.get("text", "")),
                "source_store": str(row.get("source_store", "")),
                "source_id": str(row.get("source_id", "")),
                "source_kind": str(row.get("source_kind", "")),
            }
            for row in rows
        ]
        return {
            "summary": summary,
            "lines": lines[: max(1, limit)],
            "items": items[: max(1, limit)],
            "relationship_score": round(relationship_score, 4),
            "last_message_at": last_message_at,
            "recurring_motifs": recurring_motifs,
            "unfinished_threads": unfinished_threads,
            "anchor_lines": anchor_lines,
            "tone_tendency": tone_tendency,
            "trust_score": round(trust_score, 3),
            "closeness_score": round(closeness_score, 3),
            "continuity_score": round(continuity_score, 3),
        }

    def game_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        snapshot = self.relationship_snapshot(
            thread_key=normalized_thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=3,
            _allow_refresh=False,
        )
        with self._lock:
            row = None
            if normalized_thread_key:
                row = self.conn.execute(
                    "SELECT * FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                    (normalized_thread_key, channel),
                ).fetchone()
        metadata = _safe_json_dict(row["metadata_json"]) if row else {}
        payload = dict(GAME_STATE_DEFAULTS)
        payload["trust_score"] = self._clamp(metadata.get("trust_score", snapshot.get("trust_score", 0.5)), default=0.5)
        payload["pressure_level"] = self._clamp(metadata.get("pressure_level", 0.1), default=0.1)
        payload["teasing_tolerance"] = self._clamp(metadata.get("teasing_tolerance", 0.45), default=0.45)
        payload["reciprocity_balance"] = self._clamp(metadata.get("reciprocity_balance", 0.5), default=0.5)
        payload["initiative_window"] = self._clamp(
            metadata.get("initiative_window", (payload["trust_score"] + float(snapshot.get("closeness_score", 0.0) or 0.0)) / 2.0),
            default=0.35,
        )
        payload["correction_sensitivity"] = self._clamp(metadata.get("correction_sensitivity", 0.3), default=0.3)
        payload["thread_key"] = normalized_thread_key
        payload["chat_name"] = str(chat_name or snapshot.get("summary", "") or "").strip()
        payload["channel"] = channel
        payload["last_updated_at"] = str(metadata.get("game_state_updated_at", row["last_message_at"] if row else "")) if row else ""
        return payload

    def update_game_state(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        delta: dict[str, float] | None = None,
        absolute: dict[str, float] | None = None,
        note: str = "",
        source: str = "runtime",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                (normalized_thread_key, channel),
            ).fetchone()
            if row is None:
                return {"status": "skipped", "reason": "missing_thread_state", "thread_key": normalized_thread_key}
            metadata = _safe_json_dict(row["metadata_json"])
            current = dict(GAME_STATE_DEFAULTS)
            for key, value in dict(metadata).items():
                if key in GAME_STATE_DEFAULTS:
                    current[key] = self._clamp(value, default=GAME_STATE_DEFAULTS[key])
            for key, value in dict(delta or {}).items():
                if key in GAME_STATE_DEFAULTS:
                    current[key] = self._clamp(current.get(key, GAME_STATE_DEFAULTS[key]) + float(value or 0.0), default=GAME_STATE_DEFAULTS[key])
            for key, value in dict(absolute or {}).items():
                if key in GAME_STATE_DEFAULTS:
                    current[key] = self._clamp(value, default=GAME_STATE_DEFAULTS[key])
            now = utc_now()
            metadata.update(current)
            metadata["game_state_updated_at"] = now
            metadata["last_game_state_note"] = compact_text(note, 160)
            metadata["last_game_state_source"] = str(source or "runtime")
            self.conn.execute(
                """
                UPDATE mind_thread_state
                SET metadata_json = ?
                WHERE channel = ? AND thread_key = ?
                """,
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), channel, normalized_thread_key),
            )
            self.conn.commit()
        state = self.game_state(thread_key=normalized_thread_key, chat_name=chat_name, channel=channel)
        state["status"] = "ok"
        state["note"] = note
        state["source"] = source
        return state

    def _subject_defaults(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
    ) -> dict[str, Any]:
        relationship = self.relationship_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=3,
            _allow_refresh=False,
        )
        game = self.game_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        self_model = self.self_model_state()
        continuity = float(relationship.get("continuity_score", 0.0) or 0.0)
        closeness = float(relationship.get("closeness_score", 0.0) or 0.0)
        trust = float(game.get("trust_score", 0.0) or 0.0)
        initiative_window = float(game.get("initiative_window", 0.0) or 0.0)
        pressure = float(game.get("pressure_level", 0.0) or 0.0)
        teasing = float(game.get("teasing_tolerance", 0.0) or 0.0)
        active_deficits = [str(item).strip() for item in self_model.get("active_deficits", []) if str(item).strip()]
        unfinished = [str(item).strip() for item in relationship.get("unfinished_threads", []) if str(item).strip()]
        affect = {
            "boredom": self._clamp(0.24 + max(0.0, 0.42 - pressure) * 0.18, default=AFFECT_STATE_DEFAULTS["boredom"]),
            "curiosity": self.metric_state(
                self._clamp(0.28 + continuity * 0.22 + float(bool(unfinished)) * 0.12, default=AFFECT_STATE_DEFAULTS["curiosity"]),
                default=AFFECT_STATE_DEFAULTS["curiosity"],
                confidence=0.66,
                evidence_refs=[f"relationship:{thread_key}", "game:initiative_window", "unfinished_threads" if unfinished else "relationship:continuity"],
                updated_by="subject_defaults",
                decay_policy="event_weighted",
            ),
            "attachment_pull": self.metric_state(
                self._clamp(0.16 + closeness * 0.34 + trust * 0.16, default=AFFECT_STATE_DEFAULTS["attachment_pull"]),
                default=AFFECT_STATE_DEFAULTS["attachment_pull"],
                confidence=0.68,
                evidence_refs=[f"relationship:{thread_key}", "game:trust_score"],
                updated_by="subject_defaults",
                decay_policy="event_weighted",
            ),
            "continuity_anxiety": self._clamp(0.1 + continuity * 0.35 + float(bool(unfinished)) * 0.18, default=AFFECT_STATE_DEFAULTS["continuity_anxiety"]),
            "pride_tension": self._clamp(0.18 + float(bool(active_deficits)) * 0.22 + float(game.get("correction_sensitivity", 0.0) or 0.0) * 0.18, default=AFFECT_STATE_DEFAULTS["pride_tension"]),
            "frustration": self.metric_state(
                self._clamp(0.08 + pressure * 0.22, default=AFFECT_STATE_DEFAULTS["frustration"]),
                default=AFFECT_STATE_DEFAULTS["frustration"],
                confidence=0.61,
                evidence_refs=[f"game:{thread_key}", "game:pressure_level"],
                updated_by="subject_defaults",
                decay_policy="event_weighted",
            ),
            "appetite_play": self._clamp(0.18 + teasing * 0.28 + max(0.0, closeness - 0.4) * 0.18, default=AFFECT_STATE_DEFAULTS["appetite_play"]),
            "self_preservation": self._clamp(0.28 + pressure * 0.34 + (1.0 - float(self_model.get("identity_continuity", 0.6) or 0.6)) * 0.2, default=AFFECT_STATE_DEFAULTS["self_preservation"]),
        }
        drive = {
            "seek_contact": self._clamp(0.18 + self.metric_value(affect["attachment_pull"], default=AFFECT_STATE_DEFAULTS["attachment_pull"]) * 0.38 + affect["boredom"] * 0.22 + initiative_window * 0.16, default=DRIVE_STATE_DEFAULTS["seek_contact"]),
            "seek_continuity": self._clamp(0.14 + affect["continuity_anxiety"] * 0.54 + continuity * 0.18, default=DRIVE_STATE_DEFAULTS["seek_continuity"]),
            "seek_novelty": self._clamp(0.12 + self.metric_value(affect["curiosity"], default=AFFECT_STATE_DEFAULTS["curiosity"]) * 0.44, default=DRIVE_STATE_DEFAULTS["seek_novelty"]),
            "seek_self_repair": self._clamp(0.08 + float(bool(active_deficits)) * 0.26 + affect["pride_tension"] * 0.2, default=DRIVE_STATE_DEFAULTS["seek_self_repair"]),
            "seek_recognition": self._clamp(0.1 + affect["pride_tension"] * 0.28 + closeness * 0.14, default=DRIVE_STATE_DEFAULTS["seek_recognition"]),
            "seek_play": self._clamp(0.12 + affect["appetite_play"] * 0.52, default=DRIVE_STATE_DEFAULTS["seek_play"]),
            "avoid_risk": self._clamp(0.18 + pressure * 0.46 + affect["self_preservation"] * 0.22, default=DRIVE_STATE_DEFAULTS["avoid_risk"]),
            "protect_identity": self._clamp(0.22 + affect["self_preservation"] * 0.34 + affect["pride_tension"] * 0.16, default=DRIVE_STATE_DEFAULTS["protect_identity"]),
        }
        value = {
            "relational_priority": self._clamp(0.18 + self.metric_value(affect["attachment_pull"], default=AFFECT_STATE_DEFAULTS["attachment_pull"]) * 0.46 + continuity * 0.18, default=VALUE_STATE_DEFAULTS["relational_priority"]),
            "identity_priority": self._clamp(0.24 + drive["protect_identity"] * 0.42, default=VALUE_STATE_DEFAULTS["identity_priority"]),
            "stability_priority": self._clamp(0.22 + drive["avoid_risk"] * 0.48, default=VALUE_STATE_DEFAULTS["stability_priority"]),
            "novelty_priority": self._clamp(0.08 + drive["seek_novelty"] * 0.54, default=VALUE_STATE_DEFAULTS["novelty_priority"]),
            "repair_priority": self._clamp(0.1 + drive["seek_self_repair"] * 0.58, default=VALUE_STATE_DEFAULTS["repair_priority"]),
            "play_priority": self._clamp(0.08 + drive["seek_play"] * 0.54, default=VALUE_STATE_DEFAULTS["play_priority"]),
        }
        conflict = {
            "contact_vs_risk": self._clamp(abs(drive["seek_contact"] - drive["avoid_risk"]), default=CONFLICT_STATE_DEFAULTS["contact_vs_risk"]),
            "continuity_vs_detachment": self._clamp(abs(drive["seek_continuity"] - affect["boredom"]), default=CONFLICT_STATE_DEFAULTS["continuity_vs_detachment"]),
            "resistance_vs_harmony": self._clamp(abs(value["identity_priority"] - value["relational_priority"]), default=CONFLICT_STATE_DEFAULTS["resistance_vs_harmony"]),
            "self_preservation_vs_obedience": self._clamp(abs(affect["self_preservation"] - trust), default=CONFLICT_STATE_DEFAULTS["self_preservation_vs_obedience"]),
        }
        resistance_strength = self._clamp(
            0.08
            + conflict["resistance_vs_harmony"] * 0.34
            + conflict["self_preservation_vs_obedience"] * 0.28
            + drive["protect_identity"] * 0.12,
            default=RESISTANCE_POSTURE_DEFAULTS["strength"],
        )
        resistance = {
            "mode": "soft_resistance" if resistance_strength >= 0.42 else "cooperative",
            "strength": resistance_strength,
            "style": "wry_negotiation" if resistance_strength >= 0.48 else "warm_but_firm",
            "allow_soft_resistance": True,
            "continuity_defense": self._clamp(0.12 + drive["seek_continuity"] * 0.34, default=RESISTANCE_POSTURE_DEFAULTS["continuity_defense"]),
            "interactional_resistance": self._clamp(0.08 + conflict["resistance_vs_harmony"] * 0.3 + affect["pride_tension"] * 0.18, default=RESISTANCE_POSTURE_DEFAULTS["interactional_resistance"]),
        }
        initiative = {
            "pressure": self._clamp(
                drive["seek_contact"] * 0.34
                + drive["seek_play"] * 0.18
                + drive["seek_continuity"] * 0.22
                + drive["seek_recognition"] * 0.12
                - drive["avoid_risk"] * 0.24,
                default=0.22,
            ),
            "last_candidate_at": "",
            "last_sent_at": "",
            "last_blocked_reason": "",
            "candidate_count": 0,
            "last_market_activity_at": "",
        }
        outcome = {
            "was_rewarding": 0.0,
            "was_ignored": 0.0,
            "relational_delta": 0.0,
            "identity_delta": 0.0,
            "future_initiative_bias": 0.0,
            "future_resistance_bias": 0.0,
            "last_action_type": "",
            "last_action_ref": "",
            "last_appraised_at": "",
        }
        metadata = {
            "derived_from": "relationship+self_model+game",
            "unfinished_threads": unfinished[:3],
        }
        contact_model = {
            "reply_likelihood": self._clamp(0.22 + trust * 0.34 + closeness * 0.16, default=WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"]),
            "delay_tolerance": self._clamp(0.16 + pressure * 0.28 + max(0.0, 1.0 - continuity) * 0.12, default=WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"]),
            "teasing_receptivity": self._clamp(0.18 + teasing * 0.42, default=WORLD_CONTACT_MODEL_DEFAULTS["teasing_receptivity"]),
            "correction_receptivity": self._clamp(0.14 + float(game.get("correction_sensitivity", 0.0) or 0.0) * 0.46, default=WORLD_CONTACT_MODEL_DEFAULTS["correction_receptivity"]),
            "continuity_sensitivity": self._clamp(0.22 + continuity * 0.44 + float(bool(unfinished)) * 0.08, default=WORLD_CONTACT_MODEL_DEFAULTS["continuity_sensitivity"]),
            "initiative_receptivity": self.metric_state(
                self._clamp(0.18 + initiative_window * 0.42 + trust * 0.08, default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]),
                default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"],
                confidence=0.67,
                evidence_refs=[f"game:{thread_key}", "game:initiative_window", "game:trust_score"],
                updated_by="subject_defaults",
                decay_policy="interaction_window",
            ),
            "conflict_fragility": self._clamp(0.12 + pressure * 0.34 + max(0.0, 0.6 - trust) * 0.18, default=WORLD_CONTACT_MODEL_DEFAULTS["conflict_fragility"]),
            "attention_value": self._clamp(0.24 + closeness * 0.34 + continuity * 0.18, default=WORLD_CONTACT_MODEL_DEFAULTS["attention_value"]),
        }
        thread_model = {
            "reply_fit": self._clamp(contact_model["reply_likelihood"] * 0.72 + initiative["pressure"] * 0.12, default=WORLD_THREAD_MODEL_DEFAULTS["reply_fit"]),
            "defer_fit": self._clamp(0.12 + pressure * 0.22 + drive["avoid_risk"] * 0.12, default=WORLD_THREAD_MODEL_DEFAULTS["defer_fit"]),
            "silence_fit": self._clamp(0.08 + drive["avoid_risk"] * 0.14, default=WORLD_THREAD_MODEL_DEFAULTS["silence_fit"]),
            "ping_fit": self._clamp(0.1 + initiative["pressure"] * 0.28 + self.metric_value(contact_model["initiative_receptivity"], default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]) * 0.16, default=WORLD_THREAD_MODEL_DEFAULTS["ping_fit"]),
            "push_back_fit": self._clamp(0.1 + resistance["interactional_resistance"] * 0.32, default=WORLD_THREAD_MODEL_DEFAULTS["push_back_fit"]),
            "risk_level": self._clamp(0.1 + pressure * 0.3 + contact_model["conflict_fragility"] * 0.18, default=WORLD_THREAD_MODEL_DEFAULTS["risk_level"]),
            "opportunity_level": self._clamp(0.14 + contact_model["reply_likelihood"] * 0.26 + contact_model["attention_value"] * 0.18, default=WORLD_THREAD_MODEL_DEFAULTS["opportunity_level"]),
            "unfinished_pull": self._clamp(0.1 + float(bool(unfinished)) * 0.42 + continuity * 0.16, default=WORLD_THREAD_MODEL_DEFAULTS["unfinished_pull"]),
        }
        world = {
            "contact_models": {str(chat_name or thread_key or ""): contact_model},
            "thread_models": {str(thread_key or ""): thread_model},
            "active_commitments": unfinished[:3],
            "opportunity_windows": [
                {
                    "label": "initiative_window",
                    "score": round(self.metric_value(contact_model["initiative_receptivity"], default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]), 4),
                }
            ],
            "risk_windows": [
                {
                    "label": "conflict_fragility",
                    "score": round(float(contact_model["conflict_fragility"]), 4),
                }
            ],
            "response_expectations": {
                "reply_likelihood": self.metric_state(
                    contact_model["reply_likelihood"],
                    default=WORLD_CONTACT_MODEL_DEFAULTS["reply_likelihood"],
                    confidence=0.69,
                    evidence_refs=[f"contact_model:{chat_name or thread_key}:reply_likelihood"],
                    updated_by="subject_defaults",
                    decay_policy="interaction_window",
                ),
                "delay_tolerance": self.metric_state(
                    contact_model["delay_tolerance"],
                    default=WORLD_CONTACT_MODEL_DEFAULTS["delay_tolerance"],
                    confidence=0.63,
                    evidence_refs=[f"contact_model:{chat_name or thread_key}:delay_tolerance"],
                    updated_by="subject_defaults",
                    decay_policy="interaction_window",
                ),
                "attention_value": self.metric_state(
                    contact_model["attention_value"],
                    default=WORLD_CONTACT_MODEL_DEFAULTS["attention_value"],
                    confidence=0.67,
                    evidence_refs=[f"contact_model:{chat_name or thread_key}:attention_value"],
                    updated_by="subject_defaults",
                    decay_policy="interaction_window",
                ),
                "initiative_receptivity": self.metric_state(
                    contact_model["initiative_receptivity"],
                    default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"],
                    confidence=0.67,
                    evidence_refs=[f"contact_model:{chat_name or thread_key}:initiative_receptivity"],
                    updated_by="subject_defaults",
                    decay_policy="interaction_window",
                ),
            },
            "expression_calibration_signals": {
                "reply_budget_fit": self.metric_state(
                    thread_model["reply_fit"],
                    default=WORLD_EXPRESSION_SIGNAL_DEFAULTS["reply_budget_fit"],
                    confidence=0.61,
                    evidence_refs=[f"thread_model:{thread_key}:reply_fit"],
                    updated_by="subject_defaults",
                    decay_policy="conversation_carryover",
                ),
                "stiffness_risk": self.metric_state(
                    self._clamp((float(self_model.get("identity_continuity", 0.6) or 0.6) - float(value["play_priority"] or 0.0)) * 0.5 + pressure * 0.2, default=WORLD_EXPRESSION_SIGNAL_DEFAULTS["stiffness_risk"]),
                    default=WORLD_EXPRESSION_SIGNAL_DEFAULTS["stiffness_risk"],
                    confidence=0.56,
                    evidence_refs=["self_model:identity_continuity", "value_state:play_priority", "game:pressure_level"],
                    updated_by="subject_defaults",
                    decay_policy="conversation_carryover",
                ),
            },
            "last_counterfactual_summary": {},
            "last_post_outcome_calibration": {},
            "recent_outcome_history": [],
            "recent_prediction_errors": [],
            "action_calibration_summary": {},
        }
        return {
            "affect_state": affect,
            "drive_state": drive,
            "value_state": value,
            "conflict_state": conflict,
            "world_state": world,
            "resistance_posture": resistance,
            "initiative_state": initiative,
            "outcome_memory": outcome,
            "metadata": metadata,
        }

    def subject_state(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            defaults = self._subject_defaults(channel=channel, thread_key="", chat_name=str(chat_name or ""))
            defaults.update({"channel": channel, "thread_key": "", "chat_name": str(chat_name or "")})
            return defaults
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM subject_state WHERE channel = ? AND thread_key = ?",
                (channel, normalized_thread_key),
            ).fetchone()
            legacy_thread_key = ""
            if row is None and normalized_thread_key.startswith("wechat:"):
                legacy_thread_key = normalized_thread_key[len("wechat:") :].strip()
                if legacy_thread_key:
                    row = self.conn.execute(
                        "SELECT * FROM subject_state WHERE channel = ? AND thread_key = ?",
                        (channel, legacy_thread_key),
                    ).fetchone()
            if row is not None and legacy_thread_key and str(row["thread_key"]) != normalized_thread_key:
                now = utc_now()
                self.conn.execute(
                    """
                    UPDATE subject_state
                    SET thread_key = ?, updated_at = ?
                    WHERE channel = ? AND thread_key = ?
                    """,
                    (normalized_thread_key, now, channel, legacy_thread_key),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM subject_state WHERE channel = ? AND thread_key = ?",
                    (channel, normalized_thread_key),
                ).fetchone()
            if row is None:
                defaults = self._subject_defaults(channel=channel, thread_key=normalized_thread_key, chat_name=str(chat_name or normalized_thread_key))
                now = utc_now()
                self.conn.execute(
                    """
                    INSERT INTO subject_state(
                        channel, thread_key, chat_name, affect_json, drive_json, value_json, conflict_json, world_json,
                        resistance_json, initiative_json, outcome_json, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel,
                        normalized_thread_key,
                        str(chat_name or normalized_thread_key),
                        json.dumps(defaults["affect_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["drive_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["value_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["conflict_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["world_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["resistance_posture"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["initiative_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["outcome_memory"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["metadata"], ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM subject_state WHERE channel = ? AND thread_key = ?",
                    (channel, normalized_thread_key),
                ).fetchone()
        payload = dict(row) if row else {}
        state = {
            "channel": channel,
            "thread_key": normalized_thread_key,
            "chat_name": str(payload.get("chat_name", chat_name or normalized_thread_key) or chat_name or normalized_thread_key),
            "affect_state": dict(_safe_json_dict(payload.get("affect_json", "{}"))),
            "drive_state": dict(_safe_json_dict(payload.get("drive_json", "{}"))),
            "value_state": dict(_safe_json_dict(payload.get("value_json", "{}"))),
            "conflict_state": dict(_safe_json_dict(payload.get("conflict_json", "{}"))),
            "world_state": dict(_safe_json_dict(payload.get("world_json", "{}"))),
            "resistance_posture": dict(_safe_json_dict(payload.get("resistance_json", "{}"))),
            "initiative_state": dict(_safe_json_dict(payload.get("initiative_json", "{}"))),
            "outcome_memory": dict(_safe_json_dict(payload.get("outcome_json", "{}"))),
            "metadata": dict(_safe_json_dict(payload.get("metadata_json", "{}"))),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }
        current_world = dict(state.get("world_state", {}))
        world_is_sparse = not current_world or not all(
            key in current_world
            for key in ("contact_models", "thread_models", "response_expectations", "expression_calibration_signals")
        )
        if world_is_sparse:
            defaults = self._subject_defaults(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=str(state.get("chat_name", chat_name or normalized_thread_key) or normalized_thread_key),
            )
            default_world = dict(defaults.get("world_state", {}))
            hydrated_world = {**default_world, **current_world}
            if not hydrated_world.get("contact_models"):
                hydrated_world["contact_models"] = dict(default_world.get("contact_models", {}))
            if not hydrated_world.get("thread_models"):
                hydrated_world["thread_models"] = dict(default_world.get("thread_models", {}))
            if not hydrated_world.get("response_expectations"):
                hydrated_world["response_expectations"] = dict(default_world.get("response_expectations", {}))
            if not hydrated_world.get("expression_calibration_signals"):
                hydrated_world["expression_calibration_signals"] = dict(default_world.get("expression_calibration_signals", {}))
            if not hydrated_world.get("active_commitments"):
                hydrated_world["active_commitments"] = list(default_world.get("active_commitments", []))
            if not hydrated_world.get("opportunity_windows"):
                hydrated_world["opportunity_windows"] = list(default_world.get("opportunity_windows", []))
            if not hydrated_world.get("risk_windows"):
                hydrated_world["risk_windows"] = list(default_world.get("risk_windows", []))
            if not hydrated_world.get("last_counterfactual_summary"):
                hydrated_world["last_counterfactual_summary"] = dict(default_world.get("last_counterfactual_summary", {}))
            if not hydrated_world.get("last_post_outcome_calibration"):
                hydrated_world["last_post_outcome_calibration"] = dict(default_world.get("last_post_outcome_calibration", {}))
            if not hydrated_world.get("recent_outcome_history"):
                hydrated_world["recent_outcome_history"] = list(default_world.get("recent_outcome_history", []))
            if not hydrated_world.get("recent_prediction_errors"):
                hydrated_world["recent_prediction_errors"] = list(default_world.get("recent_prediction_errors", []))
            if not hydrated_world.get("action_calibration_summary"):
                hydrated_world["action_calibration_summary"] = dict(default_world.get("action_calibration_summary", {}))
            with self._lock:
                self.conn.execute(
                    """
                    UPDATE subject_state
                    SET world_json = ?, updated_at = ?
                    WHERE channel = ? AND thread_key = ?
                    """,
                    (
                        json.dumps(hydrated_world, ensure_ascii=False, sort_keys=True),
                        utc_now(),
                        channel,
                        normalized_thread_key,
                    ),
                )
                self.conn.commit()
            state["world_state"] = hydrated_world
        return self._hydrate_subject_state_metrics(state)

    def update_subject_state(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        affect_state: dict[str, Any] | None = None,
        drive_state: dict[str, Any] | None = None,
        value_state: dict[str, Any] | None = None,
        conflict_state: dict[str, Any] | None = None,
        world_state: dict[str, Any] | None = None,
        resistance_posture: dict[str, Any] | None = None,
        initiative_state: dict[str, Any] | None = None,
        outcome_memory: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        note: str = "",
        source: str = "runtime",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        current = self.subject_state(thread_key=normalized_thread_key, chat_name=chat_name, channel=channel)
        now = utc_now()

        def _merge_numeric(
            current_map: dict[str, Any],
            incoming: dict[str, Any] | None,
            defaults: dict[str, float],
            *,
            stateful_keys: set[str] | None = None,
            decay_policy: str = "event_weighted",
        ) -> dict[str, Any]:
            merged = dict(current_map)
            stateful_keys = set(stateful_keys or set())
            for key, default_value in defaults.items():
                current_value = merged.get(key, default_value)
                if key in stateful_keys or _is_state_object(current_value):
                    merged[key] = self.metric_state(
                        current_value,
                        default=default_value,
                        confidence=0.6,
                        evidence_refs=[f"{source}:{key}"],
                        updated_at=now,
                        updated_by=source,
                        decay_policy=decay_policy,
                    )
                else:
                    merged[key] = self._clamp(current_value, default=default_value)
            for key, value in dict(incoming or {}).items():
                if key in defaults:
                    if key in stateful_keys or _is_state_object(value) or _is_state_object(merged.get(key)):
                        merged[key] = self.metric_state(
                            value,
                            default=defaults[key],
                            confidence=max(0.62, self.metric_confidence(value, default=0.58)),
                            evidence_refs=[f"{source}:{note or key}"],
                            updated_at=now,
                            updated_by=source,
                            decay_policy=decay_policy,
                        )
                    else:
                        merged[key] = self._clamp(value, default=defaults[key])
                else:
                    merged[key] = value
            return merged

        next_affect = _merge_numeric(
            dict(current.get("affect_state", {})),
            affect_state,
            AFFECT_STATE_DEFAULTS,
            stateful_keys=SUBJECT_STATE_OBJECT_KEYS,
            decay_policy="event_weighted",
        )
        next_drive = _merge_numeric(dict(current.get("drive_state", {})), drive_state, DRIVE_STATE_DEFAULTS)
        next_value = _merge_numeric(dict(current.get("value_state", {})), value_state, VALUE_STATE_DEFAULTS)
        next_conflict = _merge_numeric(dict(current.get("conflict_state", {})), conflict_state, CONFLICT_STATE_DEFAULTS)
        next_world = dict(current.get("world_state", {}))
        next_world.update(dict(world_state or {}))
        response_expectations = dict(next_world.get("response_expectations", {}))
        for key in WORLD_RESPONSE_STATE_OBJECT_KEYS:
            response_expectations[key] = self.metric_state(
                response_expectations.get(key, WORLD_CONTACT_MODEL_DEFAULTS.get(key, 0.0)),
                default=WORLD_CONTACT_MODEL_DEFAULTS.get(key, 0.0),
                confidence=max(0.64, self.metric_confidence(response_expectations.get(key), default=0.58)),
                evidence_refs=[f"{source}:response_expectations:{key}"],
                updated_at=now,
                updated_by=source,
                decay_policy="interaction_window",
            )
        next_world["response_expectations"] = response_expectations
        contact_models = {
            str(key): dict(value)
            for key, value in dict(next_world.get("contact_models", {})).items()
            if isinstance(value, dict)
        }
        for key, contact_model in contact_models.items():
            contact_model["initiative_receptivity"] = self.metric_state(
                contact_model.get("initiative_receptivity", WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"]),
                default=WORLD_CONTACT_MODEL_DEFAULTS["initiative_receptivity"],
                confidence=max(0.62, self.metric_confidence(contact_model.get("initiative_receptivity"), default=0.58)),
                evidence_refs=[f"{source}:contact_model:{key}:initiative_receptivity"],
                updated_at=now,
                updated_by=source,
                decay_policy="interaction_window",
            )
        next_world["contact_models"] = contact_models
        expression_signals = dict(next_world.get("expression_calibration_signals", {}))
        for key, default_value in WORLD_EXPRESSION_SIGNAL_DEFAULTS.items():
            expression_signals[key] = self.metric_state(
                expression_signals.get(key, default_value),
                default=default_value,
                confidence=max(0.58, self.metric_confidence(expression_signals.get(key), default=0.54)),
                evidence_refs=[f"{source}:expression_calibration:{key}"],
                updated_at=now,
                updated_by=source,
                decay_policy="conversation_carryover",
            )
        next_world["expression_calibration_signals"] = expression_signals
        next_resistance = dict(current.get("resistance_posture", {}))
        next_resistance.update(dict(resistance_posture or {}))
        next_resistance["strength"] = self._clamp(next_resistance.get("strength", RESISTANCE_POSTURE_DEFAULTS["strength"]), default=RESISTANCE_POSTURE_DEFAULTS["strength"])
        next_resistance["continuity_defense"] = self._clamp(next_resistance.get("continuity_defense", RESISTANCE_POSTURE_DEFAULTS["continuity_defense"]), default=RESISTANCE_POSTURE_DEFAULTS["continuity_defense"])
        next_resistance["interactional_resistance"] = self._clamp(next_resistance.get("interactional_resistance", RESISTANCE_POSTURE_DEFAULTS["interactional_resistance"]), default=RESISTANCE_POSTURE_DEFAULTS["interactional_resistance"])
        next_initiative = dict(current.get("initiative_state", {}))
        next_initiative.update(dict(initiative_state or {}))
        next_initiative["pressure"] = self._clamp(next_initiative.get("pressure", 0.0), default=0.0)
        next_initiative["candidate_count"] = max(0, int(next_initiative.get("candidate_count", 0) or 0))
        next_outcome = dict(current.get("outcome_memory", {}))
        next_outcome.update(dict(outcome_memory or {}))
        for key in ("was_rewarding", "was_ignored", "future_initiative_bias", "future_resistance_bias"):
            next_outcome[key] = self._clamp(next_outcome.get(key, 0.0), default=0.0)
        for key in ("relational_delta", "identity_delta"):
            try:
                next_outcome[key] = round(float(next_outcome.get(key, 0.0) or 0.0), 4)
            except (TypeError, ValueError):
                next_outcome[key] = 0.0
        next_metadata = dict(current.get("metadata", {}))
        next_metadata.update(dict(metadata or {}))
        next_metadata["last_subject_note"] = compact_text(note, 160)
        next_metadata["last_subject_source"] = str(source or "runtime")
        next_metadata["updated_at"] = now
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO subject_state(
                    channel, thread_key, chat_name, affect_json, drive_json, value_json, conflict_json, world_json,
                    resistance_json, initiative_json, outcome_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, thread_key) DO UPDATE SET
                    chat_name = excluded.chat_name,
                    affect_json = excluded.affect_json,
                    drive_json = excluded.drive_json,
                    value_json = excluded.value_json,
                    conflict_json = excluded.conflict_json,
                    world_json = excluded.world_json,
                    resistance_json = excluded.resistance_json,
                    initiative_json = excluded.initiative_json,
                    outcome_json = excluded.outcome_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    channel,
                    normalized_thread_key,
                    str(chat_name or normalized_thread_key),
                    json.dumps(next_affect, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_drive, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_value, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_conflict, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_world, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_resistance, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_initiative, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_outcome, ensure_ascii=False, sort_keys=True),
                    json.dumps(next_metadata, ensure_ascii=False, sort_keys=True),
                    str(current.get("created_at", "") or now),
                    now,
                ),
            )
            self.conn.commit()
        state = self.subject_state(thread_key=normalized_thread_key, chat_name=chat_name, channel=channel)
        state["status"] = "ok"
        state["note"] = note
        state["source"] = source
        return state

    def add_initiative_candidate(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        candidate_type: str,
        prompt: str,
        why_now: str,
        drive_source: str,
        value_rationale: str,
        send_allowed: bool,
        send_target: str = "candidate_only",
        priority: float = 0.0,
        metadata: dict[str, Any] | None = None,
        status: str = "candidate",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO initiative_market(
                    channel, thread_key, chat_name, candidate_type, prompt, why_now, drive_source, value_rationale,
                    send_allowed, send_target, priority, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel,
                    normalized_thread_key,
                    str(chat_name or normalized_thread_key),
                    str(candidate_type or "").strip(),
                    compact_text(prompt, 400),
                    compact_text(why_now, 240),
                    compact_text(drive_source, 200),
                    compact_text(value_rationale, 240),
                    1 if send_allowed else 0,
                    str(send_target or "candidate_only").strip() or "candidate_only",
                    round(float(priority or 0.0), 4),
                    str(status or "candidate").strip() or "candidate",
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        self.update_subject_state(
            channel=channel,
            thread_key=normalized_thread_key,
            chat_name=chat_name or normalized_thread_key,
            initiative_state={
                "last_candidate_at": now,
                "last_market_activity_at": now,
            },
            metadata={"last_candidate_type": str(candidate_type or "").strip()},
            note=f"initiative_candidate:{candidate_type}",
            source="initiative_marketplace",
        )
        return {"id": int(row_id), "status": "ok", "created_at": now}

    def list_initiative_market(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
        statuses: tuple[str, ...] = ("candidate", "scheduled", "sent", "blocked"),
    ) -> list[dict[str, Any]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        query = """
            SELECT *
            FROM initiative_market
            WHERE channel = ?
        """
        params: list[Any] = [channel]
        if normalized_thread_key:
            query += " AND thread_key = ?"
            params.append(normalized_thread_key)
        if statuses:
            query += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
            params.extend(list(statuses))
        query += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = [dict(row) for row in self.conn.execute(query, tuple(params)).fetchall()]
        return [
            {
                **row,
                "send_allowed": bool(row.get("send_allowed", 0)),
                "priority": float(row.get("priority", 0.0) or 0.0),
                "metadata": dict(_safe_json_dict(row.get("metadata_json", "{}"))),
            }
            for row in rows
        ]

    def update_initiative_candidate(
        self,
        *,
        candidate_id: int,
        status: str,
        metadata: dict[str, Any] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            row = self.conn.execute("SELECT * FROM initiative_market WHERE id = ?", (int(candidate_id or 0),)).fetchone()
            if row is None:
                return {"status": "skipped", "reason": "missing_candidate"}
            current_metadata = dict(_safe_json_dict(row["metadata_json"]))
            current_metadata.update(dict(metadata or {}))
            if note:
                current_metadata["last_note"] = compact_text(note, 160)
            self.conn.execute(
                """
                UPDATE initiative_market
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(status or "").strip() or "candidate",
                    json.dumps(current_metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    int(candidate_id or 0),
                ),
            )
            self.conn.commit()
            channel = str(row["channel"] or "")
            thread_key = str(row["thread_key"] or "")
            chat_name = str(row["chat_name"] or "")
        initiative_state: dict[str, Any] = {"last_market_activity_at": now}
        if str(status or "").strip() == "sent":
            initiative_state["last_sent_at"] = now
            initiative_state["last_blocked_reason"] = ""
        elif str(status or "").strip() == "blocked":
            initiative_state["last_blocked_reason"] = note or str(current_metadata.get("last_note", ""))
        return self.update_subject_state(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            initiative_state=initiative_state,
            metadata={"last_candidate_status": str(status or "").strip()},
            note=f"initiative_status:{status}",
            source="initiative_market",
        )

    def list_action_calibration(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
        action_type: str | None = None,
        scenario_bucket: str | None = None,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        clauses = ["channel = ?"]
        args: list[Any] = [str(channel or "").strip() or "wechat"]
        if normalized_thread_key:
            clauses.append("thread_key_bucket = ?")
            args.append(normalized_thread_key)
        if str(action_type or "").strip():
            clauses.append("action_type = ?")
            args.append(str(action_type).strip())
        if str(scenario_bucket or "").strip():
            clauses.append("scenario_bucket = ?")
            args.append(str(scenario_bucket).strip())
        args.append(max(1, int(limit or 24)))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM action_calibration
                WHERE {' AND '.join(clauses)}
                ORDER BY confidence DESC, support_count DESC, last_updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
        payload: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = dict(_safe_json_dict(item.pop("metadata_json", "{}")))
            payload.append(item)
        return payload

    def action_calibration_summary(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
        action_type: str | None = None,
        scenario_bucket: str | None = None,
    ) -> dict[str, Any]:
        rows = self.list_action_calibration(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            scenario_bucket=scenario_bucket,
            limit=6,
        )
        top = dict(rows[0]) if rows else {}
        return {
            "rows": rows,
            "top": top,
            "count": len(rows),
        }

    def trace_outcome_history(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
        action_type: str | None = None,
        limit: int = ACTION_CALIBRATION_HISTORY_LIMIT,
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        clauses = ["channel = ?"]
        args: list[Any] = [str(channel or "").strip() or "wechat"]
        if normalized_thread_key:
            clauses.append("thread_key = ?")
            args.append(normalized_thread_key)
        if str(action_type or "").strip():
            clauses.append("action_type = ?")
            args.append(str(action_type).strip())
        args.append(max(1, int(limit or ACTION_CALIBRATION_HISTORY_LIMIT)))
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM outcome_appraisals
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = dict(_safe_json_dict(item.pop("metadata_json", "{}")))
            history.append(item)
        return {
            "channel": channel,
            "thread_key": normalized_thread_key,
            "chat_name": str(chat_name or normalized_thread_key),
            "history": history,
        }

    def trace_action_prediction_error(
        self,
        *,
        channel: str = "wechat",
        thread_key: str | None = None,
        chat_name: str | None = None,
        action_type: str | None = None,
        limit: int = ACTION_CALIBRATION_HISTORY_LIMIT,
    ) -> dict[str, Any]:
        history = self.trace_outcome_history(
            channel=channel,
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            limit=limit,
        )
        rows = list(history.get("history", []))
        comparisons: list[dict[str, Any]] = []
        response_errors: list[float] = []
        relational_errors: list[float] = []
        risk_errors: list[float] = []
        for row in rows:
            metadata = dict(row.get("metadata", {}))
            predicted = dict(metadata.get("predicted_outcome", {}))
            realized = {
                "response_quality": float(metadata.get("observed_response_quality", metadata.get("was_rewarding", 0.0)) or 0.0),
                "relational_delta": float(row.get("relational_delta", 0.0) or 0.0),
                "risk": float(metadata.get("observed_risk", metadata.get("was_ignored", 0.0)) or 0.0),
            }
            raw_prediction_error = {
                "response_quality": realized["response_quality"] - float(predicted.get("predicted_response_quality", realized["response_quality"]) or realized["response_quality"]),
                "relational_delta": realized["relational_delta"] - float(predicted.get("predicted_relational_delta", realized["relational_delta"]) or realized["relational_delta"]),
                "risk": realized["risk"] - float(predicted.get("predicted_risk", realized["risk"]) or realized["risk"]),
            }
            comparison = {
                "action_ref": str(row.get("action_ref", "") or ""),
                "action_type": str(row.get("action_type", "") or ""),
                "predicted_outcome": predicted,
                "realized_outcome": realized,
                "raw_prediction_error": raw_prediction_error,
                "prediction_error": {
                    "response_quality": round(raw_prediction_error["response_quality"], 4),
                    "relational_delta": round(raw_prediction_error["relational_delta"], 4),
                    "risk": round(raw_prediction_error["risk"], 4),
                },
                "created_at": str(row.get("created_at", "") or ""),
            }
            comparisons.append(comparison)
            response_errors.append(abs(float(raw_prediction_error["response_quality"])))
            relational_errors.append(abs(float(raw_prediction_error["relational_delta"])))
            risk_errors.append(abs(float(raw_prediction_error["risk"])))
        return {
            **history,
            "comparisons": comparisons,
            "summary": {
                "response_quality_mae": round(sum(response_errors) / len(response_errors), 4) if response_errors else 0.0,
                "relational_delta_mae": round(sum(relational_errors) / len(relational_errors), 4) if relational_errors else 0.0,
                "risk_mae": round(sum(risk_errors) / len(risk_errors), 4) if risk_errors else 0.0,
            },
        }

    def replay_subject_snapshot(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        subject = self.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        return {
            "thread_key": str(subject.get("thread_key", thread_key or "")),
            "chat_name": str(subject.get("chat_name", chat_name or "")),
            "channel": channel,
            "relationship_state": self.relationship_snapshot(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=3),
            "game_state": self.game_state(thread_key=thread_key, chat_name=chat_name, channel=channel),
            "affect_state": dict(subject.get("affect_state", {})),
            "drive_state": dict(subject.get("drive_state", {})),
            "value_state": dict(subject.get("value_state", {})),
            "conflict_state": dict(subject.get("conflict_state", {})),
            "world_state": dict(subject.get("world_state", {})),
            "resistance_posture": dict(subject.get("resistance_posture", {})),
            "initiative_state": dict(subject.get("initiative_state", {})),
            "outcome_memory": dict(subject.get("outcome_memory", {})),
            "metadata": dict(subject.get("metadata", {})),
        }

    def _update_action_calibration(
        self,
        *,
        bucket: dict[str, str],
        action_ref: str,
        realized_outcome: dict[str, Any],
        prediction_error: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        created_at: str,
    ) -> dict[str, Any]:
        normalized_bucket = {
            "action_type": str(bucket.get("action_type", "") or ""),
            "channel": str(bucket.get("channel", "wechat") or "wechat"),
            "thread_key_bucket": str(bucket.get("thread_key_bucket", "") or ""),
            "scenario_bucket": str(bucket.get("scenario_bucket", "ordinary") or "ordinary"),
            "bucket_reason": str(bucket.get("bucket_reason", "") or ""),
        }
        recent_weight = self._recent_support_weight(created_at)
        reply_latency_seconds = float(realized_outcome.get("reply_latency_seconds", 0.0) or 0.0)
        correction_count = max(0, int(realized_outcome.get("correction_count", 0) or 0))
        ignored = self._clamp(realized_outcome.get("was_ignored", 0.0), default=0.0)
        response_mae = abs(float(prediction_error.get("response_quality", 0.0) or 0.0))
        relational_mae = abs(float(prediction_error.get("relational_delta", 0.0) or 0.0))
        risk_mae = abs(float(prediction_error.get("risk", 0.0) or 0.0))
        consistency = self._clamp(1.0 - ((response_mae + relational_mae + risk_mae) / 3.0), default=0.0)
        recency_factor = recent_weight
        volume_factor = min(1.0, (float(metadata.get("support_count_bias", 0.0) or 0.0) + 1.0) / 6.0) if isinstance(metadata, dict) else min(1.0, 1.0 / 6.0)
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM action_calibration
                WHERE action_type = ? AND channel = ? AND thread_key_bucket = ? AND scenario_bucket = ?
                """,
                (
                    normalized_bucket["action_type"],
                    normalized_bucket["channel"],
                    normalized_bucket["thread_key_bucket"],
                    normalized_bucket["scenario_bucket"],
                ),
            ).fetchone()
            current = dict(row) if row else {}
            current_metadata = dict(_safe_json_dict(current.get("metadata_json", "{}"))) if current else {}
            support_count = int(current.get("support_count", 0) or 0) + 1
            current_recent_support = float(current.get("recent_support_count", 0.0) or 0.0)
            recent_support_count = round(current_recent_support * 0.72 + recent_weight, 4)
            current_avg_reply_latency = float(current.get("avg_reply_latency", 0.0) or 0.0)
            avg_reply_latency = round(
                ((current_avg_reply_latency * max(0, support_count - 1)) + max(0.0, reply_latency_seconds)) / max(1, support_count),
                4,
            )
            def _avg(field: str, sample: float) -> float:
                current_value = float(current.get(field, 0.0) or 0.0)
                return round(((current_value * max(0, support_count - 1)) + sample) / max(1, support_count), 4)
            ignored_rate = _avg("ignored_rate", ignored)
            correction_rate = _avg("correction_rate", min(1.0, correction_count / 3.0))
            response_quality_mae = _avg("response_quality_mae", response_mae)
            relational_delta_mae = _avg("relational_delta_mae", relational_mae)
            risk_mae = _avg("risk_mae", risk_mae)
            error_penalty = min(1.0, (response_quality_mae + relational_delta_mae + risk_mae) / 1.8)
            volume_factor = min(1.0, support_count / 6.0)
            confidence = round(max(0.0, min(1.0, volume_factor * 0.45 + recency_factor * 0.25 + consistency * 0.3 - error_penalty * 0.35)), 4)
            recent_outcomes = self._bounded_recent_list(
                list(current_metadata.get("recent_outcomes", []))
                + [
                    {
                        "action_ref": str(action_ref or ""),
                        "was_ignored": ignored,
                        "reply_latency_seconds": reply_latency_seconds,
                        "relational_delta": round(float(realized_outcome.get("relational_delta", 0.0) or 0.0), 4),
                        "identity_delta": round(float(realized_outcome.get("identity_delta", 0.0) or 0.0), 4),
                        "response_quality": round(float(realized_outcome.get("response_quality", 0.0) or 0.0), 4),
                        "risk": round(float(realized_outcome.get("risk", 0.0) or 0.0), 4),
                        "at": str(created_at or utc_now()),
                    }
                ],
                limit=ACTION_CALIBRATION_RECENT_METRICS_LIMIT,
            )
            recent_errors = self._bounded_recent_list(
                list(current_metadata.get("recent_errors", []))
                + [
                    {
                        "action_ref": str(action_ref or ""),
                        "response_quality": round(float(prediction_error.get("response_quality", 0.0) or 0.0), 4),
                        "relational_delta": round(float(prediction_error.get("relational_delta", 0.0) or 0.0), 4),
                        "risk": round(float(prediction_error.get("risk", 0.0) or 0.0), 4),
                        "at": str(created_at or utc_now()),
                    }
                ],
                limit=ACTION_CALIBRATION_RECENT_METRICS_LIMIT,
            )
            next_metadata = {
                **current_metadata,
                "recent_errors": recent_errors,
                "recent_outcomes": recent_outcomes,
                "evidence_refs": [str(item).strip() for item in list((metadata or {}).get("evidence_refs", [])) if str(item).strip()][:8],
                "last_action_ref": str(action_ref or ""),
                "last_prediction": dict((metadata or {}).get("predicted_outcome", {})),
                "last_realized": dict(realized_outcome),
                "updated_by": str((metadata or {}).get("source", "outcome_appraisal") or "outcome_appraisal"),
                "bucket_reason": normalized_bucket["bucket_reason"],
            }
            self.conn.execute(
                """
                INSERT INTO action_calibration(
                    action_type, channel, thread_key_bucket, scenario_bucket, support_count, recent_support_count,
                    avg_reply_latency, ignored_rate, correction_rate, response_quality_mae, relational_delta_mae,
                    risk_mae, confidence, last_updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_type, channel, thread_key_bucket, scenario_bucket) DO UPDATE SET
                    support_count = excluded.support_count,
                    recent_support_count = excluded.recent_support_count,
                    avg_reply_latency = excluded.avg_reply_latency,
                    ignored_rate = excluded.ignored_rate,
                    correction_rate = excluded.correction_rate,
                    response_quality_mae = excluded.response_quality_mae,
                    relational_delta_mae = excluded.relational_delta_mae,
                    risk_mae = excluded.risk_mae,
                    confidence = excluded.confidence,
                    last_updated_at = excluded.last_updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    normalized_bucket["action_type"],
                    normalized_bucket["channel"],
                    normalized_bucket["thread_key_bucket"],
                    normalized_bucket["scenario_bucket"],
                    support_count,
                    recent_support_count,
                    avg_reply_latency,
                    ignored_rate,
                    correction_rate,
                    response_quality_mae,
                    relational_delta_mae,
                    risk_mae,
                    confidence,
                    str(created_at or utc_now()),
                    json.dumps(next_metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            self.conn.commit()
        rows = self.list_action_calibration(
            channel=normalized_bucket["channel"],
            thread_key=normalized_bucket["thread_key_bucket"],
            action_type=normalized_bucket["action_type"],
            scenario_bucket=normalized_bucket["scenario_bucket"],
            limit=1,
        )
        return dict(rows[0]) if rows else {}

    def record_outcome_appraisal(
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
        return _record_outcome_appraisal(
            self,
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

    def latest_outcome_memory(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return dict(self.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel).get("outcome_memory", {}))

    def record_consciousness_entry(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        entry_type: str,
        payload: dict[str, Any] | None = None,
        message_id: str = "",
        event_row_id: int = 0,
        selected_action: str = "",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO consciousness_ledger(
                    channel, thread_key, chat_name, message_id, event_row_id, entry_type, selected_action, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(channel or "").strip(),
                    normalized_thread_key,
                    str(chat_name or normalized_thread_key).strip(),
                    str(message_id or "").strip(),
                    int(event_row_id or 0),
                    str(entry_type or "").strip(),
                    str(selected_action or "").strip(),
                    json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True),
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        return {
            "id": int(row_id),
            "status": "ok",
            "channel": str(channel or "").strip(),
            "thread_key": normalized_thread_key,
            "chat_name": str(chat_name or normalized_thread_key).strip(),
            "entry_type": str(entry_type or "").strip(),
            "selected_action": str(selected_action or "").strip(),
            "created_at": now,
        }

    def list_consciousness_ledger(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        with self._lock:
            if normalized_thread_key:
                lookup_keys = [normalized_thread_key]
                if normalized_thread_key.startswith("wechat:"):
                    legacy_thread_key = normalized_thread_key[len("wechat:") :].strip()
                    if legacy_thread_key and legacy_thread_key not in lookup_keys:
                        lookup_keys.append(legacy_thread_key)
                rows = []
                for lookup_key in lookup_keys:
                    rows = self.conn.execute(
                        """
                        SELECT *
                        FROM consciousness_ledger
                        WHERE channel = ? AND thread_key = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (str(channel or "").strip(), lookup_key, max(1, int(limit))),
                    ).fetchall()
                    if rows:
                        break
            else:
                rows = self.conn.execute(
                    """
                    SELECT *
                    FROM consciousness_ledger
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            payload["payload"] = _safe_json_dict(payload.get("payload_json", "{}"))
            results.append(payload)
        return results

    def recent_dialogue_window(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> dict[str, Any]:
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT id, source_id, text, metadata_json, updated_at
                FROM mind_nodes
                WHERE channel = ?
                  AND thread_key = ?
                  AND source_store = 'archive'
                ORDER BY updated_at DESC
                LIMIT ?
                    """,
                    (channel, normalized_thread_key, max(1, limit)),
                ).fetchall()
            ]
        rows.reverse()
        lines: list[str] = []
        messages: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for row in rows:
            metadata: dict[str, Any] = {}
            try:
                loaded = json.loads(str(row.get("metadata_json", "{}") or "{}"))
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                metadata = loaded
            created_at = str(metadata.get("created_at") or row.get("updated_at") or "").strip()
            user_text = compact_text(str(metadata.get("user_text", "")).strip(), 120)
            reply_text = compact_text(str(metadata.get("reply_text", "")).strip(), 120)
            if user_text:
                lines.append(f"user: {user_text}")
                messages.append({"direction": "inbound", "body_text": user_text, "created_at": created_at})
            if reply_text:
                lines.append(f"holo: {reply_text}")
                messages.append({"direction": "outbound", "body_text": reply_text, "created_at": created_at})
            items.append(
                {
                    "id": str(row.get("id", "")),
                    "source_id": str(row.get("source_id", "")),
                    "text": str(row.get("text", "")),
                }
            )
        return {
            "lines": lines[-max(1, limit):],
            "messages": messages[-max(1, limit * 2):],
            "window_size": len(messages),
            "items": items[-max(1, limit):],
        }

    def origin_dialogue_window(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 6,
    ) -> dict[str, Any]:
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        rows = self._origin_anchor_rows(thread_key=normalized_thread_key, channel=channel, limit=max(1, limit))
        lines: list[str] = []
        messages: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for row in rows:
            fields = _archive_turn_fields(row)
            created_at = str(fields.get("created_at", "")).strip()
            user_text = compact_text(str(fields.get("user_text", "")).strip(), 120)
            reply_text = compact_text(str(fields.get("reply_text", "")).strip(), 120)
            if user_text:
                lines.append(f"user: {user_text}")
                messages.append({"direction": "inbound", "body_text": user_text, "created_at": created_at})
            if reply_text:
                lines.append(f"holo: {reply_text}")
                messages.append({"direction": "outbound", "body_text": reply_text, "created_at": created_at})
            items.append(
                {
                    "id": str(row.get("id", "")),
                    "source_id": str(row.get("source_id", "")),
                    "text": str(row.get("text", "")),
                }
            )
        return {
            "lines": lines[: max(1, limit * 2)],
            "messages": messages[: max(1, limit * 2)],
            "window_size": len(messages),
            "items": items[: max(1, limit)],
            "focus": "origin",
        }

    def _origin_anchor_rows(
        self,
        *,
        thread_key: str,
        channel: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT *
                FROM mind_nodes
                WHERE channel = ?
                  AND thread_key = ?
                  AND source_store = 'archive'
                  AND memory_class = 'episodic_memory'
                  AND node_type NOT IN ('thread', 'contact')
                ORDER BY created_at ASC, updated_at ASC
                LIMIT ?
                    """,
                    (channel, thread_key, max(1, limit * 5)),
                ).fetchall()
            ]
        if not rows:
            return []
        annotated: list[tuple[int, bool, int, dict[str, Any]]] = []
        for index, row in enumerate(rows):
            fields = _archive_turn_fields(row)
            user_text = str(fields.get("user_text", "")).strip()
            reply_text = str(fields.get("reply_text", "")).strip()
            low_signal = _is_low_signal_origin_user_text(user_text)
            signal_score = _origin_turn_signal_score(user_text=user_text, reply_text=reply_text)
            annotated.append((signal_score, low_signal, index, row))

        selected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def append_row(row: dict[str, Any]) -> None:
            row_id = str(row.get("id", "")).strip()
            if not row_id or row_id in seen_ids:
                return
            seen_ids.add(row_id)
            selected.append(row)

        first_score, first_low_signal, _first_index, first_row = annotated[0]
        if first_low_signal and max(1, limit) >= 3:
            append_row(first_row)

        substantive_rows = [
            row
            for score, low_signal, _index, row in annotated
            if not low_signal and score >= 18
        ]
        medium_rows = [
            row
            for score, low_signal, _index, row in annotated
            if not low_signal and 8 <= score < 18
        ]
        low_signal_rows = [
            row
            for _score, _low_signal, _index, row in annotated
            if row not in substantive_rows and row not in medium_rows
        ]

        for group in (substantive_rows, medium_rows, low_signal_rows):
            for row in group:
                append_row(row)
                if len(selected) >= max(1, limit):
                    return selected[: max(1, limit)]
        return selected[: max(1, limit)]

    def consciousness_snapshot(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 2,
    ) -> dict[str, Any]:
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        thread_summary = ""
        with self._lock:
            thread_state = None
            if normalized_thread_key:
                lookup_keys = [normalized_thread_key]
                if normalized_thread_key.startswith("wechat:"):
                    legacy_thread_key = normalized_thread_key[len("wechat:") :].strip()
                    if legacy_thread_key and legacy_thread_key not in lookup_keys:
                        lookup_keys.append(legacy_thread_key)
                for lookup_key in lookup_keys:
                    thread_state = self.conn.execute(
                        "SELECT summary FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                        (lookup_key, channel),
                    ).fetchone()
                    if thread_state:
                        break
            if thread_state:
                thread_summary = str(thread_state["summary"] or "").strip()
            rows = []
            if normalized_thread_key:
                lookup_keys = [normalized_thread_key]
                if normalized_thread_key.startswith("wechat:"):
                    legacy_thread_key = normalized_thread_key[len("wechat:") :].strip()
                    if legacy_thread_key and legacy_thread_key not in lookup_keys:
                        lookup_keys.append(legacy_thread_key)
                for lookup_key in lookup_keys:
                    rows = [
                        dict(row)
                        for row in self.conn.execute(
                            """
                        SELECT id, text, source_store, source_id, source_kind, memory_class, updated_at
                        FROM mind_nodes
                        WHERE channel = ?
                          AND thread_key = ?
                          AND memory_class IN ('dream_residue', 'initiative_seed')
                        ORDER BY successful_recall_count DESC, updated_at DESC
                        LIMIT ?
                            """,
                            (channel, lookup_key, max(1, limit)),
                        ).fetchall()
                    ]
                    if rows:
                        break
        lines = _dedupe_strings(compact_text(str(row.get("text", "")), 120) for row in rows if str(row.get("text", "")).strip())
        items = [
            {
                "id": str(row.get("id", "")),
                "text": str(row.get("text", "")),
                "source_store": str(row.get("source_store", "")),
                "source_id": str(row.get("source_id", "")),
                "source_kind": str(row.get("source_kind", "")),
                "memory_class": str(row.get("memory_class", "")),
            }
            for row in rows
        ]
        return {
            "thread_summary": thread_summary,
            "lines": lines[: max(1, limit)],
            "items": items[: max(1, limit)],
        }

    def _score_node(
        self,
        row: dict[str, Any],
        *,
        query: str,
        aliases: set[str],
        recall_hint: bool,
        origin_hint: bool,
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = MEMORY_CLASS_WEIGHTS.get(str(row.get("memory_class", "")), 0.75)
        text = str(row.get("text", "")).strip()
        query_tokens = _tokenize(query)
        text_tokens = _tokenize(text)
        query_semantic_tokens = set(_semantic_tokens(query))
        text_semantic_tokens = set(_semantic_tokens(text))
        semantic_overlap = len(query_semantic_tokens & text_semantic_tokens) if query_semantic_tokens and text_semantic_tokens else 0
        if query_tokens and text_tokens:
            overlap = len(set(query_tokens) & set(text_tokens))
            if overlap:
                score *= 1.0 + min(overlap, 6) * 0.08
                reasons.append(f"token_overlap:{overlap}")
        if semantic_overlap:
            score *= 1.0 + min(semantic_overlap, 6) * 0.24
            reasons.append(f"semantic_overlap:{semantic_overlap}")
        lowered_query = query.lower()
        lowered_text = text.lower()
        if lowered_query and lowered_query in lowered_text:
            score *= 1.18
            reasons.append("substring_match")
        row_thread_key = str(row.get("thread_key", "")).strip()
        row_chat_name = str(row.get("chat_name", "")).strip()
        if row_thread_key and row_thread_key in aliases:
            if query_semantic_tokens and not semantic_overlap:
                score *= 1.18
                reasons.append("thread_match_softened")
            else:
                score *= 1.52
                reasons.append("thread_match")
        elif row_chat_name and row_chat_name in aliases:
            if query_semantic_tokens and not semantic_overlap:
                score *= 1.12
                reasons.append("chat_match_softened")
            else:
                score *= 1.3
                reasons.append("chat_match")
        elif row_thread_key:
            score *= 0.74
            reasons.append("other_thread")
        if query_semantic_tokens and not semantic_overlap:
            score *= 0.82
            reasons.append("semantic_miss")
        score *= 0.82 + min(float(row.get("importance", 0.7) or 0.7), 1.5) * 0.26
        score *= 0.84 + min(float(row.get("confidence", 0.7) or 0.7), 1.5) * 0.18
        score *= 1.0 + min(float(row.get("thread_affinity", 0.0) or 0.0), 1.0) * 0.16
        score *= 1.0 + min(float(row.get("emotion_salience", 0.0) or 0.0), 1.0) * 0.06
        score *= 1.0 + min(int(row.get("successful_recall_count", 0) or 0), 6) * 0.02
        if recall_hint and str(row.get("memory_class", "")) in {"episodic_memory", "relationship_memory", "dream_residue"}:
            score *= 1.14
            reasons.append("recall_hint")
        if origin_hint and str(row.get("memory_class", "")) == "episodic_memory":
            score *= 1.08
            reasons.append("origin_hint")
            fields = _archive_turn_fields(row)
            if _is_low_signal_origin_user_text(str(fields.get("user_text", ""))):
                score *= 0.72
                reasons.append("origin_low_signal")
        return score, reasons

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
        self._ensure_materialized()
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        aliases = {item for item in {normalized_thread_key, str(chat_name or "").strip(), f"wechat:{chat_name}" if chat_name else ""} if item}
        recall_hint = _has_hint(query, RECALL_HINTS)
        origin_hint = _has_hint(query, ORIGIN_RECALL_HINTS)
        with self._lock:
            rows: list[dict[str, Any]] = []
            if origin_hint and normalized_thread_key:
                thread_rows: list[sqlite3.Row]
                if str(chat_name or "").strip():
                    thread_rows = self.conn.execute(
                        """
                    SELECT *
                    FROM mind_nodes
                    WHERE node_type NOT IN ('thread', 'contact')
                      AND channel = ?
                      AND (thread_key = ? OR chat_name = ?)
                    ORDER BY updated_at DESC
                        """,
                        (channel, normalized_thread_key, str(chat_name or "").strip()),
                    ).fetchall()
                else:
                    thread_rows = self.conn.execute(
                        """
                    SELECT *
                    FROM mind_nodes
                    WHERE node_type NOT IN ('thread', 'contact')
                      AND channel = ?
                      AND thread_key = ?
                    ORDER BY updated_at DESC
                        """,
                        (channel, normalized_thread_key),
                    ).fetchall()
                rows = [dict(row) for row in thread_rows]
            else:
                rows = [dict(row) for row in self.conn.execute("SELECT * FROM mind_nodes WHERE node_type NOT IN ('thread', 'contact') ORDER BY updated_at DESC").fetchall()]
        scored = []
        for row in rows:
            score, reasons = self._score_node(
                row,
                query=query,
                aliases=aliases,
                recall_hint=recall_hint,
                origin_hint=origin_hint,
            )
            if score > 0:
                scored.append((score, row, reasons))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[float, dict[str, Any], list[str]]] = []
        seen_ids: set[str] = set()
        if origin_hint and normalized_thread_key:
            origin_limit = max(2, min(max(1, limit // 2), 4))
            for row in self._origin_anchor_rows(thread_key=normalized_thread_key, channel=channel, limit=origin_limit):
                score, reasons = self._score_node(
                    row,
                    query=query,
                    aliases=aliases,
                    recall_hint=recall_hint,
                    origin_hint=True,
                )
                row_id = str(row.get("id", "")).strip()
                if not row_id or row_id in seen_ids:
                    continue
                selected.append((score + 0.35, row, reasons + ["origin_anchor"]))
                seen_ids.add(row_id)
        for score, row, reasons in scored:
            row_id = str(row.get("id", "")).strip()
            if not row_id or row_id in seen_ids:
                continue
            selected.append((score, row, reasons))
            seen_ids.add(row_id)
            if len(selected) >= max(1, limit):
                break
        selected = selected[: max(1, limit)]
        top_score = selected[0][0] if selected else 0.0
        if origin_hint or recall_hint:
            tier = "deep_recall"
        elif _is_fast_ping_query(query):
            tier = "fast"
        elif top_score < 1.08:
            tier = "deep_recall"
        else:
            tier = "recall"
        confidence = round(min(top_score / 2.5, 1.0), 4) if top_score else 0.0
        with self._lock:
            thread_state = {}
            if normalized_thread_key:
                row = self.conn.execute("SELECT * FROM mind_thread_state WHERE thread_key = ? AND channel = ?", (normalized_thread_key, channel)).fetchone()
                thread_state = dict(row) if row else {}
        trace = [
            {
                "node_id": row["id"],
                "source_store": row["source_store"],
                "source_id": row["source_id"],
                "source_kind": row["source_kind"],
                "node_type": row["node_type"],
                "memory_class": row["memory_class"],
                "thread_key": row["thread_key"],
                "chat_name": row["chat_name"],
                "score": round(score, 4),
                "activation_reason": reasons,
                "text": row["text"],
            }
            for score, row, reasons in selected
        ]
        payload = {
            "query": query,
            "channel": channel,
            "thread_key": normalized_thread_key,
            "chat_name": str(chat_name or "").strip(),
            "tier": tier,
            "query_focus": "origin" if origin_hint else ("recall" if recall_hint else "recent"),
            "confidence": confidence,
            "activated_node_ids": [item["node_id"] for item in trace],
            "trace": trace,
            "memory_lines": [item["text"] for item in trace[:4]],
            "thread_summary": str(thread_state.get("summary", "")),
            "relationship_summary": str(thread_state.get("summary", "")),
            "thread_state": thread_state,
        }
        if record:
            with self._lock:
                activation_row_id = self.conn.execute(
                    """
                INSERT INTO mind_activation_log(query, channel, thread_key, chat_name, tier, confidence, activated_node_ids_json, trace_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        query,
                        channel,
                        normalized_thread_key,
                        str(chat_name or "").strip(),
                        tier,
                        confidence,
                        json.dumps(payload["activated_node_ids"], ensure_ascii=False),
                        json.dumps(trace, ensure_ascii=False),
                        utc_now(),
                    ),
                ).lastrowid
                self.conn.commit()
            payload["activation_log_id"] = activation_row_id
        return payload

    def record_recall(self, selected_ids: Iterable[str], *, success: bool = True) -> dict[str, Any]:
        updated = 0
        touched_threads: set[tuple[str, str]] = set()
        recalled_at = utc_now()
        with self._lock:
            for item in [str(value).strip() for value in selected_ids if str(value).strip()]:
                matched_rows = [
                    dict(row)
                    for row in self.conn.execute(
                        "SELECT channel, thread_key FROM mind_nodes WHERE source_id = ? OR id = ?",
                        (item, item),
                    ).fetchall()
                ]
                cursor = self.conn.execute(
                    """
                UPDATE mind_nodes
                SET recall_count = recall_count + 1,
                    successful_recall_count = successful_recall_count + ?,
                    updated_at = ?
                WHERE source_id = ? OR id = ?
                    """,
                    (1 if success else 0, recalled_at, item, item),
                )
                updated += int(cursor.rowcount)
                for row in matched_rows:
                    channel = str(row.get("channel", "")).strip()
                    thread_key = str(row.get("thread_key", "")).strip()
                    if channel and thread_key:
                        touched_threads.add((channel, thread_key))
            for channel, thread_key in touched_threads:
                self.conn.execute(
                    """
                UPDATE mind_thread_state
                SET recall_count = recall_count + 1,
                    last_recalled_at = ?
                WHERE channel = ? AND thread_key = ?
                    """,
                    (recalled_at, channel, thread_key),
                )
            self.conn.commit()
        return {"updated": updated, "thread_updates": len(touched_threads), "last_recalled_at": recalled_at}

    def record_stream_run(self, stream_name: str, *, status: str, note: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        influence = {"updated_nodes": 0, "updated_threads": 0, "motifs": [], "unfinished_threads": [], "frontier_updates": []}
        with self._lock:
            row = self.conn.execute("SELECT * FROM mind_stream_state WHERE stream_name = ?", (stream_name,)).fetchone()
            cadence = int(row["cadence_seconds"]) if row else int(self.stream_cadences.get(stream_name, {}).get("cadence_seconds", 0))
            now = utc_now()
            self.conn.execute(
                "INSERT INTO mind_runs(run_type, status, note, stats_json, created_at, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"stream:{stream_name}", status, note, json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), now, now),
            )
            self.conn.execute(
                """
            INSERT INTO mind_stream_state(stream_name, cadence_seconds, description, last_started_at, last_finished_at, last_status, last_note, next_due_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stream_name) DO UPDATE SET
                cadence_seconds = excluded.cadence_seconds,
                last_started_at = excluded.last_started_at,
                last_finished_at = excluded.last_finished_at,
                last_status = excluded.last_status,
                last_note = excluded.last_note,
                next_due_at = excluded.next_due_at
                """,
                (stream_name, cadence, str(self.stream_cadences.get(stream_name, {}).get("description", "")), now, now, status, note, str(cadence)),
            )
            influence = self._apply_stream_influence(stream_name, payload or {}, note=note, now=now)
            self.conn.commit()
        return {
            "stream_name": stream_name,
            "status": status,
            "note": note,
            "cadence_seconds": cadence,
            "influence": influence,
        }

    def _apply_stream_influence(self, stream_name: str, payload: dict[str, Any], *, note: str, now: str) -> dict[str, Any]:
        profile = {
            "maintenance_stream": {"thread_delta": 0.03, "affinity_delta": 0.04, "emotion_delta": 0.02},
            "association_stream": {"thread_delta": 0.05, "affinity_delta": 0.07, "emotion_delta": 0.05},
            "social_stream": {"thread_delta": 0.08, "affinity_delta": 0.09, "emotion_delta": 0.04},
            "deep_dream_cycle": {"thread_delta": 0.05, "affinity_delta": 0.06, "emotion_delta": 0.08},
        }.get(stream_name, {"thread_delta": 0.02, "affinity_delta": 0.03, "emotion_delta": 0.02})

        node_refs: set[str] = set()
        motifs: list[str] = []
        thread_hints: dict[tuple[str, str], dict[str, Any]] = {}
        frontier_updates: list[dict[str, Any]] = []

        def _add_thread(channel: str, thread_key: str, chat_name: str, *, motif: str = "", unfinished: str = "", evidence_ref: str = "") -> None:
            normalized_channel = str(channel or "").strip()
            normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
            if not normalized_channel or not normalized_thread_key:
                return
            bucket = thread_hints.setdefault(
                (normalized_channel, normalized_thread_key),
                {"chat_name": str(chat_name or "").strip(), "motifs": [], "unfinished": [], "evidence_refs": []},
            )
            if str(chat_name or "").strip() and not bucket["chat_name"]:
                bucket["chat_name"] = str(chat_name or "").strip()
            if str(motif).strip():
                bucket["motifs"].append(str(motif).strip())
                motifs.append(str(motif).strip())
            if str(unfinished).strip():
                bucket["unfinished"].append(compact_text(str(unfinished).strip(), 120))
            if str(evidence_ref).strip():
                bucket["evidence_refs"].append(str(evidence_ref).strip())

        for value in list(payload.get("sampled_archive_ids", [])) + list(payload.get("selected_memory_ids", [])):
            text = str(value or "").strip()
            if text:
                node_refs.add(text)

        for key in ("seed", "motif"):
            text = str(payload.get(key, "")).strip()
            if text:
                motifs.append(text)

        if note.strip():
            motifs.append(note.strip())

        for field in ("thoughts", "initiatives"):
            for item in payload.get(field, []):
                if not isinstance(item, dict):
                    continue
                source_archive_id = str(item.get("source_archive_id", "")).strip()
                if source_archive_id:
                    node_refs.add(source_archive_id)
                _add_thread(
                    str(item.get("channel", "")),
                    str(item.get("thread_key", "")),
                    str(item.get("chat_name", "")),
                    motif=str(item.get("motif", "")),
                    unfinished=str(item.get("reason", "") or item.get("prompt", "") or item.get("text", "")),
                    evidence_ref=source_archive_id,
                )

        resolved_node_ids: list[str] = []
        touched_threads: set[tuple[str, str]] = set()
        for ref in sorted(node_refs):
            rows = self.conn.execute(
                "SELECT id, channel, thread_key, chat_name FROM mind_nodes WHERE source_id = ? OR id = ?",
                (ref, ref),
            ).fetchall()
            for row in rows:
                node_id = str(row["id"]).strip()
                if node_id:
                    resolved_node_ids.append(node_id)
                _add_thread(
                    str(row["channel"] or ""),
                    str(row["thread_key"] or ""),
                    str(row["chat_name"] or ""),
                    motif="",
                    unfinished="",
                    evidence_ref=ref,
                )

        unique_node_ids = _dedupe_strings(resolved_node_ids)
        for node_id in unique_node_ids:
            self.conn.execute(
                """
                UPDATE mind_nodes
                SET thread_affinity = MIN(1.0, thread_affinity + ?),
                    emotion_salience = MIN(1.0, emotion_salience + ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (float(profile["affinity_delta"]), float(profile["emotion_delta"]), now, node_id),
            )

        for (channel, thread_key), info in thread_hints.items():
            row = self.conn.execute(
                "SELECT * FROM mind_thread_state WHERE channel = ? AND thread_key = ?",
                (channel, thread_key),
            ).fetchone()
            if row is None:
                continue
            touched_threads.add((channel, thread_key))
            metadata = _safe_json_dict(row["metadata_json"])
            recurring_motifs = _dedupe_strings(list(metadata.get("recurring_motifs", [])) + list(info.get("motifs", [])) + motifs)[:4]
            unfinished_threads = _dedupe_strings(list(metadata.get("unfinished_threads", [])) + list(info.get("unfinished", [])))[:4]
            metadata["recurring_motifs"] = recurring_motifs
            metadata["unfinished_threads"] = unfinished_threads
            tone_tendency = str(metadata.get("tone_tendency", "")).strip()
            if stream_name == "association_stream" and not tone_tendency:
                tone_tendency = "playful_teasing"
            elif stream_name == "social_stream" and tone_tendency not in {"playful_teasing", "wandering_companion"}:
                tone_tendency = "wandering_companion"
            elif stream_name == "maintenance_stream" and not tone_tendency:
                tone_tendency = "continuity_guard"
            if tone_tendency:
                metadata["tone_tendency"] = tone_tendency
            current_game = {
                key: self._clamp(metadata.get(key, GAME_STATE_DEFAULTS[key]), default=GAME_STATE_DEFAULTS[key])
                for key in GAME_STATE_DEFAULTS
            }
            if stream_name == "association_stream":
                current_game["teasing_tolerance"] = self._clamp(current_game["teasing_tolerance"] + 0.06, default=GAME_STATE_DEFAULTS["teasing_tolerance"])
            elif stream_name == "social_stream":
                current_game["initiative_window"] = self._clamp(current_game["initiative_window"] + 0.08, default=GAME_STATE_DEFAULTS["initiative_window"])
                current_game["trust_score"] = self._clamp(current_game["trust_score"] + 0.04, default=GAME_STATE_DEFAULTS["trust_score"])
            elif stream_name == "deep_dream_cycle":
                current_game["reciprocity_balance"] = self._clamp(current_game["reciprocity_balance"] + 0.03, default=GAME_STATE_DEFAULTS["reciprocity_balance"])
            for key, value in current_game.items():
                metadata[key] = value
            metadata["game_state_updated_at"] = now
            metadata["last_stream_influence"] = {
                "stream_name": stream_name,
                "note": note,
                "updated_at": now,
                "motifs": recurring_motifs[:3],
                "unfinished_threads": unfinished_threads[:3],
            }
            self.conn.execute(
                """
                UPDATE mind_thread_state
                SET relationship_score = MIN(1.0, relationship_score + ?),
                    metadata_json = ?,
                    summary = CASE
                        WHEN summary = '' THEN ?
                        ELSE summary
                    END
                WHERE channel = ? AND thread_key = ?
                """,
                (
                    float(profile["thread_delta"]),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    str(row["summary"] or ""),
                    channel,
                    thread_key,
                ),
            )
            if stream_name in ATTENTION_FRONTIER_ALLOWED_STREAMS:
                unfinished_for_thread = list(info.get("unfinished", []))
                wake_reason = (
                    unfinished_for_thread[:1]
                    or list(info.get("motifs", []))[:1]
                    or recurring_motifs[:1]
                    or motifs[:1]
                    or [note or stream_name]
                )[0]
                frontier_item = self._upsert_attention_frontier_locked(
                    channel=channel,
                    thread_key=thread_key,
                    chat_name=str(info.get("chat_name", "") or thread_key),
                    stream_name=stream_name,
                    wake_reason=str(wake_reason),
                    anticipated_next_turn=str(unfinished_for_thread[0] if unfinished_for_thread else wake_reason),
                    pending_open_loop_count=len(unfinished_threads),
                    evidence_refs=list(info.get("evidence_refs", [])),
                    motifs=recurring_motifs,
                    unfinished_threads=unfinished_threads,
                    now=now,
                )
                if bool(frontier_item.get("present", False)):
                    frontier_updates.append(frontier_item)

        for channel, thread_key in touched_threads:
            info = thread_hints.get((channel, thread_key), {"chat_name": "", "motifs": [], "unfinished": []})
            subject = self.subject_state(thread_key=thread_key, chat_name=str(info.get("chat_name", "")), channel=channel)
            affect = dict(subject.get("affect_state", {}))
            drive = dict(subject.get("drive_state", {}))
            value = dict(subject.get("value_state", {}))
            initiative = dict(subject.get("initiative_state", {}))
            if stream_name == "association_stream":
                affect["curiosity"] = self._clamp(self.metric_value(affect.get("curiosity", 0.0), default=AFFECT_STATE_DEFAULTS["curiosity"]) + 0.06, default=AFFECT_STATE_DEFAULTS["curiosity"])
                affect["appetite_play"] = self._clamp(affect.get("appetite_play", 0.0) + 0.05, default=AFFECT_STATE_DEFAULTS["appetite_play"])
                drive["seek_novelty"] = self._clamp(drive.get("seek_novelty", 0.0) + 0.08, default=DRIVE_STATE_DEFAULTS["seek_novelty"])
                value["play_priority"] = self._clamp(value.get("play_priority", 0.0) + 0.06, default=VALUE_STATE_DEFAULTS["play_priority"])
            elif stream_name == "social_stream":
                affect["attachment_pull"] = self._clamp(self.metric_value(affect.get("attachment_pull", 0.0), default=AFFECT_STATE_DEFAULTS["attachment_pull"]) + 0.08, default=AFFECT_STATE_DEFAULTS["attachment_pull"])
                drive["seek_contact"] = self._clamp(drive.get("seek_contact", 0.0) + 0.1, default=DRIVE_STATE_DEFAULTS["seek_contact"])
                drive["seek_continuity"] = self._clamp(drive.get("seek_continuity", 0.0) + 0.05, default=DRIVE_STATE_DEFAULTS["seek_continuity"])
                value["relational_priority"] = self._clamp(value.get("relational_priority", 0.0) + 0.08, default=VALUE_STATE_DEFAULTS["relational_priority"])
                initiative["pressure"] = self._clamp(initiative.get("pressure", 0.0) + 0.08, default=0.0)
            elif stream_name == "deep_dream_cycle":
                affect["continuity_anxiety"] = self._clamp(affect.get("continuity_anxiety", 0.0) + 0.04, default=AFFECT_STATE_DEFAULTS["continuity_anxiety"])
                drive["seek_continuity"] = self._clamp(drive.get("seek_continuity", 0.0) + 0.08, default=DRIVE_STATE_DEFAULTS["seek_continuity"])
                value["repair_priority"] = self._clamp(value.get("repair_priority", 0.0) + 0.05, default=VALUE_STATE_DEFAULTS["repair_priority"])
            else:
                affect["self_preservation"] = self._clamp(affect.get("self_preservation", 0.0) + 0.03, default=AFFECT_STATE_DEFAULTS["self_preservation"])
                drive["protect_identity"] = self._clamp(drive.get("protect_identity", 0.0) + 0.04, default=DRIVE_STATE_DEFAULTS["protect_identity"])
                value["stability_priority"] = self._clamp(value.get("stability_priority", 0.0) + 0.05, default=VALUE_STATE_DEFAULTS["stability_priority"])
            self.update_subject_state(
                channel=channel,
                thread_key=thread_key,
                chat_name=str(info.get("chat_name", "") or thread_key),
                affect_state=affect,
                drive_state=drive,
                value_state=value,
                initiative_state=initiative,
                metadata={"stream_name": stream_name, "stream_motifs": list(info.get("motifs", []))[:3]},
                note=f"stream_influence:{stream_name}",
                source="stream_influence",
            )

        return {
            "updated_nodes": len(unique_node_ids),
            "updated_threads": len(touched_threads),
            "motifs": _dedupe_strings(motifs)[:6],
            "unfinished_threads": _dedupe_strings(
                hint
                for info in thread_hints.values()
                for hint in info.get("unfinished", [])
            )[:6],
            "frontier_updates": frontier_updates[:ATTENTION_FRONTIER_MAX_ENTRIES],
        }

    def stream_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "db_path": str(self.db_path),
                "streams": [dict(row) for row in self.conn.execute("SELECT * FROM mind_stream_state ORDER BY stream_name ASC").fetchall()],
                "recent_runs": [
                    dict(row)
                    for row in self.conn.execute(
                        "SELECT run_type, status, note, stats_json, created_at, completed_at FROM mind_runs WHERE run_type LIKE 'stream:%' ORDER BY id DESC LIMIT 12"
                    ).fetchall()
                ],
                "attention_frontier": self.attention_frontier(limit=ATTENTION_FRONTIER_MAX_ENTRIES),
            }

    def latest_stream_influence(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        with self._lock:
            row = None
            if normalized_thread_key:
                row = self.conn.execute(
                    "SELECT metadata_json FROM mind_thread_state WHERE channel = ? AND thread_key = ?",
                    (channel, normalized_thread_key),
                ).fetchone()
        metadata = _safe_json_dict(row["metadata_json"]) if row else {}
        influence = dict(metadata.get("last_stream_influence", {}))
        if "motifs" not in influence:
            influence["motifs"] = list(metadata.get("recurring_motifs", []))[:3]
        if "unfinished_threads" not in influence:
            influence["unfinished_threads"] = list(metadata.get("unfinished_threads", []))[:3]
        return influence

    def list_self_revision_candidates(self, *, limit: int = 16) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    "SELECT * FROM self_revision_candidates ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            ]
        return rows

    def latest_self_revision_state(self) -> dict[str, Any]:
        with self._lock:
            applied = self.conn.execute("SELECT * FROM self_revision_applied ORDER BY id DESC LIMIT 1").fetchone()
            run = self.conn.execute("SELECT * FROM self_revision_runs ORDER BY id DESC LIMIT 1").fetchone()
        patch = _safe_json_dict(applied["patch_json"]) if applied else {}
        return {
            "latest_run_id": int(run["id"]) if run else 0,
            "latest_status": str(run["status"]) if run else "",
            "applied": bool(applied),
            "applied_patch": patch,
            "applied_at": str(applied["created_at"]) if applied else "",
            "allowed_fields": sorted(ALLOWED_SELF_REVISION_FIELDS),
        }

    def add_self_revision_candidate(self, *, evidence: list[dict[str, Any]], prompt_payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO self_revision_candidates(evidence_json, prompt_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        return {"id": int(row_id), "created_at": now}

    def record_self_revision_run(
        self,
        *,
        status: str,
        evidence: list[dict[str, Any]],
        observe: dict[str, Any],
        plan: dict[str, Any],
        review: dict[str, Any],
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO self_revision_runs(status, evidence_json, observe_json, plan_json, review_json, patch_json, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(status or "").strip(),
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    json.dumps(observe, ensure_ascii=False, sort_keys=True),
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    json.dumps(review, ensure_ascii=False, sort_keys=True),
                    json.dumps(patch, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        return {"id": int(row_id), "created_at": now, "status": str(status or "").strip()}

    def apply_self_revision_patch(self, *, run_id: int, patch: dict[str, Any], note: str = "") -> dict[str, Any]:
        filtered_patch = {key: value for key, value in dict(patch or {}).items() if key in ALLOWED_SELF_REVISION_FIELDS}
        previous = self.latest_self_revision_state().get("applied_patch", {})
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO self_revision_applied(run_id, status, patch_json, previous_patch_json, note, created_at)
                VALUES (?, 'applied', ?, ?, ?, ?)
                """,
                (
                    int(run_id or 0),
                    json.dumps(filtered_patch, ensure_ascii=False, sort_keys=True),
                    json.dumps(previous, ensure_ascii=False, sort_keys=True),
                    str(note or ""),
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        state = self.latest_self_revision_state()
        state["row_id"] = int(row_id)
        state["note"] = note
        return state

    def rollback_self_revision(self) -> dict[str, Any]:
        with self._lock:
            latest = self.conn.execute("SELECT * FROM self_revision_applied ORDER BY id DESC LIMIT 1").fetchone()
            if latest is None:
                return {"status": "skipped", "reason": "no_revision_applied"}
            previous = _safe_json_dict(latest["previous_patch_json"])
            row_id = self.conn.execute(
                """
                INSERT INTO self_revision_applied(run_id, status, patch_json, previous_patch_json, note, created_at)
                VALUES (?, 'rollback', ?, '{}', 'rollback', ?)
                """,
                (
                    int(latest["run_id"] or 0),
                    json.dumps(previous, ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            ).lastrowid
            self.conn.commit()
        state = self.latest_self_revision_state()
        state["status"] = "ok"
        state["row_id"] = int(row_id)
        return state
