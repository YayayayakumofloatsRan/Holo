from __future__ import annotations

import json
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE212_ACTION_JOURNAL_SCHEMA = "holo.stage212.action_journal.v1"


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _payload_from_message(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json", {})
    if isinstance(raw, dict):
        return dict(raw)
    try:
        decoded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_from_message(row)
    metadata = _dict(payload.get("metadata", {}))
    if metadata:
        return metadata
    return _dict(payload)


def _crawler_steps(crawler: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for row in _list_dicts(crawler.get("crawler_ledger", [])):
        phase = str(row.get("phase", "") or "")
        if not phase:
            continue
        steps.append(
            {
                "phase": phase,
                "query": _compact(row.get("query", ""), 180),
                "status": str(row.get("status", "") or ""),
                "url": _compact(row.get("url", ""), 220),
                "score": float(row.get("score", 0.0) or 0.0),
                "authority_status": str(row.get("authority_status", "") or ""),
                "stop_reason": str(row.get("stop_reason", "") or ""),
                "result_count": int(row.get("result_count", 0) or 0),
                "source_count": int(row.get("source_count", 0) or 0),
                "purpose": str(row.get("purpose", "") or ""),
            }
        )
    return steps


def _feedback_steps(metadata: dict[str, Any], crawler: dict[str, Any]) -> list[dict[str, Any]]:
    report = _dict(metadata.get("stage190_self_feedback_loop", {})) or _dict(crawler.get("stage190_self_feedback_loop", {}))
    feedback: list[dict[str, Any]] = []
    for row in _list_dicts(report.get("steps", [])):
        feedback.append(
            {
                "action": str(row.get("action", "") or ""),
                "evidence_score": float(row.get("combined_sufficiency_score", row.get("evidence_score", 0.0)) or 0.0),
                "marginal_utility": float(row.get("marginal_utility", 0.0) or 0.0),
                "next_action": str(row.get("next_action", "") or ""),
                "stop_reason": str(row.get("stop_reason", "") or ""),
            }
        )
    return feedback


def _entry_from_metadata(metadata: dict[str, Any], *, row: dict[str, Any] | None = None) -> dict[str, Any]:
    row = dict(row or {})
    crawler = _dict(metadata.get("stage186_live_crawler_search", {}))
    web_rows = _list_dicts(metadata.get("web_observation_ledger", []))
    tool_rows = _list_dicts(metadata.get("tool_observation_ledger", []))
    if not crawler and not web_rows and not tool_rows:
        return {}
    action_type = "web_search" if crawler or any(str(item.get("action_type", "") or "") == "web_search" for item in web_rows) else "tool_action"
    promoted = [str(url) for url in list(crawler.get("source_urls", []) or []) if str(url or "").strip()]
    steps = _crawler_steps(crawler)
    feedback = _feedback_steps(metadata, crawler)
    entry = {
        "entry_id": "stage212_entry:" + stable_digest(str(row.get("id", "")), str(crawler.get("status", "")), str(promoted), limit=12),
        "source_message_id": row.get("id"),
        "created_at": str(row.get("created_at", "") or ""),
        "action_type": action_type,
        "status": str(crawler.get("status", "") or ("observed" if (web_rows or tool_rows) else "missing")),
        "stop_reason": str(crawler.get("stop_reason", "") or ""),
        "query_count": int(crawler.get("query_count", 0) or len([step for step in steps if step.get("phase") == "query"])),
        "opened_page_count": int(crawler.get("opened_page_count", 0) or len([step for step in steps if step.get("phase") == "open_page"])),
        "promoted_source_urls": promoted,
        "step_count": len(steps),
        "steps": steps[:24],
        "feedback_count": len(feedback),
        "feedback": feedback[:12],
        "hidden_reasoning_exposed": False,
    }
    return sanitize_public_metadata(entry)


def build_action_journal_from_payload(payload: dict[str, Any] | None, *, limit: int = 1) -> dict[str, Any]:
    entry = _entry_from_metadata(_dict(payload or {}), row={"id": "last_payload", "created_at": ""})
    entries = [entry] if entry else []
    return sanitize_public_metadata(
        {
            "schema": STAGE212_ACTION_JOURNAL_SCHEMA,
            "status": "recorded" if entries else "empty",
            "entry_count": len(entries),
            "entries": entries[: max(0, int(limit or 1))],
            "source": "payload",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
    )


def build_action_journal_from_messages(
    recent_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    rows = [dict(item) for item in list(recent_messages or []) if isinstance(item, dict)]
    rows.sort(key=lambda item: int(item.get("id", 0) or 0), reverse=True)
    for row in rows:
        if str(row.get("direction", "") or "") != "outbound":
            continue
        entry = _entry_from_metadata(_metadata_from_row(row), row=row)
        if not entry:
            continue
        entries.append(entry)
        if len(entries) >= max(0, int(limit or 0)):
            break
    return sanitize_public_metadata(
        {
            "schema": STAGE212_ACTION_JOURNAL_SCHEMA,
            "status": "recorded" if entries else "empty",
            "entry_count": len(entries),
            "entries": entries,
            "source": "persisted_outbound_metadata",
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
        }
    )


def render_action_journal(journal: dict[str, Any] | None) -> str:
    report = _dict(journal or {})
    entries = _list_dicts(report.get("entries", []))
    if not entries:
        return "[journal] no persisted action entries"
    lines = [f"[journal] entries={len(entries)} source={report.get('source', '-') or '-'}"]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"[action:{index}] {entry.get('action_type', '')} status={entry.get('status', '')} "
            f"queries={entry.get('query_count', 0)} opened={entry.get('opened_page_count', 0)} "
            f"stop={entry.get('stop_reason', '') or '-'}"
        )
        promoted = [str(url) for url in list(entry.get("promoted_source_urls", []) or []) if str(url or "").strip()]
        if promoted:
            lines.append("[source] promoted=" + "; ".join(promoted[:4]))
        for step in _list_dicts(entry.get("steps", []))[:18]:
            phase = str(step.get("phase", "") or "")
            if phase == "query":
                lines.append(f"[crawl:query] {step.get('query', '')}")
            elif phase == "observe_search":
                lines.append(
                    f"[crawl:search] status={step.get('status', '')} results={step.get('result_count', 0)} sources={step.get('source_count', 0)}"
                )
            elif phase == "open_page":
                lines.append(f"[crawl:open] status={step.get('status', '')} url={step.get('url', '')}")
            elif phase == "evaluate":
                lines.append(
                    f"[crawl:evaluate] status={step.get('status', '')} score={step.get('score', 0)} "
                    f"authority={step.get('authority_status', '') or '-'} stop={step.get('stop_reason', '') or '-'}"
                )
            elif phase == "stop":
                lines.append(f"[crawl:stop] status={step.get('status', '')} stop={step.get('stop_reason', '') or '-'}")
        for feedback in _list_dicts(entry.get("feedback", []))[:8]:
            lines.append(
                f"[feedback] action={feedback.get('action', '')} score={feedback.get('evidence_score', 0)} "
                f"delta={feedback.get('marginal_utility', 0)} next={feedback.get('next_action', '') or '-'} "
                f"stop={feedback.get('stop_reason', '') or '-'}"
            )
    return "\n".join(lines)
