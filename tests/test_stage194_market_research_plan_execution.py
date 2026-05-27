from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_action_planner import build_market_research_action_plan
from holo_host.market_research_feedback_loop import build_market_research_feedback_loop
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures


def _ready_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def _source_weak_plan() -> dict:
    fixture = default_market_research_pack_fixtures()[1]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=2,
    )
    return build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=2,
        network_enabled=True,
    )


def test_stage194_executes_stage193_web_search_plan_with_mocked_provider() -> None:
    from holo_host.market_research_plan_executor import (
        STAGE194_MARKET_RESEARCH_PLAN_EXECUTION_SCHEMA,
        execute_market_research_action_plan,
    )

    plan = _source_weak_plan()
    execution = execute_market_research_action_plan(
        plan,
        question="Analyze Apple AAPL 2024 10-K.",
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock_sec_search",
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple annual report on Form 10-K.",
                }
            ],
        },
    )

    assert execution["schema"] == STAGE194_MARKET_RESEARCH_PLAN_EXECUTION_SCHEMA
    assert execution["status"] == "executed"
    assert execution["executed_count"] == 1
    assert execution["executed_action"] == "web_search"
    assert execution["web_observation_ledger"][0]["status"] == "ok"
    assert "sec.gov" in execution["web_observation_ledger"][0]["source_urls"][0]
    assert execution["canonical_stop_reason"] == "final_answer_ready"


def test_stage194_blocks_stage193_web_plan_when_network_disabled() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan
    from holo_host.market_research_plan_executor import execute_market_research_action_plan

    fixture = default_market_research_pack_fixtures()[1]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=1,
    )
    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        remaining_action_budget=1,
        network_enabled=False,
    )

    execution = execute_market_research_action_plan(
        plan,
        question="Analyze Apple AAPL 2024 10-K.",
        network_enabled=False,
        web_search_fn=lambda query: (_ for _ in ()).throw(AssertionError("network should not be called")),
    )

    assert execution["status"] == "blocked"
    assert execution["rejected_count"] == 1
    assert execution["executed_count"] == 0
    assert execution["canonical_stop_reason"] == "boundary_or_permission"
    assert execution["action_results"][0]["blocked_reason"] == "network_disabled"


def test_stage194_executes_market_research_report_plan_and_reenters_feedback() -> None:
    from holo_host.market_research_plan_executor import execute_market_research_action_plan

    pack = _ready_pack()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=1,
    )
    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=1,
    )

    execution = execute_market_research_action_plan(
        plan,
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        network_enabled=False,
    )

    assert execution["status"] == "executed"
    assert execution["executed_action"] == "market_research_report"
    assert execution["market_research_report_ledger"][0]["status"] == "ok"
    assert execution["stage173_market_research_report"]["status"] == "evidence_ready"
    assert execution["post_action_stage192_feedback_loop"]["can_finalize"] is True


def test_stage194_event_stream_renders_market_execution_without_hidden_reasoning() -> None:
    from holo_host.market_research_plan_executor import execute_market_research_action_plan

    plan = _source_weak_plan()
    execution = execute_market_research_action_plan(
        plan,
        question="Analyze Apple AAPL 2024 10-K.",
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock_sec_search",
            "results": [{"title": "Apple Form 10-K", "url": "https://www.sec.gov/aapl-10k", "snippet": "filing"}],
        },
    )
    stream = build_agent_event_stream(
        {
            "text": "searched",
            "stage193_market_research_action_plan": plan,
            "stage194_market_research_plan_execution": execution,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_exec]" in rendered
    assert "web_search" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob


def test_stage194_topology_includes_market_execution_node() -> None:
    from holo_host.market_research_plan_executor import execute_market_research_action_plan

    pack = _ready_pack()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
    )
    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report={},
    )
    execution = execute_market_research_action_plan(
        plan,
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        network_enabled=False,
    )

    topology = build_stage135_i_state_topology(
        stage193_market_research_action_plan=plan,
        stage194_market_research_plan_execution=execution,
    )

    assert topology["metrics"]["market_research_plan_execution_node_count"] >= 1
    assert topology["metrics"]["market_research_plan_execution_status"] == "executed"
    assert topology["metrics"]["market_research_plan_execution_action"] == "market_research_report"
