from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .common import utc_now
from .context_compiler import compile_context_memory
from .domain_modules import get_domain_module_registry
from .agent_event_stream import build_agent_event_stream
from .holo_core_bench import evaluate_holo_core_fixture
from .kernel_metadata_sanitizer import assert_no_private_reasoning, build_public_stage152_report
from .project_state_graph import ProjectStateGraph
from .safe_command_policy import parse_allowed_command

AGENT_KERNEL_READINESS_SCHEMA = "holo.stage158.agent_kernel_readiness.v1"
KERNEL_HARDENING_SCHEMA = "holo.stage159.kernel_hardening.v1"
READINESS_PROBE_SCHEMA = "holo.stage159.readiness_probe.v1"

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

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _probe_interactive_cli() -> tuple[bool, str]:
    stream = build_agent_event_stream(
        {
            "text": "ready",
            "stage152_deepseek_tool_loop": {
                "messages": [{"role": "assistant", "reasoning_content": "secret"}],
                "stop_reason": "no_tool_calls",
            },
        },
        user_text="probe",
        thread_key="holo_cli:readiness",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    ok, paths = assert_no_private_reasoning(stream)
    return ok and bool(stream.get("events")), "active event stream rendered without private reasoning" if ok else f"private paths={paths}"


def _probe_tool_loop() -> tuple[bool, str]:
    public = build_public_stage152_report(
        {
            "schema": "holo.stage152.deepseek_tool_loop.v1",
            "messages": [{"role": "assistant", "reasoning_content": "secret"}],
            "assistant_messages_internal": [{"reasoning_content": "secret"}],
            "tool_call_count": 1,
            "stop_reason": "model_final_no_tool_calls",
            "reasoning_content_retained_count": 1,
        }
    )
    ok, paths = assert_no_private_reasoning(public)
    return ok and public.get("tool_call_count") == 1, "active Stage152 sanitizer probe" if ok else f"private paths={paths}"


def _probe_engineering_actions() -> tuple[bool, str]:
    argv, reason = parse_allowed_command("python -m pytest tests/test_stage158_agent_kernel.py -q", repo_root=_repo_root())
    rejected, reject_reason = parse_allowed_command("python -m pip install requests", repo_root=_repo_root())
    ok = bool(argv) and not reason and not rejected and reject_reason == "command_not_allowlisted"
    return ok, "active safe-command allowlist probe; no shell execution"


def _probe_project_state() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        graph = ProjectStateGraph(Path(tmpdir) / "project_state.sqlite3")
        try:
            graph.upsert_node("Holo", "Project", "Holo")
            graph.upsert_node("Holo", "Task", "Readiness probe task", status="active")
            graph.upsert_node("Holo", "NextAction", "Keep domain modules scaffold-only", status="open")
            state = graph.get_project_state("Holo")
        finally:
            graph.close()
    ok = bool(state.get("active_tasks")) and bool(state.get("next_actions"))
    return ok, "active in-memory project-state CRUD probe"


def _probe_context_compiler() -> tuple[bool, str]:
    request = "Preserve this exact readiness request."
    report = compile_context_memory(
        {
            "working_context_packet": {
                "user_goal": {"current_user_request_exact": request},
                "directive_state": {"hard_directives": ["do not use emoji"]},
            }
        },
        current_user_request=request,
    )
    ok = report.get("current_user_request_exact") == request and "do not use emoji" in str(report.get("directive_block", "")).lower()
    return ok, "active context compiler probe preserves exact request and directive"


def _probe_core_bench() -> tuple[bool, str]:
    row = evaluate_holo_core_fixture(
        {
            "fixture_id": "readiness-core-bench",
            "category_id": "directive_adherence",
            "input": "Avoid emoji.",
            "visible_text": "Understood.",
            "directives": ["no emoji"],
            "metadata": {},
        }
    )
    return row.get("status") == "passed", "active in-memory HoloCoreBench fixture evaluator"


def _probe_public_hygiene() -> tuple[bool, str]:
    script = _repo_root() / "scripts" / "check_public_release_hygiene.py"
    return script.exists(), "scripts/check_public_release_hygiene.py available for optional invocation"


def _probe_domain_scaffold() -> tuple[bool, str]:
    registry = get_domain_module_registry()
    required = {"math_research", "physics_research", "market_research", "projecth_ops"}
    scaffold_only = all(module.get("implements_live_work") is False and module.get("status") == "scaffold_only" for module in registry.values())
    return required.issubset(registry) and scaffold_only, f"domain modules={','.join(sorted(registry))}; scaffold_only={scaffold_only}"


_ACTIVE_PROBES = {
    "interactive_cli_available": _probe_interactive_cli,
    "tool_loop_available": _probe_tool_loop,
    "engineering_actions_available": _probe_engineering_actions,
    "project_state_available": _probe_project_state,
    "context_compiler_available": _probe_context_compiler,
    "core_bench_available": _probe_core_bench,
    "public_hygiene_passed_marker": _probe_public_hygiene,
    "domain_scaffold_available": _probe_domain_scaffold,
}


def _check_value(check_id: str, overrides: dict[str, bool]) -> tuple[bool, str, str]:
    if check_id in overrides:
        if check_id == "public_hygiene_passed_marker":
            return bool(overrides[check_id]), "mocked dependency override; scripts/check_public_release_hygiene.py available", "mocked"
        return bool(overrides[check_id]), "mocked dependency override", "mocked"
    probe = _ACTIVE_PROBES.get(check_id)
    if probe is None:
        return False, "unknown readiness check", "active"
    try:
        passed, details = probe()
    except Exception as exc:  # pragma: no cover - defensive reporting path
        return False, f"active probe error: {exc}", "active"
    return bool(passed), details, "active"


def build_agent_kernel_readiness_report(
    *,
    dependency_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    overrides = dict(dependency_overrides or {})
    checks: list[dict[str, Any]] = []
    for check_id in REQUIRED_KERNEL_CHECKS:
        passed, details, probe_type = _check_value(check_id, overrides)
        checks.append(
            {
                "schema": READINESS_PROBE_SCHEMA,
                "probe_schema": READINESS_PROBE_SCHEMA,
                "check_id": check_id,
                "passed": bool(passed),
                "status": "pass" if passed else "fail",
                "details": details,
                "probe_type": probe_type,
            }
        )
    missing = [item["check_id"] for item in checks if not item["passed"]]
    warnings = [item["check_id"] for item in checks if item["probe_type"] == "mocked"]
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
            "warning_count": len(warnings),
        },
        "failed_count": len(missing),
        "warning_count": len(warnings),
        "domain_modules": sorted(domain_registry),
        "kernel_hardening": {
            "schema": KERNEL_HARDENING_SCHEMA,
            "status": "failed" if missing else "passed",
            "active_probe_count": sum(1 for item in checks if item["probe_type"] == "active"),
            "mocked_probe_count": len(warnings),
        },
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
