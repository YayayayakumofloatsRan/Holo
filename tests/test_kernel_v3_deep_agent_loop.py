from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable

from kernel_v3.context import ContextCompiler

from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.agent.workloop import WorkloopEvaluator
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation, ProcessorRequest, ToolManifest
from kernel_v3.deep_loop import (
    AssistantTurn,
    DeepAgentLoopController,
    ModelAssistantTurnPlanner,
    ToolCallParseError,
    ToolCallRequest,
    _assistant_turn_prompt,
    _finance_slot_bind_followup_scaffold_turn,
    _workbench_followup_scaffold_turn,
)
from kernel_v3.finance.tool_catalog import finance_agent_loop_contract
from kernel_v3.journal import JournalStore
from kernel_v3.policy import PolicyGate
from kernel_v3.processors.contracts import ProcessorStreamEvent
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.testing.fakes import FakeEvaluator
from kernel_v3.tool_use import TOOL_DISCOVERY_NAME, emit_tool_progress, register_tool_discovery, tool_abort_requested
from kernel_v3.tools import ToolRegistry, ToolResult


class FakeTurnPlanner:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[ContextBundle] = []

    def propose_turn(self, context: ContextBundle, feedback: Feedback | None = None) -> AssistantTurn:
        self.calls.append(context)
        if not self.turns:
            raise AssertionError("FakeTurnPlanner has no more turns")
        return self.turns.pop(0)


class FakePlannerWithStreamingProbe(FakeTurnPlanner):
    def __init__(self, turns: list[AssistantTurn]) -> None:
        super().__init__(turns)
        self.stream_calls = 0

    def stream_turn(
        self,
        context: ContextBundle,
        feedback: Feedback | None = None,
        *,
        step_id: str | None = None,
    ) -> None:
        self.stream_calls += 1
        if feedback is not None and "retrieval_workbench_followup" in feedback.missing_evidence:
            raise AssertionError("workbench follow-up should be scaffolded before streaming")
        if feedback is not None and "finance_slot_bind_followup" in feedback.missing_evidence:
            raise AssertionError("finance slot-bind follow-up should be scaffolded before streaming")
        return None


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
    assert sorted(record.data["event_type"] for record in events) == [
        "completed",
        "completed",
        "queued",
        "queued",
        "started",
        "started",
    ]
    assert {record.data["tool_call_id"] for record in events} == {"call-alpha", "call-beta"}
    for tool_call_id in {"call-alpha", "call-beta"}:
        lifecycle = [
            record.data["event_type"]
            for record in events
            if record.data["tool_call_id"] == tool_call_id
        ]
        assert lifecycle == ["queued", "started", "completed"]
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


def test_deep_agent_loop_records_host_tool_exception_as_tool_result() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-host-exception",
                message="read alpha",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-alpha",
                        name="alpha.read",
                        arguments={"query": "A"},
                        reason="need alpha evidence",
                        side_effect_class="read",
                    )
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

    def raise_host_exception(_task: object, _step_id: str, _prepared: object) -> object:
        raise RuntimeError("host execution failed")

    loop._execute_prepared_tool_with_timeout = raise_host_exception  # type: ignore[method-assign]

    result = loop.run("read alpha and survive host exception")

    assert result.status == "completed"
    host_exceptions = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_host_exception"
    ]
    assert len(host_exceptions) == 1
    assert host_exceptions[0].data["status"] == "failed"
    assert host_exceptions[0].data["tool_call_id"] == "call-alpha"
    assert host_exceptions[0].data["content"]["error_type"] == "RuntimeError"
    assert "host execution failed" in host_exceptions[0].data["content"]["error_message"]
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["status"] == "failed"
    assert batch.data["content"]["results"][0]["kind"] == "tool_host_exception"
    assert batch.data["content"]["results"][0]["policy"] == "tool_host_exception"
    lifecycle = journal.records(task_id=result.task_id, kind="agent_loop_turn_result")
    assert lifecycle[-1].data["phase"] == "tool_turn"
    assert lifecycle[-1].data["transition"] == "return"
    assert lifecycle[-1].data["tool_status_counts"] == {"failed": 1}
    assert lifecycle[-1].data["failed_tool_count"] == 1
    assert lifecycle[-1].data["failed_tools"][0]["kind"] == "tool_host_exception"
    assert lifecycle[-1].data["failed_tools"][0]["tool_call_id"] == "call-alpha"


def test_deep_agent_loop_stops_before_evaluator_when_batch_contains_host_guard() -> None:
    class EvaluatorMustNotRun:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
            self.calls += 1
            raise AssertionError("batch host guard should stop before evaluator")

    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    registry.register("beta.read", _read_tool("beta"))
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-over-budget",
                message="try two reads",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-alpha",
                        name="alpha.read",
                        arguments={"query": "A"},
                        reason="first read",
                        side_effect_class="read",
                    ),
                    ToolCallRequest(
                        tool_call_id="call-beta",
                        name="beta.read",
                        arguments={"query": "B"},
                        reason="second read",
                        side_effect_class="read",
                    ),
                ],
            )
        ]
    )
    evaluator = EvaluatorMustNotRun()
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=evaluator,
        max_steps=4,
        max_tool_calls=1,
    )

    result = loop.run("read alpha and beta")

    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_tool_calls"
    assert evaluator.calls == 0
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["status"] == "partial"
    assert batch.data["content"]["results"][1]["kind"] == "host_guard"
    assert batch.data["content"]["results"][1]["policy"] == "max_tool_calls"
    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert guard.data["stop_reason"] == "max_tool_calls"
    feedback = journal.records(task_id=result.task_id, kind="feedback")[0]
    assert feedback.data["status"] == "step_limit_exceeded"


def test_deep_agent_loop_projects_tool_context_updates_into_next_turn() -> None:
    registry = ToolRegistry()
    registry.register("stateful.read", _context_update_tool())
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-stateful-read",
                message="read stateful result",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-stateful",
                        name="stateful.read",
                        arguments={"query": "missing ppe"},
                        reason="need a tool-declared context update",
                    )
                ],
            ),
            AssistantTurn(
                turn_id="turn-final-after-update",
                message=None,
                tool_calls=[],
                final_answer="context update was visible",
                reasons=["tool_context_update_visible"],
            ),
        ]
    )

    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {
                    "status": "continue",
                    "stop_reason": None,
                    "answer": None,
                    "missing_evidence": ["tool_context_update_refresh"],
                },
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "context update was visible",
                    "missing_evidence": [],
                },
            ]
        ),
        max_steps=3,
    )

    result = loop.run("prove tool context updates reach the next turn")

    assert result.status == "completed"
    update_records = journal.records(task_id=result.task_id, kind="tool_context_update")
    assert len(update_records) == 2
    assert {record.data["update_type"] for record in update_records} == {
        "tool_declared_context",
        "observation_context",
    }
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["results"][0]["context_update_refs"]

    second_context = planner.calls[1].state
    updates = next(
        section
        for section in second_context["sections"]
        if section["name"] == "tool_context_updates"
    )["updates"]
    assert updates[0]["hints"]["missing_slots"] == ["net_ppne"]
    assert updates[0]["hints"]["next_action"]["tool"] == "retrieval.run"
    assert updates[1]["hints"]["missing_slots"] == ["net_ppne"]


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
    lifecycle = journal.records(task_id=result.task_id, kind="agent_loop_turn_result")
    assert len(lifecycle) == 1
    assert lifecycle[0].data["schema"] == "holo.kernel_v3.agent_loop_turn_result.v1"
    assert lifecycle[0].data["phase"] == "terminal_turn"
    assert lifecycle[0].data["transition"] == "return"
    assert lifecycle[0].data["turn_id"] == "turn-final"
    assert lifecycle[0].data["feedback"]["status"] == "final_answer_ready"
    assert lifecycle[0].data["assistant_final_answer_present"] is True
    assert lifecycle[0].data["tool_result_count"] == 0


