from __future__ import annotations

import hashlib
import html
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
from kernel_v4.runtime import AbortController, ContextEdit, WorkflowEventSink, WorkflowObserver
from kernel_v4.tooling import StreamingToolExecutor, ToolRegistry

_ENDGAME_EVIDENCE_SUCCESS_THRESHOLD = 12
_CALCULATION_EVIDENCE_SUCCESS_THRESHOLD = 8
_SOURCE_SATURATION_EVIDENCE_SUCCESS_THRESHOLD = 24
_SOURCE_SATURATION_LOW_TURN_REMAINING = 16
_REPEATED_SOURCE_TOOL_SUCCESS_THRESHOLD = 6
_REPEATED_SOURCE_TOOL_ERROR_THRESHOLD = 4
_NO_TOOL_TEXT_TOOL_CALL_RECOVERY_LIMIT = 4
_MATERIAL_NUMERIC_CLAIM_RE = re.compile(
    r"(?i)(\$|\b\d[\d,]*(?:\.\d+)?\s*(?:%|percent|percentage points?|bps|basis points?|million|billion|thousand|days?|x|times)\b|\b\d+(?:\.\d+)?:\d+\b)"
)
_UNSUPPORTED_NUMERIC_SOURCE_RE = re.compile(
    r"(?i)(my recall|from memory|not directly observed|not directly accessible|partially accessible|could not locate|could not find|unable to locate|limitation note|best supported answer)"
)
_PROCESS_NARRATION_FINAL_RE = re.compile(
    r"(?is)^\s*(?:"
    r"i\s+now\s+have\s+(?:all\s+)?(?:the\s+)?evidence|"
    r"now\s+i\s+have\s+(?:all\s+)?(?:the\s+)?(?:evidence|numbers|facts|inputs)|"
    r"i(?:'ve| have)\s+already\s+(?:retrieved|verified|found|computed|calculated)|"
    r"let\s+me\s+provide\s+(?:the\s+)?final\s+answer|"
    r"now\s+i\s+can\s+(?:provide|answer)|"
    r"i\s+will\s+now\s+(?:provide|answer)"
    r")"
)
_SELF_REFERENTIAL_FINAL_RE = re.compile(
    r"(?is)(?:"
    r"\b(?:the\s+)?above\s+(?:answer|response|conclusion)\b|"
    r"\b(?:previous|prior)\s+(?:turn|answer|response|conclusion)\b|"
    r"\b(?:answer|response|conclusion)\s+(?:was\s+)?already\s+provided\b|"
    r"\b(?:my\s+)?final\s+answer\s+is\s+complete\b|"
    r"\b(?:answer|response|conclusion)\s+(?:above|stands\s+as\s+above|remains\s+as\s+above|is\s+complete)|"
    r"\b(?:as\s+(?:shown|stated|noted|computed|calculated|provided)\s+above|provided\s+above|shown\s+above)|"
    r"\b(?:task\s+is\s+complete|answer\s+provided\s+with|provided\s+with\s+direct\s+evidence|"
    r"no\s+further\s+corrections\s+are\s+needed)|"
    r"\b(?:underlying\s+source\s+evidence\s+and\s+arithmetic\s+are\s+sound|"
    r"verifier\s+flagged|ledger-binding|"
    r"the\s+question\s+is\s+answered\s+clearly|exact\s+amount\s+is\s+provided)"
    r")"
)
_GROSS_MARGIN_QUESTION_RE = re.compile(r"(?i)\bgross\s+margin\b")
_WORKING_CAPITAL_QUESTION_RE = re.compile(r"(?i)\bworking\s+capital\b")
_CAPITAL_INTENSITY_QUESTION_RE = re.compile(r"(?i)\b(?:capital[-\s]*intensive|asset[-\s]*intensive|capital\s+intensity|asset\s+intensity)\b")
_LEGAL_PROCEEDINGS_QUESTION_RE = re.compile(
    r"(?i)\b(?:legal\s+battles?|legal\s+proceedings?|litigation|lawsuits?|regulatory\s+investigations?|contingenc(?:y|ies))\b"
)
_OPERATING_WORKING_CAPITAL_ANSWER_RE = re.compile(r"(?i)\b(?:operating|non[-\s]*cash)\s+working\s+capital\b")
_PPE_REVENUE_ANSWER_RE = re.compile(
    r"(?i)\b(?:pp\s*&\s*e|ppe|property(?:,?\s+plant)?\s+and\s+equipment)\s*/\s*(?:revenue|sales)\b"
)
_GENERIC_FAILURE_FINAL_RE = re.compile(
    r"(?is)(?:"
    r"i\s+cannot\s+determine|i\s+can't\s+determine|cannot\s+determine|can't\s+determine|"
    r"could\s+not\s+determine|cannot\s+be\s+determined|not\s+enough\s+information|"
    r"unable\s+to\s+answer|cannot\s+answer|can't\s+answer|cannot\s+be\s+answered|"
    r"unable\s+to\s+compute|unable\s+to\s+calculate|cannot\s+compute|can't\s+compute|"
    r"could\s+not\s+compute|cannot\s+calculate|can't\s+calculate|could\s+not\s+calculate|"
    r"cannot\s+be\s+calculated|unable\s+to\s+retrieve|could\s+not\s+retrieve|"
    r"unable\s+to\s+extract|could\s+not\s+extract|couldn't\s+extract|could\s+not\s+be\s+extracted|"
    r"not\s+present\s+in\s+the\s+extracted\s+text|current\s+tool\s+surface|"
    r"insufficient\s+information|no\s+answer"
    r")"
)
_ENDGAME_TOOL_ALLOWLIST = frozenset(
    {
        "tool.discovery",
        "artifact.inspect",
        "artifact.search",
        "artifact.read",
        "document.text.extract",
        "provided_context.parse",
        "data.table.query",
        "math.sympy.compute",
        "calendar.days_between",
        "calculator.compute",
        "finance.verify_numeric",
    }
)
_CALCULATION_TOOL_ALLOWLIST = frozenset(
    {
        "tool.discovery",
        "artifact.inspect",
        "artifact.search",
        "artifact.read",
        "document.text.extract",
        "provided_context.parse",
        "data.table.query",
        "math.sympy.compute",
        "calendar.days_between",
        "calculator.compute",
        "finance.verify_numeric",
    }
)


