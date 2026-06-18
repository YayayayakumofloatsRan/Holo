from __future__ import annotations

import json
from pathlib import Path

from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import AgentRuntime, _planner_directive, task_recipe
from kernel_v3.contracts import CandidateAction, ContextBundle, JsonObject
from kernel_v3.context import ArtifactStore
from kernel_v3.finance import (
    CALENDAR_DAYS_BETWEEN_TOOL_NAME,
    CALCULATOR_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    FINANCE_SLOT_BIND_TOOL_NAME,
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    FINANCE_VERIFY_NUMERIC_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    PROVIDED_CONTEXT_PARSE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
)
from kernel_v3.finance.open_components import isolated_component_status
from kernel_v3.finance.tool_catalog import finance_toolchain_install_summary
from kernel_v3.policy import PolicyGate
from kernel_v3.processors.adapters import _compact_runtime_directive_for_provider, _planner_prompt
from kernel_v3.tool_use import ARTIFACT_QUERY_NAME, ARTIFACT_READ_NAME, TOOL_DISCOVERY_NAME


FINANCE_TOOL_READINESS_SCHEMA = "holo.kernel_v3.finance_tool_readiness.v1"

FB_FQA_TOOL_REQUIREMENTS: list[JsonObject] = [
    {
        "category_id": "financebench_filing_retrieval",
        "benchmark_families": ["FinanceBench"],
        "purpose": "official filing discovery, source URL acquisition, SEC/XBRL statement candidates",
        "required_tools": [
            TOOL_DISCOVERY_NAME,
            "retrieval.run",
            SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
            SEC_EDGAR_FINANCIALS_TOOL_NAME,
            ARTIFACT_READ_NAME,
            DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
            DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        ],
    },
    {
        "category_id": "financebench_filing_table_extraction",
        "benchmark_families": ["FinanceBench"],
        "purpose": "parse filing documents and tables before fact binding",
        "required_tools": [
            ARTIFACT_READ_NAME,
            DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
            DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
            DATA_TABLE_QUERY_TOOL_NAME,
            "workspace.write",
            "shell.exec",
            "script.exec",
        ],
    },
    {
        "category_id": "financebench_numeric_ratio_reasoning",
        "benchmark_families": ["FinanceBench"],
        "purpose": "DIO, turnover, margins, capital intensity, CAGR, basis-point and multi-input ratios",
        "required_tools": [
            FINANCE_SLOT_BIND_TOOL_NAME,
            CALCULATOR_TOOL_NAME,
            FINANCE_VERIFY_NUMERIC_TOOL_NAME,
            DATA_TABLE_QUERY_TOOL_NAME,
            MATH_SYMPY_COMPUTE_TOOL_NAME,
            CALENDAR_DAYS_BETWEEN_TOOL_NAME,
        ],
    },
    {
        "category_id": "financebench_market_or_macro_context",
        "benchmark_families": ["FinanceBench"],
        "purpose": "market, price, macro, currency, index, or non-filing fundamental context when the question demands it",
        "required_tools": [
            "retrieval.run",
            MARKET_OPENBB_FETCH_TOOL_NAME,
            CALCULATOR_TOOL_NAME,
            FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        ],
    },
    {
        "category_id": "finqa_report_context_numeric_reasoning",
        "benchmark_families": ["FinQA", "FQA"],
        "purpose": "provided report text/table reasoning with reference program kept scoring-only",
        "required_tools": [
            TOOL_DISCOVERY_NAME,
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            CALCULATOR_TOOL_NAME,
            FINANCE_SLOT_BIND_TOOL_NAME,
            FINANCE_VERIFY_NUMERIC_TOOL_NAME,
            DATA_TABLE_QUERY_TOOL_NAME,
            MATH_SYMPY_COMPUTE_TOOL_NAME,
        ],
    },
    {
        "category_id": "finqa_table_program_like_transforms",
        "benchmark_families": ["FinQA", "FQA"],
        "purpose": "model-selected table filtering, aggregation, arithmetic, and formula trace generation",
        "required_tools": [
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            DATA_TABLE_QUERY_TOOL_NAME,
            FINANCE_SLOT_BIND_TOOL_NAME,
            CALCULATOR_TOOL_NAME,
            MATH_SYMPY_COMPUTE_TOOL_NAME,
            FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        ],
    },
    {
        "category_id": "temporary_workbench_assembly",
        "benchmark_families": ["FinanceBench", "FinQA", "FQA"],
        "purpose": "model assembles a temporary workspace for parsers, normalized evidence, JSON facts, tables, and local checks",
        "required_tools": [
            TOOL_DISCOVERY_NAME,
            FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
            ARTIFACT_READ_NAME,
            DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            "workspace.list",
            "workspace.search",
            "file.read",
            "workspace.write",
            "shell.exec",
            "script.exec",
        ],
    },
]

