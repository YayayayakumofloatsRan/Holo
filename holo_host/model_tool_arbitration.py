from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .tool_action_space import build_tool_action_space, render_action_space_for_prompt

MODEL_TOOL_ARBITRATION_SCHEMA = "holo.stage161.model_tool_arbitration.v1"


def _json_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "{}"
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


def _list_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _default_decision() -> dict[str, Any]:
    return {
        "schema": MODEL_TOOL_ARBITRATION_SCHEMA,
        "goal_summary": "",
        "intent_type": "unknown",
        "selected_action": "answer_direct",
        "action_arguments": {},
        "why_this_action": "model decision was unavailable; host falls back to answer validation",
        "required_observations": [],
        "can_answer_without_tool": True,
        "confidence": 0.0,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "report attempted failure",
    }


def build_tool_arbitration_prompt(
    *,
    user_text: str,
    context_packet: dict,
    goal_state: dict,
    action_space: list[dict],
    prior_observations: list[dict],
) -> str:
    safe_context = sanitize_public_metadata(context_packet or {})
    safe_goal = sanitize_public_metadata(goal_state or {})
    safe_observations = sanitize_public_metadata(prior_observations or [])
    contract = {
        "goal_summary": "short description of the user's goal",
        "intent_type": "answer|memory_recall|web_lookup|engineering_task|project_state|followup|clarification|directive|unknown",
        "selected_action": "one action_type from the action space",
        "action_arguments": {"example": "arguments matching that action input_schema"},
        "why_this_action": "brief auditable reason; no hidden chain-of-thought",
        "required_observations": ["ledger names needed before a grounded final"],
        "can_answer_without_tool": False,
        "confidence": 0.0,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "how to report failure or ask for clarification",
    }
    return "\n".join(
        [
            "Stage161 Model-First Tool Arbitration",
            "Principle: LLM proposes. Host executes. Ledger proves. Stop controller closes.",
            "Choose exactly one next action from the action space. Deterministic hints, if present in context, are weak hints only.",
            "",
            "Exact User Text:",
            str(user_text or ""),
            "",
            "Goal State:",
            json.dumps(safe_goal, ensure_ascii=False, sort_keys=True),
            "",
            "Structured Context Packet:",
            json.dumps(safe_context, ensure_ascii=False, sort_keys=True),
            "",
            render_action_space_for_prompt(action_space),
            "",
            "Prior Observations:",
            json.dumps(safe_observations, ensure_ascii=False, sort_keys=True),
            "",
            "Return only JSON matching this contract:",
            json.dumps(contract, ensure_ascii=False, indent=2),
        ]
    )


def parse_tool_arbitration_decision(text: str) -> dict[str, Any]:
    parsed: dict[str, Any]
    try:
        loaded = json.loads(_json_text(text))
        parsed = dict(loaded) if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001
        parsed = {}
    decision = _default_decision()
    decision.update(
        {
            "goal_summary": compact_text(parsed.get("goal_summary", ""), 240),
            "intent_type": str(parsed.get("intent_type", decision["intent_type"]) or decision["intent_type"]),
            "selected_action": str(parsed.get("selected_action", decision["selected_action"]) or decision["selected_action"]),
            "action_arguments": _dict(parsed.get("action_arguments", {})),
            "why_this_action": compact_text(parsed.get("why_this_action", ""), 300),
            "required_observations": _list_str(parsed.get("required_observations", [])),
            "can_answer_without_tool": bool(parsed.get("can_answer_without_tool", False)),
            "confidence": round(max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0))), 4),
            "stop_if_observed": str(parsed.get("stop_if_observed", "final_answer_ready") or "final_answer_ready"),
            "fallback_if_failed": compact_text(parsed.get("fallback_if_failed", "report attempted failure"), 240),
        }
    )
    return decision


def decide_next_action_with_model(
    *,
    call_model: Callable[[str], str],
    user_text: str,
    context_packet: dict,
    goal_state: dict,
    action_space: list[dict],
    prior_observations: list[dict],
    deterministic_hints: dict | None = None,
) -> dict[str, Any]:
    prompt_context = dict(context_packet or {})
    if deterministic_hints:
        prompt_context["deterministic_hints"] = dict(deterministic_hints)
    prompt = build_tool_arbitration_prompt(
        user_text=user_text,
        context_packet=prompt_context,
        goal_state=goal_state,
        action_space=action_space,
        prior_observations=prior_observations,
    )
    try:
        raw = str(call_model(prompt) or "")
    except Exception as exc:  # noqa: BLE001
        raw = json.dumps({"selected_action": "defer", "why_this_action": f"model arbitration failed: {exc}"})
    decision = parse_tool_arbitration_decision(raw)
    raw_excerpt = "[redacted]" if re.search(r"(reasoning_content|chain_of_thought|hidden_reasoning)", raw, re.IGNORECASE) else compact_text(raw, 260)
    decision.update(
        {
            "schema": MODEL_TOOL_ARBITRATION_SCHEMA,
            "decision_id": "stage161_decision:" + stable_digest(user_text, decision.get("selected_action", ""), raw, limit=12),
            "source": "model_arbitration",
            "action_space_count": len(list(action_space or [])),
            "deterministic_hints": sanitize_public_metadata(dict(deterministic_hints or {})),
            "prompt_digest": stable_digest(prompt, limit=12),
            "raw_model_text_excerpt": raw_excerpt,
            "created_at": utc_now(),
        }
    )
    return sanitize_public_metadata(decision)


