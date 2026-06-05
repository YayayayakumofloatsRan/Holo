from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class WorkFrame(Contract):
    frame_id: str
    user_goal: str
    inferred_goal: str
    work_type: str
    difficulty: str
    risk_level: str
    expected_output: JsonObject
    done_criteria: list[str]
    tool_needs: list[str]
    memory_needs: list[str]
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class WorkMethod(Contract):
    method_id: str
    method_name: str
    first_moves: list[str]
    evidence_strategy: list[str]
    failure_moves: list[str]
    stop_policy: list[str]
    user_interaction_policy: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class StrategyShift(Contract):
    shift_id: str
    shift_reason: str
    next_method: str
    avoid_repeating: list[str]
    new_source_families: list[str]
    new_query_moves: list[str]
    new_tool_plan_hint: JsonObject
    confidence: float


@dataclass(frozen=True, kw_only=True)
class WorkGapAssessment(Contract):
    assessment_id: str
    covered: list[str]
    missing: list[str]
    redundant_work: list[str]
    stale_context: list[str]
    wrong_strategy: list[str]
    should_continue: bool
    should_shift_strategy: bool
    should_finalize: bool
    reason: str
    strategy_shift: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class ThreadWorkingSet(Contract):
    working_set_id: str
    thread_id: str
    active_goal: str
    current_method: str
    successful_findings: list[str]
    failed_attempts: list[str]
    open_gaps: list[str]
    user_preferences: JsonObject
    next_intent: str | None
    trace_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class WorkMethodState(Contract):
    state_id: str
    frame: JsonObject
    method: JsonObject
    thread_working_set: JsonObject
    source: str
    diagnostics: JsonObject = field(default_factory=dict)
