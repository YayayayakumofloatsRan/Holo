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
    recent_memory_learning_limit: int = 8
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
        memory_learning = _recent_memory_learning(
            journal,
            thread_id=thread_id,
            task_id=task_id,
            limit=self.config.recent_memory_learning_limit,
        )
        task_trace = trace
        recent_results = [_compact_result(record, preview_chars=self.config.text_preview_chars) for record in results]
        recent_turns = [_compact_turn(record, preview_chars=self.config.text_preview_chars) for record in turns]
        payload = {
            "kind": "thread_rag_context",
            "thread_id": thread_id,
            "task_id": task_id,
            "mission_id": mission_id,
            "recent_turns": recent_turns,
            "recent_results": recent_results,
            "recent_task_trace": task_trace,
            "evidence_refs": evidence_refs,
            "citation_refs": citation_refs,
            "failure_diagnostics": failure_diagnostics,
            "memory_learning": memory_learning,
            "active_memory_recalls": _active_memory_recalls(task_trace),
        }
        payload["attention_blocks"] = _attention_blocks(
            recent_results=recent_results,
            recent_task_trace=task_trace,
            evidence_refs=evidence_refs,
            citation_refs=citation_refs,
            failure_diagnostics=failure_diagnostics,
            memory_learning=memory_learning,
        )
        payload["task_continuity"] = _task_continuity_context(
            mission_id=mission_id,
            recent_turns=recent_turns,
            recent_results=recent_results,
            recent_task_trace=task_trace,
            evidence_refs=evidence_refs,
            citation_refs=citation_refs,
            failure_diagnostics=failure_diagnostics,
        )
        payload["self_iteration"] = _self_iteration_context(
            recent_results=recent_results,
            recent_task_trace=task_trace,
            failure_diagnostics=failure_diagnostics,
            memory_learning=memory_learning,
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
    quality_checks = [record for record in records if record.kind == "final_answer_quality_check"]
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
        "answer_quality_checks": [_compact_answer_quality(record) for record in quality_checks[-4:]],
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
        "final_answer_quality_check",
        "mission_assessment",
        "mission_directive",
        "work_gap_assessment",
        "strategy_shift",
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


def _recent_memory_learning(
    journal: JournalStore,
    *,
    thread_id: str,
    task_id: str | None,
    limit: int,
) -> list[JsonObject]:
    records: list[LedgerRecord] = []
    for record in journal.records(kind="memory_proposal"):
        if record.data.get("review_nonblocking") is not True:
            continue
        same_task = bool(task_id and record.task_id == task_id)
        same_thread = record.data.get("source_thread_id") == thread_id
        if same_task or same_thread:
            records.append(record)
    return [_compact_memory_proposal(record) for record in records[-max(1, limit) :]]


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
    host_situation = record.data.get("host_situation") if isinstance(record.data.get("host_situation"), dict) else {}
    return {
        "record_ref": record.record_id,
        "task_id": record.data.get("task_id"),
        "run_id": record.data.get("run_id"),
        "route": record.data.get("route"),
        "status": record.data.get("status"),
        "answer_preview": _preview(str(record.data.get("answer") or ""), preview_chars),
        "failure_reason": failure.get("reason") if failure else None,
        "host_situation": _compact_host_situation_data(host_situation),
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
    if record.kind == "final_answer_quality_check":
        return _compact_answer_quality(record)
    if record.kind == "mission_assessment":
        return _compact_mission_assessment(record)
    if record.kind == "mission_directive":
        return _compact_mission_directive(record)
    if record.kind == "work_gap_assessment":
        return _compact_work_gap(record)
    if record.kind == "strategy_shift":
        return _compact_strategy_shift(record)
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
    compacted = {
        "record_ref": record.record_id,
        "kind": "observation",
        "source": record.data.get("source"),
        "status": record.data.get("status"),
        "content_preview": _preview(str(content), 360),
        "content_hash": _hash_payload(content),
    }
    if record.data.get("source") == "tool:memory.recall" and isinstance(content, dict):
        compacted["memory_recall"] = _compact_memory_recall_content(content)
    return compacted


def _compact_memory_recall_content(content: JsonObject) -> JsonObject:
    combined = content.get("combined") if isinstance(content.get("combined"), dict) else {}
    results = content.get("results") if isinstance(content.get("results"), dict) else {}
    diagnostics = content.get("diagnostics") if isinstance(content.get("diagnostics"), dict) else {}
    return {
        "query_hash": content.get("query_hash"),
        "query_preview": _preview(str(content.get("query_preview") or ""), 180),
        "scope_mode": content.get("scope_mode"),
        "limit_per_scope": content.get("limit_per_scope"),
        "combined_total": combined.get("total", 0),
        "memory_ids": _string_list(combined.get("memory_ids"))[:16],
        "fallback_ranked_scopes": _string_list(diagnostics.get("fallback_ranked_scopes"))[:8],
        "scopes": {
            str(label): _compact_memory_recall_scope(result)
            for label, result in list(results.items())[:4]
            if isinstance(result, dict)
        },
    }


def _compact_memory_recall_scope(result: JsonObject) -> JsonObject:
    items = [item for item in list(result.get("items") or [])[:6] if isinstance(item, dict)]
    return {
        "total": result.get("total", len(items)),
        "memory_ids": [str(item.get("memory_id")) for item in items if item.get("memory_id")],
        "items": [
            {
                "memory_id": item.get("memory_id"),
                "kind": item.get("kind"),
                "title": _preview(str(item.get("title") or ""), 120),
                "summary": _preview(str(item.get("summary") or ""), 220),
                "body_preview": _preview(str(item.get("body_preview") or ""), 180),
                "structured_summary": item.get("structured_summary") if isinstance(item.get("structured_summary"), dict) else {},
                "privacy_class": item.get("privacy_class"),
                "confidence": item.get("confidence"),
                "provenance_refs": _string_list(item.get("provenance_refs"))[:4],
            }
            for item in items
        ],
        "filtered": dict(result.get("filtered", {})) if isinstance(result.get("filtered"), dict) else {},
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


def _compact_memory_proposal(record: LedgerRecord) -> JsonObject:
    proposed = record.data.get("proposed_item") if isinstance(record.data.get("proposed_item"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "memory_proposal",
        "proposal_id": record.data.get("proposal_id"),
        "approval_status": record.data.get("approval_status"),
        "approval_policy": record.data.get("approval_policy"),
        "review_nonblocking": record.data.get("review_nonblocking"),
        "source_kind": record.data.get("source_kind"),
        "quality_gaps": _string_list(record.data.get("quality_gaps"))[:12],
        "proposed_kind": proposed.get("kind"),
        "summary_preview": _preview(str(proposed.get("summary_preview") or ""), 360),
        "summary_hash": proposed.get("summary_hash"),
        "source_thread_id": record.data.get("source_thread_id"),
        "evidence_record_refs": _string_list(record.data.get("evidence_record_refs"))[:6],
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


def _compact_answer_quality(record: LedgerRecord) -> JsonObject:
    profile = record.data.get("answer_profile") if isinstance(record.data.get("answer_profile"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "final_answer_quality_check",
        "passed": record.data.get("passed"),
        "attempt": record.data.get("attempt"),
        "gaps": _string_list(record.data.get("gaps"))[:12],
        "prior_gaps": _string_list(record.data.get("prior_gaps"))[:12],
        "answer_chars": record.data.get("answer_chars"),
        "profile_format": profile.get("format"),
        "profile_domain": (profile.get("metadata") or {}).get("domain") if isinstance(profile.get("metadata"), dict) else None,
    }


def _compact_mission_assessment(record: LedgerRecord) -> JsonObject:
    next_directive = record.data.get("next_directive") if isinstance(record.data.get("next_directive"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "mission_assessment",
        "mission_id": record.data.get("mission_id"),
        "decision": record.data.get("decision"),
        "coverage_score": record.data.get("coverage_score"),
        "covered_requirements": _string_list(record.data.get("covered_requirements"))[:12],
        "missing_requirements": _string_list(record.data.get("missing_requirements"))[:12],
        "unsupported_claims": _string_list(record.data.get("unsupported_claims"))[:8],
        "reason_summary": _preview(str(record.data.get("reason_summary") or ""), 420),
        "next_directive": _compact_directive_payload(next_directive),
    }


def _compact_mission_directive(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "mission_directive",
        **_compact_directive_payload(record.data),
    }


def _compact_directive_payload(data: JsonObject) -> JsonObject:
    return {
        "directive_id": data.get("directive_id"),
        "mission_id": data.get("mission_id"),
        "root_goal": _preview(str(data.get("root_goal") or ""), 480),
        "strategy": data.get("strategy"),
        "next_subgoal": _preview(str(data.get("next_subgoal") or ""), 360),
        "missing_requirements": _string_list(data.get("missing_requirements"))[:12],
        "avoid_repeating": _string_list(data.get("avoid_repeating"))[-12:],
        "suggested_actions": [
            _compact_suggested_action(item)
            for item in list(data.get("suggested_actions") or [])[:6]
            if isinstance(item, dict)
        ],
        "stop_conditions": _string_list(data.get("stop_conditions"))[:8],
        "reason": _preview(str(data.get("reason") or ""), 420),
    }


def _compact_suggested_action(data: JsonObject) -> JsonObject:
    return {
        "kind": data.get("kind"),
        "name": data.get("name"),
        "description": _preview(str(data.get("description") or data.get("goal") or ""), 240),
        "payload_hash": _hash_payload(data.get("payload", {})),
    }


def _compact_work_gap(record: LedgerRecord) -> JsonObject:
    strategy_shift = record.data.get("strategy_shift") if isinstance(record.data.get("strategy_shift"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "work_gap_assessment",
        "should_continue": record.data.get("should_continue"),
        "should_finalize": record.data.get("should_finalize"),
        "should_shift_strategy": record.data.get("should_shift_strategy"),
        "gap_summary": _preview(str(record.data.get("gap_summary") or ""), 420),
        "missing_work": _string_list(record.data.get("missing_work"))[:12],
        "strategy_shift": _compact_strategy_shift_payload(strategy_shift),
    }


def _compact_strategy_shift(record: LedgerRecord) -> JsonObject:
    return {
        "record_ref": record.record_id,
        "kind": "strategy_shift",
        **_compact_strategy_shift_payload(record.data),
    }


def _compact_strategy_shift_payload(data: JsonObject) -> JsonObject:
    return {
        "shift_kind": data.get("shift_kind") or data.get("kind"),
        "reason": _preview(str(data.get("reason") or ""), 420),
        "from_strategy": data.get("from_strategy"),
        "to_strategy": data.get("to_strategy"),
        "new_source_families": _string_list(data.get("new_source_families"))[:8],
        "avoid_repeating": _string_list(data.get("avoid_repeating"))[-12:],
        "suggested_queries": _string_list(data.get("suggested_queries"))[:12],
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
    result = _compact_host_situation_data(data)
    result.update(
        {
            "record_ref": record.record_id,
            "kind": "host_situation",
            "phase": record.state_delta.get("host_situation"),
        }
    )
    return result


def _compact_host_situation_data(data: JsonObject) -> JsonObject:
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
    runtime = data.get("runtime_capabilities") if isinstance(data.get("runtime_capabilities"), dict) else {}
    runtime_retrieval = runtime.get("retrieval") if isinstance(runtime.get("retrieval"), dict) else {}
    activity = data.get("recent_activity") if isinstance(data.get("recent_activity"), dict) else {}
    failure = data.get("failure") if isinstance(data.get("failure"), dict) else {}
    return {
        "task_mode": task.get("mode"),
        "citations_required": task.get("citations_required"),
        "retrieval_configured": retrieval.get("configured"),
        "live_search_available": retrieval.get("live_search_available"),
        "live_fetch_available": retrieval.get("live_fetch_available"),
        "runtime_retrieval_available_if_routed": runtime_retrieval.get("available_if_routed"),
        "runtime_live_search_available": runtime_retrieval.get("live_search_available"),
        "runtime_live_fetch_available": runtime_retrieval.get("live_fetch_available"),
        "runtime_profile_aware_search_available": runtime_retrieval.get("profile_aware_search_available"),
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
    memory_learning: list[JsonObject],
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
    if memory_learning:
        latest = memory_learning[-1]
        blocks.append(
            {
                "block_id": f"attention-memory-learning-{latest.get('record_ref')}",
                "kind": "memory_learning_signal",
                "priority": 0.86,
                "summary": _preview(
                    f"Memory proposal {latest.get('proposal_id')} "
                    f"status={latest.get('approval_status')} "
                    f"kind={latest.get('proposed_kind')}: {latest.get('summary_preview')}",
                    360,
                ),
                "refs": [str(latest.get("record_ref"))] if latest.get("record_ref") else [],
            }
        )
    quality_checks = [
        item
        for item in recent_task_trace
        if item.get("kind") == "final_answer_quality_check" and item.get("passed") is False
    ]
    if quality_checks:
        latest_quality = quality_checks[-1]
        gaps = _string_list(latest_quality.get("gaps"))
        blocks.append(
            {
                "block_id": f"attention-answer-quality-{latest_quality.get('record_ref')}",
                "kind": "answer_quality_gap",
                "priority": 0.92,
                "summary": _preview(
                    f"Last final answer quality check failed; gaps={', '.join(gaps[:6])}",
                    360,
                ),
                "refs": [str(latest_quality.get("record_ref"))] if latest_quality.get("record_ref") else [],
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


def _active_memory_recalls(recent_task_trace: list[JsonObject]) -> list[JsonObject]:
    recalls = []
    for item in recent_task_trace:
        if item.get("kind") != "observation" or item.get("source") != "tool:memory.recall":
            continue
        recall = item.get("memory_recall")
        if isinstance(recall, dict):
            recalls.append(
                {
                    "record_ref": item.get("record_ref"),
                    "status": item.get("status"),
                    **recall,
                }
            )
    return recalls[-4:]


def _task_continuity_context(
    *,
    mission_id: str | None,
    recent_turns: list[JsonObject],
    recent_results: list[JsonObject],
    recent_task_trace: list[JsonObject],
    evidence_refs: list[str],
    citation_refs: list[str],
    failure_diagnostics: list[JsonObject],
) -> JsonObject:
    assessments = [item for item in recent_task_trace if item.get("kind") == "mission_assessment"]
    directives = [item for item in recent_task_trace if item.get("kind") == "mission_directive"]
    feedback = [item for item in recent_task_trace if item.get("kind") == "feedback"]
    retrieval_reports = [item for item in recent_task_trace if item.get("kind") == "retrieval_report"]
    terminations = [item for item in recent_task_trace if item.get("kind") == "termination_decision"]
    quality_checks = [
        item
        for item in recent_task_trace
        if item.get("kind") == "final_answer_quality_check" and item.get("passed") is False
    ]
    actions = [item for item in recent_task_trace if item.get("kind") == "action"]
    latest_directive = directives[-1] if directives else {}
    latest_assessment = assessments[-1] if assessments else {}
    latest_failure = failure_diagnostics[-1] if failure_diagnostics else {}
    latest_result = recent_results[-1] if recent_results else {}
    objective = (
        latest_directive.get("root_goal")
        or (latest_assessment.get("next_directive") or {}).get("root_goal")
        or (recent_turns[-1].get("text_preview") if recent_turns else None)
    )
    open_requirements = _ordered_unique(
        [
            *_string_list(latest_assessment.get("missing_requirements")),
            *_string_list(latest_directive.get("missing_requirements")),
            *[
                value
                for item in feedback[-3:]
                for value in _string_list(item.get("missing_evidence"))
            ],
            *_string_list(latest_failure.get("missing_evidence")),
            *[
                value
                for item in retrieval_reports[-3:]
                for value in [
                    *_string_list(item.get("missing_query_facets")),
                    *_string_list(item.get("missing_finance_facets")),
                ]
            ],
            *[
                value
                for item in quality_checks[-2:]
                for value in _string_list(item.get("gaps"))
            ],
        ]
    )
    avoid_repeating = _ordered_unique(
        [
            *_string_list(latest_directive.get("avoid_repeating")),
            *[
                query
                for item in retrieval_reports[-4:]
                for query in _string_list(item.get("attempted_queries"))
            ],
        ]
    )
    return {
        "kind": "task_continuity_context",
        "mission_id": mission_id or latest_directive.get("mission_id") or latest_assessment.get("mission_id"),
        "current_objective": _preview(str(objective or ""), 480),
        "latest_result_status": latest_result.get("status"),
        "latest_decision": latest_assessment.get("decision") or (terminations[-1].get("decision") if terminations else None),
        "coverage_score": latest_assessment.get("coverage_score"),
        "covered_requirements": _string_list(latest_assessment.get("covered_requirements"))[:12],
        "open_requirements": open_requirements[:16],
        "next_subgoal": latest_directive.get("next_subgoal"),
        "strategy": latest_directive.get("strategy"),
        "avoid_repeating": avoid_repeating[-16:],
        "recent_actions": [
            {
                "name": item.get("name"),
                "payload_hash": item.get("payload_hash"),
            }
            for item in actions[-8:]
        ],
        "evidence_refs": evidence_refs[:12],
        "citation_refs": citation_refs[:12],
        "suggested_actions": list(latest_directive.get("suggested_actions") or [])[:6],
        "stop_conditions": _string_list(latest_directive.get("stop_conditions"))[:8],
        "host_rule": (
            "Treat current_objective as the continuing task objective. Use open_requirements, "
            "avoid_repeating, recent_actions, and suggested_actions to choose the next materially "
            "different action. Finalize only when evidence and answer shape cover the objective."
        ),
    }


def _self_iteration_context(
    *,
    recent_results: list[JsonObject],
    recent_task_trace: list[JsonObject],
    failure_diagnostics: list[JsonObject],
    memory_learning: list[JsonObject],
) -> JsonObject:
    failed_quality = [
        item
        for item in recent_task_trace
        if item.get("kind") == "final_answer_quality_check" and item.get("passed") is False
    ]
    retrieval_reports = [
        item for item in recent_task_trace if item.get("kind") == "retrieval_report"
    ]
    latest_failure = failure_diagnostics[-1] if failure_diagnostics else {}
    latest_quality = failed_quality[-1] if failed_quality else {}
    quality_gaps = _ordered_unique(
        [
            *_string_list(latest_quality.get("gaps")),
            *_string_list(latest_quality.get("prior_gaps")),
        ]
    )
    attempted_queries = _ordered_unique(
        [
            query
            for report in retrieval_reports[-4:]
            for query in _string_list(report.get("attempted_queries"))
        ]
    )
    source_actions = _ordered_unique(
        [
            str(report.get("source_quality", {}).get("recommended_next_source_action"))
            for report in retrieval_reports[-4:]
            if isinstance(report.get("source_quality"), dict)
            and report.get("source_quality", {}).get("recommended_next_source_action")
        ]
    )
    strategy_hints = _ordered_unique(
        [
            str(report.get("failure_attribution", {}).get("next_strategy_hint"))
            for report in retrieval_reports[-4:]
            if isinstance(report.get("failure_attribution"), dict)
            and report.get("failure_attribution", {}).get("next_strategy_hint")
        ]
    )
    next_actions = _ordered_unique(
        [
            *source_actions,
            *strategy_hints,
            *([str(latest_failure.get("next_possible_action"))] if latest_failure.get("next_possible_action") else []),
            *(["repair_final_answer_quality"] if quality_gaps else []),
        ]
    )
    learning_refs = _ordered_unique(
        [
            str(item.get("record_ref"))
            for item in memory_learning[-4:]
            if item.get("record_ref")
        ]
    )
    learning_signals = [
        {
            "record_ref": item.get("record_ref"),
            "proposal_id": item.get("proposal_id"),
            "source_kind": item.get("source_kind"),
            "quality_gaps": _string_list(item.get("quality_gaps"))[:8],
            "summary_preview": _preview(str(item.get("summary_preview") or ""), 240),
        }
        for item in memory_learning[-4:]
    ]
    completed = [
        item for item in recent_results if item.get("status") == "completed"
    ]
    if latest_failure:
        status = "recover_from_failure"
    elif quality_gaps:
        status = "repair_answer_quality"
    elif memory_learning:
        status = "apply_thread_learning"
    elif completed:
        status = "continue_from_recent_success"
    else:
        status = "no_prior_signal"
    return {
        "kind": "self_iteration_context",
        "status": status,
        "latest_failure_reason": latest_failure.get("reason"),
        "latest_missing_evidence": _string_list(latest_failure.get("missing_evidence"))[:12],
        "answer_quality_gaps": quality_gaps[:12],
        "avoid_repeating_queries": attempted_queries[-12:],
        "recommended_next_actions": next_actions[:8],
        "learning_refs": learning_refs[-8:],
        "learning_signals": learning_signals[-4:],
        "host_rule": (
            "Use this as working memory for the next action. Do not repeat avoid_repeating_queries "
            "unless the new payload materially changes source family, tool path, or evidence target."
        ),
    }


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
