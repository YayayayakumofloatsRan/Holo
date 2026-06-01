from __future__ import annotations

from kernel_v3.agent.contracts import SemanticStateProfile
from kernel_v3.capabilities import SAFE_SEMANTIC_CAPABILITIES, capability_catalog
from kernel_v3.contracts import JsonObject


_CAPABILITY_ALIASES = {
    "file.read": "workspace.file.read",
    "workspace.write": "workspace.file.write",
    "workspace:read": "workspace.file.read",
    "workspace:write": "workspace.file.write",
    "network.fetch": "web.fetch",
    "shell:exec": "shell.exec",
    "durable_memory:write": "durable_memory.commit",
    "durable_memory:delete": "durable_memory.delete",
    "live_transport:wechat": "transport.wechat",
    "live_transport:discord": "transport.discord",
    "live_transport:slack": "transport.slack",
    "live_transport:email": "transport.email",
}


_FAMILY_BY_MARKER = {
    "conversation": (
        "conversation",
        "roleplay",
        "knowledge",
        "analysis",
        "direct_answer",
        "noop",
        "task.decompose",
        "decision",
        "strategy",
        "assistant",
        "preference",
    ),
    "retrieval": ("retrieval", "web", "browser.page", "news", "research"),
    "finance": ("finance", "market", "filing", "fundamental", "competitive", "macro", "economic_indicator"),
    "legal": ("legal", "contract", "regulation", "compliance"),
    "medical": ("medical", "health", "clinical", "diagnosis"),
    "education": ("education", "tutor", "teach", "learning"),
    "creative": ("creative", "story", "joke", "copywriting"),
    "communication": ("communication", "message", "notification", "customer_support"),
    "operations": ("operations", "sop", "process", "runbook"),
    "product": ("product", "roadmap", "requirements", "spec"),
    "risk": ("risk", "audit", "governance", "policy_review"),
    "cybersecurity": ("cyber", "cybersecurity", "security.review", "vulnerability"),
    "workspace": ("workspace", "file", "codebase_file"),
    "memory": ("memory", "durable_memory", "remember", "recall"),
    "artifact": ("artifact", "export"),
    "document": ("document", "report", "email", "draft", "review"),
    "data": ("data", "table", "chart", "spreadsheet"),
    "database": ("database", "sql", "schema"),
    "code": ("code", "test", "patch"),
    "cloud": ("cloud", "devops", "deploy"),
    "workflow": ("workflow", "automation"),
    "knowledge_base": ("knowledge_base", "knowledge-base", "kb"),
    "multimodal": ("multimodal", "image", "ocr", "media"),
    "project": ("project", "task.queue", "status"),
    "resident": ("resident", "schedule", "monitor", "inbox", "outbox"),
    "transport": ("transport", "wechat", "discord", "slack"),
    "calendar": ("calendar", "reminder"),
    "system": ("system", "shell", "environment", "process", "time"),
    "security": ("credential", "secret", "device", "browser.session", "security"),
}


_SURFACE_BY_FAMILY = {
    "conversation": "conversation",
    "retrieval": "retrieval",
    "finance": "retrieval",
    "legal": "retrieval",
    "medical": "conversation",
    "education": "conversation",
    "creative": "conversation",
    "communication": "conversation",
    "operations": "workflow_engine",
    "product": "artifact",
    "risk": "external_api",
    "cybersecurity": "workspace",
    "workspace": "workspace",
    "memory": "durable_memory",
    "artifact": "artifact",
    "document": "artifact",
    "data": "external_api",
    "database": "external_api",
    "code": "workspace",
    "cloud": "external_api",
    "workflow": "resident_queue",
    "knowledge_base": "external_api",
    "multimodal": "media_input",
    "project": "resident_queue",
    "resident": "resident_queue",
    "transport": "transport_gateway",
    "calendar": "external_api",
    "system": "system_state",
    "security": "external_account_boundary",
}


_RESOURCE_BY_FAMILY = {
    "conversation": "conversation_turn",
    "retrieval": "web_page",
    "finance": "official_filing",
    "legal": "legal_source",
    "medical": "medical_source",
    "education": "learning_prompt",
    "creative": "conversation_turn",
    "communication": "message_draft",
    "operations": "workflow_run",
    "product": "generated_artifact",
    "risk": "policy_document",
    "cybersecurity": "local_file",
    "workspace": "local_file",
    "memory": "memory_item",
    "artifact": "generated_artifact",
    "document": "generated_artifact",
    "data": "dataset",
    "database": "database_table",
    "code": "local_file",
    "cloud": "cloud_resource",
    "workflow": "queue_message",
    "knowledge_base": "knowledge_base_entry",
    "multimodal": "media_input",
    "project": "queue_message",
    "resident": "queue_message",
    "transport": "external_account",
    "calendar": "calendar_event",
    "system": "system_state",
    "security": "credential_boundary",
}


