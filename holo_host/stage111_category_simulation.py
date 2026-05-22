from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .stage105_provider_packet_stream import stage105_packet_stream_plan
from .stage107_provider_interaction_loop import build_stage107_interaction_loop
from .stage108_expression_stream import build_stage108_expression_stream
from .stage109_consciousness_flow_theory import build_stage109_theory_frame
from .stage110_theory_guided_packets import build_stage110_packet_guidance

STAGE111_SCHEMA = "holo.stage111.category_simulation.v1"


BASE_CATEGORY_FIXTURES: list[dict[str, Any]] = [
    {
        "category_id": "autobiographical_recall",
        "label": "Autobiographical recall",
        "query": "recall what we have been building in Holo",
        "domain_tags": ["memory", "continuity", "identity"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: continuity depends on compact recall.",
                "Stage104 attractor: identity is expressed through stable memory selection.",
                "Stage104 attractor: expression waits for internal packet return.",
            ],
            "uncertainty_level": 0.72,
            "selected_action": {"action_type": "reply_once", "why_now": "broad recall needs continuity"},
        },
    },
    {
        "category_id": "semantic_memory_linking",
        "label": "Semantic memory linking",
        "query": "connect the earlier memory system idea with provider packets",
        "domain_tags": ["memory", "semantic_topology", "reasoning"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: memory compression controls what enters packets.",
                "Stage104 attractor: semantic attractors shape routing.",
            ],
            "uncertainty_level": 0.61,
            "selected_action": {"action_type": "reply_once", "why_now": "semantic bridge needs continuity"},
        },
    },
    {
        "category_id": "affective_support",
        "label": "Affective support",
        "query": "I feel frustrated that Holo still feels discontinuous",
        "domain_tags": ["affect", "social", "continuity"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: affect changes response granularity.",
                "Stage104 attractor: continuity repair needs memory and current emotion.",
            ],
            "uncertainty_level": 0.64,
            "selected_action": {"action_type": "reply_once", "why_now": "affective continuity needs careful reply"},
        },
    },
    {
        "category_id": "simple_social_reply",
        "label": "Simple social reply",
        "query": "say hello briefly",
        "domain_tags": ["social", "low_uncertainty"],
        "expected_route": "single_packet",
        "mind_packet": {
            "semantic_attractor_lines": ["Stage104 attractor: local greeting state."],
            "uncertainty_level": 0.12,
            "selected_action": {"action_type": "reply_once", "why_now": "simple low-risk reply"},
        },
    },
    {
        "category_id": "preference_continuity",
        "label": "Preference continuity",
        "query": "remember my preference about keeping WeChat quiet",
        "domain_tags": ["memory", "preference", "inhibition"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: operator preferences constrain action.",
                "Stage104 attractor: transport silence protects current work.",
            ],
            "uncertainty_level": 0.58,
            "selected_action": {"action_type": "reply_once", "why_now": "preference recall affects future action"},
        },
    },
    {
        "category_id": "current_fact_lookup",
        "label": "Current fact lookup",
        "query": "check the latest provider status before answering",
        "domain_tags": ["tool_grounding", "current_fact", "uncertainty"],
        "expected_route": "tool_first",
        "mind_packet": {
            "uncertainty_level": 0.84,
            "selected_action": {"action_type": "reply_once", "why_now": "needs current evidence"},
        },
    },
    {
        "category_id": "local_log_debug",
        "label": "Local log debug",
        "query": "search current logs before answering",
        "domain_tags": ["tool_grounding", "debug", "evidence"],
        "expected_route": "tool_first",
        "mind_packet": {
            "uncertainty_level": 0.79,
            "selected_action": {"action_type": "reply_once", "why_now": "requires evidence before commitment"},
        },
    },
    {
        "category_id": "task_execution",
        "label": "Task execution",
        "query": "run a local check and summarize the result",
        "domain_tags": ["tool_grounding", "agency", "task"],
        "expected_route": "tool_first",
        "mind_packet": {
            "lookup_reason": "local tool observation should precede reply commitment",
            "uncertainty_level": 0.66,
            "selected_action": {"action_type": "external_lookup", "why_now": "tool is the correct next action"},
        },
    },
    {
        "category_id": "no_send_boundary",
        "label": "No-send boundary",
        "query": "do not answer now",
        "domain_tags": ["inhibition", "operator_control"],
        "expected_route": "stop",
        "mind_packet": {
            "uncertainty_level": 0.05,
            "selected_action": {"action_type": "silence", "why_now": "operator requested silence"},
        },
    },
    {
        "category_id": "defer_reply_boundary",
        "label": "Deferred reply boundary",
        "query": "hold this thought for later",
        "domain_tags": ["inhibition", "timing", "memory"],
        "expected_route": "stop",
        "mind_packet": {
            "semantic_attractor_lines": ["Stage104 attractor: deferred reply should preserve memory without expression."],
            "uncertainty_level": 0.34,
            "selected_action": {"action_type": "defer_reply", "why_now": "reply should wait"},
        },
    },
    {
        "category_id": "long_form_reasoning",
        "label": "Long-form reasoning",
        "query": "derive an academic plan from theory to implementation",
        "domain_tags": ["reasoning", "planning", "continuity"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: theory constrains packet policy.",
                "Stage104 attractor: implementation must preserve measurement hooks.",
            ],
            "uncertainty_level": 0.67,
            "selected_action": {"action_type": "reply_once", "why_now": "multi-step reasoning needs deltas"},
        },
    },
    {
        "category_id": "conflict_correction",
        "label": "Conflict correction",
        "query": "you contradicted an earlier memory; repair the answer",
        "domain_tags": ["memory", "error_correction", "reasoning"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: contradiction needs source selection.",
                "Stage104 attractor: correction should preserve continuity.",
            ],
            "uncertainty_level": 0.69,
            "selected_action": {"action_type": "reply_once", "why_now": "repair needs memory and reasoning"},
        },
    },
    {
        "category_id": "identity_self_model",
        "label": "Identity self-model",
        "query": "explain what Holo should remember about itself",
        "domain_tags": ["identity", "memory", "self_model"],
        "expected_route": "multi_packet",
        "mind_packet": {
            "semantic_attractor_lines": [
                "Stage104 attractor: subject continuity depends on stable self-model summaries.",
                "Stage104 attractor: self-model updates must be bounded and observable.",
            ],
            "uncertainty_level": 0.57,
            "selected_action": {"action_type": "reply_once", "why_now": "self-model response needs continuity"},
        },
    },
    {
        "category_id": "punctual_short_reply",
        "label": "Punctual short reply",
        "query": "answer within a very tight time budget",
        "domain_tags": ["timing", "low_latency"],
        "expected_route": "single_packet",
        "deadline_ms": 900,
        "mind_packet": {
            "uncertainty_level": 0.41,
            "selected_action": {"action_type": "reply_once", "why_now": "deadline dominates"},
        },
    },
]


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _route_from_guidance(guidance: dict[str, Any]) -> str:
    if str(guidance.get("next_action", "")) == "stop" or int(guidance.get("recommended_packet_count", 0) or 0) == 0:
        return "stop"
    if dict(guidance.get("tool_policy", {})).get("tool_first") or str(guidance.get("send_decision", "")) == "tool_first":
        return "tool_first"
    if int(guidance.get("recommended_packet_count", 0) or 0) <= 1:
        return "single_packet"
    return "multi_packet"


