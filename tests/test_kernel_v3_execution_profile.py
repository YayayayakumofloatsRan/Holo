from __future__ import annotations

from types import SimpleNamespace

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import TaskRecipe
from kernel_v3.agent.execution_profile import (
    execution_profile,
    execution_profile_runtime_metadata,
    profile_mission_enabled,
    profile_processor_mode,
)
from kernel_v3.agent.runtime import _disabled_workmethod_state, _with_runtime_loop_budget
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import ProcessorRequest, ProcessorResult
from kernel_v3.journal import JournalStore
from kernel_v3.mission import MissionRuntime
from kernel_v3.processors import PLANNER_SCHEMA, FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID


def test_finance_fact_fast_profile_is_short_lane() -> None:
    profile = execution_profile("finance-fact-fast")
    metadata = execution_profile_runtime_metadata(profile)

    assert profile.use_mission_supervisor is False
    assert profile.use_workmethod is False
    assert profile_processor_mode(profile, "evaluator", "model", online=True) == "fake"
    assert profile_processor_mode(profile, "semantic_intake", "model", online=True) == "fake"
    assert metadata["agent_loop"]["max_steps"] == 8
    assert metadata["agent_loop"]["max_tool_calls"] == 8
    assert metadata["retrieval"]["max_fetches"] == 8
    assert metadata["processor_budget"]["max_calls_per_task"] == 8
    assert metadata["composable_toolchain"]["enabled"] is True
    assert metadata["composable_toolchain"]["shell_exec"] is True
    assert metadata["composable_toolchain"]["model_task_compiler"] is True
    assert metadata["composable_toolchain"].get("workspace_write") is False
    assert metadata["composable_toolchain"].get("script_exec") is False


def test_finance_capability_profile_is_high_budget_toolchain_lane() -> None:
    profile = execution_profile("finance-capability")
    metadata = execution_profile_runtime_metadata(profile)

    assert profile.use_mission_supervisor is False
    assert profile.use_semantic_intake_model is True
    assert profile.max_agent_steps == 16
    assert profile.max_agent_tool_calls == 16
    assert profile.research_depth == "deep"
    assert metadata["composable_toolchain"]["workspace_read"] is True
    assert metadata["composable_toolchain"]["workspace_write"] is True
    assert metadata["composable_toolchain"]["script_exec"] is True
    assert metadata["composable_toolchain"]["shell_exec"] is True
    assert metadata["composable_toolchain"]["shell_timeout_seconds"] >= 30


def test_long_mission_profile_preserves_heavy_supervision() -> None:
    profile = execution_profile("long-mission")

    assert profile.use_mission_supervisor is True
    assert profile.use_workmethod is True
    assert profile_processor_mode(profile, "evaluator", "fake", online=True) == "model"
    assert profile_mission_enabled(profile, requested="auto") is True
    assert profile_mission_enabled(profile, requested="off") is False


def test_benchmark_runtime_metadata_uses_execution_profile_defaults() -> None:
    args = _benchmark_args(execution_profile="finance-fact-fast")

    metadata = cli._runtime_execution_metadata(args)

    assert metadata is not None
    assert metadata["execution_profile"]["profile_id"] == "finance-fact-fast"
    assert metadata["context_budget"]["token_budget"] == 4096
    assert metadata["agent_loop"]["max_steps"] == 8
    assert metadata["agent_loop"]["max_tool_calls"] == 8
    assert metadata["retrieval"]["max_queries"] == 4
    assert metadata["retrieval"]["max_sources"] == 24
    assert metadata["retrieval"]["max_fetches"] == 8
    assert metadata["retrieval"]["metadata"]["research_depth"] == "light"


def test_benchmark_runtime_metadata_keeps_explicit_loop_overrides() -> None:
    args = _benchmark_args(execution_profile="finance-fact-fast", max_agent_steps=9, max_agent_tool_calls=7)

    metadata = cli._runtime_execution_metadata(args)

    assert metadata is not None
    assert metadata["agent_loop"]["max_steps"] == 9
    assert metadata["agent_loop"]["max_tool_calls"] == 7


def test_fast_execution_profile_loop_budget_is_hard_cap_for_model_planner() -> None:
    metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = TaskRecipe(
        recipe_id="recipe-retrieval-answer",
        allowed_tools=["retrieval.run"],
        max_steps=2048,
        max_tool_calls=1024,
        max_network_fetches=2048,
        max_total_artifact_bytes=100_000_000,
        permission_profile="read_write",
        citations_required=True,
        finalizer="retrieval_synthesizer",
        context_budget_mode="truncate",
        mode="retrieval_answer",
        metadata={"execution_metadata": metadata},
    )

    bounded = _with_runtime_loop_budget(recipe, planner_mode="model")

    assert bounded.max_steps == 8
    assert bounded.max_tool_calls == 8


def test_fast_execution_profile_disabled_workmethod_state_is_constructible() -> None:
    metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))

    state = _disabled_workmethod_state(
        goal="Investigate AAPL fundamentals.",
        thread_id="thread-fast",
        task_plan=SimpleNamespace(plan_id="plan-fast", selected_mode="retrieval_answer"),
        execution_metadata=metadata,
    )

    assert state.source == "disabled_by_execution_profile"
    assert state.frame["work_type"] == "execution_profile_fast_lane"
    assert state.method["method_name"] == "fast_lane_without_workmethod"


