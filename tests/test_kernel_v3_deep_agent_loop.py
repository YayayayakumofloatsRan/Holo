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
    assert "artifact.read" in replacement["read_hint"]

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
