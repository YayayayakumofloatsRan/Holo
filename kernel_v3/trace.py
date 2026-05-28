from __future__ import annotations

from kernel_v3.journal import JournalStore


class TraceRenderer:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal

    def render_task(self, task_id: str) -> str:
        records = self.journal.records(task_id=task_id)
        lines = [f"Trace {task_id}"]
        for record in records:
            refs = []
            if record.event_ref:
                refs.append(f"event={record.event_ref}")
            if record.action_ref:
                refs.append(f"action={record.action_ref}")
            if record.observation_ref:
                refs.append(f"observation={record.observation_ref}")
            if record.feedback_ref:
                refs.append(f"feedback={record.feedback_ref}")
            ref_text = " ".join(refs)
            lines.append(
                f"{record.run_id} {record.step_id or '-'} {record.kind} {ref_text} "
                f"state_delta={record.state_delta}"
            )
        return "\n".join(lines)
