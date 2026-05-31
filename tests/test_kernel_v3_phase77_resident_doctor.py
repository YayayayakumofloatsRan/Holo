import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.memory import MemoryItem, MemoryProposal, MemoryStore, stable_memory_id, stable_proposal_id
from kernel_v3.resident import ResidentDoctor, ResidentQueue, ResidentScheduler


def test_phase77_resident_doctor_aggregates_queue_schedule_and_memory(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    scheduler = ResidentScheduler(queue=queue, clock_ms=_clock())
    memory = MemoryStore.in_memory(clock_ms=_clock())
    item = _memory_item(summary="prefer concise Chinese", thread_id="doctor-thread")
    memory.commit(item)
    memory.record_proposal(_proposal(item, proposal_id="memprop-doctor"))
    queue.enqueue(thread_id="doctor-thread", text="pending resident work", message_id="in-doctor")
    scheduler.add_schedule(
        schedule_id="sched-doctor",
        thread_id="doctor-thread",
        text="due scheduled resident work",
        due_in_ms=0,
    )

    report = ResidentDoctor(queue=queue, scheduler=scheduler, memory_store=memory).inspect(sample_limit=1)

    assert report.status == "needs_review"
    assert report.configured["memory_store"] is True
    assert report.configured["corpus_store"] is False
    assert report.queue_inspection["queue_status"]["claimable_count"] == 1
    assert report.schedule_inspection["schedule_status"]["due_count"] == 1
    assert report.memory_inspection is not None
    assert report.memory_inspection["proposal_counts"]["pending"] == 1
    assert report.corpus_inspection is None
    issue_components = {issue["component"] for issue in report.issues}
    assert {"queue", "schedule", "memory"}.issubset(issue_components)
    assert "resident run --max-iterations <n>" in report.recommended_actions
    assert "resident run --tick-schedules --max-iterations <n>" in report.recommended_actions
    assert "memory proposals" in report.recommended_actions


def test_phase77_cli_resident_doctor_includes_configured_memory_and_corpus(tmp_path: Path, capsys) -> None:
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    memory_log = tmp_path / "memory.jsonl"
    memory_index = tmp_path / "memory.sqlite"
    corpus_log = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"
    memory = MemoryStore(memory_log, index_path=memory_index, clock_ms=_clock())
    item = _memory_item(summary="cli resident doctor memory", thread_id="cli-doctor")
    memory.commit(item)
    memory.record_proposal(_proposal(item, proposal_id="memprop-cli-doctor"))
    base = [
        "--journal",
        str(journal),
        "--index",
        str(index),
        "--resident-db",
        str(resident_db),
        "--memory-log",
        str(memory_log),
        "--memory-index",
        str(memory_index),
        "--corpus-log",
        str(corpus_log),
        "--corpus-index",
        str(corpus_index),
    ]
    assert cli.main([*base, "resident", "enqueue", "doctor pending work", "--thread", "cli-doctor"]) == 0
    capsys.readouterr()
    assert (
        cli.main(
            [
                *base,
                "resident",
                "schedule-add",
                "doctor scheduled work",
                "--thread",
                "cli-doctor",
                "--schedule-id",
                "sched-cli-doctor",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main([*base, "resident", "doctor", "--sample-limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "needs_review"
    doctor = payload["doctor"]
    assert doctor["configured"]["artifact_store"] is False
    assert doctor["configured"]["memory_store"] is True
    assert doctor["configured"]["corpus_store"] is True
    assert doctor["queue_inspection"]["queue_status"]["claimable_count"] == 1
    assert doctor["schedule_inspection"]["schedule_status"]["due_count"] == 1
    assert doctor["memory_inspection"]["proposal_counts"]["pending"] == 1
    assert doctor["corpus_inspection"]["issues"][0]["code"] == "empty_corpus"


def _memory_item(*, summary: str, thread_id: str) -> MemoryItem:
    scope = {"user_id": "local:user", "project_id": "holo-kernel-v3", "thread_id": thread_id}
    dedupe_key = f"user_preference:{summary}"
    return MemoryItem(
        memory_id=stable_memory_id(kind="user_preference", scope=scope, dedupe_key=dedupe_key, summary=summary),
        kind="user_preference",
        title=summary,
        summary=summary,
        body=summary,
        structured={"source": "phase77-test"},
        scope=scope,
        privacy_class="project_internal",
        confidence=0.9,
        ttl_policy="forever",
        expires_at_ms=None,
        dedupe_key=dedupe_key,
        conflict_keys=[dedupe_key],
        provenance_refs=[],
        artifact_refs=[],
        state="active",
        approved_by="test",
        created_at_ms=1_000,
        updated_at_ms=1_000,
        last_accessed_ms=None,
    )


def _proposal(item: MemoryItem, *, proposal_id: str) -> MemoryProposal:
    payload = {"memory_id": item.memory_id, "summary": item.summary}
    return MemoryProposal(
        proposal_id=proposal_id or stable_proposal_id(payload),
        candidate_id=None,
        operation="upsert",
        proposed_item=item.to_dict(),
        rationale="test proposal",
        source_task_id="task-doctor",
        source_run_id="run-doctor",
        source_thread_id=str(item.scope["thread_id"]),
        evidence_record_refs=[],
        artifact_refs=[],
        risk_flags=[],
        approval_policy="needs_review",
        approval_status="pending",
        confidence=0.9,
        created_at_ms=1_001,
        decided_at_ms=None,
    )


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick
