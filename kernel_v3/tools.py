from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kernel_v3.contracts import CandidateAction, Observation


ToolExecutor = Callable[[CandidateAction], Observation]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    executor: ToolExecutor


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.executed_actions: list[CandidateAction] = []

    @classmethod
    def with_builtin_respond(cls) -> "ToolRegistry":
        registry = cls()
        registry.register("__respond__", _execute_respond)
        return registry

    @classmethod
    def with_fake_workspace_tools(cls, *, files: dict[str, str] | None = None) -> "ToolRegistry":
        registry = cls.with_builtin_respond()
        fake_files = dict(files or {})
        registry.register("__ask_user__", _execute_ask_user)
        registry.register("workspace.search", _fake_workspace_search(fake_files))
        registry.register("file.read", _fake_file_read(fake_files))
        registry.register("blocked_external_write", _fake_blocked_external_write)
        return registry

    def register(self, name: str, executor: ToolExecutor) -> None:
        self._tools[name] = ToolSpec(name=name, executor=executor)

    def execute(self, action: CandidateAction) -> Observation:
        tool_name = _tool_name_for_action(action)
        if tool_name is None or tool_name not in self._tools:
            raise ValueError(f"unregistered tool: {tool_name}")
        self.executed_actions.append(action)
        return self._tools[tool_name].executor(action)


def _tool_name_for_action(action: CandidateAction) -> str | None:
    if action.kind == "respond":
        return "__respond__"
    if action.kind == "ask_user":
        return "__ask_user__"
    return action.name


def _execute_respond(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="respond_result",
        status="ok",
        source="respond",
        content={"text": action.payload.get("text", "")},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _execute_ask_user(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="ask_user",
        status="needs_user_input",
        source="ask_user",
        content={"question": action.payload.get("question", "")},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _fake_workspace_search(files: dict[str, str]) -> ToolExecutor:
    def execute(action: CandidateAction) -> Observation:
        query = str(action.payload.get("query", ""))
        matches = [
            {"path": path, "text": text}
            for path, text in files.items()
            if query.lower() in text.lower() or query.lower() in path.lower()
        ]
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"matches": matches},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _fake_file_read(files: dict[str, str]) -> ToolExecutor:
    def execute(action: CandidateAction) -> Observation:
        path = str(action.payload.get("path", ""))
        if path not in files:
            return Observation(
                observation_id=f"obs-{action.action_id}",
                run_id="",
                kind="tool_result",
                status="failed",
                source=f"tool:{action.name}",
                content={"path": path, "error": "file_not_found"},
                observed_at_ms=0,
                action_id=action.action_id,
                tool_call_id=None,
            )
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="tool_result",
            status="ok",
            source=f"tool:{action.name}",
            content={"path": path, "text": files[path]},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


def _fake_blocked_external_write(action: CandidateAction) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="tool_result",
        status="blocked",
        source=f"tool:{action.name}",
        content={"reason": "external_write_blocked_in_fake_tool"},
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )
