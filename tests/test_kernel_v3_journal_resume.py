from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import Journal
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_resume_uses_task_id_and_journal_state_not_retry_phrase():
    journal_path = Path("kernel_v3/.test-journal-resume.jsonl")
    if journal_path.exists():
        journal_path.unlink()
    try:
        journal = Journal(journal_path)
        question = CandidateAction(
            action_id="act-clarify",
            kind="respond",
            name=None,
            description="ask for missing input",
            score=1.0,
            payload={"text": "请确认目标文件路径。"},
            reasons=["file path missing"],
            side_effect_class="none",
        )
        first_loop = LoopControllerV3(
            journal=journal,
            context_compiler=ContextCompiler(),
            planner=FakePlanner([question]),
            policy_gate=PolicyGate(permission="read_write"),
            tool_registry=ToolRegistry.with_builtin_respond(),
            evaluator=FakeEvaluator.needs_user_input("请确认目标文件路径。"),
        )

        first_result = first_loop.run("整理这个文件")

        assert first_result.status == "needs_user_input"
        task_id = first_result.task_id

        resumed_action = CandidateAction(
            action_id="act-final",
            kind="respond",
            name=None,
            description="answer after user clarified",
            score=1.0,
            payload={"text": "已根据 journal 中的任务状态继续。"},
            reasons=["resumed by task id"],
            side_effect_class="none",
        )
        resumed_loop = LoopControllerV3(
            journal=Journal(journal_path),
            context_compiler=ContextCompiler(),
            planner=FakePlanner([resumed_action]),
            policy_gate=PolicyGate(permission="read_write"),
            tool_registry=ToolRegistry.with_builtin_respond(),
            evaluator=FakeEvaluator.final_answer("已根据 journal 中的任务状态继续。"),
        )

        resumed_result = resumed_loop.resume(task_id, thread_id="local:default", user_input="README.md")

        assert resumed_result.status == "completed"
        assert resumed_result.task_id == task_id
        records = resumed_loop.journal.records(task_id=task_id)
        assert any(record.kind == "resume" and record.data["user_input"] == "README.md" for record in records)
        assert [record.data["action_id"] for record in records if record.kind == "action"] == [
            "act-clarify",
            "act-final",
        ]
        assert all(record.data.get("thread_id", "local:default") == "local:default" for record in records)
    finally:
        if journal_path.exists():
            journal_path.unlink()
