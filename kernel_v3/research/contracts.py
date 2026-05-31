from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class ResearchProfile(Contract):
    profile_id: str
    domain: str
    description: str
    primary_source_families: list[str]
    secondary_source_families: list[str]
    weak_source_families: list[str]
    minimum_primary_authority_score: float
    citations_required: bool
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SourceAssessment(Contract):
    assessment_id: str
    profile_id: str
    source_id: str
    uri: str
    source_family: str
    authority_level: str
    authority_score: float
    usable_as_primary: bool
    reasons: list[str]
    warnings: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CorpusDocument(Contract):
    document_id: str
    uri: str
    title: str
    source_id: str
    provider: str
    artifact_id: str
    payload_hash: str
    preview: str
    mime_type: str
    size_bytes: int
    fetched_at_ms: int
    task_id: str | None
    run_id: str
    goal_id: str
    research_profile_id: str | None
    source_assessment: JsonObject | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CorpusSearchResult(Contract):
    query: str | None
    profile_id: str | None
    documents: list[JsonObject]
    total: int
    generated_at_ms: int


@dataclass(frozen=True, kw_only=True)
class CorpusStatus(Contract):
    generated_at_ms: int
    log_path: str | None
    index_path: str | None
    document_count: int
    total_size_bytes: int
    profile_counts: dict[str, int]
    provider_counts: dict[str, int]
    source_family_counts: dict[str, int]
    authority_level_counts: dict[str, int]
    primary_usable_count: int
    audit_record_count: int
    latest_fetched_at_ms: int | None


@dataclass(frozen=True, kw_only=True)
class CorpusInspection(Contract):
    status: str
    generated_at_ms: int
    issues: list[JsonObject]
    recommended_actions: list[str]
    corpus_status: JsonObject
    artifact_consistency: JsonObject = field(default_factory=dict)
    samples: JsonObject = field(default_factory=dict)
