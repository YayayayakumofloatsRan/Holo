from __future__ import annotations

from typing import Any, Callable

from .common import stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_operator_live_action import run_market_research_operator_live_action
from .web_research_operator import run_web_research_operator

OPERATOR_REGISTRY_SCHEMA = "holo.stage217.operator_registry.v1"
OPERATOR_DISPATCH_SCHEMA = "holo.stage217.operator_dispatch.v1"
TOOL_ACTION_SPACE_SCHEMA = "holo.stage161.tool_action_space.v1"


_MARKET_OPERATOR = {
    "schema": OPERATOR_REGISTRY_SCHEMA,
    "operator_id": "market_research_operator_run",
    "operator_name": "Market Research Operator Run",
    "description": "Run the complete market-research operator trajectory: crawl, source promotion, evidence pack, report, finalization, and action journal.",
    "required_observation": "stage214_market_research_operator_run",
    "input_schema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "entity": {"type": "string"},
            "filing_type": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
    },
    "observation_schema": {"ledger": "stage214_market_research_operator_run"},
    "risk_level": "low",
    "requires_network": True,
    "requires_workspace": False,
    "is_readonly": True,
    "implements_live_work": True,
    "public_trace_event": "operator_dispatch",
    "examples": [
        {
            "when": "user asks the agent to choose and execute a filing-grounded fundamental research task",
            "arguments": {"query": "NVIDIA AI infrastructure official SEC 10-K filing", "filing_type": "10-K"},
        }
    ],
}

_WEB_RESEARCH_OPERATOR = {
    "schema": OPERATOR_REGISTRY_SCHEMA,
    "operator_id": "web_research_operator_run",
    "operator_name": "Web Research Operator Run",
    "description": "Run a bounded web/literature research trajectory: query planning, search, page opening, evidence evaluation, action journal, and grounded brief.",
    "required_observation": "stage218_web_research_operator_run",
    "input_schema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "max_queries": {"type": "integer"},
            "max_pages_per_query": {"type": "integer"},
        },
    },
    "observation_schema": {"ledger": "stage218_web_research_operator_run"},
    "risk_level": "low",
    "requires_network": True,
    "requires_workspace": False,
    "is_readonly": True,
    "implements_live_work": True,
    "public_trace_event": "web_research_operator",
    "examples": [
        {
            "when": "user asks for current web search, source-grounded documentation scouting, or literature-style web research",
            "arguments": {"query": "OpenAI Codex CLI official documentation", "max_queries": 3},
        }
    ],
}


def list_operator_definitions() -> list[dict[str, Any]]:
    return [dict(_MARKET_OPERATOR), dict(_WEB_RESEARCH_OPERATOR)]


def get_operator_definition(operator_id: str) -> dict[str, Any]:
    wanted = str(operator_id or "").strip()
    for definition in list_operator_definitions():
        if str(definition.get("operator_id", "") or "") == wanted:
            return definition
    return {}


def operator_action_space_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for definition in list_operator_definitions():
        entries.append(
            {
                "schema": TOOL_ACTION_SPACE_SCHEMA,
                "action_type": str(definition.get("operator_id", "") or ""),
                "description": str(definition.get("description", "") or ""),
                "input_schema": dict(definition.get("input_schema", {}) if isinstance(definition.get("input_schema", {}), dict) else {}),
                "observation_schema": dict(definition.get("observation_schema", {}) if isinstance(definition.get("observation_schema", {}), dict) else {}),
                "risk_level": str(definition.get("risk_level", "low") or "low"),
                "requires_network": bool(definition.get("requires_network", False)),
                "requires_workspace": bool(definition.get("requires_workspace", False)),
                "is_readonly": bool(definition.get("is_readonly", True)),
                "examples": [dict(item) for item in list(definition.get("examples", []) or []) if isinstance(item, dict)],
            }
        )
    return entries


