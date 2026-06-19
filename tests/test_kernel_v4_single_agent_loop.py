from __future__ import annotations

import asyncio

from kernel_v3.context import ArtifactStore as V3ArtifactStore
from kernel_v4.contracts import ChatMessage, ModelEvent, ToolCall, ToolManifest
from kernel_v4.context import ToolUseContext
from kernel_v4.finance_tools import finance_tool_names, register_finance_tool_surface
from kernel_v4.loop import SingleAgentLoop, SingleAgentLoopConfig
from kernel_v4.runtime import AbortController, ContextEdit
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


def test_kernel_v4_final_turn_disables_tools_and_forces_answer() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha", name="alpha.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: enough evidence is available."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=2),
        ).run("answer with alpha")
    )

    assert result.status == "completed"
    assert result.answer == "Final: enough evidence is available."
    assert model.requests[0]["tools"]
    assert model.requests[1]["tools"] == []
    final_context = model.requests[1]["context"]
    assert final_context["final_turn_no_tools"] is True
    assert final_context["remaining_turns_after_this"] == 0
    assert "FINALIZATION TURN" in final_context["tool_surface"]


def test_kernel_v4_empty_final_answer_fails_instead_of_completing() -> None:
    registry = ToolRegistry()
    model = ScriptedModel([[ModelEvent(event_type="message_stop")]])

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("answer directly"))

    assert result.status == "failed"
    assert result.reason == "empty_final_answer"


def test_kernel_v4_source_saturation_checkpoint_keeps_local_artifact_endgame_tools() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(name="document.lookup", description="Lookup document evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    registry.register(
        ToolManifest(
            name="document.text.extract",
            description="Extract exact observed document text.",
            input_schema={"source": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"ok": True, "source": payload["source"]},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2},
    )
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"verified": True},
    )
    scripted_turns = []
    for index in range(24):
        scripted_turns.append(
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id=f"call-doc-{index}", name="document.lookup", input={"index": index}),
                ),
                ModelEvent(event_type="message_stop"),
            ]
        )
    scripted_turns.append(
        [
            ModelEvent(event_type="text_delta", text="Final: synthesized from accumulated document evidence."),
            ModelEvent(event_type="message_stop"),
        ]
    )
    model = ScriptedModel(scripted_turns)

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=40),
        ).run("answer from documents")
    )

    assert result.status == "completed"
    assert any(event.event_type == "source_saturation_checkpoint_inserted" for event in result.events)
    saturation_request_messages = model.requests[24]["messages"]
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "SOURCE SATURATION CHECKPOINT" in message.content
        for message in saturation_request_messages
    )
    saturation_tools = {tool.name for tool in model.requests[24]["tools"]}
    assert "document.lookup" not in saturation_tools
    assert {
        "artifact.search",
        "artifact.read",
        "document.text.extract",
        "calculator.compute",
        "finance.verify_numeric",
    }.issubset(saturation_tools)
    assert any(event.event_type == "tool_surface_narrowed" for event in result.events)


def test_kernel_v4_loop_can_omit_dynamic_model_context_for_cache() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha", name="alpha.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: enough evidence is available."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=2, model_context_mode="off"),
        ).run("answer with alpha")
    )

    assert result.status == "completed"
    assert model.requests[0]["context"] == {}
    assert model.requests[1]["context"]["final_turn_no_tools"] is True
    assert "tool_surface" not in model.requests[1]["context"]


def test_kernel_v4_skips_duplicate_tool_calls_in_same_turn() -> None:
    registry = ToolRegistry()
    calls: list[dict] = []

    def read_alpha(payload, context):
        del context
        calls.append(dict(payload))
        return {"alpha": payload["query"]}

    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={"query": "string"}),
        read_alpha,
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha-1", name="alpha.read", input={"query": "revenue"}),
                ),
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha-2", name="alpha.read", input={"query": "revenue"}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: duplicate was skipped."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("answer with alpha"))

    assert result.status == "completed"
    assert calls == [{"query": "revenue"}]
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 2
    assert any("skipped_in_turn_duplicate_tool_call" in message.content for message in tool_messages)


def test_kernel_v4_inserts_endgame_checkpoint_after_many_evidence_tools() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="document.search.hybrid", description="Search document evidence.", input_schema={"query": "string"}),
        lambda payload, context: {"query": payload["query"], "matches": [{"text": "evidence"}]},
    )
    first_turn = [
        ModelEvent(
            event_type="tool_call",
            tool_call=ToolCall(
                tool_call_id=f"call-search-{index}",
                name="document.search.hybrid",
                input={"query": f"fact {index}"},
            ),
        )
        for index in range(12)
    ]
    first_turn.append(ModelEvent(event_type="message_stop"))
    model = ScriptedModel(
        [
            first_turn,
            [
                ModelEvent(event_type="text_delta", text="Final: enough evidence."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(model_context_mode="off"),
        ).run("answer with document evidence", initial_metadata={"enable_endgame_checkpoint": True})
    )

    assert result.status == "completed"
    second_messages = model.requests[1]["messages"]
    second_tools = {tool.name for tool in model.requests[1]["tools"]}
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "ENDGAME CHECKPOINT" in message.content
        for message in second_messages
    )
    assert "document.search.hybrid" not in second_tools
    assert {"tool.discovery", "artifact.search", "artifact.read"}.issubset(second_tools)
    assert any(event.event_type == "endgame_checkpoint_inserted" for event in result.events)
    assert any(event.event_type == "endgame_tool_surface_narrowed" for event in result.events)


def test_kernel_v4_inserts_calculation_checkpoint_after_endgame_local_evidence_loop() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(
            name="document.search.hybrid",
            description="Search document evidence.",
            input_schema={"query": {"type": "str"}},
        ),
        lambda payload, context: {"query": payload["query"], "matches": [{"text": "evidence"}]},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2, "expression": payload["expression"]},
    )
    first_turn = [
        ModelEvent(
            event_type="tool_call",
            tool_call=ToolCall(
                tool_call_id=f"call-search-{index}",
                name="document.search.hybrid",
                input={"query": f"fact {index}"},
            ),
        )
        for index in range(12)
    ]
    first_turn.append(ModelEvent(event_type="message_stop"))
    local_evidence_turns = [
        [
            ModelEvent(
                event_type="tool_call",
                tool_call=ToolCall(
                    tool_call_id=f"call-artifact-{index}",
                    name="artifact.search",
                    input={"query": f"local fact {index}"},
                ),
            ),
            ModelEvent(event_type="message_stop"),
        ]
        for index in range(8)
    ]
    model = ScriptedModel(
        [
            first_turn,
            *local_evidence_turns,
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-calc",
                        name="calculator.compute",
                        input={"expression": "1+1"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="Final: computed."), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(model_context_mode="off", max_turns=40),
        ).run(
            "answer with document evidence",
            initial_metadata={"enable_endgame_checkpoint": True, "enable_calculation_checkpoint": True},
        )
    )

    assert result.status == "completed"
    calculation_request_tools = {tool.name for tool in model.requests[9]["tools"]}
    assert "calculator.compute" in calculation_request_tools
    assert "document.search.hybrid" not in calculation_request_tools
    assert {"artifact.search", "artifact.read", "tool.discovery"}.issubset(calculation_request_tools)
    calculation_messages = model.requests[9]["messages"]
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "CALCULATION CHECKPOINT" in message.content
        for message in calculation_messages
    )
    assert any(event.event_type == "calculation_checkpoint_inserted" for event in result.events)


