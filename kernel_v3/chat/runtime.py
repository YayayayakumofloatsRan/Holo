from __future__ import annotations

import json
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import AgentRuntimeResult, FinalAnswer
from kernel_v3.agent.host_situation import build_host_situation
from kernel_v3.capabilities import SAFE_SEMANTIC_CAPABILITIES
from kernel_v3.chat.contracts import (
    ChatCommand,
    ChatRuntimeResult,
    ChatThread,
    ChatTurn,
    PendingUserInput,
    ThreadState,
    ThreadSummary,
    TurnRoutingDecision,
)
from kernel_v3.chat.memory_admin import (
    memory_export_command_result,
    memory_inspection_text,
    memory_list_text,
    memory_pipeline_command_result,
    memory_proposals_command_result,
    memory_recall_command_result,
    proposal_list_text,
)
from kernel_v3.chat.thread_store import ThreadTranscriptStore
from kernel_v3.contracts import JsonObject, LedgerRecord
from kernel_v3.interaction import guard_user_visible_text
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.processors.contracts import CHAT_ROUTE_PROMPT_CONTRACT, CHAT_ROUTE_SCHEMA
from kernel_v3.text_safety import normalize_chat_input
from kernel_v3.trace import TraceRenderer


_PLAN_SAFE_CAPABILITIES = {
    "retrieval.run",
    "workspace.search",
    "file.read",
    "workspace.write",
    "workspace:read",
    "workspace:write",
    "system.time",
}
_PLAN_ALLOWED_MODES = {
    "direct_answer",
    "semantic_answer",
    "retrieval_answer",
    "workspace_answer",
    "workspace_write",
    "system_answer",
    "clarify_first",
}


