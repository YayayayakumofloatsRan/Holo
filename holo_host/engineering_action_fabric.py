from __future__ import annotations

import re
import json
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .engineering_workspace_tools import ENGINEERING_ACTION_SCHEMA

ENGINEERING_VERIFICATION_SCHEMA = "holo.stage154.engineering_verification_ledger.v1"

_READ_PATTERNS = (
    "i read",
    "i checked",
    "i inspected",
    "i opened",
    "read the file",
    "read file",
    "checked the file",
    "inspected the file",
    "读了",
    "看了",
    "检查了",
)
_PATCH_PATTERNS = (
    "i patched",
    "patched",
    "applied patch",
    "i edited",
    "edited",
    "modified",
    "changed the file",
    "updated the file",
    "改了",
    "修改了",
    "补丁",
)
_TEST_PATTERNS = (
    "tests passed",
    "test passed",
    "pytest passed",
    "all tests pass",
    "verified by tests",
    "测试通过",
    "pytest 通过",
)
_DIFF_PATTERNS = (
    "diff clean",
    "checked the diff",
    "git status",
    "working tree clean",
    "no diff",
    "diff 已检查",
    "状态干净",
)
_SEARCH_PATTERNS = (
    "i searched",
    "searched the repo",
    "workspace search",
    "grep",
    "rg",
    "搜了",
    "搜索了",
)


def _compact(value: Any, limit: int = 280) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def normalize_engineering_action_ledger(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_list_dicts(value)):
        action_type = str(item.get("action_type", "") or "").strip()
        if not action_type:
            continue
        status = str(item.get("status", "") or "unknown")
        row = {
            "schema": ENGINEERING_ACTION_SCHEMA,
            "action_id": str(
                item.get("action_id", "")
                or "eng:" + stable_digest(action_type, str(index), json.dumps(item, ensure_ascii=False, sort_keys=True), limit=12)
            ),
            "action_type": action_type,
            "input": dict(item.get("input", {})) if isinstance(item.get("input", {}), dict) else {},
            "status": status,
            "stdout_summary": _compact(item.get("stdout_summary", "")),
            "stderr_summary": _compact(item.get("stderr_summary", "")),
            "files_read": [str(x) for x in list(item.get("files_read", []) or []) if str(x).strip()],
            "files_changed": [str(x) for x in list(item.get("files_changed", []) or []) if str(x).strip()],
            "commands_run": [str(x) for x in list(item.get("commands_run", []) or []) if str(x).strip()],
            "tests_run": [str(x) for x in list(item.get("tests_run", []) or []) if str(x).strip()],
            "duration_ms": int(item.get("duration_ms", 0) or 0),
            "observed_at": str(item.get("observed_at", "") or utc_now()),
        }
        rows.append(row)
    return rows


