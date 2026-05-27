from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream
from holo_host.interactive_cli import InteractiveCliSession
from holo_host.public_thought_stream import (
    PUBLIC_THOUGHT_STREAM_SCHEMA,
    build_public_thought_stream,
    render_public_thought_stream,
)


def _payload() -> dict:
    return {
        "text": "Final grounded answer.",
        "stage151_tool_decision": {
            "purpose": "gather_web_evidence",
            "action_candidates": [
                {
                    "action_type": "web_search",
                    "score": 0.86,
                    "required_observations": ["web_observation_ledger"],
                }
            ],
        },
        "web_observation_ledger": [
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:one",
                "action_type": "web_search",
                "query": "OpenAI Codex CLI docs",
                "status": "ok",
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli"}],
            }
        ],
        "stage186_live_crawler_search": {
            "schema": "holo.stage186.live_crawler_search.v1",
            "status": "sufficient",
            "crawler_ledger": [
                {"phase": "query", "query": "OpenAI Codex CLI docs", "query_index": 0},
                {"phase": "evaluate", "status": "supported", "score": 0.92, "stop_reason": "sufficient_evidence", "authority_status": "sufficient"},
            ],
            "stage190_self_feedback_loop": {
                "schema": "holo.stage190.self_feedback_loop.v1",
                "status": "recorded",
                "steps": [
                    {
                        "action": "web_search",
                        "combined_sufficiency_score": 0.91,
                        "marginal_utility": 0.45,
                        "next_action": "finalize",
                        "stop_reason": "sufficient_evidence",
                    }
                ],
            },
        },
        "stage152_deepseek_tool_loop": {
            "assistant_messages_internal": [{"reasoning_content": "private chain must not leak"}],
            "stop_reason": "no_tool_calls",
        },
    }


def test_public_thought_stream_builds_auditable_cards_without_private_reasoning() -> None:
    stream = build_agent_event_stream(_payload(), user_text="search docs", channel="holo_cli")
    report = build_public_thought_stream(_payload(), user_text="search docs", event_stream=stream, channel="holo_cli")
    blob = json.dumps(report, ensure_ascii=False)

    assert report["schema"] == PUBLIC_THOUGHT_STREAM_SCHEMA
    assert report["card_count"] >= 5
    assert report["hidden_reasoning_exposed"] is False
    assert report["raw_chain_of_thought_available"] is False
    assert "private chain must not leak" not in blob
    assert "reasoning_content" not in blob


def test_public_thought_stream_renders_cli_friendly_loop() -> None:
    stream = build_agent_event_stream(_payload(), user_text="search docs", channel="holo_cli")
    report = build_public_thought_stream(_payload(), user_text="search docs", event_stream=stream, channel="holo_cli")
    rendered = render_public_thought_stream(report)

    assert "[thought]" in rendered
    assert "[thought:goal]" in rendered
    assert "[thought:action]" in rendered
    assert "[thought:self_feedback]" in rendered
    assert "[thought:stop]" in rendered


def test_interactive_cli_thoughts_command_uses_last_turn_public_stream() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:stage191", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_payload(), user_text="search docs", transport="reply_api")

    rendered = session.handle_command("/thoughts")
    as_json = session.render_json()

    assert "[thought:goal]" in rendered
    assert "[thought:self_feedback]" in rendered
    assert "stage191_public_thought_stream" in as_json
    assert "private chain must not leak" not in rendered + as_json
    assert "reasoning_content" not in rendered + as_json
