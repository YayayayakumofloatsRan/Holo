from __future__ import annotations

from pathlib import Path

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.model import RuleFallbackModel
from holo_agent.schema import Decision, Observation
from holo_agent.self_feedback import evaluate_self_feedback
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient


def test_open_page_success_feedback_recommends_final_answer() -> None:
    report = evaluate_self_feedback(
        user_text="open https://docs.python.org/3/library/asyncio.html and summarize source",
        decision=Decision(action="open_page", arguments={"url": "https://docs.python.org/3/library/asyncio.html"}),
        observation=Observation(tool="open_page", status="ok", summary="asyncio docs", data={"url": "https://docs.python.org/3/library/asyncio.html"}),
        context={"observations": []},
    )

    assert report["schema"] == "holo.stage230.self_feedback.v1"
    assert report["evidence_sufficient"] is True
    assert report["recommended_next_action"] == "answer_direct"
    assert report["canonical_stop_reason"] == "final_answer_ready"


def test_open_page_http_error_feedback_reports_tool_failure() -> None:
    report = evaluate_self_feedback(
        user_text="open https://developers.openai.com/codex/cli and summarize source",
        decision=Decision(action="open_page", arguments={"url": "https://developers.openai.com/codex/cli"}),
        observation=Observation(
            tool="open_page",
            status="error",
            summary="HTTP Error 403: Forbidden",
            data={"fetch": {"status_code": 403, "error_type": "HTTPError"}},
        ),
        context={"observations": []},
    )

    assert report["evidence_sufficient"] is False
    assert report["recoverable_failure"] is False
    assert report["canonical_stop_reason"] == "tool_failure_report"
    assert "HTTPError" in report["evidence_gap"]


def test_web_search_success_feedback_requires_open_page() -> None:
    report = evaluate_self_feedback(
        user_text="search official DeepSeek tool calling docs",
        decision=Decision(action="web_search", arguments={"query": "DeepSeek tool calling docs"}),
        observation=Observation(
            tool="web_search",
            status="ok",
            summary="1 result",
            data={"results": [{"title": "DeepSeek API Docs", "url": "https://api-docs.deepseek.com/guides/function_calling"}]},
        ),
        context={"observations": []},
    )

    assert report["evidence_sufficient"] is False
    assert report["recommended_next_action"] == "open_page"
    assert report["canonical_stop_reason"] == "continue"
    assert "page evidence" in report["evidence_gap"]


def test_agent_emits_self_feedback_event_and_metadata(tmp_path: Path) -> None:
    class Client(WebClient):
        def fetch_text(self, url: str) -> str:
            return "<html><title>Asyncio</title><main>asyncio docs</main></html>"

    tools = ToolRegistry([OpenPageTool(Client())])
    agent = HoloAgent(
        tools=tools,
        model=RuleFallbackModel(),
        config=AgentConfig(max_steps=4, log_path=tmp_path / "events.jsonl", model_name="fallback", workspace_root=tmp_path),
    )

    result = agent.run("open https://docs.python.org/3/library/asyncio.html and summarize source")

    assert result.status == "ok"
    assert any(event.kind == "self_feedback" for event in result.events)
    assert result.metadata["self_feedback_reports"][0]["recommended_next_action"] == "answer_direct"
    assert result.metadata["stage_record"] == "stage230"


def test_self_feedback_is_visible_to_next_model_decision(tmp_path: Path) -> None:
    class Client(WebClient):
        def fetch_text(self, url: str) -> str:
            return "<html><title>Docs</title><main>content</main></html>"

    class RecordingModel(RuleFallbackModel):
        def __init__(self) -> None:
            self.contexts = []

        def decide(self, *, user_text, context, action_space):
            self.contexts.append(context)
            return super().decide(user_text=user_text, context=context, action_space=action_space)

    model = RecordingModel()
    agent = HoloAgent(
        tools=ToolRegistry([OpenPageTool(Client())]),
        model=model,
        config=AgentConfig(max_steps=4, log_path=tmp_path / "events.jsonl", model_name="fallback", workspace_root=tmp_path),
    )

    agent.run("open https://docs.python.org/3/library/asyncio.html and summarize source")

    assert any(ctx.get("self_feedback_reports") for ctx in model.contexts[1:])