def engineering_ledger_to_tool_observations(ledger: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in normalize_engineering_action_ledger(ledger):
        status = str(item.get("status", "") or "unknown")
        action_type = str(item.get("action_type", "") or "engineering")
        summary_parts = [
            f"{action_type} {status}",
            str(item.get("stdout_summary", "") or ""),
            str(item.get("stderr_summary", "") or ""),
        ]
        tags = ["engineering", action_type]
        if status == "ok":
            if action_type in {"file_read", "workspace_search"}:
                tags.append("read")
            if action_type == "apply_patch":
                tags.append("patch")
            if action_type == "test_run":
                tags.append("test")
            if action_type in {"git_status", "git_diff"}:
                tags.append("diff")
        rows.append(
            {
                "provider_call_id": str(item.get("action_id", "")),
                "tool": action_type,
                "status": status,
                "summary": _compact("; ".join(part for part in summary_parts if part), 420),
                "data_keys": ["files_read", "files_changed", "commands_run", "tests_run"],
                "grounding_tags": tags if status == "ok" else ["engineering"],
                "confidence": 0.95 if status == "ok" else 0.35,
            }
        )
    return rows


def _has_ok_action(rows: list[dict[str, Any]], action_types: set[str], *, require_payload: str | None = None) -> bool:
    for row in rows:
        if str(row.get("status", "") or "") != "ok":
            continue
        if str(row.get("action_type", "") or "") not in action_types:
            continue
        if require_payload and not list(row.get(require_payload, []) or []):
            continue
        return True
    return False


def _claim_families(text: str) -> list[str]:
    lowered = str(text or "").lower()
    families: list[str] = []
    if any(pattern in lowered for pattern in _READ_PATTERNS):
        families.append("read")
    if any(pattern in lowered for pattern in _PATCH_PATTERNS):
        families.append("patch")
    if any(pattern in lowered for pattern in _TEST_PATTERNS):
        families.append("test")
    if any(pattern in lowered for pattern in _DIFF_PATTERNS):
        families.append("diff")
    if any(pattern in lowered for pattern in _SEARCH_PATTERNS):
        families.append("search")
    return sorted(dict.fromkeys(families))


def evaluate_engineering_claim_grounding(text: str, engineering_action_ledger: Any) -> dict[str, Any]:
    rows = normalize_engineering_action_ledger(engineering_action_ledger)
    families = _claim_families(text)
    support = {
        "read": _has_ok_action(rows, {"file_read"}, require_payload="files_read"),
        "search": _has_ok_action(rows, {"workspace_search"}, require_payload="files_read"),
        "patch": _has_ok_action(rows, {"apply_patch"}, require_payload="files_changed"),
        "test": _has_ok_action(rows, {"test_run"}, require_payload="tests_run"),
        "diff": _has_ok_action(rows, {"git_status", "git_diff"}),
    }
    claims: list[dict[str, Any]] = []
    missing: list[str] = []
    for family in families:
        evidence_ids = [
            str(row.get("action_id", ""))
            for row in rows
            if str(row.get("status", "") or "") == "ok"
            and (
                (family == "read" and str(row.get("action_type", "")) == "file_read")
                or (family == "search" and str(row.get("action_type", "")) == "workspace_search")
                or (family == "patch" and str(row.get("action_type", "")) == "apply_patch")
                or (family == "test" and str(row.get("action_type", "")) == "test_run")
                or (family == "diff" and str(row.get("action_type", "")) in {"git_status", "git_diff"})
            )
        ]
        grounded = bool(support.get(family, False))
        if not grounded:
            missing.append(family)
        claims.append(
            {
                "claim_family": family,
                "status": "grounded" if grounded else "unverified",
                "evidence_ids": evidence_ids,
            }
        )
    status = "no_engineering_claim" if not families else "grounded" if not missing else "unverified_engineering_claim"
    return {
        "schema": ENGINEERING_VERIFICATION_SCHEMA,
        "status": status,
        "claim_count": len(families),
        "grounded_claim_count": sum(1 for item in claims if item["status"] == "grounded"),
        "unverified_claim_count": len(missing),
        "missing_families": sorted(set(missing)),
        "claims": claims,
        "ledger_count": len(rows),
        "repair_required": bool(missing),
        "repair_reason": "engineering claim lacks matching action ledger" if missing else "",
    }


def repair_engineering_claims(text: str, grounding_report: dict[str, Any] | None, *, channel: str = "") -> str:
    report = grounding_report if isinstance(grounding_report, dict) else {}
    missing = [str(item) for item in list(report.get("missing_families", []) or [])]
    if not missing:
        return str(text or "")
    if str(channel or "").lower() in {"wechat", "wechat_group"}:
        return "我没有足够的工程动作记录来确认刚才那个读文件、改动或测试结论。"
    return "I do not have matching engineering action evidence for that exact read/patch/test/diff claim, so I should treat it as unverified."


def build_engineering_action_fabric(ledger: Any, *, claim_text: str = "") -> dict[str, Any]:
    rows = normalize_engineering_action_ledger(ledger)
    grounding = evaluate_engineering_claim_grounding(claim_text, rows)
    return {
        "schema": "holo.stage154.engineering_action_fabric.v1",
        "status": "recorded" if rows else "empty",
        "action_count": len(rows),
        "actions": rows,
        "verification": grounding,
        "destructive_actions_allowed": False,
        "approval_ui_added": False,
        "provider_call_added": False,
        "transport_authority_widened": False,
    }