def test_deep_agent_loop_prompt_blocks_final_when_feedback_requires_tool_work() -> None:
    context = ContextBundle(
        context_id="ctx-feedback-tool-work",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-feedback-tool-work", "run_id": "run-1"},
        token_budget={},
    )
    feedback = Feedback(
        feedback_id="fb-retrieval-followup",
        run_id="run-1",
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup", "workbench_missing:capital_expenditures"],
    )

    prompt = json.loads(_assistant_turn_prompt(context, feedback, allowed_tool_names={"retrieval.run", "respond"}))

    contract = prompt["continuation_contract"]
    assert contract["feedback_status"] == "continue"
    assert contract["must_not_finalize_without_new_tool_observation"] is True
    assert "retrieval_workbench_followup" in contract["missing_evidence"]


def test_assistant_turn_prompt_exposes_visible_and_deferred_tool_surface() -> None:
    context = ContextBundle(
        context_id="ctx-tool-surface",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-tool-surface", "run_id": "run-1"},
        token_budget={},
    )
    visible = ToolManifest(
        name="calculator.compute",
        version="1",
        resource_kind="finance",
        operator_kind="calculate",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Evaluate arithmetic formulas with named variables.",
        input_schema={
            "expression": {"type": "str", "required": True, "description": "Formula expression."},
            "variables": {"type": "object", "required": False},
        },
        runtime={"concurrency_safe": True, "read_only": True, "always_load": True},
    )
    deferred = ToolManifest(
        name="sec.edgar.financials",
        version="1",
        resource_kind="finance",
        operator_kind="sec_edgar",
        side_effect_class="network",
        permissions_required=["network:fetch"],
        enabled=True,
        description="Retrieve SEC financial statement facts.",
        input_schema={"identifier": {"type": "str", "required": True}},
        runtime={"concurrency_safe": True, "read_only": True, "should_defer": True},
    )

    prompt = json.loads(
        _assistant_turn_prompt(
            context,
            None,
            allowed_tool_names={"calculator.compute", "sec.edgar.financials", "tool.discovery"},
            tool_manifests=[visible, deferred],
        )
    )

    surface = prompt["tool_surface"]
    assert surface["visible_tools"][0]["name"] == "calculator.compute"
    assert surface["visible_tools"][0]["input_schema"]["expression"]["required"] is True
    assert surface["deferred_tools"][0]["name"] == "sec.edgar.financials"
    assert surface["deferred_tools"][0]["schema_available_via"] == "tool.discovery"
    assert "input_schema" not in surface["deferred_tools"][0]


def test_assistant_turn_prompt_expands_context_requested_deferred_tool() -> None:
    context = ContextBundle(
        context_id="ctx-tool-surface-context-request",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-tool-surface-context-request",
            "run_id": "run-1",
            "sections": [
                {
                    "name": "tool_context_updates",
                    "updates": [
                        {
                            "hints": {
                                "next_action": {
                                    "tool": "sec.edgar.financials",
                                    "query": "3M FY2022 net PP&E",
                                }
                            }
                        }
                    ],
                }
            ],
        },
        token_budget=4096,
    )
    visible = ToolManifest(
        name="calculator.compute",
        version="1",
        resource_kind="finance",
        operator_kind="calculate",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Evaluate arithmetic formulas with named variables.",
        input_schema={"expression": {"type": "str", "required": True}},
        runtime={"concurrency_safe": True, "read_only": True, "always_load": True},
    )
    requested_deferred = ToolManifest(
        name="sec.edgar.financials",
        version="1",
        resource_kind="finance",
        operator_kind="sec_edgar",
        side_effect_class="network",
        permissions_required=["network:fetch"],
        enabled=True,
        description="Retrieve SEC financial statement facts.",
        input_schema={"identifier": {"type": "str", "required": True}},
        runtime={"concurrency_safe": True, "read_only": True, "should_defer": True},
    )

    prompt = json.loads(
        _assistant_turn_prompt(
            context,
            None,
            allowed_tool_names={"calculator.compute", "sec.edgar.financials", "tool.discovery"},
            tool_manifests=[visible, requested_deferred],
        )
    )

    surface = prompt["tool_surface"]
    visible_by_name = {item["name"]: item for item in surface["visible_tools"]}
    assert "sec.edgar.financials" in visible_by_name
    assert visible_by_name["sec.edgar.financials"]["visibility_reason"] == "context_requested"
    assert visible_by_name["sec.edgar.financials"]["input_schema"]["identifier"]["required"] is True
    assert surface["context_requested_tools"] == ["sec.edgar.financials"]
    assert all(item["name"] != "sec.edgar.financials" for item in surface["deferred_tools"])


def test_assistant_turn_prompt_expands_finance_requirement_category_tools() -> None:
    context = ContextBundle(
        context_id="ctx-finance-requirements-tools",
        thread_key="thread-finance-requirements-tools",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-finance-requirements-tools",
            "run_id": "run-finance-requirements-tools",
            "agent_runtime_directive": {
                "finance_question_requirements": {
                    "schema": "holo.kernel_v3.finance_question_requirements.v1",
                    "required_tool_categories": [
                        "structured_sec_facts",
                        "document_table_extraction",
                        "table_operations",
                        "arithmetic",
                        "numeric_verification",
                    ],
                    "risk_flags": ["requires_table_sort"],
                    "gold_or_reference_values_used": False,
                }
            },
        },
        token_budget=8192,
    )
    manifests = [
        ToolManifest(
            name="tool.discovery",
            version="1",
            resource_kind="tooling",
            operator_kind="discover",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Discover tools.",
            input_schema={},
            runtime={"always_load": True},
        ),
        ToolManifest(
            name="sec.edgar.financials",
            version="1",
            resource_kind="finance",
            operator_kind="sec",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="SEC structured facts.",
            input_schema={"identifier": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True},
        ),
        ToolManifest(
            name="document.docling.convert",
            version="1",
            resource_kind="document",
            operator_kind="convert",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="Convert documents and tables.",
            input_schema={"source": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True},
        ),
        ToolManifest(
            name="data.table.query",
            version="1",
            resource_kind="data",
            operator_kind="query",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Query evidence tables.",
            input_schema={"sql": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True},
        ),
        ToolManifest(
            name="calculator.compute",
            version="1",
            resource_kind="calculator",
            operator_kind="compute",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Compute arithmetic.",
            input_schema={"expression": {"type": "str", "required": True}},
            runtime={"always_load": True, "read_only": True},
        ),
        ToolManifest(
            name="finance.verify_numeric",
            version="1",
            resource_kind="finance",
            operator_kind="verify",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Verify finance numeric claims.",
            input_schema={"answer": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True},
        ),
    ]

    prompt = json.loads(
        _assistant_turn_prompt(
            context,
            None,
            allowed_tool_names={manifest.name for manifest in manifests},
            tool_manifests=manifests,
        )
    )

    surface = prompt["tool_surface"]
    visible_by_name = {item["name"]: item for item in surface["visible_tools"]}
    for tool_name in (
        "sec.edgar.financials",
        "document.docling.convert",
        "data.table.query",
        "calculator.compute",
        "finance.verify_numeric",
    ):
        assert tool_name in visible_by_name
    assert visible_by_name["data.table.query"]["visibility_reason"] == "context_requested"
    assert "data.table.query" in surface["context_requested_tools"]


