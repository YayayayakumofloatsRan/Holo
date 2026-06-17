from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from kernel_v3.contracts import JsonObject, LedgerRecord
from kernel_v3.text_safety import replace_lone_surrogates, sanitize_json_object, sanitize_json_value


def _canonical_json(payload: object) -> str:
    return json.dumps(sanitize_json_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class JournalStore:
    SCHEMA_VERSION = 1

    def __init__(
        self,
        journal_path: Path | str | None = None,
        *,
        index_path: Path | str | None = None,
    ) -> None:
        self.path = Path(journal_path) if journal_path is not None else None
        self.index_path = Path(index_path) if index_path is not None else None
        self._records: list[LedgerRecord] = []
        self.load_warnings: list[JsonObject] = []
        if self.path is not None and self.path.exists():
            self._records = self._load_records(self.path)
        if self.index_path is not None:
            self._rebuild_index()

    @classmethod
    def in_memory(cls) -> "JournalStore":
        return cls()

    def append(
        self,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        kind: str,
        data: JsonObject,
        event_ref: str | None = None,
        action_ref: str | None = None,
        observation_ref: str | None = None,
        feedback_ref: str | None = None,
        state_delta: JsonObject | None = None,
        artifact_refs: list[str] | None = None,
    ) -> LedgerRecord:
        safe_data = sanitize_json_object(data)
        safe_state_delta = sanitize_json_object(state_delta or {})
        record = LedgerRecord(
            schema_version=self.SCHEMA_VERSION,
            record_id=f"ledger-{len(self._records) + 1}",
            task_id=replace_lone_surrogates(task_id) if task_id is not None else None,
            run_id=replace_lone_surrogates(run_id),
            step_id=replace_lone_surrogates(step_id) if step_id is not None else None,
            kind=replace_lone_surrogates(kind),
            data=safe_data,
            recorded_at_ms=len(self._records) + 1,
            event_ref=replace_lone_surrogates(event_ref) if event_ref is not None else None,
            action_ref=replace_lone_surrogates(action_ref) if action_ref is not None else None,
            observation_ref=replace_lone_surrogates(observation_ref) if observation_ref is not None else None,
            feedback_ref=replace_lone_surrogates(feedback_ref) if feedback_ref is not None else None,
            state_delta=safe_state_delta,
            artifact_refs=[replace_lone_surrogates(ref) for ref in list(artifact_refs or [])],
            payload_hash=_payload_hash(safe_data),
        )
        self._records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(record.to_dict()) + "\n")
        if self.index_path is not None:
            self._insert_index(record)
        return record

    def records(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        kind: str | None = None,
    ) -> list[LedgerRecord]:
        records = self._records
        if task_id is not None:
            records = [record for record in records if record.task_id == task_id]
        if run_id is not None:
            records = [record for record in records if record.run_id == run_id]
        if kind is not None:
            records = [record for record in records if record.kind == kind]
        return list(records)

    def require_task(self, task_id: str) -> list[LedgerRecord]:
        records = self.records(task_id=task_id)
        if not records:
            raise ValueError(f"unknown task_id: {task_id}")
        return records

    def has_record(self, record_id: str) -> bool:
        if self.index_path is not None:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM journal_index WHERE record_id = ? LIMIT 1",
                    (record_id,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()
        return any(record.record_id == record_id for record in self._records)

    def index_records(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        kind: str | None = None,
    ) -> list[JsonObject]:
        if self.index_path is None:
            raise RuntimeError("index_path is not configured")
        clauses = []
        values: list[str] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            values.append(task_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            values.append(run_id)
        if kind is not None:
            clauses.append("kind = ?")
            values.append(kind)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT
                    record_id,
                    task_id,
                    run_id,
                    step_id,
                    kind,
                    event_ref,
                    action_ref,
                    observation_ref,
                    feedback_ref,
                    payload_hash,
                    recorded_at_ms
                FROM journal_index
                """
                + where
                + " ORDER BY recorded_at_ms",
                values,
            )
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        if self.index_path is None:
            raise RuntimeError("index_path is not configured")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.index_path)

    def _load_records(self, path: Path) -> list[LedgerRecord]:
        records: list[LedgerRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(LedgerRecord.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    self.load_warnings.append(
                        {
                            "path": str(path),
                            "line_number": line_number,
                            "error": type(exc).__name__,
                            "preview": line.strip()[:200],
                        }
                    )
        return records

    def _rebuild_index(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journal_index (
                    record_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    kind TEXT NOT NULL,
                    event_ref TEXT,
                    action_ref TEXT,
                    observation_ref TEXT,
                    feedback_ref TEXT,
                    payload_hash TEXT NOT NULL,
                    recorded_at_ms INTEGER NOT NULL
                )
                """
            )
            for record in self._records:
                self._insert_index(record, conn=conn)
            conn.commit()
        finally:
            conn.close()

    def _insert_index(self, record: LedgerRecord, *, conn: sqlite3.Connection | None = None) -> None:
        owns_conn = conn is None
        connection = conn or self._connect()
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO journal_index (
                    record_id,
                    task_id,
                    run_id,
                    step_id,
                    kind,
                    event_ref,
                    action_ref,
                    observation_ref,
                    feedback_ref,
                    payload_hash,
                    recorded_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.task_id,
                    record.run_id,
                    record.step_id,
                    record.kind,
                    record.event_ref,
                    record.action_ref,
                    record.observation_ref,
                    record.feedback_ref,
                    record.payload_hash,
                    record.recorded_at_ms,
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()


Journal = JournalStore