class ChatRuntime:
    def __init__(
        self,
        *,
        journal: JournalStore | None = None,
        agent_runtime: AgentRuntime | None = None,
        memory_store: MemoryStore | None = None,
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        semantic_mode: str = "fake",
        turn_router_mode: str = "fake",
        default_mode: str = "auto",
        execution_metadata: JsonObject | None = None,
        thread_store: ThreadTranscriptStore | None = None,
    ) -> None:
        self.journal = journal or JournalStore.in_memory()
        self.agent_runtime = agent_runtime or AgentRuntime(journal=self.journal, workspace_root=Path.cwd())
        self.memory_store = memory_store if memory_store is not None else getattr(self.agent_runtime, "memory_store", None)
        self.memory_pipeline = MemoryPipeline(store=self.memory_store, journal=self.journal) if self.memory_store is not None else None
        self.planner_mode = planner_mode
        self.evaluator_mode = evaluator_mode
        self.synthesizer_mode = synthesizer_mode
        self.semantic_mode = semantic_mode
        self.turn_router_mode = turn_router_mode
        self.default_mode = _normalize_default_mode(default_mode)
        self.execution_metadata = dict(execution_metadata or {})
        self.thread_store = thread_store

    def receive(self, message: str, *, thread_id: str = "default") -> ChatRuntimeResult:
        message = normalize_chat_input(message)
        normalized_thread = _normalize_thread_id(thread_id)
        before = self.build_thread_state(normalized_thread)
        turn = ChatTurn(
            turn_id=f"turn-{_safe_id(normalized_thread)}-{len(_thread_turn_records(self.journal, normalized_thread)) + 1}",
            thread_id=normalized_thread,
            role="user",
            text=message,
            task_id=before.active_task_id,
            run_id=None,
            linked_turn_id=_latest_turn_ref(self.journal, normalized_thread),
            created_at_ms=len(self.journal.records()) + 1,
        )
        self._append_record(
            task_id=before.active_task_id,
            run_id=_chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_turn",
            data=redact_journal_data(turn.to_dict()),
            state_delta={"thread_id": normalized_thread, "chat_role": "user"},
        )
        decision = self.route_turn(message, state=before, turn_id=turn.turn_id)
        self._append_record(
            task_id=decision.task_id,
            run_id=_chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_routing_decision",
            data=redact_journal_data(decision.to_dict()),
            state_delta={"thread_id": normalized_thread, "chat_route": decision.route},
        )
        if decision.route == "command":
            result = self._execute_command(message, state=before, turn=turn, decision=decision)
        elif decision.route == "summary":
            result = self._summary_result(state=before, turn=turn, decision=decision)
        elif decision.route == "continue_plan":
            result = self._execute_plan_command(args=["run"], state=before, turn=turn, decision=decision)
        elif decision.route == "answer_pending_question":
            pending = PendingUserInput.from_dict(before.pending_question or {})
            self._append_record(
                task_id=pending.task_id,
                run_id=_chat_run_id(normalized_thread),
                step_id=None,
                kind="chat_pending_answer",
                data=redact_journal_data(
                    {
                        "thread_id": normalized_thread,
                        "turn_id": turn.turn_id,
                        "pending_id": pending.pending_id,
                        "task_id": pending.task_id,
                        "answer_preview": _preview(message),
                    }
                ),
                state_delta={"thread_id": normalized_thread, "pending_answered": pending.pending_id},
            )
            plan_record = _latest_task_plan_record(self.journal, normalized_thread, task_id=pending.task_id)
            plan_response = _plan_confirmation_from_decision(decision)
            if plan_response == "approve":
                result = self._execute_plan_command(args=["approve"], state=before, turn=turn, decision=decision)
            elif plan_response == "reject":
                reject_args = (
                    ["reject", str(plan_record.data.get("plan_id") or ""), _preview(message, limit=80)]
                    if plan_record is not None
                    else ["reject"]
                )
                result = self._execute_plan_command(
                    args=reject_args,
                    state=before,
                    turn=turn,
                    decision=decision,
                )
            else:
                agent_result = self.agent_runtime.resume(
                    pending.task_id,
                    message,
                    thread_id=normalized_thread,
                    mode=_resume_mode_for_input(self.journal, pending.task_id),
                    planner_mode=self.planner_mode,
                    evaluator_mode=self.evaluator_mode,
                    synthesizer_mode=self.synthesizer_mode,
                    semantic_mode=self.semantic_mode,
                    execution_metadata=self._agent_execution_metadata(state=before, turn=turn, decision=decision),
                )
                result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        elif decision.route == "continue_task":
            task_id = before.active_task_id or ""
            agent_result = self.agent_runtime.resume(
                task_id,
                message,
                thread_id=normalized_thread,
                mode=_mode_for_task(self.journal, task_id),
                planner_mode=self.planner_mode,
                evaluator_mode=self.evaluator_mode,
                synthesizer_mode=self.synthesizer_mode,
                semantic_mode=self.semantic_mode,
                execution_metadata=self._agent_execution_metadata(state=before, turn=turn, decision=decision),
            )
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        else:
            mode = "clarify_first" if "continue_without_active_task" in decision.reasons else self.default_mode
            agent_result = self.agent_runtime.run(
                message,
                thread_id=normalized_thread,
                mode=mode,
                planner_mode=self.planner_mode,
                evaluator_mode=self.evaluator_mode,
                synthesizer_mode=self.synthesizer_mode,
                semantic_mode=self.semantic_mode,
                execution_metadata=self._agent_execution_metadata(state=before, turn=turn, decision=decision),
            )
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        self._append_record(
            task_id=result.task_id,
            run_id=result.run_id or _chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_agent_result",
            data=redact_journal_data(result.to_dict()),
            state_delta={"thread_id": normalized_thread, "chat_result_status": result.status},
        )
        self._append_thread_summary(normalized_thread)
        return result

    def route_turn(self, message: str, *, state: ThreadState, turn_id: str) -> TurnRoutingDecision:
        stripped = message.strip()
        command = _command_name(stripped)
        if command is not None:
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="command",
                task_id=state.active_task_id,
                command=command,
                reasons=["slash_command"],
            )
        if state.pending_question is not None:
            if self.turn_router_mode == "model":
                routed = self._route_turn_with_model(message, state=state, turn_id=turn_id)
                if routed is not None:
                    return routed
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="answer_pending_question",
                task_id=str(state.pending_question["task_id"]),
                command=None,
                reasons=["pending_user_input"],
            )
        if self.turn_router_mode == "model":
            routed = self._route_turn_with_model(message, state=state, turn_id=turn_id)
            if routed is not None:
                return routed
        return TurnRoutingDecision(
            decision_id=f"route-{turn_id}",
            thread_id=state.thread_id,
            turn_id=turn_id,
            route="new_task",
            task_id=None,
            command=None,
            reasons=["no_pending_or_continue_route"],
        )

    def _route_turn_with_model(self, message: str, *, state: ThreadState, turn_id: str) -> TurnRoutingDecision | None:
        fabric = getattr(self.agent_runtime, "processor_fabric", None)
        if fabric is None:
            return None
        plan_record = _latest_continuable_task_plan_record(self.journal, state.thread_id)
        pending_plan_record = None
        if state.pending_question is not None:
            pending_plan_record = _latest_task_plan_record(
                self.journal,
                state.thread_id,
                task_id=str(state.pending_question["task_id"]),
            )
        outcome = fabric.run_json(
            task_type="chat.route",
            task_id=state.active_task_id,
            run_id=_chat_run_id(state.thread_id),
            context_id=f"chat:{state.thread_id}",
            prompt=_chat_route_prompt(
                message,
                state=state,
                continuable_plan=plan_record,
                pending_plan=pending_plan_record,
                host_situation=build_host_situation(
                    journal=self.journal,
                    task_id=state.active_task_id,
                    thread_id=state.thread_id,
                ),
            ),
            schema=CHAT_ROUTE_SCHEMA,
            parameters={"adapter": "ChatTurnRouter", "contract_version": 1},
        )
        if outcome.parsed is None:
            return None
        return _decision_from_route_proposal(
            outcome.parsed,
            state=state,
            turn_id=turn_id,
            user_turn=message,
            continuable_plan=plan_record,
            pending_plan=pending_plan_record,
        )

    def build_thread_state(self, thread_id: str) -> ThreadState:
        normalized_thread = _normalize_thread_id(thread_id)
        clear_at = _latest_clear_at(self.journal, normalized_thread)
        task_records = [
            record
            for record in self.journal.records(kind="task")
            if record.data.get("thread_id") == normalized_thread and record.recorded_at_ms > clear_at
        ]
        task_refs = _ordered_unique([str(record.task_id) for record in task_records if record.task_id])
        latest_agent = _latest_chat_agent_result(self.journal, normalized_thread, after_ms=clear_at)
        active_task_id = task_refs[-1] if latest_agent is None and task_refs else None
        last_result_status = None
        pending: PendingUserInput | None = None
        if latest_agent is not None:
            last_result_status = str(latest_agent.data.get("status") or "unknown")
            if _keeps_task_active(last_result_status):
                active_task_id = latest_agent.task_id
            if last_result_status == "needs_user_input" and latest_agent.task_id is not None:
                pending = _pending_for_task(
                    self.journal,
                    thread_id=normalized_thread,
                    task_id=latest_agent.task_id,
                    run_id=str(latest_agent.data.get("run_id") or latest_agent.run_id),
                )
        summary = _latest_thread_summary_record(self.journal, normalized_thread)
        recent_turns = _thread_turn_records(self.journal, normalized_thread)[-8:]
        return ThreadState(
            thread_id=normalized_thread,
            active_task_id=active_task_id,
            pending_question=pending.to_dict() if pending is not None else None,
            recent_turn_refs=[record.record_id for record in recent_turns],
            recent_task_refs=task_refs[-8:],
            last_result_status=last_result_status,
            thread_summary_ref=summary.record_id if summary is not None else None,
        )

    def summarize_thread(self, thread_id: str) -> ThreadSummary:
        normalized_thread = _normalize_thread_id(thread_id)
        state = self.build_thread_state(normalized_thread)
        turns = []
        for record in _thread_turn_records(self.journal, normalized_thread)[-6:]:
            turns.append(
                {
                    "turn_id": record.data.get("turn_id"),
                    "role": record.data.get("role"),
                    "text_preview": _preview(str(record.data.get("text", "")), limit=160),
                    "task_id": record.data.get("task_id"),
                }
            )
        return ThreadSummary(
            summary_id=f"summary-{_safe_id(normalized_thread)}-{len(_thread_summary_records(self.journal, normalized_thread)) + 1}",
            thread_id=normalized_thread,
            active_task_id=state.active_task_id,
            pending_question=state.pending_question,
            last_result_status=state.last_result_status,
            last_answer_preview=_latest_answer_preview(self.journal, normalized_thread),
            last_failure_reason=_latest_failure_reason(self.journal, normalized_thread),
            recent_turns=turns,
            recent_task_refs=list(state.recent_task_refs),
        )

    def _execute_command(
        self,
        message: str,
        *,
        state: ThreadState,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        name, args = _parse_command(message)
        if name == "/new" and args:
            command = self._append_command(turn, name=name, args=args, status="ok", result={"started_new_task": True})
            goal = " ".join(args)
            agent_result = self.agent_runtime.run(
                goal,
                thread_id=state.thread_id,
                mode=self.default_mode,
                planner_mode=self.planner_mode,
                evaluator_mode=self.evaluator_mode,
                synthesizer_mode=self.synthesizer_mode,
                semantic_mode=self.semantic_mode,
                execution_metadata=self._agent_execution_metadata(state=state, turn=turn, decision=decision),
            )
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
            return _replace_command_result(result, command.result)
        if name in {"/cancel", "/interrupt"}:
            command = self._append_command(turn, name=name, args=args, status="ok", result={"active_task_cleared": state.active_task_id})
            return self._command_result(turn=turn, decision=decision, status="canceled", command=command, answer="Active task interrupted.")
        if name == "/new":
            command = self._append_command(turn, name=name, args=args, status="ok", result={"active_task_cleared": state.active_task_id})
            return self._command_result(turn=turn, decision=decision, status="ready", command=command, answer="Started a new empty chat task boundary.")
        if name == "/status":
            command = self._append_command(turn, name=name, args=args, status="ok", result=state.to_dict())
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=_status_text(state))
        if name == "/tasks":
            command = self._append_command(turn, name=name, args=args, status="ok", result={"tasks": list(state.recent_task_refs)})
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer="\n".join(state.recent_task_refs))
        if name == "/trace":
            task_id = args[0] if args else state.active_task_id
            trace = TraceRenderer(self.journal).render_task(task_id, verbose=True) if task_id else "No active task."
            command = self._append_command(turn, name=name, args=args, status="ok", result={"task_id": task_id, "trace": trace})
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=trace)
        if name == "/summary":
            summary = self._append_thread_summary(state.thread_id)
            command = self._append_command(turn, name=name, args=args, status="ok", result=summary.to_dict())
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=_summary_text(summary), summary=summary)
        if name == "/plan":
            return self._execute_plan_command(args=args, state=state, turn=turn, decision=decision)
        if name == "/memory":
            return self._execute_memory_command(args=args, state=state, turn=turn, decision=decision)
        if name == "/help":
            result = {"commands": ["/status", "/trace", "/summary", "/tasks", "/plan", "/memory", "/interrupt", "/cancel", "/new", "/help"]}
            command = self._append_command(turn, name=name, args=args, status="ok", result=result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=", ".join(result["commands"]))
        command = self._append_command(turn, name=name, args=args, status="unknown", result={"error": "unknown_command"})
        return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="Unknown command.")

    def _execute_plan_command(
        self,
        *,
        args: list[str],
        state: ThreadState,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        subcommand = args[0].lower() if args else "show"
        plan_record = _latest_task_plan_record(self.journal, state.thread_id, task_id=state.active_task_id)
        if plan_record is None:
            result = {"error": "no_task_plan", "usage": "/plan [show]|approve [plan_id]|run [plan_id]|reject [plan_id] [reason]|finalize [plan_id]"}
            command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
            return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="No task plan for this thread.")
        plan = dict(plan_record.data)
        plan_id = str(plan.get("plan_id") or "")
        requested_plan_id = args[1] if len(args) >= 2 else plan_id
        if subcommand in {"show", "status"}:
            progress = _plan_progress(self.journal, plan_record=plan_record, plan=plan)
            result = {
                "plan_id": plan_id,
                "task_id": plan_record.task_id,
                "run_id": plan_record.run_id,
                "plan": plan,
                "progress": progress,
            }
            command = self._append_command(turn, name="/plan", args=args, status="ok", result=result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=_task_plan_text(plan, progress=progress))
        if subcommand == "reject":
            if requested_plan_id != plan_id:
                result = {"error": "plan_not_found", "requested_plan_id": requested_plan_id, "latest_plan_id": plan_id}
                command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
                return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="No matching task plan.")
            reason = " ".join(args[2:]) or "user_rejected"
            decision_record = self._append_plan_decision(
                turn,
                plan_record=plan_record,
                plan=plan,
                decision="rejected",
                reason=reason,
                step=None,
                agent_result=None,
            )
            result = {
                "plan_id": plan_id,
                "plan_task_id": plan_record.task_id,
                "decision": "rejected",
                "reason": reason,
                "decision_ref": decision_record.record_id,
            }
            command = self._append_command(turn, name="/plan", args=args, status="ok", result=result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Rejected plan {plan_id}.")
        if subcommand == "approve":
            if requested_plan_id != plan_id:
                result = {"error": "plan_not_found", "requested_plan_id": requested_plan_id, "latest_plan_id": plan_id}
                command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
                return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="No matching task plan.")
            step = _next_executable_plan_step(self.journal, plan, plan_ref=plan_record.record_id)
            if step is None:
                if _ready_plan_finalizer_step(plan) is not None:
                    return self._finalize_plan_command(
                        args=args,
                        plan_record=plan_record,
                        plan=plan,
                        plan_id=plan_id,
                        turn=turn,
                        decision=decision,
                    )
                decision_record = self._append_plan_decision(
                    turn,
                    plan_record=plan_record,
                    plan=plan,
                    decision="blocked",
                    reason="no_safe_executable_step",
                    step=None,
                    agent_result=None,
                )
                result = {
                    "plan_id": plan_id,
                    "plan_task_id": plan_record.task_id,
                    "decision": "blocked",
                    "reason": "no_safe_executable_step",
                    "decision_ref": decision_record.record_id,
                }
                command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
                return self._command_result(
                    turn=turn,
                    decision=decision,
                    status="failed",
                    command=command,
                    answer="No safe executable step is available in the latest task plan.",
                )
            agent_result = self.agent_runtime.run(
                str(step.get("goal") or plan.get("goal") or ""),
                thread_id=state.thread_id,
                mode=_plan_step_mode(step),
                planner_mode=self.planner_mode,
                evaluator_mode=self.evaluator_mode,
                synthesizer_mode=self.synthesizer_mode,
                semantic_mode="fake",
                citations_required=_plan_step_citations_required(step),
                execution_metadata=self._agent_execution_metadata(
                    state=state,
                    turn=turn,
                    decision=decision,
                    extra={"task_execution_step": dict(step)},
                ),
            )
            decision_record = self._append_plan_decision(
                turn,
                plan_record=plan_record,
                plan=plan,
                decision="approved",
                reason="executed_first_safe_step",
                step=step,
                agent_result=agent_result,
            )
            command_result = {
                "started_new_task": True,
                "plan_id": plan_id,
                "plan_task_id": plan_record.task_id,
                "decision": "approved",
                "decision_ref": decision_record.record_id,
                "executed_step_id": step.get("step_id"),
                "executed_node_id": step.get("node_id"),
                "spawned_task_id": agent_result.task_id,
                "spawned_run_id": agent_result.run_id,
            }
            command = self._append_command(turn, name="/plan", args=args, status="ok", result=command_result)
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
            return _replace_command_result(result, command.result)
        if subcommand in {"run", "continue"}:
            if requested_plan_id != plan_id:
                result = {"error": "plan_not_found", "requested_plan_id": requested_plan_id, "latest_plan_id": plan_id}
                command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
                return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="No matching task plan.")
            return self._run_plan_command(
                args=args,
                state=state,
                plan_record=plan_record,
                plan=plan,
                plan_id=plan_id,
                turn=turn,
                decision=decision,
            )
        if subcommand in {"finalize", "finish"}:
            if requested_plan_id != plan_id:
                result = {"error": "plan_not_found", "requested_plan_id": requested_plan_id, "latest_plan_id": plan_id}
                command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
                return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="No matching task plan.")
            return self._finalize_plan_command(
                args=args,
                plan_record=plan_record,
                plan=plan,
                plan_id=plan_id,
                turn=turn,
                decision=decision,
            )
        result = {"error": "invalid_plan_command", "usage": "/plan [show]|approve [plan_id]|run [plan_id]|reject [plan_id] [reason]|finalize [plan_id]"}
        command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
        return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer=result["usage"])

    def _run_plan_command(
        self,
        *,
        args: list[str],
        state: ThreadState,
        plan_record: LedgerRecord,
        plan: JsonObject,
        plan_id: str,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        executed_steps: list[JsonObject] = []
        last_agent_result: AgentRuntimeResult | None = None
        plan_ref = plan_record.record_id
        for _ in range(_plan_run_limit(plan)):
            step = _next_executable_plan_step(self.journal, plan, plan_ref=plan_ref)
            if step is None:
                break
            agent_result = self.agent_runtime.run(
                str(step.get("goal") or plan.get("goal") or ""),
                thread_id=state.thread_id,
                mode=_plan_step_mode(step),
                planner_mode=self.planner_mode,
                evaluator_mode=self.evaluator_mode,
                synthesizer_mode=self.synthesizer_mode,
                semantic_mode="fake",
                citations_required=_plan_step_citations_required(step),
                execution_metadata=self._agent_execution_metadata(
                    state=state,
                    turn=turn,
                    decision=decision,
                    extra={"task_execution_step": dict(step)},
                ),
            )
            decision_record = self._append_plan_decision(
                turn,
                plan_record=plan_record,
                plan=plan,
                decision="approved",
                reason="run_next_safe_step",
                step=step,
                agent_result=agent_result,
            )
            executed_steps.append(
                {
                    "decision_ref": decision_record.record_id,
                    "executed_step_id": step.get("step_id"),
                    "executed_node_id": step.get("node_id"),
                    "spawned_task_id": agent_result.task_id,
                    "spawned_run_id": agent_result.run_id,
                    "spawned_status": agent_result.status,
                }
            )
            last_agent_result = agent_result
            if agent_result.status != "completed":
                command = self._append_command(
                    turn,
                    name="/plan",
                    args=args,
                    status="ok",
                    result={
                        "plan_id": plan_id,
                        "plan_task_id": plan_record.task_id,
                        "decision": "run_paused",
                        "reason": f"spawned_task_{agent_result.status}",
                        "executed_steps": executed_steps,
                        **_single_executed_step_fields(executed_steps),
                    },
                )
                result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
                return _replace_command_result(result, command.result)
        finalizer = _ready_plan_finalizer_step(plan)
        if finalizer is not None:
            final_answer, final_record, failure, already_finalized = self._finalize_plan_result(
                plan_record=plan_record,
                plan=plan,
                turn=turn,
            )
            if failure is None and final_answer is not None and final_record is not None:
                command = self._append_command(
                    turn,
                    name="/plan",
                    args=args,
                    status="ok",
                    result={
                        "plan_id": plan_id,
                        "plan_task_id": plan_record.task_id,
                        "decision": "run_finalized",
                        "executed_steps": executed_steps,
                        **_single_executed_step_fields(executed_steps),
                        "final_answer_ref": final_record.record_id,
                        "citation_refs": list(final_answer.citation_refs),
                        "already_finalized": already_finalized,
                    },
                )
                return ChatRuntimeResult(
                    status="completed",
                    thread_id=turn.thread_id,
                    turn_id=turn.turn_id,
                    route=decision.route,
                    task_id=plan_record.task_id,
                    run_id=plan_record.run_id,
                    answer=final_answer.answer,
                    final_answer=final_answer.to_dict(),
                    failure_report=None,
                    pending_question=self.build_thread_state(turn.thread_id).pending_question,
                    command_result=command.result,
                    summary=None,
                    trace_refs=[final_record.record_id, command.command_id],
                )
            command = self._append_command(
                turn,
                name="/plan",
                args=args,
                status="failed",
                result={
                    "plan_id": plan_id,
                    "plan_task_id": plan_record.task_id,
                    "decision": "run_failed",
                    "executed_steps": executed_steps,
                    **_single_executed_step_fields(executed_steps),
                    **(failure or {"reason": "plan_finalization_failed"}),
                },
            )
            return self._command_result(
                turn=turn,
                decision=decision,
                status="failed",
                command=command,
                answer=str((failure or {}).get("reason") or "plan_finalization_failed"),
            )
        if _has_blocked_remaining_plan_steps(self.journal, plan, plan_ref=plan_ref):
            decision_record = self._append_plan_decision(
                turn,
                plan_record=plan_record,
                plan=plan,
                decision="blocked",
                reason="no_more_safe_executable_steps",
                step=None,
                agent_result=None,
            )
            result = {
                "plan_id": plan_id,
                "plan_task_id": plan_record.task_id,
                "decision": "run_blocked",
                "reason": "no_more_safe_executable_steps",
                "decision_ref": decision_record.record_id,
                "executed_steps": executed_steps,
                **_single_executed_step_fields(executed_steps),
            }
            command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
            return self._command_result(
                turn=turn,
                decision=decision,
                status="failed",
                command=command,
                answer="No more safe executable steps are available in the latest task plan.",
            )
        command = self._append_command(
            turn,
            name="/plan",
            args=args,
            status="ok",
            result={
                "plan_id": plan_id,
                "plan_task_id": plan_record.task_id,
                "decision": "run_completed",
                "executed_steps": executed_steps,
                **_single_executed_step_fields(executed_steps),
                "reason": "no_remaining_executable_steps",
            },
        )
        if last_agent_result is not None:
            result = self._agent_result(turn=turn, decision=decision, agent_result=last_agent_result)
            return _replace_command_result(result, command.result)
        return self._command_result(
            turn=turn,
            decision=decision,
            status="completed",
            command=command,
            answer="No remaining executable plan steps.",
        )

    def _finalize_plan_command(
        self,
        *,
        args: list[str],
        plan_record: LedgerRecord,
        plan: JsonObject,
        plan_id: str,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        final_answer, final_record, failure, already_finalized = self._finalize_plan_result(
            plan_record=plan_record,
            plan=plan,
            turn=turn,
        )
        if failure is None and final_answer is not None and final_record is not None:
            command = self._append_command(
                turn,
                name="/plan",
                args=args,
                status="ok",
                result={
                    "plan_id": plan_id,
                    "plan_task_id": plan_record.task_id,
                    "final_answer_ref": final_record.record_id,
                    "citation_refs": list(final_answer.citation_refs),
                    "already_finalized": already_finalized,
                },
            )
            return ChatRuntimeResult(
                status="completed",
                thread_id=turn.thread_id,
                turn_id=turn.turn_id,
                route=decision.route,
                task_id=plan_record.task_id,
                run_id=plan_record.run_id,
                answer=final_answer.answer,
                final_answer=final_answer.to_dict(),
                failure_report=None,
                pending_question=self.build_thread_state(turn.thread_id).pending_question,
                command_result=command.to_dict(),
                summary=None,
                trace_refs=[final_record.record_id, command.command_id],
            )
        result = {"plan_id": plan_id, "plan_task_id": plan_record.task_id, **(failure or {"reason": "plan_finalization_failed"})}
        command = self._append_command(turn, name="/plan", args=args, status="failed", result=result)
        return self._command_result(
            turn=turn,
            decision=decision,
            status="failed",
            command=command,
            answer=str(result["reason"]),
        )

    def _finalize_plan_result(
        self,
        *,
        plan_record: LedgerRecord,
        plan: JsonObject,
        turn: ChatTurn,
    ):
        existing = _latest_plan_final_answer_record(self.journal, plan_record=plan_record)
        if existing is not None:
            return FinalAnswer.from_dict(existing.data), existing, None, True
        final_answer, failure = _build_plan_final_answer(self.journal, plan_record=plan_record, plan=plan)
        if failure is not None:
            return None, None, failure, False
        assert final_answer is not None
        record = self._append_record(
            task_id=plan_record.task_id,
            run_id=plan_record.run_id,
            step_id=None,
            kind="semantic_task_plan_final_answer",
            data=redact_journal_data(final_answer.to_dict()),
            state_delta={"thread_id": turn.thread_id, "task_plan_final_answer": "ok"},
        )
        return final_answer, record, None, False

    def _append_plan_decision(
        self,
        turn: ChatTurn,
        *,
        plan_record: LedgerRecord,
        plan: JsonObject,
        decision: str,
        reason: str,
        step: JsonObject | None,
        agent_result: AgentRuntimeResult | None,
    ) -> LedgerRecord:
        data: JsonObject = {
            "thread_id": turn.thread_id,
            "turn_id": turn.turn_id,
            "plan_ref": plan_record.record_id,
            "plan_id": str(plan.get("plan_id") or ""),
            "decision": decision,
            "reason": reason,
            "executed_step": dict(step) if step is not None else None,
            "spawned_task_id": agent_result.task_id if agent_result is not None else None,
            "spawned_run_id": agent_result.run_id if agent_result is not None else None,
            "spawned_status": agent_result.status if agent_result is not None else None,
        }
        return self._append_record(
            task_id=plan_record.task_id,
            run_id=plan_record.run_id,
            step_id=None,
            kind="semantic_task_plan_decision",
            data=redact_journal_data(data),
            state_delta={"thread_id": turn.thread_id, "task_plan_decision": decision},
        )

    def _execute_memory_command(
        self,
        *,
        args: list[str],
        state: ThreadState,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        if self.memory_store is None or self.memory_pipeline is None:
            command = self._append_command(turn, name="/memory", args=args, status="failed", result={"error": "memory_store_not_configured"})
            return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="Memory store is not configured.")
        subcommand = args[0].lower() if args else "list"
        if subcommand == "list":
            payload = self.memory_store.recall(
                scope={"thread_id": state.thread_id},
                limit=20,
                record_access=True,
                access_context={
                    "surface": "chat",
                    "thread_id": state.thread_id,
                    "turn_id": turn.turn_id,
                    "command": "/memory list",
                },
            ).to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=memory_recall_command_result(payload))
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=memory_list_text(payload))
        if subcommand in {"proposals", "proposal"}:
            payload = {"proposals": [_proposal.to_dict() for _proposal in self.memory_store.proposals() if _proposal.source_thread_id == state.thread_id]}
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=memory_proposals_command_result(payload))
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=proposal_list_text(payload))
        if subcommand in {"inspect", "status"}:
            payload = self.memory_store.inspect(journal=self.journal).to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=memory_inspection_text(payload))
        if subcommand == "approve" and len(args) >= 2:
            try:
                result = self.memory_pipeline.approve_proposal(args[1], approved_by="user")
            except (KeyError, ValueError) as exc:
                return self._memory_command_failed(turn=turn, decision=decision, args=args, error=_exception_reason(exc))
            payload = result.to_dict()
            command_result = memory_pipeline_command_result(payload)
            command_result["resolved_pending"] = _memory_review_resolution(args[1], decision="approved")
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=command_result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Approved {args[1]}.")
        if subcommand == "reject" and len(args) >= 2:
            reason = " ".join(args[2:]) or "user_rejected"
            try:
                result = self.memory_pipeline.reject_proposal(args[1], reason=reason)
            except (KeyError, ValueError) as exc:
                return self._memory_command_failed(turn=turn, decision=decision, args=args, error=_exception_reason(exc))
            payload = result.to_dict()
            command_result = memory_pipeline_command_result(payload)
            command_result["resolved_pending"] = _memory_review_resolution(args[1], decision="rejected")
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=command_result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Rejected {args[1]}.")
        if subcommand == "delete" and len(args) >= 2:
            reason = " ".join(args[2:]) or "user_deleted"
            try:
                tombstone = self.memory_pipeline.delete_memory(
                    args[1],
                    reason=reason,
                    deleted_by="user",
                    task_id=turn.task_id,
                    run_id=_chat_run_id(turn.thread_id),
                )
            except (KeyError, ValueError) as exc:
                return self._memory_command_failed(turn=turn, decision=decision, args=args, error=_exception_reason(exc))
            payload = tombstone.to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Deleted {args[1]}.")
        if subcommand == "export" and len(args) >= 2:
            try:
                payload = self.memory_store.export_item(
                    args[1],
                    record_access=True,
                    access_context={
                        "surface": "chat",
                        "thread_id": state.thread_id,
                        "turn_id": turn.turn_id,
                        "command": "/memory export",
                    },
                )
            except (KeyError, ValueError) as exc:
                return self._memory_command_failed(turn=turn, decision=decision, args=args, error=_exception_reason(exc))
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=memory_export_command_result(payload))
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Exported {args[1]} metadata.")
        result = {"error": "invalid_memory_command", "usage": "/memory list|proposals|inspect|approve <id>|reject <id> [reason]|delete <id> [reason]|export <id>"}
        command = self._append_command(turn, name="/memory", args=args, status="failed", result=result)
        return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer=result["usage"])

    def _memory_command_failed(
        self,
        *,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
        args: list[str],
        error: str,
    ) -> ChatRuntimeResult:
        result = {
            "error": error,
            "subcommand": args[0] if args else "",
            **({"target_id": args[1]} if len(args) >= 2 else {}),
        }
        command = self._append_command(turn, name="/memory", args=args, status="failed", result=result)
        return self._command_result(
            turn=turn,
            decision=decision,
            status="failed",
            command=command,
            answer=f"Memory command failed: {error}",
        )

    def _execution_metadata(self, extra: JsonObject | None = None) -> JsonObject:
        result = dict(self.execution_metadata)
        result.update(dict(extra or {}))
        return result

    def _agent_execution_metadata(
        self,
        *,
        state: ThreadState,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
        extra: JsonObject | None = None,
    ) -> JsonObject:
        result = self._execution_metadata(extra)
        result["thread_working_context"] = _thread_working_context(
            self.journal,
            state=state,
            turn=turn,
            decision=decision,
        )
        return result

    def _agent_result(
        self,
        *,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
        agent_result: AgentRuntimeResult,
    ) -> ChatRuntimeResult:
        answer = None
        if agent_result.final_answer is not None and isinstance(agent_result.final_answer.get("answer"), str):
            answer = str(agent_result.final_answer["answer"])
        elif agent_result.failure_report is not None:
            answer = _failure_answer_text(agent_result.failure_report, user_goal=turn.text)
        pending = None
        if agent_result.status == "needs_user_input":
            pending = _pending_for_task(
                self.journal,
                thread_id=turn.thread_id,
                task_id=agent_result.task_id,
                run_id=agent_result.run_id,
            ).to_dict()
        return ChatRuntimeResult(
            status=agent_result.status,
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
            route=decision.route,
            task_id=agent_result.task_id,
            run_id=agent_result.run_id,
            answer=answer,
            final_answer=agent_result.final_answer,
            failure_report=agent_result.failure_report,
            pending_question=pending,
            command_result=None,
            summary=None,
            trace_refs=list(agent_result.trace_refs),
            host_situation=dict(agent_result.host_situation),
        )

    def _summary_result(
        self,
        *,
        state: ThreadState,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
    ) -> ChatRuntimeResult:
        summary = self._append_thread_summary(state.thread_id)
        return ChatRuntimeResult(
            status="completed",
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
            route=decision.route,
            task_id=None,
            run_id=None,
            answer=_summary_text(summary),
            final_answer=None,
            failure_report=None,
            pending_question=None,
            command_result=None,
            summary=summary.to_dict(),
            trace_refs=[summary.summary_id],
        )

    def _command_result(
        self,
        *,
        turn: ChatTurn,
        decision: TurnRoutingDecision,
        status: str,
        command: ChatCommand,
        answer: str,
        summary: ThreadSummary | None = None,
    ) -> ChatRuntimeResult:
        result_task_id = decision.task_id
        if command.name in {"/cancel", "/interrupt", "/new"} and not command.result.get("started_new_task"):
            result_task_id = None
        return ChatRuntimeResult(
            status=status,
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
            route=decision.route,
            task_id=result_task_id,
            run_id=None,
            answer=answer,
            final_answer=None,
            failure_report=None,
            pending_question=self.build_thread_state(turn.thread_id).pending_question,
            command_result=command.to_dict(),
            summary=summary.to_dict() if summary is not None else None,
            trace_refs=[command.command_id],
        )

    def _append_command(
        self,
        turn: ChatTurn,
        *,
        name: str,
        args: list[str],
        status: str,
        result: JsonObject,
    ) -> ChatCommand:
        command = ChatCommand(
            command_id=f"cmd-{turn.turn_id}",
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
            name=name,
            args=list(args),
            status=status,
            result=result,
        )
        self._append_record(
            task_id=turn.task_id,
            run_id=_chat_run_id(turn.thread_id),
            step_id=None,
            kind="chat_command",
            data=redact_journal_data(command.to_dict()),
            state_delta={"thread_id": turn.thread_id, "chat_command": name},
        )
        return command

    def _append_thread_summary(self, thread_id: str) -> ThreadSummary:
        summary = self.summarize_thread(thread_id)
        record = self._append_record(
            task_id=summary.active_task_id,
            run_id=_chat_run_id(summary.thread_id),
            step_id=None,
            kind="thread_summary",
            data=redact_journal_data(summary.to_dict()),
            state_delta={"thread_id": summary.thread_id, "thread_summary": summary.summary_id},
        )
        return ThreadSummary(
            summary_id=record.record_id,
            thread_id=summary.thread_id,
            active_task_id=summary.active_task_id,
            pending_question=summary.pending_question,
            last_result_status=summary.last_result_status,
            last_answer_preview=summary.last_answer_preview,
            last_failure_reason=summary.last_failure_reason,
            recent_turns=summary.recent_turns,
            recent_task_refs=summary.recent_task_refs,
        )

    def _append_record(self, **kwargs) -> LedgerRecord:
        record = self.journal.append(**kwargs)
        if self.thread_store is not None:
            self.thread_store.append_journal_record(record)
        return record

    def thread(self, thread_id: str) -> ChatThread:
        state = self.build_thread_state(thread_id)
        return ChatThread(
            thread_id=state.thread_id,
            active_task_id=state.active_task_id,
            status="pending_user_input" if state.pending_question is not None else (state.last_result_status or "new"),
            turn_count=len(_thread_turn_records(self.journal, state.thread_id)),
        )


