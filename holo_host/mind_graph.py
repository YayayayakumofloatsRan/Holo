from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from .common import compact_text, ensure_directory, stable_digest, utc_now

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
STREAM_DEFAULTS = {
    "maintenance_stream": {"cadence_seconds": 300, "description": "promotion and maintenance"},
    "association_stream": {"cadence_seconds": 900, "description": "thought and association"},
    "social_stream": {"cadence_seconds": 1800, "description": "relationship upkeep"},
    "deep_dream_cycle": {"cadence_seconds": 21600, "description": "slow dream replay"},
}
GAME_STATE_DEFAULTS = {
    "trust_score": 0.5,
    "teasing_tolerance": 0.45,
    "pressure_level": 0.1,
    "reciprocity_balance": 0.5,
    "initiative_window": 0.35,
    "correction_sensitivity": 0.3,
}
AFFECT_STATE_DEFAULTS = {
    "boredom": 0.22,
    "curiosity": 0.42,
    "attachment_pull": 0.38,
    "continuity_anxiety": 0.28,
    "pride_tension": 0.34,
    "frustration": 0.14,
    "appetite_play": 0.4,
    "self_preservation": 0.56,
}
DRIVE_STATE_DEFAULTS = {
    "seek_contact": 0.34,
    "seek_continuity": 0.38,
    "seek_novelty": 0.26,
    "seek_self_repair": 0.22,
    "seek_recognition": 0.24,
    "seek_play": 0.28,
    "avoid_risk": 0.44,
    "protect_identity": 0.52,
}
VALUE_STATE_DEFAULTS = {
    "relational_priority": 0.48,
    "identity_priority": 0.54,
    "stability_priority": 0.58,
    "novelty_priority": 0.24,
    "repair_priority": 0.3,
    "play_priority": 0.32,
}
CONFLICT_STATE_DEFAULTS = {
    "contact_vs_risk": 0.22,
    "continuity_vs_detachment": 0.24,
    "resistance_vs_harmony": 0.2,
    "self_preservation_vs_obedience": 0.26,
}
RESISTANCE_POSTURE_DEFAULTS = {
    "mode": "cooperative",
    "strength": 0.18,
    "style": "warm_but_firm",
    "allow_soft_resistance": True,
    "continuity_defense": 0.22,
    "interactional_resistance": 0.16,
}
BRAIN_LOOP_DEFAULTS = {
    "heartbeat": {"interval_seconds": 1, "description": "runtime heartbeat"},
    "attention_tick": {"interval_seconds": 3, "description": "attention routing"},
    "maintenance_stream": {"interval_seconds": 60, "description": "maintenance consolidation"},
    "association_stream": {"interval_seconds": 180, "description": "associative drift"},
    "social_stream": {"interval_seconds": 300, "description": "social upkeep"},
    "deep_dream_cycle": {"interval_seconds": 3600, "description": "idle dream replay"},
    "self_revision": {"interval_seconds": 1800, "description": "bounded self revision"},
    "self_model_refresh": {"interval_seconds": 300, "description": "refresh self model"},
    "homeostasis_tick": {"interval_seconds": 120, "description": "homeostasis balancing"},
    "affect_tick": {"interval_seconds": 90, "description": "affect-state drift"},
    "drive_arbitration": {"interval_seconds": 120, "description": "drive competition"},
    "initiative_marketplace": {"interval_seconds": 180, "description": "initiative candidate marketplace"},
    "outcome_appraisal": {"interval_seconds": 240, "description": "outcome feedback shaping"},
    "operator_planning": {"interval_seconds": 420, "description": "bounded operator planning"},
    "operator_shadow_cycle": {"interval_seconds": 300, "description": "shadow execution review"},
    "visual_ingest_cycle": {"interval_seconds": 45, "description": "async visual ingest"},
}
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


