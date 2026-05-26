from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .common import utc_now
from .domain_modules import get_domain_module_registry

AGENT_KERNEL_READINESS_SCHEMA = "holo.stage158.agent_kernel_readiness.v1"

REQUIRED_KERNEL_CHECKS = (
    "interactive_cli_available",
    "tool_loop_available",
    "engineering_actions_available",
    "project_state_available",
    "context_compiler_available",
    "core_bench_available",
    "public_hygiene_passed_marker",
    "domain_scaffold_available",
)

_MODULE_CHECKS = {
    "interactive_cli_available": ("holo_host.interactive_cli", "InteractiveCliSession"),
    "tool_loop_available": ("holo_host.stage152_deepseek_tool_loop", "DeepSeek native tool loop"),
    "engineering_actions_available": ("holo_host.engineering_action_fabric", "engineering action ledger"),
    "project_state_available": ("holo_host.project_state_graph", "project state graph"),
    "context_compiler_available": ("holo_host.context_compiler", "Stage156 context compiler"),
    "core_bench_available": ("holo_host.holo_core_bench", "Stage157 core bench"),
}


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _check_value(check_id: str, overrides: dict[str, bool]) -> tuple[bool, str]:
    if check_id in overrides:
        if check_id == "public_hygiene_passed_marker":
            return bool(overrides[check_id]), "mocked dependency override; scripts/check_public_release_hygiene.py available"
        return bool(overrides[check_id]), "mocked dependency override"
    if check_id in _MODULE_CHECKS:
        module_name, description = _MODULE_CHECKS[check_id]
        return _module_available(module_name), f"{description}: {module_name}"
    if check_id == "domain_scaffold_available":
        registry = get_domain_module_registry()
        required = {"math_research", "physics_research", "market_research", "projecth_ops"}
        return required.issubset(registry), f"domain modules={','.join(sorted(registry))}"
    if check_id == "public_hygiene_passed_marker":
        script = _repo_root() / "scripts" / "check_public_release_hygiene.py"
        return script.exists(), "scripts/check_public_release_hygiene.py available"
    return False, "unknown readiness check"


def build_agent_kernel_readiness_report(
    *,
    dependency_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    overrides = dict(dependency_overrides or {})
    checks: list[dict[str, Any]] = []
    for check_id in REQUIRED_KERNEL_CHECKS:
        passed, details = _check_value(check_id, overrides)
        checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "status": "pass" if passed else "fail",
                "details": details,
            }
        )
    missing = [item["check_id"] for item in checks if not item["passed"]]
    domain_registry = get_domain_module_registry()
    return {
        "schema": AGENT_KERNEL_READINESS_SCHEMA,
        "target_milestone": "stage158-agent-kernel-v1",
        "generated_at": utc_now(),
        "status": "failed" if missing else "passed",
        "checks": checks,
        "checks_by_id": {item["check_id"]: item for item in checks},
        "missing": missing,
        "summary": {
            "total_count": len(checks),
            "passed_count": len(checks) - len(missing),
            "failed_count": len(missing),
        },
        "domain_modules": sorted(domain_registry),
        "authority_boundary": {
            "provider_calls": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_widening": False,
            "domain_live_work": False,
        },
    }


def render_agent_kernel_readiness(report: dict[str, Any]) -> str:
    lines = [
        "Stage158 Agent Kernel Readiness",
        f"status={report.get('status', 'unknown')}",
        f"passed={report.get('summary', {}).get('passed_count', 0)}/{report.get('summary', {}).get('total_count', 0)}",
    ]
    for item in report.get("checks", []) if isinstance(report.get("checks"), list) else []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('check_id')}: {item.get('status')} ({item.get('details')})")
    return "\n".join(lines)
