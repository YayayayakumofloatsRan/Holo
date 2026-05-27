from __future__ import annotations

import json

from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage152_deepseek_tool_loop import execute_deepseek_native_tool_call
from holo_host.stage171_market_research_action import execute_market_research_pack_action
from holo_host.stage172_filing_text_retrieval import (
    STAGE172_FILING_TEXT_RETRIEVAL_SCHEMA,
    retrieve_filing_text,
)


SAMPLE_10K_HTML = """
<html><head><title>Apple 2024 10-K</title></head><body>
<h1>Apple Inc. Form 10-K</h1>
<p>Item 1. Business</p>
<p>Apple designs, manufactures and markets smartphones, personal computers, tablets, wearables and accessories.</p>
<p>Item 1A. Risk Factors</p>
<p>The Company is exposed to intense competition, supply chain disruption, foreign exchange risk and regulatory risks.</p>
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>
<p>Net sales were $391.0 billion in 2024 compared to $383.3 billion in 2023. Net income was $93.7 billion in 2024.</p>
<p>Item 8. Financial Statements and Supplementary Data</p>
<p>The consolidated statements include balance sheets, statements of operations, comprehensive income, shareholders' equity and cash flows.</p>
</body></html>
"""


def _sec_search_observation() -> list[dict]:
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    return [
        {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:sec-search",
            "status": "ok",
            "action_type": "web_search",
            "query": "Apple 2024 10-K",
            "source_urls": [url],
            "results": [{"title": "Apple Form 10-K", "url": url, "snippet": "Apple annual report."}],
        }
    ]


def test_retrieves_filing_text_from_page_evidence_observation() -> None:
    rows = _sec_search_observation()
    rows[0]["page_evidence"] = {
        "schema": "holo.stage163.page_evidence.v1",
        "status": "supported",
        "selected_url": rows[0]["source_urls"][0],
        "page_observations": [
            {
                "schema": "holo.stage163.page_evidence.v1",
                "url": rows[0]["source_urls"][0],
                "status": "ok",
                "title": "Apple 10-K",
                "text": SAMPLE_10K_HTML,
            }
        ],
    }

    report = retrieve_filing_text(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=rows,
        network_enabled=False,
    )

    assert report["schema"] == STAGE172_FILING_TEXT_RETRIEVAL_SCHEMA
    assert report["status"] == "ok"
    assert report["retrieval_source"] == "page_evidence"
    assert "Item 7" in report["filing_text"]
    assert report["source_url"].startswith("https://www.sec.gov/")


def test_retrieves_filing_text_by_opening_sec_url_when_needed() -> None:
    opened: list[str] = []

    def open_page(url: str) -> dict:
        opened.append(url)
        return {"url": url, "status": "ok", "html": SAMPLE_10K_HTML, "provider": "mock_open_page"}

    report = retrieve_filing_text(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=_sec_search_observation(),
        network_enabled=True,
        open_page_fn=open_page,
    )

    assert opened == [_sec_search_observation()[0]["source_urls"][0]]
    assert report["status"] == "ok"
    assert report["retrieval_source"] == "open_page"
    assert report["filing_text_char_count"] > 400
    assert "Item 8" in report["filing_text"]


def test_network_disabled_blocks_opening_url_without_page_text() -> None:
    report = retrieve_filing_text(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=_sec_search_observation(),
        network_enabled=False,
    )

    assert report["status"] == "rejected_network_disabled"
    assert report["failure_reasons"] == ["network_disabled"]
    assert report["filing_text"] == ""


def test_market_research_pack_action_builds_pack_from_opened_filing_text() -> None:
    def open_page(url: str) -> dict:
        return {"url": url, "status": "ok", "html": SAMPLE_10K_HTML, "provider": "mock_open_page"}

    result = execute_market_research_pack_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_type": "10-K"},
        network_enabled=True,
        web_observation_ledger=_sec_search_observation(),
        open_page_fn=open_page,
    )

    assert result["status"] == "ok"
    assert result["filing_text_retrieval"]["status"] == "ok"
    assert result["filing_text_retrieval"]["retrieval_source"] == "open_page"
    assert result["stage169_market_research_pack"]["status"] == "ready"
    assert result["market_research_pack_ledger"][0]["filing_text_retrieval_status"] == "ok"


def test_market_research_pack_action_reports_retrieval_failure_when_network_disabled() -> None:
    result = execute_market_research_pack_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_type": "10-K"},
        network_enabled=False,
        web_observation_ledger=_sec_search_observation(),
    )

    assert result["status"] == "rejected"
    assert result["filing_text_retrieval"]["status"] == "rejected_network_disabled"
    assert result["market_research_pack_ledger"][0]["status"] == "rejected_network_disabled"
    assert "network_disabled" in result["market_research_pack_ledger"][0]["failure_reasons"]


def test_stage152_market_research_tool_uses_open_page_for_filing_text() -> None:
    def open_page(url: str) -> dict:
        return {"url": url, "status": "ok", "html": SAMPLE_10K_HTML, "provider": "mock_open_page"}

    result = execute_deepseek_native_tool_call(
        {
            "id": "call_market",
            "name": "market_research_pack",
            "arguments": {
                "query": "Apple AAPL 2024 10-K financial analysis",
                "web_observation_ledger": _sec_search_observation(),
            },
            "allowed": True,
            "raw_tool_call": {
                "id": "call_market",
                "type": "function",
                "function": {
                    "name": "market_research_pack",
                    "arguments": json.dumps({"query": "Apple AAPL 2024 10-K financial analysis"}, ensure_ascii=False),
                },
            },
        },
        network_enabled=True,
        open_page_fn=open_page,
    )

    assert result["status"] == "ok"
    assert result["filing_text_retrieval"]["status"] == "ok"
    assert result["stage169_market_research_pack"]["status"] == "ready"


def test_stage135_topology_includes_filing_text_retrieval_node() -> None:
    report = retrieve_filing_text(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=[],
        network_enabled=True,
        filing_text="Item 1. Business\nItem 1A. Risk Factors\nItem 7. MD&A\nItem 8. Financial Statements",
    )

    topology = build_stage135_i_state_topology(filing_text_retrieval=report)

    assert topology["metrics"]["filing_text_retrieval_node_count"] == 1
    assert topology["metrics"]["filing_text_retrieval_status"] == "ok"
    assert any(node["id"] == "stage172_filing_text_retrieval" for node in topology["nodes"])
