from kernel_v3.context import ContextCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.session import SessionEngine, TaskState
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_session_engine_reconstructs_active_task_state_from_journal_only():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-7",
        run_id="run-1",
        step_id=None,
        kind="task",
        data={
            "task_id": "task-7",
            "thread_id": "thread-a",
            "input_text": "inspect README",
            "status": "running",
        },
        state_delta={"status": "running"},
    )
    journal.append(
        task_id="task-7",
        run_id="run-1",
        step_id="step-1",
        kind="feedback",
        data={"status": "needs_user_input", "feedback_id": "fb-1"},
        feedback_ref="fb-1",
        state_delta={"status": "needs_user_input"},
    )

    state = SessionEngine.from_journal(journal).active_task("task-7")

    assert state == TaskState(
        task_id="task-7",
        run_id="run-1",
        thread_id="thread-a",
        input_text="inspect README",
        status="needs_user_input",
        step_id="step-1",
    )


def test_session_engine_start_resume_and_replay_are_journal_derived():
    journal = JournalStore.in_memory()
    engine = SessionEngine.from_journal(journal)

    started = engine.start("hello", thread_id="thread-a", journal=journal)
    resumed = engine.resume(started.task_id, "more detail", thread_id="thread-a", journal=journal)
    replayed = list(engine.replay(started.task_id))

    assert started.task_id == "task-1"
    assert started.run_id == "run-1"
    assert started.step_id == "step-0"
    assert resumed.task_id == started.task_id
    assert resumed.run_id == "run-2"
    assert resumed.step_id == "step-0"
    assert replayed == journal.records(task_id=started.task_id)
    assert engine.active_task(started.task_id).run_id == "run-2"


def test_loop_default_session_engine_derives_task_ids_from_journal():
    journal = JournalStore.in_memory()
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("first"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.final_answer("first"),
    )

    first = loop.run("first input")
    loop.planner = FakePlanner.respond_once("second")
    loop.evaluator = FakeEvaluator.final_answer("second")
    second = loop.run("second input")

    assert first.task_id == "task-1"
    assert second.task_id == "task-2"
    assert journal.records(task_id="task-1")
    assert journal.records(task_id="task-2")
