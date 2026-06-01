from __future__ import annotations

import hashlib
import json

from kernel_v3.contracts import JsonObject
from kernel_v3.resident.contracts import (
    InboundMessage,
    OutboxMessage,
    ResidentDoctorReport,
    ResidentSchedule,
    ResidentScheduleTickResult,
)


COMMAND_MANIFEST_TEXT_LIMIT = 160
COMMAND_MANIFEST_LIST_LIMIT = 20
COMMAND_MANIFEST_DEPTH_LIMIT = 5


def resident_chat_result_payload(chat_result) -> JsonObject:
    payload: JsonObject = {
        "status": chat_result.status,
        "route": chat_result.route,
        "thread_id": chat_result.thread_id,
        "turn_id": chat_result.turn_id,
        "task_id": chat_result.task_id,
        "run_id": chat_result.run_id,
        "trace_refs": list(chat_result.trace_refs),
        "redaction": {
            "answer": "outbox_text_only",
            "summary": "manifest_only",
            "failure_report": "manifest_only",
            "command_result": "manifest_only",
        },
    }
    if chat_result.command_result is not None:
        payload["command_result"] = _command_result_manifest(chat_result.command_result)
    if chat_result.pending_question is not None:
        payload["pending_question"] = _pending_question_manifest(chat_result.pending_question)
    if chat_result.final_answer is not None:
        payload["final_answer"] = _final_answer_manifest(chat_result.final_answer)
    if chat_result.failure_report is not None:
        payload["failure_report"] = _failure_report_manifest(chat_result.failure_report)
    if chat_result.summary is not None:
        payload["summary"] = _summary_manifest(chat_result.summary)
    return payload


def resident_outbox_event(outbox: OutboxMessage) -> JsonObject:
    return {
        "outbox_id": outbox.outbox_id,
        "in_reply_to": outbox.in_reply_to,
        "thread_id": outbox.thread_id,
        "status": outbox.status,
        "created_at_ms": outbox.created_at_ms,
        "task_id": outbox.task_id,
        "run_id": outbox.run_id,
        "text_preview": _preview(outbox.text),
        "text_length": len(outbox.text),
        "text_hash": _text_hash(outbox.text),
        "payload": _outbox_payload_manifest(outbox.payload),
        "redaction": {"text": "preview_hash_only", "payload": "manifest_only"},
    }


def resident_inbox_event(message: InboundMessage) -> JsonObject:
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "source": message.source,
        "status": message.status,
        "created_at_ms": message.created_at_ms,
        "lease_owner": message.lease_owner,
        "lease_until_ms": message.lease_until_ms,
        "attempts": message.attempts,
        "next_attempt_at_ms": message.next_attempt_at_ms,
        "text_preview": _preview(message.text),
        "text_length": len(message.text),
        "text_hash": _text_hash(message.text),
        "metadata": _metadata_manifest(message.metadata),
        "redaction": {"text": "preview_hash_only", "metadata": "manifest_only"},
    }


def resident_schedule_event(schedule: ResidentSchedule) -> JsonObject:
    return _resident_schedule_payload(schedule.to_dict())


def resident_schedule_enqueued_event(*, schedule: ResidentSchedule, message: InboundMessage) -> JsonObject:
    return {
        "schedule": resident_schedule_event(schedule),
        "message": resident_inbox_event(message),
        "redaction": {"schedule": "manifest_only", "message": "manifest_only"},
    }


def resident_schedule_tick_event(result: ResidentScheduleTickResult | object) -> JsonObject:
    if isinstance(result, ResidentScheduleTickResult):
        payload = result.to_dict()
    else:
        to_dict = getattr(result, "to_dict", None)
        payload = to_dict() if callable(to_dict) else {}
        payload = payload if isinstance(payload, dict) else {}
    schedules = payload.get("schedules") if isinstance(payload.get("schedules"), list) else []
    enqueued_messages = payload.get("enqueued_messages") if isinstance(payload.get("enqueued_messages"), list) else []
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    return {
        "status": payload.get("status"),
        "generated_at_ms": payload.get("generated_at_ms"),
        "due_count": payload.get("due_count", 0),
        "enqueued_count": payload.get("enqueued_count", 0),
        "skipped_count": payload.get("skipped_count", 0),
        "failed_count": payload.get("failed_count", 0),
        "schedules": [_resident_schedule_payload(item) for item in schedules if isinstance(item, dict)],
        "enqueued_messages": [_resident_inbox_payload(item) for item in enqueued_messages if isinstance(item, dict)],
        "failures": [dict(item) for item in failures if isinstance(item, dict)],
        "diagnostics": dict(diagnostics),
        "redaction": {"schedules": "manifest_only", "enqueued_messages": "manifest_only"},
    }


