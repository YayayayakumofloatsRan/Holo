from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


FORBIDDEN_DISPATCH_NAMES = [
    "web_search",
    "page_open",
    "file_read",
    "wechat",
    "memory_consolidate",
    "subagent",
    "research",
    "workspace.search",
    "file.read",
]


def test_loop_source_does_not_dispatch_by_concrete_tool_names():
    source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")

    for name in FORBIDDEN_DISPATCH_NAMES:
        assert name not in source


def test_unregistered_tool_names_still_use_same_generic_dispatch_path():
    action = CandidateAction(
        action_id="act-custom",
        kind="tool",
        name="custom.operator",
        description="call custom operator",
        score=1.0,
        payload={"value": 1},
        reasons=["test generic dispatch"],
        side_effect_class="read",
    )
    registry = ToolRegistry()
    registry.register(
        "custom.operator",
        lambda candidate: Observation(
            observation_id="obs-custom",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{candidate.name}",
            content={"ok": True},
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
        evaluator=FakeEvaluator.final_answer("custom operator completed"),
    )

    result = loop.run("run custom operator")

    assert result.status == "completed"
    assert registry.executed_actions == [action]
