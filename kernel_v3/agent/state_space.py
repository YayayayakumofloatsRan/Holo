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
    "conversation": ("conversation", "roleplay", "knowledge", "analysis", "direct_answer", "noop"),
    "retrieval": ("retrieval", "web", "browser.page", "news", "research"),
    "finance": ("finance", "market", "filing", "fundamental", "competitive"),
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
    execution_surface = _metadata_or_default(metadata, "execution_surface", _execution_surface(domain, families))
    permission_state = _permission_state(capability_statuses, risk=risk)
    route_class = _route_class(capability_statuses, status=status)
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
        evidence_posture=_evidence_posture(evidence_required=evidence_required, citations_required=citations_required),
        output_contract=_output_contract(citations_required=citations_required, execution_surface=execution_surface, activity=activity),
        autonomy=_metadata_or_default(metadata, "autonomy", "bounded_task_loop" if activity in {"research", "read", "write", "monitor"} else "single_turn_response"),
        risk_posture=_risk_posture(risk=risk, permission_state=permission_state),
        notes=_notes(capability_statuses, status=status),
    )


def summarize_state_profiles(profiles: list[JsonObject]) -> JsonObject:
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
    }


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
    if any(marker in text for marker in ("write", "draft", "compose", "patch", "schedule", "send")):
        return "write"
    if any(marker in text for marker in ("read", "search", "recall", "status", "time")):
        return "read"
    if any(marker in text for marker in ("review", "analyze", "analysis", "reason")):
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


def _execution_surface(domain: str, families: list[str]) -> str:
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
