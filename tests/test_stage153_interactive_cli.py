from __future__ import annotations

import io
import json
from unittest import mock

from holo_host import cli
from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.interactive_cli import InteractiveCliSession
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _reply_payload() -> dict:
    return {
        "action": "reply",
        "text": "Final grounded answer.",
        "stage151_tool_decision": {
            "purpose": "gather_web_evidence",
            "action_candidates": [
                {"action_type": "web_search", "score": 0.86, "required_observations": ["web_observation_ledger"]}
            ],
        },
        "web_observation_ledger": [
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:test",
                "action_type": "web_search",
                "query": "OpenAI Codex CLI docs",
                "status": "ok",
                "provider": "mock",
                "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "docs"}],
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "fetched_at": "2026-05-27T00:00:00Z",
                "error": "",
                "confidence": 0.9,
            }
        ],
        "stage151_tool_decision_grounding": {"status": "grounded", "missing_observations": []},
        "stage152_deepseek_tool_loop": {
            "stop_reason": "no_tool_calls",
            "tool_call_count": 0,
            "usage": {"prompt_cache_hit_tokens": 12, "prompt_cache_miss_tokens": 3},
            "internal_messages": [{"reasoning_content": "raw private reasoning must not appear"}],
        },
    }


def test_event_stream_renders_goal_candidate_tool_observation_stop_final() -> None:
    stream = build_agent_event_stream(
        _reply_payload(),
        user_text="联网搜索 OpenAI Codex CLI 官方文档",
        thread_key="holo_cli:test",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert stream["schema"] == "holo.stage153.agent_event_stream.v1"
    assert "[goal]" in rendered
    assert "[context]" in rendered
    assert "[candidate] web_search" in rendered
    assert "[observation] web_search status=ok sources=1" in rendered
    assert "[grounding] status=grounded" in rendered
    assert "[cache] hit=12 miss=3" in rendered
    assert "[stop] model_final_no_tool_calls" in rendered
    assert "[final]" in rendered


def test_event_stream_hides_raw_reasoning_content() -> None:
    stream = build_agent_event_stream(_reply_payload(), user_text="search")
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "raw private reasoning" not in blob
    assert "reasoning_content" not in blob


def test_empty_tool_run_says_no_tool_calls() -> None:
    stream = build_agent_event_stream({"text": "direct"}, user_text="hello")
    rendered = render_agent_event_stream(stream)

    assert "[tool_call] no tool calls" in rendered


def test_web_search_error_maps_to_tool_failure_and_suppresses_empty_market_events() -> None:
    stream = build_agent_event_stream(
        {
            "text": "web_search was attempted but failed: ssl eof.",
            "stage151_tool_decision": {
                "purpose": "gather_web_evidence",
                "selected_actions": [{"action_type": "web_search", "required_observations": ["web_observation_ledger"]}],
                "action_candidates": [
                    {"action_type": "web_search", "score": 0.86, "required_observations": ["web_observation_ledger"]}
                ],
            },
            "web_observation_ledger": [
                {
                    "schema": "holo.web_observation.v1",
                    "observation_id": "web:error",
                    "action_type": "web_search",
                    "query": "a share sources",
                    "status": "error",
                    "provider": "duckduckgo_html",
                    "results": [],
                    "source_urls": [],
                    "error": "ssl eof",
                }
            ],
            "stage193_market_research_action_plan": {},
            "stage194_market_research_plan_execution": {},
            "stage195_market_research_continuation_loop": {},
            "stage196_market_research_source_promotion": {},
            "stage197_market_research_report_assembly": {},
            "stage198_market_research_finalization_gate": {},
            "stage199_market_research_task_dossier": {},
            "stage200_market_research_dossier_resume": {},
            "stage201_market_research_dossier_registry": {},
        },
        user_text="search for a share sources",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[observation] web_search status=error" in rendered
    assert "[stop] tool_failure_report" in rendered
    assert "[market_plan]" not in rendered
    assert "[market_exec]" not in rendered


def test_interactive_session_stores_thread_key_and_last_turn() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:kept", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_reply_payload(), user_text="hello", transport="live_http")

    assert session.to_metadata()["schema"] == "holo.stage153.interactive_cli_session.v1"
    assert session.to_metadata()["thread_key"] == "holo_cli:kept"
    assert "[final]" in session.render_trace()


def test_trace_tools_json_commands_print_last_turn_state() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:test", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_reply_payload(), user_text="hello", transport="live_http")

    assert "[goal]" in session.handle_command("/trace")
    assert "https://developers.openai.com/codex/cli" in session.handle_command("/tools")
    assert '"text": "Final grounded answer."' in session.handle_command("/json")
    assert "raw private reasoning" not in session.handle_command("/json")


def test_chat_parser_defaults_to_stage153_thread_key() -> None:
    captured: dict = {}

    def fake_command_chat(config_path, **kwargs):
        captured.update(kwargs)
        return 0

    with mock.patch("holo_host.cli.command_chat", side_effect=fake_command_chat):
        result = cli.main(["chat", "--once", "ping", "--no-local-fallback"])

    assert result == 0
    assert captured["thread_key"] == "holo_cli:default"
    assert captured["chat_name"] == "HoloCLI"
    assert captured["channel"] == "holo_cli"


def test_interactive_trace_and_json_commands_use_last_reply_metadata() -> None:
    with mock.patch("holo_host.cli._live_api_request", return_value=_reply_payload()), mock.patch(
        "builtins.input", side_effect=["hello", "/trace", "/tools", "/json", "/exit"]
    ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        result = cli.command_chat(
            None,
            thread_key="holo_cli:stage153",
            chat_name="HoloCLI",
            channel="holo_cli",
            sender="Operator",
            once=None,
            json_output=False,
            no_local_fallback=True,
            timeout=3.0,
        )

    output = stdout.getvalue()
    assert result == 0
    assert "[goal]" in output
    assert "[tool_call]" in output
    assert "[observation]" in output
    assert "https://developers.openai.com/codex/cli" in output
    assert '"thread_key": "holo_cli:stage153"' in output
    assert "raw private reasoning" not in output


def test_health_memory_compact_commands_are_metadata_only_and_do_not_start_transport() -> None:
    calls: list[tuple] = []

    def fake_live_request(config_path, *, method, path, payload=None, timeout=0, **kwargs):
        calls.append((method, path))
        if path == "/health":
            return {"status": "ok", "processor_backend": "deepseek"}
        if path == "/trace-hybrid-recall":
            return {"tier": "recall", "graph_hits": [{"text": "topic anchor"}]}
        return _reply_payload()

    with mock.patch("holo_host.cli._live_api_request", side_effect=fake_live_request), mock.patch(
        "builtins.input", side_effect=["hello", "/health", "/memory topic", "/compact", "/exit"]
    ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        result = cli.command_chat(
            None,
            thread_key="holo_cli:stage153",
            chat_name="HoloCLI",
            channel="holo_cli",
            sender="Operator",
            once=None,
            json_output=False,
            no_local_fallback=True,
            timeout=3.0,
        )

    output = stdout.getvalue()
    assert result == 0
    assert "[health] status=ok" in output
    assert "topic anchor" in output
    assert "[compact]" in output
    assert not any(path.startswith("/wechat") or "wechat" in path for _, path in calls)


def test_stage135_topology_includes_agent_event_stream_node() -> None:
    stream = build_agent_event_stream(_reply_payload(), user_text="hello")

    topology = build_stage135_i_state_topology(
        user_text="hello",
        thread_key="holo_cli:stage153",
        chat_name="HoloCLI",
        channel="holo_cli",
        stage153_agent_event_stream=stream,
    )

    assert topology["metrics"]["agent_event_stream_node_count"] == 1
    assert topology["metrics"]["agent_event_stream_event_count"] >= 1
