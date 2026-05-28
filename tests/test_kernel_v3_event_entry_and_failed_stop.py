from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import Event
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_run_event_receives_event_and_failed_feedback_stops():
    event = Event(
        event_id="evt-input",
        run_id="incoming",
        type="input.received",
        timestamp_ms=123,
        payload={"text": "fail this task", "thread_id": "thread-1"},
        source="unit-test",
    )
    loop = LoopControllerV3(
        journal=Journal.in_memory(),
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("cannot complete"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator(
            [
                {
                    "status": "failed",
                    "stop_reason": "failed",
                    "answer": None,
                    "missing_evidence": [],
                }
            ]
        ),
    )

    result = loop.run_event(event)

    assert result.status == "failed"
    records = loop.journal.records(task_id=result.task_id)
    event_record = next(record for record in records if record.kind == "event")
    feedback_record = next(record for record in records if record.kind == "feedback")
    result_record = next(record for record in records if record.kind == "result")
    assert event_record.data["event_id"] == "evt-input"
    assert event_record.event_ref == "evt-input"
    assert feedback_record.data["status"] == "failed"
    assert result_record.state_delta == {"status": "failed"}
