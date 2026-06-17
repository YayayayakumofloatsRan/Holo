from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable

from kernel_v3.context import ContextCompiler

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation, ProcessorRequest, ToolManifest
from kernel_v3.deep_loop import (
    AssistantTurn,
    DeepAgentLoopController,
    ModelAssistantTurnPlanner,
    ToolCallParseError,
    ToolCallRequest,
    _assistant_turn_prompt,
)
from kernel_v3.journal import JournalStore
from kernel_v3.policy import PolicyGate
from kernel_v3.processors.contracts import ProcessorStreamEvent
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.testing.fakes import FakeEvaluator
from kernel_v3.tool_use import emit_tool_progress, tool_abort_requested
from kernel_v3.tools import ToolRegistry


class FakeTurnPlanner:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[ContextBundle] = []

    def propose_turn(self, context: ContextBundle, feedback: Feedback | None = None) -> AssistantTurn:
        self.calls.append(context)
        if not self.turns:
            raise AssertionError("FakeTurnPlanner has no more turns")
        return self.turns.pop(0)


def test_deep_agent_loop_executes_multi_tool_turn_and_journals_batch() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    registry.register("beta.read", _read_tool("beta"))
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-read-both",
                message="read both sources",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-alpha",
                        name="alpha.read",
                        arguments={"query": "A"},
                        reason="need alpha evidence",
                        side_effect_class="read",
                    ),
                    ToolCallRequest(
                        tool_call_id="call-beta",
                        name="beta.read",
                        arguments={"query": "B"},
                        reason="need beta evidence",
                        side_effect_class="read",
                    ),
                ],
            )
        ]
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=4,
        max_tool_calls=4,
    )

    result = loop.run("read alpha and beta")

    assert result.status == "completed"
    assert result.answer == "done"
    assert [action.name for action in registry.executed_actions] == ["alpha.read", "beta.read"]
    turn_record = journal.records(task_id=result.task_id, kind="assistant_turn")[0]
    assert turn_record.data["loop_runtime"] == "deep_agent_loop"
    assert turn_record.data["tool_call_count"] == 2
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["tool_call_count"] == 2
    assert {item["tool"] for item in batch.data["content"]["results"]} == {"alpha.read", "beta.read"}
    assert {item["tool_call_id"] for item in batch.data["content"]["results"]} == {"call-alpha", "call-beta"}
    assert {item["content_projection"]["shape"]["type"] for item in batch.data["content"]["results"]} == {"object"}
    assert all("payload" in item["content_projection"]["shape"]["keys"] for item in batch.data["content"]["results"])
    events = journal.records(task_id=result.task_id, kind="tool_execution_event")
    assert [record.data["event_type"] for record in events] == [
        "queued",
        "started",
        "completed",
        "queued",
        "started",
        "completed",
    ]
    assert {record.data["tool_call_id"] for record in events} == {"call-alpha", "call-beta"}
    individual = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_result"
    ]
    assert {record.data["tool_call_id"] for record in individual} == {"call-alpha", "call-beta"}
    contexts = [
        record.data["content"]["payload"]["_host_context"]
        for record in individual
    ]
    assert {context["schema"] for context in contexts} == {"holo.kernel_v3.tool_use_context.v1"}
    assert {context["tool_call_id"] for context in contexts} == {"call-alpha", "call-beta"}


def test_deep_agent_loop_terminal_turn_uses_final_answer_path() -> None:
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-final",
                message=None,
                tool_calls=[],
                final_answer="direct final",
                reasons=["enough_context"],
            )
        ]
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.final_answer("direct final"),
        max_steps=2,
    )

    result = loop.run("answer directly")

    assert result.status == "completed"
    assert result.answer == "direct final"
    assert journal.records(task_id=result.task_id, kind="assistant_turn")[0].data["turn_id"] == "turn-final"
    assert journal.records(task_id=result.task_id, kind="observation")[0].data["source"] == "respond"