def test_kernel_v4_repeated_source_checkpoint_narrows_external_source_tools() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(
            name="document.trafilatura.extract",
            description="Extract document text.",
            input_schema={"url": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"url": payload["url"], "text": "evidence"},
    )
    registry.register(
        ToolManifest(
            name="artifact.read",
            description="Read artifact evidence.",
            input_schema={"artifact_id": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"artifact_id": payload["artifact_id"], "text": "local evidence"},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-extract-1",
                        name="document.trafilatura.extract",
                        input={"url": "https://example.com/1"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-extract-2",
                        name="document.trafilatura.extract",
                        input={"url": "https://example.com/2"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-extract-3",
                        name="document.trafilatura.extract",
                        input={"url": "https://example.com/3"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: source evidence is sufficient."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=8),
        ).run(
            "answer from source evidence",
            initial_metadata={"enable_repeated_source_checkpoint": True, "repeated_source_success_threshold": 3},
        )
    )

    assert result.status == "completed"
    fourth_request_tools = {tool.name for tool in model.requests[3]["tools"]}
    assert "document.trafilatura.extract" not in fourth_request_tools
    assert {"artifact.read", "artifact.search", "calculator.compute"}.issubset(fourth_request_tools)
    assert any(event.event_type == "repeated_source_checkpoint_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "REPEATED SOURCE CHECKPOINT" in message.content
        for message in model.requests[3]["messages"]
    )


def test_kernel_v4_post_verify_checkpoint_disables_tools_for_final_answer() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "2"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: verified answer is 2."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=6),
        ).run("verify then finalize")
    )

    assert result.status == "completed"
    assert model.requests[1]["tools"] == []
    assert model.requests[1]["context"]["force_finalization_no_tools"] is True
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "POST-VERIFY FINALIZATION CHECKPOINT" in message.content
        for message in model.requests[1]["messages"]
    )
    assert any(event.event_type == "post_verify_finalization_checkpoint_inserted" for event in result.events)


def test_kernel_v4_post_verify_checkpoint_ignores_not_applicable_verifier() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {
            "status": "ok",
            "content": {
                "verifier_status": "not_applicable",
                "verification": {
                    "status": "not_applicable",
                    "diagnostics": {"reason": "answer_contains_no_material_numeric_values"},
                },
                "matched_value_count": 0,
                "answer": payload["answer"],
            },
        },
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "unable to determine"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="I cannot determine the answer from the available evidence."),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: the exact source-backed amount is still missing from the observed evidence.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=4),
        ).run("verify then fail honestly")
    )

    assert result.status == "completed"
    assert model.requests[1]["tools"] != []
    assert model.requests[1]["context"]["force_finalization_no_tools"] is False
    assert not any(event.event_type == "post_verify_finalization_checkpoint_inserted" for event in result.events)
    assert any(event.event_type == "generic_failure_final_answer_recovery_inserted" for event in result.events)
    assert not any(event.event_type == "verified_numeric_generic_failure_recovery_inserted" for event in result.events)


def test_kernel_v4_verified_numeric_generic_failure_gets_recovery_turn() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "0.54"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Unable to compute the requested ratio from the available filing."),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: the verified retention ratio is 0.54."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("verify then answer")
    )

    assert result.status == "completed"
    assert result.answer == "Final: the verified retention ratio is 0.54."
    assert model.requests[2]["tools"] == []
    assert any(event.event_type == "verified_numeric_generic_failure_recovery_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "VERIFIED NUMERIC FINALIZATION CONSISTENCY RECOVERY" in message.content
        for message in model.requests[2]["messages"]
    )


def test_kernel_v4_verified_numeric_generic_failure_fails_after_recovery() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "0.54"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Unable to compute the requested ratio from the available filing."),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="I cannot determine the answer."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("verify then answer")
    )

    assert result.status == "failed"
    assert result.reason == "generic_failure_after_verified_numeric_final_answer"


def test_kernel_v4_generic_extract_failure_reopens_tool_surface() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="document.text.extract",
            description="Extract exact observed document text.",
            input_schema={"source": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"text": "Company secured $13.2 billion in cash proceeds."},
    )
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="I was unable to extract the target filing text with the current tool surface.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-extract",
                        name="document.text.extract",
                        input={"source": "https://www.sec.gov/Archives/example/ex991.htm"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "cash proceeds were $13.2 billion"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: cash proceeds were $13.2 billion."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("find cash proceeds")
    )

    assert result.status == "completed"
    assert result.answer == "Final: cash proceeds were $13.2 billion."
    assert {tool.name for tool in model.requests[1]["tools"]} >= {"document.text.extract", "finance.verify_numeric"}
    assert any(event.event_type == "generic_failure_final_answer_recovery_inserted" for event in result.events)


def test_kernel_v4_finance_final_answer_cleanliness_recovery_removes_process_narration() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Now I have all the numbers. Let me provide the final answer. The answer is yes.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="text_delta", text="Final: the answer is yes, supported by the observed evidence."),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=4),
        ).run("answer cleanly")
    )

    assert result.status == "completed"
    assert result.answer == "Final: the answer is yes, supported by the observed evidence."
    assert model.requests[1]["tools"] == []
    assert any(event.event_type == "final_answer_cleanliness_recovery_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "FINAL ANSWER CLEANLINESS RECOVERY" in message.content
        for message in model.requests[1]["messages"]
    )


def test_kernel_v4_finance_final_answer_cleanliness_recovery_requires_self_contained_answer() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="calculator.compute", description="Compute arithmetic.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"verified": True, "answer": payload["answer"]},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text=(
                        "The verifier flagged a ledger-binding issue but the underlying source evidence "
                        "and arithmetic are sound. The answer stands as above."
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text=(
                        "Final: revenue decreased by $42 million, or 2%, based on the observed filing table."
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "revenue decreased by $42 million, or 2%"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text=(
                        "Final: revenue decreased by $42 million, or 2%, based on the observed filing table."
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("answer cleanly")
    )

    assert result.status == "completed"
    assert "$42 million" in result.answer
    assert {tool.name for tool in model.requests[1]["tools"]} >= {"finance.verify_numeric"}
    assert any(event.event_type == "final_answer_cleanliness_recovery_inserted" for event in result.events)
    assert any(event.event_type == "numeric_verification_checkpoint_inserted" for event in result.events)
    assert any(event.event_type == "post_verify_finalization_checkpoint_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "self-contained" in message.content
        for message in model.requests[1]["messages"]
    )


def test_kernel_v4_finance_final_answer_cleanliness_recovers_task_complete_shell() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": False, "issue_count": 1},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: cash declined by $781 million, or 41.7%, from $1,874 million to $1,093 million.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="The task is complete. Answer provided with direct evidence from the filing.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: cash declined by $781 million, or 41.7%, from $1,874 million to $1,093 million.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=5),
        ).run("answer cleanly")
    )

    assert result.status == "completed"
    assert "$781 million" in result.answer
    assert "41.7%" in result.answer
    assert any(event.event_type == "numeric_verification_checkpoint_inserted" for event in result.events)
    assert any(event.event_type == "final_answer_cleanliness_recovery_inserted" for event in result.events)


def test_kernel_v4_finance_final_answer_cleanliness_retries_repeated_shells() -> None:
    registry = ToolRegistry()
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="The above answer is supported by direct observations. No further corrections are needed.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="My final answer is complete and self-contained above.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: yes, the observed filing evidence supports the conclusion.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=5),
        ).run("answer cleanly")
    )

    recovery_events = [event for event in result.events if event.event_type == "final_answer_cleanliness_recovery_inserted"]
    assert result.status == "completed"
    assert result.answer == "Final: yes, the observed filing evidence supports the conclusion."
    assert len(recovery_events) == 2
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "RECOVERY ATTEMPT 2" in message.content
        for message in model.requests[2]["messages"]
    )


def test_kernel_v4_finance_coverage_checkpoint_blocks_single_working_capital_basis() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read additional evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: yes, standard working capital is positive based on current assets less current liabilities.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text=(
                        "Final: yes. Standard net working capital is positive, and operating/non-cash working "
                        "capital should also be computed from the current operating asset and liability components."
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=4),
        ).run(
            "Does Corning have positive working capital based on FY2022 data?",
            initial_metadata={
                "task_question": "Does Corning have positive working capital based on FY2022 data?",
                "force_finalization_no_tools": True,
            },
        )
    )

    assert result.status == "completed"
    assert "operating/non-cash working capital" in result.answer
    assert model.requests[0]["tools"] == []
    assert {tool.name for tool in model.requests[1]["tools"]} >= {"alpha.read"}
    assert any(event.event_type == "finance_answer_coverage_checkpoint_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "Working-capital/liquidity" in message.content
        for message in model.requests[1]["messages"]
    )


def test_kernel_v4_no_tool_finalization_recovers_from_text_tool_call_markup() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"result": 2},
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="calculator.compute">\n'
        '<｜｜DSML｜｜invoke name="expression">1+1</｜｜DSML｜｜invoke>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "2"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")],
            [ModelEvent(event_type="text_delta", text="Final: verified answer is 2."), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=6),
        ).run("verify then finalize")
    )

    assert result.status == "completed"
    assert result.answer == "Final: verified answer is 2."
    assert model.requests[1]["tools"] == []
    assert model.requests[2]["tools"] == []
    assert any(event.event_type == "no_tool_text_tool_call_recovery_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "FINALIZATION FORMAT RECOVERY" in message.content
        for message in model.requests[2]["messages"]
    )


def test_kernel_v4_no_tool_finalization_extracts_answer_from_verify_text_tool_call() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="finance_verify_numeric_14bb29b6">\n'
        '<｜｜DSML｜｜parameter name="answer" string="true">'
        "No, FY2022 revenue growth was only 1.2%, so the company was not high growth."
        "</｜｜DSML｜｜parameter>\n"
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "1.2%"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("verify then finalize")
    )

    assert result.status == "completed"
    assert result.answer == "No, FY2022 revenue growth was only 1.2%, so the company was not high growth."
    assert any(event.event_type == "text_tool_call_final_answer_extracted" for event in result.events)
    assert result.messages[-1].metadata["extracted_from_no_tool_text_tool_call"] is True


def test_kernel_v4_no_tool_finalization_does_not_complete_with_tool_markup() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="calculator_compute_1052e069">\n'
        '<｜｜DSML｜｜parameter name="expression" string="true">(2438 - 2320)</｜｜DSML｜｜parameter>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "118"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")],
            [ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(max_turns=3),
        ).run("verify then emit bad final markup")
    )

    assert result.status == "failed"
    assert result.reason == "final_answer_is_tool_call_markup"
    assert result.answer == ""
    assert any(event.event_type == "no_tool_text_tool_call_recovery_inserted" for event in result.events)


def test_kernel_v4_finance_numeric_final_answer_requires_verifier_checkpoint() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: working capital is positive at $2,278 million.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify",
                        name="finance.verify_numeric",
                        input={"answer": "$2,278 million positive working capital"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: verified working capital is positive at $2,278 million.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=6),
        ).run("answer a finance numeric question")
    )

    assert result.status == "completed"
    assert result.tool_call_count == 1
    assert result.answer == "Final: verified working capital is positive at $2,278 million."
    assert any(event.event_type == "numeric_verification_checkpoint_inserted" for event in result.events)
    assert any(
        isinstance(message, ChatMessage)
        and message.role == "system"
        and "NUMERIC VERIFICATION CHECKPOINT" in message.content
        for message in model.requests[1]["messages"]
    )


def test_kernel_v4_finance_unsupported_numeric_source_reopens_tools() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="finance.verify_numeric",
            description="Verify final numeric answer.",
            input_schema={"answer": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "verified": True, "answer": payload["answer"]},
    )
    registry.register(
        ToolManifest(
            name="artifact.search",
            description="Search source artifacts.",
            input_schema={"query": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"status": "ok", "snippet": "source-backed PP&E is present"},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify-1",
                        name="finance.verify_numeric",
                        input={"answer": "20.04"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text=(
                        "Final: fixed asset turnover is 20.04. Limitation note: the PP&E values are "
                        "from my recall and were not directly observed: $10,320 million and $9,099 million."
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-search",
                        name="artifact.search",
                        input={"query": "PP&E balance sheet"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-verify-2",
                        name="finance.verify_numeric",
                        input={"answer": "20.04 with source-backed PP&E"},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="text_delta",
                    text="Final: fixed asset turnover is 20.04, using source-backed PP&E values.",
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    result = asyncio.run(
        SingleAgentLoop(
            model=model,
            tools=registry,
            config=SingleAgentLoopConfig(finance_mode=True, max_turns=8),
        ).run("answer a finance numeric question with source-backed values")
    )

    assert result.status == "completed"
    assert result.tool_call_count == 3
    assert any(event.event_type == "unsupported_numeric_source_recovery_inserted" for event in result.events)
    assert any(message.role == "tool" and message.name == "artifact.search" for message in result.messages)
    assert "from my recall" not in result.answer


def test_kernel_v4_loop_emits_model_usage_for_cache_monitoring() -> None:
    registry = ToolRegistry()
    model = ScriptedModel(
        [
            [
                ModelEvent(event_type="text_delta", text="done"),
                ModelEvent(
                    event_type="message_stop",
                    metadata={
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 5,
                            "total_tokens": 105,
                            "cache": {
                                "prompt_cache_hit_tokens": 75,
                                "prompt_cache_miss_tokens": 25,
                                "cache_hit_rate": 0.75,
                            },
                        }
                    },
                ),
            ]
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("answer"))

    assert result.status == "completed"
    usage_events = [event for event in result.events if event.event_type == "model_usage"]
    assert len(usage_events) == 1
    assert usage_events[0].data["prompt_tokens"] == 100
    assert usage_events[0].data["cache"]["cache_hit_rate"] == 0.75
    stop_events = [event for event in result.events if event.event_type == "assistant_message_stop"]
    assert stop_events[0].data["usage"]["cache"]["prompt_cache_hit_tokens"] == 75


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
    assert "Benchmark gold/reference answers are never part of your context" in system_prompt
    assert "Public-filing questions: use sec.edgar.company_filings" in system_prompt
    assert "document.text.extract" in system_prompt
    assert "Docling is slow/fails" in system_prompt
    assert "Provided-context FQA/FinQA questions: use provided_context.parse before external retrieval" in system_prompt
    assert "use returned text_blocks/tables directly" in system_prompt
    assert "Store-count, location-count, branch-count" in system_prompt
    assert "Do not drift to market data for store-count questions" in system_prompt
    assert "cash consideration or purchase price when disclosed" in system_prompt
    assert "ownership percentages such as \"100% equity interest\" as a substitute" in system_prompt
    assert "calendar.days_between for actual day counts" in system_prompt
    assert "Do not stop merely because one tool failed" in system_prompt
    assert "tool.discovery with a focused query" in system_prompt
    assert "Do not repeat the same successful read, parse, discovery, or retrieval tool call" in system_prompt
    assert "Never call a tool with empty arguments when its schema has required fields" in system_prompt
    assert 'For provided_context.parse, prefer {"context_ref":"task_provided_context"}' in system_prompt
    assert "Before every additional retrieval/read/search/source tool call" in system_prompt
    assert "If no exact missing fact remains, stop retrieval" in system_prompt
    assert "call document.docling.convert again on the original source" in system_prompt
    assert "Final answers must be concise task answers, not repeated planning text" in system_prompt
    assert "Margin-change and driver-analysis questions" in system_prompt
    assert "Gross-margin profile questions" in system_prompt
    assert "directly reported gross profit/subtotal" in system_prompt
    assert "Normalize sign conventions explicitly" in system_prompt
    assert "Do not mix parentheses/negative display with a subtraction formula" in system_prompt
    assert "Primary-customer, customer-concentration, major-customer" in system_prompt
    assert "Preserve any disclosed revenue share, concentration percentage" in system_prompt
    assert "For primary-customer answers" in system_prompt
    assert "Legal battle, legal proceedings, litigation" in system_prompt
    assert "settlement amounts, accruals, or ranges of loss" in system_prompt
    assert "A ratio change alone is not a driver explanation" in system_prompt
    assert "percent change from the prior/base value" in system_prompt
    assert "Revenue-threshold category questions" in system_prompt
    assert "Do not answer with only one qualifying example" in system_prompt
    assert "provide a compact table of every qualifying category" in system_prompt
    assert "Segment-growth or \"excluding M&A\" questions" in system_prompt
    assert "Worldwide Sales Change" in system_prompt
    assert "Shareholder vote, board nominee" in system_prompt
    assert "Votes Against" in system_prompt
    assert "Liquidity, working-capital, or quick-ratio questions" in system_prompt
    assert "operating/non-cash working capital" in system_prompt
    assert "(current assets - inventories) / current liabilities" in system_prompt
    assert "Liquidation, bankruptcy-recovery, book-value-per-share" in system_prompt
    assert "Do not finalize from book value per common share" in system_prompt
    assert "tangible book value per common share" in system_prompt
    assert "Dividend, shareholder-distribution, stability/trend" in system_prompt
    assert "quarterly cash dividend" in system_prompt
    assert "Do not confuse dividends paid by regulated subsidiaries" in system_prompt
    assert "consecutive years" in system_prompt
    assert "annual dividend" in system_prompt
    assert "Capital-intensity or asset-intensity questions" in system_prompt
    assert "PP&E/revenue" in system_prompt
    assert "Do not introduce generic industry threshold numbers" in system_prompt
    assert "prefer GAAP net income divided by total assets" in system_prompt
    assert "do not answer that it is capital-intensive merely because capex or PP&E is nonzero" in system_prompt
    assert "final answer should not contain unsupported threshold phrases" in system_prompt
    assert "self-edit the final text to remove unsourced industry benchmark numbers" in system_prompt
    assert "For yes/no business-characterization questions" in system_prompt


def test_kernel_v4_finance_toolchain_describe_covers_fb_fqa_tool_families() -> None:
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=True)
    registry.install_core_tools()

    tool_names = {manifest.name for manifest in registry.all_manifests()}
    assert set(finance_tool_names()).issubset(tool_names)
    assert {"artifact.read", "tool.discovery"}.issubset(tool_names)
    assert "finance.slot_bind" not in tool_names

    message = asyncio.run(
        registry.execute(
            ToolCall(tool_call_id="call-describe", name="finance.toolchain.describe", input={}),
            ToolUseContext(run_id="run-finance-describe", thread_key="test"),
        )
    )

    assert message.is_error is False
    content = message.content
    assert isinstance(content, dict)
    assert content["schema"] == "holo.kernel_v4.finance_toolchain.v1"
    assert content["decision_owner"] == "model"
    assert "finance.slot_bind" in content["removed_legacy_gates"]
    contract = content["one_shot_loop_contract"]
    assert contract["host_role"] == "validate_execute_record_compact_only"
    assert "model-requested tool calls" in contract["tool_use_boundary"]
    assert "Gold/reference answers are not model context" in contract["no_gold_policy"]
    assert "finance.verify_numeric" in contract["stop_rule"]
    required_elements = contract["answer_output_contract"]["required_elements"]
    forbidden_elements = contract["answer_output_contract"]["forbidden_elements"]
    assert any("net income / total assets as ROA" in item for item in required_elements)
    assert any("unsourced generic industry threshold" in item for item in forbidden_elements)
    assert any("typically/often industry benchmark percentages" in item for item in forbidden_elements)
    assert any("do not repeat the same call" in item for item in content["tool_protocol"])
    assert any("context_ref='task_provided_context'" in item for item in content["tool_protocol"])
    assert any("call document.docling.convert again on the original source" in item for item in content["tool_protocol"])
    assert any("official SEC complete-submission text" in item for item in content["tool_protocol"])
    coverage = {item["family"]: set(item["primary_tools"]) for item in content["coverage_families"]}
    assert {"sec.edgar.financials", "document.search.hybrid", "artifact.read"}.issubset(
        coverage["public_filing_evidence"]
    )
    assert {"document.search.hybrid", "artifact.search", "calculator.compute"}.issubset(
        coverage["gross_margin_profile"]
    )
    assert {"provided_context.parse", "data.table.query", "calculator.compute"}.issubset(
        coverage["provided_context_fqa_finqa"]
    )
    assert {"calendar.days_between", "calculator.compute"}.issubset(coverage["fiscal_dates"])
    assert {"calculator.compute", "data.table.query", "math.sympy.compute"}.issubset(
        coverage["finance_transforms"]
    )
    assert {"document.search.hybrid", "data.table.query", "calculator.compute"}.issubset(
        coverage["margin_driver_bridge"]
    )
    assert {"document.search.hybrid", "data.table.query", "calculator.compute"}.issubset(
        coverage["segment_growth_mna_exclusion"]
    )
    assert {"document.docling.convert", "document.search.hybrid", "artifact.read", "calculator.compute"}.issubset(
        coverage["liquidity_quick_ratio"]
    )
    assert {"document.docling.convert", "document.search.hybrid", "artifact.read", "calculator.compute"}.issubset(
        coverage["dividend_stability_trend"]
    )
    assert coverage["numeric_verification"] == {"finance.verify_numeric"}


def test_kernel_v4_finance_workbench_open_returns_task_family_contracts() -> None:
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=True)
    registry.install_core_tools()
    context = ToolUseContext(run_id="run-finance-workbench", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-finance-workbench",
                name="finance.workbench.open",
                input={"query": "compare inventory efficiency DIO for two companies", "max_profiles": 4},
            ),
            context,
        )
    )

    assert message.is_error is False
    content = message.content
    assert content["schema"] == "holo.kernel_v4.finance_workbench.v1"
    assert content["global_contract"]["decision_owner"] == "model"
    families = {profile["family"] for profile in content["selected_profiles"]}
    assert "inventory_efficiency_dio" in families
    inventory_profile = next(profile for profile in content["selected_profiles"] if profile["family"] == "inventory_efficiency_dio")
    assert "calculator.compute" in inventory_profile["primary_tools"]
    assert "artifact.search" in inventory_profile["primary_tools"]
    assert any("average inventory" in item for item in inventory_profile["required_evidence"])
    assert "calculator.compute" in context.metadata["discovered_tool_names"]
    assert "artifact.search" in context.metadata["discovered_tool_names"]
    assert "semantic decisions remain with the model" in content["host_boundary"]


def test_kernel_v4_finance_artifact_search_reads_delegated_artifact_store() -> None:
    artifact_store = V3ArtifactStore.in_memory()
    artifact = artifact_store.write_blob(
        kind="filing-document",
        payload="Annual report excerpt. The company has increased its annual dividend for 65 consecutive years.",
        metadata={"source": "unit-regression"},
    )
    registry = ToolRegistry()
    register_finance_tool_surface(registry, allow_network=False, artifact_store=artifact_store)
    registry.install_core_tools()
    context = ToolUseContext(run_id="run-finance-artifact", thread_key="test")

    inspected = asyncio.run(
        registry.execute(
            ToolCall(tool_call_id="call-inspect", name="artifact.inspect", input={"max_items": 5}),
            context,
        )
    )
    assert inspected.is_error is False
    delegated_ids = {item["artifact_id"] for item in inspected.content["delegated_artifacts"]}
    assert artifact.artifact_id in delegated_ids

    searched = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-search",
                name="artifact.search",
                input={"query": "consecutive years dividend", "max_matches": 3},
            ),
            context,
        )
    )
    assert searched.is_error is False
    assert searched.content["matches"][0]["artifact_id"] == artifact.artifact_id
    assert "65 consecutive years" in searched.content["matches"][0]["snippet"]

    read = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-read",
                name="artifact.read",
                input={"artifact_id": artifact.artifact_id, "start": 0, "max_chars": 120},
            ),
            context,
        )
    )
    assert read.is_error is False
    assert read.content["source"] == "delegated_finance_artifact_store"
    assert "annual dividend" in read.content["text"]


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


