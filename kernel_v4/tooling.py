from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from kernel_v4.context import ToolUseContext, tool_message_from_result
from kernel_v4.contracts import JsonObject, LoopEvent, ToolCall, ToolManifest, ToolMessage, now_ms

ToolExecutorFn = Callable[[JsonObject, ToolUseContext], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    manifest: ToolManifest
    executor: ToolExecutorFn


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, manifest: ToolManifest, executor: ToolExecutorFn) -> None:
        self._tools[manifest.name] = ToolDefinition(manifest=manifest, executor=executor)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def manifests(self, *, include_deferred: bool = False) -> list[ToolManifest]:
        return [
            tool.manifest
            for tool in self._tools.values()
            if tool.manifest.enabled and (include_deferred or not tool.manifest.should_defer or tool.manifest.always_load)
        ]

    def all_manifests(self) -> list[ToolManifest]:
        return [tool.manifest for tool in self._tools.values() if tool.manifest.enabled]

    def install_core_tools(self) -> None:
        if self.get("tool.discovery") is None:
            self.register(
                ToolManifest(
                    name="tool.discovery",
                    description="Search currently registered tools and return their contracts.",
                    input_schema={
                        "query": {"type": "string", "required": False},
                        "max_results": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=20_000,
                ),
                self._execute_tool_discovery,
            )
        if self.get("artifact.read") is None:
            self.register(
                ToolManifest(
                    name="artifact.read",
                    description="Read a v4 artifact created from a large tool result.",
                    input_schema={
                        "artifact_id": {"type": "string", "required": True},
                        "max_chars": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=50_000,
                ),
                self._execute_artifact_read,
            )

    async def execute(self, call: ToolCall, context: ToolUseContext) -> ToolMessage:
        definition = self.get(call.name)
        if definition is None:
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={"error": "tool_not_found", "tool": call.name},
                context=context,
                is_error=True,
            )
        if not definition.manifest.enabled:
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={"error": "tool_disabled", "tool": call.name},
                context=context,
                is_error=True,
            )
        try:
            result = definition.executor(dict(call.input), context)
            if inspect.isawaitable(result):
                result = await result
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content=result,
                context=context,
                max_inline_chars=definition.manifest.max_result_chars or 10**12,
            )
        except Exception as exc:  # noqa: BLE001 - tool failures are loop observations.
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={
                    "error": "tool_execution_failed",
                    "tool": call.name,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:1000],
                },
                context=context,
                is_error=True,
            )

    def _execute_tool_discovery(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        query = str(payload.get("query") or "").casefold().strip()
        max_results = _positive_int(payload.get("max_results"), default=12, upper=50)
        rows: list[JsonObject] = []
        for manifest in self.all_manifests():
            haystack = " ".join(
                [
                    manifest.name,
                    manifest.description,
                    json.dumps(manifest.input_schema, ensure_ascii=False, sort_keys=True),
                ]
            ).casefold()
            score = 1.0 if not query else _score_manifest(query, haystack, manifest.name)
            if score <= 0:
                continue
            rows.append({"score": score, **manifest.summary()})
        rows.sort(key=lambda item: (-float(item["score"]), str(item["name"])))
        return {
            "schema": "holo.kernel_v4.tool_discovery_result.v1",
            "query": query,
            "tools": rows[:max_results],
            "host_boundary": "tool discovery returns contracts only; the model chooses the next concrete tool call",
        }

    def _execute_artifact_read(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "")
        max_chars = _positive_int(payload.get("max_chars"), default=20_000, upper=200_000)
        content = context.read_artifact(artifact_id)
        return {
            "schema": "holo.kernel_v4.artifact_read_result.v1",
            "artifact_id": artifact_id,
            "chars": len(content),
            "text": content[:max_chars],
            "truncated": len(content) > max_chars,
        }


class StreamingToolExecutor:
    """Executes streamed tool calls with reference-style concurrency rules."""

    def __init__(self, registry: ToolRegistry, context: ToolUseContext, *, turn_index: int) -> None:
        self.registry = registry
        self.context = context
        self.turn_index = turn_index
        self._items: list[_TrackedTool] = []
        self._events: list[LoopEvent] = []

    def add_tool_call(self, call: ToolCall) -> None:
        definition = self.registry.get(call.name)
        concurrency_safe = True if definition is None else bool(definition.manifest.concurrency_safe)
        item = _TrackedTool(call=call, concurrency_safe=concurrency_safe)
        self._items.append(item)
        self._events.append(
            LoopEvent(
                event_type="tool_queued",
                turn_index=self.turn_index,
                data={"tool_call_id": call.tool_call_id, "tool": call.name, "concurrency_safe": concurrency_safe},
            )
        )

    async def drain_completed(self) -> list[ToolMessage]:
        await self._start_ready()
        completed: list[ToolMessage] = []
        for item in self._items:
            if item.status != "completed" or item.result is None:
                continue
            item.status = "yielded"
            completed.append(item.result)
            self.context.in_progress_tool_use_ids.discard(item.call.tool_call_id)
            self._events.append(
                LoopEvent(
                    event_type="tool_result",
                    turn_index=self.turn_index,
                    data={
                        "tool_call_id": item.call.tool_call_id,
                        "tool": item.call.name,
                        "is_error": item.result.is_error,
                        **({"artifact_id": item.result.artifact_id} if item.result.artifact_id else {}),
                    },
                )
            )
        return completed

    async def drain_remaining(self) -> list[ToolMessage]:
        results: list[ToolMessage] = []
        while any(item.status != "yielded" for item in self._items):
            await self._start_ready()
            pending = [item.task for item in self._items if item.task is not None and item.status == "executing"]
            if pending:
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            results.extend(await self.drain_completed())
            if not pending and not any(item.status == "queued" for item in self._items):
                break
        return results

    def pop_events(self) -> list[LoopEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    async def _start_ready(self) -> None:
        for item in self._items:
            if item.status != "queued":
                continue
            if not self._can_start(item):
                if not item.concurrency_safe:
                    break
                continue
            item.status = "executing"
            self.context.in_progress_tool_use_ids.add(item.call.tool_call_id)
            self._events.append(
                LoopEvent(
                    event_type="tool_start",
                    turn_index=self.turn_index,
                    data={"tool_call_id": item.call.tool_call_id, "tool": item.call.name},
                )
            )
            item.task = asyncio.create_task(self._execute_item(item))

    def _can_start(self, item: "_TrackedTool") -> bool:
        executing = [other for other in self._items if other.status == "executing"]
        if not executing:
            return True
        return item.concurrency_safe and all(other.concurrency_safe for other in executing)

    async def _execute_item(self, item: "_TrackedTool") -> None:
        item.result = await self.registry.execute(item.call, self.context)
        item.status = "completed"


@dataclass
class _TrackedTool:
    call: ToolCall
    concurrency_safe: bool
    status: str = "queued"
    task: asyncio.Task[None] | None = None
    result: ToolMessage | None = None


def _positive_int(value: object, *, default: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, upper))


def _score_manifest(query: str, haystack: str, name: str) -> float:
    terms = [term for term in query.replace(".", " ").replace("_", " ").split() if term]
    if not terms:
        return 1.0
    hits = sum(1 for term in terms if term in haystack)
    exact = 2 if query in name.casefold() else 0
    return float(hits + exact)
