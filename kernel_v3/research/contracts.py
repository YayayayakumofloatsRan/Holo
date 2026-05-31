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
