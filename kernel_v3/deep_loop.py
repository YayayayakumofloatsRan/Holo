from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Protocol

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, JsonObject, Observation, ToolManifest
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.loop import LoopControllerV3, _journal_action_data
from kernel_v3.processors.contracts import JsonSchema, ProcessorStreamEvent
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.provider_tools import openai_native_tool_surface, resolve_native_tool_name
from kernel_v3.result import AgentResult
from kernel_v3.session import TaskState
from kernel_v3.tool_result_budget import (
    ToolResultReplacementState,
    apply_provider_message_replacement_view,
    apply_tool_result_replacement_budget,
    reconstruct_tool_result_replacement_state,
)
from kernel_v3.tool_runtime import tool_runtime_spec_for_action, tool_runtime_spec_for_manifest
from kernel_v3.tool_use import (
    StreamingToolExecutor,
    TOOL_DISCOVERY_NAME,
    ToolAbortSignal,
    ToolExecutionEvent,
    project_tool_result_content,
    tool_execution_control,
    tool_use_context_for_action,
)


ASSISTANT_TURN_SCHEMA = JsonSchema(
    name="assistant.turn",
    required={
        "turn_id": "str",
        "message": "str|null",
        "tool_calls": "list",
    },
    optional={
        "final_answer": "str|null",
        "final": "dict|null",
        "stop_reason": "str|null",
        "reasons": "list",
    },
)

ASSISTANT_TURN_PROMPT_CONTRACT = """Return one JSON object matching assistant.turn.
Fields:
- turn_id string
- message string or null
- tool_calls array; each item has name string, arguments object, optional
  tool_call_id string, optional reason string, optional side_effect_class string
- final_answer string or null, or final object with answer string
- stop_reason string or null
- reasons string array

The model owns semantic decomposition and tool choice. It may issue zero, one,
or multiple tool_calls in a single turn when the calls are independent or can be
observed together before the next reasoning step. The host validates tool
registration, schemas, permissions, budgets, execution, journaling, and final
termination.

Use only tools exposed in the provided tool surface. Do not ask the user unless
critical arguments are truly missing and cannot be inferred from the task,
context, or public/source lookup workflow. Tool failures are observations for
replanning. If single_agent_tool_loop_contract is present, obey its stop_rule,
answer_output_contract, and benchmark_solvability_policy before finalizing. If
numeric_verification_protocol is present, use it to decide when arithmetic,
table, symbolic, date, or domain verifier tools are needed before finalizing.
When calculator.compute is available and supported numeric inputs are known,
call calculator.compute to make the derived result trustworthy before final_answer. If
enough evidence is present, return no tool_calls and put the answer in
final_answer. Do not include markdown fences or prose outside JSON."""


_MAX_PROVIDER_TOOL_RESULT_CONTINUATIONS = 16


@dataclass(frozen=True)
class ToolCallRequest:
    tool_call_id: str
    name: str
    arguments: JsonObject
    reason: str = ""
    side_effect_class: str = "read"

    def to_action(self, *, turn_id: str, index: int) -> CandidateAction:
        return CandidateAction(
            action_id=f"act-{turn_id}-{index}-{_safe_action_id(self.name)}",
            kind="tool",
            name=self.name,
            description=self.reason or f"Run {self.name}",
            score=1.0,
            payload=dict(self.arguments),
            reasons=[self.reason] if self.reason else ["assistant_turn_tool_call"],
            side_effect_class=self.side_effect_class or "read",
        )

    def to_dict(self) -> JsonObject:
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": dict(self.arguments),
            "reason": self.reason,
            "side_effect_class": self.side_effect_class,
        }


@dataclass(frozen=True)
class ToolCallParseError:
    tool_call_id: str
    error: str
    raw_preview: str

    def to_dict(self) -> JsonObject:
        return {
            "tool_call_id": self.tool_call_id,
            "error": self.error,
            "raw_preview": self.raw_preview,
        }


@dataclass(frozen=True)
class AssistantTurn:
    turn_id: str
    message: str | None
    tool_calls: list[ToolCallRequest]
    final_answer: str | None = None
    stop_reason: str | None = None
    reasons: list[str] | None = None
    parse_errors: list[ToolCallParseError] | None = None

    def to_dict(self) -> JsonObject:
        return {
            "turn_id": self.turn_id,
            "message": self.message,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "final_answer": self.final_answer,
            "stop_reason": self.stop_reason,
            "reasons": list(self.reasons or []),
            "parse_errors": [error.to_dict() for error in self.parse_errors or []],
        }


@dataclass(frozen=True)
class AssistantTurnStream:
    turn_id: str
    index: int
    events: Iterable[ProcessorStreamEvent]
    tool_name_map: dict[str, str]
    provider_messages: list[JsonObject] = field(default_factory=list)
    continue_events: Callable[[list[JsonObject]], Iterable[ProcessorStreamEvent]] | None = None


class AssistantTurnPlanner(Protocol):
    def propose_turn(self, context: ContextBundle, feedback: Feedback | None = None) -> AssistantTurn:
        ...


class ModelAssistantTurnPlanner:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
        allowed_tool_names: set[str] | None = None,
        tool_manifests: list[ToolManifest] | None = None,
        use_streaming: bool = False,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.allowed_tool_names = set(allowed_tool_names or set())
        self.tool_manifests = list(tool_manifests or [])
        self.use_streaming = bool(use_streaming)
        self.calls: list[ContextBundle] = []

    def propose_turn(self, context: ContextBundle, feedback: Feedback | None = None) -> AssistantTurn:
        parameters = {"adapter": "ModelAssistantTurnPlanner", **_processor_budget_parameters_from_context(context)}
        if self.use_streaming:
            stream = self.stream_turn(context, feedback)
            if stream is not None:
                return _assistant_turn_from_stream_events(
                    list(stream.events),
                    index=stream.index,
                    tool_name_map=stream.tool_name_map,
                )
        self.calls.append(context)
        task_id = _task_id(context)
        run_id = _run_id(context)
        prompt = _assistant_turn_prompt(
            context,
            feedback,
            allowed_tool_names=self.allowed_tool_names,
            tool_manifests=self.tool_manifests,
        )
        outcome = self.fabric.run_json(
            task_type="assistant.turn",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=prompt,
            schema=ASSISTANT_TURN_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters=parameters,
        )
        if outcome.parsed is None:
            return AssistantTurn(
                turn_id=f"turn-{len(self.calls)}",
                message=None,
                tool_calls=[],
                final_answer=None,
                stop_reason=outcome.result.error or "processor_failed",
                reasons=["processor_failed"],
            )
        return _assistant_turn_from_json(outcome.parsed, index=len(self.calls))

    def stream_turn(
        self,
        context: ContextBundle,
        feedback: Feedback | None = None,
        *,
        step_id: str | None = None,
    ) -> AssistantTurnStream | None:
        if not self.use_streaming:
            return None
        self.calls.append(context)
        index = len(self.calls)
        task_id = _task_id(context)
        run_id = _run_id(context)
        prompt = _assistant_turn_prompt(
            context,
            feedback,
            allowed_tool_names=self.allowed_tool_names,
            tool_manifests=self.tool_manifests,
        )
        parameters = {"adapter": "ModelAssistantTurnPlanner", **_processor_budget_parameters_from_context(context)}
        requested_tool_names = _context_requested_tool_names(
            context,
            allowed_tool_names=self.allowed_tool_names,
        )
        mutable_tool_name_map: dict[str, str] = {}

        def native_surface_for(expand_tool_names: set[str]) -> Any:
            return openai_native_tool_surface(
                self.tool_manifests,
                allowed_tool_names=self.allowed_tool_names,
                expand_tool_names=expand_tool_names,
                max_tools=_context_tool_surface_limit(context),
            )

        def stream_parameters_for(
            expand_tool_names: set[str],
            *,
            continuation: bool = False,
            provider_messages_arg: list[JsonObject] | None = None,
        ) -> JsonObject:
            surface = native_surface_for(expand_tool_names)
            mutable_tool_name_map.clear()
            mutable_tool_name_map.update(surface.name_map)
            result: JsonObject = {**parameters, "streaming_planner": True}
            if continuation:
                result["streaming_planner_continuation"] = True
                result["provider_messages"] = list(provider_messages_arg or [])
            if surface.tools:
                result.update(surface.to_parameters())
                result.setdefault("tool_choice", "auto")
            return result

        stream_parameters = stream_parameters_for(requested_tool_names)
        provider_messages = [{"role": "user", "content": prompt}]

        def continue_events(messages: list[JsonObject]) -> Iterable[ProcessorStreamEvent]:
            continuation_requested_tool_names = set(requested_tool_names)
            continuation_requested_tool_names.update(
                _provider_messages_requested_tool_names(
                    messages,
                    allowed_tool_names=self.allowed_tool_names,
                )
            )
            return self.fabric.iter_stream_events(
                task_type="assistant.turn",
                task_id=task_id,
                run_id=run_id,
                context_id=context.context_id,
                prompt=prompt,
                step_id=step_id,
                provider=self.provider,
                model=self.model,
                parameters=stream_parameters_for(
                    continuation_requested_tool_names,
                    continuation=True,
                    provider_messages_arg=messages,
                ),
            )

        return AssistantTurnStream(
            turn_id=f"turn-stream-{index}",
            index=index,
            events=self.fabric.iter_stream_events(
                task_type="assistant.turn",
                task_id=task_id,
                run_id=run_id,
                context_id=context.context_id,
                prompt=prompt,
                step_id=step_id,
                provider=self.provider,
                model=self.model,
                parameters=stream_parameters,
            ),
            tool_name_map=mutable_tool_name_map,
            provider_messages=provider_messages,
            continue_events=continue_events,
        )


@dataclass(frozen=True)
class _ToolExecutionItem:
    tool_call_id: str
    action: CandidateAction
    manifest: Any
    observation: Observation
    artifact_refs: list[Any]
    context_updates: list[JsonObject]
    policy_allowed: bool
    policy_reason: str
    tool_result_artifact_ref: Any | None = None


@dataclass(frozen=True)
class _PreparedToolCall:
    call: ToolCallRequest
    turn_id: str
    action: CandidateAction
    manifest: Any
    decision: Any
    pre_exec_guard: str | None
    control: Any


@dataclass(frozen=True)
class _ToolExecutionControl:
    progress_channel_id: str
    abort_signal: ToolAbortSignal
    timeout_seconds: int | None


@dataclass(frozen=True)
class _StreamingTurnExecution:
    turn: AssistantTurn
    execution_items: list[_ToolExecutionItem] | None
    tool_calls: int
    network_fetches: int
    total_artifact_bytes: int