def test_assistant_turn_prompt_exposes_strict_finance_single_agent_loop_contract() -> None:
    finance_loop_contract = finance_agent_loop_contract()
    context = ContextBundle(
        context_id="ctx-finance-strict-loop-contract",
        thread_key="thread-finance-strict-loop-contract",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-finance-strict-loop-contract",
            "run_id": "run-finance-strict-loop-contract",
            "agent_runtime_directive": {
                "finance_agent_loop_contract": finance_loop_contract,
                "finance_question_requirements": {
                    "schema": "holo.kernel_v3.finance_question_requirements.v1",
                    "required_tool_categories": ["arithmetic", "numeric_verification"],
                    "risk_flags": ["requires_verifier"],
                    "gold_or_reference_values_used": False,
                },
            },
        },
        token_budget=8192,
    )

    prompt = json.loads(
        _assistant_turn_prompt(
            context,
            None,
            allowed_tool_names={"calculator.compute", "finance.verify_numeric"},
            tool_manifests=[],
        )
    )

    loop_contract = prompt["single_agent_tool_loop_contract"]
    assert loop_contract["schema"] == "holo.kernel_v3.single_agent_tool_loop_contract.v1"
    assert loop_contract["decision_owner"] == "model"
    assert loop_contract["host_role"] == "validate_execute_record_verify_gate_only"
    assert loop_contract["required_tool_categories"] == ["arithmetic", "numeric_verification"]
    assert loop_contract["risk_flags"] == ["requires_verifier"]
    assert "model-requested tool_calls inside this loop" in loop_contract["tool_use_boundary"]
    assert "must not create hidden finance tool results" in loop_contract["finalizer_boundary"]
    assert any(
        "calculator.compute or data.table.query" in item
        for item in loop_contract["required_for_finance_numeric_answers"]
    )
    context_contract = prompt["context"]["state"]["agent_runtime_directive"]["finance_agent_loop_contract"]
    assert context_contract["finalization_boundary"].startswith("The host finalizer may synthesize")
    assert "debug50" not in json.dumps(loop_contract).lower()


def test_streaming_planner_expands_context_requested_deferred_native_tool() -> None:
    provider = _CaptureNativeToolSurfaceProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"tool.discovery", "calculator.compute", "sec.edgar.financials"},
        tool_manifests=[
            ToolManifest(
                name="tool.discovery",
                version="1",
                resource_kind="tooling",
                operator_kind="discover",
                side_effect_class="read",
                permissions_required=[],
                enabled=True,
                description="Discover tools.",
                input_schema={},
                runtime={"always_load": True},
            ),
            ToolManifest(
                name="calculator.compute",
                version="1",
                resource_kind="finance",
                operator_kind="calculate",
                side_effect_class="read",
                permissions_required=[],
                enabled=True,
                description="Evaluate arithmetic formulas.",
                input_schema={"expression": {"type": "str", "required": True}},
            ),
            ToolManifest(
                name="sec.edgar.financials",
                version="1",
                resource_kind="finance",
                operator_kind="sec_edgar",
                side_effect_class="network",
                permissions_required=["network:fetch"],
                enabled=True,
                description="Retrieve SEC financial statement facts.",
                input_schema={"identifier": {"type": "str", "required": True}},
                runtime={"should_defer": True},
            ),
        ],
        use_streaming=True,
    )
    context = ContextBundle(
        context_id="ctx-native-context-request",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-native-context-request",
            "run_id": "run-1",
            "sections": [
                {
                    "name": "tool_context_updates",
                    "updates": [
                        {
                            "hints": {
                                "next_action": {
                                    "tool": "sec.edgar.financials",
                                    "query": "3M FY2022 net PP&E",
                                }
                            }
                        }
                    ],
                }
            ],
        },
        token_budget=4096,
    )

    stream = planner.stream_turn(context, None, step_id="step-1")
    assert stream is not None
    list(stream.events)

    exposed = set(provider.parameters[0]["native_tool_name_map"].values())
    assert "tool.discovery" in exposed
    assert "sec.edgar.financials" in exposed
    assert "sec.edgar.financials" not in {
        item["name"] for item in provider.parameters[0]["native_tool_deferred"]
    }


def test_streaming_planner_expands_finance_requirement_category_native_tools() -> None:
    provider = _CaptureNativeToolSurfaceProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"tool.discovery", "calculator.compute", "data.table.query"},
        tool_manifests=[
            ToolManifest(
                name="tool.discovery",
                version="1",
                resource_kind="tooling",
                operator_kind="discover",
                side_effect_class="read",
                permissions_required=[],
                enabled=True,
                description="Discover tools.",
                input_schema={},
                runtime={"always_load": True},
            ),
            ToolManifest(
                name="calculator.compute",
                version="1",
                resource_kind="finance",
                operator_kind="calculate",
                side_effect_class="read",
                permissions_required=[],
                enabled=True,
                description="Evaluate arithmetic formulas.",
                input_schema={"expression": {"type": "str", "required": True}},
                runtime={"always_load": True},
            ),
            ToolManifest(
                name="data.table.query",
                version="1",
                resource_kind="data",
                operator_kind="query",
                side_effect_class="read",
                permissions_required=[],
                enabled=True,
                description="Query evidence tables.",
                input_schema={"sql": {"type": "str", "required": True}},
                runtime={"should_defer": True},
            ),
        ],
        use_streaming=True,
    )
    context = ContextBundle(
        context_id="ctx-native-finance-requirement",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-native-finance-requirement",
            "run_id": "run-1",
            "agent_runtime_directive": {
                "finance_question_requirements": {
                    "schema": "holo.kernel_v3.finance_question_requirements.v1",
                    "required_tool_categories": ["table_operations", "arithmetic"],
                    "gold_or_reference_values_used": False,
                }
            },
        },
        token_budget=4096,
    )

    stream = planner.stream_turn(context, None, step_id="step-1")
    assert stream is not None
    list(stream.events)

    exposed = set(provider.parameters[0]["native_tool_name_map"].values())
    assert {"tool.discovery", "calculator.compute", "data.table.query"}.issubset(exposed)
    assert "data.table.query" not in {item["name"] for item in provider.parameters[0]["native_tool_deferred"]}


def test_streaming_loop_executes_pending_workbench_followup_before_model_turn() -> None:
    journal = JournalStore.in_memory()
    registry = ToolRegistry()
    registry.register("seed.read", _workbench_seed_tool(journal))
    registry.register("retrieval.run", _read_tool("retrieval"))
    planner = FakePlannerWithStreamingProbe(
        [
            AssistantTurn(
                turn_id="turn-seed",
                message="create workbench follow-up state",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="tc-seed",
                        name="seed.read",
                        arguments={"query": "seed"},
                        reason="seed workbench decision",
                    )
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
        evaluator=FakeEvaluator(
            [
                {
                    "status": "continue",
                    "stop_reason": None,
                    "answer": None,
                    "missing_evidence": ["retrieval_workbench_followup"],
                },
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "done",
                    "missing_evidence": [],
                },
            ]
        ),
        max_steps=4,
        max_tool_calls=4,
    )

    result = loop.run("Find 3M FY2018 net PP&E from the filing.")

    assert result.status == "completed"
    assert result.answer == "done"
    assert planner.stream_calls == 1
    assert [action.name for action in registry.executed_actions] == ["seed.read", "retrieval.run"]
    followup = registry.executed_actions[-1]
    assert followup.payload["query"] == "https://example.test/3m-2018-10k.pdf"
    assert followup.payload["metadata"]["workbench_followup"] is True
    assistant_turns = journal.records(task_id=result.task_id, kind="assistant_turn")
    assert assistant_turns[1].data["turn_id"].startswith("turn-workbench-followup-")