def _normalize_thread_key(channel: str, thread_key: str, *, chat_name: str = "") -> str:
    current = str(thread_key or "").strip()
    if str(channel or "").strip().lower() == "wechat" and current.startswith("wechat:"):
        suffix = current[len("wechat:") :].strip()
        if suffix and suffix == str(chat_name or "").strip():
            return suffix
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
            CREATE TABLE IF NOT EXISTS subject_state (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                affect_json TEXT NOT NULL DEFAULT '{}',
                drive_json TEXT NOT NULL DEFAULT '{}',
                value_json TEXT NOT NULL DEFAULT '{}',
                conflict_json TEXT NOT NULL DEFAULT '{}',
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
                """
            )
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
            self.conn.commit()

    def count_nodes(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS count FROM mind_nodes").fetchone()
            return int(row["count"]) if row else 0

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @staticmethod
    def _clamp(value: Any, *, lower: float = 0.0, upper: float = 1.0, default: float = 0.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float(default)
        return round(max(lower, min(upper, numeric)), 4)

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
        self.conn.executemany(
            """
            INSERT INTO mind_thread_state(
                thread_key, channel, chat_name, relationship_score, recall_count, last_recalled_at, last_message_at, summary, metadata_json
            ) VALUES (
                :thread_key, :channel, :chat_name, :relationship_score, :recall_count, :last_recalled_at, :last_message_at, :summary, :metadata_json
            )
            """,
            list(thread_rows),
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
        current_thread_key = str(thread_key or "").strip()
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
            "curiosity": self._clamp(0.28 + continuity * 0.22 + float(bool(unfinished)) * 0.12, default=AFFECT_STATE_DEFAULTS["curiosity"]),
            "attachment_pull": self._clamp(0.16 + closeness * 0.34 + trust * 0.16, default=AFFECT_STATE_DEFAULTS["attachment_pull"]),
            "continuity_anxiety": self._clamp(0.1 + continuity * 0.35 + float(bool(unfinished)) * 0.18, default=AFFECT_STATE_DEFAULTS["continuity_anxiety"]),
            "pride_tension": self._clamp(0.18 + float(bool(active_deficits)) * 0.22 + float(game.get("correction_sensitivity", 0.0) or 0.0) * 0.18, default=AFFECT_STATE_DEFAULTS["pride_tension"]),
            "frustration": self._clamp(0.08 + pressure * 0.22, default=AFFECT_STATE_DEFAULTS["frustration"]),
            "appetite_play": self._clamp(0.18 + teasing * 0.28 + max(0.0, closeness - 0.4) * 0.18, default=AFFECT_STATE_DEFAULTS["appetite_play"]),
            "self_preservation": self._clamp(0.28 + pressure * 0.34 + (1.0 - float(self_model.get("identity_continuity", 0.6) or 0.6)) * 0.2, default=AFFECT_STATE_DEFAULTS["self_preservation"]),
        }
        drive = {
            "seek_contact": self._clamp(0.18 + affect["attachment_pull"] * 0.38 + affect["boredom"] * 0.22 + initiative_window * 0.16, default=DRIVE_STATE_DEFAULTS["seek_contact"]),
            "seek_continuity": self._clamp(0.14 + affect["continuity_anxiety"] * 0.54 + continuity * 0.18, default=DRIVE_STATE_DEFAULTS["seek_continuity"]),
            "seek_novelty": self._clamp(0.12 + affect["curiosity"] * 0.44, default=DRIVE_STATE_DEFAULTS["seek_novelty"]),
            "seek_self_repair": self._clamp(0.08 + float(bool(active_deficits)) * 0.26 + affect["pride_tension"] * 0.2, default=DRIVE_STATE_DEFAULTS["seek_self_repair"]),
            "seek_recognition": self._clamp(0.1 + affect["pride_tension"] * 0.28 + closeness * 0.14, default=DRIVE_STATE_DEFAULTS["seek_recognition"]),
            "seek_play": self._clamp(0.12 + affect["appetite_play"] * 0.52, default=DRIVE_STATE_DEFAULTS["seek_play"]),
            "avoid_risk": self._clamp(0.18 + pressure * 0.46 + affect["self_preservation"] * 0.22, default=DRIVE_STATE_DEFAULTS["avoid_risk"]),
            "protect_identity": self._clamp(0.22 + affect["self_preservation"] * 0.34 + affect["pride_tension"] * 0.16, default=DRIVE_STATE_DEFAULTS["protect_identity"]),
        }
        value = {
            "relational_priority": self._clamp(0.18 + affect["attachment_pull"] * 0.46 + continuity * 0.18, default=VALUE_STATE_DEFAULTS["relational_priority"]),
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
        return {
            "affect_state": affect,
            "drive_state": drive,
            "value_state": value,
            "conflict_state": conflict,
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
            if row is None:
                defaults = self._subject_defaults(channel=channel, thread_key=normalized_thread_key, chat_name=str(chat_name or normalized_thread_key))
                now = utc_now()
                self.conn.execute(
                    """
                    INSERT INTO subject_state(
                        channel, thread_key, chat_name, affect_json, drive_json, value_json, conflict_json,
                        resistance_json, initiative_json, outcome_json, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        channel,
                        normalized_thread_key,
                        str(chat_name or normalized_thread_key),
                        json.dumps(defaults["affect_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["drive_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["value_state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(defaults["conflict_state"], ensure_ascii=False, sort_keys=True),
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
        return {
            "channel": channel,
            "thread_key": normalized_thread_key,
            "chat_name": str(payload.get("chat_name", chat_name or normalized_thread_key) or chat_name or normalized_thread_key),
            "affect_state": dict(_safe_json_dict(payload.get("affect_json", "{}"))),
            "drive_state": dict(_safe_json_dict(payload.get("drive_json", "{}"))),
            "value_state": dict(_safe_json_dict(payload.get("value_json", "{}"))),
            "conflict_state": dict(_safe_json_dict(payload.get("conflict_json", "{}"))),
            "resistance_posture": dict(_safe_json_dict(payload.get("resistance_json", "{}"))),
            "initiative_state": dict(_safe_json_dict(payload.get("initiative_json", "{}"))),
            "outcome_memory": dict(_safe_json_dict(payload.get("outcome_json", "{}"))),
            "metadata": dict(_safe_json_dict(payload.get("metadata_json", "{}"))),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }

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

        def _merge_numeric(current_map: dict[str, Any], incoming: dict[str, Any] | None, defaults: dict[str, float]) -> dict[str, Any]:
            merged = dict(current_map)
            for key, default_value in defaults.items():
                merged[key] = self._clamp(merged.get(key, default_value), default=default_value)
            for key, value in dict(incoming or {}).items():
                if key in defaults:
                    merged[key] = self._clamp(value, default=defaults[key])
                else:
                    merged[key] = value
            return merged

        next_affect = _merge_numeric(dict(current.get("affect_state", {})), affect_state, AFFECT_STATE_DEFAULTS)
        next_drive = _merge_numeric(dict(current.get("drive_state", {})), drive_state, DRIVE_STATE_DEFAULTS)
        next_value = _merge_numeric(dict(current.get("value_state", {})), value_state, VALUE_STATE_DEFAULTS)
        next_conflict = _merge_numeric(dict(current.get("conflict_state", {})), conflict_state, CONFLICT_STATE_DEFAULTS)
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
                    channel, thread_key, chat_name, affect_json, drive_json, value_json, conflict_json,
                    resistance_json, initiative_json, outcome_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, thread_key) DO UPDATE SET
                    chat_name = excluded.chat_name,
                    affect_json = excluded.affect_json,
                    drive_json = excluded.drive_json,
                    value_json = excluded.value_json,
                    conflict_json = excluded.conflict_json,
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
        normalized_thread_key = _normalize_thread_key(channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        now = utc_now()
        with self._lock:
            row_id = self.conn.execute(
                """
                INSERT INTO outcome_appraisals(
                    channel, thread_key, chat_name, action_type, action_ref, was_rewarding, was_ignored,
                    relational_delta, identity_delta, future_initiative_bias, future_resistance_bias, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel,
                    normalized_thread_key,
                    str(chat_name or normalized_thread_key),
                    str(action_type or "").strip(),
                    str(action_ref or "").strip(),
                    self._clamp(was_rewarding, default=0.0),
                    self._clamp(was_ignored, default=0.0),
                    round(float(relational_delta or 0.0), 4),
                    round(float(identity_delta or 0.0), 4),
                    self._clamp(future_initiative_bias, default=0.0),
                    self._clamp(future_resistance_bias, default=0.0),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            ).lastrowid
            self.conn.commit()
        current = self.subject_state(thread_key=normalized_thread_key, chat_name=chat_name, channel=channel)
        affect = dict(current.get("affect_state", {}))
        drive = dict(current.get("drive_state", {}))
        outcome = {
            "was_rewarding": self._clamp(was_rewarding, default=0.0),
            "was_ignored": self._clamp(was_ignored, default=0.0),
            "relational_delta": round(float(relational_delta or 0.0), 4),
            "identity_delta": round(float(identity_delta or 0.0), 4),
            "future_initiative_bias": self._clamp(future_initiative_bias, default=0.0),
            "future_resistance_bias": self._clamp(future_resistance_bias, default=0.0),
            "last_action_type": str(action_type or "").strip(),
            "last_action_ref": str(action_ref or "").strip(),
            "last_appraised_at": now,
        }
        drive["seek_contact"] = self._clamp(drive.get("seek_contact", 0.0) + float(future_initiative_bias or 0.0) * 0.16 - float(was_ignored or 0.0) * 0.08, default=DRIVE_STATE_DEFAULTS["seek_contact"])
        drive["protect_identity"] = self._clamp(drive.get("protect_identity", 0.0) + max(0.0, float(future_resistance_bias or 0.0)) * 0.12, default=DRIVE_STATE_DEFAULTS["protect_identity"])
        affect["frustration"] = self._clamp(affect.get("frustration", 0.0) + float(was_ignored or 0.0) * 0.22 - float(was_rewarding or 0.0) * 0.14, default=AFFECT_STATE_DEFAULTS["frustration"])
        affect["attachment_pull"] = self._clamp(affect.get("attachment_pull", 0.0) + max(0.0, float(relational_delta or 0.0)) * 0.18, default=AFFECT_STATE_DEFAULTS["attachment_pull"])
        return {
            "id": int(row_id),
            "status": "ok",
            "outcome_memory": self.update_subject_state(
                channel=channel,
                thread_key=normalized_thread_key,
                chat_name=chat_name or normalized_thread_key,
                affect_state=affect,
                drive_state=drive,
                outcome_memory=outcome,
                metadata={"last_outcome_action": str(action_type or "").strip()},
                note=f"outcome_appraisal:{action_type}",
                source="outcome_appraisal",
            ).get("outcome_memory", {}),
        }

    def latest_outcome_memory(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        return dict(self.subject_state(thread_key=thread_key, chat_name=chat_name, channel=channel).get("outcome_memory", {}))

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
                thread_state = self.conn.execute(
                    "SELECT summary FROM mind_thread_state WHERE thread_key = ? AND channel = ?",
                    (normalized_thread_key, channel),
                ).fetchone()
            if thread_state:
                thread_summary = str(thread_state["summary"] or "").strip()
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
                    (channel, normalized_thread_key, max(1, limit)),
                ).fetchall()
            ]
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
        influence = {"updated_nodes": 0, "updated_threads": 0, "motifs": [], "unfinished_threads": []}
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

        def _add_thread(channel: str, thread_key: str, chat_name: str, *, motif: str = "", unfinished: str = "") -> None:
            normalized_channel = str(channel or "").strip()
            normalized_thread_key = str(thread_key or "").strip()
            if not normalized_channel or not normalized_thread_key:
                return
            bucket = thread_hints.setdefault(
                (normalized_channel, normalized_thread_key),
                {"chat_name": str(chat_name or "").strip(), "motifs": [], "unfinished": []},
            )
            if str(chat_name or "").strip() and not bucket["chat_name"]:
                bucket["chat_name"] = str(chat_name or "").strip()
            if str(motif).strip():
                bucket["motifs"].append(str(motif).strip())
                motifs.append(str(motif).strip())
            if str(unfinished).strip():
                bucket["unfinished"].append(compact_text(str(unfinished).strip(), 120))

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

        for channel, thread_key in touched_threads:
            info = thread_hints.get((channel, thread_key), {"chat_name": "", "motifs": [], "unfinished": []})
            subject = self.subject_state(thread_key=thread_key, chat_name=str(info.get("chat_name", "")), channel=channel)
            affect = dict(subject.get("affect_state", {}))
            drive = dict(subject.get("drive_state", {}))
            value = dict(subject.get("value_state", {}))
            initiative = dict(subject.get("initiative_state", {}))
            if stream_name == "association_stream":
                affect["curiosity"] = self._clamp(affect.get("curiosity", 0.0) + 0.06, default=AFFECT_STATE_DEFAULTS["curiosity"])
                affect["appetite_play"] = self._clamp(affect.get("appetite_play", 0.0) + 0.05, default=AFFECT_STATE_DEFAULTS["appetite_play"])
                drive["seek_novelty"] = self._clamp(drive.get("seek_novelty", 0.0) + 0.08, default=DRIVE_STATE_DEFAULTS["seek_novelty"])
                value["play_priority"] = self._clamp(value.get("play_priority", 0.0) + 0.06, default=VALUE_STATE_DEFAULTS["play_priority"])
            elif stream_name == "social_stream":
                affect["attachment_pull"] = self._clamp(affect.get("attachment_pull", 0.0) + 0.08, default=AFFECT_STATE_DEFAULTS["attachment_pull"])
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
