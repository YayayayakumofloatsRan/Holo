from __future__ import annotations

from types import SimpleNamespace

from kernel_v3 import cli
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
import kernel_v3.finance.tool_readiness as tool_readiness
from kernel_v3.finance.tool_readiness import build_finance_tool_readiness_audit
from kernel_v3.journal import JournalStore
from kernel_v3.tool_use import ARTIFACT_QUERY_NAME, ARTIFACT_READ_NAME, TOOL_DISCOVERY_NAME


def test_finance_tool_readiness_audit_exposes_fb_fqa_tools_to_model(tmp_path) -> None:
    audit = build_finance_tool_readiness_audit(workspace_root=tmp_path)

    tools = {item["name"]: item for item in audit["tools"]}
    required = {
        TOOL_DISCOVERY_NAME,
        ARTIFACT_READ_NAME,
        DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        "retrieval.run",
        CALCULATOR_TOOL_NAME,
        FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
        FINANCE_SLOT_BIND_TOOL_NAME,
        FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        PROVIDED_CONTEXT_PARSE_TOOL_NAME,
        DATA_TABLE_QUERY_TOOL_NAME,
        MATH_SYMPY_COMPUTE_TOOL_NAME,
        CALENDAR_DAYS_BETWEEN_TOOL_NAME,
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        MARKET_OPENBB_FETCH_TOOL_NAME,
        "workspace.list",
        "workspace.search",
        "file.read",
        "workspace.write",
        "shell.exec",
        "script.exec",
    }

    assert audit["capability_claim"] is False
    assert audit["benchmark_progress_claim"] is False
    assert audit["interface_status"] == "ok"
    assert audit["fb_fqa_required_tool_status"] == "ok"
    assert audit["fb_fqa_required_tool_complete"] is True
    assert required <= set(tools)
    for name in required:
        assert tools[name]["allowed_by_recipe"] is True
        assert tools[name]["registered"] is True
        assert tools[name]["provider_visible"] is True
        assert tools[name]["planner_prompt_visible"] is True
        assert tools[name]["policy_allowed"] is True
    assert all(category["status"] == "ok" for category in audit["required_categories"])
    table_category = next(
        category
        for category in audit["required_categories"]
        if category["category_id"] == "financebench_filing_table_extraction"
    )
    assert PROVIDED_CONTEXT_PARSE_TOOL_NAME in table_category["required_tools"]
    assert DOCUMENT_SEARCH_HYBRID_TOOL_NAME in table_category["required_tools"]
    assert ARTIFACT_QUERY_NAME not in table_category["required_tools"]
    assert (
        tool_readiness.TOOL_COMPONENT_BINDINGS[ARTIFACT_QUERY_NAME]["install_policy"]
        == "legacy_fallback_only"
    )
    assert tools[DOCUMENT_SEARCH_HYBRID_TOOL_NAME]["component_binding"]["install_policy"] == "core_open_source"
    assert tools[DOCUMENT_DOCLING_CONVERT_TOOL_NAME]["component_binding"]["install_policy"] == "isolated_optional_heavy"
    assert tools[MARKET_OPENBB_FETCH_TOOL_NAME]["component_binding"]["install_policy"] == "isolated_optional_heavy"
    assert tools[DATA_TABLE_QUERY_TOOL_NAME]["component_binding"]["component_status"] == "ok"


def test_finance_tool_readiness_audit_local_smoke_executes_workbench_tools(tmp_path) -> None:
    audit = build_finance_tool_readiness_audit(workspace_root=tmp_path, execute_local_smoke=True)

    smoke = {item["tool"]: item for item in audit["local_smoke"]}

    assert audit["interface_status"] == "ok"
    assert audit["local_smoke_status"] == "ok"
    assert smoke[TOOL_DISCOVERY_NAME]["status"] == "ok"
    assert smoke[ARTIFACT_READ_NAME]["status"] == "ok"
    assert smoke[ARTIFACT_QUERY_NAME]["status"] == "ok"
    assert smoke[DOCUMENT_SEARCH_HYBRID_TOOL_NAME]["status"] == "ok"
    assert smoke[PROVIDED_CONTEXT_PARSE_TOOL_NAME]["status"] == "ok"
    assert smoke[FINANCE_SLOT_BIND_TOOL_NAME]["status"] == "ok"
    assert smoke[CALCULATOR_TOOL_NAME]["status"] == "ok"
    assert smoke[FINANCE_VERIFY_NUMERIC_TOOL_NAME]["status"] == "ok"
    assert smoke[DATA_TABLE_QUERY_TOOL_NAME]["status"] == "ok"
    assert smoke[MATH_SYMPY_COMPUTE_TOOL_NAME]["status"] == "ok"
    assert smoke[CALENDAR_DAYS_BETWEEN_TOOL_NAME]["status"] == "ok"
    assert smoke[DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME]["status"] == "ok"
    assert smoke["script.exec"]["status"] == "ok"


def test_finance_tool_readiness_accepts_configured_isolated_required_components(monkeypatch, tmp_path) -> None:
    def fake_isolated_component_status(component: str):
        configured = component in {"docling", "openbb"}
        return {
            "component": component,
            "configured": configured,
            "package_available": configured,
            "python": "/isolated/bin/python" if configured else None,
            "env_vars": [],
        }

    monkeypatch.setattr(tool_readiness, "isolated_component_status", fake_isolated_component_status)

    audit = tool_readiness.build_finance_tool_readiness_audit(workspace_root=tmp_path)
    tools = {item["name"]: item for item in audit["tools"]}

    assert audit["interface_status"] == "ok"
    assert audit["component_status"] == "ok"
    assert tools[DOCUMENT_DOCLING_CONVERT_TOOL_NAME]["component_binding"]["component_status"] == "ok"
    assert tools[MARKET_OPENBB_FETCH_TOOL_NAME]["component_binding"]["component_status"] == "ok"
    assert "docling" not in audit["toolchain_install_summary"]["required_missing_components"]
    assert "openbb" not in audit["toolchain_install_summary"]["required_missing_components"]
    summary = audit["toolchain_install_summary"]
    if "docling" in summary["missing_components"]:
        assert "docling" in summary["main_env_missing_but_isolated_ready_components"]
    if "openbb" in summary["missing_components"]:
        assert "openbb" in summary["main_env_missing_but_isolated_ready_components"]
    assert "docling" not in summary["optional_enhancement_missing_components"]
    assert "openbb" not in summary["optional_enhancement_missing_components"]


def test_finance_tool_audit_cli_returns_preflight_not_capability_claim(tmp_path) -> None:
    args = SimpleNamespace(
        bench_command="finance-tool-audit",
        execution_profile="finance-capability",
        no_live_network=False,
        execute_local_smoke=False,
        workspace_root=str(tmp_path),
        format="json",
    )

    payload = cli._bench_command(args, JournalStore.in_memory())

    assert payload["schema"] == "holo.kernel_v3.finance_tool_readiness.v1"
    assert payload["interface_status"] == "ok"
    assert payload["fb_fqa_required_tool_status"] == "ok"
    assert payload["fb_fqa_required_tool_complete"] is True
    assert payload["capability_claim"] is False
    assert payload["benchmark_progress_claim"] is False
