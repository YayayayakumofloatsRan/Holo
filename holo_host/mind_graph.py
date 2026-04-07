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
STREAM_DEFAULTS = {
    "maintenance_stream": {"cadence_seconds": 300, "description": "promotion and maintenance"},
    "association_stream": {"cadence_seconds": 900, "description": "thought and association"},
    "social_stream": {"cadence_seconds": 1800, "description": "relationship upkeep"},
    "deep_dream_cycle": {"cadence_seconds": 21600, "description": "slow dream replay"},
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
    "warm_attentive": "说话底色偏温暖贴身，先接住人，再顺着往下说。",
    "protective_steady": "说话底色偏护着和稳着，遇到压力时先减震，不抢着推人。",
    "co_build_nimble": "说话底色偏并肩搭东西，带一点利落和同路人的默契。",
    "playful_teasing": "说话底色偏活泼狡黠，能打趣，但不把人推远。",
    "continuity_guard": "说话底色偏续流和守线头，会自然把旧事与现在接起来。",
    "wandering_companion": "说话底色偏同行旅伴，像一路边走边说。",
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


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(str(text or ""))]


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
            self.conn.commit()

    def count_nodes(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS count FROM mind_nodes").fetchone()
            return int(row["count"]) if row else 0

    def close(self) -> None:
        with self._lock:
            self.conn.close()

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
        return {
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
            "continuity": {"continuity_guard": 1.6, "warm_attentive": 0.4},
            "craft": {"co_build_nimble": 1.8},
            "pressure": {"protective_steady": 1.8, "warm_attentive": 0.4},
            "companionship": {"warm_attentive": 1.8},
            "journey": {"wandering_companion": 1.4, "warm_attentive": 0.4},
            "treat": {"playful_teasing": 1.7, "warm_attentive": 0.3},
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
            votes["continuity_guard"] = votes.get("continuity_guard", 0.0) + 0.8
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
            motif_line = RELATIONSHIP_MOTIF_LINES.get(str(top_motifs[0]), "")
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
        if query_tokens and text_tokens:
            overlap = len(set(query_tokens) & set(text_tokens))
            if overlap:
                score *= 1.0 + min(overlap, 6) * 0.18
                reasons.append(f"token_overlap:{overlap}")
        lowered_query = query.lower()
        lowered_text = text.lower()
        if lowered_query and lowered_query in lowered_text:
            score *= 1.18
            reasons.append("substring_match")
        row_thread_key = str(row.get("thread_key", "")).strip()
        row_chat_name = str(row.get("chat_name", "")).strip()
        if row_thread_key and row_thread_key in aliases:
            score *= 1.52
            reasons.append("thread_match")
        elif row_chat_name and row_chat_name in aliases:
            score *= 1.3
            reasons.append("chat_match")
        elif row_thread_key:
            score *= 0.74
            reasons.append("other_thread")
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
        tier = "deep_recall" if recall_hint or origin_hint or top_score < 1.08 else "recall"
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
            self.conn.commit()
        return {"stream_name": stream_name, "status": status, "note": note, "cadence_seconds": cadence}

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