class DeepAgentLoopController(LoopControllerV3):
    """Claude-Code-style deep loop with model-owned multi-tool turns."""

    runtime_backend = "deep_agent_loop"

    def _drive(self, task: TaskState, feedback: Feedback | None) -> AgentResult:
        current_feedback = feedback
        step_index = 0
        tool_calls = 0
        network_fetches = 0
        total_artifact_bytes = 0
        started_at_ms = self.clock_ms()
        while True:
            step_index += 1
            step_id = f"step-{step_index}"
            step_phase = "assistant_turn"
            step_observation: Observation | None = None
            step_execution_items: list[_ToolExecutionItem] | None = None
            context = self.context_compiler.compile(task, self.journal)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=step_id,
                kind="context",
                data=redact_journal_data(context.to_dict()),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                state_delta={"context_id": context.context_id, "loop_runtime": self.runtime_backend},
            )
            scaffold_turn = _tool_result_followup_scaffold_turn(
                self.journal,
                task_id=task.task_id,
                run_id=task.run_id,
                input_text=task.input_text,
                feedback=current_feedback,
                proposed_turn=AssistantTurn(
                    turn_id=f"turn-workbench-followup-pending-{step_index}",
                    message=None,
                    tool_calls=[],
                    final_answer=None,
                    reasons=["pending_before_model_turn"],
                ),
            )
            if scaffold_turn is not None:
                turn = scaffold_turn
                preexecuted_items = None
            else:
                streamed = self._try_execute_streaming_turn(
                    task,
                    context,
                    current_feedback,
                    step_id=step_id,
                    tool_calls=tool_calls,
                    network_fetches=network_fetches,
                    total_artifact_bytes=total_artifact_bytes,
                )
                if streamed is not None:
                    turn = streamed.turn
                    preexecuted_items = streamed.execution_items
                    tool_calls = streamed.tool_calls
                    network_fetches = streamed.network_fetches
                    total_artifact_bytes = streamed.total_artifact_bytes
                else:
                    turn = self._propose_turn(context, current_feedback)
                    preexecuted_items = None
                    scaffold_turn = _tool_result_followup_scaffold_turn(
                        self.journal,
                        task_id=task.task_id,
                        run_id=task.run_id,
                        input_text=task.input_text,
                        feedback=current_feedback,
                        proposed_turn=turn,
                    )
                    if scaffold_turn is not None:
                        turn = scaffold_turn
            self._append_assistant_turn(task, turn, step_id=step_id)

            if not turn.tool_calls and not turn.parse_errors:
                step_phase = "terminal_turn"
                current_feedback = self._handle_terminal_turn(
                    task,
                    turn,
                    step_id=step_id,
                    context=context,
                )
                if self.stop_controller.should_stop(current_feedback) or current_feedback.status in {
                    "failed",
                    "needs_user_input",
                    "final_answer_ready",
                }:
                    self._append_agent_loop_turn_result(
                        task,
                        turn=turn,
                        feedback=current_feedback,
                        step_id=step_id,
                        phase=step_phase,
                        transition="return",
                        observation=step_observation,
                        execution_items=step_execution_items,
                        tool_calls=tool_calls,
                        network_fetches=network_fetches,
                        total_artifact_bytes=total_artifact_bytes,
                    )
                    return self._result(task, current_feedback, step_id=step_id)

            else:
                step_phase = "tool_turn"
                if preexecuted_items is None:
                    execution_items, tool_calls, network_fetches, total_artifact_bytes = self._execute_tool_turn(
                        task,
                        turn,
                        step_id=step_id,
                        tool_calls=tool_calls,
                        network_fetches=network_fetches,
                        total_artifact_bytes=total_artifact_bytes,
                    )
                else:
                    execution_items = preexecuted_items
                step_execution_items = execution_items
                aggregate = self._tool_batch_observation(
                    task,
                    turn=turn,
                    step_id=step_id,
                    execution_items=execution_items,
                )
                step_observation = aggregate
                self.journal.append(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    step_id=step_id,
                    kind="observation",
                    data=redact_journal_data(aggregate.to_dict()),
                    event_ref=self._last_ref(task.task_id, "event_ref"),
                    observation_ref=aggregate.observation_id,
                    state_delta={"observation_status": aggregate.status, "tool_batch_count": len(execution_items)},
                    artifact_refs=[
                        artifact.artifact_id
                        for item in execution_items
                        for artifact in item.artifact_refs
                        if hasattr(artifact, "artifact_id")
                    ],
                )
                batch_guard_reason = self._tool_batch_guard_stop_reason(aggregate)
                if batch_guard_reason is not None:
                    current_feedback = self._limit_feedback(task.run_id, batch_guard_reason)
                    self._append_feedback_record(task, current_feedback, step_id=step_id, observation=aggregate)
                    self._append_guard(
                        task,
                        batch_guard_reason,
                        step_id=step_id,
                        data={
                            "tool_batch_count": len(execution_items),
                            "tool_calls": tool_calls,
                            "network_fetches": network_fetches,
                            "source": "deep_tool_batch_result",
                        },
                    )
                    if callable(getattr(self.evaluator, "finalize_guard", None)):
                        guard_context = self.context_compiler.compile(task, self.journal)
                        current_feedback = self._finalize_guard_feedback(
                            guard_context,
                            aggregate,
                            current_feedback,
                            task=task,
                            action=self._synthetic_batch_action(turn, step_id=step_id),
                            step_id=step_id,
                        )
                    self._append_agent_loop_turn_result(
                        task,
                        turn=turn,
                        feedback=current_feedback,
                        step_id=step_id,
                        phase=step_phase,
                        transition="return_guard",
                        observation=step_observation,
                        execution_items=step_execution_items,
                        guard_stop_reason=batch_guard_reason,
                        tool_calls=tool_calls,
                        network_fetches=network_fetches,
                        total_artifact_bytes=total_artifact_bytes,
                    )
                    return self._result(task, current_feedback, step_id=step_id)

                evaluation_context = self.context_compiler.compile(task, self.journal)
                current_feedback = self.evaluator.evaluate(evaluation_context, aggregate)
                self._append_feedback_record(task, current_feedback, step_id=step_id, observation=aggregate)

                guard_reason = self._tool_batch_guard_stop_reason(aggregate)
                if guard_reason is not None and not callable(getattr(self.evaluator, "finalize_guard", None)):
                    current_feedback = self._limit_feedback(task.run_id, guard_reason)
                    self._append_feedback_record(task, current_feedback, step_id=step_id, observation=aggregate)
                    return self._result(task, current_feedback, step_id=step_id)

                resource_guard = self._resource_guard(total_artifact_bytes=total_artifact_bytes)
                if resource_guard is not None:
                    stop_reason, data = resource_guard
                    current_feedback = self._limit_feedback(task.run_id, stop_reason)
                    self._append_feedback_record(task, current_feedback, step_id=step_id, observation=aggregate)
                    self._append_guard(task, stop_reason, step_id=step_id, data=data)
                    current_feedback = self._finalize_guard_feedback(
                        evaluation_context,
                        aggregate,
                        current_feedback,
                        task=task,
                        action=self._synthetic_batch_action(turn, step_id=step_id),
                        step_id=step_id,
                    )
                    self._append_agent_loop_turn_result(
                        task,
                        turn=turn,
                        feedback=current_feedback,
                        step_id=step_id,
                        phase=step_phase,
                        transition="return_guard",
                        observation=step_observation,
                        execution_items=step_execution_items,
                        guard_stop_reason=stop_reason,
                        tool_calls=tool_calls,
                        network_fetches=network_fetches,
                        total_artifact_bytes=total_artifact_bytes,
                    )
                    return self._result(task, current_feedback, step_id=step_id)

                if self.stop_controller.should_stop(current_feedback):
                    self._append_agent_loop_turn_result(
                        task,
                        turn=turn,
                        feedback=current_feedback,
                        step_id=step_id,
                        phase=step_phase,
                        transition="return",
                        observation=step_observation,
                        execution_items=step_execution_items,
                        tool_calls=tool_calls,
                        network_fetches=network_fetches,
                        total_artifact_bytes=total_artifact_bytes,
                    )
                    return self._result(task, current_feedback, step_id=step_id)

            continuation_guard = self._continuation_guard(step_index=step_index, started_at_ms=started_at_ms)
            if continuation_guard is not None:
                stop_reason, data = continuation_guard
                current_feedback = self._limit_feedback(task.run_id, stop_reason)
                self._append_feedback_record(task, current_feedback, step_id=step_id, observation=None)
                self._append_guard(task, stop_reason, step_id=step_id, data=data)
                self._append_agent_loop_turn_result(
                    task,
                    turn=turn,
                    feedback=current_feedback,
                    step_id=step_id,
                    phase=step_phase,
                    transition="return_continuation_guard",
                    observation=step_observation,
                    execution_items=step_execution_items,
                    guard_stop_reason=stop_reason,
                    tool_calls=tool_calls,
                    network_fetches=network_fetches,
                    total_artifact_bytes=total_artifact_bytes,
                )
                return self._result(task, current_feedback, step_id=step_id)
            self._append_agent_loop_turn_result(
                task,
                turn=turn,
                feedback=current_feedback,
                step_id=step_id,
                phase=step_phase,
                transition="continue",
                observation=step_observation,
                execution_items=step_execution_items,
                tool_calls=tool_calls,
                network_fetches=network_fetches,
                total_artifact_bytes=total_artifact_bytes,
            )

    def _propose_turn(self, context: ContextBundle, feedback: Feedback | None) -> AssistantTurn:
        planner = self.planner
        proposer = getattr(planner, "propose_turn", None)
        if callable(proposer):
            turn = proposer(context, feedback)
            if isinstance(turn, AssistantTurn):
                return turn
        action = planner.propose(context, feedback)
        return _assistant_turn_from_action(action)

    def _try_execute_streaming_turn(
        self,
        task: TaskState,
        context: ContextBundle,
        feedback: Feedback | None,
        *,
        step_id: str,
        tool_calls: int,
        network_fetches: int,
        total_artifact_bytes: int,
    ) -> _StreamingTurnExecution | None:
        streamer = getattr(self.planner, "stream_turn", None)
        if not callable(streamer):
            return None
        stream = streamer(context, feedback, step_id=step_id)
        if not isinstance(stream, AssistantTurnStream):
            return None
        return self._execute_streaming_turn(
            task,
            stream,
            step_id=step_id,
            tool_calls=tool_calls,
            network_fetches=network_fetches,
            total_artifact_bytes=total_artifact_bytes,
        )

    def _execute_streaming_turn(
        self,
        task: TaskState,
        stream: AssistantTurnStream,
        *,
        step_id: str,
        tool_calls: int,
        network_fetches: int,
        total_artifact_bytes: int,
    ) -> _StreamingTurnExecution:
        text_parts: list[str] = []
        initial_final_text = ""
        terminal_text = ""
        latest_assistant_text = ""
        finish_reason: str | None = None
        parse_errors: list[ToolCallParseError] = []
        tool_chunks: dict[str, dict[str, object]] = {}
        executed_chunk_keys: set[str] = set()
        seen_tool_call_ids: set[str] = set()
        tool_call_requests: list[ToolCallRequest] = []
        execution_items: list[_ToolExecutionItem] = []
        provider_messages = [dict(message) for message in stream.provider_messages if isinstance(message, dict)]
        provider_continuation_seen = False
        provider_continuation_limited = False
        provider_continuation_rounds = 0
        active_round_items: list[_ToolExecutionItem] | None = None
        executor = StreamingToolExecutor(
            emit_event=lambda event: self._append_tool_execution_event(task, step_id=step_id, event=event),
            max_concurrency=4,
        )
        executor.begin_incremental(
            execute_one=lambda item: self._execute_prepared_tool_with_timeout(task, step_id, item),
            is_concurrency_safe=lambda item: _is_concurrency_safe(item.action, item.manifest),
            cancel_pending_on_failure=True,
            is_failed=_execution_item_failed,
            failure_cancels_siblings=_tool_failure_cancels_siblings,
            cancel_one=lambda item, reason: self._cancelled_execution_item(task, step_id=step_id, prepared=item, reason=reason),
            abort_one=lambda item, reason: self._request_prepared_tool_abort(task, step_id=step_id, prepared=item, reason=reason),
            exception_one=lambda item, exc: self._exception_execution_item(
                task,
                step_id=step_id,
                prepared=item,
                exc=exc,
            ),
        )
        try:
            def record_execution_items(items: list[_ToolExecutionItem]) -> None:
                nonlocal network_fetches, total_artifact_bytes
                for item in items:
                    execution_items.append(item)
                    if active_round_items is not None:
                        active_round_items.append(item)
                    if item.policy_allowed and item.policy_reason == "allowed" and self._is_network_action(item.action, manifest=item.manifest):
                        network_fetches += self._network_action_actual_cost(
                            item.action,
                            manifest=item.manifest,
                            observation=item.observation,
                        ) - self._network_action_cost(item.action, manifest=item.manifest)
                    total_artifact_bytes += self._estimate_artifact_bytes(
                        item.observation,
                        _execution_item_artifact_refs(item),
                    )
                    self._append_tool_execution_observation(task, step_id=step_id, item=item)

            def drain_ready_streaming_tools() -> None:
                record_execution_items(executor.drain_completed())

            def consume_provider_round(
                events: Iterable[ProcessorStreamEvent],
                *,
                round_label: str,
                initial: bool,
            ) -> tuple[dict[str, dict[str, object]], list[_ToolExecutionItem], str]:
                nonlocal active_round_items, finish_reason, initial_final_text, latest_assistant_text, terminal_text
                nonlocal tool_calls, network_fetches
                round_chunks: dict[str, dict[str, object]] = {}
                round_items: list[_ToolExecutionItem] = []
                round_text_parts: list[str] = []
                round_final_text = ""
                previous_round_items = active_round_items
                active_round_items = round_items
                try:
                    for event in events:
                        drain_ready_streaming_tools()
                        delta = event.delta
                        if event.event_type == "content_delta":
                            text = delta.get("text")
                            if isinstance(text, str):
                                round_text_parts.append(text)
                                if initial:
                                    text_parts.append(text)
                            continue
                        if event.event_type == "finish_delta":
                            reason = delta.get("finish_reason")
                            if isinstance(reason, str):
                                finish_reason = reason
                            continue
                        if event.event_type == "stream_end":
                            text = delta.get("text")
                            if isinstance(text, str):
                                round_final_text = text
                                if initial:
                                    initial_final_text = text
                            status = delta.get("status")
                            if isinstance(status, str) and status != "ok":
                                parse_error = ToolCallParseError(
                                    tool_call_id=f"{round_label}-stream-error-{event.sequence}",
                                    error=f"processor_stream_{status}",
                                    raw_preview=_preview_json_value(delta, limit=400),
                                )
                                parse_errors.append(parse_error)
                                item = self._parse_error_execution_item(
                                    task,
                                    AssistantTurn(stream.turn_id, None, []),
                                    step_id=step_id,
                                    parse_error=parse_error,
                                )
                                execution_items.append(item)
                                round_items.append(item)
                                self._append_tool_execution_observation(task, step_id=step_id, item=item)
                            continue
                        if event.event_type == "stream_error":
                            parse_error = ToolCallParseError(
                                tool_call_id=f"{round_label}-stream-error-{event.sequence}",
                                error=str(delta.get("error") or "processor_stream_error"),
                                raw_preview=_preview_json_value(delta, limit=400),
                            )
                            parse_errors.append(parse_error)
                            item = self._parse_error_execution_item(
                                task,
                                AssistantTurn(stream.turn_id, None, []),
                                step_id=step_id,
                                parse_error=parse_error,
                            )
                            execution_items.append(item)
                            round_items.append(item)
                            self._append_tool_execution_observation(task, step_id=step_id, item=item)
                            continue
                        if event.event_type != "tool_call_delta":
                            continue

                        for raw_call in _stream_tool_call_items(delta.get("tool_calls")):
                            raw_key = _stream_tool_call_key(raw_call, fallback=f"stream-tool-{len(tool_chunks) + 1}")
                            key = f"{round_label}:{raw_key}"
                            current = tool_chunks.setdefault(key, {"id": key, "name": "", "arguments": "", "raw": []})
                            round_chunks[key] = current
                            call_id = raw_call.get("id")
                            if not isinstance(call_id, str):
                                call_id = raw_call.get("tool_call_id")
                            if isinstance(call_id, str) and call_id:
                                current["id"] = call_id
                            raw_items = current.get("raw")
                            if isinstance(raw_items, list):
                                raw_items.append(raw_call)
                            function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
                            name = raw_call.get("name")
                            if not isinstance(name, str):
                                name = function.get("name") if isinstance(function, dict) else None
                            if isinstance(name, str) and name:
                                current["name"] = str(current.get("name") or "") + name
                            arguments = raw_call.get("arguments")
                            if not isinstance(arguments, str):
                                arguments = function.get("arguments") if isinstance(function, dict) else None
                            if isinstance(arguments, str) and arguments:
                                current["arguments"] = str(current.get("arguments") or "") + arguments

                        for offset, (chunk_key, chunk) in enumerate(round_chunks.items(), start=1):
                            if chunk_key in executed_chunk_keys:
                                continue
                            call = _stream_chunk_ready_tool_call(
                                chunk,
                                turn_id=stream.turn_id,
                                offset=len(tool_call_requests) + offset,
                                tool_name_map=stream.tool_name_map,
                            )
                            if call is None:
                                continue
                            executed_chunk_keys.add(chunk_key)
                            if call.tool_call_id in seen_tool_call_ids:
                                continue
                            seen_tool_call_ids.add(call.tool_call_id)
                            tool_call_requests.append(call)
                            prepared, tool_calls, network_fetches = self._prepare_tool_call(
                                task,
                                turn_id=stream.turn_id,
                                step_id=step_id,
                                call=call,
                                index=len(tool_call_requests),
                                tool_calls=tool_calls,
                                network_fetches=network_fetches,
                            )
                            executor.add_item(prepared)

                    for offset, (chunk_key, chunk) in enumerate(round_chunks.items(), start=1):
                        if chunk_key in executed_chunk_keys:
                            continue
                        tool_call_id = str(chunk.get("id") or f"{stream.turn_id}-{len(tool_call_requests) + offset}")
                        executed_chunk_keys.add(chunk_key)
                        if tool_call_id in seen_tool_call_ids:
                            continue
                        seen_tool_call_ids.add(tool_call_id)
                        parse_error = _stream_chunk_final_parse_error(
                            chunk,
                            turn_id=stream.turn_id,
                            offset=len(tool_call_requests) + offset,
                            tool_name_map=stream.tool_name_map,
                        )
                        if parse_error is None:
                            continue
                        parse_errors.append(parse_error)
                        tool_calls += 1
                        item = self._parse_error_execution_item(
                            task,
                            AssistantTurn(stream.turn_id, None, []),
                            step_id=step_id,
                            parse_error=parse_error,
                        )
                        execution_items.append(item)
                        round_items.append(item)
                        self._append_tool_execution_observation(task, step_id=step_id, item=item)

                    record_execution_items(executor.finish_remaining())
                finally:
                    active_round_items = previous_round_items

                round_text = "".join(round_text_parts) or round_final_text
                if round_text:
                    latest_assistant_text = round_text
                    if not round_items:
                        terminal_text = _provider_terminal_text(round_text, index=stream.index)
                return round_chunks, round_items, round_text

            round_chunks, round_items, round_text = consume_provider_round(
                stream.events,
                round_label="initial",
                initial=True,
            )
            provider_continuation_guard_reason = self._execution_items_guard_stop_reason(round_items)
            while round_items and callable(stream.continue_events):
                if provider_continuation_guard_reason is not None:
                    provider_continuation_limited = True
                    self.journal.append(
                        task_id=task.task_id,
                        run_id=task.run_id,
                        step_id=step_id,
                        kind="provider_conversation_update",
                        data=redact_journal_data(
                            {
                                "schema": "holo.kernel_v3.provider_tool_result_continuation_budget_guard.v1",
                                "turn_id": stream.turn_id,
                                "stop_reason": provider_continuation_guard_reason,
                                "tool_result_count": len(round_items),
                                "host_boundary": (
                                    "provider continuation stopped because a streamed tool result hit a host budget guard; "
                                    "outer deep loop will finalize or fail from the journaled batch"
                                ),
                            }
                        ),
                        event_ref=self._last_ref(task.task_id, "event_ref"),
                        state_delta={
                            "provider_conversation_update": "budget_guard",
                            "stop_reason": provider_continuation_guard_reason,
                        },
                    )
                    break
                if provider_continuation_rounds >= _MAX_PROVIDER_TOOL_RESULT_CONTINUATIONS:
                    provider_continuation_limited = True
                    self.journal.append(
                        task_id=task.task_id,
                        run_id=task.run_id,
                        step_id=step_id,
                        kind="provider_conversation_update",
                        data=redact_journal_data(
                            {
                                "schema": "holo.kernel_v3.provider_tool_result_continuation_limit.v1",
                                "turn_id": stream.turn_id,
                                "max_continuations": _MAX_PROVIDER_TOOL_RESULT_CONTINUATIONS,
                                "tool_result_count": len(round_items),
                                "host_boundary": (
                                    "provider continuation limit reached; outer deep loop will replan from journaled tool results"
                                ),
                            }
                        ),
                        event_ref=self._last_ref(task.task_id, "event_ref"),
                        state_delta={"provider_conversation_update": "continuation_limit"},
                    )
                    break
                continuation_messages = _provider_tool_result_continuation_messages(
                    provider_messages,
                    assistant_text=round_text,
                    tool_chunks=round_chunks,
                    execution_items=round_items,
                )
                if not continuation_messages:
                    break
                provider_continuation_rounds += 1
                provider_continuation_seen = True
                provider_messages = continuation_messages
                self.journal.append(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    step_id=step_id,
                    kind="provider_conversation_update",
                    data=redact_journal_data(
                        {
                            "schema": "holo.kernel_v3.provider_tool_result_continuation.v1",
                            "turn_id": stream.turn_id,
                            "continuation_round": provider_continuation_rounds,
                            "message_count": len(continuation_messages),
                            "tool_result_count": sum(1 for item in continuation_messages if item.get("role") == "tool"),
                            "host_boundary": (
                                "provider continuation receives bounded tool-result messages; "
                                "host still validates all future tool calls"
                            ),
                        }
                    ),
                    event_ref=self._last_ref(task.task_id, "event_ref"),
                    state_delta={"provider_conversation_update": "tool_results_injected"},
                )
                round_chunks, round_items, round_text = consume_provider_round(
                    stream.continue_events(continuation_messages),
                    round_label=f"continuation-{provider_continuation_rounds}",
                    initial=False,
                )
                provider_continuation_guard_reason = self._execution_items_guard_stop_reason(round_items)
        finally:
            executor.close()

        text = "".join(text_parts) or initial_final_text
        final_text = terminal_text or latest_assistant_text or text
        parsed = _try_parse_json_object(text)
        if parsed is not None and not tool_chunks and not parse_errors:
            return _StreamingTurnExecution(
                turn=_assistant_turn_from_json(parsed, index=stream.index),
                execution_items=None,
                tool_calls=tool_calls,
                network_fetches=network_fetches,
                total_artifact_bytes=total_artifact_bytes,
            )
        turn = AssistantTurn(
            turn_id=stream.turn_id,
            message=(final_text or text) or None,
            tool_calls=tool_call_requests,
            final_answer=(terminal_text or None) if provider_continuation_seen and not parse_errors else (None if tool_call_requests or parse_errors else (text or None)),
            stop_reason="processor_stream_error" if parse_errors and not tool_call_requests else finish_reason,
            reasons=[
                "processor_stream",
                "incremental_tool_execution",
                *(["provider_tool_result_continuation"] if provider_continuation_seen else []),
                *(["provider_tool_result_continuation_limit"] if provider_continuation_limited else []),
                *([finish_reason] if finish_reason else []),
            ],
            parse_errors=parse_errors,
        )
        return _StreamingTurnExecution(
            turn=turn,
            execution_items=execution_items,
            tool_calls=tool_calls,
            network_fetches=network_fetches,
            total_artifact_bytes=total_artifact_bytes,
        )

    def _handle_terminal_turn(
        self,
        task: TaskState,
        turn: AssistantTurn,
        *,
        step_id: str,
        context: ContextBundle,
    ) -> Feedback:
        if turn.final_answer is None and turn.stop_reason:
            feedback = Feedback(
                feedback_id=f"fb-{task.run_id}-{turn.stop_reason}-{step_id}",
                run_id=task.run_id,
                status="failed",
                stop_reason=turn.stop_reason,
                answer=None,
                missing_evidence=list(turn.reasons or [turn.stop_reason]),
            )
            self._append_feedback_record(task, feedback, step_id=step_id, observation=None)
            return feedback

        action = CandidateAction(
            action_id=f"act-{turn.turn_id}-respond",
            kind="respond",
            name=None,
            description=turn.message or turn.final_answer or "respond",
            score=1.0,
            payload={"text": turn.final_answer or turn.message or ""},
            reasons=list(turn.reasons or ["assistant_turn_final"]),
            side_effect_class="none",
        )
        manifest = self.tool_registry.manifest_for_action(action)
        self._record_action(task, action, step_id=step_id, manifest=manifest)
        decision = self.policy_gate.validate(run_id=task.run_id, action=action, manifest=manifest)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="policy_decision",
            data=redact_journal_data(decision.to_dict()),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            state_delta={"policy_allowed": decision.allowed},
        )
        tool_result = self.tool_registry.execute_with_artifacts(
            action,
            policy_decision=None,
            execution_context={
                "task_id": task.task_id,
                "run_id": task.run_id,
                "step_id": step_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
            },
        )
        observation = self._bind_observation(task.run_id, action, tool_result.observation)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="observation",
            data=redact_journal_data(observation.to_dict()),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            observation_ref=observation.observation_id,
            state_delta={"observation_status": observation.status},
            artifact_refs=[artifact.artifact_id for artifact in tool_result.artifact_refs],
        )
        evaluation_context = self.context_compiler.compile(task, self.journal)
        feedback = self.evaluator.evaluate(evaluation_context, observation)
        self._append_feedback(task, feedback, action=action, observation=observation, step_id=step_id)
        return feedback

    def _execute_tool_turn(
        self,
        task: TaskState,
        turn: AssistantTurn,
        *,
        step_id: str,
        tool_calls: int,
        network_fetches: int,
        total_artifact_bytes: int,
    ) -> tuple[list[_ToolExecutionItem], int, int, int]:
        execution_items: list[_ToolExecutionItem] = []
        for parse_error in turn.parse_errors or []:
            tool_calls += 1
            item = self._parse_error_execution_item(task, turn, step_id=step_id, parse_error=parse_error)
            execution_items.append(item)
            self._append_tool_execution_observation(task, step_id=step_id, item=item)

        prepared: list[_PreparedToolCall] = []
        for index, call in enumerate(turn.tool_calls, start=1):
            prepared_call, tool_calls, network_fetches = self._prepare_tool_call(
                task,
                turn_id=turn.turn_id,
                step_id=step_id,
                call=call,
                index=index,
                tool_calls=tool_calls,
                network_fetches=network_fetches,
            )
            prepared.append(prepared_call)

        executor = StreamingToolExecutor(
            emit_event=lambda event: self._append_tool_execution_event(task, step_id=step_id, event=event)
        )
        batch_items = executor.execute_batches(
            prepared,
            execute_one=lambda item: self._execute_prepared_tool_with_timeout(task, step_id, item),
            is_concurrency_safe=lambda item: _is_concurrency_safe(item.action, item.manifest),
            cancel_pending_on_failure=True,
            is_failed=_execution_item_failed,
            failure_cancels_siblings=_tool_failure_cancels_siblings,
            cancel_one=lambda item, reason: self._cancelled_execution_item(task, step_id=step_id, prepared=item, reason=reason),
            abort_one=lambda item, reason: self._request_prepared_tool_abort(task, step_id=step_id, prepared=item, reason=reason),
            exception_one=lambda item, exc: self._exception_execution_item(
                task,
                step_id=step_id,
                prepared=item,
                exc=exc,
            ),
        )
        for item in batch_items:
            execution_items.append(item)
            if item.policy_allowed and item.policy_reason == "allowed" and self._is_network_action(item.action, manifest=item.manifest):
                network_fetches += self._network_action_actual_cost(
                    item.action,
                    manifest=item.manifest,
                    observation=item.observation,
                ) - self._network_action_cost(item.action, manifest=item.manifest)
            total_artifact_bytes += self._estimate_artifact_bytes(
                item.observation,
                _execution_item_artifact_refs(item),
            )
            self._append_tool_execution_observation(task, step_id=step_id, item=item)
        return execution_items, tool_calls, network_fetches, total_artifact_bytes

    def _execute_prepared_tool_with_timeout(
        self,
        task: TaskState,
        step_id: str,
        prepared: _PreparedToolCall,
    ) -> _ToolExecutionItem:
        timeout = prepared.control.timeout_seconds
        if timeout is None:
            return self._execute_prepared_tool(task, step_id, prepared)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._execute_prepared_tool, task, step_id, prepared)
        timed_out = False
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            timed_out = True
            prepared.control.abort_signal.request("tool_timeout")
            self._append_tool_execution_event(
                task,
                step_id=step_id,
                event=_prepared_tool_execution_event(
                    "abort_requested",
                    prepared,
                    detail={"reason": "tool_timeout", "timeout_seconds": timeout},
                ),
            )
            try:
                return future.result(timeout=0.25)
            except FutureTimeoutError:
                future.cancel()
                return self._timeout_execution_item(task, step_id=step_id, prepared=prepared, reason="tool_timeout")
        finally:
            pool.shutdown(wait=not timed_out, cancel_futures=True)

    def _request_prepared_tool_abort(
        self,
        task: TaskState,
        *,
        step_id: str,
        prepared: _PreparedToolCall,
        reason: str,
    ) -> None:
        prepared.control.abort_signal.request(reason)
        self._append_tool_execution_event(
            task,
            step_id=step_id,
            event=_prepared_tool_execution_event(
                "abort_requested",
                prepared,
                detail={
                    "reason": reason,
                    "source": "streaming_tool_executor",
                    "host_boundary": "running sibling tool received cooperative abort after a failure that cancels siblings",
                },
            ),
        )

    def _prepare_tool_call(
        self,
        task: TaskState,
        *,
        turn_id: str,
        step_id: str,
        call: ToolCallRequest,
        index: int,
        tool_calls: int,
        network_fetches: int,
    ) -> tuple[_PreparedToolCall, int, int]:
        action = call.to_action(turn_id=turn_id, index=index)
        manifest = self.tool_registry.manifest_for_action(action)
        self._record_action(task, action, step_id=step_id, manifest=manifest)
        decision = self.policy_gate.validate(run_id=task.run_id, action=action, manifest=manifest)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="policy_decision",
            data=redact_journal_data(decision.to_dict()),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            state_delta={"policy_allowed": decision.allowed},
        )
        pre_exec_guard = None
        if decision.allowed:
            pre_exec_guard = self._pre_execution_guard(
                action,
                manifest=manifest,
                tool_calls=tool_calls,
                network_fetches=network_fetches,
            )
        if decision.allowed and pre_exec_guard is None:
            tool_calls += 1
            if self._is_network_action(action, manifest=manifest):
                network_fetches += self._network_action_cost(action, manifest=manifest)
        runtime_spec = tool_runtime_spec_for_action(action, manifest)
        progress_channel_id = f"tool-progress-{task.run_id}-{_safe_action_id(action.action_id)}"
        abort_signal = ToolAbortSignal(signal_id=f"tool-abort-{task.run_id}-{_safe_action_id(action.action_id)}")
        return (
            _PreparedToolCall(
                call=call,
                turn_id=turn_id,
                action=action,
                manifest=manifest,
                decision=decision,
                pre_exec_guard=pre_exec_guard,
                control=_ToolExecutionControl(
                    progress_channel_id=progress_channel_id,
                    abort_signal=abort_signal,
                    timeout_seconds=runtime_spec.timeout_seconds,
                ),
            ),
            tool_calls,
            network_fetches,
        )

    def _execute_prepared_tool(
        self,
        task: TaskState,
        step_id: str,
        prepared: _PreparedToolCall,
    ) -> _ToolExecutionItem:
        action = prepared.action
        manifest = prepared.manifest
        decision = prepared.decision
        pre_exec_guard = prepared.pre_exec_guard
        if not decision.allowed:
            observation = _with_tool_call_id(self._blocked_observation(task.run_id, action, decision.reason), prepared.call.tool_call_id)
            tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
                task,
                turn_id=prepared.turn_id,
                step_id=step_id,
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                observation=observation,
            )
            return _ToolExecutionItem(
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                manifest=manifest,
                observation=observation,
                artifact_refs=[],
                context_updates=[],
                policy_allowed=False,
                policy_reason=decision.reason,
                tool_result_artifact_ref=tool_result_artifact_ref,
            )
        if pre_exec_guard is not None:
            observation = _with_tool_call_id(self._guard_observation(task.run_id, action, pre_exec_guard), prepared.call.tool_call_id)
            tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
                task,
                turn_id=prepared.turn_id,
                step_id=step_id,
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                observation=observation,
            )
            return _ToolExecutionItem(
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                manifest=manifest,
                observation=observation,
                artifact_refs=[],
                context_updates=[],
                policy_allowed=False,
                policy_reason=pre_exec_guard,
                tool_result_artifact_ref=tool_result_artifact_ref,
            )
        tool_context = tool_use_context_for_action(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            thread_id=task.thread_id,
            input_text=task.input_text,
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=manifest,
            policy_decision=decision,
            allowed_tool_names=[manifest.name for manifest in self.tool_registry.manifests()],
            progress_channel_id=prepared.control.progress_channel_id,
            abort_signal_id=prepared.control.abort_signal.signal_id,
            timeout_seconds=prepared.control.timeout_seconds,
        )
        with tool_execution_control(
            progress_channel_id=prepared.control.progress_channel_id,
            abort_signal=prepared.control.abort_signal,
            emit_event=lambda event: self._append_tool_execution_event(task, step_id=step_id, event=event),
        ):
            tool_result = self.tool_registry.execute_with_artifacts(
                action,
                policy_decision=decision,
                execution_context=tool_context.to_execution_context(),
            )
        observation = _with_tool_call_id(
            self._bind_observation(task.run_id, action, tool_result.observation),
            prepared.call.tool_call_id,
        )
        tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
            task,
            turn_id=prepared.turn_id,
            step_id=step_id,
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            observation=observation,
        )
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=manifest,
            observation=observation,
            artifact_refs=list(tool_result.artifact_refs),
            context_updates=_tool_context_updates_for_result(
                tool_result,
                observation=observation,
                action=action,
                manifest=manifest,
                tool_result_artifact_ref=tool_result_artifact_ref,
            ),
            policy_allowed=True,
            policy_reason=decision.reason,
            tool_result_artifact_ref=tool_result_artifact_ref,
        )

    def _parse_error_execution_item(
        self,
        task: TaskState,
        turn: AssistantTurn,
        *,
        step_id: str,
        parse_error: ToolCallParseError,
    ) -> _ToolExecutionItem:
        action = CandidateAction(
            action_id=f"act-{turn.turn_id}-{step_id}-parse-error-{_safe_action_id(parse_error.tool_call_id)}",
            kind="tool",
            name="__invalid_tool_call__",
            description=f"Invalid tool call: {parse_error.error}",
            score=0.0,
            payload=parse_error.to_dict(),
            reasons=["invalid_tool_call"],
            side_effect_class="none",
        )
        observation = Observation(
            observation_id=f"obs-{action.action_id}",
            run_id=task.run_id,
            kind="tool_call_parse_error",
            status="failed",
            source="deep_agent_loop",
            content={
                "reason": "invalid_tool_call",
                **parse_error.to_dict(),
            },
            observed_at_ms=self.clock_ms(),
            action_id=action.action_id,
            tool_call_id=parse_error.tool_call_id,
        )
        return _ToolExecutionItem(
            tool_call_id=parse_error.tool_call_id,
            action=action,
            manifest=None,
            observation=observation,
            artifact_refs=[],
            context_updates=[],
            policy_allowed=False,
            policy_reason="invalid_tool_call",
        )

    def _cancelled_execution_item(
        self,
        task: TaskState,
        *,
        step_id: str,
        prepared: _PreparedToolCall,
        reason: str,
    ) -> _ToolExecutionItem:
        action = prepared.action
        observation = Observation(
            observation_id=f"obs-{action.action_id}-{reason}",
            run_id=task.run_id,
            kind="tool_call_cancelled",
            status="cancelled",
            source="deep_agent_loop",
            content={
                "reason": reason,
                "host_boundary": "pending sibling tool call was cancelled before execution; running tools are not interrupted",
            },
            observed_at_ms=self.clock_ms(),
            action_id=action.action_id,
            tool_call_id=prepared.call.tool_call_id,
        )
        tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
            task,
            turn_id=prepared.turn_id,
            step_id=step_id,
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            observation=observation,
        )
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=prepared.manifest,
            observation=observation,
            artifact_refs=[],
            context_updates=[],
            policy_allowed=False,
            policy_reason=reason,
            tool_result_artifact_ref=tool_result_artifact_ref,
        )

    def _timeout_execution_item(
        self,
        task: TaskState,
        *,
        step_id: str,
        prepared: _PreparedToolCall,
        reason: str,
    ) -> _ToolExecutionItem:
        action = prepared.action
        observation = Observation(
            observation_id=f"obs-{action.action_id}-{reason}",
            run_id=task.run_id,
            kind="tool_call_timeout",
            status="failed",
            source="deep_agent_loop",
            content={
                "reason": reason,
                "timeout_seconds": prepared.control.timeout_seconds,
                "abort_signal_id": prepared.control.abort_signal.signal_id,
                "interrupt_behavior": tool_runtime_spec_for_action(action, prepared.manifest).interrupt_behavior,
                "host_boundary": (
                    "host requested cooperative abort after timeout; Python threads cannot be force-killed, "
                    "so non-cooperative tools must implement their own bounded subprocess/network timeout"
                ),
            },
            observed_at_ms=self.clock_ms(),
            action_id=action.action_id,
            tool_call_id=prepared.call.tool_call_id,
        )
        tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
            task,
            turn_id=prepared.turn_id,
            step_id=step_id,
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            observation=observation,
        )
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=prepared.manifest,
            observation=observation,
            artifact_refs=[],
            context_updates=[],
            policy_allowed=False,
            policy_reason=reason,
            tool_result_artifact_ref=tool_result_artifact_ref,
        )

    def _exception_execution_item(
        self,
        task: TaskState,
        *,
        step_id: str,
        prepared: _PreparedToolCall,
        exc: Exception,
    ) -> _ToolExecutionItem:
        action = prepared.action
        reason = "tool_host_exception"
        observation = Observation(
            observation_id=f"obs-{action.action_id}-{reason}",
            run_id=task.run_id,
            kind=reason,
            status="failed",
            source="deep_agent_loop",
            content={
                "reason": reason,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
                "host_boundary": (
                    "host converted a tool execution exception into a normal tool_result observation; "
                    "the agent loop remains alive and the model/evaluator can decide recovery"
                ),
            },
            observed_at_ms=self.clock_ms(),
            action_id=action.action_id,
            tool_call_id=prepared.call.tool_call_id,
        )
        tool_result_artifact_ref = self._write_tool_result_artifact_for_observation(
            task,
            turn_id=prepared.turn_id,
            step_id=step_id,
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            observation=observation,
        )
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=prepared.manifest,
            observation=observation,
            artifact_refs=[],
            context_updates=[],
            policy_allowed=False,
            policy_reason=reason,
            tool_result_artifact_ref=tool_result_artifact_ref,
        )

    def _append_tool_execution_event(self, task: TaskState, *, step_id: str, event: ToolExecutionEvent) -> None:
        data = event.to_dict()
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="tool_execution_event",
            data=redact_journal_data(data),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=event.action_id or None,
            state_delta={
                "tool_execution_event": event.event_type,
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_name,
                "status": event.status,
            },
        )

    def _append_tool_execution_observation(self, task: TaskState, *, step_id: str, item: _ToolExecutionItem) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="observation",
            data=redact_journal_data(item.observation.to_dict()),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=item.action.action_id,
            observation_ref=item.observation.observation_id,
            state_delta={
                "observation_status": item.observation.status,
                "tool_call_id": item.tool_call_id,
            },
            artifact_refs=_artifact_ref_ids(_visible_execution_item_artifact_refs(item)),
        )
        for update in item.context_updates:
            update_id = str(update.get("update_id") or f"tool-context-{item.observation.observation_id}")
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=step_id,
                kind="tool_context_update",
                data=redact_journal_data({**update, "update_id": update_id}),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=item.action.action_id,
                observation_ref=item.observation.observation_id,
                state_delta={
                    "tool_context_update": str(update.get("update_type") or "observation_context"),
                    "tool": str(update.get("tool") or item.action.name or ""),
                },
                artifact_refs=[str(ref) for ref in update.get("artifact_refs", [])[:8]]
                if isinstance(update.get("artifact_refs"), list)
                else [],
            )

    def _tool_batch_observation(
        self,
        task: TaskState,
        *,
        turn: AssistantTurn,
        step_id: str,
        execution_items: list[_ToolExecutionItem],
    ) -> Observation:
        statuses = {item.observation.status for item in execution_items}
        status = "ok" if statuses == {"ok"} else "failed" if statuses == {"failed"} else "partial"
        results: list[JsonObject] = []
        for item in execution_items:
            artifact_refs = _artifact_ref_ids(_execution_item_artifact_refs(item))
            tool_result_artifact = item.tool_result_artifact_ref or self._write_tool_result_artifact(task, turn=turn, step_id=step_id, item=item)
            result: JsonObject = {
                "tool_call_id": item.tool_call_id,
                "action_id": item.action.action_id,
                "tool": item.action.name,
                "status": item.observation.status,
                "source": item.observation.source,
                "kind": item.observation.kind,
                "observation_id": item.observation.observation_id,
                "policy": item.policy_reason,
                "artifact_refs": artifact_refs,
                "content_preview": _preview_json_value(item.observation.content),
                "content_projection": project_tool_result_content(item.observation.content).to_dict(),
                "context_update_refs": [
                    str(update.get("update_id"))
                    for update in item.context_updates
                    if update.get("update_id")
                ],
            }
            if tool_result_artifact is not None:
                artifact_id = str(tool_result_artifact.artifact_id)
                result["tool_result_artifact_id"] = artifact_id
                result["artifact_refs"] = _ordered_unique_strings([*artifact_refs, artifact_id])
            results.append(result)
        results, new_replacements = apply_tool_result_replacement_budget(
            results,
            self._tool_result_replacement_state(task.task_id),
        )
        return Observation(
            observation_id=f"obs-{turn.turn_id}-{step_id}-tool-batch",
            run_id=task.run_id,
            kind="tool_batch_result",
            status=status,
            source="deep_agent_loop",
            content={
                "schema": "holo.kernel_v3.deep_tool_batch_result.v1",
                "turn_id": turn.turn_id,
                "tool_call_count": len(execution_items),
                "results": results,
                "new_replacements": new_replacements,
                "replacement_state": self._tool_result_replacement_state(task.task_id).to_dict(),
                **_assistant_continuation_for_batch(turn),
            },
            observed_at_ms=self.clock_ms(),
            action_id=None,
            tool_call_id=None,
        )

    def _write_tool_result_artifact(
        self,
        task: TaskState,
        *,
        turn: AssistantTurn,
        step_id: str,
        item: _ToolExecutionItem,
    ) -> object | None:
        return self._write_tool_result_artifact_for_observation(
            task,
            turn_id=turn.turn_id,
            step_id=step_id,
            tool_call_id=item.tool_call_id,
            action=item.action,
            observation=item.observation,
        )

    def _write_tool_result_artifact_for_observation(
        self,
        task: TaskState,
        *,
        turn_id: str,
        step_id: str,
        tool_call_id: str,
        action: CandidateAction,
        observation: Observation,
    ) -> object | None:
        artifact_store = getattr(self.context_compiler, "artifact_store", None)
        if artifact_store is None or not hasattr(artifact_store, "write_blob"):
            return None
        payload = {
            "schema": "holo.kernel_v3.tool_result_full.v1",
            "task_id": task.task_id,
            "run_id": task.run_id,
            "step_id": step_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "action_id": action.action_id,
            "tool": action.name,
            "observation": observation.to_dict(),
        }
        return artifact_store.write_blob(
            kind="tool_result_full",
            payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            mime_type="application/json",
            metadata={
                "task_id": task.task_id,
                "run_id": task.run_id,
                "step_id": step_id,
                "turn_id": turn_id,
                "tool_call_id": tool_call_id,
                "tool": str(action.name or ""),
                "observation_id": observation.observation_id,
            },
        )

    def _tool_result_replacement_state(self, task_id: str) -> ToolResultReplacementState:
        state_by_task = getattr(self, "_tool_result_replacement_state_by_task", None)
        if not isinstance(state_by_task, dict):
            state_by_task = {}
            setattr(self, "_tool_result_replacement_state_by_task", state_by_task)
        state = state_by_task.get(task_id)
        if not isinstance(state, ToolResultReplacementState):
            state = reconstruct_tool_result_replacement_state(self.journal.records(task_id=task_id, kind="observation"))
            state_by_task[task_id] = state
        return state

    def _append_assistant_turn(self, task: TaskState, turn: AssistantTurn, *, step_id: str) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="assistant_turn",
            data=redact_journal_data(
                {
                    **turn.to_dict(),
                    "schema": "holo.kernel_v3.assistant_turn.v1",
                    "loop_runtime": self.runtime_backend,
                    "tool_call_count": len(turn.tool_calls),
                }
            ),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            state_delta={"assistant_turn": turn.turn_id, "assistant_turn_tool_calls": len(turn.tool_calls)},
        )

    def _append_feedback_record(
        self,
        task: TaskState,
        feedback: Feedback,
        *,
        step_id: str,
        observation: Observation | None,
    ) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="feedback",
            data=redact_journal_data(feedback.to_dict()),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            observation_ref=observation.observation_id if observation is not None else None,
            feedback_ref=feedback.feedback_id,
            state_delta={"feedback_status": feedback.status},
        )

    def _append_agent_loop_turn_result(
        self,
        task: TaskState,
        *,
        turn: AssistantTurn,
        feedback: Feedback | None,
        step_id: str,
        phase: str,
        transition: str,
        observation: Observation | None,
        execution_items: list[_ToolExecutionItem] | None,
        tool_calls: int,
        network_fetches: int,
        total_artifact_bytes: int,
        guard_stop_reason: str | None = None,
    ) -> None:
        execution_items = list(execution_items or [])
        tool_status_counts: dict[str, int] = {}
        tool_kind_counts: dict[str, int] = {}
        failed_tools: list[JsonObject] = []
        tool_results: list[JsonObject] = []
        for item in execution_items:
            status = str(item.observation.status or "")
            kind = str(item.observation.kind or "")
            tool_status_counts[status] = tool_status_counts.get(status, 0) + 1
            tool_kind_counts[kind] = tool_kind_counts.get(kind, 0) + 1
            summary: JsonObject = {
                "tool_call_id": item.tool_call_id,
                "action_id": item.action.action_id,
                "tool": str(item.action.name or ""),
                "status": status,
                "kind": kind,
                "policy": item.policy_reason,
                "observation_id": item.observation.observation_id,
            }
            if item.tool_result_artifact_ref is not None and hasattr(item.tool_result_artifact_ref, "artifact_id"):
                summary["tool_result_artifact_id"] = str(item.tool_result_artifact_ref.artifact_id)
            tool_results.append(summary)
            if status != "ok":
                failed_tools.append(summary)

        observation_data: JsonObject = {}
        if observation is not None:
            observation_data = {
                "observation_id": observation.observation_id,
                "kind": observation.kind,
                "status": observation.status,
                "source": observation.source,
            }

        feedback_data: JsonObject = {}
        if feedback is not None:
            feedback_data = {
                "feedback_id": feedback.feedback_id,
                "status": feedback.status,
                "stop_reason": feedback.stop_reason,
                "answer_present": bool(feedback.answer),
                "missing_evidence": list(feedback.missing_evidence[:24]),
            }

        data: JsonObject = {
            "schema": "holo.kernel_v3.agent_loop_turn_result.v1",
            "runtime": self.runtime_backend,
            "phase": phase,
            "transition": transition,
            "turn_id": turn.turn_id,
            "assistant_tool_call_count": len(turn.tool_calls),
            "assistant_parse_error_count": len(turn.parse_errors or []),
            "assistant_final_answer_present": bool(turn.final_answer),
            "assistant_stop_reason": turn.stop_reason,
            "assistant_reasons": list(turn.reasons or [])[:12],
            "tool_result_count": len(tool_results),
            "tool_status_counts": tool_status_counts,
            "tool_kind_counts": tool_kind_counts,
            "failed_tool_count": len(failed_tools),
            "failed_tools": failed_tools[:8],
            "tool_results": tool_results[:12],
            "observation": observation_data,
            "feedback": feedback_data,
            "guard_stop_reason": guard_stop_reason,
            "counters": {
                "tool_calls": tool_calls,
                "network_fetches": network_fetches,
                "total_artifact_bytes": total_artifact_bytes,
            },
            "host_boundary": (
                "per-turn lifecycle result copied from mature query-loop practice: "
                "model owns next semantic step, host records structured transition and recovery state"
            ),
        }
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="agent_loop_turn_result",
            data=redact_journal_data(data),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            observation_ref=observation.observation_id if observation is not None else None,
            feedback_ref=feedback.feedback_id if feedback is not None else None,
            state_delta={
                "agent_loop_phase": phase,
                "agent_loop_transition": transition,
                "agent_loop_feedback_status": feedback.status if feedback is not None else None,
                "stop_reason": guard_stop_reason or (feedback.stop_reason if feedback is not None else None),
            },
        )

    def _tool_batch_guard_stop_reason(self, observation: Observation) -> str | None:
        direct = self._guard_stop_reason(observation)
        if direct is not None:
            return direct
        if observation.kind != "tool_batch_result":
            return None
        content = observation.content if isinstance(observation.content, dict) else {}
        return _host_budget_guard_reason_from_batch_payload(content)

    def _execution_items_guard_stop_reason(self, execution_items: list[_ToolExecutionItem]) -> str | None:
        for item in execution_items:
            reason = self._guard_stop_reason(item.observation)
            if reason is not None:
                return reason
            if item.policy_reason in _HOST_BUDGET_GUARD_REASONS:
                return item.policy_reason
        return None

    def _synthetic_batch_action(self, turn: AssistantTurn, *, step_id: str) -> CandidateAction:
        return CandidateAction(
            action_id=f"act-{turn.turn_id}-{step_id}-batch",
            kind="tool",
            name="__tool_batch__",
            description="deep loop tool batch",
            score=1.0,
            payload={"turn_id": turn.turn_id},
            reasons=["deep_agent_loop_tool_batch"],
            side_effect_class="read",
        )