@dataclass(frozen=True, kw_only=True)
class SingleAgentLoopConfig:
    max_turns: int = 64
    max_tool_calls: int = 200
    max_tool_result_chars: int = 50_000
    model_context_mode: str = "full"
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
        initial_metadata: dict | None = None,
        abort_controller: AbortController | None = None,
        workflow_event_handler: WorkflowEventSink | None = None,
    ) -> LoopResult:
        context = ToolUseContext(
            run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
            thread_key=thread_key,
            abort_controller=abort_controller or AbortController(),
            workflow=WorkflowObserver(workflow_event_handler),
        )
        if initial_metadata:
            context.metadata.update(dict(initial_metadata))
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
            _maybe_insert_endgame_checkpoint(context, events, turn_index=turn_index)
            _maybe_insert_calculation_checkpoint(context, events, turn_index=turn_index)
            _maybe_insert_repeated_source_checkpoint(context, events, turn_index=turn_index)
            _maybe_insert_source_saturation_checkpoint(
                context,
                events,
                turn_index=turn_index,
                max_turns=self.config.max_turns,
            )
            _maybe_insert_post_verify_finalization_checkpoint(context, events, turn_index=turn_index)
            visible_messages = project_messages_for_model(
                context.messages,
                context,
                max_tool_result_chars=self.config.max_tool_result_chars,
            )
            force_finalization_no_tools = bool(context.metadata.get("force_finalization_no_tools"))
            final_turn_no_tools = turn_index == self.config.max_turns or force_finalization_no_tools
            visible_tools = self.tools.manifests(include_names=_discovered_tool_names(context))
            visible_tools = _apply_endgame_tool_surface(context, events, visible_tools, turn_index=turn_index)
            if final_turn_no_tools:
                visible_tools = []
            recent_tool_calls = _recent_tool_call_summary(context.messages)
            progress_summary = _tool_progress_summary(recent_tool_calls)
            tool_surface = (
                "FINALIZATION TURN: no tools are exposed on this turn. Use the already returned evidence, "
                "calculations, verification results, artifacts, and workflow context to produce the best supported "
                "final answer now. The final answer must be self-contained: restate the answer numbers, units, "
                "formula, periods, and comparison direction instead of saying 'as above' or referring to prior text. "
                "Do not ask for more retrieval or verification."
                if final_turn_no_tools
                else tool_surface_prompt(visible_tools)
            )
            request_context = {
                "schema": "holo.kernel_v4.model_request_context.v1",
                "run_id": context.run_id,
                "turn_index": turn_index,
                "remaining_turns_after_this": self.config.max_turns - turn_index,
                "remaining_tool_calls": max(0, self.config.max_tool_calls - tool_call_count),
                "final_turn_no_tools": final_turn_no_tools,
                "force_finalization_no_tools": force_finalization_no_tools,
                "in_progress_tool_use_ids": sorted(context.in_progress_tool_use_ids),
                "tool_surface": tool_surface,
                "artifact_count": len(context.artifacts),
                "workflow": context.workflow_context_summary(),
                "recent_tool_calls": recent_tool_calls,
                "tool_progress_summary": progress_summary,
                "repeat_tool_call_policy": (
                    "Before calling a tool, compare against recent_tool_calls.successful. "
                    "Do not repeat the same successful tool with the same input unless new evidence, changed input, "
                    "or a prior tool error makes repetition necessary."
                ),
                "endgame_policy": (
                    "If multiple evidence/search/read/parse tools have succeeded for the same task, either extract the "
                    "observed facts and move to calculation/verification/final answer, or name the exact missing fact "
                    "and call the one next tool most likely to resolve it. When remaining_turns_after_this is low, "
                    "prefer a supported final answer over another broad search. If final_turn_no_tools is true, output "
                    "the final answer from current evidence and state any exact limitation instead of calling tools. "
                    "If you notice repeated retrieval thoughts for the same missing fact, do not output the repeated "
                    "plan as final text; give a concise supported conclusion or a precise blocker."
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

            model_request_context = _request_context_for_model(
                request_context,
                mode=self.config.model_context_mode,
            )
            try:
                collected = await self._collect_assistant_turn(
                    messages=visible_messages,
                    tools=visible_tools,
                    system_prompt=system_prompt,
                    context=model_request_context,
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
                if not assistant.content.strip():
                    return _failed_result(
                        context,
                        events,
                        reason="empty_final_answer",
                        turn_index=turn_index,
                        tool_call_count=tool_call_count,
                    )
                if final_turn_no_tools and _looks_like_text_tool_call_only(assistant.content):
                    extracted_answer = _extract_no_tool_text_tool_call_final_answer(assistant.content)
                    if extracted_answer:
                        assistant = AssistantMessage(
                            content=extracted_answer,
                            metadata={
                                **assistant.metadata,
                                "extracted_from_no_tool_text_tool_call": True,
                            },
                        )
                        context.messages[-1] = assistant.as_chat_message()
                        _emit(
                            context,
                            events,
                            event_type="text_tool_call_final_answer_extracted",
                            turn_index=turn_index,
                            data={"answer_chars": len(extracted_answer), "source_tool": "finance.verify_numeric"},
                        )
                    else:
                        if _maybe_recover_no_tool_text_tool_call_finalization(
                            context,
                            events,
                            assistant.content,
                            turn_index=turn_index,
                            max_turns=self.config.max_turns,
                        ):
                            continue
                        return _failed_result(
                            context,
                            events,
                            reason="final_answer_is_tool_call_markup",
                            turn_index=turn_index,
                            tool_call_count=tool_call_count,
                        )
                if self.config.finance_mode and _maybe_insert_numeric_verification_checkpoint(
                    context,
                    events,
                    assistant.content,
                    turn_index=turn_index,
                    max_turns=self.config.max_turns,
                ):
                    continue
                if self.config.finance_mode and _contains_unsupported_numeric_source_caveat(assistant.content):
                    if _maybe_recover_unsupported_numeric_source_finalization(
                        context,
                        events,
                        assistant.content,
                        turn_index=turn_index,
                        max_turns=self.config.max_turns,
                    ):
                        continue
                    return _failed_result(
                        context,
                        events,
                        reason="unsupported_numeric_source_final_answer",
                        turn_index=turn_index,
                        tool_call_count=tool_call_count,
                    )
                if self.config.finance_mode and _contains_verified_numeric_generic_failure(assistant.content, context):
                    if _maybe_recover_verified_numeric_generic_failure_finalization(
                        context,
                        events,
                        assistant.content,
                        turn_index=turn_index,
                        max_turns=self.config.max_turns,
                    ):
                        continue
                    return _failed_result(
                        context,
                        events,
                        reason="generic_failure_after_verified_numeric_final_answer",
                        turn_index=turn_index,
                        tool_call_count=tool_call_count,
                    )
                if self.config.finance_mode and _contains_generic_failure_final_answer(assistant.content):
                    if _maybe_recover_generic_failure_finalization(
                        context,
                        events,
                        assistant.content,
                        turn_index=turn_index,
                        max_turns=self.config.max_turns,
                    ):
                        continue
                    return _failed_result(
                        context,
                        events,
                        reason="generic_failure_final_answer",
                        turn_index=turn_index,
                        tool_call_count=tool_call_count,
                    )
                if self.config.finance_mode and _maybe_recover_process_narration_final_answer(
                    context,
                    events,
                    assistant.content,
                    turn_index=turn_index,
                    max_turns=self.config.max_turns,
                ):
                    continue
                if self.config.finance_mode and _maybe_insert_finance_answer_coverage_checkpoint(
                    context,
                    events,
                    assistant.content,
                    turn_index=turn_index,
                    max_turns=self.config.max_turns,
                ):
                    continue
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
        assistant_metadata: dict = {"created_at_ms": now_ms()}
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
                usage = _usage_from_model_event_metadata(event.metadata)
                stop_data = {"usage": usage} if usage else {}
                reasoning_content = event.metadata.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content:
                    assistant_metadata["_private_reasoning_content"] = reasoning_content
                    assistant_metadata["reasoning_content_chars"] = len(reasoning_content)
                _emit(runtime_context, events, event_type="assistant_message_stop", turn_index=turn_index, data=stop_data)
                if usage:
                    _emit(
                        runtime_context,
                        events,
                        event_type="model_usage",
                        turn_index=turn_index,
                        data=usage,
                    )
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
        if tools and not tool_calls and not budget_exceeded:
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
                metadata=assistant_metadata,
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


def _usage_from_model_event_metadata(metadata: JsonObject) -> JsonObject:
    usage = metadata.get("usage") if isinstance(metadata, dict) else None
    if not isinstance(usage, dict):
        return {}
    return json.loads(json.dumps(usage, ensure_ascii=False))


def _request_context_for_model(context: JsonObject, *, mode: str) -> JsonObject:
    normalized = str(mode or "full").strip().casefold()
    if normalized in {"off", "none", "disabled"}:
        if context.get("final_turn_no_tools"):
            return {
                "schema": "holo.kernel_v4.model_request_context.final_turn.v1",
                "final_turn_no_tools": True,
                "instruction": (
                    "No tools are exposed on this final turn. Use the already returned evidence, calculations, "
                    "verification results, artifacts, and conversation history to produce the best supported final answer now."
                ),
            }
        return {}
    if normalized in {"compact", "minimal"}:
        return {
            "schema": "holo.kernel_v4.model_request_context.compact.v1",
            "turn_index": context.get("turn_index"),
            "remaining_turns_after_this": context.get("remaining_turns_after_this"),
            "remaining_tool_calls": context.get("remaining_tool_calls"),
            "final_turn_no_tools": context.get("final_turn_no_tools"),
            "artifact_count": context.get("artifact_count"),
            "recent_tool_calls": context.get("recent_tool_calls"),
            "tool_progress_summary": context.get("tool_progress_summary"),
            "repeat_tool_call_policy": context.get("repeat_tool_call_policy"),
            "endgame_policy": context.get("endgame_policy"),
        }
    if normalized != "full":
        raise ValueError(f"unknown model_context_mode={mode!r}; expected off, compact, or full")
    return context


def _maybe_insert_endgame_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    turn_index: int,
) -> None:
    if not context.metadata.get("enable_endgame_checkpoint"):
        return
    if context.metadata.get("endgame_checkpoint_inserted"):
        return
    evidence_success_count = _successful_evidence_tool_count(context.messages)
    threshold = _metadata_int(
        context.metadata.get("endgame_evidence_success_threshold"),
        default=_ENDGAME_EVIDENCE_SUCCESS_THRESHOLD,
    )
    if evidence_success_count < threshold:
        return
    content = (
        "ENDGAME CHECKPOINT: many evidence/source/search/read tools have already succeeded. "
        "The host will now expose only endgame tools: local artifact inspect/search/read, exact observed-document text extraction, provided-context parse, deterministic compute, day-count, numeric verification, and tool discovery within this endgame surface. "
        "Do not request another broad SEC/company-filings lookup, document conversion, market-data, or source-retrieval call. "
        "If one exact fact is still missing inside an already observed official filing/exhibit URL, call document.text.extract on that exact URL with focused terms; otherwise search/read existing artifacts narrowly, move to calculator.compute, data.table.query, finance.verify_numeric, or finalize. "
        "For trend questions, include latest value, prior comparable value, and latest-minus-prior change."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_endgame_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="endgame_checkpoint_inserted",
            value=True,
            source="kernel_v4_endgame_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="endgame_evidence_success_count",
            value=evidence_success_count,
            source="kernel_v4_endgame_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="tool_surface_allowlist",
            value=sorted(_ENDGAME_TOOL_ALLOWLIST),
            source="kernel_v4_endgame_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="endgame_checkpoint_inserted",
        turn_index=turn_index,
        data={
            "evidence_success_count": evidence_success_count,
            "threshold": threshold,
            "tool_surface_allowlist": sorted(_ENDGAME_TOOL_ALLOWLIST),
        },
    )


def _maybe_insert_calculation_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    turn_index: int,
) -> None:
    if not context.metadata.get("enable_calculation_checkpoint"):
        return
    if not context.metadata.get("endgame_checkpoint_inserted"):
        return
    if context.metadata.get("calculation_checkpoint_inserted"):
        return
    transform_seen = _tool_seen(
        context.messages,
        {"calculator.compute", "data.table.query", "math.sympy.compute", "calendar.days_between", "finance.verify_numeric"},
    )
    if transform_seen:
        return
    entered_at = _metadata_int(context.metadata.get("endgame_evidence_success_count"), default=0)
    evidence_success_count = _successful_evidence_tool_count(context.messages)
    post_endgame_evidence_count = max(0, evidence_success_count - entered_at)
    threshold = _metadata_int(
        context.metadata.get("calculation_evidence_success_threshold"),
        default=_CALCULATION_EVIDENCE_SUCCESS_THRESHOLD,
    )
    if post_endgame_evidence_count < threshold:
        return
    content = (
        "CALCULATION CHECKPOINT: after the endgame checkpoint, more local evidence/search/read tools have succeeded but no deterministic compute or verification tool has been used. "
        "The host will now keep only local endgame evidence tools plus calculation, table, date, verification, and discovery tools. "
        "Do not request broad SEC/company-filings, market-data, document conversion, or old hidden tool aliases. Use facts already observed, or if one required input is genuinely absent, use artifact.search/read or document.text.extract with focused terms on an already observed filing URL to retrieve that exact input. Then call calculator.compute, data.table.query, math.sympy.compute, calendar.days_between, or finance.verify_numeric as needed and finalize."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_calculation_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="calculation_checkpoint_inserted",
            value=True,
            source="kernel_v4_calculation_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="tool_surface_allowlist",
            value=sorted(_CALCULATION_TOOL_ALLOWLIST),
            source="kernel_v4_calculation_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="calculation_checkpoint_inserted",
        turn_index=turn_index,
        data={
            "evidence_success_count": evidence_success_count,
            "post_endgame_evidence_count": post_endgame_evidence_count,
            "threshold": threshold,
            "tool_surface_allowlist": sorted(_CALCULATION_TOOL_ALLOWLIST),
        },
    )


def _maybe_insert_repeated_source_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    turn_index: int,
) -> None:
    if not context.metadata.get("enable_repeated_source_checkpoint"):
        return
    if context.metadata.get("repeated_source_checkpoint_inserted"):
        return
    if context.metadata.get("source_saturation_checkpoint_inserted"):
        return
    if context.metadata.get("calculation_checkpoint_inserted"):
        return
    stats = _external_source_tool_stats(context.messages)
    success_threshold = _metadata_int(
        context.metadata.get("repeated_source_success_threshold"),
        default=_REPEATED_SOURCE_TOOL_SUCCESS_THRESHOLD,
    )
    error_threshold = _metadata_int(
        context.metadata.get("repeated_source_error_threshold"),
        default=_REPEATED_SOURCE_TOOL_ERROR_THRESHOLD,
    )
    trigger = ""
    if int(stats["max_success_count_for_one_tool"]) >= success_threshold:
        trigger = "same_source_tool_success_repetition"
    elif int(stats["total_success_count"]) >= success_threshold + 2:
        trigger = "source_family_success_repetition"
    elif int(stats["total_error_count"]) >= error_threshold and _successful_evidence_tool_count(context.messages) >= 2:
        trigger = "source_error_repetition_after_evidence"
    if not trigger:
        return
    content = (
        "REPEATED SOURCE CHECKPOINT: the workflow has already produced enough successful source/extraction evidence "
        "or repeated source-tool errors. The host will now expose only local artifact inspect/search/read, provided-context parse, "
        "exact observed-document text extraction, deterministic compute, table/date/symbolic math, numeric verification, and tool discovery within this endgame surface. "
        "Do not call more SEC/company-filings, document conversion, market-data, or other broad source tools. "
        "Use existing observations and artifacts. If the answer still lacks one fact from an already observed official filing/exhibit URL, call document.text.extract on that exact URL with focused terms; otherwise search/read existing artifacts narrowly for that exact fact or synthesize the final answer now."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_repeated_source_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="repeated_source_checkpoint_inserted",
            value=True,
            source="kernel_v4_repeated_source_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="endgame_checkpoint_inserted",
            value=True,
            source="kernel_v4_repeated_source_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="endgame_evidence_success_count",
            value=_successful_evidence_tool_count(context.messages),
            source="kernel_v4_repeated_source_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="tool_surface_allowlist",
            value=sorted(_ENDGAME_TOOL_ALLOWLIST),
            source="kernel_v4_repeated_source_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="repeated_source_checkpoint_inserted",
        turn_index=turn_index,
        data={
            "trigger": trigger,
            "stats": stats,
            "success_threshold": success_threshold,
            "error_threshold": error_threshold,
            "tool_surface_allowlist": sorted(_ENDGAME_TOOL_ALLOWLIST),
        },
    )


