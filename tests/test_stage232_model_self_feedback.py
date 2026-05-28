from __future__ import annotations

from pathlib import Path
from typing import Any

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.model import DeepSeekJsonModel
from holo_agent.schema import Decision, Observation
from holo_agent.self_feedback import evaluate_self_feedback_with_model
from holo_agent.tools import ToolRegistry


def test_model_evaluator_can_recommend_next_action() -> None:
    class Evaluator:
        def evaluate_action_feedback(self, *, user_text: str, decision: dict[str, Any], observation: dict[str, Any], context: dict[str, Any], host_feedback: dict[str, Any]) -> dict[str, Any]:
            return {
                "evidence_sufficient": False,
                "evidence_gap": "Need to open the official source result.",
                "recommended_next_action": "open_page",
                "canonical_stop_reason": "continue",
                "marginal_utility": 0.9,
                "reason": "Search results are not enough evidence.",
            }

    report = evaluate_self_feedback_with_model(
        model=Evaluator(),
        user_text="search official DeepSeek docs",
        decision=Decision(action="web_search", arguments={"query": "DeepSeek docs"}),
        observation=Observation(tool="web_search", status="ok", summary="1 result", data={"results": [{"url": "https://api-docs.deepseek.com"}]}),
        context={"observations": []},
    )

    assert report["schema"] == "holo.stage232.model_self_feedback.v1"
    assert report["evaluator"] == "model"
    assert report["recommended_next_action"] == "open_page"
    assert report["model_feedback"]["reason"] == "Search results are not enough evidence."


def test_host_guardrail_blocks_model_from_marking_failed_tool_sufficient() -> None:
    class BadEvaluator:
        def evaluate_action_feedback(self, *, user_text: str, decision: dict[str, Any], observation: dict[str, Any], context: dict[str, Any], host_feedback: dict[str, Any]) -> dict[str, Any]:
            return {
                "evidence_sufficient": True,
                "recommended_next_action": "answer_direct",
                "canonical_stop_reason": "final_answer_ready",
                "evidence_gap": "",
            }

    report = evaluate_self_feedback_with_model(
        model=BadEvaluator(),
        user_text="open blocked URL",
        decision=Decision(action="open_page", arguments={"url": "https://developers.openai.com/codex/cli"}),
        observation=Observation(tool="open_page", status="error", summary="HTTP Error 403: Forbidden"),
        context={"observations": []},
    )

    assert report["evaluator"] == "model_guarded"
    assert report["evidence_sufficient"] is False
    assert report["canonical_stop_reason"] == "tool_failure_report"
    assert "host_guardrail" in report["guardrail_flags"]


def test_agent_emits_model_evaluate_event_and_metadata(tmp_path: Path) -> None:
    class Registry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__([])

        def specs(self) -> list[dict[str, Any]]:
            return [{"name": "web_search", "description": "search web", "input_schema": {"query": "string"}}]

        def run(self, name: str, arguments: dict[str, Any]) -> Observation:
            return Observation(tool="web_search", status="ok", summary="1 result", data={"results": [{"url": "https://example.com"}]})

    class Model:
        def __init__(self) -> None:
            self.count = 0

        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            self.count += 1
            if self.count == 1:
                return Decision(action="web_search", arguments={"query": "example"}, can_answer=False)
            assert context["self_feedback_reports"][0]["evaluator"] == "model"
            return Decision(action="answer_direct", can_answer=True)

        def evaluate_action_feedback(self, *, user_text: str, decision: dict[str, Any], observation: dict[str, Any], context: dict[str, Any], host_feedback: dict[str, Any]) -> dict[str, Any]:
            return {
                "evidence_sufficient": False,
                "recommended_next_action": "open_page",
                "canonical_stop_reason": "continue",
                "evidence_gap": "need opened page",
            }

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "I need opened page evidence before citing this source."

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": False}

    result = HoloAgent(
        tools=Registry(),
        model=Model(),
        config=AgentConfig(max_steps=3, log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("search example")

    assert any(event.kind == "model_evaluate" for event in result.events)
    assert result.metadata["self_feedback_reports"][0]["evaluator"] == "model"
    assert result.metadata["stage_record"] == "stage232"


def test_deepseek_model_exposes_action_feedback_json_contract() -> None:
    class StubDeepSeek(DeepSeekJsonModel):
        def __init__(self) -> None:
            super().__init__(api_key="test-key")
            self.prompt = ""

        def _call(self, messages, *, temperature=0.0) -> str:
            self.prompt = messages[0]["content"]
            return '{"evidence_sufficient": false, "evidence_gap": "Need page evidence", "recommended_next_action": "open_page", "canonical_stop_reason": "continue", "marginal_utility": 0.8, "reason": "Search result only."}'

    model = StubDeepSeek()
    report = model.evaluate_action_feedback(
        user_text="search docs",
        decision={"action": "web_search"},
        observation={"tool": "web_search", "status": "ok"},
        context={"rendered_context": "context"},
        host_feedback={"recommended_next_action": "open_page"},
    )

    assert report["recommended_next_action"] == "open_page"
    assert report["canonical_stop_reason"] == "continue"
    assert "Return JSON only" in model.prompt
    assert "hidden" not in report
