from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from kernel_v4.context import ToolUseContext, tool_message_from_result
from kernel_v4.contracts import JsonObject, LoopEvent, ToolCall, ToolManifest, ToolMessage, now_ms
from kernel_v4.runtime import ContextEdit

ToolExecutorFn = Callable[[JsonObject, ToolUseContext], Any | Awaitable[Any]]
_NATIVE_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NATIVE_TOOL_NAME_CHARS = 64


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
        if self.get("tool.workbench") is None:
            self.register(
                ToolManifest(
                    name="tool.workbench",
                    description=(
                        "Open a temporary task workbench: discover relevant registered tools, group them by capability, "
                        "and return tool contracts plus current artifact context. This plans tool access only; it does not answer."
                    ),
                    input_schema={
                        "query": {"type": "string", "required": False},
                        "families": {
                            "type": "string",
                            "required": False,
                            "description": "Optional comma-separated tool families to emphasize.",
                        },
                        "max_tools": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=30_000,
                ),
                self._execute_tool_workbench,
            )
        if self.get("artifact.read") is None:
            self.register(
                ToolManifest(
                    name="artifact.read",
                    description="Read a v4 artifact created from a large tool result.",
                    input_schema={
                        "artifact_id": {"type": "string", "required": True},
                        "start": {"type": "integer", "required": False},
                        "max_chars": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=50_000,
                ),
                self._execute_artifact_read,
            )
        if self.get("artifact.inspect") is None:
            self.register(
                ToolManifest(
                    name="artifact.inspect",
                    description="Inspect v4 artifact metadata, previews, sizes, lifecycle counters, and recent artifacts.",
                    input_schema={
                        "artifact_id": {"type": "string", "required": False},
                        "max_items": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=20_000,
                ),
                self._execute_artifact_inspect,
            )
        if self.get("artifact.search") is None:
            self.register(
                ToolManifest(
                    name="artifact.search",
                    description="Search v4 artifacts by text query and return compact snippets before deciding whether to read.",
                    input_schema={
                        "query": {"type": "string", "required": True},
                        "artifact_id": {"type": "string", "required": False},
                        "max_matches": {"type": "integer", "required": False},
                        "window_chars": {"type": "integer", "required": False},
                    },
                    concurrency_safe=True,
                    always_load=True,
                    max_result_chars=30_000,
                ),
                self._execute_artifact_search,
            )

    async def execute(self, call: ToolCall, context: ToolUseContext) -> ToolMessage:
        if context.abort_signal.aborted:
            return _cancelled_tool_message(call, context, reason=context.abort_signal.reason or "cancelled")
        requested_tool_name = call.name
        canonical_tool_name = _canonical_registered_tool_name(call.name, self._tools.keys())
        if canonical_tool_name != call.name:
            call = ToolCall(tool_call_id=call.tool_call_id, name=canonical_tool_name, input=call.input)
        active_allowlist = _active_tool_surface_allowlist(context)
        if active_allowlist is not None and call.name not in active_allowlist:
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={
                    "error": "tool_not_in_active_surface",
                    "tool": call.name,
                    **({"requested_tool": requested_tool_name} if requested_tool_name != call.name else {}),
                    "active_tool_surface_allowlist": sorted(active_allowlist),
                    "instruction": (
                        "This tool is registered or historically visible, but it is not executable in the current "
                        "tool surface. Use only one of the exact active tool names, use existing observations, "
                        "or finalize if the evidence and calculations are sufficient. Do not call hidden, "
                        "sanitized, or previously visible source-tool aliases."
                    ),
                },
                context=context,
                is_error=True,
                metadata={"tool_not_in_active_surface": True},
            )
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
            active_allowlist = _active_tool_surface_allowlist(context)
            return tool_message_from_result(
                tool_call_id=call.tool_call_id,
                name=call.name,
                content={
                    "error": "tool_not_found",
                    "tool": call.name,
                    **({"requested_tool": requested_tool_name} if requested_tool_name != call.name else {}),
                    "active_tool_surface_allowlist": sorted(active_allowlist) if active_allowlist is not None else None,
                    "instruction": (
                        "This tool is not currently executable. If active_tool_surface_allowlist is present, use only "
                        "one of those exact tool names, or finalize from existing observations. Do not call hidden, "
                        "sanitized, or previously visible source-tool aliases."
                    ),
                },
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
        active_allowlist = _active_tool_surface_allowlist(context)
        for manifest in self.all_manifests():
            if active_allowlist is not None and manifest.name not in active_allowlist:
                continue
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
            "active_tool_surface_allowlist": sorted(active_allowlist) if active_allowlist is not None else None,
            "host_boundary": "tool discovery returns contracts only; the model chooses the next concrete tool call",
        }

    def _execute_artifact_read(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "")
        max_chars = _positive_int(payload.get("max_chars"), default=8_000, upper=200_000)
        start = _non_negative_int(payload.get("start"), default=0, upper=10**9)
        content = context.read_artifact(artifact_id)
        end = min(len(content), start + max_chars)
        return {
            "schema": "holo.kernel_v4.artifact_read_result.v1",
            "artifact_id": artifact_id,
            "chars": len(content),
            "start": start,
            "end": end,
            "text": content[start:end],
            "truncated": end < len(content),
            "instruction": (
                "This is a bounded window. Use artifact.search for targeted snippets, or call artifact.read "
                "again with start/end-focused max_chars if broader context is necessary."
            ),
        }

    def _execute_artifact_inspect(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "").strip() or None
        max_items = _positive_int(payload.get("max_items"), default=20, upper=100)
        artifacts = context.artifact_summary(artifact_id=artifact_id, recent_limit=max_items)
        v3_artifacts = _v3_artifact_summaries(context, artifact_id=artifact_id, max_items=max_items)
        if artifact_id and not artifacts and not v3_artifacts:
            return {"error": "artifact_not_found", "artifact_id": artifact_id}
        return {
            "schema": "holo.kernel_v4.artifact_inspect_result.v1",
            "artifact_id": artifact_id,
            "kernel_v4_artifacts": artifacts,
            "delegated_artifacts": v3_artifacts,
            "artifact_count": len(context.artifacts) + len(_v3_artifact_summaries(context, max_items=10_000)),
            "host_boundary": "artifact inspection returns lifecycle metadata only; the model chooses search/read/next tool calls.",
        }

    def _execute_artifact_search(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        query = str(payload.get("query") or "").strip()
        artifact_id = str(payload.get("artifact_id") or "").strip() or None
        max_matches = _positive_int(payload.get("max_matches"), default=8, upper=50)
        window_chars = _positive_int(payload.get("window_chars"), default=240, upper=2_000)
        if not query:
            return {"error": "missing_query", "required": "query"}
        candidates = _v4_artifact_candidates(context, artifact_id=artifact_id)
        matches: list[JsonObject] = []
        for candidate_id, content in candidates:
            matches.extend(
                _search_text(
                    artifact_id=candidate_id,
                    source="kernel_v4_context",
                    text=content,
                    query=query,
                    max_matches=max_matches,
                    window_chars=window_chars,
                )
            )
        matches.sort(key=lambda item: (str(item["artifact_id"]), int(item["offset"])))
        return {
            "schema": "holo.kernel_v4.artifact_search_result.v1",
            "query": query,
            "artifact_id": artifact_id,
            "matches": matches[:max_matches],
            "searched_artifacts": len(candidates),
            "host_boundary": "artifact search returns snippets only; call artifact.read for broader context if needed.",
        }

    def _execute_tool_workbench(self, payload: JsonObject, context: ToolUseContext) -> JsonObject:
        query = str(payload.get("query") or "").casefold().strip()
        requested_families = set(_payload_string_list(payload.get("families")))
        max_tools = _positive_int(payload.get("max_tools"), default=24, upper=80)
        rows: list[JsonObject] = []
        families: dict[str, JsonObject] = {}
        active_allowlist = _active_tool_surface_allowlist(context)
        for manifest in self.all_manifests():
            if active_allowlist is not None and manifest.name not in active_allowlist:
                continue
            family = _tool_family(manifest)
            haystack = " ".join(
                [
                    family,
                    manifest.name,
                    manifest.description,
                    json.dumps(manifest.input_schema, ensure_ascii=False, sort_keys=True),
                ]
            ).casefold()
            score = 1.0 if not query else _score_manifest(query, haystack, manifest.name)
            if requested_families and family not in requested_families:
                score *= 0.25
            if score <= 0 and requested_families and family in requested_families:
                score = 0.5
            if score <= 0:
                continue
            summary = manifest.summary()
            summary["family"] = family
            summary["score"] = score
            rows.append(summary)
            families.setdefault(
                family,
                {
                    "family": family,
                    "purpose": _tool_family_purpose(family),
                    "workflow_hint": _tool_family_workflow_hint(family),
                    "tools": [],
                },
            )
        rows.sort(key=lambda item: (-float(item["score"]), str(item["family"]), str(item["name"])))
        selected = rows[:max_tools]
        selected_names = {str(item["name"]) for item in selected if isinstance(item.get("name"), str)}
        for item in selected:
            families[str(item["family"])]["tools"].append(item)
        discovered = set(_string_list(context.metadata.get("discovered_tool_names")))
        discovered.update(selected_names)
        context.apply_edit(
            ContextEdit(
                operation="metadata.set",
                key="discovered_tool_names",
                value=sorted(discovered),
                source="tool.workbench",
            )
        )
        selected_families = [
            value for value in families.values() if any(tool["name"] in selected_names for tool in value["tools"])
        ]
        return {
            "schema": "holo.kernel_v4.tool_workbench.v1",
            "query": query,
            "requested_families": sorted(requested_families),
            "selected_tools": selected,
            "selected_families": selected_families,
            "current_artifacts": context.artifact_summary(recent_limit=10),
            "active_tool_surface_allowlist": sorted(active_allowlist) if active_allowlist is not None else None,
            "host_boundary": (
                "Workbench assembly exposes tool contracts and context only. The model still decides which tools to call, "
                "what evidence is sufficient, and when to finalize."
            ),
        }


class StreamingToolExecutor:
    """Executes streamed tool calls with reference-style concurrency rules."""

    def __init__(self, registry: ToolRegistry, context: ToolUseContext, *, turn_index: int) -> None:
        self.registry = registry
        self.context = context
        self.turn_index = turn_index
        self._items: list[_TrackedTool] = []
        self._events: list[LoopEvent] = []
        self._in_turn_fingerprints: dict[str, str] = {}

    def add_tool_call(self, call: ToolCall) -> None:
        definition = self.registry.get(call.name)
        concurrency_safe = True if definition is None else bool(definition.manifest.concurrency_safe)
        fingerprint = _tool_call_fingerprint(call)
        duplicate_of = self._in_turn_fingerprints.get(fingerprint)
        if duplicate_of is None:
            self._in_turn_fingerprints[fingerprint] = call.tool_call_id
        item = _TrackedTool(call=call, concurrency_safe=concurrency_safe, duplicate_of=duplicate_of)
        self._items.append(item)
        self.context.record_tool_lifecycle(
            tool_call_id=call.tool_call_id,
            tool=call.name,
            status="queued",
            turn_index=self.turn_index,
            metadata={"concurrency_safe": concurrency_safe, **({"duplicate_of": duplicate_of} if duplicate_of else {})},
        )
        self._emit(
            event_type="tool_queued",
            data={
                "tool_call_id": call.tool_call_id,
                "tool": call.name,
                "concurrency_safe": concurrency_safe,
                **({"duplicate_of": duplicate_of} if duplicate_of else {}),
            },
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
            if await self._complete_in_turn_duplicate(item):
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

    async def _complete_in_turn_duplicate(self, item: "_TrackedTool") -> bool:
        if not item.duplicate_of:
            return False
        previous = self._find_item(item.duplicate_of)
        if previous is None:
            return False
        if previous.status in {"queued", "executing"}:
            return True
        if previous.result is None:
            return False
        item.result = tool_message_from_result(
            tool_call_id=item.call.tool_call_id,
            name=item.call.name,
            content={
                "schema": "holo.kernel_v4.in_turn_duplicate_tool_call.v1",
                "tool": item.call.name,
                "status": "skipped_in_turn_duplicate_tool_call",
                "previous_tool_call_id": previous.call.tool_call_id,
                "previous_result_was_error": previous.result.is_error,
                "previous_result_preview": _preview_tool_result(previous.result),
                "instruction": (
                    "This same tool input was already requested earlier in this assistant turn. "
                    "Use the earlier tool result and continue to the next evidence, transform, verification, or final answer step."
                ),
            },
            context=self.context,
            is_error=True,
            metadata={
                "in_turn_duplicate_tool_call": True,
                "previous_tool_call_id": previous.call.tool_call_id,
                "previous_result_was_error": previous.result.is_error,
            },
        )
        item.status = "failed"
        self.context.record_tool_lifecycle(
            tool_call_id=item.call.tool_call_id,
            tool=item.call.name,
            status="failed",
            turn_index=self.turn_index,
            metadata={
                "is_error": True,
                "in_turn_duplicate_tool_call": True,
                "previous_tool_call_id": previous.call.tool_call_id,
            },
        )
        self._emit(
            event_type="tool_duplicate_skipped",
            data={
                "tool_call_id": item.call.tool_call_id,
                "tool": item.call.name,
                "previous_tool_call_id": previous.call.tool_call_id,
            },
        )
        return True

    def _find_item(self, tool_call_id: str) -> "_TrackedTool | None":
        for item in self._items:
            if item.call.tool_call_id == tool_call_id:
                return item
        return None


@dataclass
class _TrackedTool:
    call: ToolCall
    concurrency_safe: bool
    duplicate_of: str | None = None
    status: str = "queued"
    task: asyncio.Task[None] | None = None
    result: ToolMessage | None = None


def _non_negative_int(value: object, *, default: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(parsed, upper))


def _positive_int(value: object, *, default: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, upper))


def _payload_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.casefold().strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).casefold().strip() for item in value if str(item).strip()]
    return []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _active_tool_surface_allowlist(context: ToolUseContext) -> set[str] | None:
    raw = context.metadata.get("tool_surface_allowlist")
    if not isinstance(raw, list):
        return None
    names = {str(item) for item in raw if isinstance(item, str) and item}
    return names or None


def _canonical_registered_tool_name(tool_name: str, registered_names: Any) -> str:
    requested = str(tool_name or "").strip()
    if not requested:
        return requested
    registered = {str(name) for name in registered_names}
    if requested in registered:
        return requested
    alias_map: dict[str, str | None] = {}
    for real_name in registered:
        for alias in {_native_tool_alias(real_name), _native_tool_name(real_name)}:
            existing = alias_map.get(alias)
            if existing is None and alias not in alias_map:
                alias_map[alias] = real_name
            elif existing != real_name:
                alias_map[alias] = None
    mapped = alias_map.get(requested)
    return mapped or requested


def _native_tool_name(tool_name: str) -> str:
    digest = hashlib.sha256(str(tool_name or "").encode("utf-8")).hexdigest()[:8]
    slug = _native_tool_alias(tool_name)
    needs_hash = slug != tool_name or len(slug) > _MAX_NATIVE_TOOL_NAME_CHARS
    if not needs_hash:
        return slug
    suffix = "_" + digest
    max_base = max(1, _MAX_NATIVE_TOOL_NAME_CHARS - len(suffix))
    return (slug[:max_base].rstrip("_") or "tool") + suffix


def _native_tool_alias(tool_name: str) -> str:
    slug = _NATIVE_TOOL_NAME_RE.sub("_", str(tool_name or "")).strip("_")
    return re.sub(r"_+", "_", slug) or "tool"


def _v4_artifact_candidates(context: ToolUseContext, *, artifact_id: str | None) -> list[tuple[str, str]]:
    if artifact_id:
        if artifact_id not in context.artifacts:
            return []
        return [(artifact_id, context.read_artifact(artifact_id))]
    return [(candidate_id, context.read_artifact(candidate_id)) for candidate_id in sorted(context.artifacts)]


def _v3_artifact_summaries(
    context: ToolUseContext,
    *,
    artifact_id: str | None = None,
    max_items: int = 20,
) -> list[JsonObject]:
    raw = context.metadata.get("v3_artifacts")
    if not isinstance(raw, dict):
        return []
    rows: list[JsonObject] = []
    for key, value in raw.items():
        if artifact_id and str(key) != artifact_id:
            continue
        if isinstance(value, dict):
            row = dict(value)
        else:
            row = {"artifact_id": str(key), "metadata": value}
        row.setdefault("artifact_id", str(key))
        row.setdefault("source", "delegated_finance_artifact_store")
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("artifact_id")))
    return rows[: max(1, max_items)]


