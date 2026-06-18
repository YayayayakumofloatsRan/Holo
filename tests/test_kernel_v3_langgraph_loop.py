from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import _loop_controller_for_recipe, task_recipe
from kernel_v3.context import ContextCompiler
from kernel_v3.journal import JournalStore
from kernel_v3.langgraph_loop import LangGraphLoopController, langgraph_loop_available
from kernel_v3.loop import LoopControllerV3
from kernel_v3.mature_loop import MatureSingleAgentLoopController
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_langgraph_loop_controller_executes_holo_policy_tool_evaluator_path() -> None:
    assert langgraph_loop_available()
    journal = JournalStore.in_memory()
    loop = LangGraphLoopController(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner.respond_once("langgraph loop ok"),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=ToolRegistry.with_builtin_respond(),
        evaluator=FakeEvaluator.final_answer("langgraph loop ok"),
        max_steps=2,
    )

    result = loop.run("use langgraph")

    assert result.status == "completed"
    assert result.answer == "langgraph loop ok"
    context = journal.records(task_id=result.task_id, kind="context")[0]
    assert context.state_delta["loop_runtime"] == "langgraph"
    assert journal.records(task_id=result.task_id, kind="policy_decision")
    assert journal.records(task_id=result.task_id, kind="observation")[0].data["source"] == "respond"
    assert journal.records(task_id=result.task_id, kind="feedback")[0].data["status"] == "final_answer_ready"


def test_finance_capability_execution_profile_selects_mature_single_agent_loop_controller() -> None:
    metadata = execution_profile_runtime_metadata(execution_profile("finance-capability"))
    recipe = task_recipe("retrieval_answer", metadata=metadata)

    assert metadata["agent_loop"]["runtime_backend"] == "deep_agent_loop"
    assert _loop_controller_for_recipe(recipe) is MatureSingleAgentLoopController


def test_finance_fast_execution_profile_still_selects_langgraph_loop_controller() -> None:
    metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=metadata)

    assert metadata["agent_loop"]["runtime_backend"] == "langgraph"
    assert _loop_controller_for_recipe(recipe) is LangGraphLoopController


def test_plain_recipe_keeps_holo_loop_controller_without_langgraph_metadata() -> None:
    recipe = task_recipe("retrieval_answer", metadata={})

    assert _loop_controller_for_recipe(recipe) is LoopControllerV3
