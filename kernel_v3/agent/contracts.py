from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject


AgentMode = Literal["direct_answer", "retrieval_answer", "workspace_answer", "clarify_first", "auto"]


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
    next_possible_action: str | None
    task_id: str
    run_id: str


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
