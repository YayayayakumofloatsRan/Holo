import json
from pathlib import Path

import kernel_v3.contracts as contracts
from kernel_v3.contracts import (
    ArtifactRef,
    CandidateAction,
    ContextBundle,
    Event,
    Feedback,
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
    ToolManifest,
)


SCHEMA_EXAMPLES = [
    Event(
        event_id="evt-1",
        run_id="run-1",
        type="message.received",
        timestamp_ms=1_700_000_000_000,
        payload={"text": "hello"},
        source="cli",
    ),
    Task(
        task_id="task-1",
        goal="answer user",
        status="pending",
        created_at_ms=1_700_000_000_001,
        priority=5,
        metadata={"thread_key": "local:default"},
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
        thread_key="local:default",
        event_ids=["evt-1"],
        memory_refs=[],
        state={"task_id": "task-1"},
        token_budget=4096,
    ),
    CandidateAction(
        action_id="act-1",
        kind="respond",
        description="send concise answer",
        score=0.8,
        payload={"text": "hi"},
        reasons=["direct user request"],
        name=None,
        side_effect_class="none",
    ),
    PolicyDecision(
        decision_id="decision-1",
        run_id="run-1",
        action_id="act-1",
        allowed=True,
        reason="safe",
        constraints={"permission": "read_write"},
    ),
    ToolCall(
        tool_call_id="tool-1",
        run_id="run-1",
        action_id="act-1",
        name="workspace.search",
        arguments={"query": "Holo"},
        status="requested",
    ),
    ToolManifest(
        name="workspace.search",
        version="1",
        resource_kind="workspace",
        operator_kind="search",
        side_effect_class="read",
        permissions_required=["workspace:read"],
        enabled=True,
        description="Search workspace text",
        input_schema={"query": "str"},
    ),
    Observation(
        observation_id="obs-1",
        run_id="run-1",
        kind="tool_result",
        status="ok",
        source="tool:workspace.search",
        content={"matches": []},
        observed_at_ms=1_700_000_000_003,
        action_id="act-1",
        tool_call_id="tool-1",
    ),
    ArtifactRef(
        artifact_id="artifact-obs-1",
        kind="observation_payload",
        uri="journal://obs-1",
        payload_hash="hash-1",
        metadata={"observation_id": "obs-1"},
    ),
    Feedback(
        feedback_id="fb-1",
        run_id="run-1",
        status="final_answer_ready",
        stop_reason="completed",
        answer="hello",
        missing_evidence=[],
    ),
    ProcessorRequest(
        request_id="preq-1",
        run_id="run-1",
        processor="fake",
        prompt="Answer briefly",
        context_id="ctx-1",
        parameters={"temperature": 0.0},
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
        key="local:default:last_topic",
        value={"topic": "kernel"},
        rationale="durable user project context",
        confidence=0.9,
    ),
    LedgerRecord(
        schema_version=1,
        record_id="ledger-1",
        task_id="task-1",
        run_id="run-1",
        step_id="step-1",
        kind="decision",
        data={"decision_id": "decision-1"},
        recorded_at_ms=1_700_000_000_004,
        event_ref="evt-1",
        action_ref="act-1",
        observation_ref="obs-1",
        feedback_ref="fb-1",
        state_delta={"status": "completed"},
        artifact_refs=["artifact://ledger-1"],
        payload_hash="hash-1",
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
    assert "reply_api" not in source
    assert "processors" not in source
    assert "memory_bridge" not in source
