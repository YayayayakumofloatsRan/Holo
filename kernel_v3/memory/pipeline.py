from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore
from kernel_v3.memory.contracts import MemoryItem, MemoryProposal, ShadowCandidate
from kernel_v3.memory.privacy import contains_secret_like_content, validate_memory_item
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
                data=candidate.to_dict(),
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
                    data=proposal_or_rejection.to_dict(),
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
            data=decided.to_dict(),
            state_delta={"memory_proposal": "approved"},
        )
        self._journal_memory_record(
            task_id=task_id or decided.source_task_id,
            run_id=run_id or decided.source_run_id or "",
            kind="memory_item_committed",
            data=committed.to_dict(),
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
            data=committed.to_dict(),
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
            data=decided.to_dict(),
            state_delta={"memory_proposal": "rejected", "reason": reason},
        )
        return MemoryPipelineResult(
            shadow_candidates=[],
            proposals=[decided],
            committed_items=[],
            rejected=[{"proposal_id": proposal_id, "reason": reason}],
        )

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
            rationale="explicit durable memory intent",
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
        summary = _memory_summary(candidate.candidate_text)
        scope = {"user_id": self.user_id, "project_id": self.project_id, "thread_id": thread_id}
        dedupe_key = f"{_memory_kind(candidate.candidate_text)}:{candidate.normalized_topic}"
        timestamp = self._now_ms()
        return MemoryItem(
            memory_id=stable_memory_id(kind=_memory_kind(candidate.candidate_text), scope=scope, dedupe_key=dedupe_key, summary=summary),
            kind=_memory_kind(candidate.candidate_text),
            title=_memory_title(candidate.candidate_text),
            summary=summary,
            body=candidate.candidate_text,
            structured={"source": "semantic_intake", "topic": candidate.normalized_topic},
            scope=scope,
            privacy_class="project_internal",
            confidence=0.85,
            ttl_policy="forever",
            expires_at_ms=None,
            dedupe_key=dedupe_key,
            conflict_keys=[dedupe_key],
            provenance_refs=[source_record_ref] if source_record_ref else [],
            artifact_refs=[],
            state="pending",
            approved_by=None,
            created_at_ms=timestamp,
            updated_at_ms=timestamp,
            last_accessed_ms=None,
            metadata={"source_task_id": task_id, "source_run_id": run_id},
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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