TOOL_COMPONENT_BINDINGS: dict[str, JsonObject] = {
    TOOL_DISCOVERY_NAME: {"components": ["python"], "install_policy": "holo_core"},
    ARTIFACT_READ_NAME: {"components": ["python"], "install_policy": "holo_core"},
    ARTIFACT_QUERY_NAME: {"components": ["python"], "install_policy": "legacy_fallback_only"},
    "retrieval.run": {"components": [], "install_policy": "holo_core"},
    CALCULATOR_TOOL_NAME: {"components": ["python_decimal"], "install_policy": "holo_core"},
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME: {"components": ["python"], "install_policy": "holo_core"},
    FINANCE_SLOT_BIND_TOOL_NAME: {"components": ["pydantic"], "install_policy": "holo_core"},
    FINANCE_VERIFY_NUMERIC_TOOL_NAME: {"components": ["pydantic"], "install_policy": "holo_core"},
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME: {"components": ["edgartools"], "install_policy": "core_open_source"},
    SEC_EDGAR_FINANCIALS_TOOL_NAME: {"components": ["edgartools"], "install_policy": "core_open_source"},
    PROVIDED_CONTEXT_PARSE_TOOL_NAME: {"components": ["pandas", "lxml", "beautifulsoup4"], "install_policy": "core_open_source"},
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME: {"components": ["docling"], "install_policy": "isolated_optional_heavy"},
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME: {"components": ["trafilatura"], "install_policy": "core_open_source"},
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME: {"components": ["rank_bm25"], "install_policy": "core_open_source"},
    MARKET_OPENBB_FETCH_TOOL_NAME: {"components": ["openbb"], "install_policy": "isolated_optional_heavy"},
    DATA_TABLE_QUERY_TOOL_NAME: {"components": ["duckdb", "pandas"], "install_policy": "core_open_source"},
    MATH_SYMPY_COMPUTE_TOOL_NAME: {"components": ["sympy"], "install_policy": "core_open_source"},
    CALENDAR_DAYS_BETWEEN_TOOL_NAME: {"components": ["python"], "install_policy": "holo_core"},
    "workspace.list": {"components": ["python"], "install_policy": "holo_core"},
    "workspace.search": {"components": ["python"], "install_policy": "holo_core"},
    "file.read": {"components": ["python"], "install_policy": "holo_core"},
    "workspace.write": {"components": ["python"], "install_policy": "holo_core"},
    "shell.exec": {"components": ["python"], "install_policy": "holo_core"},
    "script.exec": {"components": ["python"], "install_policy": "holo_core"},
}

ISOLATED_OPTIONAL_COMPONENTS = {"docling", "openbb", "playwright", "crawl4ai", "langfuse", "phoenix", "promptfoo"}