_HOST_BUDGET_GUARD_REASONS = {"max_tool_calls", "max_network_fetches"}


def _host_budget_guard_reason_from_batch_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    reason = payload.get("reason")
    if isinstance(reason, str) and reason in _HOST_BUDGET_GUARD_REASONS:
        return reason
    nested_content = payload.get("content")
    if isinstance(nested_content, dict):
        nested_reason = _host_budget_guard_reason_from_batch_payload(nested_content)
        if nested_reason is not None:
            return nested_reason
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    for item in results:
        nested_reason = _host_budget_guard_reason_from_batch_result(item)
        if nested_reason is not None:
            return nested_reason
    return None


def _host_budget_guard_reason_from_batch_result(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    status = str(item.get("status") or "")
    source = str(item.get("source") or "")
    kind = str(item.get("kind") or "")
    policy = item.get("policy")
    policy_text = str(policy) if isinstance(policy, str) else ""
    is_host_guard = status == "blocked" and (
        source == "loop_guard"
        or kind == "host_guard"
        or policy_text in _HOST_BUDGET_GUARD_REASONS
    )
    if not is_host_guard:
        return None
    if policy_text in _HOST_BUDGET_GUARD_REASONS:
        return policy_text
    preview = item.get("content_preview")
    if isinstance(preview, str) and preview:
        try:
            parsed = json.loads(preview)
        except json.JSONDecodeError:
            parsed = None
        nested_reason = _host_budget_guard_reason_from_batch_payload(parsed)
        if nested_reason is not None:
            return nested_reason
    nested_reason = _host_budget_guard_reason_from_batch_payload(item)
    if nested_reason in _HOST_BUDGET_GUARD_REASONS:
        return nested_reason
    return None


def _assistant_turn_from_action(action: CandidateAction) -> AssistantTurn:
    if action.kind == "tool" and action.name:
        return AssistantTurn(
            turn_id=action.action_id,
            message=action.description,
            tool_calls=[
                ToolCallRequest(
                    tool_call_id=action.action_id,
                    name=action.name,
                    arguments=dict(action.payload),
                    reason="; ".join(action.reasons) or action.description,
                    side_effect_class=action.side_effect_class,
                )
            ],
            reasons=list(action.reasons),
        )
    if action.kind == "ask_user":
        return AssistantTurn(
            turn_id=action.action_id,
            message=_payload_text(action.payload) or action.description,
            tool_calls=[],
            final_answer=_payload_text(action.payload) or action.description,
            stop_reason="needs_user_input",
            reasons=list(action.reasons),
        )
    return AssistantTurn(
        turn_id=action.action_id,
        message=_payload_text(action.payload) or action.description,
        tool_calls=[],
        final_answer=_payload_text(action.payload) or action.description,
        reasons=list(action.reasons),
    )


def _assistant_turn_from_json(data: JsonObject, *, index: int = 1) -> AssistantTurn:
    turn_id = str(data.get("turn_id") or f"turn-{index}").strip() or f"turn-{index}"
    raw_calls = data.get("tool_calls")
    tool_calls: list[ToolCallRequest] = []
    parse_errors: list[ToolCallParseError] = []
    if isinstance(raw_calls, list):
        for call_index, raw_call in enumerate(raw_calls, start=1):
            fallback_call_id = f"{turn_id}-{call_index}"
            if not isinstance(raw_call, dict):
                parse_errors.append(
                    ToolCallParseError(
                        tool_call_id=fallback_call_id,
                        error="tool_call_not_object",
                        raw_preview=_preview_json_value(raw_call, limit=400),
                    )
                )
                continue
            tool_call_id = str(raw_call.get("tool_call_id") or raw_call.get("id") or fallback_call_id)
            name = str(raw_call.get("name") or raw_call.get("tool") or "").strip()
            if not name:
                parse_errors.append(
                    ToolCallParseError(
                        tool_call_id=tool_call_id,
                        error="missing_tool_name",
                        raw_preview=_preview_json_value(raw_call, limit=400),
                    )
                )
                continue
            arguments = raw_call.get("arguments") if "arguments" in raw_call else {}
            if not isinstance(arguments, dict) and "payload" in raw_call:
                arguments = raw_call.get("payload")
            if not isinstance(arguments, dict):
                parse_errors.append(
                    ToolCallParseError(
                        tool_call_id=tool_call_id,
                        error="invalid_tool_arguments",
                        raw_preview=_preview_json_value(raw_call, limit=400),
                    )
                )
                continue
            tool_calls.append(
                ToolCallRequest(
                    tool_call_id=tool_call_id,
                    name=name,
                    arguments=_json_object(arguments),
                    reason=str(raw_call.get("reason") or raw_call.get("description") or "").strip(),
                    side_effect_class=str(raw_call.get("side_effect_class") or "read").strip() or "read",
                )
            )
    final_answer = data.get("final_answer")
    if not isinstance(final_answer, str):
        final = data.get("final")
        if isinstance(final, dict) and isinstance(final.get("answer"), str):
            final_answer = final["answer"]
        else:
            final_answer = None
    reasons = data.get("reasons")
    return AssistantTurn(
        turn_id=turn_id,
        message=data.get("message") if isinstance(data.get("message"), str) else None,
        tool_calls=tool_calls,
        final_answer=final_answer,
        stop_reason=data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else None,
        reasons=[str(item) for item in reasons] if isinstance(reasons, list) else [],
        parse_errors=parse_errors,
    )


def _assistant_turn_from_stream_events(
    events: list[ProcessorStreamEvent],
    *,
    index: int = 1,
    tool_name_map: dict[str, str] | JsonObject | None = None,
) -> AssistantTurn:
    turn_id = f"turn-stream-{index}"
    text_parts: list[str] = []
    final_text = ""
    finish_reason: str | None = None
    stream_errors: list[ToolCallParseError] = []
    tool_chunks: dict[str, dict[str, object]] = {}

    for event in sorted(events, key=lambda item: item.sequence):
        delta = event.delta
        if event.event_type == "content_delta":
            text = delta.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif event.event_type == "tool_call_delta":
            for raw_call in _stream_tool_call_items(delta.get("tool_calls")):
                key = _stream_tool_call_key(raw_call, fallback=f"stream-tool-{len(tool_chunks) + 1}")
                current = tool_chunks.setdefault(key, {"id": key, "name": "", "arguments": "", "raw": []})
                call_id = raw_call.get("id")
                if not isinstance(call_id, str):
                    call_id = raw_call.get("tool_call_id")
                if isinstance(call_id, str) and call_id:
                    current["id"] = call_id
                raw_items = current.get("raw")
                if isinstance(raw_items, list):
                    raw_items.append(raw_call)
                function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
                name = raw_call.get("name")
                if not isinstance(name, str):
                    name = function.get("name") if isinstance(function, dict) else None
                if isinstance(name, str) and name:
                    current["name"] = str(current.get("name") or "") + name
                arguments = raw_call.get("arguments")
                if not isinstance(arguments, str):
                    arguments = function.get("arguments") if isinstance(function, dict) else None
                if isinstance(arguments, str) and arguments:
                    current["arguments"] = str(current.get("arguments") or "") + arguments
        elif event.event_type == "finish_delta":
            reason = delta.get("finish_reason")
            if isinstance(reason, str):
                finish_reason = reason
        elif event.event_type == "stream_end":
            text = delta.get("text")
            if isinstance(text, str):
                final_text = text
            status = delta.get("status")
            if isinstance(status, str) and status != "ok":
                stream_errors.append(
                    ToolCallParseError(
                        tool_call_id=f"stream-error-{event.sequence}",
                        error=f"processor_stream_{status}",
                        raw_preview=_preview_json_value(delta, limit=400),
                    )
                )
        elif event.event_type == "stream_error":
            stream_errors.append(
                ToolCallParseError(
                    tool_call_id=f"stream-error-{event.sequence}",
                    error=str(delta.get("error") or "processor_stream_error"),
                    raw_preview=_preview_json_value(delta, limit=400),
                )
            )

    text = "".join(text_parts) or final_text
    parsed = _try_parse_json_object(text)
    if parsed is not None and not tool_chunks and not stream_errors:
        return _assistant_turn_from_json(parsed, index=index)

    tool_calls: list[ToolCallRequest] = []
    parse_errors = list(stream_errors)
    for offset, chunk in enumerate(tool_chunks.values(), start=1):
        tool_call_id = str(chunk.get("id") or f"{turn_id}-{offset}")
        name = resolve_native_tool_name(str(chunk.get("name") or "").strip(), tool_name_map)
        raw_arguments = str(chunk.get("arguments") or "").strip()
        if not name:
            parse_errors.append(
                ToolCallParseError(
                    tool_call_id=tool_call_id,
                    error="missing_tool_name",
                    raw_preview=_preview_json_value(chunk, limit=400),
                )
            )
            continue
        if not raw_arguments:
            parse_errors.append(
                ToolCallParseError(
                    tool_call_id=tool_call_id,
                    error="missing_tool_arguments",
                    raw_preview=_preview_json_value(chunk, limit=400),
                )
            )
            continue
        arguments = _try_parse_json_object(raw_arguments)
        if arguments is None:
            parse_errors.append(
                ToolCallParseError(
                    tool_call_id=tool_call_id,
                    error="invalid_tool_arguments",
                    raw_preview=_preview_json_value(chunk, limit=400),
                )
            )
            continue
        tool_calls.append(
            ToolCallRequest(
                tool_call_id=tool_call_id,
                name=name,
                arguments=arguments,
                reason="processor_stream_tool_call",
                side_effect_class="read",
            )
        )

    return AssistantTurn(
        turn_id=turn_id,
        message=text or None,
        tool_calls=tool_calls,
        final_answer=None if tool_calls or parse_errors else (text or None),
        stop_reason="processor_stream_error" if stream_errors and not tool_calls else finish_reason,
        reasons=["processor_stream"] + ([finish_reason] if finish_reason else []),
        parse_errors=parse_errors,
    )


def _workbench_followup_scaffold_turn(
    journal: Any,
    *,
    task_id: str,
    run_id: str,
    input_text: str,
    feedback: Feedback | None,
    proposed_turn: AssistantTurn,
) -> AssistantTurn | None:
    if not _feedback_requires_retrieval_workbench_followup(feedback):
        return None
    record = _latest_workbench_decision_record(journal, task_id=task_id, run_id=run_id)
    if record is None:
        return None
    data = record.data if isinstance(record.data, dict) else {}
    decision = str(data.get("decision") or "")
    if data.get("status") != "ok" or decision not in {"continue", "fail_with_limitations"}:
        return None
    if _network_budget_guard_seen_after_record(
        journal,
        task_id=task_id,
        run_id=run_id,
        record_id=str(getattr(record, "record_id", "") or ""),
    ):
        return None
    next_document_targets = _json_string_list(data.get("next_document_targets"))
    next_queries = _ordered_unique_strings([*_json_string_list(data.get("next_queries")), *next_document_targets])
    source_families = _json_string_list(data.get("next_source_families"))
    missing_slots = _ordered_unique_strings(
        [
            *_json_string_list(data.get("missing_slots")),
            *_json_string_list(data.get("semantic_missing_slots")),
            *_json_string_list(feedback.missing_evidence if feedback is not None else []),
        ]
    )
    if not next_queries and not source_families:
        return None
    attempted = _attempted_retrieval_queries(journal, task_id=task_id, run_id=run_id)
    direct_targets = [target for target in next_document_targets if _looks_like_http_url(target)]
    proposed_retrieval_calls = [call for call in proposed_turn.tool_calls if call.name == "retrieval.run"]
    if proposed_retrieval_calls and not direct_targets:
        return None
    if proposed_retrieval_calls and direct_targets:
        proposed_primary = {
            str(call.arguments.get("query") or "").strip().casefold()
            for call in proposed_retrieval_calls
            if isinstance(call.arguments, dict)
        }
        if any(target.casefold() in proposed_primary for target in direct_targets):
            return None
    selected_query = next((target for target in direct_targets if target.casefold() not in attempted), "")
    if not selected_query:
        selected_query = next((query for query in next_queries if query.casefold() not in attempted), "")
    if not selected_query:
        selected_query = _source_family_followup_query(
            input_text,
            source_families=source_families,
            missing_slots=missing_slots,
        )
        if not selected_query or selected_query.casefold() in attempted:
            return None
    source_urls = _ordered_unique_strings([*direct_targets, *[item for item in next_queries if _looks_like_http_url(item)]])
    task_goal = _compact_task_goal(input_text)
    queries = _ordered_unique_strings([selected_query, *direct_targets, *next_queries])[:8]
    metadata: JsonObject = {
        "host_scaffold": "model_workbench_followup",
        "host_scaffold_role": "execute_model_workbench_route_without_selecting_answer_facts",
        "workbench_followup": True,
        "workbench_decision_ref": getattr(record, "record_id", None),
        "workbench_source_decision": decision,
        "task_goal": task_goal,
        "workbench_reason_summary": str(data.get("reason_summary") or "")[:500],
        "semantic_missing_slots": missing_slots[:24],
        "preferred_source_families": source_families[:16],
        "next_document_targets": next_document_targets[:16],
        "research_profile": "finance_fundamentals",
        "source_authority_requirement": "primary",
    }
    if source_urls:
        metadata["source_urls"] = source_urls[:16]
    return AssistantTurn(
        turn_id=f"turn-workbench-followup-{_safe_action_id(str(getattr(record, 'record_id', 'decision')))}",
        message="Executing retrieval workbench follow-up.",
        tool_calls=[
            ToolCallRequest(
                tool_call_id="tc-workbench-followup-retrieval",
                name="retrieval.run",
                arguments={
                    "query": selected_query,
                    "queries": queries,
                    "search_strategy": "structured",
                    "max_queries": max(3, min(8, len(queries))),
                    "max_sources": 24,
                    "max_fetches": 12,
                    "max_spans_per_document": 8,
                    "metadata": metadata,
                },
                reason="retrieval_workbench_followup",
                side_effect_class="network",
            )
        ],
        final_answer=None,
        stop_reason=None,
        reasons=[
            "host_scaffold_model_workbench_followup",
            "retrieval_workbench_followup",
            f"source_turn:{proposed_turn.turn_id}",
        ],
    )


def _tool_result_followup_scaffold_turn(
    journal: Any,
    *,
    task_id: str,
    run_id: str,
    input_text: str,
    feedback: Feedback | None,
    proposed_turn: AssistantTurn,
) -> AssistantTurn | None:
    slot_bind = _finance_slot_bind_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text=input_text,
        feedback=feedback,
        proposed_turn=proposed_turn,
    )
    if slot_bind is not None:
        return slot_bind
    return _workbench_followup_scaffold_turn(
        journal,
        task_id=task_id,
        run_id=run_id,
        input_text=input_text,
        feedback=feedback,
        proposed_turn=proposed_turn,
    )


