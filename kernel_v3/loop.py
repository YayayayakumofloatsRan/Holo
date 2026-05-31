from __future__ import annotations

import json
import time
from collections.abc import Callable

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, Event, Feedback, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.journal import Journal
from kernel_v3.planner import Planner
from kernel_v3.policy import PolicyGate
from kernel_v3.result import AgentResult
from kernel_v3.session import SessionEngine, TaskState
from kernel_v3.stop import StopController
from kernel_v3.tools import ToolRegistry


class LoopControllerV3:
    def __init__(
        self,
        *,
        journal: Journal,
        context_compiler: ContextCompiler,
        planner: Planner,
        policy_gate: PolicyGate,
        tool_registry: ToolRegistry,
        evaluator: Evaluator,
        stop_controller: StopController | None = None,
        session_engine: SessionEngine | None = None,
        max_steps: int | None = None,
        max_tool_calls: int | None = None,
        max_duration_ms: int | None = None,
        max_network_fetches: int | None = None,
        max_total_artifact_bytes: int | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.journal = journal
        self.context_compiler = context_compiler
        self.planner = planner
        self.policy_gate = policy_gate
        self.tool_registry = tool_registry
        self.evaluator = evaluator
        self.stop_controller = stop_controller or StopController()
        self.session_engine = session_engine or SessionEngine.from_journal(journal)
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.max_duration_ms = max_duration_ms
        self.max_network_fetches = max_network_fetches
        self.max_total_artifact_bytes = max_total_artifact_bytes
        self.clock_ms = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)

    def run(self, input_text: str) -> AgentResult:
        task = self.session_engine.start(input_text, record_state=False)
        self._record_start(task, input_text=input_text)
        return self._drive(task, feedback=None)

    def run_event(self, event: Event) -> AgentResult:
        input_text = str(event.payload.get("text", ""))
        thread_id = str(event.payload.get("thread_id", "local:default"))
        task = self.session_engine.start(input_text, thread_id=thread_id, record_state=False)
        self._record_start_event(task, event)
        return self._drive(task, feedback=None)

    def resume(self, task_id: str, *, user_input: str, thread_id: str = "local:default") -> AgentResult:
        records = self.journal.require_task(task_id)
        task_threads = {
            str(record.data["thread_id"])
            for record in records
            if "thread_id" in record.data
        }
        if task_threads and thread_id not in task_threads:
            raise ValueError(f"thread_id {thread_id!r} does not match task_id {task_id!r}")
        run_index = 1 + len({record.run_id for record in records if record.kind in {"run", "session_state"}})
        task = self.session_engine.resume(
            task_id,
            user_input,
            run_index,
            thread_id=thread_id,
            record_state=False,
        )
        event = Event(
            event_id=f"evt-{task.run_id}-resume",
            run_id=task.run_id,
            type="input.resumed",
            timestamp_ms=len(records) + 1,
            payload={"text": user_input, "thread_id": thread_id},
            source="resume",
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="resume",
            data={**event.to_dict(), "user_input": user_input, "thread_id": task.thread_id},
            event_ref=event.event_id,
            state_delta={"status": "resumed"},
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="run",
            data={"run_id": task.run_id, "status": task.status, "thread_id": task.thread_id},
            event_ref=event.event_id,
            state_delta={"status": task.status},
        )
        return self._drive(task, feedback=None)

    def _record_start(self, task: TaskState, *, input_text: str) -> None:
        event = Event(
            event_id=f"evt-{task.run_id}-input",
            run_id=task.run_id,
            type="input.received",
            timestamp_ms=1,
            payload={"text": input_text},
            source="user",
        )
        self._record_start_event(task, event)

    def _record_start_event(self, task: TaskState, event: Event) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="event",
            data=event.to_dict(),
            event_ref=event.event_id,
            state_delta={"status": "event_received"},
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="task",
            data={
                "task_id": task.task_id,
                "status": task.status,
                "input_text": str(event.payload.get("text", "")),
                "thread_id": task.thread_id,
            },
            event_ref=event.event_id,
            state_delta={"status": task.status},
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="run",
            data={"run_id": task.run_id, "status": task.status, "thread_id": task.thread_id},
            event_ref=event.event_id,
            state_delta={"status": task.status},
        )

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
                data=context.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                state_delta={"context_id": context.context_id},
            )
            action = self.planner.propose(context, current_feedback)
            self._record_action(task, action, step_id=step_id)
            manifest = self.tool_registry.manifest_for_action(action)
            decision = self.policy_gate.validate(run_id=task.run_id, action=action, manifest=manifest)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=step_id,
                kind="policy_decision",
                data=decision.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=action.action_id,
                state_delta={"policy_allowed": decision.allowed},
            )
            artifact_refs = []
            if decision.allowed:
                pre_exec_guard = self._pre_execution_guard(
                    action,
                    manifest=manifest,
                    tool_calls=tool_calls,
                    network_fetches=network_fetches,
                )
                if pre_exec_guard is not None:
                    observation = self._guard_observation(task.run_id, action, pre_exec_guard)
                else:
                    tool_result = self.tool_registry.execute_with_artifacts(
                        action,
                        policy_decision=decision,
                        execution_context={
                            "task_id": task.task_id,
                            "run_id": task.run_id,
                            "step_id": step_id,
                        },
                    )
                    observation = self._bind_observation(task.run_id, action, tool_result.observation)
                    artifact_refs = tool_result.artifact_refs
                    if action.kind == "tool":
                        tool_calls += 1
                    if self._is_network_action(action, manifest=manifest):
                        network_fetches += self._network_action_cost(action, manifest=manifest)
                    total_artifact_bytes += self._estimate_artifact_bytes(observation, artifact_refs)
            else:
                observation = self._blocked_observation(task.run_id, action, decision.reason)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=step_id,
                kind="observation",
                data=observation.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=action.action_id,
                observation_ref=observation.observation_id,
                state_delta={"observation_status": observation.status},
                artifact_refs=[artifact.artifact_id for artifact in artifact_refs],
            )
            if observation.status == "blocked" and observation.content == {"reason": "max_tool_calls"}:
                current_feedback = self._limit_feedback(task.run_id, "max_tool_calls")
                self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
                self._append_guard(task, "max_tool_calls", step_id=step_id, data={"tool_calls": tool_calls})
                return self._result(task, current_feedback, step_id=step_id)
            if observation.status == "blocked" and observation.content == {"reason": "max_network_fetches"}:
                current_feedback = self._limit_feedback(task.run_id, "max_network_fetches")
                self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
                requested_network_fetches = self._network_action_cost(action, manifest=manifest)
                self._append_guard(
                    task,
                    "max_network_fetches",
                    step_id=step_id,
                    data={
                        "network_fetches": network_fetches,
                        "requested_network_fetches": requested_network_fetches,
                        "projected_network_fetches": network_fetches + requested_network_fetches,
                        "max_network_fetches": self.max_network_fetches,
                    },
                )
                return self._result(task, current_feedback, step_id=step_id)
            current_feedback = self.evaluator.evaluate(context, observation)
            self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
            resource_guard = self._resource_guard(total_artifact_bytes=total_artifact_bytes)
            if resource_guard is not None:
                stop_reason, data = resource_guard
                current_feedback = self._limit_feedback(task.run_id, stop_reason)
                self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
                self._append_guard(task, stop_reason, step_id=step_id, data=data)
                return self._result(task, current_feedback, step_id=step_id)
            if self.stop_controller.should_stop(current_feedback):
                return self._result(task, current_feedback, step_id=step_id)
            continuation_guard = self._continuation_guard(step_index=step_index, started_at_ms=started_at_ms)
            if continuation_guard is not None:
                stop_reason, data = continuation_guard
                current_feedback = self._limit_feedback(task.run_id, stop_reason)
                self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
                self._append_guard(task, stop_reason, step_id=step_id, data=data)
                return self._result(task, current_feedback, step_id=step_id)

    def _record_action(self, task: TaskState, action: CandidateAction, *, step_id: str) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="action",
            data=action.to_dict(),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            state_delta={"action_kind": action.kind},
        )

    def _bind_observation(
        self,
        run_id: str,
        action: CandidateAction,
        observation: Observation,
    ) -> Observation:
        return Observation(
            observation_id=observation.observation_id,
            run_id=run_id,
            kind=observation.kind,
            status=observation.status,
            source=observation.source,
            content=observation.content,
            observed_at_ms=observation.observed_at_ms,
            action_id=action.action_id,
            tool_call_id=observation.tool_call_id,
        )

    def _blocked_observation(self, run_id: str, action: CandidateAction, reason: str) -> Observation:
        return Observation(
            observation_id=f"obs-{action.action_id}-blocked",
            run_id=run_id,
            kind="policy_block",
            status="blocked",
            source="policy",
            content={"reason": reason},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    def _guard_observation(self, run_id: str, action: CandidateAction, reason: str) -> Observation:
        return Observation(
            observation_id=f"obs-{action.action_id}-{reason}",
            run_id=run_id,
            kind="host_guard",
            status="blocked",
            source="loop_guard",
            content={"reason": reason},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    def _limit_feedback(self, run_id: str, stop_reason: str) -> Feedback:
        return Feedback(
            feedback_id=f"fb-{run_id}-{stop_reason}",
            run_id=run_id,
            status="step_limit_exceeded",
            stop_reason=stop_reason,
            answer=None,
            missing_evidence=[],
        )

    def _append_feedback(
        self,
        task: TaskState,
        feedback: Feedback,
        *,
        action: CandidateAction,
        observation: Observation,
        step_id: str,
    ) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="feedback",
            data=feedback.to_dict(),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            observation_ref=observation.observation_id,
            feedback_ref=feedback.feedback_id,
            state_delta={"feedback_status": feedback.status},
        )

    def _append_guard(self, task: TaskState, stop_reason: str, *, step_id: str, data: dict[str, object]) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="guard",
            data={"stop_reason": stop_reason, **data},
            event_ref=self._last_ref(task.task_id, "event_ref"),
            state_delta={"status": "step_limit_exceeded", "stop_reason": stop_reason},
        )

    def _pre_execution_guard(
        self,
        action: CandidateAction,
        *,
        manifest,
        tool_calls: int,
        network_fetches: int,
    ) -> str | None:
        if action.kind == "tool" and self.max_tool_calls is not None and tool_calls >= self.max_tool_calls:
            return "max_tool_calls"
        if (
            action.kind == "tool"
            and self._is_network_action(action, manifest=manifest)
            and self.max_network_fetches is not None
            and network_fetches + self._network_action_cost(action, manifest=manifest) > self.max_network_fetches
        ):
            return "max_network_fetches"
        return None

    def _resource_guard(self, *, total_artifact_bytes: int) -> tuple[str, dict[str, object]] | None:
        if self.max_total_artifact_bytes is not None and total_artifact_bytes > self.max_total_artifact_bytes:
            return "max_total_artifact_bytes", {"artifact_bytes": total_artifact_bytes}
        return None

    def _continuation_guard(
        self,
        *,
        step_index: int,
        started_at_ms: int,
    ) -> tuple[str, dict[str, object]] | None:
        if self.max_steps is not None and step_index >= self.max_steps:
            return "max_steps", {"steps": step_index}
        if self.max_duration_ms is not None:
            elapsed_ms = self.clock_ms() - started_at_ms
            if elapsed_ms > self.max_duration_ms:
                return "max_duration_ms", {"elapsed_ms": elapsed_ms}
        return None

    def _is_network_action(self, action: CandidateAction, *, manifest) -> bool:
        manifest_effect = getattr(manifest, "side_effect_class", None)
        return action.side_effect_class == "network" or manifest_effect == "network"

    def _network_action_cost(self, action: CandidateAction, *, manifest) -> int:
        if not self._is_network_action(action, manifest=manifest):
            return 0
        payload_cost = _network_cost_from_payload(action.payload)
        if payload_cost is not None:
            return max(1, payload_cost)
        manifest_schema = getattr(manifest, "input_schema", {})
        if isinstance(manifest_schema, dict):
            default_cost = _positive_int(manifest_schema.get("default_network_fetch_cost"))
            if default_cost is not None:
                return max(1, default_cost)
        return 1

    def _estimate_artifact_bytes(self, observation: Observation, artifact_refs: list[object]) -> int:
        total = 0
        for artifact in artifact_refs:
            metadata = getattr(artifact, "metadata", {})
            size = metadata.get("size_bytes") if isinstance(metadata, dict) else None
            if isinstance(size, int):
                total += size
        if total:
            return total
        encoded = json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return len(encoded.encode("utf-8"))

    def _result(self, task: TaskState, feedback: Feedback, *, step_id: str | None = None) -> AgentResult:
        status = "completed" if feedback.status == "final_answer_ready" else feedback.status
        result = AgentResult(
            task_id=task.task_id,
            run_id=task.run_id,
            status=status,
            answer=feedback.answer,
            stop_reason=feedback.stop_reason,
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="result",
            data={
                "task_id": result.task_id,
                "run_id": result.run_id,
                "status": result.status,
                "answer": result.answer,
                "stop_reason": result.stop_reason,
            },
            event_ref=self._last_ref(task.task_id, "event_ref"),
            feedback_ref=feedback.feedback_id,
            state_delta={"status": result.status},
        )
        return result

    def _last_ref(self, task_id: str, field: str) -> str | None:
        for record in reversed(self.journal.records(task_id=task_id)):
            value = getattr(record, field)
            if isinstance(value, str):
                return value
        return None


def _network_cost_from_payload(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("network_fetch_count", "max_network_fetches", "max_fetches", "fetch_count"):
        value = _positive_int(payload.get(key))
        if value is not None:
            return value
    goal = payload.get("goal")
    if isinstance(goal, dict):
        return _network_cost_from_payload(goal)
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed
