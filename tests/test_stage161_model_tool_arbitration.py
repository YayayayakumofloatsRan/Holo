from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_kernel_prompt_policy import assert_no_persona_prompt_leak, strip_persona_prompt_text
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.agent_loop_policy import evaluate_stage161_loop_policy
from holo_host.model_tool_arbitration import (
    build_tool_arbitration_prompt,
    decide_next_action_with_model,
    derive_arbitration_from_stage152,
)
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.tool_action_space import build_tool_action_space
from holo_host.tool_decision_contract import (
    validate_answer_direct_against_ledgers,
    validate_tool_decision,
)


def _model_response(action: str, **extra: object) -> str:
    payload = {
        "goal_summary": "answer the user with evidence",
        "intent_type": "answer",
        "selected_action": action,
        "action_arguments": {},
        "why_this_action": "model selected from structured action space",
        "required_observations": [],
        "can_answer_without_tool": action == "answer_direct",
        "confidence": 0.81,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "report attempted failure",
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def test_model_can_select_memory_recall_without_keyword_router() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response(
            "memory_recall",
            intent_type="memory_recall",
            action_arguments={"query": "previous exchange"},
            required_observations=["memory_observation_ledger"],
            can_answer_without_tool=False,
        ),
        user_text="tell me what mattered earlier",
        context_packet={"directive_state": ["no emoji"]},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
        deterministic_hints={"suggested_actions": ["answer_direct"]},
    )

    assert decision["schema"] == "holo.stage161.model_tool_arbitration.v1"
    assert decision["selected_action"] == "memory_recall"
    assert decision["deterministic_hints"]["suggested_actions"] == ["answer_direct"]


def test_model_selected_memory_recall_executes_host_tool() -> None:
    frame = build_intent_frame("tell me what mattered earlier", channel="holo_cli")
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response(
            "memory_recall",
            intent_type="memory_recall",
            action_arguments={"query": "earlier"},
            required_observations=["memory_observation_ledger"],
            can_answer_without_tool=False,
        ),
        user_text=frame["raw_user_text_exact"],
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        memory_observation_ledger=[
            {
                "memory_call_id": "mem:1",
                "source_family": "durable",
                "selected_ids": ["m1"],
                "status": "grounded",
                "summary": "user asked to avoid emoji",
                "confidence": 0.9,
            }
        ],
        final_text="Retrieved: user asked to avoid emoji.",
    )

    assert report["stage161_model_first"] is True
    assert report["selected_action"] == "memory_recall"
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert any(step["phase"] == "model_decide" for step in report["steps"])


def test_model_selected_answer_direct_is_blocked_if_memory_claim_has_no_ledger() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("answer_direct", can_answer_without_tool=True),
        user_text="what do you remember?",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    validation = validate_answer_direct_against_ledgers(
        "I remember you prefer fewer emoji.",
        decision,
        memory_observation_ledger=[],
    )

    assert validation["status"] == "blocked"
    assert validation["repair_required"] is True
    assert "memory_observation_ledger" in validation["missing_ledgers"]


def test_model_selected_web_search_executes_or_records_failure() -> None:
    frame = build_intent_frame("please investigate this", channel="holo_cli")
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response(
            "web_search",
            intent_type="web_lookup",
            action_arguments={"query": "OpenAI Codex docs"},
            required_observations=["web_observation_ledger"],
            can_answer_without_tool=False,
        ),
        user_text=frame["raw_user_text_exact"],
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        web_observation_ledger=[
            {
                "observation_id": "web:error",
                "action_type": "web_search",
                "status": "error",
                "error": "provider timeout",
            }
        ],
    )

    assert report["selected_action"] == "web_search"
    assert report["canonical_stop_reason"] == "tool_failure_report"
    assert "provider timeout" in report["final_override_text"]


def test_model_no_tool_calls_is_validated_not_trusted() -> None:
    decision = derive_arbitration_from_stage152(
        {
            "schema": "holo.stage152.deepseek_native_tool_loop.v1",
            "tool_call_count": 0,
            "stop_reason": "no_tool_calls",
            "final_text": "I remember the exact prior detail.",
        },
        user_text="what do you remember?",
    )
    validation = validate_answer_direct_against_ledgers(
        "I remember the exact prior detail.",
        decision,
        memory_observation_ledger=[],
    )

    assert decision["selected_action"] == "answer_direct"
    assert validation["status"] == "blocked"