def test_long_mission_without_profile_still_allows_dynamic_model_loop_budget() -> None:
    recipe = TaskRecipe(
        recipe_id="recipe-retrieval-answer",
        allowed_tools=["retrieval.run"],
        max_steps=2,
        max_tool_calls=1,
        max_network_fetches=2048,
        max_total_artifact_bytes=1_000_000,
        permission_profile="read_write",
        citations_required=True,
        finalizer="retrieval_synthesizer",
        context_budget_mode="truncate",
        mode="retrieval_answer",
        metadata={},
    )

    bounded = _with_runtime_loop_budget(recipe, planner_mode="model")

    assert bounded.max_steps == 2048
    assert bounded.max_tool_calls == 1024


def test_processor_budget_blocks_oversized_prompt_before_provider_call() -> None:
    journal = JournalStore.in_memory()
    provider = _CountingJsonProvider(_planner_payload())
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-budget",
        run_id="run-budget",
        context_id="ctx-budget",
        prompt="x" * 20,
        schema=PLANNER_SCHEMA,
        parameters={"processor_budget": {"max_prompt_chars_per_call": 8}},
    )

    assert outcome.result.status == "failed"
    assert outcome.result.error == "processor_budget_exceeded"
    assert outcome.result.output["reason"] == "max_prompt_chars_per_call"
    assert provider.calls == 0


def test_processor_budget_blocks_calls_after_task_limit() -> None:
    provider = _CountingJsonProvider(_planner_payload())
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
    )
    parameters = {"processor_budget": {"max_calls_per_task": 1}}

    first = fabric.run_json(
        task_type="planner.propose",
        task_id="task-budget",
        run_id="run-budget",
        context_id="ctx-budget",
        prompt="first",
        schema=PLANNER_SCHEMA,
        parameters=parameters,
    )
    second = fabric.run_json(
        task_type="planner.propose",
        task_id="task-budget",
        run_id="run-budget",
        context_id="ctx-budget",
        prompt="second",
        schema=PLANNER_SCHEMA,
        parameters=parameters,
    )

    assert first.result.status == "ok"
    assert second.result.status == "failed"
    assert second.result.error == "processor_budget_exceeded"
    assert second.result.output["reason"] == "max_calls_per_task"
    assert provider.calls == 1


def test_processor_budget_blocks_after_total_token_limit_is_spent() -> None:
    provider = _CountingJsonProvider(_planner_payload())
    fabric = ProcessorFabric(
        providers={"fake_json": provider},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
    )
    parameters = {"processor_budget": {"max_total_tokens_per_task": 1}}

    first = fabric.run_json(
        task_type="planner.propose",
        task_id="task-token-budget",
        run_id="run-budget",
        context_id="ctx-budget",
        prompt="first",
        schema=PLANNER_SCHEMA,
        parameters=parameters,
    )
    second = fabric.run_json(
        task_type="planner.propose",
        task_id="task-token-budget",
        run_id="run-budget",
        context_id="ctx-budget",
        prompt="second",
        schema=PLANNER_SCHEMA,
        parameters=parameters,
    )

    assert first.result.status == "ok"
    assert second.result.status == "failed"
    assert second.result.error == "processor_budget_exceeded"
    assert second.result.output["reason"] == "max_total_tokens_per_task"
    assert provider.calls == 1


def test_chat_runtime_can_skip_mission_wrapper() -> None:
    journal = JournalStore.in_memory()
    runtime = cli._chat_runtime(
        journal,
        artifact_store=ArtifactStore.in_memory(),
        live_model=False,
        mission_enabled=False,
    )

    assert isinstance(runtime.agent_runtime, AgentRuntime)
    assert not isinstance(runtime.agent_runtime, MissionRuntime)


def test_chat_runtime_defaults_to_mission_wrapper() -> None:
    journal = JournalStore.in_memory()
    runtime = cli._chat_runtime(
        journal,
        artifact_store=ArtifactStore.in_memory(),
        live_model=False,
    )

    assert isinstance(runtime.agent_runtime, MissionRuntime)


def _benchmark_args(**overrides):
    values = {
        "execution_profile": "finance-fact-fast",
        "response_language": "zh",
        "context_profile": cli.DEFAULT_LIVE_CONTEXT_PROFILE,
        "context_token_budget": None,
        "context_section_budget": None,
        "workspace_evidence_chars": None,
        "synthesis_evidence_preview_chars": None,
        "max_agent_steps": None,
        "max_agent_tool_calls": None,
        "max_agent_artifact_bytes": None,
        "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
        "research_depth": cli.DEFAULT_RESEARCH_DEPTH,
        "live_retrieval": None,
        "live_max_network_fetches": cli.DEFAULT_LIVE_NETWORK_FETCH_BUDGET,
        "command": "bench",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _planner_payload():
    return {
        "action_id": "act-answer",
        "kind": "respond",
        "name": None,
        "description": "answer",
        "payload": {"text": "ok"},
        "score": 1.0,
        "reasons": ["test"],
        "side_effect_class": "none",
    }


class _CountingJsonProvider(FakeJsonProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.calls = 0

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        self.calls += 1
        return super().run(request)
