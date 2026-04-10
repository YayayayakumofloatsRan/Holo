from __future__ import annotations

import json
from typing import Any, Iterable

from ..common import compact_text, stable_digest, utc_now

POLICY_SEDIMENT_STATUSES = {"candidate", "promoted", "rejected", "rolled_back"}
POLICY_REPLAY_STATUSES = {"pending", "approved", "rejected", "rolled_back"}
POLICY_SEDIMENT_SUPPORTED_ACTIONS = {
    "silence",
    "defer_reply",
    "push_back",
    "counter_offer",
    "continuity_defense",
    "proactive_ping",
    "initiative_ping",
}
POLICY_SEDIMENT_MIN_SUPPORT = 3
POLICY_SEDIMENT_MIN_CONFIDENCE = 0.55
POLICY_SEDIMENT_MAX_SHIFT = 0.18


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        payload = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    try:
        payload = json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(payload) if isinstance(payload, list) else []


def _clean_refs(values: Iterable[Any], *, limit: int = 8) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_text(str(value or "").strip(), 140)
        if not text or text in seen:
            continue
        seen.add(text)
        refs.append(text)
        if len(refs) >= limit:
            break
    return refs


def _clamp(value: Any, *, lower: float = -POLICY_SEDIMENT_MAX_SHIFT, upper: float = POLICY_SEDIMENT_MAX_SHIFT, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return round(max(lower, min(upper, numeric)), 4)


def _unit(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return round(max(0.0, min(1.0, numeric)), 4)


def _action_family(action_type: str) -> str:
    action = str(action_type or "").strip()
    if action in {"silence", "defer_reply"}:
        return "hold"
    if action in {"push_back", "counter_offer", "continuity_defense"}:
        return "resistance"
    if action in {"proactive_ping", "initiative_ping"}:
        return "initiative"
    if action in {"reply_once", "reply_multi"}:
        return "reply"
    return action or "unknown"


def _status(value: str) -> str:
    current = str(value or "").strip().lower()
    return current if current in POLICY_SEDIMENT_STATUSES else "candidate"


def _replay_status(value: str) -> str:
    current = str(value or "").strip().lower()
    return current if current in POLICY_REPLAY_STATUSES else "pending"


def policy_sediment_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"present": False, "status": "missing"}
    item = dict(row)
    metadata = _json_dict(item.pop("metadata_json", "{}"))
    scenario_features = _json_dict(item.pop("scenario_features_json", "{}"))
    evidence_refs = _clean_refs(_json_list(item.pop("evidence_refs_json", "[]")), limit=8)
    item["present"] = True
    item["status"] = _status(str(item.get("status", "") or "candidate"))
    item["replay_approval_status"] = _replay_status(str(item.get("replay_approval_status", "") or "pending"))
    item["scenario_features"] = scenario_features
    item["evidence_refs"] = evidence_refs
    item["metadata"] = metadata
    item["action_preference_shift"] = float(item.get("action_preference_shift", 0.0) or 0.0)
    item["support_count"] = int(item.get("support_count", 0) or 0)
    item["recency_support"] = float(item.get("recency_support", 0.0) or 0.0)
    item["observed_regret_delta"] = float(item.get("observed_regret_delta", 0.0) or 0.0)
    item["confidence"] = float(item.get("confidence", 0.0) or 0.0)
    return item


def policy_scenario_bucket(
    self: Any,
    *,
    channel: str = "wechat",
    thread_key: str | None = None,
    chat_name: str | None = None,
    action_type: str,
    calibration_bucket: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    calibration_row: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(
        normalized_channel,
        str(thread_key or "").strip(),
        chat_name=str(chat_name or "").strip(),
    )
    bucket = dict(calibration_bucket or {})
    row = dict(calibration_row or {})
    candidate_payload = dict(candidate or {})
    meta = dict(metadata or {})
    base_bucket = str(bucket.get("scenario_bucket", "") or "").strip()
    if not base_bucket:
        base_bucket = f"{_action_family(action_type)}:ordinary"
    frontier = dict(meta.get("stage19", {})) if isinstance(meta.get("stage19", {}), dict) else {}
    warmth = str(meta.get("thread_warmth", "") or frontier.get("thread_warmth", "") or "").strip().lower()
    if not warmth:
        heat = float(frontier.get("thread_heat", 0.0) or 0.0)
        if heat >= 0.7:
            warmth = "hot"
        elif heat >= 0.24 or bool(frontier.get("frontier_used_for_thread", False)):
            warmth = "warm"
        else:
            warmth = "cold"
    if warmth not in {"hot", "warm", "cold", "frontier-warm"}:
        warmth = "warm" if warmth.startswith("warm") else "cold"

    predicted = dict(candidate_payload.get("predicted_outcome", {})) if isinstance(candidate_payload.get("predicted_outcome", {}), dict) else {}
    predicted_risk = _unit(predicted.get("predicted_risk", candidate_payload.get("predicted_risk", row.get("risk_mae", 0.0))))
    ignored_rate = _unit(row.get("ignored_rate", meta.get("ignored_rate", 0.0)))
    correction_rate = _unit(row.get("correction_rate", meta.get("correction_rate", 0.0)))
    relationship_tension = _unit(meta.get("relationship_tension", max(predicted_risk, ignored_rate)))
    tension_band = "tense" if max(relationship_tension, predicted_risk, ignored_rate) >= 0.45 else "relaxed"
    correction_band = "correction_heavy" if correction_rate >= 0.34 or int(meta.get("correction_count", 0) or 0) >= 2 else "relaxed"
    if "high_risk" in base_bucket or predicted_risk >= 0.45:
        turn_risk = "high_risk_ambiguity"
    elif "low_signal" in base_bucket or bool(meta.get("low_signal", False)):
        turn_risk = "low_risk_short"
    else:
        turn_risk = "ordinary"
    family = _action_family(str(action_type or ""))
    features = {
        "channel": normalized_channel,
        "thread_key": normalized_thread_key,
        "thread_warmth": warmth,
        "relationship_tension": tension_band,
        "correction_pattern": correction_band,
        "turn_risk": turn_risk,
        "action_family": family,
        "base_calibration_bucket": base_bucket,
    }
    scenario_bucket = "|".join(
        [
            f"channel={normalized_channel}",
            f"warmth={warmth}",
            f"tension={tension_band}",
            f"correction={correction_band}",
            f"turn={turn_risk}",
            f"family={family}",
            f"base={base_bucket}",
        ]
    )
    return {
        "scenario_bucket": scenario_bucket,
        "scenario_features": features,
        "bucket_reason": compact_text(f"{family} policy on {normalized_channel} under {turn_risk}/{tension_band}/{correction_band}", 180),
    }


def _shift_from_calibration(row: dict[str, Any]) -> tuple[float, float]:
    support = max(0, int(row.get("support_count", 0) or 0))
    confidence = _unit(row.get("confidence", 0.0))
    support_scale = min(1.0, support / 6.0)
    response_fit = max(0.0, 1.0 - float(row.get("response_quality_mae", 0.0) or 0.0))
    relational_fit = max(0.0, 1.0 - float(row.get("relational_delta_mae", 0.0) or 0.0))
    risk_fit = max(0.0, 1.0 - float(row.get("risk_mae", 0.0) or 0.0))
    latency_fit = max(0.0, 1.0 - float(row.get("avg_reply_latency", 0.0) or 0.0) / 3600.0)
    ignored_rate = _unit(row.get("ignored_rate", 0.0))
    correction_rate = _unit(row.get("correction_rate", 0.0))
    risk_mae = _unit(row.get("risk_mae", 0.0))
    benefit = response_fit * 0.42 + relational_fit * 0.24 + risk_fit * 0.18 + latency_fit * 0.16
    penalty = ignored_rate * 0.34 + correction_rate * 0.26 + risk_mae * 0.2
    raw = benefit - penalty - 0.48
    shift = _clamp(raw * confidence * support_scale * 0.44)
    regret_delta = round(-abs(shift) * max(0.5, confidence), 4)
    return shift, regret_delta


def _promotable(row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("support_count", 0) or 0) >= POLICY_SEDIMENT_MIN_SUPPORT
        and float(row.get("confidence", 0.0) or 0.0) >= POLICY_SEDIMENT_MIN_CONFIDENCE
        and abs(float(row.get("action_preference_shift", 0.0) or 0.0)) > 0.0
        and float(row.get("observed_regret_delta", 0.0) or 0.0) <= -0.001
        and _clean_refs(row.get("evidence_refs", []), limit=1)
    )


def upsert_policy_candidate_from_calibration(
    self: Any,
    *,
    channel: str,
    thread_key: str,
    chat_name: str = "",
    action_type: str,
    calibration_row: dict[str, Any],
    calibration_bucket: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ..mind_graph import _normalize_thread_key

    action = str(action_type or "").strip()
    if action not in POLICY_SEDIMENT_SUPPORTED_ACTIONS:
        return {"status": "skipped", "reason": "unsupported_action", "action_type": action}
    row = dict(calibration_row or {})
    support = int(row.get("support_count", 0) or 0)
    if support < POLICY_SEDIMENT_MIN_SUPPORT:
        return {"status": "skipped", "reason": "insufficient_support", "support_count": support, "action_type": action}
    confidence = _unit(row.get("confidence", 0.0))
    if confidence < POLICY_SEDIMENT_MIN_CONFIDENCE:
        return {"status": "skipped", "reason": "low_confidence", "confidence": confidence, "action_type": action}
    row_metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else _json_dict(row.get("metadata_json", "{}"))
    supplied_metadata = dict(metadata or {})
    evidence_refs = _clean_refs(
        list(row_metadata.get("evidence_refs", []))
        + list(supplied_metadata.get("evidence_refs", []))
        + [str(row_metadata.get("last_action_ref", "") or "")],
        limit=8,
    )
    if not evidence_refs:
        return {"status": "skipped", "reason": "missing_evidence_refs", "action_type": action}
    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
    if not normalized_thread_key:
        return {"status": "skipped", "reason": "missing_thread_key", "action_type": action}
    scenario = policy_scenario_bucket(
        self,
        channel=normalized_channel,
        thread_key=normalized_thread_key,
        chat_name=chat_name,
        action_type=action,
        calibration_bucket=calibration_bucket or row.get("calibration_bucket", {}),
        calibration_row=row,
        metadata=supplied_metadata,
    )
    shift, regret_delta = _shift_from_calibration(row)
    if abs(shift) < 0.001:
        return {"status": "skipped", "reason": "weak_shift", "action_type": action}
    scenario_bucket = str(scenario["scenario_bucket"])
    policy_id = "policy:" + stable_digest(normalized_channel, normalized_thread_key, scenario_bucket, action, limit=24)
    now = utc_now()
    next_metadata = {
        "source": str(supplied_metadata.get("source", "outcome_appraisal") or "outcome_appraisal"),
        "stage": "stage21",
        "calibration_row_id": int(row.get("id", 0) or 0),
        "calibration_bucket": dict(calibration_bucket or {}),
        "bucket_reason": str(scenario.get("bucket_reason", "")),
        "last_updated_by": "policy_sedimentation",
    }
    with self._lock:
        current_row = self.conn.execute(
            """
            SELECT * FROM policy_sediment
            WHERE channel = ? AND thread_key = ? AND scenario_bucket = ? AND action_type = ?
            """,
            (normalized_channel, normalized_thread_key, scenario_bucket, action),
        ).fetchone()
        current = policy_sediment_from_row(dict(current_row) if current_row else None)
        terminal = str(current.get("status", "")) in {"rejected", "rolled_back"}
        replay_status = _replay_status(str(current.get("replay_approval_status", "pending") or "pending")) if current.get("present") else "pending"
        status = str(current.get("status", "candidate") or "candidate") if current.get("present") else "candidate"
        if not terminal and replay_status == "approved":
            candidate_view = {
                "support_count": support,
                "confidence": confidence,
                "action_preference_shift": shift,
                "observed_regret_delta": regret_delta,
                "evidence_refs": evidence_refs,
            }
            status = "promoted" if _promotable(candidate_view) else "candidate"
        elif not terminal:
            status = "candidate"
        merged_metadata = {
            **(dict(current.get("metadata", {})) if current.get("present") else {}),
            **next_metadata,
        }
        rollback_handle = str(current.get("rollback_handle", "") or "")
        promoted_at = str(current.get("promoted_at", "") or "")
        if status == "promoted" and not promoted_at:
            promoted_at = now
        if current.get("present"):
            self.conn.execute(
                """
                UPDATE policy_sediment
                SET support_count = ?,
                    recency_support = ?,
                    observed_regret_delta = ?,
                    confidence = ?,
                    action_preference_shift = ?,
                    scenario_features_json = ?,
                    evidence_refs_json = ?,
                    metadata_json = ?,
                    replay_approval_status = ?,
                    status = ?,
                    rollback_handle = ?,
                    promoted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    support,
                    float(row.get("recent_support_count", 0.0) or 0.0),
                    regret_delta,
                    confidence,
                    shift,
                    json.dumps(dict(scenario.get("scenario_features", {})), ensure_ascii=False, sort_keys=True),
                    json.dumps(evidence_refs, ensure_ascii=False, sort_keys=True),
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    replay_status,
                    status,
                    rollback_handle,
                    promoted_at,
                    now,
                    int(current["id"]),
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO policy_sediment(
                    policy_id, channel, thread_key, scenario_bucket, scenario_features_json, action_type,
                    action_preference_shift, support_count, recency_support, observed_regret_delta,
                    confidence, replay_approval_status, rollback_handle, status, evidence_refs_json,
                    metadata_json, created_at, updated_at, promoted_at, rolled_back_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    policy_id,
                    normalized_channel,
                    normalized_thread_key,
                    scenario_bucket,
                    json.dumps(dict(scenario.get("scenario_features", {})), ensure_ascii=False, sort_keys=True),
                    action,
                    shift,
                    support,
                    float(row.get("recent_support_count", 0.0) or 0.0),
                    regret_delta,
                    confidence,
                    replay_status,
                    status,
                    json.dumps(evidence_refs, ensure_ascii=False, sort_keys=True),
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    promoted_at,
                ),
            )
        self.conn.commit()
        refreshed = self.conn.execute("SELECT * FROM policy_sediment WHERE policy_id = ?", (policy_id,)).fetchone()
    payload = policy_sediment_from_row(dict(refreshed) if refreshed else None)
    payload["upserted"] = bool(payload.get("present", False))
    return payload


def list_policy_sediment(
    self: Any,
    *,
    channel: str | None = None,
    thread_key: str | None = None,
    chat_name: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    from ..mind_graph import _normalize_thread_key

    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
    clauses: list[str] = []
    args: list[Any] = []
    if normalized_channel:
        clauses.append("channel = ?")
        args.append(normalized_channel)
    if normalized_thread_key:
        clauses.append("thread_key = ?")
        args.append(normalized_thread_key)
    if str(status or "").strip():
        clauses.append("status = ?")
        args.append(_status(str(status or "")))
    if str(action_type or "").strip():
        clauses.append("action_type = ?")
        args.append(str(action_type or "").strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(max(1, int(limit or 24)))
    with self._lock:
        rows = [
            dict(row)
            for row in self.conn.execute(
                f"""
                SELECT * FROM policy_sediment
                {where}
                ORDER BY
                    CASE status WHEN 'promoted' THEN 0 WHEN 'candidate' THEN 1 ELSE 2 END ASC,
                    confidence DESC,
                    support_count DESC,
                    updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
        ]
    return [policy_sediment_from_row(row) for row in rows]


def promoted_policy_overlays(
    self: Any,
    *,
    channel: str,
    thread_key: str,
    chat_name: str = "",
    action_type: str,
    scenario_bucket: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    from ..mind_graph import _normalize_thread_key

    action = str(action_type or "").strip()
    if action not in POLICY_SEDIMENT_SUPPORTED_ACTIONS:
        return []
    normalized_channel = str(channel or "wechat").strip() or "wechat"
    normalized_thread_key = _normalize_thread_key(normalized_channel, str(thread_key or "").strip(), chat_name=str(chat_name or "").strip())
    if not normalized_thread_key:
        return []
    with self._lock:
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM policy_sediment
                WHERE channel = ?
                  AND thread_key = ?
                  AND action_type = ?
                  AND scenario_bucket = ?
                  AND status = 'promoted'
                  AND replay_approval_status = 'approved'
                ORDER BY confidence DESC, support_count DESC, promoted_at DESC
                LIMIT ?
                """,
                (normalized_channel, normalized_thread_key, action, scenario_bucket, max(1, int(limit or 3))),
            ).fetchall()
        ]
    return [policy_sediment_from_row(row) for row in rows]


def review_policy_candidate(
    self: Any,
    *,
    policy_id: str | None = None,
    row_id: int | None = None,
    approved: bool | None = None,
    replay_report: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    clauses: list[str] = []
    args: list[Any] = []
    if row_id is not None:
        clauses.append("id = ?")
        args.append(int(row_id))
    elif str(policy_id or "").strip():
        clauses.append("policy_id = ?")
        args.append(str(policy_id or "").strip())
    else:
        return {"status": "skipped", "reason": "missing_policy_id"}
    now = utc_now()
    with self._lock:
        row = self.conn.execute(f"SELECT * FROM policy_sediment WHERE {' AND '.join(clauses)}", tuple(args)).fetchone()
        if not row:
            return {"status": "missing", "reason": "policy_not_found"}
        current = policy_sediment_from_row(dict(row))
        report = dict(replay_report or {})
        if approved is None:
            metrics = dict(report.get("aggregate_metrics", {}))
            approved = bool(report.get("fixture_count", 0)) and float(metrics.get("policy_regret_vs_best_available_action", 1.0) or 1.0) <= float(dict(current.get("metadata", {})).get("baseline_policy_regret", metrics.get("policy_regret_vs_best_available_action", 1.0)) or 1.0) + 0.001
        replay_status = "approved" if bool(approved) else "rejected"
        next_status = str(current.get("status", "candidate") or "candidate")
        if replay_status == "rejected":
            next_status = "rejected"
        elif replay_status == "approved" and _promotable(current):
            next_status = "promoted"
        metadata = {
            **dict(current.get("metadata", {})),
            "replay_gate": {
                "status": replay_status,
                "reason": compact_text(str(reason or "stage21_replay_gate"), 180),
                "aggregate_metrics": dict(report.get("aggregate_metrics", {})),
                "at": now,
            },
        }
        promoted_at = str(current.get("promoted_at", "") or "")
        if next_status == "promoted" and not promoted_at:
            promoted_at = now
        self.conn.execute(
            """
            UPDATE policy_sediment
            SET replay_approval_status = ?,
                status = ?,
                metadata_json = ?,
                promoted_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                replay_status,
                next_status,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                promoted_at,
                now,
                int(current["id"]),
            ),
        )
        self.conn.commit()
        refreshed = self.conn.execute("SELECT * FROM policy_sediment WHERE id = ?", (int(current["id"]),)).fetchone()
    payload = policy_sediment_from_row(dict(refreshed) if refreshed else None)
    payload["reviewed"] = True
    return payload


def rollback_policy(self: Any, *, policy_id: str | None = None, row_id: int | None = None, reason: str = "") -> dict[str, Any]:
    clauses: list[str] = []
    args: list[Any] = []
    if row_id is not None:
        clauses.append("id = ?")
        args.append(int(row_id))
    elif str(policy_id or "").strip():
        current = str(policy_id or "").strip()
        if current.isdigit():
            clauses.append("id = ?")
            args.append(int(current))
        else:
            clauses.append("policy_id = ?")
            args.append(current)
    else:
        return {"status": "skipped", "reason": "missing_policy_id"}
    now = utc_now()
    with self._lock:
        row = self.conn.execute(f"SELECT * FROM policy_sediment WHERE {' AND '.join(clauses)}", tuple(args)).fetchone()
        if not row:
            return {"status": "missing", "reason": "policy_not_found"}
        current = policy_sediment_from_row(dict(row))
        rollback_handle = str(current.get("rollback_handle", "") or "")
        if not rollback_handle:
            rollback_handle = "rollback:" + stable_digest(str(current.get("policy_id", "")), now, limit=24)
        metadata = {
            **dict(current.get("metadata", {})),
            "rollback": {
                "previous_status": str(current.get("status", "")),
                "previous_replay_approval_status": str(current.get("replay_approval_status", "")),
                "previous_action_preference_shift": float(current.get("action_preference_shift", 0.0) or 0.0),
                "reason": compact_text(str(reason or "manual_rollback"), 180),
                "at": now,
            },
        }
        self.conn.execute(
            """
            UPDATE policy_sediment
            SET status = 'rolled_back',
                replay_approval_status = 'rolled_back',
                rollback_handle = ?,
                metadata_json = ?,
                rolled_back_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                rollback_handle,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
                int(current["id"]),
            ),
        )
        self.conn.commit()
        refreshed = self.conn.execute("SELECT * FROM policy_sediment WHERE id = ?", (int(current["id"]),)).fetchone()
    payload = policy_sediment_from_row(dict(refreshed) if refreshed else None)
    payload["rolled_back"] = bool(payload.get("status") == "rolled_back")
    return payload


def show_policy_candidates(self: Any, *, channel: str | None = None, thread_key: str | None = None, chat_name: str | None = None, limit: int = 24) -> dict[str, Any]:
    rows = list_policy_sediment(self, channel=channel, thread_key=thread_key, chat_name=chat_name, status="candidate", limit=limit)
    return {
        "status": "ok",
        "channel": str(channel or "wechat"),
        "thread_key": str(thread_key or ""),
        "chat_name": str(chat_name or ""),
        "candidates": rows,
        "count": len(rows),
    }


def show_promoted_policies(self: Any, *, channel: str | None = None, thread_key: str | None = None, chat_name: str | None = None, limit: int = 24) -> dict[str, Any]:
    rows = list_policy_sediment(self, channel=channel, thread_key=thread_key, chat_name=chat_name, status="promoted", limit=limit)
    return {
        "status": "ok",
        "channel": str(channel or "wechat"),
        "thread_key": str(thread_key or ""),
        "chat_name": str(chat_name or ""),
        "promoted_policies": rows,
        "count": len(rows),
    }