def _maybe_insert_post_verify_finalization_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    turn_index: int,
) -> None:
    if context.metadata.get("post_verify_finalization_checkpoint_inserted"):
        return
    if not _successful_numeric_verification_seen(context.messages):
        return
    content = (
        "POST-VERIFY FINALIZATION CHECKPOINT: finance.verify_numeric has completed successfully. "
        "No more tools are needed for the verified material numeric answer. "
        "Use the observed evidence, calculations, verification result, periods, units, formulas, and citations to produce the final answer now. "
        "The answer must be self-contained: include the key verified numbers and units explicitly, not a reference to prior text. "
        "Do not call discovery, table, calculator, retrieval, source, artifact, or old sanitized tool aliases after successful numeric verification."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_post_verify_finalization_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="post_verify_finalization_checkpoint_inserted",
            value=True,
            source="kernel_v4_post_verify_finalization_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="force_finalization_no_tools",
            value=True,
            source="kernel_v4_post_verify_finalization_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="post_verify_finalization_checkpoint_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": True, "visible_tools_forced_to": 0},
    )


def _maybe_insert_numeric_verification_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    if turn_index >= max_turns:
        return False
    if context.metadata.get("numeric_verification_checkpoint_inserted"):
        return False
    if _successful_numeric_verification_seen(context.messages):
        return False
    if not _contains_material_numeric_claim(text):
        return False
    content = (
        "NUMERIC VERIFICATION CHECKPOINT: your draft final answer contains material numeric claims, "
        "but finance.verify_numeric has not completed successfully. Do not finalize yet. "
        "If arithmetic is derived, call calculator.compute first. Then call finance.verify_numeric "
        "with the candidate final numeric answer and supporting source/calculation context. "
        "Only after verifier feedback should you write the final answer."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_numeric_verification_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="numeric_verification_checkpoint_inserted",
            value=True,
            source="kernel_v4_numeric_verification_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="numeric_verification_checkpoint_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": False},
    )
    return True