def derive_arbitration_from_stage152(
    stage152_report: dict[str, Any] | None,
    *,
    user_text: str = "",
) -> dict[str, Any]:
    report = dict(stage152_report or {})
    calls = [dict(item) for item in list(report.get("tool_calls", []) or []) if isinstance(item, dict)]
    if not calls and isinstance(report.get("live_trace", {}), dict):
        for event in list(report.get("live_trace", {}).get("events", []) or []):
            if not isinstance(event, dict) or str(event.get("event", "") or "") not in {"tool", "tool_call"}:
                continue
            name = str(event.get("action_type", event.get("tool", "")) or "")
            if not name:
                continue
            query = str(event.get("query", "") or "")
            args = {"query": query} if query and name == "web_search" else {"url": query} if query and name == "open_page" else {}
            calls.append({"name": name, "id": str(event.get("call_id", "") or ""), "arguments": args})
    observations = []
    for key in ("web_observation_ledger", "memory_observation_ledger", "tool_observation_ledger"):
        observations.extend(dict(row) for row in list(report.get(key, []) or []) if isinstance(row, dict))
    if calls:
        first = calls[0]
        selected = str(first.get("name", first.get("tool", first.get("function", {}).get("name", ""))) or "")
        args = _dict(first.get("arguments", {}))
        can_answer = False
        source = "stage152_tool_call"
    else:
        selected = "answer_direct"
        args = {}
        can_answer = True
        source = "stage152_no_tool_calls"
    required = []
    if selected == "memory_recall":
        required = ["memory_observation_ledger"]
    elif selected in {"web_search", "open_page", "find_in_page"}:
        required = ["web_observation_ledger"]
    elif selected in {"workspace_search", "file_read", "apply_patch", "test_run", "git_status", "git_diff"}:
        required = ["engineering_action_ledger"]
    elif selected == "market_research_pack":
        required = ["market_research_pack_ledger"]
    elif selected == "market_research_report":
        required = ["market_research_report_ledger"]
    elif selected == "market_research_dossier_resume":
        required = ["market_research_dossier_resume_ledger"]
    return sanitize_public_metadata(
        {
            "schema": MODEL_TOOL_ARBITRATION_SCHEMA,
            "decision_id": "stage161_decision:" + stable_digest(user_text, selected, source, limit=12),
            "source": source,
            "goal_summary": compact_text(user_text, 220),
            "intent_type": "unknown",
            "selected_action": selected or "answer_direct",
            "action_arguments": args,
            "why_this_action": "DeepSeek native tool loop proposed a host action" if calls else "DeepSeek returned no tool calls; host treats this as answer_direct and validates final claims",
            "required_observations": required,
            "can_answer_without_tool": can_answer,
            "confidence": 0.72 if calls else 0.52,
            "stop_if_observed": "final_answer_ready",
            "fallback_if_failed": "report attempted failure",
            "observation_count": len(observations),
            "stage152_stop_reason": str(report.get("stop_reason", "") or ""),
            "created_at": utc_now(),
        }
    )


def deterministic_hints_from_stage151(stage151_tool_decision: dict[str, Any] | None) -> dict[str, Any]:
    decision = dict(stage151_tool_decision or {})
    candidates = [dict(item) for item in list(decision.get("action_candidates", []) or []) if isinstance(item, dict)]
    suggested = [str(item.get("action_type", "") or "") for item in candidates if str(item.get("action_type", "") or "")]
    return {
        "possible_intents": [str(decision.get("intent_type", "") or "")] if decision.get("intent_type") else [],
        "suggested_actions": suggested,
        "risk_flags": [],
        "current_fact_possible": bool(decision.get("network_required", False)),
        "memory_possible": "memory_recall" in suggested,
        "engineering_possible": any(action in suggested for action in {"workspace_search", "file_read", "test_run", "git_status", "git_diff"}),
    }
