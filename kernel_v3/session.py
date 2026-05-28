from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskState:
    task_id: str
    run_id: str
    input_text: str
    status: str


class SessionEngine:
    def __init__(self) -> None:
        self._next_task = 1
        self._next_run = 1

    def start(self, input_text: str) -> TaskState:
        task = TaskState(
            task_id=f"task-{self._next_task}",
            run_id=f"run-{self._next_run}",
            input_text=input_text,
            status="running",
        )
        self._next_task += 1
        self._next_run += 1
        return task

    def resume(self, task_id: str, input_text: str, run_index: int) -> TaskState:
        return TaskState(
            task_id=task_id,
            run_id=f"run-{run_index}",
            input_text=input_text,
            status="running",
        )
