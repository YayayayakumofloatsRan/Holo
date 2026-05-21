from __future__ import annotations

import hashlib
from typing import Any

STAGE108_SCHEMA = "holo.stage108.expression_stream.v1"


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _events(loop: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(loop.get("events", []) or []) if isinstance(item, dict)]


def _event_ids(rows: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for row in rows:
        event_id = str(row.get("event_id", "") or "").strip()
        if event_id and event_id not in ids:
            ids.append(event_id)
    return ids


def _event_phases(rows: list[dict[str, Any]]) -> list[str]:
    phases: list[str] = []
    for row in rows:
        phase = str(row.get("phase", "") or "").strip()
        if phase and phase not in phases:
            phases.append(phase)
    return phases


def _segment(
    *,
    expression_id: str,
    index: int,
    role: str,
    source_events: list[dict[str, Any]],
    surface_form: str,
    text_budget: int,
    delay_ms: int = 0,
    trigger: str = "",
    content_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_ids = _event_ids(source_events)
    return {
        "segment_id": f"{expression_id}:segment:{index}:{role}",
        "index": index,
        "segment_role": role,
        "surface_form": surface_form,
        "text_budget": int(text_budget),
        "delay_ms": int(delay_ms),
        "trigger": trigger,
        "source_events": source_ids,
        "source_phases": _event_phases(source_events),
        "content_contract": dict(content_contract or {}),
    }


def _provider_return_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("phase", "") or "") == "provider_return"]


def _tool_observation_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("phase", "") or "") == "tool_observation"]