def build_finance_tool_readiness_audit(
    *,
    execution_profile_id: str = "finance-capability",
    live_network: bool = True,
    workspace_root: Path | str | None = None,
    execute_local_smoke: bool = False,
) -> JsonObject:
    """Audit FB/FQA tool exposure without claiming benchmark capability."""

    profile = execution_profile(execution_profile_id)
    metadata = execution_profile_runtime_metadata(profile)
    retrieval = metadata.setdefault("retrieval", {})
    if live_network:
        retrieval["allow_network"] = True
        retrieval["max_network_fetches"] = int(retrieval.get("max_network_fetches") or profile.max_fetches or 3)
    recipe = task_recipe("retrieval_answer", metadata=metadata)
    runtime = AgentRuntime(workspace_root=Path(workspace_root) if workspace_root is not None else Path.cwd())
    registry = runtime._registry(recipe, "FB/FQA finance tool readiness audit")
    manifests = {manifest.name: manifest for manifest in registry.manifests()}
    gate = PolicyGate(permission=recipe.permission_profile, allowed_permissions=set(recipe.metadata.get("allowed_permissions", [])))
    directive = _planner_directive(recipe)
    compact_directive = _compact_runtime_directive_for_provider(directive)
    compact_tool_selection = compact_directive.get("tool_selection") if isinstance(compact_directive.get("tool_selection"), list) else []
    compact_tool_names = {str(item.get("name")) for item in compact_tool_selection if isinstance(item, dict)}
    prompt_payload = _planner_prompt(_audit_context(recipe=recipe, directive=directive), None)
    prompt_directive = json.loads(prompt_payload)["context"]["state"]["agent_runtime_directive"]
    prompt_tool_selection = prompt_directive.get("tool_selection") if isinstance(prompt_directive.get("tool_selection"), list) else []
    prompt_tool_names = {str(item.get("name")) for item in prompt_tool_selection if isinstance(item, dict)}
    provider_allowed_tools = set(_string_list(compact_directive.get("allowed_tools")))
    prompt_allowed_tools = set(_string_list(prompt_directive.get("allowed_tools")))
    install_summary = finance_toolchain_install_summary()
    installed_components = set(_string_list(install_summary.get("installed_components")))
    isolated_statuses = {
        component: isolated_component_status(component)
        for binding in TOOL_COMPONENT_BINDINGS.values()
        for component in _string_list(binding.get("components"))
    }
    required_tools = _ordered_unique(
        tool
        for category in FB_FQA_TOOL_REQUIREMENTS
        for tool in _string_list(category.get("required_tools"))
    )
    tool_rows: dict[str, JsonObject] = {}
    for tool_name in required_tools:
        manifest = manifests.get(tool_name)
        binding = TOOL_COMPONENT_BINDINGS.get(tool_name, {"components": [], "install_policy": "unknown"})
        bound_components = _string_list(binding.get("components"))
        missing_bound_components = [
            name
            for name in bound_components
            if not _component_available(name, installed_components=installed_components, isolated_statuses=isolated_statuses)
        ]
        policy_reason = "manifest_missing"
        policy_allowed = False
        if manifest is not None:
            action = CandidateAction(
                action_id="audit-" + tool_name.replace(".", "-"),
                kind="tool",
                name=tool_name,
                description="finance tool readiness audit",
                score=1.0,
                payload={},
                reasons=["audit tool exposure and policy"],
                side_effect_class=manifest.side_effect_class,
            )
            decision = gate.validate(run_id="run-finance-tool-readiness", action=action, manifest=manifest)
            policy_reason = decision.reason
            policy_allowed = bool(decision.allowed)
        tool_rows[tool_name] = {
            "name": tool_name,
            "allowed_by_recipe": tool_name in recipe.allowed_tools,
            "registered": manifest is not None,
            "provider_visible": tool_name in provider_allowed_tools or tool_name in compact_tool_names,
            "planner_prompt_visible": tool_name in prompt_allowed_tools or tool_name in prompt_tool_names,
            "policy_allowed": policy_allowed,
            "policy_reason": policy_reason,
            "side_effect_class": manifest.side_effect_class if manifest is not None else None,
            "permissions_required": list(manifest.permissions_required) if manifest is not None else [],
            "schema_keys": sorted(str(key) for key in manifest.input_schema.keys() if not str(key).startswith("_")) if manifest is not None else [],
            "component_binding": {
                "components": bound_components,
                "install_policy": binding.get("install_policy"),
                "component_status": "ok" if not missing_bound_components else "missing",
                "missing_components": missing_bound_components,
                "isolated_worker": isolated_statuses.get(bound_components[0]) if len(bound_components) == 1 else None,
            },
        }
    category_rows = []
    for category in FB_FQA_TOOL_REQUIREMENTS:
        category_tools = _string_list(category.get("required_tools"))
        failures = [
            name
            for name in category_tools
            if not (
                bool(tool_rows.get(name, {}).get("allowed_by_recipe"))
                and bool(tool_rows.get(name, {}).get("registered"))
                and bool(tool_rows.get(name, {}).get("provider_visible"))
                and bool(tool_rows.get(name, {}).get("planner_prompt_visible"))
                and bool(tool_rows.get(name, {}).get("policy_allowed"))
            )
        ]
        component_missing_tools = [
            name
            for name in category_tools
            if _string_list(_json_object(tool_rows.get(name, {}).get("component_binding")).get("missing_components"))
        ]
        category_rows.append(
            {
                "category_id": category.get("category_id"),
                "benchmark_families": category.get("benchmark_families"),
                "purpose": category.get("purpose"),
                "required_tools": category_tools,
                "status": "ok" if not failures else "failed",
                "component_status": "ok" if not component_missing_tools else "attention",
                "failed_tools": failures,
                "component_missing_tools": component_missing_tools,
            }
        )
    missing_components = _string_list(install_summary.get("missing_components"))
    required_missing_components = sorted(
        {
            component
            for row in tool_rows.values()
            for component in _string_list(_json_object(row.get("component_binding")).get("missing_components"))
        }
    )
    critical_missing = [
        item
        for item in required_missing_components
        if item in {"langgraph", "litellm", "pydantic", "edgartools", "trafilatura", "duckdb", "pandas", "sympy"}
    ]
    interface_failures = [
        item["category_id"]
        for item in category_rows
        if item.get("status") != "ok"
    ]
    local_smoke = _local_smoke_checks(registry=registry, gate=gate, artifact_store=runtime.artifact_store) if execute_local_smoke else []
    local_smoke_failures = [item for item in local_smoke if item.get("status") not in {"ok", "blocked_expected"}]
    interface_status = "ok" if not interface_failures else "failed"
    isolated_configured_components = [
        name for name, status in sorted(isolated_statuses.items()) if bool(status.get("configured"))
    ]
    main_env_missing_but_isolated_ready = [
        item for item in missing_components if item in isolated_configured_components
    ]
    optional_enhancement_missing_components = [
        item
        for item in missing_components
        if item not in set(required_missing_components) and item not in set(main_env_missing_but_isolated_ready)
    ]
    component_status = "ok" if not required_missing_components else ("failed" if critical_missing else "attention")
    smoke_status = "not_run" if not execute_local_smoke else ("ok" if not local_smoke_failures else "failed")
    fb_fqa_required_tool_complete = (
        interface_status == "ok"
        and not required_missing_components
        and smoke_status in {"not_run", "ok"}
    )
    fb_fqa_required_tool_status = "ok" if fb_fqa_required_tool_complete else "failed"
    optional_enhancement_status = "ok" if not optional_enhancement_missing_components else "attention"
    status = "failed" if interface_status == "failed" or component_status == "failed" or smoke_status == "failed" else (
        "attention" if component_status == "attention" else "ok"
    )
    return {
        "schema": FINANCE_TOOL_READINESS_SCHEMA,
        "status": status,
        "interface_status": interface_status,
        "component_status": component_status,
        "local_smoke_status": smoke_status,
        "fb_fqa_required_tool_status": fb_fqa_required_tool_status,
        "fb_fqa_required_tool_complete": fb_fqa_required_tool_complete,
        "optional_enhancement_status": optional_enhancement_status,
        "capability_claim": False,
        "benchmark_progress_claim": False,
        "evidence_policy": {
            "gold_reference_in_prompt": False,
            "fake_offline_tests_as_capability_evidence": False,
            "note": "This is a tool interface and prompt visibility preflight, not a finance benchmark result.",
        },
        "execution_profile": profile.profile_id,
        "live_network_budget_enabled": live_network,
        "runtime_backend": metadata.get("agent_loop", {}).get("runtime_backend"),
        "allowed_tools_count": len(recipe.allowed_tools),
        "allowed_tools": list(recipe.allowed_tools),
        "allowed_permissions": _string_list(recipe.metadata.get("allowed_permissions")),
        "provider_tool_selection_count": compact_directive.get("tool_selection_count"),
        "planner_prompt_tool_selection_count": prompt_directive.get("tool_selection_count"),
        "completeness_tiers": [
            {
                "tier_id": "fb_fqa_score_critical_required_tools",
                "status": fb_fqa_required_tool_status,
                "complete": fb_fqa_required_tool_complete,
                "contract": "Every FinanceBench/FinQA required tool must be registered, model-visible, policy-allowed, and backed by either the main venv or an isolated worker.",
                "required_missing_components": required_missing_components,
                "interface_failures": interface_failures,
            },
            {
                "tier_id": "local_execution_smoke",
                "status": smoke_status,
                "complete": smoke_status in {"not_run", "ok"},
                "contract": "When requested, run no-internet smoke checks for model-visible tool execution, artifact round trips, table query, calculation, and verifier paths.",
                "failed_smoke_tools": [
                    str(item.get("tool"))
                    for item in local_smoke_failures
                    if isinstance(item, dict) and item.get("tool")
                ],
            },
            {
                "tier_id": "optional_enhancements",
                "status": optional_enhancement_status,
                "complete": not optional_enhancement_missing_components,
                "contract": "Browser crawling, observability, prompt eval, and multi-agent frameworks are enhancement candidates; they do not block FB/FQA scoring unless a live task proves the need.",
                "missing_components": optional_enhancement_missing_components,
            },
        ],
        "required_categories": category_rows,
        "tools": [tool_rows[name] for name in required_tools],
        "toolchain_install_summary": {
            "installed_components": _string_list(install_summary.get("installed_components")),
            "missing_components": missing_components,
            "required_missing_components": required_missing_components,
            "critical_missing_components": critical_missing,
            "isolated_optional_missing_components": [
                item for item in required_missing_components if item in ISOLATED_OPTIONAL_COMPONENTS
            ],
            "isolated_configured_components": isolated_configured_components,
            "main_env_missing_but_isolated_ready_components": main_env_missing_but_isolated_ready,
            "optional_enhancement_missing_components": optional_enhancement_missing_components,
            "score_critical_required_status": fb_fqa_required_tool_status,
            "score_critical_required_complete": fb_fqa_required_tool_complete,
            "installed_count": install_summary.get("installed_count"),
            "missing_count": install_summary.get("missing_count"),
        },
        "local_smoke": local_smoke,
    }


