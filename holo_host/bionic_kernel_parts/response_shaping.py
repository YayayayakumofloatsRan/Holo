from __future__ import annotations

from typing import Any

from .bounded_payload import as_dict, clip_list, compact

LABEL_TEMPLATE_MARKERS = ("Next:", "Basis:", "Open:", "Context:")


def _compact_list(values: Any, *, limit: int, item_limit: int = 160) -> list[str]:
    items: list[str] = []
    for item in clip_list(values, limit=limit):
        text = compact(item, limit=item_limit)
        if text and text not in items:
            items.append(text)
    return items


def _question_count(text: str) -> int:
    return text.count("?") + text.count("？")


def _label_marker_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for marker in LABEL_TEMPLATE_MARKERS if marker.lower() in lowered)


def _finish_sentence(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value if value.endswith((".", "?", "!", "。", "？", "！")) else f"{value}."


def _finish_question(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value if value.endswith(("?", "？")) else f"{value}?"


def _quality_payload(*, text: str, context_refs: list[str], grounded_question: str) -> dict[str, Any]:
    question_count = _question_count(text)
    label_marker_count = _label_marker_count(text)
    score = 1.0
    if question_count > 1:
        score -= min(0.45, 0.2 * (question_count - 1))
    if label_marker_count:
        score -= min(0.6, 0.2 * label_marker_count)
    if grounded_question and grounded_question not in text:
        score -= 0.2
    if len([item for item in context_refs if str(item or "").strip()]) < 2:
        score -= 0.15
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "question_count": question_count,
        "label_marker_count": label_marker_count,
        "grounded_question": grounded_question,
    }


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

    grounded_question = open_questions[0] if open_questions else ""
    if open_questions:
        shape = "open_question"
        parts = [
            _finish_sentence(f"I would keep {query_text} on the current verified cut"),
            _finish_sentence(f"Because {reason}"),
            _finish_question(grounded_question),
        ]
        if continuity:
            parts.append(_finish_sentence(f"This follows {continuity}"))
    else:
        shape = "next_step"
        parts = [
            _finish_sentence(f"I would continue with {query_text}"),
            _finish_sentence(f"The action-market basis is {reason}"),
        ]
    if continuity and not open_questions:
        parts.append(_finish_sentence(f"This follows {continuity}"))
    text = compact(" ".join(part for part in parts if part), limit=360)

    return {
        "text": text,
        "shape": shape,
        "context_refs": context_refs[:4],
        "inquiry_quality": _quality_payload(
            text=text,
            context_refs=context_refs[:4],
            grounded_question=grounded_question,
        ),
    }