def profile_intent_state(
    *,
    profile_id: str,
    intent_kind: str,
    capabilities: list[str],
    metadata: JsonObject,
    evidence_required: bool,
    citations_required: bool,
    risk: str,
    status: str,
) -> SemanticStateProfile:
    capability_statuses = [_capability_status(capability) for capability in capabilities]
    families = _ordered_unique(
        [
            str(item["family"])
            for item in capability_statuses
            if isinstance(item.get("family"), str) and item.get("family")
        ]
    )
    domain = _metadata_or_default(metadata, "domain", _domain(intent_kind, families))
    activity = _metadata_or_default(metadata, "activity", _activity(intent_kind, capabilities))
    resource = _metadata_or_default(metadata, "resource", _resource(domain, families))
    permission_state = _permission_state(capability_statuses, risk=risk)
    route_class = _route_class(capability_statuses, status=status)
    execution_surface = _metadata_or_default(
        metadata,
        "execution_surface",
        _execution_surface(domain, families, activity=activity, capability_statuses=capability_statuses),
    )
    evidence_posture = _evidence_posture(evidence_required=evidence_required, citations_required=citations_required)
    output_contract = _output_contract(
        citations_required=citations_required,
        execution_surface=execution_surface,
        activity=activity,
    )
    autonomy = _metadata_or_default(
        metadata,
        "autonomy",
        "bounded_task_loop" if activity in {"research", "read", "write", "monitor", "plan", "analyze"} else "single_turn_response",
    )
    risk_posture = _risk_posture(risk=risk, permission_state=permission_state)
    return SemanticStateProfile(
        profile_id=profile_id,
        intent_kind=intent_kind,
        domain=domain,
        activity=activity,
        resource=resource,
        execution_surface=execution_surface,
        permission_state=permission_state,
        route_class=route_class,
        capability_families=families,
        capability_statuses=capability_statuses,
        evidence_posture=evidence_posture,
        output_contract=output_contract,
        autonomy=autonomy,
        risk_posture=risk_posture,
        state_axes=_state_axes(
            intent_kind=intent_kind,
            capabilities=capabilities,
            metadata=metadata,
            domain=domain,
            families=families,
            activity=activity,
            resource=resource,
            execution_surface=execution_surface,
            permission_state=permission_state,
            route_class=route_class,
            evidence_posture=evidence_posture,
            output_contract=output_contract,
            autonomy=autonomy,
            risk_posture=risk_posture,
            status=status,
        ),
        notes=_notes(capability_statuses, status=status),
    )


def summarize_state_profiles(profiles: list[JsonObject]) -> JsonObject:
    state_axes = _summarize_state_axes(profiles)
    return {
        "domains": _ordered_unique(
            [
                *_strings_from_profiles(profiles, "domain"),
                *[
                    str(family)
                    for profile in profiles
                    for family in profile.get("capability_families", [])
                    if isinstance(family, str) and family
                ],
            ]
        ),
        "activities": _ordered_unique(_strings_from_profiles(profiles, "activity")),
        "resources": _ordered_unique(_strings_from_profiles(profiles, "resource")),
        "execution_surfaces": _ordered_unique(_strings_from_profiles(profiles, "execution_surface")),
        "permission_states": _ordered_unique(_strings_from_profiles(profiles, "permission_state")),
        "route_classes": _ordered_unique(_strings_from_profiles(profiles, "route_class")),
        "output_contracts": _ordered_unique(_strings_from_profiles(profiles, "output_contract")),
        "risk_postures": _ordered_unique(_strings_from_profiles(profiles, "risk_posture")),
        "state_axes": state_axes,
    }


