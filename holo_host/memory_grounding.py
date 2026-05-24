from __future__ import annotations

import json
import re
from typing import Any

from .common import stable_digest

MEMORY_GROUNDING_SCHEMA = "holo.memory_grounding.v1"

SOURCE_FAMILIES = {
    "working",
    "durable",
    "candidate",
    "archive",
    "mind_graph",
    "vector",
    "current_context",
    "none",
}

MEMORY_STATUSES = {"grounded", "weak", "missing", "contradicted"}

MEMORY_TOOL_NAMES = {"memory_recall", "memory_warehouse_search", "doc_lookup"}

MEMORY_CLAIM_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "memory_recall",
        (
            r"\bi remember\b",
            r"\bi recall\b",
            r"\bfrom memory\b",
            "\u6211\u8bb0\u5f97",
            "\u6211\u56de\u5fc6",
            "\u4ece\u8bb0\u5fc6\u91cc",
            "\u8bb0\u5fc6\u91cc",
        ),
    ),
    (
        "prior_user_statement",
        (
            r"\byou (?:told|said) me before\b",
            r"\byou said before\b",
            r"\bearlier you said\b",
            r"\blast time you said\b",
            "\u4f60\u4e4b\u524d\u8bf4\u8fc7",
            "\u4f60\u4ee5\u524d\u8bf4\u8fc7",
            "\u4f60\u4e0a\u6b21\u8bf4\u8fc7",
        ),
    ),
    (
        "previous_conversation",
        (
            r"\bfrom our previous conversation\b",
            r"\bwe (?:discussed|talked about)\b",
            r"\bas we discussed\b",
            "\u4ece\u4e4b\u524d\u7684\u5bf9\u8bdd",
            "\u6211\u4eec\u804a\u8fc7",
            "\u6211\u4eec\u4e4b\u524d\u804a\u8fc7",
            "\u4e0a\u6b21\u804a\u5230",
        ),
    ),
    (
        "preference_memory",
        (
            r"\byour preference was\b",
            r"\byou prefer(?:red)?\b",
            r"\byou like(?:d)?\b",
            "\u4f60\u4ee5\u524d\u7684\u504f\u597d",
            "\u4f60\u7684\u504f\u597d\u662f",
            "\u4f60\u4e4b\u524d\u504f\u597d",
        ),
    ),
)

MEMORY_REQUEST_PATTERNS = tuple(pattern for _, patterns in MEMORY_CLAIM_PATTERNS for pattern in patterns) + (
    r"\bdo you remember\b",
    r"\bcan you recall\b",
    "\u8fd8\u8bb0\u5f97",
    "\u56de\u5fc6",
    "\u8bb0\u5fc6",
    "\u6700\u65e9",
    "\u6700\u6df1\u5904",
)


