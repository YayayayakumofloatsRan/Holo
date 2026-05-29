from __future__ import annotations

from kernel_v3.journal import JournalStore


class TraceRenderer:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal

    def render_task(self, task_id: str, *, verbose: bool = False) -> str:
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
            if verbose:
                lines.extend(self._verbose_lines(record))
        return "\n".join(lines)

    def render_evidence(self, task_id: str) -> str:
        records = self.journal.records(task_id=task_id, kind="observation")
        lines = [f"Evidence {task_id}"]
        for record in records:
            data = record.data
            lines.append(
                f"{data.get('observation_id', record.observation_ref)} "
                f"{data.get('kind', '')} {data.get('status', '')} {data.get('source', '')} "
                f"artifacts={record.artifact_refs}"
            )
        return "\n".join(lines)

    def render_artifacts(self, task_id: str) -> str:
        records = self.journal.records(task_id=task_id)
        lines = [f"Artifacts {task_id}"]
        seen: set[str] = set()
        for record in records:
            for artifact_id in record.artifact_refs:
                if artifact_id in seen:
                    continue
                seen.add(artifact_id)
                lines.append(f"{artifact_id} record={record.record_id} step={record.step_id or '-'}")
        return "\n".join(lines)

    def render_retrieval_trace(self, task_id: str) -> str:
        records = self.journal.records(task_id=task_id)
        lines = [f"Retrieval Trace {task_id}"]
        for record in records:
            if record.kind == "action":
                payload = record.data.get("payload", {})
                if isinstance(payload, dict) and "query" in payload:
                    lines.append(
                        f"{record.step_id or '-'} action={record.action_ref} "
                        f"tool={record.data.get('name')} query={payload.get('query')}"
                    )
                if isinstance(payload, dict) and "url" in payload:
                    lines.append(
                        f"{record.step_id or '-'} action={record.action_ref} "
                        f"tool={record.data.get('name')} url={payload.get('url')}"
                    )
            elif record.kind == "observation":
                data = record.data
                content = data.get("content", {})
                extract_length = self._extract_length(content)
                lines.append(
                    f"{record.step_id or '-'} observation={record.observation_ref} "
                    f"status={data.get('status')} source={data.get('source')} "
                    f"extract_length={extract_length} artifacts={record.artifact_refs}"
                )
            elif record.kind == "feedback":
                missing = record.data.get("missing_evidence", [])
                if missing:
                    lines.append(f"{record.step_id or '-'} why_continue={', '.join(map(str, missing))}")
                stop_reason = record.data.get("stop_reason")
                if stop_reason:
                    lines.append(f"{record.step_id or '-'} why_stop={stop_reason}")
        return "\n".join(lines)

    def _verbose_lines(self, record) -> list[str]:
        if record.kind == "policy_decision":
            return [f"  policy allowed={record.data.get('allowed')} reason={record.data.get('reason')}"]
        if record.kind == "observation":
            return [
                f"  observation status={record.data.get('status')} source={record.data.get('source')} "
                f"artifacts={record.artifact_refs}"
            ]
        if record.kind == "feedback":
            return [
                f"  feedback status={record.data.get('status')} "
                f"missing_evidence={record.data.get('missing_evidence', [])} "
                f"stop_reason={record.data.get('stop_reason')}"
            ]
        if record.kind == "action":
            return [
                f"  action kind={record.data.get('kind')} name={record.data.get('name')} "
                f"payload={record.data.get('payload', {})}"
            ]
        if record.kind == "guard":
            return [f"  guard stop_reason={record.data.get('stop_reason')} data={record.data}"]
        return []

    def _extract_length(self, content) -> int:
        if isinstance(content, str):
            return len(content)
        if isinstance(content, dict):
            total = 0
            for value in content.values():
                if isinstance(value, str):
                    total += len(value)
                elif isinstance(value, list):
                    total += sum(self._extract_length(item) for item in value)
                elif isinstance(value, dict):
                    total += self._extract_length(value)
            return total
        return 0
