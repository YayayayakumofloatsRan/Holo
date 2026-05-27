from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_self_feedback_loop import (
    STAGE190_SELF_FEEDBACK_SCHEMA,
    evaluate_crawler_feedback_step,
)
from holo_host.live_crawler_search import run_live_crawler_search


def test_feedback_step_continues_when_authority_is_missing() -> None:
    step = evaluate_crawler_feedback_step(
        goal="research Apple fundamentals",
        query="Apple 2024 10-K annual report",
        action="web_search",
        page_evidence={"status": "supported", "best_evidence_score": 0.91},
        source_authority={"status": "insufficient", "required_source_family": "financial_filing"},
        remaining_query_budget=1,
    )

    assert step["stop_decision"] == "continue"
    assert step["next_action"] == "continue_search"
    assert step["stop_reason"] == "authority_insufficient"
    assert "source_authority:financial_filing" in step["unresolved_items"]


def test_feedback_step_stops_when_evidence_and_authority_are_sufficient() -> None:
    step = evaluate_crawler_feedback_step(
        goal="research Apple fundamentals",
        query="Apple 2024 10-K annual report",
        action="web_search",
        page_evidence={"status": "supported", "best_evidence_score": 0.94},
        source_authority={"status": "sufficient", "required_source_family": "financial_filing"},
        remaining_query_budget=2,
    )

    assert step["stop_decision"] == "stop"
    assert step["next_action"] == "finalize"
    assert step["stop_reason"] == "sufficient_evidence"


def test_crawler_records_stage190_self_feedback_loop() -> None:
    calls: list[str] = []

    def search(query: str) -> dict:
        calls.append(query)
        if len(calls) == 1:
            return {
                "query": query,
                "status": "ok",
                "provider": "mock_search",
                "results": [
                    {
                        "title": "Apple 10-K financial analysis",
                        "url": "https://random.example.com/apple-10k-analysis",
                        "snippet": "Apple 2024 10-K annual report financial analysis.",
                    }
                ],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple Form 10-K annual report.",
                }
            ],
        }

    def open_page(url: str) -> dict:
        if "sec.gov" in url:
            return {"url": url, "status": "ok", "html": "<title>Apple Form 10-K</title><body>Apple Form 10-K annual report financial filing.</body>"}
        return {"url": url, "status": "ok", "html": "<title>Apple 10-K financial analysis</title><body>Apple 2024 10-K annual report financial analysis.</body>"}

    report = run_live_crawler_search(
        user_text="search Apple 2024 10-K annual report financial filing",
        web_search_fn=search,
        open_page_fn=open_page,
        network_enabled=True,
        max_queries=3,
    )

    feedback = report["stage190_self_feedback_loop"]
    assert feedback["schema"] == STAGE190_SELF_FEEDBACK_SCHEMA
    assert feedback["continue_count"] >= 1
    assert feedback["final_stop_reason"] == "sufficient_evidence"
    assert any(step["stop_reason"] == "authority_insufficient" for step in feedback["steps"])
    assert any(step["next_action"] == "finalize" for step in feedback["steps"])


def test_event_stream_renders_self_feedback_without_hidden_reasoning() -> None:
    report = {
        "schema": "holo.stage186.live_crawler_search.v1",
        "status": "sufficient",
        "crawler_ledger": [],
        "stage190_self_feedback_loop": {
            "schema": STAGE190_SELF_FEEDBACK_SCHEMA,
            "status": "recorded",
            "final_stop_reason": "sufficient_evidence",
            "steps": [
                {
                    "schema": "holo.stage190.feedback_step.v1",
                    "action": "web_search",
                    "query": "Apple 10-K",
                    "authority_status": "sufficient",
                    "combined_sufficiency_score": 0.9,
                    "marginal_utility": 0.42,
                    "next_action": "finalize",
                    "stop_reason": "sufficient_evidence",
                }
            ],
        },
    }

    stream = build_agent_event_stream(
        {
            "text": "done",
            "stage186_live_crawler_search": report,
            "reasoning_content": "private hidden reasoning",
        },
        user_text="search Apple 10-K",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[feedback]" in rendered
    assert "next=finalize" in rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob
