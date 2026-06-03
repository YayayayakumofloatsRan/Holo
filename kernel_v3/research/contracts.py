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
class ResearchMission(Contract):
    mission_id: str
    root_goal: str
    domain: str
    target_entities: list[str]
    requirements: list[JsonObject]
    answer_profile: JsonObject
    status: str
    coverage_map: JsonObject = field(default_factory=dict)
    open_gaps: list[str] = field(default_factory=list)
    attempted_strategies: list[str] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResearchPlan(Contract):
    plan_id: str
    mission_id: str
    subgoals: list[JsonObject]
    source_strategy: JsonObject
    query_strategy: JsonObject
    verification_strategy: JsonObject
    write_targets: list[JsonObject] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CoverageAssessment(Contract):
    assessment_id: str
    mission_id: str
    coverage_score: float
    covered_requirements: list[str]
    missing_requirements: list[str]
    bad_sources: list[JsonObject]
    unsupported_claims: list[str]
    next_strategy: JsonObject | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResearchSourceEntry(Contract):
    source_id: str
    profile_id: str
    title: str
    source_family: str
    authority_level: str
    base_url: str
    allowed_hosts: list[str]
    use_cases: list[str]
    required_identifiers: list[str]
    query_hints: list[str]
    crawl_notes: list[str]
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
