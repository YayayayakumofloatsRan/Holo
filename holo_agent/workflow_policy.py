from __future__ import annotations

import re
from typing import Any


ENGINEERING_TERMS = (
    "patch",
    "modify",
    "edit",
    "change",
    "fix",
    "test",
    "pytest",
    "diff",
    "git",
    "read",
    "file",
    "workspace",
    "repo",
    "修改",
    "修复",
    "测试",
    "读取",
    "文件",
)


def build_workflow_policy(user_text: str) -> dict[str, Any]:
    text = str(user_text or "").lower()
    is_engineering = any(term in text for term in ENGINEERING_TERMS)
    if not is_engineering:
        return {
            "task_family": "general",
            "required_order": ["answer_direct"],
            "final_answer_rules": ["Ground final claims in observations."],
        }
    return {
        "task_family": "engineering_change",
        "required_order": ["workspace_search", "file_read", "apply_patch", "test_run", "git_diff", "git_status", "answer_direct"],
        "final_answer_rules": [
            "Inspect/search before reading specific files.",
            "Read files before patching them.",
            "Run relevant tests after patching when tests are available.",
            "Inspect git diff/status before handoff.",
            "Do not finalize patch/test claims without matching observations.",
        ],
    }


def verify_engineering_final(text: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    lowered = str(text or "").lower()
    observed_tools = {str(obs.get("tool", "")) for obs in observations if str(obs.get("status", "")) == "ok"}
    missing: list[str] = []

    if re.search(r"\b(read|opened|inspected)\b|读取|查看", lowered) and "file_read" not in observed_tools and "open_page" not in observed_tools:
        missing.append("file_read")
    if re.search(r"\b(patched|modified|changed|edited|fixed)\b|已修改|已修复|补丁", lowered) and "apply_patch" not in observed_tools:
        missing.append("apply_patch")
    if re.search(r"\btests? (passed|pass)|pytest passed|测试通过", lowered) and "test_run" not in observed_tools:
        missing.append("test_run")
    if re.search(r"\bdiff\b|git status|工作区|变更", lowered) and not ({"git_diff", "git_status"} & observed_tools):
        missing.append("git_diff/git_status")

    return {
        "status": "ok" if not missing else "unverified_engineering_claim",
        "missing_observations": sorted(set(missing)),
        "observed_tools": sorted(observed_tools),
    }


def repair_unverified_engineering_final(text: str, report: dict[str, Any]) -> str:
    missing = ", ".join(report.get("missing_observations", []))
    return f"Unverified engineering claim: missing observation ledger for {missing}. I cannot state those engineering results as completed."