def test_kernel_v4_artifact_lifecycle_inspect_search_and_window_read() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    context = ToolUseContext(run_id="run-artifact-lifecycle", thread_key="test")
    artifact_id = context.store_artifact(
        kind="filing",
        content="Balance sheet excerpt\nRevenue was 123.\nOperating income was 45.\n",
    )
    duplicate_id = context.store_artifact(
        kind="filing",
        content="Balance sheet excerpt\nRevenue was 123.\nOperating income was 45.\n",
    )

    assert duplicate_id == artifact_id
    assert context.artifact_records[artifact_id]["store_hits"] == 2
    assert any(edit.operation == "artifact.cache_hit" for edit in context.context_edits)

    inspected = asyncio.run(
        registry.execute(
            ToolCall(tool_call_id="call-inspect", name="artifact.inspect", input={"artifact_id": artifact_id}),
            context,
        )
    )
    assert inspected.is_error is False
    assert inspected.content["schema"] == "holo.kernel_v4.artifact_inspect_result.v1"
    assert inspected.content["kernel_v4_artifacts"][0]["artifact_id"] == artifact_id
    assert inspected.content["kernel_v4_artifacts"][0]["sha256"]

    searched = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-search",
                name="artifact.search",
                input={"artifact_id": artifact_id, "query": "operating income", "max_matches": 3},
            ),
            context,
        )
    )
    assert searched.is_error is False
    assert searched.content["matches"]
    assert "Operating income" in searched.content["matches"][0]["snippet"]

    start = max(0, searched.content["matches"][0]["start"])
    read = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-read",
                name="artifact.read",
                input={"artifact_id": artifact_id, "start": start, "max_chars": 100},
            ),
            context,
        )
    )
    assert read.is_error is False
    assert read.content["start"] == start
    assert "Operating income" in read.content["text"]
    assert context.artifact_records[artifact_id]["read_hits"] >= 1


def test_kernel_v4_artifact_read_default_is_bounded_window() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    context = ToolUseContext(run_id="run-bounded-artifact-read", thread_key="test")
    artifact_id = context.store_artifact(kind="test", content="x" * 12_000)

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-bounded-read",
                name="artifact.read",
                input={"artifact_id": artifact_id},
            ),
            context,
        )
    )

    assert message.is_error is False
    assert message.content["end"] == 8_000
    assert len(message.content["text"]) == 8_000
    assert message.content["truncated"] is True
    assert "bounded window" in message.content["instruction"]


def test_kernel_v4_tool_workbench_groups_tools_and_marks_discovered() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "string", "required": True}},
            should_defer=True,
            always_load=False,
        ),
        lambda payload, context: {"ok": True},
    )
    context = ToolUseContext(run_id="run-tool-workbench", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-workbench",
                name="tool.workbench",
                input={"query": "calculate ratio using calculator", "max_tools": 10},
            ),
            context,
        )
    )

    assert message.is_error is False
    assert message.content["schema"] == "holo.kernel_v4.tool_workbench.v1"
    selected_names = {tool["name"] for tool in message.content["selected_tools"]}
    assert "calculator.compute" in selected_names
    family_names = {family["family"] for family in message.content["selected_families"]}
    assert "transform_compute" in family_names
    assert "calculator.compute" in context.metadata["discovered_tool_names"]


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


def test_kernel_v4_tool_discovery_respects_active_tool_surface_allowlist() -> None:
    registry = ToolRegistry()
    registry.install_core_tools()
    registry.register(
        ToolManifest(
            name="sec.edgar.financials",
            description="Retrieve SEC financial facts.",
            input_schema={"ticker": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"unused": True},
    )
    registry.register(
        ToolManifest(
            name="calculator.compute",
            description="Compute deterministic arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
        ),
        lambda payload, context: {"unused": True},
    )
    context = ToolUseContext(run_id="run-allowlist")
    context.metadata["tool_surface_allowlist"] = ["tool.discovery", "calculator.compute"]

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-discovery",
                name="tool.discovery",
                input={"query": "sec edgar calculator", "max_results": 10},
            ),
            context,
        )
    )

    assert message.is_error is False
    discovered_names = {tool["name"] for tool in message.content["tools"]}
    assert "calculator.compute" in discovered_names
    assert "sec.edgar.financials" not in discovered_names
    assert message.content["active_tool_surface_allowlist"] == ["calculator.compute", "tool.discovery"]

    blocked_visible_tool = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-blocked-visible",
                name="sec.edgar.financials",
                input={"ticker": "ADBE"},
            ),
            context,
        )
    )

    assert blocked_visible_tool.is_error is True
    assert blocked_visible_tool.content["error"] == "tool_not_in_active_surface"
    assert blocked_visible_tool.content["tool"] == "sec.edgar.financials"
    assert blocked_visible_tool.content["active_tool_surface_allowlist"] == ["calculator.compute", "tool.discovery"]

    alias_blocked_message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-alias-blocked",
                name="sec_edgar_financials_0fff6646",
                input={"ticker": "ADBE"},
            ),
            context,
        )
    )

    assert alias_blocked_message.is_error is True
    assert alias_blocked_message.content["error"] == "tool_not_in_active_surface"
    assert alias_blocked_message.content["tool"] == "sec.edgar.financials"
    assert alias_blocked_message.content["requested_tool"] == "sec_edgar_financials_0fff6646"
    assert alias_blocked_message.content["active_tool_surface_allowlist"] == ["calculator.compute", "tool.discovery"]
    assert "previously visible source-tool aliases" in alias_blocked_message.content["instruction"]