def _finance_slot_bind_followup_scaffold_turn(
    journal: Any,
    *,
    task_id: str,
    run_id: str,
    input_text: str,
    feedback: Feedback | None,
    proposed_turn: AssistantTurn,
) -> AssistantTurn | None:
    if not _feedback_requires_finance_slot_bind_followup(feedback):
        return None
    record, data = _latest_finance_slot_bind_followup_record(journal, task_id=task_id, run_id=run_id)
    if record is None:
        return None
    missing_slots = _json_string_list(data.get("missing_slots"))
    next_action = data.get("next_action") if isinstance(data.get("next_action"), dict) else {}
    tool_name = str(next_action.get("tool") or next_action.get("name") or "").strip()
    if not tool_name:
        return None
    arguments = next_action.get("arguments") if isinstance(next_action.get("arguments"), dict) else {}
    arguments = dict(arguments)
    reason = str(next_action.get("reason") or data.get("reason_summary") or "finance_slot_bind_followup").strip()
    if tool_name == "retrieval.run":
        arguments = _finance_slot_bind_retrieval_arguments(
            input_text,
            missing_slots=missing_slots,
            next_action=next_action,
            reason=reason,
            existing=arguments,
        )
    if not arguments:
        return None
    if tool_name == "retrieval.run":
        query = str(arguments.get("query") or "").strip().casefold()
        if query and query in _attempted_retrieval_queries(journal, task_id=task_id, run_id=run_id):
            return None
    metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
    metadata = {
        **dict(metadata),
        "host_scaffold": "model_finance_slot_bind_followup",
        "host_scaffold_role": "execute_model_declared_next_action_without_selecting_answer_facts",
        "finance_slot_bind_followup": True,
        "finance_slot_bind_ref": getattr(record, "record_id", None),
        "semantic_missing_slots": missing_slots[:24],
        "model_next_action": _compact_json_object(next_action, limit=12),
        "task_goal": _compact_task_goal(input_text),
        "source_authority_requirement": "primary",
    }
    arguments["metadata"] = metadata
    attempted = _attempted_tool_payloads(journal, task_id=task_id, run_id=run_id, tool_name=tool_name)
    fingerprint = _payload_fingerprint(arguments)
    proposed_same_tool = [call for call in proposed_turn.tool_calls if call.name == tool_name]
    if proposed_same_tool and any(_payload_fingerprint(call.arguments) == fingerprint for call in proposed_same_tool):
        return None
    if fingerprint in attempted:
        return None
    return AssistantTurn(
        turn_id=f"turn-finance-slot-bind-followup-{_safe_action_id(str(getattr(record, 'record_id', 'slot-bind')))}",
        message="Executing finance slot-bind follow-up.",
        tool_calls=[
            ToolCallRequest(
                tool_call_id="tc-finance-slot-bind-followup",
                name=tool_name,
                arguments=arguments,
                reason=reason or "finance_slot_bind_followup",
                side_effect_class=_next_action_side_effect_class(tool_name),
            )
        ],
        final_answer=None,
        stop_reason=None,
        reasons=[
            "host_scaffold_model_finance_slot_bind_followup",
            "finance_slot_bind_followup",
            f"source_turn:{proposed_turn.turn_id}",
        ],
    )


