from __future__ import annotations

import hashlib
import json

from kernel_v3.contracts import JsonObject


STRUCTURED_SUMMARY_KEYS = {
    "source",
    "topic",
    "profile_format",
    "detail_level",
    "gaps",
    "prior_gaps",
    "attempt",
    "answer_chars",
    "target_sections",
    "minimum_coverage",
    "citation_refs",
    "used_evidence",
    "next_possible_action",
    "failure_reason",
    "outcome",
    "attempted_actions",
    "attempted_sources",
    "missing_evidence",
    "limitations",
    "host_failure_diagnosis",
    "host_retrieval_available",
    "root_goal_preview",
    "domain",
    "source_proposal_ids",
    "source_kinds",
    "next_possible_actions",
    "entry_count",
}


def structured_memory_summary(value: JsonObject, *, text_limit: int = 180, list_item_limit: int = 140) -> JsonObject:
    if not value:
        return {}
    keys = sorted(str(key) for key in value)
    safe_values: JsonObject = {}
    for key in keys:
        if key not in STRUCTURED_SUMMARY_KEYS:
            continue
        projected = _structured_value(value.get(key), text_limit=text_limit, list_item_limit=list_item_limit)
        if projected not in (None, [], {}):
            safe_values[key] = projected
    if not safe_values or set(safe_values) <= {"source"}:
        return {}
    return {
        "keys": keys[:24],
        "key_count": len(keys),
        "values": safe_values,
        "hash": hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _structured_value(value: object, *, text_limit: int, list_item_limit: int) -> object:
    if isinstance(value, str):
        return _preview(value, text_limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        projected = []
        for item in value[:16]:
            if isinstance(item, str):
                projected.append(_preview(item, list_item_limit))
            elif isinstance(item, (int, float, bool)) or item is None:
                projected.append(item)
        return projected
    return None


def _preview(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."
