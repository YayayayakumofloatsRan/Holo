from __future__ import annotations

from pathlib import Path
from argparse import Namespace
from typing import Any

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.cli import _agent as build_cli_agent
from holo_agent.model import DeepSeekJsonModel, RuleFallbackModel
from holo_agent.schema import Decision
from holo_agent.tools import ToolRegistry, WebClient, WebResearchTool, WebSearchTool, OpenPageTool


class AlwaysFailWebClient(WebClient):
    def search(self, query: str, *, max_results: int = 5):
        raise RuntimeError("network blocked")

    def fetch_text(self, url: str) -> str:
        raise RuntimeError("network blocked")


def _web_agent(tmp_path: Path, model) -> HoloAgent:
    client = AlwaysFailWebClient()
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    return HoloAgent(
        tools=ToolRegistry([search, open_page, WebResearchTool(search, open_page)]),
        model=model,
        config=AgentConfig(log_path=tmp_path / "events.jsonl"),
    )


def test_model_decision_receives_prior_observations_before_retry(tmp_path: Path) -> None:
    seen_contexts: list[dict[str, Any]] = []

    class InspectingModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            seen_contexts.append(context)
            if len(seen_contexts) == 1:
                return Decision(action="web_research", arguments={"query": user_text}, can_answer=False)
            assert context["observations"][0]["status"] == "error"
            return Decision(action="answer_direct", arguments={}, can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return f"observed={len(observations)} status={observations[-1]['status']}"

    result = _web_agent(tmp_path, InspectingModel()).run("search official docs")

    assert result.status == "failed"
    assert result.stop_reason == "tool_failure_report"
    assert len(seen_contexts) == 2
    assert seen_contexts[0]["observations"] == []
    assert result.final == "observed=1 status=error"


def test_fallback_does_not_repeat_identical_failed_web_research(tmp_path: Path) -> None:
    result = _web_agent(tmp_path, RuleFallbackModel()).run("search official docs")

    tool_calls = [event for event in result.events if event.kind == "tool_call"]
    assert len(tool_calls) == 1
    assert result.status == "failed"
    assert result.stop_reason == "tool_failure_report"
    assert "web_search was attempted but failed" in result.final


def test_web_research_uses_model_source_evaluator_before_accepting_source(tmp_path: Path) -> None:
    class AmbiguousClient(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [
                {"title": "OpenAI homepage", "url": "https://openai.com/", "snippet": ""},
                {"title": "OpenAI Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""},
            ]

        def fetch_text(self, url: str) -> str:
            if url.endswith("/codex/cli"):
                return "OpenAI Codex CLI official documentation for the terminal coding agent."
            return "OpenAI Codex CLI official documentation keywords appear here, but this page is only a generic homepage."

    class MockSourceEvaluator:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            self.calls.append({"query": query, "source": source, "page_text": page_text})
            accepted = source["url"].endswith("/codex/cli")
            return {
                "accepted": accepted,
                "confidence": 0.95 if accepted else 0.1,
                "reason": "specific Codex CLI documentation" if accepted else "generic homepage despite keyword overlap",
            }

    client = AmbiguousClient()
    evaluator = MockSourceEvaluator()
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    obs = WebResearchTool(search, open_page, source_evaluator=evaluator).run(
        query="search official OpenAI Codex CLI docs and cite sources"
    )

    assert obs.status == "ok"
    assert len(evaluator.calls) >= 2
    assert obs.data["sources"][0]["url"] == "https://developers.openai.com/codex/cli"
    assert all(source["url"] != "https://openai.com/" for source in obs.data["sources"])
    trajectory = obs.data["trajectory"]
    assert any(item["phase"] == "evaluate" and item["accepted"] is False for item in trajectory)


def test_source_evaluator_acceptance_is_not_overridden_by_confidence_threshold(tmp_path: Path) -> None:
    class SingleSourceClient(WebClient):
        def search(self, query: str, *, max_results: int = 5):
            return [{"title": "OpenAI Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""}]

        def fetch_text(self, url: str) -> str:
            return "OpenAI Codex CLI official documentation for the terminal coding agent."

    class LowConfidenceButAcceptedEvaluator:
        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": True, "confidence": 0.2, "reason": "model accepts with caveat"}

    client = SingleSourceClient()
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    obs = WebResearchTool(search, open_page, source_evaluator=LowConfidenceButAcceptedEvaluator()).run(
        query="search official OpenAI Codex CLI docs and cite sources"
    )

    assert obs.status == "ok"
    assert obs.data["sources"][0]["url"] == "https://developers.openai.com/codex/cli"


def test_cli_auto_model_prefers_deepseek_when_api_key_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    agent = build_cli_agent(Namespace(model="auto", max_steps=2, log=".holo_kernel/events.jsonl"))

    assert isinstance(agent.model, DeepSeekJsonModel)
    assert agent.config.model_name == "deepseek-chat"


def test_cli_auto_model_uses_explicit_fallback_when_no_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    agent = build_cli_agent(Namespace(model="auto", max_steps=2, log=".holo_kernel/events.jsonl"))

    assert isinstance(agent.model, RuleFallbackModel)
    assert agent.config.model_name == "fallback"
