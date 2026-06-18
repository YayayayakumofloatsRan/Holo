from __future__ import annotations

import asyncio
import json
from unittest import mock

from kernel_v4.contracts import ChatMessage, ModelEvent, ToolManifest
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
    assert payload["tools"][0]["function"]["parameters"]["required"] == ["expression"]
    assert payload["messages"][0]["role"] == "system"
    assert "Runtime context" in payload["messages"][0]["content"]


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
    assert availability["model"] == "deepseek-chat"
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
