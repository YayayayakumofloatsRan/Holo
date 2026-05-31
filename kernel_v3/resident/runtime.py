from __future__ import annotations

from kernel_v3.chat import ChatRuntime
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
    ) -> None:
        self.queue = queue
        self.chat_runtime = chat_runtime
        self.worker_id = worker_id
        self.lease_ttl_ms = lease_ttl_ms
        self.max_attempts = max_attempts
        self.retry_backoff_ms = retry_backoff_ms

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
        if blocked:
            status = "blocked"
            reason = results[-1].reason if results else "blocked"
        elif results and results[-1].status == "idle":
            status = "idle" if processed == 0 and failed == 0 else "completed"
            reason = results[-1].reason
        elif len(results) >= max_iterations:
            status = "max_iterations"
            reason = "max_iterations"
        else:
            status = "completed"
            reason = None
        return ResidentLoopResult(
            status=status,
            worker_id=self.worker_id,
            iterations=len(results),
            processed_count=processed,
            failed_count=failed,
            blocked_count=blocked,
            idle_count=idle,
            reason=reason,
            results=[item.to_dict() for item in results],
        )

    def run_once(self) -> ResidentRunResult:
        lease = self.queue.acquire_lease(worker_id=self.worker_id, ttl_ms=self.lease_ttl_ms)
        if lease is None:
            return ResidentRunResult(
                status="blocked",
                worker_id=self.worker_id,
                message_id=None,
                outbox_id=None,
                reason="lease_unavailable",
                payload={},
            )
        message = self.queue.claim_next(worker_id=self.worker_id, lease_ttl_ms=self.lease_ttl_ms)
        if message is None:
            self.queue.release_lease(worker_id=self.worker_id)
            return ResidentRunResult(
                status="idle",
                worker_id=self.worker_id,
                message_id=None,
                outbox_id=None,
                reason="no_pending_inbox",
                payload={"lease": lease.to_dict()},
            )
        try:
            chat_result = self.chat_runtime.receive(message.text, thread_id=message.thread_id)
            renewed = self.queue.renew_lease(worker_id=self.worker_id, ttl_ms=self.lease_ttl_ms)
            if renewed is None:
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
            completed = self.queue.complete(message.message_id, worker_id=self.worker_id)
            if not completed:
                return ResidentRunResult(
                    status="blocked",
                    worker_id=self.worker_id,
                    message_id=message.message_id,
                    outbox_id=outbox.outbox_id,
                    reason="message_ownership_lost_before_complete",
                    payload={"chat_status": chat_result.status, "outbox_status": outbox.status},
                )
            return ResidentRunResult(
                status="processed",
                worker_id=self.worker_id,
                message_id=message.message_id,
                outbox_id=outbox.outbox_id,
                reason=None,
                payload={"chat_status": chat_result.status, "outbox_status": outbox.status},
            )
        except Exception as exc:  # pragma: no cover - defensive worker containment
            recorded = self.queue.fail(
                message.message_id,
                reason=type(exc).__name__,
                worker_id=self.worker_id,
                max_attempts=self.max_attempts,
                retry_backoff_ms=self.retry_backoff_ms,
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
