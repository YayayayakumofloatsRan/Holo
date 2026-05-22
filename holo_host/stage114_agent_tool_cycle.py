from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .stage105_provider_packet_stream import stage105_packet_stream_plan
from .stage106_deepseek_tool_adapter import parse_provider_tool_calls
from .stage107_provider_interaction_loop import build_stage107_interaction_loop
from .stage113_agent_tool_executor import LookupFn, execute_stage113_agent_tools

STAGE114_SCHEMA = "holo.stage114.agent_tool_cycle.v1"


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _stage105_tool_calls(stage105_plan: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, request in enumerate(list(stage105_plan.get("tool_requests", []) or [])):
        if not isinstance(request, dict):
            continue
        calls.append(
            {
                "id": str(request.get("provider_call_id", "") or f"stage105_tool_{index + 1}"),
                "name": str(request.get("name", "") or ""),
                "arguments": dict(request.get("payload", {}) or {}) if isinstance(request.get("payload", {}), dict) else {},
                "allowed": True,
                "status": "accepted",
                "error": "",
                "source": "stage105_tool_request",
            }
        )
    return calls


def _provider_tool_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [dict(item) for item in calls if bool(item.get("allowed", False))]
    rejected = [dict(item) for item in calls if not bool(item.get("allowed", False))]
    return {
        "count": len(calls),
        "accepted_names": [str(item.get("name", "")) for item in accepted],
        "rejected_errors": [str(item.get("error", "")) for item in rejected],
        "calls": calls,
    }


def _first_provider_packet(loop: dict[str, Any]) -> dict[str, Any]:
    for event in list(loop.get("events", []) or []):
        if str(event.get("phase", "")) == "provider_packet":
            return {
                "available": True,
                "event_id": str(event.get("event_id", "")),
                "packet_id": str(event.get("packet_id", "")),
                "packet_role": str(event.get("packet_role", "")),
                "inputs": dict(event.get("inputs", {}) or {}),
                "metadata": dict(event.get("metadata", {}) or {}),
            }
    return {"available": False, "inputs": {}, "metadata": {}}


def _simulated_decoded_provider_response(tool: str, query: str) -> dict[str, Any]:
    tool_calls: list[dict[str, Any]] = []
    if tool in {"external_lookup", "both"}:
        tool_calls.append(
            {
                "id": "sim_external_lookup",
                "type": "function",
                "function": {
                    "name": "external_lookup",
                    "arguments": json.dumps({"query": query, "max_results": 3}),
                },
            }
        )
    if tool in {"memory_recall", "both"}:
        tool_calls.append(
            {
                "id": "sim_memory_recall",
                "type": "function",
                "function": {
                    "name": "memory_recall",
                    "arguments": json.dumps({"query": query, "limit": 6}),
                },
            }
        )
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {"content": "", "tool_calls": tool_calls},
            }
        ]
    }


def run_stage114_agent_tool_cycle(
    stage105_plan: dict[str, Any],
    *,
    decoded_provider_response: dict[str, Any] | None = None,
    external_lookup_fn: LookupFn | None = None,
    memory_corpus: list[dict[str, Any]] | None = None,
    memory_corpus_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    network_enabled: bool = False,
) -> dict[str, Any]:
    provider_calls = parse_provider_tool_calls(decoded_provider_response) if decoded_provider_response is not None else []
    stage105_calls = _stage105_tool_calls(stage105_plan) if not provider_calls else []
    calls = provider_calls or stage105_calls
    execution = execute_stage113_agent_tools(
        calls,
        external_lookup_fn=external_lookup_fn,
        memory_corpus=memory_corpus,
        memory_corpus_path=memory_corpus_path,
        repo_root=repo_root,
        network_enabled=network_enabled,
    )
    reentry_loop = build_stage107_interaction_loop(
        stage105_plan,
        tool_observations=list(execution.get("observations", []) or []),
    )
    cycle_id = f"stage114:{_stable_digest(stage105_plan.get('query', ''), [call.get('id', '') for call in calls])}"
    return {
        "schema": STAGE114_SCHEMA,
        "stage": 114,
        "cycle_id": cycle_id,
        "query": str(stage105_plan.get("query", "") or ""),
        "provider_tool_calls": _provider_tool_summary(provider_calls),
        "stage105_tool_calls": _provider_tool_summary(stage105_calls),
        "tool_execution": execution,
        "reentry_loop": {
            "stage": 107,
            "status": reentry_loop.get("status", ""),
            "next_action": reentry_loop.get("next_action", ""),
            "events": list(reentry_loop.get("events", []) or []),
        },
        "next_provider_packet": _first_provider_packet(reentry_loop),
        "ready": {
            "tool_execution_completed": int(dict(execution.get("summary", {})).get("executed_count", 0) or 0) > 0,
            "has_next_provider_packet": bool(_first_provider_packet(reentry_loop).get("available", False)),
            "can_continue_agent_loop": bool(_first_provider_packet(reentry_loop).get("available", False)),
        },
        "authority": {
            "provider_may_execute_tools": False,
            "local_executor_stage": 113,
            "reentry_stage": 107,
        },
    }


def run_stage114_simulated_cycle(
    *,
    query: str,
    simulate_tool: str,
    memory_corpus_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    network_enabled: bool = False,
) -> dict[str, Any]:
    stage105 = stage105_packet_stream_plan(
        {
            "semantic_attractor_lines": [
                "tool observations should re-enter provider packets",
                "agent loop requires local execution before reply commitment",
            ],
            "uncertainty_level": 0.67,
            "selected_action": {"action_type": "reply_once", "why_now": "tool-grounded continuation"},
        },
        query=query,
        max_packets=4,
    )
    return run_stage114_agent_tool_cycle(
        stage105,
        decoded_provider_response=_simulated_decoded_provider_response(simulate_tool, query),
        memory_corpus_path=memory_corpus_path,
        repo_root=repo_root,
        network_enabled=network_enabled,
    )