def test_finance_slot_bind_followup_scaffold_executes_model_declared_retrieval() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-slot-followup",
        run_id="run-1",
        step_id="step-slot",
        kind="finance_slot_bind",
        data={
            "schema": "holo.kernel_v3.finance_slot_bind.v1",
            "status": "failed",
            "decision": "needs_more_evidence",
            "missing_slots": ["net_ppne"],
            "next_action": {
                "tool": "retrieval.run",
                "query": "3M FY2018 balance sheet net property plant equipment",
                "reason": "No balance-sheet PP&E net fact was found in the visible ledger.",
            },
            "reason_summary": "Need one more primary filing fact before calculator.",
        },
    )
    feedback = Feedback(
        feedback_id="fb-slot-followup",
        run_id="run-1",
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["finance_slot_bind_followup", "missing_slot:net_ppne"],
    )

    scaffold = _finance_slot_bind_followup_scaffold_turn(
        journal,
        task_id="task-slot-followup",
        run_id="run-1",
        input_text="Find 3M FY2018 capital intensity using net PP&E.",
        feedback=feedback,
        proposed_turn=AssistantTurn(
            turn_id="turn-premature",
            message=None,
            tool_calls=[],
            final_answer="partial answer",
        ),
    )

    assert scaffold is not None
    call = scaffold.tool_calls[0]
    assert call.name == "retrieval.run"
    assert call.arguments["query"] == "3M FY2018 balance sheet net property plant equipment"
    assert call.arguments["metadata"]["finance_slot_bind_followup"] is True
    assert call.arguments["metadata"]["semantic_missing_slots"] == ["net_ppne"]
    assert call.arguments["metadata"]["model_next_action"]["tool"] == "retrieval.run"


def test_streaming_loop_executes_pending_finance_slot_bind_followup_before_model_turn() -> None:
    journal = JournalStore.in_memory()
    registry = ToolRegistry()
    registry.register("seed.read", _finance_slot_bind_seed_tool(journal))
    registry.register("retrieval.run", _read_tool("retrieval"))
    planner = FakePlannerWithStreamingProbe(
        [
            AssistantTurn(
                turn_id="turn-seed-slot-bind",
                message="create slot-bind follow-up state",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="tc-seed-slot-bind",
                        name="seed.read",
                        arguments={"query": "seed"},
                        reason="seed slot-bind decision",
                    )
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
        evaluator=FakeEvaluator(
            [
                {
                    "status": "continue",
                    "stop_reason": None,
                    "answer": None,
                    "missing_evidence": ["finance_slot_bind_followup", "missing_slot:net_ppne"],
                },
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "done",
                    "missing_evidence": [],
                },
            ]
        ),
        max_steps=4,
        max_tool_calls=4,
    )

    result = loop.run("Find 3M FY2018 net PP&E from the filing.")

    assert result.status == "completed"
    assert result.answer == "done"
    assert planner.stream_calls == 1
    assert [action.name for action in registry.executed_actions] == ["seed.read", "retrieval.run"]
    followup = registry.executed_actions[-1]
    assert followup.payload["query"] == "3M FY2018 net PP&E balance sheet"
    assert followup.payload["metadata"]["finance_slot_bind_followup"] is True
    assistant_turns = journal.records(task_id=result.task_id, kind="assistant_turn")
    assert assistant_turns[1].data["turn_id"].startswith("turn-finance-slot-bind-followup-")


def test_finance_workloop_does_not_finalize_on_workbench_fail_with_missing_slots() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )
    journal = JournalStore.in_memory()
    task_id = "task-finance-workbench-fail-open"
    run_id = "run-1"
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-1",
        kind="retrieval_evidence",
        data={"evidence_id": "ev-1", "text": "Target filing was fetched but capex was not extracted."},
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-1",
        kind="retrieval_citation",
        data={"citation_id": "cite-1", "evidence_id": "ev-1"},
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-1",
        kind="retrieval_report",
        data={
            "status": "failed",
            "diagnostics": {
                "retrieval_workbench": {
                    "status": "ok",
                    "decision": "fail_with_limitations",
                    "missing_slots": ["capital_expenditures"],
                    "next_queries": ["3M 2018 10-K purchases of property plant and equipment"],
                    "next_source_families": ["sec_edgar", "structured_companyfacts"],
                }
            },
        },
    )
    observation = Observation(
        observation_id="obs-premature-final",
        run_id=run_id,
        kind="respond_result",
        status="ok",
        source="respond",
        content={"text": "Not available from the current PDF parse."},
        observed_at_ms=1,
        action_id="act-premature-final",
        tool_call_id=None,
    )
    evaluator = WorkloopEvaluator(
        inner=FakeEvaluator.final_answer("Not available from the current PDF parse."),
        journal=journal,
        recipe=recipe,
    )
    context = ContextBundle(
        context_id="ctx-finance-workbench-fail-open",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": task_id, "run_id": run_id},
        token_budget={},
    )

    feedback = evaluator.evaluate(context, observation)

    assert feedback.status == "continue"
    assert "retrieval_workbench_followup" in feedback.missing_evidence
    assert "workbench_missing:capital_expenditures" in feedback.missing_evidence


def test_deep_agent_loop_scaffolds_workbench_source_family_followup() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-workbench-source-family"
    run_id = "run-1"
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-3",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "fail_with_limitations",
            "missing_slots": [],
            "next_queries": [],
            "next_document_targets": [
                "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000066740&type=10-K",
                "https://investors.3m.com/financials/sec-filings",
            ],
            "next_source_families": ["sec_edgar_filing", "sec_companyfacts", "company_ir_html"],
        },
    )
    proposed = AssistantTurn(
        turn_id="turn-read-stale-artifact",
        message="Read the failed PDF artifact.",
        tool_calls=[
            ToolCallRequest(
                tool_call_id="tc-artifact",
                name="artifact.read",
                arguments={"artifact_id": "artifact-pdf"},
                reason="inspect current artifact",
            )
        ],
    )
    feedback = Feedback(
        feedback_id="fb-workbench-followup",
        run_id=run_id,
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup"],
    )

    scaffold = _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text="What is the FY2018 capital expenditure amount in USD millions for 3M?",
        feedback=feedback,
        proposed_turn=proposed,
    )

    assert scaffold is not None
    assert scaffold.tool_calls[0].name == "retrieval.run"
    args = scaffold.tool_calls[0].arguments
    assert args["query"].startswith("https://www.sec.gov/cgi-bin/browse-edgar")
    assert args["metadata"]["workbench_followup"] is True
    assert args["metadata"]["preferred_source_families"] == [
        "sec_edgar_filing",
        "sec_companyfacts",
        "company_ir_html",
    ]
    assert args["metadata"]["task_goal"].startswith("What is the FY2018 capital expenditure")


def test_deep_agent_loop_scaffold_prefers_direct_target_over_text_query() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-workbench-direct-target"
    run_id = "run-1"
    sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-4",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "missing_slots": ["capital_expenditure_cash_flow_2018"],
            "next_queries": ["3M 2018 10-K capital expenditure cash flow statement"],
            "next_document_targets": [sec_url],
            "next_source_families": ["sec_companyfacts"],
            "reason_summary": "Need structured SEC data.",
        },
    )
    feedback = Feedback(
        feedback_id="fb-workbench-followup",
        run_id=run_id,
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup"],
    )

    scaffold = _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text="What is the FY2018 capital expenditure amount in USD millions for 3M?",
        feedback=feedback,
        proposed_turn=AssistantTurn(turn_id="turn-final-too-soon", message=None, tool_calls=[], final_answer="Not available"),
    )

    assert scaffold is not None
    args = scaffold.tool_calls[0].arguments
    assert args["query"] == sec_url
    assert args["queries"][0] == sec_url
    assert args["metadata"]["source_urls"] == [sec_url]


