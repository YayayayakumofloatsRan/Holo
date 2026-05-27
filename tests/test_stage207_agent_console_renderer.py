from __future__ import annotations

import io
from unittest import mock

from holo_host import cli
from holo_host.agent_console_renderer import render_agent_console_turn
from holo_host.interactive_cli import InteractiveCliSession


def _crawler_payload() -> dict:
    return {
        "action": "reply",
        "text": "Grounded Codex CLI source: https://developers.openai.com/codex/cli",
        "stage151_tool_decision": {
            "selected_actions": [
                {"action_type": "web_search", "score": 0.91, "required_observations": ["web_observation_ledger"]}
            ],
            "action_candidates": [
                {"action_type": "web_search", "score": 0.91, "required_observations": ["web_observation_ledger"]}
            ],
        },
        "stage186_live_crawler_search": {
            "schema": "holo.stage186.live_crawler_search.v1",
            "status": "sufficient",
            "stop_reason": "sufficient_evidence",
            "crawler_ledger": [
                {"phase": "query", "query": "OpenAI Codex CLI official docs", "query_index": 1},
                {"phase": "observe_search", "status": "ok", "result_count": 2, "source_count": 1},
                {"phase": "open_page", "status": "ok", "url": "https://developers.openai.com/codex/cli"},
                {
                    "phase": "evaluate",
                    "status": "sufficient",
                    "score": 0.91,
                    "stop_reason": "sufficient_evidence",
                    "authority_status": "official",
                },
                {"phase": "stop", "status": "sufficient", "stop_reason": "sufficient_evidence"},
            ],
            "source_urls": ["https://developers.openai.com/codex/cli"],
        },
        "web_observation_ledger": [
            {
                "schema": "holo.web_observation.v1",
                "action_type": "web_search",
                "query": "OpenAI Codex CLI official docs",
                "status": "ok",
                "provider": "mock",
                "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli"}],
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "confidence": 0.9,
            }
        ],
        "stage152_deepseek_tool_loop": {
            "internal_messages": [{"reasoning_content": "raw hidden reasoning must not render"}],
            "usage": {"prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 2},
        },
        "canonical_stop_reason": "final_answer_ready",
    }


def test_console_renderer_separates_user_trace_thoughts_and_final_with_faint_system_lines() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:stage207", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_crawler_payload(), user_text="search Codex CLI official docs", transport="live_http")

    rendered = render_agent_console_turn(
        user_text=session.last_user_text,
        final_text=session.last_payload["text"],
        event_stream=session.last_event_stream,
        public_thought_stream=session.last_payload["stage191_public_thought_stream"],
        use_ansi=True,
    )

    assert rendered.startswith("holo> search Codex CLI official docs")
    assert "\x1b[2m[goal]" in rendered
    assert "\x1b[2m[crawl:query]" in rendered
    assert "\x1b[2m[thought:model_decision]" in rendered
    assert "\nGrounded Codex CLI source: https://developers.openai.com/codex/cli" in rendered
    final_segment = rendered.rsplit("\nGrounded Codex CLI source:", 1)[1]
    assert "\x1b[" not in final_segment


def test_console_renderer_does_not_leak_hidden_reasoning() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:stage207", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_crawler_payload(), user_text="search Codex CLI official docs", transport="live_http")

    rendered = session.render_console_turn(use_ansi=False)
    blob = rendered + session.render_json()

    assert "raw hidden reasoning" not in blob
    assert "reasoning_content" not in blob
    assert "public auditable loop" in rendered


def test_chat_trace_uses_console_renderer_for_live_turns() -> None:
    with mock.patch("holo_host.cli._live_api_request", return_value=_crawler_payload()), mock.patch(
        "builtins.input", side_effect=["search Codex CLI official docs", "/exit"]
    ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        result = cli.command_chat(
            None,
            thread_key="holo_cli:stage207",
            chat_name="HoloCLI",
            channel="holo_cli",
            sender="Operator",
            once=None,
            json_output=False,
            trace_output=True,
            no_local_fallback=True,
            timeout=3.0,
        )

    output = stdout.getvalue()
    assert result == 0
    assert "holo> search Codex CLI official docs" in output
    assert "[crawl:open] status=ok url=https://developers.openai.com/codex/cli" in output
    assert "[thought:self_feedback]" in output or "[thought:stop]" in output
    assert "Grounded Codex CLI source: https://developers.openai.com/codex/cli" in output
    assert "raw hidden reasoning" not in output
