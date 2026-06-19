from __future__ import annotations

import asyncio
import json
from unittest import mock

import pytest

from kernel_v4.contracts import ChatMessage, ModelEvent, ToolCall, ToolManifest
from kernel_v4.finance_runner import build_finance_registry
from kernel_v4.providers import DeepSeekChatProvider, OpenAICompatibleChatProvider, openai_native_tool_surface_v4


class _SseResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]
        self._index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def readline(self):
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


async def _collect(provider, *, messages, tools, system_prompt="system", context=None):
    events = []
    async for event in provider.stream(
        messages=messages,
        tools=tools,
        system_prompt=system_prompt,
        context=context or {},
    ):
        events.append(event)
    return events


def test_openai_compatible_provider_payload_exposes_v4_tools() -> None:
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={
            "expression": {"type": "str", "required": True, "min_length": 1},
            "precision": {"type": "int", "required": False, "min": 8, "max": 80},
        },
    )

    payload, name_map = provider.build_payload(
        messages=[ChatMessage(role="user", content="compute 2+2")],
        tools=[tool],
        system_prompt="system",
        context={"run_id": "run-1"},
        stream=True,
    )

    native_name = payload["tools"][0]["function"]["name"]
    assert native_name.startswith("calculator_compute_")
    assert name_map[native_name] == "calculator.compute"
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["tools"][0]["function"]["parameters"]["required"] == ["expression"]
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "system"
    assert "Runtime context" not in payload["messages"][0]["content"]
    assert payload["messages"][-1]["role"] == "system"
    assert "Runtime context" in payload["messages"][-1]["content"]
    assert "run-1" in payload["messages"][-1]["content"]


def test_openai_compatible_provider_keeps_static_system_prefix_cache_friendly() -> None:
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
    )
    tool = ToolManifest(name="calculator.compute", description="Compute arithmetic.")

    first, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="same task")],
        tools=[tool],
        system_prompt="static system prompt",
        context={"run_id": "run-a", "turn_index": 1},
        stream=True,
    )
    second, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="same task")],
        tools=[tool],
        system_prompt="static system prompt",
        context={"run_id": "run-b", "turn_index": 2},
        stream=True,
    )

    assert first["messages"][0] == second["messages"][0]
    assert first["messages"][1] == second["messages"][1]
    assert first["messages"][-1] != second["messages"][-1]
    assert "turn_index" in first["messages"][-1]["content"]


def test_openai_compatible_provider_exposes_deepseek_thinking_controls() -> None:
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        thinking="disabled",
        reasoning_effort="high",
    )

    payload, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="answer")],
        tools=[],
        system_prompt="system",
        context={},
        stream=True,
    )

    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload

    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        thinking="enabled",
        reasoning_effort="high",
    )
    payload, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="answer")],
        tools=[],
        system_prompt="system",
        context={},
        stream=True,
    )

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_deepseek_provider_defaults_to_thinking_disabled_for_cost(monkeypatch) -> None:
    monkeypatch.delenv("HOLO_V4_DEEPSEEK_THINKING", raising=False)
    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    provider = DeepSeekChatProvider(model="deepseek-v4-pro")

    payload, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="answer")],
        tools=[],
        system_prompt="system",
        context={},
        stream=True,
    )

    assert payload["thinking"] == {"type": "disabled"}


def test_openai_native_tool_surface_exposes_workbench_inputs_as_concrete_schema() -> None:
    registry = build_finance_registry(allow_network=False)
    surface = openai_native_tool_surface_v4(registry.all_manifests())
    by_real_name = {real_name: native_name for native_name, real_name in surface.name_map.items()}

    tool_workbench = next(
        tool for tool in surface.tools if tool["function"]["name"] == by_real_name["tool.workbench"]
    )
    finance_workbench = next(
        tool for tool in surface.tools if tool["function"]["name"] == by_real_name["finance.workbench.open"]
    )
    finance_audit = next(
        tool for tool in surface.tools if tool["function"]["name"] == by_real_name["finance.toolchain.audit"]
    )

    tool_props = tool_workbench["function"]["parameters"]["properties"]
    finance_props = finance_workbench["function"]["parameters"]["properties"]
    audit_props = finance_audit["function"]["parameters"]["properties"]
    assert tool_props["query"]["type"] == "string"
    assert tool_props["families"]["type"] == "string"
    assert tool_props["max_tools"]["type"] == "integer"
    assert finance_props["query"]["type"] == "string"
    assert finance_props["task_family"]["type"] == "string"
    assert finance_props["max_profiles"]["type"] == "integer"
    assert audit_props["mode"]["type"] == "string"


