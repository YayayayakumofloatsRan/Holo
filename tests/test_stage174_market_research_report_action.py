from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream, render_tool_observations
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.model_tool_arbitration import derive_arbitration_from_stage152
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage152_deepseek_tool_loop import (
    DEEPSEEK_NATIVE_TOOL_REGISTRY,
    build_deepseek_native_tool_payload,
    execute_deepseek_native_tool_call,
    run_deepseek_native_tool_loop,
)
from holo_host.stage171_market_research_action import execute_market_research_pack_action
from holo_host.tool_action_space import build_tool_action_space


SAMPLE_10K_TEXT = """
Item 1. Business
Apple designs, manufactures and markets smartphones, personal computers, tablets, wearables and accessories.

Item 1A. Risk Factors
The Company is exposed to intense competition, supply chain disruption, foreign exchange risk and regulatory risks.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Net sales were $391.0 billion in 2024 compared to $383.3 billion in 2023. Net income was $93.7 billion in 2024.

Item 8. Financial Statements and Supplementary Data
The consolidated statements include balance sheets, statements of operations, comprehensive income, shareholders' equity and cash flows.
"""


def _sec_observation() -> list[dict]:
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    return [
        {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:sec",
            "status": "ok",
            "action_type": "web_search",
            "query": "Apple 2024 10-K",
            "source_urls": [url],
            "results": [{"title": "Apple Form 10-K", "url": url, "snippet": "Apple annual report."}],
        }
    ]


def _tool_call(name: str, arguments: dict, call_id: str = "call_report") -> dict:
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "allowed": True,
        "status": "accepted",
        "raw_tool_call": {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        },
    }


def _response(content: str, *, tool_calls: list[dict] | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"finish_reason": "tool_calls" if tool_calls else "stop", "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }


def test_market_research_report_action_builds_report_and_ledger_from_ready_pack() -> None:
    from holo_host.stage174_market_research_report_action import (
        STAGE174_MARKET_RESEARCH_REPORT_LEDGER_SCHEMA,
        execute_market_research_report_action,
    )

    pack_action = execute_market_research_pack_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_text": SAMPLE_10K_TEXT},
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )

    result = execute_market_research_report_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "market_research_pack_ledger": pack_action["market_research_pack_ledger"]},
        network_enabled=True,
    )

    assert result["status"] == "ok"
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"
    assert result["market_research_report_ledger"][0]["schema"] == STAGE174_MARKET_RESEARCH_REPORT_LEDGER_SCHEMA
    assert result["market_research_report_ledger"][0]["report_status"] == "evidence_ready"
    assert result["tool_observation_ledger"][0]["tool"] == "market_research_report"


def test_market_research_report_action_can_build_pack_then_report_from_inputs() -> None:
    from holo_host.stage174_market_research_report_action import execute_market_research_report_action

    result = execute_market_research_report_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
            "web_observation_ledger": _sec_observation(),
        },
        network_enabled=True,
    )

    assert result["status"] == "ok"
    assert result["stage169_market_research_pack"]["status"] == "ready"
    assert result["stage173_market_research_report"]["section_count"] >= 4
    assert result["market_research_report_ledger"][0]["pack_status"] == "ready"


def test_stage152_registry_executes_market_research_report_tool() -> None:
    assert "market_research_report" in DEEPSEEK_NATIVE_TOOL_REGISTRY

    result = execute_deepseek_native_tool_call(
        _tool_call(
            "market_research_report",
            {
                "query": "Apple AAPL 2024 10-K financial analysis",
                "filing_text": SAMPLE_10K_TEXT,
                "web_observation_ledger": _sec_observation(),
            },
        ),
        network_enabled=True,
    )

    assert result["tool"] == "market_research_report"
    assert result["status"] == "ok"
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"
    assert result["market_research_report_ledger"][0]["status"] == "ok"