def resident_doctor_event(
    report: ResidentDoctorReport,
    *,
    overall_status: str | None = None,
    live_retrieval_status: str | None = None,
    live_retrieval_issues: list[JsonObject] | None = None,
    live_retrieval_config: JsonObject | None = None,
) -> JsonObject:
    payload = report.to_dict()
    issues = _doctor_issue_manifests(payload.get("issues"))
    event: JsonObject = {
        "status": overall_status or report.status,
        "doctor_status": report.status,
        "generated_at_ms": report.generated_at_ms,
        "configured": dict(report.configured),
        "component_statuses": {
            "queue": _component_status(payload, "queue_inspection"),
            "schedule": _component_status(payload, "schedule_inspection"),
            "memory": _component_status(payload, "memory_inspection"),
            "corpus": _component_status(payload, "corpus_inspection"),
            "retrieval": _component_status(payload, "retrieval_provider_inspection"),
        },
        "queue_status": _inspection_child(payload, "queue_inspection", "queue_status"),
        "schedule_status": _inspection_child(payload, "schedule_inspection", "schedule_status"),
        "memory_summary": _memory_inspection_summary(payload.get("memory_inspection")),
        "corpus_summary": _corpus_inspection_summary(payload.get("corpus_inspection")),
        "retrieval_summary": _retrieval_inspection_summary(payload.get("retrieval_provider_inspection")),
        "issue_count": len(issues),
        "issues": issues[:COMMAND_MANIFEST_LIST_LIMIT],
        "issues_truncated": len(issues) > COMMAND_MANIFEST_LIST_LIMIT,
        "recommended_actions": _string_list(payload.get("recommended_actions"))[:COMMAND_MANIFEST_LIST_LIMIT],
        "recommended_actions_truncated": len(_string_list(payload.get("recommended_actions")))
        > COMMAND_MANIFEST_LIST_LIMIT,
        "report_hash": _text_hash(_stable_json(payload)),
        "redaction": {
            "doctor_report": "summary_hash_only",
            "inspection_samples": "omitted",
            "raw_payloads": "not_embedded",
        },
    }
    live_issues = list(live_retrieval_issues or [])
    if live_retrieval_status is not None or live_issues or live_retrieval_config is not None:
        event["live_retrieval"] = {
            "status": live_retrieval_status,
            "issue_count": len(live_issues),
            "issues": _doctor_issue_manifests(live_issues)[:COMMAND_MANIFEST_LIST_LIMIT],
            "issues_truncated": len(live_issues) > COMMAND_MANIFEST_LIST_LIMIT,
            "config": _compact_command_value(live_retrieval_config or {}, depth=0, key="live_retrieval_config"),
            "redaction": {"config": "safe_diagnostics_only"},
        }
    return event


def _final_answer_manifest(final_answer: JsonObject) -> JsonObject:
    return {
        "citation_refs": _string_list(final_answer.get("citation_refs")),
        "used_evidence": _string_list(final_answer.get("used_evidence")),
        "limitations": _string_list(final_answer.get("limitations")),
        "confidence": final_answer.get("confidence"),
        "task_id": final_answer.get("task_id"),
        "run_id": final_answer.get("run_id"),
        "trace_refs": _string_list(final_answer.get("trace_refs")),
        "answer_preview": _preview(str(final_answer.get("answer") or "")),
        "answer_hash": _text_hash(str(final_answer.get("answer") or "")),
        "redaction": {"answer": "preview_hash_only"},
    }


def _failure_report_manifest(failure_report: JsonObject) -> JsonObject:
    reason = str(failure_report.get("reason") or "")
    return {
        "reason_preview": _preview(reason),
        "reason_hash": _text_hash(reason),
        "missing_evidence": _string_list(failure_report.get("missing_evidence")),
        "trace_refs": _string_list(failure_report.get("trace_refs")),
        "user_help_needed": failure_report.get("user_help_needed"),
        "redaction": {"reason": "preview_hash_only"},
    }


