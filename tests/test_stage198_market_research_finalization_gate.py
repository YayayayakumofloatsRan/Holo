from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_report_assembly import assemble_market_research_report
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


def _weak_assembly() -> dict:
    return assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion={
            "status": "weak",
            "authority_status": "insufficient",
            "source_family": "third_party_summary",
            "selected_url": "https://example.com/apple-summary",
            "missing_authority": ["financial_filing"],
            "canonical_stop_reason": "evidence_exhausted",
        },
        stage173_market_research_report={},
    )


def _assembled() -> dict:
    return assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=_ready_report(),
    )


def test_stage198_finalizes_assembled_report_into_visible_answer() -> None:
    from holo_host.market_research_finalization_gate import (
        STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA,
        build_market_research_finalization_gate,
    )

    gate = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=_assembled(),
        candidate_visible_text="I can do market research.",
    )

    assert gate["schema"] == STAGE198_MARKET_RESEARCH_FINALIZATION_GATE_SCHEMA
    assert gate["status"] == "finalized"
    assert gate["final_visible_text_ready"] is True
    assert gate["should_replace_visible_text"] is True
    assert "Market research report" in gate["visible_text"]
    assert "Source:" in gate["visible_text"]
    assert SEC_URL in gate["visible_text"]
    assert gate["canonical_stop_reason"] == "final_answer_ready"


def test_stage198_blocks_citation_mismatch_before_visible_final() -> None:
    from holo_host.market_research_finalization_gate import build_market_research_finalization_gate

    report = _ready_report()
    report["citations"] = [{"citation_id": "citation:1", "url": "https://example.com/wrong", "source_family": "news"}]
    report["citation_count"] = 1
    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=_promoted_source(),
        stage173_market_research_report=report,
    )
    gate = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=assembly,
        candidate_visible_text="Here is the final report.",
    )

    assert gate["status"] == "blocked"
    assert gate["final_visible_text_ready"] is False
    assert gate["should_replace_visible_text"] is True
    assert "citation mismatch" in gate["visible_text"].lower()
    assert "not treat this as final" in gate["visible_text"].lower()


def test_stage198_repairs_insufficient_evidence_to_bounded_visible_text() -> None:
    from holo_host.market_research_finalization_gate import build_market_research_finalization_gate

    gate = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=_weak_assembly(),
        candidate_visible_text="Apple is attractive based on latest filings.",
    )

    assert gate["status"] == "insufficient_evidence"
    assert gate["final_visible_text_ready"] is False
    assert gate["should_replace_visible_text"] is True
    assert "Insufficient current filing evidence" in gate["visible_text"]
    assert "not_provided" in gate["visible_text"]


def test_stage198_event_stream_and_topology_render_finalization() -> None:
    from holo_host.market_research_finalization_gate import build_market_research_finalization_gate

    gate = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=_assembled(),
        candidate_visible_text="draft",
    )
    stream = build_agent_event_stream(
        {
            "text": gate["visible_text"],
            "stage198_market_research_finalization_gate": gate,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered
    topology = build_stage135_i_state_topology(stage198_market_research_finalization_gate=gate)

    assert "[report_final]" in rendered
    assert "status=finalized" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_finalization_node_count"] == 1
    assert topology["metrics"]["market_research_finalization_status"] == "finalized"


def test_stage198_noops_without_stage197_report_boundary() -> None:
    from holo_host.market_research_finalization_gate import build_market_research_finalization_gate

    gate = build_market_research_finalization_gate(
        question="hello",
        stage197_market_research_report_assembly={},
        candidate_visible_text="normal answer",
    )

    assert gate["status"] == "not_applicable"
    assert gate["should_replace_visible_text"] is False
