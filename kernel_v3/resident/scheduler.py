from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.resident.contracts import (
    InboundMessage,
    ResidentSchedule,
    ResidentScheduleInspection,
    ResidentScheduleStatus,
    ResidentScheduleTickResult,
)
from kernel_v3.resident.projection import (
    resident_schedule_enqueued_event,
    resident_schedule_event,
    resident_schedule_tick_event,
)
from kernel_v3.resident.queue import ResidentQueue


RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP = 20
RESIDENT_SCHEDULE_TICK_LIMIT_CAP = 50


class ResidentScheduler:
    def __init__(
        self,
        *,
        queue: ResidentQueue,
        clock_ms: Callable[[], int] | None = None,
        journal: JournalStore | None = None,
    ) -> None:
        self.queue = queue
        self.db_path = Path(queue.db_path)
        self.clock_ms = clock_ms or queue.clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.journal = journal
        self._ensure_schema()

    def add_schedule(
        self,
        *,
        thread_id: str,
        text: str,
        schedule_id: str | None = None,
        source: str = "schedule",
        priority: int = 0,
        due_at_ms: int | None = None,
        due_in_ms: int = 0,
        interval_ms: int | None = None,
        max_runs: int | None = 1,
        metadata: JsonObject | None = None,
    ) -> ResidentSchedule:
        now = self._now_ms()
        due_at = int(due_at_ms) if due_at_ms is not None else now + max(0, int(due_in_ms))
        _validate_schedule(interval_ms=interval_ms, max_runs=max_runs)
        schedule = ResidentSchedule(
            schedule_id=schedule_id or f"schedule-{now}",
            thread_id=thread_id,
            text=text,
            source=source,
            status="active",
            priority=_normalize_priority(priority),
            created_at_ms=now,
            next_due_at_ms=due_at,
            interval_ms=interval_ms,
            max_runs=max_runs,
            run_count=0,
            last_enqueued_at_ms=None,
            last_message_id=None,
            metadata=dict(metadata or {}),
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = _schedule_by_id(conn, schedule.schedule_id)
            if existing is not None:
                if existing.to_dict() == schedule.to_dict():
                    conn.rollback()
                    return existing
                if (
                    existing.thread_id == schedule.thread_id
                    and existing.text == schedule.text
                    and existing.source == schedule.source
                    and existing.priority == schedule.priority
                    and existing.next_due_at_ms == schedule.next_due_at_ms
                    and existing.interval_ms == schedule.interval_ms
                    and existing.max_runs == schedule.max_runs
                    and existing.metadata == schedule.metadata
                ):
                    conn.rollback()
                    return existing
                conn.rollback()
                raise ValueError(f"resident_schedule_id_conflict:{schedule.schedule_id}")
            conn.execute(
                """
                INSERT INTO resident_schedules (
                    schedule_id, thread_id, text, source, status, created_at_ms,
                    priority, next_due_at_ms, interval_ms, max_runs, run_count,
                    last_enqueued_at_ms, last_message_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _schedule_row(schedule),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        self._journal_event(
            "resident_schedule_added",
            resident_schedule_event(schedule),
            state_delta={"resident_schedule_status": schedule.status, "resident_schedule_id": schedule.schedule_id},
        )
        return schedule

    def list_schedules(self, *, include_inactive: bool = False) -> list[ResidentSchedule]:
        conn = self._connect()
        try:
            where = "" if include_inactive else "WHERE status = 'active'"
            rows = conn.execute(
                """
                SELECT schedule_id, thread_id, text, source, status, created_at_ms,
                       priority, next_due_at_ms, interval_ms, max_runs, run_count,
                       last_enqueued_at_ms, last_message_id, metadata_json
                FROM resident_schedules
                """
                + where
                + " ORDER BY priority DESC, created_at_ms, schedule_id"
            ).fetchall()
            return [_schedule_from_row(row) for row in rows]
        finally:
            conn.close()

    def status(self) -> ResidentScheduleStatus:
        now = self._now_ms()
        conn = self._connect()
        try:
            counts = _status_counts(conn)
            due_count = _count(
                conn,
                """
                SELECT COUNT(*)
                FROM resident_schedules
                WHERE status = 'active'
                  AND next_due_at_ms IS NOT NULL
                  AND next_due_at_ms <= ?
                  AND (max_runs IS NULL OR run_count < max_runs)
                """,
                (now,),
            )
            recurring_count = _count(
                conn,
                "SELECT COUNT(*) FROM resident_schedules WHERE status = 'active' AND interval_ms IS NOT NULL",
                (),
            )
            unbounded_count = _count(
                conn,
                "SELECT COUNT(*) FROM resident_schedules WHERE status = 'active' AND max_runs IS NULL",
                (),
            )
            next_due_row = conn.execute(
                """
                SELECT MIN(next_due_at_ms)
                FROM resident_schedules
                WHERE status = 'active'
                  AND next_due_at_ms IS NOT NULL
                  AND (max_runs IS NULL OR run_count < max_runs)
                """
            ).fetchone()
            next_due_at_ms = int(next_due_row[0]) if next_due_row is not None and next_due_row[0] is not None else None
            return ResidentScheduleStatus(
                generated_at_ms=now,
                db_path=str(self.db_path),
                schedule_counts=counts,
                active_count=int(counts.get("active", 0)),
                due_count=due_count,
                recurring_count=recurring_count,
                unbounded_count=unbounded_count,
                next_due_at_ms=next_due_at_ms,
            )
        finally:
            conn.close()

    def inspect(self, *, sample_limit: int = 5) -> ResidentScheduleInspection:
        status = self.status()
        effective_sample_limit = _clamp_limit(sample_limit, cap=RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP)
        issues: list[JsonObject] = []
        actions: list[str] = []
        if status.due_count:
            due_ids = self._sample_due_schedule_ids(now_ms=status.generated_at_ms, limit=effective_sample_limit)
            issues.append(
                {
                    "severity": "info",
                    "code": "due_schedules",
                    "count": status.due_count,
                    "schedule_ids": due_ids,
                }
            )
            actions.append("resident run --tick-schedules --max-iterations <n>")
        if status.unbounded_count:
            unbounded_ids = self._sample_unbounded_schedule_ids(limit=effective_sample_limit)
            issues.append(
                {
                    "severity": "info",
                    "code": "unbounded_recurring_schedules",
                    "count": status.unbounded_count,
                    "schedule_ids": unbounded_ids,
                }
            )
            actions.append("resident schedule-list --include-inactive")
        if any(issue["severity"] == "error" for issue in issues):
            health = "error"
        elif any(issue["severity"] == "warning" for issue in issues):
            health = "warning"
        elif issues:
            health = "attention"
        else:
            health = "ok"
        return ResidentScheduleInspection(
            status=health,
            generated_at_ms=status.generated_at_ms,
            issues=issues,
            recommended_actions=_ordered_unique(actions),
            schedule_status=status.to_dict(),
            samples=_inspection_samples(
                self._sample_schedules(limit=effective_sample_limit),
                requested_sample_limit=sample_limit,
                effective_sample_limit=effective_sample_limit,
            ),
        )

    def disable_schedule(self, schedule_id: str, *, reason: str = "manual_disable") -> ResidentSchedule | None:
        now = self._now_ms()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = _schedule_by_id(conn, schedule_id)
            if existing is None:
                conn.rollback()
                return None
            if existing.status != "active":
                conn.rollback()
                return existing
            metadata = dict(existing.metadata)
            metadata["disabled_reason"] = reason
            metadata["disabled_at_ms"] = now
            conn.execute(
                """
                UPDATE resident_schedules
                SET status = 'disabled', metadata_json = ?
                WHERE schedule_id = ?
                """,
                (_json(metadata), schedule_id),
            )
            row = _schedule_by_id(conn, schedule_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if row is not None:
            self._journal_event(
                "resident_schedule_disabled",
                resident_schedule_event(row),
                state_delta={"resident_schedule_status": row.status, "resident_schedule_id": row.schedule_id},
            )
        return row

    def tick(self, *, limit: int = 20) -> ResidentScheduleTickResult:
        now = self._now_ms()
        effective_limit = _clamp_limit(limit, cap=RESIDENT_SCHEDULE_TICK_LIMIT_CAP)
        due = self._due_schedules(now_ms=now, limit=effective_limit)
        enqueued: list[InboundMessage] = []
        updated_schedules: list[ResidentSchedule] = []
        failures: list[JsonObject] = []

        for schedule in due:
            if schedule.next_due_at_ms is None:
                failures.append({"schedule_id": schedule.schedule_id, "reason": "missing_next_due_at_ms"})
                continue
            message_id = _message_id(schedule)
            try:
                message = self.queue.enqueue(
                    thread_id=schedule.thread_id,
                    text=schedule.text,
                    source=schedule.source,
                    priority=schedule.priority,
                    message_id=message_id,
                    metadata={
                        **dict(schedule.metadata),
                        "schedule_id": schedule.schedule_id,
                        "scheduled_due_at_ms": schedule.next_due_at_ms,
                        "schedule_run_index": schedule.run_count + 1,
                        "schedule_priority": schedule.priority,
                    },
                )
                updated = self._advance_schedule(schedule, message=message, ticked_at_ms=now)
                enqueued.append(message)
                updated_schedules.append(updated)
                self._journal_event(
                    "resident_schedule_enqueued",
                    resident_schedule_enqueued_event(schedule=updated, message=message),
                    state_delta={
                        "resident_schedule_status": updated.status,
                        "resident_schedule_id": updated.schedule_id,
                        "resident_message_id": message.message_id,
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive queue containment
                failures.append({"schedule_id": schedule.schedule_id, "reason": type(exc).__name__})

        status = "idle"
        if failures and enqueued:
            status = "partial_failure"
        elif failures:
            status = "failed"
        elif enqueued:
            status = "completed"
        result = ResidentScheduleTickResult(
            status=status,
            generated_at_ms=now,
            due_count=len(due),
            enqueued_count=len(enqueued),
            skipped_count=max(0, len(due) - len(enqueued) - len(failures)),
            failed_count=len(failures),
            schedules=[schedule.to_dict() for schedule in updated_schedules],
            enqueued_messages=[message.to_dict() for message in enqueued],
            failures=failures,
            diagnostics=_limit_diagnostics(
                requested_limit=limit,
                effective_limit=effective_limit,
                limit_cap=RESIDENT_SCHEDULE_TICK_LIMIT_CAP,
            ),
        )
        self._journal_event(
            "resident_schedule_tick",
            resident_schedule_tick_event(result),
            state_delta={"resident_schedule_tick_status": result.status, "resident_schedule_due_count": result.due_count},
        )
        return result

    def _due_schedules(self, *, now_ms: int, limit: int) -> list[ResidentSchedule]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT schedule_id, thread_id, text, source, status, created_at_ms,
                       priority, next_due_at_ms, interval_ms, max_runs, run_count,
                       last_enqueued_at_ms, last_message_id, metadata_json
                FROM resident_schedules
                WHERE status = 'active'
                  AND next_due_at_ms IS NOT NULL
                  AND next_due_at_ms <= ?
                  AND (max_runs IS NULL OR run_count < max_runs)
                ORDER BY priority DESC, next_due_at_ms, created_at_ms, schedule_id
                LIMIT ?
                """,
                (now_ms, max(0, int(limit))),
            ).fetchall()
            return [_schedule_from_row(row) for row in rows]
        finally:
            conn.close()

    def _sample_due_schedule_ids(self, *, now_ms: int, limit: int) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT schedule_id
                FROM resident_schedules
                WHERE status = 'active'
                  AND next_due_at_ms IS NOT NULL
                  AND next_due_at_ms <= ?
                  AND (max_runs IS NULL OR run_count < max_runs)
                ORDER BY priority DESC, next_due_at_ms, created_at_ms, schedule_id
                LIMIT ?
                """,
                (now_ms, limit),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def _sample_unbounded_schedule_ids(self, *, limit: int) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT schedule_id
                FROM resident_schedules
                WHERE status = 'active' AND max_runs IS NULL
                ORDER BY priority DESC, created_at_ms, schedule_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def _sample_schedules(self, *, limit: int) -> list[ResidentSchedule]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT schedule_id, thread_id, text, source, status, created_at_ms,
                       priority, next_due_at_ms, interval_ms, max_runs, run_count,
                       last_enqueued_at_ms, last_message_id, metadata_json
                FROM resident_schedules
                ORDER BY priority DESC, created_at_ms, schedule_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_schedule_from_row(row) for row in rows]
        finally:
            conn.close()

    def _advance_schedule(
        self,
        schedule: ResidentSchedule,
        *,
        message: InboundMessage,
        ticked_at_ms: int,
    ) -> ResidentSchedule:
        run_count = schedule.run_count + 1
        completed = schedule.max_runs is not None and run_count >= schedule.max_runs
        if completed:
            status = "completed"
            next_due_at_ms = None
        else:
            status = "active"
            next_due_at_ms = (schedule.next_due_at_ms or ticked_at_ms) + int(schedule.interval_ms or 0)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE resident_schedules
                SET status = ?, next_due_at_ms = ?, run_count = ?,
                    last_enqueued_at_ms = ?, last_message_id = ?
                WHERE schedule_id = ?
                """,
                (status, next_due_at_ms, run_count, ticked_at_ms, message.message_id, schedule.schedule_id),
            )
            row = _schedule_by_id(conn, schedule.schedule_id)
            conn.commit()
            if row is None:  # pragma: no cover - impossible after successful update
                raise RuntimeError(f"resident_schedule_missing_after_update:{schedule.schedule_id}")
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resident_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    next_due_at_ms INTEGER,
                    interval_ms INTEGER,
                    max_runs INTEGER,
                    run_count INTEGER NOT NULL,
                    last_enqueued_at_ms INTEGER,
                    last_message_id TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            _ensure_column(conn, "resident_schedules", "priority", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_schedules_due ON resident_schedules(status, next_due_at_ms)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resident_schedules_priority_due ON resident_schedules(status, priority DESC, next_due_at_ms)"
            )
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

    def _journal_event(self, kind: str, data: JsonObject, *, state_delta: JsonObject | None = None) -> None:
        if self.journal is None:
            return
        self.journal.append(
            task_id=None,
            run_id="resident-scheduler",
            step_id=None,
            kind=kind,
            data=data,
            state_delta=state_delta or {},
        )


