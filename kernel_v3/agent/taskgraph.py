from __future__ import annotations

from kernel_v3.agent.contracts import (
    SemanticIntake,
    TaskExecutionPlan,
    TaskExecutionStep,
    TaskGraphNode,
    TaskGraphProposal,
    TaskGraphValidation,
)
from kernel_v3.agent.state_space import profile_intent_state, summarize_state_profiles
from kernel_v3.capabilities import SAFE_SEMANTIC_CAPABILITIES
from kernel_v3.contracts import JsonObject


_MAX_GRAPH_NODES = 32
_RETRIEVAL_CAPABILITIES = {
    "finance.fundamentals_research",
    "finance.market_news",
    "finance.market_data",
    "finance.macro_data",
    "finance.competitive_landscape",
    "technical.documentation_research",
    "technical.api_documentation",
    "technical.developer_docs",
    "technical.source_repository",
    "retrieval.run",
    "web.research",
    "web.search",
    "web.fetch",
    "web.crawl",
    "browser.page.open",
}
_WORKSPACE_READ_CAPABILITIES = {"workspace.list", "workspace.search", "file.read", "workspace:read"}
_WORKSPACE_WRITE_CAPABILITIES = {"workspace.write", "workspace:write"}
_MEMORY_READ_CAPABILITIES = {"durable_memory.read", "durable_memory.search", "memory.recall"}
_SYSTEM_TOOL_CAPABILITIES = {"system.time"}
_SYSTEM_HOST_CAPABILITIES = {"system.environment"}
_SYSTEM_CAPABILITIES = _SYSTEM_TOOL_CAPABILITIES | _SYSTEM_HOST_CAPABILITIES | {"system.process"}
_EXECUTABLE_TOOL_CAPABILITIES = {
    "retrieval.run",
    "workspace.list",
    "workspace.search",
    "file.read",
    "workspace.write",
    "memory.recall",
    "system.time",
}
_FINANCE_FUNDAMENTALS_PROFILE_ID = "finance_fundamentals"
_TECHNICAL_DOCUMENTATION_PROFILE_ID = "technical_documentation"
_TECHNICAL_DOCUMENTATION_CAPABILITIES = {
    "technical.documentation_research",
    "technical.api_documentation",
    "technical.developer_docs",
    "technical.source_repository",
}