def _contains_material_numeric_claim(text: str) -> bool:
    return bool(_MATERIAL_NUMERIC_CLAIM_RE.search(str(text or "")))


def _contains_unsupported_numeric_source_caveat(text: str) -> bool:
    value = str(text or "")
    return bool(_MATERIAL_NUMERIC_CLAIM_RE.search(value) and _UNSUPPORTED_NUMERIC_SOURCE_RE.search(value))


def _contains_verified_numeric_generic_failure(text: str, context: ToolUseContext) -> bool:
    return bool(
        _GENERIC_FAILURE_FINAL_RE.search(str(text or ""))
        and _successful_numeric_verification_seen(context.messages)
    )


def _contains_generic_failure_final_answer(text: str) -> bool:
    return bool(_GENERIC_FAILURE_FINAL_RE.search(str(text or "")))


def _maybe_insert_finance_answer_coverage_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    if turn_index >= max_turns:
        return False
    checkpoint_count = int(context.metadata.get("finance_answer_coverage_checkpoint_count") or 0)
    if checkpoint_count >= 3:
        return False
    question = str(context.metadata.get("task_question") or "")
    if not question:
        return False
    answer = str(text or "")
    checks: list[str] = []
    if _GROSS_MARGIN_QUESTION_RE.search(question):
        answer_lower = answer.lower()
        if "gross profit" not in answer_lower or "subtotal" not in answer_lower:
            checks.append(
                "Gross-margin profile: re-check whether the filing has a directly reported gross profit/subtotal "
                "immediately after the revenue/cost rows. If present, use that reported subtotal, include the "
                "absolute gross profit values, then compute gross margin percentages and percentage-point changes. "
                "Do not finalize with percentages only, and do not replace a reported subtotal with a component sum "
                "that omits another cost line included by the filing."
            )
    if _WORKING_CAPITAL_QUESTION_RE.search(question):
        if not _OPERATING_WORKING_CAPITAL_ANSWER_RE.search(answer):
            checks.append(
                "Working-capital/liquidity: if component rows are available, compute and label both standard net "
                "working capital (total current assets - total current liabilities) and operating/non-cash working "
                "capital from current operating asset/liability components. Use calculator.compute for the operating "
                "basis, e.g. accounts receivable + inventories + other current operating assets - accounts payable - "
                "accrued/other operating current liabilities, excluding cash and current debt/borrowings. State which "
                "basis supports the answer."
            )
    if _CAPITAL_INTENSITY_QUESTION_RE.search(question):
        if not _PPE_REVENUE_ANSWER_RE.search(answer):
            checks.append(
                "Capital-intensity/asset-intensity: include raw inputs and multiple relevant ratios when available, "
                "including capex/revenue, PP&E/revenue, PP&E/assets, capex/operating cash flow, asset turnover, "
                "and ROA. Do not finalize from one ratio alone if the filing provides the others, and do not give a "
                "qualitative-only business-description conclusion without the computed ratios."
            )
    if _LEGAL_PROCEEDINGS_QUESTION_RE.search(question):
        checks.append(
            "Legal proceedings/litigation: verify that the final answer is based on Item 3 or the legal/contingency "
            "note, not only risk factors or an income-statement charge. Search for every named material matter and "
            "carry forward disclosed settlement, accrual, charge, reserve, or range-of-loss amounts. Do not finalize "
            "from a table of contents entry, a generic Government Regulation paragraph, or one legal charge if the "
            "filing has named proceedings sections or contingency-note amounts."
        )
    if not checks:
        return False
    repeat_prefix = ""
    if checkpoint_count:
        repeat_prefix = (
            f"FINANCE ANSWER COVERAGE CHECKPOINT ATTEMPT {checkpoint_count + 1}: the previous draft still missed "
            "one or more required task-family coverage items. Do not give a qualitative-only summary and do not refer "
            "to a previous turn; either use tools for the missing facts or rewrite the answer with the missing coverage. "
        )
    content = (
        repeat_prefix
        + "FINANCE ANSWER COVERAGE CHECKPOINT: before final acceptance, audit the draft answer against the task-family "
        "coverage contract below. This checkpoint does not provide benchmark gold; it only restates the generic "
        "coverage requirements for this question type. If any required coverage is missing, use the available tools "
        "to retrieve/compute/verify it, then rewrite a self-contained final answer. If coverage is already complete, "
        "rewrite the final answer now and explicitly include the relevant facts, formulas, units, periods, and citations.\n"
        + "\n".join(f"- {check}" for check in checks)
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_finance_answer_coverage_checkpoint",
        )
    )
    for key in ("force_finalization_no_tools", "tool_surface_allowlist"):
        context.apply_edit(
            ContextEdit(
                operation="metadata.delete",
                key=key,
                source="kernel_v4_finance_answer_coverage_checkpoint",
            )
        )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="finance_answer_coverage_checkpoint_inserted",
            value=True,
            source="kernel_v4_finance_answer_coverage_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="finance_answer_coverage_checkpoint_count",
            value=checkpoint_count + 1,
            source="kernel_v4_finance_answer_coverage_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="finance_answer_coverage_checkpoint_inserted",
        turn_index=turn_index,
        data={"check_count": len(checks), "tool_surface_changed": True},
    )
    return True