def _replace_command_result(result: ChatRuntimeResult, command_result: JsonObject) -> ChatRuntimeResult:
    return ChatRuntimeResult(
        status=result.status,
        thread_id=result.thread_id,
        turn_id=result.turn_id,
        route=result.route,
        task_id=result.task_id,
        run_id=result.run_id,
        answer=result.answer,
        final_answer=result.final_answer,
        failure_report=result.failure_report,
        pending_question=result.pending_question,
        command_result=command_result,
        summary=result.summary,
        trace_refs=result.trace_refs,
        host_situation=dict(result.host_situation),
    )


def _chat_route_prompt(
    message: str,
    *,
    state: ThreadState,
    continuable_plan: LedgerRecord | None,
    pending_plan: LedgerRecord | None,
    host_situation: JsonObject | None = None,
) -> str:
    pending_plan_confirmation = _is_pending_plan_confirmation(pending_plan)
    pending_task = _route_plan_summary(pending_plan)
    continuable_task = _route_plan_summary(continuable_plan)
    payload = {
        "contract": CHAT_ROUTE_PROMPT_CONTRACT,
        "contract_version": 1,
        "user_turn": message,
        "thread_state": {
            "thread_id": state.thread_id,
            "active_task_id": state.active_task_id,
            "pending_question": state.pending_question,
            "last_result_status": state.last_result_status,
            "recent_task_refs": list(state.recent_task_refs),
            "thread_summary_ref": state.thread_summary_ref,
        },
        "pending_task": pending_task,
        "continuable_task": continuable_task,
        "host_state": {
            "active_task_present": state.active_task_id is not None,
            "pending_user_input": state.pending_question is not None,
            "pending_plan_confirmation": pending_plan_confirmation,
            "continuable_task_plan_present": continuable_plan is not None,
            "continuable_task_id": continuable_plan.task_id if continuable_plan is not None else None,
            "continuable_plan_id": continuable_plan.data.get("plan_id") if continuable_plan is not None else None,
        },
        "host_situation": dict(host_situation or {}),
        "host_rules": [
            "Do not execute commands, tools, memory writes, or transports.",
            "pending_user_input is context, not a forced route.",
            "Use answer_pending_question only when the turn directly answers the pending question or explicitly approves/rejects a pending plan.",
            "Use answer_pending_question for missing slots or parameters of the same task, such as a filename, target, date range, approval, or rejection.",
            "If the pending task is broad clarify_first and the new turn is a complete standalone goal, use new_task instead of resuming the old clarification task.",
            "A broad clarification pending from a vague turn such as 'I do not understand' should not capture a later tool-bearing goal such as search, retrieval, research, file read/write, time, or system-state work.",
            "If the new turn changes domain, tool surface, or objective from the pending task, use new_task.",
            "Use new_task when the turn is a clear fresh request, even if an older pending question exists.",
            "If pending_plan_confirmation is true, set command to approve_plan or reject_plan when the turn semantically approves or rejects.",
            "Use continue_plan only when the user wants to advance an unfinished approved task plan.",
            "Use continue_task only when the user wants to resume an active task.",
            "Use summary only for broad recap, overview, or history-list requests.",
            "Use new_task for specific questions whose answer should be extracted from current thread context, so the normal agent can answer naturally.",
            "A bare confusion turn such as 'I do not understand' is not a summary request.",
            "For current thread, host, agent, or runtime state queries, use new_task unless the user used a slash command.",
            "Use new_task when the turn is a fresh request or when continuation is vague but no active or continuable task exists.",
            "The host will validate route feasibility against thread state before acting.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _route_plan_summary(plan_record: LedgerRecord | None) -> JsonObject | None:
    if plan_record is None:
        return None
    plan = dict(plan_record.data)
    steps = plan.get("steps")
    step_summaries: list[JsonObject] = []
    if isinstance(steps, list):
        for raw_step in steps[:4]:
            if not isinstance(raw_step, dict):
                continue
            step_summaries.append(
                {
                    "step_id": raw_step.get("step_id"),
                    "kind": raw_step.get("kind"),
                    "goal": raw_step.get("goal"),
                    "mode": raw_step.get("mode"),
                    "action_kind": raw_step.get("action_kind"),
                    "tool_name": raw_step.get("tool_name"),
                    "status": raw_step.get("status"),
                    "required_capabilities": _string_values(raw_step.get("required_capabilities")),
                }
            )
    return {
        "task_id": plan_record.task_id,
        "run_id": plan_record.run_id,
        "plan_id": plan.get("plan_id"),
        "status": plan.get("status"),
        "selected_mode": plan.get("selected_mode"),
        "approval_required": plan.get("approval_required"),
        "blocked_capabilities": _string_values(plan.get("blocked_capabilities")),
        "confirmation_prompt": _string_or_none(plan.get("confirmation_prompt")),
        "steps": step_summaries,
    }


def _decision_from_route_proposal(
    proposal: JsonObject,
    *,
    state: ThreadState,
    turn_id: str,
    user_turn: str,
    continuable_plan: LedgerRecord | None,
    pending_plan: LedgerRecord | None,
) -> TurnRoutingDecision:
    route = str(proposal.get("route") or "new_task")
    command = _string_or_none(proposal.get("command"))
    reasons = _ordered_unique(["model_turn_route", *_string_values(proposal.get("reasons"))])
    if state.pending_question is not None:
        if _is_pending_plan_confirmation(pending_plan) and command in {"approve_plan", "reject_plan"}:
            reasons = _ordered_unique([*reasons, "pending_plan_confirmation"])
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="answer_pending_question",
                task_id=str(state.pending_question["task_id"]),
                command=command,
                reasons=reasons,
            )
        if route == "answer_pending_question":
            if _route_relation_starts_new_task(proposal, pending_plan=pending_plan):
                return TurnRoutingDecision(
                    decision_id=f"route-{turn_id}",
                    thread_id=state.thread_id,
                    turn_id=turn_id,
                    route="new_task",
                    task_id=None,
                    command=None,
                    reasons=_ordered_unique([*reasons, "model_relation_overrode_pending_question"]),
                )
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="answer_pending_question",
                task_id=str(state.pending_question["task_id"]),
                command=None,
                reasons=_ordered_unique([*reasons, "pending_user_input"]),
            )
    if route == "summary":
        return TurnRoutingDecision(
            decision_id=f"route-{turn_id}",
            thread_id=state.thread_id,
            turn_id=turn_id,
            route="summary",
            task_id=state.active_task_id,
            command=None,
            reasons=_ordered_unique([*reasons, "journal_summary_request"]),
        )
    if route == "continue_task":
        if state.active_task_id is not None:
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="continue_task",
                task_id=state.active_task_id,
                command=None,
                reasons=_ordered_unique([*reasons, "active_task_present"]),
            )
        return TurnRoutingDecision(
            decision_id=f"route-{turn_id}",
            thread_id=state.thread_id,
            turn_id=turn_id,
            route="new_task",
            task_id=None,
            command=None,
            reasons=_ordered_unique([*reasons, "model_continue_without_active_task", "continue_without_active_task"]),
        )
    if route == "continue_plan":
        if continuable_plan is not None:
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="continue_plan",
                task_id=continuable_plan.task_id,
                command=None,
                reasons=_ordered_unique([*reasons, "continuable_task_plan_present"]),
            )
        return TurnRoutingDecision(
            decision_id=f"route-{turn_id}",
            thread_id=state.thread_id,
            turn_id=turn_id,
            route="new_task",
            task_id=None,
            command=None,
            reasons=_ordered_unique([*reasons, "model_continue_plan_without_continuable_plan", "continue_without_active_task"]),
        )
    return TurnRoutingDecision(
        decision_id=f"route-{turn_id}",
        thread_id=state.thread_id,
        turn_id=turn_id,
        route="new_task",
        task_id=None,
        command=None,
        reasons=_ordered_unique([*reasons, "fresh_or_invalid_model_route"]),
    )


