from __future__ import annotations

import json
from typing import Any, Iterable

from ..common import compact_text, stable_digest, utc_now

TEMPORAL_ITEM_TYPES = {
    "open_loop",
    "commitment",
    "deferred_intention",
    "interruption_marker",
    "resume_candidate",
    "due_followup",
}
TEMPORAL_LIVE_STATUSES = {"open", "scheduled", "due"}
TEMPORAL_TERMINAL_STATUSES = {"fulfilled", "superseded", "canceled", "expired"}
TEMPORAL_VALID_STATUSES = TEMPORAL_LIVE_STATUSES | TEMPORAL_TERMINAL_STATUSES
TEMPORAL_MAX_LIVE_PER_THREAD = 24
TEMPORAL_MAX_ITEMS = 48


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _clean_list(values: Iterable[Any], *, limit: int = 6, width: int = 120) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(str(value or "").strip(), width)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _normalize_status(status: str) -> str:
    current = str(status or "").strip().lower()
    return current if current in TEMPORAL_VALID_STATUSES else "open"


def _normalize_type(item_type: str) -> str:
    current = str(item_type or "").strip().lower()
    return current if current in TEMPORAL_ITEM_TYPES else "open_loop"


def _default_dedupe_key(
    *,
    channel: str,
    thread_key: str,
    item_type: str,
    source_event_id: str,
    source_action_ref: str,
    resume_cue: str,
) -> str:
    return "temporal:" + stable_digest(channel, thread_key, item_type, source_event_id, source_action_ref, resume_cue)[:24]


def _effective_status(row: dict[str, Any], *, now: str) -> tuple[str, bool, bool]:
    status = _normalize_status(str(row.get("status", "") or "open"))
    due_at = str(row.get("due_at", "") or "")
    revisit_after = str(row.get("revisit_after", "") or "")
    revisit_before = str(row.get("revisit_before", "") or "")
    expired = bool(status in TEMPORAL_LIVE_STATUSES and revisit_before and revisit_before <= now)
    if expired:
        return "expired", False, True
    due = bool(status in TEMPORAL_LIVE_STATUSES and ((due_at and due_at <= now) or (revisit_after and revisit_after <= now)))
    if due:
        return "due", True, False
    return status, False, False


def temporal_item_from_row(self: Any, row: dict[str, Any] | None, *, now: str | None = None) -> dict[str, Any]:
    if not row:
        return {"present": False, "status": "missing", "type": ""}
    current_now = now or utc_now()
    metadata = _json_dict(row.get("metadata_json", "{}"))
    status, due, expired = _effective_status(row, now=current_now)
    item_type = _normalize_type(str(row.get("type", "") or "open_loop"))
    return {
        "present": status in TEMPORAL_LIVE_STATUSES,
        "type": item_type,
        "status": status,
        "stored_status": _normalize_status(str(row.get("status", "") or "open")),
        "due": bool(due),
        "expired": bool(expired),
        "channel": str(row.get("channel", "") or ""),
        "thread_key": str(row.get("thread_key", "") or ""),
        "canonical_thread_key": str(row.get("thread_key", "") or ""),
        "chat_name": str(row.get("chat_name", "") or ""),
        "confidence": float(row.get("confidence", 0.0) or 0.0),
        "source_event_id": str(row.get("source_event_id", "") or ""),
        "source_action_ref": str(row.get("source_action_ref", "") or ""),
        "source_action_type": str(row.get("source_action_type", "") or ""),
        "due_at": str(row.get("due_at", "") or ""),
        "revisit_after": str(row.get("revisit_after", "") or ""),
        "revisit_before": str(row.get("revisit_before", "") or ""),
        "resume_cue": str(row.get("resume_cue", "") or ""),
        "dedupe_key": str(row.get("dedupe_key", "") or ""),
        "queue_job_id": int(row.get("queue_job_id", 0) or 0),
        "metadata": metadata,
        "evidence_refs": _clean_list(metadata.get("evidence_refs", []), limit=6, width=120),
        "created_at": str(row.get("created_at", "") or ""),
        "updated_at": str(row.get("updated_at", "") or ""),
    }


def _prune_temporal_state_locked(self: Any, *, channel: str, thread_key: str, now: str) -> None:
    rows = [
        dict(row)
        for row in self.conn.execute(
            """
            SELECT id, status, revisit_before, due_at, updated_at
            FROM temporal_subject_state
            WHERE channel = ? AND thread_key = ?
            ORDER BY
                CASE WHEN status IN ('open', 'scheduled', 'due') THEN 0 ELSE 1 END ASC,
                updated_at DESC,
                id DESC
            """,
            (channel, thread_key),
        ).fetchall()
    ]
    for row in rows:
        status, _due, expired = _effective_status(row, now=now)
        if expired and str(row.get("status", "") or "") != "expired":
            self.conn.execute(
                "UPDATE temporal_subject_state SET status = 'expired', updated_at = ? WHERE id = ?",
                (now, int(row["id"])),
            )
    for row in rows[TEMPORAL_MAX_ITEMS:]:
        self.conn.execute("DELETE FROM temporal_subject_state WHERE id = ?", (int(row["id"]),))


