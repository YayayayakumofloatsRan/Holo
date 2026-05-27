from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.interactive_cli import InteractiveCliSession
from holo_host.market_research_dossier_registry import record_market_research_dossier
from holo_host.market_research_task_dossier import build_market_research_task_dossier
from holo_host.model_tool_arbitration import decide_next_action_with_model
from holo_host.stage152_deepseek_tool_loop import execute_deepseek_native_tool_call
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.tool_action_space import build_tool_action_space


def _needs_evidence_dossier(question: str = "Analyze Apple AAPL 2024 10-K.") -> dict:
    return build_market_research_task_dossier(
        question=question,
        stage197_market_research_report_assembly={
            "schema": "holo.stage197.market_research_report_assembly.v1",
            "status": "needs_report",
            "missing_requirements": ["financial_filing_source"],
        },
        stage198_market_research_finalization_gate={
            "schema": "holo.stage198.market_research_finalization_gate.v1",
            "status": "blocked",
            "final_visible_text_ready": False,
            "canonical_stop_reason": "evidence_exhausted",
        },
    )


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage203-mock",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple fiscal 2024 Form 10-K annual report.",
            }
        ],
    }


def _model_response(action: str) -> str:
    return json.dumps(
        {
            "goal_summary": "continue stored market research",
            "intent_type": "market_research",
            "selected_action": action,
            "action_arguments": {"thread_key": "holo_cli:research", "query": "continue Apple market research"},
            "why_this_action": "resume the persisted market research dossier before answering",
            "required_observations": ["market_research_dossier_resume_ledger"],
            "can_answer_without_tool": False,
            "confidence": 0.86,
            "stop_if_observed": "final_answer_ready",
            "fallback_if_failed": "report missing persisted dossier",
        },
        ensure_ascii=False,
    )


def _resume_payload(tmp_path: Path) -> dict:
    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_needs_evidence_dossier(),
    )
    tool_result = execute_deepseek_native_tool_call(
        {
            "id": "call_resume",
            "name": "market_research_dossier_resume",
            "arguments": {"thread_key": "holo_cli:research", "project_key": "market:apple", "query": "continue Apple research"},
            "allowed": True,
        },
        network_enabled=True,
        web_search_fn=_mock_search,
        state_dir=str(tmp_path),
    )
    frame = build_intent_frame("continue stored market research", channel="holo_cli")
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("market_research_dossier_resume"),
        user_text=frame["raw_user_text_exact"],
        context_packet={},
        goal_state={"last_intent_type": "market_research"},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        stage201_market_research_dossier_registry=tool_result["stage201_market_research_dossier_registry"],
        market_research_dossier_resume_ledger=tool_result["market_research_dossier_resume_ledger"],
    )
    return {
        "text": "Resumed stored market research dossier.",
        "stage160r_agent_loop_fsm": fsm,
        "stage161_model_tool_arbitration": decision,
        "stage201_market_research_dossier_registry": tool_result["stage201_market_research_dossier_registry"],
        "market_research_dossier_resume_ledger": tool_result["market_research_dossier_resume_ledger"],
    }


def test_stage203_event_stream_renders_dossier_resume_fsm_steps(tmp_path: Path) -> None:
    stream = build_agent_event_stream(_resume_payload(tmp_path), user_text="continue market research", channel="holo_cli")
    rendered = render_agent_event_stream(stream)

    assert "[model_decide] selected=market_research_dossier_resume" in rendered
    assert "[act] market_research_dossier_resume status=executed" in rendered
    assert "[observe] market_research_dossier_resume status=executed" in rendered
    assert "[market_registry]" in rendered
    assert "lookup=found" in rendered
    assert "resume=market_research_dossier_resume" in rendered
    assert "ledger=1" in rendered
    assert "[stop] final_answer_ready" in rendered


def test_stage203_event_stream_hides_hidden_reasoning_payload(tmp_path: Path) -> None:
    payload = _resume_payload(tmp_path)
    payload["reasoning_content"] = "private chain should not leak"
    payload["stage152_deepseek_tool_loop"] = {
        "internal_messages": [{"reasoning_content": "raw provider reasoning should not leak"}],
    }
    stream = build_agent_event_stream(payload, user_text="continue market research", channel="holo_cli")
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "private chain should not leak" not in blob
    assert "raw provider reasoning should not leak" not in blob
    assert "reasoning_content" not in blob


def test_stage203_interactive_trace_command_shows_dossier_resume_events(tmp_path: Path) -> None:
    session = InteractiveCliSession(thread_key="holo_cli:research", chat_name="HoloCLI", channel="holo_cli")
    session.record_turn(_resume_payload(tmp_path), user_text="continue market research", transport="live_http")
    rendered = session.handle_command("/trace")

    assert "[model_decide] selected=market_research_dossier_resume" in rendered
    assert "[act] market_research_dossier_resume status=executed" in rendered
    assert "[observe] market_research_dossier_resume status=executed" in rendered
    assert "resume=market_research_dossier_resume" in rendered


def test_stage203_json_uses_sanitized_dossier_resume_trace(tmp_path: Path) -> None:
    session = InteractiveCliSession(thread_key="holo_cli:research", chat_name="HoloCLI", channel="holo_cli")
    payload = _resume_payload(tmp_path)
    payload["internal_messages"] = [{"reasoning_content": "hidden"}]
    session.record_turn(payload, user_text="continue market research", transport="live_http")
    json_text = session.handle_command("/json")

    assert "stage153_agent_event_stream" in json_text
    assert "market_research_dossier_resume" in json_text
    assert "reasoning_content" not in json_text
    assert '"reasoning_content": "hidden"' not in json_text


def test_stage203_topology_counts_dossier_resume_trace_event(tmp_path: Path) -> None:
    payload = _resume_payload(tmp_path)
    stream = build_agent_event_stream(payload, user_text="continue market research", channel="holo_cli")
    topology = build_stage135_i_state_topology(
        user_text="continue market research",
        thread_key="holo_cli:research",
        chat_name="HoloCLI",
        channel="holo_cli",
        stage153_agent_event_stream=stream,
    )

    assert topology["metrics"]["agent_event_stream_node_count"] == 1
    assert topology["metrics"]["dossier_resume_trace_event_count"] == 1
