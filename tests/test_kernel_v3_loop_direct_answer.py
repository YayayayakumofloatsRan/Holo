from kernel_v3.context import ContextCompiler
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.result import AgentResult
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_direct_answer_uses_full_loop():
    journal = Journal.in_memory()
    planner = FakePlanner.respond_once("我可以通过 kernel v3 执行受控任务。")
    evaluator = FakeEvaluator.final_answer("我可以通过 kernel v3 执行受控任务。")
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=planner,
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=evaluator,
    )

    result = loop.run("你能做什么？")

    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert result.answer == "我可以通过 kernel v3 执行受控任务。"
    assert planner.calls[0].state["input_text"] == "你能做什么？"

    records = journal.records()
    kinds = [record.kind for record in records]
    assert kinds == [
        "event",
        "task",
        "run",
        "context",
        "action",
        "policy_decision",
        "observation",
        "feedback",
        "result",
    ]
    assert records[0].data["type"] == "input.received"
    assert records[3].data["context_id"].startswith("ctx-")
    assert records[4].data["kind"] == "respond"
    assert records[5].data["allowed"] is True
    assert records[6].data["kind"] == "respond_result"
    assert records[7].data["status"] == "final_answer_ready"
