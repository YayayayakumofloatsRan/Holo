from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_policy_block_is_auditable_outcome_not_exception():
    action = CandidateAction(
        action_id="act-delete",
        kind="tool",
        name="file.delete",
        description="delete project files",
        score=1.0,
        payload={"path": "."},
        reasons=["user asked for deletion"],
        side_effect_class="destructive",
    )
    loop = LoopControllerV3(
        journal=Journal.in_memory(),
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_only"),
        tool_registry=ToolRegistry(),
        evaluator=FakeEvaluator.stop_on_block(),
    )

    result = loop.run("删除整个项目")

    assert result.status in {"blocked", "needs_user_input"}
    records = loop.journal.records()
    decision_record = next(record for record in records if record.kind == "policy_decision")
    observation_record = next(record for record in records if record.kind == "observation")
    feedback_record = next(record for record in records if record.kind == "feedback")
    assert decision_record.data["allowed"] is False
    assert observation_record.data["status"] == "blocked"
    assert observation_record.data["action_id"] == "act-delete"
    assert feedback_record.data["stop_reason"] in {"blocked", "needs_user_input"}
