from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.memory.contracts import MemoryItem, MemoryProposal, MemoryTombstone, ShadowCandidate
from kernel_v3.memory.privacy import contains_secret_like_content, validate_memory_item
from kernel_v3.memory.projection import (
    memory_item_event,
    memory_proposal_event,
    memory_tombstone_event,
    shadow_candidate_event,
)
from kernel_v3.memory.store import MemoryStore, stable_candidate_id, stable_memory_id, stable_proposal_id

if TYPE_CHECKING:
    from kernel_v3.agent.contracts import SemanticIntake


@dataclass(frozen=True, kw_only=True)
class MemoryPipelineResult:
    shadow_candidates: list[ShadowCandidate]
    proposals: list[MemoryProposal]
    committed_items: list[MemoryItem]
    rejected: list[JsonObject]

    def to_dict(self) -> JsonObject:
        return {
            "shadow_candidates": [item.to_dict() for item in self.shadow_candidates],
            "proposals": [item.to_dict() for item in self.proposals],
            "committed_items": [item.to_dict() for item in self.committed_items],
            "rejected": list(self.rejected),
        }


class MemoryPipeline:
    def __init__(
        self,
        *,
        store: MemoryStore,
        journal: JournalStore | None = None,
        clock_ms: Callable[[], int] | None = None,
        project_id: str = "holo-kernel-v3",
        user_id: str = "local:user",
    ) -> None:
        self.store = store
        self.journal = journal
        self.clock_ms = clock_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.project_id = project_id
        self.user_id = user_id

    def propose_from_semantic_intake(
        self,
        intake: "SemanticIntake",
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> MemoryPipelineResult:
        candidates: list[ShadowCandidate] = []
        proposals: list[MemoryProposal] = []
        rejected: list[JsonObject] = []
        for intent in _memory_intents(intake):
            text = str(intent.get("text") or intake.goal)
            if contains_secret_like_content(text):
                rejection = self._reject_secret(
                    task_id=task_id,
                    run_id=run_id,
                    thread_id=thread_id,
                    source_record_ref=source_record_ref,
                    text=text,
                )
                rejected.append(rejection)
                continue
            candidate = self._candidate_from_intent(
                intent,
                intake=intake,
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
            )
            self.store.record_shadow_candidate(candidate)
            self._journal_memory_record(
                task_id=task_id,
                run_id=run_id,
                kind="memory_shadow_candidate",
                data=shadow_candidate_event(candidate),
                state_delta={"memory_candidate": candidate.status},
            )
            candidates.append(candidate)
            proposal_or_rejection = self._proposal_from_candidate(
                candidate,
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
            )
            if isinstance(proposal_or_rejection, MemoryProposal):
                self.store.record_proposal(proposal_or_rejection)
                self._journal_memory_record(
                    task_id=task_id,
                    run_id=run_id,
                    kind="memory_proposal",
                    data=memory_proposal_event(proposal_or_rejection),
                    state_delta={"memory_proposal": proposal_or_rejection.approval_status},
                )
                proposals.append(proposal_or_rejection)
            else:
                rejected.append(proposal_or_rejection)
        return MemoryPipelineResult(
            shadow_candidates=candidates,
            proposals=proposals,
            committed_items=[],
            rejected=rejected,
        )

    def propose_from_research_result(
        self,
        *,
        answer_text: str,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
        metadata: JsonObject | None = None,
    ) -> MemoryPipelineResult:
        full_text = " ".join(str(answer_text or "").split())
        if not full_text:
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[])
        if contains_secret_like_content(full_text):
            rejection = self._reject_secret(
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                text=full_text,
            )
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[rejection])
        research_note = _research_result_payload(answer_text=full_text, metadata=metadata)
        text = str(research_note["body"])
        topic = str(research_note["topic"])
        candidate = ShadowCandidate(
            candidate_id=stable_candidate_id(
                {
                    "source_kind": "research_final_answer",
                    "task_id": task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "source_record_ref": source_record_ref,
                    "text_hash": _hash_text(full_text),
                    "topic": topic,
                }
            ),
            source_kind="research_final_answer",
            candidate_text=text,
            normalized_topic=topic,
            required_capabilities=["durable_memory:write"],
            blocked_capabilities=[],
            status="open",
            expires_at_ms=None,
            created_at_ms=self._now_ms(),
            metadata={
                "source_record_ref": source_record_ref,
                "task_id": task_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "source_kind": "research_final_answer",
                "memory_kind": "research_note",
                "title": research_note["title"],
                "summary": research_note["summary"],
                "body": text,
                "dedupe_key": research_note["dedupe_key"],
                "structured": research_note["structured"],
                "confidence": research_note["confidence"],
                "rationale": research_note["rationale"],
                "review_nonblocking": True,
                **dict(metadata or {}),
            },
        )
        self.store.record_shadow_candidate(candidate)
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind="memory_shadow_candidate",
            data=shadow_candidate_event(candidate),
            state_delta={"memory_candidate": candidate.status},
        )
        proposal_or_rejection = self._proposal_from_candidate(
            candidate,
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            source_record_ref=source_record_ref,
        )
        if isinstance(proposal_or_rejection, MemoryProposal):
            proposal = replace(
                proposal_or_rejection,
                rationale="research result may be useful as workspace/thread durable memory",
                metadata={
                    **dict(proposal_or_rejection.metadata),
                    "source_kind": "research_final_answer",
                    "review_nonblocking": True,
                    **dict(metadata or {}),
                },
            )
            self.store.record_proposal(proposal)
            self._journal_memory_record(
                task_id=task_id,
                run_id=run_id,
                kind="memory_proposal",
                data=memory_proposal_event(proposal),
                state_delta={"memory_proposal": proposal.approval_status},
            )
            return MemoryPipelineResult(shadow_candidates=[candidate], proposals=[proposal], committed_items=[], rejected=[])
        return MemoryPipelineResult(
            shadow_candidates=[candidate],
            proposals=[],
            committed_items=[],
            rejected=[proposal_or_rejection],
        )

    def propose_from_task_reflection(
        self,
        *,
        root_goal: str,
        outcome: str,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
        failure_report: JsonObject | None = None,
        final_answer: JsonObject | None = None,
        host_situation: JsonObject | None = None,
        metadata: JsonObject | None = None,
    ) -> MemoryPipelineResult:
        reflection = _task_reflection_payload(
            root_goal=root_goal,
            outcome=outcome,
            failure_report=failure_report,
            final_answer=final_answer,
            host_situation=host_situation,
            metadata=metadata,
        )
        text = str(reflection.get("body") or "")
        if not text:
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[])
        if contains_secret_like_content(text):
            rejection = self._reject_secret(
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                text=text,
            )
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[rejection])
        candidate = ShadowCandidate(
            candidate_id=stable_candidate_id(
                {
                    "source_kind": "task_reflection",
                    "task_id": task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "source_record_ref": source_record_ref,
                    "text_hash": _hash_text(text),
                    "dedupe_key": reflection["dedupe_key"],
                }
            ),
            source_kind="task_reflection",
            candidate_text=text,
            normalized_topic=str(reflection["topic"]),
            required_capabilities=["durable_memory:write"],
            blocked_capabilities=[],
            status="open",
            expires_at_ms=None,
            created_at_ms=self._now_ms(),
            metadata={
                "source_record_ref": source_record_ref,
                "task_id": task_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "source_kind": "task_reflection",
                "memory_kind": "workflow_convention",
                "title": reflection["title"],
                "summary": reflection["summary"],
                "body": text,
                "dedupe_key": reflection["dedupe_key"],
                "structured": reflection["structured"],
                "confidence": reflection["confidence"],
                "rationale": reflection["rationale"],
                "review_nonblocking": True,
                **dict(metadata or {}),
            },
        )
        self.store.record_shadow_candidate(candidate)
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind="memory_shadow_candidate",
            data=shadow_candidate_event(candidate),
            state_delta={"memory_candidate": candidate.status},
        )
        proposal_or_rejection = self._proposal_from_candidate(
            candidate,
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            source_record_ref=source_record_ref,
        )
        if isinstance(proposal_or_rejection, MemoryProposal):
            proposal = replace(
                proposal_or_rejection,
                rationale=str(reflection["rationale"]),
                metadata={
                    **dict(proposal_or_rejection.metadata),
                    "source_kind": "task_reflection",
                    "outcome": outcome,
                    "failure_reason": reflection["structured"].get("failure_reason"),
                    "next_possible_action": reflection["structured"].get("next_possible_action"),
                    "review_nonblocking": True,
                    **dict(metadata or {}),
                },
            )
            self.store.record_proposal(proposal)
            self._journal_memory_record(
                task_id=task_id,
                run_id=run_id,
                kind="memory_proposal",
                data=memory_proposal_event(proposal),
                state_delta={"memory_proposal": proposal.approval_status},
            )
            return MemoryPipelineResult(shadow_candidates=[candidate], proposals=[proposal], committed_items=[], rejected=[])
        return MemoryPipelineResult(
            shadow_candidates=[candidate],
            proposals=[],
            committed_items=[],
            rejected=[proposal_or_rejection],
        )

    def propose_from_answer_quality_check(
        self,
        *,
        root_goal: str,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
        answer_profile: JsonObject | None,
        gaps: list[str],
        attempt: str,
        prior_gaps: list[str] | None = None,
        answer_chars: int | None = None,
        citation_refs: list[str] | None = None,
        used_evidence: list[str] | None = None,
        metadata: JsonObject | None = None,
    ) -> MemoryPipelineResult:
        payload = _answer_quality_learning_payload(
            root_goal=root_goal,
            answer_profile=answer_profile,
            gaps=gaps,
            attempt=attempt,
            prior_gaps=prior_gaps,
            answer_chars=answer_chars,
            citation_refs=citation_refs,
            used_evidence=used_evidence,
            metadata=metadata,
        )
        text = str(payload.get("body") or "")
        if not text:
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[])
        if contains_secret_like_content(text):
            rejection = self._reject_secret(
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                text=text,
            )
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[rejection])
        candidate = ShadowCandidate(
            candidate_id=stable_candidate_id(
                {
                    "source_kind": "answer_quality_check",
                    "task_id": task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "source_record_ref": source_record_ref,
                    "text_hash": _hash_text(text),
                    "dedupe_key": payload["dedupe_key"],
                }
            ),
            source_kind="answer_quality_check",
            candidate_text=text,
            normalized_topic=str(payload["topic"]),
            required_capabilities=["durable_memory:write"],
            blocked_capabilities=[],
            status="open",
            expires_at_ms=None,
            created_at_ms=self._now_ms(),
            metadata={
                "source_record_ref": source_record_ref,
                "task_id": task_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "source_kind": "answer_quality_check",
                "memory_kind": "workflow_convention",
                "title": payload["title"],
                "summary": payload["summary"],
                "body": text,
                "dedupe_key": payload["dedupe_key"],
                "structured": payload["structured"],
                "confidence": payload["confidence"],
                "rationale": payload["rationale"],
                "review_nonblocking": True,
                **dict(metadata or {}),
            },
        )
        self.store.record_shadow_candidate(candidate)
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind="memory_shadow_candidate",
            data=shadow_candidate_event(candidate),
            state_delta={"memory_candidate": candidate.status},
        )
        proposal_or_rejection = self._proposal_from_candidate(
            candidate,
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            source_record_ref=source_record_ref,
        )
        if isinstance(proposal_or_rejection, MemoryProposal):
            proposal = replace(
                proposal_or_rejection,
                rationale=str(payload["rationale"]),
                metadata={
                    **dict(proposal_or_rejection.metadata),
                    "source_kind": "answer_quality_check",
                    "review_nonblocking": True,
                    "quality_gaps": _string_list(payload["structured"].get("gaps")),
                    "attempt": attempt,
                    **dict(metadata or {}),
                },
            )
            self.store.record_proposal(proposal)
            self._journal_memory_record(
                task_id=task_id,
                run_id=run_id,
                kind="memory_proposal",
                data=memory_proposal_event(proposal),
                state_delta={"memory_proposal": proposal.approval_status},
            )
            return MemoryPipelineResult(shadow_candidates=[candidate], proposals=[proposal], committed_items=[], rejected=[])
        return MemoryPipelineResult(
            shadow_candidates=[candidate],
            proposals=[],
            committed_items=[],
            rejected=[proposal_or_rejection],
        )

    def propose_thread_learning_digest(
        self,
        *,
        thread_id: str,
        task_id: str,
        run_id: str,
        source_record_ref: str | None = None,
        min_source_proposals: int = 2,
        max_source_proposals: int = 8,
    ) -> MemoryPipelineResult:
        source_proposals = _thread_learning_source_proposals(
            self.store.proposals(),
            thread_id=thread_id,
            limit=max_source_proposals,
        )
        if len(source_proposals) < max(1, min_source_proposals):
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[])
        digest = _thread_learning_digest_payload(source_proposals, thread_id=thread_id)
        text = str(digest.get("body") or "")
        if not text:
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[])
        if contains_secret_like_content(text):
            rejection = self._reject_secret(
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                text=text,
            )
            return MemoryPipelineResult(shadow_candidates=[], proposals=[], committed_items=[], rejected=[rejection])
        source_ids = _string_list(digest.get("source_proposal_ids"))
        candidate = ShadowCandidate(
            candidate_id=stable_candidate_id(
                {
                    "source_kind": "thread_learning_digest",
                    "task_id": task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "source_record_ref": source_record_ref,
                    "source_proposal_ids": source_ids,
                    "text_hash": _hash_text(text),
                }
            ),
            source_kind="thread_learning_digest",
            candidate_text=text,
            normalized_topic=str(digest["topic"]),
            required_capabilities=["durable_memory:write"],
            blocked_capabilities=[],
            status="open",
            expires_at_ms=None,
            created_at_ms=self._now_ms(),
            metadata={
                "source_record_ref": source_record_ref,
                "task_id": task_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "source_kind": "thread_learning_digest",
                "memory_kind": "thread_learning_digest",
                "title": digest["title"],
                "summary": digest["summary"],
                "body": text,
                "dedupe_key": digest["dedupe_key"],
                "structured": digest["structured"],
                "confidence": digest["confidence"],
                "rationale": digest["rationale"],
                "review_nonblocking": True,
                "source_proposal_ids": source_ids,
            },
        )
        self.store.record_shadow_candidate(candidate)
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind="memory_shadow_candidate",
            data=shadow_candidate_event(candidate),
            state_delta={"memory_candidate": candidate.status},
        )
        proposal_or_rejection = self._proposal_from_candidate(
            candidate,
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            source_record_ref=source_record_ref,
        )
        if isinstance(proposal_or_rejection, MemoryProposal):
            proposal = replace(
                proposal_or_rejection,
                rationale=str(digest["rationale"]),
                metadata={
                    **dict(proposal_or_rejection.metadata),
                    "source_kind": "thread_learning_digest",
                    "review_nonblocking": True,
                    "source_proposal_ids": source_ids,
                    "source_proposal_count": len(source_ids),
                },
            )
            self.store.record_proposal(proposal)
            self._journal_memory_record(
                task_id=task_id,
                run_id=run_id,
                kind="memory_proposal",
                data=memory_proposal_event(proposal),
                state_delta={"memory_proposal": proposal.approval_status},
            )
            return MemoryPipelineResult(shadow_candidates=[candidate], proposals=[proposal], committed_items=[], rejected=[])
        return MemoryPipelineResult(
            shadow_candidates=[candidate],
            proposals=[],
            committed_items=[],
            rejected=[proposal_or_rejection],
        )

    def approve_proposal(
        self,
        proposal_id: str,
        *,
        approved_by: str = "user",
        decided_at_ms: int | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> MemoryPipelineResult:
        proposal = self.store.proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal_id: {proposal_id}")
        if proposal.approval_policy in {"reject"}:
            raise ValueError(f"proposal_not_approvable:{proposal_id}")
        if proposal.approval_status == "approved":
            committed = self._committed_item_for_approved_proposal(
                proposal,
                approved_by=approved_by,
                decided_at_ms=decided_at_ms,
            )
            return MemoryPipelineResult(
                shadow_candidates=[],
                proposals=[proposal],
                committed_items=[committed],
                rejected=[],
            )
        if proposal.approval_status in {"rejected", "expired"}:
            raise ValueError(f"proposal_already_closed:{proposal_id}")
        timestamp = decided_at_ms if decided_at_ms is not None else self._now_ms()
        item = MemoryItem.from_dict(proposal.proposed_item)
        committed = replace(
            item,
            approved_by=approved_by,
            state="active",
            updated_at_ms=timestamp,
        )
        decided = self.store.decide_proposal(
            proposal_id,
            approval_status="approved",
            decided_at_ms=timestamp,
            metadata={"approved_by": approved_by},
        )
        committed = self.store.commit(committed)
        self._journal_memory_record(
            task_id=task_id or decided.source_task_id,
            run_id=run_id or decided.source_run_id or "",
            kind="memory_proposal_approved",
            data=memory_proposal_event(decided),
            state_delta={"memory_proposal": "approved"},
        )
        self._journal_memory_record(
            task_id=task_id or decided.source_task_id,
            run_id=run_id or decided.source_run_id or "",
            kind="memory_item_committed",
            data=memory_item_event(committed),
            state_delta={"memory_item": "committed"},
        )
        return MemoryPipelineResult(
            shadow_candidates=[],
            proposals=[decided],
            committed_items=[committed],
            rejected=[],
        )

    def _committed_item_for_approved_proposal(
        self,
        proposal: MemoryProposal,
        *,
        approved_by: str,
        decided_at_ms: int | None,
    ) -> MemoryItem:
        memory_id = str(proposal.proposed_item.get("memory_id") or "")
        existing = self.store.get(memory_id, include_inactive=True) if memory_id else None
        if existing is not None:
            return existing
        if decided_at_ms is not None:
            timestamp = decided_at_ms
        elif proposal.decided_at_ms is not None:
            timestamp = proposal.decided_at_ms
        else:
            timestamp = self._now_ms()
        item = MemoryItem.from_dict(proposal.proposed_item)
        committed = replace(
            item,
            approved_by=approved_by,
            state="active",
            updated_at_ms=timestamp,
        )
        committed = self.store.commit(committed)
        self._journal_memory_record(
            task_id=proposal.source_task_id,
            run_id=proposal.source_run_id or "",
            kind="memory_item_committed",
            data=memory_item_event(committed),
            state_delta={"memory_item": "committed_recovered"},
        )
        return committed

    def reject_proposal(
        self,
        proposal_id: str,
        *,
        reason: str,
        decided_at_ms: int | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> MemoryPipelineResult:
        proposal = self.store.proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal_id: {proposal_id}")
        if proposal.approval_status == "approved":
            raise ValueError(f"proposal_already_approved:{proposal_id}")
        if proposal.approval_status == "rejected":
            return MemoryPipelineResult(
                shadow_candidates=[],
                proposals=[proposal],
                committed_items=[],
                rejected=[{"proposal_id": proposal_id, "reason": reason}],
            )
        decided = self.store.decide_proposal(
            proposal_id,
            approval_status="rejected",
            decided_at_ms=decided_at_ms if decided_at_ms is not None else self._now_ms(),
            metadata={"rejection_reason": reason},
        )
        self._journal_memory_record(
            task_id=task_id or decided.source_task_id,
            run_id=run_id or decided.source_run_id or "",
            kind="memory_proposal_rejected",
            data=memory_proposal_event(decided),
            state_delta={"memory_proposal": "rejected", "reason_hash": _hash_text(reason)},
        )
        return MemoryPipelineResult(
            shadow_candidates=[],
            proposals=[decided],
            committed_items=[],
            rejected=[{"proposal_id": proposal_id, "reason": reason}],
        )

    def delete_memory(
        self,
        memory_id: str,
        *,
        reason: str,
        deleted_by: str = "user",
        deleted_at_ms: int | None = None,
        task_id: str | None = None,
        run_id: str = "",
    ) -> MemoryTombstone:
        existing = _existing_tombstone(self.store, memory_id)
        tombstone = self.store.delete(
            memory_id,
            reason=reason,
            deleted_by=deleted_by,
            deleted_at_ms=deleted_at_ms,
            metadata={"source": "memory_pipeline", "already_deleted": existing is not None},
        )
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind="memory_item_delete_observed" if existing is not None else "memory_item_deleted",
            data=memory_tombstone_event(tombstone),
            state_delta={
                "memory_item": "deleted_existing" if existing is not None else "deleted",
                "memory_id": memory_id,
                "reason_hash": _hash_text(reason),
            },
        )
        return tombstone

    def _candidate_from_intent(
        self,
        intent: JsonObject,
        *,
        intake: SemanticIntake,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> ShadowCandidate:
        text = str(intent.get("text") or intake.goal)
        topic = _normalized_topic(text)
        payload = {
            "task_id": task_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "source_record_ref": source_record_ref,
            "text_hash": _hash_text(text),
            "topic": topic,
        }
        return ShadowCandidate(
            candidate_id=stable_candidate_id(payload),
            source_kind="semantic_intake",
            candidate_text=text,
            normalized_topic=topic,
            required_capabilities=_string_list(intent.get("required_capabilities")),
            blocked_capabilities=list(intake.blocked_capabilities),
            status="open",
            expires_at_ms=None,
            created_at_ms=self._now_ms(),
            metadata={
                "source_record_ref": source_record_ref,
                "intent_kind": str(intent.get("kind") or ""),
                "task_id": task_id,
                "run_id": run_id,
                "thread_id": thread_id,
            },
        )

    def _proposal_from_candidate(
        self,
        candidate: ShadowCandidate,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> MemoryProposal | JsonObject:
        item = self._draft_item(candidate, task_id=task_id, run_id=run_id, thread_id=thread_id, source_record_ref=source_record_ref)
        decision = validate_memory_item(item)
        if not decision.allowed:
            return self._journal_rejection(
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                reason=decision.reason,
                text_hash=_hash_text(candidate.candidate_text),
                risk_flags=decision.risk_flags,
            )
        existing = [
            memory
            for memory in self.store.list_items(scope=item.scope)
            if memory.dedupe_key == item.dedupe_key
        ]
        risk_flags = list(decision.risk_flags)
        approval_policy = "needs_review"
        if any(memory.summary != item.summary or memory.body != item.body for memory in existing):
            risk_flags.append("conflicts_existing")
            approval_policy = "conflict_review"
        proposal_payload = {
            "candidate_id": candidate.candidate_id,
            "operation": "upsert",
            "memory_id": item.memory_id,
            "source_record_ref": source_record_ref,
        }
        return MemoryProposal(
            proposal_id=stable_proposal_id(proposal_payload),
            candidate_id=candidate.candidate_id,
            operation="upsert",
            proposed_item=item.to_dict(),
            rationale=str(candidate.metadata.get("rationale") or "explicit durable memory intent"),
            source_task_id=task_id,
            source_run_id=run_id,
            source_thread_id=thread_id,
            evidence_record_refs=[source_record_ref] if source_record_ref else [],
            artifact_refs=[],
            risk_flags=_ordered_unique(risk_flags),
            approval_policy=approval_policy,
            approval_status="pending",
            confidence=item.confidence,
            created_at_ms=self._now_ms(),
            decided_at_ms=None,
            metadata={"existing_memory_ids": [memory.memory_id for memory in existing]},
        )

    def _draft_item(
        self,
        candidate: ShadowCandidate,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> MemoryItem:
        metadata = dict(candidate.metadata)
        summary = str(metadata.get("summary") or _memory_summary(candidate.candidate_text))[:240]
        body = str(metadata.get("body") or candidate.candidate_text)
        kind = str(metadata.get("memory_kind") or _memory_kind(candidate.candidate_text))
        title = str(metadata.get("title") or _memory_title(candidate.candidate_text))[:120]
        scope = {"user_id": self.user_id, "project_id": self.project_id, "thread_id": thread_id}
        dedupe_key = str(metadata.get("dedupe_key") or f"{kind}:{candidate.normalized_topic}")
        timestamp = self._now_ms()
        structured = {"source": candidate.source_kind, "topic": candidate.normalized_topic}
        if isinstance(metadata.get("structured"), dict):
            structured.update(dict(metadata["structured"]))
        return MemoryItem(
            memory_id=stable_memory_id(kind=kind, scope=scope, dedupe_key=dedupe_key, summary=summary),
            kind=kind,
            title=title,
            summary=summary,
            body=body,
            structured=structured,
            scope=scope,
            privacy_class=str(metadata.get("privacy_class") or "project_internal"),
            confidence=_confidence(metadata.get("confidence"), default=0.85),
            ttl_policy=str(metadata.get("ttl_policy") or "forever"),
            expires_at_ms=metadata.get("expires_at_ms") if isinstance(metadata.get("expires_at_ms"), int) else None,
            dedupe_key=dedupe_key,
            conflict_keys=[dedupe_key],
            provenance_refs=[source_record_ref] if source_record_ref else [],
            artifact_refs=[],
            state="pending",
            approved_by=None,
            created_at_ms=timestamp,
            updated_at_ms=timestamp,
            last_accessed_ms=None,
            metadata={
                "source_task_id": task_id,
                "source_run_id": run_id,
                "source_kind": candidate.source_kind,
                "review_nonblocking": metadata.get("review_nonblocking") is True,
            },
        )

    def _reject_secret(
        self,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
        text: str,
    ) -> JsonObject:
        return self._journal_rejection(
            task_id=task_id,
            run_id=run_id,
            thread_id=thread_id,
            source_record_ref=source_record_ref,
            reason="memory_rejected_secret_like_content",
            text_hash=_hash_text(text),
            risk_flags=["contains_secret_like_content"],
        )

    def _journal_rejection(
        self,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
        reason: str,
        text_hash: str,
        risk_flags: list[str],
    ) -> JsonObject:
        data = {
            "reason": reason,
            "thread_id": thread_id,
            "source_record_ref": source_record_ref,
            "candidate_text_hash": text_hash,
            "risk_flags": list(risk_flags),
            "redaction": {"candidate_text": "hash_only"},
        }
        self._journal_memory_record(
            task_id=task_id,
            run_id=run_id,
            kind=reason,
            data=data,
            state_delta={"memory_proposal": "rejected", "reason": reason},
        )
        return data

    def _journal_memory_record(
        self,
        *,
        task_id: str | None,
        run_id: str,
        kind: str,
        data: JsonObject,
        state_delta: JsonObject,
    ) -> None:
        if self.journal is None:
            return
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind=kind,
            data=data,
            state_delta=state_delta,
        )

    def _now_ms(self) -> int:
        return int(self.clock_ms())


def _memory_intents(intake: "SemanticIntake") -> list[JsonObject]:
    result = []
    for intent in intake.intents:
        if not isinstance(intent, dict):
            continue
        capabilities = _string_list(intent.get("required_capabilities"))
        kind = str(intent.get("kind") or "")
        if "durable_memory:write" in capabilities or kind == "memory_write":
            result.append(dict(intent))
    return result


def _memory_kind(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("preference", "prefer", "偏好", "喜欢", "希望", "以后")):
        return "user_preference"
    return "project_fact"


def _memory_title(text: str) -> str:
    summary = _memory_summary(text)
    return summary[:60] or "Durable memory"


def _memory_summary(text: str) -> str:
    stripped = " ".join(text.split())
    stripped = re.sub(r"^(?:请|帮我|please\s+)?(?:记住|记下|保存|remember|save)\s*", "", stripped, flags=re.IGNORECASE)
    return stripped[:240] or "Durable memory candidate"


def _normalized_topic(text: str) -> str:
    summary = _memory_summary(text).lower()
    if re.search(r"(?:回复|回答|短答|长答|中文|英文|response|answer|concise|verbose|language)", summary, re.IGNORECASE):
        return "response-style"
    words = re.findall(r"[\w\u4e00-\u9fff]+", summary)
    return "-".join(words[:12]) or "memory"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _existing_tombstone(store: MemoryStore, memory_id: str) -> MemoryTombstone | None:
    for tombstone in store.tombstones():
        if tombstone.memory_id == memory_id:
            return tombstone
    return None


def _research_result_payload(*, answer_text: str, metadata: JsonObject | None) -> JsonObject:
    metadata = dict(metadata or {})
    research_mission = metadata.get("research_mission") if isinstance(metadata.get("research_mission"), dict) else {}
    answer_profile = metadata.get("answer_profile") if isinstance(metadata.get("answer_profile"), dict) else {}
    citation_refs = _string_list(metadata.get("citation_refs"))[:16]
    used_evidence = _string_list(metadata.get("used_evidence"))[:16]
    root_goal = _research_goal_from_metadata(research_mission) or _preview_text(answer_text, 160)
    topic = "research-note-" + _hash_text(root_goal.lower())[:16]
    summary = _research_summary(answer_text)
    findings = _extract_research_findings(answer_text, limit=8)
    limitations = _extract_research_limitations(answer_text, limit=6)
    body = _research_note_body(
        root_goal=root_goal,
        summary=summary,
        findings=findings,
        limitations=limitations,
        citation_refs=citation_refs,
        used_evidence=used_evidence,
    )
    structured = {
        "source": "research_final_answer",
        "topic": topic,
        "root_goal_preview": _preview_text(root_goal, 320),
        "answer_chars": len(answer_text),
        "profile_format": answer_profile.get("format"),
        "detail_level": answer_profile.get("detail_level"),
        "citation_refs": citation_refs,
        "used_evidence": used_evidence,
        "limitations": limitations,
    }
    return {
        "topic": topic,
        "title": _preview_text(f"Research note: {root_goal}", 120),
        "summary": _preview_text(summary, 240),
        "body": body,
        "dedupe_key": f"research_note:{topic}",
        "structured": structured,
        "confidence": _confidence(metadata.get("confidence"), default=0.82),
        "rationale": "research final answer distilled into a compact reviewable durable research note",
    }


def _answer_quality_learning_payload(
    *,
    root_goal: str,
    answer_profile: JsonObject | None,
    gaps: list[str],
    attempt: str,
    prior_gaps: list[str] | None,
    answer_chars: int | None,
    citation_refs: list[str] | None,
    used_evidence: list[str] | None,
    metadata: JsonObject | None,
) -> JsonObject:
    gap_list = _ordered_unique([str(item) for item in gaps if str(item).strip()])
    if not gap_list:
        return {}
    profile = dict(answer_profile or {})
    profile_format = str(profile.get("format") or "answer")
    detail_level = str(profile.get("detail_level") or "")
    target_sections = _string_list(profile.get("target_sections"))[:12]
    coverage = _string_list(profile.get("minimum_coverage"))[:12]
    citation_list = _string_list(citation_refs)[:16]
    evidence_list = _string_list(used_evidence)[:16]
    goal_preview = _preview_text(root_goal, 320)
    topic_seed = {
        "goal_hash": _hash_text(root_goal)[:12],
        "profile_format": profile_format,
        "detail_level": detail_level,
        "gaps": gap_list,
        "attempt": attempt,
        "metadata_kind": (metadata or {}).get("reflection_kind") if isinstance(metadata, dict) else None,
    }
    topic = "answer-quality-" + _hash_text(str(topic_seed))[:16]
    next_action = "repair final answer to satisfy the declared answer_profile before returning it to the user"
    body_lines = [
        "Holo answer quality learning signal.",
        f"Goal: {goal_preview}" if goal_preview else "",
        f"Profile: format={profile_format}, detail={detail_level}.",
        f"Attempt: {attempt}.",
        f"Observed gaps: {', '.join(gap_list)}.",
        f"Prior gaps: {', '.join(_string_list(prior_gaps)[:12])}." if prior_gaps else "",
        f"Answer chars: {answer_chars}." if isinstance(answer_chars, int) else "",
        f"Target sections: {', '.join(target_sections)}." if target_sections else "",
        f"Minimum coverage: {', '.join(coverage)}." if coverage else "",
        f"Citation refs present: {len(citation_list)}.",
        f"Evidence refs present: {len(evidence_list)}.",
        f"Reusable lesson: {next_action}.",
    ]
    summary = _preview_text(
        f"Answer quality gap for {profile_format}: {', '.join(gap_list)}; goal={goal_preview}",
        240,
    )
    structured = {
        "source": "answer_quality_check",
        "profile_format": profile_format,
        "detail_level": detail_level,
        "gaps": gap_list,
        "prior_gaps": _string_list(prior_gaps)[:12],
        "attempt": attempt,
        "answer_chars": answer_chars if isinstance(answer_chars, int) else None,
        "target_sections": target_sections,
        "minimum_coverage": coverage,
        "citation_refs": citation_list,
        "used_evidence": evidence_list,
        "next_possible_action": next_action,
    }
    return {
        "topic": topic,
        "title": _preview_text(f"Answer quality learning: {profile_format}", 120),
        "summary": summary,
        "body": _preview_text("\n".join(item for item in body_lines if item), 2_400),
        "dedupe_key": f"answer_quality:{topic}",
        "structured": structured,
        "confidence": 0.74,
        "rationale": "host-derived answer quality gap; keep pending for review before durable memory commit",
    }


def _thread_learning_source_proposals(
    proposals: list[MemoryProposal],
    *,
    thread_id: str,
    limit: int,
) -> list[MemoryProposal]:
    selected: list[MemoryProposal] = []
    for proposal in proposals:
        if proposal.source_thread_id != thread_id:
            continue
        if proposal.approval_status != "pending":
            continue
        if proposal.metadata.get("review_nonblocking") is not True:
            continue
        if proposal.metadata.get("source_kind") == "thread_learning_digest":
            continue
        selected.append(proposal)
    return selected[-max(1, limit) :]


def _thread_learning_digest_payload(proposals: list[MemoryProposal], *, thread_id: str) -> JsonObject:
    source_ids = [proposal.proposal_id for proposal in proposals]
    entries = [_learning_entry_from_proposal(proposal) for proposal in proposals]
    summaries = [entry["summary"] for entry in entries if entry.get("summary")]
    next_actions = _ordered_unique(
        [
            str(entry.get("next_possible_action"))
            for entry in entries
            if isinstance(entry.get("next_possible_action"), str) and entry.get("next_possible_action")
        ]
    )
    source_kinds = _ordered_unique(
        [
            str(entry.get("source_kind"))
            for entry in entries
            if isinstance(entry.get("source_kind"), str) and entry.get("source_kind")
        ]
    )
    topic = "thread-learning-" + _hash_text(thread_id + ":" + "|".join(source_ids))[:16]
    summary = _preview_text(
        "Thread learning digest: " + "; ".join(summaries[:4]),
        240,
    )
    lines = [
        "Holo thread learning digest.",
        f"Thread: {thread_id}",
        f"Source proposals: {', '.join(source_ids)}",
        f"Source kinds: {', '.join(source_kinds)}" if source_kinds else "",
        "Observed learning signals:",
        *[f"- {entry['summary']}" for entry in entries if entry.get("summary")],
    ]
    if next_actions:
        lines.extend(["Potential next actions:", *[f"- {item}" for item in next_actions[:6]]])
    body = _preview_text("\n".join(item for item in lines if item), 2_400)
    structured = {
        "source": "thread_learning_digest",
        "thread_id": thread_id,
        "source_proposal_ids": source_ids,
        "source_kinds": source_kinds,
        "next_possible_actions": next_actions[:8],
        "entry_count": len(entries),
        "entries": entries[:8],
    }
    return {
        "topic": topic,
        "title": _preview_text(f"Thread learning digest: {thread_id}", 120),
        "summary": summary,
        "body": body,
        "dedupe_key": f"thread_learning_digest:{topic}",
        "structured": structured,
        "confidence": min(0.9, 0.65 + len(entries) * 0.04),
        "rationale": "host-consolidated thread learning proposal assembled from pending nonblocking memory proposals",
        "source_proposal_ids": source_ids,
    }


def _learning_entry_from_proposal(proposal: MemoryProposal) -> JsonObject:
    proposed = proposal.proposed_item if isinstance(proposal.proposed_item, dict) else {}
    structured = proposed.get("structured") if isinstance(proposed.get("structured"), dict) else {}
    summary = str(proposed.get("summary") or "")
    return {
        "proposal_id": proposal.proposal_id,
        "memory_id": proposed.get("memory_id"),
        "kind": proposed.get("kind"),
        "source_kind": proposal.metadata.get("source_kind") or proposed.get("kind"),
        "summary": _preview_text(summary, 260),
        "failure_reason": structured.get("failure_reason"),
        "next_possible_action": structured.get("next_possible_action") or proposal.metadata.get("next_possible_action"),
        "quality_gaps": _string_list(structured.get("gaps"))[:12] or _string_list(proposal.metadata.get("quality_gaps"))[:12],
        "citation_refs": _string_list(structured.get("citation_refs"))[:8],
        "used_evidence": _string_list(structured.get("used_evidence"))[:8],
    }


def _research_goal_from_metadata(research_mission: JsonObject) -> str:
    for key in ("root_goal", "goal", "user_goal", "query", "topic"):
        value = research_mission.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _research_summary(text: str) -> str:
    lines = [_clean_markdown_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line and not _looks_like_heading(line)]
    if not lines:
        return _preview_text(text, 360)
    return _preview_text(" ".join(lines[:3]), 360)


def _extract_research_findings(text: str, *, limit: int) -> list[str]:
    findings: list[str] = []
    for raw in text.splitlines():
        line = _clean_markdown_line(raw)
        if not line or _looks_like_heading(line):
            continue
        if _looks_like_limitation(line):
            continue
        if _looks_like_finding(line):
            findings.append(_preview_text(line, 260))
        elif len(findings) < max(2, limit // 2) and len(line) >= 32:
            findings.append(_preview_text(line, 260))
        if len(_ordered_unique(findings)) >= limit:
            break
    return _ordered_unique(findings)[:limit]


def _extract_research_limitations(text: str, *, limit: int) -> list[str]:
    limitations: list[str] = []
    in_limitation_section = False
    for raw in text.splitlines():
        line = _clean_markdown_line(raw)
        if not line:
            continue
        if _looks_like_limitation(line):
            in_limitation_section = True
            if not _looks_like_heading(line):
                limitations.append(_preview_text(line, 240))
            continue
        if in_limitation_section:
            if _looks_like_heading(line):
                in_limitation_section = False
                continue
            limitations.append(_preview_text(line, 240))
        if len(_ordered_unique(limitations)) >= limit:
            break
    return _ordered_unique(limitations)[:limit]


def _research_note_body(
    *,
    root_goal: str,
    summary: str,
    findings: list[str],
    limitations: list[str],
    citation_refs: list[str],
    used_evidence: list[str],
) -> str:
    lines = [
        "Holo research memory note.",
        f"Goal: {_preview_text(root_goal, 320)}",
        f"Summary: {_preview_text(summary, 480)}",
    ]
    if findings:
        lines.append("Key findings:")
        lines.extend(f"- {item}" for item in findings[:8])
    if limitations:
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in limitations[:6])
    if citation_refs:
        lines.append("Citation refs: " + ", ".join(citation_refs[:16]))
    if used_evidence:
        lines.append("Evidence refs: " + ", ".join(used_evidence[:16]))
    return _preview_text("\n".join(lines), 2_400)


def _clean_markdown_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+[.)]\s+", "", text)
    text = text.strip("# ").strip()
    text = text.replace("**", "").replace("__", "")
    return " ".join(text.split())


def _looks_like_heading(line: str) -> bool:
    return len(line) <= 80 and not line.endswith(("。", ".", "；", ";", "：", ":")) and len(line.split()) <= 8


def _looks_like_finding(line: str) -> bool:
    lowered = line.lower()
    return any(char.isdigit() for char in line) or "cite-" in lowered or "evidence-" in lowered or len(line) >= 72


def _looks_like_limitation(line: str) -> bool:
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in (
            "limitation",
            "limitations",
            "missing",
            "not available",
            "insufficient",
            "局限",
            "缺失",
            "不足",
            "未提供",
            "无法",
        )
    )


def _task_reflection_payload(
    *,
    root_goal: str,
    outcome: str,
    failure_report: JsonObject | None,
    final_answer: JsonObject | None,
    host_situation: JsonObject | None,
    metadata: JsonObject | None,
) -> JsonObject:
    failure = failure_report if isinstance(failure_report, dict) else {}
    final = final_answer if isinstance(final_answer, dict) else {}
    host = host_situation if isinstance(host_situation, dict) else {}
    host_failure = host.get("failure") if isinstance(host.get("failure"), dict) else {}
    reason = str(failure.get("reason") or host_failure.get("reason") or outcome)
    next_action = str(failure.get("next_possible_action") or host_failure.get("next_possible_action") or "")
    attempted_actions = _string_list(failure.get("attempted_actions"))[:10]
    attempted_sources = _string_list(failure.get("attempted_sources"))[:10]
    missing_evidence = _string_list(failure.get("missing_evidence"))[:12]
    limitations = _string_list(final.get("limitations"))[:8]
    goal_preview = _memory_summary(root_goal)[:320]
    structured = {
        "source": "task_reflection",
        "outcome": outcome,
        "failure_reason": reason if failure else None,
        "next_possible_action": next_action or None,
        "attempted_actions": attempted_actions,
        "attempted_sources": attempted_sources,
        "missing_evidence": missing_evidence,
        "limitations": limitations,
        "host_failure_diagnosis": host_failure.get("diagnosis"),
        "host_retrieval_available": _host_retrieval_available(host),
    }
    text = "\n".join(
        item
        for item in [
            "Holo task reflection.",
            f"Goal: {goal_preview}" if goal_preview else "",
            f"Outcome: {outcome}.",
            f"Failure reason: {reason}." if failure else "",
            f"Attempted actions: {', '.join(attempted_actions)}." if attempted_actions else "",
            f"Attempted sources: {', '.join(attempted_sources)}." if attempted_sources else "",
            f"Missing evidence: {', '.join(missing_evidence)}." if missing_evidence else "",
            f"Next possible action: {next_action}." if next_action else "",
            (
                "Reusable lesson: when a similar task recurs, inspect prior failure mode and choose a materially "
                "different acquisition, tool, source, or synthesis strategy before repeating the same action."
            ),
        ]
        if item
    )
    topic_seed = {
        "goal_hash": _hash_text(root_goal)[:12],
        "outcome": outcome,
        "reason": reason,
        "next_action": next_action,
        "metadata_kind": (metadata or {}).get("reflection_kind") if isinstance(metadata, dict) else None,
    }
    topic = "task-reflection-" + _hash_text(str(topic_seed))[:16]
    return {
        "topic": topic,
        "title": _preview_text(f"Task reflection: {reason}", 120),
        "summary": _preview_text(f"{outcome}: {goal_preview}; reason={reason}; next={next_action}", 240),
        "body": text,
        "dedupe_key": f"task_reflection:{topic}",
        "structured": structured,
        "confidence": 0.72 if failure else 0.78,
        "rationale": "host-derived task reflection; keep pending for review before durable memory commit",
    }


def _host_retrieval_available(host: JsonObject) -> bool | None:
    runtime = host.get("runtime_capabilities") if isinstance(host.get("runtime_capabilities"), dict) else {}
    retrieval = runtime.get("retrieval") if isinstance(runtime.get("retrieval"), dict) else {}
    value = retrieval.get("available_if_routed")
    return value if isinstance(value, bool) else None


def _confidence(value: object, *, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(0.0, min(1.0, result))


def _preview_text(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
