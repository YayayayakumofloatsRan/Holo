from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from holo_host.codex_runner import CodexRunner, DeepSeekProvider
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest


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


def test_deepseek_provider_can_run_multiple_tool_rounds_before_final_answer() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict[str, object]] = []

        def fake_lookup(query: str, max_results: int) -> dict[str, object]:
            return {
                "query": query,
                "status": "ok",
                "results": [
                    {"title": "Tool loop paper", "url": "https://example.test/tool-loop", "snippet": "multi-round tool calls"}
                ][:max_results],
            }

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return _tool_response("memory_recall", "call_memory_1", {"query": "multi round tools", "limit": 2}, 31)
            if len(captured_payloads) == 2:
                return _tool_response(
                    "external_lookup",
                    "call_lookup_1",
                    {"query": "multi round tool calling", "max_results": 2},
                    37,
                )
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Final answer after memory and external lookup."},
                    }
                ],
                "usage": {"prompt_tokens": 41, "completion_tokens": 9, "total_tokens": 50},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Use tools until the answer has memory and external evidence.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "max_provider_tool_rounds": 4,
                            "tool_requests": [
                                {"name": "memory_recall", "reason": "local memory", "payload": {}},
                                {"name": "external_lookup", "reason": "external evidence", "payload": {}},
                            ],
                            "tool_memory_corpus": [{"id": "m1", "text": "multi round tools need re-entry"}],
                            "external_lookup_fn": fake_lookup,
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

    assert result.text == "Final answer after memory and external lookup."
    assert len(captured_payloads) == 3
    assert captured_payloads[1]["tool_choice"] == "auto"
    assert captured_payloads[2]["tool_choice"] == "auto"
    assert [message["role"] for message in captured_payloads[2]["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert captured_payloads[2]["messages"][4]["tool_call_id"] == "call_lookup_1"
    loop = result.metadata["agent_tool_loop"]
    assert loop["round_count"] == 2
    assert loop["executed_count"] == 2
    assert loop["final_request_sent"] is True
    assert [round_item["tool_names"] for round_item in loop["rounds"]] == [["memory_recall"], ["external_lookup"]]
    assert result.metadata["usage"]["total_tokens"] == 118


def test_deepseek_provider_converts_rejected_tool_calls_into_tool_observations() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict[str, object]] = []

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return _tool_response("shell_exec", "call_shell_1", {"cmd": "whoami"}, 20)
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "I cannot execute that tool."}}],
                "usage": {"prompt_tokens": 21, "completion_tokens": 6, "total_tokens": 27},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Try an unsafe tool.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "tool_requests": [{"name": "memory_recall", "reason": "safe", "payload": {}}],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

    assert result.text == "I cannot execute that tool."
    assert len(captured_payloads) == 2
    tool_message = captured_payloads[1]["messages"][2]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_shell_1"
    assert "unknown_tool" in tool_message["content"]
    assert result.metadata["agent_tool_loop"]["skipped_count"] == 1
    assert result.metadata["agent_tool_loop"]["tool_failure_reentry"] is True
    assert result.metadata["tool_failure_reentry"] is True
    assert result.metadata["tool_observation_ledger"] == [
        {
            "provider_call_id": "call_shell_1",
            "tool": "shell_exec",
            "status": "rejected",
            "summary": "tool rejected: unknown_tool",
            "data_keys": ["reason"],
            "grounding_tags": [],
        }
    ]