def _feedback_requires_finance_slot_bind_followup(feedback: Feedback | None) -> bool:
    if feedback is None or feedback.status != "continue":
        return False
    normalized = {str(item).strip().lower().replace("-", "_") for item in feedback.missing_evidence}
    return "finance_slot_bind_followup" in normalized


def _latest_finance_slot_bind_followup_record(journal: Any, *, task_id: str, run_id: str) -> tuple[Any | None, JsonObject]:
    records = getattr(journal, "records", None)
    if not callable(records):
        return None, {}
    for record in reversed(records(task_id=task_id)):
        if getattr(record, "run_id", None) != run_id:
            continue
        data = record.data if isinstance(record.data, dict) else {}
        payload: JsonObject = {}
        if getattr(record, "kind", None) == "finance_slot_bind":
            payload = dict(data)
        elif getattr(record, "kind", None) == "observation" and str(data.get("source") or "") == "tool:finance.slot_bind":
            content = data.get("content") if isinstance(data.get("content"), dict) else {}
            payload = dict(content)
        if not payload:
            continue
        missing_slots = _json_string_list(payload.get("missing_slots"))
        next_action = payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {}
        decision = str(payload.get("decision") or payload.get("status") or "").strip().casefold()
        if missing_slots and next_action and decision in {
            "needs_more_evidence",
            "missing_slots",
            "failed",
            "need_more_evidence",
            "continue",
        }:
            return record, payload
    return None, {}