def test_deep_agent_loop_scaffold_overrides_broad_model_retrieval_with_direct_target() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-workbench-broad-model-query"
    run_id = "run-1"
    sec_url = "https://www.sec.gov/Archives/edgar/data/66740/000006674019000008/mmm-20181231.htm"
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-7",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "missing_slots": ["capital_expenditures from 3M FY2018 cash flow statement"],
            "next_queries": ["3M FY2018 capital expenditure cash flow statement 10-K"],
            "next_document_targets": [sec_url],
            "next_source_families": ["sec_edgar_filing"],
        },
    )
    feedback = Feedback(
        feedback_id="fb-workbench-followup",
        run_id=run_id,
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup"],
    )
    proposed = AssistantTurn(
        turn_id="turn-model-broad-retrieval",
        message="Search for the missing line item.",
        tool_calls=[
            ToolCallRequest(
                tool_call_id="tc-model-search",
                name="retrieval.run",
                arguments={"query": "3M FY2018 capital expenditure cash flow statement 10-K"},
                reason="search missing evidence",
            )
        ],
    )

    scaffold = _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text="What is the FY2018 capital expenditure amount in USD millions for 3M?",
        feedback=feedback,
        proposed_turn=proposed,
    )

    assert scaffold is not None
    args = scaffold.tool_calls[0].arguments
    assert args["query"] == sec_url
    assert args["queries"][0] == sec_url
    assert scaffold.reasons[0] == "host_scaffold_model_workbench_followup"


def test_deep_agent_loop_scaffold_does_not_mark_candidate_queries_as_attempted() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-workbench-candidate-not-attempted"
    run_id = "run-1"
    sec_url = "https://www.sec.gov/Archives/edgar/data/66740/000006674019000008/mmm-20181231.htm"
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-6",
        kind="action",
        data={
            "name": "retrieval.run",
            "payload": {
                "query": "Benchmark target source follows. Acquire evidence from Source URL first.",
                "queries": [
                    "Benchmark target source follows. Acquire evidence from Source URL first.",
                    sec_url,
                ],
            },
        },
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-7",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "missing_slots": ["capital_expenditures"],
            "next_queries": ["3M FY2018 capital expenditure cash flow statement 10-K"],
            "next_document_targets": [sec_url],
            "next_source_families": ["sec_edgar_filing"],
        },
    )
    feedback = Feedback(
        feedback_id="fb-workbench-followup",
        run_id=run_id,
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup"],
    )

    scaffold = _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text="What is the FY2018 capital expenditure amount in USD millions for 3M?",
        feedback=feedback,
        proposed_turn=AssistantTurn(turn_id="turn-no-tool", message=None, tool_calls=[]),
    )

    assert scaffold is not None
    assert scaffold.tool_calls[0].arguments["query"] == sec_url


def test_deep_agent_loop_scaffold_stops_after_network_budget_guard() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-workbench-network-guard"
    run_id = "run-1"
    workbench = journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-4",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "missing_slots": ["net_ppe_2018"],
            "next_queries": ["3M 2018 10-K balance sheet PP&E"],
            "next_document_targets": ["https://www.sec.gov/Archives/edgar/data/66740/000006674019000011/0000066740-19-000011-index.htm"],
            "next_source_families": ["sec_edgar"],
        },
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id="step-5",
        kind="observation",
        data={
            "kind": "host_guard",
            "status": "blocked",
            "content": {"reason": "max_network_fetches"},
            "workbench_ref": workbench.record_id,
        },
    )
    feedback = Feedback(
        feedback_id="fb-workbench-followup",
        run_id=run_id,
        status="continue",
        stop_reason=None,
        answer=None,
        missing_evidence=["retrieval_workbench_followup", "workbench_missing:net_ppe_2018"],
    )

    scaffold = _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text="What is the year end FY2018 net PPNE for 3M?",
        feedback=feedback,
        proposed_turn=AssistantTurn(turn_id="turn-no-tool", message=None, tool_calls=[]),
    )

    assert scaffold is None


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


def test_streaming_loop_injects_tool_results_into_provider_continuation() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    journal = JournalStore.in_memory()
    context_compiler = ContextCompiler()
    provider = _ToolResultContinuationProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=context_compiler,
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done after tool"),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read alpha and continue with tool result")

    assert result.status == "completed"
    assert len(provider.requests) == 2
    continuation_messages = provider.requests[1].parameters["provider_messages"]
    assert [message["role"] for message in continuation_messages] == ["user", "assistant", "tool"]
    assert continuation_messages[1]["tool_calls"][0]["id"] == "tc-alpha"
    tool_payload = json.loads(continuation_messages[2]["content"])
    assert tool_payload["schema"] == "holo.kernel_v3.provider_tool_result_message.v1"
    assert tool_payload["tool"] == "alpha.read"
    assert tool_payload["content_projection"]["shape"]["type"] == "object"
    assert tool_payload["tool_result_artifact_id"]
    assert tool_payload["tool_result_artifact_id"] in tool_payload["artifact_refs"]
    assert tool_payload["artifact_query_hint"]["tool"] == "artifact.query"
    assert tool_payload["artifact_query_hint"]["artifact_id"] == tool_payload["tool_result_artifact_id"]
    assert tool_payload["artifact_read_hint"]["tool"] == "artifact.read"
    assert tool_payload["artifact_read_hint"]["artifact_id"] == tool_payload["tool_result_artifact_id"]
    full_payload = json.loads(context_compiler.artifact_store.read_blob(tool_payload["tool_result_artifact_id"]))
    assert full_payload["schema"] == "holo.kernel_v3.tool_result_full.v1"
    assert full_payload["tool_call_id"] == "tc-alpha"

    updates = journal.records(task_id=result.task_id, kind="provider_conversation_update")
    assert updates[0].data["tool_result_count"] == 1
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    continuation = batch.data["content"]["assistant_continuation"]
    assert continuation["source"] == "provider_tool_result_continuation"
    assert continuation["has_final_answer"] is True
    assert "done after tool" in continuation["text_preview"]


def test_streaming_loop_continues_provider_tool_result_rounds_until_final_text() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    registry.register("beta.read", _read_tool("beta"))
    journal = JournalStore.in_memory()
    provider = _MultiRoundToolResultContinuationProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read", "beta.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done after beta"),
        max_steps=3,
        max_tool_calls=4,
    )

    result = loop.run("read alpha, then decide whether beta is needed")

    assert result.status == "completed"
    assert len(provider.requests) == 3
    second_messages = provider.requests[1].parameters["provider_messages"]
    assert [message["role"] for message in second_messages] == ["user", "assistant", "tool"]
    third_messages = provider.requests[2].parameters["provider_messages"]
    assert [message["role"] for message in third_messages] == ["user", "assistant", "tool", "assistant", "tool"]
    assert third_messages[3]["tool_calls"][0]["id"] == "tc-beta"
    beta_payload = json.loads(third_messages[4]["content"])
    assert beta_payload["tool"] == "beta.read"

    updates = journal.records(task_id=result.task_id, kind="provider_conversation_update")
    assert [record.data["continuation_round"] for record in updates] == [1, 2]
    turn = journal.records(task_id=result.task_id, kind="assistant_turn")[0]
    assert turn.data["tool_call_count"] == 2
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["content"]["tool_call_count"] == 2
    assert {item["tool"] for item in batch.data["content"]["results"]} == {"alpha.read", "beta.read"}
    continuation = batch.data["content"]["assistant_continuation"]
    assert continuation["has_final_answer"] is True
    assert "done after beta" in continuation["text_preview"]


def test_streaming_provider_continuation_stops_when_round_hits_tool_budget_guard() -> None:
    class EvaluatorMustNotRun:
        def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
            raise AssertionError("streaming batch budget guard should stop before evaluator")

    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    registry.register("beta.read", _read_tool("beta"))
    journal = JournalStore.in_memory()
    provider = _ContinuationRequestsOverBudgetToolProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"alpha.read", "beta.read"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=EvaluatorMustNotRun(),
        max_steps=3,
        max_tool_calls=1,
    )

    result = loop.run("read alpha, then try beta over budget")

    assert result.status == "step_limit_exceeded"
    assert result.stop_reason == "max_tool_calls"
    assert len(provider.requests) == 2
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    updates = journal.records(task_id=result.task_id, kind="provider_conversation_update")
    assert updates[-1].data["schema"] == "holo.kernel_v3.provider_tool_result_continuation_budget_guard.v1"
    assert updates[-1].data["stop_reason"] == "max_tool_calls"
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    assert batch.data["status"] == "partial"
    assert batch.data["content"]["results"][1]["kind"] == "host_guard"
    assert batch.data["content"]["results"][1]["policy"] == "max_tool_calls"


