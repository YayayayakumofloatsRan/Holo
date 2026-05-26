from __future__ import annotations

import json
from unittest import mock

from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage150_context_memory_fabric import build_stage150_context_memory_fabric
from holo_host.stage151_tool_decision_loop import (
    STAGE151_LIVE_TRACE_SCHEMA,
    TIME_OBSERVATION_SCHEMA,
    WEB_OBSERVATION_SCHEMA,
    build_stage151_live_trace,
    build_time_observation,
    build_tool_decision_report,
    evaluate_tool_decision_grounding,
    execute_tool_decision,
    format_stage151_live_trace,
    maybe_ground_visible_web_reply,
    repair_tool_decision_grounding,
)


def test_time_observation_is_present_every_turn() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    broker = CapabilityBroker(config)

    payload = broker.summarize_turn("普通问题，不需要联网", {}, eager_network=False)

    assert payload["time_observation"]["schema"] == TIME_OBSERVATION_SCHEMA
    assert payload["time_observation"]["local_time"]
    assert payload["stage151_tool_decision"]["time_observation"]["schema"] == TIME_OBSERVATION_SCHEMA


def test_network_disabled_blocks_web_fetch_and_records_rejected_observation() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    config.runtime.network_enabled = False
    broker = CapabilityBroker(config)

    with mock.patch.object(CapabilityBroker, "_external_lookup") as lookup:
        payload = broker.summarize_turn("联网搜索 openai codex 文档", {})

    assert not lookup.called
    assert payload["web_observation_ledger"][0]["schema"] == WEB_OBSERVATION_SCHEMA
    assert payload["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert payload["tool_observation_ledger"][0]["status"] == "rejected"


def test_non_eager_network_only_plans_web_action_without_fetch() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    broker = CapabilityBroker(config)

    with mock.patch.object(CapabilityBroker, "_external_lookup") as lookup:
        payload = broker.summarize_turn("联网搜索 openai codex 文档", {}, eager_network=False)

    assert not lookup.called
    assert payload["stage151_tool_decision"]["selected_actions"]
    assert payload["stage151_tool_decision"]["network_required"] is True
    assert payload["web_observation_ledger"] == []


def test_web_search_mocked_provider_records_ok_observation_with_source_urls() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    broker = CapabilityBroker(config)

    with mock.patch.object(
        CapabilityBroker,
        "_external_lookup",
        return_value={
            "query": "openai codex docs",
            "status": "ok",
            "provider": "mock_search",
            "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Codex CLI docs"}],
        },
    ):
        payload = broker.summarize_turn("联网搜索 openai codex 文档", {})

    observation = payload["web_observation_ledger"][0]
    assert observation["status"] == "ok"
    assert observation["provider"] == "mock_search"
    assert observation["source_urls"] == ["https://developers.openai.com/codex/cli"]
    assert payload["tool_requests"][0]["name"] == "web_search"


def test_url_input_triggers_open_page_candidate() -> None:
    decision = build_tool_decision_report("打开 https://example.com 并看功能页")

    assert decision["selected_actions"][0]["action_type"] == "open_page"
    observations = execute_tool_decision(
        decision,
        network_enabled=True,
        open_page_fn=lambda url: {
            "url": url,
            "status": "ok",
            "provider": "mock_open",
            "results": [{"title": "Example", "url": url, "snippet": "Example feature page"}],
        },
    )
    assert observations[0]["action_type"] == "open_page"
    assert observations[0]["status"] == "ok"


def test_latest_current_query_triggers_web_search_and_time_observation() -> None:
    decision = build_tool_decision_report("查一下今天最新 DeepSeek tool calling 官方文档")

    selected = [item["action_type"] for item in decision["selected_actions"]]
    assert "web_search" in selected
    web_candidate = next(item for item in decision["action_candidates"] if item["action_type"] == "web_search")
    assert "time_observation" in web_candidate["required_observations"]


def test_final_reply_cannot_claim_web_search_without_web_ledger() -> None:
    report = evaluate_tool_decision_grounding("我已经联网搜索到最新官方文档。", web_observation_ledger=[], time_observation=build_time_observation())

    assert report["status"] == "ungrounded_web_claim"
    repaired = repair_tool_decision_grounding("我已经联网搜索到最新官方文档。", report, channel="holo_cli")
    assert "web_search" in repaired
    assert "Stage151" not in repaired


