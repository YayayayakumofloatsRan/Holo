from __future__ import annotations

from typing import Any

from .bounded_payload import clip_list, safe_float
from .turing_eval import score_bionic_turing_probe_set


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
    formatting_markers = (
        "next:",
        "basis:",
        "open:",
        "context:",
    )
    marker_hits = sum(1 for marker in template_markers if marker in generation_text.lower())
    template_pressure = min(1.0, marker_hits / max(1, len(template_markers)))
    formatting_hits = sum(1 for marker in formatting_markers if marker in generation_text.lower())
    formatting_pressure = min(1.0, formatting_hits / max(1, len(formatting_markers)))
    context_refs = clip_list(generation.get("context_refs", []), limit=8)
    context_shaping_units = len([item for item in context_refs if str(item or "").strip()])
    if str(generation.get("shape", "") or "").strip():
        context_shaping_units += 1
    context_shaping = min(1.0, context_shaping_units / 6.0)
    inquiry_quality = generation.get("inquiry_quality", {})
    inquiry_quality_score = 0.0
    question_count = generation_text.count("?") + generation_text.count("？")
    if isinstance(inquiry_quality, dict):
        inquiry_quality_score = safe_float(inquiry_quality.get("score", 0.0))
        question_count = int(safe_float(inquiry_quality.get("question_count", question_count)))
    turing_score = score_bionic_turing_probe_set(
        [
            {
                "probe_id": "current_turn",
                "text": generation_text,
                "capsule": {
                    "generation": {"context_refs": context_refs},
                    "metrics": {
                        "template_pressure_score": template_pressure,
                    },
                },
                "expected_anchor": str(packet.get("continuity_summary", "") or ""),
            }
        ]
    )
    return {
        "working_field_density": round(min(1.0, sum(1 for item in field_units if str(item or "").strip()) / 8.0), 4),
        "inhibition_count": len(list(inhibition.get("reasons", []))),
        "grounding_modalities": len(clip_list(situational_field.get("modalities", []), limit=16)),
        "history_reread_avoided": bool(inhibition.get("history_reread_inhibited", False)),
        "action_market_top_margin": round(top_margin, 4),
        "template_pressure_score": round(template_pressure, 4),
        "formatting_pressure_score": round(formatting_pressure, 4),
        "context_shaping_score": round(context_shaping, 4),
        "inquiry_quality_score": round(inquiry_quality_score, 4),
        "bionic_turing_score": round(safe_float(turing_score.get("overall_score", 0.0)), 4),
        "bionic_turing_pass_threshold": round(safe_float(turing_score.get("pass_threshold", 0.82)), 4),
        "question_count": question_count,
        "query_chars": len(str(query or "")),
    }
