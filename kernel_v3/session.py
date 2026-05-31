from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from kernel_v3.journal import JournalStore


@dataclass(frozen=True)
class TaskState:
    task_id: str
    run_id: str
    thread_id: str
    input_text: str
    status: str
    step_id: str


class SessionEngine:
    def __init__(self, journal: JournalStore | None = None) -> None:
        self.journal = journal

    @classmethod
    def from_journal(cls, journal: JournalStore) -> "SessionEngine":
        return cls(journal)

    def start(
        self,
        input_text: str,
        *,
        thread_id: str = "local:default",
        journal: JournalStore | None = None,
        record_state: bool = True,
    ) -> TaskState:
        source = self._journal(journal)
        task_id = f"task-{self._next_task_index(source)}"
        run_id = "run-1"
        state = TaskState(
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            input_text=input_text,
            status="running",
            step_id="step-0",
        )
        if source is not None and record_state:
            source.append(
                task_id=task_id,
                run_id=run_id,
                step_id=state.step_id,
                kind="session_state",
                data=_state_data(state),
                state_delta={"status": state.status},
            )
        return state

    def resume(
        self,
        task_id: str,
        input_text: str,
        run_index: int | None = None,
        *,
        thread_id: str,
        journal: JournalStore | None = None,
        record_state: bool = True,
    ) -> TaskState:
        source = self._journal(journal)
        if run_index is None:
            if source is None:
                raise ValueError("run_index is required when no journal is configured")
            run_index = self._next_run_index(source, task_id)
        state = TaskState(
            task_id=task_id,
            run_id=f"run-{run_index}",
            thread_id=thread_id,
            input_text=input_text,
            status="running",
            step_id="step-0",
        )
        if source is not None and record_state:
            source.append(
                task_id=task_id,
                run_id=state.run_id,
                step_id=state.step_id,
                kind="session_state",
                data=_state_data(state),
                state_delta={"status": state.status},
            )
        return state

    def replay(self, task_id: str) -> Iterable[object]:
        source = self._journal(None)
        if source is None:
            raise ValueError("replay requires a journal")
        return source.records(task_id=task_id)

    def active_task(self, task_id: str) -> TaskState:
        source = self._journal(None)
        if source is None:
            raise ValueError("active_task requires a journal")
        records = source.require_task(task_id)
        task_record = next((record for record in records if record.kind in {"task", "session_state"}), None)
        if task_record is None:
            raise ValueError(f"task has no state record: {task_id}")
        latest = records[-1]
        return TaskState(
            task_id=task_id,
            run_id=latest.run_id,
            thread_id=str(task_record.data.get("thread_id", "local:default")),
            input_text=str(task_record.data.get("input_text", "")),
            status=str(latest.state_delta.get("status", task_record.data.get("status", "running"))),
            step_id=latest.step_id or "step-0",
        )

    def _journal(self, override: JournalStore | None) -> JournalStore | None:
        return override or self.journal

    def _next_task_index(self, journal: JournalStore | None) -> int:
        if journal is None:
            return 1
        task_ids = {
            int(record.task_id.split("-", 1)[1])
            for record in journal.records()
            if record.kind in {"task", "session_state"}
            and record.task_id
            and record.task_id.startswith("task-")
            and record.task_id.split("-", 1)[1].isdigit()
        }
        return max(task_ids, default=0) + 1

    def _next_run_index(self, journal: JournalStore, task_id: str) -> int:
        run_ids = {
            int(record.run_id.split("-", 1)[1])
            for record in journal.records(task_id=task_id)
            if record.kind in {"run", "session_state"}
            and record.run_id.startswith("run-")
            and record.run_id.split("-", 1)[1].isdigit()
        }
        return max(run_ids, default=0) + 1


def _state_data(state: TaskState) -> dict[str, str]:
    return {
        "task_id": state.task_id,
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "input_text": state.input_text,
        "status": state.status,
        "step_id": state.step_id,
    }