def test_grounded_web_observation_replaces_unresolved_visible_lookup_reply() -> None:
    observation = {
        "schema": WEB_OBSERVATION_SCHEMA,
        "observation_id": "web:test",
        "action_type": "web_search",
        "query": "OpenAI Codex CLI docs",
        "status": "ok",
        "provider": "mock",
        "results": [
            {
                "title": "Codex CLI",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation.",
            }
        ],
        "source_urls": ["https://developers.openai.com/codex/cli"],
        "fetched_at": "2026-05-27T00:00:00Z",
        "error": "",
        "confidence": 0.9,
    }

    repaired = maybe_ground_visible_web_reply(
        user_text="联网搜索 OpenAI Codex CLI 官方文档，给出来源",
        text="我没有可核验的联网观察，不能把这当作已经查到的当前信息。",
        web_observation_ledger=[observation],
        time_observation=build_time_observation(),
    )

    assert "我已完成联网检索" in repaired
    assert "https://developers.openai.com/codex/cli" in repaired
    assert "没有可核验的联网观察" not in repaired


def test_cli_trace_shows_purpose_tool_call_observation_grounding_final() -> None:
    decision = build_tool_decision_report("联网搜索 openai codex 文档")
    observation = {
        "schema": WEB_OBSERVATION_SCHEMA,
        "observation_id": "web:test",
        "action_type": "web_search",
        "query": "openai codex docs",
        "status": "ok",
        "provider": "mock",
        "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "docs"}],
        "source_urls": ["https://developers.openai.com/codex/cli"],
        "fetched_at": "2026-05-26T00:00:00Z",
        "error": "",
        "confidence": 0.9,
    }
    grounding = evaluate_tool_decision_grounding("根据官方文档，Codex CLI...", web_observation_ledger=[observation], time_observation=decision["time_observation"])
    trace = build_stage151_live_trace(
        user_text="联网搜索 openai codex 文档",
        tool_decision=decision,
        web_observation_ledger=[observation],
        grounding=grounding,
        final_text="根据官方文档，Codex CLI...",
    )

    assert trace["schema"] == STAGE151_LIVE_TRACE_SCHEMA
    rendered = format_stage151_live_trace({"stage151_live_trace": trace})
    assert "[purpose]" in rendered
    assert "[candidate]" in rendered
    assert "[tool_call] web_search" in rendered
    assert "[observation] web_search status=ok results=1" in rendered
    assert "sources=https://developers.openai.com/codex/cli" in rendered
    assert "[grounding] status=grounded" in rendered
    assert "[final]" in rendered


def test_cli_trace_does_not_leak_hidden_reasoning() -> None:
    trace = build_stage151_live_trace(
        user_text="联网搜索",
        tool_decision=build_tool_decision_report("联网搜索 openai"),
        web_observation_ledger=[],
        grounding={},
        final_text="需要先完成搜索。",
    )

    blob = json.dumps(trace, ensure_ascii=False).lower()
    assert "chain_of_thought" not in blob
    assert "hidden reasoning" not in blob


def test_stage150_packet_includes_time_and_web_observation_summaries() -> None:
    time_observation = build_time_observation()
    web_observation = {
        "schema": WEB_OBSERVATION_SCHEMA,
        "observation_id": "web:test",
        "action_type": "web_search",
        "query": "openai codex docs",
        "status": "ok",
        "provider": "mock",
        "results": [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "docs"}],
        "source_urls": ["https://developers.openai.com/codex/cli"],
        "fetched_at": "2026-05-26T00:00:00Z",
        "error": "",
        "confidence": 0.9,
    }

    report = build_stage150_context_memory_fabric(
        user_text="联网搜索 openai codex 文档",
        channel="holo_cli",
        thread_key="holo_cli:test",
        chat_name="HoloCLI",
        capability_context={"time_observation": time_observation, "web_observation_ledger": [web_observation]},
    )

    packet = report["working_context_packet"]
    assert packet["tool_memory_visual_observations"]["time_observation"]["schema"] == TIME_OBSERVATION_SCHEMA
    assert packet["tool_memory_visual_observations"]["web_observations"]
    families = {item["family"] for item in packet["evidence_ledger_view"]}
    assert {"time", "web"}.issubset(families)


def test_stage135_topology_includes_tool_decision_loop_node() -> None:
    decision = build_tool_decision_report("联网搜索 openai codex 文档")

    payload = build_stage135_i_state_topology(
        user_text="联网搜索 openai codex 文档",
        channel="holo_cli",
        thread_key="holo_cli:test",
        chat_name="HoloCLI",
        stage151_tool_decision=decision,
    )

    assert payload["metrics"]["tool_decision_loop_node_count"] == 1
    assert payload["metrics"]["tool_decision_loop_selected_count"] >= 1
    assert any(node["id"] == "stage151_tool_decision_loop" for node in payload["nodes"])