def _pending_question_manifest(pending_question: JsonObject) -> JsonObject:
    question = pending_question.get("question")
    return {
        "pending_id": pending_question.get("pending_id"),
        "task_id": pending_question.get("task_id"),
        "run_id": pending_question.get("run_id"),
        "source_ref": pending_question.get("source_ref"),
        "question_preview": _preview(str(question or "")),
        "question_hash": _text_hash(str(question or "")),
        "redaction": {"question": "preview_hash_only"},
    }


def _summary_manifest(summary: JsonObject) -> JsonObject:
    return {
        "summary_id": summary.get("summary_id"),
        "active_task_id": summary.get("active_task_id"),
        "last_result_status": summary.get("last_result_status"),
        "recent_turn_count": len(summary.get("recent_turns") or [])
        if isinstance(summary.get("recent_turns"), list)
        else 0,
    }


def _outbox_payload_manifest(payload: JsonObject) -> JsonObject:
    return {
        "status": payload.get("status"),
        "route": payload.get("route"),
        "task_id": payload.get("task_id"),
        "run_id": payload.get("run_id"),
        "trace_refs": _string_list(payload.get("trace_refs")),
        "command_result": _command_result_manifest(payload.get("command_result")),
        "final_answer": _final_answer_payload_manifest(payload.get("final_answer")),
        "failure_report": _failure_report_payload_manifest(payload.get("failure_report")),
        "pending_question": _pending_question_payload_manifest(payload.get("pending_question")),
        "redaction": {"answer": "not_embedded", "summary": "manifest_only", "command_result": "manifest_only"},
    }


