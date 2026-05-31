from __future__ import annotations

from kernel_v3.journal import JournalStore


RESIDENT_TRACE_LIMIT_CAP = 500


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
            if record.kind.startswith("retrieval_"):
                lines.extend(self._retrieval_lines(record))
            elif record.kind == "action":
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

    def render_memory_trace(self, task_id: str) -> str:
        records = self.journal.records(task_id=task_id)
        lines = [f"Memory Trace {task_id}"]
        for record in records:
            if record.kind.startswith("memory_"):
                data = record.data
                lines.append(
                    f"{record.run_id} {record.step_id or '-'} {record.kind} "
                    f"proposal={data.get('proposal_id')} memory={data.get('memory_id')} "
                    f"status={data.get('approval_status') or data.get('reason') or data.get('status')} "
                    f"source={data.get('source_record_ref')}"
                )
        return "\n".join(lines)

    def render_resident_trace(self, *, limit: int = 200) -> str:
        all_records = [record for record in self.journal.records() if record.kind.startswith("resident_")]
        effective_limit = _clamp_limit(limit, cap=RESIDENT_TRACE_LIMIT_CAP)
        records = all_records[-effective_limit:] if effective_limit else []
        lines = [f"Resident Trace total={len(all_records)} shown={len(records)}"]
        if len(all_records) > len(records):
            lines.append(
                f"... truncated {len(all_records) - len(records)} older resident records "
                f"(limit={effective_limit}, cap={RESIDENT_TRACE_LIMIT_CAP})"
            )
        for record in records:
            data = record.data
            lines.append(
                f"{record.run_id} {record.kind} "
                f"task={record.task_id or '-'} "
                f"message={data.get('message_id') or data.get('in_reply_to') or '-'} "
                f"outbox={data.get('outbox_id') or '-'} "
                f"status={data.get('status') or data.get('reason') or record.state_delta}"
            )
        return "\n".join(lines)

    def _retrieval_lines(self, record) -> list[str]:
        data = record.data
        step = record.step_id or "-"
        kind = record.kind
        if kind == "retrieval_query_plan":
            queries = data.get("queries", [])
            return [
                f"{step} query_plan={data.get('plan_id')} goal={data.get('goal_id')} "
                f"queries={len(queries) if isinstance(queries, list) else 0}"
            ]
        if kind == "retrieval_search_attempt":
            sources = data.get("sources", [])
            return [
                f"{step} search={data.get('attempt_id')} status={data.get('status')} "
                f"query={data.get('query')} sources={len(sources) if isinstance(sources, list) else 0}"
            ]
        if kind == "retrieval_rank_sources":
            ranked = data.get("ranked_sources", [])
            return [
                f"{step} rank={data.get('ranking_id')} "
                f"sources={len(ranked) if isinstance(ranked, list) else 0}"
            ]
        if kind == "retrieval_fetch_attempt":
            return [
                f"{step} fetch={data.get('fetch_id')} status={data.get('status')} "
                f"uri={data.get('uri')} artifact={data.get('artifact_id')} "
                f"hash={data.get('payload_hash')} size={data.get('size_bytes')} "
                f"preview={_preview(str(data.get('preview', '')), 96)}"
            ]
        if kind == "retrieval_extraction":
            spans = data.get("spans", [])
            document = data.get("document", {})
            artifact_id = document.get("artifact_id") if isinstance(document, dict) else None
            return [
                f"{step} extraction document={_nested(data, 'document', 'document_id')} "
                f"artifact={artifact_id} spans={len(spans) if isinstance(spans, list) else 0}"
            ]
        if kind == "retrieval_evidence":
            return [
                f"{step} evidence={data.get('evidence_id')} source={data.get('source_id')} "
                f"artifact={data.get('artifact_id')} score={data.get('score')} "
                f"text={_preview(str(data.get('text', '')), 96)}"
            ]
        if kind == "retrieval_citation":
            return [
                f"{step} citation={data.get('citation_id')} evidence={data.get('evidence_id')} "
                f"artifact={data.get('artifact_id')} quote={_preview(str(data.get('quote', '')), 96)}"
            ]
        if kind == "retrieval_evaluation_decision":
            return [
                f"{step} evaluation={data.get('decision_id') or data.get('evaluation_id')} "
                f"sufficient={data.get('sufficient')} "
                f"reason={data.get('reason')}"
            ]
        if kind == "retrieval_report":
            diagnostics = data.get("diagnostics", {})
            evidence_count = diagnostics.get("evidence_count") if isinstance(diagnostics, dict) else None
            citation_count = diagnostics.get("citation_count") if isinstance(diagnostics, dict) else None
            return [
                f"{step} report={data.get('report_id')} status={data.get('status')} "
                f"evidence={evidence_count} citations={citation_count} artifacts={record.artifact_refs}"
            ]
        return []

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
        if record.kind == "processor_request":
            return [
                f"  processor_request task_type={record.data.get('task_type')} "
                f"provider={record.data.get('provider')} model={record.data.get('model')} "
                f"prompt_hash={_nested(record.data, 'prompt', 'hash')}"
            ]
        if record.kind == "processor_result":
            return [
                f"  processor_result status={record.data.get('status')} "
                f"task_type={record.data.get('task_type')} provider={record.data.get('provider')} "
                f"model={record.data.get('model')} duration_ms={record.data.get('duration_ms')} "
                f"usage={record.data.get('usage', {})} error={record.data.get('error')}"
            ]
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


def _nested(data, *path):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _clamp_limit(value: int, *, cap: int) -> int:
    return min(max(0, int(value)), cap)