def _finance_slot_bind_retrieval_arguments(
    input_text: str,
    *,
    missing_slots: list[str],
    next_action: JsonObject,
    reason: str,
    existing: JsonObject,
) -> JsonObject:
    result = dict(existing)
    raw_queries = [
        *_json_string_list(next_action.get("queries")),
        *_json_string_list(next_action.get("next_queries")),
        *_json_string_list(next_action.get("source_urls")),
        *_json_string_list(next_action.get("target_urls")),
        *_json_string_list(next_action.get("next_document_targets")),
    ]
    for key in ("query", "url", "source_url", "target_url", "document_url"):
        value = next_action.get(key)
        if isinstance(value, str) and value.strip():
            raw_queries.insert(0, value.strip())
    query = str(result.get("query") or "").strip()
    if not query:
        query = next((item for item in raw_queries if item), "")
    if not query:
        query = _source_family_followup_query(
            input_text,
            source_families=_json_string_list(next_action.get("source_families")),
            missing_slots=[*missing_slots, reason],
        )
    if not query:
        return {}
    queries = _ordered_unique_strings([query, *raw_queries])[:8]
    result.setdefault("query", query)
    result.setdefault("queries", queries)
    result.setdefault("search_strategy", "structured")
    result.setdefault("max_queries", max(3, min(8, len(queries))))
    result.setdefault("max_sources", 24)
    result.setdefault("max_fetches", 12)
    result.setdefault("max_spans_per_document", 8)
    return result


def _attempted_tool_payloads(journal: Any, *, task_id: str, run_id: str, tool_name: str) -> set[str]:
    records = getattr(journal, "records", None)
    if not callable(records):
        return set()
    attempted: set[str] = set()
    for record in records(task_id=task_id, kind="action"):
        if getattr(record, "run_id", None) != run_id:
            continue
        data = record.data if isinstance(record.data, dict) else {}
        if data.get("name") != tool_name:
            continue
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        attempted.add(_payload_fingerprint(payload))
    return attempted


def _payload_fingerprint(value: object) -> str:
    try:
        return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(_compact_json_object(value, limit=24), ensure_ascii=False, sort_keys=True)


def _compact_json_object(value: object, *, limit: int) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= limit:
            break
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[str(key)] = item if not isinstance(item, str) else item[:500]
        elif isinstance(item, list):
            result[str(key)] = item[:8]
        elif isinstance(item, dict):
            result[str(key)] = _compact_json_object(item, limit=8)
    return result


def _next_action_side_effect_class(tool_name: str) -> str:
    name = tool_name.casefold()
    if name in {"retrieval.run", "sec.edgar.financials", "document.docling.convert", "web.search", "web.fetch"}:
        return "network"
    if "write" in name:
        return "write"
    if "shell" in name or "bash" in name:
        return "shell"
    return "read"


def _feedback_requires_retrieval_workbench_followup(feedback: Feedback | None) -> bool:
    if feedback is None or feedback.status != "continue":
        return False
    normalized = {str(item).strip().lower().replace("-", "_") for item in feedback.missing_evidence}
    return "retrieval_workbench_followup" in normalized


def _latest_workbench_decision_record(journal: Any, *, task_id: str, run_id: str) -> Any | None:
    records = getattr(journal, "records", None)
    if not callable(records):
        return None
    for record in reversed(records(task_id=task_id, kind="retrieval_workbench_decision")):
        if getattr(record, "run_id", None) == run_id:
            return record
    return None


def _attempted_retrieval_queries(journal: Any, *, task_id: str, run_id: str) -> set[str]:
    records = getattr(journal, "records", None)
    if not callable(records):
        return set()
    attempted: set[str] = set()
    for record in records(task_id=task_id, kind="action"):
        if getattr(record, "run_id", None) != run_id:
            continue
        data = record.data if isinstance(record.data, dict) else {}
        if data.get("name") != "retrieval.run":
            continue
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        query = payload.get("query")
        if isinstance(query, str) and query.strip():
            attempted.add(query.strip().casefold())
    return attempted


def _network_budget_guard_seen_after_record(
    journal: Any,
    *,
    task_id: str,
    run_id: str,
    record_id: str,
) -> bool:
    if not record_id:
        return False
    records = getattr(journal, "records", None)
    if not callable(records):
        return False
    seen_anchor = False
    for record in records(task_id=task_id):
        if getattr(record, "run_id", None) != run_id:
            continue
        if getattr(record, "record_id", None) == record_id:
            seen_anchor = True
            continue
        if not seen_anchor or getattr(record, "kind", None) != "observation":
            continue
        data = record.data if isinstance(record.data, dict) else {}
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        if data.get("kind") == "host_guard" and content.get("reason") == "max_network_fetches":
            return True
    return False


def _source_family_followup_query(input_text: str, *, source_families: list[str], missing_slots: list[str]) -> str:
    text = _compact_task_goal(input_text)
    families = " ".join(source_families[:6])
    missing = " ".join(missing_slots[:6])
    query = " ".join(part for part in [text, missing, families] if part).strip()
    return query[:500]


def _compact_task_goal(input_text: str) -> str:
    text = " ".join(str(input_text or "").split())
    if len(text) > 260:
        text = text[:260].rsplit(" ", 1)[0]
    return text


def _json_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ordered_unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _looks_like_http_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def _assistant_turn_prompt(
    context: ContextBundle,
    feedback: Feedback | None,
    *,
    allowed_tool_names: set[str],
    tool_manifests: list[ToolManifest] | None = None,
) -> str:
    requested_tool_names = _context_requested_tool_names(
        context,
        allowed_tool_names=allowed_tool_names,
    )
    payload = {
        "contract": ASSISTANT_TURN_PROMPT_CONTRACT,
        "single_agent_tool_loop_contract": _single_agent_tool_loop_contract_for_turn(context),
        "context": _compact_context_for_turn(context),
        "feedback": feedback.to_dict() if feedback is not None else None,
        "continuation_contract": _feedback_continuation_contract(feedback),
        "numeric_verification_protocol": _numeric_verification_protocol_for_turn(allowed_tool_names),
        "allowed_tool_names": sorted(allowed_tool_names),
        "tool_surface": _assistant_turn_tool_surface(
            tool_manifests or [],
            allowed_tool_names=allowed_tool_names,
            expand_tool_names=requested_tool_names,
            max_visible_tools=_context_tool_surface_limit(context),
        ),
        "tool_call_protocol": {
            "tool_call_shape": {
                "tool_call_id": "stable id for this call, unique within the turn",
                "name": "registered tool name",
                "arguments": "object matching tool input_schema",
                "reason": "why this call is needed now",
                "side_effect_class": "none|read|network|write|shell|destructive",
            },
            "host_rule": "The host will validate and return every tool result as observations before the next turn.",
        },
    }
    sanitized = apply_provider_message_replacement_view(payload)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True, indent=2)


def _numeric_verification_protocol_for_turn(allowed_tool_names: set[str]) -> JsonObject:
    numeric_tools = [
        tool
        for tool in (
            "calculator.compute",
            "data.table.query",
            "math.sympy.compute",
            "calendar.days_between",
            "finance.verify_numeric",
        )
        if tool in allowed_tool_names
    ]
    return {
        "schema": "holo.kernel_v3.numeric_verification_protocol.v1",
        "decision_owner": "model",
        "host_role": "validate_execute_record_return_observations",
        "available_numeric_tools": numeric_tools,
        "applies_to": [
            "arithmetic",
            "ratios",
            "percentages",
            "bps differences",
            "growth rates",
            "margins",
            "averages",
            "multiples",
            "rankings",
            "unit conversions",
            "date or fiscal-day counts",
            "any material derived numeric answer",
        ],
        "tool_selection_guidance": [
            "Use calculator.compute for ordinary deterministic arithmetic once numeric inputs are supported.",
            "If calculator.compute is available and the task needs a material derived number, actively call calculator.compute before final_answer; the calculator observation is the trustworthy numeric basis.",
            "Use data.table.query for filtering, grouping, aggregation, ranking, joins, or table-derived calculations.",
            "Use math.sympy.compute for symbolic or high-precision math beyond ordinary arithmetic.",
            "Use calendar.days_between when the numeric result depends on date intervals.",
            "Use domain verifier tools such as finance.verify_numeric when available for final numeric support.",
        ],
        "mandatory_next_action_when_inputs_known": (
            "When supported input values for a required derived number are present and calculator.compute is allowed, "
            "the next assistant turn should call calculator.compute with expression, variables, unit, formula_name, "
            "and input_fact_ids when available. Final synthesis should wait for the calculator observation."
        ),
        "finalization_guidance": (
            "Do not finalize a material derived numeric conclusion from mental arithmetic while an appropriate "
            "numeric tool is available. If inputs are missing, retrieve/parse/query them or state the input gap; "
            "if a numeric tool is unavailable, state the formula and limitation."
        ),
    }


def _single_agent_tool_loop_contract_for_turn(context: ContextBundle) -> JsonObject:
    state = context.state if isinstance(context.state, dict) else {}
    directive = state.get("agent_runtime_directive") if isinstance(state.get("agent_runtime_directive"), dict) else {}
    finance_contract = (
        directive.get("finance_agent_loop_contract")
        if isinstance(directive.get("finance_agent_loop_contract"), dict)
        else {}
    )
    finance_requirements = (
        directive.get("finance_question_requirements")
        if isinstance(directive.get("finance_question_requirements"), dict)
        else {}
    )
    if not finance_contract and not finance_requirements:
        return {}
    return {
        "schema": "holo.kernel_v3.single_agent_tool_loop_contract.v1",
        "decision_owner": "model",
        "host_role": "validate_execute_record_verify_gate_only",
        "tool_use_boundary": (
            "All retrieval, slot binding, table operations, calculator calls, and numeric verification "
            "needed for the final answer must appear as model-requested tool_calls inside this loop."
        ),
        "finalizer_boundary": (
            "The host finalizer may synthesize from observed loop outputs and reject unsupported answers, "
            "but it must not create hidden finance tool results or compute missing formulas after final_answer."
        ),
        "required_for_finance_numeric_answers": [
            "source-backed facts in observations or artifact reads",
            "finance.slot_bind when line-item, period, or fact selection is nontrivial",
            "calculator.compute or data.table.query for deterministic transforms after inputs are supported",
            "finance.verify_numeric on the draft answer when numeric verification is available",
            "do not substitute raw source numbers for a requested derived metric when the requested ratio, margin, growth rate, difference, average, DIO/DSO/DPO, multiple, bps, CAGR, ranking, or comparison still lacks FormulaTrace/calculator output",
        ],
        "benchmark_solvability_policy": (
            "For benchmark-like FB/FQA tasks with named entities, periods, filings, or provided context, "
            "assume the task is intended to be solvable. Do not return generic inability until relevant "
            "allowed source families, parser/table tools, artifact reads, calculation tools, and verifier paths "
            "have been tried or are blocked by explicit policy, budget, or repeated tool failures."
        ),
        "answer_output_contract": {
            "required_elements": [
                "direct answer to the exact question",
                "entity/security and period basis",
                "source-backed facts with evidence/citation refs",
                "formula or transform expression for calculations",
                "calculator.compute FormulaTrace for derived finance numbers when the tool is available",
                "finance.verify_numeric observation for final material numeric claims when the tool is available",
                "computed result with unit and rounding basis",
                "comparison or qualitative judgment when requested",
                "limitations only for genuinely missing or non-applicable evidence",
            ],
            "forbidden_elements": [
                "unsupported numbers, thresholds, or peer benchmarks",
                "generic failure text when partial cited evidence can answer",
                "mental arithmetic when calculator.compute or data.table.query is available",
                "unstated substitutions for requested line items, periods, or average/ending basis",
            ],
        },
        "stop_rule": (
            "Return final_answer only after required evidence, formula traces, and verification observations "
            "are present, or after stating explicit non-applicability or evidence limitations. "
            "For finance calculation, ratio, efficiency, ranking, margin, growth, multiple, bps, or comparison tasks, "
            "do not return final_answer without calculator.compute and finance.verify_numeric observations when those tools are available and inputs are present. "
            "If a tool returns no result or fails while budget remains, replan through another relevant allowed tool or artifact path before finalizing."
        ),
        "gold_reference_visibility": "benchmark gold/reference material is never model-visible",
        "finance_contract_schema": finance_contract.get("schema"),
        "required_tool_categories": _json_string_list(finance_requirements.get("required_tool_categories")),
        "risk_flags": _json_string_list(finance_requirements.get("risk_flags")),
    }


def _assistant_turn_tool_surface(
    tool_manifests: list[ToolManifest],
    *,
    allowed_tool_names: set[str],
    expand_tool_names: set[str] | None = None,
    max_visible_tools: int | None = None,
) -> JsonObject:
    allowed = set(allowed_tool_names)
    expand = set(expand_tool_names or set())
    visible: list[JsonObject] = []
    deferred: list[JsonObject] = []
    for manifest in tool_manifests:
        if manifest.name not in allowed:
            continue
        runtime = tool_runtime_spec_for_manifest(manifest)
        brief: JsonObject = {
            "name": manifest.name,
            "description": _preview_text(str(manifest.description or ""), 220),
            "side_effect_class": manifest.side_effect_class,
            "permissions_required": list(manifest.permissions_required)[:8],
            "runtime": {
                "concurrency_safe": runtime.concurrency_safe,
                "read_only": runtime.read_only,
                "destructive": runtime.destructive,
                "open_world": runtime.open_world,
                "timeout_seconds": runtime.timeout_seconds,
                "failure_cancels_siblings": runtime.failure_cancels_siblings,
                "max_result_size_chars": runtime.max_result_size_chars,
                "should_defer": runtime.should_defer,
                "always_load": runtime.always_load,
            },
        }
        force_visible = manifest.name in expand
        if runtime.should_defer and not runtime.always_load and not force_visible:
            deferred.append(
                {
                    **brief,
                    "schema_available_via": TOOL_DISCOVERY_NAME,
                    "defer_rule": "Call tool.discovery when this tool may be needed and exact arguments/schema are not already known.",
                }
            )
            continue
        visible_item = {**brief, "input_schema": _compact_tool_input_schema(manifest.input_schema)}
        if force_visible and runtime.should_defer and not runtime.always_load:
            visible_item["visibility_reason"] = "context_requested"
        visible.append(visible_item)
    visible = sorted(
        visible,
        key=lambda item: (
            not bool((item.get("runtime") if isinstance(item.get("runtime"), dict) else {}).get("always_load")),
            item.get("name") not in expand,
            str(item.get("name") or ""),
        ),
    )
    if max_visible_tools is not None and max_visible_tools >= 0 and len(visible) > max_visible_tools:
        overflow = visible[max_visible_tools:]
        visible = visible[:max_visible_tools]
        for item in overflow:
            deferred.append(
                {
                    **{key: value for key, value in item.items() if key != "input_schema"},
                    "schema_available_via": TOOL_DISCOVERY_NAME,
                    "defer_rule": "Tool omitted from visible surface by token budget; call tool.discovery before using it.",
                    "defer_reason": "tool_surface_budget",
                }
            )
    return {
        "schema": "holo.kernel_v3.assistant_turn_tool_surface.v1",
        "visible_tools": visible,
        "deferred_tools": deferred,
        "visible_tool_count": len(visible),
        "deferred_tool_count": len(deferred),
        "context_requested_tools": sorted(expand),
        "max_visible_tools": max_visible_tools,
        "host_rule": (
            "Use visible input_schema for direct tool_calls. For deferred tools or uncertain schemas, "
            "call tool.discovery first; the host still validates every tool call."
        ),
    }


def _compact_tool_input_schema(value: object, *, limit: int = 32) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    compact: JsonObject = {}
    for key, raw in list(value.items())[:limit]:
        key_text = str(key)
        if key_text.startswith("_"):
            continue
        compact[key_text] = _compact_tool_schema_value(raw, depth=0)
    if len(value) > limit:
        compact["_truncated"] = True
        compact["_total_keys"] = len(value)
    return compact


def _compact_tool_schema_value(value: object, *, depth: int) -> object:
    if depth >= 3:
        return _preview_json_value(value, limit=180)
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, raw in list(value.items())[:16]:
            key_text = str(key)
            if key_text in {"description", "notes", "use_when", "examples"} and isinstance(raw, str):
                result[key_text] = _preview_text(raw, 220)
            elif key_text.startswith("_"):
                continue
            else:
                result[key_text] = _compact_tool_schema_value(raw, depth=depth + 1)
        if len(value) > 16:
            result["_truncated"] = True
        return result
    if isinstance(value, list):
        return [_compact_tool_schema_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, str):
        return _preview_text(value, 220)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:220]


def _feedback_continuation_contract(feedback: Feedback | None) -> JsonObject:
    if feedback is None or feedback.status != "continue":
        return {}
    missing = [str(item) for item in feedback.missing_evidence if str(item)]
    normalized = {item.lower().replace("_", " ").replace("-", " ") for item in missing}
    requires_tool = any(
        marker in normalized
        for marker in (
            "retrieval workbench followup",
            "retrieval workbench follow up",
            "finance slot bind followup",
            "finance slot bind follow up",
            "finance workbench missing slots",
            "finance formula trace required",
            "formula trace required",
            "calculator trace required",
            "calculator required before final",
            "transform work required",
        )
    )
    return {
        "feedback_status": "continue",
        "must_not_finalize_without_new_tool_observation": requires_tool,
        "missing_evidence": missing[:24],
        "instruction": (
            "Choose one or more allowed tool_calls now. Do not return final_answer until the missing work is resolved by new observations."
            if requires_tool
            else "Continue reasoning from feedback; prefer tool_calls when evidence, computation, or verification is still missing."
        ),
    }


