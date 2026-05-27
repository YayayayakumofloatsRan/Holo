from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.public_thought_stream import build_public_thought_stream, render_public_thought_stream
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from holo_host.stage173_market_research_report import build_market_research_report


def _ready_report() -> tuple[dict, dict]:
    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    return pack, build_market_research_report(market_research_pack=pack, question=fixture["query"])


def _third_party_report() -> tuple[dict, dict]:
    fixture = default_market_research_pack_fixtures()[1]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )
    return pack, build_market_research_report(market_research_pack=pack, question=fixture["query"])


def test_market_research_feedback_stops_when_report_is_ready() -> None:
    from holo_host.market_research_feedback_loop import (
        STAGE192_MARKET_RESEARCH_FEEDBACK_SCHEMA,
        build_market_research_feedback_loop,
    )

    pack, report = _ready_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple using its 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
    )

    assert feedback["schema"] == STAGE192_MARKET_RESEARCH_FEEDBACK_SCHEMA
    assert feedback["can_finalize"] is True
    assert feedback["next_action"] == "finalize_report"
    assert feedback["final_stop_reason"] == "report_ready"
    assert feedback["best_sufficiency_score"] >= 0.8


def test_market_research_feedback_continues_when_source_authority_is_insufficient() -> None:
    from holo_host.market_research_feedback_loop import build_market_research_feedback_loop

    pack, report = _third_party_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple using its 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=2,
    )

    assert feedback["can_finalize"] is False
    assert feedback["next_action"] in {"market_research_pack", "web_search"}
    assert feedback["final_stop_reason"] == "source_authority_insufficient"
    assert "source_authority:financial_filing" in feedback["unresolved_items"]
    assert feedback["steps"][0]["stop_decision"] == "continue"


def test_market_research_feedback_exhausts_when_report_is_insufficient_and_no_budget_remains() -> None:
    from holo_host.market_research_feedback_loop import build_market_research_feedback_loop

    pack, report = _third_party_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple using its 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=0,
    )

    assert feedback["can_finalize"] is False
    assert feedback["next_action"] == "report_insufficient_evidence"
    assert feedback["final_stop_reason"] == "evidence_exhausted"


def test_event_stream_and_public_thoughts_render_market_research_feedback() -> None:
    from holo_host.market_research_feedback_loop import build_market_research_feedback_loop

    pack, report = _third_party_report()
    feedback = build_market_research_feedback_loop(
        question="Analyze Apple using its 2024 10-K.",
        market_research_pack=pack,
        market_research_report=report,
        remaining_action_budget=1,
    )
    payload = {
        "text": "Report is not ready.",
        "stage192_market_research_feedback_loop": feedback,
        "reasoning_content": "private hidden reasoning",
    }
    stream = build_agent_event_stream(payload, user_text="Analyze Apple", channel="holo_cli")
    rendered = render_agent_event_stream(stream)
    thought = build_public_thought_stream(payload, user_text="Analyze Apple", event_stream=stream, channel="holo_cli")
    thought_rendered = render_public_thought_stream(thought)
    blob = json.dumps(stream, ensure_ascii=False) + json.dumps(thought, ensure_ascii=False) + rendered + thought_rendered

    assert "[feedback] market_research_report" in rendered
    assert "next=market_research_pack" in rendered or "next=web_search" in rendered
    assert "[thought:self_feedback]" in thought_rendered
    assert "private hidden reasoning" not in blob
    assert "reasoning_content" not in blob