def test_kernel_v4_tool_registry_executes_unique_native_tool_alias_when_allowed() -> None:
    registry = ToolRegistry()
    calls: list[dict] = []

    def sec_financials(payload, context):
        del context
        calls.append(dict(payload))
        return {"ticker": payload["ticker"]}

    registry.register(
        ToolManifest(
            name="sec.edgar.financials",
            description="Retrieve SEC financial facts.",
            input_schema={"ticker": {"type": "str", "required": True}},
        ),
        sec_financials,
    )
    context = ToolUseContext(run_id="run-native-alias")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-native-alias",
                name="sec_edgar_financials_0fff6646",
                input={"ticker": "ADBE"},
            ),
            context,
        )
    )

    assert message.is_error is False
    assert message.name == "sec.edgar.financials"
    assert calls == [{"ticker": "ADBE"}]


def test_kernel_v4_workflow_events_are_exposed_while_loop_runs() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha evidence.", input_schema={}),
        lambda payload, context: {"ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha", name="alpha.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )
    workflow_events: list[str] = []

    result = asyncio.run(
        SingleAgentLoop(model=model, tools=registry).run(
            "read alpha",
            workflow_event_handler=lambda event: workflow_events.append(event.event_type),
        )
    )

    assert result.status == "completed"
    assert "model_turn_start" in workflow_events
    assert "assistant_tool_call" in workflow_events
    assert "tool_queued" in workflow_events
    assert "tool_start" in workflow_events
    assert "tool_result" in workflow_events
    assert "loop_completed" in workflow_events


def test_kernel_v4_model_stream_error_returns_failed_result() -> None:
    class FailingModel:
        async def stream(self, *, messages, tools, system_prompt, context):
            del messages, tools, system_prompt, context
            raise RuntimeError("provider timed out")
            yield  # pragma: no cover

    result = asyncio.run(SingleAgentLoop(model=FailingModel(), tools=ToolRegistry()).run("hello"))

    assert result.status == "failed"
    assert result.reason == "model_stream_error:RuntimeError:provider timed out"
    assert any(event.event_type == "loop_failed" and event.data["reason"] == result.reason for event in result.events)


def test_kernel_v4_abort_cancels_running_tool_with_synthetic_result() -> None:
    registry = ToolRegistry()
    abort_controller = AbortController()

    async def slow_tool(payload, context: ToolUseContext):
        del payload, context
        await asyncio.sleep(60)
        return {"unexpected": True}

    registry.register(
        ToolManifest(name="slow.read", description="Slow read.", input_schema={}),
        slow_tool,
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-slow", name="slow.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
        ]
    )

    def abort_on_tool_start(event):
        if event.event_type == "tool_start":
            abort_controller.abort("test_cancel")

    result = asyncio.run(
        SingleAgentLoop(model=model, tools=registry).run(
            "read slowly",
            abort_controller=abort_controller,
            workflow_event_handler=abort_on_tool_start,
        )
    )

    assert result.status == "aborted"
    assert result.reason == "test_cancel"
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 1
    assert "tool_cancelled" in tool_messages[0].content
    assert "test_cancel" in tool_messages[0].content
    assert tool_messages[0].metadata["cancelled"] is True