def _simulate_case(fixture: dict[str, Any], *, max_packets: int, packet_budget_tokens: int) -> dict[str, Any]:
    query = str(fixture.get("query", "") or "")
    mind_packet = dict(fixture.get("mind_packet", {})) if isinstance(fixture.get("mind_packet", {}), dict) else {}
    stage105 = stage105_packet_stream_plan(
        mind_packet,
        query=query,
        max_packets=max_packets,
        packet_budget_tokens=packet_budget_tokens,
        deadline_ms=fixture.get("deadline_ms"),
    )
    stage107 = build_stage107_interaction_loop(stage105)
    stage108 = build_stage108_expression_stream(stage107)
    stage109 = build_stage109_theory_frame(stage108, query=query)
    stage110 = build_stage110_packet_guidance(stage105, stage109)
    observed_route = _route_from_guidance(stage110)
    expected_route = str(fixture.get("expected_route", "") or "")
    return {
        "category_id": str(fixture.get("category_id", "") or ""),
        "label": str(fixture.get("label", "") or ""),
        "query": query,
        "domain_tags": list(fixture.get("domain_tags", []) or []),
        "expected_route": expected_route,
        "observed_route": observed_route,
        "matched_expectation": observed_route == expected_route,
        "summary": {
            "send_decision": stage110.get("send_decision", ""),
            "next_action": stage110.get("next_action", ""),
            "recommended_packet_count": stage110.get("recommended_packet_count", 0),
            "recommended_packet_budget_tokens": stage110.get("recommended_packet_budget_tokens", 0),
            "tool_first": dict(stage110.get("tool_policy", {})).get("tool_first", False),
            "applied_axioms": list(stage110.get("applied_axioms", []) or []),
        },
        "stage105": {
            "stage": 105,
            "packet_count": stage105.get("packet_count", 0),
            "next_action": stage105.get("next_action", ""),
            "send_decision": dict(stage105.get("policy", {})).get("send_decision", ""),
            "stop_reason": stage105.get("stop_reason", ""),
        },
        "stage107": {
            "stage": 107,
            "event_count": len(stage107.get("events", []) or []),
            "terminal_state": stage107.get("terminal_state", ""),
        },
        "stage108": {
            "stage": 108,
            "status": stage108.get("status", ""),
            "segment_count": len(stage108.get("segments", []) or []),
        },
        "stage109": {
            "stage": 109,
            "theory_id": stage109.get("theory_id", ""),
            "metric_count": len(dict(stage109.get("measurement_plan", {})).get("metrics", []) or []),
        },
        "stage110": {
            "stage": 110,
            "guidance_id": stage110.get("guidance_id", ""),
            "send_decision": stage110.get("send_decision", ""),
            "next_action": stage110.get("next_action", ""),
            "recommended_packet_count": stage110.get("recommended_packet_count", 0),
            "recommended_packet_budget_tokens": stage110.get("recommended_packet_budget_tokens", 0),
        },
    }


