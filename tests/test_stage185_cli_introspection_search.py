from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config
from holo_host.stage151_tool_decision_loop import build_tool_decision_report


def test_public_trace_includes_current_stage_state_from_handoff() -> None:
    stream = build_agent_event_stream(
        {"text": "Current stage status."},
        user_text="what stage are you on?",
        thread_key="holo_cli:default",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[state] milestone=stage185-cli-introspection-search-intent" in rendered
    assert any(event.get("event") == "state" for event in stream["events"])


def test_direct_turn_never_renders_unknown_stop_reason() -> None:
    stream = build_agent_event_stream(
        {
            "text": "Direct answer.",
            "canonical_stop_reason": "unknown",
            "stage153_agent_event_stream": {"stop_reason": "unknown"},
        },
        user_text="missing anything?",
    )
    rendered = render_agent_event_stream(stream)

    assert "[stop] unknown" not in rendered
    assert any(line in rendered for line in ("[stop] final_answer_ready", "[stop] model_final_no_tool_calls"))


def test_fsm_unknown_stop_is_repaired_for_new_cli_turns() -> None:
    stream = build_agent_event_stream(
        {
            "text": "Final answer.",
            "stage160r_agent_loop_fsm": {
                "schema": "holo.stage160r.agent_loop_fsm.v1",
                "canonical_stop_reason": "unknown",
                "steps": [],
            },
        },
        user_text="hello",
    )
    rendered = render_agent_event_stream(stream)

    assert "[stop] unknown" not in rendered
    assert "[stop] final_answer_ready" in rendered


def test_chinese_search_and_crawler_intent_selects_web_search() -> None:
    decision = build_tool_decision_report("你应该可以自己检索，挑一个金融方向，先想一想，然后去做")

    assert decision["selected_actions"]
    assert decision["selected_actions"][0]["action_type"] == "web_search"
    top = decision["action_candidates"][0]
    assert top["action_type"] == "web_search"
    assert top["score"] >= 0.8


def test_capability_broker_records_chinese_external_lookup_query_without_eager_fetch() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    broker = CapabilityBroker(config)

    payload = broker.summarize_turn("你应该可以自己检索，挑一个金融方向，先想一想，然后去做", {}, eager_network=False)

    assert payload["stage151_tool_decision"]["selected_actions"][0]["action_type"] == "web_search"
    assert payload["tool_requests"][0]["name"] == "web_search"
    assert "检索" in payload["stage151_tool_decision"]["selected_actions"][0]["query"]


def test_public_deliberation_trace_shows_multiple_auditable_think_steps_without_hidden_reasoning() -> None:
    stream = build_agent_event_stream(
        {
            "text": "I cannot treat this as current web evidence.",
            "stage151_tool_decision": build_tool_decision_report("搜索 Apple 最新 10-K"),
            "web_observation_ledger": [
                {
                    "schema": "holo.web_observation.v1",
                    "action_type": "web_search",
                    "query": "Apple 最新 10-K",
                    "status": "error",
                    "results": [],
                    "source_urls": [],
                    "error": "timeout",
                }
            ],
            "stage151_tool_decision_grounding": {
                "status": "ungrounded_web_claim",
                "missing_observations": ["web_observation"],
            },
        },
        user_text="搜索 Apple 最新 10-K",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert rendered.count("[think]") >= 3
    assert "[think] intent:" in rendered
    assert "[think] evidence:" in rendered
    assert "[think] action:" in rendered
    assert "reasoning_content" not in blob
    assert "chain_of_thought" not in blob
