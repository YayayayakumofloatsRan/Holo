from __future__ import annotations

from pathlib import Path
from typing import Any

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.schema import Decision
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebSearchTool


class DocsClient(WebClient):
    def search(self, query: str, *, max_results: int = 5):
        return [
            {"title": "OpenAI Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "official docs"},
            {"title": "OpenAI Codex repo", "url": "https://github.com/openai/codex", "snippet": "source repo"},
        ]

    def fetch_text(self, url: str) -> str:
        return "OpenAI Codex CLI official documentation. It is a terminal coding agent."


def test_successful_web_search_returns_to_model_instead_of_host_stopping(tmp_path: Path) -> None:
    decisions_seen: list[dict[str, Any]] = []

    class ScriptedModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            decisions_seen.append(context)
            if len(decisions_seen) == 1:
                return Decision(action="web_search", arguments={"query": "OpenAI Codex CLI official docs"}, can_answer=False)
            assert context["observations"][0]["tool"] == "web_search"
            return Decision(action="open_page", arguments={"url": context["observations"][0]["data"]["results"][0]["url"]}, can_answer=False)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "finalized"

    client = DocsClient()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=ScriptedModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", max_steps=2),
    ).run("search official OpenAI Codex CLI docs")

    assert len(decisions_seen) == 2
    assert [obs.tool for obs in result.observations] == ["web_search", "open_page"]
    action_space = next(event for event in result.events if event.kind == "action_space").data["actions"]
    assert any(action["name"] == "answer_direct" for action in action_space)


def test_llm_controls_search_open_final_sequence(tmp_path: Path) -> None:
    class ScriptedModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            observations = context.get("observations", [])
            if not observations:
                return Decision(action="web_search", arguments={"query": "OpenAI Codex CLI official docs"}, can_answer=False)
            if observations[-1]["tool"] == "web_search":
                return Decision(action="open_page", arguments={"url": observations[-1]["data"]["results"][0]["url"]}, can_answer=False)
            return Decision(action="answer_direct", arguments={}, can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            assert [obs["tool"] for obs in observations] == ["web_search", "open_page"]
            return "Codex CLI docs source: https://developers.openai.com/codex/cli"

    client = DocsClient()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=ScriptedModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", max_steps=4),
    ).run("search official OpenAI Codex CLI docs")

    assert result.status == "ok"
    assert result.stop_reason == "final_answer_ready"
    assert "https://developers.openai.com/codex/cli" in result.final
    assert [event.kind for event in result.events].count("model_decide") == 3


def test_model_finalize_alias_is_treated_as_answer_direct(tmp_path: Path) -> None:
    class ScriptedModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            observations = context.get("observations", [])
            if not observations:
                return Decision(action="web_search", arguments={"query": "OpenAI Codex CLI official docs"}, can_answer=False)
            return Decision(action="finalize", arguments={}, can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "final answer from observed search results"

    client = DocsClient()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=ScriptedModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", max_steps=4),
    ).run("search official OpenAI Codex CLI docs")

    assert result.status == "ok"
    assert result.stop_reason == "final_answer_ready"
    assert result.final == "final answer from observed search results"
    assert all(event.kind != "tool_call" or event.message != "finalize" for event in result.events)


def test_recovered_tool_failure_with_later_success_can_finish_ok(tmp_path: Path) -> None:
    class RecoveringToolRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__([])

        def run(self, name: str, arguments: dict[str, Any]):
            if name == "web_search" and arguments.get("query") == "bad":
                from holo_agent.schema import Observation

                return Observation(tool="web_search", status="error", summary="temporary failure", data={"query": "bad"})
            from holo_agent.schema import Observation

            return Observation(tool="open_page", status="ok", summary="official docs", data={"url": "https://developers.openai.com/codex/cli"})

    class Model:
        def __init__(self) -> None:
            self.count = 0

        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            self.count += 1
            if self.count == 1:
                return Decision(action="web_search", arguments={"query": "bad"}, can_answer=False)
            if self.count == 2:
                return Decision(action="open_page", arguments={"url": "https://developers.openai.com/codex/cli"}, can_answer=False)
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "Official docs confirmed: https://developers.openai.com/codex/cli"

    result = HoloAgent(
        tools=RecoveringToolRegistry(),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", max_steps=5),
    ).run("Find official Codex docs")

    assert result.status == "ok"
    assert result.stop_reason == "final_answer_ready"
