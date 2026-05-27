from __future__ import annotations

from typing import Any

from .agent_event_stream import build_agent_event_stream, sanitize_event_payload
from .common import compact_text, stable_digest, utc_now

PUBLIC_THOUGHT_STREAM_SCHEMA = "holo.stage191.public_thought_stream.v1"
PUBLIC_THOUGHT_CARD_SCHEMA = "holo.stage191.public_thought_card.v1"


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _card(phase: str, summary: str, *, source_event: str = "", confidence: float = 0.0) -> dict[str, Any]:
    return {
        "schema": PUBLIC_THOUGHT_CARD_SCHEMA,
        "card_id": "stage191_card:" + stable_digest(phase, summary, source_event, limit=12),
        "phase": phase,
        "summary": _compact(summary, 260),
        "source_event": source_event,
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 4),
    }


def _card_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(event.get("event", "") or "")
    if kind == "goal":
        return _card("goal", str(event.get("summary", "") or ""), source_event=kind, confidence=0.9)
    if kind in {"think", "model_decide", "decide"}:
        if kind == "think":
            phase = str(event.get("phase", "") or "deliberation")
            summary = str(event.get("summary", "") or "")
        elif kind == "model_decide":
            phase = "model_decision"
            need = ",".join(str(x) for x in list(event.get("required_observations", []) or [])) or "none"
            summary = f"selected={event.get('selected_action', '')}; required={need}"
        else:
            phase = "host_decision"
            need = ",".join(str(x) for x in list(event.get("required_observations", []) or [])) or "none"
            summary = f"selected={event.get('action_type', '')}; required={need}"
        return _card(phase, summary, source_event=kind, confidence=0.74)
    if kind in {"act", "tool_call", "crawl:query", "crawl:search", "crawl:open"}:
        if kind == "act":
            summary = f"{event.get('action_type', '')} status={event.get('status', '')}"
        elif kind == "tool_call":
            summary = f"{event.get('action_type', '')} status={event.get('status', '')} query={event.get('query', '')}"
        elif kind == "crawl:query":
            summary = f"query={event.get('query', '')}"
        elif kind == "crawl:search":
            summary = f"search status={event.get('status', '')}; results={event.get('result_count', 0)}; sources={event.get('source_count', 0)}"
        else:
            summary = f"open status={event.get('status', '')}; url={event.get('url', '')}"
        return _card("action", summary, source_event=kind, confidence=0.76)
    if kind in {"observe", "observation", "crawl:evaluate"}:
        if kind == "observe":
            unresolved = ",".join(str(x) for x in list(event.get("unresolved_items", []) or [])) or "none"
            summary = f"{event.get('action_type', '')} status={event.get('status', '')}; unresolved={unresolved}"
        elif kind == "crawl:evaluate":
            summary = f"status={event.get('status', '')}; score={event.get('score', 0)}; authority={event.get('authority_status', '')}; stop={event.get('stop_reason', '')}"
        else:
            summary = f"{event.get('action_type', '')} status={event.get('status', '')}; sources={event.get('source_count', 0)}; results={event.get('result_count', 0)}"
        return _card("observation", summary, source_event=kind, confidence=0.78)
    if kind == "feedback":
        summary = (
            f"{event.get('action', '')} score={event.get('evidence_score', 0)}; "
            f"delta={event.get('marginal_utility', 0)}; next={event.get('next_action', '')}; stop={event.get('stop_reason', '')}"
        )
        return _card("self_feedback", summary, source_event=kind, confidence=0.82)
    if kind == "market_plan":
        summary = (
            f"status={event.get('status', '')}; next={event.get('next_action', '')}; "
            f"first={event.get('first_action', '')}; candidates={event.get('candidate_count', 0)}; stop={event.get('stop_reason', '')}"
        )
        return _card("action_plan", summary, source_event=kind, confidence=0.82)
    if kind == "market_exec":
        summary = (
            f"status={event.get('status', '')}; action={event.get('executed_action', '')}; "
            f"executed={event.get('executed_count', 0)}; rejected={event.get('rejected_count', 0)}; "
            f"failed={event.get('failed_count', 0)}; stop={event.get('stop_reason', '')}"
        )
        return _card("action", summary, source_event=kind, confidence=0.82)
    if kind == "evaluate":
        unresolved = ",".join(str(x) for x in list(event.get("unresolved_items", []) or [])) or "none"
        return _card("stop_evaluation", f"status={event.get('status', '')}; unresolved={unresolved}", source_event=kind, confidence=0.78)
    if kind == "grounding":
        missing = ",".join(str(x) for x in list(event.get("missing", []) or [])) or "none"
        return _card("grounding", f"status={event.get('status', '')}; missing={missing}", source_event=kind, confidence=0.8)
    if kind == "stop":
        return _card("stop", f"reason={event.get('reason', '')}; source={event.get('source', '')}", source_event=kind, confidence=0.86)
    if kind == "final":
        return _card("final", str(event.get("summary", "") or ""), source_event=kind, confidence=0.72)
    return None


def build_public_thought_stream(
    payload: dict[str, Any] | None,
    *,
    user_text: str = "",
    event_stream: dict[str, Any] | None = None,
    thread_key: str = "",
    chat_name: str = "",
    channel: str = "",
    transport: str = "",
) -> dict[str, Any]:
    """Build a public, auditable thought stream without raw hidden reasoning."""

    source = sanitize_event_payload(dict(payload or {}))
    stream = sanitize_event_payload(dict(event_stream or {}))
    if not stream.get("events"):
        stream = build_agent_event_stream(
            source,
            user_text=user_text,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            transport=transport,
        )
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in _list_dicts(stream.get("events", [])):
        card = _card_from_event(event)
        if not card:
            continue
        key = f"{card['phase']}:{card['summary']}"
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)
    phase_counts: dict[str, int] = {}
    for card in cards:
        phase = str(card.get("phase", "") or "unknown")
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    return sanitize_event_payload(
        {
            "schema": PUBLIC_THOUGHT_STREAM_SCHEMA,
            "status": "recorded",
            "card_count": len(cards),
            "phase_counts": phase_counts,
            "cards": cards[:32],
            "source_event_stream_schema": str(stream.get("schema", "") or ""),
            "hidden_reasoning_exposed": False,
            "raw_chain_of_thought_available": False,
            "created_at": utc_now(),
        }
    )


def render_public_thought_stream(report: dict[str, Any] | None) -> str:
    thought = dict(report or {})
    cards = _list_dicts(thought.get("cards", []))
    if not cards:
        return "[thought] no public thought stream recorded"
    lines = ["[thought] public auditable loop; raw hidden reasoning is not exposed"]
    for card in cards:
        phase = str(card.get("phase", "unknown") or "unknown")
        summary = str(card.get("summary", "") or "")
        if summary:
            lines.append(f"[thought:{phase}] {summary}")
    return "\n".join(lines)