def upsert_temporal_item(
    self: Any,
    *,
    item_type: str,
    channel: str,
    thread_key: str,
    chat_name: str = "",
    confidence: float = 0.58,
    source_event_id: str = "",
    source_action_ref: str = "",
    source_action_type: str = "",
    due_at: str = "",
    revisit_after: str = "",
    revisit_before: str = "",
    resume_cue: str = "",
    dedupe_key: str = "",
    status: str = "open",
    queue_job_id: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(
        normalized_channel,
        str(thread_key or "").strip(),
        chat_name=str(chat_name or "").strip(),
    )
    if not normalized_thread_key:
        return {"status": "skipped", "reason": "missing_thread_key"}
    normalized_type = _normalize_type(item_type)
    normalized_status = _normalize_status(status)
    cue = compact_text(str(resume_cue or "").strip(), 220)
    event_id = str(source_event_id or "").strip()
    action_ref = str(source_action_ref or "").strip()
    key = compact_text(str(dedupe_key or "").strip(), 160)
    if not key:
        key = _default_dedupe_key(
            channel=normalized_channel,
            thread_key=normalized_thread_key,
            item_type=normalized_type,
            source_event_id=event_id,
            source_action_ref=action_ref,
            resume_cue=cue,
        )
    now = utc_now()
    next_metadata = dict(metadata or {})
    next_metadata["evidence_refs"] = _clean_list(
        list(next_metadata.get("evidence_refs", []))
        + [f"event:{event_id}" if event_id else "", f"action:{action_ref}" if action_ref else ""],
        limit=6,
        width=120,
    )
    with self._lock:
        current = self.conn.execute(
            """
            SELECT * FROM temporal_subject_state
            WHERE channel = ? AND thread_key = ? AND dedupe_key = ? AND type = ?
            """,
            (normalized_channel, normalized_thread_key, key, normalized_type),
        ).fetchone()
        current_payload = temporal_item_from_row(self, dict(current) if current else None, now=now)
        if current_payload.get("stored_status") in TEMPORAL_TERMINAL_STATUSES and normalized_status in TEMPORAL_LIVE_STATUSES:
            return {**current_payload, "status": str(current_payload.get("status", "")), "upserted": False, "reason": "terminal_item_preserved"}
        if current:
            current_metadata = dict(current_payload.get("metadata", {}))
            merged_metadata = {
                **current_metadata,
                **next_metadata,
                "evidence_refs": _clean_list(
                    list(current_metadata.get("evidence_refs", [])) + list(next_metadata.get("evidence_refs", [])),
                    limit=6,
                    width=120,
                ),
            }
            self.conn.execute(
                """
                UPDATE temporal_subject_state
                SET chat_name = ?,
                    confidence = MAX(confidence, ?),
                    source_event_id = CASE WHEN source_event_id = '' THEN ? ELSE source_event_id END,
                    source_action_ref = CASE WHEN source_action_ref = '' THEN ? ELSE source_action_ref END,
                    source_action_type = CASE WHEN source_action_type = '' THEN ? ELSE source_action_type END,
                    due_at = CASE WHEN due_at = '' THEN ? ELSE due_at END,
                    revisit_after = CASE WHEN revisit_after = '' THEN ? ELSE revisit_after END,
                    revisit_before = CASE WHEN revisit_before = '' THEN ? ELSE revisit_before END,
                    resume_cue = CASE WHEN resume_cue = '' THEN ? ELSE resume_cue END,
                    status = ?,
                    queue_job_id = CASE WHEN queue_job_id = 0 THEN ? ELSE queue_job_id END,
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(chat_name or current_payload.get("chat_name", "") or normalized_thread_key).strip(),
                    self._clamp(confidence, default=0.58),
                    event_id,
                    action_ref,
                    str(source_action_type or "").strip(),
                    str(due_at or "").strip(),
                    str(revisit_after or "").strip(),
                    str(revisit_before or "").strip(),
                    cue,
                    normalized_status,
                    int(queue_job_id or 0),
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    int(current["id"]),
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO temporal_subject_state(
                    type, channel, thread_key, chat_name, confidence, source_event_id, source_action_ref,
                    source_action_type, due_at, revisit_after, revisit_before, resume_cue, dedupe_key,
                    status, queue_job_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_type,
                    normalized_channel,
                    normalized_thread_key,
                    str(chat_name or normalized_thread_key).strip(),
                    self._clamp(confidence, default=0.58),
                    event_id,
                    action_ref,
                    str(source_action_type or "").strip(),
                    str(due_at or "").strip(),
                    str(revisit_after or "").strip(),
                    str(revisit_before or "").strip(),
                    cue,
                    key,
                    normalized_status,
                    int(queue_job_id or 0),
                    json.dumps(next_metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        _prune_temporal_state_locked(self, channel=normalized_channel, thread_key=normalized_thread_key, now=now)
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT * FROM temporal_subject_state
            WHERE channel = ? AND thread_key = ? AND dedupe_key = ? AND type = ?
            """,
            (normalized_channel, normalized_thread_key, key, normalized_type),
        ).fetchone()
    item = temporal_item_from_row(self, dict(row) if row else None, now=now)
    if item.get("upserted") is None and hasattr(self, "upsert_task_world_object") and normalized_type in {"commitment", "resume_candidate", "deferred_intention"} and cue:
        object_type = "schedule" if str(due_at or revisit_after or "").strip() else "task"
        task_world = self.upsert_task_world_object(
            object_type=object_type,
            summary=cue,
            source_ref=event_id or action_ref or f"temporal:{key}",
            confidence=max(0.62, float(item.get("confidence", 0.0) or 0.0)),
            stale_after=str(revisit_before or due_at or ""),
            linked_threads=[normalized_thread_key],
            linked_commitments=[key],
            status="live" if normalized_status in TEMPORAL_LIVE_STATUSES else "done",
            metadata={
                "source": "temporal_subject_state",
                "temporal_item_type": normalized_type,
                "temporal_dedupe_key": key,
                "source_action_type": str(source_action_type or "").strip(),
                "evidence_refs": list(next_metadata.get("evidence_refs", [])),
            },
        )
        if task_world.get("present", False):
            item["task_world_object_id"] = str(task_world.get("object_id", "") or "")
    item["upserted"] = True
    return item


def update_temporal_item_status(
    self: Any,
    *,
    channel: str,
    thread_key: str,
    chat_name: str = "",
    item_type: str | None = None,
    dedupe_key: str = "",
    source_event_id: str = "",
    source_action_ref: str = "",
    status: str,
    metadata: dict[str, Any] | None = None,
    limit: int = TEMPORAL_MAX_LIVE_PER_THREAD,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
    if not normalized_thread_key:
        return {"status": "skipped", "reason": "missing_thread_key", "updated": 0, "items": []}
    next_status = _normalize_status(status)
    now = utc_now()
    clauses = ["channel = ?", "thread_key = ?", "status IN ('open', 'scheduled', 'due')"]
    args: list[Any] = [normalized_channel, normalized_thread_key]
    if item_type:
        clauses.append("type = ?")
        args.append(_normalize_type(item_type))
    if dedupe_key:
        clauses.append("dedupe_key = ?")
        args.append(str(dedupe_key).strip())
    if source_event_id:
        clauses.append("source_event_id = ?")
        args.append(str(source_event_id).strip())
    if source_action_ref:
        clauses.append("source_action_ref = ?")
        args.append(str(source_action_ref).strip())
    if len(args) <= 2:
        return {"status": "skipped", "reason": "missing_selector", "updated": 0, "items": []}
    if next_status == "fulfilled" and _normalize_type(str(item_type or "")) != "commitment":
        clauses.append(
            "NOT (type = 'commitment' AND status = 'scheduled' AND ((due_at != '' AND due_at > ?) OR (revisit_after != '' AND revisit_after > ?)))"
        )
        args.extend([now, now])
    with self._lock:
        rows = [
            dict(row)
            for row in self.conn.execute(
                f"SELECT * FROM temporal_subject_state WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",
                tuple(args + [max(1, int(limit))]),
            ).fetchall()
        ]
        updated: list[dict[str, Any]] = []
        for row in rows:
            row_metadata = _json_dict(row.get("metadata_json", "{}"))
            row_metadata.update(dict(metadata or {}))
            row_metadata["status_reason"] = compact_text(str(row_metadata.get("status_reason", "") or next_status), 160)
            self.conn.execute(
                "UPDATE temporal_subject_state SET status = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
                (next_status, json.dumps(row_metadata, ensure_ascii=False, sort_keys=True), now, int(row["id"])),
            )
            row["status"] = next_status
            row["metadata_json"] = json.dumps(row_metadata, ensure_ascii=False, sort_keys=True)
            row["updated_at"] = now
            updated.append(temporal_item_from_row(self, row, now=now))
        self.conn.commit()
    return {"status": "ok", "updated": len(updated), "items": updated}


def close_temporal_items(
    self: Any,
    *,
    channel: str,
    thread_key: str,
    chat_name: str = "",
    item_type: str | None = None,
    dedupe_key: str = "",
    source_event_id: str = "",
    source_action_ref: str = "",
    status: str = "fulfilled",
    reason: str = "",
) -> dict[str, Any]:
    return update_temporal_item_status(
        self,
        channel=channel,
        thread_key=thread_key,
        chat_name=chat_name,
        item_type=item_type,
        dedupe_key=dedupe_key,
        source_event_id=source_event_id,
        source_action_ref=source_action_ref,
        status=status,
        metadata={"status_reason": reason or status},
    )


def temporal_state(
    self: Any,
    *,
    channel: str = "wechat",
    thread_key: str | None = None,
    chat_name: str | None = None,
    include_inactive: bool = False,
    limit: int = TEMPORAL_MAX_ITEMS,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(
        normalized_channel,
        str(thread_key or "").strip(),
        chat_name=str(chat_name or "").strip(),
    )
    if not normalized_thread_key:
        return {
            "status": "ok",
            "thread_key": "",
            "chat_name": str(chat_name or ""),
            "channel": normalized_channel,
            "items": [],
            "open_loops": [],
            "commitments": [],
            "deferred_intentions": [],
            "interruption_markers": [],
            "resume_candidates": [],
            "due_followup_keys": [],
        }
    now = utc_now()
    with self._lock:
        _prune_temporal_state_locked(self, channel=normalized_channel, thread_key=normalized_thread_key, now=now)
        self.conn.commit()
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM temporal_subject_state
                WHERE channel = ? AND thread_key = ?
                ORDER BY
                    CASE WHEN status IN ('open', 'scheduled', 'due') THEN 0 ELSE 1 END ASC,
                    due_at ASC,
                    updated_at DESC
                LIMIT ?
                """,
                (normalized_channel, normalized_thread_key, max(1, int(limit))),
            ).fetchall()
        ]
    items = [temporal_item_from_row(self, row, now=now) for row in rows]
    if not include_inactive:
        items = [item for item in items if bool(item.get("present", False))]
    grouped = {
        "open_loops": [item for item in items if item.get("type") == "open_loop"],
        "commitments": [item for item in items if item.get("type") == "commitment"],
        "deferred_intentions": [item for item in items if item.get("type") == "deferred_intention"],
        "interruption_markers": [item for item in items if item.get("type") == "interruption_marker"],
        "resume_candidates": [item for item in items if item.get("type") == "resume_candidate"],
    }
    due_keys = _clean_list(
        item.get("dedupe_key", "")
        for item in items
        if bool(item.get("due", False)) and bool(item.get("present", False))
    )[:8]
    return {
        "status": "ok",
        "thread_key": normalized_thread_key,
        "chat_name": str(chat_name or normalized_thread_key),
        "channel": normalized_channel,
        "include_inactive": bool(include_inactive),
        "items": items,
        **grouped,
        "due_followup_keys": due_keys,
        "counts": {
            "open_loops": len(grouped["open_loops"]),
            "commitments": len(grouped["commitments"]),
            "deferred_intentions": len(grouped["deferred_intentions"]),
            "interruption_markers": len(grouped["interruption_markers"]),
            "resume_candidates": len(grouped["resume_candidates"]),
            "due_followup_keys": len(due_keys),
        },
    }


def show_open_loops(self: Any, *, channel: str = "wechat", thread_key: str | None = None, chat_name: str | None = None, include_inactive: bool = False) -> dict[str, Any]:
    state = temporal_state(self, channel=channel, thread_key=thread_key, chat_name=chat_name, include_inactive=include_inactive)
    return {**state, "items": list(state.get("open_loops", []))}


def show_commitments(self: Any, *, channel: str = "wechat", thread_key: str | None = None, chat_name: str | None = None, include_inactive: bool = False) -> dict[str, Any]:
    state = temporal_state(self, channel=channel, thread_key=thread_key, chat_name=chat_name, include_inactive=include_inactive)
    return {
        **state,
        "items": list(state.get("commitments", [])) + list(state.get("deferred_intentions", [])),
    }


def trace_resume_candidate(self: Any, *, channel: str = "wechat", thread_key: str | None = None, chat_name: str | None = None, include_inactive: bool = False) -> dict[str, Any]:
    state = temporal_state(self, channel=channel, thread_key=thread_key, chat_name=chat_name, include_inactive=include_inactive)
    candidates = list(state.get("resume_candidates", [])) + list(state.get("interruption_markers", [])) + list(state.get("open_loops", []))
    due_candidates = [item for item in candidates if bool(item.get("due", False))]
    selected = (due_candidates or candidates or [{}])[0]
    return {
        **state,
        "resume_candidates": candidates,
        "selected_resume_candidate": selected,
        "resume_available": bool(selected),
        "resume_cue": str(selected.get("resume_cue", "") if selected else ""),
    }
