from __future__ import annotations

import io
import json
from pathlib import Path
from unittest import mock

from holo_host import cli
from holo_host.agent_kernel_readiness import (
    AGENT_KERNEL_READINESS_SCHEMA,
    REQUIRED_KERNEL_CHECKS,
    build_agent_kernel_readiness_report,
)
from holo_host.domain_modules import DOMAIN_MODULE_SCHEMA, get_domain_module_registry


def test_domain_module_registry_loads_scaffolds() -> None:
    registry = get_domain_module_registry()

    assert set(registry) >= {"math_research", "physics_research", "market_research", "projecth_ops"}
    assert all(module["schema"] == DOMAIN_MODULE_SCHEMA for module in registry.values())


def test_each_scaffold_has_instruction_memory_tool_and_bench_fields() -> None:
    required = {
        "module_id",
        "module_name",
        "instruction_scope",
        "memory_schema",
        "tool_requirements",
        "bench_categories",
        "report_templates",
        "risk_boundaries",
    }

    for module in get_domain_module_registry().values():
        assert required.issubset(module)
        assert module["instruction_scope"]
        assert isinstance(module["memory_schema"], dict)
        assert isinstance(module["tool_requirements"], list)
        assert isinstance(module["bench_categories"], list)
        assert isinstance(module["report_templates"], list)
        assert isinstance(module["risk_boundaries"], list)


def test_readiness_report_passes_with_mocked_dependencies() -> None:
    report = build_agent_kernel_readiness_report(
        dependency_overrides={check_id: True for check_id in REQUIRED_KERNEL_CHECKS}
    )

    assert report["schema"] == AGENT_KERNEL_READINESS_SCHEMA
    assert report["status"] == "passed"
    assert report["summary"]["failed_count"] == 0
    assert report["checks_by_id"]["domain_scaffold_available"]["passed"] is True


def test_readiness_report_fails_when_required_subsystem_missing() -> None:
    overrides = {check_id: True for check_id in REQUIRED_KERNEL_CHECKS}
    overrides["context_compiler_available"] = False

    report = build_agent_kernel_readiness_report(dependency_overrides=overrides)

    assert report["status"] == "failed"
    assert "context_compiler_available" in report["missing"]
    assert report["checks_by_id"]["context_compiler_available"]["passed"] is False


def test_cli_prints_readiness_json() -> None:
    fake_report = {
        "schema": AGENT_KERNEL_READINESS_SCHEMA,
        "status": "passed",
        "summary": {"passed_count": 8, "failed_count": 0, "total_count": 8},
        "checks": [],
        "checks_by_id": {},
        "missing": [],
    }

    with mock.patch("holo_host.cli.build_agent_kernel_readiness_report", return_value=fake_report), mock.patch(
        "sys.stdout", new_callable=io.StringIO
    ) as stdout:
        result = cli.main(["agent-kernel-readiness"])

    assert result == 0
    printed = json.loads(stdout.getvalue())
    assert printed["schema"] == AGENT_KERNEL_READINESS_SCHEMA
    assert printed["status"] == "passed"


def test_no_domain_module_performs_live_work_yet() -> None:
    for module in get_domain_module_registry().values():
        assert module["status"] == "scaffold_only"
        assert module["implements_live_work"] is False
        assert module.get("runtime_entrypoint") in (None, "")


def test_public_hygiene_references_remain_safe() -> None:
    report = build_agent_kernel_readiness_report(
        dependency_overrides={check_id: True for check_id in REQUIRED_KERNEL_CHECKS}
    )
    hygiene = report["checks_by_id"]["public_hygiene_passed_marker"]

    assert hygiene["passed"] is True
    assert "scripts/check_public_release_hygiene.py" in hygiene["details"]
    assert ".holo_runtime" not in hygiene["details"]


def test_stage158_handoff_describes_real_stage156_and_stage157_surfaces() -> None:
    handoff = Path("docs/ENGINEERING_HANDOFF_STAGE158.md").read_text(encoding="utf-8")

    assert "checkout did not contain Stage156 or Stage157" not in handoff
    assert "real Stage156 context compiler" in handoff
    assert "real Stage157 HoloCoreBench" in handoff


def test_stage158_release_doc_exposes_cli_and_boundaries() -> None:
    release_doc = Path("docs/STAGE158_AGENT_KERNEL_V1.md").read_text(encoding="utf-8")

    assert "python -m holo_host chat --thread-key holo_cli:default" in release_doc
    assert "python -m holo_host run-core-bench --output artifacts\\stage157\\holo_core_bench.html --dry-run" in release_doc
    assert "python -m holo_host agent-kernel-readiness" in release_doc
    assert "raw DeepSeek `reasoning_content`" in release_doc
    assert "Stage158 does not add provider calls" in release_doc