def _compact(text: Any, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _digest(*parts: Any, limit: int = 10) -> str:
    normalized = [
        json.dumps(part, ensure_ascii=False, sort_keys=True) if isinstance(part, (dict, list, tuple)) else str(part)
        for part in parts
        if part is not None
    ]
    return stable_digest(*normalized, limit=limit)


def _clamp_float(value: Any, default: float = 0.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = float(default)
    return max(0.0, min(1.0, current))


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _family_for_id(memory_id: str) -> str:
    text = str(memory_id or "").strip().lower()
    if text.startswith("working"):
        return "working"
    if text.startswith("candidate"):
        return "candidate"
    if text.startswith("archive"):
        return "archive"
    if text.startswith(("vector", "milvus")):
        return "vector"
    if text.startswith(("graph", "mind", "node", "activation")):
        return "mind_graph"
    if text.startswith(("memory", "durable", "stage104")):
        return "durable"
    return "mind_graph" if text else "none"


def _dominant_family(selected_ids: list[str], *, fallback: str = "none") -> str:
    counts: dict[str, int] = {}
    for memory_id in selected_ids:
        family = _family_for_id(memory_id)
        counts[family] = counts.get(family, 0) + 1
    if not counts:
        return fallback if fallback in SOURCE_FAMILIES else "none"
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _status_for(
    *,
    source_family: str,
    selected_ids: list[str],
    confidence: float,
    missing_source: bool = False,
    contradicted: bool = False,
) -> str:
    if contradicted:
        return "contradicted"
    if missing_source or source_family == "none":
        return "missing"
    if source_family == "current_context" and not selected_ids:
        return "weak"
    if confidence < 0.45:
        return "weak"
    return "grounded"


def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    selected_ids = _unique_strings(raw.get("selected_ids", []))
    source_family = str(raw.get("source_family", "") or _dominant_family(selected_ids)).strip()
    if source_family not in SOURCE_FAMILIES:
        source_family = "none"
    confidence = _clamp_float(raw.get("confidence", 0.0))
    contradiction_flags = _unique_strings(raw.get("contradiction_flags", []))
    missing_source = bool(raw.get("missing_source", False))
    status = str(raw.get("status", "") or "").strip()
    if status not in MEMORY_STATUSES:
        status = _status_for(
            source_family=source_family,
            selected_ids=selected_ids,
            confidence=confidence,
            missing_source=missing_source,
            contradicted=bool(contradiction_flags),
        )
    if status == "missing":
        missing_source = True
    tags = _unique_strings(raw.get("grounding_tags", []))
    if source_family != "none" and status not in {"missing", "contradicted"}:
        tags = _unique_strings([*tags, "memory", source_family])
    call_id = str(raw.get("memory_call_id", "") or "").strip()
    if not call_id:
        call_id = "memory:" + _digest(source_family, selected_ids, raw.get("summary", ""), limit=10)
    return {
        "schema": MEMORY_GROUNDING_SCHEMA,
        "memory_call_id": call_id,
        "source_family": source_family,
        "selected_ids": selected_ids,
        "status": status,
        "summary": _compact(raw.get("summary", "")),
        "confidence": round(confidence, 4),
        "freshness": str(raw.get("freshness", "") or "unknown"),
        "grounding_tags": tags,
        "contradiction_flags": contradiction_flags,
        "missing_source": bool(missing_source),
    }


def _contains_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def is_memory_request(text: Any) -> bool:
    return _contains_any_pattern(str(text or ""), MEMORY_REQUEST_PATTERNS)


def _explicit_rows(memory_report: Any, reply_debug: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(memory_report, list):
        rows.extend(_list_dicts(memory_report))
    elif isinstance(memory_report, dict):
        if isinstance(memory_report.get("memory_observation_ledger"), list):
            rows.extend(_list_dicts(memory_report.get("memory_observation_ledger")))
        elif "source_family" in memory_report or "memory_call_id" in memory_report:
            rows.append(dict(memory_report))
    if isinstance(reply_debug.get("memory_observation_ledger"), list):
        rows.extend(_list_dicts(reply_debug.get("memory_observation_ledger")))
    return rows


def normalize_memory_observation_ledger(
    memory_report: Any = None,
    *,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    tool_observation_ledger: Any = None,
    active_memory_refresh: dict[str, Any] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Build a normalized memory evidence ledger without writing memory."""

    debug = _dict(reply_debug)
    explicit = _explicit_rows(memory_report, debug)
    if explicit:
        return _dedupe_rows([_normalize_row(item) for item in explicit])

    packet = _dict(sidecar)
    rows: list[dict[str, Any]] = []

    for item in _list_dicts(tool_observation_ledger):
        tool_name = str(item.get("tool", "") or "")
        if tool_name not in MEMORY_TOOL_NAMES:
            continue
        status = str(item.get("status", "") or "")
        failed = status.lower() in {"rejected", "skipped", "denied", "error", "failed"}
        source_family = "archive" if tool_name in {"memory_warehouse_search", "doc_lookup"} else "durable"
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": str(item.get("provider_call_id", "") or tool_name),
                    "source_family": source_family,
                    "selected_ids": _unique_strings(item.get("selected_ids", [])),
                    "status": "missing" if failed else "grounded",
                    "summary": item.get("summary", ""),
                    "confidence": 0.0 if failed else 0.72,
                    "freshness": "tool_observed",
                    "grounding_tags": ["memory", source_family, "tool_memory"],
                    "missing_source": failed,
                }
            )
        )

    selected_memory_ids = _unique_strings(packet.get("selected_memory_ids", []) or [])
    selected_ids = _unique_strings(selected_memory_ids + list(packet.get("activation_trace_ids", []) or []))
    recall_confidence = max(
        _clamp_float(packet.get("recall_confidence", 0.0)),
        _clamp_float(packet.get("graph_confidence", 0.0)),
    )
    if selected_ids:
        family = _dominant_family(
            selected_memory_ids or selected_ids,
            fallback=str(packet.get("memory_route", "") or "mind_graph"),
        )
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "selected_memory:" + _digest(selected_ids, limit=10),
                    "source_family": family,
                    "selected_ids": selected_ids,
                    "summary": packet.get("graph_trace_summary", "") or f"selected memory ids: {len(selected_ids)}",
                    "confidence": recall_confidence or 0.72,
                    "freshness": str(packet.get("retrieval_mode", "") or "retrieved"),
                    "grounding_tags": ["memory", family],
                }
            )
        )

    vector_hits = _list_dicts(packet.get("vector_hits", []))
    if vector_hits:
        vector_ids = _unique_strings(
            item.get("node_id", "") or item.get("id", "") or item.get("source", "") for item in vector_hits
        )
        vector_confidence = max((_clamp_float(item.get("score", 0.0)) for item in vector_hits), default=0.0)
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "vector:" + _digest(vector_ids, limit=10),
                    "source_family": "vector",
                    "selected_ids": vector_ids,
                    "summary": f"vector hits: {len(vector_hits)}",
                    "confidence": vector_confidence or recall_confidence or 0.5,
                    "freshness": "retrieved",
                    "grounding_tags": ["memory", "vector"],
                }
            )
        )

    reconstruction = _dict(packet.get("recall_reconstruction", {})) or _dict(debug.get("recall_reconstruction", {}))
    reconstruction_summary = str(reconstruction.get("summary", "") or "").strip()
    reconstruction_anchors = _unique_strings(reconstruction.get("anchors", []))
    if reconstruction_summary or reconstruction_anchors:
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "recall_reconstruction:" + _digest(reconstruction_summary, reconstruction_anchors, limit=10),
                    "source_family": _dominant_family(
                        selected_ids,
                        fallback="mind_graph" if selected_ids else "current_context",
                    ),
                    "selected_ids": selected_ids,
                    "summary": reconstruction_summary or f"reconstructed anchors: {len(reconstruction_anchors)}",
                    "confidence": recall_confidence or (0.52 if selected_ids else 0.38),
                    "freshness": "reconstructed",
                    "grounding_tags": ["memory", "reconstructed"],
                }
            )
        )

    recent_lines = list(_dict(packet.get("recent_dialogue_window", {})).get("lines", []) or []) + list(
        packet.get("thread_recall_lines", []) or []
    )
    if not rows and recent_lines:
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "current_context:" + _digest(recent_lines[:3], limit=10),
                    "source_family": "current_context",
                    "selected_ids": [],
                    "status": "weak",
                    "summary": f"current context lines: {len(recent_lines)}",
                    "confidence": 0.38,
                    "freshness": "current_context",
                    "grounding_tags": ["memory", "current_context"],
                }
            )
        )

    refresh = _dict(active_memory_refresh)
    if not rows and str(refresh.get("status", "") or "") == "ingested":
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "active_history:" + _digest(refresh, limit=10),
                    "source_family": "archive",
                    "selected_ids": [],
                    "status": "weak",
                    "summary": f"active history refresh ingested {refresh.get('message_count', 0)} messages",
                    "confidence": 0.42,
                    "freshness": "fresh_history",
                    "grounding_tags": ["memory", "archive"],
                }
            )
        )

    if not rows and is_memory_request(query):
        rows.append(
            _normalize_row(
                {
                    "memory_call_id": "memory_missing:" + _digest(query, limit=10),
                    "source_family": "none",
                    "selected_ids": [],
                    "status": "missing",
                    "summary": "memory requested but no selected source was available",
                    "confidence": 0.0,
                    "freshness": "none",
                    "grounding_tags": [],
                    "missing_source": True,
                }
            )
        )

    return _dedupe_rows(rows)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        call_id = str(row.get("memory_call_id", "") or "")
        if call_id in seen:
            continue
        seen.add(call_id)
        result.append(row)
    return result


def claimed_memory_families(text: str) -> list[str]:
    families: list[str] = []
    current = str(text or "")
    for family, patterns in MEMORY_CLAIM_PATTERNS:
        if _contains_any_pattern(current, patterns):
            families.append(family)
    return sorted(set(families))


def evaluate_memory_grounding(text: str, ledger: Any) -> dict[str, Any]:
    normalized = normalize_memory_observation_ledger(ledger)
    claimed = claimed_memory_families(text)
    grounded_rows = [
        item
        for item in normalized
        if str(item.get("status", "") or "") == "grounded"
        and "memory" in {str(tag) for tag in list(item.get("grounding_tags", []) or [])}
    ]
    weak_rows = [item for item in normalized if str(item.get("status", "") or "") == "weak"]
    contradicted_rows = [item for item in normalized if str(item.get("status", "") or "") == "contradicted"]
    if not claimed:
        status = "grounded"
    elif contradicted_rows:
        status = "contradicted_memory_claim"
    elif grounded_rows:
        status = "grounded"
    elif weak_rows:
        status = "weak_memory_source"
    else:
        status = "ungrounded_memory_claim"
    observed_families = sorted(
        {
            str(item.get("source_family", "") or "")
            for item in normalized
            if str(item.get("source_family", "") or "") != "none"
        }
    )
    return {
        "schema": MEMORY_GROUNDING_SCHEMA,
        "status": status,
        "claimed_families": claimed,
        "observed_families": observed_families,
        "grounded_count": len(grounded_rows),
        "weak_count": len(weak_rows),
        "contradicted_count": len(contradicted_rows),
        "ledger_count": len(normalized),
        "missing_source": bool(claimed and not grounded_rows),
    }


def _soften_confident_memory_claims(text: str, *, weak: bool) -> str:
    replacements = [
        (r"\bI remember\b", "I may be recalling" if weak else "I cannot verify from memory that"),
        (r"\bI recall\b", "I may be recalling" if weak else "I cannot verify from memory that"),
        (r"\bfrom memory\b", "from a weak memory cue" if weak else "without a verified memory source"),
        (
            r"\byou told me before\b",
            "you may have told me before" if weak else "I cannot verify that you told me before",
        ),
        (
            r"\byou said before\b",
            "you may have said before" if weak else "I cannot verify that you said before",
        ),
        (r"\bwe discussed\b", "we may have discussed" if weak else "I cannot verify that we discussed"),
        (r"\bwe talked about\b", "we may have talked about" if weak else "I cannot verify that we talked about"),
        (
            r"\byour preference was\b",
            "your preference may have been" if weak else "I cannot verify that your preference was",
        ),
        (
            "\u6211\u8bb0\u5f97",
            "\u6211\u4e0d\u5b8c\u5168\u786e\u5b9a\uff0c\u53ea\u80fd\u8bf4\u8bb0\u5fc6\u7ebf\u7d22\u50cf\u662f"
            if weak
            else "\u6211\u6ca1\u6709\u8db3\u591f\u7684\u8bb0\u5fc6\u6765\u6e90\u53ef\u4ee5\u786e\u8ba4",
        ),
        (
            "\u4ece\u8bb0\u5fc6\u91cc",
            "\u4ece\u8f83\u5f31\u7684\u8bb0\u5fc6\u7ebf\u7d22\u770b" if weak else "\u5728\u7f3a\u5c11\u53ef\u6838\u9a8c\u8bb0\u5fc6\u6765\u6e90\u65f6",
        ),
        (
            "\u4f60\u4e4b\u524d\u8bf4\u8fc7",
            "\u4f60\u53ef\u80fd\u4e4b\u524d\u8bf4\u8fc7"
            if weak
            else "\u6211\u65e0\u6cd5\u786e\u8ba4\u4f60\u4e4b\u524d\u8bf4\u8fc7",
        ),
        (
            "\u4f60\u4ee5\u524d\u8bf4\u8fc7",
            "\u4f60\u53ef\u80fd\u4ee5\u524d\u8bf4\u8fc7" if weak else "\u6211\u65e0\u6cd5\u786e\u8ba4\u4f60\u4ee5\u524d\u8bf4\u8fc7",
        ),
        (
            "\u6211\u4eec\u804a\u8fc7",
            "\u6211\u4eec\u53ef\u80fd\u804a\u8fc7" if weak else "\u6211\u65e0\u6cd5\u786e\u8ba4\u6211\u4eec\u804a\u8fc7",
        ),
        (
            "\u4f60\u4ee5\u524d\u7684\u504f\u597d",
            "\u4f60\u4ee5\u524d\u7684\u504f\u597d\u53ef\u80fd"
            if weak
            else "\u4f60\u4ee5\u524d\u504f\u597d\u7684\u8bb0\u5fc6\u6765\u6e90\u4e0d\u8db3",
        ),
    ]
    repaired = str(text or "")
    for pattern, replacement in replacements:
        repaired = re.sub(pattern, replacement, repaired, flags=re.IGNORECASE)
    return repaired


def repair_memory_claims(text: str, grounding_report: dict[str, Any], *, channel: str = "") -> str:
    status = str(grounding_report.get("status", "") or "")
    if status == "grounded":
        return str(text or "")
    if status == "weak_memory_source":
        prefix = "Memory source weak; treating this as tentative, not confirmed."
        return f"{prefix} {_soften_confident_memory_claims(text, weak=True)}".strip()
    if status == "contradicted_memory_claim":
        prefix = "Memory source conflicts; I should not state this as settled memory."
        return f"{prefix} {_soften_confident_memory_claims(text, weak=False)}".strip()
    if status == "ungrounded_memory_claim":
        prefix = "Memory source unavailable; I should not claim this from memory."
        if str(channel or "").startswith("wechat"):
            prefix = "Memory source unavailable; I should not claim this from memory."
        return f"{prefix} {_soften_confident_memory_claims(text, weak=False)}".strip()
    return str(text or "")
