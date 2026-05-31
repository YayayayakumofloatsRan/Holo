import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent.runtime import AgentRuntime
from kernel_v3.chat.runtime import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.resident import ResidentQueue, ResidentRuntime
from kernel_v3.trace import TraceRenderer


def test_phase73_resident_worker_processes_inbox_to_outbox(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    chat = ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal))
    queue.enqueue(thread_id="resident-thread", text="hello resident", message_id="in-1")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-1", journal=journal).run_once()

    assert result.status == "processed"
    assert queue.inbox_messages()[0].status == "completed"
    outbox = queue.outbox_messages()[0]
    assert outbox.in_reply_to == "in-1"
    assert outbox.status == "ready"
    assert "离线 host fallback" in outbox.text
    assert "Direct answer:" not in outbox.text
    resident_kinds = [record.kind for record in journal.records() if record.kind.startswith("resident_")]
    assert resident_kinds == [
        "resident_lease_acquired",
        "resident_inbox_claimed",
        "resident_outbox_appended",
        "resident_inbox_completed",
        "resident_lease_released",
    ]
    assert "resident_outbox_appended" in TraceRenderer(journal).render_resident_trace()


def test_phase73_worker_lease_prevents_duplicate_ownership(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())

    first = queue.acquire_lease(worker_id="worker-1", ttl_ms=30_000)
    second = queue.acquire_lease(worker_id="worker-2", ttl_ms=30_000)

    assert first is not None
    assert second is None


