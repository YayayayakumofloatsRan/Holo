from __future__ import annotations

from typing import Any

from .bounded_payload import as_dict, clip_list, compact


def _compact_list(values: Any, *, limit: int, item_limit: int = 160) -> list[str]:
    items: list[str] = []
    for item in clip_list(values, limit=limit):
        text = compact(item, limit=item_limit)
        if text and text not in items:
            items.append(text)
    return items


def shape_deterministic_reply(
    *,
    query: str,
    packet: dict[str, Any],
    selected_action: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded offline reply without falling back to a fixed persona template."""

    situational = as_dict(packet.get("situational_field", {}))
    query_text = compact(query, limit=120)
    continuity = compact(packet.get("continuity_summary", ""), limit=120)
    reason = compact(
        selected_action.get("reason") or selected_action.get("why_now") or "continue the bounded turn",
        limit=120,
    )
    open_questions = _compact_list(situational.get("open_questions", []), limit=1, item_limit=100)
    modalities = _compact_list(situational.get("modalities", []), limit=4, item_limit=80)

    context_refs: list[str] = ["query", "action"]
    if continuity:
        context_refs.append("continuity")
    if open_questions:
        context_refs.append("open_question")
    if modalities and len(context_refs) < 4:
        context_refs.append("modalities")

    if open_questions:
        shape = "open_question"
        parts = [
            f"Next: {query_text}.",
            f"Basis: {reason}.",
            f"Open: {open_questions[0]}.",
        ]
    else:
        shape = "next_step"
        parts = [
            f"Next: {query_text}.",
            f"Basis: {reason}.",
        ]
    if continuity:
        parts.append(f"Context: {continuity}.")

    return {
        "text": compact(" ".join(part for part in parts if part), limit=130),
        "shape": shape,
        "context_refs": context_refs[:4],
    }
