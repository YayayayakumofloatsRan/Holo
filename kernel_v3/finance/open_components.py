from __future__ import annotations

import importlib
import importlib.util
import os
from collections.abc import Mapping, Sequence
from typing import Any

from kernel_v3.contracts import CandidateAction, JsonObject, JsonValue, Observation, ToolManifest
from kernel_v3.tools import ToolRegistry


FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME = "finance.toolchain.describe"
SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME = "sec.edgar.company_filings"
SEC_EDGAR_FINANCIALS_TOOL_NAME = "sec.edgar.financials"
DOCUMENT_DOCLING_CONVERT_TOOL_NAME = "document.docling.convert"
MARKET_OPENBB_FETCH_TOOL_NAME = "market.openbb.fetch"

FINANCE_OPEN_COMPONENT_TOOL_NAMES = [
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
]

FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES = [
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
]

_OPENBB_ALLOWED_ROUTES = {
    "equity.price.historical",
    "equity.fundamental.metrics",
    "equity.fundamental.income",
    "equity.fundamental.balance",
    "equity.fundamental.cash",
    "index.price.historical",
    "crypto.price.historical",
    "currency.price.historical",
    "economy.fred_series",
}


def register_finance_open_component_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(
        FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
        _execute_toolchain_describe,
        manifest=ToolManifest(
            name=FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
            version="1",
            resource_kind="finance_toolchain",
            operator_kind="describe",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Describe optional mature finance components available to Holo: "
                "EdgarTools, Docling, OpenBB, and LangGraph readiness."
            ),
            input_schema={},
        ),
    )
    registry.register(
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        _execute_sec_company_filings,
        manifest=ToolManifest(
            name=SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
            version="1",
            resource_kind="sec_edgar",
            operator_kind="company_filings",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description="Use EdgarTools to list recent SEC filings for a company identifier, ticker, or CIK.",
            input_schema={
                "identifier": {"type": "str", "required": True, "min_length": 1},
                "form": {"type": "str", "required": False, "min_length": 1},
                "limit": {"type": "int", "required": False, "min": 1, "max": 25},
            },
        ),
    )
    registry.register(
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        _execute_sec_financials,
        manifest=ToolManifest(
            name=SEC_EDGAR_FINANCIALS_TOOL_NAME,
            version="1",
            resource_kind="sec_edgar",
            operator_kind="financials",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description=(
                "Use EdgarTools to retrieve standardized SEC/XBRL financial statement candidates. "
                "The model still chooses the relevant metric, period, unit, and formula."
            ),
            input_schema={
                "identifier": {"type": "str", "required": True, "min_length": 1},
                "form": {"type": "str", "required": False, "min_length": 1},
                "statement": {"type": "str", "required": False, "min_length": 1},
                "limit": {"type": "int", "required": False, "min": 1, "max": 200},
            },
        ),
    )
    registry.register(
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        _execute_docling_convert,
        manifest=ToolManifest(
            name=DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
            version="1",
            resource_kind="document",
            operator_kind="docling_convert",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description=(
                "Use Docling to convert a URL document into structured text or markdown. "
                "Only http(s) sources are accepted by this tool; local files must go through workspace tools."
            ),
            input_schema={
                "source": {"type": "str", "required": True, "min_length": 1, "aliases": ["url", "source_url"]},
                "output_format": {"type": "str", "required": False, "min_length": 1},
                "max_chars": {"type": "int", "required": False, "min": 500, "max": 20000},
            },
        ),
    )
    registry.register(
        MARKET_OPENBB_FETCH_TOOL_NAME,
        _execute_openbb_fetch,
        manifest=ToolManifest(
            name=MARKET_OPENBB_FETCH_TOOL_NAME,
            version="1",
            resource_kind="market_data",
            operator_kind="openbb_fetch",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description=(
                "Use OpenBB for allowlisted market/fundamental data routes. "
                "The model must decide whether market data is relevant to the finance question."
            ),
            input_schema={
                "route": {"type": "str", "required": True, "min_length": 1},
                "kwargs": {"type": "object", "required": False},
                "limit": {"type": "int", "required": False, "min": 1, "max": 500},
            },
        ),
    )
    return registry


