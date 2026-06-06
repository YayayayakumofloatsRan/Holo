from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class SearchGoal(Contract):
    goal_id: str
    query: str
    max_queries: int = 1
    max_sources: int = 5
    max_fetches: int = 3
    max_spans_per_document: int = 2
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class QueryPlan(Contract):
    plan_id: str
    goal_id: str
    queries: list[str]
    max_sources: int
    max_fetches: int
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SearchSource(Contract):
    source_id: str
    uri: str
    title: str
    snippet: str
    provider: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RetrievalNextAction(Contract):
    action_id: str
    action: str
    tool_hint: str
    source_id: str | None = None
    uri: str | None = None
    reason: str
    payload_hint: JsonObject = field(default_factory=dict)
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class DiscoveryExpansion(Contract):
    expansion_id: str
    goal_id: str
    source_id: str
    uri: str
    status: str
    candidate_sources: list[JsonObject]
    next_tool_actions: list[JsonObject]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ResearchGraph(Contract):
    graph_id: str
    goal_id: str
    nodes: list[JsonObject]
    edges: list[JsonObject]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RetrievalProviderCapability(Contract):
    provider_id: str
    provider_kind: str
    live_network: bool
    default_enabled: bool
    profile_aware: bool
    supported_research_profiles: list[str]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RetrievalProviderInspection(Contract):
    status: str
    generated_at_ms: int
    network_access: bool
    provider_capabilities: list[JsonObject]
    issues: list[JsonObject]
    recommended_actions: list[str]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SearchAttempt(Contract):
    attempt_id: str
    goal_id: str
    plan_id: str
    query: str
    status: str
    sources: list[JsonObject]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RankedSource(Contract):
    source_id: str
    uri: str
    title: str
    snippet: str
    provider: str
    score: float
    rank: int
    reasons: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RankSources(Contract):
    ranking_id: str
    goal_id: str
    ranked_sources: list[JsonObject]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FetchAttempt(Contract):
    fetch_id: str
    goal_id: str
    source_id: str
    uri: str
    status: str
    artifact_id: str | None
    payload_hash: str | None
    preview: str
    size_bytes: int
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FetchedDocument(Contract):
    document_id: str
    goal_id: str
    source_id: str
    uri: str
    title: str
    artifact_id: str
    payload_hash: str
    preview: str
    size_bytes: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ExtractedSpan(Contract):
    span_id: str
    goal_id: str
    document_id: str
    source_id: str
    text: str
    start_offset: int
    end_offset: int
    score: float
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class EvidenceItem(Contract):
    evidence_id: str
    goal_id: str
    span_id: str
    document_id: str
    source_id: str
    artifact_id: str
    uri: str
    title: str
    text: str
    score: float
    payload_hash: str
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CitationItem(Contract):
    citation_id: str
    goal_id: str
    evidence_id: str
    artifact_id: str
    uri: str
    title: str
    quote: str
    span_start: int
    span_end: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class EvidenceEvaluationDecision(Contract):
    decision_id: str
    goal_id: str
    status: str
    sufficient: bool
    reason: str
    evidence_count: int
    citation_count: int
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RetrievalReport(Contract):
    report_id: str
    goal_id: str
    status: str
    query_plan_id: str
    search_attempt_ids: list[str]
    fetch_attempt_ids: list[str]
    evidence_ids: list[str]
    citation_ids: list[str]
    evaluation_id: str
    artifact_refs: list[str]
    preview: str
    diagnostics: JsonObject = field(default_factory=dict)
