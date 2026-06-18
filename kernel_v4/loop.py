from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from kernel_v4.context import ToolUseContext, project_messages_for_model
from kernel_v4.contracts import (
    AssistantMessage,
    ChatMessage,
    LoopEvent,
    LoopResult,
    ModelClient,
    ModelEvent,
    ToolCall,
    now_ms,
)
from kernel_v4.prompts import build_system_prompt, tool_surface_prompt
from kernel_v4.runtime import AbortController, WorkflowEventSink, WorkflowObserver
from kernel_v4.tooling import StreamingToolExecutor, ToolRegistry


@dataclass(frozen=True, kw_only=True)
class SingleAgentLoopConfig:
    max_turns: int = 24
    max_tool_calls: int = 80
    max_tool_result_chars: int = 50_000
    finance_mode: bool = False
    extra_system_prompt: str | None = None


@dataclass
class _CollectedAssistantTurn:
    assistant: AssistantMessage
    tool_results: list[ChatMessage]
    tool_call_count: int
    budget_exceeded: bool = False


class SingleAgentLoop:
    """Reference-style single-agent tool loop.

    This loop deliberately has no finance-specific semantic gates. The model
    decides what evidence is sufficient and which tools to call; the host
    executes, records, compacts oversized tool results, and stops only on loop
    budget, explicit final answer, or hard tool/runtime failure.
    """

    def __init__(
        self,
        *,
        model: ModelClient,
        tools: ToolRegistry,
        config: SingleAgentLoopConfig | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.config = config or SingleAgentLoopConfig()
        self.tools.install_core_tools()

    async def run(
        self,
        user_message: str,
        *,
        thread_key: str = "default",
        run_id: str | None = None,
        abort_controller: AbortController | None = None,
        workflow_event_handler: WorkflowEventSink | None = None,
    ) -> LoopResult:
        context = ToolUseContext(
            run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
            thread_key=thread_key,
            abort_controller=abort_controller or AbortController(),
            workflow=WorkflowObserver(workflow_event_handler),
        )
        system_prompt = build_system_prompt(
            finance=self.config.finance_mode,
            extra=self.config.extra_system_prompt,
        )
        context.messages = [ChatMessage(role="user", content=user_message)]
        events: list[LoopEvent] = []
        _emit(
            context,
            events,
            event_type="loop_start",
            turn_index=0,
            data={
                "run_id": context.run_id,
                "thread_key": thread_key,
                "finance_mode": self.config.finance_mode,
                "legacy_finance_gates": "not_loaded",
            },
        )
        if context.abort_signal.aborted:
            return _aborted_result(
                context,
                events,
                reason=context.abort_signal.reason or "cancelled",
                turn_index=0,
                tool_call_count=0,
            )
        tool_call_count = 0

        for turn_index in range(1, self.config.max_turns + 1):
            if context.abort_signal.aborted:
                return _aborted_result(
                    context,
                    events,
                    reason=context.abort_signal.reason or "cancelled",
                    turn_index=turn_index,
                    tool_call_count=tool_call_count,
                )
            visible_messages = project_messages_for_model(
                context.messages,
                context,
                max_tool_result_chars=self.config.max_tool_result_chars,
            )
            visible_tools = self.tools.manifests(include_names=_discovered_tool_names(context))
            recent_tool_calls = _recent_tool_call_summary(context.messages)
            request_context = {
                "schema": "holo.kernel_v4.model_request_context.v1",
                "run_id": context.run_id,
                "turn_index": turn_index,
                "in_progress_tool_use_ids": sorted(context.in_progress_tool_use_ids),
                "tool_surface": tool_surface_prompt(visible_tools),
                "artifact_count": len(context.artifacts),
                "workflow": context.workflow_context_summary(),
                "recent_tool_calls": recent_tool_calls,
                "repeat_tool_call_policy": (
                    "Before calling a tool, compare against recent_tool_calls.successful. "
                    "Do not repeat the same successful tool with the same input unless new evidence, changed input, "
                    "or a prior tool error makes repetition necessary."
                ),
                "host_boundary": "host executes requested tools and returns tool results; model owns semantic decisions",
            }
            _emit(
                context,
                events,
                event_type="model_turn_start",
                turn_index=turn_index,
                data={
                    "message_count": len(visible_messages),
                    "visible_tool_count": len(visible_tools),
                    "abort": context.abort_signal.to_dict(),
                },
            )

            try:
                collected = await self._collect_assistant_turn(
                    messages=visible_messages,
                    tools=visible_tools,
                    system_prompt=system_prompt,
                    context=request_context,
                    runtime_context=context,
                    turn_index=turn_index,
                    events=events,
                    remaining_tool_calls=self.config.max_tool_calls - tool_call_count,
                )
            except Exception as exc:  # noqa: BLE001 - provider/model failures must not tear down the host CLI.
                return _failed_result(
                    context,
                    events,
                    reason=_model_stream_error_reason(exc),
                    turn_index=turn_index,
                    tool_call_count=tool_call_count,
                )
            assistant = collected.assistant
            if collected.budget_exceeded:
                return _failed_result(
                    context,
                    events,
                    reason="max_tool_calls_exceeded",
                    turn_index=turn_index,
                    tool_call_count=tool_call_count + collected.tool_call_count,
                )
            context.messages.append(assistant.as_chat_message())
            context.messages.extend(collected.tool_results)
            tool_call_count += collected.tool_call_count
            if context.abort_signal.aborted:
                return _aborted_result(
                    context,
                    events,
                    reason=context.abort_signal.reason or "cancelled",
                    turn_index=turn_index,
                    tool_call_count=tool_call_count,
                )
            if not assistant.tool_calls:
                _emit(
                    context,
                    events,
                    event_type="loop_completed",
                    turn_index=turn_index,
                    data={"reason": "assistant_final_answer", "answer_chars": len(assistant.content)},
                )
                return LoopResult(
                    status="completed",
                    answer=assistant.content,
                    messages=tuple(context.messages),
                    events=tuple(events),
                    tool_call_count=tool_call_count,
                    turn_count=turn_index,
                )

            if context.abort_signal.aborted:
                return _aborted_result(
                    context,
                    events,
                    reason=context.abort_signal.reason or "cancelled",
                    turn_index=turn_index,
                    tool_call_count=tool_call_count,
                )

        return _failed_result(
            context,
            events,
            reason="max_turns_exceeded",
            turn_index=self.config.max_turns,
            tool_call_count=tool_call_count,
        )

    async def _collect_assistant_turn(
        self,
        *,
        messages: list[ChatMessage],
        tools: list,
        system_prompt: str,
        context: dict,
        runtime_context: ToolUseContext,
        turn_index: int,
        events: list[LoopEvent],
        remaining_tool_calls: int,
    ) -> _CollectedAssistantTurn:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        tool_results: list[ChatMessage] = []
        budget_exceeded = False
        executor = StreamingToolExecutor(self.tools, runtime_context, turn_index=turn_index)
        async for event in self.model.stream(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            context=context,
        ):
            event = _coerce_model_event(event)
            if event.event_type == "text_delta":
                text_parts.append(event.text)
                _emit(
                    runtime_context,
                    events,
                    event_type="assistant_text_delta",
                    turn_index=turn_index,
                    data={"chars": len(event.text)},
                )
            elif event.event_type == "tool_call" and event.tool_call is not None:
                if len(tool_calls) >= remaining_tool_calls:
                    budget_exceeded = True
                    _emit(
                        runtime_context,
                        events,
                        event_type="tool_budget_exceeded",
                        turn_index=turn_index,
                        data={"max_new_tool_calls": remaining_tool_calls, "tool": event.tool_call.name},
                    )
                    continue
                tool_calls.append(event.tool_call)
                _emit(
                    runtime_context,
                    events,
                    event_type="assistant_tool_call",
                    turn_index=turn_index,
                    data={"tool_call_id": event.tool_call.tool_call_id, "tool": event.tool_call.name},
                )
                executor.add_tool_call(event.tool_call)
                events.extend(executor.pop_events())
            elif event.event_type == "message_stop":
                _emit(runtime_context, events, event_type="assistant_message_stop", turn_index=turn_index, data={})
            completed = await executor.drain_completed()
            events.extend(executor.pop_events())
            tool_results.extend(result.as_chat_message() for result in completed)
            if runtime_context.abort_signal.aborted:
                await executor.cancel_remaining(reason=runtime_context.abort_signal.reason or "cancelled")
                break
        remaining = await executor.drain_remaining()
        events.extend(executor.pop_events())
        tool_results.extend(result.as_chat_message() for result in remaining)
        assistant_content = "".join(text_parts).strip()
        if not tool_calls and not budget_exceeded:
            assistant_content, text_calls = _extract_text_tool_calls(
                assistant_content,
                tools=tools,
                turn_index=turn_index,
            )
            for call in text_calls:
                if len(tool_calls) >= remaining_tool_calls:
                    budget_exceeded = True
                    _emit(
                        runtime_context,
                        events,
                        event_type="tool_budget_exceeded",
                        turn_index=turn_index,
                        data={"max_new_tool_calls": remaining_tool_calls, "tool": call.name},
                    )
                    continue
                tool_calls.append(call)
                _emit(
                    runtime_context,
                    events,
                    event_type="assistant_tool_call",
                    turn_index=turn_index,
                    data={"tool_call_id": call.tool_call_id, "tool": call.name, "source": "text_tool_call_fallback"},
                )
                executor.add_tool_call(call)
                events.extend(executor.pop_events())
            text_results = await executor.drain_remaining()
            events.extend(executor.pop_events())
            tool_results.extend(result.as_chat_message() for result in text_results)
        return _CollectedAssistantTurn(
            assistant=AssistantMessage(
                content=assistant_content,
                tool_calls=tuple(tool_calls),
                metadata={"created_at_ms": now_ms()},
            ),
            tool_results=tool_results,
            tool_call_count=len(tool_calls),
            budget_exceeded=budget_exceeded,
        )


def _failed_result(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    reason: str,
    turn_index: int,
    tool_call_count: int,
) -> LoopResult:
    _emit(context, events, event_type="loop_failed", turn_index=turn_index, data={"reason": reason})
    return LoopResult(
        status="failed",
        answer="",
        messages=tuple(context.messages),
        events=tuple(events),
        reason=reason,
        tool_call_count=tool_call_count,
        turn_count=turn_index,
    )


def _model_stream_error_reason(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > 300:
        message = message[:297] + "..."
    return f"model_stream_error:{type(exc).__name__}:{message}"


def _aborted_result(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    reason: str,
    turn_index: int,
    tool_call_count: int,
) -> LoopResult:
    _emit(context, events, event_type="loop_aborted", turn_index=turn_index, data={"reason": reason})
    return LoopResult(
        status="aborted",
        answer="",
        messages=tuple(context.messages),
        events=tuple(events),
        reason=reason,
        tool_call_count=tool_call_count,
        turn_count=turn_index,
    )


def _emit(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    event_type: str,
    turn_index: int,
    data: dict,
) -> LoopEvent:
    event = LoopEvent(event_type=event_type, turn_index=turn_index, data=data)
    events.append(event)
    context.emit_workflow(event)
    return event


def _coerce_model_event(value) -> ModelEvent:
    if isinstance(value, ModelEvent):
        return value
    if isinstance(value, dict):
        tool_call = value.get("tool_call")
        if isinstance(tool_call, dict):
            tool_call = ToolCall(
                tool_call_id=str(tool_call.get("tool_call_id") or tool_call.get("id") or ""),
                name=str(tool_call.get("name") or ""),
                input=dict(tool_call.get("input") or tool_call.get("arguments") or {}),
            )
        return ModelEvent(
            event_type=str(value.get("event_type") or value.get("type") or "message_stop"),
            text=str(value.get("text") or ""),
            tool_call=tool_call if isinstance(tool_call, ToolCall) else None,
            metadata=dict(value.get("metadata") or {}),
        )
    raise TypeError(f"unsupported model event: {type(value).__name__}")


def _discovered_tool_names(context: ToolUseContext) -> set[str]:
    value = context.metadata.get("discovered_tool_names")
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item}


def _recent_tool_call_summary(messages: list[ChatMessage], *, limit: int = 20) -> JsonObject:
    tool_results: dict[str, ChatMessage] = {
        message.tool_call_id: message
        for message in messages
        if message.role == "tool" and isinstance(message.tool_call_id, str) and message.tool_call_id
    }
    calls: list[JsonObject] = []
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            input_text = _stable_json(call.input)
            result = tool_results.get(call.tool_call_id)
            status = "pending"
            if result is not None:
                status = "error" if result.metadata.get("is_error") else "success"
            item: JsonObject = {
                "tool_call_id": call.tool_call_id,
                "tool": call.name,
                "status": status,
                "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "input_preview": input_text[:500],
            }
            if result is not None:
                item["result_preview"] = result.content[:1000]
            calls.append(item)
    recent = calls[-limit:]
    successful = [item for item in recent if item["status"] == "success"]
    seen: set[tuple[str, str]] = set()
    duplicates: list[JsonObject] = []
    for item in successful:
        key = (str(item["tool"]), str(item["input_sha256"]))
        if key in seen:
            duplicates.append({"tool": item["tool"], "input_sha256": item["input_sha256"]})
        seen.add(key)
    return {
        "recent": recent,
        "successful": successful,
        "duplicate_successful_inputs": duplicates,
    }


def _stable_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


_DSML_TOOL_BLOCK_RE = re.compile(r"<｜｜DSML｜｜tool_calls>(.*?)</｜｜DSML｜｜tool_calls>", re.DOTALL)
_DSML_INVOKE_RE = re.compile(r"<｜｜DSML｜｜invoke\s+name=\"([^\"]+)\">(.*?)</｜｜DSML｜｜invoke>", re.DOTALL)
_DSML_INVOKE_START_RE = re.compile(r"<｜｜DSML｜｜invoke\s+name=\"([^\"]+)\">", re.DOTALL)
_DSML_INVOKE_END = "</｜｜DSML｜｜invoke>"


def _extract_text_tool_calls(
    text: str,
    *,
    tools: list,
    turn_index: int,
) -> tuple[str, list[ToolCall]]:
    visible_tool_names = {str(tool.name) for tool in tools}
    calls: list[ToolCall] = []

    def replace_block(match: re.Match[str]) -> str:
        block = match.group(1)
        parsed = _parse_dsml_tool_block(block, visible_tool_names=visible_tool_names, turn_index=turn_index, offset=len(calls))
        calls.extend(parsed)
        return ""

    cleaned = _DSML_TOOL_BLOCK_RE.sub(replace_block, text).strip()
    return cleaned, calls


def _parse_dsml_tool_block(
    block: str,
    *,
    visible_tool_names: set[str],
    turn_index: int,
    offset: int,
) -> list[ToolCall]:
    outer = _DSML_INVOKE_START_RE.search(block)
    if outer is None:
        return []
    tool_name = outer.group(1).strip()
    if tool_name not in visible_tool_names:
        return []
    body = block[outer.end() :]
    if _DSML_INVOKE_END in body:
        body = body.rsplit(_DSML_INVOKE_END, 1)[0]
    payload: JsonObject = {}
    for key, raw_value in _DSML_INVOKE_RE.findall(body):
        key = key.strip()
        value = raw_value.strip()
        if not key or key == tool_name:
            continue
        payload[key] = _parse_text_tool_value(value)
    if not payload:
        payload = _parse_text_tool_payload(body)
    return [
        ToolCall(
            tool_call_id=f"text-tool-{turn_index}-{offset}",
            name=tool_name,
            input=payload,
        )
    ]


def _parse_text_tool_value(value: str) -> object:
    if not value:
        return ""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_text_tool_payload(body: str) -> JsonObject:
    stripped = _DSML_INVOKE_RE.sub("", body).strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"input": stripped}
    return parsed if isinstance(parsed, dict) else {"value": parsed}
