from __future__ import annotations

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.schema import Decision
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebSearchTool
from holo_agent.web_providers import SourcePolicyProvider


def test_source_policy_provider_returns_openai_codex_docs_candidate() -> None:
    provider = SourcePolicyProvider()

    attempt = provider.search(
        "Find official OpenAI Codex CLI docs and cite sources",
        allowed_domains=["developers.openai.com"],
        max_results=5,
    )

    assert attempt.status == "ok"
    assert attempt.results[0]["url"] == "https://developers.openai.com/codex/cli"
    assert attempt.results[0]["source_family"] == "official_docs"


def test_source_policy_provider_returns_deepseek_tool_docs_candidate() -> None:
    provider = SourcePolicyProvider()

    attempt = provider.search(
        "DeepSeek tool calling official docs",
        allowed_domains=["api-docs.deepseek.com"],
        max_results=5,
    )

    assert attempt.status == "ok"
    assert "api-docs.deepseek.com" in attempt.results[0]["url"]
    assert attempt.results[0]["source_family"] == "official_docs"


def test_web_client_default_uses_source_policy_provider_before_html_search() -> None:
    client = WebClient()

    results = client.search(
        "Find official OpenAI Codex CLI docs and cite sources",
        allowed_domains=["developers.openai.com"],
        max_results=5,
    )

    assert results[0]["url"] == "https://developers.openai.com/codex/cli"
    assert results[0]["provider"] == "source_policy"


def test_agent_can_reach_openai_docs_with_source_policy_provider_without_generic_search(tmp_path) -> None:
    class Client(WebClient):
        def fetch_text(self, url: str) -> str:
            return "Codex CLI is OpenAI's coding agent that runs locally from your terminal."

    class Model:
        def decide(self, *, user_text: str, context: dict, action_space: list[dict]) -> Decision:
            if not context["observations"]:
                return Decision(action="web_search", arguments={"query": user_text})
            if len(context["observations"]) == 1:
                result = context["observations"][0]["data"]["results"][0]
                assert result["provider"] == "source_policy"
                return Decision(action="open_page", arguments={"url": result["url"]})
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict], context: dict) -> str:
            return "Official source found: https://developers.openai.com/codex/cli"

        def evaluate_source(self, *, query: str, source: dict, page_text: str, trajectory: list[dict]) -> dict:
            return {"accepted": True}

    client = Client()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official OpenAI Codex CLI docs and cite sources")

    assert result.status == "ok"
    assert result.metadata["web_provider_health"]["attempts"][0]["provider"] == "source_policy"


def test_failed_open_after_source_candidate_stops_as_tool_failure(tmp_path) -> None:
    class Client(WebClient):
        def fetch_text(self, url: str) -> str:
            raise RuntimeError("HTTP Error 403: Forbidden")

    result = HoloAgent(
        tools=ToolRegistry.default(root=tmp_path, client=Client()),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official OpenAI Codex CLI docs and cite sources")

    assert result.status == "failed"
    assert result.stop_reason == "tool_failure_report"
    assert "open_page was attempted but failed" in result.final
