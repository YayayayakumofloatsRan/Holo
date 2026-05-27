from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_feedback_loop import build_market_research_feedback_loop
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures


SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


def _sec_web_row() -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:sec",
        "action_type": "web_search",
        "query": "site:sec.gov Apple AAPL 2024 Form 10-K SEC filing",
        "status": "ok",
        "provider": "mock_sec_search",
        "results": [
            {
                "title": "Apple Form 10-K",
                "url": SEC_URL,
                "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
            }
        ],
        "source_urls": [SEC_URL],
        "page_evidence": {
            "schema": "holo.stage163.page_evidence.v1",
            "status": "supported",
            "opened_count": 1,
            "selected_url": SEC_URL,
            "page_observations": [
                {
                    "url": SEC_URL,
                    "status": "ok",
                    "title": "Apple Form 10-K",
                    "text": fixture["filing_text"],
                }
            ],
        },
    }


def _weak_web_row() -> dict:
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:weak",
        "action_type": "web_search",
        "query": "Apple 2024 10-K analysis",
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "Apple 10-K analysis",
                "url": "https://example.com/apple-10k-analysis",
                "snippet": "Third-party summary of Apple financial results.",
            }
        ],
        "source_urls": ["https://example.com/apple-10k-analysis"],
    }


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


def test_stage196_promotes_sec_page_evidence_to_pack_ready_source() -> None:
    from holo_host.market_research_source_promotion import (
        STAGE196_MARKET_RESEARCH_SOURCE_PROMOTION_SCHEMA,
        promote_market_research_sources,
    )

    report = promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[_sec_web_row()],
        network_enabled=False,
    )

    assert report["schema"] == STAGE196_MARKET_RESEARCH_SOURCE_PROMOTION_SCHEMA
    assert report["status"] == "promoted"
    assert report["selected_url"] == SEC_URL
    assert report["source_family"] == "financial_filing"
    assert report["authority_status"] == "sufficient"
    assert report["page_evidence_status"] == "supported"
    assert report["filing_text_available"] is True
    assert report["can_build_market_research_pack"] is True
    assert report["promoted_web_observation_ledger"][0]["source_urls"] == [SEC_URL]


def test_stage196_rejects_third_party_summary_as_weak_source() -> None:
    from holo_host.market_research_source_promotion import promote_market_research_sources

    report = promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[_weak_web_row()],
        network_enabled=False,
    )

    assert report["status"] == "weak"
    assert report["can_build_market_research_pack"] is False
    assert report["authority_status"] == "insufficient"
    assert "missing_required_source_family:financial_filing" in report["missing_authority"]


def test_stage196_can_crawl_when_existing_rows_are_missing() -> None:
    from holo_host.market_research_source_promotion import promote_market_research_sources

    fixture = default_market_research_pack_fixtures()[0]
    report = promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[],
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock_sec_search",
            "results": [{"title": "Apple Form 10-K", "url": SEC_URL, "snippet": "Apple Form 10-K annual report."}],
        },
        open_page_fn=lambda url: {
            "url": url,
            "status": "ok",
            "provider": "mock_sec_page",
            "html": fixture["filing_text"],
        },
        max_crawl_queries=2,
    )

    assert report["status"] == "promoted"
    assert report["crawler_used"] is True
    assert report["stage186_live_crawler_search"]["web_observation_ledger"]
    assert report["source_authority_report"]["status"] == "sufficient"
    assert report["selected_url"] == SEC_URL


def test_stage196_network_disabled_records_blocked_without_fetching() -> None:
    from holo_host.market_research_source_promotion import promote_market_research_sources

    report = promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[],
        network_enabled=False,
        web_search_fn=lambda query: (_ for _ in ()).throw(AssertionError("network should not be called")),
        max_crawl_queries=2,
    )

    assert report["status"] == "blocked"
    assert report["canonical_stop_reason"] == "boundary_or_permission"
    assert report["promoted_web_observation_ledger"][0]["status"] == "rejected_network_disabled"


def test_stage195_records_source_promotion_after_web_search_round() -> None:
    from holo_host.market_research_continuation_loop import run_market_research_continuation_loop

    fixture = default_market_research_pack_fixtures()[0]
    weak_pack = _weak_pack()
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
            "results": [{"title": "Apple Form 10-K", "url": SEC_URL, "snippet": "Apple Form 10-K annual report."}],
        },
        open_page_fn=lambda url: {
            "url": url,
            "status": "ok",
            "provider": "mock_sec_page",
            "html": fixture["filing_text"],
        },
        max_rounds=4,
    )

    assert loop["stage196_market_research_source_promotion"]["status"] == "promoted"
    assert loop["stage196_market_research_source_promotion"]["selected_url"] == SEC_URL
    assert loop["rounds"][0]["source_promotion"]["status"] == "promoted"


def test_stage196_event_stream_and_topology_render_source_promotion() -> None:
    from holo_host.market_research_source_promotion import promote_market_research_sources

    report = promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[_sec_web_row()],
        network_enabled=False,
    )
    stream = build_agent_event_stream(
        {
            "text": "done",
            "stage196_market_research_source_promotion": report,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    topology = build_stage135_i_state_topology(stage196_market_research_source_promotion=report)

    assert "[source_promote]" in rendered
    assert "status=promoted" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_source_promotion_node_count"] == 1
    assert topology["metrics"]["market_research_source_promotion_status"] == "promoted"
