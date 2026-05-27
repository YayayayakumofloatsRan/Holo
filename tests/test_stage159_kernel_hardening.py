from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_kernel_readiness import build_agent_kernel_readiness_report
from holo_host.holo_core_bench import run_holo_core_bench
from holo_host.interactive_cli import InteractiveCliSession
from holo_host.stage151_tool_decision_loop import (
    build_network_health_report,
    build_tool_decision_report,
    execute_tool_decision,
)


def test_sanitizer_removes_reasoning_content_recursively() -> None:
    from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata

    payload = {
        "visible": "ok",
        "nested": {
            "reasoning_content": "secret",
            "safe": [{"chain_of_thought": "secret"}, {"text": "visible"}],
        },
    }

    sanitized = sanitize_public_metadata(payload)

    ok, paths = assert_no_private_reasoning(sanitized)
    assert ok is True
    assert paths == []
    assert sanitized == {"visible": "ok", "nested": {"safe": [{"text": "visible"}]}}


def test_public_stage152_report_drops_internal_messages() -> None:
    from holo_host.kernel_metadata_sanitizer import build_public_stage152_report

    report = build_public_stage152_report(
        {
            "schema": "holo.stage152.deepseek_tool_loop.v1",
            "status": "completed",
            "messages": [{"role": "assistant", "reasoning_content": "secret"}],
            "assistant_messages_internal": [{"reasoning_content": "secret"}],
            "final_decoded": {"choices": [{"message": {"reasoning_content": "secret"}}]},
            "tool_call_count": 1,
            "reasoning_content_retained_count": 1,
            "stop_reason": "model_final_no_tool_calls",
        }
    )

    assert report["tool_call_count"] == 1
    assert report["reasoning_content_retained_count"] == 1
    assert "messages" not in report
    assert "assistant_messages_internal" not in report
    assert "final_decoded" not in report
    assert '"reasoning_content"' not in json.dumps(report)


def test_interactive_json_uses_sanitized_payload() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:stage159", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(
        {
            "text": "done",
            "stage152_deepseek_tool_loop": {
                "reasoning_content_retained_count": 1,
                "assistant_messages_internal": [{"reasoning_content": "do not leak"}],
                "messages": [{"role": "assistant", "reasoning_content": "do not leak"}],
            },
        },
        user_text="show json",
    )

    rendered = session.render_json()

    assert "do not leak" not in rendered
    assert "assistant_messages_internal" not in rendered
    assert '"reasoning_content"' not in rendered


def test_safe_command_allows_pytest_without_shell(tmp_path: Path) -> None:
    from holo_host.engineering_workspace_tools import test_run

    test_file = tmp_path / "test_smoke.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout="1 passed", stderr="")

    with mock.patch("holo_host.engineering_workspace_tools.subprocess.run", side_effect=fake_run):
        row = test_run(tmp_path, "python -m pytest test_smoke.py -q")

    assert row["status"] == "ok"
    assert calls[0]["argv"] == ["python", "-m", "pytest", "test_smoke.py", "-q"]
    assert calls[0]["kwargs"].get("shell") is not True


def test_safe_command_rejects_shell_chaining() -> None:
    from holo_host.safe_command_policy import parse_allowed_command

    argv, reason = parse_allowed_command("python -m pytest -q && git status --short")

    assert argv == []
    assert reason == "command_not_allowlisted"


def test_safe_command_rejects_package_install() -> None:
    from holo_host.safe_command_policy import parse_allowed_command

    argv, reason = parse_allowed_command("python -m pip install requests")

    assert argv == []
    assert reason == "command_not_allowlisted"


def test_safe_command_rejects_path_escape(tmp_path: Path) -> None:
    from holo_host.safe_command_policy import parse_allowed_command

    argv, reason = parse_allowed_command("git diff -- ../secret.txt", repo_root=tmp_path)

    assert argv == []
    assert reason == "path_escape"


def test_readiness_uses_active_probes() -> None:
    report = build_agent_kernel_readiness_report()

    assert report["kernel_hardening"]["schema"] == "holo.stage159.kernel_hardening.v1"
    assert report["summary"]["failed_count"] == 0
    assert all(item["probe_schema"] == "holo.stage159.readiness_probe.v1" for item in report["checks"])
    assert all(item["probe_type"] == "active" for item in report["checks"])


def test_core_bench_live_smoke_runs_without_provider_or_network() -> None:
    report = run_holo_core_bench(mode="live-smoke")

    assert report["mode"] == "live-smoke"
    assert report["status"] == "passed"
    assert report["authority_boundary"]["provider_calls"] is False
    assert report["authority_boundary"]["tool_execution"] is False
    assert "kernel_hardening_live_smoke" in report["categories_by_id"]


def test_canonical_stop_reason_maps_stage152_budget() -> None:
    from holo_host.canonical_stop_reason import map_canonical_stop_reason

    mapped = map_canonical_stop_reason(stage152={"stop_reason": "tool_call_budget_exceeded"})

    assert mapped["canonical_stop_reason"] == "budget_exhausted"
    assert mapped["canonical_stop_source"] == "stage152_deepseek_tool_loop"


def test_canonical_stop_reason_in_event_stream() -> None:
    stream = build_agent_event_stream(
        {"text": "Stopped.", "stage152_deepseek_tool_loop": {"stop_reason": "tool_call_budget_exceeded"}},
        user_text="continue",
        thread_key="holo_cli:stage159",
        chat_name="HoloCLI",
        channel="holo_cli",
    )

    rendered = render_agent_event_stream(stream)

    assert "[stop] budget_exhausted" in rendered


def test_network_disabled_records_health_and_rejection() -> None:
    decision = build_tool_decision_report("search latest OpenAI docs")
    observations = execute_tool_decision(decision, network_enabled=False)
    health = build_network_health_report(
        network_enabled=False,
        provider="host",
        last_web_status=observations[0]["status"],
        last_error=observations[0]["error"],
    )

    assert observations[0]["status"] == "rejected_network_disabled"
    assert health["schema"] == "holo.stage159.network_health.v1"
    assert health["network_enabled"] is False
    assert health["last_web_status"] == "rejected_network_disabled"


def test_stage135_topology_exposes_kernel_hardening_node() -> None:
    from holo_host.stage135_i_state_topology import build_stage135_i_state_topology

    topology = build_stage135_i_state_topology(
        user_text="search latest docs",
        stage153_agent_event_stream={"event_count": 2},
        network_health={
            "schema": "holo.stage159.network_health.v1",
            "network_enabled": False,
            "last_web_status": "rejected_network_disabled",
        },
        canonical_stop={
            "canonical_stop_reason": "boundary_or_permission",
            "canonical_stop_source": "stage151_tool_decision",
        },
    )

    assert topology["metrics"]["kernel_hardening_node_count"] == 1
    assert topology["metrics"]["canonical_stop_reason"] == "boundary_or_permission"
    assert topology["metrics"]["last_web_status"] == "rejected_network_disabled"
