from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class MissionRequirement(Contract):
    requirement_id: str
    text: str
    status: str
    evidence_refs: list[str] = field(default_factory=list)
    citation_refs: list[str] = field(default_factory=list)
    missing_reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class CoverageMap(Contract):
    mission_id: str
    coverage_score: float
    requirements: list[JsonObject]
    evidence_refs: list[str]
    citation_refs: list[str]
    missing_requirements: list[str]
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MissionDirective(Contract):
    directive_id: str
    mission_id: str
    root_goal: str
    strategy: str
    next_subgoal: str
    missing_requirements: list[str]
    avoid_repeating: list[str]
    suggested_actions: list[JsonObject]
    stop_conditions: list[str]
    reason: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MissionAssessment(Contract):
    assessment_id: str
    mission_id: str
    task_id: str
    run_id: str
    decision: str
    coverage_score: float
    covered_requirements: list[str]
    missing_requirements: list[str]
    unsupported_claims: list[str]
    next_directive: JsonObject | None
    confidence: float
    reason_summary: str
    model_decision: JsonObject | None = None
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MissionIteration(Contract):
    iteration_id: str
    mission_id: str
    task_id: str
    run_id: str
    index: int
    status: str
    run_delta: JsonObject
    assessment: JsonObject


@dataclass(frozen=True, kw_only=True)
class MissionState(Contract):
    mission_id: str
    thread_id: str
    root_goal: str
    status: str
    requirements: list[JsonObject]
    coverage_map: JsonObject
    attempted_strategies: list[str]
    open_gaps: list[str]
    blocked_reasons: list[str]
    iteration_count: int
    active_task_id: str | None = None
    last_run_id: str | None = None
    directive: JsonObject | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class MissionRuntimeResult(Contract):
    status: str
    mission_id: str
    task_id: str
    run_id: str
    agent_result: JsonObject
    mission_state: JsonObject
    assessment: JsonObject
    trace_refs: list[str]
