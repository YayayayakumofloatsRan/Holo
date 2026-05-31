from __future__ import annotations

from kernel_v3.agent.contracts import (
    SemanticIntake,
    TaskExecutionPlan,
    TaskExecutionStep,
    TaskGraphNode,
    TaskGraphProposal,
    TaskGraphValidation,
)
from kernel_v3.contracts import JsonObject


_SAFE_CAPABILITIES = {"retrieval.run", "workspace.search", "file.read", "workspace:read"}
_MAX_GRAPH_NODES = 8


def task_graph_from_semantic(intake: SemanticIntake) -> TaskGraphProposal:
    nodes: list[TaskGraphNode] = []
    prior_node_id: str | None = None
    for index, intent in enumerate(_intent_dicts(intake), start=1):
        kind = _intent_kind(intent)
        node_id = _node_id(index, kind)
        depends_on = _depends_on(intent, default=prior_node_id)
        node = TaskGraphNode(
            node_id=node_id,
            kind=kind,
            goal=str(intent.get("text") or intake.goal),
            sequence_index=_sequence_index(intent, default=index),
            depends_on=depends_on,
            required_capabilities=_string_list(intent.get("required_capabilities")),
            suggested_mode=_mode_for_kind(kind),
            evidence_required=kind in {"retrieval_research", "workspace_read"},
            citations_required=kind == "retrieval_research",
            status=str(intent.get("status") or "ready"),
            metadata=_metadata(intent),
        )
        nodes.append(node)
        prior_node_id = node_id
    if not nodes:
        nodes.append(
            TaskGraphNode(
                node_id="node-1-direct_answer",
                kind="direct_answer",
                goal=intake.goal,
                sequence_index=1,
                depends_on=[],
                required_capabilities=[],
                suggested_mode="direct_answer",
                evidence_required=False,
                citations_required=False,
                status="ready",
                metadata={},
            )
        )
    blocked = _ordered_unique(
        [
            *intake.blocked_capabilities,
            *[
                cap
                for node in nodes
                for cap in node.required_capabilities
                if _is_blocked(cap)
            ],
        ]
    )
    return TaskGraphProposal(
        graph_id="task-graph-1",
        goal=intake.goal,
        nodes=[node.to_dict() for node in nodes],
        blocked_capabilities=blocked,
        warnings=list(intake.warnings),
        needs_user_confirmation=bool(intake.requires_clarification),
        clarification_question=intake.clarification_question,
        max_steps=max(1, len(nodes) + 1),
        max_tool_calls=sum(1 for node in nodes if node.kind in {"retrieval_research", "workspace_read"}),
        metadata={"source": "semantic_intake", "primary_intent": intake.primary_intent},
    )


def validate_task_graph(proposal: TaskGraphProposal) -> TaskGraphValidation:
    nodes = [TaskGraphNode.from_dict(node) for node in proposal.nodes]
    node_ids = {node.node_id for node in nodes}
    rejected: list[str] = []
    reasons: list[str] = []
    warnings = list(proposal.warnings)
    invalid_dependencies = [
        node.node_id
        for node in nodes
        if any(dependency not in node_ids for dependency in node.depends_on)
    ]
    if invalid_dependencies:
        rejected.extend(invalid_dependencies)
        reasons.append("invalid_task_graph_dependencies")
    if len(nodes) > _MAX_GRAPH_NODES:
        rejected.extend(node.node_id for node in nodes[_MAX_GRAPH_NODES:])
        reasons.append("task_graph_node_limit_exceeded")
    blocked = _ordered_unique(
        [
            *proposal.blocked_capabilities,
            *[
                cap
                for node in nodes
                for cap in node.required_capabilities
                if _is_blocked(cap)
            ],
        ]
    )
    blocked_node_ids = [
        node.node_id
        for node in nodes
        if node.status in {"blocked", "needs_permission", "needs_review"}
    ]
    if blocked:
        reasons.append("blocked_capabilities_present")
    if blocked_node_ids:
        reasons.append("blocked_nodes_present")
    if proposal.needs_user_confirmation:
        reasons.append("user_confirmation_required")
    invalid = bool(invalid_dependencies) or len(nodes) > _MAX_GRAPH_NODES
    selected_mode = _selected_mode(
        nodes,
        blocked=bool(blocked or blocked_node_ids),
        invalid=invalid,
        needs_confirmation=proposal.needs_user_confirmation,
    )
    if invalid:
        status = "invalid"
    elif proposal.needs_user_confirmation:
        status = "needs_user_confirmation"
    elif blocked or blocked_node_ids:
        status = "blocked"
    else:
        status = "ready"
    return TaskGraphValidation(
        graph_id=proposal.graph_id,
        status=status,
        selected_mode=selected_mode,
        reasons=_ordered_unique(reasons),
        blocked_capabilities=blocked,
        warnings=_ordered_unique(warnings),
        allowed_node_ids=[node.node_id for node in nodes if node.node_id not in set(rejected)],
        rejected_node_ids=_ordered_unique(rejected),
        needs_user_confirmation=proposal.needs_user_confirmation,
        metadata={"node_count": len(nodes), "max_nodes": _MAX_GRAPH_NODES},
    )