def _stream_tool_call_items(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _stream_tool_call_key(raw_call: JsonObject, *, fallback: str) -> str:
    index = raw_call.get("index")
    if isinstance(index, int):
        return f"index-{index}"
    for key in ("id", "tool_call_id"):
        value = raw_call.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _stream_chunk_ready_tool_call(
    chunk: dict[str, object],
    *,
    turn_id: str,
    offset: int,
    tool_name_map: dict[str, str] | JsonObject | None,
) -> ToolCallRequest | None:
    tool_call_id = str(chunk.get("id") or f"{turn_id}-{offset}")
    name = resolve_native_tool_name(str(chunk.get("name") or "").strip(), tool_name_map)
    if not name:
        return None
    raw_arguments = str(chunk.get("arguments") or "").strip()
    if not raw_arguments:
        return None
    arguments = _try_parse_json_object(raw_arguments)
    if arguments is None:
        return None
    return ToolCallRequest(
        tool_call_id=tool_call_id,
        name=name,
        arguments=arguments,
        reason="processor_stream_tool_call",
        side_effect_class="read",
    )


def _stream_chunk_final_parse_error(
    chunk: dict[str, object],
    *,
    turn_id: str,
    offset: int,
    tool_name_map: dict[str, str] | JsonObject | None,
) -> ToolCallParseError | None:
    tool_call_id = str(chunk.get("id") or f"{turn_id}-{offset}")
    name = resolve_native_tool_name(str(chunk.get("name") or "").strip(), tool_name_map)
    if not name:
        return ToolCallParseError(
            tool_call_id=tool_call_id,
            error="missing_tool_name",
            raw_preview=_preview_json_value(chunk, limit=400),
        )
    raw_arguments = str(chunk.get("arguments") or "").strip()
    if not raw_arguments:
        return ToolCallParseError(
            tool_call_id=tool_call_id,
            error="missing_tool_arguments",
            raw_preview=_preview_json_value(chunk, limit=400),
        )
    arguments = _try_parse_json_object(raw_arguments)
    if arguments is None:
        return ToolCallParseError(
            tool_call_id=tool_call_id,
            error="invalid_tool_arguments",
            raw_preview=_preview_json_value(chunk, limit=400),
        )
    return None


def _prepared_tool_execution_event(
    event_type: str,
    prepared: _PreparedToolCall,
    *,
    outcome: _ToolExecutionItem | None = None,
    detail: JsonObject | None = None,
) -> ToolExecutionEvent:
    event_detail: JsonObject = dict(detail or {})
    status: str | None = None
    if outcome is not None:
        event_detail["observation_id"] = outcome.observation.observation_id
        event_detail["observation_kind"] = outcome.observation.kind
        status = outcome.observation.status
    return ToolExecutionEvent(
        event_type=event_type,
        tool_call_id=prepared.call.tool_call_id,
        action_id=prepared.action.action_id,
        tool_name=str(prepared.action.name or ""),
        status=status,
        detail=event_detail,
    )


def _try_parse_json_object(text: str) -> JsonObject | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return _json_object(decoded) if isinstance(decoded, dict) else None


def _preview_text(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _compact_context_for_turn(context: ContextBundle) -> JsonObject:
    state = context.state
    selected_keys = [
        "task_id",
        "run_id",
        "thread_id",
        "input_text",
        "agent_recipe",
        "capability_catalog",
        "host_situation",
        "agent_runtime_directive",
        "toolchain_state",
        "finance_working_state",
        "answer_profile",
        "research_mission",
        "retrieval_capability_state",
        "agent_retrieval_plan_state",
        "agent_replan_hints",
        "budget",
        "sections",
    ]
    compact = {key: state.get(key) for key in selected_keys if key in state}
    agent_trace = _agent_trace_section_from_state(state)
    if agent_trace:
        compact["agent_trace"] = agent_trace
    return {
        "context_id": context.context_id,
        "thread_key": context.thread_key,
        "token_budget": context.token_budget,
        "state": _json_object(compact),
    }


def _agent_trace_section_from_state(state: JsonObject) -> JsonObject:
    sections = state.get("sections")
    if not isinstance(sections, list):
        return {}
    for section in sections:
        if isinstance(section, dict) and section.get("name") == "agent_trace":
            return dict(section)
    return {}


def _context_requested_tool_names(
    context: ContextBundle,
    *,
    allowed_tool_names: set[str],
) -> set[str]:
    names: list[str] = []
    state = context.state if isinstance(context.state, dict) else {}
    _collect_requested_tool_names(state, names)
    allowed = set(allowed_tool_names)
    result = _ordered_unique_strings(names)
    if allowed:
        result = [name for name in result if name in allowed]
    return set(result)


def _collect_requested_tool_names(value: object, names: list[str]) -> None:
    if isinstance(value, dict):
        categories = value.get("required_tool_categories")
        if isinstance(categories, list):
            names.extend(_tools_for_requirement_categories(categories))
        risks = value.get("risk_flags")
        if isinstance(risks, list):
            names.extend(_tools_for_requirement_risk_flags(risks))
        for key in ("next_action", "slot_bind_next_action", "model_next_action"):
            nested = value.get(key)
            if isinstance(nested, dict):
                tool = nested.get("tool")
                if isinstance(tool, str) and tool:
                    names.append(tool)
        requested = value.get("requested_tool_names")
        if isinstance(requested, list):
            names.extend(str(item) for item in requested if str(item))
        options = value.get("next_action_options")
        if isinstance(options, list):
            names.extend(str(item) for item in options if _looks_like_tool_name(str(item)))
        tools = value.get("tools")
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        names.append(name)
        for nested_value in value.values():
            if isinstance(nested_value, (dict, list)):
                _collect_requested_tool_names(nested_value, names)
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                _collect_requested_tool_names(item, names)


def _tools_for_requirement_categories(categories: list[object]) -> list[str]:
    mapping = {
        "source_acquisition": ["retrieval.run"],
        "structured_sec_facts": ["sec.edgar.financials"],
        "document_table_extraction": ["provided_context.parse", "document.docling.convert", "document.trafilatura.extract"],
        "table_operations": ["data.table.query"],
        "arithmetic": ["calculator.compute", "calendar.days_between"],
        "numeric_verification": ["finance.verify_numeric"],
        "temporary_workbench": ["data.table.query", "script.exec"],
    }
    result: list[str] = []
    for item in categories:
        result.extend(mapping.get(str(item or "").strip(), []))
    return result


def _tools_for_requirement_risk_flags(risk_flags: list[object]) -> list[str]:
    mapping = {
        "needs_primary_filing": ["retrieval.run", "sec.edgar.company_filings"],
        "needs_structured_xbrl": ["sec.edgar.financials"],
        "needs_table_rows": ["document.docling.convert", "data.table.query"],
        "needs_bridge_reconciliation": ["document.docling.convert", "data.table.query"],
        "needs_market_or_macro_context": ["market.openbb.fetch", "retrieval.run"],
        "requires_calculator": ["calculator.compute"],
        "requires_calendar_days": ["calendar.days_between"],
        "requires_verifier": ["finance.verify_numeric"],
        "requires_table_sort": ["data.table.query"],
        "needs_temporary_workbench": ["data.table.query", "script.exec"],
    }
    result: list[str] = []
    for item in risk_flags:
        result.extend(mapping.get(str(item or "").strip(), []))
    return result


def _looks_like_tool_name(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and "." in text and " " not in text)


def _context_tool_surface_limit(context: ContextBundle) -> int:
    budget = _context_token_budget_value(context)
    if budget <= 0:
        return 32
    if budget < 4096:
        return 8
    if budget < 8192:
        return 12
    if budget < 32768:
        return 24
    return 48


def _context_token_budget_value(context: ContextBundle) -> int:
    for value in (
        getattr(context, "token_budget", None),
        context.state.get("token_budget") if isinstance(context.state, dict) else None,
        (context.state.get("budget", {}) if isinstance(context.state, dict) else {}).get("token_budget")
        if isinstance((context.state.get("budget", {}) if isinstance(context.state, dict) else {}), dict)
        else None,
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _processor_budget_parameters_from_context(context: ContextBundle) -> JsonObject:
    recipe = context.state.get("agent_recipe")
    if isinstance(recipe, dict):
        budget = recipe.get("processor_budget")
        if isinstance(budget, dict):
            return {"processor_budget": dict(budget)}
    budget = context.state.get("processor_budget")
    if isinstance(budget, dict):
        return {"processor_budget": dict(budget)}
    return {}


def _partition_execution_batches(items: list[_PreparedToolCall]) -> list[list[_PreparedToolCall]]:
    batches: list[list[_PreparedToolCall]] = []
    current: list[_PreparedToolCall] = []
    for item in items:
        safe = _is_concurrency_safe(item.action, item.manifest)
        if safe:
            current.append(item)
            continue
        if current:
            batches.append(current)
            current = []
        batches.append([item])
    if current:
        batches.append(current)
    return batches


def _is_concurrency_safe(action: CandidateAction, manifest: Any) -> bool:
    return tool_runtime_spec_for_action(action, manifest).concurrency_safe


def _execution_item_artifact_refs(item: _ToolExecutionItem) -> list[Any]:
    refs = list(item.artifact_refs)
    if item.tool_result_artifact_ref is not None:
        refs.append(item.tool_result_artifact_ref)
    return refs


def _visible_execution_item_artifact_refs(item: _ToolExecutionItem) -> list[Any]:
    refs = list(item.artifact_refs)
    if _should_surface_tool_result_artifact(item.observation, item.tool_result_artifact_ref):
        refs.append(item.tool_result_artifact_ref)
    return refs


def _should_surface_tool_result_artifact(observation: Observation, artifact_ref: Any | None) -> bool:
    if artifact_ref is None or not hasattr(artifact_ref, "artifact_id"):
        return False
    return project_tool_result_content(observation.content).truncated


def _artifact_ref_ids(artifact_refs: list[Any]) -> list[str]:
    return _ordered_unique_strings(
        [
            str(artifact.artifact_id)
            for artifact in artifact_refs
            if hasattr(artifact, "artifact_id") and str(artifact.artifact_id)
        ]
    )


def _execution_item_failed(item: _ToolExecutionItem) -> bool:
    return item.observation.status not in {"ok"}


def _tool_failure_cancels_siblings(item: _PreparedToolCall, outcome: _ToolExecutionItem) -> bool:
    if not _execution_item_failed(outcome):
        return False
    spec = tool_runtime_spec_for_action(item.action, item.manifest)
    return spec.failure_cancels_siblings


def _with_tool_call_id(observation: Observation, tool_call_id: str) -> Observation:
    return Observation(
        observation_id=observation.observation_id,
        run_id=observation.run_id,
        kind=observation.kind,
        status=observation.status,
        source=observation.source,
        content=observation.content,
        observed_at_ms=observation.observed_at_ms,
        action_id=observation.action_id,
        tool_call_id=observation.tool_call_id or tool_call_id,
    )


def _provider_tool_result_continuation_messages(
    base_messages: list[JsonObject],
    *,
    assistant_text: str,
    tool_chunks: dict[str, dict[str, object]],
    execution_items: list[_ToolExecutionItem],
) -> list[JsonObject]:
    chunks_by_id = {
        str(chunk.get("id") or ""): chunk
        for chunk in tool_chunks.values()
        if str(chunk.get("id") or "")
    }
    tool_calls: list[JsonObject] = []
    tool_messages: list[JsonObject] = []
    for item in execution_items:
        if _execution_item_is_parse_error(item):
            continue
        chunk = chunks_by_id.get(item.tool_call_id, {})
        raw_name = str(chunk.get("name") or item.action.name or "")
        raw_arguments = str(chunk.get("arguments") or "").strip()
        if not raw_arguments:
            raw_arguments = json.dumps(item.action.payload, ensure_ascii=False, sort_keys=True)
        if not raw_name:
            continue
        tool_calls.append(
            {
                "id": item.tool_call_id,
                "type": "function",
                "function": {
                    "name": raw_name,
                    "arguments": raw_arguments,
                },
            }
        )
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": item.tool_call_id,
                "content": json.dumps(_provider_tool_result_content(item), ensure_ascii=False, sort_keys=True),
            }
        )
    if not tool_calls:
        return []
    messages = [dict(message) for message in base_messages if isinstance(message, dict)]
    messages.append(
        {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": tool_calls,
        }
    )
    messages.extend(tool_messages)
    return messages


def _execution_item_is_parse_error(item: _ToolExecutionItem) -> bool:
    return item.action.name == "__invalid_tool_call__" or item.observation.kind == "tool_call_parse_error"


def _provider_terminal_text(text: str, *, index: int) -> str:
    parsed = _try_parse_json_object(text)
    if parsed is None:
        return text
    turn = _assistant_turn_from_json(parsed, index=index)
    if turn.tool_calls or turn.parse_errors:
        return text
    return turn.final_answer or turn.message or text


def _provider_tool_result_content(item: _ToolExecutionItem) -> JsonObject:
    artifact_refs = _artifact_ref_ids(_execution_item_artifact_refs(item))
    tool_result_artifact_id = (
        str(item.tool_result_artifact_ref.artifact_id)
        if item.tool_result_artifact_ref is not None and hasattr(item.tool_result_artifact_ref, "artifact_id")
        else ""
    )
    if tool_result_artifact_id:
        artifact_refs = _ordered_unique_strings([tool_result_artifact_id, *artifact_refs])
    projection = project_tool_result_content(item.observation.content, limit=1600).to_dict()
    payload: JsonObject = {
        "schema": "holo.kernel_v3.provider_tool_result_message.v1",
        "tool": item.action.name,
        "tool_call_id": item.tool_call_id,
        "status": item.observation.status,
        "observation_id": item.observation.observation_id,
        "observation_kind": item.observation.kind,
        "source": item.observation.source,
        "content_projection": projection,
        "artifact_refs": artifact_refs[:8],
        "host_boundary": "bounded tool result for provider continuation; full payload remains in Holo artifacts/journal",
    }
    if tool_result_artifact_id:
        payload["tool_result_artifact_id"] = tool_result_artifact_id
        payload["artifact_query_hint"] = {
            "tool": "artifact.query",
            "artifact_id": tool_result_artifact_id,
            "path": "observation.content",
            "purpose": "narrow full result before broad read",
        }
        payload["artifact_read_hint"] = {
            "tool": "artifact.read",
            "artifact_id": tool_result_artifact_id,
            "mode": "read",
            "purpose": "read the full tool result JSON when the bounded content_projection is insufficient",
        }
    if item.action.name == TOOL_DISCOVERY_NAME or item.observation.kind == "tool_discovery_result":
        content = item.observation.content if isinstance(item.observation.content, dict) else {}
        tools = content.get("tools")
        discovered = [
            str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool.get("name")
        ] if isinstance(tools, list) else []
        payload["discovered_tool_names"] = _ordered_unique_strings(discovered)
        payload["requested_tool_names"] = _json_string_list(content.get("requested_tool_names"))
        payload["missing_tool_names"] = _json_string_list(content.get("missing_tool_names"))
        payload["tool_discovery_query_mode"] = str(content.get("query_mode") or "")
        payload["provider_continuation_effect"] = (
            "Discovered allowed tools may be exposed as native tool schemas on the next provider continuation."
        )
    return payload


def _provider_messages_requested_tool_names(
    messages: list[JsonObject],
    *,
    allowed_tool_names: set[str],
) -> set[str]:
    names: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        data = (
            _try_parse_json_object(content)
            if isinstance(content, str)
            else dict(content)
            if isinstance(content, dict)
            else None
        )
        if not isinstance(data, dict):
            continue
        names.extend(_json_string_list(data.get("discovered_tool_names")))
        names.extend(_json_string_list(data.get("loaded_tool_names")))
    allowed = set(allowed_tool_names)
    result = _ordered_unique_strings(names)
    if allowed:
        result = [name for name in result if name in allowed]
    return set(result)


def _assistant_continuation_for_batch(turn: AssistantTurn) -> JsonObject:
    if "provider_tool_result_continuation" not in set(turn.reasons or []):
        return {}
    text = turn.final_answer or turn.message or ""
    return {
        "assistant_continuation": {
            "schema": "holo.kernel_v3.assistant_continuation.v1",
            "source": "provider_tool_result_continuation",
            "text_preview": _preview_text(text, 600),
            "has_final_answer": bool(turn.final_answer),
            "host_boundary": "continuation text is model output after bounded tool results; evaluator still decides finality",
        }
    }


def _tool_context_updates_for_result(
    tool_result: Any,
    *,
    observation: Observation,
    action: CandidateAction,
    manifest: ToolManifest | None,
    tool_result_artifact_ref: Any | None = None,
) -> list[JsonObject]:
    updates: list[JsonObject] = []
    updates.extend(
        _normalize_explicit_context_updates(
            getattr(tool_result, "context_updates", []),
            observation=observation,
            action=action,
            manifest=manifest,
        )
    )
    derived = _derived_tool_context_update(observation, action=action, manifest=manifest)
    if derived:
        updates.append(derived)
    artifact_update = _tool_result_artifact_context_update(
        observation,
        action=action,
        manifest=manifest,
        tool_result_artifact_ref=tool_result_artifact_ref,
    ) if _should_surface_tool_result_artifact(observation, tool_result_artifact_ref) else {}
    if artifact_update:
        updates.append(artifact_update)
    if artifact_update and len(updates) > 8:
        return [*updates[:7], artifact_update]
    return updates[:8]


def _normalize_explicit_context_updates(
    values: object,
    *,
    observation: Observation,
    action: CandidateAction,
    manifest: ToolManifest | None,
) -> list[JsonObject]:
    raw_updates = values if isinstance(values, list) else []
    updates: list[JsonObject] = []
    for index, raw in enumerate(raw_updates, start=1):
        if not isinstance(raw, dict):
            continue
        update = _json_object(raw)
        update.setdefault("schema", "holo.kernel_v3.tool_context_update.v1")
        update.setdefault("update_id", f"tool-context-{observation.observation_id}-explicit-{index}")
        update.setdefault("update_type", "tool_declared_context")
        update.setdefault("tool", action.name or getattr(manifest, "name", ""))
        update.setdefault("source_observation_id", observation.observation_id)
        update.setdefault("source_observation_kind", observation.kind)
        update.setdefault("status", observation.status)
        update.setdefault("host_boundary", _TOOL_CONTEXT_UPDATE_BOUNDARY)
        updates.append(update)
    return updates


def _tool_result_artifact_context_update(
    observation: Observation,
    *,
    action: CandidateAction,
    manifest: ToolManifest | None,
    tool_result_artifact_ref: Any | None,
) -> JsonObject:
    if tool_result_artifact_ref is None or not hasattr(tool_result_artifact_ref, "artifact_id"):
        return {}
    artifact_id = str(tool_result_artifact_ref.artifact_id)
    if not artifact_id:
        return {}
    return {
        "schema": "holo.kernel_v3.tool_context_update.v1",
        "update_id": f"tool-context-{observation.observation_id}-tool-result-artifact",
        "update_type": "artifact_read_hint",
        "tool": action.name or getattr(manifest, "name", ""),
        "source_observation_id": observation.observation_id,
        "source_observation_kind": observation.kind,
        "source": observation.source,
        "status": observation.status,
        "hints": {
            "artifact_query_hint": {
                "tool": "artifact.query",
                "artifact_id": artifact_id,
                "path": "observation.content",
            },
            "artifact_read_hint": {
                "tool": "artifact.read",
                "artifact_id": artifact_id,
                "mode": "read",
            },
        },
        "artifact_refs": [artifact_id],
        "host_boundary": _TOOL_CONTEXT_UPDATE_BOUNDARY,
    }


def _derived_tool_context_update(
    observation: Observation,
    *,
    action: CandidateAction,
    manifest: ToolManifest | None,
) -> JsonObject:
    if not isinstance(observation.content, dict):
        return {}
    content = _json_object(observation.content)
    hints: JsonObject = {}
    for key in (
        "missing_slots",
        "next_action",
        "artifact_read_hint",
        "content_replacement",
        "content_replacement_applied",
        "tool_surface_schema",
        "matched_count",
        "requested_tool_names",
        "query",
        "mode",
        "truncated",
        "reason",
    ):
        if key in content:
            hints[key] = _compact_context_update_value(content[key])
    tools = content.get("tools")
    if isinstance(tools, list):
        hints["tools"] = [
            _compact_context_update_tool(item)
            for item in tools[:8]
            if isinstance(item, dict)
        ]
    if action.name == TOOL_DISCOVERY_NAME or observation.kind == "tool_discovery_result":
        matched_tool_names = _json_string_list(content.get("matched_tool_names"))
        if not matched_tool_names and isinstance(tools, list):
            matched_tool_names = [
                str(item.get("name"))
                for item in tools
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name")
            ][:8]
        if matched_tool_names:
            hints["requested_tool_names"] = _ordered_unique_strings(matched_tool_names)
            hints["loaded_tool_names"] = _ordered_unique_strings(matched_tool_names)
    artifact = content.get("artifact")
    if isinstance(artifact, dict):
        hints["artifact"] = {
            key: artifact.get(key)
            for key in ("artifact_id", "kind", "uri")
            if artifact.get(key) is not None
        }
    if not hints:
        return {}
    artifact_refs: list[str] = []
    direct_artifact_refs = content.get("artifact_refs")
    if isinstance(direct_artifact_refs, list):
        artifact_refs.extend(str(ref) for ref in direct_artifact_refs[:8] if str(ref))
    hint = content.get("artifact_read_hint")
    if isinstance(hint, dict):
        artifact_id = hint.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            artifact_refs.append(artifact_id)
    return {
        "schema": "holo.kernel_v3.tool_context_update.v1",
        "update_id": f"tool-context-{observation.observation_id}",
        "update_type": "observation_context",
        "tool": action.name or getattr(manifest, "name", ""),
        "source_observation_id": observation.observation_id,
        "source_observation_kind": observation.kind,
        "source": observation.source,
        "status": observation.status,
        "hints": hints,
        "artifact_refs": _ordered_unique_strings(artifact_refs),
        "host_boundary": _TOOL_CONTEXT_UPDATE_BOUNDARY,
    }


def _compact_context_update_tool(item: JsonObject) -> JsonObject:
    runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
    return {
        key: value
        for key, value in {
            "name": item.get("name"),
            "description": _preview_text(str(item.get("description") or ""), 160),
            "side_effect_class": item.get("side_effect_class"),
            "resource_kind": item.get("resource_kind"),
            "operator_kind": item.get("operator_kind"),
            "runtime": {
                key: runtime.get(key)
                for key in ("concurrency_safe", "read_only", "always_load", "should_defer")
                if runtime.get(key) is not None
            },
        }.items()
        if value not in (None, "", {}, [])
    }


def _compact_context_update_value(value: object) -> object:
    if isinstance(value, str):
        return _preview_text(value, 420)
    if isinstance(value, list):
        return [
            _compact_context_update_value(item)
            for item in value[:16]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_context_update_value(raw)
            for key, raw in list(value.items())[:24]
            if not str(key).startswith("_host_")
        }
    return value


_TOOL_CONTEXT_UPDATE_BOUNDARY = (
    "tool context update is an observation-derived hint; the model still owns tool choice, "
    "semantic binding, and final judgment"
)


def _payload_text(payload: JsonObject) -> str | None:
    for key in ("text", "answer", "message", "content", "question"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _preview_json_value(value: Any, *, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _json_object(value: Any) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    encoded = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    return encoded if isinstance(encoded, dict) else {}


def _safe_action_id(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip().lower())
    return text.strip("-")[:64] or "tool"


def _task_id(context: ContextBundle) -> str | None:
    value = context.state.get("task_id")
    return value if isinstance(value, str) and value else None


def _run_id(context: ContextBundle) -> str:
    value = context.state.get("run_id")
    return value if isinstance(value, str) and value else "run-unknown"
