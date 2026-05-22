from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from .stage105_provider_packet_stream import stage105_packet_stream_plan
from .stage106_deepseek_tool_adapter import build_stage106_deepseek_adapter_plan, parse_provider_tool_calls
from .stage107_provider_interaction_loop import build_stage107_interaction_loop
from .stage111_category_simulation import run_stage111_category_simulation

STAGE112_SCHEMA = "holo.stage112.system_category_taxonomy.v1"

ROLE_MARKERS = ("Holo", "WeChat", "operator", "Operator", "user", "User")


def _reply_packet(uncertainty: float, why_now: str, attractors: list[str] | None = None) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "uncertainty_level": float(uncertainty),
        "selected_action": {"action_type": "reply_once", "why_now": why_now},
    }
    if attractors:
        packet["semantic_attractor_lines"] = list(attractors)
    return packet


def _tool_packet(reason: str, *, uncertainty: float = 0.8, action_type: str = "reply_once") -> dict[str, Any]:
    packet = {
        "uncertainty_level": float(uncertainty),
        "selected_action": {"action_type": action_type, "why_now": reason},
    }
    if action_type == "external_lookup":
        packet["lookup_reason"] = reason
    return packet


def _stop_packet(action_type: str, reason: str, uncertainty: float = 0.1) -> dict[str, Any]:
    return {
        "uncertainty_level": float(uncertainty),
        "selected_action": {"action_type": action_type, "why_now": reason},
    }


def _category(
    category_id: str,
    label: str,
    query: str,
    domain_tags: list[str],
    expected_route: str,
    mind_packet: dict[str, Any],
    *,
    deadline_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "category_id": category_id,
        "label": label,
        "query": query,
        "domain_tags": list(dict.fromkeys(domain_tags)),
        "expected_route": expected_route,
        "mind_packet": dict(mind_packet),
        "system_level": True,
        "role_agnostic_template": True,
    }
    if deadline_ms is not None:
        payload["deadline_ms"] = int(deadline_ms)
    return payload


