from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, JsonObject, Observation
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.loop import LoopControllerV3, _journal_action_data
from kernel_v3.processors.contracts import JsonSchema
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.result import AgentResult
from kernel_v3.session import TaskState
from kernel_v3.tool_result_budget import (
    ToolResultReplacementState,
    apply_tool_result_replacement_budget,
    reconstruct_tool_result_replacement_state,
)
from kernel_v3.tool_runtime import tool_runtime_spec_for_action
from kernel_v3.tool_use import (
    StreamingToolExecutor,
    ToolExecutionEvent,
    project_tool_result_content,
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
replanning. If enough evidence is present, return no tool_calls and put the
answer in final_answer. Do not include markdown fences or prose outside JSON."""


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
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.allowed_tool_names = set(allowed_tool_names or set())
        self.calls: list[ContextBundle] = []

    def propose_turn(self, context: ContextBundle, feedback: Feedback | None = None) -> AssistantTurn:
        self.calls.append(context)
        task_id = _task_id(context)
        run_id = _run_id(context)
        outcome = self.fabric.run_json(
            task_type="assistant.turn",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=_assistant_turn_prompt(context, feedback, allowed_tool_names=self.allowed_tool_names),
            schema=ASSISTANT_TURN_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={"adapter": "ModelAssistantTurnPlanner", **_processor_budget_parameters_from_context(context)},
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


@dataclass(frozen=True)
class _ToolExecutionItem:
    tool_call_id: str
    action: CandidateAction
    manifest: Any
    observation: Observation
    artifact_refs: list[Any]
    policy_allowed: bool
    policy_reason: str


@dataclass(frozen=True)
class _PreparedToolCall:
    call: ToolCallRequest
    action: CandidateAction
    manifest: Any
    decision: Any
    pre_exec_guard: str | None


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
            turn = self._propose_turn(context, current_feedback)
            self._append_assistant_turn(task, turn, step_id=step_id)

            if not turn.tool_calls and not turn.parse_errors:
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
                    return self._result(task, current_feedback, step_id=step_id)

            else:
                execution_items, tool_calls, network_fetches, total_artifact_bytes = self._execute_tool_turn(
                    task,
                    turn,
                    step_id=step_id,
                    tool_calls=tool_calls,
                    network_fetches=network_fetches,
                    total_artifact_bytes=total_artifact_bytes,
                )
                aggregate = self._tool_batch_observation(
                    task,
                    turn=turn,
                    step_id=step_id,
                    execution_items=execution_items,
                )
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
                evaluation_context = self.context_compiler.compile(task, self.journal)
                current_feedback = self.evaluator.evaluate(evaluation_context, aggregate)
                self._append_feedback_record(task, current_feedback, step_id=step_id, observation=aggregate)

                guard_reason = self._guard_stop_reason(aggregate)
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
                    return self._result(task, current_feedback, step_id=step_id)

                if self.stop_controller.should_stop(current_feedback):
                    return self._result(task, current_feedback, step_id=step_id)

            continuation_guard = self._continuation_guard(step_index=step_index, started_at_ms=started_at_ms)
            if continuation_guard is not None:
                stop_reason, data = continuation_guard
                current_feedback = self._limit_feedback(task.run_id, stop_reason)
                self._append_feedback_record(task, current_feedback, step_id=step_id, observation=None)
                self._append_guard(task, stop_reason, step_id=step_id, data=data)
                return self._result(task, current_feedback, step_id=step_id)

    def _propose_turn(self, context: ContextBundle, feedback: Feedback | None) -> AssistantTurn:
        planner = self.planner
        proposer = getattr(planner, "propose_turn", None)
        if callable(proposer):
            turn = proposer(context, feedback)
            if isinstance(turn, AssistantTurn):
                return turn
        action = planner.propose(context, feedback)
        return _assistant_turn_from_action(action)

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
            action = call.to_action(turn_id=turn.turn_id, index=index)
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
            prepared.append(
                _PreparedToolCall(
                    call=call,
                    action=action,
                    manifest=manifest,
                    decision=decision,
                    pre_exec_guard=pre_exec_guard,
                )
            )

        executor = StreamingToolExecutor(
            emit_event=lambda event: self._append_tool_execution_event(task, step_id=step_id, event=event)
        )
        batch_items = executor.execute_batches(
            prepared,
            execute_one=lambda item: self._execute_prepared_tool(task, step_id, item),
            is_concurrency_safe=lambda item: _is_concurrency_safe(item.action, item.manifest),
            cancel_pending_on_failure=True,
            is_failed=_execution_item_failed,
            cancel_one=lambda item, reason: self._cancelled_execution_item(task, step_id=step_id, prepared=item, reason=reason),
        )
        for item in batch_items:
            execution_items.append(item)
            if item.policy_allowed and item.policy_reason == "allowed" and self._is_network_action(item.action, manifest=item.manifest):
                network_fetches += self._network_action_actual_cost(
                    item.action,
                    manifest=item.manifest,
                    observation=item.observation,
                ) - self._network_action_cost(item.action, manifest=item.manifest)
            total_artifact_bytes += self._estimate_artifact_bytes(item.observation, item.artifact_refs)
            self._append_tool_execution_observation(task, step_id=step_id, item=item)
        return execution_items, tool_calls, network_fetches, total_artifact_bytes

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
            return _ToolExecutionItem(
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                manifest=manifest,
                observation=observation,
                artifact_refs=[],
                policy_allowed=False,
                policy_reason=decision.reason,
            )
        if pre_exec_guard is not None:
            observation = _with_tool_call_id(self._guard_observation(task.run_id, action, pre_exec_guard), prepared.call.tool_call_id)
            return _ToolExecutionItem(
                tool_call_id=prepared.call.tool_call_id,
                action=action,
                manifest=manifest,
                observation=observation,
                artifact_refs=[],
                policy_allowed=False,
                policy_reason=pre_exec_guard,
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
        )
        tool_result = self.tool_registry.execute_with_artifacts(
            action,
            policy_decision=decision,
            execution_context=tool_context.to_execution_context(),
        )
        observation = _with_tool_call_id(
            self._bind_observation(task.run_id, action, tool_result.observation),
            prepared.call.tool_call_id,
        )
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=manifest,
            observation=observation,
            artifact_refs=list(tool_result.artifact_refs),
            policy_allowed=True,
            policy_reason=decision.reason,
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
        return _ToolExecutionItem(
            tool_call_id=prepared.call.tool_call_id,
            action=action,
            manifest=prepared.manifest,
            observation=observation,
            artifact_refs=[],
            policy_allowed=False,
            policy_reason=reason,
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
            artifact_refs=[artifact.artifact_id for artifact in item.artifact_refs if hasattr(artifact, "artifact_id")],
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
        results = [
            {
                "tool_call_id": item.tool_call_id,
                "action_id": item.action.action_id,
                "tool": item.action.name,
                "status": item.observation.status,
                "source": item.observation.source,
                "kind": item.observation.kind,
                "observation_id": item.observation.observation_id,
                "policy": item.policy_reason,
                "artifact_refs": [
                    artifact.artifact_id
                    for artifact in item.artifact_refs
                    if hasattr(artifact, "artifact_id")
                ],
                "content_preview": _preview_json_value(item.observation.content),
                "content_projection": project_tool_result_content(item.observation.content).to_dict(),
            }
            for item in execution_items
        ]
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
            },
            observed_at_ms=self.clock_ms(),
            action_id=None,
            tool_call_id=None,
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


def _assistant_turn_prompt(
    context: ContextBundle,
    feedback: Feedback | None,
    *,
    allowed_tool_names: set[str],
) -> str:
    payload = {
        "contract": ASSISTANT_TURN_PROMPT_CONTRACT,
        "context": _compact_context_for_turn(context),
        "feedback": feedback.to_dict() if feedback is not None else None,
        "allowed_tool_names": sorted(allowed_tool_names),
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
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


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
    return {
        "context_id": context.context_id,
        "thread_key": context.thread_key,
        "token_budget": context.token_budget,
        "state": _json_object(compact),
    }


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


def _execution_item_failed(item: _ToolExecutionItem) -> bool:
    return item.observation.status not in {"ok"}


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
