from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_source_promotion import promote_market_research_sources
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from holo_host.stage173_market_research_report import build_market_research_report


SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


def _ready_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def _ready_report() -> dict:
    return build_market_research_report(
        market_research_pack=_ready_pack(),
        question="Analyze Apple AAPL 2024 10-K.",
    )


def _promoted_source() -> dict:
    return promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:sec",
                "action_type": "web_search",
                "query": "Apple AAPL 2024 10-K",
                "status": "ok",
                "provider": "mock",
                "results": [{"title": "Apple Form 10-K", "url": SEC_URL, "snippet": "Apple annual report."}],
                "source_urls": [SEC_URL],
                "page_evidence": {
                    "schema": "holo.stage163.page_evidence.v1",
                    "status": "supported",
                    "selected_url": SEC_URL,
                    "opened_count": 1,
                    "page_observations": [{"url": SEC_URL, "status": "ok", "text": "Item 1. Business Item 7. MD&A Item 8. Financial Statements"}],
                },
            }
        ],
        network_enabled=False,
    )


def _weak_source() -> dict:
    return promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:weak",
                "action_type": "web_search",
                "query": "Apple AAPL 2024 10-K",
                "status": "ok",
                "provider": "mock",
                "results": [{"title": "Apple 10-K analysis", "url": "https://example.com/apple", "snippet": "Third-party summary."}],
                "source_urls": ["https://example.com/apple"],
            }
        ],
        network_enabled=False,
    )


def test_stage197_assembles_ready_report_when_citation_matches_promoted_source() -> None:
    from holo_host.market_research_report_assembly import (
        STAGE197_MARKET_RESEARCH_REPORT_ASSEMBLY_SCHEMA,
        assemble_market_research_report,
    )

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=_ready_report(),
    )

    assert assembly["schema"] == STAGE197_MARKET_RESEARCH_REPORT_ASSEMBLY_SCHEMA
    assert assembly["status"] == "assembled"
    assert assembly["final_report_ready"] is True
    assert assembly["citation_quality_status"] == "sufficient"
    assert assembly["primary_source_url"] == SEC_URL
    assert assembly["ordered_sources"][0]["url"] == SEC_URL
    assert assembly["canonical_stop_reason"] == "final_answer_ready"


def test_stage197_blocks_ready_report_when_promoted_source_is_missing_from_citations() -> None:
    from holo_host.market_research_report_assembly import assemble_market_research_report

    report = _ready_report()
    report["citations"] = [{"citation_id": "citation:1", "url": "https://example.com/wrong", "source_family": "news"}]
    report["citation_count"] = 1

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=report,
    )

    assert assembly["status"] == "citation_mismatch"
    assert assembly["final_report_ready"] is False
    assert assembly["citation_quality_status"] == "missing_promoted_source"
    assert "promoted_source_missing_from_report_citations" in assembly["missing_requirements"]


def test_stage197_builds_insufficient_evidence_report_when_source_promotion_is_weak() -> None:
    from holo_host.market_research_report_assembly import assemble_market_research_report

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_weak_source(),
        stage173_market_research_report={},
    )

    assert assembly["status"] == "insufficient_evidence"
    assert assembly["final_report_ready"] is False
    assert assembly["canonical_stop_reason"] == "evidence_exhausted"
    assert "insufficient current filing evidence" in assembly["insufficient_evidence_report"]["summary"].lower()
    assert assembly["insufficient_evidence_report"]["investment_recommendation"] == "not_provided"


def test_stage197_event_stream_and_topology_render_report_assembly() -> None:
    from holo_host.market_research_report_assembly import assemble_market_research_report

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=_ready_report(),
    )
    stream = build_agent_event_stream(
        {
            "text": "done",
            "stage197_market_research_report_assembly": assembly,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered
    topology = build_stage135_i_state_topology(stage197_market_research_report_assembly=assembly)

    assert "[report_assembly]" in rendered
    assert "status=assembled" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_report_assembly_node_count"] == 1
    assert topology["metrics"]["market_research_report_assembly_status"] == "assembled"


def test_stage197_reply_payload_shape_contains_public_report_boundary() -> None:
    from holo_host.market_research_report_assembly import assemble_market_research_report

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=_ready_report(),
    )

    assert assembly["authority_boundary"]["provider_model_calls"] is False
    assert assembly["authority_boundary"]["memory_writes"] is False
    assert "reasoning_content" not in json.dumps(assembly, ensure_ascii=False)
