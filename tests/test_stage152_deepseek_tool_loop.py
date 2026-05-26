from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from holo_host.codex_runner import CodexRunner, DeepSeekProvider
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest
from holo_host.stage151_tool_decision_loop import build_time_observation, evaluate_tool_decision_grounding
from holo_host.stage152_deepseek_tool_loop import (
    STAGE152_TOOL_LOOP_SCHEMA,
    WEB_OBSERVATION_SCHEMA,
    build_deepseek_native_tool_payload,
    format_stage152_live_trace,
    run_deepseek_native_tool_loop,
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
network_enabled = true

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "high"
max_output_tokens = 128
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


def _response(content: str, *, tool_calls: list[dict] | None = None, reasoning_content: str = "", usage: dict | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return {
        "choices": [{"finish_reason": "tool_calls" if tool_calls else "stop", "message": message}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def test_deepseek_tool_loop_stops_when_tool_calls_is_none() -> None:
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response("Direct final answer.", tool_calls=None),
        base_payload={"messages": [{"role": "user", "content": "hello"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("should not be called"),
        network_enabled=True,
    )

    assert result["schema"] == STAGE152_TOOL_LOOP_SCHEMA
    assert result["round_count"] == 0
    assert result["final_request_sent"] is False
    assert result["stop_reason"] == "no_tool_calls"


def test_tool_result_is_appended_as_role_tool() -> None:
    captured_payloads: list[dict] = []

    def call_model(payload: dict) -> dict:
        captured_payloads.append(payload)
        return _response("Final after memory.")

    result = run_deepseek_native_tool_loop(
        initial_decoded=_response(
            "",
            tool_calls=[_tool_call("memory_recall", {"query": "emoji preference"}, "call_memory")],
            reasoning_content="hidden scratchpad",
        ),
        base_payload={"messages": [{"role": "user", "content": "remember?"}], **build_deepseek_native_tool_payload()},
        call_model=call_model,
        network_enabled=True,
        memory_corpus=[{"id": "pref-emoji", "text": "user preference: fewer emoji"}],
    )

    assert result["round_count"] == 1
    messages = captured_payloads[0]["messages"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["id"] == "call_memory"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_memory"


def test_reasoning_content_is_retained_internally_but_not_visible_in_trace() -> None:
    secret = "raw hidden reasoning should stay internal"
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response(
            "",
            tool_calls=[_tool_call("time_observe", {"reason": "date-sensitive"}, "call_time")],
            reasoning_content=secret,
        ),
        base_payload={"messages": [{"role": "user", "content": "today?"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("As of today, the host time is observed."),
        network_enabled=True,
    )

    assert result["reasoning_content_retained_count"] == 1
    assert result["assistant_messages_internal"][0]["reasoning_content"] == secret
    rendered = format_stage152_live_trace({"stage152_live_trace": result["live_trace"]})
    assert "hidden reasoning" not in rendered
    assert secret not in rendered
    assert "[tool] time_observe" in rendered
    assert "[evaluate]" in rendered
    assert "[stop]" in rendered


def test_cache_tokens_are_captured_from_usage() -> None:
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response(
            "",
            tool_calls=[_tool_call("time_observe", {"reason": "today"}, "call_time")],
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            },
        ),
        base_payload={"messages": [{"role": "user", "content": "today?"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response(
            "As of today, observed.",
            usage={
                "prompt_tokens": 40,
                "completion_tokens": 10,
                "total_tokens": 50,
                "prompt_cache_hit_tokens": 30,
                "prompt_cache_miss_tokens": 10,
            },
        ),
        network_enabled=True,
    )

    assert result["usage"]["prompt_cache_hit_tokens"] == 110
    assert result["usage"]["prompt_cache_miss_tokens"] == 30


def test_network_disabled_rejects_web_tool() -> None:
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response("", tool_calls=[_tool_call("web_search", {"query": "OpenAI Codex docs"}, "call_web")]),
        base_payload={"messages": [{"role": "user", "content": "search"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("I searched the web and found the official docs."),
        network_enabled=False,
    )

    assert result["web_observation_ledger"][0]["schema"] == WEB_OBSERVATION_SCHEMA
    assert result["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert result["grounding"]["status"] != "grounded"
    assert "web_search" in result["final_text"]


def test_final_claim_without_ledger_is_repaired() -> None:
    report = evaluate_tool_decision_grounding(
        "I searched the official website and found the latest docs.",
        web_observation_ledger=[],
        time_observation=build_time_observation(),
    )

    assert report["repair_required"] is True


def test_successful_mocked_web_search_grounds_final_answer() -> None:
    def search(query: str) -> dict:
        return {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Official Codex CLI documentation."}],
        }

    result = run_deepseek_native_tool_loop(
        initial_decoded=_response("", tool_calls=[_tool_call("web_search", {"query": "OpenAI Codex CLI docs"}, "call_web")]),
        base_payload={"messages": [{"role": "user", "content": "search"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("I searched the official Codex CLI docs and found the source."),
        network_enabled=True,
        web_search_fn=search,
    )

    assert result["web_observation_ledger"][0]["status"] == "ok"
    assert result["web_observation_ledger"][0]["source_urls"] == ["https://developers.openai.com/codex/cli"]
    assert result["grounding"]["status"] == "grounded"
    rendered = format_stage152_live_trace({"stage152_live_trace": result["live_trace"]})
    assert "sources=https://developers.openai.com/codex/cli" in rendered


def test_deepseek_provider_uses_stage152_native_tools_and_redacts_trace_reasoning() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = _config(root)
        runner = CodexRunner(config)
        provider = DeepSeekProvider()
        captured_payloads: list[dict] = []

        def fake_post_json(url: str, api_key: str, payload: dict, timeout_seconds: int) -> dict:
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return _response(
                    "",
                    tool_calls=[_tool_call("web_search", {"query": "OpenAI Codex CLI docs"}, "call_web")],
                    reasoning_content="private reasoning must not be shown",
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "prompt_cache_hit_tokens": 7, "prompt_cache_miss_tokens": 3},
                )
            return _response(
                "I searched the official Codex CLI docs.",
                usage={"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18, "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 4},
            )

        with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
            with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                result = provider.run_task(
                    runner,
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="Search official Codex CLI docs.",
                        lane="micro_fast",
                        metadata={
                            "enable_provider_tools": True,
                            "auto_execute_provider_tools": True,
                            "stage152_native_tool_loop": True,
                            "web_search_fn": lambda query: {
                                "query": query,
                                "status": "ok",
                                "provider": "mock_search",
                                "results": [
                                    {
                                        "title": "Codex CLI",
                                        "url": "https://developers.openai.com/codex/cli",
                                        "snippet": "Official docs",
                                    }
                                ],
                            },
                        },
                    ),
                    spec={"output_schema": "plain_text"},
                    lane_name="micro_fast",
                    lane_config=config.processor_fabric.provider_backends["micro_fast"],
                )

    assert captured_payloads[0]["tools"][0]["function"]["name"] == "time_observe"
    assert any(tool["function"]["name"] == "web_search" for tool in captured_payloads[0]["tools"])
    messages = captured_payloads[1]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
    assert messages[1]["reasoning_content"] == "private reasoning must not be shown"
    assert result.metadata["stage152_deepseek_tool_loop"]["tool_call_count"] == 1
    assert result.metadata["stage152_deepseek_tool_loop"]["reasoning_content_retained_count"] == 1
    assert result.metadata["usage"]["prompt_cache_hit_tokens"] == 15
    trace = format_stage152_live_trace({"stage152_live_trace": result.metadata["stage152_live_trace"]})
    assert "[tool] web_search" in trace
    assert "private reasoning" not in trace