def _route_relation_starts_new_task(proposal: JsonObject, *, pending_plan: LedgerRecord | None) -> bool:
    if not _pending_plan_is_broad_clarification(pending_plan):
        return False
    relation = proposal.get("route_relation")
    if not isinstance(relation, dict):
        return False
    return relation.get("same_task") is False and relation.get("is_standalone_goal") is True


def _pending_plan_is_broad_clarification(plan_record: LedgerRecord | None) -> bool:
    if plan_record is None:
        return True
    plan = dict(plan_record.data)
    if str(plan.get("selected_mode") or "") == "clarify_first":
        return True
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False
    return any(isinstance(step, dict) and str(step.get("mode") or "") == "clarify_first" for step in steps)


def _plan_confirmation_from_decision(decision: TurnRoutingDecision) -> str | None:
    if decision.command == "approve_plan":
        return "approve"
    if decision.command == "reject_plan":
        return "reject"
    return None


def _latest_task_plan_record(journal: JournalStore, thread_id: str, *, task_id: str | None) -> LedgerRecord | None:
    task_ids = {task_id} if task_id else _thread_task_ids(journal, thread_id)
    records = [
        record
        for record in journal.records(kind="semantic_task_plan")
        if record.task_id in task_ids
    ]
    if task_id is None:
        approval_records = [record for record in records if record.data.get("approval_required") is True]
        if approval_records:
            return approval_records[-1]
    return records[-1] if records else None


