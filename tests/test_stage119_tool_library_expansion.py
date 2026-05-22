from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from holo_host.capabilities import CapabilityBroker
from holo_host.codex_runner import CodexRunner, DeepSeekProvider
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest, TurnContext
from holo_host.processors import CodexCliProcessor, _agent_tool_requests, build_attention_state
from holo_host.stage106_deepseek_tool_adapter import STAGE119_DEFAULT_TOOL_NAMES, build_tool_payload
from holo_host.stage113_agent_tool_executor import execute_stage113_agent_tools


STAGE119_REQUIRED_TOOLS = {
    "memory_recall",
    "external_lookup",
    "workspace_inspect",
    "local_command",
    "workspace_edit",
    "git_inspect",
    "test_runner",
    "progress_note",
    "file_read",
    "file_list",
    "file_search",
    "file_stat",
    "directory_tree",
    "json_read",
    "toml_read",
    "markdown_outline",
    "symbol_search",
    "repo_overview",
    "git_status",
    "git_diff",
    "git_log",
    "test_discover",
    "python_module_check",
    "config_inspect",
    "runtime_health",
    "memory_warehouse_search",
    "doc_lookup",
    "artifact_list",
    "env_read",
    "dependency_check",
    "time_now",
    "path_resolve",
    "workspace_snapshot",
    "command_run",
    "file_write",
    "file_replace",
    "file_append",
    "note_append",
    "git_stage",
    "git_commit",
    "command_modify",
}


def _context() -> TurnContext:
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="User",
        user_text="inspect workspace, recall memory, and use tools",
        sidecar={},
        mind_packet={"selected_action": {"action_type": "reply_once", "score": 0.9}},
        attention_state=build_attention_state("inspect workspace, recall memory, and use tools", channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={},
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
max_output_tokens = 128
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


def _tool_response(name: str, call_id: str, arguments: dict[str, object]) -> dict[str, object]:
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
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }


class _MetadataRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="permission metadata captured",
            session_id="stage119",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def test_stage119_library_exposes_dozens_of_common_tools() -> None:
    requests = [{"name": name, "reason": "stage119 full library", "payload": {}} for name in STAGE119_DEFAULT_TOOL_NAMES]
    requested_names = {item["name"] for item in requests}
    payload = build_tool_payload(requests)
    exposed_names = {tool["function"]["name"] for tool in payload["tools"]}

    assert len(requested_names) >= 40
    assert len(exposed_names) >= 40
    assert STAGE119_REQUIRED_TOOLS.issubset(requested_names)
    assert STAGE119_REQUIRED_TOOLS.issubset(exposed_names)


def test_stage119_permission_grants_flow_from_turn_metadata_to_provider_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = _config(Path(tmpdir))
        capability_context = CapabilityBroker(config).summarize_turn(
            "write a file if permitted",
            {"tool_permission_grants": [{"tool": "file_write"}]},
            eager_network=False,
        )
        context = _context()
        context.capability_context = capability_context
        runner = _MetadataRecordingRunner()
        processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]

        processor.generate(context, session_id="stage119")

    metadata = dict(runner.calls[-1]["metadata"])
    assert capability_context["tool_permission_grants"] == [{"tool": "file_write"}]
    assert metadata["tool_permission_grants"] == [{"tool": "file_write"}]


