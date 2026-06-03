from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.mission.contracts import MissionAssessment, MissionState
from kernel_v3.mission.supervisor import MissionSupervisor
from kernel_v3.mission.thread_rag import ThreadWorkingMemoryProvider


class AgentRuntimeLike(Protocol):
    journal: JournalStore
    processor_fabric: object | None

    def run(self, goal: str, **kwargs) -> AgentRuntimeResult:
        ...

    def resume(self, task_id: str, user_input: str, **kwargs) -> AgentRuntimeResult:
        ...


class MissionRuntime:
    def __init__(
        self,
        *,
        agent_runtime: AgentRuntimeLike,
        supervisor: MissionSupervisor | None = None,
        thread_memory: ThreadWorkingMemoryProvider | None = None,
        max_iterations: int = 6,
        assessor_mode: str = "rule",
    ) -> None:
        self.agent_runtime = agent_runtime
        self.journal = agent_runtime.journal
        self.thread_memory = thread_memory or ThreadWorkingMemoryProvider()
        self.supervisor = supervisor or MissionSupervisor(
            journal=self.journal,
            processor_fabric=getattr(agent_runtime, "processor_fabric", None),
            assessor_mode=assessor_mode,
            max_iterations=max_iterations,
        )
        self.max_iterations = max(1, int(max_iterations))

    def __getattr__(self, name: str):
        return getattr(self.agent_runtime, name)

    def run(
        self,
        goal: str,
        *,
        thread_id: str = "local:default",
        mode: str = "auto",
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        semantic_mode: str = "fake",
        citations_required: bool | None = None,
        execution_metadata: JsonObject | None = None,
        response_language: str | None = None,
    ) -> AgentRuntimeResult:
        mission = self.supervisor.start(
            root_goal=goal,
            thread_id=thread_id,
            metadata={"entrypoint": "run", "mode": mode},
        )
        return self._drive(
            mission,
            user_input=goal,
            task_id=None,
            thread_id=thread_id,
            mode=mode,
            planner_mode=planner_mode,
            evaluator_mode=evaluator_mode,
            synthesizer_mode=synthesizer_mode,
            semantic_mode=semantic_mode,
            citations_required=citations_required,
            execution_metadata=execution_metadata,
            response_language=response_language,
        )

    def resume(
        self,
        task_id: str,
        user_input: str,
        *,
        thread_id: str = "local:default",
        mode: str = "auto",
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        semantic_mode: str = "fake",
        citations_required: bool | None = None,
        execution_metadata: JsonObject | None = None,
        response_language: str | None = None,
    ) -> AgentRuntimeResult:
        mission = self.supervisor.start(
            root_goal=user_input,
            thread_id=thread_id,
            metadata={"entrypoint": "resume", "mode": mode, "source_task_id": task_id},
        )
        return self._drive(
            mission,
            user_input=user_input,
            task_id=task_id,
            thread_id=thread_id,
            mode=mode,
            planner_mode=planner_mode,
            evaluator_mode=evaluator_mode,
            synthesizer_mode=synthesizer_mode,
            semantic_mode=semantic_mode,
            citations_required=citations_required,
            execution_metadata=execution_metadata,
            response_language=response_language,
        )

    def _drive(
        self,
        mission: MissionState,
        *,
        user_input: str,
        task_id: str | None,
        thread_id: str,
        mode: str,
        planner_mode: str,
        evaluator_mode: str,
        synthesizer_mode: str,
        semantic_mode: str,
        citations_required: bool | None,
        execution_metadata: JsonObject | None,
        response_language: str | None,
    ) -> AgentRuntimeResult:
        current_input = user_input
        current_task_id = task_id
        last_result: AgentRuntimeResult | None = None
        last_assessment: MissionAssessment | None = None
        for index in range(1, self.max_iterations + 1):
            metadata = self._iteration_metadata(
                execution_metadata,
                mission=mission,
                thread_id=thread_id,
                task_id=current_task_id,
            )
            if current_task_id is None:
                result = self.agent_runtime.run(
                    current_input,
                    thread_id=thread_id,
                    mode=mode,
                    planner_mode=planner_mode,
                    evaluator_mode=evaluator_mode,
                    synthesizer_mode=synthesizer_mode,
                    semantic_mode=semantic_mode,
                    citations_required=citations_required,
                    execution_metadata=metadata,
                    response_language=response_language,
                )
            else:
                result = self.agent_runtime.resume(
                    current_task_id,
                    current_input,
                    thread_id=thread_id,
                    mode=mode,
                    planner_mode=planner_mode,
                    evaluator_mode=evaluator_mode,
                    synthesizer_mode=synthesizer_mode,
                    semantic_mode=semantic_mode,
                    citations_required=citations_required,
                    execution_metadata=metadata,
                    response_language=response_language,
                )
            mission, assessment = self.supervisor.assess(mission, result, index=index)
            last_result = result
            last_assessment = assessment
            current_task_id = result.task_id
            if assessment.decision == "continue" and assessment.next_directive is not None and index < self.max_iterations:
                current_input = _directive_user_input(mission, assessment)
                continue
            return self._finalize_result(result, mission=mission, assessment=assessment)
        if last_result is None or last_assessment is None:
            raise RuntimeError("MissionRuntime finished without an agent result")
        return self._mission_failure(last_result, mission=mission, assessment=last_assessment, reason="mission_iteration_limit")

    def _iteration_metadata(
        self,
        metadata: JsonObject | None,
        *,
        mission: MissionState,
        thread_id: str,
        task_id: str | None,
    ) -> JsonObject:
        merged = dict(metadata or {})
        thread_rag = self.thread_memory.compile(
            self.journal,
            thread_id=thread_id,
            task_id=task_id or mission.active_task_id,
            mission_id=mission.mission_id,
        )
        merged["mission_context"] = {
            "mission_state": mission.to_dict(),
            "directive": mission.directive,
            "instruction": (
                "Treat root_goal as the global task objective. If the previous run failed, "
                "use the directive to propose a materially different safe next action instead of giving up."
            ),
        }
        merged["thread_rag_context"] = thread_rag
        return merged

    def _finalize_result(
        self,
        result: AgentRuntimeResult,
        *,
        mission: MissionState,
        assessment: MissionAssessment,
    ) -> AgentRuntimeResult:
        if assessment.decision == "final_answer" and result.final_answer is not None:
            self._append_terminal("mission_final_answer", result, mission=mission, assessment=assessment)
            return result
        if assessment.decision in {"failure_report", "blocked"}:
            return self._mission_failure(result, mission=mission, assessment=assessment, reason=assessment.reason_summary)
        if assessment.decision == "ask_user":
            self._append_terminal("mission_ask_user", result, mission=mission, assessment=assessment)
            return result
        return result

    def _mission_failure(
        self,
        result: AgentRuntimeResult,
        *,
        mission: MissionState,
        assessment: MissionAssessment,
        reason: str,
    ) -> AgentRuntimeResult:
        failure = dict(result.failure_report or {})
        failure.setdefault("reason", reason)
        failure["reason"] = reason if result.status != "failed" else str(failure.get("reason") or reason)
        failure.setdefault("attempted_actions", [])
        failure.setdefault("attempted_sources", [])
        failure["missing_evidence"] = list(assessment.missing_requirements)
        failure["next_possible_action"] = "mission_exhausted_or_blocked"
        failure["user_help_needed"] = assessment.decision == "ask_user"
        failure["task_id"] = result.task_id
        failure["run_id"] = result.run_id
        failure["trace_refs"] = list(result.trace_refs)
        self._append_terminal("mission_failure_report", result, mission=mission, assessment=assessment, extra={"failure_report": failure})
        return replace(result, status="failed", final_answer=None, failure_report=failure)

    def _append_terminal(
        self,
        kind: str,
        result: AgentRuntimeResult,
        *,
        mission: MissionState,
        assessment: MissionAssessment,
        extra: JsonObject | None = None,
    ) -> None:
        payload = {
            "mission_id": mission.mission_id,
            "task_id": result.task_id,
            "run_id": result.run_id,
            "decision": assessment.decision,
            "assessment": assessment.to_dict(),
            "mission_state": mission.to_dict(),
            **dict(extra or {}),
        }
        self.journal.append(
            task_id=result.task_id,
            run_id=result.run_id,
            step_id=None,
            kind=kind,
            data=redact_journal_data(payload),
            state_delta={"mission_id": mission.mission_id, "mission_terminal": kind},
        )


def _directive_user_input(mission: MissionState, assessment: MissionAssessment) -> str:
    directive = assessment.next_directive if isinstance(assessment.next_directive, dict) else {}
    missing = ", ".join(str(item) for item in assessment.missing_requirements[:6])
    strategy = str(directive.get("strategy") or "try_materially_new_strategy")
    subgoal = str(directive.get("next_subgoal") or missing or mission.root_goal)
    avoid = directive.get("avoid_repeating")
    avoid_list = ", ".join(str(item) for item in avoid[:8]) if isinstance(avoid, list) else ""
    parts = [
        f"Continue the same global mission: {mission.root_goal}",
        f"Current uncovered gap: {subgoal}",
        f"Required new strategy: {strategy}",
        "Do not ask the user unless a critical permission or missing argument is genuinely required.",
        "Do not repeat failed payloads; propose a materially different safe next action.",
    ]
    if avoid_list:
        parts.append(f"Avoid repeating: {avoid_list}")
    return "\n".join(parts)