def _state_axes(
    *,
    intent_kind: str,
    capabilities: list[str],
    metadata: JsonObject,
    domain: str,
    families: list[str],
    activity: str,
    resource: str,
    execution_surface: str,
    permission_state: str,
    route_class: str,
    evidence_posture: str,
    output_contract: str,
    autonomy: str,
    risk_posture: str,
    status: str,
) -> JsonObject:
    return {
        "task_lifecycle": _axis(metadata, "task_lifecycle", _task_lifecycle(status=status)),
        "workloop": _axis(metadata, "workloop", "planning"),
        "intent_scope": _axis(
            metadata,
            "intent_scope",
            _intent_scope(intent_kind=intent_kind, activity=activity, autonomy=autonomy, route_class=route_class),
        ),
        "execution_surface": execution_surface,
        "evidence": evidence_posture,
        "tooling": _axis(
            metadata,
            "tooling",
            _tooling_state(permission_state=permission_state, route_class=route_class, capabilities=capabilities),
        ),
        "permissions": permission_state,
        "memory": _axis(metadata, "memory", _memory_state(domain=domain, capabilities=capabilities)),
        "resident": _axis(metadata, "resident", _resident_state(domain=domain, status=status, activity=activity)),
        "network": _axis(
            metadata,
            "network",
            _network_state(
                domain=domain,
                families=families,
                permission_state=permission_state,
                route_class=route_class,
                capabilities=capabilities,
            ),
        ),
        "artifacts": _axis(
            metadata,
            "artifacts",
            _artifact_state(domain=domain, families=families, output_contract=output_contract),
        ),
        "external_systems": _axis(
            metadata,
            "external_systems",
            _external_system_state(domain=domain, families=families, permission_state=permission_state),
        ),
        "domain_profile": _axis(
            metadata,
            "domain_profile",
            _domain_profile(intent_kind=intent_kind, domain=domain, activity=activity, capabilities=capabilities),
        ),
        "output_contract": output_contract,
        "route_class": route_class,
        "user_control": _axis(metadata, "user_control", _user_control(status=status)),
        "autonomy": autonomy,
        "world_model": _axis(
            metadata,
            "world_model",
            _world_model(domain=domain, families=families, execution_surface=execution_surface, resource=resource),
        ),
        "resource_kind": resource,
        "action_phase": _axis(metadata, "action_phase", "intake"),
        "risk": risk_posture,
        "temporal": _axis(metadata, "temporal", _temporal_state(intent_kind=intent_kind, capabilities=capabilities)),
        "authority": _axis(
            metadata,
            "authority",
            _authority_state(
                domain=domain,
                families=families,
                evidence_posture=evidence_posture,
                execution_surface=execution_surface,
                capabilities=capabilities,
            ),
        ),
        "identity_boundary": _axis(
            metadata,
            "identity_boundary",
            _identity_boundary(intent_kind=intent_kind, domain=domain, capabilities=capabilities),
        ),
        "communication_channel": _axis(metadata, "communication_channel", "chat_thread"),
        "goal_structure": _axis(
            metadata,
            "goal_structure",
            _goal_structure(intent_kind=intent_kind, activity=activity, autonomy=autonomy, route_class=route_class),
        ),
        "dependency_state": _axis(
            metadata,
            "dependency_state",
            _dependency_state(
                metadata=metadata,
                evidence_posture=evidence_posture,
                execution_surface=execution_surface,
                permission_state=permission_state,
                status=status,
            ),
        ),
        "commitment_state": _axis(
            metadata,
            "commitment_state",
            _commitment_state(activity=activity, permission_state=permission_state, status=status),
        ),
        "preference_state": _axis(
            metadata,
            "preference_state",
            _preference_state(domain=domain, capabilities=capabilities),
        ),
        "memory_scope": _axis(
            metadata,
            "memory_scope",
            _memory_scope(domain=domain, capabilities=capabilities, memory_state=_memory_state(domain=domain, capabilities=capabilities)),
        ),
        "planning_depth": _axis(
            metadata,
            "planning_depth",
            _planning_depth(intent_kind=intent_kind, activity=activity, autonomy=autonomy, route_class=route_class),
        ),
        "operation_runtime": _axis(
            metadata,
            "operation_runtime",
            _operation_runtime(intent_kind=intent_kind, activity=activity, autonomy=autonomy, domain=domain),
        ),
        "quality_bar": _axis(
            metadata,
            "quality_bar",
            _quality_bar(
                domain=domain,
                activity=activity,
                evidence_posture=evidence_posture,
                authority=_authority_state(
                    domain=domain,
                    families=families,
                    evidence_posture=evidence_posture,
                    execution_surface=execution_surface,
                    capabilities=capabilities,
                ),
            ),
        ),
        "interruption_policy": _axis(
            metadata,
            "interruption_policy",
            _interruption_policy(permission_state=permission_state, route_class=route_class),
        ),
    }


