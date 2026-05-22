from __future__ import annotations

import json
import subprocess
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


ALL_STAGE118_TOOLS = {
    "memory_recall",
    "external_lookup",
    "workspace_inspect",
    "local_command",
    "workspace_edit",
    "git_inspect",
    "test_runner",
    "progress_note",
}


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
            reply_text="tool-expanded",
            session_id="stage118-chat",
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


def test_stage118_tool_payload_exposes_eight_tools() -> None:
    payload = build_tool_payload([{"name": name, "reason": "stage118", "payload": {}} for name in ALL_STAGE118_TOOLS])

    exposed = {tool["function"]["name"] for tool in payload["tools"]}
    assert ALL_STAGE118_TOOLS.issubset(exposed)
    assert payload["tool_choice"] == "auto"


def test_stage113_executes_workspace_edit_and_progress_note(tmp_path: Path) -> None:
    target = tmp_path / "notes" / "stage118.txt"

    report = execute_stage113_agent_tools(
        [
            {
                "id": "call_write",
                "name": "workspace_edit",
                "arguments": {
                    "operation": "write_file",
                    "path": "notes/stage118.txt",
                    "content": "before tool expansion\n",
                    "create_dirs": True,
                },
                "allowed": True,
                "status": "accepted",
            },
            {
                "id": "call_replace",
                "name": "workspace_edit",
                "arguments": {
                    "operation": "replace_text",
                    "path": "notes/stage118.txt",
                    "old_text": "before",
                    "new_text": "after",
                },
                "allowed": True,
                "status": "accepted",
            },
            {
                "id": "call_progress",
                "name": "progress_note",
                "arguments": {
                    "title": "Stage118",
                    "summary": "expanded local agent tools",
                    "category": "tooling",
                },
                "allowed": True,
                "status": "accepted",
            },
        ],
        repo_root=tmp_path,
        network_enabled=False,
        permission_grants=[
            {"tool": "workspace_edit"},
            {"tool": "progress_note"},
        ],
    )

    assert report["summary"]["executed_count"] == 3
    assert target.read_text(encoding="utf-8") == "after tool expansion\n"
    assert report["observations"][0]["tool"] == "workspace_edit"
    assert report["observations"][1]["status"] == "ok"
    progress_path = tmp_path / "docs" / "agent_progress_notes" / "stage118.md"
    assert progress_path.exists()
    assert "expanded local agent tools" in progress_path.read_text(encoding="utf-8")


def test_stage113_executes_git_inspect_and_test_runner(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_sample():\n    assert 1 + 1 == 2\n", encoding="utf-8")

    report = execute_stage113_agent_tools(
        [
            {
                "id": "call_git",
                "name": "git_inspect",
                "arguments": {"operation": "status_short"},
                "allowed": True,
                "status": "accepted",
            },
            {
                "id": "call_test",
                "name": "test_runner",
                "arguments": {"path_patterns": ["tests/test_sample.py"], "timeout_seconds": 30},
                "allowed": True,
                "status": "accepted",
            },
        ],
        repo_root=tmp_path,
        network_enabled=False,
    )

    assert report["summary"]["executed_count"] == 2
    assert report["observations"][0]["tool"] == "git_inspect"
    assert "tests/" in report["observations"][0]["summary"]
    assert report["observations"][1]["tool"] == "test_runner"
    assert report["observations"][1]["status"] == "ok"
    assert "passed" in report["observations"][1]["summary"]


def test_deepseek_provider_can_chain_edit_test_and_git_tools() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        (root / "tests").mkdir()
        (root / "tests" / "test_stage118_provider.py").write_text("def test_provider():\n    assert True\n", encoding="utf-8")
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict[str, object]] = []

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return _tool_response(
                    "workspace_edit",
                    "call_edit",
                    {
                        "operation": "write_file",
                        "path": "notes/provider_stage118.txt",
                        "content": "provider wrote this\n",
                        "create_dirs": True,
                    },
                    20,
                )
            if len(captured_payloads) == 2:
                return _tool_response(
                    "test_runner",
                    "call_test",
                    {"path_patterns": ["tests/test_stage118_provider.py"], "timeout_seconds": 30},
                    27,
                )
            if len(captured_payloads) == 3:
                return _tool_response("git_inspect", "call_git", {"operation": "status_short"}, 22)
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "Edit, tests, and git inspection completed."}}],
                "usage": {"prompt_tokens": 28, "completion_tokens": 8, "total_tokens": 36},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Edit a file, run a test, inspect git, then answer.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "max_provider_tool_rounds": 5,
                            "tool_requests": [
                                {"name": "workspace_edit", "reason": "write file", "payload": {}},
                                {"name": "test_runner", "reason": "run tests", "payload": {}},
                                {"name": "git_inspect", "reason": "inspect git", "payload": {}},
                            ],
                            "tool_permission_grants": [{"tool": "workspace_edit"}],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )
        file_text = (root / "notes" / "provider_stage118.txt").read_text(encoding="utf-8")

    assert result.text == "Edit, tests, and git inspection completed."
    assert len(captured_payloads) == 4
    assert file_text == "provider wrote this\n"
    assert result.metadata["agent_tool_loop"]["round_count"] == 3
    assert result.metadata["agent_tool_loop"]["executed_count"] == 3


def test_holo_chat_defaults_include_stage118_tools() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = _config(Path(tmpdir))
        runner = _MetadataRecordingRunner()
        processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
        context = TurnContext(
            channel="holo_app",
            thread_key="holo_app:main",
            chat_name="HoloSubject",
            sender="User",
            user_text="expand agent tools",
            sidecar={},
            mind_packet={"selected_action": {"action_type": "reply_once", "score": 0.9}},
            attention_state=build_attention_state("expand agent tools", channel="holo_app"),
            emotion_state={},
            history=[],
            metadata={},
            capability_context={},
        )

        processor.generate(context, session_id="stage118-chat")

    metadata = dict(runner.calls[-1]["metadata"])
    names = {item["name"] for item in metadata["tool_requests"]}
    assert (ALL_STAGE118_TOOLS - {"workspace_edit", "progress_note"}).issubset(names)
    assert "workspace_edit" not in names
    assert "progress_note" not in names
