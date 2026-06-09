from __future__ import annotations

from types import SimpleNamespace

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.execution_profile import (
    execution_profile,
    execution_profile_runtime_metadata,
    profile_mission_enabled,
    profile_processor_mode,
)
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.mission import MissionRuntime
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID


def test_finance_fact_fast_profile_is_short_lane() -> None:
    profile = execution_profile("finance-fact-fast")
    metadata = execution_profile_runtime_metadata(profile)

    assert profile.use_mission_supervisor is False
    assert profile.use_workmethod is False
    assert profile_processor_mode(profile, "evaluator", "model", online=True) == "fake"
    assert profile_processor_mode(profile, "semantic_intake", "model", online=True) == "fake"
    assert metadata["agent_loop"]["max_steps"] == 4
    assert metadata["retrieval"]["max_fetches"] == 8
    assert metadata["processor_budget"]["max_calls_per_task"] == 4


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
    assert metadata["agent_loop"]["max_steps"] == 4
    assert metadata["agent_loop"]["max_tool_calls"] == 3
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