def _execute_toolchain_describe(action: CandidateAction) -> Observation:
    content: JsonObject = {
        "schema": "holo.kernel_v3.finance_open_component_toolchain.v1",
        "host_boundary": (
            "Mature components supply source/data/document primitives; Holo still validates tool policy, "
            "records observations, preserves gold isolation, and leaves finance judgment to the LLM."
        ),
        "components": [
            _component_status(
                component="edgartools",
                import_name="edgar",
                package="edgartools",
                tools=[SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME],
                source="https://github.com/dgunning/edgartools",
            ),
            _component_status(
                component="docling",
                import_name="docling",
                package="docling",
                tools=[DOCUMENT_DOCLING_CONVERT_TOOL_NAME],
                source="https://docling-project.github.io/docling/",
            ),
            _component_status(
                component="openbb",
                import_name="openbb",
                package="openbb",
                tools=[MARKET_OPENBB_FETCH_TOOL_NAME],
                source="https://github.com/OpenBB-finance/OpenBB",
            ),
            _component_status(
                component="langgraph",
                import_name="langgraph",
                package="langgraph",
                tools=[],
                source="https://docs.langchain.com/oss/python/langgraph/overview",
                role="runtime_candidate_for_double_layer_agent_loop",
            ),
        ],
        "tool_names": list(FINANCE_OPEN_COMPONENT_TOOL_NAMES),
        "network_tool_names": list(FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES),
        "openbb_allowed_routes": sorted(_OPENBB_ALLOWED_ROUTES),
    }
    return _observation(action, "ok", content, kind="finance_toolchain_status")


def _execute_sec_company_filings(action: CandidateAction) -> Observation:
    edgar, error = _import_component("edgar", package="edgartools")
    if error is not None:
        return _observation(action, "failed", error, kind="sec_edgar_result")
    identity_error = _configure_edgar_identity(edgar)
    if identity_error is not None:
        return _observation(action, "failed", identity_error, kind="sec_edgar_result")
    identifier = str(action.payload.get("identifier") or "").strip()
    form = str(action.payload.get("form") or "10-K").strip() or "10-K"
    limit = _positive_int(action.payload.get("limit"), default=10, maximum=25)
    try:
        company = edgar.Company(identifier)
        filings = company.get_filings(form=form) if form else company.get_filings()
        limited = filings.head(limit) if hasattr(filings, "head") else filings
        records = _records_from_object(limited, limit=limit)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("edgartools", exc), kind="sec_edgar_result")
    return _observation(
        action,
        "ok",
        {
            "component": "edgartools",
            "identifier": identifier,
            "form": form,
            "limit": limit,
            "records": records,
            "semantic_decision_owner": "model",
        },
        kind="sec_edgar_result",
    )


def _execute_sec_financials(action: CandidateAction) -> Observation:
    edgar, error = _import_component("edgar", package="edgartools")
    if error is not None:
        return _observation(action, "failed", error, kind="sec_edgar_result")
    identity_error = _configure_edgar_identity(edgar)
    if identity_error is not None:
        return _observation(action, "failed", identity_error, kind="sec_edgar_result")
    identifier = str(action.payload.get("identifier") or "").strip()
    form = str(action.payload.get("form") or "10-K").strip() or "10-K"
    statement = _normalize_statement(str(action.payload.get("statement") or ""))
    limit = _positive_int(action.payload.get("limit"), default=80, maximum=200)
    try:
        company = edgar.Company(identifier)
        financials = _edgar_financials_for_company(company, form=form)
        statement_obj = _edgar_statement(financials, statement=statement)
        records = _records_from_object(statement_obj, limit=limit)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("edgartools", exc), kind="sec_edgar_result")
    return _observation(
        action,
        "ok",
        {
            "component": "edgartools",
            "identifier": identifier,
            "form": form,
            "statement": statement or "auto",
            "limit": limit,
            "records": records,
            "semantic_decision_owner": "model",
        },
        kind="sec_edgar_result",
    )


