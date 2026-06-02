from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from kernel_v3.contracts import JsonObject, LedgerRecord
from kernel_v3.storage import default_thread_root, safe_storage_id


TRANSCRIPT_KINDS = {
    "chat_turn",
    "chat_routing_decision",
    "chat_pending_answer",
    "chat_command",
    "chat_agent_result",
    "chat_thread_event",
    "thread_summary",
}


class ThreadTranscriptStore:
    """User-facing per-thread transcript storage.

    The global JournalStore remains the authoritative audit log for model,
    tool, retrieval, and policy records. This store mirrors only chat-facing
    records so thread history can be inspected without scanning a monolithic
    ledger.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_thread_root()

    def append_journal_record(self, record: LedgerRecord) -> None:
        if record.kind not in TRANSCRIPT_KINDS:
            return
        thread_id = _record_thread_id(record)
        if thread_id is None:
            return
        entry = _transcript_entry(record, thread_id=thread_id)
        self._append(thread_id, entry)

    def ensure_thread(self, thread_id: str) -> Path:
        path = self.thread_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        return path

    def thread_path(self, thread_id: str) -> Path:
        return self.root / safe_storage_id(thread_id) / "thread.jsonl"

    def records(self, thread_id: str, *, kind: str | None = None) -> list[JsonObject]:
        path = self.thread_path(thread_id)
        if not path.exists():
            return []
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if kind is not None:
            records = [record for record in records if record.get("kind") == kind]
        return records

    def threads(self) -> list[JsonObject]:
        if not self.root.exists():
            return []
        payload: list[JsonObject] = []
        for path in sorted(self.root.glob("*/thread.jsonl")):
            records = _load_records(path)
            if not records:
                continue
            thread_id = _thread_id_from_records(records, fallback=path.parent.name)
            turns = [record for record in records if record.get("kind") == "chat_turn"]
            latest = max(int(record.get("recorded_at_ms") or 0) for record in records)
            latest_result = _latest_record(records, "chat_agent_result")
            payload.append(
                {
                    "thread_id": thread_id,
                    "turn_count": len(turns),
                    "last_recorded_at_ms": latest,
                    "last_result_status": _record_data(latest_result).get("status") if latest_result else None,
                    "pending_question": _latest_pending(records),
                    "transcript_path": str(path),
                }
            )
        return sorted(payload, key=lambda item: (-int(item.get("last_recorded_at_ms") or 0), str(item.get("thread_id") or "")))

    def _append(self, thread_id: str, entry: JsonObject) -> None:
        path = self.thread_path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _transcript_entry(record: LedgerRecord, *, thread_id: str) -> JsonObject:
    return {
        "schema_version": 1,
        "thread_id": thread_id,
        "record_id": record.record_id,
        "task_id": record.task_id,
        "run_id": record.run_id,
        "step_id": record.step_id,
        "kind": record.kind,
        "data": record.data,
        "recorded_at_ms": record.recorded_at_ms,
        "payload_hash": record.payload_hash,
        "artifact_refs": list(record.artifact_refs),
    }


def _record_thread_id(record: LedgerRecord) -> str | None:
    data = record.data if isinstance(record.data, dict) else {}
    state_delta = record.state_delta if isinstance(record.state_delta, dict) else {}
    value = data.get("thread_id") or state_delta.get("thread_id")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _load_records(path: Path) -> list[JsonObject]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _thread_id_from_records(records: Iterable[JsonObject], *, fallback: str) -> str:
    for record in records:
        value = record.get("thread_id")
        if isinstance(value, str) and value:
            return value
        data = _record_data(record)
        value = data.get("thread_id")
        if isinstance(value, str) and value:
            return value
    return fallback


def _latest_record(records: list[JsonObject], kind: str) -> JsonObject | None:
    for record in reversed(records):
        if record.get("kind") == kind:
            return record
    return None


def _record_data(record: JsonObject | None) -> JsonObject:
    data = record.get("data") if isinstance(record, dict) else None
    return data if isinstance(data, dict) else {}


def _latest_pending(records: list[JsonObject]) -> bool:
    latest_result = _latest_record(records, "chat_agent_result")
    if latest_result is None:
        return False
    data = _record_data(latest_result)
    pending = data.get("pending_question")
    return isinstance(pending, dict) and bool(pending.get("question"))
