from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_feedback_loop import build_market_research_feedback_loop
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from holo_host.stage173_market_research_report import build_market_research_report


def _ready_pack_report() -> tuple[dict, dict]:
    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    return pack, build_market_research_report(market_research_pack=pack, question=fixture["query"])


def _third_party_pack_report() -> tuple[dict, dict]:
    fixture = default_market_research_pack_fixtures()[1]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    return pack, build_market_research_report(market_research_pack=pack, question=fixture["query"])


def test_stage193_finalizes_when_stage192_report_is_ready() -> None:
    from holo_host.market_research_action_planner import (
        STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA,
        build_market_research_action_plan,
    )

    pack, report = _ready_pack_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=2,
    )

    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=2,
    )

    assert plan["schema"] == STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA
    assert plan["status"] == "no_action_needed"
    assert plan["can_finalize"] is True
    assert plan["next_action"] == "finalize_report"
    assert plan["candidate_count"] == 1


def test_stage193_plans_authoritative_filing_search_when_source_authority_is_weak() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan

    pack, report = _third_party_pack_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=2,
    )

    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=2,
        network_enabled=True,
    )

    assert plan["status"] == "planned"
    assert plan["next_action"] == "web_search"
    assert plan["stop_reason"] == "action_plan_ready"
    assert plan["can_finalize"] is False
    first = plan["action_candidates"][0]
    assert first["action_type"] == "web_search"
    assert first["required_source_family"] == "financial_filing"
    assert "SEC" in first["query"] or "sec.gov" in first["query"]
    assert first["can_execute_now"] is True
    assert "source_authority:financial_filing" in plan["unresolved_items"]


def test_stage193_plans_report_generation_when_pack_is_ready_but_report_missing() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan

    pack, _report = _ready_pack_report()
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

    assert plan["status"] == "planned"
    assert plan["next_action"] == "market_research_report"
    assert plan["action_candidates"][0]["action_type"] == "market_research_report"
    assert plan["action_candidates"][0]["can_execute_now"] is True


def test_stage193_blocks_web_search_when_network_is_disabled() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan

    pack, report = _third_party_pack_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=1,
    )

    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=1,
        network_enabled=False,
    )

    assert plan["status"] == "blocked"
    assert plan["next_action"] == "web_search"
    assert plan["stop_reason"] == "boundary_or_permission"
    assert plan["action_candidates"][0]["can_execute_now"] is False
    assert plan["action_candidates"][0]["blocked_reason"] == "network_disabled"


def test_stage193_event_stream_renders_market_research_action_plan() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan

    pack, report = _third_party_pack_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=1,
    )
    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report=report,
    )
    stream = build_agent_event_stream(
        {
            "text": "More evidence is needed.",
            "stage192_market_research_feedback_loop": feedback,
            "stage193_market_research_action_plan": plan,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_plan]" in rendered
    assert "next=web_search" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob


def test_stage193_topology_includes_market_research_action_plan_node() -> None:
    from holo_host.market_research_action_planner import build_market_research_action_plan

    pack, report = _third_party_pack_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=1,
    )
    plan = build_market_research_action_plan(
        question="Analyze Apple AAPL 2024 10-K.",
        stage192_market_research_feedback_loop=feedback,
        market_research_pack=pack,
        market_research_report=report,
    )

    topology = build_stage135_i_state_topology(
        stage192_market_research_feedback_loop=feedback,
        stage193_market_research_action_plan=plan,
    )

    assert topology["metrics"]["market_research_action_plan_node_count"] >= 1
    assert topology["metrics"]["market_research_action_plan_status"] == "planned"
    assert topology["metrics"]["market_research_action_plan_next_action"] == "web_search"
