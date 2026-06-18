from __future__ import annotations

import asyncio

from kernel_v4.contracts import ChatMessage, ModelEvent, ToolCall, ToolManifest
from kernel_v4.finance_tools import register_finance_tool_surface
from kernel_v4.loop import SingleAgentLoop, SingleAgentLoopConfig
from kernel_v4.tooling import ToolRegistry


class ScriptedModel:
    def __init__(self, turns: list[list[ModelEvent]]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, object]] = []

    async def stream(self, *, messages, tools, system_prompt, context):
        self.requests.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "system_prompt": system_prompt,
                "context": dict(context),
            }
        )
        if not self.turns:
            raise AssertionError("no scripted turn left")
        for event in self.turns.pop(0):
            await asyncio.sleep(0)
            yield event


def test_kernel_v4_loop_feeds_tool_results_into_next_model_turn() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={"query": "string"}),
        lambda payload, context: {"alpha": payload["query"], "seen_messages": len(context.messages)},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(event_type="text_delta", text="I will inspect alpha."),
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha", name="alpha.read", input={"query": "revenue"}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: alpha evidence was returned and used."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("answer with alpha"))

    assert result.status == "completed"
    assert result.answer == "Final: alpha evidence was returned and used."
    assert result.tool_call_count == 1
    second_request_messages = model.requests[1]["messages"]
    assert any(isinstance(message, ChatMessage) and message.role == "tool" for message in second_request_messages)
    assert [event.event_type for event in result.events].count("tool_result") == 1


def test_kernel_v4_finance_surface_has_no_legacy_slot_bind_gate() -> None:
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=False)
    loop = SingleAgentLoop(
        model=ScriptedModel([[ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")]]),
        tools=registry,
        config=SingleAgentLoopConfig(finance_mode=True),
    )

    tool_names = {manifest.name for manifest in registry.all_manifests()}
    assert "finance.slot_bind" not in tool_names
    assert "calculator.compute" in tool_names
    assert "finance.verify_numeric" in tool_names
    assert "document.search.hybrid" in tool_names
    assert "FactLedger" not in loop.config.extra_system_prompt if loop.config.extra_system_prompt else True


def test_kernel_v4_finance_prompt_explicitly_removes_local_gates() -> None:
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=False)
    model = ScriptedModel([[ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")]])

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True),
        ).run("FinanceBench-style calculation")
    )

    assert result.status == "completed"
    system_prompt = str(model.requests[0]["system_prompt"])
    assert "There is no local FactLedger, SlotFrame, or finance.slot_bind gate" in system_prompt
    assert "call calculator.compute or data.table.query instead of mental arithmetic" in system_prompt


def test_kernel_v4_large_tool_result_is_artifact_readable() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="huge.read",
            description="Return a large payload.",
            input_schema={},
            max_result_chars=100,
        ),
        lambda payload, context: {"text": "x" * 500},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-huge", name="huge.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final after artifact replacement."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_tool_result_chars=100),
        ).run("read huge")
    )

    assert result.status == "completed"
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 1
    assert "large_tool_result_replacement" in tool_messages[0].content
    assert tool_messages[0].metadata["artifact_id"].startswith("v4-tool-result-")


def test_kernel_v4_tool_discovery_returns_contracts_not_semantic_answers() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(name="calculator.compute", description="Compute deterministic arithmetic.", input_schema={}),
        lambda payload, context: {"ok": True},
    )

    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-discovery",
                        name="tool.discovery",
                        input={"query": "calculator", "max_results": 5},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("find a calculator"))

    assert result.status == "completed"
    tool_message = next(message for message in result.messages if message.role == "tool")
    assert "calculator.compute" in tool_message.content
    assert "host_boundary" in tool_message.content
