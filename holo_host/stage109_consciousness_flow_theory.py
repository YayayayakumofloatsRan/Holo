from __future__ import annotations

import hashlib
from typing import Any

STAGE109_SCHEMA = "holo.stage109.consciousness_flow_theory.v1"


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _segments(stream: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(stream.get("segments", []) or []) if isinstance(item, dict)]


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        current = str(value or "").strip()
        if current and current not in seen:
            seen.append(current)
    return seen


def _source_event_coverage(stream: dict[str, Any]) -> dict[str, Any]:
    segments = _segments(stream)
    source_events = _unique(
        [
            str(event_id)
            for segment in segments
            for event_id in list(segment.get("source_events", []) or [])
        ]
    )
    return {
        "segment_count": len(segments),
        "linked_source_event_count": len(source_events),
        "all_segments_linked": bool(segments) and all(bool(segment.get("source_events")) for segment in segments),
        "status": "covered" if segments and all(bool(segment.get("source_events")) for segment in segments) else "pending",
    }


def _surface_forms(stream: dict[str, Any]) -> list[str]:
    return _unique([str(segment.get("surface_form", "") or "") for segment in _segments(stream)])


def build_stage109_theory_frame(stage108_stream: dict[str, Any] | None = None, *, query: str = "") -> dict[str, Any]:
    stream = dict(stage108_stream or {})
    theory_id = f"stage109:{_stable_digest(query, stream.get('expression_id', ''), stream.get('status', ''))}"
    coverage = _source_event_coverage(stream)
    surface_forms = _surface_forms(stream)
    return {
        "schema": STAGE109_SCHEMA,
        "stage": 109,
        "theory_id": theory_id,
        "query": str(query or stream.get("query", "") or ""),
        "title": "Finite-Context Consciousness Flow over Provider APIs",
        "core_thesis": (
            "For provider-above agents, consciousness-like flow is simulated by controlling finite context packets, "
            "local compression, grounded tool observations, and external expression granularity."
        ),
        "claim_boundary": {
            "claims_real_subjective_consciousness": False,
            "base_model_training_required": False,
            "provider_above_adaptation": True,
            "focus": "mechanistic interaction and observability, not metaphysical consciousness claims",
        },
        "axioms": [
            {
                "id": "A1_finite_context",
                "statement": "Every provider call receives a bounded packet; there is no infinite context.",
                "engineering_surface": "packet_budget_tokens and packet roles",
            },
            {
                "id": "A2_local_continuity",
                "statement": "Continuity is carried locally by memory selection, semantic attractors, and compressed deltas.",
                "engineering_surface": "Stage104 attractors plus Stage107 delta summaries",
            },
            {
                "id": "A3_compressive_recurrence",
                "statement": "A thought stream is packet, return, compression, and next packet, not one static prompt.",
                "engineering_surface": "Stage107 provider interaction loop",
            },
            {
                "id": "A4_grounded_perturbation",
                "statement": "Tools perturb the loop with observations before the next provider packet.",
                "engineering_surface": "Stage106 tool affordance and Stage107 tool observation",
            },
            {
                "id": "A5_expression_decoupling",
                "statement": "Visible speech is a separate realization layer and need not match internal packets one-to-one.",
                "engineering_surface": "Stage108 expression stream",
            },
        ],
        "stage_mechanism_map": [
            {
                "stage": 104,
                "mechanism": "semantic_attractors",
                "role": "long-term local compression into reusable meaning basins",
                "observable": "semantic_attractor_lines",
            },
            {
                "stage": 105,
                "mechanism": "finite_provider_packet_stream",
                "role": "decide whether to send, how many packets to send, and when to stop",
                "observable": "packet_count, packet_role, send_decision",
            },
            {
                "stage": 106,
                "mechanism": "provider_tool_affordance_adapter",
                "role": "let provider propose tools while Holo retains execution authority",
                "observable": "tools, tool_choice, accepted or rejected tool_calls",
            },
            {
                "stage": 107,
                "mechanism": "packet_return_delta_loop",
                "role": "advance packet, return, distill, observation, and stop phases",
                "observable": "provider_packet, provider_return, distill_delta, tool_observation",
            },
            {
                "stage": 108,
                "mechanism": "expression_stream_realization",
                "role": "map internal events to bubbles, paragraphs, delayed segments, or no output",
                "observable": "segment_role, surface_form, source_events",
            },
        ],
        "internal_external_bridge": {
            "external_reply_is_not_equal_to_provider_packet": True,
            "one_internal_event_can_drive_multiple_surface_forms": True,
            "multiple_internal_events_can_merge_into_one_surface_form": True,
            "surface_forms_observed": surface_forms,
            "source_event_coverage": coverage,
        },
        "research_hypotheses": [
            {
                "id": "H1_attractor_stability",
                "hypothesis": "Stable semantic attractors improve continuity under finite context budgets.",
                "falsifiable": True,
                "metric_ids": ["attractor_reuse_rate", "source_event_coverage"],
            },
            {
                "id": "H2_compression_continuity",
                "hypothesis": "Provider-return delta compression preserves enough semantic movement for the next packet.",
                "falsifiable": True,
                "metric_ids": ["delta_retention", "reply_commit_consistency"],
            },
            {
                "id": "H3_grounded_tool_perturbation",
                "hypothesis": "Tool observations reduce hallucination pressure when inserted before reply commitment.",
                "falsifiable": True,
                "metric_ids": ["grounding_ratio", "unobserved_claim_rate"],
            },
            {
                "id": "H4_expression_granularity",
                "hypothesis": "External granularity should follow internal event topology and social pressure.",
                "falsifiable": True,
                "metric_ids": ["expression_granularity_fit", "segment_source_alignment"],
            },
            {
                "id": "H5_stop_control",
                "hypothesis": "Explicit no-send and wait states prevent compulsive provider calls and premature speech.",
                "falsifiable": True,
                "metric_ids": ["unnecessary_provider_call_rate", "premature_expression_rate"],
            },
        ],
        "measurement_plan": {
            "unit_of_analysis": "one Stage105-108 interaction trace",
            "metrics": [
                {
                    "id": "source_event_coverage",
                    "definition": "fraction of external segments with at least one Stage107 source event",
                    "current_value": coverage,
                },
                {
                    "id": "delta_retention",
                    "definition": "overlap between provider return semantic claims and next packet previous_delta summary",
                    "requires": ["provider_return", "distill_delta", "next provider_packet"],
                },
                {
                    "id": "grounding_ratio",
                    "definition": "share of factual claims supported by tool_observation or selected memory evidence",
                    "requires": ["tool_observation", "reply_commit"],
                },
                {
                    "id": "expression_granularity_fit",
                    "definition": "agreement between internal event topology and chosen surface_form/segment_count",
                    "current_surface_forms": surface_forms,
                },
                {
                    "id": "premature_expression_rate",
                    "definition": "rate of external segments emitted before provider_return or tool_observation is available",
                    "expected": 0,
                },
            ],
        },
        "literature_bridge": [
            {
                "id": "chain_of_thought",
                "connection": "intermediate reasoning improves task performance; Holo externalizes only selected downstream segments",
            },
            {
                "id": "react",
                "connection": "reasoning and acting alternate; Holo represents alternation as provider packets and local tool observations",
            },
            {
                "id": "toolformer",
                "connection": "model can learn when tools help; Holo exposes allowlisted tool affordances above the provider",
            },
            {
                "id": "reflexion",
                "connection": "verbal feedback can improve later behavior; Holo stores compressed deltas and attractors locally",
            },
            {
                "id": "generative_agents",
                "connection": "memory, reflection, and planning generate believable continuity; Holo makes the trace inspectable",
            },
            {
                "id": "self_refine",
                "connection": "iterative feedback-refinement maps to packet return and delta compression loops",
            },
        ],
        "publishable_contribution": {
            "proposed_title": "Finite-Context Consciousness Flow for Provider-Based Biomimetic Agents",
            "novelty_claim": (
                "A provider-above architecture that unifies memory attractors, finite packet control, tool observations, "
                "delta compression, and expression segmentation into one inspectable loop."
            ),
            "artifact_requirements": [
                "trace logs for Stage105-108",
                "topic-categorized simulation batches",
                "human-rated expression granularity labels",
                "ablation of attractor, tool, and expression-stream layers",
            ],
        },
    }
