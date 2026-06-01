from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject, ToolManifest


@dataclass(frozen=True, kw_only=True)
class CapabilitySpec(Contract):
    capability_id: str
    family: str
    status: str
    description: str
    tool_name: str | None = None
    side_effect_class: str = "none"
    permissions_required: list[str] = field(default_factory=list)
    enabled_by_default: bool = False
    metadata: JsonObject = field(default_factory=dict)


def capability_catalog(
    *,
    tool_manifests: list[ToolManifest] | None = None,
    allowed_tools: list[str] | None = None,
    allowed_permissions: set[str] | None = None,
    mode: str | None = None,
) -> JsonObject:
    manifests = {manifest.name: manifest for manifest in tool_manifests or []}
    allowed_tool_set = set(allowed_tools or [])
    allowed_permission_set = set(allowed_permissions or set())
    specs = _base_capabilities()
    specs.extend(_tool_capabilities(manifests, allowed_tool_set, allowed_permission_set))
    return {
        "version": 1,
        "mode": mode,
        "families": _family_summary(specs),
        "capabilities": [spec.to_dict() for spec in specs],
        "executable_tools": [
            spec.tool_name
            for spec in specs
            if spec.tool_name and spec.status in {"enabled", "available_with_permission"}
        ],
        "not_configured": [spec.capability_id for spec in specs if spec.status == "not_configured"],
        "planned": [spec.capability_id for spec in specs if spec.status == "planned"],
    }


def semantic_capability_catalog() -> JsonObject:
    return {
        "modes": ["direct_answer", "retrieval_answer", "workspace_answer", "workspace_write", "system_answer", "clarify_first"],
        "core_rule": "The model proposes capabilities/actions; the host validates policy, executes tools, journals, and stops.",
        "state_dimensions": {
            "task_lifecycle": ["new_task", "continue_task", "ask_user_pending", "finalizing", "failed", "blocked"],
            "evidence": ["not_required", "needed", "partial", "sufficient", "insufficient", "conflicting"],
            "tooling": ["respond_only", "host_tool_available", "permission_required", "not_configured", "planned"],
            "memory": ["ephemeral_thread", "proposal_pending", "committed_snapshot", "deleted_or_expired"],
            "resident": ["interactive_turn", "queued_message", "scheduled_job", "waiting_for_user"],
            "user_control": ["normal", "interrupted", "cancelled", "clarification_requested"],
        },
        "task_domains": [
            "conversation",
            "roleplay",
            "technical_reasoning",
            "retrieval_research",
            "finance_fundamentals",
            "workspace_read",
            "workspace_write",
            "artifact_generation",
            "memory_admin",
            "resident_operations",
            "transport_operations",
            "system_observation",
            "security_boundary",
            "physical_world_unavailable",
        ],
        "capability_statuses": [
            "enabled",
            "available_with_permission",
            "disabled",
            "not_configured",
            "planned",
            "host_only",
        ],
        "families": {
            "conversation": ["conversation.respond", "user.ask"],
            "workspace": ["workspace.search", "workspace.file.read", "workspace.file.write"],
            "retrieval": ["retrieval.run", "web.search", "web.fetch", "web.crawl"],
            "finance": ["finance.fundamentals_research", "finance.source_directory"],
            "memory": ["durable_memory.read", "durable_memory.propose", "durable_memory.commit"],
            "resident": ["resident.inbox", "resident.outbox", "resident.scheduler"],
            "transport": ["transport.wechat", "transport.discord", "transport.slack"],
            "system": ["system.time", "system.environment", "shell.exec"],
        },
        "executable_tools_by_recipe": {
            "retrieval_answer": ["retrieval.run"],
            "workspace_answer": ["workspace.search", "file.read"],
            "workspace_write": ["workspace.search", "file.read", "workspace.write"],
            "system_answer": ["system.time"],
            "direct_answer": [],
            "clarify_first": [],
        },
        "not_default_or_requires_configuration": [
            "web.search",
            "web.fetch",
            "web.crawl",
            "network.fetch",
            "shell.exec",
            "live_transport:*",
            "durable_memory.commit",
        ],
    }


