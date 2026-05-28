from __future__ import annotations

from pathlib import Path

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.cli import ChatSession
from holo_agent.model import RuleFallbackModel
from holo_agent.schema import Observation
from holo_agent.tools import ToolRegistry, WebSearchTool, WebClient


class TimeoutClient(WebClient):
    def search(self, query: str, *, max_results: int = 5, **kwargs):
        raise RuntimeError("provider_timeout")


def test_retry_phrase_inherits_previous_web_goal(tmp_path: Path) -> None:
    agent = HoloAgent(
        tools=ToolRegistry([WebSearchTool(TimeoutClient())]),
        model=RuleFallbackModel(),
        config=AgentConfig(max_steps=3, log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    )
    session = ChatSession(agent)

    first = session.run_turn("上网查一下deepseek api key的用法")
    second = session.run_turn("再试一次")

    assert first.stop_reason == "tool_failure_report"
    assert second.metadata["effective_user_text"] == "上网查一下deepseek api key的用法"
    assert second.observations[0].tool == "web_search"


def test_question_mark_after_failed_web_goal_inherits_goal(tmp_path: Path) -> None:
    agent = HoloAgent(
        tools=ToolRegistry([WebSearchTool(TimeoutClient())]),
        model=RuleFallbackModel(),
        config=AgentConfig(max_steps=3, log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    )
    session = ChatSession(agent)

    session.run_turn("上网查一下deepseek api key的用法")
    retry = session.run_turn("？？？")

    assert retry.metadata["effective_user_text"] == "上网查一下deepseek api key的用法"
    assert retry.observations[0].tool == "web_search"


def test_non_retry_text_does_not_inherit_failed_goal(tmp_path: Path) -> None:
    class DirectRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__([])

        def run(self, name: str, arguments: dict) -> Observation:
            return Observation(tool=name, status="error", summary="should not run")

    agent = HoloAgent(
        tools=DirectRegistry(),
        model=RuleFallbackModel(),
        config=AgentConfig(max_steps=3, log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    )
    session = ChatSession(agent)

    response = session.run_turn("hello")

    assert response.metadata["effective_user_text"] == "hello"
    assert not response.observations
