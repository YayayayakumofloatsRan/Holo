from __future__ import annotations

import importlib
import importlib.util

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage151_tool_decision_loop import build_grounded_web_observation_answer, execute_tool_decision


def _stage163():
    assert importlib.util.find_spec("holo_host.stage163_page_evidence_verifier") is not None
    return importlib.import_module("holo_host.stage163_page_evidence_verifier")


def _search_row() -> dict:
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:search",
        "action_type": "web_search",
        "query": "OpenAI Codex CLI docs",
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "Codex CLI",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official documentation for Codex CLI.",
            }
        ],
        "source_urls": ["https://developers.openai.com/codex/cli"],
        "search_evidence": {"status": "sufficient", "evidence_score": 0.92},
    }


def test_page_evidence_extracts_title_and_relevant_snippet() -> None:
    stage163 = _stage163()

    extracted = stage163.extract_page_evidence_text(
        """
        <html><head><title>Codex CLI documentation</title><script>ignore()</script></head>
        <body><nav>menu</nav><main>Codex CLI is an OpenAI coding agent that runs in the terminal.</main></body></html>
        """,
        url="https://developers.openai.com/codex/cli",
    )
    score = stage163.score_page_evidence(
        {
            "url": "https://developers.openai.com/codex/cli",
            "status": "ok",
            "title": extracted["title"],
            "text": extracted["text"],
        },
        query="OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
    )

    assert extracted["title"] == "Codex CLI documentation"
    assert "OpenAI coding agent" in extracted["text"]
    assert score["schema"] == "holo.stage163.page_evidence_score.v1"
    assert score["status"] == "supported"
    assert score["term_coverage"] >= 0.75
    assert "Codex CLI" in score["supporting_snippet"]


def test_page_evidence_rejects_irrelevant_page_body() -> None:
    stage163 = _stage163()

    score = stage163.score_page_evidence(
        {
            "url": "https://example.com/unrelated",
            "status": "ok",
            "title": "Generic page",
            "text": "This page discusses gardening, weather, and unrelated local events.",
        },
        query="OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
    )

    assert score["status"] == "unsupported"
    assert "query_term_coverage" in score["missing_evidence"]


def test_page_verifier_opens_top_sources_until_supported() -> None:
    stage163 = _stage163()
    calls: list[str] = []

    def open_page(url: str) -> dict:
        calls.append(url)
        if "irrelevant" in url:
            return {"url": url, "status": "ok", "results": [{"title": "Other", "url": url, "snippet": "unrelated page"}]}
        return {
            "url": url,
            "status": "ok",
            "results": [
                {
                    "title": "Codex CLI documentation",
                    "url": url,
                    "snippet": "Codex CLI is OpenAI official terminal coding agent documentation.",
                }
            ],
        }

    report = stage163.verify_page_evidence_for_search(
        {
            **_search_row(),
            "source_urls": ["https://example.com/irrelevant", "https://developers.openai.com/codex/cli"],
        },
        open_page_fn=open_page,
        network_enabled=True,
        query="OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
        max_pages=2,
    )

    assert calls == ["https://example.com/irrelevant", "https://developers.openai.com/codex/cli"]
    assert report["status"] == "supported"
    assert report["opened_count"] == 2
    assert report["selected_url"] == "https://developers.openai.com/codex/cli"


def test_page_verifier_network_disabled_records_rejection_without_opening() -> None:
    stage163 = _stage163()

    report = stage163.verify_page_evidence_for_search(
        _search_row(),
        open_page_fn=lambda url: {"status": "ok", "results": []},
        network_enabled=False,
        query="OpenAI Codex CLI docs",
        user_text="search OpenAI Codex official docs",
    )

    assert report["status"] == "rejected_network_disabled"
    assert report["opened_count"] == 0
    assert report["page_observations"][0]["status"] == "rejected_network_disabled"


def test_execute_tool_decision_attaches_page_evidence_after_web_search() -> None:
    def search(query: str) -> dict:
        return {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [
                {
                    "title": "Codex CLI",
                    "url": "https://developers.openai.com/codex/cli",
                    "snippet": "Official documentation.",
                }
            ],
        }

    def open_page(url: str) -> dict:
        return {
            "url": url,
            "status": "ok",
            "provider": "mock_open",
            "results": [
                {
                    "title": "Codex CLI documentation",
                    "url": url,
                    "snippet": "OpenAI Codex CLI documentation for the terminal coding agent.",
                }
            ],
        }

    rows = execute_tool_decision(
        {"user_text": "search OpenAI Codex official docs", "selected_actions": [{"action_type": "web_search", "query": "OpenAI Codex CLI docs"}]},
        network_enabled=True,
        web_search_fn=search,
        open_page_fn=open_page,
    )

    assert rows[0]["page_evidence"]["schema"] == "holo.stage163.page_evidence.v1"
    assert rows[0]["page_evidence"]["status"] == "supported"
    assert rows[0]["page_evidence"]["selected_url"] == "https://developers.openai.com/codex/cli"


def test_stage153_event_stream_renders_page_evidence_status() -> None:
    row = {
        **_search_row(),
        "page_evidence": {
            "schema": "holo.stage163.page_evidence.v1",
            "status": "supported",
            "opened_count": 1,
            "selected_url": "https://developers.openai.com/codex/cli",
        },
    }

    rendered = render_agent_event_stream(
        build_agent_event_stream({"text": "grounded", "web_observation_ledger": [row]}, user_text="search OpenAI Codex official docs", channel="holo_cli")
    )

    assert "page=supported" in rendered
    assert "opened=1" in rendered


def test_stage135_topology_includes_page_evidence_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="search OpenAI Codex official docs",
        channel="holo_cli",
        thread_key="holo_cli:stage163",
        chat_name="HoloCLI",
        web_observation_ledger=[
            {
                **_search_row(),
                "page_evidence": {
                    "schema": "holo.stage163.page_evidence.v1",
                    "status": "supported",
                    "opened_count": 1,
                    "selected_url": "https://developers.openai.com/codex/cli",
                },
            }
        ],
    )

    assert topology["metrics"]["page_evidence_verifier_node_count"] == 1
    assert topology["metrics"]["page_evidence_best_status"] == "supported"


def test_grounded_web_answer_uses_page_supporting_snippet() -> None:
    answer = build_grounded_web_observation_answer(
        user_text="search OpenAI Codex official docs",
        web_observation_ledger=[
            {
                **_search_row(),
                "page_evidence": {
                    "schema": "holo.stage163.page_evidence.v1",
                    "status": "supported",
                    "selected_url": "https://developers.openai.com/codex/cli",
                    "supporting_snippet": "Codex CLI is an OpenAI coding agent that runs in the terminal.",
                },
            }
        ],
    )

    assert "OpenAI coding agent that runs in the terminal" in answer
