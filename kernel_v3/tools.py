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

    def register(self, name: str, executor: ToolExecutor) -> None:
        self._tools[name] = ToolSpec(name=name, executor=executor)

    def execute(self, action: CandidateAction) -> Observation:
        tool_name = "__respond__" if action.kind == "respond" else action.name
        if tool_name is None or tool_name not in self._tools:
            raise ValueError(f"unregistered tool: {tool_name}")
        self.executed_actions.append(action)
        return self._tools[tool_name].executor(action)


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