def render_finance_tool_readiness_audit(audit: JsonObject) -> str:
    lines = [
        f"Finance tool readiness: {audit.get('status')}",
        f"interface={audit.get('interface_status')} components={audit.get('component_status')} local_smoke={audit.get('local_smoke_status')}",
        f"fb_fqa_required_tools={audit.get('fb_fqa_required_tool_status')} optional_enhancements={audit.get('optional_enhancement_status')}",
        f"execution_profile={audit.get('execution_profile')} runtime_backend={audit.get('runtime_backend')} live_network_budget={audit.get('live_network_budget_enabled')}",
        f"allowed_tools={audit.get('allowed_tools_count')} provider_tool_selection={audit.get('provider_tool_selection_count')} planner_prompt_tool_selection={audit.get('planner_prompt_tool_selection_count')}",
        "capability_claim=false; benchmark_progress_claim=false",
        "",
        "Required categories:",
    ]
    for category in audit.get("required_categories", []):
        if not isinstance(category, dict):
            continue
        failed = category.get("failed_tools") or []
        component_missing = category.get("component_missing_tools") or []
        suffix = "" if not failed else " failed_tools=" + ",".join(str(item) for item in failed)
        if component_missing:
            suffix += " component_attention=" + ",".join(str(item) for item in component_missing)
        lines.append(f"- {category.get('category_id')}: interface={category.get('status')} components={category.get('component_status')}{suffix}")
    summary = audit.get("toolchain_install_summary")
    if isinstance(summary, dict):
        missing = _string_list(summary.get("missing_components"))
        required_missing = _string_list(summary.get("required_missing_components"))
        critical = _string_list(summary.get("critical_missing_components"))
        lines.append("")
        lines.append(f"Components: installed={summary.get('installed_count')} missing={summary.get('missing_count')}")
        if required_missing:
            lines.append("Required missing components: " + ", ".join(required_missing))
        if missing:
            lines.append("Main-env/catalog missing components: " + ", ".join(missing))
        optional = _string_list(summary.get("isolated_optional_missing_components"))
        if optional:
            lines.append("Required isolated optional components not configured in main or worker env: " + ", ".join(optional))
        configured = _string_list(summary.get("isolated_configured_components"))
        if configured:
            lines.append("Isolated configured components: " + ", ".join(configured))
        isolated_ready = _string_list(summary.get("main_env_missing_but_isolated_ready_components"))
        if isolated_ready:
            lines.append("Main-env missing but isolated-worker ready: " + ", ".join(isolated_ready))
        optional_missing = _string_list(summary.get("optional_enhancement_missing_components"))
        if optional_missing:
            lines.append("Optional enhancement components not installed: " + ", ".join(optional_missing))
        if critical:
            lines.append("Critical missing components: " + ", ".join(critical))
    return "\n".join(lines)


