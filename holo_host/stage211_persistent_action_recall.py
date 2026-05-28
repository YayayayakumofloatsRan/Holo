from __future__ import annotations

import json
from typing import Any

from .common import stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .stage210_last_action_recall import (
    build_last_action_recall_report,
    is_last_action_recall_query,
)

STAGE211_PERSISTENT_ACTION_RECALL_SCHEMA = "holo.stage211.persistent_action_recall.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _payload_from_message(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json", {})
    if isinstance(raw, dict):
        return dict(raw)
    try:
        decoded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _has_action_evidence(metadata: dict[str, Any]) -> bool:
    crawler = _dict(metadata.get("stage186_live_crawler_search", {}))
    if crawler.get("schema") == "holo.stage186.live_crawler_search.v1":
        return True
    if isinstance(metadata.get("web_observation_ledger"), list) and metadata.get("web_observation_ledger"):
        return True
    if isinstance(metadata.get("tool_observation_ledger"), list) and metadata.get("tool_observation_ledger"):
        return True
    return False


def extract_previous_action_payload(recent_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Find the newest outbound action ledger in persisted thread history."""

    for row in reversed([dict(item) for item in list(recent_messages or []) if isinstance(item, dict)]):
        if str(row.get("direction", "") or "") != "outbound":
            continue
        payload = _payload_from_message(row)
        metadata = _dict(payload.get("metadata", {}))
        if not _has_action_evidence(metadata):
            continue
        previous_payload = {
            "text": str(row.get("body_text", "") or ""),
            "metadata": metadata,
            "stage211_source_message_id": row.get("id"),
            "stage211_source_created_at": str(row.get("created_at", "") or ""),
        }
        for key in (
            "stage186_live_crawler_search",
            "web_observation_ledger",
            "tool_observation_ledger",
            "stage153_agent_event_stream",
        ):
            if key in metadata:
                previous_payload[key] = metadata[key]
        return sanitize_public_metadata(previous_payload)
    return {}


def build_persistent_action_recall_report(
    text: str,
    *,
    recent_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    if not is_last_action_recall_query(text):
        return {}
    previous_payload = extract_previous_action_payload(recent_messages)
    stage210_report = build_last_action_recall_report(text, previous_payload=previous_payload)
    status = "answered" if stage210_report.get("status") == "answered" else "missing"
    report = {
        "schema": STAGE211_PERSISTENT_ACTION_RECALL_SCHEMA,
        "status": status,
        "recall_id": "stage211:" + stable_digest(text, str(previous_payload.get("stage211_source_message_id", "")), limit=12),
        "source": "persisted_outbound_metadata",
        "source_message_id": previous_payload.get("stage211_source_message_id"),
        "stage210_status": str(stage210_report.get("status", "") or ""),
        "action_type": str(stage210_report.get("action_type", "") or "unknown"),
        "query_count": int(stage210_report.get("query_count", 0) or 0),
        "promoted_source_count": len(list(stage210_report.get("promoted_source_urls", []) or [])),
        "weak_source_count": len(list(stage210_report.get("observed_weak_source_urls", []) or [])),
        "canonical_stop_reason": "final_answer_ready" if status == "answered" else "evidence_exhausted",
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
    if status == "missing":
        report["missing_reason"] = "no_previous_persisted_action_ledger"
    return sanitize_public_metadata({"stage211": report, "stage210": stage210_report})


def build_persistent_action_recall_reply(
    text: str,
    *,
    recent_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    thread_key: str = "",
    chat_name: str = "",
    channel: str = "holo_cli",
) -> dict[str, Any]:
    reports = build_persistent_action_recall_report(text, recent_messages=recent_messages)
    if not reports:
        return {}
    stage211 = _dict(reports.get("stage211", {}))
    stage210 = _dict(reports.get("stage210", {}))
    if stage211.get("status") != "answered" or stage210.get("status") != "answered":
        return {}
    answer_text = str(stage210.get("answer_text", "") or "").strip()
    if not answer_text:
        return {}
    return sanitize_public_metadata(
        {
            "action": "reply",
            "text": answer_text,
            "bubbles": [answer_text],
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "canonical_stop_reason": "final_answer_ready",
            "canonical_stop_source": "stage211_persistent_action_recall",
            "stage210_last_action_recall": stage210,
            "stage211_persistent_action_recall": stage211,
        }
    )
