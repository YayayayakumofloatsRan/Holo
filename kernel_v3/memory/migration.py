from __future__ import annotations

from dataclasses import dataclass

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.memory.pipeline import MemoryPipeline
from kernel_v3.memory.store import MemoryStore


@dataclass(frozen=True, kw_only=True)
class MemoryMigrationReport:
    scanned_records: int
    migrated_records: int
    proposals: list[str]
    rejected: list[JsonObject]
    source_record_refs: list[str]

    def to_dict(self) -> JsonObject:
        return {
            "scanned_records": self.scanned_records,
            "migrated_records": self.migrated_records,
            "proposals": list(self.proposals),
            "rejected": list(self.rejected),
            "source_record_refs": list(self.source_record_refs),
        }


def migrate_semantic_intake_records(
    *,
    journal: JournalStore,
    store: MemoryStore,
    default_thread_id: str = "default",
    limit: int | None = None,
) -> MemoryMigrationReport:
    from kernel_v3.agent.contracts import SemanticIntake

    pipeline = MemoryPipeline(store=store, journal=journal)
    scanned = 0
    migrated = 0
    proposals: list[str] = []
    rejected: list[JsonObject] = []
    source_refs: list[str] = []
    records = journal.records(kind="semantic_intake")
    if limit is not None:
        records = records[: max(0, limit)]
    for record in records:
        scanned += 1
        if _already_migrated(journal, record.record_id):
            continue
        intake = SemanticIntake.from_dict(record.data)
        if not _has_memory_write_intent(intake.to_dict()):
            continue
        thread_id = _thread_id_for_task(journal, record.task_id) or default_thread_id
        result = pipeline.propose_from_semantic_intake(
            intake,
            task_id=record.task_id or "task-memory-migration",
            run_id=record.run_id,
            thread_id=thread_id,
            source_record_ref=record.record_id,
        )
        migrated += 1
        proposals.extend(proposal.proposal_id for proposal in result.proposals)
        rejected.extend(result.rejected)
        source_refs.append(record.record_id)
        journal.append(
            task_id=record.task_id,
            run_id=record.run_id,
            step_id=None,
            kind="memory_migration",
            data={
                "source_record_ref": record.record_id,
                "proposal_ids": [proposal.proposal_id for proposal in result.proposals],
                "rejected": list(result.rejected),
            },
            state_delta={"memory_migration": "semantic_intake"},
        )
    return MemoryMigrationReport(
        scanned_records=scanned,
        migrated_records=migrated,
        proposals=proposals,
        rejected=rejected,
        source_record_refs=source_refs,
    )


def _already_migrated(journal: JournalStore, record_id: str) -> bool:
    for record in journal.records(kind="memory_migration"):
        if record.data.get("source_record_ref") == record_id:
            return True
    return False


def _has_memory_write_intent(intake: JsonObject) -> bool:
    intents = intake.get("intents")
    if not isinstance(intents, list):
        return False
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        if intent.get("kind") == "memory_write":
            return True
        capabilities = intent.get("required_capabilities")
        if isinstance(capabilities, list) and "durable_memory:write" in capabilities:
            return True
    return False


def _thread_id_for_task(journal: JournalStore, task_id: str | None) -> str | None:
    if task_id is None:
        return None
    for record in journal.records(task_id=task_id):
        if record.kind not in {"task", "session_state", "chat_turn"}:
            continue
        thread_id = record.data.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
    return None
