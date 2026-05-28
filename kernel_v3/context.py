from __future__ import annotations

from kernel_v3.contracts import ContextBundle
from kernel_v3.journal import Journal
from kernel_v3.session import TaskState


class ContextCompiler:
    def compile(self, task: TaskState, journal: Journal) -> ContextBundle:
        records = journal.records(task_id=task.task_id)
        event_ids = [
            str(record.data["event_id"])
            for record in records
            if record.kind in {"event", "resume"} and "event_id" in record.data
        ]
        return ContextBundle(
            context_id=f"ctx-{task.run_id}-{len(records) + 1}",
            thread_key=task.thread_id,
            event_ids=event_ids,
            memory_refs=[],
            state={
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "journal_records": len(records),
            },
            token_budget=4096,
        )
