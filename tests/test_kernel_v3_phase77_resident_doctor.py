import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryItem, MemoryProposal, MemoryStore, stable_memory_id, stable_proposal_id
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore, finance_fundamentals_profile
from kernel_v3.research.corpus import corpus_document_from_retrieval
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import SearchGoal, SearchSource
from kernel_v3.retrieval.contracts import FetchedDocument
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
    assert "memory_without_provenance" in {issue["code"] for issue in report.issues}
    issue_components = {issue["component"] for issue in report.issues}
    assert {"queue", "schedule", "memory"}.issubset(issue_components)
    assert "resident run --max-iterations <n>" in report.recommended_actions
    assert "resident run --tick-schedules --max-iterations <n>" in report.recommended_actions
    assert "memory proposals" in report.recommended_actions
    assert "review memory provenance" in report.recommended_actions


def test_phase77_resident_doctor_reports_memory_reference_integrity(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident-integrity.sqlite", clock_ms=_clock())
    scheduler = ResidentScheduler(queue=queue, clock_ms=_clock())
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    memory = MemoryStore.in_memory(clock_ms=_clock())
    memory.commit(
        _memory_item(
            summary="broken doctor memory",
            thread_id="doctor-integrity",
            provenance_refs=["ledger-missing"],
            artifact_refs=["artifact-missing"],
        )
    )

    report = ResidentDoctor(
        queue=queue,
        scheduler=scheduler,
        journal=journal,
        artifact_store=artifacts,
        memory_store=memory,
    ).inspect(sample_limit=1)

    assert report.status == "error"
    assert report.memory_inspection is not None
    assert report.memory_inspection["provenance_consistency"]["missing_provenance_refs"] == 1
    issue_codes = {issue["code"] for issue in report.issues}
    assert {"missing_memory_provenance", "missing_memory_artifacts"}.issubset(issue_codes)
    assert "repair artifact store or delete affected memory" in report.recommended_actions


def test_phase77_resident_doctor_uses_research_profile_for_corpus_health(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident-profile-corpus.sqlite", clock_ms=_clock())
    scheduler = ResidentScheduler(queue=queue, clock_ms=_clock())
    corpus = ResearchCorpusStore.in_memory(clock_ms=_clock())
    source = _source(
        "src-sec-global",
        "https://www.sec.gov/Archives/edgar/data/320193/global-filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=_document(
                source=source,
                artifact_id="artifact-global-sec",
                payload_hash="hash-global-sec",
                preview=source.snippet,
            ),
            source=source,
            goal=SearchGoal(goal_id="goal-global", query="AAPL revenue"),
            task_id="task-global",
            run_id="run-global",
            fetched_at_ms=1_001,
            source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
        )
    )

    report = ResidentDoctor(
        queue=queue,
        scheduler=scheduler,
        corpus_store=corpus,
        research_profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
    ).inspect(sample_limit=1)

    assert report.status == "attention"
    assert report.configured["corpus_store"] is True
    assert report.corpus_inspection is not None
    scope = report.corpus_inspection["corpus_status"]["inspection_scope"]
    assert scope["profile_id"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert scope["document_count"] == 0
    assert scope["global_document_count"] == 1
    codes = {(issue["component"], issue["code"]) for issue in report.issues}
    assert ("corpus", "empty_profile_corpus") in codes
    assert (
        f"retrieve <query> --profile {FINANCE_FUNDAMENTALS_PROFILE_ID} --index-corpus"
        in report.recommended_actions
    )


def test_phase77_resident_doctor_contains_component_inspection_failures(tmp_path: Path) -> None:
    report = ResidentDoctor(
        queue=_FailingQueue(tmp_path / "resident-failed.sqlite"),
        scheduler=_FailingScheduler(),
        memory_store=_FailingMemoryStore(),
        corpus_store=_FailingCorpusStore(),
        retrieval_operator=_FailingRetrievalOperator(),
    ).inspect(sample_limit=1)

    assert report.status == "error"
    assert report.queue_inspection["status"] == "error"
    assert report.schedule_inspection["status"] == "error"
    assert report.memory_inspection is not None
    assert report.memory_inspection["status"] == "error"
    assert report.corpus_inspection is not None
    assert report.corpus_inspection["status"] == "error"
    assert report.retrieval_provider_inspection is not None
    assert report.retrieval_provider_inspection["status"] == "error"
    codes = {(issue["component"], issue["code"]) for issue in report.issues}
    assert ("queue", "queue_inspection_failed") in codes
    assert ("schedule", "schedule_inspection_failed") in codes
    assert ("memory", "memory_inspection_failed") in codes
    assert ("corpus", "corpus_inspection_failed") in codes
    assert ("retrieval", "retrieval_inspection_failed") in codes
    assert all(issue["redaction"] == {"exception_message": "omitted"} for issue in report.issues)
    assert "repair resident queue store or rerun resident doctor with diagnostics" in report.recommended_actions
    assert "repair resident schedule store or rerun resident doctor with diagnostics" in report.recommended_actions
    assert "repair memory store or rebuild memory index" in report.recommended_actions
    assert "repair research corpus store or rebuild corpus index" in report.recommended_actions
    assert "repair retrieval provider configuration" in report.recommended_actions


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


def _memory_item(
    *,
    summary: str,
    thread_id: str,
    provenance_refs: list[str] | None = None,
    artifact_refs: list[str] | None = None,
) -> MemoryItem:
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
        provenance_refs=list(provenance_refs or []),
        artifact_refs=list(artifact_refs or []),
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


class _FailingQueue:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.clock_ms = _clock()

    def inspect(self, *, sample_limit: int = 5):
        raise RuntimeError("queue raw failure must not leak")


class _FailingScheduler:
    def inspect(self, *, sample_limit: int = 5):
        raise RuntimeError("schedule raw failure must not leak")


class _FailingMemoryStore:
    def inspect(self, *, sample_limit: int = 5, journal=None, artifact_store=None):
        raise RuntimeError("memory raw failure must not leak")


class _FailingCorpusStore:
    def inspect(self, *, sample_limit: int = 5, artifact_store=None, profile_id=None):
        raise RuntimeError("corpus raw failure must not leak")


class _FailingRetrievalOperator:
    pass


def _source(
    source_id: str,
    uri: str,
    title: str,
    snippet: str,
) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
        metadata={},
    )


def _document(*, source: SearchSource, artifact_id: str, payload_hash: str, preview: str) -> FetchedDocument:
    return FetchedDocument(
        document_id=f"doc-{source.source_id}",
        goal_id="goal-doctor",
        source_id=source.source_id,
        uri=source.uri,
        title=source.title,
        artifact_id=artifact_id,
        payload_hash=payload_hash,
        preview=preview,
        size_bytes=len(preview.encode("utf-8")),
        metadata={"mime_type": "text/plain"},
    )