def test_kernel_v4_context_edit_is_visible_to_next_model_turn() -> None:
    registry = ToolRegistry()

    def edit_context(payload, context: ToolUseContext):
        del payload
        context.apply_edit(ContextEdit(operation="metadata.set", key="company", value="HD", source="test.tool"))
        return {"edited": True}

    registry.register(
        ToolManifest(name="context.edit", description="Edit runtime context.", input_schema={}),
        edit_context,
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-edit", name="context.edit", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("edit context"))

    assert result.status == "completed"
    second_context = model.requests[1]["context"]
    assert isinstance(second_context, dict)
    workflow = second_context["workflow"]
    assert workflow["context_edit_count"] >= 1
    assert "company" in workflow["context_metadata_keys"]
    assert any(edit["operation"] == "metadata.set" for edit in workflow["context_edits_recent"])


def test_kernel_v4_recent_successful_tool_calls_are_visible_to_next_model_turn() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha.", input_schema={"query": {"type": "str"}}),
        lambda payload, context: {"query": payload["query"], "ok": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha", name="alpha.read", input={"query": "revenue"}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("read alpha"))

    assert result.status == "completed"
    second_context = model.requests[1]["context"]
    assert second_context["remaining_turns_after_this"] >= 0
    assert second_context["remaining_tool_calls"] >= 0
    assert "supported final answer" in second_context["endgame_policy"]
    assert "Do not repeat the same successful tool" in second_context["repeat_tool_call_policy"]
    recent_tool_calls = second_context["recent_tool_calls"]
    assert '"query": {"type": "str"}' in second_context["tool_surface"]
    assert recent_tool_calls["successful"][0]["tool"] == "alpha.read"
    assert recent_tool_calls["successful"][0]["status"] == "success"
    assert '"query": "revenue"' in recent_tool_calls["successful"][0]["input_preview"]
    assert '"ok": true' in recent_tool_calls["successful"][0]["result_preview"]
    assert second_context["tool_progress_summary"]["successful_family_counts"]["evidence"] == 1


def test_kernel_v4_duplicate_successful_tool_call_is_skipped_with_observation() -> None:
    registry = ToolRegistry()
    executions = 0

    def read_alpha(payload, context):
        nonlocal executions
        del context
        executions += 1
        return {"query": payload["query"], "ok": True}

    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha.", input_schema={"query": {"type": "str"}}),
        read_alpha,
    )
    repeated_call = ToolCall(tool_call_id="call-alpha-2", name="alpha.read", input={"query": "revenue"})
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha-1", name="alpha.read", input={"query": "revenue"}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(event_type="tool_call", tool_call=repeated_call),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("read alpha"))

    assert result.status == "completed"
    assert executions == 1
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert "duplicate_successful_tool_call" in tool_messages[1].content
    assert tool_messages[1].metadata["is_error"] is True
    assert tool_messages[1].metadata["duplicate_successful_tool_call"] is True


def test_kernel_v4_blocked_tool_result_is_error_and_not_duplicate_success() -> None:
    registry = ToolRegistry()
    executions = 0

    def blocked_read(payload, context):
        nonlocal executions
        del context
        executions += 1
        return {
            "schema": "test.blocked_tool.v1",
            "status": "blocked",
            "content": {"error": "missing_required_field:query", "received": payload},
        }

    registry.register(
        ToolManifest(name="alpha.read", description="Read alpha.", input_schema={"query": {"type": "str"}}),
        blocked_read,
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha-1", name="alpha.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-alpha-2", name="alpha.read", input={}),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("read alpha"))

    assert result.status == "completed"
    assert executions == 2
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 2
    assert all(message.metadata["is_error"] is True for message in tool_messages)
    assert all("duplicate_successful_tool_call" not in message.content for message in tool_messages)


def test_kernel_v4_dsml_text_tool_call_fallback_executes_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="tool.discovery", description="Discover tools.", input_schema={"query": {"type": "str"}}),
        lambda payload, context: {"query": payload["query"], "ok": True},
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="tool.discovery">\n'
        '<｜｜DSML｜｜invoke name="query">select:calculator.compute</｜｜DSML｜｜invoke>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = ScriptedModel(
        [
            [ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("discover calculator"))

    assert result.status == "completed"
    assert result.tool_call_count == 1
    assistant_messages = [message for message in result.messages if message.role == "assistant"]
    assert assistant_messages[0].content == ""
    assert assistant_messages[0].tool_calls[0].name == "tool.discovery"
    assert assistant_messages[0].tool_calls[0].input == {"query": "select:calculator.compute"}
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert '"query": "select:calculator.compute"' in tool_messages[0].content
    assert any(event.data.get("source") == "text_tool_call_fallback" for event in result.events)


def test_kernel_v4_dsml_text_tool_call_fallback_preserves_unavailable_tool_text() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(name="tool.discovery", description="Discover tools.", input_schema={"query": {"type": "str"}}),
        lambda payload, context: {"query": payload["query"], "ok": True},
    )
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="hidden.tool">\n'
        '<｜｜DSML｜｜invoke name="query">value</｜｜DSML｜｜invoke>\n'
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    model = ScriptedModel([[ModelEvent(event_type="text_delta", text=dsml), ModelEvent(event_type="message_stop")]])

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("try hidden tool"))

    assert result.status == "completed"
    assert result.answer == dsml
    assert result.tool_call_count == 0
    assert not any(event.data.get("source") == "text_tool_call_fallback" for event in result.events)


def test_kernel_v4_starts_streamed_tool_before_model_stream_finishes() -> None:
    async def run_case() -> tuple[object, bool]:
        registry = ToolRegistry()
        tool_started = asyncio.Event()

        async def slow_tool(payload, context: ToolUseContext):
            del payload, context
            tool_started.set()
            await asyncio.sleep(0)
            return {"ok": True}

        class BlockingAfterToolCallModel:
            def __init__(self) -> None:
                self.tool_started_before_stream_end = False
                self.turn_count = 0

            async def stream(self, *, messages, tools, system_prompt, context):
                del messages, tools, system_prompt, context
                self.turn_count += 1
                if self.turn_count > 1:
                    yield ModelEvent(event_type="text_delta", text="final")
                    yield ModelEvent(event_type="message_stop")
                    return
                yield ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(tool_call_id="call-slow", name="slow.read", input={}),
                )
                await asyncio.wait_for(tool_started.wait(), timeout=1)
                self.tool_started_before_stream_end = True
                yield ModelEvent(event_type="text_delta", text="after tool started")
                yield ModelEvent(event_type="message_stop")

        registry.register(
            ToolManifest(name="slow.read", description="Slow read.", input_schema={}),
            slow_tool,
        )
        model = BlockingAfterToolCallModel()
        result = await SingleAgentLoop(model=model, tools=registry).run("read slowly")
        return result, model.tool_started_before_stream_end

    result, tool_started_before_stream_end = asyncio.run(run_case())

    assert result.status == "completed"
    assert tool_started_before_stream_end is True
    event_names = [event.event_type for event in result.events]
    assert event_names.index("tool_start") < event_names.index("assistant_message_stop")


def test_kernel_v4_tool_discovery_expands_deferred_tool_surface_next_turn() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            name="sec.edgar.financials",
            description="Retrieve SEC financial facts.",
            input_schema={"ticker": {"type": "str", "required": True}},
            should_defer=True,
            always_load=False,
        ),
        lambda payload, context: {"unused": True},
    )
    model = ScriptedModel(
        [
            [
                ModelEvent(
                    event_type="tool_call",
                    tool_call=ToolCall(
                        tool_call_id="call-discover",
                        name="tool.discovery",
                        input={"query": "sec edgar financials", "max_results": 5},
                    ),
                ),
                ModelEvent(event_type="message_stop"),
            ],
            [ModelEvent(event_type="text_delta", text="done"), ModelEvent(event_type="message_stop")],
        ]
    )

    result = asyncio.run(SingleAgentLoop(model=model, tools=registry).run("find sec tool"))

    assert result.status == "completed"
    first_tools = {tool.name for tool in model.requests[0]["tools"]}
    second_tools = {tool.name for tool in model.requests[1]["tools"]}
    assert "sec.edgar.financials" not in first_tools
    assert "sec.edgar.financials" in second_tools
    second_context = model.requests[1]["context"]
    assert "sec.edgar.financials" in second_context["workflow"]["context_edits_recent"][-1]["value"]
