from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kernel_v4.contracts import JsonObject, LoopEvent, ToolStatus, now_ms

WorkflowEventSink = Callable[[LoopEvent], None]


@dataclass
class AbortSignal:
    aborted: bool = False
    reason: str | None = None
    aborted_at_ms: int | None = None

    def to_dict(self) -> JsonObject:
        return {
            "aborted": self.aborted,
            **({"reason": self.reason} if self.reason else {}),
            **({"aborted_at_ms": self.aborted_at_ms} if self.aborted_at_ms is not None else {}),
        }


class AbortController:
    """Small Python equivalent of the reference loop's AbortController."""

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: str = "cancelled") -> None:
        if self.signal.aborted:
            return
        self.signal.aborted = True
        self.signal.reason = reason
        self.signal.aborted_at_ms = now_ms()


@dataclass(frozen=True, kw_only=True)
class ContextEdit:
    operation: str
    key: str | None = None
    value: Any = None
    source: str = "host"
    at_ms: int = field(default_factory=now_ms)

    def to_dict(self) -> JsonObject:
        return {
            "operation": self.operation,
            "source": self.source,
            "at_ms": self.at_ms,
            **({"key": self.key} if self.key is not None else {}),
            **({"value": self.value} if _json_safe(self.value) else {"value_preview": str(self.value)[:500]}),
        }


@dataclass
class ToolLifecycleRecord:
    tool_call_id: str
    tool: str
    status: ToolStatus
    queued_at_ms: int | None = None
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    yielded_at_ms: int | None = None
    cancelled_at_ms: int | None = None
    error: str | None = None
    artifact_id: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def transition(self, status: ToolStatus, *, metadata: JsonObject | None = None) -> None:
        self.status = status
        at_ms = now_ms()
        if status == "queued":
            self.queued_at_ms = self.queued_at_ms or at_ms
        elif status == "executing":
            self.started_at_ms = self.started_at_ms or at_ms
        elif status in {"completed", "failed"}:
            self.completed_at_ms = at_ms
        elif status == "yielded":
            self.yielded_at_ms = at_ms
        elif status == "cancelled":
            self.cancelled_at_ms = at_ms
            self.completed_at_ms = self.completed_at_ms or at_ms
        if metadata:
            self.metadata.update(metadata)
            if isinstance(metadata.get("error"), str):
                self.error = str(metadata["error"])
            if isinstance(metadata.get("artifact_id"), str):
                self.artifact_id = str(metadata["artifact_id"])

    def to_dict(self) -> JsonObject:
        return {
            "tool_call_id": self.tool_call_id,
            "tool": self.tool,
            "status": self.status,
            **({"queued_at_ms": self.queued_at_ms} if self.queued_at_ms is not None else {}),
            **({"started_at_ms": self.started_at_ms} if self.started_at_ms is not None else {}),
            **({"completed_at_ms": self.completed_at_ms} if self.completed_at_ms is not None else {}),
            **({"yielded_at_ms": self.yielded_at_ms} if self.yielded_at_ms is not None else {}),
            **({"cancelled_at_ms": self.cancelled_at_ms} if self.cancelled_at_ms is not None else {}),
            **({"error": self.error} if self.error else {}),
            **({"artifact_id": self.artifact_id} if self.artifact_id else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }


@dataclass
class WorkflowObserver:
    sink: WorkflowEventSink | None = None
    events: list[LoopEvent] = field(default_factory=list)

    def emit(self, event: LoopEvent) -> None:
        self.events.append(event)
        if self.sink is not None:
            self.sink(event)


def _json_safe(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, list, tuple, dict))
