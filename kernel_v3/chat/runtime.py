from __future__ import annotations

from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import AgentRuntimeResult
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
from kernel_v3.contracts import JsonObject, LedgerRecord
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.trace import TraceRenderer


class ChatRuntime:
    def __init__(
        self,
        *,
        journal: JournalStore | None = None,
        agent_runtime: AgentRuntime | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self.journal = journal or JournalStore.in_memory()
        self.agent_runtime = agent_runtime or AgentRuntime(journal=self.journal, workspace_root=Path.cwd())
        self.memory_store = memory_store if memory_store is not None else getattr(self.agent_runtime, "memory_store", None)
        self.memory_pipeline = MemoryPipeline(store=self.memory_store, journal=self.journal) if self.memory_store is not None else None

    def receive(self, message: str, *, thread_id: str = "default") -> ChatRuntimeResult:
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
        self.journal.append(
            task_id=before.active_task_id,
            run_id=_chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_turn",
            data=turn.to_dict(),
            state_delta={"thread_id": normalized_thread, "chat_role": "user"},
        )
        decision = self.route_turn(message, state=before, turn_id=turn.turn_id)
        self.journal.append(
            task_id=decision.task_id,
            run_id=_chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_routing_decision",
            data=decision.to_dict(),
            state_delta={"thread_id": normalized_thread, "chat_route": decision.route},
        )
        if decision.route == "command":
            result = self._execute_command(message, state=before, turn=turn, decision=decision)
        elif decision.route == "summary":
            result = self._summary_result(state=before, turn=turn, decision=decision)
        elif decision.route == "answer_pending_question":
            pending = PendingUserInput.from_dict(before.pending_question or {})
            self.journal.append(
                task_id=pending.task_id,
                run_id=_chat_run_id(normalized_thread),
                step_id=None,
                kind="chat_pending_answer",
                data={
                    "thread_id": normalized_thread,
                    "turn_id": turn.turn_id,
                    "pending_id": pending.pending_id,
                    "task_id": pending.task_id,
                    "answer_preview": _preview(message),
                },
                state_delta={"thread_id": normalized_thread, "pending_answered": pending.pending_id},
            )
            agent_result = self.agent_runtime.resume(
                pending.task_id,
                message,
                thread_id=normalized_thread,
                mode=_resume_mode_for_input(self.journal, pending.task_id),
            )
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        elif decision.route == "continue_task":
            task_id = before.active_task_id or ""
            agent_result = self.agent_runtime.resume(
                task_id,
                message,
                thread_id=normalized_thread,
                mode=_mode_for_task(self.journal, task_id),
            )
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        else:
            mode = "clarify_first" if "continue_without_active_task" in decision.reasons else "auto"
            agent_result = self.agent_runtime.run(message, thread_id=normalized_thread, mode=mode)
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
        self.journal.append(
            task_id=result.task_id,
            run_id=result.run_id or _chat_run_id(normalized_thread),
            step_id=None,
            kind="chat_agent_result",
            data=result.to_dict(),
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
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="answer_pending_question",
                task_id=str(state.pending_question["task_id"]),
                command=None,
                reasons=["pending_user_input"],
            )
        if _looks_like_summary_request(stripped):
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="summary",
                task_id=state.active_task_id,
                command=None,
                reasons=["journal_summary_request"],
            )
        if state.active_task_id is not None and _looks_like_continue(stripped):
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="continue_task",
                task_id=state.active_task_id,
                command=None,
                reasons=["continue_intent", "active_task_present"],
            )
        if _looks_like_continue(stripped):
            return TurnRoutingDecision(
                decision_id=f"route-{turn_id}",
                thread_id=state.thread_id,
                turn_id=turn_id,
                route="new_task",
                task_id=None,
                command=None,
                reasons=["continue_intent", "continue_without_active_task"],
            )
        return TurnRoutingDecision(
            decision_id=f"route-{turn_id}",
            thread_id=state.thread_id,
            turn_id=turn_id,
            route="new_task",
            task_id=None,
            command=None,
            reasons=["no_pending_or_continue_route"],
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
            agent_result = self.agent_runtime.run(goal, thread_id=state.thread_id, mode="auto")
            result = self._agent_result(turn=turn, decision=decision, agent_result=agent_result)
            return _replace_command_result(result, command.result)
        if name == "/cancel":
            command = self._append_command(turn, name=name, args=args, status="ok", result={"active_task_cleared": state.active_task_id})
            return self._command_result(turn=turn, decision=decision, status="canceled", command=command, answer="Active task cleared.")
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
        if name == "/memory":
            return self._execute_memory_command(args=args, state=state, turn=turn, decision=decision)
        if name == "/help":
            result = {"commands": ["/status", "/trace", "/summary", "/tasks", "/memory", "/cancel", "/new", "/help"]}
            command = self._append_command(turn, name=name, args=args, status="ok", result=result)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=", ".join(result["commands"]))
        command = self._append_command(turn, name=name, args=args, status="unknown", result={"error": "unknown_command"})
        return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer="Unknown command.")

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
            payload = self.memory_store.recall(scope={"thread_id": state.thread_id}, limit=20).to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=_memory_list_text(payload))
        if subcommand in {"proposals", "proposal"}:
            payload = {"proposals": [_proposal.to_dict() for _proposal in self.memory_store.proposals() if _proposal.source_thread_id == state.thread_id]}
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=_proposal_list_text(payload))
        if subcommand == "approve" and len(args) >= 2:
            result = self.memory_pipeline.approve_proposal(args[1], approved_by="user")
            payload = result.to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Approved {args[1]}.")
        if subcommand == "reject" and len(args) >= 2:
            reason = " ".join(args[2:]) or "user_rejected"
            result = self.memory_pipeline.reject_proposal(args[1], reason=reason)
            payload = result.to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Rejected {args[1]}.")
        if subcommand == "delete" and len(args) >= 2:
            reason = " ".join(args[2:]) or "user_deleted"
            tombstone = self.memory_store.delete(args[1], reason=reason, deleted_by="user")
            payload = tombstone.to_dict()
            command = self._append_command(turn, name="/memory", args=args, status="ok", result=payload)
            return self._command_result(turn=turn, decision=decision, status="completed", command=command, answer=f"Deleted {args[1]}.")
        result = {"error": "invalid_memory_command", "usage": "/memory list|proposals|approve <id>|reject <id> [reason]|delete <id> [reason]"}
        command = self._append_command(turn, name="/memory", args=args, status="failed", result=result)
        return self._command_result(turn=turn, decision=decision, status="failed", command=command, answer=result["usage"])

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
            task_id=state.active_task_id,
            run_id=None,
            answer=_summary_text(summary),
            final_answer=None,
            failure_report=None,
            pending_question=state.pending_question,
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
        if command.name in {"/cancel", "/new"} and not command.result.get("started_new_task"):
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
        self.journal.append(
            task_id=turn.task_id,
            run_id=_chat_run_id(turn.thread_id),
            step_id=None,
            kind="chat_command",
            data=command.to_dict(),
            state_delta={"thread_id": turn.thread_id, "chat_command": name},
        )
        return command

    def _append_thread_summary(self, thread_id: str) -> ThreadSummary:
        summary = self.summarize_thread(thread_id)
        record = self.journal.append(
            task_id=summary.active_task_id,
            run_id=_chat_run_id(summary.thread_id),
            step_id=None,
            kind="thread_summary",
            data=summary.to_dict(),
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
    )


