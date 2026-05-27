from __future__ import annotations

import importlib
import importlib.util

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage151_tool_decision_loop import execute_tool_decision


def _stage164():
    assert importlib.util.find_spec("holo_host.stage164_search_fallback_synthesis") is not None
    return importlib.import_module("holo_host.stage164_search_fallback_synthesis")


def _result(title: str, url: str, snippet: str) -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet}


def _supported_row(url: str, snippet: str) -> dict:
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:" + url.rsplit("/", 1)[-1],
        "action_type": "web_search",
        "query": "OpenAI Codex CLI docs",
        "status": "ok",
        "provider": "mock",
        "results": [_result("Codex CLI", url, "official docs")],
        "source_urls": [url],
        "search_evidence": {"status": "sufficient", "evidence_score": 0.9},
        "page_evidence": {
            "schema": "holo.stage163.page_evidence.v1",
            "status": "supported",
            "selected_url": url,
            "best_evidence_score": 0.91,
            "supporting_snippet": snippet,
            "opened_count": 1,
        },
    }


def test_fallback_search_tries_second_provider_after_primary_error() -> None:
    stage164 = _stage164()
    calls: list[str] = []

    def primary(query: str) -> dict:
        calls.append("primary:" + query)
        return {"query": query, "status": "error", "results": [], "provider": "primary", "error": "timeout"}

    def fallback(query: str) -> dict:
        calls.append("fallback:" + query)
        return {
            "query": query,
            "status": "ok",
            "provider": "fallback",
            "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official documentation")],
        }

    report = stage164.run_search_fallback_controller(
        "OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
        network_enabled=True,
        search_providers=[("primary", primary), ("fallback", fallback)],
        max_attempts_per_provider=1,
    )

    assert calls == ["primary:OpenAI Codex CLI docs", "fallback:OpenAI Codex CLI docs"]
    assert report["schema"] == "holo.stage164.search_fallback.v1"
    assert report["status"] == "sufficient"
    assert report["selected_provider"] == "fallback"
    assert report["provider_attempt_count"] == 2
    assert report["observations"][-1]["stage164_search_fallback"]["provider_name"] == "fallback"


def test_fallback_search_stops_when_primary_is_sufficient() -> None:
    stage164 = _stage164()
    calls: list[str] = []

    def primary(query: str) -> dict:
        calls.append("primary")
        return {
            "query": query,
            "status": "ok",
            "provider": "primary",
            "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official documentation")],
        }

    def fallback(query: str) -> dict:
        calls.append("fallback")
        return {"query": query, "status": "ok", "provider": "fallback", "results": []}

    report = stage164.run_search_fallback_controller(
        "OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
        network_enabled=True,
        search_providers=[("primary", primary), ("fallback", fallback)],
    )

    assert calls == ["primary"]
    assert report["selected_provider"] == "primary"
    assert report["status"] == "sufficient"


def test_fallback_search_network_disabled_rejects_without_provider_calls() -> None:
    stage164 = _stage164()
    calls: list[str] = []

    report = stage164.run_search_fallback_controller(
        "OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
        network_enabled=False,
        search_providers=[("primary", lambda query: calls.append(query) or {"query": query, "status": "ok", "results": []})],
    )

    assert calls == []
    assert report["status"] == "rejected_network_disabled"
    assert report["observations"][0]["status"] == "rejected_network_disabled"


def test_source_synthesis_combines_supported_page_evidence() -> None:
    stage164 = _stage164()

    synthesis = stage164.build_source_synthesis(
        [
            _supported_row("https://developers.openai.com/codex/cli", "Codex CLI is OpenAI's terminal coding agent."),
            _supported_row("https://github.com/openai/codex", "The openai/codex repository contains Codex CLI source code."),
        ],
        query="OpenAI Codex CLI docs",
    )

    assert synthesis["schema"] == "holo.stage164.source_synthesis.v1"
    assert synthesis["status"] == "supported"
    assert synthesis["supported_source_count"] == 2
    assert len(synthesis["citations"]) == 2
    assert "terminal coding agent" in synthesis["synthesized_summary"]


def test_source_synthesis_detects_conflicting_source_snippets() -> None:
    stage164 = _stage164()
    yes = _supported_row("https://example.com/a", "Codex CLI supports local terminal coding workflows.")
    no = _supported_row("https://example.com/b", "Codex CLI does not support local terminal coding workflows.")

    synthesis = stage164.build_source_synthesis([yes, no], query="Codex CLI local terminal support")

    assert synthesis["status"] == "conflicted"
    assert synthesis["conflict_count"] >= 1
    assert "source_conflict" in synthesis["risk_flags"]


def test_execute_tool_decision_attaches_fallback_and_source_synthesis() -> None:
    def primary(query: str) -> dict:
        return {"query": query, "status": "error", "results": [], "provider": "primary", "error": "timeout"}

    def fallback(query: str) -> dict:
        return {
            "query": query,
            "status": "ok",
            "provider": "fallback",
            "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official documentation")],
        }

    def open_page(url: str) -> dict:
        return {
            "url": url,
            "status": "ok",
            "results": [_result("Codex CLI", url, "Codex CLI is an OpenAI terminal coding agent documented on the official site.")],
        }

    rows = execute_tool_decision(
        {"user_text": "search OpenAI Codex official docs", "selected_actions": [{"action_type": "web_search", "query": "OpenAI Codex CLI docs"}]},
        network_enabled=True,
        web_search_fn=primary,
        fallback_search_fns=[("fallback", fallback)],
        open_page_fn=open_page,
    )

    assert rows[-1]["stage164_search_fallback"]["provider_name"] == "fallback"
    assert rows[-1]["source_synthesis"]["schema"] == "holo.stage164.source_synthesis.v1"
    assert rows[-1]["source_synthesis"]["status"] == "supported"


def test_stage153_event_stream_renders_source_synthesis() -> None:
    row = _supported_row("https://developers.openai.com/codex/cli", "Codex CLI is OpenAI's terminal coding agent.")
    row["source_synthesis"] = {
        "schema": "holo.stage164.source_synthesis.v1",
        "status": "supported",
        "supported_source_count": 1,
        "confidence": 0.86,
    }

    rendered = render_agent_event_stream(
        build_agent_event_stream({"text": "grounded", "web_observation_ledger": [row]}, user_text="search OpenAI Codex official docs", channel="holo_cli")
    )

    assert "synthesis=supported" in rendered
    assert "supported_sources=1" in rendered


def test_stage135_topology_includes_source_synthesis_node() -> None:
    row = _supported_row("https://developers.openai.com/codex/cli", "Codex CLI is OpenAI's terminal coding agent.")
    row["source_synthesis"] = {
        "schema": "holo.stage164.source_synthesis.v1",
        "status": "supported",
        "supported_source_count": 1,
        "confidence": 0.86,
    }

    topology = build_stage135_i_state_topology(
        user_text="search OpenAI Codex official docs",
        channel="holo_cli",
        thread_key="holo_cli:stage164",
        chat_name="HoloCLI",
        web_observation_ledger=[row],
    )

    assert topology["metrics"]["source_synthesis_node_count"] == 1
    assert topology["metrics"]["source_synthesis_status"] == "supported"