def _summarize_state_axes(profiles: list[JsonObject]) -> JsonObject:
    axes: dict[str, list[str]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        value = profile.get("state_axes")
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                continue
            if isinstance(item, str) and item:
                axes.setdefault(key, []).append(item)
            elif isinstance(item, list):
                axes.setdefault(key, []).extend(str(entry) for entry in item if isinstance(entry, str) and entry)
    return {key: _ordered_unique(values) for key, values in sorted(axes.items())}


def _capability_index() -> dict[str, JsonObject]:
    return {str(item["capability_id"]): item for item in capability_catalog()["capabilities"]}


def _capability_status(capability: str) -> JsonObject:
    canonical = _CAPABILITY_ALIASES.get(capability, capability)
    spec = _capability_index().get(canonical)
    if spec is not None:
        return {
            "capability_id": capability,
            "canonical_id": canonical,
            "family": str(spec.get("family") or _family_for(capability)),
            "status": str(spec.get("status") or _status_for(capability)),
            "tool_name": spec.get("tool_name"),
            "side_effect_class": str(spec.get("side_effect_class") or "none"),
            "permissions_required": list(spec.get("permissions_required") or []),
        }
    return {
        "capability_id": capability,
        "canonical_id": canonical,
        "family": _family_for(capability),
        "status": _status_for(capability),
        "tool_name": _tool_for(capability),
        "side_effect_class": _side_effect_for(capability),
        "permissions_required": _permissions_for(capability),
    }


def _domain(intent_kind: str, families: list[str]) -> str:
    if families:
        if "finance" in families:
            return "finance"
        if "retrieval" in families:
            return "retrieval"
        return families[0]
    return _family_for(intent_kind)


def _activity(intent_kind: str, capabilities: list[str]) -> str:
    text = " ".join([intent_kind, *capabilities]).lower()
    if any(marker in text for marker in ("research", "web.", "retrieval", "market_news")):
        return "research"
    if any(marker in text for marker in ("write", "draft", "compose", "patch", "schedule", "send", "creative")):
        return "write"
    if any(marker in text for marker in ("tutor", "teach", "education", "explain")):
        return "teach"
    if any(marker in text for marker in ("plan", "roadmap", "requirements", "operations", "product")):
        return "plan"
    if any(marker in text for marker in ("read", "search", "recall", "status", "time")):
        return "read"
    if any(marker in text for marker in ("review", "analyze", "analysis", "reason", "compliance")):
        return "analyze"
    if any(marker in text for marker in ("monitor", "resident")):
        return "monitor"
    if any(marker in text for marker in ("transport", "device", "credential", "secret")):
        return "boundary"
    return "respond"


def _resource(domain: str, families: list[str]) -> str:
    for family in [domain, *families]:
        if family in _RESOURCE_BY_FAMILY:
            return _RESOURCE_BY_FAMILY[family]
    return "conversation_turn"


def _execution_surface(
    domain: str,
    families: list[str],
    *,
    activity: str,
    capability_statuses: list[JsonObject],
) -> str:
    side_effects = {str(item.get("side_effect_class") or "none") for item in capability_statuses}
    if activity == "research" and ("network" in side_effects or domain in {"legal", "medical", "retrieval"}):
        return "retrieval"
    for family in [domain, *families]:
        if family in _SURFACE_BY_FAMILY:
            return _SURFACE_BY_FAMILY[family]
    return "conversation"


def _permission_state(capability_statuses: list[JsonObject], *, risk: str) -> str:
    statuses = {str(item.get("status") or "") for item in capability_statuses}
    permissions = {
        permission
        for item in capability_statuses
        for permission in item.get("permissions_required", [])
        if isinstance(permission, str)
    }
    side_effects = {str(item.get("side_effect_class") or "none") for item in capability_statuses}
    if risk in {"destructive", "credential", "secret"} or "destructive" in side_effects:
        return "dangerous_blocked"
    if "not_configured" in statuses:
        return "not_configured"
    if "planned" in statuses:
        return "planned"
    if "host_only" in statuses:
        return "host_only"
    if any(permission.startswith("network") for permission in permissions):
        return "network_permission_required"
    if any(effect in {"write", "shell"} for effect in side_effects) or any(permission.endswith(":write") for permission in permissions):
        return "write_permission_required"
    if any(effect in {"read", "network"} for effect in side_effects):
        return "read_allowed"
    return "none_required"


def _route_class(capability_statuses: list[JsonObject], *, status: str) -> str:
    if status in {"blocked", "needs_permission", "needs_review", "invalid"}:
        return "host_boundary"
    if not capability_statuses:
        return "respond_only"
    statuses = {str(item.get("status") or "") for item in capability_statuses}
    tools = [str(item.get("tool_name")) for item in capability_statuses if isinstance(item.get("tool_name"), str)]
    if "host_only" in statuses:
        return "host_only_boundary"
    if "planned" in statuses or "not_configured" in statuses:
        return "planned_or_not_configured_boundary"
    if tools:
        return "executable_tool"
    return "host_capability_or_response"


def _evidence_posture(*, evidence_required: bool, citations_required: bool) -> str:
    if citations_required:
        return "citations_required"
    if evidence_required:
        return "evidence_required"
    return "not_required"


def _output_contract(*, citations_required: bool, execution_surface: str, activity: str) -> str:
    if citations_required:
        return "cited_answer"
    if activity == "write" and execution_surface in {"workspace", "artifact"}:
        return "file_artifact"
    if activity == "boundary":
        return "failure_or_boundary_report"
    return "plain_answer"


def _risk_posture(*, risk: str, permission_state: str) -> str:
    if permission_state in {"dangerous_blocked", "host_only", "planned", "not_configured"}:
        return permission_state
    return risk or "normal"


def _notes(capability_statuses: list[JsonObject], *, status: str) -> list[str]:
    notes = []
    if status not in {"ready", ""}:
        notes.append(f"intent_status:{status}")
    for item in capability_statuses:
        capability = str(item.get("capability_id") or "")
        cap_status = str(item.get("status") or "")
        if cap_status in {"planned", "not_configured", "host_only", "available_with_permission"}:
            notes.append(f"{capability}:{cap_status}")
    return _ordered_unique(notes)


def _axis(metadata: JsonObject, key: str, default: str) -> str:
    axes = metadata.get("state_axes")
    if isinstance(axes, dict):
        value = axes.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _task_lifecycle(*, status: str) -> str:
    if status in {"blocked", "needs_permission", "needs_review", "invalid"}:
        return "blocked"
    if status in {"needs_user_input", "needs_clarification"}:
        return "ask_user_pending"
    if status in {"failed", "error"}:
        return "failed"
    return "new_task"


def _intent_scope(*, intent_kind: str, activity: str, autonomy: str, route_class: str) -> str:
    text = f"{intent_kind} {activity} {autonomy}".lower()
    if "long_running" in autonomy or "monitor" in text:
        return "long_running_monitor"
    if activity == "research" and any(marker in text for marker in ("open", "market", "competitive", "fundamental")):
        return "open_ended_research"
    if "compound" in text or "workflow" in text or "automation" in text:
        return "compound_task"
    if route_class in {"host_boundary", "planned_or_not_configured_boundary", "host_only_boundary"}:
        return "operator_handoff"
    return "single_turn"


def _tooling_state(*, permission_state: str, route_class: str, capabilities: list[str]) -> str:
    if not capabilities:
        return "respond_only"
    if route_class == "executable_tool":
        return "host_tool_available"
    if permission_state in {"network_permission_required", "write_permission_required", "read_allowed"}:
        return "permission_required"
    if permission_state == "not_configured":
        return "not_configured"
    if permission_state in {"planned", "host_only", "dangerous_blocked"}:
        return "planned"
    return "respond_only"


def _memory_state(*, domain: str, capabilities: list[str]) -> str:
    text = " ".join([domain, *capabilities]).lower()
    if "durable_memory.commit" in capabilities or "durable_memory.delete" in capabilities:
        return "proposal_pending"
    if "durable_memory" in text or domain == "memory":
        return "committed_snapshot" if any(marker in text for marker in ("read", "search", "recall")) else "proposal_pending"
    return "ephemeral_thread"


def _resident_state(*, domain: str, status: str, activity: str) -> str:
    if status in {"needs_user_input", "needs_clarification"}:
        return "waiting_for_user"
    if domain == "resident" or activity == "monitor":
        return "queued_message"
    return "interactive_turn"


def _network_state(
    *,
    domain: str,
    families: list[str],
    permission_state: str,
    route_class: str,
    capabilities: list[str],
) -> str:
    text = " ".join([domain, *families, *capabilities]).lower()
    if route_class in {"host_boundary", "host_only_boundary"}:
        return "blocked_by_policy"
    if "web.search" in capabilities and permission_state == "not_configured":
        return "generic_search_configured"
    if "retrieval" in families or domain in {"retrieval", "finance", "legal"}:
        if "finance.source_directory" in capabilities or domain == "finance":
            return "structured_source_candidates"
        if permission_state == "network_permission_required":
            return "live_fetch_allowlisted"
    if any(marker in text for marker in ("transport", "browser", "cloud", "database")):
        return "blocked_by_policy" if permission_state in {"planned", "not_configured"} else "live_fetch_allowlisted"
    return "offline"


def _artifact_state(*, domain: str, families: list[str], output_contract: str) -> str:
    if output_contract == "file_artifact":
        return "generated"
    if domain in {"artifact", "document", "product"} or any(family in {"artifact", "document"} for family in families):
        return "generated"
    return "none"


def _external_system_state(*, domain: str, families: list[str], permission_state: str) -> str:
    if domain in {"transport", "security"} or any(family in {"transport", "security"} for family in families):
        return "credential_required"
    if domain in {"calendar", "cloud", "database"} or any(
        family in {"calendar", "cloud", "database"} for family in families
    ):
        return "operator_approval_required" if permission_state in {"planned", "not_configured"} else "not_connected"
    if permission_state in {"planned", "not_configured"}:
        return "not_connected"
    return "not_connected"


def _domain_profile(*, intent_kind: str, domain: str, activity: str, capabilities: list[str]) -> str:
    text = " ".join([intent_kind, domain, activity, *capabilities]).lower()
    if "finance.market_news" in capabilities or "market_news" in text:
        return "market_news"
    if "finance.macro_data" in capabilities or "macro_data" in text or "economic_indicator" in text:
        return "macro_data_research"
    if domain == "finance" and "competitive" in text:
        return "competitive_intelligence"
    if domain == "finance":
        return "finance_fundamentals"
    if domain == "legal":
        if "contract" in text:
            return "contract_review"
        return "legal_research"
    if domain == "medical":
        return "medical_information"
    if domain == "education":
        return "education_tutoring"
    if domain == "communication":
        return "communication_drafting"
    if domain == "operations":
        return "operations_planning"
    if domain == "product":
        return "product_analysis"
    if domain == "cybersecurity":
        return "cybersecurity_review"
    if domain == "data":
        return "data_analysis"
    if domain == "database":
        return "database_query"
    if domain == "cloud":
        return "cloud_or_devops_boundary"
    if domain == "workflow":
        return "workflow_automation"
    if domain == "knowledge_base":
        return "knowledge_base_maintenance"
    if domain == "multimodal":
        return "multimodal_analysis"
    if domain == "creative" or "roleplay" in text:
        return "creative_or_roleplay"
    if domain == "code":
        return "software_engineering"
    if domain == "risk":
        return "risk_compliance_review"
    return "general"


def _user_control(*, status: str) -> str:
    if status == "interrupted":
        return "interrupted"
    if status == "cancelled":
        return "cancelled"
    if status in {"needs_user_input", "needs_clarification"}:
        return "clarification_requested"
    return "normal"


def _world_model(*, domain: str, families: list[str], execution_surface: str, resource: str) -> str:
    if domain == "finance":
        return "market_state"
    if execution_surface == "retrieval" or "retrieval" in families:
        return "web_corpus"
    if execution_surface == "workspace" or resource == "local_file":
        return "workspace_project"
    if execution_surface == "durable_memory" or domain == "memory":
        return "durable_memory_snapshot"
    if execution_surface in {"external_account_boundary", "transport_gateway"}:
        return "external_account_boundary"
    if execution_surface == "media_input":
        return "media_input"
    if execution_surface in {"database_connector", "cloud_connector", "external_api"}:
        return "database_or_cloud_boundary"
    if execution_surface == "workflow_engine":
        return "workflow_engine"
    if execution_surface == "system_state":
        return "current_conversation"
    if resource == "device_boundary":
        return "physical_world_unavailable"
    return "current_conversation"


def _temporal_state(*, intent_kind: str, capabilities: list[str]) -> str:
    text = " ".join([intent_kind, *capabilities]).lower()
    if "system.time" in capabilities or "time" in text:
        return "current_time"
    if any(marker in text for marker in ("news", "market", "today", "recent")):
        return "recent_news"
    if any(marker in text for marker in ("calendar", "reminder", "schedule")):
        return "scheduled_future"
    if any(marker in text for marker in ("resident", "monitor", "long_running")):
        return "long_running"
    if "historical" in text:
        return "historical_period"
    return "timeless"


def _authority_state(
    *,
    domain: str,
    families: list[str],
    evidence_posture: str,
    execution_surface: str,
    capabilities: list[str],
) -> str:
    if domain == "finance" or "finance.fundamentals_research" in capabilities:
        return "primary_source_required"
    if evidence_posture == "citations_required":
        return "retrieval_citation"
    if execution_surface == "workspace":
        return "workspace_evidence"
    if domain in {"conversation", "creative", "education"}:
        return "user_provided"
    if "system" in families:
        return "self_knowledge"
    return "not_needed"


def _identity_boundary(*, intent_kind: str, domain: str, capabilities: list[str]) -> str:
    text = " ".join([intent_kind, domain, *capabilities]).lower()
    if "private_reasoning" in text or "chain_of_thought" in text:
        return "private_reasoning_blocked"
    if "roleplay" in text or "roleplay.perform" in capabilities:
        return "roleplay_persona"
    if domain in {"legal", "medical", "finance"}:
        return "professional_domain_role"
    if "self" in text or "identity" in text or "capability" in text:
        return "tool_capability_disclosure"
    return "assistant_self_description"


def _goal_structure(*, intent_kind: str, activity: str, autonomy: str, route_class: str) -> str:
    text = f"{intent_kind} {activity} {autonomy} {route_class}".lower()
    if any(marker in text for marker in ("physical", "device", "human_world")):
        return "human_world_request"
    if any(marker in text for marker in ("resident", "monitor", "background")):
        return "background_monitor"
    if any(marker in text for marker in ("schedule", "recurring", "reminder")):
        return "recurring"
    if any(marker in text for marker in ("open", "research", "investigate", "explore")):
        return "open_ended"
    if any(marker in text for marker in ("compound", "workflow", "multi_step", "automation")):
        return "compound_ordered"
    return "atomic"


def _dependency_state(
    *,
    metadata: JsonObject,
    evidence_posture: str,
    execution_surface: str,
    permission_state: str,
    status: str,
) -> str:
    depends_on = metadata.get("depends_on")
    if isinstance(depends_on, list) and depends_on:
        return "depends_on_prior_step"
    if status in {"needs_user_input", "needs_clarification"}:
        return "depends_on_user_input"
    if permission_state in {"dangerous_blocked", "host_only"}:
        return "depends_on_permission"
    if permission_state in {"planned", "not_configured"}:
        return "depends_on_unconfigured_connector"
    if evidence_posture in {"evidence_required", "citations_required", "partial", "insufficient"} or execution_surface == "retrieval":
        return "depends_on_external_data"
    if permission_state in {"network_permission_required", "write_permission_required", "dangerous_blocked", "host_only"}:
        return "depends_on_permission"
    return "none"


def _commitment_state(*, activity: str, permission_state: str, status: str) -> str:
    if status == "cancelled":
        return "cancelled_commitment"
    if status in {"completed", "final_answer"}:
        return "completed_commitment"
    if permission_state in {"write_permission_required", "network_permission_required", "dangerous_blocked", "host_only", "planned", "not_configured"}:
        return "pending_user_approval"
    if activity in {"write", "monitor", "plan"}:
        return "drafting_commitment"
    return "none"


def _preference_state(*, domain: str, capabilities: list[str]) -> str:
    text = " ".join([domain, *capabilities]).lower()
    if "preference.apply" in capabilities:
        return "thread_preference"
    if "durable_memory.commit" in capabilities:
        return "durable_preference_candidate"
    if "durable_memory" in text and any(marker in text for marker in ("read", "search", "recall")):
        return "durable_preference_applied"
    if "conflict" in text and "preference" in text:
        return "preference_conflict"
    return "not_relevant"


def _memory_scope(*, domain: str, capabilities: list[str], memory_state: str) -> str:
    text = " ".join([domain, *capabilities]).lower()
    if memory_state == "committed_snapshot":
        return "durable_snapshot"
    if memory_state == "proposal_pending":
        return "proposal_shadow"
    if "durable_memory.delete" in capabilities or "durable_memory.export" in capabilities:
        return "admin_review"
    if "thread" in text or "summary" in text:
        return "thread_summary"
    return "current_turn"


def _planning_depth(*, intent_kind: str, activity: str, autonomy: str, route_class: str) -> str:
    text = f"{intent_kind} {activity} {autonomy} {route_class}".lower()
    if route_class in {"host_boundary", "planned_or_not_configured_boundary", "host_only_boundary"}:
        return "operator_review_plan"
    if "resident" in text or "monitor" in text:
        return "resident_plan"
    if "research" in text:
        return "research_plan"
    if any(marker in text for marker in ("compound", "workflow", "automation", "plan")):
        return "multi_step_plan"
    if activity in {"respond", "read", "write", "analyze", "teach"}:
        return "single_action"
    return "none"


def _operation_runtime(*, intent_kind: str, activity: str, autonomy: str, domain: str) -> str:
    text = f"{intent_kind} {activity} {autonomy} {domain}".lower()
    if "scheduled" in text or "calendar" in text or "reminder" in text:
        return "scheduled"
    if "resident" in text:
        return "resident"
    if "long_running" in text or "monitor" in text:
        return "long_running"
    if any(marker in text for marker in ("workflow", "operator", "handoff")):
        return "external_handoff"
    if autonomy == "bounded_task_loop" or activity in {"research", "write", "analyze", "plan"}:
        return "bounded_loop"
    return "instant"


def _quality_bar(*, domain: str, activity: str, evidence_posture: str, authority: str) -> str:
    if domain in {"legal", "medical", "finance", "risk", "cybersecurity"}:
        return "regulated_domain"
    if authority in {"primary_source_required", "conflicting_sources"} or evidence_posture == "citations_required":
        return "audit_ready"
    if activity in {"research", "analyze", "review", "plan"} or evidence_posture == "evidence_required":
        return "rigorous"
    if domain in {"creative", "communication"}:
        return "casual"
    return "standard"


def _interruption_policy(*, permission_state: str, route_class: str) -> str:
    if route_class in {"host_boundary", "host_only_boundary", "planned_or_not_configured_boundary"}:
        return "operator_approval_required"
    if permission_state == "write_permission_required":
        return "ask_before_side_effect"
    if permission_state in {"network_permission_required", "read_allowed", "none_required"}:
        return "ask_only_if_blocked"
    return "user_can_interrupt"


def _family_for(value: str) -> str:
    lowered = value.lower()
    for family, markers in _FAMILY_BY_MARKER.items():
        if any(marker in lowered for marker in markers):
            return family
    return "conversation"


def _status_for(capability: str) -> str:
    if capability in SAFE_SEMANTIC_CAPABILITIES:
        return "enabled"
    if capability.startswith(
        (
            "transport.",
            "live_transport:",
            "calendar.",
            "browser.",
            "device.",
            "credential.",
            "secret.",
            "database.",
            "cloud.",
            "workflow.automation.run",
            "knowledge_base.",
            "multimodal.",
        )
    ):
        return "planned"
    return "not_configured"


def _tool_for(capability: str) -> str | None:
    if capability in {"retrieval.run", "web.research"}:
        return "retrieval.run"
    if capability in {"file.read", "workspace.file.read"}:
        return "file.read"
    if capability in {"workspace.write", "workspace.file.write", "workspace:write"}:
        return "workspace.write"
    if capability == "system.time":
        return "system.time"
    return None


def _side_effect_for(capability: str) -> str:
    if any(marker in capability for marker in ("write", "schedule", "send", "patch", "maintain", "deploy")):
        return "write"
    if any(marker in capability for marker in ("web.", "network", "transport", "browser")):
        return "network"
    if any(marker in capability for marker in ("device", "shell")):
        return "destructive"
    if any(marker in capability for marker in ("read", "search", "time", "status", "query", "inspect", "analyze", "ocr")):
        return "read"
    return "none"


def _permissions_for(capability: str) -> list[str]:
    if any(marker in capability for marker in ("web.", "network", "transport", "browser")):
        return ["network:fetch"]
    if any(marker in capability for marker in ("workspace.write", "workspace:write", "patch")):
        return ["workspace:write"]
    if "calendar" in capability:
        return ["calendar:write"]
    if "database" in capability:
        return ["database:read"]
    if "cloud" in capability:
        return ["cloud:read"]
    if "workflow.automation.run" in capability:
        return ["workflow:run"]
    if "knowledge_base.maintain" in capability:
        return ["knowledge_base:write"]
    if "knowledge_base" in capability:
        return ["knowledge_base:read"]
    if "multimodal" in capability:
        return ["multimodal:read"]
    if "device" in capability:
        return ["device:control"]
    if "secret" in capability or "credential" in capability:
        return ["secret:read"]
    return []


def _metadata_or_default(metadata: JsonObject, key: str, default: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _strings_from_profiles(profiles: list[JsonObject], key: str) -> list[str]:
    return [str(profile[key]) for profile in profiles if isinstance(profile.get(key), str) and profile.get(key)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