def _search_text(
    *,
    artifact_id: str,
    source: str,
    text: str,
    query: str,
    max_matches: int,
    window_chars: int,
) -> list[JsonObject]:
    haystack = text.casefold()
    terms = _query_terms(query)
    if not terms:
        return []
    offsets: list[int] = []
    for term in terms:
        start = 0
        while len(offsets) < max_matches:
            index = haystack.find(term, start)
            if index < 0:
                break
            offsets.append(index)
            start = index + max(1, len(term))
    offsets = sorted(set(offsets))[:max_matches]
    matches: list[JsonObject] = []
    for offset in offsets:
        start = max(0, offset - window_chars // 2)
        end = min(len(text), offset + window_chars // 2)
        matches.append(
            {
                "artifact_id": artifact_id,
                "source": source,
                "offset": offset,
                "start": start,
                "end": end,
                "snippet": " ".join(text[start:end].split()),
            }
        )
    return matches


def _query_terms(query: str) -> list[str]:
    return [term for term in query.casefold().replace("/", " ").replace("_", " ").split() if len(term) >= 2]


def _tool_family(manifest: ToolManifest) -> str:
    name = manifest.name.casefold()
    description = manifest.description.casefold()
    if name.startswith("artifact."):
        return "artifact_context"
    if name.startswith("tool."):
        return "tool_discovery"
    if name.startswith("sec.edgar") or name.startswith("document.") or name.startswith("provided_context."):
        return "evidence_retrieval"
    if name.startswith("market."):
        return "market_data"
    if name.startswith("calculator.") or name.startswith("math.") or name.startswith("data.table") or name.startswith("calendar."):
        return "transform_compute"
    if name.startswith("finance.verify"):
        return "numeric_verification"
    if name.startswith("finance."):
        return "finance_contracts"
    if any(token in name for token in (".read", ".search", ".fetch", ".parse", ".extract")):
        return "generic_evidence"
    if "compute" in name or "calculate" in description:
        return "transform_compute"
    return "general_tools"


def _tool_family_purpose(family: str) -> str:
    return {
        "artifact_context": "Inspect, search, and read durable context artifacts from prior large results.",
        "tool_discovery": "Discover registered tools and assemble a temporary workbench for the current task.",
        "evidence_retrieval": "Retrieve or parse source evidence from filings, documents, or supplied context.",
        "market_data": "Fetch market or price data when the task requires it.",
        "transform_compute": "Compute deterministic arithmetic, table transforms, date differences, and symbolic math.",
        "numeric_verification": "Verify material numeric claims before final answer.",
        "finance_contracts": "Expose finance task contracts without taking over semantic decisions.",
        "generic_evidence": "General read/search/fetch/parse tools outside finance-specific naming.",
        "general_tools": "Other registered tools available to the model.",
    }.get(family, "Registered tools available to the model.")


def _tool_family_workflow_hint(family: str) -> str:
    return {
        "artifact_context": "Use inspect/search first for orientation; use read with offsets for broader context.",
        "tool_discovery": "Use when the visible provider tool list is partial or a new task needs a tool bench.",
        "evidence_retrieval": "Retrieve authoritative evidence before selecting inputs or formulas.",
        "market_data": "Use only when filings/supplied context are not the requested data source.",
        "transform_compute": "Use after evidence inputs are observed; avoid mental arithmetic for material numbers.",
        "numeric_verification": "Use after computing final material numbers and before finalizing.",
        "finance_contracts": "Use to identify evidence and transform contracts, then call concrete tools yourself.",
        "generic_evidence": "Use for task-specific source inspection when no stronger domain tool exists.",
        "general_tools": "Inspect the manifest schema and call only with valid inputs.",
    }.get(family, "Inspect the manifest schema and call only with valid inputs.")


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


def _tool_call_fingerprint(call: ToolCall) -> str:
    return f"{call.name}:{_stable_json(call.input)}"


def _preview_tool_result(result: ToolMessage, *, max_chars: int = 2_000) -> str:
    text = json.dumps(
        {
            "name": result.name,
            "is_error": result.is_error,
            "artifact_id": result.artifact_id,
            "content": result.content,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return text[:max_chars]


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
