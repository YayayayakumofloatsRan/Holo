from __future__ import annotations

from typing import Any

from .bounded_payload import clip_list, safe_float


def compute_bionic_metrics(
    *,
    query: str,
    packet: dict[str, Any],
    action_market: list[dict[str, Any]],
    situational_field: dict[str, Any],
    inhibition: dict[str, Any],
    generation: dict[str, Any],
) -> dict[str, Any]:
    field_units = [
        packet.get("continuity_summary", ""),
        *list(situational_field.get("modalities", []) if isinstance(situational_field.get("modalities", []), list) else []),
        *list(situational_field.get("open_questions", []) if isinstance(situational_field.get("open_questions", []), list) else []),
    ]
    scores = [safe_float(item.get("score", 0.0)) for item in action_market[:2]]
    top_margin = scores[0] - scores[1] if len(scores) >= 2 else (scores[0] if scores else 0.0)
    generation_text = str(generation.get("text", "") or "")
    template_markers = (
        "stage29 bionic capsule reply:",
        "i read this as a bounded holo turn:",
        "answer as a bounded holo bionic kernel turn",
    )
    marker_hits = sum(1 for marker in template_markers if marker in generation_text.lower())
    template_pressure = min(1.0, marker_hits / max(1, len(template_markers)))
    context_refs = clip_list(generation.get("context_refs", []), limit=8)
    context_shaping_units = len([item for item in context_refs if str(item or "").strip()])
    if str(generation.get("shape", "") or "").strip():
        context_shaping_units += 1
    context_shaping = min(1.0, context_shaping_units / 6.0)
    return {
        "working_field_density": round(min(1.0, sum(1 for item in field_units if str(item or "").strip()) / 8.0), 4),
        "inhibition_count": len(list(inhibition.get("reasons", []))),
        "grounding_modalities": len(clip_list(situational_field.get("modalities", []), limit=16)),
        "history_reread_avoided": bool(inhibition.get("history_reread_inhibited", False)),
        "action_market_top_margin": round(top_margin, 4),
        "template_pressure_score": round(template_pressure, 4),
        "context_shaping_score": round(context_shaping, 4),
        "query_chars": len(str(query or "")),
    }
