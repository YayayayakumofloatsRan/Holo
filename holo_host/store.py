from __future__ import annotations

import json
import sqlite3
import threading
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import json_dumps, utc_now
from .models import IncomingMessage, OutgoingMessage, ProcessorUsageRecord


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class QueueStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            return

    @_synchronized
    def close(self) -> None:
        self.conn.close()

    @_synchronized
    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                initiative_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_inbound_at TEXT,
                last_outbound_at TEXT
            );

            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL,
                contact_id INTEGER NOT NULL,
                thread_key TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                codex_session_id TEXT NOT NULL DEFAULT '',
                allow_auto_reply INTEGER NOT NULL DEFAULT 1,
                allow_proactive INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_at TEXT,
                last_direction TEXT,
                UNIQUE(channel, thread_key),
                FOREIGN KEY(contact_id) REFERENCES contacts(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL,
                direction TEXT NOT NULL,
                contact_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                in_reply_to TEXT NOT NULL DEFAULT '',
                references_header TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                body_text TEXT NOT NULL DEFAULT '',
                body_html TEXT NOT NULL DEFAULT '',
                sender_email TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                recipient_email TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(contact_id) REFERENCES contacts(id),
                FOREIGN KEY(thread_id) REFERENCES threads(id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                message_row_id INTEGER,
                thread_id INTEGER,
                contact_id INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                available_at TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                sent_message_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(message_row_id) REFERENCES messages(id),
                FOREIGN KEY(thread_id) REFERENCES threads(id),
                FOREIGN KEY(contact_id) REFERENCES contacts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, available_at, priority DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_threads_contact ON threads(contact_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS event_bus (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                chat_name TEXT NOT NULL DEFAULT '',
                message_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                payload_json TEXT NOT NULL DEFAULT '{}',
                decision_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                executed_at TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_event_bus_thread ON event_bus(channel, thread_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_event_bus_status ON event_bus(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS processor_usage_ledger (
                id INTEGER PRIMARY KEY,
                task_type TEXT NOT NULL DEFAULT '',
                lane TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                reasoning_effort TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                event_id TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_processor_usage_created ON processor_usage_ledger(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_processor_usage_task ON processor_usage_ledger(task_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_processor_usage_lane ON processor_usage_ledger(lane, created_at DESC);
            """
        )
        self._ensure_column("contacts", "last_initiative_at", "TEXT")
        self._ensure_column("contacts", "initiative_note", "TEXT NOT NULL DEFAULT ''")
        self._normalize_wechat_aliases()
        self.conn.commit()

    @_synchronized
    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            str(row["name"])
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _latest_timestamp(*values: Any) -> str:
        normalized = [str(value or "").strip() for value in values if str(value or "").strip()]
        return max(normalized) if normalized else ""

    @staticmethod
    def _normalize_wechat_contact_email(email: str) -> str:
        current = str(email or "").strip()
        while current.startswith("wechat:wechat:"):
            current = "wechat:" + current[len("wechat:wechat:") :]
        return current

    @staticmethod
    def _normalize_wechat_thread_key(channel: str, thread_key: str, *, subject: str = "", display_name: str = "") -> str:
        normalized_channel = str(channel or "").strip().lower()
        current = str(thread_key or "").strip()
        if normalized_channel != "wechat":
            return current
        if current.startswith("wechat:"):
            suffix = current[len("wechat:") :].strip()
            if not suffix or suffix.endswith("@chatroom") or suffix.startswith("wxid_"):
                return current
            return f"wechat:{suffix}"
        if not current or current.endswith("@chatroom") or current.startswith("wxid_"):
            return current
        names = {
            current,
            str(subject or "").strip(),
            str(display_name or "").strip(),
        }
        names.discard("")
        if names:
            preferred = next(
                (
                    name
                    for name in (str(display_name or "").strip(), str(subject or "").strip(), current)
                    if name and not name.endswith("@chatroom") and not name.startswith("wxid_")
                ),
                "",
            )
            if preferred:
                return f"wechat:{preferred}"
        return current

    def _normalize_wechat_aliases(self) -> None:
        self._normalize_wechat_contact_aliases()
        self._normalize_wechat_thread_aliases()

    @_synchronized
    def _normalize_wechat_contact_aliases(self) -> None:
        rows = self._fetchall("SELECT * FROM contacts WHERE email LIKE 'wechat:wechat:%'")
        for legacy in rows:
            legacy_id = int(legacy["id"])
            normalized_email = self._normalize_wechat_contact_email(str(legacy.get("email") or ""))
            if not normalized_email or normalized_email == str(legacy.get("email") or ""):
                continue
            canonical = self._fetchone("SELECT * FROM contacts WHERE email = ?", (normalized_email,))
            now = utc_now()
            if canonical and int(canonical["id"]) != legacy_id:
                canonical_id = int(canonical["id"])
                self.conn.execute("UPDATE threads SET contact_id = ? WHERE contact_id = ?", (canonical_id, legacy_id))
                self.conn.execute("UPDATE messages SET contact_id = ? WHERE contact_id = ?", (canonical_id, legacy_id))
                self.conn.execute("UPDATE jobs SET contact_id = ? WHERE contact_id = ?", (canonical_id, legacy_id))
                self.conn.execute(
                    """
                    UPDATE contacts
                    SET display_name = ?,
                        initiative_enabled = ?,
                        updated_at = ?,
                        last_inbound_at = ?,
                        last_outbound_at = ?,
                        last_initiative_at = ?,
                        initiative_note = ?
                    WHERE id = ?
                    """,
                    (
                        str(canonical.get("display_name") or legacy.get("display_name") or ""),
                        1 if bool(canonical.get("initiative_enabled", 1)) or bool(legacy.get("initiative_enabled", 1)) else 0,
                        now,
                        self._latest_timestamp(canonical.get("last_inbound_at"), legacy.get("last_inbound_at")),
                        self._latest_timestamp(canonical.get("last_outbound_at"), legacy.get("last_outbound_at")),
                        self._latest_timestamp(canonical.get("last_initiative_at"), legacy.get("last_initiative_at")),
                        str(canonical.get("initiative_note") or legacy.get("initiative_note") or ""),
                        canonical_id,
                    ),
                )
                self.conn.execute("DELETE FROM contacts WHERE id = ?", (legacy_id,))
                continue
            self.conn.execute(
                "UPDATE contacts SET email = ?, updated_at = ? WHERE id = ?",
                (normalized_email, now, legacy_id),
            )

    @_synchronized
    def _normalize_wechat_thread_aliases(self) -> None:
        rows = self._fetchall(
            """
            SELECT threads.*, contacts.display_name AS contact_display_name
            FROM threads
            LEFT JOIN contacts ON contacts.id = threads.contact_id
            WHERE threads.channel = 'wechat'
            """
        )
        for legacy in rows:
            legacy_id = int(legacy["id"])
            normalized_key = self._normalize_wechat_thread_key(
                "wechat",
                str(legacy.get("thread_key") or ""),
                subject=str(legacy.get("subject") or ""),
                display_name=str(legacy.get("contact_display_name") or ""),
            )
            if not normalized_key or normalized_key == str(legacy.get("thread_key") or ""):
                continue
            canonical = self._fetchone(
                "SELECT * FROM threads WHERE channel = 'wechat' AND thread_key = ?",
                (normalized_key,),
            )
            now = utc_now()
            if canonical and int(canonical["id"]) != legacy_id:
                canonical_id = int(canonical["id"])
                self.conn.execute("UPDATE messages SET thread_id = ? WHERE thread_id = ?", (canonical_id, legacy_id))
                self.conn.execute("UPDATE jobs SET thread_id = ? WHERE thread_id = ?", (canonical_id, legacy_id))
                latest_last_message = self._latest_timestamp(canonical.get("last_message_at"), legacy.get("last_message_at"))
                latest_direction = str(canonical.get("last_direction") or legacy.get("last_direction") or "")
                if latest_last_message == str(legacy.get("last_message_at") or "").strip():
                    latest_direction = str(legacy.get("last_direction") or latest_direction)
                self.conn.execute(
                    """
                    UPDATE threads
                    SET contact_id = ?,
                        subject = ?,
                        codex_session_id = ?,
                        allow_auto_reply = ?,
                        allow_proactive = ?,
                        updated_at = ?,
                        last_message_at = ?,
                        last_direction = ?
                    WHERE id = ?
                    """,
                    (
                        int(canonical.get("contact_id") or legacy.get("contact_id") or 0),
                        str(canonical.get("subject") or legacy.get("subject") or normalized_key),
                        str(canonical.get("codex_session_id") or legacy.get("codex_session_id") or ""),
                        1 if bool(canonical.get("allow_auto_reply", 1)) or bool(legacy.get("allow_auto_reply", 1)) else 0,
                        1 if bool(canonical.get("allow_proactive", 1)) or bool(legacy.get("allow_proactive", 1)) else 0,
                        now,
                        latest_last_message or None,
                        latest_direction,
                        canonical_id,
                    ),
                )
                self.conn.execute("DELETE FROM threads WHERE id = ?", (legacy_id,))
                continue
            self.conn.execute(
                """
                UPDATE threads
                SET thread_key = ?,
                    subject = CASE WHEN subject = '' THEN ? ELSE subject END,
                    updated_at = ?
                WHERE id = ?
                """,
                (normalized_key, str(legacy.get("subject") or normalized_key), now, legacy_id),
            )

    @_synchronized
    def _fetchone(self, query: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self.conn.execute(query, args).fetchone()
        return dict(row) if row else None

    @_synchronized
    def _fetchall(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(query, args).fetchall()]

    @_synchronized
    def ensure_contact(self, email: str, display_name: str = "") -> dict[str, Any]:
        email = self._normalize_wechat_contact_email(email)
        now = utc_now()
        existing = self._fetchone("SELECT * FROM contacts WHERE email = ?", (email,))
        if existing:
            self.conn.execute(
                "UPDATE contacts SET display_name = ?, updated_at = ? WHERE id = ?",
                (display_name or existing["display_name"], now, existing["id"]),
            )
            self.conn.commit()
            return self._fetchone("SELECT * FROM contacts WHERE id = ?", (existing["id"],)) or existing

        cursor = self.conn.execute(
            """
            INSERT INTO contacts(email, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, display_name, now, now),
        )
        self.conn.commit()
        return self._fetchone("SELECT * FROM contacts WHERE id = ?", (cursor.lastrowid,))

    @_synchronized
    def ensure_thread(
        self,
        *,
        channel: str,
        contact_id: int,
        thread_key: str,
        subject: str,
    ) -> tuple[dict[str, Any], bool]:
        thread_key = self._normalize_wechat_thread_key(channel, thread_key, subject=subject)
        now = utc_now()
        existing = self._fetchone(
            "SELECT * FROM threads WHERE channel = ? AND thread_key = ?",
            (channel, thread_key),
        )
        if existing:
            self.conn.execute(
                """
                UPDATE threads
                SET subject = CASE WHEN subject = '' THEN ? ELSE subject END,
                    updated_at = ?
                WHERE id = ?
                """,
                (subject, now, existing["id"]),
            )
            self.conn.commit()
            return self._fetchone("SELECT * FROM threads WHERE id = ?", (existing["id"],)) or existing, False

        cursor = self.conn.execute(
            """
            INSERT INTO threads(channel, contact_id, thread_key, subject, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel, contact_id, thread_key, subject, now, now),
        )
        self.conn.commit()
        return self._fetchone("SELECT * FROM threads WHERE id = ?", (cursor.lastrowid,)), True

    @_synchronized
    def find_contact(self, email: str) -> dict[str, Any] | None:
        email = self._normalize_wechat_contact_email(email)
        return self._fetchone("SELECT * FROM contacts WHERE email = ?", (email,))

    @_synchronized
    def find_thread(self, *, channel: str, thread_key: str) -> dict[str, Any] | None:
        thread_key = self._normalize_wechat_thread_key(channel, thread_key)
        return self._fetchone(
            "SELECT * FROM threads WHERE channel = ? AND thread_key = ?",
            (channel, thread_key),
        )

    @_synchronized
    def set_contact_initiative_enabled(self, contact_id: int, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE contacts SET initiative_enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, utc_now(), contact_id),
        )
        self.conn.commit()

    @_synchronized
    def mark_initiative_sent(self, contact_id: int, *, note: str = "") -> None:
        now = utc_now()
        self.conn.execute(
            """
            UPDATE contacts
            SET last_initiative_at = ?,
                initiative_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, note, now, contact_id),
        )
        self.conn.commit()

    @_synchronized
    def initiative_available(self, contact_id: int, *, cooldown_hours: int) -> bool:
        contact = self._fetchone("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        if not contact:
            return False
        if not bool(contact.get("initiative_enabled", 1)):
            return False
        last_initiative_at = str(contact.get("last_initiative_at", "") or "").strip()
        if not last_initiative_at:
            return True
        cutoff = (
            datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=cooldown_hours)
        ).isoformat().replace("+00:00", "Z")
        return last_initiative_at <= cutoff

    @_synchronized
    def has_event(self, event_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM messages WHERE event_id = ?", (event_id,)).fetchone()
        return row is not None

    @_synchronized
    def record_inbound(self, message: IncomingMessage) -> dict[str, Any]:
        if self.has_event(message.event_id):
            existing = self._fetchone("SELECT * FROM messages WHERE event_id = ?", (message.event_id,))
            if existing:
                thread = self._fetchone("SELECT * FROM threads WHERE id = ?", (int(existing["thread_id"]),))
                contact = self._fetchone("SELECT * FROM contacts WHERE id = ?", (int(existing["contact_id"]),))
                latest = self._fetchone(
                    """
                    SELECT * FROM messages
                    WHERE thread_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (int(existing["thread_id"]),),
                )
                awaiting_reply = bool(
                    existing.get("direction") == "inbound"
                    and latest
                    and int(latest["id"]) == int(existing["id"])
                )
                return {
                    "duplicate": True,
                    "message": existing,
                    "thread": thread,
                    "contact": contact,
                    "awaiting_reply": awaiting_reply,
                }
            return {"duplicate": True, "message": existing, "awaiting_reply": False}

        contact = self.ensure_contact(message.sender_email, message.sender_name)
        thread, created = self.ensure_thread(
            channel=message.channel,
            contact_id=int(contact["id"]),
            thread_key=message.thread_key,
            subject=message.subject,
        )
        now = utc_now()
        payload = {
            "metadata": message.metadata,
            "source_ref": message.source_ref,
            "reply_to_email": message.reply_to_email,
        }
        cursor = self.conn.execute(
            """
            INSERT INTO messages(
                event_id, channel, direction, contact_id, thread_id, message_id,
                in_reply_to, references_header, subject, body_text, body_html,
                sender_email, sender_name, recipient_email, payload_json, created_at
            ) VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                message.event_id,
                message.channel,
                int(contact["id"]),
                int(thread["id"]),
                message.message_id,
                message.in_reply_to,
                " ".join(message.references),
                message.subject,
                message.body_text,
                message.body_html,
                message.sender_email,
                message.sender_name,
                json_dumps(payload),
                message.received_at or now,
            ),
        )
        self.conn.execute(
            """
            UPDATE contacts
            SET last_inbound_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (message.received_at or now, now, int(contact["id"])),
        )
        self.conn.execute(
            """
            UPDATE threads
            SET last_message_at = ?, last_direction = 'inbound', updated_at = ?
            WHERE id = ?
            """,
            (message.received_at or now, now, int(thread["id"])),
        )
        self.conn.commit()
        stored = self._fetchone("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))
        return {
            "duplicate": False,
            "contact": contact,
            "thread": thread,
            "message": stored,
            "new_thread": created,
        }

    @_synchronized
    def enqueue_job(
        self,
        *,
        task_type: str,
        status: str = "pending",
        priority: int = 100,
        message_row_id: int | None = None,
        thread_id: int | None = None,
        contact_id: int | None = None,
        payload: dict[str, Any] | None = None,
        available_at: str | None = None,
    ) -> int:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO jobs(
                task_type, status, priority, message_row_id, thread_id, contact_id,
                payload_json, available_at, scheduled_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_type,
                status,
                priority,
                message_row_id,
                thread_id,
                contact_id,
                json_dumps(payload or {}),
                available_at or now,
                available_at or now,
                now,
                now,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    @_synchronized
    def list_due_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT * FROM jobs
            WHERE status IN ('pending', 'retry_wait')
              AND available_at <= ?
            ORDER BY priority DESC, available_at ASC, id ASC
            LIMIT ?
            """,
            (utc_now(), limit),
        )

    @_synchronized
    def claim_job(self, job_id: int) -> bool:
        now = utc_now()
        cursor = self.conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                attempt_count = attempt_count + 1,
                updated_at = ?
            WHERE id = ?
              AND status IN ('pending', 'retry_wait')
            """,
            (now, job_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    @_synchronized
    def complete_job(self, job_id: int, *, status: str = "completed", sent_message_id: str = "") -> None:
        self.conn.execute(
            "UPDATE jobs SET status = ?, sent_message_id = ?, updated_at = ? WHERE id = ?",
            (status, sent_message_id, utc_now(), job_id),
        )
        self.conn.commit()

    @_synchronized
    def block_job(self, job_id: int, reason: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET status = 'blocked', last_error = ?, updated_at = ? WHERE id = ?",
            (reason, utc_now(), job_id),
        )
        self.conn.commit()

    @_synchronized
    def retry_job(self, job_id: int, reason: str, delay_seconds: int) -> None:
        available_at = (
            datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=delay_seconds)
        ).isoformat().replace("+00:00", "Z")
        self.conn.execute(
            """
            UPDATE jobs
            SET status = 'retry_wait',
                last_error = ?,
                available_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (reason, available_at, utc_now(), job_id),
        )
        self.conn.commit()

    @_synchronized
    def update_thread_session(self, thread_id: int, session_id: str) -> None:
        if not session_id:
            return
        self.conn.execute(
            "UPDATE threads SET codex_session_id = ?, updated_at = ? WHERE id = ?",
            (session_id, utc_now(), thread_id),
        )
        self.conn.commit()

    @_synchronized
    def record_outbound(
        self,
        *,
        thread_id: int,
        contact_id: int,
        remote_message_id: str,
        outgoing: OutgoingMessage,
    ) -> dict[str, Any]:
        now = utc_now()
        payload = {"metadata": outgoing.metadata}
        cursor = self.conn.execute(
            """
            INSERT INTO messages(
                event_id, channel, direction, contact_id, thread_id, message_id,
                in_reply_to, references_header, subject, body_text, body_html,
                sender_email, sender_name, recipient_email, payload_json, created_at
            ) VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)
            """,
            (
                f"{outgoing.channel}:{remote_message_id}",
                outgoing.channel,
                contact_id,
                thread_id,
                remote_message_id,
                outgoing.in_reply_to,
                " ".join(outgoing.references),
                outgoing.subject,
                outgoing.body_text,
                outgoing.body_html,
                outgoing.recipient_email,
                json_dumps(payload),
                now,
            ),
        )
        self.conn.execute(
            "UPDATE contacts SET last_outbound_at = ?, updated_at = ? WHERE id = ?",
            (now, now, contact_id),
        )
        self.conn.execute(
            """
            UPDATE threads
            SET subject = ?, last_message_at = ?, last_direction = 'outbound', updated_at = ?
            WHERE id = ?
            """,
            (outgoing.subject, now, now, thread_id),
        )
        self.conn.commit()
        return self._fetchone("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))

    @_synchronized
    def count_recent_outbound(self, contact_id: int, *, within_seconds: int = 3600) -> int:
        cutoff = (
            datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=within_seconds)
        ).isoformat().replace("+00:00", "Z")
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE contact_id = ?
              AND direction = 'outbound'
              AND created_at >= ?
            """,
            (contact_id, cutoff),
        ).fetchone()
        return int(row["count"]) if row else 0

    @_synchronized
    def recent_thread_messages(self, thread_id: int, limit: int = 6) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT * FROM messages
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread_id, limit),
        )

    @_synchronized
    def latest_activity_at(self, *, channel: str | None = None) -> str:
        if channel:
            row = self.conn.execute(
                "SELECT MAX(last_message_at) AS ts FROM threads WHERE channel = ?",
                (str(channel).strip(),),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT MAX(last_message_at) AS ts FROM threads").fetchone()
        return str((row["ts"] if row else "") or "")

    @_synchronized
    def get_thread_bundle(self, job_id: int, history_limit: int = 6) -> dict[str, Any] | None:
        job = self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not job:
            return None
        thread = self._fetchone("SELECT * FROM threads WHERE id = ?", (int(job["thread_id"]),))
        contact = self._fetchone("SELECT * FROM contacts WHERE id = ?", (int(job["contact_id"]),))
        message = None
        if job.get("message_row_id"):
            message = self._fetchone("SELECT * FROM messages WHERE id = ?", (int(job["message_row_id"]),))
        history = list(reversed(self.recent_thread_messages(int(job["thread_id"]), history_limit)))
        payload = json.loads(str(job.get("payload_json") or "{}"))
        return {
            "job": job,
            "thread": thread,
            "contact": contact,
            "message": message,
            "history": history,
            "payload": payload,
        }

    @_synchronized
    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))

    @_synchronized
    def enqueue_event(
        self,
        *,
        event_type: str,
        channel: str,
        thread_key: str,
        chat_name: str,
        message_id: str = "",
        payload: dict[str, Any] | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        normalized_thread_key = self._normalize_wechat_thread_key(channel, thread_key, subject=chat_name, display_name=chat_name)
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO event_bus(
                event_type, channel, thread_key, chat_name, message_id, status,
                payload_json, decision_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?)
            """,
            (
                str(event_type or "").strip(),
                str(channel or "").strip(),
                normalized_thread_key,
                str(chat_name or normalized_thread_key).strip(),
                str(message_id or "").strip(),
                str(status or "pending").strip() or "pending",
                json_dumps(payload or {}),
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get_event(int(cursor.lastrowid)) or {}

    @_synchronized
    def get_event(self, event_row_id: int) -> dict[str, Any] | None:
        return self._fetchone("SELECT * FROM event_bus WHERE id = ?", (int(event_row_id or 0),))

    @_synchronized
    def update_event_decision(
        self,
        event_row_id: int,
        *,
        decision: dict[str, Any],
        selected_action: str = "",
        status: str = "decided",
    ) -> dict[str, Any]:
        now = utc_now()
        payload = dict(decision or {})
        if selected_action:
            payload.setdefault("selected_action", selected_action)
        self.conn.execute(
            """
            UPDATE event_bus
            SET decision_json = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json_dumps(payload),
                str(status or "decided").strip() or "decided",
                now,
                int(event_row_id or 0),
            ),
        )
        self.conn.commit()
        return self.get_event(event_row_id) or {}

    @_synchronized
    def update_event_result(
        self,
        event_row_id: int,
        *,
        result: dict[str, Any],
        status: str = "executed",
    ) -> dict[str, Any]:
        now = utc_now()
        normalized_status = str(status or "executed").strip() or "executed"
        self.conn.execute(
            """
            UPDATE event_bus
            SET result_json = ?,
                status = ?,
                updated_at = ?,
                executed_at = CASE
                    WHEN ? IN ('executed', 'silenced', 'deferred', 'replied', 'lookup_complete')
                    THEN ?
                    ELSE executed_at
                END
            WHERE id = ?
            """,
            (
                json_dumps(dict(result or {})),
                normalized_status,
                now,
                normalized_status,
                now,
                int(event_row_id or 0),
            ),
        )
        self.conn.commit()
        return self.get_event(event_row_id) or {}

    @_synchronized
    def recent_events(
        self,
        *,
        channel: str,
        thread_key: str,
        limit: int = 16,
    ) -> list[dict[str, Any]]:
        normalized_thread_key = self._normalize_wechat_thread_key(channel, thread_key)
        return self._fetchall(
            """
            SELECT * FROM event_bus
            WHERE channel = ? AND thread_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(channel or "").strip(), normalized_thread_key, max(1, int(limit))),
        )

    @_synchronized
    def record_processor_usage(self, record: ProcessorUsageRecord | dict[str, Any]) -> dict[str, Any]:
        payload = record.to_dict() if isinstance(record, ProcessorUsageRecord) else dict(record or {})
        created_at = str(payload.get("created_at") or utc_now()).strip() or utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO processor_usage_ledger(
                task_type, lane, provider, model, reasoning_effort, thread_key, event_id,
                duration_ms, prompt_tokens, completion_tokens, total_tokens,
                estimated, status, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("task_type", "")).strip(),
                str(payload.get("lane", "")).strip(),
                str(payload.get("provider", "")).strip(),
                str(payload.get("model", "")).strip(),
                str(payload.get("reasoning_effort", "")).strip(),
                str(payload.get("thread_key", "")).strip(),
                str(payload.get("event_id", "")).strip(),
                int(payload.get("duration_ms", 0) or 0),
                int(payload.get("prompt_tokens", 0) or 0),
                int(payload.get("completion_tokens", 0) or 0),
                int(payload.get("total_tokens", 0) or 0),
                1 if bool(payload.get("estimated", True)) else 0,
                str(payload.get("status", "")).strip() or "ok",
                json_dumps(payload.get("metadata", {})),
                created_at,
            ),
        )
        self.conn.commit()
        return self._fetchone("SELECT * FROM processor_usage_ledger WHERE id = ?", (int(cursor.lastrowid),)) or {}

    @_synchronized
    def list_processor_usage(
        self,
        *,
        limit: int = 50,
        task_type: str | None = None,
        lane: str | None = None,
        provider: str | None = None,
        event_id: str | None = None,
        thread_key: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        args: list[Any] = []
        if str(task_type or "").strip():
            clauses.append("task_type = ?")
            args.append(str(task_type).strip())
        if str(lane or "").strip():
            clauses.append("lane = ?")
            args.append(str(lane).strip())
        if str(provider or "").strip():
            clauses.append("provider = ?")
            args.append(str(provider).strip())
        if str(event_id or "").strip():
            clauses.append("event_id = ?")
            args.append(str(event_id).strip())
        if str(thread_key or "").strip():
            clauses.append("thread_key = ?")
            args.append(str(thread_key).strip())
        args.append(max(1, int(limit)))
        return self._fetchall(
            f"""
            SELECT * FROM processor_usage_ledger
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ?
            """,
            tuple(args),
        )

    @_synchronized
    def has_pending_proactive(self, thread_id: int) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE thread_id = ?
              AND task_type = 'proactive_followup'
              AND status IN ('pending', 'retry_wait', 'running')
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        return row is not None

    @_synchronized
    def has_pending_initiative(self, thread_id: int) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE thread_id = ?
              AND task_type = 'initiative_ping'
              AND status IN ('pending', 'retry_wait', 'running')
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        return row is not None

    @_synchronized
    def schedule_due_followups(self, after_hours: int, limit: int = 10) -> list[int]:
        cutoff = (
            datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=after_hours)
        ).isoformat().replace("+00:00", "Z")
        rows = self._fetchall(
            """
            SELECT threads.*, contacts.id AS contact_id
            FROM threads
            JOIN contacts ON contacts.id = threads.contact_id
            WHERE threads.allow_proactive = 1
              AND threads.last_direction = 'inbound'
              AND threads.last_message_at IS NOT NULL
              AND threads.last_message_at <= ?
            ORDER BY threads.last_message_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        created: list[int] = []
        for row in rows:
            thread_id = int(row["id"])
            if self.has_pending_proactive(thread_id):
                continue
            job_id = self.enqueue_job(
                task_type="proactive_followup",
                priority=60,
                thread_id=thread_id,
                contact_id=int(row["contact_id"]),
                payload={"reason": "stale_inbound_thread", "after_hours": after_hours},
            )
            created.append(job_id)
        return created