def _validate_schedule(*, interval_ms: int | None, max_runs: int | None) -> None:
    if interval_ms is not None and int(interval_ms) < 0:
        raise ValueError("resident_schedule_interval_must_be_non_negative")
    if max_runs is not None and int(max_runs) <= 0:
        raise ValueError("resident_schedule_max_runs_must_be_positive")
    if (max_runs is None or max_runs > 1) and not interval_ms:
        raise ValueError("resident_schedule_repeating_requires_positive_interval")


def _schedule_row(schedule: ResidentSchedule) -> tuple[object, ...]:
    return (
        schedule.schedule_id,
        schedule.thread_id,
        schedule.text,
        schedule.source,
        schedule.status,
        schedule.created_at_ms,
        schedule.priority,
        schedule.next_due_at_ms,
        schedule.interval_ms,
        schedule.max_runs,
        schedule.run_count,
        schedule.last_enqueued_at_ms,
        schedule.last_message_id,
        _json(schedule.metadata),
    )


def _schedule_from_row(row) -> ResidentSchedule:
    return ResidentSchedule.from_dict(
        {
            "schedule_id": row[0],
            "thread_id": row[1],
            "text": row[2],
            "source": row[3],
            "status": row[4],
            "created_at_ms": int(row[5]),
            "priority": int(row[6]) if row[6] is not None else 0,
            "next_due_at_ms": int(row[7]) if row[7] is not None else None,
            "interval_ms": int(row[8]) if row[8] is not None else None,
            "max_runs": int(row[9]) if row[9] is not None else None,
            "run_count": int(row[10]),
            "last_enqueued_at_ms": int(row[11]) if row[11] is not None else None,
            "last_message_id": row[12],
            "metadata": _json_dict(row[13]),
        }
    )


