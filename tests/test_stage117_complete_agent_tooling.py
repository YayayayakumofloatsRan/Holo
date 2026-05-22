from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from holo_host.codex_runner import CodexRunner, DeepSeekProvider
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest, TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage106_deepseek_tool_adapter import build_tool_payload
from holo_host.stage113_agent_tool_executor import execute_stage113_agent_tools


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
max_output_tokens = 128
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


class _MetadataRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="tool-ready",
            session_id="stage117-chat",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "lane": kwargs.get("lane", ""), "usage": {}},
        )


def _tool_response(name: str, call_id: str, arguments: dict[str, object], usage_total: int) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": usage_total - 5, "completion_tokens": 5, "total_tokens": usage_total},
    }


def test_stage106_preserves_named_tool_choice_for_forced_live_smokes() -> None:
    tool_choice = {"type": "function", "function": {"name": "workspace_inspect"}}

    payload = build_tool_payload(
        [
            {"name": "workspace_inspect", "reason": "inspect workspace", "payload": {}},
            {"name": "local_command", "reason": "run verification", "payload": {}},
        ],
        tool_choice=tool_choice,
    )

    assert payload["tool_choice"] == tool_choice
    assert [tool["function"]["name"] for tool in payload["tools"]] == ["workspace_inspect", "local_command"]


def test_stage113_executes_workspace_inspect_and_allowlisted_local_command(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("Stage117 workspace tool evidence\n", encoding="utf-8")

    report = execute_stage113_agent_tools(
        [
            {
                "id": "call_read",
                "name": "workspace_inspect",
                "arguments": {"operation": "read_file", "path": "docs/note.md", "max_chars": 200},
                "allowed": True,
                "status": "accepted",
            },
            {
                "id": "call_cmd",
                "name": "local_command",
                "arguments": {"argv": ["git", "status", "--short"], "timeout_seconds": 5},
                "allowed": True,
                "status": "accepted",
            },
        ],
        repo_root=tmp_path,
        network_enabled=False,
    )

    assert report["summary"]["executed_count"] == 2
    assert report["observations"][0]["tool"] == "workspace_inspect"
    assert "Stage117 workspace tool evidence" in report["observations"][0]["summary"]
    assert report["observations"][1]["tool"] == "local_command"
    assert report["observations"][1]["status"] in {"ok", "failed"}
    assert "shell" not in report["observations"][1]["data"]


def test_deepseek_provider_completes_workspace_and_command_tool_chain() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "docs").mkdir()
        (root / "docs" / "stage117.md").write_text("Stage117 complete tool chain\n", encoding="utf-8")
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict[str, object]] = []
        forced_choice = {"type": "function", "function": {"name": "workspace_inspect"}}

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return _tool_response(
                    "workspace_inspect",
                    "call_read",
                    {"operation": "read_file", "path": "docs/stage117.md", "max_chars": 200},
                    25,
                )
            if len(captured_payloads) == 2:
                return _tool_response(
                    "local_command",
                    "call_status",
                    {"argv": ["git", "status", "--short"], "timeout_seconds": 5},
                    31,
                )
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "Workspace and command tools completed."}}],
                "usage": {"prompt_tokens": 33, "completion_tokens": 7, "total_tokens": 40},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Inspect the workspace and verify git status before answering.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "provider_tool_choice": forced_choice,
                            "tool_requests": [
                                {"name": "workspace_inspect", "reason": "read workspace", "payload": {}},
                                {"name": "local_command", "reason": "verify status", "payload": {}},
                            ],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

    assert result.text == "Workspace and command tools completed."
    assert len(captured_payloads) == 3
    assert captured_payloads[0]["tool_choice"] == forced_choice
    assert captured_payloads[1]["tool_choice"] == "auto"
    assert captured_payloads[2]["messages"][2]["tool_call_id"] == "call_read"
    assert "Stage117 complete tool chain" in captured_payloads[1]["messages"][2]["content"]
    assert captured_payloads[2]["messages"][4]["tool_call_id"] == "call_status"
    assert result.metadata["agent_tool_loop"]["round_count"] == 2
    assert result.metadata["agent_tool_loop"]["executed_count"] == 2


def test_holo_chat_defaults_include_workspace_and_command_tools() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = _config(Path(tmpdir))
        runner = _MetadataRecordingRunner()
        processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
        context = TurnContext(
            channel="holo_app",
            thread_key="holo_app:main",
            chat_name="HoloSubject",
            sender="User",
            user_text="check the tool calling path",
            sidecar={},
            mind_packet={"selected_action": {"action_type": "reply_once", "score": 0.9}},
            attention_state=build_attention_state("check the tool calling path", channel="holo_app"),
            emotion_state={},
            history=[],
            metadata={},
            capability_context={},
        )

        processor.generate(context, session_id="stage117-chat")

    metadata = dict(runner.calls[-1]["metadata"])
    names = {item["name"] for item in metadata["tool_requests"]}
    assert {"memory_recall", "external_lookup", "workspace_inspect", "local_command"}.issubset(names)