def _pending_for_task(journal: JournalStore, *, thread_id: str, task_id: str, run_id: str) -> PendingUserInput:
    question = "请补充完成这个任务所需的信息。"
    source_ref = None
    for record in reversed(journal.records(task_id=task_id, kind="observation")):
        if record.data.get("status") != "needs_user_input":
            continue
        content = record.data.get("content")
        if isinstance(content, dict) and isinstance(content.get("question"), str):
            question = str(content["question"])
            source_ref = record.record_id
            break
    return PendingUserInput(
        pending_id=f"pending-{task_id}-{run_id}",
        thread_id=thread_id,
        task_id=task_id,
        run_id=run_id,
        question=question,
        source_ref=source_ref,
        created_at_ms=len(journal.records()) + 1,
    )


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
    if route in {"new_task", "continue_task", "answer_pending_question"}:
        return data.get("task_id") is not None
    command_result = data.get("command_result")
    return route == "command" and isinstance(command_result, dict) and command_result.get("started_new_task") is True


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
        if record.data.get("name") == "/cancel":
            cleared = max(cleared, record.recorded_at_ms)
        if record.data.get("name") == "/new" and not record.data.get("result", {}).get("started_new_task"):
            cleared = max(cleared, record.recorded_at_ms)
    return cleared


def _latest_answer_preview(journal: JournalStore, thread_id: str) -> str | None:
    task_ids = _thread_task_ids(journal, thread_id)
    for record in reversed(journal.records(kind="agent_final_answer")):
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


def _looks_like_continue(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in {"continue", "continue.", "go on", "resume", "接着", "继续", "继续刚才的", "接着刚才"}


def _looks_like_summary_request(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("刚刚我们说了什么", "我们说了什么", "what did we say", "recap", "summary"))


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
    parts = [f"Thread {summary.thread_id}"]
    if summary.active_task_id:
        parts.append(f"active task: {summary.active_task_id}")
    if summary.last_result_status:
        parts.append(f"last status: {summary.last_result_status}")
    if summary.pending_question:
        parts.append(f"pending: {summary.pending_question.get('question')}")
    if summary.last_answer_preview:
        parts.append(f"last answer: {summary.last_answer_preview}")
    if summary.last_failure_reason:
        parts.append(f"last failure: {summary.last_failure_reason}")
    if summary.recent_turns:
        previews = [str(turn.get("text_preview", "")) for turn in summary.recent_turns if turn.get("text_preview")]
        parts.append("recent turns: " + " | ".join(previews))
    return "\n".join(parts)


def _memory_list_text(payload: JsonObject) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return "No active durable memory for this thread."
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"{item.get('memory_id')}: {item.get('summary')}")
    return "\n".join(lines) or "No active durable memory for this thread."


def _proposal_list_text(payload: JsonObject) -> str:
    proposals = payload.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return "No pending durable memory proposals for this thread."
    lines = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        lines.append(f"{proposal.get('proposal_id')}: {proposal.get('approval_status')} {proposal.get('approval_policy')}")
    return "\n".join(lines) or "No pending durable memory proposals for this thread."


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
