from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_tool_action_uses_generic_registry_dispatch():
    action = CandidateAction(
        action_id="act-search",
        kind="tool",
        name="workspace.search",
        description="search workspace text",
        score=1.0,
        payload={"query": "Holo"},
        reasons=["user requested README search"],
        side_effect_class="read",
    )
    registry = ToolRegistry()
    registry.register(
        "workspace.search",
        lambda candidate: Observation(
            observation_id="obs-search",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{candidate.name}",
            content={"matches": ["Holo is an agent harness"]},
            observed_at_ms=0,
            action_id=candidate.action_id,
            tool_call_id=None,
        ),
    )
    loop = LoopControllerV3(
        journal=Journal.in_memory(),
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("Holo is an agent harness"),
    )

    result = loop.run("搜索 README 里 Holo 的定义")

    assert result.status == "completed"
    assert registry.executed_actions == [action]
    records = loop.journal.records()
    action_record = next(record for record in records if record.kind == "action")
    observation_record = next(record for record in records if record.kind == "observation")
    assert action_record.data["name"] == "workspace.search"
    assert observation_record.data["kind"] == "tool_result"
    assert observation_record.data["action_id"] == action_record.data["action_id"]