def test_deterministic_hints_do_not_force_action() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("answer_direct", can_answer_without_tool=True),
        user_text="latest docs?",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
        deterministic_hints={"suggested_actions": ["web_search"], "current_fact_possible": True},
    )

    assert decision["selected_action"] == "answer_direct"
    assert decision["deterministic_hints"]["suggested_actions"] == ["web_search"]


def test_invalid_model_action_is_rejected() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("download_internet"),
        user_text="search",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    validation = validate_tool_decision(decision, build_tool_action_space(), network_enabled=True)

    assert validation["status"] == "rejected"
    assert validation["reason"] == "unknown_action"


def test_tool_failure_allows_retry_when_budget_remains() -> None:
    policy = evaluate_stage161_loop_policy(
        selected_action="web_search",
        action_status="failed",
        retry_count=0,
        retry_budget=1,
        observation_status="error",
    )

    assert policy["next_step"] == "retry"
    assert policy["canonical_stop_reason"] == "tool_failure_report"


def test_tool_failure_final_reports_attempted_failure() -> None:
    policy = evaluate_stage161_loop_policy(
        selected_action="web_search",
        action_status="failed",
        retry_count=1,
        retry_budget=1,
        observation_status="error",
        error="503",
    )

    assert policy["next_step"] == "final"
    assert "attempted" in policy["final_guidance"].lower()
    assert "503" in policy["final_guidance"]


def test_followup_uses_goal_state_in_model_prompt() -> None:
    prompt = build_tool_arbitration_prompt(
        user_text="还有呢？",
        context_packet={},
        goal_state={"last_goal_text": "recall previous conversation", "last_intent_type": "memory_recall"},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )

    assert "还有呢？" in prompt
    assert "recall previous conversation" in prompt
    assert "memory_recall" in prompt


def test_cli_event_stream_shows_model_decide() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("web_search", action_arguments={"query": "apple"}),
        user_text="搜索一下apple",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    frame = build_intent_frame("搜索一下apple", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        web_observation_ledger=[{"observation_id": "web:1", "action_type": "web_search", "status": "error", "error": "offline"}],
    )
    stream = build_agent_event_stream(
        {
            "text": report["final_text"],
            "stage160r_agent_loop_fsm": report,
            "stage161_model_tool_arbitration": decision,
            "stage161_tool_action_space_count": len(build_tool_action_space()),
        },
        user_text="搜索一下apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[action_space]" in rendered
    assert "[model_decide] selected=web_search" in rendered


def test_holo_cli_prompt_has_no_persona_text() -> None:
    cleaned = strip_persona_prompt_text("微信 熟人 打趣 馋 the subject\nNeed answer.", channel="holo_cli")
    ok, leaks = assert_no_persona_prompt_leak(cleaned, channel="holo_cli")

    assert ok, leaks
    assert "Need answer." in cleaned


def test_no_unknown_stop_reason() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("defer"),
        user_text="later",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    frame = build_intent_frame("later", channel="holo_cli")
    report = run_agent_loop_fsm(intent_frame=frame, model_arbitration=decision)

    assert report["canonical_stop_reason"] != "unknown"


def test_no_hidden_reasoning_in_arbitration_metadata() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: '{"selected_action":"answer_direct","reasoning_content":"secret chain"}',
        user_text="hello",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )

    blob = json.dumps(decision, ensure_ascii=False)
    assert "secret chain" not in blob
    assert "reasoning_content" not in blob


def test_apple_search_no_playful_fruit_reply() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response(
            "web_search",
            intent_type="web_lookup",
            action_arguments={"query": "apple"},
            required_observations=["web_observation_ledger"],
            can_answer_without_tool=False,
        ),
        user_text="搜索一下apple",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    frame = build_intent_frame("搜索一下apple", channel="holo_cli")
    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        web_observation_ledger=[
            {"observation_id": "web:error", "action_type": "web_search", "status": "error", "error": "network_disabled"}
        ],
    )

    text = report["final_text"]
    assert "apple" in decision["action_arguments"]["query"]
    assert "馋" not in text
    assert "水果" not in text
    assert "web_search" in text


def test_stage135_topology_includes_model_tool_arbitration_node() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("memory_recall", action_arguments={"query": "prior"}),
        user_text="recall prior details",
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    topology = build_stage135_i_state_topology(
        user_text="recall prior details",
        channel="holo_cli",
        thread_key="holo_cli:stage161",
        chat_name="HoloCLI",
        stage161_model_tool_arbitration=decision,
    )

    assert topology["metrics"]["model_tool_arbitration_node_count"] == 1
    assert topology["metrics"]["model_tool_arbitration_selected_action"] == "memory_recall"