def _audit_context(*, recipe, directive: JsonObject) -> ContextBundle:
    return ContextBundle(
        context_id="ctx-finance-tool-readiness",
        thread_key="thread-finance-tool-readiness",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-finance-tool-readiness",
            "run_id": "run-finance-tool-readiness",
            "input_text": "Audit whether FB/FQA finance tools are exposed to the model.",
            "host_situation": {},
            "agent_recipe": recipe.to_dict(),
            "agent_runtime_directive": directive,
            "capability_catalog": {},
        },
        token_budget=4096,
    )


def _local_smoke_checks(*, registry, gate: PolicyGate, artifact_store: ArtifactStore) -> list[JsonObject]:
    local_facts = [
        {
            "fact_id": "fact-revenue",
            "entity": "TestCo",
            "ticker": "TCO",
            "period": "FY2024",
            "fiscal_year": 2024,
            "metric": "revenue",
            "value": "200",
            "unit": "USD",
            "scale": "millions",
            "source_ref": "tool-readiness-source",
            "evidence_ref": "evidence-revenue",
            "citation_ref": "cite-revenue",
            "metadata": {"line_item": "Revenue"},
        },
        {
            "fact_id": "fact-net-income",
            "entity": "TestCo",
            "ticker": "TCO",
            "period": "FY2024",
            "fiscal_year": 2024,
            "metric": "net income",
            "value": "50",
            "unit": "USD",
            "scale": "millions",
            "source_ref": "tool-readiness-source",
            "evidence_ref": "evidence-net-income",
            "citation_ref": "cite-net-income",
            "metadata": {"line_item": "Net income"},
        },
    ]
    artifact = artifact_store.write_blob(
        kind="finance_tool_readiness_fixture",
        mime_type="application/json",
        payload=json.dumps({"facts": local_facts, "question": "What was TestCo FY2024 revenue?"}, sort_keys=True),
        metadata={"purpose": "local_smoke_artifact_context_roundtrip"},
    )
    checks = [
        (FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME, {}),
        (
            TOOL_DISCOVERY_NAME,
            {
                "query": (
                    f"select:{PROVIDED_CONTEXT_PARSE_TOOL_NAME},{FINANCE_SLOT_BIND_TOOL_NAME},"
                    f"{CALCULATOR_TOOL_NAME},{FINANCE_VERIFY_NUMERIC_TOOL_NAME}"
                ),
                "max_results": 8,
            },
        ),
        (
            ARTIFACT_READ_NAME,
            {"artifact_id": artifact.artifact_id, "mode": "preview", "max_chars": 1200},
        ),
        (
            ARTIFACT_QUERY_NAME,
            {"artifact_id": artifact.artifact_id, "path": "facts", "query": "revenue", "max_matches": 4},
        ),
        (
            DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
            {
                "artifact_id": artifact.artifact_id,
                "query": "FY2024 revenue",
                "focus_terms": ["revenue", "net income"],
                "slot_names": ["revenue"],
                "fiscal_year": 2024,
                "max_matches": 4,
            },
        ),
        (
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            {
                "context": (
                    'pre_text: ["TestCo reported revenue and net income."]\n\n'
                    'table: [["metric","FY2024"],["revenue","200"],["net income","50"]]\n\n'
                    'post_text: ["Amounts are in USD millions."]'
                ),
                "context_format": "finqa",
                "table_name_prefix": "finqa_context",
                "max_rows": 20,
            },
        ),
        (
            FINANCE_SLOT_BIND_TOOL_NAME,
            {
                "facts": local_facts,
                "slot_bindings": [
                    {"slot_name": "revenue", "variable_name": "revenue", "fact_id": "fact-revenue"},
                    {"slot_name": "net_income", "variable_name": "net_income", "fact_id": "fact-net-income"},
                ],
                "formula_requests": [
                    {
                        "formula_name": "net_margin",
                        "expression": "net_income / revenue",
                        "variables": {"net_income": "net_income", "revenue": "revenue"},
                        "unit": "percent",
                    }
                ],
                "period_basis": [{"fact_id": "fact-revenue", "basis": "FY2024"}],
                "line_item_basis": [{"fact_id": "fact-net-income", "basis": "net income"}],
                "reason_summary": "local smoke slot binding for a model-selected finance formula",
            },
        ),
        (
            CALCULATOR_TOOL_NAME,
            {
                "expression": "(beg + end) / 2 / cogs * 365",
                "variables": {"beg": 20.976, "end": 23.451, "cogs": 106.206},
                "unit": "days",
                "formula_name": "DIO",
            },
        ),
        (
            FINANCE_VERIFY_NUMERIC_TOOL_NAME,
            {
                "answer": "TestCo FY2024 revenue was 200 million and net income was 50 million.",
                "facts": local_facts,
                "question": "What were TestCo FY2024 revenue and net income?",
            },
        ),
        (
            DATA_TABLE_QUERY_TOOL_NAME,
            {
                "rows": [{"company": "HD", "dio": 76.34}, {"company": "LOW", "dio": 112.20}],
                "sql": "select company, dio from evidence order by dio asc",
                "limit": 2,
            },
        ),
        (
            MATH_SYMPY_COMPUTE_TOOL_NAME,
            {"expression": "(x + x) / y", "variables": {"x": 3, "y": 2}, "operation": "simplify"},
        ),
        (
            CALENDAR_DAYS_BETWEEN_TOOL_NAME,
            {"start_date": "2024-01-28", "end_date": "2025-02-02", "label": "retail FY2024"},
        ),
        (
            DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
            {
                "html": "<html><body><article><h1>Inventory disclosure</h1><p>Cost of sales was $10 million.</p></article></body></html>",
                "max_chars": 2000,
            },
        ),
        (
            "script.exec",
            {
                "language": "python",
                "script": "import json\nprint(json.dumps({'facts':[{'metric':'revenue','value':200}]}))\n",
                "expected_output": "json",
                "timeout_seconds": 10,
            },
        ),
    ]
    rows = []
    for index, (tool_name, payload) in enumerate(checks, start=1):
        manifest = registry.manifest_for_action(
            CandidateAction(
                action_id=f"smoke-manifest-{index}",
                kind="tool",
                name=tool_name,
                description="manifest lookup",
                score=1.0,
                payload={},
                reasons=[],
                side_effect_class="read",
            )
        )
        if manifest is None:
            rows.append({"tool": tool_name, "status": "failed", "reason": "manifest_missing"})
            continue
        action = CandidateAction(
            action_id=f"smoke-{index}",
            kind="tool",
            name=tool_name,
            description="local no-internet smoke check",
            score=1.0,
            payload=payload,
            reasons=["audit local tool execution"],
            side_effect_class=manifest.side_effect_class,
        )
        decision = gate.validate(run_id="run-finance-tool-readiness-smoke", action=action, manifest=manifest)
        result = registry.execute_with_artifacts(
            action,
            policy_decision=decision,
            execution_context={"run_id": "run-finance-tool-readiness-smoke"},
        )
        content = result.observation.content if isinstance(result.observation.content, dict) else {}
        rows.append(
            {
                "tool": tool_name,
                "policy": decision.reason,
                "status": result.observation.status,
                "kind": result.observation.kind,
                "preview_keys": sorted(str(key) for key in content.keys())[:12],
            }
        )
    return rows


def _ordered_unique(values) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _json_object(value) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _component_available(
    component: str,
    *,
    installed_components: set[str],
    isolated_statuses: dict[str, JsonObject],
) -> bool:
    if component in installed_components:
        return True
    status = isolated_statuses.get(component)
    return bool(isinstance(status, dict) and status.get("configured") and status.get("package_available") is True)


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    return []
