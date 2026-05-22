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
            reply_text="provider tools are available",
            session_id="stage115-chat",
            returncode=0,
            stdout="",
            stderr="",
            metadata={
                "provider": "fake",
                "lane": str(kwargs.get("lane", "") or ""),
                "model": "fake-chat",
                "reasoning_effort": "low",
                "usage": {},
                "reply_lane_reason": dict(kwargs.get("metadata", {}) or {}).get("reply_lane_reason", ""),
            },
        )


def test_deepseek_provider_executes_tool_call_and_requests_final_reply() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict[str, object]] = []

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_memory_1",
                                        "type": "function",
                                        "function": {
                                            "name": "memory_recall",
                                            "arguments": json.dumps({"query": "provider packet continuity", "limit": 2}),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
                }
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Final answer grounded in recalled provider packet continuity."},
                    }
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Explain provider packet continuity.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "tool_requests": [{"name": "memory_recall", "reason": "always available", "payload": {}}],
                            "tool_memory_corpus": [
                                {"id": "m1", "text": "provider packet continuity requires tool observations"},
                            ],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

        assert result.text == "Final answer grounded in recalled provider packet continuity."
        assert len(captured_payloads) == 2
        assert captured_payloads[0]["tools"][0]["function"]["name"] == "memory_recall"
        messages = captured_payloads[1]["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
        assert messages[1]["tool_calls"][0]["id"] == "call_memory_1"
        assert messages[2]["tool_call_id"] == "call_memory_1"
        assert "provider packet continuity" in messages[2]["content"]
        assert captured_payloads[1]["tool_choice"] == "none"
        assert result.metadata["agent_tool_loop"]["executed_count"] == 1
        assert result.metadata["agent_tool_loop"]["final_request_sent"] is True
        assert result.metadata["usage"]["total_tokens"] == 83


def test_holo_chat_enables_agent_tools_for_ordinary_turns() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = _MetadataRecordingRunner()
        processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]

        context = TurnContext(
            channel="holo_app",
            thread_key="holo_app:main",
            chat_name="HoloSubject",
            sender="User",
            user_text="回忆一下provider发包和工具调用的关系",
            sidecar={},
            mind_packet={"selected_action": {"action_type": "reply_once", "score": 0.8}},
            attention_state=build_attention_state("回忆一下provider发包和工具调用的关系", channel="holo_app"),
            emotion_state={},
            history=[],
            metadata={"event_id": "stage115-event"},
            capability_context={},
        )

        processor.generate(context, session_id="stage115-chat")

    metadata = dict(runner.calls[-1]["metadata"])
    tool_requests = list(metadata["tool_requests"])
    tool_names = {str(item.get("name", "")) for item in tool_requests if isinstance(item, dict)}
    assert metadata["enable_provider_tools"] is True
    assert metadata["auto_execute_provider_tools"] is True
    assert {"memory_recall", "external_lookup"}.issubset(tool_names)
    memory_request = next(item for item in tool_requests if item["name"] == "memory_recall")
    assert memory_request["payload"]["thread_key"] == "holo_app:main"
    assert memory_request["payload"]["query"] == "回忆一下provider发包和工具调用的关系"
    assert context.capability_context == {}


def test_deepseek_provider_does_not_auto_execute_without_flag() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()

        def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_memory_1",
                                    "type": "function",
                                    "function": {
                                        "name": "memory_recall",
                                        "arguments": json.dumps({"query": "provider packet continuity"}),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
            }

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json) as post_json:
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Explain provider packet continuity.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "tool_requests": [{"name": "memory_recall", "reason": "available", "payload": {}}],
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

        assert post_json.call_count == 1
        assert result.text == ""
        assert result.metadata["tool_call_count"] == 1
        assert "agent_tool_loop" not in result.metadata
