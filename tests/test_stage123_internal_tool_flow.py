from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage121_conscious_packet_scheduler import build_stage121_packet_policy
from holo_host.stage122_internal_external_channel_boundary import build_stage122_channel_frame
from holo_host.stage123_internal_tool_flow import (
    append_stage123_internal_tool_contract,
    build_stage123_internal_tool_flow,
)


def _config(root: Path):
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
network_enabled = false

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 2048

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4"
reasoning_effort = "medium"
max_output_tokens = 4096
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="external answer after tool-aware internal flow",
            session_id="stage123",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def _context(text: str, *, uncertainty: float = 0.0) -> TurnContext:
    payload = {"selected_action": {"action_type": "reply_once", "score": 0.9}}
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="User",
        user_text=text,
        sidecar=payload,
        mind_packet=payload,
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={
            "tool_requests": [
                {"name": "memory_recall", "reason": "ground continuity", "payload": {"query": text}},
                {"name": "workspace_inspect", "reason": "read current repo state", "payload": {"operation": "list", "path": "."}},
                {"name": "test_runner", "reason": "verify behavior", "payload": {"target": "tests/test_stage123_internal_tool_flow.py"}},
            ]
        },
        uncertainty_level=uncertainty,
    )


def _stage122_frame(text: str, *, uncertainty: float = 0.86) -> tuple[dict, list[dict]]:
    tool_requests = [
        {"name": "memory_recall", "reason": "continuity", "payload": {}},
        {"name": "workspace_inspect", "reason": "evidence", "payload": {}},
        {"name": "test_runner", "reason": "verify", "payload": {}},
    ]
    packet_policy = build_stage121_packet_policy(
        prompt="continuous internal tool flow\n" * 90,
        query=text,
        tool_requests=tool_requests,
        uncertainty_level=uncertainty,
        selected_action_type="reply_once",
        lane_name="subject_main",
        lane_max_output_tokens=4096,
    )
    frame = build_stage122_channel_frame(
        user_text=text,
        selected_action_type="reply_once",
        stage121_packet_policy=packet_policy,
        tool_requests=tool_requests,
        uncertainty_level=uncertainty,
    )
    return frame, tool_requests


def test_stage123_internal_flow_can_call_tools_without_executing_them_itself() -> None:
    frame, tool_requests = _stage122_frame("内部流必须能调用工具，但不能绕过本地权限边界")

    flow = build_stage123_internal_tool_flow(
        stage122_channel_frame=frame,
        tool_requests=tool_requests,
    )

    assert flow["stage"] == 123
    assert flow["schema"] == "holo.stage123.internal_tool_flow.v1"
    assert flow["internal_tool_calls"]["enabled"] is True
    assert flow["internal_tool_calls"]["call_before_external_speech"] is True
    assert flow["internal_tool_calls"]["proposed_tool_names"] == ["memory_recall", "workspace_inspect", "test_runner"]
    assert flow["tool_authority"]["provider_may_propose_tools"] is True
    assert flow["tool_authority"]["provider_may_execute_tools"] is False
    assert flow["tool_authority"]["executor"] == "holo_wsl_brain_stage113"
    assert "tool_observation_reentry" in flow["loop_contract"]["required_phases"]
    assert flow["external_expression_gate"]["requires_observation_or_no_tool_needed"] is True


def test_stage123_contract_is_appended_once_and_tells_provider_to_use_tool_calls() -> None:
    frame, tool_requests = _stage122_frame("need tools")
    flow = build_stage123_internal_tool_flow(stage122_channel_frame=frame, tool_requests=tool_requests)

    prompt = append_stage123_internal_tool_contract("base prompt", flow)
    prompt_again = append_stage123_internal_tool_contract(prompt, flow)

    assert prompt.count("Stage123 Internal Tool Flow") == 1
    assert prompt_again == prompt
    assert "tool_calls" in prompt
    assert "Stage113" in prompt
    assert "external_speech" in prompt


def test_stage123_processor_attaches_internal_tool_flow_to_metadata_and_debug(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _RecordingRunner()
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    context = _context("内部流要能调用记忆、仓库检查和测试工具，再形成外部回复", uncertainty=0.88)

    plan = processor.generate(context, session_id="stage123")

    call = runner.calls[-1]
    metadata = dict(call["metadata"])
    flow = metadata["stage123_internal_tool_flow"]
    assert flow["internal_tool_calls"]["enabled"] is True
    assert flow["internal_tool_calls"]["call_before_external_speech"] is True
    assert flow["tool_authority"]["executor"] == "holo_wsl_brain_stage113"
    assert metadata["enable_provider_tools"] is True
    assert metadata["auto_execute_provider_tools"] is True
    assert "Stage123 Internal Tool Flow" in str(call["prompt"])
    assert "tool_calls" in str(call["prompt"])
    assert plan.debug["stage123_internal_tool_flow"]["internal_tool_calls"]["enabled"] is True
    assert plan.text == "external answer after tool-aware internal flow"


def test_stage123_cli_reports_internal_tool_flow(capsys) -> None:
    result = cli.main(
        [
            "stage123-internal-tool-flow",
            "--query",
            "内部流需要调用记忆和仓库检查工具",
            "--uncertainty",
            "0.8",
            "--tool",
            "memory_recall",
            "--tool",
            "workspace_inspect",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 123
    assert payload["internal_tool_calls"]["enabled"] is True
    assert payload["tool_authority"]["provider_may_execute_tools"] is False
