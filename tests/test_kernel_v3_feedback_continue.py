from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Observation
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def _tool_observation(candidate: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{candidate.action_id}",
        run_id="",
        kind="tool_result",
        status="ok",
        source=f"tool:{candidate.name}",
        content={"tool": candidate.name, "result": candidate.payload.get("query") or candidate.payload.get("path")},
        observed_at_ms=0,
        action_id=candidate.action_id,
        tool_call_id=None,
    )


def test_feedback_can_drive_continuation_in_same_task():
    search = CandidateAction(
        action_id="act-search",
        kind="tool",
        name="workspace.search",
        description="search README",
        score=1.0,
        payload={"query": "Holo"},
        reasons=["need initial evidence"],
        side_effect_class="read",
    )
    read = CandidateAction(
        action_id="act-read",
        kind="tool",
        name="file.read",
        description="read README",
        score=1.0,
        payload={"path": "README.md"},
        reasons=["evaluator asked for file.read"],
        side_effect_class="read",
    )
    registry = ToolRegistry()
    registry.register("workspace.search", _tool_observation)
    registry.register("file.read", _tool_observation)
    loop = LoopControllerV3(
        journal=Journal.in_memory(),
        context_compiler=ContextCompiler(),
        planner=FakePlanner([search, read]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {"status": "continue", "missing_evidence": ["need file.read"], "answer": None},
                {"status": "final_answer_ready", "missing_evidence": [], "answer": "Holo definition from README.md"},
            ]
        ),
    )

    result = loop.run("搜索 README 里 Holo 的定义")

    assert result.status == "completed"
    assert result.answer == "Holo definition from README.md"
    assert search.action_id != read.action_id
    records = loop.journal.records()
    task_ids = {record.task_id for record in records if record.task_id is not None}
    assert len(task_ids) == 1
    assert [record.data["action_id"] for record in records if record.kind == "action"] == [
        "act-search",
        "act-read",
    ]
    assert [record.data["status"] for record in records if record.kind == "feedback"] == [
        "continue",
        "final_answer_ready",
    ]