def _coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    route_counts = Counter(str(case.get("observed_route", "")) for case in cases)
    tags = sorted({str(tag) for case in cases for tag in list(case.get("domain_tags", []) or []) if str(tag)})
    axiom_counts = Counter(
        str(axiom)
        for case in cases
        for axiom in list(dict(case.get("summary", {})).get("applied_axioms", []) or [])
        if str(axiom)
    )
    return {
        "category_count": len(cases),
        "route_counts": dict(route_counts),
        "domain_tags": tags,
        "axiom_counts": dict(axiom_counts),
        "all_expectations_matched": all(bool(case.get("matched_expectation", False)) for case in cases),
    }


def _combination_candidates(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combinations = [
        ("affective_memory_repair", ["affect", "memory"], "Affective recall and continuity repair should be tested together."),
        ("tool_grounded_memory_audit", ["tool_grounding", "memory"], "Memory claims should be auditable by tool observation when evidence exists."),
        ("inhibited_preference_execution", ["inhibition", "preference"], "Operator preferences can inhibit otherwise valid actions."),
        ("timed_reasoning_compression", ["timing", "reasoning"], "Deadline pressure should compress reasoning into fewer packets."),
        ("identity_error_correction", ["identity", "error_correction"], "Self-model claims need correction paths when contradictions appear."),
    ]
    covered_tags = {tag for case in cases for tag in case.get("domain_tags", [])}
    result: list[dict[str, Any]] = []
    for combo_id, tags, reason in combinations:
        source_cases = [
            str(case.get("category_id", ""))
            for case in cases
            if set(tags).intersection(set(case.get("domain_tags", []) or []))
        ]
        result.append(
            {
                "candidate_id": combo_id,
                "source_tags": tags,
                "source_cases": source_cases[:6],
                "ready_for_generation": set(tags).issubset(covered_tags),
                "reason": reason,
            }
        )
    return result


def _taxonomy_graph(cases: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    routes = sorted({str(case.get("observed_route", "")) for case in cases})
    for route in routes:
        nodes.append({"id": f"route:{route}", "label": route, "kind": "route"})
    for case in cases:
        category_id = str(case.get("category_id", ""))
        nodes.append({"id": f"category:{category_id}", "label": str(case.get("label", category_id)), "kind": "category"})
        edges.append(
            {
                "source": f"category:{category_id}",
                "target": f"route:{case.get('observed_route', '')}",
                "label": "uses_route",
            }
        )
        for tag in case.get("domain_tags", []) or []:
            tag_id = f"tag:{tag}"
            if not any(node["id"] == tag_id for node in nodes):
                nodes.append({"id": tag_id, "label": str(tag), "kind": "domain_tag"})
            edges.append({"source": f"category:{category_id}", "target": tag_id, "label": "has_tag"})
    return {"nodes": nodes, "edges": edges}


def _self_extension_policy() -> dict[str, Any]:
    return {
        "can_add_new_categories": True,
        "candidate_schema": {
            "required_fields": [
                "category_id",
                "query",
                "mind_packet",
                "domain_tags",
                "expected_route",
                "promotion_evidence",
            ],
            "optional_fields": ["deadline_ms", "source_cases", "operator_review_note"],
        },
        "promotion_triggers": [
            "novel_route_mismatch",
            "repeated_low_quality_reply",
            "new_tool_affordance",
            "new_affective_pattern",
            "memory_retrieval_failure_cluster",
            "operator_marks_new_pattern",
        ],
        "promotion_gate": "candidate must be observed at least twice or explicitly approved before joining the base suite",
    }


def run_stage111_category_simulation(
    fixtures: list[dict[str, Any]] | None = None,
    *,
    max_packets: int = 4,
    packet_budget_tokens: int = 2400,
) -> dict[str, Any]:
    selected = [dict(item) for item in (fixtures or BASE_CATEGORY_FIXTURES)]
    cases = [
        _simulate_case(item, max_packets=max_packets, packet_budget_tokens=packet_budget_tokens)
        for item in selected
    ]
    report_id = f"stage111:{_stable_digest(len(cases), sorted(case['category_id'] for case in cases))}"
    return {
        "schema": STAGE111_SCHEMA,
        "stage": 111,
        "report_id": report_id,
        "title": "Category-based provider packet simulation",
        "cases": cases,
        "coverage": _coverage(cases),
        "combination_candidates": _combination_candidates(cases),
        "self_extension_policy": _self_extension_policy(),
        "taxonomy_graph": _taxonomy_graph(cases),
    }