def _base_capabilities() -> list[CapabilitySpec]:
    return [
        CapabilitySpec(
            capability_id="conversation.respond",
            family="conversation",
            status="enabled",
            description="Return a user-visible response through the host.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="user.ask",
            family="conversation",
            status="enabled",
            description="Ask the user for missing critical information.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="finance.fundamentals_research",
            family="finance",
            status="enabled",
            description="Use the finance fundamentals profile to prefer filings, exchange disclosures, company IR, and official statistics.",
            enabled_by_default=True,
            metadata={"research_profile_id": "finance_fundamentals"},
        ),
        CapabilitySpec(
            capability_id="finance.source_directory",
            family="finance",
            status="enabled",
            description="Describe authoritative source families and where the agent should search for fundamentals evidence.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="workspace.file.write",
            family="workspace",
            status="available_with_permission",
            description="Write workspace files through host policy and artifact/journal redaction.",
            tool_name="workspace.write",
            side_effect_class="write",
            permissions_required=["workspace:write"],
        ),
        CapabilitySpec(
            capability_id="web.search",
            family="retrieval",
            status="not_configured",
            description="Live web search provider. Requires explicit endpoint/provider configuration.",
            side_effect_class="network",
            permissions_required=["network:fetch"],
        ),
        CapabilitySpec(
            capability_id="web.fetch",
            family="retrieval",
            status="available_with_permission",
            description="Fetch a host-approved URL through bounded HTTP fetch providers.",
            tool_name="network.fetch",
            side_effect_class="network",
            permissions_required=["network:fetch"],
        ),
        CapabilitySpec(
            capability_id="web.crawl",
            family="retrieval",
            status="planned",
            description="Bounded crawl/page expansion capability for research workflows.",
            side_effect_class="network",
            permissions_required=["network:fetch"],
        ),
        CapabilitySpec(
            capability_id="durable_memory.read",
            family="memory",
            status="host_only",
            description="Read committed durable memory into context snapshots.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="durable_memory.propose",
            family="memory",
            status="enabled",
            description="Create reviewable memory proposals from semantic intake and observations.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="durable_memory.commit",
            family="memory",
            status="host_only",
            description="Commit approved memory proposals. The model cannot directly commit memory.",
            permissions_required=["durable_memory:write"],
        ),
        CapabilitySpec(
            capability_id="resident.inbox",
            family="resident",
            status="enabled",
            description="Queue incoming local resident messages.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="resident.outbox",
            family="resident",
            status="enabled",
            description="Record resident outputs for delivery/acknowledgement.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="resident.scheduler",
            family="resident",
            status="enabled",
            description="Run local scheduled resident jobs through the host queue.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="transport.wechat",
            family="transport",
            status="planned",
            description="External WeChat transport integration. Not a kernel decision layer.",
            permissions_required=["live_transport:wechat"],
        ),
        CapabilitySpec(
            capability_id="system.time",
            family="system",
            status="enabled",
            description="Host time tool for current time and timezone-aware responses.",
            tool_name="system.time",
            side_effect_class="read",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="system.environment",
            family="system",
            status="planned",
            description="Safe environment diagnostics with secret redaction.",
            side_effect_class="read",
        ),
        CapabilitySpec(
            capability_id="shell.exec",
            family="system",
            status="available_with_permission",
            description="Bounded shell execution with explicit executable allowlist.",
            tool_name="shell.exec",
            side_effect_class="shell",
            permissions_required=["shell:exec"],
        ),
    ]


def _tool_capabilities(
    manifests: dict[str, ToolManifest],
    allowed_tools: set[str],
    allowed_permissions: set[str],
) -> list[CapabilitySpec]:
    result: list[CapabilitySpec] = []
    mappings = {
        "retrieval.run": ("retrieval.run", "retrieval", "Run bounded retrieval FSM and produce evidence/citations."),
        "workspace.search": ("workspace.search", "workspace", "Search workspace files."),
        "file.read": ("workspace.file.read", "workspace", "Read a workspace file."),
        "workspace.write": ("workspace.file.write", "workspace", "Write a workspace file under host policy."),
        "network.fetch": ("web.fetch", "retrieval", "Fetch a URL through a bounded network tool."),
        "shell.exec": ("shell.exec", "system", "Execute an allowlisted shell command."),
        "system.time": ("system.time", "system", "Read current host time with an explicit timezone."),
    }
    for tool_name, manifest in manifests.items():
        capability_id, family, description = mappings.get(
            tool_name,
            (f"tool.{tool_name}", manifest.resource_kind or "tool", manifest.description),
        )
        required = set(manifest.permissions_required)
        allowed = not required or required.issubset(allowed_permissions) or tool_name in allowed_tools
        if not manifest.enabled:
            status = "disabled"
        elif allowed:
            status = "enabled"
        else:
            status = "available_with_permission"
        result.append(
            CapabilitySpec(
                capability_id=capability_id,
                family=family,
                status=status,
                description=description,
                tool_name=tool_name,
                side_effect_class=manifest.side_effect_class,
                permissions_required=list(manifest.permissions_required),
                enabled_by_default=manifest.enabled and status == "enabled",
                metadata={
                    "resource_kind": manifest.resource_kind,
                    "operator_kind": manifest.operator_kind,
                    "input_schema": manifest.input_schema,
                },
            )
        )
    return result


def _family_summary(specs: list[CapabilitySpec]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for spec in specs:
        family = summary.setdefault(spec.family, {})
        family[spec.status] = family.get(spec.status, 0) + 1
    return summary