def test_streaming_continuation_loads_tool_discovered_native_schema() -> None:
    registry = ToolRegistry()
    registry.register(
        "sec.edgar.financials",
        _read_tool("sec"),
        manifest=ToolManifest(
            name="sec.edgar.financials",
            version="1",
            resource_kind="finance",
            operator_kind="sec_edgar",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="Retrieve SEC filing facts.",
            input_schema={"identifier": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True, "concurrency_safe": True},
        ),
    )
    register_tool_discovery(
        registry,
        allowed_tool_names={TOOL_DISCOVERY_NAME, "sec.edgar.financials"},
    )
    journal = JournalStore.in_memory()
    provider = _DiscoveryThenNativeToolContinuationProvider()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": provider}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={TOOL_DISCOVERY_NAME, "sec.edgar.financials"},
        tool_manifests=registry.manifests(),
        use_streaming=True,
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done after sec"),
        max_steps=3,
        max_tool_calls=4,
    )

    result = loop.run("discover the SEC tool, then retrieve 3M facts")

    assert result.status == "completed"
    assert len(provider.requests) == 3
    first_map = provider.requests[0].parameters["native_tool_name_map"]
    assert set(first_map.values()) == {TOOL_DISCOVERY_NAME}
    second_map = provider.requests[1].parameters["native_tool_name_map"]
    assert "sec.edgar.financials" in set(second_map.values())
    assert "sec.edgar.financials" not in {
        item["name"] for item in provider.requests[1].parameters["native_tool_deferred"]
    }
    discovery_payload = json.loads(provider.requests[1].parameters["provider_messages"][2]["content"])
    assert discovery_payload["discovered_tool_names"] == ["sec.edgar.financials"]
    assert discovery_payload["provider_continuation_effect"].startswith("Discovered allowed tools")


def test_json_turn_tool_discovery_expands_next_prompt_tool_surface() -> None:
    registry = ToolRegistry()
    registry.register(
        "sec.edgar.financials",
        _read_tool("sec"),
        manifest=ToolManifest(
            name="sec.edgar.financials",
            version="1",
            resource_kind="finance",
            operator_kind="sec_edgar",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="Retrieve SEC filing facts.",
            input_schema={"identifier": {"type": "str", "required": True}},
            runtime={"should_defer": True, "read_only": True, "concurrency_safe": True},
        ),
    )
    register_tool_discovery(
        registry,
        allowed_tool_names={TOOL_DISCOVERY_NAME, "sec.edgar.financials"},
    )
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-discover-sec",
                message="load SEC tool",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="tc-discover-sec",
                        name=TOOL_DISCOVERY_NAME,
                        arguments={"query": "select:sec.edgar.financials"},
                        reason="load the deferred SEC schema",
                    )
                ],
            ),
            AssistantTurn(
                turn_id="turn-final-after-discovery",
                message=None,
                tool_calls=[],
                final_answer="discovery reached next turn",
            ),
        ]
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {
                    "status": "continue",
                    "stop_reason": None,
                    "answer": None,
                    "missing_evidence": ["tool_discovery_loaded"],
                },
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "discovery reached next turn",
                    "missing_evidence": [],
                },
            ]
        ),
        max_steps=3,
    )

    result = loop.run("discover SEC tool before using it")

    assert result.status == "completed"
    second_context = planner.calls[1]
    updates = next(
        section
        for section in second_context.state["sections"]
        if section["name"] == "tool_context_updates"
    )["updates"]
    assert updates[0]["hints"]["requested_tool_names"] == ["sec.edgar.financials"]
    assert updates[0]["hints"]["loaded_tool_names"] == ["sec.edgar.financials"]

    prompt = json.loads(
        _assistant_turn_prompt(
            second_context,
            None,
            allowed_tool_names={manifest.name for manifest in registry.manifests()},
            tool_manifests=registry.manifests(),
        )
    )
    visible_by_name = {item["name"]: item for item in prompt["tool_surface"]["visible_tools"]}
    assert visible_by_name["sec.edgar.financials"]["visibility_reason"] == "context_requested"
    assert visible_by_name["sec.edgar.financials"]["input_schema"]["identifier"]["required"] is True


def test_streamed_malformed_tool_arguments_become_parse_error_observation() -> None:
    provider = _MalformedStreamingToolCallProvider()
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
    assert len(provider.requests) == 1
    assert not journal.records(task_id=result.task_id, kind="provider_conversation_update")


def test_stream_error_observation_does_not_fabricate_provider_tool_call() -> None:
    provider = _StreamErrorOnlyProvider()
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
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": "stream error observed",
                    "missing_evidence": [],
                }
            ]
        ),
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("observe provider stream error")

    assert result.status == "completed"
    assert len(provider.requests) == 1
    parse_records = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_call_parse_error"
    ]
    assert parse_records[0].data["content"]["error"] == "provider_stream_broken"
    assert not journal.records(task_id=result.task_id, kind="provider_conversation_update")


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


def test_streaming_planner_waits_for_split_tool_arguments_before_execution() -> None:
    registry = ToolRegistry()
    registry.register("alpha.read", _read_tool("alpha"))
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _SplitArgumentStreamingToolCallProvider()}, journal=journal),
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

    result = loop.run("read alpha through split streamed tool arguments")

    assert result.status == "completed"
    assert [action.name for action in registry.executed_actions] == ["alpha.read"]
    assert registry.executed_actions[0].payload["query"] == "A"
    parse_records = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_call_parse_error"
    ]
    assert parse_records == []
    turn_record = journal.records(task_id=result.task_id, kind="assistant_turn")[0]
    assert turn_record.data["tool_calls"][0]["tool_call_id"] == "tc-split-alpha"


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


def test_streaming_tool_executor_blocks_safe_tool_behind_exclusive_tool() -> None:
    events: list[str] = []
    registry = ToolRegistry()
    registry.register(
        "exclusive.write",
        _ordered_tool("exclusive", events, sleep_seconds=0.05),
        manifest=ToolManifest(
            name="exclusive.write",
            version="1",
            resource_kind="exclusive",
            operator_kind="write",
            side_effect_class="write",
            permissions_required=[],
            enabled=True,
            description="Exclusive write tool.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"concurrency_safe": False, "read_only": False},
        ),
    )
    registry.register(
        "safe.read",
        _ordered_tool("safe", events, sleep_seconds=0.0),
        manifest=ToolManifest(
            name="safe.read",
            version="1",
            resource_kind="safe",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Concurrency-safe read tool.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"concurrency_safe": True, "read_only": True},
        ),
    )
    journal = JournalStore.in_memory()
    planner = ModelAssistantTurnPlanner(
        fabric=ProcessorFabric(providers={"streaming": _TwoStreamingToolCallsProvider()}, journal=journal),
        provider="streaming",
        model="stream-model",
        allowed_tool_names={"exclusive.write", "safe.read"},
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
        max_tool_calls=4,
    )

    result = loop.run("run exclusive and safe streamed tools")

    assert result.status == "completed"
    assert [action.name for action in registry.executed_actions] == ["exclusive.write", "safe.read"]
    assert events.index("exclusive:end") < events.index("safe:start")
    execution_events = [
        (record.data["event_type"], record.data["tool_name"])
        for record in journal.records(task_id=result.task_id, kind="tool_execution_event")
        if record.data["event_type"] in {"started", "completed"}
    ]
    assert execution_events == [
        ("started", "exclusive.write"),
        ("completed", "exclusive.write"),
        ("started", "safe.read"),
        ("completed", "safe.read"),
    ]


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