def _maybe_recover_verified_numeric_generic_failure_finalization(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    del text
    if turn_index >= max_turns:
        return False
    if context.metadata.get("verified_numeric_generic_failure_recovery_inserted"):
        return False
    content = (
        "VERIFIED NUMERIC FINALIZATION CONSISTENCY RECOVERY: finance.verify_numeric has completed successfully, "
        "but your draft final answer says the answer cannot be computed, retrieved, or determined. "
        "Do not submit a generic failure after successful numeric verification. Reconcile the verified result with "
        "the observed source evidence and write the final answer now. If the verification input was actually wrong "
        "or unsupported by observed evidence, state that precise contradiction instead of a generic inability claim. "
        "Do not call tools; use only the already observed evidence, calculations, verification result, periods, units, "
        "formulas, and citations."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_verified_numeric_generic_failure_recovery",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="verified_numeric_generic_failure_recovery_inserted",
            value=True,
            source="kernel_v4_verified_numeric_generic_failure_recovery",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="force_finalization_no_tools",
            value=True,
            source="kernel_v4_verified_numeric_generic_failure_recovery",
        )
    )
    _emit(
        context,
        events,
        event_type="verified_numeric_generic_failure_recovery_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": True, "visible_tools_forced_to": 0},
    )
    return True


def _maybe_recover_generic_failure_finalization(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    del text
    if turn_index >= max_turns:
        return False
    if context.metadata.get("generic_failure_final_answer_recovery_inserted"):
        return False
    content = (
        "GENERIC FAILURE FINALIZATION RECOVERY: your draft final answer says the answer cannot be determined, "
        "retrieved, extracted, or computed. Do not submit a generic blocker while the task may still be solvable. "
        "Re-open the most relevant evidence path. If an exact official filing/exhibit URL was already observed, "
        "use document.text.extract on that exact URL with focused terms; otherwise use the available artifact/search/read "
        "or source tools to retrieve the one missing fact, then compute and verify if needed. If it truly remains blocked "
        "after this recovery, state the precise missing source-backed fact rather than a broad inability claim."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_generic_failure_final_answer_recovery",
        )
    )
    for key in ("force_finalization_no_tools", "tool_surface_allowlist"):
        context.apply_edit(
            ContextEdit(
                operation="metadata.delete",
                key=key,
                source="kernel_v4_generic_failure_final_answer_recovery",
            )
        )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="generic_failure_final_answer_recovery_inserted",
            value=True,
            source="kernel_v4_generic_failure_final_answer_recovery",
        )
    )
    _emit(
        context,
        events,
        event_type="generic_failure_final_answer_recovery_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": True},
    )
    return True