def build_task_execution_plan(
    proposal: TaskGraphProposal,
    validation: TaskGraphValidation,
) -> TaskExecutionPlan:
    graph_nodes = [TaskGraphNode.from_dict(node) for node in proposal.nodes]
    allowed = set(validation.allowed_node_ids)
    rejected = set(validation.rejected_node_ids)
    steps: list[TaskExecutionStep] = []
    for index, node in enumerate(graph_nodes, start=1):
        status = _step_status(node, validation=validation, rejected=rejected)
        approval_required = status in {"needs_confirmation", "blocked", "invalid"}
        steps.append(
            TaskExecutionStep(
                step_id=f"plan-step-{index}",
                node_id=node.node_id,
                sequence_index=node.sequence_index,
                kind=node.kind,
                goal=node.goal,
                mode=node.suggested_mode,
                action_kind=_action_kind_for_node(node),
                tool_name=_tool_for_node(node),
                depends_on=list(node.depends_on),
                required_capabilities=list(node.required_capabilities),
                evidence_required=node.evidence_required,
                citations_required=node.citations_required,
                approval_required=approval_required,
                status=status,
                metadata={"node_allowed": node.node_id in allowed},
            )
        )
    plan_approval_required = validation.status != "ready" or any(step.approval_required for step in steps)
    return TaskExecutionPlan(
        plan_id=f"plan-{proposal.graph_id}",
        graph_id=proposal.graph_id,
        status=validation.status,
        selected_mode=validation.selected_mode,
        steps=[step.to_dict() for step in steps],
        blocked_capabilities=list(validation.blocked_capabilities),
        warnings=list(validation.warnings),
        approval_required=plan_approval_required,
        confirmation_prompt=_confirmation_prompt(proposal, validation, steps),
        metadata={
            "source": "task_graph_validation",
            "node_count": len(graph_nodes),
            "ready_step_count": sum(1 for step in steps if step.status == "ready"),
        },
    )


def _intent_dicts(intake: SemanticIntake) -> list[JsonObject]:
    return [dict(item) for item in intake.intents if isinstance(item, dict)]


def _intent_kind(intent: JsonObject) -> str:
    value = str(intent.get("kind") or "direct_answer")
    return value if value else "direct_answer"


def _node_id(index: int, kind: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in kind)
    return f"node-{index}-{safe}"


def _depends_on(intent: JsonObject, *, default: str | None) -> list[str]:
    metadata = _metadata(intent)
    value = metadata.get("depends_on")
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item]
    return [default] if default else []


def _sequence_index(intent: JsonObject, *, default: int) -> int:
    value = intent.get("sequence_index")
    return int(value) if isinstance(value, int) and value > 0 else default


def _metadata(intent: JsonObject) -> JsonObject:
    value = intent.get("metadata")
    return dict(value) if isinstance(value, dict) else {}


def _mode_for_kind(kind: str) -> str:
    if kind == "retrieval_research":
        return "retrieval_answer"
    if kind == "workspace_read":
        return "workspace_answer"
    if kind == "clarification":
        return "clarify_first"
    return "direct_answer"


def _action_kind_for_node(node: TaskGraphNode) -> str:
    if node.kind in {"retrieval_research", "workspace_read"}:
        return "tool"
    if node.kind == "clarification":
        return "ask_user"
    return "respond"


def _tool_for_node(node: TaskGraphNode) -> str | None:
    if node.kind == "retrieval_research":
        return "retrieval.run"
    if node.kind == "workspace_read":
        return "workspace.search,file.read"
    return None


def _step_status(
    node: TaskGraphNode,
    *,
    validation: TaskGraphValidation,
    rejected: set[str],
) -> str:
    if node.node_id in rejected or validation.status == "invalid":
        return "invalid"
    if node.status in {"blocked", "needs_permission", "needs_review"}:
        return "blocked"
    if validation.needs_user_confirmation:
        return "needs_confirmation"
    if any(_is_blocked(capability) for capability in node.required_capabilities):
        return "blocked"
    return "ready"


def _confirmation_prompt(
    proposal: TaskGraphProposal,
    validation: TaskGraphValidation,
    steps: list[TaskExecutionStep],
) -> str | None:
    if not validation.needs_user_confirmation and validation.status == "ready":
        return None
    if proposal.clarification_question:
        return proposal.clarification_question
    step_lines = [
        f"{step.sequence_index}. {step.kind}: {step.goal}"
        for step in steps[:_MAX_GRAPH_NODES]
    ]
    blocked = f" Blocked capabilities: {', '.join(validation.blocked_capabilities)}." if validation.blocked_capabilities else ""
    reasons = f" Reasons: {', '.join(validation.reasons)}." if validation.reasons else ""
    return "Confirm this host-validated task plan before execution: " + " | ".join(step_lines) + blocked + reasons


def _selected_mode(
    nodes: list[TaskGraphNode],
    *,
    blocked: bool,
    invalid: bool,
    needs_confirmation: bool,
) -> str:
    if invalid or needs_confirmation:
        return "clarify_first"
    if blocked:
        return "direct_answer"
    return nodes[0].suggested_mode if nodes else "direct_answer"


def _is_blocked(capability: str) -> bool:
    if not capability:
        return False
    return capability not in _SAFE_CAPABILITIES


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
