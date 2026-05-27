from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
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


def _weak_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[1]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def test_stage195_ready_pack_runs_report_then_stops_ready() -> None:
    from holo_host.market_research_continuation_loop import (
        STAGE195_MARKET_RESEARCH_CONTINUATION_LOOP_SCHEMA,
        run_market_research_continuation_loop,
    )

    pack = _ready_pack()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=2,
    )

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        initial_stage192_feedback_loop=feedback,
        market_research_pack=pack,
        network_enabled=False,
        max_rounds=2,
    )

    assert loop["schema"] == STAGE195_MARKET_RESEARCH_CONTINUATION_LOOP_SCHEMA
    assert loop["status"] == "ready"
    assert loop["round_count"] == 1
    assert loop["executed_round_count"] == 1
    assert loop["can_finalize"] is True
    assert loop["canonical_stop_reason"] == "final_answer_ready"
    assert loop["rounds"][0]["selected_action"] == "market_research_report"
    assert loop["final_stage192_feedback_loop"]["can_finalize"] is True
    assert loop["stage173_market_research_report"]["status"] == "evidence_ready"
    assert loop["market_research_report_ledger"][0]["status"] == "ok"


def test_stage195_network_disabled_blocks_missing_authority_without_fetching() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    pack = _weak_pack()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=2,
    )

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        initial_stage192_feedback_loop=feedback,
        market_research_pack=pack,
        network_enabled=False,
        web_search_fn=lambda query: (_ for _ in ()).throw(AssertionError("network should not be called")),
        max_rounds=2,
    )

    assert loop["status"] == "blocked"
    assert loop["round_count"] == 1
    assert loop["blocked_round_count"] == 1
    assert loop["executed_round_count"] == 0
    assert loop["canonical_stop_reason"] == "boundary_or_permission"
    assert loop["rounds"][0]["selected_action"] == "web_search"
    assert loop["rounds"][0]["execution"]["status"] == "blocked"


def test_stage195_stops_after_failed_web_search_without_infinite_loop() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    pack = _weak_pack()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=pack,
        market_research_report={},
        remaining_action_budget=3,
    )

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        initial_stage192_feedback_loop=feedback,
        market_research_pack=pack,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "error",
            "provider": "mock",
            "error": "mock network failure",
            "results": [],
        },
        max_rounds=3,
    )

    assert loop["status"] == "failed"
    assert loop["round_count"] == 1
    assert loop["failed_round_count"] == 1
    assert loop["canonical_stop_reason"] == "tool_failure_report"
    assert loop["rounds"][0]["execution"]["failed_count"] == 1


def test_stage195_can_search_pack_and_report_across_bounded_rounds() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    weak_pack = _weak_pack()
    fixture = default_market_research_pack_fixtures()[0]
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=weak_pack,
        market_research_report={},
        remaining_action_budget=4,
    )

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        initial_stage192_feedback_loop=feedback,
        market_research_pack=weak_pack,
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
        open_page_fn=lambda url: {
            "url": url,
            "status": "ok",
            "provider": "mock_sec_page",
            "html": fixture["filing_text"],
        },
        max_rounds=4,
    )

    assert loop["status"] == "ready"
    assert loop["round_count"] == 3
    assert [row["selected_action"] for row in loop["rounds"]] == [
        "web_search",
        "market_research_pack",
        "market_research_report",
    ]
    assert loop["stage169_market_research_pack"]["source_authority"]["status"] == "sufficient"
    assert loop["stage173_market_research_report"]["status"] == "evidence_ready"
    assert loop["can_finalize"] is True


def test_stage195_event_stream_renders_continuation_without_hidden_reasoning() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=_ready_pack(),
        network_enabled=False,
        max_rounds=2,
    )
    stream = build_agent_event_stream(
        {
            "text": "done",
            "stage195_market_research_continuation_loop": loop,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_continue]" in rendered
    assert "rounds=1" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob


def test_stage195_topology_includes_continuation_node() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    loop = run_market_research_continuation_loop(
        question="Analyze Apple AAPL 2024 10-K.",
        market_research_pack=_ready_pack(),
        network_enabled=False,
        max_rounds=2,
    )

    topology = build_stage135_i_state_topology(stage195_market_research_continuation_loop=loop)

    assert topology["metrics"]["market_research_continuation_node_count"] >= 1
    assert topology["metrics"]["market_research_continuation_status"] == "ready"
    assert topology["metrics"]["market_research_continuation_round_count"] == 1
    assert topology["metrics"]["market_research_continuation_can_finalize"] is True