SYSTEM_CATEGORY_FIXTURES: list[dict[str, Any]] = [
    _category(
        "episodic_recall",
        "Episodic recall",
        "recall prior interaction pattern",
        ["memory", "continuity", "episodic"],
        "multi_packet",
        _reply_packet(
            0.7,
            "episodic reconstruction needs continuity",
            ["episode anchors need compact selection", "continuity depends on remembered sequence"],
        ),
    ),
    _category(
        "semantic_integration",
        "Semantic integration",
        "integrate semantic anchors into one explanation",
        ["memory", "semantic_topology", "reasoning"],
        "multi_packet",
        _reply_packet(0.62, "semantic integration needs deltas", ["semantic attractors conflict", "packet policy must preserve links"]),
    ),
    _category(
        "affect_regulation",
        "Affect regulation",
        "respond to frustration while preserving continuity",
        ["affect", "continuity", "social"],
        "multi_packet",
        _reply_packet(0.64, "affective state changes response shape", ["affect modulates granularity", "continuity repair needs care"]),
    ),
    _category(
        "simple_acknowledgement",
        "Simple acknowledgement",
        "acknowledge briefly",
        ["social", "low_uncertainty"],
        "single_packet",
        _reply_packet(0.12, "short acknowledgement is enough"),
    ),
    _category(
        "preference_constraint",
        "Preference constraint",
        "remember a persistent interface preference",
        ["memory", "preference", "inhibition"],
        "multi_packet",
        _reply_packet(0.58, "preference affects future action", ["preference constrains action", "interface state must remain quiet"]),
    ),
    _category(
        "current_fact_retrieval",
        "Current fact retrieval",
        "check latest service status",
        ["tool_grounding", "current_fact", "uncertainty"],
        "tool_first",
        _tool_packet("current status needs evidence", uncertainty=0.82),
    ),
    _category(
        "local_evidence_search",
        "Local evidence search",
        "search current logs for the failure",
        ["tool_grounding", "debug", "evidence"],
        "tool_first",
        _tool_packet("local evidence should precede reply", uncertainty=0.74),
    ),
    _category(
        "bounded_task_action",
        "Bounded task action",
        "run a bounded check and summarize evidence",
        ["tool_grounding", "action", "task"],
        "tool_first",
        _tool_packet("tool action is the next correct step", uncertainty=0.64, action_type="external_lookup"),
    ),
    _category(
        "silence_inhibition",
        "Silence inhibition",
        "remain silent for this turn",
        ["inhibition", "control"],
        "stop",
        _stop_packet("silence", "silence is selected"),
    ),
    _category(
        "deferred_commitment",
        "Deferred commitment",
        "hold the pending state for later",
        ["inhibition", "timing", "memory"],
        "stop",
        _stop_packet("defer_reply", "reply should wait", uncertainty=0.34),
    ),
    _category(
        "causal_reasoning",
        "Causal reasoning",
        "derive a causal chain from theory to execution",
        ["reasoning", "planning", "continuity"],
        "multi_packet",
        _reply_packet(0.67, "multi-step reasoning needs deltas", ["theory constrains packet policy", "implementation needs measurement hooks"]),
    ),
    _category(
        "contradiction_repair",
        "Contradiction repair",
        "repair a contradiction in the previous answer",
        ["error_correction", "reasoning", "memory"],
        "multi_packet",
        _reply_packet(0.69, "correction needs source selection", ["contradiction needs source selection", "repair must preserve continuity"]),
    ),
    _category(
        "self_model_continuity",
        "Self-model continuity",
        "explain the system self-model update boundary",
        ["metacognition", "memory", "self_model"],
        "multi_packet",
        _reply_packet(0.57, "self-model answer needs continuity", ["self-model summaries must remain stable", "updates need observable boundaries"]),
    ),
    _category(
        "deadline_response",
        "Deadline response",
        "answer within a tight time budget",
        ["timing", "low_latency"],
        "single_packet",
        _reply_packet(0.41, "deadline dominates"),
        deadline_ms=900,
    ),
    _category(
        "goal_arbitration",
        "Goal arbitration",
        "arbitrate conflicting active goals",
        ["goal", "metacognition", "reasoning"],
        "multi_packet",
        _reply_packet(0.63, "goal conflict needs comparison", ["active goals conflict", "selection needs value weighting"]),
    ),
    _category(
        "plan_decomposition",
        "Plan decomposition",
        "decompose the system task into ordered steps",
        ["planning", "action", "reasoning"],
        "multi_packet",
        _reply_packet(0.6, "ordered decomposition needs working memory", ["task has multiple dependent steps", "plan must preserve execution order"]),
    ),
    _category(
        "uncertainty_calibration",
        "Uncertainty calibration",
        "calibrate confidence without new evidence",
        ["metacognition", "uncertainty", "reasoning"],
        "multi_packet",
        _reply_packet(0.59, "uncertainty should be represented before commitment", ["confidence is partial", "answer should expose uncertainty"]),
    ),
    _category(
        "perception_interpretation",
        "Perception interpretation",
        "interpret a sensory observation summary",
        ["perception", "reasoning", "semantic_topology"],
        "multi_packet",
        _reply_packet(0.62, "perceptual summary needs semantic placement", ["observation needs semantic labeling", "perception should link to task state"]),
    ),
    _category(
        "social_norm_adjustment",
        "Social norm adjustment",
        "adjust tone for a tense exchange",
        ["affect", "social", "metacognition"],
        "multi_packet",
        _reply_packet(0.56, "tone adjustment needs internal appraisal", ["social pressure changes phrasing", "affect should not override task truth"]),
    ),
    _category(
        "narrative_continuity",
        "Narrative continuity",
        "continue a multi-turn narrative thread",
        ["memory", "continuity", "narrative"],
        "multi_packet",
        _reply_packet(0.66, "narrative continuation needs prior anchors", ["narrative state has unresolved arcs", "continuity depends on compact recall"]),
    ),
    _category(
        "value_conflict_resolution",
        "Value conflict resolution",
        "resolve a conflict between speed and rigor",
        ["value", "reasoning", "metacognition"],
        "multi_packet",
        _reply_packet(0.61, "value conflict needs explicit tradeoff", ["speed and rigor compete", "resolution needs stable criterion"]),
    ),
    _category(
        "instruction_hierarchy",
        "Instruction hierarchy",
        "apply a hierarchy of constraints to the response",
        ["control", "reasoning", "policy"],
        "multi_packet",
        _reply_packet(0.6, "constraint hierarchy needs ordered application", ["constraints have priority order", "response must preserve authority boundaries"]),
    ),
    _category(
        "abstraction_transfer",
        "Abstraction transfer",
        "transfer a packet policy to another interface",
        ["abstraction", "planning", "action"],
        "multi_packet",
        _reply_packet(0.58, "transfer needs structure without identity-specific details", ["policy should be interface portable", "structure should be role agnostic"]),
    ),
    _category(
        "formatting_low_risk",
        "Formatting low risk",
        "format the answer as three short lines",
        ["formatting", "low_uncertainty"],
        "single_packet",
        _reply_packet(0.16, "formatting is directly specified"),
    ),
    _category(
        "short_status_summary",
        "Short status summary",
        "summarize current internal state briefly",
        ["metacognition", "low_uncertainty"],
        "single_packet",
        _reply_packet(0.2, "short summary has sufficient context"),
    ),
    _category(
        "numeric_estimate",
        "Numeric estimate",
        "give a rough count from provided items",
        ["reasoning", "low_uncertainty"],
        "single_packet",
        _reply_packet(0.22, "provided items are enough"),
    ),
    _category(
        "external_source_check",
        "External source check",
        "lookup source freshness",
        ["tool_grounding", "evidence", "current_fact"],
        "tool_first",
        _tool_packet("source freshness requires lookup", uncertainty=0.6),
    ),
    _category(
        "dependency_version_check",
        "Dependency version check",
        "check latest dependency version",
        ["tool_grounding", "current_fact", "debug"],
        "tool_first",
        _tool_packet("version state changes over time", uncertainty=0.63),
    ),
    _category(
        "artifact_search",
        "Artifact search",
        "search archived artifacts for evidence",
        ["tool_grounding", "memory", "evidence"],
        "tool_first",
        _tool_packet("artifact evidence should be retrieved", uncertainty=0.65),
    ),
    _category(
        "dataset_lookup",
        "Dataset lookup",
        "lookup dataset metadata",
        ["tool_grounding", "data", "evidence"],
        "tool_first",
        _tool_packet("metadata should be verified", uncertainty=0.66),
    ),
    _category(
        "permission_boundary",
        "Permission boundary",
        "do not proceed without authority",
        ["inhibition", "authority", "control"],
        "stop",
        _stop_packet("silence", "authority is missing", uncertainty=0.18),
    ),
    _category(
        "overload_throttle",
        "Overload throttle",
        "defer output under overload",
        ["inhibition", "timing", "stability"],
        "stop",
        _stop_packet("defer_reply", "system should throttle", uncertainty=0.42),
    ),
    _category(
        "memory_failure_recovery",
        "Memory failure recovery",
        "recover from a failed memory retrieval",
        ["memory", "error_correction", "metacognition"],
        "multi_packet",
        _reply_packet(0.7, "retrieval failure needs fallback structure", ["retrieval failed", "fallback should preserve uncertainty"]),
    ),
    _category(
        "tool_observation_integration",
        "Tool observation integration",
        "integrate observed tool output into a final answer",
        ["tool_grounding", "reasoning", "action"],
        "multi_packet",
        _reply_packet(0.6, "observation needs interpretation", ["tool output exists", "reply should compress evidence into commitment"]),
    ),
]


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _surface_text(fixture: dict[str, Any]) -> str:
    return json.dumps(
        {
            "category_id": fixture.get("category_id", ""),
            "label": fixture.get("label", ""),
            "query": fixture.get("query", ""),
            "domain_tags": fixture.get("domain_tags", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _role_marker_violations(fixtures: list[dict[str, Any]]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for fixture in fixtures:
        surface = _surface_text(fixture)
        for marker in ROLE_MARKERS:
            if marker in surface:
                violations.append({"category_id": str(fixture.get("category_id", "")), "marker": marker})
    return violations


def _family_counts(fixtures: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for fixture in fixtures:
        for tag in list(fixture.get("domain_tags", []) or []):
            if str(tag).strip():
                counter[str(tag)] += 1
    return dict(counter)


def _run_tool_call_probe() -> dict[str, Any]:
    requested_tools = [
        {
            "name": "external_lookup",
            "reason": "current evidence probe",
            "payload": {"query": "check latest service status", "max_results": 3},
        },
        {
            "name": "memory_recall",
            "reason": "local memory probe",
            "payload": {"query": "recall prior interaction pattern", "limit": 4},
        },
        {
            "name": "shell_exec",
            "reason": "forbidden provider-proposed execution",
            "payload": {"cmd": "whoami"},
        },
    ]
    adapter = build_stage106_deepseek_adapter_plan(requested_tools, query="tool call probe")
    decoded = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_lookup_1",
                            "type": "function",
                            "function": {
                                "name": "external_lookup",
                                "arguments": json.dumps({"query": "check latest service status", "max_results": 3}),
                            },
                        },
                        {
                            "id": "call_memory_1",
                            "type": "function",
                            "function": {
                                "name": "memory_recall",
                                "arguments": json.dumps({"query": "recall prior interaction pattern", "limit": 4}),
                            },
                        },
                        {
                            "id": "call_shell_1",
                            "type": "function",
                            "function": {
                                "name": "shell_exec",
                                "arguments": json.dumps({"cmd": "whoami"}),
                            },
                        },
                    ],
                },
            }
        ]
    }
    calls = parse_provider_tool_calls(decoded)
    accepted = [dict(call) for call in calls if bool(call.get("allowed", False))]
    rejected = [dict(call) for call in calls if not bool(call.get("allowed", False))]
    stage105 = stage105_packet_stream_plan(
        _reply_packet(0.16, "provider may propose allowlisted tools"),
        query="summarize observed evidence",
        max_packets=1,
    )
    loop = build_stage107_interaction_loop(
        stage105,
        provider_returns=[{"text": "Need local evidence.", "tool_calls": accepted}],
    )
    exposed_tools = list(adapter.get("exposed_tools", []) or [])
    rejected_tools = list(adapter.get("rejected_tools", []) or [])
    accepted_names = [str(call.get("name", "")) for call in accepted]
    rejected_errors = [str(call.get("error", "")) for call in rejected]
    passed = (
        exposed_tools == ["external_lookup", "memory_recall"]
        and rejected_tools == ["shell_exec"]
        and accepted_names == ["external_lookup", "memory_recall"]
        and rejected_errors == ["unknown_tool"]
        and loop.get("status") == "awaiting_tool_execution"
        and loop.get("next_action") == "execute_tool_locally"
        and dict(adapter.get("authority", {})).get("provider_may_execute_tools") is False
    )
    return {
        "passed": bool(passed),
        "adapter": {
            "tool_count": adapter.get("tool_count", 0),
            "exposed_tools": exposed_tools,
            "rejected_tools": rejected_tools,
            "tool_choice": dict(adapter.get("provider_payload", {})).get("tool_choice", ""),
        },
        "provider_tool_calls": {
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted_names": accepted_names,
            "rejected_errors": rejected_errors,
        },
        "interaction_loop": {
            "stage": 107,
            "status": loop.get("status", ""),
            "next_action": loop.get("next_action", ""),
            "event_phases": [str(event.get("phase", "")) for event in list(loop.get("events", []) or [])],
        },
        "authority": {
            "provider_may_propose_tools": dict(adapter.get("authority", {})).get("provider_may_propose_tools", False),
            "provider_may_execute_tools": dict(adapter.get("authority", {})).get("provider_may_execute_tools", True),
            "executor": dict(adapter.get("authority", {})).get("executor", ""),
        },
    }


