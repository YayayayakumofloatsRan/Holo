from __future__ import annotations

from typing import Any


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id", "") or "").strip()


def _row_score(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_tags(row: dict[str, Any]) -> list[str]:
    tags = row.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags if str(tag).strip()]


def plan_ready_candidates(rag: Any, *, limit: int = 8) -> dict[str, Any]:
    candidate_rows = rag.load_rows("candidate")
    durable_rows = rag.load_rows("durable")
    ordered = sorted(
        candidate_rows,
        key=lambda row: (
            bool(row.get("explicit_user_signal", False)),
            _row_score(row, "confidence"),
            _row_score(row, "importance"),
            row.get("last_seen_at", ""),
        ),
        reverse=True,
    )
    would_apply: list[dict[str, Any]] = []
    would_skip: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    threshold = float(getattr(rag, "MATCH_REINFORCE_THRESHOLD", 0.82))

    for row in ordered:
        if len(selected_ids) >= max(0, int(limit)):
            break
        candidate_id = _row_id(row)
        if not candidate_id:
            would_skip.append({"candidate_id": "", "reason": "missing_id"})
            continue
        promotable, reason = rag.can_promote(row)
        if not promotable:
            would_skip.append({"candidate_id": candidate_id, "reason": str(reason)})
            continue

        score, match = rag.find_best_match(
            durable_rows,
            str(row.get("kind", "")),
            str(row.get("text", "")),
            _safe_tags(row),
        )
        action = "promote_new"
        target_id = ""
        if match and float(score) >= threshold:
            action = "merge_existing"
            target_id = _row_id(match)

        selected_ids.add(candidate_id)
        would_apply.append(
            {
                "candidate_id": candidate_id,
                "action": action,
                "target_id": target_id,
                "match_score": round(float(score or 0.0), 4),
                "kind": str(row.get("kind", "") or ""),
                "confidence": round(_row_score(row, "confidence"), 4),
                "importance": round(_row_score(row, "importance"), 4),
                "explicit_user_signal": bool(row.get("explicit_user_signal", False)),
            }
        )

    return {
        "status": "plan",
        "dry_run": True,
        "limit": max(0, int(limit)),
        "candidate_count": len(candidate_rows),
        "durable_count": len(durable_rows),
        "would_apply": would_apply,
        "would_skip": would_skip,
        "remaining_after_plan": max(0, len(candidate_rows) - len(selected_ids)),
        "privacy": {
            "raw_text_included": False,
            "redaction_policy": "candidate text is used for matching but not emitted",
        },
    }
