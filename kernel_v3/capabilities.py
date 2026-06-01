from __future__ import annotations

from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject, ToolManifest


SAFE_SEMANTIC_CAPABILITIES = frozenset(
    {
        "conversation.respond",
        "user.ask",
        "roleplay.perform",
        "knowledge.explain",
        "analysis.reason",
        "document.draft",
        "document.review",
        "report.compose",
        "email.draft",
        "web.research",
        "finance.fundamentals_research",
        "finance.market_news",
        "finance.market_data",
        "finance.competitive_landscape",
        "finance.source_directory",
        "retrieval.run",
        "workspace.search",
        "file.read",
        "workspace.write",
        "workspace:read",
        "workspace:write",
        "durable_memory.read",
        "durable_memory.search",
        "durable_memory.propose",
        "artifact.create",
        "artifact.read",
        "data.table.analyze",
        "chart.generate",
        "project.plan",
        "project.status",
        "system.time",
    }
)


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
        "catalog_rule": (
            "Choose semantic intent labels freely, but use these capability ids "
            "for executable or blocked host boundaries. Planned/host_only "
            "capabilities describe state and future surfaces; they are not tools."
        ),
        "state_dimensions": {
            "task_lifecycle": ["new_task", "continue_task", "ask_user_pending", "finalizing", "failed", "blocked"],
            "workloop": ["planning", "executing", "observing", "evaluating_progress", "replanning", "terminating"],
            "intent_scope": ["single_turn", "compound_task", "open_ended_research", "long_running_monitor", "operator_handoff"],
            "execution_surface": [
                "conversation",
                "retrieval",
                "workspace",
                "artifact",
                "durable_memory",
                "resident_queue",
                "transport_gateway",
                "browser_session",
                "system_state",
                "external_api",
                "human_world_unavailable",
            ],
            "evidence": ["not_required", "needed", "partial", "sufficient", "insufficient", "conflicting"],
            "tooling": ["respond_only", "host_tool_available", "permission_required", "not_configured", "planned"],
            "permissions": ["none_required", "read_allowed", "write_permission_required", "network_permission_required", "dangerous_blocked"],
            "memory": ["ephemeral_thread", "proposal_pending", "committed_snapshot", "deleted_or_expired"],
            "resident": ["interactive_turn", "queued_message", "scheduled_job", "waiting_for_user"],
            "network": ["offline", "structured_source_candidates", "live_fetch_allowlisted", "generic_search_configured", "blocked_by_policy"],
            "artifacts": ["none", "generated", "stored_blob", "redacted_preview", "exported"],
            "external_systems": ["not_connected", "transport_planned", "credential_required", "operator_approval_required"],
            "domain_profile": [
                "general",
                "finance_fundamentals",
                "technical_research",
                "market_news",
                "competitive_intelligence",
                "legal_research",
                "medical_information",
                "data_analysis",
                "creative_or_roleplay",
                "software_engineering",
            ],
            "output_contract": ["plain_answer", "cited_answer", "file_artifact", "structured_report", "failure_report", "ask_user"],
            "user_control": ["normal", "interrupted", "cancelled", "clarification_requested"],
        },
        "task_domains": [
            "conversation",
            "roleplay",
            "technical_reasoning",
            "retrieval_research",
            "finance_fundamentals",
            "market_news_research",
            "market_data_research",
            "competitive_intelligence",
            "financial_modeling",
            "document_drafting",
            "document_review",
            "report_generation",
            "email_drafting",
            "legal_research",
            "contract_review",
            "medical_information",
            "education_tutoring",
            "creative_writing",
            "code_review",
            "code_editing",
            "test_execution",
            "data_analysis",
            "spreadsheet_or_table_work",
            "project_management",
            "workspace_read",
            "workspace_write",
            "artifact_generation",
            "memory_admin",
            "knowledge_recall",
            "resident_operations",
            "long_running_monitoring",
            "transport_operations",
            "calendar_or_reminder",
            "notification_or_message_send",
            "browser_navigation_boundary",
            "external_api_integration",
            "system_observation",
            "environment_diagnostics",
            "credential_or_secret_boundary",
            "security_boundary",
            "physical_world_unavailable",
        ],
        "semantic_slots": {
            "domain": "what area the user task belongs to",
            "activity": "what the agent should do: answer, research, draft, inspect, monitor, write, route, or refuse",
            "resource": "what object is being worked on: web source, file, artifact, memory item, queue message, transport, device, or external API",
            "capability": "host-visible capability id requested by the model packet",
            "permission": "host-owned permission or configuration boundary",
            "evidence": "whether cited retrieval/workspace/artifact evidence is needed",
            "output": "final answer, ask_user, artifact, failure report, or pending resident output",
        },
        "capability_statuses": [
            "enabled",
            "available_with_permission",
            "disabled",
            "not_configured",
            "planned",
            "host_only",
        ],
        "families": {
            "conversation": [
                "conversation.respond",
                "user.ask",
                "roleplay.perform",
                "knowledge.explain",
                "analysis.reason",
            ],
            "workspace": ["workspace.search", "workspace.file.read", "workspace.file.write"],
            "retrieval": ["retrieval.run", "web.research", "web.search", "web.fetch", "web.crawl", "browser.page.open"],
            "finance": [
                "finance.fundamentals_research",
                "finance.market_news",
                "finance.source_directory",
                "finance.market_data",
                "finance.competitive_landscape",
            ],
            "memory": ["durable_memory.read", "durable_memory.search", "durable_memory.propose", "durable_memory.commit", "durable_memory.delete", "durable_memory.export"],
            "artifact": ["artifact.create", "artifact.read", "artifact.export"],
            "document": ["document.draft", "document.review", "report.compose", "email.draft"],
            "data": ["data.table.analyze", "data.transform", "chart.generate"],
            "code": ["code.search", "code.read", "code.patch", "test.run"],
            "project": ["project.plan", "project.status", "task.queue"],
            "resident": ["resident.inbox", "resident.outbox", "resident.scheduler", "resident.monitor"],
            "transport": ["transport.wechat", "transport.discord", "transport.slack", "transport.email"],
            "calendar": ["calendar.read", "calendar.schedule", "reminder.create"],
            "system": ["system.time", "system.environment", "system.process", "shell.exec"],
            "security": ["credential.read", "secret.store", "browser.session.attach", "device.input.control"],
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
            "browser.page.open",
            "finance.market_news",
            "finance.market_data",
            "shell.exec",
            "live_transport:*",
            "durable_memory.commit",
            "durable_memory.delete",
            "transport.*",
            "calendar.schedule",
            "credential.read",
            "secret.store",
            "device.input.control",
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
            capability_id="roleplay.perform",
            family="conversation",
            status="enabled",
            description="Answer in a user-requested role or persona inside the current thread.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="knowledge.explain",
            family="conversation",
            status="enabled",
            description="Explain general knowledge from model reasoning without tool execution.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="analysis.reason",
            family="conversation",
            status="enabled",
            description="Perform bounded reasoning from the current prompt/context without exposing private chain-of-thought.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="document.draft",
            family="document",
            status="enabled",
            description="Draft user-visible text in the response; file writes still require workspace.write.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="document.review",
            family="document",
            status="enabled",
            description="Review provided text or context and return comments without mutating files.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="report.compose",
            family="document",
            status="enabled",
            description="Compose a structured report in the response from available context/evidence.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="email.draft",
            family="document",
            status="enabled",
            description="Draft an email/message body in the response without sending it.",
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
            capability_id="finance.market_news",
            family="finance",
            status="available_with_permission",
            description="Current market news research with source/date constraints through retrieval.run and configured source/fetch providers.",
            side_effect_class="network",
            permissions_required=["network:fetch"],
        ),
        CapabilitySpec(
            capability_id="finance.market_data",
            family="finance",
            status="available_with_permission",
            description="Market price, quote, and time-series research through approved retrieval or market-data providers.",
            side_effect_class="network",
            permissions_required=["network:fetch"],
        ),
        CapabilitySpec(
            capability_id="finance.competitive_landscape",
            family="finance",
            status="enabled",
            description="Research a company's competitive landscape through grounded retrieval when sources are required.",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            metadata={"research_profile_id": "finance_fundamentals"},
        ),
        CapabilitySpec(
            capability_id="web.research",
            family="retrieval",
            status="available_with_permission",
            description="General web research through retrieval.run when a search/fetch provider is configured.",
            tool_name="retrieval.run",
            side_effect_class="network",
            permissions_required=["network:fetch"],
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
            capability_id="browser.page.open",
            family="retrieval",
            status="planned",
            description="Open and inspect a browser/page representation through a bounded page provider.",
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
            capability_id="durable_memory.search",
            family="memory",
            status="enabled",
            description="Recall committed durable memory through host-scoped context injection and memory admin APIs.",
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
            capability_id="durable_memory.delete",
            family="memory",
            status="host_only",
            description="Delete or tombstone committed memory through explicit user/admin action.",
            permissions_required=["durable_memory:delete"],
        ),
        CapabilitySpec(
            capability_id="durable_memory.export",
            family="memory",
            status="host_only",
            description="Export durable memory and provenance for audit.",
            permissions_required=["durable_memory:export"],
        ),
        CapabilitySpec(
            capability_id="artifact.create",
            family="artifact",
            status="enabled",
            description="Create host-visible generated artifacts through approved response or workspace-write paths.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="artifact.read",
            family="artifact",
            status="enabled",
            description="Read artifact previews and references already exposed by the host context.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="artifact.export",
            family="artifact",
            status="planned",
            description="Export artifact bundles through a host-approved export surface.",
            side_effect_class="write",
            permissions_required=["artifact:export"],
        ),
        CapabilitySpec(
            capability_id="data.table.analyze",
            family="data",
            status="planned",
            description="Analyze structured tables or datasets through bounded data tools.",
            side_effect_class="read",
        ),
        CapabilitySpec(
            capability_id="data.transform",
            family="data",
            status="planned",
            description="Transform structured data into derived files or artifacts under host policy.",
            side_effect_class="write",
            permissions_required=["workspace:write"],
        ),
        CapabilitySpec(
            capability_id="chart.generate",
            family="data",
            status="planned",
            description="Generate chart artifacts from grounded data.",
            side_effect_class="write",
            permissions_required=["workspace:write"],
        ),
        CapabilitySpec(
            capability_id="code.search",
            family="code",
            status="available_with_permission",
            description="Search repository code through workspace search.",
            tool_name="workspace.search",
            side_effect_class="read",
        ),
        CapabilitySpec(
            capability_id="code.read",
            family="code",
            status="available_with_permission",
            description="Read repository code through file.read.",
            tool_name="file.read",
            side_effect_class="read",
        ),
        CapabilitySpec(
            capability_id="code.patch",
            family="code",
            status="planned",
            description="Apply code patches through a bounded edit tool with diff review.",
            side_effect_class="write",
            permissions_required=["workspace:write"],
        ),
        CapabilitySpec(
            capability_id="test.run",
            family="code",
            status="planned",
            description="Run tests through an allowlisted command runner.",
            side_effect_class="shell",
            permissions_required=["shell:exec"],
        ),
        CapabilitySpec(
            capability_id="project.plan",
            family="project",
            status="enabled",
            description="Maintain a host-visible task plan for the current run.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="project.status",
            family="project",
            status="enabled",
            description="Report current task, run, thread, and plan status from journal-derived state.",
            enabled_by_default=True,
        ),
        CapabilitySpec(
            capability_id="task.queue",
            family="project",
            status="host_only",
            description="Represent queued resident or scheduled tasks without letting the model mutate the queue directly.",
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
            capability_id="resident.monitor",
            family="resident",
            status="planned",
            description="Monitor local resident worker health and queued work.",
        ),
        CapabilitySpec(
            capability_id="transport.wechat",
            family="transport",
            status="planned",
            description="External WeChat transport integration. Not a kernel decision layer.",
            permissions_required=["live_transport:wechat"],
        ),
        CapabilitySpec(
            capability_id="transport.discord",
            family="transport",
            status="planned",
            description="External Discord transport integration. Not a kernel decision layer.",
            permissions_required=["live_transport:discord"],
        ),
        CapabilitySpec(
            capability_id="transport.slack",
            family="transport",
            status="planned",
            description="External Slack transport integration. Not a kernel decision layer.",
            permissions_required=["live_transport:slack"],
        ),
        CapabilitySpec(
            capability_id="transport.email",
            family="transport",
            status="planned",
            description="External email transport integration through a host gateway.",
            permissions_required=["live_transport:email"],
        ),
        CapabilitySpec(
            capability_id="calendar.read",
            family="calendar",
            status="planned",
            description="Read calendar state through an approved calendar connector.",
            side_effect_class="read",
            permissions_required=["calendar:read"],
        ),
        CapabilitySpec(
            capability_id="calendar.schedule",
            family="calendar",
            status="planned",
            description="Create or update calendar events through an approved connector.",
            side_effect_class="write",
            permissions_required=["calendar:write"],
        ),
        CapabilitySpec(
            capability_id="reminder.create",
            family="calendar",
            status="planned",
            description="Create reminders through the resident scheduler or future calendar connector.",
            side_effect_class="write",
            permissions_required=["resident:schedule"],
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
            capability_id="system.process",
            family="system",
            status="planned",
            description="Read bounded process/runtime diagnostics without exposing secrets.",
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
        CapabilitySpec(
            capability_id="credential.read",
            family="security",
            status="host_only",
            description="Read credentials only through host-owned secret providers; model-visible context never receives raw secrets.",
            permissions_required=["secret:read"],
        ),
        CapabilitySpec(
            capability_id="secret.store",
            family="security",
            status="host_only",
            description="Store secrets only through a dedicated host secret store, not journal or memory.",
            permissions_required=["secret:write"],
        ),
        CapabilitySpec(
            capability_id="browser.session.attach",
            family="security",
            status="planned",
            description="Attach to a user browser/session only through explicit host authorization.",
            side_effect_class="network",
            permissions_required=["browser:attach"],
        ),
        CapabilitySpec(
            capability_id="device.input.control",
            family="security",
            status="planned",
            description="Control local mouse/keyboard or physical devices only through a future high-risk operator.",
            side_effect_class="destructive",
            permissions_required=["device:control"],
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
