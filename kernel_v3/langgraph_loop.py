from __future__ import annotations

from typing import Any, Literal, TypedDict

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation
from kernel_v3.loop import LoopControllerV3
from kernel_v3.result import AgentResult
from kernel_v3.session import TaskState

try:  # pragma: no cover - exercised when langgraph is installed.
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - fallback keeps imports safe.
    END = START = None
    MemorySaver = None
    StateGraph = None


def langgraph_loop_available() -> bool:
    return StateGraph is not None and START is not None and END is not None


class _LoopGraphState(TypedDict, total=False):
    task: TaskState
    current_feedback: Feedback | None
    step_index: int
    tool_calls: int
    network_fetches: int
    total_artifact_bytes: int
    started_at_ms: int
    step_id: str
    context: ContextBundle
    evaluation_context: ContextBundle
    action: CandidateAction
    manifest: Any
    observation: Observation
    artifact_refs: list[Any]
    result: AgentResult
    terminal: bool


class LangGraphLoopController(LoopControllerV3):
    """LangGraph-backed controller preserving Holo host-owned boundaries."""

    runtime_backend = "langgraph"

    def _drive(self, task: TaskState, feedback: Feedback | None) -> AgentResult:
        if not langgraph_loop_available():
            return super()._drive(task, feedback)
        graph = self._compile_langgraph_loop()
        initial: _LoopGraphState = {
            "task": task,
            "current_feedback": feedback,
            "step_index": 0,
            "tool_calls": 0,
            "network_fetches": 0,
            "total_artifact_bytes": 0,
            "started_at_ms": self.clock_ms(),
            "terminal": False,
        }
        recursion_limit = max(25, int(self.max_steps or 64) * 3 + 10)
        config = {
            "configurable": {"thread_id": f"{task.task_id}:{task.run_id}"},
            "recursion_limit": recursion_limit,
        }
        final_state = graph.invoke(initial, config=config)
        result = final_state.get("result")
        if isinstance(result, AgentResult):
            return result
        feedback = final_state.get("current_feedback")
        if isinstance(feedback, Feedback):
            return self._result(task, feedback, step_id=final_state.get("step_id"))
        return self._result(task, self._limit_feedback(task.run_id, "langgraph_loop_incomplete"))

    def _compile_langgraph_loop(self):
        graph = StateGraph(_LoopGraphState)
        graph.add_node("prepare_and_execute", self._langgraph_prepare_and_execute)
        graph.add_node("evaluate_and_route", self._langgraph_evaluate_and_route)
        graph.add_edge(START, "prepare_and_execute")
        graph.add_edge("prepare_and_execute", "evaluate_and_route")
        graph.add_conditional_edges(
            "evaluate_and_route",
            self._langgraph_route,
            {
                "continue": "prepare_and_execute",
                "done": END,
            },
        )
        checkpointer = MemorySaver() if MemorySaver is not None else None
        return graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()

    def _langgraph_prepare_and_execute(self, state: _LoopGraphState) -> _LoopGraphState:
        task = state["task"]
        step_index = int(state.get("step_index") or 0) + 1
        step_id = f"step-{step_index}"
        context = self.context_compiler.compile(task, self.journal)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="context",
            data=self._redacted_context(context),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            state_delta={"context_id": context.context_id, "loop_runtime": self.runtime_backend},
        )
        current_feedback = state.get("current_feedback")
        action = self.planner.propose(context, current_feedback if isinstance(current_feedback, Feedback) else None)
        manifest = self.tool_registry.manifest_for_action(action)
        self._record_action(task, action, step_id=step_id, manifest=manifest)
        decision = self.policy_gate.validate(run_id=task.run_id, action=action, manifest=manifest)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="policy_decision",
            data=self._redacted_policy(decision),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            state_delta={"policy_allowed": decision.allowed},
        )
        artifact_refs: list[Any] = []
        tool_calls = int(state.get("tool_calls") or 0)
        network_fetches = int(state.get("network_fetches") or 0)
        total_artifact_bytes = int(state.get("total_artifact_bytes") or 0)
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
                        "thread_id": task.thread_id,
                        "input_text": task.input_text,
                    },
                )
                observation = self._bind_observation(task.run_id, action, tool_result.observation)
                artifact_refs = list(tool_result.artifact_refs)
                if action.kind == "tool":
                    tool_calls += 1
                if self._is_network_action(action, manifest=manifest):
                    network_fetches += self._network_action_actual_cost(
                        action,
                        manifest=manifest,
                        observation=observation,
                    )
                total_artifact_bytes += self._estimate_artifact_bytes(observation, artifact_refs)
        else:
            observation = self._blocked_observation(task.run_id, action, decision.reason)
        self.journal.append(
            task_id=task.task_id,
            run_id=task.run_id,
            step_id=step_id,
            kind="observation",
            data=self._redacted_observation(observation),
            event_ref=self._last_ref(task.task_id, "event_ref"),
            action_ref=action.action_id,
            observation_ref=observation.observation_id,
            state_delta={"observation_status": observation.status},
            artifact_refs=[artifact.artifact_id for artifact in artifact_refs],
        )
        if observation.status == "blocked" and observation.content == {"reason": "max_tool_calls"}:
            self._append_guard(task, "max_tool_calls", step_id=step_id, data={"tool_calls": tool_calls})
        elif observation.status == "blocked" and observation.content == {"reason": "max_network_fetches"}:
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
        return {
            **state,
            "step_index": step_index,
            "step_id": step_id,
            "context": context,
            "action": action,
            "manifest": manifest,
            "observation": observation,
            "artifact_refs": artifact_refs,
            "tool_calls": tool_calls,
            "network_fetches": network_fetches,
            "total_artifact_bytes": total_artifact_bytes,
        }

    def _langgraph_evaluate_and_route(self, state: _LoopGraphState) -> _LoopGraphState:
        task = state["task"]
        action = state["action"]
        observation = state["observation"]
        step_id = state["step_id"]
        evaluation_context = self.context_compiler.compile(task, self.journal)
        current_feedback = self.evaluator.evaluate(evaluation_context, observation)
        self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
        guard_reason = self._guard_stop_reason(observation)
        if guard_reason is not None and not callable(getattr(self.evaluator, "finalize_guard", None)):
            current_feedback = self._limit_feedback(task.run_id, guard_reason)
            self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
            return self._terminal_state(state, task=task, feedback=current_feedback, step_id=step_id)
        resource_guard = self._resource_guard(total_artifact_bytes=int(state.get("total_artifact_bytes") or 0))
        if resource_guard is not None:
            stop_reason, data = resource_guard
            current_feedback = self._limit_feedback(task.run_id, stop_reason)
            self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
            self._append_guard(task, stop_reason, step_id=step_id, data=data)
            current_feedback = self._finalize_guard_feedback(
                evaluation_context,
                observation,
                current_feedback,
                task=task,
                action=action,
                step_id=step_id,
            )
            return self._terminal_state(state, task=task, feedback=current_feedback, step_id=step_id)
        if self.stop_controller.should_stop(current_feedback):
            return self._terminal_state(state, task=task, feedback=current_feedback, step_id=step_id)
        continuation_guard = self._continuation_guard(
            step_index=int(state.get("step_index") or 0),
            started_at_ms=int(state.get("started_at_ms") or 0),
        )
        if continuation_guard is not None:
            stop_reason, data = continuation_guard
            current_feedback = self._limit_feedback(task.run_id, stop_reason)
            self._append_feedback(task, current_feedback, action=action, observation=observation, step_id=step_id)
            self._append_guard(task, stop_reason, step_id=step_id, data=data)
            current_feedback = self._finalize_guard_feedback(
                evaluation_context,
                observation,
                current_feedback,
                task=task,
                action=action,
                step_id=step_id,
            )
            return self._terminal_state(state, task=task, feedback=current_feedback, step_id=step_id)
        return {
            **state,
            "evaluation_context": evaluation_context,
            "current_feedback": current_feedback,
            "terminal": False,
        }

    def _terminal_state(
        self,
        state: _LoopGraphState,
        *,
        task: TaskState,
        feedback: Feedback,
        step_id: str,
    ) -> _LoopGraphState:
        return {
            **state,
            "current_feedback": feedback,
            "result": self._result(task, feedback, step_id=step_id),
            "terminal": True,
        }

    def _langgraph_route(self, state: _LoopGraphState) -> Literal["continue", "done"]:
        return "done" if state.get("terminal") else "continue"

    def _redacted_context(self, context: ContextBundle):
        from kernel_v3.journal_redaction import redact_journal_data

        return redact_journal_data(context.to_dict())

    def _redacted_policy(self, decision):
        from kernel_v3.journal_redaction import redact_journal_data

        return redact_journal_data(decision.to_dict())

    def _redacted_observation(self, observation: Observation):
        from kernel_v3.journal_redaction import redact_journal_data

        return redact_journal_data(observation.to_dict())
