from __future__ import annotations

from pathlib import Path
from typing import Any

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.schema import Decision
from holo_agent.source_authority import classify_source_url, build_source_authority_report
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebSearchTool


def test_classifies_primary_official_sources() -> None:
    assert classify_source_url("https://developers.openai.com/codex/cli")["authority"] == "official"
    assert classify_source_url("https://github.com/openai/codex")["authority"] == "official_repository"
    assert classify_source_url("https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm")["authority"] == "regulatory_filing"


def test_classifies_secondary_sources() -> None:
    report = classify_source_url("https://example-blog.com/openai-codex-guide")

    assert report["authority"] == "secondary"
    assert report["primary"] is False


def test_build_source_authority_report_from_observations() -> None:
    observations = [
        {
            "tool": "web_search",
            "status": "ok",
            "data": {
                "results": [
                    {"title": "SEC filing", "url": "https://www.sec.gov/ixviewer/doc/action"},
                    {"title": "Company IR", "url": "https://investor.apple.com/investor-relations/default.aspx"},
                    {"title": "Blog", "url": "https://example.com/analysis"},
                ]
            },
        },
        {
            "tool": "open_page",
            "status": "ok",
            "data": {"url": "https://investor.apple.com/investor-relations/default.aspx"},
        },
    ]

    report = build_source_authority_report(observations)

    assert report["source_count"] == 3
    assert report["primary_source_count"] == 2
    assert report["authority_counts"]["regulatory_filing"] == 1
    assert report["authority_counts"]["company_official"] == 1
    assert report["opened_primary_source_count"] == 1


def test_source_authority_report_flags_no_primary_sources() -> None:
    report = build_source_authority_report(
        [{"tool": "web_search", "status": "ok", "data": {"results": [{"title": "Blog", "url": "https://example.com/analysis"}]}}]
    )

    assert report["primary_source_count"] == 0
    assert report["status"] == "weak_sources"


def test_agent_context_and_metadata_include_source_authority(tmp_path: Path) -> None:
    seen_contexts: list[dict[str, Any]] = []

    class Client(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""}]

        def fetch_text(self, url: str) -> str:
            return "Codex CLI official docs"

    class Model:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            seen_contexts.append(context)
            if not context["observations"]:
                return Decision(action="web_search", arguments={"query": "Codex CLI official docs"}, can_answer=False)
            assert context["source_authority"]["primary_source_count"] == 1
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "Official source found: https://developers.openai.com/codex/cli"

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": True}

    client = Client()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official Codex CLI docs")

    assert result.status == "ok"
    assert result.metadata["source_authority"]["primary_source_count"] == 1
    assert seen_contexts[-1]["source_authority"]["sources"][0]["authority"] == "official"