def test_deep_agent_loop_returns_parse_errors_as_observations_for_replanning() -> None:
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-bad-call",
                message="bad tool call",
                tool_calls=[],
                parse_errors=[
                    ToolCallParseError(
                        tool_call_id="call-bad",
                        error="invalid_tool_arguments",
                        raw_preview='{"name":"alpha.read","arguments":"bad"}',
                    )
                ],
            ),
            AssistantTurn(
                turn_id="turn-final",
                message=None,
                tool_calls=[],
                final_answer="fixed after feedback",
                reasons=["replanned_after_tool_error"],
            ),
        ]
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [
                {
                    "status": "continue",
                    "stop_reason": None,
                    "answer": None,
                    "missing_evidence": ["invalid_tool_arguments"],
                },
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "fixed after feedback",
                    "missing_evidence": [],
                },
            ]
        ),
        max_steps=4,
        max_tool_calls=4,
    )

    result = loop.run("recover from invalid tool call")

    assert result.status == "completed"
    assert result.answer == "fixed after feedback"
    assert len(planner.calls) == 2
    parse_records = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_call_parse_error"
    ]
    assert parse_records[0].data["tool_call_id"] == "call-bad"
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["results"][0]["tool_call_id"] == "call-bad"
    assert batch.data["content"]["results"][0]["status"] == "failed"


def test_deep_agent_loop_consumes_streamed_tool_call_delta() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _StreamingToolCallProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha through streamed tool call")

    assert result.status == "completed"
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    stream_records = journal.records(task_id=result.task_id, kind="processor_stream")
    assert stream_records[0].data["event_count"] == 3
    turn_record = journal.records(task_id=result.task_id, kind="assistant_turn")[0]
    assert turn_record.data["tool_call_count"] == 1
    assert turn_record.data["tool_calls"][0]["tool_call_id"] == "tc-alpha"
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["results"][0]["tool"] == "alpha.read"


def test_streamed_malformed_tool_arguments_become_parse_error_observation() -> None:
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _MalformedStreamingToolCallProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "parse error observed",
                    "missing_evidence": [],
                }
            ]
        ),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("emit malformed streamed tool call")

    assert result.status == "completed"
    parse_records = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_call_parse_error"
    ]
    assert parse_records[0].data["content"]["error"] == "invalid_tool_arguments"
    assert parse_records[0].data["tool_call_id"] == "tc-bad"


def test_streaming_planner_maps_native_provider_tool_name_back_to_holo_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        "alpha.read",
        _read_tool("alpha"),
        manifest=ToolManifest(
            name="alpha.read",
            version="1",
            resource_kind="alpha",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Read alpha data.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
        ),
    )
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _NativeNameStreamingToolCallProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha through native streamed tool call")

    assert result.status == "completed"
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    assert registry.executed_actions[0].payload["query"] == "A"


def test_streaming_planner_starts_tool_before_provider_stream_is_drained() -> None:
    tool_started = threading.Event()
    provider = _BlockingAfterToolDeltaProvider(tool_started)
    registry = ToolRegistry()
    registry.register("alpha.read", _signaling_read_tool("alpha", tool_started))
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha before stream drain")

    assert result.status == "completed"
    assert provider.tool_started_before_stream_end is True
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    execution_events = journal.records(task_id=result.task_id, kind="tool_execution_event")
    assert [record.data["event_type"] for record in execution_events[:2]] == ["queued", "started"]
    assert execution_events[-1].data["event_type"] == "completed"


def test_streaming_tool_progress_is_journaled_from_host_context() -> None:
    registry = ToolRegistry()
    registry.register(
        "alpha.read",
        _progress_read_tool("alpha"),
        manifest=ToolManifest(
            name="alpha.read",
            version="1",
            resource_kind="alpha",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Read alpha data with progress.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"progress_supported": True, "concurrency_safe": True, "read_only": True},
        ),
    )
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _StreamingToolCallProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha with progress")

    assert result.status == "completed"
    progress_records = [
        record
        for record in journal.records(task_id=result.task_id, kind="tool_execution_event")
        if record.data["event_type"] == "progress"
    ]
    assert progress_records[0].data["tool_call_id"] == "tc-alpha"
    assert progress_records[0].data["detail"]["stage"] == "fetch"


def test_streaming_tool_timeout_requests_cooperative_abort() -> None:
    abort_seen = threading.Event()
    registry = ToolRegistry()
    registry.register(
        "alpha.read",
        _abortable_read_tool("alpha", abort_seen),
        manifest=ToolManifest(
            name="alpha.read",
            version="1",
            resource_kind="alpha",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Abortable alpha read.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"progress_supported": True, "interrupt_behavior": "cancel", "timeout_seconds": 1},
        ),
    )
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _StreamingToolCallProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha with abort")

    assert result.status == "completed"
    assert abort_seen.is_set()
    events = journal.records(task_id=result.task_id, kind="tool_execution_event")
    assert any(record.data["event_type"] == "abort_requested" for record in events)
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["results"][0]["status"] == "failed"


