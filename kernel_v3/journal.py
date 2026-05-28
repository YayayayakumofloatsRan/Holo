from __future__ import annotations

import json
from pathlib import Path

from kernel_v3.contracts import JsonObject, LedgerRecord


class Journal:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: list[LedgerRecord] = []
        if self.path is not None and self.path.exists():
            self._records = [
                LedgerRecord.from_dict(json.loads(line))
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    @classmethod
    def in_memory(cls) -> "Journal":
        return cls()

    def append(
        self,
        *,
        task_id: str | None,
        run_id: str,
        step_id: str | None,
        kind: str,
        data: JsonObject,
    ) -> LedgerRecord:
        record = LedgerRecord(
            record_id=f"ledger-{len(self._records) + 1}",
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind=kind,
            data=data,
            recorded_at_ms=len(self._records) + 1,
        )
        self._records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def records(self, *, task_id: str | None = None) -> list[LedgerRecord]:
        if task_id is None:
            return list(self._records)
        return [record for record in self._records if record.task_id == task_id]

    def require_task(self, task_id: str) -> list[LedgerRecord]:
        records = self.records(task_id=task_id)
        if not records:
            raise ValueError(f"unknown task_id: {task_id}")
        return records
