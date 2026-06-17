from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from kernel_v3.agent.runtime import AgentRuntime, task_recipe
from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction
from kernel_v3.finance import (
    DATA_TABLE_QUERY_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    FINANCE_AGENT_LOOP_CONTRACT_SCHEMA,
    FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES,
    FINANCE_OPEN_COMPONENT_READ_TOOL_NAMES,
    FINANCE_OPEN_COMPONENT_TOOL_NAMES,
    FINANCE_SLOT_BIND_TOOL_NAME,
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    finance_agent_loop_contract,
    finance_one_shot_tool_protocol,
    finance_tool_surface_catalog,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    register_finance_tools,
)
from kernel_v3.finance import open_components
from kernel_v3.policy import PolicyGate
from kernel_v3.tools import ToolRegistry


def test_finance_register_exposes_mature_component_tools_with_host_boundaries() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    manifests = {manifest.name: manifest for manifest in registry.manifests()}

    assert FINANCE_SLOT_BIND_TOOL_NAME in manifests
    for tool_name in FINANCE_OPEN_COMPONENT_TOOL_NAMES:
        assert tool_name in manifests

    assert manifests[FINANCE_SLOT_BIND_TOOL_NAME].side_effect_class == "read"
    assert manifests[FINANCE_SLOT_BIND_TOOL_NAME].permissions_required == []
    assert manifests[FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME].side_effect_class == "read"
    assert manifests[FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME].permissions_required == []
    for tool_name in FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES:
        assert manifests[tool_name].side_effect_class == "network"
        assert manifests[tool_name].permissions_required == ["network:fetch"]
    for tool_name in FINANCE_OPEN_COMPONENT_READ_TOOL_NAMES:
        assert manifests[tool_name].side_effect_class == "read"
        assert manifests[tool_name].permissions_required == []


def test_finance_slot_bind_tool_validates_model_selected_facts_and_returns_calculator_payload() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-slot-bind",
        kind="tool",
        name=FINANCE_SLOT_BIND_TOOL_NAME,
        description="bind model selected facts",
        score=0.95,
        payload={
            "facts": [
                {
                    "fact_id": "fact-revenue",
                    "entity": "TestCo",
                    "ticker": None,
                    "period": "FY2024",
                    "fiscal_year": 2024,
                    "metric": "revenue",
                    "value": "200",
                    "unit": "USD",
                    "scale": "actual",
                    "source_ref": "source-1",
                    "evidence_ref": "evidence-1",
                    "citation_ref": "cite-1",
                    "metadata": {"label": "Revenue"},
                },
                {
                    "fact_id": "fact-gross-profit",
                    "entity": "TestCo",
                    "ticker": None,
                    "period": "FY2024",
                    "fiscal_year": 2024,
                    "metric": "gross profit",
                    "value": "80",
                    "unit": "USD",
                    "scale": "actual",
                    "source_ref": "source-2",
                    "evidence_ref": "evidence-2",
                    "citation_ref": "cite-2",
                    "metadata": {"label": "Gross profit"},
                },
            ],
            "slot_bindings": [
                {"slot_name": "revenue", "variable_name": "revenue", "fact_id": "fact-revenue"},
                {"slot_name": "gross_profit", "variable_name": "gross_profit", "fact_id": "fact-gross-profit"},
            ],
            "formula_requests": [
                {
                    "formula_name": "gross_margin",
                    "expression": "gross_profit / revenue",
                    "variables": {"gross_profit": "gross_profit", "revenue": "revenue"},
                    "unit": "percent",
                }
            ],
            "period_basis": [{"slot_name": "revenue", "selected_period": "FY2024"}],
            "line_item_basis": [{"slot_name": "gross_profit", "selected_line_item": "Gross profit"}],
            "reason_summary": "Model selected FY2024 revenue and gross profit facts.",
        },
        reasons=["need auditable slot binding"],
        side_effect_class="read",
    )

    decision = PolicyGate(permission="read_write").validate(
        run_id="run-slot-bind",
        action=action,
        manifest=registry.manifest_for_action(action),
    )
    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.source == f"tool:{FINANCE_SLOT_BIND_TOOL_NAME}"
    assert observation.content["status"] == "ready"
    assert observation.content["accepted_slot_binding_count"] == 2
    assert observation.content["accepted_formula_plan_count"] == 1
    payload = observation.content["calculator_payloads"][0]
    assert payload["expression"] == "gross_profit / revenue"
    assert payload["variables"] == {"gross_profit": "80", "revenue": "200"}
    assert payload["input_fact_ids"] == ["fact-gross-profit", "fact-revenue"]
    assert payload["diagnostics"]["source"] == "finance_slot_bind_tool"


