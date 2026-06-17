from __future__ import annotations

import importlib.util
import shutil

from kernel_v3.contracts import JsonObject


FINANCE_TOOL_SURFACE_SCHEMA = "holo.kernel_v3.finance_tool_surface.v1"


def finance_tool_surface_catalog() -> list[JsonObject]:
    """Return the complete finance problem-solving tool surface.

    The catalog is intentionally descriptive rather than prescriptive: it tells
    the model what tools exist and how to call them, but semantic choice remains
    model-owned and host-verified.
    """

    return [
        _tool_family(
            family_id="agent_loop_orchestration",
            purpose="persistent finance agent loop, replanning, termination, and state handoff",
            holo_tools=["planner.propose", "evaluator.assess", "synthesizer.answer", "mission.supervisor"],
            current_status="holo_owned_active",
            mature_components=[
                _component("langgraph", "langgraph", source="https://docs.langchain.com/oss/python/langgraph/overview"),
                _component("autogen", "autogen_agentchat", package="autogen-agentchat", source="https://microsoft.github.io/autogen/stable/"),
                _component("crewai", "crewai", source="https://docs.crewai.com/"),
            ],
            selected_component="langgraph",
            integration_decision="candidate_for_double_layer_loop_runtime; Holo keeps policy, journal, gold isolation, and verifier gates",
            boundary="framework may run control-flow primitives; model still owns finance judgment and host validates every state transition",
        ),
        _tool_family(
            family_id="llm_provider_gateway",
            purpose="model calls, retries, fallback, usage accounting, and provider normalization",
            holo_tools=["processor.fabric", "processor.router"],
            current_status="holo_owned_active",
            mature_components=[
                _component("litellm", "litellm", source="https://docs.litellm.ai/docs/"),
            ],
            selected_component="litellm",
            integration_decision="candidate_provider_gateway; use after key/provider boundary is aligned with Holo redaction",
            boundary="provider abstraction cannot see secrets in prompts or journal; Holo owns redaction and budget gates",
        ),
        _tool_family(
            family_id="structured_output_schema",
            purpose="schema validation, one-shot JSON tool actions, typed packets, and repair",
            holo_tools=["processor.schema_validate", "processor.json_repair"],
            current_status="partly_open_source_active",
            mature_components=[
                _component("pydantic", "pydantic", source="https://pydantic.dev/docs/validation/latest/get-started/"),
            ],
            selected_component="pydantic",
            integration_decision="active_for_typed_contracts; expand use for model-callable tool packets",
            boundary="schema checks validate shape only; finance truth still comes from evidence and verifier gates",
        ),
        _tool_family(
            family_id="search_discovery",
            purpose="discover official filings, issuer pages, source documents, market/macro sources, and news candidates",
            holo_tools=["retrieval.run", "workspace.search"],
            current_status="holo_owned_active",
            mature_components=[
                _service_component("searxng", source="https://docs.searxng.org/"),
            ],
            selected_component="searxng",
            integration_decision="candidate_meta_search_provider; current retrieval.run already exposes a one-shot search action",
            boundary="search returns candidates, not answers; host source policy and citations decide usability",
        ),
        _tool_family(
            family_id="network_fetch_crawl_browser",
            purpose="bounded URL fetch, page extraction, dynamic pages, and crawler-style source acquisition",
            holo_tools=["network.fetch", "retrieval.run", "document.trafilatura.extract"],
            current_status="holo_owned_active",
            mature_components=[
                _component("trafilatura", "trafilatura", source="https://trafilatura.readthedocs.io/en/latest/"),
                _component("crawl4ai", "crawl4ai", source="https://github.com/unclecode/crawl4ai"),
                _component("playwright", "playwright", source="https://playwright.dev/python/docs/intro"),
            ],
            selected_component="trafilatura_then_playwright",
            integration_decision="candidate_fetch_extract_layer; browser automation only when plain fetch/doc parser fails",
            boundary="host allowlist, byte limits, cache policy, and artifact redaction apply before model sees text",
        ),
        _tool_family(
            family_id="sec_edgar_xbrl",
            purpose="official SEC submissions, companyfacts, XBRL concepts, filings, forms, accessions, and statement candidates",
            holo_tools=["sec.edgar.company_filings", "sec.edgar.financials", "retrieval.run"],
            current_status="open_source_wrapped_active",
            mature_components=[
                _component("edgartools", "edgar", package="edgartools", source="https://github.com/dgunning/edgartools"),
            ],
            selected_component="edgartools",
            integration_decision="active_first_class_sec_component; direct SEC APIs remain fallback/verification source",
            boundary="EdgarTools returns official candidates; model chooses metric/period/facts and Holo verifies citations",
        ),
        _tool_family(
            family_id="document_table_conversion",
            purpose="PDF/HTML/XLSX/XBRL/CSV conversion, table preservation, chunking, and parser diagnostics",
            holo_tools=["document.docling.convert", "document.trafilatura.extract", "retrieval.run", "script.exec"],
            current_status="wrapper_active_dependency_missing",
            mature_components=[
                _component("docling", "docling", source="https://docling-project.github.io/docling/"),
                _component("pandas", "pandas", source="https://pandas.pydata.org/docs/"),
            ],
            selected_component="docling",
            integration_decision="install_and_make_default_for_structured_document_conversion",
            boundary="parser output is candidate evidence; FactLedger, citations, slot binding, and verifier remain mandatory",
        ),
        _tool_family(
            family_id="market_macro_fundamental_data",
            purpose="prices, fundamentals, macro series, crypto, currencies, indexes, FRED-style data, and non-filing data",
            holo_tools=["market.openbb.fetch", "retrieval.run"],
            current_status="wrapper_active_dependency_missing",
            mature_components=[
                _component("openbb", "openbb", source="https://docs.openbb.co/platform/"),
            ],
            selected_component="openbb",
            integration_decision="install_and_use_for_allowlisted_market_and_fundamental_routes",
            boundary="route allowlist prevents arbitrary data calls; model decides relevance and Holo records source metadata",
        ),
        _tool_family(
            family_id="calculator_math_stats",
            purpose="auditable arithmetic, ratio computation, percentages, bps, valuation multiples, DIO, CAGR, and statistical helpers",
            holo_tools=["calculator.compute", "math.sympy.compute"],
            current_status="holo_owned_active",
            mature_components=[
                _component("python_decimal", "decimal", package="python-stdlib", source="https://docs.python.org/3/library/decimal.html", stdlib=True),
                _component("python_statistics", "statistics", package="python-stdlib", source="https://docs.python.org/3/library/statistics.html", stdlib=True),
                _component("sympy", "sympy", source="https://www.sympy.org/en/index.html"),
            ],
            selected_component="python_decimal",
            integration_decision="active_decimal_calculator; add SymPy only for symbolic/complex math when needed",
            boundary="calculator only evaluates model-proposed formulas with evidence-backed inputs; it never selects the answer",
        ),
        _tool_family(
            family_id="table_dataframe_query",
            purpose="large table normalization, joins, SQL over extracted evidence, and memory-safe dataframe operations",
            holo_tools=["data.table.query", "script.exec", "shell.exec", "workspace.write", "file.read"],
            current_status="partly_open_source_active",
            mature_components=[
                _component("pandas", "pandas", source="https://pandas.pydata.org/docs/"),
                _component("polars", "polars", source="https://pola.rs/"),
                _component("duckdb", "duckdb", source="https://duckdb.org/docs/stable/"),
                _component("sqlite3", "sqlite3", package="python-stdlib", source="https://docs.python.org/3/library/sqlite3.html", stdlib=True),
            ],
            selected_component="pandas_now_polars_duckdb_next",
            integration_decision="use pandas now; install Polars/DuckDB for larger evidence tables and SQL-style joins",
            boundary="scripts are host-audited artifacts; LLM owns which table operation is needed and interprets results",
        ),
        _tool_family(
            family_id="workspace_code_execution",
            purpose="local artifact inspection, temporary parsers, controlled scripts, and reproducible transformation outputs",
            holo_tools=["workspace.list", "workspace.search", "file.read", "workspace.write", "script.exec", "shell.exec"],
            current_status="holo_owned_active",
            mature_components=[
                _component("python", "sys", package="python-stdlib", source="https://docs.python.org/3/", stdlib=True),
                _component("pytest", "pytest", source="https://docs.pytest.org/en/stable/"),
            ],
            selected_component="python_stdlib_pytest",
            integration_decision="active_for_engineering_regression_not_fake_finance_evidence",
            boundary="live benchmark claims cannot rely on fake/offline tests; scripts may support parsing and engineering checks only",
        ),
        _tool_family(
            family_id="evidence_provenance_verification",
            purpose="FactLedger, ClaimLedger, FormulaTrace, target binding, citation support, numeric verifier, and synthesis gate",
            holo_tools=["finance.verify_numeric", "host.verifier_gate", "host.synthesis_gate"],
            current_status="holo_owned_active",
            mature_components=[
                _component("pydantic", "pydantic", source="https://pydantic.dev/docs/validation/latest/get-started/"),
            ],
            selected_component="holo_verifier_with_pydantic_contracts",
            integration_decision="keep_holo_owned_because_gold_isolation_and_finance_truth_gates_are_system_invariants",
            boundary="no open-source component may receive benchmark gold/reference during runtime; gold is post-run scoring only",
        ),
        _tool_family(
            family_id="memory_cache_storage",
            purpose="durable memory, run cache, document cache, prompt/cache-hit diagnostics, and structured state recall",
            holo_tools=["memory.recall", "ArtifactStore", "JournalStore"],
            current_status="holo_owned_active",
            mature_components=[
                _component("sqlite3", "sqlite3", package="python-stdlib", source="https://docs.python.org/3/library/sqlite3.html", stdlib=True),
                _component("duckdb", "duckdb", source="https://duckdb.org/docs/stable/"),
            ],
            selected_component="sqlite_now_duckdb_next_for_analytics",
            integration_decision="use SQLite now; add DuckDB for trace analytics and large benchmark summaries",
            boundary="memory is redacted and durable; secrets and gold/reference are never stored in model-visible memory",
        ),
        _tool_family(
            family_id="process_observability_visualization",
            purpose="live run visibility, process RSS/PID, stages, tool calls, traces, metrics, and debugging dashboards",
            holo_tools=["bench.finance-progress", "workflow-view", "demo_dashboard"],
            current_status="partly_open_source_active",
            mature_components=[
                _component("rich", "rich", source="https://rich.readthedocs.io/en/stable/introduction.html"),
                _component("opentelemetry", "opentelemetry", package="opentelemetry-api", source="https://opentelemetry.io/docs/what-is-opentelemetry/"),
                _component("langfuse", "langfuse", source="https://github.com/langfuse/langfuse"),
                _component("phoenix", "phoenix", package="arize-phoenix", source="https://arize.com/docs/phoenix"),
            ],
            selected_component="rich_now_opentelemetry_next",
            integration_decision="Rich active for CLI; add OpenTelemetry/Phoenix or Langfuse when trace export is needed",
            boundary="observability must redact prompts/secrets/gold and must not destabilize UbuntuHolo",
        ),
        _tool_family(
            family_id="benchmark_evaluation",
            purpose="FinanceBench/FAB/FinQA style runs, dev/test split enforcement, post-run scoring, and regression checks",
            holo_tools=["bench.finance", "bench.finance-progress", "pytest"],
            current_status="holo_owned_active",
            mature_components=[
                _component("pytest", "pytest", source="https://docs.pytest.org/en/stable/"),
                _service_component("promptfoo", executable="promptfoo", source="https://github.com/promptfoo/promptfoo"),
            ],
            selected_component="holo_benchmark_runner_with_pytest_regression",
            integration_decision="keep finance benchmark runner Holo-owned because gold isolation is mandatory",
            boundary="fake/offline tests are never evidence of finance capability; only live runs count for benchmark progress",
        ),
    ]


