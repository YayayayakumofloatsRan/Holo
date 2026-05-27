from __future__ import annotations

from typing import Any

TOOL_ACTION_SPACE_SCHEMA = "holo.stage161.tool_action_space.v1"


def _action(
    action_type: str,
    *,
    description: str,
    input_schema: dict[str, Any] | None = None,
    observation_schema: dict[str, Any] | None = None,
    risk_level: str = "low",
    requires_network: bool = False,
    requires_workspace: bool = False,
    is_readonly: bool = True,
    examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": TOOL_ACTION_SPACE_SCHEMA,
        "action_type": action_type,
        "description": description,
        "input_schema": dict(input_schema or {}),
        "observation_schema": dict(observation_schema or {}),
        "risk_level": risk_level,
        "requires_network": bool(requires_network),
        "requires_workspace": bool(requires_workspace),
        "is_readonly": bool(is_readonly),
        "examples": list(examples or []),
    }


def build_tool_action_space(*, include_write_actions: bool = True) -> list[dict[str, Any]]:
    actions = [
        _action(
            "answer_direct",
            description="Answer from already sufficient context and ledgers; must not claim external evidence without ledger support.",
            input_schema={"type": "object", "properties": {"answer_plan": {"type": "string"}}},
            observation_schema={"type": "none"},
            examples=[{"when": "definition or synthesis from current context", "arguments": {"answer_plan": "concise grounded answer"}}],
        ),
        _action(
            "ask_clarification",
            description="Ask the user for missing task-critical information before acting.",
            input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
            observation_schema={"type": "user_reply"},
            examples=[{"when": "multiple incompatible targets", "arguments": {"question": "Which file should I inspect?"}}],
        ),
        _action(
            "memory_recall",
            description="Recall prior conversation, reusable state, directives, or durable memory through host memory surfaces.",
            input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            observation_schema={"ledger": "memory_observation_ledger"},
            examples=[{"when": "user asks what was said earlier", "arguments": {"query": "previous user directive about emoji"}}],
        ),
        _action(
            "time_observe",
            description="Observe host clock for date/time-sensitive claims.",
            input_schema={"type": "object", "properties": {"reason": {"type": "string"}}},
            observation_schema={"ledger": "time_observation"},
            examples=[{"when": "today/current date matters", "arguments": {"reason": "date-sensitive answer"}}],
        ),
        _action(
            "web_search",
            description="Search the web for current or explicitly requested external information.",
            input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            observation_schema={"ledger": "web_observation_ledger"},
            requires_network=True,
            examples=[{"when": "user asks to search official docs", "arguments": {"query": "DeepSeek tool calling docs"}}],
        ),
        _action(
            "open_page",
            description="Open a URL and record fetched page evidence.",
            input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
            observation_schema={"ledger": "web_observation_ledger"},
            requires_network=True,
            examples=[{"when": "user provides a URL", "arguments": {"url": "https://example.com"}}],
        ),
        _action(
            "find_in_page",
            description="Find a string or pattern inside an already identified page.",
            input_schema={
                "type": "object",
                "required": ["url", "pattern"],
                "properties": {"url": {"type": "string"}, "pattern": {"type": "string"}},
            },
            observation_schema={"ledger": "web_observation_ledger"},
            requires_network=True,
            examples=[{"when": "find SDK section in docs", "arguments": {"url": "https://example.com", "pattern": "SDK"}}],
        ),
        _action(
            "workspace_search",
            description="Search repository files for names, symbols, or text.",
            input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "glob": {"type": "string"}}},
            observation_schema={"ledger": "engineering_action_ledger"},
            requires_workspace=True,
            examples=[{"when": "locate implementation", "arguments": {"query": "run_agent_loop_fsm"}}],
        ),
        _action(
            "file_read",
            description="Read a workspace file, optionally with line bounds.",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
            },
            observation_schema={"ledger": "engineering_action_ledger"},
            requires_workspace=True,
            examples=[{"when": "inspect code before editing", "arguments": {"path": "holo_host/reply_api.py", "start_line": 1}}],
        ),
        _action(
            "apply_patch",
            description="Apply a scoped workspace patch. Host policy rejects unsafe patches.",
            input_schema={"type": "object", "required": ["patch_text"], "properties": {"patch_text": {"type": "string"}}},
            observation_schema={"ledger": "engineering_action_ledger"},
            risk_level="medium",
            requires_workspace=True,
            is_readonly=False,
            examples=[{"when": "implement a focused fix", "arguments": {"patch_text": "*** Begin Patch..."}}],
        ),
        _action(
            "test_run",
            description="Run an allowlisted verification command.",
            input_schema={"type": "object", "required": ["command"], "properties": {"command": {"type": "string"}}},
            observation_schema={"ledger": "engineering_action_ledger"},
            risk_level="medium",
            requires_workspace=True,
            examples=[{"when": "verify tests", "arguments": {"command": "python -m pytest tests/test_file.py -q"}}],
        ),
        _action(
            "git_status",
            description="Read git status in the workspace.",
            input_schema={"type": "object", "properties": {}},
            observation_schema={"ledger": "engineering_action_ledger"},
            requires_workspace=True,
            examples=[{"when": "summarize changed files", "arguments": {}}],
        ),
        _action(
            "git_diff",
            description="Read git diff, optionally scoped to one repository-relative path.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            observation_schema={"ledger": "engineering_action_ledger"},
            requires_workspace=True,
            examples=[{"when": "review patch", "arguments": {"path": "holo_host/reply_api.py"}}],
        ),
        _action(
            "project_state_read",
            description="Read project goals, decisions, open loops, risks, and next actions.",
            input_schema={"type": "object", "properties": {"project": {"type": "string"}}},
            observation_schema={"ledger": "project_state_graph"},
            examples=[{"when": "project continuity needed", "arguments": {"project": "Holo"}}],
        ),
        _action(
            "project_state_update",
            description="Propose a project state graph update; host records only if the runtime path authorizes it.",
            input_schema={"type": "object", "properties": {"project": {"type": "string"}, "update": {"type": "string"}}},
            observation_schema={"ledger": "project_state_update"},
            risk_level="medium",
            is_readonly=False,
            examples=[{"when": "record accepted next action", "arguments": {"project": "Holo", "update": "Stage161 started"}}],
        ),
        _action(
            "market_research_pack",
            description="Build or require a source-authority-sufficient filing evidence pack before market or financial analysis claims.",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "entity": {"type": "string"},
                    "filing_type": {"type": "string"},
                },
            },
            observation_schema={"ledger": "market_research_pack"},
            requires_network=True,
            examples=[
                {
                    "when": "user asks for company financial or filing analysis",
                    "arguments": {"query": "Apple AAPL 2024 10-K financial analysis", "filing_type": "10-K"},
                }
            ],
        ),
        _action(
            "defer",
            description="Do not act now; report why the host should stop or wait.",
            input_schema={"type": "object", "properties": {"reason": {"type": "string"}}},
            observation_schema={"type": "none"},
            examples=[{"when": "boundary prevents action", "arguments": {"reason": "needs user clarification"}}],
        ),
    ]
    if not include_write_actions:
        actions = [item for item in actions if item.get("is_readonly")]
    return actions


def action_space_index(action_space: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return {str(item.get("action_type", "") or ""): dict(item) for item in list(action_space or build_tool_action_space()) if isinstance(item, dict)}


def render_action_space_for_prompt(action_space: list[dict[str, Any]] | None = None) -> str:
    lines = ["Available Tool Action Space (model proposes; host executes or rejects):"]
    for item in list(action_space or build_tool_action_space()):
        action_type = str(item.get("action_type", "") or "")
        if not action_type:
            continue
        flags = []
        if item.get("requires_network"):
            flags.append("network")
        if item.get("requires_workspace"):
            flags.append("workspace")
        if not item.get("is_readonly", True):
            flags.append("write")
        flag_text = ",".join(flags) if flags else "readonly"
        required = ",".join(str(x) for x in list(item.get("input_schema", {}).get("required", []) or [])) or "-"
        lines.append(f"- {action_type}: risk={item.get('risk_level', 'low')} flags={flag_text} required={required}; {item.get('description', '')}")
    return "\n".join(lines)