def test_stage119_readonly_wrapper_tools_execute_common_workflows(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\n## Memory\n\nTool library notes.\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"topic": "holo", "items": [1, 2]}', encoding="utf-8")
    (tmp_path / ".holo_host.toml").write_text("[runtime]\nstate_dir = '.holo_runtime'\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sample.py").write_text("def test_sample():\n    assert True\n", encoding="utf-8")

    report = execute_stage113_agent_tools(
        [
            {"id": "read", "name": "file_read", "arguments": {"path": "docs/guide.md"}, "allowed": True},
            {"id": "list", "name": "file_list", "arguments": {"path": "."}, "allowed": True},
            {"id": "search", "name": "file_search", "arguments": {"query": "Tool library"}, "allowed": True},
            {"id": "stat", "name": "file_stat", "arguments": {"path": "data.json"}, "allowed": True},
            {"id": "tree", "name": "directory_tree", "arguments": {"path": ".", "max_entries": 12}, "allowed": True},
            {"id": "json", "name": "json_read", "arguments": {"path": "data.json"}, "allowed": True},
            {"id": "toml", "name": "toml_read", "arguments": {"path": ".holo_host.toml"}, "allowed": True},
            {"id": "outline", "name": "markdown_outline", "arguments": {"path": "docs/guide.md"}, "allowed": True},
            {"id": "symbols", "name": "symbol_search", "arguments": {"query": "VALUE", "glob": "**/*.py"}, "allowed": True},
            {"id": "overview", "name": "repo_overview", "arguments": {}, "allowed": True},
            {"id": "discover", "name": "test_discover", "arguments": {}, "allowed": True},
            {"id": "module", "name": "python_module_check", "arguments": {"path": "module.py"}, "allowed": True},
            {"id": "config", "name": "config_inspect", "arguments": {}, "allowed": True},
            {"id": "health", "name": "runtime_health", "arguments": {}, "allowed": True},
            {"id": "docs", "name": "doc_lookup", "arguments": {"query": "Memory"}, "allowed": True},
            {"id": "artifacts", "name": "artifact_list", "arguments": {}, "allowed": True},
            {"id": "env", "name": "env_read", "arguments": {"names": ["PATH", "DEEPSEEK_API_KEY"]}, "allowed": True},
            {"id": "deps", "name": "dependency_check", "arguments": {}, "allowed": True},
            {"id": "time", "name": "time_now", "arguments": {}, "allowed": True},
            {"id": "path", "name": "path_resolve", "arguments": {"path": "docs/guide.md"}, "allowed": True},
            {"id": "snapshot", "name": "workspace_snapshot", "arguments": {}, "allowed": True},
            {"id": "cmd", "name": "command_run", "arguments": {"argv": ["git", "status", "--short"]}, "allowed": True},
        ],
        repo_root=tmp_path,
        network_enabled=False,
    )

    assert report["summary"]["executed_count"] == 22
    assert not report["skipped"]
    statuses = {item["provider_call_id"]: item["status"] for item in report["observations"]}
    assert statuses["json"] == "ok"
    assert statuses["outline"] == "ok"
    assert statuses["module"] == "ok"
    assert statuses["env"] == "ok"
    assert report["observations"][5]["data"]["keys"] == ["items", "topic"]
    assert any(item["tool"] == "command_run" for item in report["observations"])


def test_stage119_modifying_tools_require_explicit_permission(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")

    denied = execute_stage113_agent_tools(
        [
            {
                "id": "write_denied",
                "name": "file_write",
                "arguments": {"path": "notes/denied.txt", "content": "no", "create_dirs": True},
                "allowed": True,
            },
            {
                "id": "cmd_denied",
                "name": "command_modify",
                "arguments": {"argv": ["git", "add", "tracked.txt"]},
                "allowed": True,
            },
        ],
        repo_root=tmp_path,
    )

    assert denied["summary"]["executed_count"] == 2
    assert [item["status"] for item in denied["observations"]] == ["rejected", "rejected"]
    assert not (tmp_path / "notes" / "denied.txt").exists()

    granted = execute_stage113_agent_tools(
        [
            {
                "id": "write_allowed",
                "name": "file_write",
                "arguments": {"path": "notes/allowed.txt", "content": "yes\n", "create_dirs": True},
                "allowed": True,
            },
            {
                "id": "append_allowed",
                "name": "file_append",
                "arguments": {"path": "notes/allowed.txt", "content": "again\n"},
                "allowed": True,
            },
            {
                "id": "stage_allowed",
                "name": "command_modify",
                "arguments": {"argv": ["git", "add", "tracked.txt"]},
                "allowed": True,
            },
        ],
        repo_root=tmp_path,
        permission_grants=[
            {"tool": "file_write"},
            {"tool": "file_append"},
            {"tool": "command_modify", "argv_prefix": ["git", "add"]},
        ],
    )

    assert granted["summary"]["executed_count"] == 3
    assert [item["status"] for item in granted["observations"]] == ["ok", "ok", "ok"]
    assert (tmp_path / "notes" / "allowed.txt").read_text(encoding="utf-8") == "yes\nagain\n"


def test_deepseek_provider_passes_tool_permission_grants_to_executor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        payloads: list[dict[str, object]] = []

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            payloads.append(payload)
            if len(payloads) == 1:
                return _tool_response(
                    "file_write",
                    "call_file_write",
                    {"path": "notes/provider_stage119.txt", "content": "provider write\n", "create_dirs": True},
                )
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "file written with host permission"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Write a note through tools, then answer.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "tool_requests": [{"name": "file_write", "reason": "write note", "payload": {}}],
                            "tool_permission_grants": [{"tool": "file_write"}],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

        assert result.text == "file written with host permission"
        assert (root / "notes" / "provider_stage119.txt").read_text(encoding="utf-8") == "provider write\n"
        assert result.metadata["agent_tool_loop"]["executed_count"] == 1
