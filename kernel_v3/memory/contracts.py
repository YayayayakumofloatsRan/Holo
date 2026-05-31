from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


class MemoryPrivacyError(ValueError):
    """Raised when a durable memory write violates privacy rules."""


@dataclass(frozen=True, kw_only=True)
class ProvenanceRef(Contract):
    provenance_id: str
    record_ref: str
    artifact_ref: str | None
    citation_quote: str | None
    source_hash: str
    source_kind: str
    created_at_ms: int


@dataclass(frozen=True, kw_only=True)
class MemoryItem(Contract):
    memory_id: str
    kind: str
    title: str
    summary: str
    body: str
    structured: JsonObject
    scope: JsonObject
    privacy_class: str
    confidence: float
    ttl_policy: str
    expires_at_ms: int | None
    dedupe_key: str
    conflict_keys: list[str]
    provenance_refs: list[str]
    artifact_refs: list[str]
    state: str
    approved_by: str | None
    created_at_ms: int
    updated_at_ms: int
    last_accessed_ms: int | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MemoryProposal(Contract):
    proposal_id: str
    candidate_id: str | None
    operation: str
    proposed_item: JsonObject
    rationale: str
    source_task_id: str | None
    source_run_id: str | None
    source_thread_id: str | None
    evidence_record_refs: list[str]
    artifact_refs: list[str]
    risk_flags: list[str]
    approval_policy: str
    approval_status: str
    confidence: float
    created_at_ms: int
    decided_at_ms: int | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ShadowCandidate(Contract):
    candidate_id: str
    source_kind: str
    candidate_text: str
    normalized_topic: str
    required_capabilities: list[str]
    blocked_capabilities: list[str]
    status: str
    expires_at_ms: int | None
    created_at_ms: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MemoryTombstone(Contract):
    tombstone_id: str
    memory_id: str
    reason: str
    deleted_by: str
    deleted_at_ms: int
    provenance_refs: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MemoryRecallResult(Contract):
    query: str | None
    scope: JsonObject
    items: list[JsonObject]
    total: int
    filtered: JsonObject
    generated_at_ms: int


@dataclass(frozen=True, kw_only=True)
class MemoryInspection(Contract):
    status: str
    active_count: int
    expired_count: int
    deleted_count: int
    sensitive_count: int
    proposal_counts: JsonObject
    shadow_candidate_count: int
    tombstone_count: int
    audit_record_count: int
    samples: JsonObject
    recommended_actions: list[str]
    generated_at_ms: int
