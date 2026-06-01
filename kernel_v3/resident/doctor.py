from __future__ import annotations

import time
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryInspection, MemoryStore
from kernel_v3.research import CorpusInspection, ResearchCorpusStore
from kernel_v3.retrieval import RetrievalOperator, inspect_retrieval_providers
from kernel_v3.retrieval.contracts import RetrievalProviderInspection
from kernel_v3.resident.contracts import (
    ResidentDoctorReport,
    ResidentQueueInspection,
    ResidentScheduleInspection,
)
from kernel_v3.resident.queue import ResidentQueue
from kernel_v3.resident.scheduler import ResidentScheduler


class ResidentDoctor:
    def __init__(
        self,
        *,
        queue: ResidentQueue,
        scheduler: ResidentScheduler,
        journal: JournalStore | None = None,
        artifact_store: ArtifactStore | None = None,
        memory_store: MemoryStore | None = None,
        corpus_store: ResearchCorpusStore | None = None,
        retrieval_operator: RetrievalOperator | None = None,
        research_profile_id: str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.queue = queue
        self.scheduler = scheduler
        self.journal = journal
        self.artifact_store = artifact_store
        self.memory_store = memory_store
        self.corpus_store = corpus_store
        self.retrieval_operator = retrieval_operator
        self.research_profile_id = research_profile_id
        self.clock_ms = clock_ms or queue.clock_ms or (lambda: time.monotonic_ns() // 1_000_000)

    def inspect(self, *, sample_limit: int = 5) -> ResidentDoctorReport:
        queue_inspection = self._inspect_queue(sample_limit=sample_limit)
        schedule_inspection = self._inspect_schedule(sample_limit=sample_limit)
        memory_inspection = self._inspect_memory(sample_limit=sample_limit)
        corpus_inspection = self._inspect_corpus(sample_limit=sample_limit)
        retrieval_provider_inspection = self._inspect_retrieval_providers()
        configured = {
            "artifact_store": self.artifact_store is not None,
            "memory_store": self.memory_store is not None,
            "corpus_store": self.corpus_store is not None,
            "retrieval_operator": self.retrieval_operator is not None,
            "resident_db": str(self.queue.db_path),
        }
        component_statuses = [
            queue_inspection.status,
            schedule_inspection.status,
            memory_inspection.status if memory_inspection is not None else "ok",
            corpus_inspection.status if corpus_inspection is not None else "ok",
            retrieval_provider_inspection.status if retrieval_provider_inspection is not None else "ok",
        ]
        issues: list[JsonObject] = []
        issues.extend(_component_issues("queue", queue_inspection.issues))
        issues.extend(_component_issues("schedule", schedule_inspection.issues))
        if memory_inspection is not None:
            issues.extend(_memory_issues(memory_inspection.to_dict()))
        if corpus_inspection is not None:
            issues.extend(_component_issues("corpus", corpus_inspection.issues))
        if retrieval_provider_inspection is not None:
            issues.extend(_component_issues("retrieval", retrieval_provider_inspection.issues))
        return ResidentDoctorReport(
            status=_combined_health(component_statuses),
            generated_at_ms=self._now_ms(),
            configured=configured,
            issues=issues,
            recommended_actions=_ordered_unique(
                [
                    *queue_inspection.recommended_actions,
                    *schedule_inspection.recommended_actions,
                    *(memory_inspection.recommended_actions if memory_inspection is not None else []),
                    *(corpus_inspection.recommended_actions if corpus_inspection is not None else []),
                    *(
                        retrieval_provider_inspection.recommended_actions
                        if retrieval_provider_inspection is not None
                        else []
                    ),
                ]
            ),
            queue_inspection=queue_inspection.to_dict(),
            schedule_inspection=schedule_inspection.to_dict(),
            memory_inspection=memory_inspection.to_dict() if memory_inspection is not None else None,
            corpus_inspection=corpus_inspection.to_dict() if corpus_inspection is not None else None,
            retrieval_provider_inspection=(
                retrieval_provider_inspection.to_dict() if retrieval_provider_inspection is not None else None
            ),
        )

    def _inspect_queue(self, *, sample_limit: int) -> ResidentQueueInspection:
        try:
            return self.queue.inspect(sample_limit=sample_limit)
        except Exception as exc:
            return ResidentQueueInspection(
                status="error",
                generated_at_ms=self._now_ms(),
                issues=[_inspection_failure_issue("queue", exc)],
                recommended_actions=["repair resident queue store or rerun resident doctor with diagnostics"],
                queue_status={"status": "failed", "reason": type(exc).__name__},
                samples={},
            )

    def _inspect_schedule(self, *, sample_limit: int) -> ResidentScheduleInspection:
        try:
            return self.scheduler.inspect(sample_limit=sample_limit)
        except Exception as exc:
            return ResidentScheduleInspection(
                status="error",
                generated_at_ms=self._now_ms(),
                issues=[_inspection_failure_issue("schedule", exc)],
                recommended_actions=["repair resident schedule store or rerun resident doctor with diagnostics"],
                schedule_status={"status": "failed", "reason": type(exc).__name__},
                samples={},
            )

    def _inspect_memory(self, *, sample_limit: int) -> MemoryInspection | None:
        if self.memory_store is None:
            return None
        try:
            return self.memory_store.inspect(
                sample_limit=sample_limit,
                journal=self.journal,
                artifact_store=self.artifact_store,
            )
        except Exception as exc:
            return MemoryInspection(
                status="error",
                active_count=0,
                expired_count=0,
                deleted_count=0,
                sensitive_count=0,
                proposal_counts={},
                shadow_candidate_count=0,
                tombstone_count=0,
                audit_record_count=0,
                issues=[_inspection_failure_issue("memory", exc)],
                provenance_consistency={"checked": False, "reason": "memory_inspection_failed"},
                samples={},
                recommended_actions=["repair memory store or rebuild memory index"],
                generated_at_ms=self._now_ms(),
            )

    def _inspect_corpus(self, *, sample_limit: int) -> CorpusInspection | None:
        if self.corpus_store is None:
            return None
        try:
            return self.corpus_store.inspect(
                sample_limit=sample_limit,
                artifact_store=self.artifact_store,
                profile_id=self.research_profile_id,
            )
        except Exception as exc:
            return CorpusInspection(
                status="error",
                generated_at_ms=self._now_ms(),
                issues=[_inspection_failure_issue("corpus", exc)],
                recommended_actions=["repair research corpus store or rebuild corpus index"],
                corpus_status={"status": "failed", "reason": type(exc).__name__},
                artifact_consistency={"checked": False, "reason": "corpus_inspection_failed"},
                samples={},
            )

    def _inspect_retrieval_providers(self) -> RetrievalProviderInspection | None:
        if self.retrieval_operator is None:
            return None
        try:
            return inspect_retrieval_providers(
                self.retrieval_operator,
                research_profile_id=self.research_profile_id,
                clock_ms=self.clock_ms,
            )
        except Exception as exc:
            return RetrievalProviderInspection(
                status="error",
                generated_at_ms=self._now_ms(),
                network_access=False,
                provider_capabilities=[],
                issues=[_inspection_failure_issue("retrieval", exc)],
                recommended_actions=["repair retrieval provider configuration"],
                diagnostics={"status": "failed", "reason": type(exc).__name__},
            )

    def _now_ms(self) -> int:
        return int(self.clock_ms())


def _inspection_failure_issue(component: str, exc: Exception) -> JsonObject:
    return {
        "severity": "error",
        "code": f"{component}_inspection_failed",
        "reason": type(exc).__name__,
        "redaction": {"exception_message": "omitted"},
    }


def _component_issues(component: str, issues: list[JsonObject]) -> list[JsonObject]:
    return [{**dict(issue), "component": component} for issue in issues]


def _memory_issues(memory_inspection: JsonObject) -> list[JsonObject]:
    issues: list[JsonObject] = []
    raw_issues = memory_inspection.get("issues")
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if isinstance(issue, dict):
                issues.append({**issue, "component": "memory"})
    proposal_counts = memory_inspection.get("proposal_counts")
    pending = int(proposal_counts.get("pending", 0)) if isinstance(proposal_counts, dict) else 0
    if pending:
        issues.append({"component": "memory", "severity": "attention", "code": "pending_memory_proposals", "count": pending})
    expired = int(memory_inspection.get("expired_count", 0))
    if expired:
        issues.append({"component": "memory", "severity": "info", "code": "expired_memory_items", "count": expired})
    sensitive = int(memory_inspection.get("sensitive_count", 0))
    if sensitive:
        issues.append({"component": "memory", "severity": "info", "code": "sensitive_memory_items", "count": sensitive})
    return issues


def _combined_health(statuses: list[str]) -> str:
    order = {"ok": 0, "attention": 1, "needs_review": 2, "warning": 3, "error": 4}
    highest = max(statuses, key=lambda status: order.get(status, 1))
    return highest if highest in order else "attention"


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
