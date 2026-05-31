from __future__ import annotations

import hashlib
import json

from kernel_v3.contracts import JsonObject
from kernel_v3.resident.contracts import InboundMessage, OutboxMessage


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


def _metadata_manifest(metadata: JsonObject) -> JsonObject:
    keys = sorted(str(key) for key in metadata.keys())
    return {
        "key_count": len(keys),
        "keys": keys[:COMMAND_MANIFEST_LIST_LIMIT],
        "keys_truncated": len(keys) > COMMAND_MANIFEST_LIST_LIMIT,
        "hash": _text_hash(_stable_json(metadata)),
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
