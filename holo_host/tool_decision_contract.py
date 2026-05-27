from __future__ import annotations

import re
from typing import Any

from .tool_action_space import action_space_index, build_tool_action_space

TOOL_DECISION_CONTRACT_SCHEMA = "holo.stage161.tool_decision_contract.v1"

_WEB_CLAIM_RE = re.compile(r"(searched|looked up|latest|current|as of today|official|web|online|\u641c\u7d22|\u8054\u7f51|\u6700\u65b0|\u5b98\u65b9|\u5b98\u7f51)")
_MEMORY_CLAIM_RE = re.compile(r"(i remember|i recall|you told me before|you said before|we discussed|from memory|\u6211\u8bb0\u5f97|\u6211\u56de\u5fc6|\u4f60\u4e4b\u524d\u8bf4\u8fc7|\u6211\u4eec\u804a\u8fc7|\u4ece\u8bb0\u5fc6\u91cc)", re.IGNORECASE)
_ENGINEERING_CLAIM_RE = re.compile(r"(read file|patched|tests passed|test passed|diff clean|git status|\u5df2\u8bfb|\u5df2\u4fee\u6539|\u6d4b\u8bd5\u901a\u8fc7)")


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _has_successful_web(web_rows: Any) -> bool:
    return any(str(row.get("status", "") or "") == "ok" for row in _list_dicts(web_rows))


def _has_time(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("observed_at") or value.get("local_time") or value.get("utc_time"))


def _has_memory(rows: Any) -> bool:
    return any(str(row.get("status", "") or "") in {"grounded", "weak"} for row in _list_dicts(rows))


def _has_engineering(rows: Any) -> bool:
    return any(str(row.get("status", "") or "") in {"ok", "success", "passed"} for row in _list_dicts(rows))


def validate_tool_decision(
    decision: dict[str, Any],
    action_space: list[dict[str, Any]] | None = None,
    *,
    network_enabled: bool = True,
    workspace_enabled: bool = True,
) -> dict[str, Any]:
    index = action_space_index(action_space or build_tool_action_space())
    selected = str((decision or {}).get("selected_action", "") or "")
    if selected not in index:
        return {
            "schema": TOOL_DECISION_CONTRACT_SCHEMA,
            "status": "rejected",
            "selected_action": selected,
            "reason": "unknown_action",
            "missing_arguments": [],
        }
    action = index[selected]
    if action.get("requires_network") and not network_enabled:
        return {
            "schema": TOOL_DECISION_CONTRACT_SCHEMA,
            "status": "rejected",
            "selected_action": selected,
            "reason": "network_disabled",
            "missing_arguments": [],
        }
    if action.get("requires_workspace") and not workspace_enabled:
        return {
            "schema": TOOL_DECISION_CONTRACT_SCHEMA,
            "status": "rejected",
            "selected_action": selected,
            "reason": "workspace_unavailable",
            "missing_arguments": [],
        }
    args = dict((decision or {}).get("action_arguments", {}) or {})
    required = [str(item) for item in list(action.get("input_schema", {}).get("required", []) or [])]
    missing = [item for item in required if args.get(item) in (None, "")]
    if missing:
        return {
            "schema": TOOL_DECISION_CONTRACT_SCHEMA,
            "status": "rejected",
            "selected_action": selected,
            "reason": "missing_required_arguments",
            "missing_arguments": missing,
        }
    return {
        "schema": TOOL_DECISION_CONTRACT_SCHEMA,
        "status": "accepted",
        "selected_action": selected,
        "reason": "accepted",
        "missing_arguments": [],
    }


def validate_answer_direct_against_ledgers(
    text: str,
    decision: dict[str, Any] | None = None,
    *,
    web_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
    memory_observation_ledger: Any = None,
    engineering_action_ledger: Any = None,
) -> dict[str, Any]:
    body = str(text or "")
    lowered = body.lower()
    missing: list[str] = []
    if _WEB_CLAIM_RE.search(lowered) and not (_has_successful_web(web_observation_ledger) or _has_time(time_observation or {})):
        missing.append("web_observation_ledger")
    if _MEMORY_CLAIM_RE.search(body) and not _has_memory(memory_observation_ledger):
        missing.append("memory_observation_ledger")
    if _ENGINEERING_CLAIM_RE.search(lowered) and not _has_engineering(engineering_action_ledger):
        missing.append("engineering_action_ledger")
    return {
        "schema": TOOL_DECISION_CONTRACT_SCHEMA,
        "status": "blocked" if missing else "accepted",
        "selected_action": str((decision or {}).get("selected_action", "answer_direct") or "answer_direct"),
        "missing_ledgers": missing,
        "repair_required": bool(missing),
        "reason": "unsupported_visible_claim" if missing else "answer_direct_supported",
    }
