from __future__ import annotations

from pathlib import Path

from holo_agent.context_kernel import (
    CONTEXT_KERNEL_SCHEMA,
    build_context_pack,
    compact_executable_state,
    render_context_for_model,
)
from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.model import RuleFallbackModel
from holo_agent.schema import Observation
from holo_agent.tools import ToolRegistry
from holo_agent.workspace import InstructionLayer, Skill, WorkspaceContext


def _workspace(root: Path) -> WorkspaceContext:
    return WorkspaceContext(
        root=root,
        instruction_layers=[
            InstructionLayer(path="AGENTS.md", scope="workspace", text="Use pytest. Keep reports source-first."),
            InstructionLayer(path="docs/AGENTS.md", scope="workspace", text="Docs edits require concise handoff."),
        ],
        skills=[
            Skill(name="web-research", path=".holo/skills/web-research/SKILL.md", description="Research web sources.", body="LONG BODY SHOULD NOT LOAD"),
            Skill(name="market-research", path=".holo/skills/market/SKILL.md", description="Build market dossiers.", body="MARKET BODY SHOULD NOT LOAD"),
        ],
        preferences={"style": "concise"},
    )


def test_context_pack_has_stable_prefix_and_dynamic_suffix(tmp_path: Path) -> None:
    observation = Observation(tool="web_search", status="ok", summary="found docs", data={"results": [{"url": "https://example.com"}]})

    pack = build_context_pack(
        user_text="search official docs",
        workspace=_workspace(tmp_path),
        action_space=[{"name": "web_search", "description": "search web"}],
        workflow_policy={"task_family": "research"},
        search_goal={"task_type": "official_docs"},
        observations=[observation.to_dict()],
        self_feedback_reports=[{"evidence_gap": "need opened page"}],
    )

    assert pack["schema"] == CONTEXT_KERNEL_SCHEMA
    assert "Holo Agent Kernel v2" in pack["stable_prefix"]
    assert "found docs" not in pack["stable_prefix"]
    assert "found docs" in pack["observation_suffix"]
    assert pack["exact_user_message"] == "search official docs"
    assert pack["sections"][-1]["name"] == "exact_user_message"


def test_operator_skills_are_progressively_disclosed(tmp_path: Path) -> None:
    pack = build_context_pack(
        user_text="do market research",
        workspace=_workspace(tmp_path),
        action_space=[{"name": "web_research", "description": "bounded web research"}],
        selected_operator="web-research",
    )

    rendered = render_context_for_model(pack)

    assert "Research web sources." in rendered
    assert "LONG BODY SHOULD NOT LOAD" in rendered
    assert "MARKET BODY SHOULD NOT LOAD" not in rendered


def test_unselected_skill_metadata_only(tmp_path: Path) -> None:
    pack = build_context_pack(
        user_text="do market research",
        workspace=_workspace(tmp_path),
        action_space=[{"name": "web_research", "description": "bounded web research"}],
    )

    rendered = render_context_for_model(pack)

    assert "web-research" in rendered
    assert "Research web sources." in rendered
    assert "LONG BODY SHOULD NOT LOAD" not in rendered


def test_compaction_preserves_executable_state_not_narrative() -> None:
    compact = compact_executable_state(
        decisions=[{"action": "web_search"}, {"action": "open_page"}],
        observations=[
            {"tool": "web_search", "status": "ok", "summary": "found source"},
            {"tool": "open_page", "status": "error", "summary": "HTTP Error 403: Forbidden"},
        ],
        self_feedback_reports=[{"evidence_gap": "HTTPError 403", "recommended_next_action": "answer_direct"}],
        stop_reason="tool_failure_report",
    )

    assert compact["last_action"] == "open_page"
    assert compact["last_observation_status"] == "error"
    assert compact["unresolved_gaps"] == ["HTTPError 403"]
    assert "we discussed" not in str(compact).lower()


def test_token_budget_truncates_low_priority_observations_first(tmp_path: Path) -> None:
    observations = [
        {"tool": "web_search", "status": "ok", "summary": "old " + ("x" * 300)},
        {"tool": "open_page", "status": "ok", "summary": "latest important evidence"},
    ]

    pack = build_context_pack(
        user_text="current exact request must remain",
        workspace=_workspace(tmp_path),
        action_space=[{"name": "open_page", "description": "open"}],
        observations=observations,
        token_budget=140,
    )

    rendered = render_context_for_model(pack)

    assert "current exact request must remain" in rendered
    assert "latest important evidence" in rendered
    assert pack["budget"]["truncated_sections"]


def test_render_order_keeps_exact_user_message_near_end(tmp_path: Path) -> None:
    pack = build_context_pack(
        user_text="EXACT USER REQUEST",
        workspace=_workspace(tmp_path),
        action_space=[{"name": "answer_direct", "description": "answer"}],
    )

    rendered = render_context_for_model(pack)

    assert rendered.rfind("EXACT USER REQUEST") > rendered.find("Instruction Chain")


def test_basic_capability_question_gets_direct_answer_not_tool_observation_error(tmp_path: Path) -> None:
    agent = HoloAgent(
        tools=ToolRegistry.default(root=tmp_path),
        model=RuleFallbackModel(),
        config=AgentConfig(max_steps=4, log_path=tmp_path / "events.jsonl", model_name="fallback", workspace_root=tmp_path),
    )

    result = agent.run("？？？你现在可以做什么？")

    assert result.status == "ok"
    assert "I do not have a tool observation" not in result.final
    assert "工具" in result.final
    assert "网页" in result.final or "搜索" in result.final
