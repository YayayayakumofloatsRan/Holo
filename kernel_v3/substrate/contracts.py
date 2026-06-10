from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject


SlotRequirement = Literal["required", "optional"]
TransformPlanStatus = Literal["ready", "missing_slots", "not_applicable"]
VerificationStatus = Literal["passed", "failed", "not_applicable"]


@dataclass(frozen=True, kw_only=True)
class EvidencePolicy(Contract):
    policy_id: str
    domain: str
    required_source_families: list[str] = field(default_factory=list)
    forbidden_source_families: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    authority: str | None = None
    freshness: str | None = None
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SlotSpec(Contract):
    name: str
    requirement: SlotRequirement = "required"
    description: str | None = None
    accepted_attributes: list[str] = field(default_factory=list)
    source_requirements: list[str] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SlotFill(Contract):
    slot_name: str
    claim_id: str | None = None
    value: str | None = None
    source_ref: str | None = None
    confidence: float | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SlotFrame(Contract):
    frame_id: str
    task_type: str
    domain: str
    required_slots: list[SlotSpec] = field(default_factory=list)
    optional_slots: list[SlotSpec] = field(default_factory=list)
    filled_slots: list[SlotFill] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    evidence_policy: EvidencePolicy | None = None
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Claim(Contract):
    claim_id: str
    domain: str
    entity: str | None
    attribute: str
    value: str | None = None
    unit: str | None = None
    time_period: str | None = None
    source_ref: str | None = None
    evidence_ref: str | None = None
    citation_ref: str | None = None
    extraction_method: str | None = None
    confidence: float | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TransformPlan(Contract):
    plan_id: str
    domain: str
    operation: str
    status: TransformPlanStatus
    method: str | None = None
    input_claim_ids: list[str] = field(default_factory=list)
    output_attribute: str | None = None
    payload: JsonObject | None = None
    missing_slots: list[str] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class VerificationGateResult(Contract):
    gate_id: str
    domain: str
    status: VerificationStatus
    policy_id: str | None = None
    issues: list[JsonObject] = field(default_factory=list)
    matched_claims: list[JsonObject] = field(default_factory=list)
    matched_transforms: list[JsonObject] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)