def _latest_continuable_task_plan_record(journal: JournalStore, thread_id: str) -> LedgerRecord | None:
    task_ids = _thread_task_ids(journal, thread_id)
    records = [
        record
        for record in journal.records(kind="semantic_task_plan")
        if record.task_id in task_ids and record.data.get("approval_required") is True
    ]
    for record in reversed(records):
        plan = dict(record.data)
        if _latest_plan_final_answer_record(journal, plan_record=record) is not None:
            continue
        if _next_executable_plan_step(journal, plan, plan_ref=record.record_id) is not None:
            return record
        if _ready_plan_finalizer_step(plan) is not None:
            return record
    return None


def _is_pending_plan_confirmation(plan_record: LedgerRecord | None) -> bool:
    if plan_record is None:
        return False
    if plan_record.data.get("approval_required") is not True:
        return False
    prompt = plan_record.data.get("confirmation_prompt")
    return isinstance(prompt, str) and bool(prompt.strip())


def _task_plan_text(plan: JsonObject, *, progress: JsonObject | None = None) -> str:
    lines = [
        f"plan={plan.get('plan_id') or 'unknown'} status={plan.get('status') or 'unknown'} "
        f"approval_required={bool(plan.get('approval_required'))}"
    ]
    if progress is not None:
        lines.append(
            f"progress finalized={bool(progress.get('finalized'))} "
            f"completed_steps={progress.get('completed_step_count') or 0}/{progress.get('step_count') or 0}"
        )
        final_ref = progress.get("final_answer_ref")
        if isinstance(final_ref, str) and final_ref:
            lines.append(f"final_answer_ref={final_ref}")
    prompt = plan.get("confirmation_prompt")
    if isinstance(prompt, str) and prompt.strip():
        lines.append(f"prompt={prompt}")
    progress_by_step = _progress_by_step_id(progress)
    steps = plan.get("steps")
    if isinstance(steps, list):
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("step_id") or "")
            step_progress = progress_by_step.get(step_id, {})
            lines.append(
                " ".join(
                    [
                        f"{raw_step.get('step_id') or '?'}:",
                        f"progress={step_progress.get('progress_status') or 'pending'}",
                        str(raw_step.get("status") or "unknown"),
                        str(raw_step.get("kind") or "step"),
                        f"mode={raw_step.get('mode') or 'unknown'}",
                        f"tool={raw_step.get('tool_name') or 'none'}",
                        f"approval_required={bool(raw_step.get('approval_required'))}",
                    ]
                )
            )
            goal = raw_step.get("goal")
            if isinstance(goal, str) and goal.strip():
                lines.append(f"  goal={_preview(goal, limit=180)}")
            capabilities = raw_step.get("required_capabilities")
            if isinstance(capabilities, list) and capabilities:
                lines.append("  capabilities=" + ", ".join(str(item) for item in capabilities))
            spawned_task_id = step_progress.get("spawned_task_id")
            if isinstance(spawned_task_id, str) and spawned_task_id:
                lines.append(
                    "  spawned="
                    + spawned_task_id
                    + " status="
                    + str(step_progress.get("spawned_status") or "unknown")
                )
    return "\n".join(lines)


def _progress_by_step_id(progress: JsonObject | None) -> dict[str, JsonObject]:
    if progress is None:
        return {}
    steps = progress.get("steps")
    if not isinstance(steps, list):
        return {}
    return {
        str(step.get("step_id")): dict(step)
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("step_id"), str)
    }


def _plan_progress(journal: JournalStore, *, plan_record: LedgerRecord, plan: JsonObject) -> JsonObject:
    plan_ref = plan_record.record_id
    decisions = _latest_plan_decisions_by_node(journal, plan_ref)
    final_answer = _latest_plan_final_answer_record(journal, plan_record=plan_record)
    steps_value = plan.get("steps")
    steps = [dict(step) for step in steps_value if isinstance(step, dict)] if isinstance(steps_value, list) else []
    progress_steps = [_step_progress(journal, step=step, decision=decisions.get(str(step.get("node_id") or ""))) for step in steps]
    return {
        "plan_ref": plan_ref,
        "plan_id": str(plan.get("plan_id") or ""),
        "task_id": plan_record.task_id,
        "run_id": plan_record.run_id,
        "finalized": final_answer is not None,
        "final_answer_ref": final_answer.record_id if final_answer is not None else None,
        "step_count": len(progress_steps),
        "completed_step_count": sum(1 for step in progress_steps if step.get("progress_status") == "completed"),
        "approved_step_count": sum(1 for step in progress_steps if step.get("decision") == "approved"),
        "steps": progress_steps,
    }


def _latest_plan_decisions_by_node(journal: JournalStore, plan_ref: str) -> dict[str, LedgerRecord]:
    decisions: dict[str, LedgerRecord] = {}
    for record in journal.records(kind="semantic_task_plan_decision"):
        if record.data.get("plan_ref") != plan_ref:
            continue
        step = record.data.get("executed_step")
        if isinstance(step, dict) and isinstance(step.get("node_id"), str):
            decisions[str(step["node_id"])] = record
    return decisions


def _step_progress(journal: JournalStore, *, step: JsonObject, decision: LedgerRecord | None) -> JsonObject:
    spawned_task_id = decision.data.get("spawned_task_id") if decision is not None else None
    child_final_answer = _latest_final_answer_for_task(journal, spawned_task_id) if isinstance(spawned_task_id, str) else None
    progress_status = _step_progress_status(step=step, decision=decision, child_final_answer=child_final_answer)
    return {
        "step_id": step.get("step_id"),
        "node_id": step.get("node_id"),
        "kind": step.get("kind"),
        "plan_status": step.get("status"),
        "progress_status": progress_status,
        "decision": decision.data.get("decision") if decision is not None else None,
        "decision_ref": decision.record_id if decision is not None else None,
        "spawned_task_id": spawned_task_id,
        "spawned_run_id": decision.data.get("spawned_run_id") if decision is not None else None,
        "spawned_status": decision.data.get("spawned_status") if decision is not None else None,
        "final_answer_ref": child_final_answer.record_id if child_final_answer is not None else None,
    }


def _step_progress_status(*, step: JsonObject, decision: LedgerRecord | None, child_final_answer: LedgerRecord | None) -> str:
    if decision is None:
        status = str(step.get("status") or "pending")
        return "pending" if status in {"ready", "needs_confirmation"} else status
    decision_value = str(decision.data.get("decision") or "")
    if decision_value == "approved" and child_final_answer is not None:
        return "completed"
    if decision_value == "approved":
        return str(decision.data.get("spawned_status") or "approved")
    return decision_value or "unknown"


def _single_executed_step_fields(executed_steps: list[JsonObject]) -> JsonObject:
    if len(executed_steps) != 1:
        return {}
    step = executed_steps[0]
    return {
        "executed_step_id": step.get("executed_step_id"),
        "executed_node_id": step.get("executed_node_id"),
        "spawned_task_id": step.get("spawned_task_id"),
        "spawned_run_id": step.get("spawned_run_id"),
    }


def _next_executable_plan_step(journal: JournalStore, plan: JsonObject, *, plan_ref: str) -> JsonObject | None:
    steps_value = plan.get("steps")
    if not isinstance(steps_value, list):
        return None
    steps = [dict(step) for step in steps_value if isinstance(step, dict)]
    executed_node_ids = _executed_plan_node_ids(journal, plan_ref)
    completed_node_ids = _completed_plan_node_ids(journal, plan_ref)
    blocked_nodes = {
        str(step.get("node_id"))
        for step in steps
        if str(step.get("status") or "") in {"blocked", "invalid"} and step.get("node_id") is not None
    }
    for step in sorted(steps, key=_step_sequence_index):
        node_id = str(step.get("node_id") or "")
        if node_id and node_id in executed_node_ids:
            continue
        if not _is_safe_plan_step(step):
            continue
        dependencies = _string_values(step.get("depends_on"))
        if any(dependency in blocked_nodes for dependency in dependencies):
            continue
        if dependencies and not all(dependency in completed_node_ids for dependency in dependencies):
            continue
        return step
    return None


def _plan_run_limit(plan: JsonObject) -> int:
    steps_value = plan.get("steps")
    if not isinstance(steps_value, list):
        return 1
    return max(1, len([step for step in steps_value if isinstance(step, dict)]))


def _has_blocked_remaining_plan_steps(journal: JournalStore, plan: JsonObject, *, plan_ref: str) -> bool:
    steps_value = plan.get("steps")
    if not isinstance(steps_value, list):
        return False
    executed_node_ids = _executed_plan_node_ids(journal, plan_ref)
    completed_node_ids = _completed_plan_node_ids(journal, plan_ref)
    if executed_node_ids - completed_node_ids:
        return True
    finalizer = _ready_plan_finalizer_step(plan)
    finalizer_node_id = str(finalizer.get("node_id") or "") if finalizer is not None else ""
    for raw_step in steps_value:
        if not isinstance(raw_step, dict):
            continue
        step = dict(raw_step)
        node_id = str(step.get("node_id") or "")
        if node_id and node_id in executed_node_ids:
            continue
        if node_id and node_id == finalizer_node_id:
            continue
        status = str(step.get("status") or "")
        if status in {"blocked", "invalid"}:
            return True
        if not _safe_plan_capabilities(step):
            return True
        dependencies = _string_values(step.get("depends_on"))
        if dependencies and not all(dependency in completed_node_ids for dependency in dependencies):
            return True
    return False


def _executed_plan_node_ids(journal: JournalStore, plan_ref: str) -> set[str]:
    executed: set[str] = set()
    for record in journal.records(kind="semantic_task_plan_decision"):
        if record.data.get("plan_ref") != plan_ref or record.data.get("decision") != "approved":
            continue
        step = record.data.get("executed_step")
        if isinstance(step, dict) and isinstance(step.get("node_id"), str):
            executed.add(str(step["node_id"]))
    return executed


def _completed_plan_node_ids(journal: JournalStore, plan_ref: str) -> set[str]:
    completed: set[str] = set()
    for record in journal.records(kind="semantic_task_plan_decision"):
        if record.data.get("plan_ref") != plan_ref or record.data.get("decision") != "approved":
            continue
        step = record.data.get("executed_step")
        spawned_task_id = record.data.get("spawned_task_id")
        if not isinstance(step, dict) or not isinstance(step.get("node_id"), str):
            continue
        if not isinstance(spawned_task_id, str) or not spawned_task_id:
            continue
        if _latest_final_answer_for_task(journal, spawned_task_id) is None:
            continue
        completed.add(str(step["node_id"]))
    return completed


def _approved_plan_decisions(journal: JournalStore, plan_ref: str) -> dict[str, LedgerRecord]:
    decisions: dict[str, LedgerRecord] = {}
    for record in journal.records(kind="semantic_task_plan_decision"):
        if record.data.get("plan_ref") != plan_ref or record.data.get("decision") != "approved":
            continue
        step = record.data.get("executed_step")
        if isinstance(step, dict) and isinstance(step.get("node_id"), str):
            decisions[str(step["node_id"])] = record
    return decisions


def _build_plan_final_answer(
    journal: JournalStore,
    *,
    plan_record: LedgerRecord,
    plan: JsonObject,
) -> tuple[FinalAnswer | None, JsonObject | None]:
    finalizer = _ready_plan_finalizer_step(plan)
    if finalizer is None:
        return None, {"reason": "no_plan_finalizer_step"}
    plan_ref = plan_record.record_id
    approved = _approved_plan_decisions(journal, plan_ref)
    dependencies = _string_values(finalizer.get("depends_on"))
    missing_nodes = [node_id for node_id in dependencies if node_id not in approved]
    if missing_nodes:
        return None, {"reason": "missing_dependency_output", "missing_nodes": missing_nodes}
    outputs: list[JsonObject] = []
    for node_id in dependencies:
        decision = approved[node_id]
        spawned_task_id = decision.data.get("spawned_task_id")
        if not isinstance(spawned_task_id, str) or not spawned_task_id:
            return None, {"reason": "missing_spawned_task", "missing_nodes": [node_id]}
        child_answer = _latest_final_answer_for_task(journal, spawned_task_id)
        if child_answer is None:
            return None, {"reason": "missing_dependency_final_answer", "missing_nodes": [node_id]}
        outputs.append(
            {
                "node_id": node_id,
                "decision_ref": decision.record_id,
                "spawned_task_id": spawned_task_id,
                "step": decision.data.get("executed_step") if isinstance(decision.data.get("executed_step"), dict) else {},
                "final_answer": child_answer.data,
                "final_answer_ref": child_answer.record_id,
            }
        )
    if not outputs:
        return None, {"reason": "missing_dependency_output", "missing_nodes": dependencies}
    citation_refs = _ordered_unique(
        [
            citation
            for output in outputs
            for citation in _string_values(output["final_answer"].get("citation_refs") if isinstance(output["final_answer"], dict) else [])
        ]
    )
    if finalizer.get("citations_required") is True and not citation_refs:
        return None, {"reason": "citations_required_but_missing"}
    used_evidence = _ordered_unique(
        [
            evidence
            for output in outputs
            for evidence in _string_values(output["final_answer"].get("used_evidence") if isinstance(output["final_answer"], dict) else [])
        ]
    )
    limitations = _ordered_unique(
        [
            limitation
            for output in outputs
            for limitation in _string_values(output["final_answer"].get("limitations") if isinstance(output["final_answer"], dict) else [])
        ]
    )
    limitations.append("plan_final_answer_uses_only_completed_approved_step_outputs")
    answer = guard_user_visible_text(_plan_final_answer_text(plan=plan, finalizer=finalizer, outputs=outputs))
    confidence = min(_answer_confidence(output["final_answer"]) for output in outputs)
    trace_refs = _ordered_unique(
        [
            plan_record.record_id,
            *[str(output["decision_ref"]) for output in outputs],
            *[str(output["final_answer_ref"]) for output in outputs],
        ]
    )
    return FinalAnswer(
        answer=answer,
        citation_refs=citation_refs,
        used_evidence=used_evidence,
        limitations=limitations,
        confidence=confidence,
        task_id=str(plan_record.task_id or ""),
        run_id=plan_record.run_id,
        trace_refs=trace_refs,
    ), None


def _ready_plan_finalizer_step(plan: JsonObject) -> JsonObject | None:
    steps_value = plan.get("steps")
    if not isinstance(steps_value, list):
        return None
    for step in sorted([dict(item) for item in steps_value if isinstance(item, dict)], key=_step_sequence_index):
        if str(step.get("action_kind") or "") != "respond":
            continue
        dependencies = _string_values(step.get("depends_on"))
        if not dependencies:
            continue
        if str(step.get("status") or "") not in {"ready", "needs_confirmation"}:
            continue
        return step
    return None


def _latest_final_answer_for_task(journal: JournalStore, task_id: str) -> LedgerRecord | None:
    records = [record for record in journal.records(task_id=task_id, kind="agent_final_answer")]
    return records[-1] if records else None


def _latest_plan_final_answer_record(journal: JournalStore, *, plan_record: LedgerRecord) -> LedgerRecord | None:
    records = [
        record
        for record in journal.records(task_id=plan_record.task_id, kind="semantic_task_plan_final_answer")
        if record.run_id == plan_record.run_id
    ]
    return records[-1] if records else None


def _plan_final_answer_text(*, plan: JsonObject, finalizer: JsonObject, outputs: list[JsonObject]) -> str:
    lines = [str(finalizer.get("goal") or plan.get("goal") or "Completed approved plan outputs.")]
    for output in outputs:
        step = output.get("step") if isinstance(output.get("step"), dict) else {}
        final_answer = output.get("final_answer") if isinstance(output.get("final_answer"), dict) else {}
        label = str(step.get("goal") or output.get("node_id") or "completed step")
        answer = str(final_answer.get("answer") or "").strip()
        if answer:
            lines.append(f"- {label}: {answer}")
    return "\n".join(lines)


def _answer_confidence(answer: object) -> float:
    if isinstance(answer, dict):
        value = answer.get("confidence")
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
    return 0.0


def _is_safe_plan_step(step: JsonObject) -> bool:
    status = str(step.get("status") or "")
    if status not in {"ready", "needs_confirmation"}:
        return False
    action_kind = str(step.get("action_kind") or "")
    if action_kind not in {"tool", "respond", "ask_user"}:
        return False
    if action_kind == "respond":
        dependencies = _string_values(step.get("depends_on"))
        if dependencies or step.get("evidence_required") is True or step.get("citations_required") is True:
            return False
    mode = _plan_step_mode(step)
    if mode not in _PLAN_ALLOWED_MODES:
        return False
    return _safe_plan_capabilities(step)


def _safe_plan_capabilities(step: JsonObject) -> bool:
    capabilities = _string_values(step.get("required_capabilities"))
    return all(
        capability in _PLAN_SAFE_CAPABILITIES or capability in SAFE_SEMANTIC_CAPABILITIES
        for capability in capabilities
    )


def _plan_step_mode(step: JsonObject) -> str:
    mode = str(step.get("mode") or "")
    return mode if mode in _PLAN_ALLOWED_MODES else "direct_answer"


def _plan_step_citations_required(step: JsonObject) -> bool | None:
    value = step.get("citations_required")
    return value if isinstance(value, bool) else None


def _step_sequence_index(step: JsonObject) -> int:
    value = step.get("sequence_index")
    return value if isinstance(value, int) else 1_000_000


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _pending_for_task(journal: JournalStore, *, thread_id: str, task_id: str, run_id: str) -> PendingUserInput:
    question = "请补充完成这个任务所需的信息。"
    source_ref = None
    metadata: JsonObject = {"pending_type": "clarification"}
    for record in reversed(journal.records(task_id=task_id, kind="observation")):
        if record.data.get("status") != "needs_user_input":
            continue
        content = record.data.get("content")
        if isinstance(content, dict) and isinstance(content.get("question"), str):
            question = str(content["question"])
            source_ref = record.record_id
            break
    pending_memory = _pending_memory_proposals(journal, task_id=task_id)
    if pending_memory:
        proposal_ids = [str(record.data.get("proposal_id")) for record in pending_memory if record.data.get("proposal_id")]
        source_ref = pending_memory[-1].record_id
        metadata = {
            "pending_type": "memory_review",
            "memory_proposal_ids": proposal_ids,
            "blocked_capabilities": ["durable_memory:write"],
            "review_commands": [
                "/memory proposals",
                "/memory approve <proposal_id>",
                "/memory reject <proposal_id> [reason]",
            ],
        }
        question = (
            "已创建待审核长期记忆提案："
            + ", ".join(proposal_ids)
            + "。长期记忆不会自动提交；请使用 /memory proposals 查看，"
            + "用 /memory approve <proposal_id> 批准，或用 /memory reject <proposal_id> [reason] 拒绝。"
        )
    return PendingUserInput(
        pending_id=f"pending-{task_id}-{run_id}",
        thread_id=thread_id,
        task_id=task_id,
        run_id=run_id,
        question=question,
        source_ref=source_ref,
        created_at_ms=len(journal.records()) + 1,
        metadata=metadata,
    )


def _thread_working_context(
    journal: JournalStore,
    *,
    state: ThreadState,
    turn: ChatTurn,
    decision: TurnRoutingDecision,
) -> JsonObject:
    pending = state.pending_question if isinstance(state.pending_question, dict) else None
    task_id = decision.task_id or state.active_task_id or (str(pending.get("task_id")) if pending and pending.get("task_id") else None)
    return {
        "kind": "thread_working_context",
        "thread_id": state.thread_id,
        "route": decision.route,
        "route_reasons": list(decision.reasons),
        "current_turn": {
            "turn_id": turn.turn_id,
            "role": turn.role,
            "text_preview": _preview(turn.text, limit=480),
            "task_id_before_turn": turn.task_id,
        },
        "pending_question": _compact_pending_question(pending),
        "resume_semantics": _resume_semantics(decision, pending=pending),
        "original_task": _task_origin_context(journal, task_id) if task_id else None,
        "recent_turns": _recent_turn_context(journal, state.thread_id, limit=8),
        "recent_conversation": _recent_conversation_context(journal, state.thread_id, limit=12),
        "last_agent_result": _latest_agent_result_context(journal, state.thread_id),
        "last_answer_preview": _latest_answer_preview(journal, state.thread_id),
        "last_failure_reason": _latest_failure_reason(journal, state.thread_id),
        "recent_task_trace": _recent_task_trace_context(journal, task_id, limit=16) if task_id else [],
    }


def _compact_pending_question(pending: JsonObject | None) -> JsonObject | None:
    if not isinstance(pending, dict):
        return None
    return {
        "pending_id": pending.get("pending_id"),
        "thread_id": pending.get("thread_id"),
        "task_id": pending.get("task_id"),
        "run_id": pending.get("run_id"),
        "question": _preview(str(pending.get("question") or ""), limit=480),
        "source_ref": pending.get("source_ref"),
        "metadata": _compact_json(pending.get("metadata"), limit=160),
    }


def _resume_semantics(decision: TurnRoutingDecision, *, pending: JsonObject | None) -> JsonObject:
    if decision.route == "answer_pending_question":
        return {
            "same_task": True,
            "interpretation": "current_user_turn_answers_pending_question",
            "instruction": (
                "Interpret the current user turn through the pending question and original task. "
                "Do not ask a new generic clarification unless a critical slot is still missing."
            ),
            "pending_question_text": _preview(str((pending or {}).get("question") or ""), limit=480),
        }
    if decision.route == "continue_task":
        return {
            "same_task": True,
            "interpretation": "current_user_turn_continues_active_task",
        }
    return {
        "same_task": False,
        "interpretation": "current_user_turn_starts_or_routes_task",
    }


def _task_origin_context(journal: JournalStore, task_id: str | None) -> JsonObject | None:
    if not task_id:
        return None
    for record in journal.records(task_id=task_id, kind="task"):
        return {
            "task_id": task_id,
            "run_id": record.run_id,
            "thread_id": record.data.get("thread_id"),
            "input_text_preview": _preview(str(record.data.get("input_text") or ""), limit=640),
            "record_ref": record.record_id,
        }
    return None


def _recent_turn_context(journal: JournalStore, thread_id: str, *, limit: int) -> list[JsonObject]:
    turns: list[JsonObject] = []
    for record in _thread_turn_records(journal, thread_id)[-limit:]:
        turns.append(
            {
                "record_ref": record.record_id,
                "turn_id": record.data.get("turn_id"),
                "role": record.data.get("role"),
                "task_id": record.data.get("task_id"),
                "text_preview": _preview(str(record.data.get("text") or ""), limit=360),
            }
        )
    return turns


def _recent_conversation_context(journal: JournalStore, thread_id: str, *, limit: int) -> list[JsonObject]:
    records = [
        record
        for record in journal.records()
        if (
            record.kind == "chat_turn"
            and record.data.get("thread_id") == thread_id
        )
        or (
            record.kind == "chat_agent_result"
            and record.data.get("thread_id") == thread_id
        )
    ]
    return [_compact_conversation_record(record) for record in records[-limit:]]


def _compact_conversation_record(record: LedgerRecord) -> JsonObject:
    data = record.data
    if record.kind == "chat_turn":
        return {
            "record_ref": record.record_id,
            "kind": "chat_turn",
            "role": data.get("role"),
            "turn_id": data.get("turn_id"),
            "task_id": data.get("task_id"),
            "text_preview": _preview(str(data.get("text") or ""), limit=480),
        }
    failure = data.get("failure_report") if isinstance(data.get("failure_report"), dict) else None
    pending = data.get("pending_question") if isinstance(data.get("pending_question"), dict) else None
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else None
    host_situation = data.get("host_situation") if isinstance(data.get("host_situation"), dict) else {}
    return {
        "record_ref": record.record_id,
        "kind": "chat_agent_result",
        "role": "assistant",
        "turn_id": data.get("turn_id"),
        "task_id": data.get("task_id"),
        "run_id": data.get("run_id"),
        "route": data.get("route"),
        "status": data.get("status"),
        "answer_preview": _preview(str(data.get("answer") or ""), limit=640),
        "failure_reason": failure.get("reason") if failure else None,
        "pending_question": _compact_pending_question(pending),
        "summary_preview": _preview(str(summary.get("text") or summary.get("summary") or ""), limit=360) if summary else None,
        "host_situation": _compact_host_situation_for_context(host_situation),
    }


def _latest_agent_result_context(journal: JournalStore, thread_id: str) -> JsonObject | None:
    for record in reversed(journal.records(kind="chat_agent_result")):
        if record.data.get("thread_id") != thread_id or not _is_task_result(record.data):
            continue
        host_situation = record.data.get("host_situation") if isinstance(record.data.get("host_situation"), dict) else {}
        return {
            "record_ref": record.record_id,
            "task_id": record.data.get("task_id"),
            "run_id": record.data.get("run_id"),
            "route": record.data.get("route"),
            "status": record.data.get("status"),
            "answer_preview": _preview(str(record.data.get("answer") or ""), limit=360),
            "pending_question": _compact_pending_question(record.data.get("pending_question") if isinstance(record.data.get("pending_question"), dict) else None),
            "host_situation": _compact_host_situation_for_context(host_situation),
        }
    return None


def _recent_task_trace_context(journal: JournalStore, task_id: str | None, *, limit: int) -> list[JsonObject]:
    if not task_id:
        return []
    trace_kinds = {
        "task",
        "resume",
        "semantic_intake",
        "semantic_task_plan",
        "action",
        "policy_decision",
        "observation",
        "feedback",
        "guard",
        "host_situation",
        "agent_failure_report",
        "agent_final_answer",
        "semantic_task_plan_final_answer",
    }
    records = [record for record in journal.records(task_id=task_id) if record.kind in trace_kinds]
    return [_compact_trace_record(record) for record in records[-limit:]]


def _compact_trace_record(record: LedgerRecord) -> JsonObject:
    data = record.data
    base: JsonObject = {
        "record_ref": record.record_id,
        "kind": record.kind,
        "run_id": record.run_id,
        "step_id": record.step_id,
    }
    if record.kind == "task":
        base["input_text_preview"] = _preview(str(data.get("input_text") or ""), limit=360)
    elif record.kind == "resume":
        base["user_input_preview"] = _preview(str(data.get("user_input") or ""), limit=360)
    elif record.kind == "semantic_intake":
        base.update(
            {
                "primary_intent": data.get("primary_intent"),
                "suggested_mode": data.get("suggested_mode"),
                "requires_clarification": data.get("requires_clarification"),
                "clarification_question": _preview(str(data.get("clarification_question") or ""), limit=240),
                "blocked_capabilities": _string_values(data.get("blocked_capabilities")),
            }
        )
    elif record.kind == "semantic_task_plan":
        base.update(
            {
                "status": data.get("status"),
                "selected_mode": data.get("selected_mode"),
                "blocked_capabilities": _string_values(data.get("blocked_capabilities")),
                "confirmation_prompt": _preview(str(data.get("confirmation_prompt") or ""), limit=240),
            }
        )
    elif record.kind == "action":
        payload = data.get("payload")
        base.update(
            {
                "action_kind": data.get("kind"),
                "name": data.get("name"),
                "side_effect_class": data.get("side_effect_class"),
                "payload": _compact_json(payload, limit=240),
                "reasons": _string_values(data.get("reasons"))[:4],
            }
        )
    elif record.kind == "policy_decision":
        base.update({"allowed": data.get("allowed"), "reason": data.get("reason")})
    elif record.kind == "observation":
        base.update(
            {
                "status": data.get("status"),
                "source": data.get("source"),
                "observation_kind": data.get("kind"),
                "content": _compact_json(data.get("content"), limit=320),
            }
        )
    elif record.kind == "feedback":
        base.update(
            {
                "status": data.get("status"),
                "stop_reason": data.get("stop_reason"),
                "answer_preview": _preview(str(data.get("answer") or ""), limit=240),
                "missing_evidence": _string_values(data.get("missing_evidence"))[:8],
            }
        )
    elif record.kind == "guard":
        base.update({"stop_reason": data.get("stop_reason"), "data": _compact_json(data, limit=160)})
    elif record.kind == "host_situation":
        base.update(_compact_host_situation_for_context(data))
    elif record.kind == "agent_failure_report":
        base.update(
            {
                "reason": data.get("reason"),
                "missing_evidence": _string_values(data.get("missing_evidence"))[:8],
                "next_possible_action": data.get("next_possible_action"),
            }
        )
    elif record.kind in {"agent_final_answer", "semantic_task_plan_final_answer"}:
        base.update(
            {
                "answer_preview": _preview(str(data.get("answer") or ""), limit=360),
                "citation_refs": _string_values(data.get("citation_refs"))[:8],
            }
        )
    return base


def _compact_host_situation_for_context(data: JsonObject) -> JsonObject:
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
    activity = data.get("recent_activity") if isinstance(data.get("recent_activity"), dict) else {}
    failure = data.get("failure") if isinstance(data.get("failure"), dict) else {}
    return {
        "task_mode": task.get("mode"),
        "citations_required": task.get("citations_required"),
        "retrieval_configured": retrieval.get("configured"),
        "live_search_available": retrieval.get("live_search_available"),
        "live_fetch_available": retrieval.get("live_fetch_available"),
        "network_budget_available": retrieval.get("network_budget_available"),
        "retrieval_runs": activity.get("retrieval_runs"),
        "search_attempts": activity.get("search_attempts"),
        "fetch_attempts": activity.get("fetch_attempts"),
        "successful_fetches": activity.get("successful_fetches"),
        "latest_retrieval_status": activity.get("latest_retrieval_status"),
        "latest_failure_reason": activity.get("latest_failure_reason"),
        "failure_diagnosis": failure.get("diagnosis"),
        "failure_reason": failure.get("reason"),
        "next_possible_action": failure.get("next_possible_action"),
    }


