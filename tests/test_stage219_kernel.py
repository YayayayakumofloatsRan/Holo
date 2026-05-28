from __future__ import annotations

import json
from pathlib import Path

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.event_log import EventLog
from holo_agent.model import RuleFallbackModel, lexical_source_evaluation
from holo_agent.prompt_policy import BANNED_PERSONA_TEXT, SYSTEM_PROMPT, assert_no_persona_text
from holo_agent.schema import Observation
from holo_agent.tools import OpenPageTool, QUERY_STOP_TERMS, ToolRegistry, WebClient, WebResearchTool, WebSearchTool, compact


class MockWebClient(WebClient):
    def search(self, query: str, *, max_results: int = 5):
        if "official" not in query.lower() and "documentation" not in query.lower():
            return [{"title": "Weak result", "url": "https://example.com/weak", "snippet": ""}]
        return [{"title": "OpenAI Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "Official docs"}]

    def fetch_text(self, url: str) -> str:
        if "codex/cli" in url:
            return "<html><body>OpenAI Codex CLI official documentation terminal coding agent edit files run commands.</body></html>"
        return "<html><body>Unrelated weak page.</body></html>"


class FailingWebClient(WebClient):
    def search(self, query: str, *, max_results: int = 5):
        raise RuntimeError("network blocked")

    def fetch_text(self, url: str) -> str:
        raise RuntimeError("network blocked")


def _agent(tmp_path: Path, client: WebClient) -> HoloAgent:
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    return HoloAgent(
        tools=ToolRegistry([search, open_page, WebResearchTool(search, open_page)]),
        model=RuleFallbackModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl"),
    )


def test_kernel_prompt_has_no_persona_text() -> None:
    ok, leaks = assert_no_persona_text(SYSTEM_PROMPT)

    assert ok, leaks
    assert "engineering and research agent" in SYSTEM_PROMPT


def test_web_research_runs_search_open_evaluate_loop(tmp_path: Path) -> None:
    result = _agent(tmp_path, MockWebClient()).run("search official OpenAI Codex CLI docs and cite sources")

    assert result.status == "ok"
    assert result.stop_reason == "final_answer_ready"
    assert "https://developers.openai.com/codex/cli" in result.final
    kinds = [event.kind for event in result.events]
    assert kinds[0] == "goal"
    assert kinds.index("context") < kinds.index("model_decide")
    assert kinds.index("action_space") < kinds.index("model_decide")
    assert "tool_call" in kinds
    assert "observation" in kinds
    assert [obs.tool for obs in result.observations] == ["web_search", "open_page"]


def test_web_research_failure_is_reported_as_attempted_failure(tmp_path: Path) -> None:
    result = _agent(tmp_path, FailingWebClient()).run("search official sources")

    assert result.status == "failed"
    assert result.stop_reason == "tool_failure_report"
    assert "web_search was attempted but failed" in result.final
    assert "network blocked" in result.final
    tool_calls = [event for event in result.events if event.kind == "tool_call"]
    assert len(tool_calls) == 1


def test_duckduckgo_redirect_urls_are_decoded_before_opening(tmp_path: Path) -> None:
    class RedirectClient(MockWebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [
                {
                    "title": "OpenAI Codex CLI",
                    "url": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fdevelopers.openai.com%2Fcodex%2Fcli",
                    "snippet": "",
                }
            ]

    result = _agent(tmp_path, RedirectClient()).run("search official OpenAI Codex CLI docs")

    assert result.status == "ok"
    assert "https://developers.openai.com/codex/cli" in result.final


def test_event_log_writes_jsonl_without_private_reasoning(tmp_path: Path) -> None:
    result = _agent(tmp_path, MockWebClient()).run("search official OpenAI Codex CLI docs")
    rows = EventLog(tmp_path / "events.jsonl").read()
    blob = json.dumps(rows, ensure_ascii=False)

    assert rows
    assert "reasoning_content" not in blob
    assert rows[-1]["kind"] == "final"
    assert result.final in rows[-1]["message"]


def test_chinese_request_is_preserved_in_goal_event(tmp_path: Path) -> None:
    result = _agent(tmp_path, MockWebClient()).run("检索 OpenAI Codex CLI 官方文档并给出来源")

    assert result.events[0].message == "检索 OpenAI Codex CLI 官方文档并给出来源"
    assert result.status == "ok"


def test_bing_navigation_links_are_not_search_sources() -> None:
    page = """
    <a href="https://www.bing.com/images/search?q=OpenAI+Codex">Images</a>
    <a href="https://www.bing.com/videos/search?q=OpenAI+Codex">Videos</a>
    <a href="https://www.bing.com/maps?q=OpenAI+Codex">Maps</a>
    <a href="https://www.bing.com/shop/topics?q=OpenAI+Codex">Shopping</a>
    <a href="https://www.bing.com/travel/search?q=OpenAI+Codex&m=flights">Flights</a>
    <a href="https://www.bing.com/travel/search?q=OpenAI+Codex&m=travel">Travel</a>
    <a href="https://www.google.com/xhtml/search?q=OpenAI+Codex">Google fallback search</a>
    <a href="https://developers.openai.com/codex/cli">OpenAI Codex CLI docs</a>
    """

    results = WebClient()._parse_search_results(page, max_results=5)

    assert results == [{"title": "OpenAI Codex CLI docs", "url": "https://developers.openai.com/codex/cli", "snippet": ""}]


def test_chinese_query_terms_are_utf8_not_mojibake() -> None:
    assert "检索" in QUERY_STOP_TERMS
    assert "官方" in QUERY_STOP_TERMS
    assert all("�" not in term and "€" not in term for term in QUERY_STOP_TERMS)
    assert all("�" not in term and "€" not in term for term in BANNED_PERSONA_TEXT)
    evaluation = lexical_source_evaluation("检索 OpenAI Codex CLI 官方文档", {"title": "OpenAI Codex CLI", "url": ""}, "official documentation")
    assert evaluation["accepted"] is True
    assert compact("abc", 2).endswith("...")


def test_web_research_rejects_weak_homepage_when_specific_doc_matches(tmp_path: Path) -> None:
    class SpecificDocsClient(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [
                {"title": "openai.com", "url": "https://openai.com/", "snippet": ""},
                {"title": "OpenAI Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""},
            ]

        def fetch_text(self, url: str) -> str:
            if url.endswith("/codex/cli"):
                return "OpenAI Codex CLI official documentation terminal coding agent."
            return "OpenAI product homepage."

    client = SpecificDocsClient()
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    obs = WebResearchTool(search, open_page, source_evaluator=RuleFallbackModel()).run(
        query="search official OpenAI Codex CLI docs and cite sources"
    )

    assert obs.status == "ok"
    assert obs.data["sources"][0]["url"] == "https://developers.openai.com/codex/cli"
    assert all(source["url"] != "https://openai.com/" for source in obs.data["sources"])
