from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .schema import Event, Observation


HookFn = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class HookManager:
    hooks: dict[str, list[HookFn]] = field(default_factory=dict)

    def register(self, name: str, fn: HookFn) -> None:
        self.hooks.setdefault(name, []).append(fn)

    def emit(self, name: str, **payload: Any) -> None:
        for fn in list(self.hooks.get(name, [])):
            fn(dict(payload))


def event_to_hook_payload(event: Event) -> dict[str, Any]:
    return {"event": event.to_dict()}


def observation_to_hook_payload(observation: Observation) -> dict[str, Any]:
    return {"observation": observation.to_dict()}