def _pending_provider_packet(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in reversed(rows):
        if str(row.get("phase", "") or "") == "provider_packet":
            return {
                "event_id": str(row.get("event_id", "") or ""),
                "packet_id": str(row.get("packet_id", "") or ""),
                "packet_role": str(row.get("packet_role", "") or ""),
            }
    return {}


def _paragraph_segment(expression_id: str, source_rows: list[dict[str, Any]], *, index: int = 1) -> dict[str, Any]:
    return _segment(
        expression_id=expression_id,
        index=index,
        role="reply_commit",
        source_events=source_rows,
        surface_form="paragraph",
        text_budget=max(360, 120 * max(1, len(source_rows))),
        trigger="merge_internal_events",
        content_contract={
            "mode": "single_paragraph",
            "must_preserve_sequence": True,
            "must_not_dump_internal_state": True,
        },
    )


def _auto_segments(expression_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    observations = _tool_observation_events(rows)
    if observations:
        segments.append(
            _segment(
                expression_id=expression_id,
                index=len(segments) + 1,
                role="evidence",
                source_events=observations,
                surface_form="bubble",
                text_budget=120,
                delay_ms=0,
                trigger="tool_observation",
                content_contract={
                    "mode": "evidence_before_reply",
                    "must_summarize_observation": True,
                    "must_not_claim_unobserved_facts": True,
                },
            )
        )

    provider_returns = _provider_return_events(rows)
    if not provider_returns:
        return segments

    role_sequence = ["acknowledge", "semantic_delta", "reply_commit"]
    for provider_event in provider_returns:
        role = role_sequence[min(len(segments) - len(observations), len(role_sequence) - 1)]
        packet_role = str(provider_event.get("packet_role", "") or "")
        if packet_role == "reply_commit":
            role = "reply_commit"
        elif packet_role == "deliberation_delta":
            role = "semantic_delta"
        elif packet_role == "context_seed":
            role = "acknowledge"
        segments.append(
            _segment(
                expression_id=expression_id,
                index=len(segments) + 1,
                role=role,
                source_events=[provider_event],
                surface_form="bubble",
                text_budget=100 if role == "acknowledge" else 160 if role == "semantic_delta" else 220,
                delay_ms=0 if role == "acknowledge" else 220 if role == "semantic_delta" else 360,
                trigger=packet_role or "provider_return",
                content_contract={
                    "mode": "externalize_internal_phase",
                    "packet_role": packet_role,
                    "must_remain_user_facing": True,
                },
            )
        )
    return segments


def _visualization(loop: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    source_nodes = [
        {
            "id": str(row.get("event_id", "") or ""),
            "label": str(row.get("phase", "") or ""),
            "kind": "stage107_event",
            "packet_role": str(row.get("packet_role", "") or ""),
        }
        for row in _events(loop)
        if str(row.get("event_id", "") or "").strip()
    ]
    segment_nodes = [
        {
            "id": segment["segment_id"],
            "label": segment["segment_role"],
            "kind": "expression_segment",
            "surface_form": segment["surface_form"],
        }
        for segment in segments
    ]
    edges: list[dict[str, Any]] = []
    for segment in segments:
        for source_event in segment.get("source_events", []):
            edges.append({"source": source_event, "target": segment["segment_id"], "label": "drives_expression"})
    return {"nodes": source_nodes + segment_nodes, "edges": edges}


def build_stage108_expression_stream(
    stage107_loop: dict[str, Any],
    *,
    granularity: str = "auto",
) -> dict[str, Any]:
    rows = _events(stage107_loop)
    query = str(stage107_loop.get("query", "") or "")
    expression_id = f"stage108:{_stable_digest(stage107_loop.get('loop_id', ''), query, granularity)}"
    normalized_granularity = str(granularity or "auto").strip().lower() or "auto"

    if any(str(row.get("phase", "") or "") == "stop" for row in rows):
        return {
            "schema": STAGE108_SCHEMA,
            "stage": 108,
            "expression_id": expression_id,
            "query": query,
            "status": "no_output",
            "next_action": "stop",
            "segment_count": 0,
            "segments": [],
            "policy": {
                "surface_granularity": "silence",
                "source_status": str(stage107_loop.get("status", "") or ""),
            },
            "stage107": {
                "stage": 107,
                "loop_id": str(stage107_loop.get("loop_id", "") or ""),
                "status": str(stage107_loop.get("status", "") or ""),
                "next_action": str(stage107_loop.get("next_action", "") or ""),
            },
            "visualization": _visualization(stage107_loop, []),
        }

    source_rows = _provider_return_events(rows) + _tool_observation_events(rows)
    if not source_rows:
        return {
            "schema": STAGE108_SCHEMA,
            "stage": 108,
            "expression_id": expression_id,
            "query": query,
            "status": "awaiting_internal_event",
            "next_action": str(stage107_loop.get("next_action", "") or "send_provider_packet"),
            "segment_count": 0,
            "segments": [],
            "internal_pending_packet": _pending_provider_packet(rows),
            "policy": {
                "surface_granularity": "none_until_internal_return",
                "source_status": str(stage107_loop.get("status", "") or ""),
            },
            "stage107": {
                "stage": 107,
                "loop_id": str(stage107_loop.get("loop_id", "") or ""),
                "status": str(stage107_loop.get("status", "") or ""),
                "next_action": str(stage107_loop.get("next_action", "") or ""),
            },
            "visualization": _visualization(stage107_loop, []),
        }

    if normalized_granularity == "paragraph":
        segments = [_paragraph_segment(expression_id, source_rows)]
        surface_granularity = "paragraph"
    elif normalized_granularity == "single":
        segments = [
            _segment(
                expression_id=expression_id,
                index=1,
                role="reply_commit",
                source_events=source_rows,
                surface_form="bubble",
                text_budget=240,
                trigger="single_surface_reply",
                content_contract={"mode": "single_bubble", "must_compress": True},
            )
        ]
        surface_granularity = "single"
    else:
        segments = _auto_segments(expression_id, rows)
        surface_granularity = "multi_bubble" if len(segments) > 1 else "single_bubble"

    return {
        "schema": STAGE108_SCHEMA,
        "stage": 108,
        "expression_id": expression_id,
        "query": query,
        "status": "ready_to_emit",
        "next_action": "emit_expression_segments",
        "segment_count": len(segments),
        "segments": segments,
        "policy": {
            "surface_granularity": surface_granularity,
            "requested_granularity": normalized_granularity,
            "source_status": str(stage107_loop.get("status", "") or ""),
            "one_internal_event_can_drive_multiple_surface_forms": True,
            "multiple_internal_events_can_merge_into_one_surface_form": True,
        },
        "stage107": {
            "stage": 107,
            "loop_id": str(stage107_loop.get("loop_id", "") or ""),
            "status": str(stage107_loop.get("status", "") or ""),
            "next_action": str(stage107_loop.get("next_action", "") or ""),
        },
        "visualization": _visualization(stage107_loop, segments),
    }
