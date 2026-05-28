from __future__ import annotations

from pathlib import Path
from typing import Any

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.schema import Decision, Observation
from holo_agent.tools import ToolRegistry


class NoopToolRegistry(ToolRegistry):
    def __init__(self) -> None:
        super().__init__([])


def test_engineering_goal_adds_workflow_policy_to_model_context(tmp_path: Path) -> None:
    seen_contexts: list[dict[str, Any]] = []

    class InspectingModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            seen_contexts.append(context)
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "I need evidence before changing files."

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": False}

    HoloAgent(
        tools=NoopToolRegistry(),
        model=InspectingModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Patch README.md and run tests")

    policy = seen_contexts[0]["workflow_policy"]
    assert policy["task_family"] == "engineering_change"
    assert policy["required_order"] == ["workspace_search", "file_read", "apply_patch", "test_run", "git_diff", "git_status", "answer_direct"]
    assert "Do not finalize patch/test claims without matching observations." in policy["final_answer_rules"]


def test_unverified_engineering_final_is_repaired(tmp_path: Path) -> None:
    class OverclaimingModel:
        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "I read README.md, patched it, and tests passed."

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": False}

    result = HoloAgent(
        tools=NoopToolRegistry(),
        model=OverclaimingModel(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Patch README.md and run tests")

    assert result.status == "failed"
    assert result.stop_reason == "evidence_exhausted"
    assert "Unverified engineering claim" in result.final
    assert "test_run" in result.final
    assert "apply_patch" in result.final


def test_verified_engineering_claim_is_allowed(tmp_path: Path) -> None:
    class LedgerToolRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__([])

        def run(self, name: str, arguments: dict[str, Any]) -> Observation:
            return Observation(tool="test_run", status="ok", summary="1 passed", data={"command": ["python", "-m", "pytest"]})

    class Model:
        def __init__(self) -> None:
            self.count = 0

        def decide(self, *, user_text: str, context: dict[str, Any], action_space: list[dict[str, Any]]) -> Decision:
            self.count += 1
            if self.count == 1:
                return Decision(action="test_run", arguments={"command": "python -m pytest -q"}, can_answer=False)
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict[str, Any]], context: dict[str, Any]) -> str:
            return "Tests passed."

        def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
            return {"accepted": False}

    result = HoloAgent(
        tools=LedgerToolRegistry(),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Run tests")

    assert result.status == "ok"
    assert result.final == "Tests passed."

