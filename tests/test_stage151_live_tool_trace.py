from __future__ import annotations

import json
from unittest import mock

from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config
from holo_host.stage151_live_tool_trace import (
    STAGE151_SCHEMA,
    build_external_lookup_observation,
    build_stage151_live_tool_trace,
    evaluate_network_grounding,
    format_stage151_live_trace,
    repair_network_grounding,
)


def test_network_disabled_blocks_external_lookup_and_records_rejection() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    config.runtime.network_enabled = False
    broker = CapabilityBroker(config)

    with mock.patch.object(CapabilityBroker, "_external_lookup") as lookup:
        payload = broker.summarize_turn("search latest Holo agent paper", {})

    assert not lookup.called
    assert payload["tool_requests"][0]["name"] == "web_search"
    assert payload["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    row = payload["tool_observation_ledger"][0]
    assert row["tool"] == "web_search"
    assert row["status"] == "rejected"
    assert row["error"] == "network_disabled"
    assert row["grounding_tags"] == []


def test_network_enabled_mocked_lookup_records_ledger() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    config.runtime.network_enabled = True
    broker = CapabilityBroker(config)

    with mock.patch.object(
        CapabilityBroker,
        "_external_lookup",
        return_value={
            "query": "latest Holo agent paper",
            "status": "ok",
            "results": [{"title": "Paper", "url": "https://example.com/paper", "snippet": "A current result."}],
        },
    ):
        payload = broker.summarize_turn("search latest Holo agent paper", {})

    row = payload["tool_observation_ledger"][0]
    assert row["status"] == "ok"
    assert row["source_urls"] == ["https://example.com/paper"]
    assert row["fetched_at"]
    assert "external_lookup" in row["grounding_tags"]


def test_current_fact_claim_without_ledger_is_repaired() -> None:
    report = evaluate_network_grounding("I searched the web and found the latest result.", [])

    assert report["status"] == "missing_current_lookup_ledger"
    assert report["repair_required"] is True
    repaired = repair_network_grounding("I searched the web and found the latest result.", report, channel="holo_cli")
    assert "recorded current web lookup" in repaired
    assert "Stage151" not in repaired


def test_current_fact_claim_with_ledger_passes() -> None:
    ledger = [
        build_external_lookup_observation(
            {
                "query": "latest Holo agent paper",
                "status": "ok",
                "results": [{"title": "Paper", "url": "https://example.com/paper", "snippet": "A current result."}],
            },
            network_enabled=True,
        )
    ]

    report = evaluate_network_grounding("I searched the web and found the latest result.", ledger)

    assert report["status"] == "grounded"
    assert report["repair_required"] is False
    assert report["successful_lookup_count"] == 1


def test_cli_trace_shows_tool_call_and_observation() -> None:
    ledger = [
        build_external_lookup_observation(
            {
                "query": "latest Holo agent paper",
                "status": "ok",
                "results": [{"title": "Paper", "url": "https://example.com/paper", "snippet": "A current result."}],
            },
            network_enabled=True,
        )
    ]
    trace = build_stage151_live_tool_trace(
        user_text="search latest Holo agent paper",
        capability_context={
            "tool_requests": [{"name": "external_lookup", "reason": "requested", "payload": {"query": "latest Holo agent paper"}}],
            "tool_observation_ledger": ledger,
        },
        reply_result={"text": "Here is the result.", "tool_observation_ledger": ledger},
    )

    assert trace["schema"] == STAGE151_SCHEMA
    rendered = format_stage151_live_trace({"stage151_live_tool_trace": trace})
    assert "[plan]" in rendered
    assert "[tool_call] external_lookup" in rendered
    assert "[tool_observation] external_lookup status=ok results=1" in rendered
    assert "[grounding]" in rendered
    assert "[final]" in rendered


def test_trace_does_not_leak_hidden_reasoning() -> None:
    trace = build_stage151_live_tool_trace(
        user_text="search latest Holo agent paper",
        capability_context={"tool_requests": [{"name": "external_lookup", "reason": "requested", "payload": {"query": "paper"}}]},
        reply_result={"text": "Done."},
    )

    blob = json.dumps(trace, ensure_ascii=False).lower()
    assert "chain_of_thought" not in blob
    assert "hidden reasoning" not in blob
    assert "[final] Done." in format_stage151_live_trace({"stage151_live_tool_trace": trace})