def test_openai_compatible_provider_can_force_visible_v4_tool() -> None:
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        force_tool_name="calculator.compute",
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )

    payload, name_map = provider.build_payload(
        messages=[ChatMessage(role="user", content="compute 2+2")],
        tools=[tool],
        system_prompt="system",
        context={"turn_index": 1},
        stream=True,
    )
    continuation_payload, _ = provider.build_payload(
        messages=[ChatMessage(role="user", content="compute 2+2")],
        tools=[tool],
        system_prompt="system",
        context={"turn_index": 2},
        stream=True,
    )

    native_name = next(native for native, real in name_map.items() if real == "calculator.compute")
    assert payload["tool_choice"] == {"type": "function", "function": {"name": native_name}}
    assert continuation_payload["tool_choice"] == "auto"


def test_openai_compatible_provider_stream_maps_native_tool_call_to_v4_name(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )
    seen_headers: list[str | None] = []

    def fake_urlopen(request, timeout):
        del timeout
        seen_headers.append(request.get_header("Authorization"))
        body = json.loads(request.data.decode("utf-8"))
        native_name = body["tools"][0]["function"]["name"]
        return _SseResponse(
            [
                'data: {"choices":[{"delta":{"content":"checking "}}]}\n',
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "type": "function",
                                            "function": {
                                                "name": native_name,
                                                "arguments": "{\"expression\":",
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
                + "\n",
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"2+2\\"}"}}]},"finish_reason":"tool_calls"}]}\n',
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(
            _collect(
                provider,
                messages=[ChatMessage(role="user", content="use calculator")],
                tools=[tool],
            )
        )

    assert seen_headers == ["Bearer secret-key"]
    tool_events = [event for event in events if event.event_type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.name == "calculator.compute"
    assert tool_events[0].tool_call.input == {"expression": "2+2"}
    assert any(event.event_type == "text_delta" and event.text == "checking " for event in events)
    assert events[-1].event_type == "message_stop"


def test_openai_compatible_provider_resolves_historical_native_tool_alias(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )
    current_tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )
    previous_messages = [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=(
                ToolCall(
                    tool_call_id="call-old-artifact-search",
                    name="artifact.search",
                    input={"query": "gross margin"},
                ),
            ),
        )
    ]

    def fake_urlopen(request, timeout):
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        exposed_names = {tool["function"]["name"] for tool in body["tools"]}
        assert any(name.startswith("calculator_compute_") for name in exposed_names)
        assert "artifact_search_9308f523" not in exposed_names
        return _SseResponse(
            [
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-reused-alias",
                                            "type": "function",
                                            "function": {
                                                "name": "artifact_search_9308f523",
                                                "arguments": "{\"query\":\"gross margin\"}",
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                )
                + "\n",
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(_collect(provider, messages=previous_messages, tools=[current_tool]))

    tool_events = [event for event in events if event.event_type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.name == "artifact.search"


def test_openai_compatible_provider_round_trips_reasoning_content(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
        thinking="enabled",
        reasoning_effort="high",
    )

    def fake_urlopen(request, timeout):
        del request, timeout
        return _SseResponse(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}\n',
                'data: {"choices":[{"delta":{"content":"done"}}]}\n',
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(_collect(provider, messages=[ChatMessage(role="user", content="answer")], tools=[]))

    assert events[-1].event_type == "message_stop"
    assert events[-1].metadata["reasoning_content"] == "private reasoning"
    assert events[-1].metadata["reasoning_content_chars"] == len("private reasoning")

    payload, _ = provider.build_payload(
        messages=[
            ChatMessage(
                role="assistant",
                content="",
                metadata={"_private_reasoning_content": "private reasoning"},
            )
        ],
        tools=[],
        system_prompt="system",
        context={},
        stream=True,
    )
    assert payload["messages"][1]["reasoning_content"] == "private reasoning"


def test_openai_compatible_provider_stream_records_usage_and_cache(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )

    def fake_urlopen(request, timeout):
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream_options"] == {"include_usage": True}
        return _SseResponse(
            [
                'data: {"choices":[{"delta":{"content":"done"}}]}\n',
                "data: "
                + json.dumps(
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 7,
                            "total_tokens": 107,
                            "prompt_cache_hit_tokens": 80,
                            "prompt_cache_miss_tokens": 20,
                        },
                    }
                )
                + "\n",
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(_collect(provider, messages=[ChatMessage(role="user", content="hello")], tools=[]))

    stop = events[-1]
    assert stop.event_type == "message_stop"
    assert stop.metadata["usage"]["prompt_tokens"] == 100
    assert stop.metadata["usage"]["cache"]["prompt_cache_hit_tokens"] == 80
    assert stop.metadata["usage"]["cache"]["cache_hit_rate"] == 0.8


def test_openai_compatible_provider_stream_maps_unsuffixed_sanitized_tool_alias(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )

    def fake_urlopen(request, timeout):
        del request, timeout
        return _SseResponse(
            [
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "type": "function",
                                            "function": {
                                                "name": "calculator_compute",
                                                "arguments": "{\"expression\":\"2+2\"}",
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                )
                + "\n",
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(
            _collect(
                provider,
                messages=[ChatMessage(role="user", content="use calculator")],
                tools=[tool],
            )
        )

    tool_events = [event for event in events if event.event_type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.name == "calculator.compute"
    assert tool_events[0].tool_call.input == {"expression": "2+2"}


def test_openai_compatible_provider_leaves_unknown_tool_alias_unmapped(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )

    def fake_urlopen(request, timeout):
        del request, timeout
        return _SseResponse(
            [
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"not_registered_tool","arguments":"{\\"x\\":1}"}}]},"finish_reason":"tool_calls"}]}\n',
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(
            _collect(
                provider,
                messages=[ChatMessage(role="user", content="use calculator")],
                tools=[tool],
            )
        )

    tool_events = [event for event in events if event.event_type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.name == "not_registered_tool"


def test_openai_compatible_provider_waits_for_streamed_tool_arguments(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        max_retries=0,
    )
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )

    def fake_urlopen(request, timeout):
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        native_name = body["tools"][0]["function"]["name"]
        return _SseResponse(
            [
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-1",
                                            "type": "function",
                                            "function": {"name": native_name},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
                + "\n",
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"expression\\": \\"2+2\\"}"}}]},"finish_reason":"tool_calls"}]}\n',
                "data: [DONE]\n",
            ]
        )

    with mock.patch("kernel_v4.providers.urllib.request.urlopen", side_effect=fake_urlopen):
        events = asyncio.run(
            _collect(
                provider,
                messages=[ChatMessage(role="user", content="use calculator")],
                tools=[tool],
            )
        )

    tool_events = [event for event in events if event.event_type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.input == {"expression": "2+2"}


def test_openai_compatible_provider_stream_queue_has_hard_timeout(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
        timeout_seconds=1,
        max_retries=0,
    )

    def stuck_producer(*_args, **_kwargs):
        return None

    with mock.patch("kernel_v4.providers._produce_sse_chunks", side_effect=stuck_producer):
        with pytest.raises(RuntimeError, match="stream queue exceeded 1s"):
            asyncio.run(
                _collect(
                    provider,
                    messages=[ChatMessage(role="user", content="hello")],
                    tools=[],
                )
            )


def test_provider_packet_preview_does_not_expose_api_key(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-key")
    provider = OpenAICompatibleChatProvider(
        base_url="https://provider.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
        model="test-model",
    )

    preview = provider.packet_preview(
        messages=[ChatMessage(role="user", content="hello")],
        tools=[],
        system_prompt="system",
        context={"run_id": "run-1"},
    )
    dumped = json.dumps(preview, ensure_ascii=False, sort_keys=True)

    assert preview["api_key"] == "set"
    assert "secret-key" not in dumped
    assert "TEST_PROVIDER_KEY" not in dumped


def test_deepseek_provider_uses_live_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.delenv("HOLO_V4_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    provider = DeepSeekChatProvider()
    availability = provider.availability().to_dict()

    assert availability["available"] is True
    assert availability["provider"] == "deepseek"
    assert availability["model"] == "deepseek-v4-pro"
    assert availability["base_url"] == "https://api.deepseek.com/chat/completions"


def test_deepseek_provider_keeps_tool_payload_minimal_for_compatibility(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    provider = DeepSeekChatProvider(force_tool_name="calculator.compute")
    tool = ToolManifest(
        name="calculator.compute",
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )

    payload, _name_map = provider.build_payload(
        messages=[ChatMessage(role="user", content="compute 2+2")],
        tools=[tool],
        system_prompt="system",
        context={},
        stream=True,
    )

    assert "parallel_tool_calls" not in payload
    assert payload["tool_choice"]["type"] == "function"


def test_openai_native_tool_surface_v4_defers_non_always_load_tools() -> None:
    direct = ToolManifest(name="tool.discovery", description="Discover tools.", always_load=True)
    deferred = ToolManifest(name="sec.edgar.financials", description="SEC facts.", should_defer=True)

    surface = openai_native_tool_surface_v4([deferred, direct])

    assert set(surface.name_map.values()) == {"tool.discovery"}
    assert surface.deferred_tools == [{"name": "sec.edgar.financials", "description": "SEC facts."}]
