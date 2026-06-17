from __future__ import annotations

import math

from kernel_v3.agent.runtime import task_recipe
from kernel_v3.contracts import CandidateAction
from kernel_v3.finance import (
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES,
    FINANCE_OPEN_COMPONENT_TOOL_NAMES,
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
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

    for tool_name in FINANCE_OPEN_COMPONENT_TOOL_NAMES:
        assert tool_name in manifests

    assert manifests[FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME].side_effect_class == "read"
    assert manifests[FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME].permissions_required == []
    for tool_name in FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES:
        assert manifests[tool_name].side_effect_class == "network"
        assert manifests[tool_name].permissions_required == ["network:fetch"]


def test_finance_toolchain_describe_reports_component_install_status(monkeypatch) -> None:
    def fake_find_spec(import_name: str):
        return object() if import_name == "edgar" else None

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
    assert components["openbb"]["install_hint"] == "pip install openbb"
    assert observation.content["host_boundary"].startswith("Mature components supply")


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
    assert SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME not in offline_recipe.allowed_tools
    assert SEC_EDGAR_FINANCIALS_TOOL_NAME not in offline_recipe.allowed_tools
    assert DOCUMENT_DOCLING_CONVERT_TOOL_NAME not in offline_recipe.allowed_tools
    assert MARKET_OPENBB_FETCH_TOOL_NAME not in offline_recipe.allowed_tools
    for tool_name in FINANCE_OPEN_COMPONENT_TOOL_NAMES:
        assert tool_name in live_recipe.allowed_tools
    assert "network:fetch" in live_recipe.metadata["allowed_permissions"]