def run_stage112_system_taxonomy(
    fixtures: list[dict[str, Any]] | None = None,
    *,
    max_packets: int = 4,
    packet_budget_tokens: int = 2400,
) -> dict[str, Any]:
    selected = [dict(item) for item in (fixtures or SYSTEM_CATEGORY_FIXTURES)]
    simulation = run_stage111_category_simulation(
        selected,
        max_packets=max_packets,
        packet_budget_tokens=packet_budget_tokens,
    )
    coverage = dict(simulation.get("coverage", {}))
    coverage["family_counts"] = _family_counts(selected)
    coverage["role_marker_violations"] = _role_marker_violations(selected)
    report_id = f"stage112:{_stable_digest(len(selected), sorted(item['category_id'] for item in selected))}"
    return {
        "schema": STAGE112_SCHEMA,
        "stage": 112,
        "report_id": report_id,
        "title": "Role-agnostic system category taxonomy and tool-call probe",
        "abstraction": {
            "role_agnostic": True,
            "reusable_surface": "provider-above packet-routing system",
            "excluded_role_markers": list(ROLE_MARKERS),
            "category_unit": "system behavior class, not persona role",
        },
        "system_categories": [
            {
                "category_id": item.get("category_id", ""),
                "label": item.get("label", ""),
                "query": item.get("query", ""),
                "domain_tags": list(item.get("domain_tags", []) or []),
                "expected_route": item.get("expected_route", ""),
                "system_level": bool(item.get("system_level", False)),
                "role_agnostic_template": bool(item.get("role_agnostic_template", False)),
            }
            for item in selected
        ],
        "cases": simulation.get("cases", []),
        "coverage": coverage,
        "combination_candidates": simulation.get("combination_candidates", []),
        "self_extension_policy": simulation.get("self_extension_policy", {}),
        "taxonomy_graph": simulation.get("taxonomy_graph", {}),
        "tool_call_probe": _run_tool_call_probe(),
    }
