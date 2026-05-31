from __future__ import annotations

from kernel_v3.chat import ChatRuntime
from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.resident.contracts import ResidentLoopResult, ResidentRunResult
from kernel_v3.resident.queue import ResidentQueue


class ResidentRuntime:
    def __init__(
        self,
        *,
        queue: ResidentQueue,
        chat_runtime: ChatRuntime,
        worker_id: str = "resident-worker-1",
        lease_ttl_ms: int = 30_000,
        max_attempts: int = 3,
        retry_backoff_ms: int = 1_000,
        journal: JournalStore | None = None,
    ) -> None:
        self.queue = queue
        self.chat_runtime = chat_runtime
        self.worker_id = worker_id
        self.lease_ttl_ms = lease_ttl_ms
        self.max_attempts = max_attempts
        self.retry_backoff_ms = retry_backoff_ms
        self.journal = journal

    def run_loop(self, *, max_iterations: int = 10, stop_on_idle: bool = True) -> ResidentLoopResult:
        results: list[ResidentRunResult] = []
        for _ in range(max(0, max_iterations)):
            result = self.run_once()
            results.append(result)
            if result.status == "blocked":
                break
            if stop_on_idle and result.status == "idle":
                break
        processed = len([item for item in results if item.status == "processed"])
        failed = len([item for item in results if item.status == "failed"])
        blocked = len([item for item in results if item.status == "blocked"])
        idle = len([item for item in results if item.status == "idle"])
        queue_status = self.queue.status()
        unresolved_failed = int(queue_status.inbox_counts.get("failed", 0)) + queue_status.dead_letter_count
        unresolved_retry = int(queue_status.inbox_counts.get("retry_wait", 0))
        if blocked:
            status = "blocked"
            reason = results[-1].reason if results else "blocked"
        elif unresolved_failed:
            status = "failed"
            reason = "unresolved_failed_inbox"
        elif unresolved_retry:
            status = "retry_wait"
            reason = "unresolved_retry_wait"
        elif results and results[-1].status == "idle":
            status = "idle" if processed == 0 and failed == 0 else "completed"
            reason = results[-1].reason
        elif len(results) >= max_iterations:
            status = "max_iterations"
            reason = "max_iterations"
        else:
            status = "completed"
            reason = None
        loop = ResidentLoopResult(
            status=status,
            worker_id=self.worker_id,
            iterations=len(results),
            processed_count=processed,
            failed_count=failed,
            blocked_count=blocked,
            idle_count=idle,
            reason=reason,
            results=[item.to_dict() for item in results],
            queue_status=queue_status.to_dict(),
        )
        self._journal_event(
            "resident_loop_result",
            loop.to_dict(),
            state_delta={"resident_loop_status": loop.status, "resident_loop_iterations": loop.iterations},
        )
        return loop

    def run_once(self) -> ResidentRunResult:
        lease = self.queue.acquire_lease(worker_id=self.worker_id, ttl_ms=self.lease_ttl_ms)
        if lease is None:
            self._journal_event(
                "resident_worker_blocked",
                {"worker_id": self.worker_id, "reason": "lease_unavailable"},
                state_delta={"resident_worker_status": "blocked"},
            )
            return ResidentRunResult(
                status="blocked",
                worker_id=self.worker_id,
                message_id=None,
                outbox_id=None,
                reason="lease_unavailable",
                payload={},
            )
        self._journal_event(
            "resident_lease_acquired",
            lease.to_dict(),
            state_delta={"resident_lease_owner": self.worker_id, "resident_lease_status": lease.status},
        )
        message = self.queue.claim_next(worker_id=self.worker_id, lease_ttl_ms=self.lease_ttl_ms)
        if message is None:
            self.queue.release_lease(worker_id=self.worker_id)
            self._journal_event(
                "resident_worker_idle",
                {"worker_id": self.worker_id, "reason": "no_pending_inbox", "lease": lease.to_dict()},
                state_delta={"resident_worker_status": "idle"},
            )
            self._journal_event(
                "resident_lease_released",
                {"worker_id": self.worker_id, "lease_id": lease.lease_id},
                state_delta={"resident_lease_status": "released"},
            )
            return ResidentRunResult(
                status="idle",
                worker_id=self.worker_id,
                message_id=None,
                outbox_id=None,
                reason="no_pending_inbox",
                payload={"lease": lease.to_dict()},
            )
        self._journal_event(
            "resident_inbox_claimed",
            message.to_dict(),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        try:
            chat_result = self.chat_runtime.receive(message.text, thread_id=message.thread_id)
            renewed = self.queue.renew_lease(worker_id=self.worker_id, ttl_ms=self.lease_ttl_ms)
            if renewed is None:
                self._journal_event(
                    "resident_worker_blocked",
                    {"worker_id": self.worker_id, "message_id": message.message_id, "reason": "lease_lost_before_outbox"},
                    state_delta={"resident_worker_status": "blocked"},
                )
                return ResidentRunResult(
                    status="blocked",
                    worker_id=self.worker_id,
                    message_id=message.message_id,
                    outbox_id=None,
                    reason="lease_lost_before_outbox",
                    payload={},
                )
            outbox = self.queue.append_outbox(
                in_reply_to=message.message_id,
                thread_id=message.thread_id,
                text=_outbox_text(chat_result),
                status=_outbox_status(chat_result.status),
                task_id=chat_result.task_id,
                run_id=chat_result.run_id,
                payload=chat_result.to_dict(),
            )
            self._journal_event(
                "resident_outbox_appended",
                outbox.to_dict(),
                task_id=chat_result.task_id,
                state_delta={"resident_outbox_status": outbox.status, "resident_outbox_id": outbox.outbox_id},
            )
            answered_pending = []
            if chat_result.route == "answer_pending_question":
                answered_pending = self.queue.mark_pending_user_input_answered(
                    thread_id=message.thread_id,
                    answered_by_message_id=message.message_id,
                    task_id=chat_result.task_id,
                    run_id=chat_result.run_id,
                    exclude_in_reply_to=message.message_id,
                )
                for answered in answered_pending:
                    self._journal_event(
                        "resident_pending_outbox_answered",
                        answered.to_dict(),
                        task_id=chat_result.task_id,
                        state_delta={
                            "resident_outbox_status": answered.status,
                            "resident_outbox_id": answered.outbox_id,
                            "resident_answered_by_message_id": message.message_id,
                        },
                    )
            completed = self.queue.complete(message.message_id, worker_id=self.worker_id)
            if not completed:
                self._journal_event(
                    "resident_worker_blocked",
                    {
                        "worker_id": self.worker_id,
                        "message_id": message.message_id,
                        "outbox_id": outbox.outbox_id,
                        "reason": "message_ownership_lost_before_complete",
                    },
                    task_id=chat_result.task_id,
                    state_delta={"resident_worker_status": "blocked"},
                )
                return ResidentRunResult(
                    status="blocked",
                    worker_id=self.worker_id,
                    message_id=message.message_id,
                    outbox_id=outbox.outbox_id,
                    reason="message_ownership_lost_before_complete",
                    payload={"chat_status": chat_result.status, "outbox_status": outbox.status},
                )
            self._journal_event(
                "resident_inbox_completed",
                {"worker_id": self.worker_id, "message_id": message.message_id, "outbox_id": outbox.outbox_id},
                task_id=chat_result.task_id,
                state_delta={"resident_inbox_status": "completed", "resident_message_id": message.message_id},
            )
            return ResidentRunResult(
                status="processed",
                worker_id=self.worker_id,
                message_id=message.message_id,
                outbox_id=outbox.outbox_id,
                reason=None,
                payload={
                    "chat_status": chat_result.status,
                    "chat_route": chat_result.route,
                    "outbox_status": outbox.status,
                    "answered_pending_outbox_ids": [item.outbox_id for item in answered_pending],
                    "command_result": chat_result.command_result,
                    "pending_question": chat_result.pending_question,
                    "final_answer_ref": _final_answer_ref(chat_result),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive worker containment
            recorded = self.queue.fail(
                message.message_id,
                reason=type(exc).__name__,
                worker_id=self.worker_id,
                max_attempts=self.max_attempts,
                retry_backoff_ms=self.retry_backoff_ms,
            )
            self._journal_event(
                "resident_inbox_failed",
                {
                    "worker_id": self.worker_id,
                    "message_id": message.message_id,
                    "reason": type(exc).__name__,
                    "failure_recorded": recorded,
                    "max_attempts": self.max_attempts,
                    "retry_backoff_ms": self.retry_backoff_ms,
                },
                state_delta={"resident_inbox_status": "failed", "resident_message_id": message.message_id},
            )
            return ResidentRunResult(
                status="failed",
                worker_id=self.worker_id,
                message_id=message.message_id,
                outbox_id=None,
                reason=type(exc).__name__,
                payload={"error": type(exc).__name__, "failure_recorded": recorded},
            )
        finally:
            self.queue.release_lease(worker_id=self.worker_id)
            self._journal_event(
                "resident_lease_released",
                {"worker_id": self.worker_id, "lease_id": lease.lease_id, "message_id": message.message_id},
                state_delta={"resident_lease_status": "released"},
            )

    def _journal_event(
        self,
        kind: str,
        data: JsonObject,
        *,
        task_id: str | None = None,
        state_delta: JsonObject | None = None,
    ) -> None:
        if self.journal is None:
            return
        self.journal.append(
            task_id=task_id,
            run_id=f"resident-{self.worker_id}",
            step_id=None,
            kind=kind,
            data=data,
            state_delta=state_delta or {},
        )


def _outbox_text(chat_result) -> str:
    if chat_result.answer:
        return chat_result.answer
    if chat_result.pending_question and isinstance(chat_result.pending_question.get("question"), str):
        return str(chat_result.pending_question["question"])
    if chat_result.failure_report and isinstance(chat_result.failure_report.get("reason"), str):
        return f"Failed: {chat_result.failure_report['reason']}"
    return chat_result.status


def _outbox_status(status: str) -> str:
    if status == "needs_user_input":
        return "pending_user_input"
    if status in {"failed", "blocked"}:
        return "failed"
    return "ready"


def _final_answer_ref(chat_result) -> str | None:
    command = chat_result.command_result
    if isinstance(command, dict):
        result = command.get("result")
        if isinstance(result, dict) and isinstance(result.get("final_answer_ref"), str):
            return str(result["final_answer_ref"])
    return None