def test_finance_toolchain_describe_reports_component_install_status(monkeypatch) -> None:
    installed = {"edgar", "trafilatura", "duckdb", "sympy"}

    def fake_find_spec(import_name: str):
        return object() if import_name in installed else None

    monkeypatch.setattr(open_components.importlib.util, "find_spec", fake_find_spec)
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-toolchain-describe",
        kind="tool",
        name=FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
        description="describe mature finance components",
        score=1.0,
        payload={},
        reasons=["inspect toolchain"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-toolchain-describe",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "finance_toolchain_status"
    components = {item["component"]: item for item in observation.content["components"]}
    assert components["edgartools"]["installed"] is True
    assert components["docling"]["installed"] is False
    assert components["trafilatura"]["installed"] is True
    assert components["duckdb"]["installed"] is True
    assert components["sympy"]["installed"] is True
    assert components["openbb"]["install_hint"] == "pip install openbb"
    assert observation.content["host_boundary"].startswith("Mature components supply")
    assert observation.content["one_shot_tool_protocol"]["decision_owner"] == "model"
    assert observation.content["agent_loop_contract"]["schema"] == FINANCE_AGENT_LOOP_CONTRACT_SCHEMA
    assert observation.content["agent_loop_contract"]["decision_owner"] == "model"
    assert "financebench_id" not in json.dumps(observation.content["agent_loop_contract"])
    assert "debug50" not in json.dumps(observation.content["agent_loop_contract"]).lower()
    assert observation.content["tool_surface_schema"] == "holo.kernel_v3.finance_tool_surface.v1"
    family_ids = {item["family_id"] for item in observation.content["tool_surface"]}
    assert "calculator_math_stats" in family_ids
    assert "search_discovery" in family_ids
    assert "sec_edgar_xbrl" in family_ids
    assert "document_table_conversion" in family_ids
    assert "market_macro_fundamental_data" in family_ids
    assert "process_observability_visualization" in family_ids


def test_finance_tool_surface_catalog_covers_required_one_shot_tool_families() -> None:
    catalog = finance_tool_surface_catalog()
    family_ids = {item["family_id"] for item in catalog}

    assert {
        "agent_loop_orchestration",
        "llm_provider_gateway",
        "structured_output_schema",
        "search_discovery",
        "network_fetch_crawl_browser",
        "sec_edgar_xbrl",
        "document_table_conversion",
        "market_macro_fundamental_data",
        "calculator_math_stats",
        "table_dataframe_query",
        "workspace_code_execution",
        "evidence_provenance_verification",
        "memory_cache_storage",
        "process_observability_visualization",
        "benchmark_evaluation",
    }.issubset(family_ids)
    for family in catalog:
        assert family["one_shot_contract"]["planner_action_kind"] == "tool"
        assert family["one_shot_contract"]["model_decides"] is True
        assert family["one_shot_contract"]["host_validates"] is True
        assert family["holo_tools"]
        assert family["mature_components"]


def test_finance_one_shot_tool_protocol_keeps_model_as_decision_owner() -> None:
    protocol = finance_one_shot_tool_protocol()

    assert protocol["decision_owner"] == "model"
    assert protocol["call_shape"]["kind"] == "tool"
    assert "payload" in protocol["call_shape"]
    assert "which tool or source family is most relevant" in protocol["model_must_decide"]
    assert "gold/reference isolation" in protocol["host_must_enforce"]


def test_finance_agent_loop_contract_is_generic_and_covers_debug50_task_families() -> None:
    contract = finance_agent_loop_contract()

    assert contract["schema"] == FINANCE_AGENT_LOOP_CONTRACT_SCHEMA
    assert contract["decision_owner"] == "model"
    assert contract["host_role"] == "schema_policy_execution_journal_verifier_only"
    assert [phase["phase"] for phase in contract["core_loop"]] == [
        "task_compile",
        "evidence_acquire",
        "ledger_bind",
        "transform_compute",
        "semantic_synthesis",
        "verify_or_replan",
    ]
    families = {item["family"] for item in contract["task_family_workflows"]}
    assert {
        "direct_line_item_or_disclosure_extraction",
        "defined_formula_numeric_calculation",
        "computed_business_judgment",
        "driver_attribution_or_bridge_adjustment",
        "table_ranking_or_comparison",
    }.issubset(families)
    serialized = json.dumps(contract, ensure_ascii=False)
    assert "financebench_id" not in serialized
    assert "debug50" not in serialized.lower()


def test_docling_tool_reports_missing_dependency_without_host_fallback(monkeypatch) -> None:
    def fake_import_component(import_name: str, *, package: str):
        return None, {
            "error": "dependency_missing",
            "component": package,
            "import_name": import_name,
            "install_hint": f"pip install {package}",
            "host_boundary": "tool did not run; no benchmark answer was inferred by host fallback",
        }

    monkeypatch.setattr(open_components, "_import_component", fake_import_component)
    monkeypatch.setattr(open_components, "_isolated_component_python", lambda component: None)
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-docling-missing",
        kind="tool",
        name=DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        description="convert filing url",
        score=0.9,
        payload={"source": "https://www.sec.gov/example.htm"},
        reasons=["need structured table conversion"],
        side_effect_class="network",
    )
    decision = PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}).validate(
        run_id="run-docling-missing",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "failed"
    assert observation.kind == "docling_conversion"
    assert observation.content["error"] == "dependency_missing"
    assert observation.content["host_boundary"] == "tool did not run; no benchmark answer was inferred by host fallback"
    assert observation.content["isolated_worker"]["configured"] is False


def test_docling_tool_uses_isolated_worker_when_main_dependency_is_missing(monkeypatch) -> None:
    def fake_import_component(import_name: str, *, package: str):
        return None, {
            "error": "dependency_missing",
            "component": package,
            "import_name": import_name,
            "install_hint": f"pip install {package}",
            "host_boundary": "tool did not run; no benchmark answer was inferred by host fallback",
        }

    def fake_run(argv, **kwargs):
        script = argv[2]
        if "find_spec" in script:
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"available": True}), stderr="")
        payload = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "content": {
                        "component": "docling",
                        "source": payload["source"],
                        "output_format": payload["output_format"],
                        "text": "Converted filing markdown",
                        "text_chars": 25,
                        "truncated": False,
                        "semantic_decision_owner": "model",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("HOLO_DOCLING_PYTHON", "python-worker")
    monkeypatch.setattr(open_components, "_import_component", fake_import_component)
    monkeypatch.setattr(open_components.subprocess, "run", fake_run)
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-docling-isolated",
        kind="tool",
        name=DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        description="convert filing url",
        score=0.9,
        payload={"source": "https://www.sec.gov/example.htm"},
        reasons=["need isolated structured table conversion"],
        side_effect_class="network",
    )
    decision = PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}).validate(
        run_id="run-docling-isolated",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "docling_conversion"
    assert observation.content["component"] == "docling"
    assert observation.content["component_execution"] == "isolated_worker"
    assert observation.content["isolated_worker"]["configured"] is True
    assert observation.content["isolated_worker"]["package_available"] is True
    assert observation.content["main_process_import_error"]["error"] == "dependency_missing"
    assert observation.content["text"] == "Converted filing markdown"


def test_openbb_tool_blocks_unallowlisted_routes_before_component_import(monkeypatch) -> None:
    def fail_import_component(import_name: str, *, package: str):  # pragma: no cover - should not be called
        raise AssertionError("unallowlisted OpenBB route should be blocked before import")

    monkeypatch.setattr(open_components, "_import_component", fail_import_component)
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-openbb-block",
        kind="tool",
        name=MARKET_OPENBB_FETCH_TOOL_NAME,
        description="try arbitrary route",
        score=0.9,
        payload={"route": "__class__.__mro__", "kwargs": {}},
        reasons=["boundary test"],
        side_effect_class="network",
    )
    decision = PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}).validate(
        run_id="run-openbb-block",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "blocked"
    assert observation.kind == "openbb_result"
    assert observation.content["error"] == "route_not_allowlisted"
    assert "equity.price.historical" in observation.content["allowed_routes"]


def test_openbb_tool_uses_isolated_worker_when_main_dependency_is_missing(monkeypatch) -> None:
    def fake_import_component(import_name: str, *, package: str):
        return None, {
            "error": "dependency_missing",
            "component": package,
            "import_name": import_name,
            "install_hint": f"pip install {package}",
            "host_boundary": "tool did not run; no benchmark answer was inferred by host fallback",
        }

    seen_homes: list[str] = []

    def fake_run(argv, **kwargs):
        seen_homes.append(str(kwargs.get("env", {}).get("HOME") or ""))
        script = argv[2]
        if "find_spec" in script:
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"available": True}), stderr="")
        payload = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "content": {
                        "component": "openbb",
                        "route": payload["route"],
                        "kwargs": payload["kwargs"],
                        "limit": payload["limit"],
                        "records": [{"date": "2024-01-01", "close": 100}],
                        "semantic_decision_owner": "model",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("HOLO_OPENBB_PYTHON", "python-worker")
    monkeypatch.setattr(open_components, "_import_component", fake_import_component)
    monkeypatch.setattr(open_components.subprocess, "run", fake_run)
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-openbb-isolated",
        kind="tool",
        name=MARKET_OPENBB_FETCH_TOOL_NAME,
        description="fetch allowlisted market route",
        score=0.9,
        payload={"route": "equity.price.historical", "kwargs": {"symbol": "HD"}, "limit": 1},
        reasons=["need isolated market component"],
        side_effect_class="network",
    )
    decision = PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}).validate(
        run_id="run-openbb-isolated",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "openbb_result"
    assert observation.content["component"] == "openbb"
    assert observation.content["component_execution"] == "isolated_worker"
    assert observation.content["isolated_worker"]["configured"] is True
    assert observation.content["isolated_worker"]["package_available"] is True
    assert observation.content["records"][0]["close"] == 100
    assert seen_homes
    assert all(home.endswith(".holo_components/openbb-home") for home in seen_homes)


def test_isolated_component_python_uses_local_worker_fallback(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / "openbb-worker" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    openbb_home = tmp_path / "openbb-home"

    monkeypatch.delenv("HOLO_OPENBB_PYTHON", raising=False)
    monkeypatch.delenv("HOLO_FINANCE_COMPONENT_PYTHON", raising=False)
    monkeypatch.delenv("HOLO_OPENBB_HOME", raising=False)
    monkeypatch.setitem(open_components._LOCAL_ISOLATED_COMPONENT_PYTHONS, "openbb", python_path)
    monkeypatch.setattr(open_components, "_LOCAL_OPENBB_HOME", openbb_home)

    assert open_components._isolated_component_python("openbb") == str(python_path)
    assert open_components._isolated_component_env("openbb")["HOME"] == str(openbb_home)


def test_trafilatura_tool_extracts_provided_html_without_fetch() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-trafilatura-html",
        kind="tool",
        name=DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        description="extract html",
        score=0.9,
        payload={
            "html": "<html><body><article><h1>Inventory disclosure</h1><p>Cost of sales was $10 million.</p></article></body></html>",
            "max_chars": 2000,
        },
        reasons=["need readable text"],
        side_effect_class="network",
    )
    decision = PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}).validate(
        run_id="run-trafilatura-html",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "trafilatura_extract"
    assert observation.content["component"] == "trafilatura"
    assert observation.content["fetched"] is False
    assert "Cost of sales" in observation.content["text"]


def test_data_table_query_runs_readonly_duckdb_over_rows() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-table-query",
        kind="tool",
        name=DATA_TABLE_QUERY_TOOL_NAME,
        description="query evidence table",
        score=0.9,
        payload={
            "rows": [
                {"company": "HD", "dio": 76.34},
                {"company": "LOW", "dio": 112.20},
            ],
            "sql": "select company, dio from evidence order by dio asc",
            "limit": 2,
        },
        reasons=["rank inventory efficiency"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-table-query",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "data_table_query"
    assert observation.content["records"][0]["company"] == "HD"
    assert observation.content["records"][0]["dio"] == 76.34


def test_data_table_query_writes_full_payload_artifact_when_store_is_available() -> None:
    artifact_store = ArtifactStore.in_memory()
    registry = register_finance_tools(ToolRegistry.with_builtin_respond(), artifact_store=artifact_store)
    action = CandidateAction(
        action_id="act-table-query-artifact",
        kind="tool",
        name=DATA_TABLE_QUERY_TOOL_NAME,
        description="query evidence table with artifact payload",
        score=0.9,
        payload={
            "rows": [
                {"company": "HD", "dio": 76.34},
                {"company": "LOW", "dio": 112.20},
            ],
            "sql": "select company, dio from evidence order by dio asc",
            "limit": 2,
        },
        reasons=["rank inventory efficiency"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-table-query-artifact",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    result = registry.execute_with_artifacts(action, policy_decision=decision)
    observation = result.observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.content["records"][0]["company"] == "HD"
    assert observation.content["artifact_read_hint"]["tool"] == "artifact.read"
    artifact_id = str(observation.content["artifact_id"])
    assert result.artifact_refs[0].artifact_id == artifact_id
    assert artifact_store.has_blob(artifact_id)
    payload = json.loads(str(artifact_store.read_blob(artifact_id)))
    assert payload["records"][1]["company"] == "LOW"
    assert payload["sql"] == "select company, dio from evidence order by dio asc"


def test_data_table_query_blocks_write_sql() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-table-query-block",
        kind="tool",
        name=DATA_TABLE_QUERY_TOOL_NAME,
        description="bad sql",
        score=0.9,
        payload={"rows": [{"a": 1}], "sql": "drop table evidence"},
        reasons=["boundary test"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-table-query-block",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "blocked"
    assert observation.content["error"] == "unsafe_or_unsupported_sql"


def test_data_table_query_blocks_duckdb_external_reads() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-table-query-external-read-block",
        kind="tool",
        name=DATA_TABLE_QUERY_TOOL_NAME,
        description="bad sql external read",
        score=0.9,
        payload={"rows": [{"a": 1}], "sql": "select * from read_csv_auto('/etc/passwd')"},
        reasons=["boundary test"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-table-query-external-read-block",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "blocked"
    assert observation.content["error"] == "unsafe_or_unsupported_sql"


def test_sympy_tool_evaluates_model_proposed_expression() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-sympy",
        kind="tool",
        name=MATH_SYMPY_COMPUTE_TOOL_NAME,
        description="symbolic compute",
        score=0.9,
        payload={"expression": "(x + x) / y", "variables": {"x": 3, "y": 2}, "operation": "simplify"},
        reasons=["need exact expression"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-sympy",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "sympy_compute"
    assert observation.content["result"] == "3"


def test_sympy_tool_blocks_unsafe_variable_substitution() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-sympy-unsafe",
        kind="tool",
        name=MATH_SYMPY_COMPUTE_TOOL_NAME,
        description="unsafe symbolic compute",
        score=0.9,
        payload={"expression": "x + 1", "variables": {"x": "__import__('os').system('id')"}},
        reasons=["boundary test"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_write").validate(
        run_id="run-sympy-unsafe",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "blocked"
    assert observation.content["error"] == "unsafe_or_empty_expression"


def test_edgartools_environment_defaults_to_tmp_cache(monkeypatch, tmp_path) -> None:
    cache_root = tmp_path / "edgar-cache"
    monkeypatch.setenv("HOLO_EDGAR_CACHE_ROOT", str(cache_root))
    monkeypatch.delenv("EDGAR_LOCAL_DATA_DIR", raising=False)
    monkeypatch.delenv("EDGAR_CACHE_DIR", raising=False)

    open_components._prepare_edgar_environment()

    assert open_components.os.environ["EDGAR_LOCAL_DATA_DIR"] == str(cache_root / "data")
    assert open_components.os.environ["EDGAR_CACHE_DIR"] == str(cache_root / "cache")
    assert (cache_root / "data").is_dir()
    assert (cache_root / "cache").is_dir()


def test_edgartools_financials_adapter_accepts_property_api() -> None:
    class FakeFilingObject:
        financials = {"statement": "cash_flow"}

    class FakeLatest:
        def obj(self):
            return FakeFilingObject()

    class FakeFilings:
        def latest(self):
            return FakeLatest()

    class FakeCompany:
        def get_filings(self, *, form: str):
            assert form == "10-K"
            return FakeFilings()

    assert open_components._edgar_financials_for_company(FakeCompany(), form="10-K") == {"statement": "cash_flow"}


def test_open_component_json_sanitizer_removes_non_finite_float() -> None:
    assert open_components._json_sanitize({"value": math.nan, "ok": 1.25}) == {"value": None, "ok": 1.25}


def test_finance_retrieval_recipe_exposes_mature_component_tools_only_with_network_budget() -> None:
    offline_recipe = task_recipe(
        "retrieval_answer",
        metadata={"require_numeric_verifier": True},
    )
    live_recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "require_numeric_verifier": True,
            "execution_metadata": {
                "retrieval": {
                    "allow_network": True,
                    "max_network_fetches": 3,
                }
            },
        },
    )

    assert FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME in offline_recipe.allowed_tools
    for tool_name in FINANCE_OPEN_COMPONENT_READ_TOOL_NAMES:
        assert tool_name in offline_recipe.allowed_tools
    assert SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME not in offline_recipe.allowed_tools
    assert SEC_EDGAR_FINANCIALS_TOOL_NAME not in offline_recipe.allowed_tools
    assert DOCUMENT_DOCLING_CONVERT_TOOL_NAME not in offline_recipe.allowed_tools
    assert DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME not in offline_recipe.allowed_tools
    assert MARKET_OPENBB_FETCH_TOOL_NAME not in offline_recipe.allowed_tools
    for tool_name in FINANCE_OPEN_COMPONENT_TOOL_NAMES:
        assert tool_name in live_recipe.allowed_tools
    assert "network:fetch" in live_recipe.metadata["allowed_permissions"]


def test_finance_research_profile_exposes_tool_surface_without_numeric_verifier(tmp_path) -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "execution_metadata": {
                "retrieval": {
                    "allow_network": True,
                    "max_network_fetches": 3,
                    "metadata": {"research_profile": "finance_fundamentals"},
                }
            }
        },
    )

    assert FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME in recipe.allowed_tools
    assert DATA_TABLE_QUERY_TOOL_NAME in recipe.allowed_tools
    assert MATH_SYMPY_COMPUTE_TOOL_NAME in recipe.allowed_tools
    assert SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME in recipe.allowed_tools
    assert DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME in recipe.allowed_tools
    runtime = AgentRuntime(workspace_root=tmp_path)
    manifests = {manifest.name for manifest in runtime._registry(recipe, "Explain a finance disclosure.").manifests()}
    assert FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME in manifests
    assert DATA_TABLE_QUERY_TOOL_NAME in manifests
    assert MATH_SYMPY_COMPUTE_TOOL_NAME in manifests
