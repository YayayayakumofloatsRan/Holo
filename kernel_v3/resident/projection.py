from __future__ import annotations

import hashlib

from kernel_v3.contracts import JsonObject
from kernel_v3.resident.contracts import OutboxMessage


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
        },
    }
    if chat_result.command_result is not None:
        payload["command_result"] = chat_result.command_result
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
    return {
        "reason": failure_report.get("reason"),
        "missing_evidence": _string_list(failure_report.get("missing_evidence")),
        "trace_refs": _string_list(failure_report.get("trace_refs")),
        "user_help_needed": failure_report.get("user_help_needed"),
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
        "command_result": payload.get("command_result") if isinstance(payload.get("command_result"), dict) else None,
        "final_answer": payload.get("final_answer") if isinstance(payload.get("final_answer"), dict) else None,
        "failure_report": payload.get("failure_report") if isinstance(payload.get("failure_report"), dict) else None,
        "pending_question": payload.get("pending_question") if isinstance(payload.get("pending_question"), dict) else None,
        "redaction": {"answer": "not_embedded", "summary": "manifest_only"},
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _preview(text: str, *, limit: int = 160) -> str:
    return text[:limit]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
