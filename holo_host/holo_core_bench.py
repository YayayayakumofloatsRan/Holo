from __future__ import annotations

import importlib.util
from typing import Any

from .common import utc_now

HOLO_CORE_BENCH_SCHEMA = "holo.stage157.core_bench.v1"

_BENCH_CATEGORIES = (
    ("interactive_cli", "holo_host.interactive_cli", "Inspectable interactive CLI session surface"),
    ("tool_loop", "holo_host.stage152_deepseek_tool_loop", "Native tool-loop metadata and trace surface"),
    ("engineering_actions", "holo_host.engineering_action_fabric", "Workspace-scoped engineering action ledger"),
    ("project_state", "holo_host.project_state_graph", "Typed project continuity graph"),
    ("context_compiler", "holo_host.context_compiler", "Stable-prefix and dynamic-suffix context compiler"),
    ("domain_scaffold", "holo_host.domain_modules", "Domain-module scaffold registry"),
)


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def run_holo_core_bench(*, dry_run: bool = True, dependency_overrides: dict[str, bool] | None = None) -> dict[str, Any]:
    """Run a deterministic readiness-style core bench.

    The bench is intentionally local and dry-run by default. It does not call
    providers, execute tools, write memory, or start transports.
    """

    overrides = dict(dependency_overrides or {})
    categories: list[dict[str, Any]] = []
    for category_id, module_name, description in _BENCH_CATEGORIES:
        available = bool(overrides.get(category_id, _module_available(module_name)))
        categories.append(
            {
                "category_id": category_id,
                "module": module_name,
                "description": description,
                "status": "passed" if available else "failed",
                "score": 1.0 if available else 0.0,
                "dry_run": bool(dry_run),
            }
        )
    failed = [item["category_id"] for item in categories if item["status"] != "passed"]
    return {
        "schema": HOLO_CORE_BENCH_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "failed" if failed else "passed",
        "categories": categories,
        "summary": {
            "category_count": len(categories),
            "passed_count": len(categories) - len(failed),
            "failed_count": len(failed),
        },
        "failed_categories": failed,
        "authority_boundary": {
            "provider_calls": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
        },
    }


def render_holo_core_bench(report: dict[str, Any]) -> str:
    lines = ["Stage157 Holo Core Bench", f"status={report.get('status', 'unknown')}"]
    for item in report.get("categories", []) if isinstance(report.get("categories"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('category_id')}: {item.get('status')} score={item.get('score')}")
    return "\n".join(lines)
