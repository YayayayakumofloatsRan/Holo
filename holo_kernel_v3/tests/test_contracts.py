import json
from pathlib import Path

import holo_kernel_v3.contracts as contracts
from holo_kernel_v3.contracts import (
    CandidateAction,
    ContextBundle,
    Event,
    LedgerRecord,
    MemoryWriteProposal,
    Observation,
    PolicyDecision,
    ProcessorRequest,
    ProcessorResult,
    Run,
    Step,
    Task,
    ToolCall,
)


SCHEMA_EXAMPLES = [
    Event(
        event_id="evt-1",
        run_id="run-1",
        type="message.received",
        timestamp_ms=1_700_000_000_000,
        payload={"text": "hello"},
        source="wechat",
    ),
    Task(
        task_id="task-1",
        goal="answer user",
        status="pending",
        created_at_ms=1_700_000_000_001,
        priority=5,
        metadata={"thread_key": "wechat:Alice"},
    ),
    Run(
        run_id="run-1",
        task_id="task-1",
        status="running",
        started_at_ms=1_700_000_000_002,
        ended_at_ms=None,
        metadata={"kernel": "v3"},
    ),
    Step(
        step_id="step-1",
        run_id="run-1",
        index=0,
        kind="policy",
        status="done",
        input_ref="evt-1",
        output_ref="decision-1",
        error=None,
    ),
    ContextBundle(
        context_id="ctx-1",
        thread_key="wechat:Alice",
        event_ids=["evt-1"],
        memory_refs=["mem-1"],
        state={"mood": "neutral"},
        token_budget=4096,
    ),
    CandidateAction(
        action_id="act-1",
        kind="reply",
        description="send concise answer",
        score=0.8,
        payload={"text": "hi"},
        reasons=["direct user request"],
    ),
    PolicyDecision(
        decision_id="decision-1",
        run_id="run-1",
        selected_action_id="act-1",
        action="reply",
        confidence=0.74,
        rationale="user asked a direct question",
        candidate_action_ids=["act-1", "act-2"],
        constraints={"send_allowed": True},
    ),
    ToolCall(
        tool_call_id="tool-1",
        run_id="run-1",
        name="search_memory",
        arguments={"query": "last topic"},
        status="requested",
    ),
    Observation(
        observation_id="obs-1",
        run_id="run-1",
        source="tool:search_memory",
        content={"matches": []},
        observed_at_ms=1_700_000_000_003,
        tool_call_id="tool-1",
    ),
    ProcessorRequest(
        request_id="preq-1",
        run_id="run-1",
        processor="default",
        prompt="Answer briefly",
        context_id="ctx-1",
        parameters={"temperature": 0.2},
    ),
    ProcessorResult(
        result_id="pres-1",
        request_id="preq-1",
        status="ok",
        output={"text": "hello"},
        usage={"input_tokens": 12, "output_tokens": 3},
        error=None,
    ),
    MemoryWriteProposal(
        proposal_id="memprop-1",
        run_id="run-1",
        memory_type="episodic",
        key="wechat:Alice:last_topic",
        value={"topic": "kernel"},
        rationale="durable user project context",
        confidence=0.9,
    ),
    LedgerRecord(
        record_id="ledger-1",
        run_id="run-1",
        event_id="evt-1",
        step_id="step-1",
        kind="decision",
        data={"decision_id": "decision-1"},
        recorded_at_ms=1_700_000_000_004,
    ),
]


def test_all_contract_schemas_round_trip_through_dicts():
    for schema in SCHEMA_EXAMPLES:
        encoded = schema.to_dict()
        decoded = type(schema).from_dict(encoded)

        assert decoded == schema
        assert decoded.to_dict() == encoded


def test_all_contract_schemas_round_trip_through_json():
    for schema in SCHEMA_EXAMPLES:
        payload = json.dumps(schema.to_dict(), sort_keys=True)
        decoded = type(schema).from_dict(json.loads(payload))

        assert decoded == schema


def test_contracts_do_not_import_old_holo_host_modules():
    source = Path(contracts.__file__).read_text(encoding="utf-8")

    assert "holo_host" not in source
