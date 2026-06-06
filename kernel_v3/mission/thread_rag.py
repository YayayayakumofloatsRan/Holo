from __future__ import annotations

import hashlib
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject, LedgerRecord
from kernel_v3.journal import JournalStore


@dataclass(frozen=True, kw_only=True)
class ThreadRagConfig:
    recent_turn_limit: int = 12
    recent_result_limit: int = 8
    recent_trace_limit: int = 24
    text_preview_chars: int = 640


class ThreadWorkingMemoryProvider:
    def __init__(self, *, config: ThreadRagConfig | None = None) -> None:
        self.config = config or ThreadRagConfig()

    def compile(
        self,
        journal: JournalStore,
        *,
        thread_id: str,
        task_id: str | None = None,
        mission_id: str | None = None,
    ) -> JsonObject:
        turns = _thread_records(journal, thread_id, kind="chat_turn")[-self.config.recent_turn_limit :]
        results = _thread_records(journal, thread_id, kind="chat_agent_result")[-self.config.recent_result_limit :]
        trace = _task_trace(journal, task_id, limit=self.config.recent_trace_limit) if task_id else []
        evidence_refs = _recent_refs(journal, task_id=task_id, kind="retrieval_evidence", key="evidence_id")
        citation_refs = _recent_refs(journal, task_id=task_id, kind="retrieval_citation", key="citation_id")
        failure_diagnostics = _recent_failure_diagnostics(journal, task_id=task_id)
        task_trace = trace
        recent_results = [_compact_result(record, preview_chars=self.config.text_preview_chars) for record in results]
        payload = {
            "kind": "thread_rag_context",
            "thread_id": thread_id,
            "task_id": task_id,
            "mission_id": mission_id,
            "recent_turns": [_compact_turn(record, preview_chars=self.config.text_preview_chars) for record in turns],
            "recent_results": recent_results,
            "recent_task_trace": task_trace,
            "evidence_refs": evidence_refs,
            "citation_refs": citation_refs,
            "failure_diagnostics": failure_diagnostics,
        }
        payload["attention_blocks"] = _attention_blocks(
            recent_results=recent_results,
            recent_task_trace=task_trace,
            evidence_refs=evidence_refs,
            citation_refs=citation_refs,
            failure_diagnostics=failure_diagnostics,
        )
        payload["context_hash"] = _hash_payload(payload)
        return payload


def collect_run_delta(journal: JournalStore, *, task_id: str, run_id: str) -> JsonObject:
    records = [record for record in journal.records(task_id=task_id) if record.run_id == run_id]
    actions = [record for record in records if record.kind == "action"]
    observations = [record for record in records if record.kind == "observation"]
    retrieval_reports = [record for record in records if record.kind == "retrieval_report"]
    evidence = [record for record in records if record.kind == "retrieval_evidence"]
    citations = [record for record in records if record.kind == "retrieval_citation"]
    failures = [record for record in records if record.kind == "agent_failure_report"]
    finals = [record for record in records if record.kind == "agent_final_answer"]
    terminations = [record for record in records if record.kind == "termination_decision"]
    feedback = [record for record in records if record.kind == "feedback"]
    return {
        "task_id": task_id,
        "run_id": run_id,
        "actions": [_compact_action(record) for record in actions],
        "observations": [_compact_observation(record) for record in observations[-8:]],
        "retrieval_reports": [_compact_retrieval_report(record) for record in retrieval_reports[-4:]],
        "evidence_refs": _record_refs(evidence, key="evidence_id"),
        "citation_refs": _record_refs(citations, key="citation_id"),
        "failure_reports": [_compact_failure(record) for record in failures[-2:]],
        "final_answers": [_compact_final(record) for record in finals[-2:]],
        "termination_decisions": [_compact_termination(record) for record in terminations[-4:]],
        "feedback": [_compact_feedback(record) for record in feedback[-4:]],
        "record_refs": [record.record_id for record in records],
        "record_count": len(records),
    }


def _thread_records(journal: JournalStore, thread_id: str, *, kind: str) -> list[LedgerRecord]:
    return [record for record in journal.records(kind=kind) if record.data.get("thread_id") == thread_id]


def _task_trace(journal: JournalStore, task_id: str | None, *, limit: int) -> list[JsonObject]:
    if not task_id:
        return []
    kinds = {
        "action",
        "observation",
        "retrieval_report",
        "feedback",
        "host_situation",
        "termination_decision",
        "agent_failure_report",
        "agent_final_answer",
        "mission_assessment",
        "mission_directive",
    }
    records = [record for record in journal.records(task_id=task_id) if record.kind in kinds]
    return [_compact_trace(record) for record in records[-limit:]]


def _recent_refs(journal: JournalStore, *, task_id: str | None, kind: str, key: str) -> list[str]:
    if not task_id:
        return []
    records = journal.records(task_id=task_id, kind=kind)
    return _record_refs(records[-12:], key=key)