def finance_one_shot_tool_protocol() -> JsonObject:
    return {
        "schema": "holo.kernel_v3.model_tool_call_protocol.v1",
        "decision_owner": "model",
        "call_shape": {
            "action_id": "stable unique id",
            "kind": "tool",
            "name": "one registered tool name",
            "payload": "object matching the selected tool input schema",
            "reasons": "why this tool is needed now",
            "side_effect_class": "read|network|shell|write",
        },
        "model_must_decide": [
            "whether a tool is needed",
            "which tool or source family is most relevant",
            "the concrete payload and stop condition",
            "whether returned evidence is sufficient",
            "which facts and formula to use in the answer",
        ],
        "host_must_enforce": [
            "tool manifest schema",
            "permission and network boundaries",
            "resource budgets and cache paths",
            "journal/artifact redaction",
            "citation, numeric, formula, and synthesis gates",
            "gold/reference isolation",
        ],
    }


def finance_toolchain_install_summary() -> JsonObject:
    catalog = finance_tool_surface_catalog()
    components: dict[str, JsonObject] = {}
    for family in catalog:
        for component in family.get("mature_components", []):
            if not isinstance(component, dict):
                continue
            key = str(component.get("component") or "")
            if not key or key in components:
                continue
            components[key] = {
                "component": key,
                "package": component.get("package"),
                "installed": component.get("installed"),
                "install_hint": component.get("install_hint"),
                "used_by_families": [family.get("family_id")],
            }
        for key, component in components.items():
            if any(isinstance(item, dict) and item.get("component") == key for item in family.get("mature_components", [])):
                families = component.setdefault("used_by_families", [])
                if isinstance(families, list) and family.get("family_id") not in families:
                    families.append(family.get("family_id"))
    installed = sorted(key for key, value in components.items() if value.get("installed") is True)
    missing = sorted(key for key, value in components.items() if value.get("installed") is False)
    return {
        "installed_components": installed,
        "missing_components": missing,
        "component_count": len(components),
        "installed_count": len(installed),
        "missing_count": len(missing),
        "components": [components[key] for key in sorted(components)],
    }