def _maybe_recover_unsupported_numeric_source_finalization(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    del text
    if turn_index >= max_turns:
        return False
    if context.metadata.get("unsupported_numeric_source_recovery_inserted"):
        return False
    content = (
        "UNSUPPORTED NUMERIC SOURCE RECOVERY: your draft final answer contains material numeric claims while "
        "admitting that one or more line items were recalled from memory, not directly observed, or only partially "
        "accessible. Do not finalize from recalled numbers. Re-open evidence acquisition, retrieve source-backed "
        "line items from the filing or structured SEC/document artifacts, compute with calculator.compute if needed, "
        "then call finance.verify_numeric again before finalizing. If a required line item truly cannot be sourced, "
        "state the precise missing source-backed fact instead of inventing or recalling it."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_unsupported_numeric_source_recovery",
        )
    )
    for key in ("force_finalization_no_tools", "tool_surface_allowlist"):
        context.apply_edit(
            ContextEdit(
                operation="metadata.delete",
                key=key,
                source="kernel_v4_unsupported_numeric_source_recovery",
            )
        )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="unsupported_numeric_source_recovery_inserted",
            value=True,
            source="kernel_v4_unsupported_numeric_source_recovery",
        )
    )
    _emit(
        context,
        events,
        event_type="unsupported_numeric_source_recovery_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": True},
    )
    return True


def _maybe_recover_process_narration_final_answer(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    if turn_index >= max_turns:
        return False
    recovery_count = int(context.metadata.get("process_narration_final_answer_recovery_count") or 0)
    if recovery_count >= 3:
        return False
    process_narration = bool(_PROCESS_NARRATION_FINAL_RE.search(text))
    self_referential = bool(_SELF_REFERENTIAL_FINAL_RE.search(text))
    if not process_narration and not self_referential:
        return False
    repeat_prefix = ""
    if recovery_count:
        repeat_prefix = (
            f"FINAL ANSWER CLEANLINESS RECOVERY ATTEMPT {recovery_count + 1}: the previous recovery still did not "
            "produce an answer body, so that draft will be discarded. "
        )
    content = (
        repeat_prefix
        + "FINAL ANSWER CLEANLINESS RECOVERY: your draft final answer is not self-contained; it uses process narration, "
        "refers to an earlier answer, or says the answer/evidence/calculation stands above. "
        "Rewrite the final answer now as the answer itself. Start with the direct answer, then include the key answer "
        "numbers, units, formula, period, method choice, comparison direction, and citations already observed. "
        "Do not say that you now have evidence, do not say 'let me provide the final answer', do not say 'as above', "
        "do not say 'the answer is complete', and do not describe the process. Use the observed evidence and citations "
        "already in the conversation. If the self-contained answer contains material finance numbers that have not yet "
        "been verified and finance.verify_numeric is visible, verify them before finalizing."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_final_answer_cleanliness_recovery",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="process_narration_final_answer_recovery_inserted",
            value=True,
            source="kernel_v4_final_answer_cleanliness_recovery",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="process_narration_final_answer_recovery_count",
            value=recovery_count + 1,
            source="kernel_v4_final_answer_cleanliness_recovery",
        )
    )
    if process_narration and not self_referential:
        context.apply_edit(
            ContextEdit(
                operation="metadata.set",
                key="force_finalization_no_tools",
                value=True,
                source="kernel_v4_final_answer_cleanliness_recovery",
            )
        )
    _emit(
        context,
        events,
        event_type="final_answer_cleanliness_recovery_inserted",
        turn_index=turn_index,
        data={"tool_surface_changed": True},
    )
    return True


def _maybe_recover_no_tool_text_tool_call_finalization(
    context: ToolUseContext,
    events: list[LoopEvent],
    text: str,
    *,
    turn_index: int,
    max_turns: int,
) -> bool:
    if turn_index >= max_turns:
        return False
    if not _looks_like_text_tool_call_only(text):
        return False
    attempts = _metadata_int(context.metadata.get("no_tool_text_tool_call_recovery_count"), default=0)
    if attempts >= _NO_TOOL_TEXT_TOOL_CALL_RECOVERY_LIMIT:
        return False
    content = (
        "FINALIZATION FORMAT RECOVERY: your previous assistant message was a text-form/DSML tool call, "
        "but no tools are exposed in finalization. Do not emit tool-call markup. Use the evidence, calculations, "
        "and verification results already in the conversation to write the final answer in ordinary prose now."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_no_tool_text_tool_call_recovery",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="no_tool_text_tool_call_recovery_count",
            value=attempts + 1,
            source="kernel_v4_no_tool_text_tool_call_recovery",
        )
    )
    _emit(
        context,
        events,
        event_type="no_tool_text_tool_call_recovery_inserted",
        turn_index=turn_index,
        data={"attempt": attempts + 1, "limit": _NO_TOOL_TEXT_TOOL_CALL_RECOVERY_LIMIT},
    )
    return True


