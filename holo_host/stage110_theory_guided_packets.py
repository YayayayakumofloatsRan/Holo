from __future__ import annotations

import hashlib
from typing import Any

STAGE110_SCHEMA = "holo.stage110.theory_guided_packets.v1"


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _policy(stage105: dict[str, Any]) -> dict[str, Any]:
    payload = stage105.get("policy", {})
    return dict(payload) if isinstance(payload, dict) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metric_ids(stage109: dict[str, Any]) -> list[str]:
    measurement_plan = stage109.get("measurement_plan", {})
    metrics = list(dict(measurement_plan).get("metrics", []) or []) if isinstance(measurement_plan, dict) else []
    ids: list[str] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id = str(metric.get("id", "") or "").strip()
        if metric_id and metric_id not in ids:
            ids.append(metric_id)
    return ids


def _stage108_status(stage109: dict[str, Any]) -> str:
    stage108 = stage109.get("stage108", {})
    if isinstance(stage108, dict):
        return str(stage108.get("status", "") or "").strip()
    bridge = stage109.get("internal_external_bridge", {})
    if isinstance(bridge, dict):
        coverage = bridge.get("source_event_coverage", {})
        if isinstance(coverage, dict) and str(coverage.get("status", "") or "") == "pending":
            return "awaiting_internal_event"
    return ""


def _packet_rules(stage105: dict[str, Any], recommended_count: int, recommended_budget: int) -> list[dict[str, Any]]:
    packets = [dict(item) for item in list(stage105.get("packets", []) or []) if isinstance(item, dict)]
    rules: list[dict[str, Any]] = []
    if recommended_count > 0:
        rules.append(
            {
                "rule_id": "preserve_context_seed",
                "reason": "finite working memory must begin from query, selected action, and compact recall",
                "applies_to": "context_seed",
            }
        )
    if recommended_count >= 2:
        rules.append(
            {
                "rule_id": "require_delta_repack",
                "reason": "provider returns must be compressed before the next packet",
                "applies_to": "deliberation_delta",
            }
        )
    if recommended_count >= 3:
        rules.append(
            {
                "rule_id": "commit_after_delta",
                "reason": "reply commitment should happen only after semantic movement is compressed",
                "applies_to": "reply_commit",
            }
        )
    for packet in packets:
        packet_role = str(packet.get("packet_role", "") or "")
        rules.append(
            {
                "rule_id": f"budget_{packet_role or packet.get('index', '')}",
                "applies_to": packet_role,
                "recommended_budget_tokens": max(384, recommended_budget // max(1, recommended_count)),
            }
        )
    return rules


def build_stage110_packet_guidance(stage105_plan: dict[str, Any], stage109_frame: dict[str, Any] | None = None) -> dict[str, Any]:
    frame = dict(stage109_frame or {})
    policy = _policy(stage105_plan)
    query = str(stage105_plan.get("query", "") or frame.get("query", "") or "")
    base_count = _safe_int(stage105_plan.get("packet_count", 0), 0)
    base_budget = _safe_int(policy.get("packet_budget_tokens", 2400), 2400)
    uncertainty = _safe_float(policy.get("uncertainty_level", 0.0), 0.0)
    attractor_count = _safe_int(policy.get("semantic_attractor_count", 0), 0)
    broad_recall = bool(policy.get("broad_recall", False))
    send_decision = str(policy.get("send_decision", "") or "").strip()
    next_action = str(stage105_plan.get("next_action", "") or "").strip()
    applied_axioms = ["A1_finite_context", "A5_expression_decoupling"]

    recommended_count = base_count
    recommended_budget = base_budget
    tool_first = send_decision == "tool_first" or next_action == "tool_request"

    if send_decision == "do_not_send" or next_action == "no_send":
        recommended_count = 0
        recommended_budget = 0
        next_action = "stop"
        applied_axioms.extend(["A3_compressive_recurrence", "A5_expression_decoupling"])
    elif tool_first:
        recommended_count = max(1, min(base_count or 1, 1))
        recommended_budget = max(960, base_budget // 2)
        send_decision = "tool_first"
        next_action = "execute_tool_locally"
        applied_axioms.extend(["A4_grounded_perturbation", "A5_expression_decoupling"])
    else:
        if broad_recall or attractor_count >= 2:
            recommended_count = max(base_count, min(3, _safe_int(policy.get("max_packets", 4), 4)))
            recommended_budget = max(base_budget, base_budget + 600)
            applied_axioms.extend(["A2_local_continuity", "A3_compressive_recurrence"])
        elif uncertainty >= 0.55:
            recommended_count = max(base_count, 2)
            recommended_budget = max(base_budget, base_budget + 300)
            applied_axioms.append("A3_compressive_recurrence")
        elif uncertainty <= 0.25:
            recommended_count = min(max(base_count, 1), 1)
            recommended_budget = min(base_budget, 1800)
        next_action = "send_provider_packet" if recommended_count > 0 else "stop"

    metric_ids = _metric_ids(frame)
    stage108_status = _stage108_status(frame)
    guidance_id = f"stage110:{_stable_digest(query, send_decision, recommended_count, recommended_budget)}"
    return {
        "schema": STAGE110_SCHEMA,
        "stage": 110,
        "guidance_id": guidance_id,
        "query": query,
        "send_decision": send_decision or policy.get("send_decision", ""),
        "next_action": next_action,
        "recommended_packet_count": int(recommended_count),
        "recommended_packet_budget_tokens": int(recommended_budget),
        "applied_axioms": list(dict.fromkeys(applied_axioms)),
        "packet_rules": _packet_rules(stage105_plan, int(recommended_count), int(recommended_budget)),
        "tool_policy": {
            "tool_first": bool(tool_first),
            "must_observe_before_reply_commit": bool(tool_first),
            "provider_may_execute_tools": False,
            "observation_reenters_next_packet": True,
        },
        "expression_policy": {
            "may_emit_before_provider_return": False,
            "required_stage108_status": stage108_status or "awaiting_internal_event",
            "external_reply_is_not_equal_to_provider_packet": True,
            "wait_for_ready_to_emit_or_no_output": True,
        },
        "measurement_hooks": {
            "required_metric_ids": metric_ids,
            "must_record_packet_budget": True,
            "must_record_delta_retention": "delta_retention" in metric_ids,
            "must_record_expression_fit": "expression_granularity_fit" in metric_ids,
        },
        "stage105": {
            "packet_count": base_count,
            "send_decision": policy.get("send_decision", ""),
            "next_action": stage105_plan.get("next_action", ""),
            "stop_reason": stage105_plan.get("stop_reason", ""),
        },
        "stage109": {
            "stage": 109,
            "theory_id": str(frame.get("theory_id", "") or ""),
            "title": str(frame.get("title", "") or ""),
        },
    }