def _tool_family(
    *,
    family_id: str,
    purpose: str,
    holo_tools: list[str],
    current_status: str,
    mature_components: list[JsonObject],
    selected_component: str,
    integration_decision: str,
    boundary: str,
) -> JsonObject:
    callable_now = current_status in {"holo_owned_active", "open_source_wrapped_active", "partly_open_source_active"}
    return {
        "family_id": family_id,
        "purpose": purpose,
        "holo_tools": holo_tools,
        "current_status": current_status,
        "callable_now": callable_now,
        "mature_components": mature_components,
        "selected_component": selected_component,
        "integration_decision": integration_decision,
        "one_shot_contract": {
            "planner_action_kind": "tool",
            "planner_fields": ["name", "payload", "reasons", "side_effect_class"],
            "model_decides": True,
            "host_validates": True,
        },
        "boundary": boundary,
    }


def _component(
    component: str,
    import_name: str,
    *,
    package: str | None = None,
    source: str,
    stdlib: bool = False,
) -> JsonObject:
    package_name = package or component
    installed = _import_available(import_name)
    result: JsonObject = {
        "component": component,
        "package": package_name,
        "import_name": import_name,
        "source": source,
        "stdlib": stdlib,
        "installed": installed,
    }
    if not installed and not stdlib:
        result["install_hint"] = f"pip install {package_name}"
    return result


def _service_component(component: str, *, source: str, executable: str | None = None) -> JsonObject:
    installed = shutil.which(executable) is not None if executable else None
    result: JsonObject = {
        "component": component,
        "package": component,
        "source": source,
        "service_or_cli": True,
        "installed": installed,
    }
    if executable:
        result["executable"] = executable
        if not installed:
            result["install_hint"] = f"install {component} CLI/service"
    else:
        result["install_hint"] = f"configure {component} service"
    return result


def _import_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False
