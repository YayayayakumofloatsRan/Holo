from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.resident.contracts import InboundMessage, OutboxMessage, ResidentQueueInspection, ResidentQueueStatus, WorkerLease


_OUTBOX_STATUSES = {
    "ready",
    "pending_user_input",
    "pending_user_input_delivered",
    "failed",
    "delivery_failed",
    "answered",
    "acknowledged",
}


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
        message_id = message_id or f"inbox-{now}"
        message = InboundMessage(
            message_id=message_id,
            thread_id=thread_id,
            text=text,
            source=source,
            status="pending",
            created_at_ms=now,
            lease_owner=None,
            lease_until_ms=None,
            attempts=0,
            next_attempt_at_ms=None,
            metadata=dict(metadata or {}),
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = _inbox_by_id(conn, message_id)
            if existing is not None:
                if existing.thread_id != thread_id or existing.text != text or existing.source != source:
                    conn.rollback()
                    raise ValueError(f"resident_inbox_message_id_conflict:{message_id}")
                conn.rollback()
                return existing
            conn.execute(
                """
                INSERT INTO resident_inbox (
                    message_id, thread_id, text, source, status, created_at_ms,
                    lease_owner, lease_until_ms, attempts, next_attempt_at_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _inbox_row(message),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return message

    def acquire_lease(self, *, worker_id: str, ttl_ms: int = 30_000) -> WorkerLease | None:
        now = self._now_ms()
        expires = now + ttl_ms
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT worker_id, expires_at_ms FROM resident_leases WHERE lease_id = ?", ("resident",)).fetchone()
            if row is not None and int(row[1]) > now and row[0] != worker_id:
                conn.rollback()
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
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_lease(self, *, worker_id: str, ttl_ms: int = 30_000) -> WorkerLease | None:
        now = self._now_ms()
        expires = now + ttl_ms
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT worker_id FROM resident_leases WHERE lease_id = ?", ("resident",)).fetchone()
            if row is None or row[0] != worker_id:
                conn.rollback()
                return None
            lease = WorkerLease(
                lease_id="resident",
                worker_id=worker_id,
                acquired_at_ms=now,
                expires_at_ms=expires,
                status="renewed",
            )
            conn.execute(
                """
                UPDATE resident_leases
                SET acquired_at_ms = ?, expires_at_ms = ?, status = ?
                WHERE lease_id = ? AND worker_id = ?
                """,
                (lease.acquired_at_ms, lease.expires_at_ms, lease.status, lease.lease_id, lease.worker_id),
            )
            conn.execute(
                """
                UPDATE resident_inbox
                SET lease_until_ms = ?
                WHERE status = 'running' AND lease_owner = ?
                """,
                (expires, worker_id),
            )
            conn.commit()
            return lease
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_lease(self, *, worker_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE resident_leases SET expires_at_ms = ?, status = ? WHERE lease_id = ? AND worker_id = ?",
                (self._now_ms(), "released", "resident", worker_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_next(self, *, worker_id: str, lease_ttl_ms: int = 30_000) -> InboundMessage | None:
        now = self._now_ms()
        lease_until = now + lease_ttl_ms
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if not _lease_is_active(conn, worker_id=worker_id, now_ms=now):
                conn.rollback()
                return None
            row = conn.execute(
                """
                SELECT message_id, thread_id, text, source, status, created_at_ms,
                       lease_owner, lease_until_ms, attempts, metadata_json, next_attempt_at_ms
                FROM resident_inbox
                WHERE status = 'pending'
                   OR (status = 'retry_wait' AND next_attempt_at_ms IS NOT NULL AND next_attempt_at_ms <= ?)
                   OR (status = 'running' AND lease_until_ms IS NOT NULL AND lease_until_ms <= ?)
                ORDER BY created_at_ms, message_id
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            attempts = int(row[8]) + 1
            updated = conn.execute(
                """
                UPDATE resident_inbox
                SET status = 'running', lease_owner = ?, lease_until_ms = ?, attempts = ?, next_attempt_at_ms = NULL
                WHERE message_id = ?
                  AND (
                    status = 'pending'
                    OR (status = 'retry_wait' AND next_attempt_at_ms IS NOT NULL AND next_attempt_at_ms <= ?)
                    OR (status = 'running' AND lease_until_ms IS NOT NULL AND lease_until_ms <= ?)
                  )
                """,
                (worker_id, lease_until, attempts, row[0], now, now),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
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
                    "next_attempt_at_ms": None,
                    "metadata": _json_dict(row[9]),
                }
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, message_id: str, *, worker_id: str | None = None) -> bool:
        return self._set_inbox_status(message_id, "completed", worker_id=worker_id)

    def fail(
        self,
        message_id: str,
        *,
        reason: str,
        worker_id: str | None = None,
        max_attempts: int | None = None,
        retry_backoff_ms: int = 0,
    ) -> bool:
        now = self._now_ms()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT attempts, metadata_json FROM resident_inbox WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            attempts = int(row[0]) if row is not None else 0
            metadata = _json_dict(row[1] if row else None)
            metadata["failure_reason"] = reason
            status = "failed"
            next_attempt_at_ms = None
            if max_attempts is not None:
                metadata["max_attempts"] = max_attempts
                if attempts < max_attempts:
                    status = "retry_wait"
                    next_attempt_at_ms = now + max(0, int(retry_backoff_ms))
                    metadata["retry_reason"] = reason
                else:
                    status = "dead_letter"
            if worker_id is None:
                updated = conn.execute(
                    """
                    UPDATE resident_inbox
                    SET status = ?, lease_owner = NULL, lease_until_ms = NULL,
                        next_attempt_at_ms = ?, metadata_json = ?
                    WHERE message_id = ?
                    """,
                    (status, next_attempt_at_ms, _json(metadata), message_id),
                )
            else:
                updated = conn.execute(
                    """
                    UPDATE resident_inbox
                    SET status = ?, lease_owner = NULL, lease_until_ms = NULL,
                        next_attempt_at_ms = ?, metadata_json = ?
                    WHERE message_id = ? AND lease_owner = ?
                    """,
                    (status, next_attempt_at_ms, _json(metadata), message_id, worker_id),
                )
            conn.commit()
            return updated.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def requeue(
        self,
        message_id: str,
        *,
        reason: str = "manual_requeue",
        reset_attempts: bool = True,
    ) -> InboundMessage | None:
        now = self._now_ms()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = _inbox_by_id(conn, message_id)
            if existing is None or existing.status not in {"retry_wait", "failed", "dead_letter"}:
                conn.rollback()
                return None
            metadata = dict(existing.metadata)
            metadata["last_requeue_reason"] = reason
            metadata["last_requeued_at_ms"] = now
            metadata["requeue_count"] = int(metadata.get("requeue_count") or 0) + 1
            attempts = 0 if reset_attempts else existing.attempts
            updated = conn.execute(
                """
                UPDATE resident_inbox
                SET status = 'pending', lease_owner = NULL, lease_until_ms = NULL,
                    attempts = ?, next_attempt_at_ms = NULL, metadata_json = ?
                WHERE message_id = ? AND status IN ('retry_wait', 'failed', 'dead_letter')
                """,
                (attempts, _json(metadata), message_id),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            return InboundMessage(
                message_id=existing.message_id,
                thread_id=existing.thread_id,
                text=existing.text,
                source=existing.source,
                status="pending",
                created_at_ms=existing.created_at_ms,
                lease_owner=None,
                lease_until_ms=None,
                attempts=attempts,
                next_attempt_at_ms=None,
                metadata=metadata,
            )
        except Exception:
            conn.rollback()
            raise
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
        if status not in _OUTBOX_STATUSES:
            raise ValueError(f"invalid_resident_outbox_status:{status}")
        existing = self._outbox_for_reply(in_reply_to)
        if existing is not None:
            return existing
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
        except sqlite3.IntegrityError:
            conn.rollback()
            existing = self._outbox_for_reply(in_reply_to)
            if existing is not None:
                return existing
            raise
        finally:
            conn.close()
        return message

    def inbox_messages(self) -> list[InboundMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT message_id, thread_id, text, source, status, created_at_ms,
                       lease_owner, lease_until_ms, attempts, metadata_json, next_attempt_at_ms
                FROM resident_inbox
                ORDER BY created_at_ms, message_id
                """
            ).fetchall()
            return [_inbox_from_row(row) for row in rows]
        finally:
            conn.close()

    def inbox_message(self, message_id: str) -> InboundMessage | None:
        conn = self._connect()
        try:
            return _inbox_by_id(conn, message_id)
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

    def outbox_for_reply(self, in_reply_to: str) -> OutboxMessage | None:
        return self._outbox_for_reply(in_reply_to)

    def status(self) -> ResidentQueueStatus:
        now = self._now_ms()
        conn = self._connect()
        try:
            inbox_counts = _status_counts(conn, "resident_inbox")
            outbox_counts = _status_counts(conn, "resident_outbox")
            lease_row = conn.execute(
                """
                SELECT lease_id, worker_id, acquired_at_ms, expires_at_ms, status
                FROM resident_leases
                WHERE lease_id = ?
                """,
                ("resident",),
            ).fetchone()
            active_lease = None
            if lease_row is not None and int(lease_row[3]) > now:
                active_lease = WorkerLease(
                    lease_id=lease_row[0],
                    worker_id=lease_row[1],
                    acquired_at_ms=int(lease_row[2]),
                    expires_at_ms=int(lease_row[3]),
                    status=lease_row[4],
                ).to_dict()
            due_retry_count = _count(
                conn,
                "SELECT COUNT(*) FROM resident_inbox WHERE status = 'retry_wait' AND next_attempt_at_ms IS NOT NULL AND next_attempt_at_ms <= ?",
                (now,),
            )
            stale_running_count = _count(
                conn,
                "SELECT COUNT(*) FROM resident_inbox WHERE status = 'running' AND lease_until_ms IS NOT NULL AND lease_until_ms <= ?",
                (now,),
            )
            claimable_count = (
                int(inbox_counts.get("pending", 0))
                + due_retry_count
                + stale_running_count
            )
            dead_letter_count = int(inbox_counts.get("dead_letter", 0))
            ready_outbox_count = int(outbox_counts.get("ready", 0))
            return ResidentQueueStatus(
                generated_at_ms=now,
                db_path=str(self.db_path),
                inbox_counts=inbox_counts,
                outbox_counts=outbox_counts,
                active_lease=active_lease,
                claimable_count=claimable_count,
                stale_running_count=stale_running_count,
                due_retry_count=due_retry_count,
                dead_letter_count=dead_letter_count,
                ready_outbox_count=ready_outbox_count,
            )
        finally:
            conn.close()

    def inspect(self, *, sample_limit: int = 5) -> ResidentQueueInspection:
        status = self.status()
        inbox = self.inbox_messages()
        outbox = self.outbox_messages()
        issues: list[JsonObject] = []
        actions: list[str] = []

        if status.dead_letter_count:
            dead = [message.message_id for message in inbox if message.status == "dead_letter"][:sample_limit]
            issues.append(
                {
                    "severity": "error",
                    "code": "dead_letter_inbox",
                    "count": status.dead_letter_count,
                    "message_ids": dead,
                }
            )
            actions.append("resident requeue <message_id> --reason manual_review")
        if status.stale_running_count:
            stale = [
                message.message_id
                for message in inbox
                if (
                    message.status == "running"
                    and message.lease_until_ms is not None
                    and message.lease_until_ms <= status.generated_at_ms
                )
            ][:sample_limit]
            issues.append(
                {
                    "severity": "warning",
                    "code": "stale_running_inbox",
                    "count": status.stale_running_count,
                    "message_ids": stale,
                }
            )
            actions.append("resident run-once --worker-id <worker>")
        if status.due_retry_count:
            due = [
                message.message_id
                for message in inbox
                if (
                    message.status == "retry_wait"
                    and message.next_attempt_at_ms is not None
                    and message.next_attempt_at_ms <= status.generated_at_ms
                )
            ][:sample_limit]
            issues.append(
                {
                    "severity": "info",
                    "code": "retry_due",
                    "count": status.due_retry_count,
                    "message_ids": due,
                }
            )
            actions.append("resident run-once --worker-id <worker>")
        pending_count = int(status.inbox_counts.get("pending", 0))
        if pending_count:
            pending = [message.message_id for message in inbox if message.status == "pending"][:sample_limit]
            issues.append(
                {
                    "severity": "info",
                    "code": "pending_inbox",
                    "count": pending_count,
                    "message_ids": pending,
                }
            )
            actions.append("resident run --max-iterations <n>")
        ready_count = int(status.outbox_counts.get("ready", 0))
        if ready_count:
            ready = [message.outbox_id for message in outbox if message.status == "ready"][:sample_limit]
            issues.append(
                {
                    "severity": "info",
                    "code": "ready_outbox",
                    "count": ready_count,
                    "outbox_ids": ready,
                }
            )
            actions.append("resident outbox")
        delivery_failed_count = int(status.outbox_counts.get("delivery_failed", 0))
        if delivery_failed_count:
            failed = [
                message.outbox_id
                for message in outbox
                if message.status == "delivery_failed"
            ][:sample_limit]
            issues.append(
                {
                    "severity": "warning",
                    "code": "delivery_failed_outbox",
                    "count": delivery_failed_count,
                    "outbox_ids": failed,
                }
            )
            actions.append("resident retry-outbox <outbox_id> --reason delivery_retry")
        waiting_count = (
            int(status.outbox_counts.get("pending_user_input", 0))
            + int(status.outbox_counts.get("pending_user_input_delivered", 0))
        )
        if waiting_count:
            waiting = [
                message.outbox_id
                for message in outbox
                if message.status in {"pending_user_input", "pending_user_input_delivered"}
            ][:sample_limit]
            issues.append(
                {
                    "severity": "info",
                    "code": "awaiting_user_input",
                    "count": waiting_count,
                    "outbox_ids": waiting,
                }
            )
            actions.append("wait for user reply in same thread")

        if any(issue["severity"] == "error" for issue in issues):
            health = "error"
        elif any(issue["severity"] == "warning" for issue in issues):
            health = "warning"
        elif issues:
            health = "attention"
        else:
            health = "ok"
        return ResidentQueueInspection(
            status=health,
            generated_at_ms=status.generated_at_ms,
            issues=issues,
            recommended_actions=_ordered_unique(actions),
            queue_status=status.to_dict(),
            samples={
                "inbox": [message.to_dict() for message in inbox[:sample_limit]],
                "outbox": [message.to_dict() for message in outbox[:sample_limit]],
            },
        )

    def mark_outbox_status(self, outbox_id: str, *, status: str) -> OutboxMessage | None:
        outbox, _reason = self.transition_outbox_status(outbox_id, status=status)
        return outbox

    def retry_outbox(self, outbox_id: str, *, reason: str = "manual_retry") -> tuple[OutboxMessage | None, str | None]:
        now = self._now_ms()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None, "outbox_not_found"
            current = _outbox_from_row(row)
            if current.status != "delivery_failed":
                conn.rollback()
                return None, f"invalid_outbox_retry_status:{current.status}"
            payload = dict(current.payload)
            payload["requested_status"] = "ready"
            payload["status_updated_at_ms"] = now
            payload["retry_reason"] = reason
            payload["retried_at_ms"] = now
            payload["retry_count"] = int(payload.get("retry_count") or 0) + 1
            conn.execute(
                "UPDATE resident_outbox SET status = ?, payload_json = ? WHERE outbox_id = ?",
                ("ready", _json(payload), outbox_id),
            )
            row = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
            conn.commit()
            return (_outbox_from_row(row) if row is not None else None), None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def transition_outbox_status(self, outbox_id: str, *, status: str) -> tuple[OutboxMessage | None, str | None]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None, "outbox_not_found"
            current = _outbox_from_row(row)
            next_status = _next_outbox_status(current.status, requested=status)
            if next_status is None:
                conn.rollback()
                return None, f"invalid_outbox_status_transition:{current.status}->{status}"
            payload = dict(current.payload)
            payload["requested_status"] = status
            payload["status_updated_at_ms"] = self._now_ms()
            if status == "acknowledged":
                payload["acknowledged_at_ms"] = payload["status_updated_at_ms"]
            if next_status == current.status:
                if payload == current.payload:
                    conn.rollback()
                    return current, None
                conn.execute(
                    "UPDATE resident_outbox SET payload_json = ? WHERE outbox_id = ?",
                    (_json(payload), outbox_id),
                )
            else:
                conn.execute(
                    "UPDATE resident_outbox SET status = ?, payload_json = ? WHERE outbox_id = ?",
                    (next_status, _json(payload), outbox_id),
                )
            row = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
            conn.commit()
            return (_outbox_from_row(row) if row is not None else None), None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_pending_user_input_answered(
        self,
        *,
        thread_id: str,
        answered_by_message_id: str,
        task_id: str | None,
        run_id: str | None,
        exclude_in_reply_to: str | None = None,
    ) -> list[OutboxMessage]:
        now = self._now_ms()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE thread_id = ?
                  AND status IN ('pending_user_input', 'pending_user_input_delivered')
                  AND (? IS NULL OR task_id = ?)
                  AND (? IS NULL OR in_reply_to != ?)
                ORDER BY created_at_ms, outbox_id
                """,
                (thread_id, task_id, task_id, exclude_in_reply_to, exclude_in_reply_to),
            ).fetchall()
            answered: list[OutboxMessage] = []
            for row in rows:
                existing = _outbox_from_row(row)
                payload = dict(existing.payload)
                payload["answered_by_message_id"] = answered_by_message_id
                payload["answered_at_ms"] = now
                if task_id is not None:
                    payload["answered_task_id"] = task_id
                if run_id is not None:
                    payload["answered_run_id"] = run_id
                updated = conn.execute(
                    """
                    UPDATE resident_outbox
                    SET status = 'answered', payload_json = ?
                    WHERE outbox_id = ?
                      AND status IN ('pending_user_input', 'pending_user_input_delivered')
                    """,
                    (_json(payload), existing.outbox_id),
                )
                if updated.rowcount != 1:
                    continue
                answered.append(
                    OutboxMessage(
                        outbox_id=existing.outbox_id,
                        in_reply_to=existing.in_reply_to,
                        thread_id=existing.thread_id,
                        text=existing.text,
                        status="answered",
                        created_at_ms=existing.created_at_ms,
                        task_id=existing.task_id,
                        run_id=existing.run_id,
                        payload=payload,
                    )
                )
            conn.commit()
            return answered
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _outbox_for_reply(self, in_reply_to: str) -> OutboxMessage | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT outbox_id, in_reply_to, thread_id, text, status, created_at_ms,
                       task_id, run_id, payload_json
                FROM resident_outbox
                WHERE in_reply_to = ?
                ORDER BY created_at_ms, outbox_id
                LIMIT 1
                """,
                (in_reply_to,),
            ).fetchone()
            return _outbox_from_row(row) if row is not None else None
        finally:
            conn.close()

    def _set_inbox_status(self, message_id: str, status: str, *, worker_id: str | None = None) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if worker_id is None:
                updated = conn.execute(
                    """
                    UPDATE resident_inbox
                    SET status = ?, lease_owner = NULL, lease_until_ms = NULL, next_attempt_at_ms = NULL
                    WHERE message_id = ?
                    """,
                    (status, message_id),
                )
            else:
                updated = conn.execute(
                    """
                    UPDATE resident_inbox
                    SET status = ?, lease_owner = NULL, lease_until_ms = NULL, next_attempt_at_ms = NULL
                    WHERE message_id = ? AND lease_owner = ?
                    """,
                    (status, message_id, worker_id),
                )
            conn.commit()
            return updated.rowcount == 1
        except Exception:
            conn.rollback()
            raise
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
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

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
            next_attempt_at_ms INTEGER,
            metadata_json TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "resident_inbox", "next_attempt_at_ms", "INTEGER")
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
    _dedupe_outbox_replies(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resident_outbox_in_reply_to ON resident_outbox(in_reply_to)")
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


def _dedupe_outbox_replies(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM resident_outbox
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM resident_outbox
            GROUP BY in_reply_to
        )
        """
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column in {str(row[1]) for row in rows}:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _status_counts(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    rows = conn.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status").fetchall()
    return {str(status): int(count) for status, count in rows}


def _count(conn: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = conn.execute(query, values).fetchone()
    return int(row[0]) if row is not None else 0


def _next_outbox_status(current: str, *, requested: str) -> str | None:
    if current not in _OUTBOX_STATUSES or requested not in _OUTBOX_STATUSES:
        return None
    if requested == current:
        return current
    if requested == "acknowledged":
        if current in {"ready", "failed"}:
            return "acknowledged"
        if current == "pending_user_input":
            return "pending_user_input_delivered"
        if current == "pending_user_input_delivered":
            return "pending_user_input_delivered"
        if current == "answered":
            return "answered"
        return None
    if current in {"ready", "failed", "pending_user_input", "pending_user_input_delivered"} and requested == "delivery_failed":
        return "delivery_failed"
    if current == "pending_user_input" and requested == "pending_user_input_delivered":
        return "pending_user_input_delivered"
    return None


def _lease_is_active(conn: sqlite3.Connection, *, worker_id: str, now_ms: int) -> bool:
    row = conn.execute(
        "SELECT expires_at_ms FROM resident_leases WHERE lease_id = ? AND worker_id = ?",
        ("resident", worker_id),
    ).fetchone()
    return row is not None and int(row[0]) > now_ms


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
        message.next_attempt_at_ms,
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
            "next_attempt_at_ms": int(row[10]) if row[10] is not None else None,
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


def _inbox_by_id(conn: sqlite3.Connection, message_id: str) -> InboundMessage | None:
    row = conn.execute(
        """
        SELECT message_id, thread_id, text, source, status, created_at_ms,
               lease_owner, lease_until_ms, attempts, metadata_json, next_attempt_at_ms
        FROM resident_inbox
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    return _inbox_from_row(row) if row is not None else None


def _json(payload: JsonObject) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _json_dict(value: object) -> JsonObject:
    if not isinstance(value, str) or not value.strip():
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
