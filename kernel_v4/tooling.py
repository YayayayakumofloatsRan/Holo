from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from kernel_v4.context import ToolUseContext, tool_message_from_result
from kernel_v4.contracts import JsonObject, LoopEvent, ToolCall, ToolManifest, ToolMessage, now_ms
from kernel_v4.runtime import ContextEdit

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

    def manifests(self, *, include_deferred: bool = False, include_names: set[str] | None = None) -> list[ToolManifest]:
        include_names = include_names or set()
        manifests: list[ToolManifest] = []
        for tool in self._tools.values():
            manifest = tool.manifest
            if not manifest.enabled:
                continue
            if include_deferred or not manifest.should_defer or manifest.always_load:
                manifests.append(manifest)
                continue
            if manifest.name in include_names:
                manifests.append(replace(manifest, should_defer=False, always_load=True))
        return manifests

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
        if context.abort_signal.aborted:
            return _cancelled_tool_message(call, context, reason=context.abort_signal.reason or "cancelled")
        duplicate = _find_previous_successful_tool_call(call, context)
        if duplicate is not None:
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={
                    "schema": "holo.kernel_v4.duplicate_successful_tool_call.v1",
                    "tool": call.name,
                    "status": "skipped_duplicate_successful_call",
                    "previous_tool_call_id": duplicate["previous_tool_call_id"],
                    "previous_result_preview": duplicate["previous_result_preview"],
                    "instruction": (
                        "This same tool input already succeeded earlier in the conversation. "
                        "Use the previous tool result and continue to the next evidence, transform, verification, or final answer step."
                    ),
                },
                context=context,
                is_error=True,
                metadata={"duplicate_successful_tool_call": True, "previous_tool_call_id": duplicate["previous_tool_call_id"]},
            )
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
            is_error = _result_indicates_tool_error(result)
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content=result,
                context=context,
                is_error=is_error,
                max_inline_chars=definition.manifest.max_result_chars or 10**12,
                metadata=({"tool_status": str(result.get("status"))} if isinstance(result, dict) and "status" in result else None),
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
        selected = rows[:max_results]
        discovered = set(_string_list(context.metadata.get("discovered_tool_names")))
        discovered.update(str(row["name"]) for row in selected if isinstance(row.get("name"), str))
        context.apply_edit(
            ContextEdit(
                operation="metadata.set",
                key="discovered_tool_names",
                value=sorted(discovered),
                source="tool.discovery",
            )
        )
        return {
            "schema": "holo.kernel_v4.tool_discovery_result.v1",
            "query": query,
            "tools": selected,
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
        self.context.record_tool_lifecycle(
            tool_call_id=call.tool_call_id,
            tool=call.name,
            status="queued",
            turn_index=self.turn_index,
            metadata={"concurrency_safe": concurrency_safe},
        )
        self._emit(
            event_type="tool_queued",
            data={"tool_call_id": call.tool_call_id, "tool": call.name, "concurrency_safe": concurrency_safe},
        )

    async def drain_completed(self) -> list[ToolMessage]:
        await self._start_ready()
        completed: list[ToolMessage] = []
        for item in self._items:
            if item.status not in {"completed", "cancelled", "failed"} or item.result is None:
                continue
            item.status = "yielded"
            completed.append(item.result)
            self.context.in_progress_tool_use_ids.discard(item.call.tool_call_id)
            self.context.record_tool_lifecycle(
                tool_call_id=item.call.tool_call_id,
                tool=item.call.name,
                status="yielded",
                turn_index=self.turn_index,
                metadata={
                    "is_error": item.result.is_error,
                    **({"artifact_id": item.result.artifact_id} if item.result.artifact_id else {}),
                },
            )
            self._emit(
                event_type="tool_result",
                data={
                    "tool_call_id": item.call.tool_call_id,
                    "tool": item.call.name,
                    "is_error": item.result.is_error,
                    **({"artifact_id": item.result.artifact_id} if item.result.artifact_id else {}),
                },
            )
        return completed

    async def drain_remaining(self) -> list[ToolMessage]:
        results: list[ToolMessage] = []
        while any(item.status != "yielded" for item in self._items):
            if self.context.abort_signal.aborted:
                await self.cancel_remaining(reason=self.context.abort_signal.reason or "cancelled")
            await self._start_ready()
            if self.context.abort_signal.aborted:
                await self.cancel_remaining(reason=self.context.abort_signal.reason or "cancelled")
            pending = [item.task for item in self._items if item.task is not None and item.status == "executing"]
            if pending:
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            results.extend(await self.drain_completed())
            if not pending and not any(item.status == "queued" for item in self._items):
                break
        return results

    async def cancel_remaining(self, *, reason: str) -> None:
        pending_tasks: list[asyncio.Task[None]] = []
        for item in self._items:
            if item.status in {"completed", "yielded", "cancelled", "failed"}:
                continue
            if item.task is not None and not item.task.done():
                item.task.cancel()
                pending_tasks.append(item.task)
            item.result = _cancelled_tool_message(item.call, self.context, reason=reason)
            item.status = "cancelled"
            self.context.in_progress_tool_use_ids.discard(item.call.tool_call_id)
            self.context.record_tool_lifecycle(
                tool_call_id=item.call.tool_call_id,
                tool=item.call.name,
                status="cancelled",
                turn_index=self.turn_index,
                metadata={"reason": reason},
            )
            self._emit(
                event_type="tool_cancelled",
                data={"tool_call_id": item.call.tool_call_id, "tool": item.call.name, "reason": reason},
            )
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    def pop_events(self) -> list[LoopEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    async def _start_ready(self) -> None:
        for item in self._items:
            if item.status != "queued":
                continue
            if self.context.abort_signal.aborted:
                await self.cancel_remaining(reason=self.context.abort_signal.reason or "cancelled")
                return
            if not self._can_start(item):
                if not item.concurrency_safe:
                    break
                continue
            item.status = "executing"
            self.context.in_progress_tool_use_ids.add(item.call.tool_call_id)
            self.context.record_tool_lifecycle(
                tool_call_id=item.call.tool_call_id,
                tool=item.call.name,
                status="executing",
                turn_index=self.turn_index,
            )
            self._emit(
                event_type="tool_start",
                data={"tool_call_id": item.call.tool_call_id, "tool": item.call.name},
            )
            item.task = asyncio.create_task(self._execute_item(item))

    def _emit(self, *, event_type: str, data: JsonObject) -> None:
        event = LoopEvent(event_type=event_type, turn_index=self.turn_index, data=data)
        self._events.append(event)
        self.context.emit_workflow(event)

    def _can_start(self, item: "_TrackedTool") -> bool:
        executing = [other for other in self._items if other.status == "executing"]
        if not executing:
            return True
        return item.concurrency_safe and all(other.concurrency_safe for other in executing)

    async def _execute_item(self, item: "_TrackedTool") -> None:
        try:
            item.result = await self.registry.execute(item.call, self.context)
        except asyncio.CancelledError:
            item.result = _cancelled_tool_message(
                item.call,
                self.context,
                reason=self.context.abort_signal.reason or "cancelled",
            )
            item.status = "cancelled"
            self.context.record_tool_lifecycle(
                tool_call_id=item.call.tool_call_id,
                tool=item.call.name,
                status="cancelled",
                turn_index=self.turn_index,
                metadata={"reason": self.context.abort_signal.reason or "cancelled"},
            )
            return
        item.status = "failed" if item.result.is_error else "completed"
        self.context.record_tool_lifecycle(
            tool_call_id=item.call.tool_call_id,
            tool=item.call.name,
            status=item.status,
            turn_index=self.turn_index,
            metadata={
                "is_error": item.result.is_error,
                **({"artifact_id": item.result.artifact_id} if item.result.artifact_id else {}),
            },
        )


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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _find_previous_successful_tool_call(call: ToolCall, context: ToolUseContext) -> JsonObject | None:
    target_input = _stable_json(call.input)
    previous_calls: dict[str, ToolCall] = {}
    for message in context.messages:
        if message.role == "assistant":
            for previous in message.tool_calls:
                previous_calls[previous.tool_call_id] = previous
            continue
        if message.role != "tool" or not message.tool_call_id:
            continue
        previous = previous_calls.get(message.tool_call_id)
        if previous is None:
            continue
        if previous.name != call.name or _stable_json(previous.input) != target_input:
            continue
        if message.metadata.get("is_error"):
            continue
        return {
            "previous_tool_call_id": previous.tool_call_id,
            "previous_result_preview": message.content[:2000],
        }
    return None


def _result_indicates_tool_error(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    if "error" in result:
        return True
    status = _status_text(result.get("status"))
    if _is_error_status(status):
        return True
    content = result.get("content")
    if isinstance(content, dict):
        if "error" in content:
            return True
        if _is_error_status(_status_text(content.get("status"))):
            return True
    return False


def _status_text(value: object) -> str:
    return str(value or "").casefold().strip()


def _is_error_status(status: str) -> bool:
    if not status:
        return False
    return status in {
        "blocked",
        "error",
        "errored",
        "failed",
        "failure",
        "cancelled",
        "canceled",
        "timeout",
        "timed_out",
        "invalid",
        "denied",
        "rejected",
        "unavailable",
        "missing_required_field",
    }


def _cancelled_tool_message(call: ToolCall, context: ToolUseContext, *, reason: str) -> ToolMessage:
    return tool_message_from_result(
        tool_call_id=call.tool_call_id,
        name=call.name,
        content={
            "schema": "holo.kernel_v4.tool_cancelled.v1",
            "tool": call.name,
            "reason": reason,
        },
        context=context,
        is_error=True,
        metadata={"cancelled": True, "reason": reason},
    )


def _score_manifest(query: str, haystack: str, name: str) -> float:
    terms = [term for term in query.replace(".", " ").replace("_", " ").split() if term]
    if not terms:
        return 1.0
    hits = sum(1 for term in terms if term in haystack)
    exact = 2 if query in name.casefold() else 0
    return float(hits + exact)


def _stable_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)
