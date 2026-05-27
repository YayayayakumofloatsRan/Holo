from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.market_research_dossier_registry import record_market_research_dossier
from holo_host.market_research_task_dossier import build_market_research_task_dossier
from holo_host.model_tool_arbitration import decide_next_action_with_model, derive_arbitration_from_stage152
from holo_host.stage152_deepseek_tool_loop import (
    DEEPSEEK_NATIVE_TOOL_REGISTRY,
    build_deepseek_native_tool_payload,
    execute_deepseek_native_tool_call,
    run_deepseek_native_tool_loop,
)
from holo_host.tool_action_space import build_tool_action_space
from holo_host.tool_decision_contract import validate_tool_decision


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
        "provider": "stage202-mock",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple fiscal 2024 Form 10-K annual report.",
            }
        ],
    }


def _model_response(action: str, **extra: object) -> str:
    payload = {
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
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _tool_call(name: str, arguments: dict, call_id: str = "call_resume") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _response(content: str, *, tool_calls: list[dict] | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"finish_reason": "tool_calls" if tool_calls else "stop", "message": message}]}


def test_stage202_action_space_exposes_dossier_resume() -> None:
    action = next((row for row in build_tool_action_space() if row["action_type"] == "market_research_dossier_resume"), None)

    assert action is not None
    assert action["observation_schema"]["ledger"] == "market_research_dossier_resume_ledger"
    assert action["requires_network"] is False
    assert action["requires_workspace"] is False


def test_stage202_deepseek_tool_registry_contains_dossier_resume() -> None:
    payload = build_deepseek_native_tool_payload(["market_research_dossier_resume"])

    assert "market_research_dossier_resume" in DEEPSEEK_NATIVE_TOOL_REGISTRY
    assert payload["tools"][0]["function"]["name"] == "market_research_dossier_resume"


def test_stage202_model_selected_dossier_resume_validates_as_known_action() -> None:
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("market_research_dossier_resume"),
        user_text="继续这个市场研究",
        context_packet={"stage201_market_research_dossier_registry": {"lookup": {"status": "found"}}},
        goal_state={"last_intent_type": "market_research"},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    validation = validate_tool_decision(decision, build_tool_action_space(), network_enabled=False)

    assert decision["selected_action"] == "market_research_dossier_resume"
    assert validation["status"] == "accepted"


def test_stage202_deepseek_tool_call_resumes_persisted_dossier(tmp_path: Path) -> None:
    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_needs_evidence_dossier(),
    )
    result = execute_deepseek_native_tool_call(
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

    assert result["tool"] == "market_research_dossier_resume"
    assert result["status"] in {"resumed", "completed"}
    assert result["stage201_market_research_dossier_registry"]["lookup"]["status"] == "found"
    assert result["market_research_dossier_resume_ledger"][0]["status"] in {"resumed", "completed"}
    assert result["tool_message"]["role"] == "tool"


def test_stage202_deepseek_loop_accumulates_resume_ledger(tmp_path: Path) -> None:
    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_needs_evidence_dossier(),
    )
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response(
            "",
            tool_calls=[
                _tool_call(
                    "market_research_dossier_resume",
                    {"thread_key": "holo_cli:research", "project_key": "market:apple", "query": "continue Apple research"},
                )
            ],
        ),
        base_payload={"messages": [{"role": "user", "content": "continue market research"}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("I resumed the persisted market research dossier."),
        network_enabled=True,
        web_search_fn=_mock_search,
        state_dir=str(tmp_path),
    )

    assert result["tool_call_count"] == 1
    assert result["market_research_dossier_resume_ledger"][0]["tool"] == "market_research_dossier_resume"
    assert result["stage201_market_research_dossier_registry"]["lookup"]["status"] == "found"


def test_stage202_fsm_accepts_dossier_resume_observation(tmp_path: Path) -> None:
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
    frame = build_intent_frame("继续这个市场研究", channel="holo_cli")
    decision = decide_next_action_with_model(
        call_model=lambda prompt: _model_response("market_research_dossier_resume"),
        user_text=frame["raw_user_text_exact"],
        context_packet={},
        goal_state={},
        action_space=build_tool_action_space(),
        prior_observations=[],
    )
    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=decision,
        stage201_market_research_dossier_registry=tool_result["stage201_market_research_dossier_registry"],
        market_research_dossier_resume_ledger=tool_result["market_research_dossier_resume_ledger"],
    )

    assert report["selected_action"] == "market_research_dossier_resume"
    assert report["canonical_stop_reason"] == "final_answer_ready"


def test_stage202_event_stream_renders_resume_action(tmp_path: Path) -> None:
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
    stream = build_agent_event_stream(
        {
            "stage201_market_research_dossier_registry": tool_result["stage201_market_research_dossier_registry"],
            "market_research_dossier_resume_ledger": tool_result["market_research_dossier_resume_ledger"],
        },
        user_text="continue market research",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "[market_registry]" in rendered
    assert "lookup=found" in rendered
    assert "action=web_search" in rendered or "action=market_research" in rendered


def test_stage202_arbitration_from_stage152_requires_resume_ledger() -> None:
    decision = derive_arbitration_from_stage152(
        {"tool_calls": [{"name": "market_research_dossier_resume", "arguments": {"thread_key": "holo_cli:research"}}]},
        user_text="continue this market research",
    )

    assert decision["selected_action"] == "market_research_dossier_resume"
    assert decision["required_observations"] == ["market_research_dossier_resume_ledger"]
