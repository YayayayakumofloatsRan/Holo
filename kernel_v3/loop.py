from __future__ import annotations

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
    ) -> None:
        self.journal = journal
        self.context_compiler = context_compiler
        self.planner = planner
        self.policy_gate = policy_gate
        self.tool_registry = tool_registry
        self.evaluator = evaluator
        self.stop_controller = stop_controller or StopController()
        self.session_engine = session_engine or SessionEngine()

    def run(self, input_text: str) -> AgentResult:
        task = self.session_engine.start(input_text)
        self._record_start(task, input_text=input_text)
        return self._drive(task, feedback=None)

    def run_event(self, event: Event) -> AgentResult:
        input_text = str(event.payload.get("text", ""))
        task = self.session_engine.start(input_text)
        self._record_start_event(task, event)
        return self._drive(task, feedback=None)

    def resume(self, task_id: str, *, user_input: str) -> AgentResult:
        records = self.journal.require_task(task_id)
        run_index = 1 + len({record.run_id for record in records})
        task = self.session_engine.resume(task_id, user_input, run_index)
        event = Event(
            event_id=f"evt-{task.run_id}-resume",
            run_id=task.run_id,
            type="input.resumed",
            timestamp_ms=len(records) + 1,
            payload={"text": user_input},
            source="resume",
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="resume",
            data={**event.to_dict(), "user_input": user_input},
            event_ref=event.event_id,
            state_delta={"status": "resumed"},
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="run",
            data={"run_id": task.run_id, "status": task.status},
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
            },
            event_ref=event.event_id,
            state_delta={"status": task.status},
        )
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
            kind="run",
            data={"run_id": task.run_id, "status": task.status},
            event_ref=event.event_id,
            state_delta={"status": task.status},
        )

    def _drive(self, task: TaskState, feedback: Feedback | None) -> AgentResult:
        current_feedback = feedback
        while True:
            context = self.context_compiler.compile(task, self.journal)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=None,
                kind="context",
                data=context.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                state_delta={"context_id": context.context_id},
            )
            action = self.planner.propose(context, current_feedback)
            self._record_action(task, action)
            decision = self.policy_gate.validate(run_id=task.run_id, action=action)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=None,
                kind="policy_decision",
                data=decision.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=action.action_id,
                state_delta={"policy_allowed": decision.allowed},
            )
            if decision.allowed:
                observation = self.tool_registry.execute(action)
                observation = self._bind_observation(task.run_id, action, observation)
            else:
                observation = self._blocked_observation(task.run_id, action, decision.reason)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=None,
                kind="observation",
                data=observation.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=action.action_id,
                observation_ref=observation.observation_id,
                state_delta={"observation_status": observation.status},
            )
            current_feedback = self.evaluator.evaluate(context, observation)
            self.journal.append(
                task_id=task.task_id,
                run_id=task.run_id,
                step_id=None,
                kind="feedback",
                data=current_feedback.to_dict(),
                event_ref=self._last_ref(task.task_id, "event_ref"),
                action_ref=action.action_id,
                observation_ref=observation.observation_id,
                feedback_ref=current_feedback.feedback_id,
                state_delta={"feedback_status": current_feedback.status},
            )
            if self.stop_controller.should_stop(current_feedback):
                return self._result(task, current_feedback)

    def _record_action(self, task: TaskState, action: CandidateAction) -> None:
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=None,
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

    def _result(self, task: TaskState, feedback: Feedback) -> AgentResult:
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
            step_id=None,
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