def test_deep_loop_runtime_failure_requests_abort_for_running_sibling_tool() -> None:
    slow_started = threading.Event()
    abort_seen = threading.Event()

    def abortable_read(action: CandidateAction) -> Observation:
        slow_started.set()
        while not tool_abort_requested(action.payload):
            emit_tool_progress(action.payload, status="running", detail={"stage": "waiting"})
            time.sleep(0.01)
        abort_seen.set()
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="failed",
            source=f"tool:{action.name}",
            content={"aborted": True},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    def failing_coordinator(action: CandidateAction) -> Observation:
        assert slow_started.wait(1)
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="failed",
            source=f"tool:{action.name}",
            content={"failed": True},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    registry = ToolRegistry()
    registry.register(
        "slow.read",
        abortable_read,
        manifest=ToolManifest(
            name="slow.read",
            version="1",
            resource_kind="slow",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Abortable slow read.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"concurrency_safe": True, "read_only": True, "interrupt_behavior": "cancel", "timeout_seconds": 1},
        ),
    )
    registry.register(
        "coordinator.fail",
        failing_coordinator,
        manifest=ToolManifest(
            name="coordinator.fail",
            version="1",
            resource_kind="coordinator",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Coordinator read that invalidates sibling work on failure.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"concurrency_safe": True, "read_only": True, "failure_cancels_siblings": True},
        ),
    )
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-abort-sibling",
                message="run abortable sibling tools",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="tc-slow",
                        name="slow.read",
                        arguments={"query": "slow"},
                        reason="long running evidence read",
                    ),
                    ToolCallRequest(
                        tool_call_id="tc-fail",
                        name="coordinator.fail",
                        arguments={"query": "fail"},
                        reason="coordinator failure should abort sibling",
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
        max_steps=3,
        max_tool_calls=4,
    )

    result = loop.run("abort running sibling when coordinator fails")

    assert result.status == "completed"
    assert abort_seen.is_set()
    abort_events = [
        record
        for record in journal.records(task_id=result.task_id, kind="tool_execution_event")
        if record.data["event_type"] == "abort_requested"
    ]
    assert [(record.data["tool_name"], record.data["detail"]["reason"]) for record in abort_events] == [
        ("slow.read", "sibling_tool_failed")
    ]
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    by_tool = {item["tool"]: item for item in batch.data["content"]["results"]}
    assert by_tool["slow.read"]["status"] == "failed"
    assert by_tool["coordinator.fail"]["status"] == "failed"


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


def test_batch_tool_timeout_returns_failed_observation_without_waiting_for_tool_completion() -> None:
    registry = ToolRegistry()
    registry.register(
        "slow.read",
        _slow_noncooperative_read_tool(),
        manifest=ToolManifest(
            name="slow.read",
            version="1",
            resource_kind="slow",
            operator_kind="read",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="Slow non-cooperative read.",
            input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
            runtime={"interrupt_behavior": "cancel", "timeout_seconds": 1},
        ),
    )
    journal = JournalStore.in_memory()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-slow",
                message="read slow source",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-slow",
                        name="slow.read",
                        arguments={"query": "slow"},
                        reason="need slow evidence",
                        side_effect_class="read",
                    )
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
        max_steps=3,
        max_tool_calls=3,
    )

    result = loop.run("read slow source")

    assert result.status == "completed"
    events = journal.records(task_id=result.task_id, kind="tool_execution_event")
    assert any(record.data["event_type"] == "abort_requested" for record in events)
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    item = batch.data["content"]["results"][0]
    assert item["status"] == "failed"
    assert item["kind"] == "tool_call_timeout"
    assert set(item["content_projection"]["shape"]["keys"]) == {
        "abort_signal_id",
        "host_boundary",
        "interrupt_behavior",
        "reason",
        "timeout_seconds",
    }


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