def test_phase73_restart_picks_pending_inbox_item(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello after restart", message_id="in-restart")
    restarted = ResidentQueue(db_path, clock_ms=_clock(start=2_000))
    journal = JournalStore.in_memory()

    result = ResidentRuntime(
        queue=restarted,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-restart",
    ).run_once()

    assert result.status == "processed"
    assert restarted.inbox_messages()[0].status == "completed"
    assert restarted.outbox_messages()[0].in_reply_to == "in-restart"


def test_phase73_enqueue_is_idempotent_for_retried_inbound_delivery(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())

    first = queue.enqueue(thread_id="resident-thread", text="same delivery", source="gateway", message_id="in-same")
    second = queue.enqueue(thread_id="resident-thread", text="same delivery", source="gateway", message_id="in-same")

    assert second == first
    assert len(queue.inbox_messages()) == 1
    assert queue.inbox_messages()[0].message_id == "in-same"


def test_phase73_enqueue_rejects_conflicting_duplicate_message_id(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())

    queue.enqueue(thread_id="resident-thread", text="first payload", source="gateway", message_id="in-conflict")

    try:
        queue.enqueue(thread_id="resident-thread", text="changed payload", source="gateway", message_id="in-conflict")
    except ValueError as exc:
        assert "resident_inbox_message_id_conflict:in-conflict" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("conflicting duplicate message_id was accepted")
    assert len(queue.inbox_messages()) == 1


def test_phase73_restart_after_partial_outbox_write_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello after partial crash", message_id="in-partial")
    assert queue.acquire_lease(worker_id="crashed-worker", ttl_ms=10) is not None
    claimed = queue.claim_next(worker_id="crashed-worker", lease_ttl_ms=1)
    assert claimed is not None
    queue.append_outbox(
        in_reply_to=claimed.message_id,
        thread_id=claimed.thread_id,
        text="previous outbox already written",
        status="ready",
        task_id="task-crash",
        run_id="run-crash",
        payload={"partial": True},
    )

    restarted = ResidentQueue(db_path, clock_ms=_clock(start=10_000))
    journal = JournalStore.in_memory()
    result = ResidentRuntime(
        queue=restarted,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-restart",
    ).run_once()

    inbox = restarted.inbox_messages()[0]
    outbox = restarted.outbox_messages()
    assert result.status == "processed"
    assert inbox.status == "completed"
    assert inbox.attempts == 2
    assert len(outbox) == 1
    assert outbox[0].in_reply_to == "in-partial"
    assert outbox[0].text == "previous outbox already written"


def test_phase73_claim_requires_active_worker_lease(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello without lease", message_id="in-no-lease")

    assert queue.claim_next(worker_id="worker-without-lease") is None
    inbox = queue.inbox_messages()[0]
    assert inbox.status == "pending"
    assert inbox.attempts == 0


def test_phase73_stale_worker_cannot_complete_message_after_reclaim(tmp_path: Path):
    db_path = tmp_path / "resident.sqlite"
    queue = ResidentQueue(db_path, clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello reclaim", message_id="in-reclaim")
    assert queue.acquire_lease(worker_id="worker-old", ttl_ms=10) is not None
    first = queue.claim_next(worker_id="worker-old", lease_ttl_ms=1)
    assert first is not None

    restarted = ResidentQueue(db_path, clock_ms=_clock(start=10_000))
    assert restarted.acquire_lease(worker_id="worker-new", ttl_ms=30_000) is not None
    second = restarted.claim_next(worker_id="worker-new", lease_ttl_ms=30_000)
    assert second is not None

    assert restarted.complete("in-reclaim", worker_id="worker-old") is False
    inbox = restarted.inbox_messages()[0]
    assert inbox.status == "running"
    assert inbox.lease_owner == "worker-new"

    assert restarted.complete("in-reclaim", worker_id="worker-new") is True
    assert restarted.inbox_messages()[0].status == "completed"


def test_phase73_renew_lease_extends_running_message_claim(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="hello renew", message_id="in-renew")
    assert queue.acquire_lease(worker_id="worker-1", ttl_ms=10) is not None
    claimed = queue.claim_next(worker_id="worker-1", lease_ttl_ms=10)
    assert claimed is not None
    before = queue.inbox_messages()[0].lease_until_ms

    renewed = queue.renew_lease(worker_id="worker-1", ttl_ms=50)
    after = queue.inbox_messages()[0].lease_until_ms

    assert renewed is not None
    assert before is not None
    assert after is not None
    assert after > before


def test_phase73_needs_user_input_writes_pending_outbox_without_self_continuation(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _workspace_read_intake()}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
    )
    queue.enqueue(thread_id="resident-thread", text="read the file", message_id="in-question")

    result = ResidentRuntime(
        queue=queue,
        chat_runtime=chat,
        worker_id="worker-1",
    ).run_once()

    outbox = queue.outbox_messages()[0]
    assert result.status == "processed"
    assert outbox.status == "pending_user_input"
    assert "请明确" in outbox.text
    assert len(queue.outbox_messages()) == 1


def test_phase73_answering_pending_question_marks_old_outbox_answered(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": [_workspace_read_intake(), _workspace_read_intake()]}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(
            journal=journal,
            processor_fabric=fabric,
            workspace_files={"README.md": "resident answered workspace evidence"},
        ),
        semantic_mode="model",
    )
    runtime = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-1", journal=journal)
    queue.enqueue(thread_id="resident-thread", text="read the file", message_id="in-question")

    first = runtime.run_once()
    queue.enqueue(thread_id="resident-thread", text="README.md", message_id="in-answer")
    second = runtime.run_once()

    outboxes = {item.in_reply_to: item for item in queue.outbox_messages()}
    pending = outboxes["in-question"]
    answer = outboxes["in-answer"]
    assert first.status == "processed"
    assert second.status == "processed"
    assert pending.status == "answered"
    assert pending.payload["answered_by_message_id"] == "in-answer"
    assert pending.payload["answered_run_id"] == "run-2"
    assert answer.status == "ready"
    assert "resident answered workspace evidence" in answer.text
    assert second.payload["answered_pending_outbox_ids"] == [pending.outbox_id]
    assert journal.records(kind="resident_pending_outbox_answered")
    assert "resident_pending_outbox_answered" in TraceRenderer(journal).render_resident_trace()


def test_phase73_answered_marker_does_not_mark_current_pending_outbox(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    old = queue.append_outbox(
        in_reply_to="in-question",
        thread_id="resident-thread",
        text="which file?",
        status="pending_user_input",
        task_id="task-1",
        run_id="run-1",
    )
    current = queue.append_outbox(
        in_reply_to="in-answer",
        thread_id="resident-thread",
        text="still need a clearer path",
        status="pending_user_input",
        task_id="task-1",
        run_id="run-2",
    )

    answered = queue.mark_pending_user_input_answered(
        thread_id="resident-thread",
        answered_by_message_id="in-answer",
        task_id="task-1",
        run_id="run-2",
        exclude_in_reply_to="in-answer",
    )

    statuses = {item.outbox_id: item.status for item in queue.outbox_messages()}
    assert [item.outbox_id for item in answered] == [old.outbox_id]
    assert statuses[old.outbox_id] == "answered"
    assert statuses[current.outbox_id] == "pending_user_input"


def test_phase73_pending_user_input_ack_preserves_waiting_semantics(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    outbox = queue.append_outbox(
        in_reply_to="in-question",
        thread_id="resident-thread",
        text="which file?",
        status="pending_user_input",
        task_id="task-1",
        run_id="run-1",
    )

    acked, reason = queue.transition_outbox_status(outbox.outbox_id, status="acknowledged")
    second, second_reason = queue.transition_outbox_status(outbox.outbox_id, status="acknowledged")

    assert reason is None
    assert second_reason is None
    assert acked is not None
    assert second is not None
    assert acked.status == "pending_user_input_delivered"
    assert second.status == "pending_user_input_delivered"
    assert second.payload["requested_status"] == "acknowledged"
    assert second.payload["acknowledged_at_ms"] >= acked.payload["acknowledged_at_ms"]


def test_phase73_answered_marker_resolves_delivered_pending_user_input(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    outbox = queue.append_outbox(
        in_reply_to="in-question",
        thread_id="resident-thread",
        text="which file?",
        status="pending_user_input",
        task_id="task-1",
        run_id="run-1",
    )
    acked, reason = queue.transition_outbox_status(outbox.outbox_id, status="acknowledged")
    assert reason is None
    assert acked is not None
    assert acked.status == "pending_user_input_delivered"

    answered = queue.mark_pending_user_input_answered(
        thread_id="resident-thread",
        answered_by_message_id="in-answer",
        task_id="task-1",
        run_id="run-2",
    )

    assert [item.outbox_id for item in answered] == [outbox.outbox_id]
    assert queue.outbox_messages()[0].status == "answered"
    assert queue.outbox_messages()[0].payload["answered_by_message_id"] == "in-answer"


def test_phase73_invalid_outbox_transition_is_rejected(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    outbox = queue.append_outbox(
        in_reply_to="in-ready",
        thread_id="resident-thread",
        text="ready",
        status="ready",
        task_id=None,
        run_id=None,
    )

    transitioned, reason = queue.transition_outbox_status(outbox.outbox_id, status="answered")

    assert transitioned is None
    assert reason == "invalid_outbox_status_transition:ready->answered"
    assert queue.outbox_messages()[0].status == "ready"


def test_phase73_append_outbox_rejects_unknown_status(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())

    try:
        queue.append_outbox(
            in_reply_to="in-invalid",
            thread_id="resident-thread",
            text="invalid",
            status="invented",
            task_id=None,
            run_id=None,
        )
    except ValueError as exc:
        assert "invalid_resident_outbox_status:invented" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("invalid outbox status was accepted")


def test_phase73_resident_worker_can_use_configured_model_semantic_chat(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieval_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "retrieval_research",
                        "text": "research resident evidence",
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {},
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
    )
    queue.enqueue(thread_id="resident-model-thread", text="unseen resident research request", message_id="in-model")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-model", journal=journal).run_once()

    outbox = queue.outbox_messages()[0]
    assert result.status == "processed"
    assert outbox.status == "ready"
    assert outbox.payload["final_answer"]["citation_refs"]
    assert journal.records(task_id=outbox.task_id, kind="processor_result")[0].data["task_type"] == "semantic.intake"


def test_phase73_bounded_run_loop_processes_until_idle(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    queue.enqueue(thread_id="resident-thread", text="first loop item", message_id="in-loop-1")
    queue.enqueue(thread_id="resident-thread", text="second loop item", message_id="in-loop-2")

    result = ResidentRuntime(
        queue=queue,
        chat_runtime=ChatRuntime(journal=journal, agent_runtime=AgentRuntime(journal=journal)),
        worker_id="worker-loop",
    ).run_loop(max_iterations=5)

    assert result.status == "completed"
    assert result.iterations == 3
    assert result.processed_count == 2
    assert result.idle_count == 1
    assert [message.status for message in queue.inbox_messages()] == ["completed", "completed"]
    assert [message.in_reply_to for message in queue.outbox_messages()] == ["in-loop-1", "in-loop-2"]


def test_phase73_worker_failure_retries_then_dead_letters(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="will fail", message_id="in-fail")
    runtime = ResidentRuntime(
        queue=queue,
        chat_runtime=_RaisingChatRuntime(),
        worker_id="worker-fail",
        max_attempts=2,
        retry_backoff_ms=0,
    )

    first = runtime.run_once()
    first_inbox = queue.inbox_messages()[0]
    second = runtime.run_once()
    second_inbox = queue.inbox_messages()[0]
    third = runtime.run_once()

    assert first.status == "failed"
    assert first.payload["failure_recorded"] is True
    assert first_inbox.status == "retry_wait"
    assert first_inbox.attempts == 1
    assert first_inbox.next_attempt_at_ms is not None
    assert second.status == "failed"
    assert second_inbox.status == "dead_letter"
    assert second_inbox.attempts == 2
    assert second_inbox.metadata["failure_reason"] == "RuntimeError"
    assert third.status == "idle"
    assert not queue.outbox_messages()


def test_phase73_dead_letter_can_be_requeued_for_manual_recovery(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="recover me", message_id="in-dead")
    assert queue.acquire_lease(worker_id="worker-requeue", ttl_ms=30_000) is not None
    claimed = queue.claim_next(worker_id="worker-requeue")
    assert claimed is not None
    assert queue.fail("in-dead", reason="RuntimeError", worker_id="worker-requeue", max_attempts=1)

    requeued = queue.requeue("in-dead", reason="operator_retry")

    assert requeued is not None
    assert requeued.status == "pending"
    assert requeued.attempts == 0
    assert requeued.metadata["last_requeue_reason"] == "operator_retry"
    assert requeued.metadata["requeue_count"] == 1
    assert queue.status().claimable_count == 1


def test_phase73_completed_message_cannot_be_requeued(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="done", message_id="in-done")
    assert queue.acquire_lease(worker_id="worker-done", ttl_ms=30_000) is not None
    claimed = queue.claim_next(worker_id="worker-done")
    assert claimed is not None
    assert queue.complete("in-done", worker_id="worker-done") is True

    assert queue.requeue("in-done", reason="operator_retry") is None
    assert queue.inbox_messages()[0].status == "completed"


def test_phase73_queue_status_reports_health_counts(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="retry item", message_id="in-retry")
    queue.enqueue(thread_id="resident-thread", text="running item", message_id="in-running")
    queue.enqueue(thread_id="resident-thread", text="pending item", message_id="in-pending")
    assert queue.acquire_lease(worker_id="worker-status", ttl_ms=10) is not None
    retry_claim = queue.claim_next(worker_id="worker-status", lease_ttl_ms=1)
    assert retry_claim is not None
    queue.fail(retry_claim.message_id, reason="Transient", worker_id="worker-status", max_attempts=3, retry_backoff_ms=5_000)
    running_claim = queue.claim_next(worker_id="worker-status", lease_ttl_ms=1)
    assert running_claim is not None
    queue.append_outbox(
        in_reply_to="manual-outbox",
        thread_id="resident-thread",
        text="ready outbox",
        status="ready",
        task_id=None,
        run_id=None,
    )

    status = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock(start=10_000)).status()

    assert status.inbox_counts["retry_wait"] == 1
    assert status.inbox_counts["running"] == 1
    assert status.inbox_counts["pending"] == 1
    assert status.outbox_counts["ready"] == 1
    assert status.claimable_count == 3
    assert status.due_retry_count == 1
    assert status.stale_running_count == 1
    assert status.ready_outbox_count == 1
    assert status.active_lease is None


def test_phase73_queue_inspect_reports_actionable_health(tmp_path: Path):
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    queue.enqueue(thread_id="resident-thread", text="dead item", message_id="in-dead")
    queue.enqueue(thread_id="resident-thread", text="pending item", message_id="in-pending")
    assert queue.acquire_lease(worker_id="worker-inspect", ttl_ms=10) is not None
    dead_claim = queue.claim_next(worker_id="worker-inspect")
    assert dead_claim is not None
    assert queue.fail(dead_claim.message_id, reason="RuntimeError", worker_id="worker-inspect", max_attempts=1)
    queue.append_outbox(
        in_reply_to="out-ready",
        thread_id="resident-thread",
        text="ready",
        status="ready",
        task_id=None,
        run_id=None,
    )
    queue.append_outbox(
        in_reply_to="out-waiting",
        thread_id="resident-thread",
        text="which file?",
        status="pending_user_input",
        task_id="task-1",
        run_id="run-1",
    )

    inspection = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock(start=10_000)).inspect(sample_limit=2)

    codes = {issue["code"] for issue in inspection.issues}
    assert inspection.status == "error"
    assert {"dead_letter_inbox", "pending_inbox", "ready_outbox", "awaiting_user_input"}.issubset(codes)
    assert "resident requeue <message_id> --reason manual_review" in inspection.recommended_actions
    assert "resident outbox" in inspection.recommended_actions
    assert inspection.queue_status["dead_letter_count"] == 1
    assert inspection.samples["inbox"]
    assert inspection.samples["outbox"]


def test_phase73_cli_resident_enqueue_run_once_and_outbox(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert cli.main([*base, "resident", "enqueue", "hello cli", "--thread", "resident-cli"]) == 0
    enqueued = json.loads(capsys.readouterr().out)
    assert enqueued["message"]["thread_id"] == "resident-cli"

    assert cli.main([*base, "resident", "run-once", "--worker-id", "worker-cli"]) == 0
    processed = json.loads(capsys.readouterr().out)
    assert processed["status"] == "processed"

    assert cli.main([*base, "resident", "outbox"]) == 0
    outbox = json.loads(capsys.readouterr().out)
    assert outbox["messages"][0]["status"] == "ready"
    assert "离线 host fallback" in outbox["messages"][0]["text"]
    assert "Direct answer:" not in outbox["messages"][0]["text"]
    outbox_id = outbox["messages"][0]["outbox_id"]

    assert cli.main([*base, "resident", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["queue"]["inbox_counts"]["completed"] == 1
    assert status["queue"]["outbox_counts"]["ready"] == 1

    assert cli.main([*base, "resident", "ack", outbox_id, "--status", "acknowledged"]) == 0
    acked = json.loads(capsys.readouterr().out)
    assert acked["outbox"]["status"] == "acknowledged"

    assert cli.main([*base, "resident", "run", "--worker-id", "worker-cli", "--max-iterations", "2"]) == 0
    loop = json.loads(capsys.readouterr().out)
    assert loop["status"] == "idle"

    assert cli.main([*base, "resident-trace"]) == 0
    trace = capsys.readouterr().out
    assert "Resident Trace" in trace
    assert "resident_inbox_enqueued" in trace
    assert "resident_outbox_ack" in trace
    assert outbox_id in trace


def test_phase73_cli_resident_ack_rejects_invalid_outbox_transition(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    queue = ResidentQueue(resident_db, clock_ms=_clock())
    outbox = queue.append_outbox(
        in_reply_to="in-ready",
        thread_id="resident-cli",
        text="ready",
        status="ready",
        task_id=None,
        run_id=None,
    )
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    status = cli.main([*base, "resident", "ack", outbox.outbox_id, "--status", "answered"])

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload["reason"] == "invalid_outbox_status_transition:ready->answered"
    assert ResidentQueue(resident_db).outbox_messages()[0].status == "ready"


def test_phase73_cli_resident_inspect_reports_queue_health(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    queue = ResidentQueue(resident_db, clock_ms=_clock())
    queue.enqueue(thread_id="resident-cli", text="pending", message_id="in-cli-pending")
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert cli.main([*base, "resident", "inspect", "--sample-limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["inspection"]["issues"][0]["code"] == "pending_inbox"
    assert payload["inspection"]["samples"]["inbox"][0]["message_id"] == "in-cli-pending"


def test_phase73_cli_resident_enqueue_can_replay_message_id_idempotently(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]

    assert cli.main([*base, "resident", "enqueue", "same gateway delivery", "--thread", "resident-cli", "--message-id", "in-cli-same"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main([*base, "resident", "enqueue", "same gateway delivery", "--thread", "resident-cli", "--message-id", "in-cli-same"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["message"] == first["message"]
    assert cli.main([*base, "resident", "inbox"]) == 0
    inbox = json.loads(capsys.readouterr().out)
    assert len(inbox["messages"]) == 1
    assert inbox["messages"][0]["message_id"] == "in-cli-same"


def test_phase73_cli_resident_requeue_dead_letter_and_journals(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = ["--journal", str(journal), "--index", str(index), "--resident-db", str(resident_db)]
    queue = ResidentQueue(resident_db, clock_ms=_clock())
    queue.enqueue(thread_id="resident-cli", text="recover via cli", message_id="in-cli-dead")
    assert queue.acquire_lease(worker_id="worker-cli-dead", ttl_ms=30_000) is not None
    claimed = queue.claim_next(worker_id="worker-cli-dead")
    assert claimed is not None
    assert queue.fail("in-cli-dead", reason="RuntimeError", worker_id="worker-cli-dead", max_attempts=1)

    assert cli.main([*base, "resident", "requeue", "in-cli-dead", "--reason", "manual_retry"]) == 0
    requeued = json.loads(capsys.readouterr().out)
    assert requeued["message"]["status"] == "pending"
    assert requeued["message"]["attempts"] == 0

    assert cli.main([*base, "resident", "run-once", "--worker-id", "worker-cli-recovered"]) == 0
    processed = json.loads(capsys.readouterr().out)
    assert processed["status"] == "processed"
    assert cli.main([*base, "resident-trace"]) == 0
    trace = capsys.readouterr().out
    assert "resident_inbox_requeued" in trace
    assert "in-cli-dead" in trace


def test_phase73_cli_resident_model_mode_is_live_gated(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("HOLO_V3_LIVE_MODEL", raising=False)
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"

    status = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "--resident-db",
            str(resident_db),
            "resident",
            "run-once",
            "--semantic-intake",
            "model",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload == {"reason": "live_model_not_enabled", "status": "blocked"}


class _RaisingChatRuntime:
    def receive(self, text: str, *, thread_id: str):
        raise RuntimeError("simulated failure")


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick


def _workspace_read_intake() -> dict:
    return {
        "primary_intent": "workspace_read",
        "suggested_mode": "workspace_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "workspace_read",
                "text": "read a workspace target",
                "sequence_index": 1,
                "required_capabilities": ["workspace.search", "file.read"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }
