from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_goal_state import update_goal_state
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_kernel_prompt_policy import (
    assert_no_persona_prompt_leak,
    strip_persona_prompt_text,
)
from holo_host.agent_loop_fsm import (
    build_host_memory_recall_ledger,
    repair_final_with_fsm,
    run_agent_loop_fsm,
)
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def test_holo_cli_prompt_policy_strips_wechat_persona() -> None:
    prompt = "System\nPersona Blend:\n\u5fae\u4fe1 \u719f\u4eba \u8d34\u7740\u8bf4\u8bdd\n\nKeep exact request."

    cleaned = strip_persona_prompt_text(prompt, channel="holo_cli")
    ok, leaks = assert_no_persona_prompt_leak(cleaned, channel="holo_cli")

    assert ok, leaks
    assert "Agent Kernel Prompt Policy" in cleaned
    assert "\u5fae\u4fe1" not in cleaned
    assert "\u719f\u4eba" not in cleaned
    assert "\u8d34\u7740\u8bf4\u8bdd" not in cleaned


def test_holo_cli_prompt_policy_rejects_playful_fruit_language() -> None:
    ok, leaks = assert_no_persona_prompt_leak("this prompt is \u998b and playful", channel="holo_cli")

    assert not ok
    assert "\u998b" in leaks


def test_memory_recall_intent_creates_mandatory_action() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e00\u4e0b\u4e0a\u6b21\u548c\u4f60\u7684\u5bf9\u8bdd", channel="holo_cli")

    assert frame["intent_type"] == "memory_recall"
    assert "memory_recall" in frame["mandatory_actions"]
    assert "memory_observation_ledger" in frame["required_observations"]


def test_memory_recall_mandatory_action_executes_or_records_failure() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e00\u4e0b\u4e0a\u6b21\u5bf9\u8bdd", channel="holo_cli")
    ledger = build_host_memory_recall_ledger(frame)
    report = run_agent_loop_fsm(intent_frame=frame, memory_observation_ledger=ledger)

    assert ledger
    assert ledger[0]["status"] in {"missing", "unavailable"}
    assert report["canonical_stop_reason"] == "evidence_exhausted"
    assert "memory_recall" in report["final_override_text"]


def test_shangci_and_shanghui_trigger_memory_recall() -> None:
    for text in ("\u4e0a\u6b21\u6211\u4eec\u8bf4\u8fc7\u4ec0\u4e48", "\u4e0a\u56de\u804a\u7684\u5185\u5bb9"):
        frame = build_intent_frame(text, channel="holo_cli")
        assert frame["intent_type"] == "memory_recall"
        assert frame["mandatory_actions"] == ["memory_recall"]


def test_followup_haiyouni_inherits_previous_memory_goal() -> None:
    first = build_intent_frame("\u56de\u5fc6\u4e00\u4e0b\u4e0a\u6b21\u5bf9\u8bdd", channel="holo_cli")
    first_report = run_agent_loop_fsm(intent_frame=first, memory_observation_ledger=[])
    state = update_goal_state(None, first, first_report, final_text=first_report["final_text"])

    follow = build_intent_frame("\u8fd8\u6709\u5462\uff1f", previous_goal_state=state, channel="holo_cli")

    assert follow["intent_type"] == "followup"
    assert follow["inherited_from_goal_id"] == first["goal_id"]
    assert follow["mandatory_actions"] == ["memory_recall"]


def test_question_mark_after_failed_answer_enters_repair_followup() -> None:
    previous = {
        "schema": "holo.stage160r.goal_state.v1",
        "last_goal_id": "goal:failed",
        "last_goal_text": "\u56de\u5fc6\u4e0a\u6b21",
        "last_intent_type": "memory_recall",
        "last_required_actions": ["memory_recall"],
        "last_required_observations": ["memory_observation_ledger"],
        "last_stop_reason": "evidence_exhausted",
    }

    frame = build_intent_frame("?", previous_goal_state=previous, channel="holo_cli")

    assert frame["intent_type"] == "followup"
    assert frame["mandatory_actions"] == ["memory_recall"]
    assert frame["confidence"] >= 0.8


def test_candidate_memory_recall_without_execution_blocks_final_answer() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e00\u4e0b\u4e0a\u6b21\u5bf9\u8bdd", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        tool_decision={"action_candidates": [{"action_type": "memory_recall", "score": 0.9}]},
        memory_observation_ledger=[],
        final_text="model guessed a memory",
    )

    assert report["canonical_stop_reason"] == "evidence_exhausted"
    assert repair_final_with_fsm("model guessed a memory", report, channel="holo_cli") != "model guessed a memory"


