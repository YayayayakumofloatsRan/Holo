from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

JsonObject = dict[str, Any]
JsonValue = Any

MessageRole = Literal["system", "user", "assistant", "tool"]
ModelEventType = Literal["text_delta", "tool_call", "message_stop"]
ToolStatus = Literal["queued", "executing", "completed", "yielded"]
LoopStatus = Literal["completed", "failed", "blocked"]


def now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass(frozen=True, kw_only=True)
class ToolCall:
    tool_call_id: str
    name: str
    input: JsonObject


@dataclass(frozen=True, kw_only=True)
class ToolManifest:
    name: str
    description: str
    input_schema: JsonObject = field(default_factory=dict)
    side_effect_class: str = "read"
    concurrency_safe: bool = True
    enabled: bool = True
    should_defer: bool = False
    always_load: bool = False
    timeout_seconds: int | None = None
    max_result_chars: int | None = 50_000

    def summary(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "side_effect_class": self.side_effect_class,
            "concurrency_safe": self.concurrency_safe,
            "enabled": self.enabled,
            "should_defer": self.should_defer,
            "always_load": self.always_load,
            "timeout_seconds": self.timeout_seconds,
            "max_result_chars": self.max_result_chars,
        }


@dataclass(frozen=True, kw_only=True)
class ChatMessage:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "role": self.role,
            "content": self.content,
            **({"name": self.name} if self.name else {}),
            **({"tool_call_id": self.tool_call_id} if self.tool_call_id else {}),
            **({"tool_calls": [call.__dict__ for call in self.tool_calls]} if self.tool_calls else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }


@dataclass(frozen=True, kw_only=True)
class AssistantMessage:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

    def as_chat_message(self) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            content=self.content,
            tool_calls=self.tool_calls,
            metadata=self.metadata,
        )


@dataclass(frozen=True, kw_only=True)
class ToolMessage:
    tool_call_id: str
    name: str
    content: JsonValue
    is_error: bool = False
    artifact_id: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def as_chat_message(self) -> ChatMessage:
        return ChatMessage(
            role="tool",
            name=self.name,
            tool_call_id=self.tool_call_id,
            content=stringify_tool_content(self.content),
            metadata={
                **self.metadata,
                **({"is_error": True} if self.is_error else {}),
                **({"artifact_id": self.artifact_id} if self.artifact_id else {}),
            },
        )


@dataclass(frozen=True, kw_only=True)
class ModelEvent:
    event_type: ModelEventType
    text: str = ""
    tool_call: ToolCall | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class LoopEvent:
    event_type: str
    turn_index: int
    data: JsonObject
    at_ms: int = field(default_factory=now_ms)


@dataclass(frozen=True, kw_only=True)
class LoopResult:
    status: LoopStatus
    answer: str
    messages: tuple[ChatMessage, ...]
    events: tuple[LoopEvent, ...]
    reason: str | None = None
    tool_call_count: int = 0
    turn_count: int = 0


class ModelClient(Protocol):
    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolManifest],
        system_prompt: str,
        context: JsonObject,
    ):
        """Yield ModelEvent objects for one assistant turn."""


def stringify_tool_content(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)