def _compact_json(value, *, limit: int):
    if isinstance(value, str):
        return _preview(value, limit=limit)
    if isinstance(value, list):
        return [_compact_json(item, limit=limit) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key): _compact_json(item, limit=limit) for key, item in list(value.items())[:16]}
    return value


def _pending_memory_proposals(journal: JournalStore, *, task_id: str) -> list[LedgerRecord]:
    proposals: list[LedgerRecord] = []
    for record in journal.records(task_id=task_id, kind="memory_proposal"):
        if record.data.get("approval_status") == "pending":
            proposals.append(record)
    return proposals


def _mode_for_task(journal: JournalStore, task_id: str) -> str:
    for record in reversed(journal.records(task_id=task_id, kind="agent_recipe")):
        mode = record.data.get("mode")
        if isinstance(mode, str) and mode:
            return mode
    return "auto"


def _resume_mode_for_input(journal: JournalStore, task_id: str) -> str:
    mode = _mode_for_task(journal, task_id)
    return "auto" if mode == "clarify_first" else mode


def _latest_chat_agent_result(journal: JournalStore, thread_id: str, *, after_ms: int) -> LedgerRecord | None:
    records = [
        record
        for record in journal.records(kind="chat_agent_result")
        if (
            record.data.get("thread_id") == thread_id
            and record.recorded_at_ms > after_ms
            and _is_task_result(record.data)
        )
    ]
    return records[-1] if records else None


def _is_task_result(data: JsonObject) -> bool:
    route = data.get("route")
    if route in {"new_task", "continue_task", "answer_pending_question", "continue_plan"}:
        return data.get("task_id") is not None
    command_result = data.get("command_result")
    if route != "command" or not isinstance(command_result, dict):
        return False
    if command_result.get("started_new_task") is True:
        return True
    result = command_result.get("result")
    return isinstance(result, dict) and isinstance(result.get("final_answer_ref"), str) and data.get("task_id") is not None


def _keeps_task_active(status: str) -> bool:
    return status in {"running", "continue", "needs_user_input"}


def _thread_turn_records(journal: JournalStore, thread_id: str) -> list[LedgerRecord]:
    return [record for record in journal.records(kind="chat_turn") if record.data.get("thread_id") == thread_id]


def _thread_summary_records(journal: JournalStore, thread_id: str) -> list[LedgerRecord]:
    return [record for record in journal.records(kind="thread_summary") if record.data.get("thread_id") == thread_id]


def _latest_thread_summary_record(journal: JournalStore, thread_id: str) -> LedgerRecord | None:
    records = _thread_summary_records(journal, thread_id)
    return records[-1] if records else None


def _latest_turn_ref(journal: JournalStore, thread_id: str) -> str | None:
    records = _thread_turn_records(journal, thread_id)
    return records[-1].record_id if records else None


def _latest_clear_at(journal: JournalStore, thread_id: str) -> int:
    cleared = 0
    for record in journal.records(kind="chat_command"):
        if record.data.get("thread_id") != thread_id:
            continue
        if record.data.get("name") in {"/cancel", "/interrupt"}:
            cleared = max(cleared, record.recorded_at_ms)
        if record.data.get("name") == "/new" and not record.data.get("result", {}).get("started_new_task"):
            cleared = max(cleared, record.recorded_at_ms)
    return cleared


def _latest_answer_preview(journal: JournalStore, thread_id: str) -> str | None:
    task_ids = _thread_task_ids(journal, thread_id)
    for record in reversed(journal.records()):
        if record.kind not in {"agent_final_answer", "semantic_task_plan_final_answer"}:
            continue
        if record.task_id in task_ids and isinstance(record.data.get("answer"), str):
            return _preview(str(record.data["answer"]), limit=240)
    return None


def _latest_failure_reason(journal: JournalStore, thread_id: str) -> str | None:
    task_ids = _thread_task_ids(journal, thread_id)
    for record in reversed(journal.records(kind="agent_failure_report")):
        if record.task_id in task_ids and isinstance(record.data.get("reason"), str):
            return str(record.data["reason"])
    return None


def _thread_task_ids(journal: JournalStore, thread_id: str) -> set[str]:
    return {
        str(record.task_id)
        for record in journal.records(kind="task")
        if record.task_id is not None and record.data.get("thread_id") == thread_id
    }


def _command_name(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0].lower()


def _parse_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


def _normalize_thread_id(thread_id: str) -> str:
    normalized = thread_id.strip()
    return normalized or "default"


def _normalize_default_mode(mode: str) -> str:
    aliases = {
        "direct": "direct_answer",
        "semantic": "semantic_answer",
        "retrieval": "retrieval_answer",
        "workspace": "workspace_answer",
        "clarify": "clarify_first",
    }
    normalized = aliases.get(str(mode or "auto"), str(mode or "auto"))
    if normalized in {"auto", "direct_answer", "semantic_answer", "retrieval_answer", "workspace_answer", "clarify_first"}:
        return normalized
    return "auto"


def _chat_run_id(thread_id: str) -> str:
    return f"chat-{_safe_id(thread_id)}"


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower())
    return safe.strip("-") or "default"


def _preview(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _status_text(state: ThreadState) -> str:
    return (
        f"thread={state.thread_id} active_task={state.active_task_id or 'none'} "
        f"status={state.last_result_status or 'new'} pending={bool(state.pending_question)}"
    )


def _summary_text(summary: ThreadSummary) -> str:
    parts = [f"线程 {summary.thread_id} 的最近记录："]
    if summary.active_task_id:
        parts.append(f"当前任务: {summary.active_task_id}")
    if summary.last_result_status:
        parts.append(f"最近状态: {summary.last_result_status}")
    if summary.pending_question:
        parts.append(f"待补充: {summary.pending_question.get('question')}")
    if summary.last_answer_preview:
        parts.append(f"上一条回答: {summary.last_answer_preview}")
    if summary.last_failure_reason:
        parts.append(f"最近失败原因: {summary.last_failure_reason}")
    if summary.recent_turns:
        previews = [str(turn.get("text_preview", "")) for turn in summary.recent_turns if turn.get("text_preview")]
        parts.append("最近输入: " + " | ".join(previews))
    return "\n".join(parts)


def _failure_answer_text(failure_report: JsonObject, *, user_goal: str) -> str:
    reason = str(failure_report.get("reason") or "failed")
    attempted = _string_list(failure_report.get("attempted_actions"))
    missing = _string_list(failure_report.get("missing_evidence"))
    next_action = failure_report.get("next_possible_action")
    observations = failure_report.get("last_observations")
    observed_reasons = _failure_observation_reasons(observations if isinstance(observations, list) else [])

    lines = [_failure_intro_sentence(failure_report, user_goal=user_goal)]
    if attempted:
        lines.append(f"我已经尝试过：{', '.join(attempted[:4])}。")
    if observed_reasons:
        lines.append(f"工具返回的问题是：{'; '.join(observed_reasons[:3])}。")
    elif reason:
        lines.append(f"当前停止原因是：{reason}。")
    if missing:
        lines.append(f"缺少的关键材料是：{', '.join(missing[:4])}。")
    if isinstance(next_action, str) and next_action:
        lines.append(f"下一步应当是：{next_action}。")
    lines.append(_failure_host_situation_sentence(failure_report))
    return "\n".join(lines)


def _failure_intro_sentence(failure_report: JsonObject, *, user_goal: str) -> str:
    situation = failure_report.get("host_situation")
    situation = situation if isinstance(situation, dict) else {}
    task = situation.get("task")
    task = task if isinstance(task, dict) else {}
    failure = situation.get("failure")
    failure = failure if isinstance(failure, dict) else {}
    diagnosis = str(failure.get("diagnosis") or "")
    task_mode = str(task.get("mode") or "")
    reason = str(failure_report.get("reason") or "")
    attempted = _string_list(failure_report.get("attempted_actions"))
    missing = _string_list(failure_report.get("missing_evidence"))
    goal_preview = _preview(user_goal, limit=80)
    if diagnosis == "processor_or_planning_failure":
        return f"我这轮没有完成“{goal_preview}”，原因是模型/API处理或规划步骤失败。"
    if (
        task_mode == "retrieval_answer"
        or "retrieval.run" in attempted
        or reason.startswith("retrieval_")
        or "retrieval" in reason
        or "sufficient_retrieval_evidence" in missing
    ):
        return f"我这次没有拿到足够证据来完成“{goal_preview}”。"
    return f"我这轮没有完成“{goal_preview}”。"


def _failure_host_situation_sentence(failure_report: JsonObject) -> str:
    situation = failure_report.get("host_situation")
    situation = situation if isinstance(situation, dict) else {}
    retrieval = situation.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    task = situation.get("task")
    task = task if isinstance(task, dict) else {}
    activity = situation.get("recent_activity")
    activity = activity if isinstance(activity, dict) else {}
    failure = situation.get("failure")
    failure = failure if isinstance(failure, dict) else {}
    diagnosis = str(failure.get("diagnosis") or "")
    configured = retrieval.get("configured")
    live_available = bool(retrieval.get("live_search_available") or retrieval.get("live_fetch_available"))
    network_budget = retrieval.get("network_budget_available")
    task_mode = str(task.get("mode") or "")

    if diagnosis == "processor_or_planning_failure":
        processor_error = activity.get("latest_processor_error")
        if isinstance(processor_error, str) and processor_error:
            return f"所以我不能编造结论；当前问题是模型/API处理或规划步骤失败：{_preview(processor_error, limit=120)}。"
        return "所以我不能编造结论；当前问题是模型处理或规划步骤失败，宿主已经把失败记录进上下文供下一轮重试或降级。"
    if diagnosis == "non_retrieval_task_incomplete":
        return "所以我不能编造结论；当前问题不是联网权限，而是这轮直接回答流程没有形成可用的最终回答。"
    if task_mode == "retrieval_answer" and configured is False:
        return "所以我不能编造结论；当前问题是检索工具或检索源没有配置成可执行状态。"
    if network_budget is False:
        return "所以我不能编造结论；当前问题是网络检索预算或权限不可用，需要先由宿主开放相应能力。"
    if diagnosis == "tool_budget_exhausted_after_attempts":
        return "所以我不能编造结论；当前已经进行过检索尝试，问题是工具预算在证据覆盖完成前被耗尽。"
    if diagnosis == "citation_coverage_insufficient":
        return "所以我不能编造结论；当前检索路径可用，但缺少可引用证据或 citation 覆盖。"
    if live_available:
        return "所以我不能编造结论；当前不是缺少 live retrieval 权限，而是搜索、抓取、解析、来源权威性或证据覆盖还不够。"
    return "所以我不能编造结论；当前应当根据失败归因换策略、补证据，或明确给出受限结论。"


def _failure_observation_reasons(observations: list[object]) -> list[str]:
    reasons: list[str] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, dict):
            continue
        for key in ("reason", "error", "status"):
            value = content.get(key)
            if isinstance(value, str) and value:
                reasons.append(value)
                break
    return _ordered_unique(reasons)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _exception_reason(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc) or type(exc).__name__


def _memory_review_resolution(proposal_id: str, *, decision: str) -> JsonObject:
    return {
        "pending_type": "memory_review",
        "memory_proposal_ids": [proposal_id],
        "decision": decision,
    }


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
