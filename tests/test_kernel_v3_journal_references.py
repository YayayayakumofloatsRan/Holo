from kernel_v3.context import ContextCompiler
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_journal_records_have_transition_references_and_state_deltas():
    journal = Journal.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("ok"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.final_answer("ok"),
    )

    result = loop.run("hello")

    records = journal.records(task_id=result.task_id)
    event_record = next(record for record in records if record.kind == "event")
    action_record = next(record for record in records if record.kind == "action")
    observation_record = next(record for record in records if record.kind == "observation")
    feedback_record = next(record for record in records if record.kind == "feedback")
    result_record = next(record for record in records if record.kind == "result")

    assert event_record.event_ref == event_record.data["event_id"]
    assert action_record.event_ref == event_record.event_ref
    assert action_record.action_ref == action_record.data["action_id"]
    assert observation_record.action_ref == action_record.action_ref
    assert observation_record.observation_ref == observation_record.data["observation_id"]
    assert feedback_record.observation_ref == observation_record.observation_ref
    assert feedback_record.feedback_ref == feedback_record.data["feedback_id"]
    assert result_record.feedback_ref == feedback_record.feedback_ref
    assert result_record.state_delta == {"status": "completed"}
