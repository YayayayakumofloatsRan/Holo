from __future__ import annotations

from kernel_v3.chat import ChatRuntime
from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.resident.contracts import ResidentLoopResult, ResidentRunResult
from kernel_v3.resident.queue import ResidentQueue
from kernel_v3.resident.scheduler import ResidentScheduler


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
        scheduler: ResidentScheduler | None = None,
        schedule_tick_limit: int = 20,
    ) -> None:
        self.queue = queue
        self.chat_runtime = chat_runtime
        self.worker_id = worker_id
        self.lease_ttl_ms = lease_ttl_ms
        self.max_attempts = max_attempts
        self.retry_backoff_ms = retry_backoff_ms
        self.journal = journal
        self.scheduler = scheduler
        self.schedule_tick_limit = schedule_tick_limit

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
        unresolved_failed_inbox = int(queue_status.inbox_counts.get("failed", 0)) + queue_status.dead_letter_count
        unresolved_failed_outbox = int(queue_status.outbox_counts.get("failed", 0))
        unresolved_retry = int(queue_status.inbox_counts.get("retry_wait", 0))
        unresolved_delivery_failed = int(queue_status.outbox_counts.get("delivery_failed", 0))
        unresolved_user_input = int(queue_status.outbox_counts.get("pending_user_input", 0)) + int(
            queue_status.outbox_counts.get("pending_user_input_delivered", 0)
        )
        schedule_status = self._schedule_status()
        schedule_failure_reason = _schedule_failure_reason(results, schedule_status)
        if blocked:
            status = "blocked"
            reason = results[-1].reason if results else "blocked"
        elif schedule_failure_reason is not None:
            status = "failed"
            reason = schedule_failure_reason
        elif unresolved_failed_inbox:
            status = "failed"
            reason = "unresolved_failed_inbox"
        elif unresolved_failed_outbox:
            status = "failed"
            reason = "unresolved_failed_outbox"
        elif unresolved_delivery_failed:
            status = "delivery_failed"
            reason = "unresolved_delivery_failed_outbox"
        elif unresolved_retry:
            status = "retry_wait"
            reason = "unresolved_retry_wait"
        elif unresolved_user_input:
            status = "awaiting_user_input"
            reason = "unresolved_pending_user_input"
        else:
            if (
                schedule_status
                and results
                and results[-1].status == "idle"
                and int(schedule_status.get("active_count") or 0) > 0
                and schedule_status.get("next_due_at_ms") is not None
            ):
                status = "waiting_for_schedule"
                reason = "next_schedule_pending"
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
            schedule_status=schedule_status,
        )
        self._journal_event(
            "resident_loop_result",
            loop.to_dict(),
            state_delta={
                "resident_loop_status": loop.status,
                "resident_loop_iterations": loop.iterations,
                "resident_schedule_active_count": schedule_status.get("active_count", 0),
            },
        )
        return loop

    def run_once(self) -> ResidentRunResult:
        schedule_tick = self._tick_schedules()
        lease = self.queue.acquire_lease(worker_id=self.worker_id, ttl_ms=self.lease_ttl_ms)
        if lease is None:
            self._journal_event(
                "resident_worker_blocked",
                _with_schedule_tick({"worker_id": self.worker_id, "reason": "lease_unavailable"}, schedule_tick),
                state_delta={"resident_worker_status": "blocked"},
            )
            return ResidentRunResult(
                status="blocked",
                worker_id=self.worker_id,
                message_id=None,
                outbox_id=None,
                reason="lease_unavailable",
                payload=_with_schedule_tick({}, schedule_tick),
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
                payload=_with_schedule_tick({"lease": lease.to_dict()}, schedule_tick),
            )
        self._journal_event(
            "resident_inbox_claimed",
            message.to_dict(),
            state_delta={"resident_inbox_status": message.status, "resident_message_id": message.message_id},
        )
        try:
            existing_outbox = self.queue.outbox_for_reply(message.message_id)
            if existing_outbox is not None:
                self._journal_event(
                    "resident_outbox_recovered",
                    existing_outbox.to_dict(),
                    task_id=existing_outbox.task_id,
                    state_delta={
                        "resident_outbox_status": existing_outbox.status,
                        "resident_outbox_id": existing_outbox.outbox_id,
                    },
                )
                completed = self.queue.complete(message.message_id, worker_id=self.worker_id)
                if not completed:
                    self._journal_event(
                        "resident_worker_blocked",
                        {
                            "worker_id": self.worker_id,
                            "message_id": message.message_id,
                            "outbox_id": existing_outbox.outbox_id,
                            "reason": "message_ownership_lost_before_recovered_complete",
                        },
                        task_id=existing_outbox.task_id,
                        state_delta={"resident_worker_status": "blocked"},
                    )
                    return ResidentRunResult(
                        status="blocked",
                        worker_id=self.worker_id,
                        message_id=message.message_id,
                        outbox_id=existing_outbox.outbox_id,
                        reason="message_ownership_lost_before_recovered_complete",
                        payload=_with_schedule_tick(
                            {"outbox_status": existing_outbox.status, "recovered_existing_outbox": True},
                            schedule_tick,
                        ),
                    )
                self._journal_event(
                    "resident_inbox_completed",
                    {
                        "worker_id": self.worker_id,
                        "message_id": message.message_id,
                        "outbox_id": existing_outbox.outbox_id,
                        "recovered_existing_outbox": True,
                    },
                    task_id=existing_outbox.task_id,
                    state_delta={"resident_inbox_status": "completed", "resident_message_id": message.message_id},
                )
                return ResidentRunResult(
                    status="processed",
                    worker_id=self.worker_id,
                    message_id=message.message_id,
                    outbox_id=existing_outbox.outbox_id,
                    reason=None,
                    payload=_with_schedule_tick(
                        {
                            "outbox_status": existing_outbox.status,
                            "recovered_existing_outbox": True,
                            "chat_status": _chat_status_from_outbox(existing_outbox),
                        },
                        schedule_tick,
                    ),
                )
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
                    payload=_with_schedule_tick({}, schedule_tick),
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
                    task_id=_answered_task_id(chat_result),
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
                    payload=_with_schedule_tick(
                        {"chat_status": chat_result.status, "outbox_status": outbox.status},
                        schedule_tick,
                    ),
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
                payload=_with_schedule_tick(
                    {
                        "chat_status": chat_result.status,
                        "chat_route": chat_result.route,
                        "outbox_status": outbox.status,
                        "answered_pending_outbox_ids": [item.outbox_id for item in answered_pending],
                        "command_result": chat_result.command_result,
                        "pending_question": chat_result.pending_question,
                        "final_answer_ref": _final_answer_ref(chat_result),
                    },
                    schedule_tick,
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive worker containment
            recorded = self.queue.fail(
                message.message_id,
                reason=type(exc).__name__,
                worker_id=self.worker_id,
                max_attempts=self.max_attempts,
                retry_backoff_ms=self.retry_backoff_ms,
            )
            failed_message = self.queue.inbox_message(message.message_id)
            inbox_status = failed_message.status if failed_message is not None else "unknown"
            self._journal_event(
                "resident_inbox_failed",
                {
                    "worker_id": self.worker_id,
                    "message_id": message.message_id,
                    "reason": type(exc).__name__,
                    "failure_recorded": recorded,
                    "resulting_status": inbox_status,
                    "attempts": failed_message.attempts if failed_message is not None else message.attempts,
                    "next_attempt_at_ms": failed_message.next_attempt_at_ms if failed_message is not None else None,
                    "max_attempts": self.max_attempts,
                    "retry_backoff_ms": self.retry_backoff_ms,
                },
                state_delta={"resident_inbox_status": inbox_status, "resident_message_id": message.message_id},
            )
            return ResidentRunResult(
                status="failed",
                worker_id=self.worker_id,
                message_id=message.message_id,
                outbox_id=None,
                reason=type(exc).__name__,
                payload=_with_schedule_tick(
                    {
                        "error": type(exc).__name__,
                        "failure_recorded": recorded,
                        "inbox_status": inbox_status,
                        "attempts": failed_message.attempts if failed_message is not None else message.attempts,
                        "next_attempt_at_ms": failed_message.next_attempt_at_ms if failed_message is not None else None,
                    },
                    schedule_tick,
                ),
            )
        finally:
            self.queue.release_lease(worker_id=self.worker_id)
            self._journal_event(
                "resident_lease_released",
                {"worker_id": self.worker_id, "lease_id": lease.lease_id, "message_id": message.message_id},
                state_delta={"resident_lease_status": "released"},
            )

    def _tick_schedules(self) -> JsonObject | None:
        if self.scheduler is None:
            return None
        try:
            return self.scheduler.tick(limit=self.schedule_tick_limit).to_dict()
        except Exception as exc:  # pragma: no cover - defensive scheduler containment
            payload = {"status": "failed", "reason": type(exc).__name__, "worker_id": self.worker_id}
            self._journal_event(
                "resident_schedule_tick_failed",
                payload,
                state_delta={"resident_schedule_tick_status": "failed"},
            )
            return payload

    def _schedule_status(self) -> JsonObject:
        if self.scheduler is None:
            return {}
        try:
            return self.scheduler.status().to_dict()
        except Exception as exc:  # pragma: no cover - defensive scheduler containment
            return {"status": "failed", "reason": type(exc).__name__}

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


def _chat_status_from_outbox(outbox) -> str | None:
    value = outbox.payload.get("status")
    return str(value) if isinstance(value, str) and value else None


def _final_answer_ref(chat_result) -> str | None:
    command = chat_result.command_result
    if isinstance(command, dict):
        result = command.get("result")
        if isinstance(result, dict) and isinstance(result.get("final_answer_ref"), str):
            return str(result["final_answer_ref"])
    return None


def _answered_task_id(chat_result) -> str | None:
    command = chat_result.command_result
    if isinstance(command, dict):
        plan_task_id = command.get("plan_task_id")
        if isinstance(plan_task_id, str) and plan_task_id:
            return plan_task_id
        result = command.get("result")
        if isinstance(result, dict):
            plan_task_id = result.get("plan_task_id")
            if isinstance(plan_task_id, str) and plan_task_id:
                return plan_task_id
    return chat_result.task_id


def _with_schedule_tick(payload: JsonObject, schedule_tick: JsonObject | None) -> JsonObject:
    if schedule_tick is None:
        return payload
    return {**payload, "schedule_tick": schedule_tick}


def _schedule_failure_reason(results: list[ResidentRunResult], schedule_status: JsonObject) -> str | None:
    if schedule_status.get("status") == "failed":
        return "resident_schedule_status_failed"
    for result in results:
        tick = result.payload.get("schedule_tick")
        if isinstance(tick, dict) and tick.get("status") == "failed":
            return "resident_schedule_tick_failed"
    return None