def _schedule_by_id(conn: sqlite3.Connection, schedule_id: str) -> ResidentSchedule | None:
    row = conn.execute(
        """
        SELECT schedule_id, thread_id, text, source, status, created_at_ms,
               priority, next_due_at_ms, interval_ms, max_runs, run_count,
               last_enqueued_at_ms, last_message_id, metadata_json
        FROM resident_schedules
        WHERE schedule_id = ?
        """,
        (schedule_id,),
    ).fetchone()
    return _schedule_from_row(row) if row is not None else None


def _status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) FROM resident_schedules GROUP BY status").fetchall()
    return {str(status): int(count) for status, count in rows}


def _count(conn: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = conn.execute(query, values).fetchone()
    return int(row[0]) if row is not None else 0


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column in {str(row[1]) for row in rows}:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _clamp_limit(value: int, *, cap: int) -> int:
    return min(max(0, int(value)), cap)


def _normalize_priority(value: int) -> int:
    return max(-1000, min(1000, int(value)))


def _limit_diagnostics(*, requested_limit: int, effective_limit: int, limit_cap: int) -> JsonObject:
    diagnostics: JsonObject = {"limit": effective_limit}
    if effective_limit != requested_limit:
        diagnostics["requested_limit"] = requested_limit
        diagnostics["limit_cap"] = limit_cap
        diagnostics["limit_clamped"] = True
    return diagnostics


def _inspection_samples(
    schedules: list[ResidentSchedule],
    *,
    requested_sample_limit: int,
    effective_sample_limit: int,
) -> JsonObject:
    samples: JsonObject = {"schedules": [resident_schedule_event(schedule) for schedule in schedules]}
    if effective_sample_limit != requested_sample_limit:
        samples["requested_sample_limit"] = requested_sample_limit
        samples["sample_limit"] = effective_sample_limit
        samples["sample_limit_cap"] = RESIDENT_SCHEDULE_SAMPLE_LIMIT_CAP
        samples["sample_limit_clamped"] = True
    return samples


def _message_id(schedule: ResidentSchedule) -> str:
    return f"scheduled-{schedule.schedule_id}-{schedule.next_due_at_ms}"


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
