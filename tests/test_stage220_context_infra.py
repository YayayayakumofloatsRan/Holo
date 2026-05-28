from __future__ import annotations

import json
from pathlib import Path

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent import __version__
from holo_agent.cli import main
from holo_agent.hooks import HookManager
from holo_agent.memory import MemoryStore
from holo_agent.model import RuleFallbackModel
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebResearchTool, WebSearchTool
from holo_agent.workspace import load_workspace_context


class MockWebClient(WebClient):
    def search(self, query: str, *, max_results: int = 5):
        return [{"title": "Docs", "url": "https://developers.openai.com/codex/cli", "snippet": ""}]

    def fetch_text(self, url: str) -> str:
        return "<html><body>OpenAI Codex CLI official documentation terminal coding agent.</body></html>"


def _write_workspace(root: Path) -> None:
    (root / "HOLO.md").write_text("Project instruction: cite sources.", encoding="utf-8")
    skill_dir = root / ".holo" / "skills" / "web-research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Web Research\nSearch, open, evaluate, cite.", encoding="utf-8")
    (root / ".holo").mkdir(exist_ok=True)
    (root / ".holo" / "preferences.json").write_text('{"style": "concise"}', encoding="utf-8")


def _agent(root: Path, hook_manager: HookManager | None = None) -> HoloAgent:
    client = MockWebClient()
    search = WebSearchTool(client)
    open_page = OpenPageTool(client)
    return HoloAgent(
        tools=ToolRegistry([search, open_page, WebResearchTool(search, open_page)]),
        model=RuleFallbackModel(),
        config=AgentConfig(log_path=root / ".holo_kernel" / "events.jsonl", workspace_root=root),
        hooks=hook_manager or HookManager(),
    )


def test_workspace_context_loads_instructions_skills_and_preferences(tmp_path: Path) -> None:
    _write_workspace(tmp_path)

    context = load_workspace_context(tmp_path)

    assert context.instruction_layers[0].text == "Project instruction: cite sources."
    assert context.skills[0].name == "web-research"
    assert context.preferences["style"] == "concise"


def test_agent_context_event_contains_workspace_layers(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    result = _agent(tmp_path).run("search official Codex CLI docs")

    context_events = [event for event in result.events if event.kind == "context"]
    assert context_events
    workspace = context_events[0].data["workspace"]
    assert len(workspace["instruction_layers"]) == 1
    assert len(workspace["skills"]) == 1
    assert workspace["preferences"]["style"] == "concise"


def test_hooks_receive_after_tool_observation(tmp_path: Path) -> None:
    seen = []
    hooks = HookManager()
    hooks.register("after_tool", lambda payload: seen.append(payload))

    _agent(tmp_path, hooks).run("search official Codex CLI docs")

    assert seen
    assert [item["observation"]["tool"] for item in seen[:2]] == ["web_search", "open_page"]


def test_memory_store_records_preferences_and_notes(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.set_preference("market_report_style", "source-first")
    store.add_note("Prefer primary filings for finance tasks.", kind="preference")
    snapshot = store.snapshot()

    assert snapshot["preferences"]["market_report_style"] == "source-first"
    assert snapshot["notes"][0]["text"] == "Prefer primary filings for finance tasks."


def test_cli_status_and_memory_commands(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["status"]) == 0
    status_output = json.loads(capsys.readouterr().out)
    assert status_output["kernel_version"] == "2.1.0"
    assert status_output["kernel_version"] == __version__
    assert status_output["workspace"]["skills"][0]["name"] == "web-research"

    assert main(["memory", "--set", "tone=concise"]) == 0
    memory_output = json.loads(capsys.readouterr().out)
    assert memory_output["preferences"]["tone"] == "concise"


def test_agent_metadata_uses_kernel_version_not_stage_number(tmp_path: Path) -> None:
    result = _agent(tmp_path).run("search official Codex CLI docs")

    assert result.metadata["kernel_version"] == "2.1.0"
    assert result.metadata["kernel_version"] == __version__
    assert not result.metadata["kernel_version"].startswith("stage")
    assert result.metadata["stage_record"] == "stage226"
