from __future__ import annotations

import json

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage152_deepseek_tool_loop import (
    DEEPSEEK_NATIVE_TOOL_REGISTRY,
    execute_deepseek_native_tool_call,
)
from holo_host.stage170_market_research_gate import normalize_market_research_pack
from holo_host.stage171_market_research_action import (
    STAGE171_MARKET_RESEARCH_ACTION_SCHEMA,
    STAGE171_MARKET_RESEARCH_LEDGER_SCHEMA,
    execute_market_research_pack_action,
)


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
    return [
        {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:sec",
            "status": "ok",
            "action_type": "web_search",
            "query": "Apple 2024 10-K",
            "source_urls": ["https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"],
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                }
            ],
        }
    ]


def _tool_call(name: str, arguments: dict, call_id: str = "call_market") -> dict:
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


def test_market_research_pack_action_builds_ready_pack_and_ledger() -> None:
    result = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_type": "10-K",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )

    assert result["schema"] == STAGE171_MARKET_RESEARCH_ACTION_SCHEMA
    assert result["status"] == "ok"
    assert result["stage169_market_research_pack"]["status"] == "ready"
    assert result["market_research_pack_ledger"][0]["schema"] == STAGE171_MARKET_RESEARCH_LEDGER_SCHEMA
    assert result["market_research_pack_ledger"][0]["status"] == "ok"
    assert result["market_research_pack_ledger"][0]["pack_status"] == "ready"
    assert result["market_research_pack_ledger"][0]["evidence_item_count"] >= 5
    assert result["market_research_pack_ledger"][0]["source_urls"][0].startswith("https://www.sec.gov/")


def test_market_research_pack_action_network_disabled_records_rejection() -> None:
    result = execute_market_research_pack_action(
        {"query": "Apple AAPL 2024 10-K financial analysis"},
        network_enabled=False,
        web_observation_ledger=[],
    )

    assert result["status"] == "rejected"
    assert result["market_research_pack_ledger"][0]["status"] == "rejected_network_disabled"
    assert result["market_research_pack_ledger"][0]["failure_reasons"] == ["network_disabled"]
    assert "stage169_market_research_pack" not in result


def test_market_research_pack_action_third_party_source_is_insufficient() -> None:
    result = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=[
            {
                "status": "ok",
                "source_urls": ["https://example.com/apple-analysis"],
                "results": [{"title": "Apple Analysis", "url": "https://example.com/apple-analysis", "snippet": "third party"}],
            }
        ],
    )

    assert result["status"] == "insufficient"
    assert result["stage169_market_research_pack"]["status"] == "insufficient"
    assert "source_authority_insufficient" in result["market_research_pack_ledger"][0]["failure_reasons"]


def test_stage152_registry_executes_market_research_pack_tool() -> None:
    assert "market_research_pack" in DEEPSEEK_NATIVE_TOOL_REGISTRY

    result = execute_deepseek_native_tool_call(
        _tool_call(
            "market_research_pack",
            {
                "query": "Apple AAPL 2024 10-K financial analysis",
                "filing_text": SAMPLE_10K_TEXT,
                "web_observation_ledger": _sec_observation(),
            },
        ),
        network_enabled=True,
    )

    assert result["tool"] == "market_research_pack"
    assert result["status"] == "ok"
    assert result["stage169_market_research_pack"]["status"] == "ready"
    assert result["market_research_pack_ledger"][0]["pack_status"] == "ready"
    assert result["tool_observation_ledger"][0]["tool"] == "market_research_pack"


def test_normalize_market_research_pack_reads_stage171_ledger() -> None:
    action = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )

    pack = normalize_market_research_pack(sidecar={"market_research_pack_ledger": action["market_research_pack_ledger"]})

    assert pack["schema"] == "holo.stage169.market_research_pack.v1"
    assert pack["status"] == "ready"


def test_fsm_accepts_market_research_pack_observation() -> None:
    action = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )
    frame = build_intent_frame("Analyze Apple 2024 10-K net sales.", channel="holo_cli")
    arbitration = {
        "schema": "holo.stage161.model_tool_arbitration.v1",
        "selected_action": "market_research_pack",
        "required_observations": ["market_research_pack_ledger"],
        "confidence": 0.84,
    }

    fsm = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=arbitration,
        market_research_pack_ledger=action["market_research_pack_ledger"],
        final_text="Apple net sales were $391.0 billion in 2024.",
    )

    assert fsm["canonical_stop_reason"] == "final_answer_ready"
    assert any(step["selected_action"] == "market_research_pack" and step["action_status"] == "executed" for step in fsm["steps"])


def test_event_stream_renders_market_research_pack_action() -> None:
    action = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )
    fsm = run_agent_loop_fsm(
        intent_frame=build_intent_frame("Analyze Apple 2024 10-K net sales.", channel="holo_cli"),
        model_arbitration={"selected_action": "market_research_pack", "required_observations": ["market_research_pack_ledger"]},
        market_research_pack_ledger=action["market_research_pack_ledger"],
    )
    stream = build_agent_event_stream(
        {
            "text": "Grounded answer.",
            "stage160r_agent_loop_fsm": fsm,
            "market_research_pack_ledger": action["market_research_pack_ledger"],
        },
        user_text="Analyze Apple 2024 10-K net sales.",
        channel="holo_cli",
    )

    rendered = render_agent_event_stream(stream)

    assert "[act] market_research_pack status=executed" in rendered
    assert "[observe] market_research_pack status=executed" in rendered


def test_stage135_topology_includes_market_research_pack_action_node() -> None:
    action = execute_market_research_pack_action(
        {
            "query": "Apple AAPL 2024 10-K financial analysis",
            "filing_text": SAMPLE_10K_TEXT,
        },
        network_enabled=True,
        web_observation_ledger=_sec_observation(),
    )

    topology = build_stage135_i_state_topology(market_research_pack_ledger=action["market_research_pack_ledger"])

    assert topology["metrics"]["market_research_pack_action_node_count"] == 1
    assert topology["metrics"]["market_research_pack_action_status"] == "ok"
    assert any(node["id"] == "stage171_market_research_pack_action" for node in topology["nodes"])
