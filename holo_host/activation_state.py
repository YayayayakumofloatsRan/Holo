from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .common import ensure_directory, utc_now


def _dedupe_strings(lines: Iterable[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in lines:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
        if limit is not None and len(unique) >= limit:
            break
    return unique


class ActivationStateStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        ensure_directory(self.db_path.parent)
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS mind_activation_state (
                channel TEXT NOT NULL,
                thread_key TEXT NOT NULL,
                chat_name TEXT NOT NULL DEFAULT '',
                heat REAL NOT NULL DEFAULT 0.0,
                active_node_ids_json TEXT NOT NULL DEFAULT '[]',
                motifs_json TEXT NOT NULL DEFAULT '[]',
                recall_priors_json TEXT NOT NULL DEFAULT '{}',
                contributor_counts_json TEXT NOT NULL DEFAULT '{}',
                last_updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(channel, thread_key)
            );
            CREATE TABLE IF NOT EXISTS mind_activation_events (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                contributor TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                node_ids_json TEXT NOT NULL DEFAULT '[]',
                motifs_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
                """
            )
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @staticmethod
    def _decode_json(raw: Any, *, default: Any) -> Any:
        if isinstance(raw, (dict, list)):
            return raw
        text = str(raw or "").strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default

    def _load_state(self, *, channel: str, thread_key: str, chat_name: str) -> dict[str, Any]:
        cache_key = (channel, thread_key)
        if cache_key in self._cache:
            return dict(self._cache[cache_key])
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM mind_activation_state WHERE channel = ? AND thread_key = ?",
                (channel, thread_key),
            ).fetchone()
        if not row:
            payload = {
                "channel": channel,
                "thread_key": thread_key,
                "chat_name": chat_name,
                "heat": 0.0,
                "active_node_ids": [],
                "motifs": [],
                "recall_priors": {},
                "contributor_counts": {},
                "last_updated_at": "",
            }
        else:
            payload = {
                "channel": str(row["channel"]),
                "thread_key": str(row["thread_key"]),
                "chat_name": str(row["chat_name"]),
                "heat": float(row["heat"] or 0.0),
                "active_node_ids": list(self._decode_json(row["active_node_ids_json"], default=[])),
                "motifs": list(self._decode_json(row["motifs_json"], default=[])),
                "recall_priors": dict(self._decode_json(row["recall_priors_json"], default={})),
                "contributor_counts": dict(self._decode_json(row["contributor_counts_json"], default={})),
                "last_updated_at": str(row["last_updated_at"] or ""),
            }
        self._cache[cache_key] = dict(payload)
        return payload

    def record(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        contributor: str,
        note: str = "",
        node_ids: Iterable[str] | None = None,
        motifs: Iterable[str] | None = None,
        recall_priors: dict[str, float] | None = None,
        payload: dict[str, Any] | None = None,
        heat_delta: float = 0.1,
    ) -> dict[str, Any]:
        normalized_thread_key = str(thread_key or "").strip()
        if not normalized_thread_key:
            return {"status": "skipped", "reason": "missing_thread_key"}
        current = self._load_state(channel=channel, thread_key=normalized_thread_key, chat_name=chat_name)
        merged_node_ids = _dedupe_strings(list(node_ids or []) + list(current.get("active_node_ids", [])), limit=12)
        merged_motifs = _dedupe_strings(list(motifs or []) + list(current.get("motifs", [])), limit=8)
        prior_payload = dict(current.get("recall_priors", {}))
        for key, value in dict(recall_priors or {}).items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            prior_payload[key_text] = round(max(0.0, float(prior_payload.get(key_text, 0.0) or 0.0) + float(value or 0.0)), 4)
        contributor_counts = dict(current.get("contributor_counts", {}))
        contributor_counts[contributor] = int(contributor_counts.get(contributor, 0) or 0) + 1
        now = utc_now()
        next_state = {
            "channel": channel,
            "thread_key": normalized_thread_key,
            "chat_name": str(chat_name or "").strip(),
            "heat": round(max(0.0, float(current.get("heat", 0.0) or 0.0) + float(heat_delta or 0.0)), 4),
            "active_node_ids": merged_node_ids,
            "motifs": merged_motifs,
            "recall_priors": prior_payload,
            "contributor_counts": contributor_counts,
            "last_updated_at": now,
        }
        with self._lock:
            self.conn.execute(
                """
            INSERT INTO mind_activation_state(
                channel, thread_key, chat_name, heat, active_node_ids_json, motifs_json, recall_priors_json, contributor_counts_json, last_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel, thread_key) DO UPDATE SET
                chat_name = excluded.chat_name,
                heat = excluded.heat,
                active_node_ids_json = excluded.active_node_ids_json,
                motifs_json = excluded.motifs_json,
                recall_priors_json = excluded.recall_priors_json,
                contributor_counts_json = excluded.contributor_counts_json,
                last_updated_at = excluded.last_updated_at
                """,
                (
                    channel,
                    normalized_thread_key,
                    str(chat_name or "").strip(),
                    next_state["heat"],
                    json.dumps(next_state["active_node_ids"], ensure_ascii=False),
                    json.dumps(next_state["motifs"], ensure_ascii=False),
                    json.dumps(next_state["recall_priors"], ensure_ascii=False, sort_keys=True),
                    json.dumps(next_state["contributor_counts"], ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            self.conn.execute(
                """
            INSERT INTO mind_activation_events(
                channel, thread_key, chat_name, contributor, note, node_ids_json, motifs_json, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel,
                    normalized_thread_key,
                    str(chat_name or "").strip(),
                    contributor,
                    note,
                    json.dumps(merged_node_ids[:8], ensure_ascii=False),
                    json.dumps(merged_motifs[:8], ensure_ascii=False),
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            self.conn.commit()
        self._cache[(channel, normalized_thread_key)] = dict(next_state)
        return {"status": "ok", "state": next_state}

    def state(self, *, channel: str, thread_key: str, chat_name: str = "") -> dict[str, Any]:
        payload = self._load_state(channel=channel, thread_key=thread_key, chat_name=chat_name)
        with self._lock:
            recent_events = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT contributor, note, node_ids_json, motifs_json, payload_json, created_at
                FROM mind_activation_events
                WHERE channel = ? AND thread_key = ?
                ORDER BY id DESC
                LIMIT 10
                    """,
                    (channel, thread_key),
                ).fetchall()
            ]
        return {
            **payload,
            "recent_events": [
                {
                    "contributor": str(item.get("contributor", "")),
                    "note": str(item.get("note", "")),
                    "node_ids": list(self._decode_json(item.get("node_ids_json"), default=[])),
                    "motifs": list(self._decode_json(item.get("motifs_json"), default=[])),
                    "payload": dict(self._decode_json(item.get("payload_json"), default={})),
                    "created_at": str(item.get("created_at", "")),
                }
                for item in recent_events
            ],
        }

    def snapshot(self, *, channel: str, thread_key: str, chat_name: str = "") -> dict[str, Any]:
        return self._load_state(channel=channel, thread_key=thread_key, chat_name=chat_name)

    def global_recent_events(self, *, limit: int = 24) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT channel, thread_key, chat_name, contributor, note, node_ids_json, motifs_json, payload_json, created_at
                FROM mind_activation_events
                ORDER BY id DESC
                LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
            ]
        return [
            {
                "channel": str(item.get("channel", "")),
                "thread_key": str(item.get("thread_key", "")),
                "chat_name": str(item.get("chat_name", "")),
                "contributor": str(item.get("contributor", "")),
                "note": str(item.get("note", "")),
                "node_ids": list(self._decode_json(item.get("node_ids_json"), default=[])),
                "motifs": list(self._decode_json(item.get("motifs_json"), default=[])),
                "payload": dict(self._decode_json(item.get("payload_json"), default={})),
                "created_at": str(item.get("created_at", "")),
            }
            for item in rows
        ]

    def global_recent_motifs(self, *, limit: int = 24) -> list[str]:
        with self._lock:
            rows = [
                dict(row)
                for row in self.conn.execute(
                    """
                SELECT motifs_json
                FROM mind_activation_events
                WHERE channel = 'global'
                ORDER BY id DESC
                LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
            ]
        motifs: list[str] = []
        for item in rows:
            motifs.extend(str(motif).strip() for motif in self._decode_json(item.get("motifs_json"), default=[]) if str(motif).strip())
        return _dedupe_strings(motifs, limit=8)