def test_assistant_turn_prompt_lifts_agent_trace_for_next_turn() -> None:
    context = ContextBundle(
        context_id="ctx-agent-trace",
        thread_key="local:default",
        event_ids=[],
        memory_refs=[],
        token_budget=4096,
        state={
            "task_id": "task-1",
            "run_id": "run-1",
            "sections": [
                {
                    "name": "agent_trace",
                    "records": [
                        {
                            "record_id": "ledger-10",
                            "step_id": "step-1",
                            "kind": "assistant_turn",
                            "assistant_turn": {
                                "turn_id": "turn-1",
                                "tool_calls": [
                                    {
                                        "tool_call_id": "tc-search",
                                        "name": "retrieval.run",
                                        "arguments": {"query": "3M FY2022 10-K"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        },
    )

    prompt = _assistant_turn_prompt(context, None, allowed_tool_names={"retrieval.run"})
    payload = json.loads(prompt)

    trace = payload["context"]["state"]["agent_trace"]
    assert trace["records"][0]["kind"] == "assistant_turn"
    assert trace["records"][0]["assistant_turn"]["tool_calls"][0]["name"] == "retrieval.run"


def test_deep_agent_loop_persists_full_tool_result_artifact_for_replaced_batch() -> None:
    registry = ToolRegistry()
    registry.register("large.read", _large_read_tool())
    journal = JournalStore.in_memory()
    context_compiler = ContextCompiler()
    planner = FakeTurnPlanner(
        [
            AssistantTurn(
                turn_id="turn-large",
                message="read large source",
                tool_calls=[
                    ToolCallRequest(
                        tool_call_id="call-large",
                        name="large.read",
                        arguments={"query": "large"},
                        reason="need large evidence",
                        side_effect_class="read",
                    )
                ],
            )
        ]
    )
    loop = DeepAgentLoopController(
        journal=journal,
        context_compiler=context_compiler,
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("done"),
        max_steps=4,
        max_tool_calls=4,
    )

    result = loop.run("read large source")

    assert result.status == "completed"
    batch = [
        record
        for record in journal.records(task_id=result.task_id, kind="observation")
        if record.data.get("kind") == "tool_batch_result"
    ][0]
    item = batch.data["content"]["results"][0]
    artifact_id = item["tool_result_artifact_id"]
    replacement = item["content_replacement"]

    assert item["content_replacement_applied"] is True
    assert artifact_id in item["artifact_refs"]
    assert artifact_id in replacement["artifact_refs"]
    assert "artifact.query" in replacement["read_hint"]
    assert "artifact.read" in replacement["read_hint"]
    context_updates = journal.records(task_id=result.task_id, kind="tool_context_update")
    artifact_updates = [
        record
        for record in context_updates
        if record.data.get("update_type") == "artifact_read_hint"
    ]
    assert artifact_updates
    assert artifact_id in artifact_updates[0].data["artifact_refs"]
    assert artifact_updates[0].data["hints"]["artifact_query_hint"]["tool"] == "artifact.query"
    assert artifact_updates[0].data["hints"]["artifact_read_hint"]["artifact_id"] == artifact_id

    full_payload = json.loads(context_compiler.artifact_store.read_blob(artifact_id))
    assert full_payload["schema"] == "holo.kernel_v3.tool_result_full.v1"
    assert full_payload["tool_call_id"] == "call-large"
    assert full_payload["observation"]["content"]["blob"].startswith("RAW-LARGE-")


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


class _ToolResultContinuationProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
        provider_messages = request.parameters.get("provider_messages")
        if isinstance(provider_messages, list):
            assert provider_messages[-1]["role"] == "tool"
            yield ProcessorStreamEvent(
                event_type="stream_end",
                request_id=request.request_id,
                sequence=1,
                delta={"status": "ok", "text": '{"final_answer":"done after tool"}'},
            )
            return
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=1,
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
            sequence=2,
            delta={"status": "ok"},
        )


class _MultiRoundToolResultContinuationProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
        provider_messages = request.parameters.get("provider_messages")
        if isinstance(provider_messages, list) and len(provider_messages) == 3:
            assert provider_messages[-1]["role"] == "tool"
            yield ProcessorStreamEvent(
                event_type="tool_call_delta",
                request_id=request.request_id,
                sequence=1,
                delta={
                    "tool_calls": [
                        {
                            "id": "tc-beta",
                            "function": {
                                "name": "beta.read",
                                "arguments": '{"query":"B"}',
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
            return
        if isinstance(provider_messages, list):
            assert len(provider_messages) == 5
            assert provider_messages[-1]["role"] == "tool"
            yield ProcessorStreamEvent(
                event_type="stream_end",
                request_id=request.request_id,
                sequence=1,
                delta={"status": "ok", "text": '{"final_answer":"done after beta"}'},
            )
            return
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=1,
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
            sequence=2,
            delta={"status": "ok"},
        )


class _ContinuationRequestsOverBudgetToolProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
        provider_messages = request.parameters.get("provider_messages")
        if isinstance(provider_messages, list) and len(self.requests) == 2:
            yield ProcessorStreamEvent(
                event_type="tool_call_delta",
                request_id=request.request_id,
                sequence=1,
                delta={
                    "tool_calls": [
                        {
                            "id": "tc-beta-over-budget",
                            "function": {
                                "name": "beta.read",
                                "arguments": '{"query":"B"}',
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
            return
        if isinstance(provider_messages, list):
            raise AssertionError("provider continuation should stop after max_tool_calls guard")
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=1,
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
            sequence=2,
            delta={"status": "ok"},
        )


class _DiscoveryThenNativeToolContinuationProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
        provider_messages = request.parameters.get("provider_messages")
        native_name_map = request.parameters.get("native_tool_name_map")
        assert isinstance(native_name_map, dict)
        exposed = set(native_name_map.values())
        if not isinstance(provider_messages, list):
            assert exposed == {TOOL_DISCOVERY_NAME}
            yield ProcessorStreamEvent(
                event_type="tool_call_delta",
                request_id=request.request_id,
                sequence=1,
                delta={
                    "tool_calls": [
                        {
                            "id": "tc-discover-sec",
                            "function": {
                                "name": TOOL_DISCOVERY_NAME,
                                "arguments": '{"query":"select:sec.edgar.financials"}',
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
            return
        if len(provider_messages) == 3:
            assert "sec.edgar.financials" in exposed
            native_sec_name = next(name for name, tool in native_name_map.items() if tool == "sec.edgar.financials")
            yield ProcessorStreamEvent(
                event_type="tool_call_delta",
                request_id=request.request_id,
                sequence=1,
                delta={
                    "tool_calls": [
                        {
                            "id": "tc-sec",
                            "function": {
                                "name": native_sec_name,
                                "arguments": '{"identifier":"MMM"}',
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
            return
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=1,
            delta={"status": "ok", "text": '{"final_answer":"done after sec"}'},
        )


class _MalformedStreamingToolCallProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
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


class _StreamErrorOnlyProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.requests: list[ProcessorRequest] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.requests.append(request)
        yield ProcessorStreamEvent(
            event_type="stream_error",
            request_id=request.request_id,
            sequence=1,
            delta={"error": "provider_stream_broken"},
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


class _CaptureNativeToolSurfaceProvider:
    name = "streaming"
    model = "stream-model"

    def __init__(self) -> None:
        self.parameters: list[dict] = []

    def stream(self, request: ProcessorRequest) -> Iterable[ProcessorStreamEvent]:
        self.parameters.append(dict(request.parameters))
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=1,
            delta={"status": "ok", "text": '{"final_answer":"done"}'},
        )


class _SplitArgumentStreamingToolCallProvider:
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
                        "id": "tc-split-alpha",
                        "index": 0,
                        "function": {
                            "name": "alpha.read",
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=2,
            delta={
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {
                            "arguments": '{"query"',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=3,
            delta={
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {
                            "arguments": ':"A"}',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="finish_delta",
            request_id=request.request_id,
            sequence=4,
            delta={"finish_reason": "tool_calls"},
        )
        yield ProcessorStreamEvent(
            event_type="stream_end",
            request_id=request.request_id,
            sequence=5,
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


class _TwoStreamingToolCallsProvider:
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
                        "id": "tc-exclusive-write",
                        "function": {
                            "name": "exclusive.write",
                            "arguments": '{"query":"A"}',
                        },
                    }
                ]
            },
        )
        yield ProcessorStreamEvent(
            event_type="tool_call_delta",
            request_id=request.request_id,
            sequence=3,
            delta={
                "tool_calls": [
                    {
                        "id": "tc-safe-read",
                        "function": {
                            "name": "safe.read",
                            "arguments": '{"query":"B"}',
                        },
                    }
                ]
            },
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


def _context_update_tool():
    def execute(action: CandidateAction) -> ToolResult:
        observation = Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={
                "missing_slots": ["net_ppne"],
                "next_action": {
                    "tool": "retrieval.run",
                    "query": "3M FY2022 10-K net PP&E",
                },
            },
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )
        return ToolResult(
            observation=observation,
            artifact_refs=[],
            context_updates=[
                {
                    "update_type": "tool_declared_context",
                    "hints": {
                        "missing_slots": ["net_ppne"],
                        "next_action": {
                            "tool": "retrieval.run",
                            "query": "3M FY2022 10-K net PP&E",
                        },
                    },
                }
            ],
        )

    return execute


def _workbench_seed_tool(journal: JournalStore):
    def execute(action: CandidateAction) -> Observation:
        host_context = action.payload.get("_host_context") if isinstance(action.payload, dict) else {}
        host_context = host_context if isinstance(host_context, dict) else {}
        task_id = str(host_context.get("task_id") or "task-unknown")
        run_id = str(host_context.get("run_id") or "run-unknown")
        step_id = str(host_context.get("step_id") or "step-unknown")
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="retrieval_workbench_decision",
            data={
                "status": "ok",
                "decision": "continue",
                "missing_slots": ["net PP&E"],
                "next_queries": ["3M 2018 10-K net PP&E"],
                "next_document_targets": ["https://example.test/3m-2018-10k.pdf"],
                "next_source_families": ["company_ir_pdf"],
                "reason_summary": "Need balance sheet line item from target filing.",
            },
        )
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"seeded_workbench_followup": True},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _finance_slot_bind_seed_tool(journal: JournalStore):
    def execute(action: CandidateAction) -> Observation:
        host_context = action.payload.get("_host_context") if isinstance(action.payload, dict) else {}
        host_context = host_context if isinstance(host_context, dict) else {}
        task_id = str(host_context.get("task_id") or "task-unknown")
        run_id = str(host_context.get("run_id") or "run-unknown")
        step_id = str(host_context.get("step_id") or "step-unknown")
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="finance_slot_bind",
            data={
                "schema": "holo.kernel_v3.finance_slot_bind.v1",
                "status": "failed",
                "decision": "needs_more_evidence",
                "missing_slots": ["net_ppne"],
                "next_action": {
                    "tool": "retrieval.run",
                    "query": "3M FY2018 net PP&E balance sheet",
                    "reason": "Need target filing balance-sheet PP&E net evidence.",
                },
                "reason_summary": "Need missing balance-sheet PP&E net fact.",
            },
        )
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"seeded_finance_slot_bind_followup": True},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _ordered_tool(name: str, events: list[str], *, sleep_seconds: float):
    def execute(action: CandidateAction) -> Observation:
        events.append(f"{name}:start")
        if sleep_seconds:
            time.sleep(sleep_seconds)
        events.append(f"{name}:end")
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


def _large_read_tool():
    def execute(action: CandidateAction) -> Observation:
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"blob": "RAW-LARGE-" + "z" * 60000},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _slow_noncooperative_read_tool():
    def execute(action: CandidateAction) -> Observation:
        time.sleep(1.5)
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"done": True},
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
