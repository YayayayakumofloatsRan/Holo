from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject


AgentMode = Literal[
    "direct_answer",
    "semantic_answer",
    "retrieval_answer",
    "workspace_answer",
    "workspace_write",
    "system_answer",
    "clarify_first",
    "auto",
]


@dataclass(frozen=True, kw_only=True)
class TaskIntent(Contract):
    intent_id: str
    kind: str
    text: str
    sequence_index: int
    required_capabilities: list[str]
    risk: str
    status: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SemanticStateProfile(Contract):
    profile_id: str
    intent_kind: str
    domain: str
    activity: str
    resource: str
    execution_surface: str
    permission_state: str
    route_class: str
    capability_families: list[str]
    capability_statuses: list[JsonObject]
    evidence_posture: str
    output_contract: str
    autonomy: str
    risk_posture: str
    state_axes: JsonObject = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: JsonObject):
        payload = dict(data)
        payload.setdefault("state_axes", {})
        return super().from_dict(payload)


@dataclass(frozen=True, kw_only=True)
class SemanticIntake(Contract):
    intake_id: str
    goal: str
    primary_intent: str
    suggested_mode: str
    compound: bool
    requires_clarification: bool
    intents: list[JsonObject]
    blocked_capabilities: list[str]
    warnings: list[str]
    response_hint: str | None
    clarification_question: str | None


@dataclass(frozen=True, kw_only=True)
class TaskGraphNode(Contract):
    node_id: str
    kind: str
    goal: str
    sequence_index: int
    depends_on: list[str]
    required_capabilities: list[str]
    suggested_mode: str
    evidence_required: bool
    citations_required: bool
    status: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskGraphProposal(Contract):
    graph_id: str
    goal: str
    nodes: list[JsonObject]
    blocked_capabilities: list[str]
    warnings: list[str]
    needs_user_confirmation: bool
    clarification_question: str | None
    max_steps: int
    max_tool_calls: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskGraphValidation(Contract):
    graph_id: str
    status: str
    selected_mode: str
    reasons: list[str]
    blocked_capabilities: list[str]
    warnings: list[str]
    allowed_node_ids: list[str]
    rejected_node_ids: list[str]
    needs_user_confirmation: bool
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskExecutionStep(Contract):
    step_id: str
    node_id: str
    sequence_index: int
    kind: str
    goal: str
    mode: str
    action_kind: str
    tool_name: str | None
    depends_on: list[str]
    required_capabilities: list[str]
    evidence_required: bool
    citations_required: bool
    approval_required: bool
    status: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskExecutionPlan(Contract):
    plan_id: str
    graph_id: str
    status: str
    selected_mode: str
    steps: list[JsonObject]
    blocked_capabilities: list[str]
    warnings: list[str]
    approval_required: bool
    confirmation_prompt: str | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskRecipe(Contract):
    recipe_id: str
    allowed_tools: list[str]
    max_steps: int
    max_tool_calls: int
    max_network_fetches: int
    max_total_artifact_bytes: int
    permission_profile: str
    citations_required: bool
    finalizer: str
    context_budget_mode: str
    mode: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AnswerProfile(Contract):
    profile_id: str
    format: str
    detail_level: str
    target_sections: list[str]
    citation_density: str
    minimum_coverage: list[str]
    language: str | None
    min_answer_chars: int
    min_section_count: int
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FinalAnswer(Contract):
    answer: str
    citation_refs: list[str]
    used_evidence: list[str]
    limitations: list[str]
    confidence: float
    task_id: str
    run_id: str
    trace_refs: list[str]


@dataclass(frozen=True, kw_only=True)
class FailureReport(Contract):
    reason: str
    attempted_actions: list[str]
    attempted_sources: list[str]
    missing_evidence: list[str]
    last_observations: list[JsonObject]
    user_help_needed: bool
    next_possible_action: str | None
    task_id: str
    run_id: str
    trace_refs: list[str]
    host_situation: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AgentRuntimeResult(Contract):
    status: str
    task_id: str
    run_id: str
    mode: str
    recipe_id: str
    final_answer: JsonObject | None
    failure_report: JsonObject | None
    trace_refs: list[str]
    host_situation: JsonObject = field(default_factory=dict)