def _extract_no_tool_text_tool_call_final_answer(text: str) -> str:
    value = str(text or "")
    if not re.search(r"(?i)finance[._-]?verify[._-]?numeric", value):
        return ""
    match = re.search(
        r"<｜｜DSML｜｜parameter\s+name=[\"']answer[\"'][^>]*>(?P<answer>.*?)</｜｜DSML｜｜parameter>",
        value,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"<parameter\s+name=[\"']answer[\"'][^>]*>(?P<answer>.*?)</parameter>",
            value,
            flags=re.DOTALL | re.IGNORECASE,
        )
    if not match:
        return ""
    answer = re.sub(r"<[^>]+>", "", match.group("answer"))
    answer = html.unescape(answer)
    answer = re.sub(r"\s+", " ", answer).strip()
    return answer if len(answer) >= 20 else ""


def _maybe_insert_source_saturation_checkpoint(
    context: ToolUseContext,
    events: list[LoopEvent],
    *,
    turn_index: int,
    max_turns: int,
) -> None:
    if context.metadata.get("source_saturation_checkpoint_inserted"):
        return
    evidence_success_count = _successful_evidence_tool_count(context.messages)
    remaining_turns = max(0, max_turns - turn_index)
    threshold = _metadata_int(
        context.metadata.get("source_saturation_evidence_success_threshold"),
        default=_SOURCE_SATURATION_EVIDENCE_SUCCESS_THRESHOLD,
    )
    if evidence_success_count < threshold and not (
        evidence_success_count >= _ENDGAME_EVIDENCE_SUCCESS_THRESHOLD
        and remaining_turns <= _SOURCE_SATURATION_LOW_TURN_REMAINING
    ):
        return
    content = (
        "SOURCE SATURATION CHECKPOINT: many evidence/source/search/read tools have already succeeded. "
        "The host will now expose only local artifact inspect/search/read, exact observed-document text extraction, provided-context parse, deterministic calculation, table, date, symbolic math, numeric verification, and endgame discovery tools. "
        "Do not continue broad SEC/company-filings retrieval, document conversion, market-data fetches, or old hidden tool aliases. "
        "Use the source facts and artifacts already observed in conversation history. If one required source-backed fact is genuinely absent from artifacts but an exact official filing/exhibit URL has already been observed, call document.text.extract on that exact URL with focused terms; otherwise search/read existing artifacts narrowly for that exact fact, compute, verify, or finalize. "
        "For acquisition, divestiture, event, or transaction-list questions, build a compact final table by fiscal year with acquired business/site or target, date, consideration/ownership percentage when available, segment/context, and source. "
        "If purchase price, cash consideration, net cash consideration, goodwill, or another transaction amount was observed, carry that amount into the final answer; ownership percentage alone is not a substitute for the disclosed consideration amount. "
        "For store-count, location-count, branch-count, or square-footage change questions, use the store data/table or comparable period filing evidence already observed, compute the latest-minus-prior change, and finalize instead of continuing broad retrieval. "
        "For revenue/sales-driver questions, if the target filing's MD&A already states the management-named drivers, synthesize those drivers now and do not keep searching for extra market or statement data unless contribution shares were explicitly requested. "
        "If the task asks multiple fiscal years, use the annual-report acquisition/divestiture note or existing artifacts for each year, then finalize; do not keep reconverting the same filings or searching the same terms."
    )
    context.apply_edit(
        ContextEdit(
            operation="message.append",
            value=ChatMessage(role="system", content=content),
            source="kernel_v4_source_saturation_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="source_saturation_checkpoint_inserted",
            value=True,
            source="kernel_v4_source_saturation_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="source_saturation_evidence_success_count",
            value=evidence_success_count,
            source="kernel_v4_source_saturation_checkpoint",
        )
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="tool_surface_allowlist",
            value=sorted(_ENDGAME_TOOL_ALLOWLIST),
            source="kernel_v4_source_saturation_checkpoint",
        )
    )
    _emit(
        context,
        events,
        event_type="source_saturation_checkpoint_inserted",
        turn_index=turn_index,
        data={
            "evidence_success_count": evidence_success_count,
            "remaining_turns": remaining_turns,
            "threshold": threshold,
            "tool_surface_changed": True,
            "tool_surface_allowlist": sorted(_ENDGAME_TOOL_ALLOWLIST),
        },
    )


def _apply_endgame_tool_surface(
    context: ToolUseContext,
    events: list[LoopEvent],
    visible_tools: list,
    *,
    turn_index: int,
) -> list:
    allowed = _metadata_tool_surface_allowlist(context)
    if not allowed:
        return visible_tools
    narrowed = [manifest for manifest in visible_tools if manifest.name in allowed]
    if len(narrowed) != len(visible_tools):
        _emit(
            context,
            events,
            event_type=(
                "endgame_tool_surface_narrowed"
                if context.metadata.get("endgame_checkpoint_inserted")
                else "tool_surface_narrowed"
            ),
            turn_index=turn_index,
            data={
                "before": len(visible_tools),
                "after": len(narrowed),
                "allowed_tool_names": sorted(allowed),
                "removed_tool_names": sorted(manifest.name for manifest in visible_tools if manifest.name not in allowed),
            },
        )
    return narrowed


def _metadata_tool_surface_allowlist(context: ToolUseContext) -> set[str]:
    value = context.metadata.get("tool_surface_allowlist")
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item}


