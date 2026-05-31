from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.resident.contracts import InboundMessage, OutboxMessage, WorkerLease


class ResidentQueue:
    def __init__(self, db_path: Path | str, *, clock_ms: Callable[[], int] | None = None) -> None:
        self.db_path = Path(db_path)
        self.clock_ms = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._ensure_schema()

    def enqueue(
        self,
        *,
        thread_id: str,
        text: str,
        source: str = "local",
        message_id: str | None = None,
        metadata: JsonObject | None = None,
    ) -> InboundMessage:
        now = self._now_ms()
        message = InboundMessage(
            message_id=message_id or f"inbox-{now}",
            thread_id=thread_id,
            text=text,
            source=source,
            status="pending",
            created_at_ms=now,
            lease_owner=None,
            lease_until_ms=None,
            attempts=0,
            metadata=dict(metadata or {}),
        )
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO resident_inbox (
                    message_id, thread_id, text, source, status, created_at_ms,
                    lease_owner, lease_until_ms, attempts, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _inbox_row(message),
            )
            conn.commit()
        finally:
            conn.close()
        return message

    def acquire_lease(self, *, worker_id: str, ttl_ms: int = 30_000) -> WorkerLease | None:
        now = self._now_ms()
        expires = now + ttl_ms
        conn = self._connect()
        try:
            row = conn.execute("SELECT worker_id, expires_at_ms FROM resident_leases WHERE lease_id = ?", ("resident",)).fetchone()
            if row is not None and int(row[1]) > now and row[0] != worker_id:
                return None
            lease = WorkerLease(
                lease_id="resident",
                worker_id=worker_id,
                acquired_at_ms=now,
                expires_at_ms=expires,
                status="acquired",
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO resident_leases (
                    lease_id, worker_id, acquired_at_ms, expires_at_ms, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (lease.lease_id, lease.worker_id, lease.acquired_at_ms, lease.expires_at_ms, lease.status),
            )
            conn.commit()
            return lease
        finally:
            conn.close()

    def release_lease(self, *, worker_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE resident_leases SET expires_at_ms = ?, status = ? WHERE lease_id = ? AND worker_id = ?",
                (self._now_ms(), "released", "resident", worker_id),
            )
            conn.commit()
        finally:
            conn.close()

    def claim_next(self, *, worker_id: str, lease_ttl_ms: int = 30_000) -> InboundMessage | None:
        now = self._now_ms()
        lease_until = now + lease_ttl_ms
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT message_id, thread_id, text, source, status, created_at_ms,
                       lease_owner, lease_until_ms, attempts, metadata_json
                FROM resident_inbox
                WHERE status = 'pending'
                   OR (status = 'running' AND lease_until_ms IS NOT NULL AND lease_until_ms <= ?)
                ORDER BY created_at_ms, message_id
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row[8]) + 1
            conn.execute(
                """
                UPDATE resident_inbox
                SET status = 'running', lease_owner = ?, lease_until_ms = ?, attempts = ?
                WHERE message_id = ?
                """,
                (worker_id, lease_until, attempts, row[0]),
            )
            conn.commit()
            return InboundMessage.from_dict(
                {
                    "message_id": row[0],
                    "thread_id": row[1],
                    "text": row[2],
                    "source": row[3],
                    "status": "running",
                    "created_at_ms": int(row[5]),
                    "lease_owner": worker_id,
                    "lease_until_ms": lease_until,
                    "attempts": attempts,
                    "metadata": _json_dict(row[9]),
                }
            )
        finally:
            conn.close()

    def complete(self, message_id: str) -> None:
        self._set_inbox_status(message_id, "completed")

    def fail(self, message_id: str, *, reason: str) -> None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT metadata_json FROM resident_inbox WHERE message_id = ?", (message_id,)).fetchone()
            metadata = _json_dict(row[0] if row else None)
            metadata["failure_reason"] = reason
            conn.execute(
                """
                UPDATE resident_inbox
                SET status = 'failed', lease_owner = NULL, lease_until_ms = NULL, metadata_json = ?
                WHERE message_id = ?
                """,
                (_json(metadata), message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def append_outbox(
        self,
        *,
        in_reply_to: str,
        thread_id: str,
        text: str,
        status: str,
        task_id: str | None,
        run_id: str | None,
        payload: JsonObject | None = None,
    ) -> OutboxMessage:
        now = self._now_ms()
        message = OutboxMessage(
            outbox_id=f"outbox-{now}-{in_reply_to}",
            in_reply_to=in_reply_to,
            thread_id=thread_id,
            text=text,
            status=status,
            created_at_ms=now,
            task_id=task_id,
            run_id=run_id,
            payload=dict(payload or {}),
        )
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO resident_outbox (
                    outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                    task_id, run_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _outbox_row(message),
            )
            conn.commit()
        finally:
            conn.close()
        return message

    def inbox_messages(self) -> list[InboundMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT message_id, thread_id, text, source, status, created_at_ms,
                       lease_owner, lease_until_ms, attempts, metadata_json
                FROM resident_inbox
                ORDER BY created_at_ms, message_id
                """
            ).fetchall()
            return [_inbox_from_row(row) for row in rows]
        finally:
            conn.close()

    def outbox_messages(self) -> list[OutboxMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                ORDER BY created_at_ms, outbox_id
                """
            ).fetchall()
            return [_outbox_from_row(row) for row in rows]
        finally:
            conn.close()

    def _set_inbox_status(self, message_id: str, status: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE resident_inbox
                SET status = ?, lease_owner = NULL, lease_until_ms = NULL
                WHERE message_id = ?
                """,
                (status, message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            _create_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _now_ms(self) -> int:
        return int(self.clock_ms())


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resident_inbox (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            text TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            lease_owner TEXT,
            lease_until_ms INTEGER,
            attempts INTEGER NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resident_inbox_status ON resident_inbox(status, created_at_ms)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resident_outbox (
            outbox_id TEXT PRIMARY KEY,
            in_reply_to TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            task_id TEXT,
            run_id TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resident_leases (
            lease_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            acquired_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            status TEXT NOT NULL
        )
        """
    )


def _inbox_row(message: InboundMessage) -> tuple[object, ...]:
    return (
        message.message_id,
        message.thread_id,
        message.text,
        message.source,
        message.status,
        message.created_at_ms,
        message.lease_owner,
        message.lease_until_ms,
        message.attempts,
        _json(message.metadata),
    )


def _outbox_row(message: OutboxMessage) -> tuple[object, ...]:
    return (
        message.outbox_id,
        message.in_reply_to,
        message.thread_id,
        message.text,
        message.status,
        message.created_at_ms,
        message.task_id,
        message.run_id,
        _json(message.payload),
    )


def _inbox_from_row(row) -> InboundMessage:
    return InboundMessage.from_dict(
        {
            "message_id": row[0],
            "thread_id": row[1],
            "text": row[2],
            "source": row[3],
            "status": row[4],
            "created_at_ms": int(row[5]),
            "lease_owner": row[6],
            "lease_until_ms": int(row[7]) if row[7] is not None else None,
            "attempts": int(row[8]),
            "metadata": _json_dict(row[9]),
        }
    )


def _outbox_from_row(row) -> OutboxMessage:
    return OutboxMessage.from_dict(
        {
            "outbox_id": row[0],
            "in_reply_to": row[1],
            "thread_id": row[2],
            "text": row[3],
            "status": row[4],
            "created_at_ms": int(row[5]),
            "task_id": row[6],
            "run_id": row[7],
            "payload": _json_dict(row[8]),
        }
    )


def _json(payload: JsonObject) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _json_dict(value: object) -> JsonObject:
    if not isinstance(value, str) or not value.strip():
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}