def test_deepseek_tool_loop_accumulates_market_research_report_metadata() -> None:
    result = run_deepseek_native_tool_loop(
        initial_decoded=_response(
            "",
            tool_calls=[
                {
                    "id": "call_report",
                    "type": "function",
                    "function": {
                        "name": "market_research_report",
                        "arguments": json.dumps(
                            {
                                "query": "Apple AAPL 2024 10-K financial analysis",
                                "filing_text": SAMPLE_10K_TEXT,
                                "web_observation_ledger": _sec_observation(),
                            },
                            ensure_ascii=False,
                        ),
                    },
                }
            ],
        ),
        base_payload={"messages": [{"role": "user", "content": "Analyze Apple."}], **build_deepseek_native_tool_payload()},
        call_model=lambda payload: _response("Report generated from filing evidence."),
        network_enabled=True,
    )

    assert result["market_research_report_ledger"][0]["status"] == "ok"
    assert result["stage173_market_research_report"]["status"] == "evidence_ready"
    assert result["tool_observation_ledger"][0]["tool"] == "market_research_report"


def test_model_arbitration_and_action_space_include_market_research_report() -> None:
    actions = {item["action_type"]: item for item in build_tool_action_space()}

    assert "market_research_report" in actions
    report = {
        "schema": "holo.stage152.deepseek_tool_loop.v1",
        "live_trace": {
            "events": [
                {"event": "tool", "action_type": "market_research_report", "call_id": "call_report", "query": "Apple"}
            ]
        },
        "market_research_report_ledger": [{"action_id": "report:1", "status": "ok"}],
    }
    arbitration = derive_arbitration_from_stage152(report, user_text="Analyze Apple.")

    assert arbitration["selected_action"] == "market_research_report"
    assert arbitration["required_observations"] == ["market_research_report_ledger"]


def test_fsm_accepts_market_research_report_observation() -> None:
    from holo_host.stage174_market_research_report_action import execute_market_research_report_action

    action = execute_market_research_report_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_text": SAMPLE_10K_TEXT, "web_observation_ledger": _sec_observation()},
        network_enabled=True,
    )

    fsm = run_agent_loop_fsm(
        intent_frame=build_intent_frame("Analyze Apple 2024 10-K.", channel="holo_cli"),
        model_arbitration={"selected_action": "market_research_report", "required_observations": ["market_research_report_ledger"]},
        market_research_report_ledger=action["market_research_report_ledger"],
    )

    assert fsm["canonical_stop_reason"] == "final_answer_ready"
    assert any(step["selected_action"] == "market_research_report" and step["action_status"] == "executed" for step in fsm["steps"])


def test_event_stream_and_tools_render_market_research_report_action() -> None:
    from holo_host.stage174_market_research_report_action import execute_market_research_report_action

    action = execute_market_research_report_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_text": SAMPLE_10K_TEXT, "web_observation_ledger": _sec_observation()},
        network_enabled=True,
    )
    fsm = run_agent_loop_fsm(
        intent_frame=build_intent_frame("Analyze Apple 2024 10-K.", channel="holo_cli"),
        model_arbitration={"selected_action": "market_research_report", "required_observations": ["market_research_report_ledger"]},
        market_research_report_ledger=action["market_research_report_ledger"],
    )
    payload = {
        "text": "Report generated.",
        "stage160r_agent_loop_fsm": fsm,
        "market_research_report_ledger": action["market_research_report_ledger"],
    }
    rendered = render_agent_event_stream(build_agent_event_stream(payload, user_text="Analyze Apple 2024 10-K.", channel="holo_cli"))

    assert "[act] market_research_report status=executed" in rendered
    assert "market_research_report status=ok" in render_tool_observations(payload)


def test_stage135_topology_includes_report_action_output() -> None:
    from holo_host.stage174_market_research_report_action import execute_market_research_report_action

    action = execute_market_research_report_action(
        {"query": "Apple AAPL 2024 10-K financial analysis", "filing_text": SAMPLE_10K_TEXT, "web_observation_ledger": _sec_observation()},
        network_enabled=True,
    )

    topology = build_stage135_i_state_topology(
        stage173_market_research_report=action["stage173_market_research_report"],
        market_research_report_ledger=action["market_research_report_ledger"],
    )

    assert topology["metrics"]["market_research_report_node_count"] == 1
    assert topology["metrics"]["market_research_report_action_node_count"] == 1
    assert topology["metrics"]["market_research_report_status"] == "evidence_ready"
