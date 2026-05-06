from __future__ import annotations

import json
from typing import Any

from ..common import compact_text, utc_now
from .state_defaults import AUTOBIOGRAPHICAL_CHAPTER_DEFAULT, AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS


def update_autobiographical_state(
    self: Any,
    payload: dict[str, Any],
    *,
    reason: str = "",
    source: str = "runtime",
) -> dict[str, Any]:
    current = self.autobiographical_state()
    now = utc_now()

    def _merge_rows(key: str, *, cap: int = 8) -> list[Any]:
        rows: list[Any] = []
        for item in list(current.get(key, [])) + list(payload.get(key, [])):
            if item in rows:
                continue
            rows.append(item)
        return rows[:cap]

    stable_traits = [str(item).strip() for item in _merge_rows("stable_traits", cap=8) if str(item).strip()]
    unresolved = [str(item).strip() for item in _merge_rows("unresolved_tensions", cap=8) if str(item).strip()]
    next_state = {
        "identity_arc": compact_text(str(payload.get("identity_arc", current.get("identity_arc", "")) or current.get("identity_arc", "")), 400),
        "current_chapter": compact_text(
            str(payload.get("current_chapter", current.get("current_chapter", AUTOBIOGRAPHICAL_CHAPTER_DEFAULT)) or current.get("current_chapter", AUTOBIOGRAPHICAL_CHAPTER_DEFAULT)),
            200,
        ),
        "turning_points": _merge_rows("turning_points", cap=12),
        "recent_changes": _merge_rows("recent_changes", cap=12),
        "stable_traits": stable_traits or list(AUTOBIOGRAPHICAL_STABLE_TRAITS_DEFAULTS),
        "preference_history": _merge_rows("preference_history", cap=12),
        "attachment_history": _merge_rows("attachment_history", cap=12),
        "unresolved_tensions": unresolved,
        "self_explanations": _merge_rows("self_explanations", cap=12),
        "metadata": {
            **dict(current.get("metadata", {})),
            **dict(payload.get("metadata", {})),
            "last_reason": compact_text(reason, 160),
            "last_source": str(source or "runtime"),
            "updated_at": now,
        },
    }
    with self._lock:
        self.conn.execute(
            """
            INSERT INTO autobiographical_state(
                runtime_id, identity_arc, current_chapter, turning_points_json, recent_changes_json, stable_traits_json,
                preference_history_json, attachment_history_json, unresolved_tensions_json, self_explanations_json,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(runtime_id) DO UPDATE SET
                identity_arc = excluded.identity_arc,
                current_chapter = excluded.current_chapter,
                turning_points_json = excluded.turning_points_json,
                recent_changes_json = excluded.recent_changes_json,
                stable_traits_json = excluded.stable_traits_json,
                preference_history_json = excluded.preference_history_json,
                attachment_history_json = excluded.attachment_history_json,
                unresolved_tensions_json = excluded.unresolved_tensions_json,
                self_explanations_json = excluded.self_explanations_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                1,
                next_state["identity_arc"],
                next_state["current_chapter"],
                json.dumps(next_state["turning_points"], ensure_ascii=False),
                json.dumps(next_state["recent_changes"], ensure_ascii=False),
                json.dumps(next_state["stable_traits"], ensure_ascii=False),
                json.dumps(next_state["preference_history"], ensure_ascii=False),
                json.dumps(next_state["attachment_history"], ensure_ascii=False),
                json.dumps(next_state["unresolved_tensions"], ensure_ascii=False),
                json.dumps(next_state["self_explanations"], ensure_ascii=False),
                json.dumps(next_state["metadata"], ensure_ascii=False, sort_keys=True),
                str(current.get("created_at", "") or now),
                now,
            ),
        )
        self.conn.commit()
    updated = self.autobiographical_state()
    updated["status"] = "ok"
    updated["reason"] = reason
    updated["source"] = source
    return updated
