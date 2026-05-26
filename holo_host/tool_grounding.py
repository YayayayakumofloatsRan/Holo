from __future__ import annotations

import re
from typing import Any

TOOL_GROUNDING_SCHEMA = "holo.tool_grounding.v1"

TOOL_FAMILY_TAGS: dict[str, tuple[str, ...]] = {
    "memory_recall": ("memory",),
    "memory_warehouse_search": ("memory",),
    "external_lookup": ("external_lookup", "current_fact"),
    "web_search": ("external_lookup", "current_fact"),
    "open_page": ("external_lookup", "current_fact"),
    "find_in_page": ("external_lookup", "current_fact"),
    "web_preview": ("external_lookup", "current_fact"),
    "workspace_inspect": ("workspace",),
    "file_read": ("workspace",),
    "file_list": ("workspace",),
    "file_search": ("workspace",),
    "file_stat": ("workspace",),
    "directory_tree": ("workspace",),
    "json_read": ("workspace",),
    "toml_read": ("workspace",),
    "markdown_outline": ("workspace", "docs"),
    "symbol_search": ("workspace",),
    "repo_overview": ("workspace", "git"),
    "doc_lookup": ("docs",),
    "artifact_list": ("workspace", "artifacts"),
    "workspace_snapshot": ("workspace",),
    "path_resolve": ("workspace",),
    "git_inspect": ("git",),
    "git_status": ("git",),
    "git_diff": ("git",),
    "git_log": ("git",),
    "test_runner": ("tests",),
    "test_discover": ("tests",),
    "python_module_check": ("tests", "workspace"),
    "local_command": ("command",),
    "command_run": ("command",),
    "config_inspect": ("runtime",),
    "runtime_health": ("runtime",),
    "env_read": ("runtime",),
    "dependency_check": ("runtime",),
    "time_now": ("time",),
}

CLAIM_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("workspace", (r"\bchecked\b.*\b(project|workspace|repo|directory|file)", r"\bread\b.*\b(file|directory|repo|workspace)", r"\bproject directory\b", r"\bworkspace\b", r"\brepo\b", r"\bdocs?\b", r"检查.*(目录|文件|仓库|项目)", r"读.*(目录|文件|仓库)")),
    ("external_lookup", (r"\bsearched\b.*\b(web|internet|online|paper|latest)", r"\blooked up\b", r"\blatest\b", r"\bcurrent\b", r"上网", r"联网", r"搜索.*(论文|最新|网页)")),
    ("memory", (r"\brecall(?:ed)?\b", r"\bmemory\b", r"\bremember(?:ed)?\b", r"回忆", r"记忆", r"记得")),
    ("git", (r"\bgit\b", r"\bdiff\b", r"\bcommit\b", r"提交", r"差异")),
    ("tests", (r"\bpytest\b", r"\btests?\b", r"\btest run\b", r"测试", r"验证")),
    ("runtime", (r"\bconfig\b", r"\bruntime\b", r"\benv\b", r"\bhealth\b", r"配置", r"运行状态", r"环境")),
    ("command", (r"\bran\b.*\bcommand\b", r"\bcommand output\b", r"执行.*命令")),
)


def _compact(text: Any, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _tags_for_tool(tool: str, *, status: str) -> list[str]:
    if str(status or "").lower() in {"rejected", "skipped", "denied", "error", "failed", "unavailable", "planned", "empty"}:
        return []
    tags = TOOL_FAMILY_TAGS.get(str(tool or "").strip(), ())
    return sorted({str(tag) for tag in tags if str(tag).strip()})


def _preserve_live_lookup_fields(row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if str(row.get("tool", "") or "") != "external_lookup":
        return row
    for key in ("query", "results", "error", "source_urls", "fetched_at", "network_enabled", "reason"):
        if key in item:
            row[key] = item.get(key)
    return row


def _data_keys(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    return sorted(str(key) for key in data.keys())


def normalize_tool_observation_ledger(tool_report: Any) -> list[dict[str, Any]]:
    """Return a stable, low-cardinality ledger for provider-proposed tools.

    The ledger is the durable contract between local execution, follow-up
    provider packets, grounding checks, and topology visualization.
    """

    if isinstance(tool_report, list):
        rows = [dict(item) for item in tool_report if isinstance(item, dict)]
        return [
            _preserve_live_lookup_fields(
                {
                    "provider_call_id": str(item.get("provider_call_id", "") or ""),
                    "tool": str(item.get("tool", "") or ""),
                    "status": str(item.get("status", "") or ""),
                    "summary": _compact(item.get("summary", "")),
                    "data_keys": sorted(str(key) for key in list(item.get("data_keys", []) or [])),
                    "grounding_tags": sorted(str(tag) for tag in list(item.get("grounding_tags", []) or [])),
                },
                item,
            )
            for item in rows
        ]

    report = dict(tool_report or {}) if isinstance(tool_report, dict) else {}
    ledger: list[dict[str, Any]] = []
    for raw in list(report.get("observations", []) or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        tool = str(item.get("tool", "") or "")
        status = str(item.get("status", "") or "ok")
        data = item.get("data", {})
        ledger.append(
            _preserve_live_lookup_fields(
                {
                    "provider_call_id": str(item.get("provider_call_id", "") or ""),
                    "tool": tool,
                    "status": status,
                    "summary": _compact(item.get("summary", "")),
                    "data_keys": _data_keys(data),
                    "grounding_tags": _tags_for_tool(tool, status=status),
                },
                {**item, **(data if isinstance(data, dict) else {})},
            )
        )
    for raw in list(report.get("skipped", []) or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        reason = str(item.get("reason", "") or "not_executed")
        ledger.append(
            {
                "provider_call_id": str(item.get("provider_call_id", "") or ""),
                "tool": str(item.get("tool", "") or ""),
                "status": "rejected",
                "summary": _compact(item.get("summary", "") or f"tool rejected: {reason}"),
                "data_keys": ["reason"],
                "grounding_tags": [],
            }
        )
    return ledger


def _claimed_families(text: str) -> list[str]:
    lowered = str(text or "").lower()
    families: list[str] = []
    for family, patterns in CLAIM_PATTERNS:
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns):
            families.append(family)
    return sorted(set(families))


def _filter_generic_capability_mentions(text: str, families: list[str]) -> list[str]:
    """Avoid treating generic tool capability descriptions as executed-tool claims."""

    lowered = str(text or "").lower()
    execution_claim = bool(
        re.search(r"\b(i|we)\s+(checked|read|inspected|opened|ran|executed|called|used)\b", lowered)
        or re.search(r"\b(tool|command|pytest|git|workspace|runtime|config).{0,32}\b(returned|showed|reported|passed|failed)\b", lowered)
        or any(marker in str(text or "") for marker in ("我检查", "我读取", "我执行", "我运行", "我调用", "已经执行", "已经运行", "测试通过"))
    )
    if execution_claim:
        return families
    generic_only = {"workspace", "git", "tests", "runtime", "command"}
    return [family for family in families if family not in generic_only]


def evaluate_tool_grounding(text: str, ledger: Any) -> dict[str, Any]:
    normalized = normalize_tool_observation_ledger(ledger)
    observed: set[str] = set()
    for item in normalized:
        if str(item.get("status", "") or "").lower() in {"rejected", "skipped", "denied"}:
            continue
        observed.update(str(tag) for tag in list(item.get("grounding_tags", []) or []) if str(tag).strip())
    claimed = _filter_generic_capability_mentions(text, _claimed_families(text))
    missing = [family for family in claimed if family not in observed]
    return {
        "schema": TOOL_GROUNDING_SCHEMA,
        "status": "ungrounded_tool_claim" if missing else "grounded",
        "claimed_families": claimed,
        "observed_families": sorted(observed),
        "missing_families": missing,
        "ledger_count": len(normalized),
    }


def repair_ungrounded_tool_claims(text: str, grounding_report: dict[str, Any], *, channel: str = "") -> str:
    missing = [str(item) for item in list(grounding_report.get("missing_families", []) or []) if str(item).strip()]
    if not missing:
        return str(text or "")
    prefix = "Tool check not executed"
    if str(channel or "").startswith("wechat"):
        prefix = "Tool check not executed"
    return f"{prefix}: {', '.join(missing)}. {str(text or '').strip()}".strip()
