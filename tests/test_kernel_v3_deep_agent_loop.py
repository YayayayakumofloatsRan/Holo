from __future__ import annotations

from collections.abc import Iterable

from kernel_v3.context import ContextCompiler

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation, ProcessorRequest
from kernel_v3.deep_loop import AssistantTurn, DeepAgentLoopController, ModelAssistantTurnPlanner, ToolCallParseError, ToolCallRequest
from kernel_v3.journal import JournalStore
from kernel_v3.policy import PolicyGate
from kernel_v3.processors.contracts import ProcessorStreamEvent
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.testing.fakes import FakeEvaluator
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