def _record_refs(records: list[LedgerRecord], *, key: str) -> list[str]:
    refs: list[str] = []
    for record in records:
        value = record.data.get(key) or record.record_id
        if isinstance(value, str) and value:
            refs.append(value)
    return _ordered_unique(refs)


def _recent_failure_diagnostics(journal: JournalStore, *, task_id: str | None) -> list[JsonObject]:
    if not task_id:
        return []
    records = journal.records(task_id=task_id, kind="agent_failure_report")[-4:]
    return [_compact_failure(record) for record in records]


def _compact_turn(record: LedgerRecord, *, preview_chars: int) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "turn_id": record.data.get("turn_id"),
        "role": record.data.get("role"),
        "task_id": record.data.get("task_id"),
        "text_preview": _preview(str(record.data.get("text") or ""), preview_chars),
    }


def _compact_result(record: LedgerRecord, *, preview_chars: int) -> JsonObject:
    failure = record.data.get("failure_report") if isinstance(record.data.get("failure_report"), dict) else None
    return {
        "record_ref": record.record_id,
        "task_id": record.data.get("task_id"),
        "run_id": record.data.get("run_id"),
        "route": record.data.get("route"),
        "status": record.data.get("status"),
        "answer_preview": _preview(str(record.data.get("answer") or ""), preview_chars),
        "failure_reason": failure.get("reason") if failure else None,
    }


def _compact_trace(record: LedgerRecord) -> JsonObject:
    if record.kind == "action":
        return _compact_action(record)
    if record.kind == "observation":
        return _compact_observation(record)
    if record.kind == "retrieval_report":
        return _compact_retrieval_report(record)
    if record.kind == "feedback":
        return _compact_feedback(record)
    if record.kind == "host_situation":
        return _compact_host_situation(record)
    if record.kind == "termination_decision":
        return _compact_termination(record)
    if record.kind == "agent_failure_report":
        return _compact_failure(record)
    if record.kind == "agent_final_answer":
        return _compact_final(record)
    return {"record_ref": record.record_id, "kind": record.kind}


def _compact_action(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "action",
        "action_id": record.data.get("action_id"),
        "action_kind": record.data.get("kind"),
        "name": record.data.get("name"),
        "side_effect_class": record.data.get("side_effect_class"),
        "payload_hash": _hash_payload(record.data.get("payload", {})),
        "description": _preview(str(record.data.get("description") or ""), 240),
        "reasons": _string_list(record.data.get("reasons"))[:4],
    }


def _compact_observation(record: LedgerRecord) -> JsonObject:
    content = record.data.get("content")
    return {
        "record_ref": record.record_id,
        "kind": "observation",
        "source": record.data.get("source"),
        "status": record.data.get("status"),
        "content_preview": _preview(str(content), 360),
        "content_hash": _hash_payload(content),
    }


def _compact_retrieval_report(record: LedgerRecord) -> JsonObject:
    diagnostics = record.data.get("diagnostics") if isinstance(record.data.get("diagnostics"), dict) else {}
    failure_attribution = diagnostics.get("failure_attribution") if isinstance(diagnostics.get("failure_attribution"), dict) else {}
    source_quality = diagnostics.get("source_quality") if isinstance(diagnostics.get("source_quality"), dict) else {}
    source_authority = diagnostics.get("source_authority") if isinstance(diagnostics.get("source_authority"), dict) else {}
    search_summaries = diagnostics.get("search_summaries")
    attempted_queries = []
    if isinstance(search_summaries, list):
        attempted_queries = [
            str(item.get("query"))
            for item in search_summaries
            if isinstance(item, dict) and isinstance(item.get("query"), str) and item.get("query")
        ]
    return {
        "record_ref": record.record_id,
        "kind": "retrieval_report",
        "report_id": record.data.get("report_id"),
        "status": record.data.get("status"),
        "goal_id": record.data.get("goal_id"),
        "goal_query": _preview(str(diagnostics.get("goal_query") or ""), 240),
        "attempted_queries": attempted_queries[-12:],
        "preview": _preview(str(record.data.get("preview") or ""), 360),
        "reason": diagnostics.get("reason"),
        "missing_query_facets": _string_list(diagnostics.get("missing_query_facets")),
        "missing_finance_facets": _string_list(diagnostics.get("missing_finance_facets")),
        "rejected_evidence_count": diagnostics.get("rejected_evidence_count"),
        "failure_attribution": {
            "primary_failure_mode": failure_attribution.get("primary_failure_mode"),
            "next_strategy_hint": failure_attribution.get("next_strategy_hint"),
            "reason": failure_attribution.get("reason"),
        } if failure_attribution else {},
        "source_quality": {
            "authority_requirement": source_quality.get("authority_requirement"),
            "authority_sufficient": source_quality.get("authority_sufficient"),
            "acceptable_source_count": source_quality.get("acceptable_source_count"),
            "primary_source_count": source_quality.get("primary_source_count"),
            "secondary_source_count": source_quality.get("secondary_source_count"),
            "weak_source_count": source_quality.get("weak_source_count"),
            "recommended_next_source_action": source_quality.get("recommended_next_source_action"),
        } if source_quality else {},
        "source_authority": {
            "primary_source_count": source_authority.get("primary_source_count"),
            "secondary_source_count": source_authority.get("secondary_source_count"),
            "weak_source_count": source_authority.get("weak_source_count"),
            "best_authority_score": source_authority.get("best_authority_score"),
        } if source_authority else {},
    }


def _compact_failure(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "agent_failure_report",
        "reason": record.data.get("reason"),
        "missing_evidence": _string_list(record.data.get("missing_evidence")),
        "next_possible_action": record.data.get("next_possible_action"),
        "attempted_actions": _string_list(record.data.get("attempted_actions")),
        "user_help_needed": record.data.get("user_help_needed"),
    }


def _compact_final(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "agent_final_answer",
        "citation_refs": _string_list(record.data.get("citation_refs")),
        "used_evidence": _string_list(record.data.get("used_evidence")),
        "confidence": record.data.get("confidence"),
        "answer_preview": _preview(str(record.data.get("answer") or ""), 480),
    }


def _compact_termination(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "termination_decision",
        "decision": record.data.get("decision"),
        "reason": record.data.get("reason"),
        "feedback_status": record.data.get("feedback_status"),
        "override": record.data.get("override"),
    }


def _compact_feedback(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "feedback",
        "status": record.data.get("status"),
        "stop_reason": record.data.get("stop_reason"),
        "missing_evidence": _string_list(record.data.get("missing_evidence")),
    }


def _compact_host_situation(record: LedgerRecord) -> JsonObject:
    data = record.data
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
    activity = data.get("recent_activity") if isinstance(data.get("recent_activity"), dict) else {}
    failure = data.get("failure") if isinstance(data.get("failure"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "host_situation",
        "phase": record.state_delta.get("host_situation"),
        "task_mode": task.get("mode"),
        "citations_required": task.get("citations_required"),
        "retrieval_configured": retrieval.get("configured"),
        "live_search_available": retrieval.get("live_search_available"),
        "live_fetch_available": retrieval.get("live_fetch_available"),
        "retrieval_runs": activity.get("retrieval_runs"),
        "search_attempts": activity.get("search_attempts"),
        "fetch_attempts": activity.get("fetch_attempts"),
        "successful_fetches": activity.get("successful_fetches"),
        "latest_retrieval_status": activity.get("latest_retrieval_status"),
        "failure_diagnosis": failure.get("diagnosis"),
        "failure_reason": failure.get("reason"),
        "next_possible_action": failure.get("next_possible_action"),
    }


def _attention_blocks(
    *,
    recent_results: list[JsonObject],
    recent_task_trace: list[JsonObject],
    evidence_refs: list[str],
    citation_refs: list[str],
    failure_diagnostics: list[JsonObject],
) -> list[JsonObject]:
    blocks: list[JsonObject] = []
    if failure_diagnostics:
        latest = failure_diagnostics[-1]
        blocks.append(
            {
                "block_id": f"attention-failure-{latest.get('record_ref')}",
                "kind": "recent_failure",
                "priority": 0.96,
                "summary": _preview(
                    f"Last failure: {latest.get('reason')}; missing={', '.join(_string_list(latest.get('missing_evidence'))[:4])}",
                    360,
                ),
                "refs": [str(latest.get("record_ref"))] if latest.get("record_ref") else [],
            }
        )
    finals = [item for item in recent_results if item.get("status") == "completed" and item.get("answer_preview")]
    if finals:
        latest = finals[-1]
        blocks.append(
            {
                "block_id": f"attention-answer-{latest.get('record_ref')}",
                "kind": "recent_final_answer",
                "priority": 0.82,
                "summary": _preview(str(latest.get("answer_preview") or ""), 360),
                "refs": [str(latest.get("record_ref"))] if latest.get("record_ref") else [],
            }
        )
    if evidence_refs or citation_refs:
        blocks.append(
            {
                "block_id": "attention-current-evidence",
                "kind": "current_evidence",
                "priority": 0.9,
                "summary": f"Current task has {len(evidence_refs)} evidence refs and {len(citation_refs)} citation refs.",
                "refs": [*evidence_refs[:6], *citation_refs[:6]],
            }
        )
    if recent_task_trace:
        latest_trace = recent_task_trace[-1]
        blocks.append(
            {
                "block_id": f"attention-trace-{latest_trace.get('record_ref')}",
                "kind": "latest_task_state",
                "priority": 0.72,
                "summary": _preview(str(latest_trace), 360),
                "refs": [str(latest_trace.get("record_ref"))] if latest_trace.get("record_ref") else [],
            }
        )
    return sorted(blocks, key=lambda item: float(item.get("priority") or 0.0), reverse=True)[:6]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item)]


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _preview(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _hash_payload(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()
