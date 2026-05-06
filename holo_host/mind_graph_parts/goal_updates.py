from __future__ import annotations

import json
from typing import Any

from ..common import compact_text, utc_now


def goal_state(self: Any) -> dict[str, Any]:
    from ..mind_graph import _safe_json_dict

    with self._lock:
        row = self.conn.execute("SELECT * FROM goal_state WHERE runtime_id = 1").fetchone()
        if row is None:
            defaults = self._default_goal_state()
            now = utc_now()
            self.conn.execute(
                """
                INSERT INTO goal_state(
                    runtime_id, active_goals_json, dormant_goals_json, completed_goals_json, goal_commitments_json,
                    goal_progress_json, goal_conflicts_json, pursuit_bias_json, abandonment_cost_json, next_goal_windows_json,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    json.dumps(defaults["active_goals"], ensure_ascii=False),
                    json.dumps(defaults["dormant_goals"], ensure_ascii=False),
                    json.dumps(defaults["completed_goals"], ensure_ascii=False),
                    json.dumps(defaults["goal_commitments"], ensure_ascii=False),
                    json.dumps(defaults["goal_progress"], ensure_ascii=False, sort_keys=True),
                    json.dumps(defaults["goal_conflicts"], ensure_ascii=False),
                    json.dumps(defaults["pursuit_bias"], ensure_ascii=False, sort_keys=True),
                    json.dumps(defaults["abandonment_cost"], ensure_ascii=False, sort_keys=True),
                    json.dumps(defaults["next_goal_windows"], ensure_ascii=False),
                    json.dumps(defaults["metadata"], ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM goal_state WHERE runtime_id = 1").fetchone()
    payload = dict(row) if row else {}
    return {
        "active_goals": self._decode_json_array(payload.get("active_goals_json", "[]")),
        "dormant_goals": self._decode_json_array(payload.get("dormant_goals_json", "[]")),
        "completed_goals": self._decode_json_array(payload.get("completed_goals_json", "[]")),
        "goal_commitments": self._decode_json_array(payload.get("goal_commitments_json", "[]")),
        "goal_progress": {
            str(key): self.metric_state(
                value,
                default=0.0,
                confidence=0.62,
                evidence_refs=[f"goal_progress:{key}"],
                updated_at=str(payload.get("updated_at", "") or utc_now()),
                updated_by=str(dict(_safe_json_dict(payload.get("metadata_json", "{}"))).get("last_source", "") or "goal_state"),
                decay_policy="goal_continuity",
            )
            for key, value in dict(_safe_json_dict(payload.get("goal_progress_json", "{}"))).items()
        },
        "goal_conflicts": self._decode_json_array(payload.get("goal_conflicts_json", "[]")),
        "pursuit_bias": dict(_safe_json_dict(payload.get("pursuit_bias_json", "{}"))),
        "abandonment_cost": dict(_safe_json_dict(payload.get("abandonment_cost_json", "{}"))),
        "next_goal_windows": self._decode_json_array(payload.get("next_goal_windows_json", "[]")),
        "metadata": dict(_safe_json_dict(payload.get("metadata_json", "{}"))),
        "created_at": str(payload.get("created_at", "") or ""),
        "updated_at": str(payload.get("updated_at", "") or ""),
    }


def update_goal_state(
    self: Any,
    payload: dict[str, Any],
    *,
    reason: str = "",
    source: str = "runtime",
) -> dict[str, Any]:
    from ..mind_graph import _state_decay_policy, _state_evidence_refs

    current = self.goal_state()
    now = utc_now()

    def _goal_item_key(key: str, item: Any) -> str:
        if not isinstance(item, dict):
            return ""
        if key in {"active_goals", "dormant_goals", "completed_goals"}:
            return str(item.get("goal_id", "") or "").strip()
        if key == "goal_commitments":
            return str(item.get("goal_type", "") or item.get("summary", "") or "").strip()
        if key == "goal_conflicts":
            return str(item.get("summary", "") or "").strip()
        if key == "next_goal_windows":
            return str(item.get("goal_id", "") or item.get("target_thread", "") or item.get("window", "") or "").strip()
        return ""

    def _merge_list(key: str, *, cap: int = 12) -> list[Any]:
        rows: list[Any] = []
        index_by_key: dict[str, int] = {}
        for item in list(current.get(key, [])) + list(payload.get(key, [])):
            item_key = _goal_item_key(key, item)
            if item_key:
                index = index_by_key.get(item_key)
                if index is None:
                    index_by_key[item_key] = len(rows)
                    rows.append(item)
                else:
                    rows[index] = item
                continue
            if item in rows:
                continue
            rows.append(item)
        return rows[:cap]

    next_progress = {
        str(key): self.metric_state(
            value,
            default=0.0,
            confidence=0.62,
            evidence_refs=[f"goal_progress:{key}"],
            updated_at=now,
            updated_by=source,
            decay_policy="goal_continuity",
        )
        for key, value in dict(current.get("goal_progress", {})).items()
    }
    for key, value in dict(payload.get("goal_progress", {})).items():
        key_text = str(key)
        existing_metric = next_progress.get(key_text, self.metric_state(0.0, updated_at=now, updated_by=source, decay_policy="goal_continuity"))
        refs = _state_evidence_refs(existing_metric, [compact_text(reason or f"goal_progress:{key_text}", 120)])
        next_progress[key_text] = self.metric_state(
            value,
            default=self.metric_value(existing_metric, default=0.0),
            confidence=max(0.64, self.metric_confidence(value, default=self.metric_confidence(existing_metric, default=0.58))),
            evidence_refs=refs,
            updated_at=now,
            updated_by=source,
            decay_policy=_state_decay_policy(existing_metric, default="goal_continuity"),
        )
    next_pursuit_bias = dict(current.get("pursuit_bias", {}))
    next_pursuit_bias.update({str(key): self._clamp(value, default=0.0) for key, value in dict(payload.get("pursuit_bias", {})).items()})
    next_abandonment_cost = dict(current.get("abandonment_cost", {}))
    next_abandonment_cost.update({str(key): self._clamp(value, default=0.0) for key, value in dict(payload.get("abandonment_cost", {})).items()})
    next_state = {
        "active_goals": _merge_list("active_goals", cap=12),
        "dormant_goals": _merge_list("dormant_goals", cap=12),
        "completed_goals": _merge_list("completed_goals", cap=12),
        "goal_commitments": _merge_list("goal_commitments", cap=12),
        "goal_progress": next_progress,
        "goal_conflicts": _merge_list("goal_conflicts", cap=12),
        "pursuit_bias": next_pursuit_bias,
        "abandonment_cost": next_abandonment_cost,
        "next_goal_windows": _merge_list("next_goal_windows", cap=12),
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
            INSERT INTO goal_state(
                runtime_id, active_goals_json, dormant_goals_json, completed_goals_json, goal_commitments_json,
                goal_progress_json, goal_conflicts_json, pursuit_bias_json, abandonment_cost_json, next_goal_windows_json,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(runtime_id) DO UPDATE SET
                active_goals_json = excluded.active_goals_json,
                dormant_goals_json = excluded.dormant_goals_json,
                completed_goals_json = excluded.completed_goals_json,
                goal_commitments_json = excluded.goal_commitments_json,
                goal_progress_json = excluded.goal_progress_json,
                goal_conflicts_json = excluded.goal_conflicts_json,
                pursuit_bias_json = excluded.pursuit_bias_json,
                abandonment_cost_json = excluded.abandonment_cost_json,
                next_goal_windows_json = excluded.next_goal_windows_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                1,
                json.dumps(next_state["active_goals"], ensure_ascii=False),
                json.dumps(next_state["dormant_goals"], ensure_ascii=False),
                json.dumps(next_state["completed_goals"], ensure_ascii=False),
                json.dumps(next_state["goal_commitments"], ensure_ascii=False),
                json.dumps(next_state["goal_progress"], ensure_ascii=False, sort_keys=True),
                json.dumps(next_state["goal_conflicts"], ensure_ascii=False),
                json.dumps(next_state["pursuit_bias"], ensure_ascii=False, sort_keys=True),
                json.dumps(next_state["abandonment_cost"], ensure_ascii=False, sort_keys=True),
                json.dumps(next_state["next_goal_windows"], ensure_ascii=False),
                json.dumps(next_state["metadata"], ensure_ascii=False, sort_keys=True),
                str(current.get("created_at", "") or now),
                now,
            ),
        )
        self.conn.commit()
    updated = self.goal_state()
    updated["status"] = "ok"
    updated["reason"] = reason
    updated["source"] = source
    return updated