def _metadata_int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _successful_evidence_tool_count(messages: list[ChatMessage]) -> int:
    tool_results: dict[str, ChatMessage] = {
        message.tool_call_id: message
        for message in messages
        if message.role == "tool" and isinstance(message.tool_call_id, str) and message.tool_call_id
    }
    count = 0
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            result = tool_results.get(call.tool_call_id)
            if result is None or result.metadata.get("is_error"):
                continue
            if _is_evidence_tool(call.name):
                count += 1
    return count


def _tool_seen(messages: list[ChatMessage], names: set[str]) -> bool:
    for message in messages:
        if message.role != "assistant":
            continue
        if any(call.name in names for call in message.tool_calls):
            return True
    return False


def _successful_tool_result_seen(messages: list[ChatMessage], names: set[str]) -> bool:
    tool_results: dict[str, ChatMessage] = {
        message.tool_call_id: message
        for message in messages
        if message.role == "tool" and isinstance(message.tool_call_id, str) and message.tool_call_id
    }
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            if call.name not in names:
                continue
            result = tool_results.get(call.tool_call_id)
            if result is not None and not result.metadata.get("is_error"):
                return True
    return False


def _successful_numeric_verification_seen(messages: list[ChatMessage]) -> bool:
    tool_results: dict[str, ChatMessage] = {
        message.tool_call_id: message
        for message in messages
        if message.role == "tool" and isinstance(message.tool_call_id, str) and message.tool_call_id
    }
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            if call.name != "finance.verify_numeric":
                continue
            result = tool_results.get(call.tool_call_id)
            if result is None or result.metadata.get("is_error"):
                continue
            if _numeric_verification_result_is_applicable_success(result):
                return True
    return False


def _numeric_verification_result_is_applicable_success(result: ChatMessage) -> bool:
    payload = _json_object_from_tool_message(result)
    if not payload:
        return False
    if str(payload.get("status") or "").casefold() in {"error", "failed", "blocked"}:
        return False
    if payload.get("verified") is True:
        return True
    content = payload.get("content")
    if not isinstance(content, dict):
        content = payload
    verifier_status = str(content.get("verifier_status") or "").casefold()
    verification = content.get("verification")
    verification_status = ""
    if isinstance(verification, dict):
        verification_status = str(verification.get("status") or "").casefold()
    if verifier_status in {"not_applicable", "error", "failed", "blocked"}:
        return False
    if verification_status in {"not_applicable", "error", "failed", "blocked"}:
        return False
    try:
        matched_value_count = int(content.get("matched_value_count") or 0)
    except (TypeError, ValueError):
        matched_value_count = 0
    if matched_value_count > 0:
        return True
    if verifier_status in {"ok", "passed", "verified", "success"}:
        return True
    return verification_status in {"ok", "passed", "verified", "success"}


def _json_object_from_tool_message(message: ChatMessage) -> JsonObject:
    try:
        value = json.loads(message.content)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_evidence_tool(name: str) -> bool:
    return (
        name.startswith("artifact.")
        or name.startswith("document.")
        or name.startswith("sec.edgar.")
        or name == "provided_context.parse"
        or name == "market.openbb.fetch"
    )


def _is_external_source_tool(name: str) -> bool:
    return (
        name.startswith("document.")
        or name.startswith("sec.edgar.")
        or name == "market.openbb.fetch"
    )


def _external_source_tool_stats(messages: list[ChatMessage]) -> JsonObject:
    tool_results: dict[str, ChatMessage] = {
        message.tool_call_id: message
        for message in messages
        if message.role == "tool" and isinstance(message.tool_call_id, str) and message.tool_call_id
    }
    success_by_tool: dict[str, int] = {}
    error_by_tool: dict[str, int] = {}
    for message in messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls:
            if not _is_external_source_tool(call.name):
                continue
            result = tool_results.get(call.tool_call_id)
            if result is None:
                continue
            bucket = error_by_tool if result.metadata.get("is_error") else success_by_tool
            bucket[call.name] = bucket.get(call.name, 0) + 1
    return {
        "success_by_tool": dict(sorted(success_by_tool.items())),
        "error_by_tool": dict(sorted(error_by_tool.items())),
        "total_success_count": sum(success_by_tool.values()),
        "total_error_count": sum(error_by_tool.values()),
        "max_success_count_for_one_tool": max(success_by_tool.values(), default=0),
        "max_error_count_for_one_tool": max(error_by_tool.values(), default=0),
    }


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


def _tool_progress_summary(recent_tool_calls: JsonObject) -> JsonObject:
    recent = [item for item in recent_tool_calls.get("recent", []) if isinstance(item, dict)]
    counts: dict[str, int] = {}
    successful_evidence_tools: list[str] = []
    recent_errors: list[JsonObject] = []
    for item in recent:
        tool = str(item.get("tool") or "")
        status = str(item.get("status") or "")
        family = _tool_family(tool)
        if status == "success":
            counts[family] = counts.get(family, 0) + 1
            if family == "evidence":
                successful_evidence_tools.append(tool)
        elif status == "error":
            recent_errors.append(
                {
                    "tool": tool,
                    "input_sha256": item.get("input_sha256"),
                    "result_preview": str(item.get("result_preview") or "")[:500],
                }
            )
    return {
        "successful_family_counts": counts,
        "recent_successful_evidence_tools": successful_evidence_tools[-10:],
        "recent_error_count": len(recent_errors),
        "recent_errors": recent_errors[-5:],
    }


def _tool_family(tool_name: str) -> str:
    name = str(tool_name or "").casefold()
    if name in {"calculator.compute", "math.sympy.compute", "data.table.query", "calendar.days_between"}:
        return "transform"
    if name == "finance.verify_numeric":
        return "verification"
    if name == "tool.discovery":
        return "discovery"
    evidence_markers = (
        "search",
        "read",
        "parse",
        "financial",
        "filing",
        "fetch",
        "extract",
        "convert",
    )
    if any(marker in name for marker in evidence_markers):
        return "evidence"
    return "other"


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
        if not parsed:
            return match.group(0)
        calls.extend(parsed)
        return ""

    cleaned = _DSML_TOOL_BLOCK_RE.sub(replace_block, text).strip()
    return cleaned, calls


def _looks_like_text_tool_call_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    cleaned = _DSML_TOOL_BLOCK_RE.sub("", stripped).strip()
    return cleaned == "" and bool(_DSML_TOOL_BLOCK_RE.search(stripped))


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