def task_graph_from_semantic(intake: SemanticIntake) -> TaskGraphProposal:
    nodes: list[TaskGraphNode] = []
    prior_node_id: str | None = None
    for index, intent in enumerate(_intent_dicts(intake), start=1):
        kind = _intent_kind(intent)
        capabilities = _string_list(intent.get("required_capabilities"))
        metadata = _metadata(intent)
        metadata.setdefault("semantic_label", kind)
        metadata.setdefault("capability_plan", _capability_plan(capabilities))
        if intake.suggested_mode == "semantic_answer" and _is_non_tool_semantic_node(capabilities):
            metadata.setdefault("suggested_mode", "semantic_answer")
        node_id = _node_id(index, kind)
        depends_on = _depends_on(intent, default=prior_node_id)
        evidence_required = _evidence_required(kind, capabilities, metadata=metadata)
        citations_required = _citations_required(kind, capabilities, metadata=metadata)
        state_profile = profile_intent_state(
            profile_id=f"profile-{node_id}",
            intent_kind=kind,
            capabilities=capabilities,
            metadata=metadata,
            evidence_required=evidence_required,
            citations_required=citations_required,
            risk=str(intent.get("risk") or ""),
            status=str(intent.get("status") or "ready"),
        )
        metadata["state_profile"] = state_profile.to_dict()
        node = TaskGraphNode(
            node_id=node_id,
            kind=kind,
            goal=str(intent.get("text") or intake.goal),
            sequence_index=_sequence_index(intent, default=index),
            depends_on=depends_on,
            required_capabilities=capabilities,
            suggested_mode=_mode_for_intent(kind, capabilities, metadata=metadata),
            evidence_required=evidence_required,
            citations_required=citations_required,
            status=str(intent.get("status") or "ready"),
            metadata=metadata,
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
    state_profile_summary = summarize_state_profiles(
        [
            dict(node.metadata["state_profile"])
            for node in nodes
            if isinstance(node.metadata.get("state_profile"), dict)
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
        max_tool_calls=sum(1 for node in nodes if _action_kind_for_node(node) == "tool"),
        metadata={
            "source": "semantic_intake",
            "primary_intent": intake.primary_intent,
            "state_profile_summary": state_profile_summary,
        },
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
        capability_args = _capability_args(node.metadata)
        if not capability_args:
            capability_args = _default_capability_args_for_node(node)
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
                metadata={
                    "node_allowed": node.node_id in allowed,
                    "node_metadata": dict(node.metadata),
                    "capability_args": capability_args,
                    "capability_plan": _json_object(node.metadata.get("capability_plan")),
                },
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


def _capability_args(metadata: JsonObject) -> JsonObject:
    value = metadata.get("capability_args")
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key, payload in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(payload, dict):
            result[key] = dict(payload)
        elif isinstance(payload, list):
            result[key] = [dict(item) for item in payload if isinstance(item, dict)]
    return result


def _default_capability_args_for_node(node: TaskGraphNode) -> JsonObject:
    capabilities = set(node.required_capabilities)
    if not capabilities.intersection(_RETRIEVAL_CAPABILITIES):
        return {}
    if capabilities.intersection(_TECHNICAL_DOCUMENTATION_CAPABILITIES):
        query = " ".join(str(node.goal or "").split()) or "technical documentation research"
        payloads = [
            _profile_retrieval_payload(
                query=query,
                task_kind=_primary_technical_documentation_task_kind(capabilities),
                authority="primary",
                strategy="aggregate",
                profile_id=_TECHNICAL_DOCUMENTATION_PROFILE_ID,
                required=True,
            )
        ]
        if "technical.api_documentation" in capabilities or "technical.documentation_research" in capabilities:
            payloads.append(
                _profile_retrieval_payload(
                    query=f"{query} official API reference authentication endpoint parameters examples",
                    task_kind="api_documentation",
                    authority="primary",
                    strategy="aggregate",
                    profile_id=_TECHNICAL_DOCUMENTATION_PROFILE_ID,
                    required=False,
                )
            )
        return {"retrieval.run": payloads}
    if not capabilities.intersection(
        {
            "finance.fundamentals_research",
            "finance.market_data",
            "finance.market_news",
            "finance.macro_data",
            "finance.competitive_landscape",
        }
    ):
        return {}
    query = " ".join(str(node.goal or "").split()) or "financial research"
    payloads: list[JsonObject] = []
    payloads.append(
        _finance_retrieval_payload(
            query=query,
            task_kind=_primary_finance_task_kind(capabilities),
            authority="secondary_or_better",
            strategy="aggregate",
            profile_id=_profile_for_finance_capabilities(capabilities),
            required=True,
        )
    )
    if "finance.fundamentals_research" in capabilities:
        payloads.extend(
            [
                _finance_retrieval_payload(
                    query=f"{query} official annual report 10-K 10-Q investor relations revenue earnings margin cash flow",
                    task_kind="fundamentals",
                    authority="primary",
                    strategy="aggregate",
                    profile_id=_FINANCE_FUNDAMENTALS_PROFILE_ID,
                    required=False,
                ),
                _finance_retrieval_payload(
                    query=f"{query} SEC EDGAR companyfacts submissions 10-K 10-Q financial statements",
                    task_kind="fundamentals",
                    authority="primary",
                    strategy="structured",
                    profile_id=_FINANCE_FUNDAMENTALS_PROFILE_ID,
                    required=False,
                ),
            ]
        )
    if "finance.market_data" in capabilities or "finance.fundamentals_research" in capabilities:
        payloads.append(
            _finance_retrieval_payload(
                query=f"{query} stock price PE ratio market cap valuation quote",
                task_kind="market_data",
                authority="secondary_or_better",
                strategy="aggregate",
                profile_id=_profile_for_finance_capabilities(capabilities),
                required=False,
            )
        )
    if "finance.market_news" in capabilities:
        payloads.append(
            _finance_retrieval_payload(
                query=f"{query} latest earnings release market news official investor relations",
                task_kind="market_news",
                authority="secondary_or_better",
                strategy="fresh_live",
                profile_id=_profile_for_finance_capabilities(capabilities),
                required=False,
            )
        )
    if "finance.competitive_landscape" in capabilities:
        payloads.append(
            _finance_retrieval_payload(
                query=f"{query} competitors peer comparison industry landscape",
                task_kind="competitive_landscape",
                authority="secondary_or_better",
                strategy="aggregate",
                profile_id=_profile_for_finance_capabilities(capabilities),
                required=False,
            )
        )
    if "finance.macro_data" in capabilities:
        payloads.append(
            _finance_retrieval_payload(
                query=f"{query} official macroeconomic data FRED central bank treasury statistics",
                task_kind="macro_data",
                authority="primary",
                strategy="structured",
                profile_id=_profile_for_finance_capabilities(capabilities),
                required=False,
            )
        )
    return {"retrieval.run": payloads} if payloads else {}


def _primary_finance_task_kind(capabilities: set[str]) -> str:
    for capability, task_kind in [
        ("finance.fundamentals_research", "fundamentals"),
        ("finance.market_data", "market_data"),
        ("finance.market_news", "market_news"),
        ("finance.competitive_landscape", "competitive_landscape"),
        ("finance.macro_data", "macro_data"),
    ]:
        if capability in capabilities:
            return task_kind
    return "finance_research"


def _primary_technical_documentation_task_kind(capabilities: set[str]) -> str:
    if "technical.api_documentation" in capabilities:
        return "api_documentation"
    if "technical.source_repository" in capabilities:
        return "source_repository"
    if "technical.developer_docs" in capabilities:
        return "developer_docs"
    return "technical_documentation"


def _profile_for_finance_capabilities(capabilities: set[str]) -> str | None:
    if capabilities.intersection(
        {
            "finance.fundamentals_research",
            "finance.market_data",
            "finance.market_news",
            "finance.macro_data",
            "finance.competitive_landscape",
        }
    ):
        return _FINANCE_FUNDAMENTALS_PROFILE_ID
    return None


def _profile_retrieval_payload(
    *,
    query: str,
    task_kind: str,
    authority: str,
    strategy: str,
    profile_id: str,
    required: bool,
) -> JsonObject:
    return {
        "query": query,
        "metadata": {
            "research_profile": profile_id,
            "research_task_kind": task_kind,
            "source_authority_requirement": authority,
            "search_strategy": strategy,
            "subgoal_required": required,
        },
    }


def _finance_retrieval_payload(
    *,
    query: str,
    task_kind: str,
    authority: str,
    strategy: str,
    profile_id: str | None,
    required: bool,
) -> JsonObject:
    metadata: JsonObject = {
        "research_task_kind": task_kind,
        "source_authority_requirement": authority,
        "search_strategy": strategy,
        "subgoal_required": required,
    }
    if profile_id:
        metadata["research_profile"] = profile_id
    return {
        "query": query,
        "metadata": metadata,
    }


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _mode_for_intent(kind: str, capabilities: list[str], *, metadata: JsonObject) -> str:
    requested = metadata.get("suggested_mode")
    if isinstance(requested, str) and requested in {
        "direct_answer",
        "semantic_answer",
        "retrieval_answer",
        "workspace_answer",
        "workspace_write",
        "system_answer",
        "clarify_first",
    }:
        return requested
    if _has_any(capabilities, _SYSTEM_TOOL_CAPABILITIES):
        return "system_answer"
    if _has_any(capabilities, _SYSTEM_HOST_CAPABILITIES):
        return "semantic_answer"
    if _has_any(capabilities, _RETRIEVAL_CAPABILITIES):
        return "retrieval_answer"
    if _has_any(capabilities, _MEMORY_READ_CAPABILITIES):
        return "semantic_answer"
    if _has_any(capabilities, _WORKSPACE_WRITE_CAPABILITIES):
        return "workspace_write"
    if _has_any(capabilities, _WORKSPACE_READ_CAPABILITIES):
        return "workspace_answer"
    if kind in {"retrieval_research", "web_research", "market_news_research", "market_data_research", "macro_data_research"}:
        return "retrieval_answer"
    if kind == "workspace_read":
        return "workspace_answer"
    if kind == "clarification":
        return "clarify_first"
    return "direct_answer"


def _action_kind_for_node(node: TaskGraphNode) -> str:
    if _tool_for_node(node) is not None:
        return "tool"
    if node.kind == "clarification" or node.status == "needs_user_input":
        return "ask_user"
    return "respond"


def _tool_for_node(node: TaskGraphNode) -> str | None:
    capabilities = set(node.required_capabilities)
    if capabilities & _RETRIEVAL_CAPABILITIES:
        return "retrieval.run"
    if capabilities & _MEMORY_READ_CAPABILITIES:
        return "memory.recall"
    if capabilities & _WORKSPACE_WRITE_CAPABILITIES:
        return "workspace.write"
    if "workspace.list" in capabilities:
        return "workspace.list"
    if {"workspace.search", "file.read"}.issubset(capabilities):
        return "workspace.search,file.read"
    if "workspace.search" in capabilities:
        return "workspace.search"
    if "file.read" in capabilities:
        return "file.read"
    if capabilities & _SYSTEM_TOOL_CAPABILITIES:
        return "system.time"
    if node.kind in {"retrieval_research", "web_research", "market_news_research", "market_data_research", "macro_data_research"}:
        return "retrieval.run"
    if node.kind == "workspace_read":
        return "workspace.search,file.read"
    if node.kind in {"directory_list", "workspace_list"}:
        return "workspace.list"
    return None


def _capability_plan(capabilities: list[str]) -> JsonObject:
    if not capabilities:
        return {"action_family": "respond", "tools": [], "requires_evidence": False}
    tools = [capability for capability in capabilities if capability in _EXECUTABLE_TOOL_CAPABILITIES]
    if _has_any(capabilities, _RETRIEVAL_CAPABILITIES) and "retrieval.run" not in tools:
        tools.append("retrieval.run")
    if _has_any(capabilities, _MEMORY_READ_CAPABILITIES) and "memory.recall" not in tools:
        tools.append("memory.recall")
    if "workspace:write" in capabilities and "workspace.write" not in tools:
        tools.append("workspace.write")
    return {
        "action_family": "tool" if tools else "host_capability",
        "tools": tools,
        "requires_evidence": any(
            capability in capabilities
            for capability in {
                *_RETRIEVAL_CAPABILITIES,
                *_WORKSPACE_READ_CAPABILITIES,
                *_MEMORY_READ_CAPABILITIES,
            }
        ),
    }


def _evidence_required(kind: str, capabilities: list[str], *, metadata: JsonObject) -> bool:
    value = metadata.get("evidence_required")
    if isinstance(value, bool):
        return value
    if any(
        capability in capabilities
        for capability in {
            *_RETRIEVAL_CAPABILITIES,
            *_WORKSPACE_READ_CAPABILITIES,
            *_MEMORY_READ_CAPABILITIES,
        }
    ):
        return True
    return kind in {"retrieval_research", "web_research", "market_news_research", "market_data_research", "macro_data_research", "workspace_read"}


def _citations_required(kind: str, capabilities: list[str], *, metadata: JsonObject) -> bool:
    value = metadata.get("citations_required")
    if isinstance(value, bool):
        return value
    if _has_any(capabilities, _RETRIEVAL_CAPABILITIES):
        return True
    return kind in {"retrieval_research", "web_research", "market_news_research", "market_data_research", "macro_data_research"}


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
    if any(_is_blocked(capability) for capability in node.required_capabilities):
        return "blocked"
    if validation.needs_user_confirmation:
        return "needs_confirmation"
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
    return capability not in SAFE_SEMANTIC_CAPABILITIES


def _has_any(capabilities: list[str], markers: set[str]) -> bool:
    return bool(set(capabilities) & markers)


def _is_non_tool_semantic_node(capabilities: list[str]) -> bool:
    if not capabilities:
        return True
    tool_capabilities = (
        _RETRIEVAL_CAPABILITIES
        | _WORKSPACE_READ_CAPABILITIES
        | _WORKSPACE_WRITE_CAPABILITIES
        | _MEMORY_READ_CAPABILITIES
        | _SYSTEM_TOOL_CAPABILITIES
    )
    return not any(capability in tool_capabilities for capability in capabilities)


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