def _capability_updates_from_market_operator(action_report: dict[str, Any], operator_run: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {
        "stage215_market_research_operator_action": action_report,
        "stage214_market_research_operator_run": operator_run,
    }
    if isinstance(operator_run.get("stage186_live_crawler_search", {}), dict):
        crawler = dict(operator_run.get("stage186_live_crawler_search", {}))
        updates["stage186_live_crawler_search"] = crawler
        updates["web_observation_ledger"] = [
            dict(row)
            for row in list(crawler.get("web_observation_ledger", []) or [])
            if isinstance(row, dict)
        ]
    for key in (
        "stage196_market_research_source_promotion",
        "stage169_market_research_pack",
        "stage173_market_research_report",
        "stage197_market_research_report_assembly",
        "stage198_market_research_finalization_gate",
        "stage212_action_journal",
    ):
        if isinstance(operator_run.get(key, {}), dict):
            updates[key] = dict(operator_run.get(key, {}))
    return sanitize_public_metadata(updates)


def _capability_updates_from_web_research_operator(operator_run: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {
        "stage218_web_research_operator_run": operator_run,
    }
    crawler = dict(operator_run.get("stage186_live_crawler_search", {})) if isinstance(operator_run.get("stage186_live_crawler_search", {}), dict) else {}
    if crawler:
        updates["stage186_live_crawler_search"] = crawler
        updates["web_observation_ledger"] = [
            dict(row)
            for row in list(crawler.get("web_observation_ledger", []) or [])
            if isinstance(row, dict)
        ]
    if isinstance(operator_run.get("stage212_action_journal", {}), dict):
        updates["stage212_action_journal"] = dict(operator_run.get("stage212_action_journal", {}))
    return sanitize_public_metadata(updates)


def _rejected(selected_action: str, reason: str) -> dict[str, Any]:
    return {
        "schema": OPERATOR_DISPATCH_SCHEMA,
        "status": "rejected",
        "operator_id": selected_action,
        "selected_action": selected_action,
        "reason": reason,
        "required_observation": "",
        "capability_context_updates": {},
        "final_visible_text": "",
        "canonical_stop_reason": "boundary_or_permission",
        "created_at": utc_now(),
    }


def dispatch_operator_action(
    decision: dict[str, Any],
    *,
    user_text: str,
    metadata: dict[str, Any] | None = None,
    channel: str = "",
    network_enabled: bool = True,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_action = str((decision or {}).get("selected_action", "") or "").strip()
    definition = get_operator_definition(selected_action)
    if not definition:
        return _rejected(selected_action, "unknown_operator")
    if not bool(definition.get("implements_live_work", False)):
        return _rejected(selected_action, "operator_not_live")

    action_args = dict((decision or {}).get("action_arguments", {}) or {})
    meta = dict(metadata or {})
    meta["stage215_market_research_operator_force"] = True
    if meta.get("stage217_operator_registry_dry_run") or action_args.get("dry_run"):
        meta["stage215_market_research_operator_dry_run"] = True
    if action_args.get("query") and not meta.get("stage215_market_research_operator_query"):
        meta["stage215_market_research_operator_query"] = str(action_args.get("query", "") or "")

    if selected_action == "market_research_operator_run":
        action_report = run_market_research_operator_live_action(
            user_text=user_text,
            metadata=meta,
            channel=channel,
            network_enabled=bool(network_enabled),
            web_search_fn=web_search_fn,
            open_page_fn=open_page_fn,
        )
        operator_run = (
            dict(action_report.get("stage214_market_research_operator_run", {}))
            if isinstance(action_report.get("stage214_market_research_operator_run", {}), dict)
            else {}
        )
        updates = _capability_updates_from_market_operator(action_report, operator_run) if operator_run else {}
        status = "executed" if str(action_report.get("status", "") or "") == "executed" else "failed"
        stop_reason = "final_answer_ready" if status == "executed" and str(operator_run.get("status", "") or "") == "ready" else "tool_failure_report"
        return sanitize_public_metadata(
            {
                "schema": OPERATOR_DISPATCH_SCHEMA,
                "dispatch_id": "stage217_dispatch:" + stable_digest(user_text, selected_action, action_report.get("operator_run_id", ""), limit=12),
                "status": status,
                "operator_id": selected_action,
                "selected_action": selected_action,
                "required_observation": str(definition.get("required_observation", "") or ""),
                "capability_context_updates": updates,
                "final_visible_text": str(action_report.get("final_visible_text", "") or operator_run.get("final_visible_text", "") or ""),
                "canonical_stop_reason": stop_reason,
                "failure_reasons": list(action_report.get("failure_reasons", []) or operator_run.get("failure_reasons", []) or []),
                "created_at": utc_now(),
            }
        )

    if selected_action == "web_research_operator_run":
        operator_run = run_web_research_operator(
            user_text=user_text,
            action_arguments=action_args,
            network_enabled=bool(network_enabled),
            web_search_fn=web_search_fn,
            open_page_fn=open_page_fn,
        )
        updates = _capability_updates_from_web_research_operator(operator_run)
        run_status = str(operator_run.get("status", "") or "")
        status = "executed" if run_status == "ready" else "failed"
        stop_reason = str(operator_run.get("canonical_stop_reason", "") or "")
        if not stop_reason:
            stop_reason = "final_answer_ready" if status == "executed" else "tool_failure_report"
        return sanitize_public_metadata(
            {
                "schema": OPERATOR_DISPATCH_SCHEMA,
                "dispatch_id": "stage217_dispatch:" + stable_digest(user_text, selected_action, operator_run.get("operator_run_id", ""), limit=12),
                "status": status,
                "operator_id": selected_action,
                "selected_action": selected_action,
                "required_observation": str(definition.get("required_observation", "") or ""),
                "capability_context_updates": updates,
                "final_visible_text": str(operator_run.get("final_visible_text", "") or ""),
                "canonical_stop_reason": stop_reason,
                "failure_reasons": list(operator_run.get("failure_reasons", []) or []),
                "created_at": utc_now(),
            }
        )

    return _rejected(selected_action, "operator_dispatch_not_implemented")