def test_web_failure_final_reports_attempted_failure() -> None:
    frame = build_intent_frame("\u8054\u7f51\u641c\u7d22 OpenAI Codex \u5b98\u65b9\u6587\u6863", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        web_observation_ledger=[
            {
                "observation_id": "web:error",
                "action_type": "web_search",
                "status": "error",
                "error": "timeout",
            }
        ],
    )

    assert report["canonical_stop_reason"] == "tool_failure_report"
    assert "web_search" in report["final_override_text"]
    assert "timeout" in report["final_override_text"]


def test_web_failure_final_does_not_say_need_to_complete_search() -> None:
    frame = build_intent_frame("search latest DeepSeek docs", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        web_observation_ledger=[{"observation_id": "web:error", "action_type": "web_search", "status": "error", "error": "503"}],
    )

    assert "need to complete" not in report["final_override_text"].lower()
    assert "will search" not in report["final_override_text"].lower()


def test_web_failure_final_has_no_persona_playfulness() -> None:
    frame = build_intent_frame("\u641c\u7d22\u6700\u65b0\u6587\u6863", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        web_observation_ledger=[{"observation_id": "web:error", "action_type": "web_search", "status": "error", "error": "network"}],
    )

    text = report["final_override_text"]
    assert "\ud83d" not in text
    assert "\u998b" not in text
    assert "\u706b\u5806" not in text
    assert "\u5c3e\u5df4" not in text


def test_canonical_stop_reason_not_unknown_for_new_turn() -> None:
    frame = build_intent_frame("hello", channel="holo_cli")
    report = run_agent_loop_fsm(intent_frame=frame, final_text="direct")

    assert report["canonical_stop_reason"] != "unknown"


def test_event_stream_renders_fsm_steps() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e00\u4e0b\u4e0a\u6b21\u5bf9\u8bdd", channel="holo_cli")
    report = run_agent_loop_fsm(intent_frame=frame, memory_observation_ledger=[])
    stream = build_agent_event_stream(
        {"text": report["final_text"], "stage160r_agent_loop_fsm": report, "stage160r_intent_frame": frame},
        user_text=frame["raw_user_text_exact"],
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[goal]" in rendered
    assert "[decide]" in rendered
    assert "[act] memory_recall" in rendered
    assert "[observe] memory_recall" in rendered
    assert "[evaluate]" in rendered
    assert "[stop] evidence_exhausted" in rendered
    assert "[final]" in rendered


def test_event_stream_has_no_hidden_reasoning() -> None:
    frame = build_intent_frame("search latest docs", channel="holo_cli")
    report = run_agent_loop_fsm(intent_frame=frame, web_observation_ledger=[])
    stream = build_agent_event_stream(
        {
            "text": report["final_text"],
            "stage160r_agent_loop_fsm": report,
            "reasoning_content": "private chain",
            "internal_messages": [{"reasoning_content": "private chain"}],
        },
        user_text="search latest docs",
    )
    blob = json.dumps(stream, ensure_ascii=False) + render_agent_event_stream(stream)

    assert "private chain" not in blob
    assert "reasoning_content" not in blob


def test_deepseek_no_tool_calls_does_not_override_missing_mandatory_action() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e0a\u6b21", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        memory_observation_ledger=[],
        final_text="DeepSeek answered without tool calls.",
    )

    assert report["canonical_stop_reason"] == "evidence_exhausted"
    assert report["final_text"] != "DeepSeek answered without tool calls."


def test_stage135_topology_includes_agent_loop_fsm_node() -> None:
    frame = build_intent_frame("\u56de\u5fc6\u4e0a\u6b21", channel="holo_cli")
    report = run_agent_loop_fsm(intent_frame=frame, memory_observation_ledger=[])

    topology = build_stage135_i_state_topology(
        user_text=frame["raw_user_text_exact"],
        channel="holo_cli",
        thread_key="holo_cli:stage160r",
        chat_name="HoloCLI",
        stage160r_agent_loop_fsm=report,
    )

    assert topology["metrics"]["agent_loop_fsm_node_count"] == 1
    assert topology["metrics"]["agent_loop_fsm_stop_reason"] == "evidence_exhausted"