def _execute_docling_convert(action: CandidateAction) -> Observation:
    source = str(action.payload.get("source") or "").strip()
    if not source.lower().startswith(("https://", "http://")):
        return _observation(
            action,
            "blocked",
            {
                "error": "unsupported_source",
                "reason": "document.docling.convert currently accepts only http(s) sources; use workspace tools for local files.",
                "source_preview": source[:200],
            },
            kind="docling_conversion",
        )
    docling_converter, error = _import_component("docling.document_converter", package="docling")
    if error is not None:
        return _observation(action, "failed", error, kind="docling_conversion")
    output_format = str(action.payload.get("output_format") or "markdown").strip().lower()
    max_chars = _positive_int(action.payload.get("max_chars"), default=8000, maximum=20000)
    try:
        converter = docling_converter.DocumentConverter()
        result = converter.convert(source)
        document = result.document
        exported = _docling_export(document, output_format=output_format)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("docling", exc), kind="docling_conversion")
    return _observation(
        action,
        "ok",
        {
            "component": "docling",
            "source": source,
            "output_format": output_format,
            "text": _truncate(exported, max_chars),
            "text_chars": len(exported),
            "truncated": len(exported) > max_chars,
            "semantic_decision_owner": "model",
        },
        kind="docling_conversion",
    )


def _execute_openbb_fetch(action: CandidateAction) -> Observation:
    route = str(action.payload.get("route") or "").strip().lower()
    if route not in _OPENBB_ALLOWED_ROUTES:
        return _observation(
            action,
            "blocked",
            {
                "error": "route_not_allowlisted",
                "route": route,
                "allowed_routes": sorted(_OPENBB_ALLOWED_ROUTES),
                "reason": "OpenBB tool exposes only bounded read-only finance data routes.",
            },
            kind="openbb_result",
        )
    openbb, error = _import_component("openbb", package="openbb")
    if error is not None:
        return _observation(action, "failed", error, kind="openbb_result")
    kwargs = action.payload.get("kwargs") if isinstance(action.payload.get("kwargs"), dict) else {}
    limit = _positive_int(action.payload.get("limit"), default=100, maximum=500)
    try:
        obb = getattr(openbb, "obb", None)
        if obb is None:
            raise RuntimeError("openbb module does not expose obb")
        endpoint = obb
        for part in route.split("."):
            endpoint = getattr(endpoint, part)
        result = endpoint(**kwargs)
        records = _records_from_object(result, limit=limit)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("openbb", exc), kind="openbb_result")
    return _observation(
        action,
        "ok",
        {
            "component": "openbb",
            "route": route,
            "kwargs": _json_sanitize(kwargs),
            "limit": limit,
            "records": records,
            "semantic_decision_owner": "model",
        },
        kind="openbb_result",
    )


def _component_status(
    *,
    component: str,
    import_name: str,
    package: str,
    tools: list[str],
    source: str,
    role: str | None = None,
) -> JsonObject:
    installed = importlib.util.find_spec(import_name) is not None
    status: JsonObject = {
        "component": component,
        "package": package,
        "import_name": import_name,
        "installed": installed,
        "tools": list(tools),
        "source": source,
    }
    if role:
        status["role"] = role
    if not installed:
        status["install_hint"] = f"pip install {package}"
    return status


def _import_component(import_name: str, *, package: str) -> tuple[Any | None, JsonObject | None]:
    if importlib.util.find_spec(import_name) is None:
        return None, {
            "error": "dependency_missing",
            "component": package,
            "import_name": import_name,
            "install_hint": f"pip install {package}",
            "host_boundary": "tool did not run; no benchmark answer was inferred by host fallback",
        }
    try:
        return importlib.import_module(import_name), None
    except Exception as exc:
        return None, _component_exception(package, exc)


def _configure_edgar_identity(edgar: Any) -> JsonObject | None:
    identity = (
        os.environ.get("EDGAR_IDENTITY")
        or os.environ.get("SEC_EDGAR_IDENTITY")
        or os.environ.get("HOLO_SEC_IDENTITY")
    )
    if not identity:
        return {
            "error": "edgar_identity_missing",
            "component": "edgartools",
            "reason": "SEC EDGAR requests require an identity string. Set EDGAR_IDENTITY in the process environment.",
            "host_boundary": "tool did not run; no SEC data was fabricated",
        }
    set_identity = getattr(edgar, "set_identity", None)
    if callable(set_identity):
        set_identity(str(identity))
    return None


def _edgar_financials_for_company(company: Any, *, form: str) -> Any:
    if form:
        filings = company.get_filings(form=form)
        latest = filings.latest() if hasattr(filings, "latest") else None
        if latest is not None:
            filing_obj = latest.obj() if hasattr(latest, "obj") else latest
            financials = filing_obj.financials() if hasattr(filing_obj, "financials") else None
            if financials is not None:
                return financials
    if hasattr(company, "get_financials"):
        return company.get_financials()
    raise RuntimeError("edgartools Company object does not expose get_financials")


def _edgar_statement(financials: Any, *, statement: str) -> Any:
    candidates = {
        "income_statement": ["income_statement", "income", "statements_of_income"],
        "balance_sheet": ["balance_sheet", "balance", "balancesheet"],
        "cash_flow_statement": ["cash_flow_statement", "cashflow_statement", "cash_flow", "cashflow"],
    }
    names = candidates.get(statement, [])
    if not names:
        names = [
            "income_statement",
            "balance_sheet",
            "cash_flow_statement",
            "cashflow_statement",
        ]
    for name in names:
        attr = getattr(financials, name, None)
        if callable(attr):
            return attr()
        if attr is not None:
            return attr
    return financials


def _normalize_statement(value: str) -> str:
    text = " ".join(str(value or "").lower().replace("-", " ").replace("_", " ").split())
    if not text:
        return ""
    if "cash" in text and "flow" in text:
        return "cash_flow_statement"
    if "balance" in text:
        return "balance_sheet"
    if "income" in text or "operation" in text:
        return "income_statement"
    return text.replace(" ", "_")


def _docling_export(document: Any, *, output_format: str) -> str:
    if output_format in {"json", "dict"}:
        if hasattr(document, "export_to_dict"):
            return str(_json_sanitize(document.export_to_dict()))
        if hasattr(document, "model_dump"):
            return str(_json_sanitize(document.model_dump()))
    if output_format in {"html"}:
        exporter = getattr(document, "export_to_html", None)
        if callable(exporter):
            return str(exporter())
    exporter = getattr(document, "export_to_markdown", None)
    if callable(exporter):
        return str(exporter())
    return str(document)


def _records_from_object(value: Any, *, limit: int) -> list[JsonObject]:
    value = _object_to_records_source(value)
    if isinstance(value, list):
        return [_record(item) for item in value[:limit]]
    if isinstance(value, Mapping):
        return [_record(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_record(item) for item in list(value)[:limit]]
    return [_record({"value": str(value)[:2_000]})]


def _object_to_records_source(value: Any) -> Any:
    for method_name in ("to_dataframe", "to_pandas", "to_df"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                dataframe = method()
            except TypeError:
                continue
            return _dataframe_to_records(dataframe)
    if hasattr(value, "results"):
        return _object_to_records_source(getattr(value, "results"))
    if hasattr(value, "data"):
        return _object_to_records_source(getattr(value, "data"))
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except TypeError:
            pass
    return value


def _dataframe_to_records(dataframe: Any) -> list[JsonObject]:
    to_dict = getattr(dataframe, "to_dict", None)
    if not callable(to_dict):
        return [{"value": str(dataframe)[:2_000]}]
    try:
        records = to_dict(orient="records")
    except TypeError:
        records = to_dict()
    if isinstance(records, list):
        return [_record(item) for item in records]
    if isinstance(records, dict):
        return [_record(item) for item in records.values()] if all(isinstance(item, dict) for item in records.values()) else [_record(records)]
    return [{"value": str(records)[:2_000]}]


def _record(value: Any) -> JsonObject:
    sanitized = _json_sanitize(value)
    if isinstance(sanitized, dict):
        return sanitized
    return {"value": sanitized}


def _json_sanitize(value: Any, *, depth: int = 0) -> JsonValue:
    if depth > 8:
        return str(value)[:1_000]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        result: JsonObject = {}
        for key, item in list(value.items())[:200]:
            result[str(key)] = _json_sanitize(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_sanitize(item, depth=depth + 1) for item in list(value)[:500]]
    return str(value)[:2_000]


def _component_exception(component: str, exc: Exception) -> JsonObject:
    return {
        "error": "component_call_failed",
        "component": component,
        "error_type": type(exc).__name__,
        "message": str(exc)[:1_000],
        "host_boundary": "component failure is reported as observation; no answer is inferred by host fallback",
    }


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _truncate(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _observation(action: CandidateAction, status: str, content: JsonObject, *, kind: str) -> Observation:
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind=kind,
        status=status,
        source=f"tool:{action.name}",
        content=content,
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )
