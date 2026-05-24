from __future__ import annotations

import re
from typing import Any

TOOL_NEED_SCHEMA = "holo.tool_need.v1"

GROUP_PATTERNS: dict[str, tuple[str, ...]] = {
    "memory": (r"\brecall\b", r"\bremember\b", r"\bmemory\b", r"回忆", r"记忆", r"记得"),
    "workspace": (
        r"\bread\b.*\b(directory|folder|file|repo|workspace)",
        r"\binspect\b.*\b(directory|folder|file|repo|workspace)",
        r"\byour own directory\b",
        r"\bproject directory\b",
        r"\bworkspace\b",
        r"\brepo\b",
        r"\bfile\b",
        r"目录",
        r"文件",
        r"仓库",
        r"项目",
    ),
    "docs": (r"\bdocs?\b", r"\bmarkdown\b", r"\bpublish\b", r"文档", r"发布"),
    "git": (r"\bgit\b", r"\bdiff\b", r"\bcommit\b", r"\bstatus\b", r"提交", r"差异"),
    "tests": (r"\bpytest\b", r"\btests?\b", r"\btest runner\b", r"测试", r"验证"),
    "external_lookup": (r"\bsearch\b", r"\blook up\b", r"\blatest\b", r"\bpaper\b", r"\bweb\b", r"\binternet\b", r"搜索", r"论文", r"最新", r"联网", r"上网"),
    "runtime": (r"\bconfig\b", r"\bruntime\b", r"\benv\b", r"\bhealth\b", r"配置", r"运行", r"环境"),
    "artifacts": (r"\bartifact\b", r"\bhtml\b", r"\bvisual", r"产物", r"可视化"),
    "time": (r"\btime\b", r"\btoday\b", r"\bdate\b", r"时间", r"今天"),
}

MUTATION_PATTERNS = (
    r"\bwrite\b",
    r"\bedit\b",
    r"\bmodify\b",
    r"\bpatch\b",
    r"\bfix\b",
    r"\bcommit\b",
    r"\bgit add\b",
    r"\brun\b.*\binstall\b",
    r"写入",
    r"修改",
    r"修复",
    r"提交",
)


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def classify_tool_need(query: Any) -> dict[str, Any]:
    text = str(query or "")
    groups = [group for group, patterns in GROUP_PATTERNS.items() if _matches(text, patterns)]
    needs_mutation = _matches(text, MUTATION_PATTERNS)
    if needs_mutation and "git" not in groups and re.search(r"\bcommit\b|提交", text, flags=re.IGNORECASE):
        groups.append("git")
    if needs_mutation and "workspace" not in groups and re.search(r"\b(write|edit|modify|patch|fix)\b|写入|修改|修复", text, flags=re.IGNORECASE):
        groups.append("workspace")
    ordered = [group for group in GROUP_PATTERNS.keys() if group in set(groups)]
    return {
        "schema": TOOL_NEED_SCHEMA,
        "query": text,
        "needs_tool": bool(ordered or needs_mutation),
        "needs_memory": "memory" in ordered,
        "needs_workspace": "workspace" in ordered,
        "needs_docs": "docs" in ordered,
        "needs_git": "git" in ordered,
        "needs_tests": "tests" in ordered,
        "needs_external_lookup": "external_lookup" in ordered,
        "needs_runtime": "runtime" in ordered,
        "needs_artifacts": "artifacts" in ordered,
        "needs_time": "time" in ordered,
        "needs_mutation_permission": bool(needs_mutation),
        "tool_groups": ordered,
    }