def _final_answer_payload_manifest(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    if "answer_hash" in value and isinstance(value.get("redaction"), dict):
        return dict(value)
    return _final_answer_manifest(value)


def _failure_report_payload_manifest(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    if "reason_hash" in value and isinstance(value.get("redaction"), dict):
        return dict(value)
    return _failure_report_manifest(value)


def _pending_question_payload_manifest(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    if "question_hash" in value and isinstance(value.get("redaction"), dict):
        return dict(value)
    return _pending_question_manifest(value)


def _component_status(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    return status if isinstance(status, str) else None


def _inspection_child(payload: JsonObject, key: str, child_key: str) -> JsonObject | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    child = value.get(child_key)
    return dict(child) if isinstance(child, dict) else None


def _memory_inspection_summary(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    return {
        "status": value.get("status"),
        "active_count": value.get("active_count", 0),
        "expired_count": value.get("expired_count", 0),
        "deleted_count": value.get("deleted_count", 0),
        "sensitive_count": value.get("sensitive_count", 0),
        "proposal_counts": _dict_value(value.get("proposal_counts")),
        "shadow_candidate_count": value.get("shadow_candidate_count", 0),
        "tombstone_count": value.get("tombstone_count", 0),
        "audit_record_count": value.get("audit_record_count", 0),
        "provenance_consistency": _without_keys(_dict_value(value.get("provenance_consistency")), {"samples"}),
    }


def _corpus_inspection_summary(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    corpus_status = _dict_value(value.get("corpus_status"))
    return {
        "status": value.get("status"),
        "document_count": corpus_status.get("document_count", 0),
        "primary_usable_count": corpus_status.get("primary_usable_count", 0),
        "profile_counts": _dict_value(corpus_status.get("profile_counts")),
        "inspection_scope": _dict_value(corpus_status.get("inspection_scope")),
        "artifact_consistency": _dict_value(value.get("artifact_consistency")),
    }


def _retrieval_inspection_summary(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    diagnostics = _dict_value(value.get("diagnostics"))
    return {
        "status": value.get("status"),
        "network_access": bool(value.get("network_access", False)),
        "provider_count": diagnostics.get("provider_count", 0),
        "search_provider_ids": _string_list(diagnostics.get("search_provider_ids")),
        "fetch_provider_ids": _string_list(diagnostics.get("fetch_provider_ids")),
        "provider_chain": _compact_command_value(diagnostics.get("provider_chain", []), depth=0, key="provider_chain"),
        "research_profile_id": diagnostics.get("research_profile_id"),
    }


def _doctor_issue_manifests(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [_doctor_issue_manifest(item) for item in value if isinstance(item, dict)]


def _doctor_issue_manifest(issue: JsonObject) -> JsonObject:
    selected_keys = (
        "component",
        "severity",
        "code",
        "provider_id",
        "provider_kind",
        "research_profile_id",
        "profile_id",
        "count",
        "document_count",
        "stale_count",
        "missing_artifact_ref_count",
        "missing_artifact_blob_count",
        "reason",
    )
    result = {key: issue[key] for key in selected_keys if key in issue}
    result["details_hash"] = _text_hash(_stable_json(issue))
    return result


def _dict_value(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _without_keys(value: JsonObject, keys: set[str]) -> JsonObject:
    return {key: item for key, item in value.items() if key not in keys}


def _metadata_manifest(metadata: JsonObject) -> JsonObject:
    keys = sorted(str(key) for key in metadata.keys())
    return {
        "key_count": len(keys),
        "keys": keys[:COMMAND_MANIFEST_LIST_LIMIT],
        "keys_truncated": len(keys) > COMMAND_MANIFEST_LIST_LIMIT,
        "hash": _text_hash(_stable_json(metadata)),
    }


def _resident_schedule_payload(payload: JsonObject) -> JsonObject:
    text = str(payload.get("text") or "")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "schedule_id": payload.get("schedule_id"),
        "thread_id": payload.get("thread_id"),
        "source": payload.get("source"),
        "status": payload.get("status"),
        "created_at_ms": payload.get("created_at_ms"),
        "next_due_at_ms": payload.get("next_due_at_ms"),
        "interval_ms": payload.get("interval_ms"),
        "max_runs": payload.get("max_runs"),
        "run_count": payload.get("run_count"),
        "last_enqueued_at_ms": payload.get("last_enqueued_at_ms"),
        "last_message_id": payload.get("last_message_id"),
        "text_preview": _preview(text),
        "text_length": len(text),
        "text_hash": _text_hash(text),
        "metadata": _metadata_manifest(metadata),
        "redaction": {"text": "preview_hash_only", "metadata": "manifest_only"},
    }


def _resident_inbox_payload(payload: JsonObject) -> JsonObject:
    text = str(payload.get("text") or "")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "message_id": payload.get("message_id"),
        "thread_id": payload.get("thread_id"),
        "source": payload.get("source"),
        "status": payload.get("status"),
        "created_at_ms": payload.get("created_at_ms"),
        "lease_owner": payload.get("lease_owner"),
        "lease_until_ms": payload.get("lease_until_ms"),
        "attempts": payload.get("attempts"),
        "next_attempt_at_ms": payload.get("next_attempt_at_ms"),
        "text_preview": _preview(text),
        "text_length": len(text),
        "text_hash": _text_hash(text),
        "metadata": _metadata_manifest(metadata),
        "redaction": {"text": "preview_hash_only", "metadata": "manifest_only"},
    }


def _command_result_manifest(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    compacted = _compact_command_value(value, depth=0, key="")
    return compacted if isinstance(compacted, dict) else {"value": compacted}


def _compact_command_value(value: object, *, depth: int, key: str) -> object:
    if depth > COMMAND_MANIFEST_DEPTH_LIMIT:
        return _value_manifest(value, reason="depth_limited")
    if isinstance(value, dict):
        return {
            str(child_key): _compact_command_value(child_value, depth=depth + 1, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        items = [
            _compact_command_value(item, depth=depth + 1, key=key)
            for item in value[:COMMAND_MANIFEST_LIST_LIMIT]
        ]
        if len(value) <= COMMAND_MANIFEST_LIST_LIMIT:
            return items
        return {
            "items": items,
            "truncated_count": len(value) - COMMAND_MANIFEST_LIST_LIMIT,
            "redaction": {"list": "truncated"},
        }
    if isinstance(value, str):
        if key == "trace" or len(value) > COMMAND_MANIFEST_TEXT_LIMIT:
            return _text_manifest(value, reason="preview_hash_only")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _value_manifest(value, reason="unsupported_type")


def _text_manifest(text: str, *, reason: str) -> JsonObject:
    return {
        "preview": _preview(text, limit=COMMAND_MANIFEST_TEXT_LIMIT),
        "length": len(text),
        "hash": _text_hash(text),
        "redaction": {"text": reason},
    }


def _value_manifest(value: object, *, reason: str) -> JsonObject:
    text = str(value)
    return {
        "preview": _preview(text, limit=COMMAND_MANIFEST_TEXT_LIMIT),
        "hash": _text_hash(text),
        "redaction": {"value": reason},
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _preview(text: str, *, limit: int = 160) -> str:
    return text[:limit]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