def test_assistant_turn_prompt_applies_provider_message_replacement_view() -> None:
    context = ContextBundle(
        context_id="ctx-replacement",
        thread_key="local:default",
        event_ids=[],
        memory_refs=[],
        token_budget=4096,
        state={
            "task_id": "task-1",
            "run_id": "run-1",
            "sections": [
                {
                    "name": "recent_observations",
                    "records": [
                        {
                            "content": {
                                "results": [
                                    {
                                        "tool_call_id": "tc-large",
                                        "content_preview": "RAW-" + "x" * 5000,
                                        "content_projection": {
                                            "preview": "PROJECTED-" + "y" * 5000,
                                            "estimated_chars": 100000,
                                        },
                                        "content_replacement": {
                                            "schema": "holo.kernel_v3.tool_result_replacement.v1",
                                            "tool_call_id": "tc-large",
                                            "replacement_preview": "bounded replacement",
                                        },
                                    }
                                ]
                            }
                        }
                    ],
                }
            ],
        },
    )

    prompt = _assistant_turn_prompt(context, None, allowed_tool_names={"alpha.read"})
    payload = json.loads(prompt)
    result = payload["context"]["state"]["sections"][0]["records"][0]["content"]["results"][0]

    assert result["content_preview"] == "bounded replacement"
    assert result["content_projection"]["preview"] == "bounded replacement"
    assert "RAW-" not in prompt
    assert "PROJECTED-" not in prompt


class _StreamingToolCallProvider:
    name = "streaming"
    model = "stream-model"

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        yield ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=1,
            delta={"provider": self.name},
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=2,
            delta={
                "tool_calls": [
                    {
                        "id": "tc-alpha",
                        "function": {
                            "name": "alpha.read",
                            "arguments": '{"query":"A"}',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=3,
            delta={"status": "ok"},
        )


class _MalformedStreamingToolCallProvider:
    name = "streaming"
    model = "stream-model"

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=1,
            delta={
                "tool_calls": [
                    {
                        "id": "tc-bad",
                        "function": {
                            "name": "alpha.read",
                            "arguments": '{"query":',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=2,
            delta={"status": "ok"},
        )


class _NativeNameStreamingToolCallProvider:
    name = "streaming"
    model = "stream-model"

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        native_tools = request.parameters.get("native_tools")
        assert isinstance(native_tools, list)
        native_name = native_tools[0]["function"]["name"]
        assert isinstance(native_name, str)
        assert native_name.startswith("alpha_read_")
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=1,
            delta={
                "tool_calls": [
                    {
                        "id": "tc-native-alpha",
                        "function": {
                            "name": native_name,
                            "arguments": '{"query":"A"}',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=2,
            delta={"status": "ok"},
        )


class _BlockingAfterToolDeltaProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self, tool_started: threading.Event) -> None:
        self.tool_started = tool_started
        self.tool_started_before_stream_end = False

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        yield ProcessorStreamEvent(
            event_type="stream_start",
            request_id=request.request_id,
            sequence=1,
            delta={"provider": self.name},
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=2,
            delta={
                "tool_calls": [
                    {
                        "id": "tc-blocking-alpha",
                        "function": {
                            "name": "alpha.read",
                            "arguments": '{"query":"A"}',
                        },
                    }
                ]
            },
        )
        self.tool_started_before_stream_end = self.tool_started.wait(timeout=1.0)
        yield ProcessorStreamEvent(
            event_type="content_delta",
            request_id=request.request_id,
            sequence=3,
            delta={"text": "continuing after tool start"},
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=4,
            delta={"status": "ok"},
        )


def _read_tool(name: str):
    def execute(action: CandidateAction) -> Observation:
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"name": name, "payload": action.payload},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _signaling_read_tool(name: str, started: threading.Event):
    def execute(action: CandidateAction) -> Observation:
        started.set()
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"name": name, "payload": action.payload},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _progress_read_tool(name: str):
    def execute(action: CandidateAction) -> Observation:
        emit_tool_progress(action.payload, status="running", detail={"stage": "fetch"})
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"name": name, "payload": action.payload},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _abortable_read_tool(name: str, abort_seen: threading.Event):
    def execute(action: CandidateAction) -> Observation:
        while not tool_abort_requested(action.payload):
            emit_tool_progress(action.payload, status="running", detail={"stage": "waiting"})
            time.sleep(0.05)
        abort_seen.set()
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="failed",
            source=f"tool:{action.name}",
            content={"name": name, "aborted": True},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute
