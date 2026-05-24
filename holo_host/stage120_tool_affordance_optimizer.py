from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from .stage106_deepseek_tool_adapter import STAGE119_DEFAULT_TOOL_NAMES

STAGE120_SCHEMA = "holo.stage120.tool_affordance_optimizer.v1"

STAGE120_DEFAULT_MAX_TOOLS = 18

STAGE120_BASELINE_TOOLS = (
    "memory_recall",
    "workspace_inspect",
    "external_lookup",
    "local_command",
    "command_run",
    "path_resolve",
)

STAGE120_GROUPS: dict[str, tuple[str, ...]] = {
    "memory": ("memory_recall", "memory_warehouse_search", "doc_lookup"),
    "workspace": ("workspace_inspect", "file_read", "file_search", "file_list", "file_stat", "symbol_search", "repo_overview"),
    "docs": ("doc_lookup", "markdown_outline", "file_read"),
    "external": ("external_lookup",),
    "git": ("git_status", "git_diff", "git_log", "git_inspect"),
    "tests": ("test_runner", "test_discover", "python_module_check"),
    "runtime": ("config_inspect", "runtime_health", "env_read", "dependency_check"),
    "artifacts": ("artifact_list", "workspace_snapshot"),
    "time": ("time_now",),
    "modify": ("file_write", "file_replace", "file_append", "note_append", "workspace_edit", "progress_note"),
}

STAGE120_GROUP_HINTS: dict[str, tuple[str, ...]] = {
    "memory": ("记忆", "回忆", "记得", "recall", "memory", "remember"),
    "workspace": ("代码", "文件", "仓库", "检查", "搜索", "workspace", "repo", "file", ".py", ".md"),
    "docs": ("文档", "说明", "publish", "发布", "doc", "markdown", ".md"),
    "git": ("git", "diff", "commit", "add", "status", "提交"),
    "tests": ("测试", "pytest", "test", "验证", "回归"),
    "runtime": ("配置", "环境", "依赖", "健康", "config", "runtime", "env", "dependency", "api key"),
    "artifacts": ("产物", "artifact", "可视化", "html", "workbench"),
    "time": ("时间", "现在几点", "today", "date", "time"),
    "modify": ("修改", "写入", "保存", "改进", "修复", "edit", "write", "patch", "fix"),
}

STAGE120_PERMISSIONED_TOOLS = {
    "workspace_edit",
    "progress_note",
    "file_write",
    "file_replace",
    "file_append",
    "note_append",
    "git_stage",
    "git_commit",
    "command_modify",
}


def _request_to_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        item = dict(raw)
    else:
        to_dict = getattr(raw, "to_dict", None)
        item = dict(to_dict()) if callable(to_dict) else {}
    name = str(item.get("name", "") or "").strip()
    if not name:
        return {}
    payload = item.get("payload", {})
    return {
        "name": name,
        "reason": str(item.get("reason", "") or ""),
        "payload": dict(payload) if isinstance(payload, dict) else {},
    }


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def _query_groups(query: str) -> list[str]:
    groups = [group for group, hints in STAGE120_GROUP_HINTS.items() if _contains_hint(query, hints)]
    if re.search(r"\b[a-zA-Z_][\w-]*\.(py|md|json|toml|txt)\b", query):
        if "workspace" not in groups:
            groups.append("workspace")
    return groups


def _grant_tools(permission_grants: Any) -> list[str]:
    names: list[str] = []
    for raw in list(permission_grants or []):
        if isinstance(raw, str):
            name = raw.strip()
        elif isinstance(raw, dict):
            name = str(raw.get("tool", "") or raw.get("name", "") or "").strip()
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names


def _append_tool(
    selected: "OrderedDict[str, dict[str, Any]]",
    source: dict[str, dict[str, Any]],
    name: str,
    *,
    reason: str,
    force_permissioned: bool = False,
) -> None:
    if not name or name not in STAGE119_DEFAULT_TOOL_NAMES or name in selected:
        return
    if name in STAGE120_PERMISSIONED_TOOLS and not force_permissioned:
        return
    item = dict(source.get(name, {})) if name in source else {"name": name, "payload": {}}
    item["name"] = name
    item.setdefault("payload", {})
    if not str(item.get("reason", "") or "").strip():
        item["reason"] = reason
    selected[name] = item


def optimize_stage120_tool_requests(
    tool_requests: Any,
    *,
    query: str,
    permission_grants: Any = None,
    tool_scope: str = "",
    max_tools: int = STAGE120_DEFAULT_MAX_TOOLS,
    tool_need: Any = None,
) -> list[dict[str, Any]]:
    source: dict[str, dict[str, Any]] = {}
    explicit_names: list[str] = []
    for raw in list(tool_requests or []):
        item = _request_to_dict(raw)
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        if name not in source:
            source[name] = item
            explicit_names.append(name)

    selected: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    scope = str(tool_scope or "").strip().lower()
    grant_names = _grant_tools(permission_grants)
    if scope == "full":
        for name in explicit_names:
            _append_tool(selected, source, name, reason="explicit_tool_request", force_permissioned=True)
        for name in STAGE119_DEFAULT_TOOL_NAMES:
            _append_tool(selected, source, name, reason="stage120_full_tool_scope", force_permissioned=True)
        return list(selected.values())

    for name in explicit_names:
        _append_tool(
            selected,
            source,
            name,
            reason="explicit_tool_request",
            force_permissioned=name in grant_names,
        )

    for name in STAGE120_BASELINE_TOOLS:
        _append_tool(selected, source, name, reason="stage120_baseline_tool")

    groups = _query_groups(query)
    if isinstance(tool_need, dict):
        for group in list(tool_need.get("tool_groups", []) or []):
            group_name = str(group or "").strip()
            if group_name == "external_lookup":
                group_name = "external"
            if group_name == "external":
                if "external" not in groups:
                    groups.append("external")
                continue
            if group_name in STAGE120_GROUPS and group_name not in groups:
                groups.append(group_name)
    if not groups:
        groups = ["memory"]
    for group in groups:
        for name in STAGE120_GROUPS.get(group, ()):
            _append_tool(
                selected,
                source,
                name,
                reason=f"stage120_topic_group:{group}",
                force_permissioned=name in grant_names,
            )

    for name in grant_names:
        _append_tool(selected, source, name, reason="stage120_permission_grant", force_permissioned=True)
        if name == "command_modify":
            _append_tool(selected, source, "git_status", reason="stage120_permission_grant_context")

    max_count = max(6, min(int(max_tools or STAGE120_DEFAULT_MAX_TOOLS), len(STAGE119_DEFAULT_TOOL_NAMES)))
    if len(selected) <= max_count:
        return list(selected.values())

    protected_explicit = {
        name
        for name in explicit_names
        if str(source.get(name, {}).get("reason", "") or "").strip().lower() not in {"library", "stage119_library"}
    }
    priority_order: list[str] = []
    for name in explicit_names:
        if name in protected_explicit and name not in priority_order:
            priority_order.append(name)
    for name in grant_names:
        if name not in priority_order:
            priority_order.append(name)
    for name in STAGE120_BASELINE_TOOLS:
        if name not in priority_order:
            priority_order.append(name)
    topic_priority = set(STAGE120_BASELINE_TOOLS).union(grant_names).union(protected_explicit)
    for group in groups:
        for name in STAGE120_GROUPS.get(group, ()):
            topic_priority.add(name)
            if name not in priority_order:
                priority_order.append(name)
    protected = topic_priority
    kept: list[dict[str, Any]] = []
    for name in priority_order:
        if name in selected:
            kept.append(selected[name])
    kept_names = {str(item.get("name", "") or "") for item in kept}
    overflow: list[dict[str, Any]] = []
    for name, item in selected.items():
        if name in kept_names:
            continue
        if name not in protected:
            overflow.append(item)
        else:
            kept.append(item)
            kept_names.add(name)
    return (kept + overflow)[:max_count]


def build_stage120_tool_affordance_report(
    tool_requests: Any,
    *,
    query: str,
    permission_grants: Any = None,
    tool_scope: str = "",
    max_tools: int = STAGE120_DEFAULT_MAX_TOOLS,
    tool_need: Any = None,
) -> dict[str, Any]:
    selected = optimize_stage120_tool_requests(
        tool_requests,
        query=query,
        permission_grants=permission_grants,
        tool_scope=tool_scope,
        max_tools=max_tools,
        tool_need=tool_need,
    )
    return {
        "schema": STAGE120_SCHEMA,
        "stage": 120,
        "query": str(query or ""),
        "library_tool_count": len(STAGE119_DEFAULT_TOOL_NAMES),
        "selected_tool_count": len(selected),
        "selected_tools": [str(item.get("name", "") or "") for item in selected],
        "query_groups": _query_groups(query),
        "tool_need": dict(tool_need or {}) if isinstance(tool_need, dict) else {},
        "tool_scope": str(tool_scope or "bounded"),
        "permission_grants": list(permission_grants or []),
    }
