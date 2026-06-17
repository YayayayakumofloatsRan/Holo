from __future__ import annotations

import importlib
import importlib.util
import io
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kernel_v3.contracts import CandidateAction, JsonObject, JsonValue, Observation, ToolManifest
from kernel_v3.finance.tool_catalog import (
    FINANCE_TOOL_SURFACE_SCHEMA,
    finance_one_shot_tool_protocol,
    finance_tool_surface_catalog,
    finance_toolchain_install_summary,
)
from kernel_v3.tools import ToolRegistry


FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME = "finance.toolchain.describe"
SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME = "sec.edgar.company_filings"
SEC_EDGAR_FINANCIALS_TOOL_NAME = "sec.edgar.financials"
DOCUMENT_DOCLING_CONVERT_TOOL_NAME = "document.docling.convert"
DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME = "document.trafilatura.extract"
MARKET_OPENBB_FETCH_TOOL_NAME = "market.openbb.fetch"
DATA_TABLE_QUERY_TOOL_NAME = "data.table.query"
MATH_SYMPY_COMPUTE_TOOL_NAME = "math.sympy.compute"

FINANCE_OPEN_COMPONENT_TOOL_NAMES = [
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
]

FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES = [
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
]

FINANCE_OPEN_COMPONENT_READ_TOOL_NAMES = [
    DATA_TABLE_QUERY_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
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
                "Describe the complete finance tool surface available to Holo, including "
                "callable tools, mature open-source components, install status, and one-shot model call contracts."
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
        DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        _execute_trafilatura_extract,
        manifest=ToolManifest(
            name=DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
            version="1",
            resource_kind="document",
            operator_kind="trafilatura_extract",
            side_effect_class="network",
            permissions_required=["network:fetch"],
            enabled=True,
            description=(
                "Use Trafilatura to extract main readable text from an http(s) URL or provided HTML. "
                "The model decides when this extraction is relevant; host returns text candidates only."
            ),
            input_schema={
                "source": {"type": "str", "required": False, "min_length": 1, "aliases": ["url", "source_url"]},
                "html": {"type": "str", "required": False, "min_length": 1},
                "include_tables": {"type": "bool", "required": False},
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
    registry.register(
        DATA_TABLE_QUERY_TOOL_NAME,
        _execute_data_table_query,
        manifest=ToolManifest(
            name=DATA_TABLE_QUERY_TOOL_NAME,
            version="1",
            resource_kind="data_table",
            operator_kind="duckdb_query",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Use DuckDB/Pandas to run a read-only SQL SELECT over model-provided evidence rows or CSV text. "
                "This is for table normalization, joins, filters, and aggregation; it does not choose finance facts."
            ),
            input_schema={
                "sql": {"type": "str", "required": True, "min_length": 1},
                "rows": {"type": "list[object]", "required": False},
                "tables": {"type": "object", "required": False},
                "csv_text": {"type": "str", "required": False},
                "table_name": {"type": "str", "required": False},
                "limit": {"type": "int", "required": False, "min": 1, "max": 500},
            },
        ),
    )
    registry.register(
        MATH_SYMPY_COMPUTE_TOOL_NAME,
        _execute_sympy_compute,
        manifest=ToolManifest(
            name=MATH_SYMPY_COMPUTE_TOOL_NAME,
            version="1",
            resource_kind="math",
            operator_kind="sympy_compute",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Use SymPy for model-proposed symbolic simplification or exact numeric evaluation. "
                "For ordinary finance arithmetic, prefer calculator.compute; this tool is for harder formulas."
            ),
            input_schema={
                "expression": {"type": "str", "required": True, "min_length": 1},
                "variables": {"type": "object", "required": False},
                "operation": {"type": "str", "required": False},
                "precision": {"type": "int", "required": False, "min": 8, "max": 80},
            },
        ),
    )
    return registry


def _execute_toolchain_describe(action: CandidateAction) -> Observation:
    content: JsonObject = {
        "schema": "holo.kernel_v3.finance_open_component_toolchain.v1",
        "tool_surface_schema": FINANCE_TOOL_SURFACE_SCHEMA,
        "host_boundary": (
            "Mature components supply source/data/document primitives; Holo still validates tool policy, "
            "records observations, preserves gold isolation, and leaves finance judgment to the LLM."
        ),
        "one_shot_tool_protocol": finance_one_shot_tool_protocol(),
        "tool_surface": finance_tool_surface_catalog(),
        "install_summary": finance_toolchain_install_summary(),
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
                component="trafilatura",
                import_name="trafilatura",
                package="trafilatura",
                tools=[DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME],
                source="https://trafilatura.readthedocs.io/en/latest/",
            ),
            _component_status(
                component="openbb",
                import_name="openbb",
                package="openbb",
                tools=[MARKET_OPENBB_FETCH_TOOL_NAME],
                source="https://github.com/OpenBB-finance/OpenBB",
            ),
            _component_status(
                component="duckdb",
                import_name="duckdb",
                package="duckdb",
                tools=[DATA_TABLE_QUERY_TOOL_NAME],
                source="https://duckdb.org/docs/stable/",
            ),
            _component_status(
                component="sympy",
                import_name="sympy",
                package="sympy",
                tools=[MATH_SYMPY_COMPUTE_TOOL_NAME],
                source="https://www.sympy.org/en/index.html",
            ),
            _component_status(
                component="langgraph",
                import_name="langgraph",
                package="langgraph",
                tools=[],
                source="https://docs.langchain.com/oss/python/langgraph/overview",
                role="active_profile_loop_backend_first_stage",
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


def _execute_trafilatura_extract(action: CandidateAction) -> Observation:
    trafilatura, error = _import_component("trafilatura", package="trafilatura")
    if error is not None:
        return _observation(action, "failed", error, kind="trafilatura_extract")
    source = str(action.payload.get("source") or "").strip()
    html = str(action.payload.get("html") or "")
    include_tables = bool(action.payload.get("include_tables", True))
    max_chars = _positive_int(action.payload.get("max_chars"), default=8000, maximum=20000)
    if not html and not source:
        return _observation(
            action,
            "blocked",
            {
                "error": "missing_source_or_html",
                "reason": "provide either an http(s) source URL or an html string",
            },
            kind="trafilatura_extract",
        )
    if source and not source.lower().startswith(("https://", "http://")):
        return _observation(
            action,
            "blocked",
            {
                "error": "unsupported_source",
                "reason": "document.trafilatura.extract accepts only http(s) sources when fetching",
                "source_preview": source[:200],
            },
            kind="trafilatura_extract",
        )
    try:
        document_html = html
        fetched = False
        if not document_html:
            fetch_url = getattr(trafilatura, "fetch_url", None)
            if not callable(fetch_url):
                raise RuntimeError("trafilatura.fetch_url is unavailable")
            document_html = fetch_url(source) or ""
            fetched = True
        extract = getattr(trafilatura, "extract", None)
        if not callable(extract):
            raise RuntimeError("trafilatura.extract is unavailable")
        text = extract(
            document_html,
            output_format="txt",
            include_tables=include_tables,
            include_comments=False,
        )
    except Exception as exc:
        return _observation(action, "failed", _component_exception("trafilatura", exc), kind="trafilatura_extract")
    text = str(text or "")
    return _observation(
        action,
        "ok",
        {
            "component": "trafilatura",
            "source": source or None,
            "fetched": fetched,
            "include_tables": include_tables,
            "text": _truncate(text, max_chars),
            "text_chars": len(text),
            "truncated": len(text) > max_chars,
            "semantic_decision_owner": "model",
        },
        kind="trafilatura_extract",
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


def _execute_data_table_query(action: CandidateAction) -> Observation:
    duckdb, error = _import_component("duckdb", package="duckdb")
    if error is not None:
        return _observation(action, "failed", error, kind="data_table_query")
    pandas, pandas_error = _import_component("pandas", package="pandas")
    if pandas_error is not None:
        return _observation(action, "failed", pandas_error, kind="data_table_query")
    sql = str(action.payload.get("sql") or "").strip()
    if not _safe_readonly_sql(sql):
        return _observation(
            action,
            "blocked",
            {
                "error": "unsafe_or_unsupported_sql",
                "reason": "data.table.query accepts a single read-only SELECT/WITH query",
                "sql_preview": sql[:200],
            },
            kind="data_table_query",
        )
    limit = _positive_int(action.payload.get("limit"), default=100, maximum=500)
    try:
        tables = _table_query_inputs(action.payload, pandas)
        if not tables:
            return _observation(
                action,
                "blocked",
                {"error": "missing_table_data", "reason": "provide rows, tables, or csv_text"},
                kind="data_table_query",
            )
        connection = duckdb.connect(database=":memory:")
        registered: list[str] = []
        for table_name, dataframe in tables.items():
            safe_name = _safe_table_name(table_name)
            connection.register(safe_name, dataframe)
            registered.append(safe_name)
        cleaned_sql = sql.rstrip().rstrip(";")
        result_df = connection.execute(f"SELECT * FROM ({cleaned_sql}) AS model_query LIMIT {limit}").fetchdf()
        records = _dataframe_to_records(result_df)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("duckdb", exc), kind="data_table_query")
    finally:
        try:
            connection.close()  # type: ignore[name-defined]
        except Exception:
            pass
    return _observation(
        action,
        "ok",
        {
            "component": "duckdb",
            "registered_tables": registered,
            "sql": sql,
            "limit": limit,
            "records": records[:limit],
            "record_count": len(records),
            "semantic_decision_owner": "model",
        },
        kind="data_table_query",
    )


def _execute_sympy_compute(action: CandidateAction) -> Observation:
    sympy, error = _import_component("sympy", package="sympy")
    if error is not None:
        return _observation(action, "failed", error, kind="sympy_compute")
    expression = str(action.payload.get("expression") or "").strip()
    variables = action.payload.get("variables") if isinstance(action.payload.get("variables"), dict) else {}
    if not _safe_sympy_expression(expression) or not _safe_sympy_variables(variables):
        return _observation(
            action,
            "blocked",
            {
                "error": "unsafe_or_empty_expression",
                "reason": "math.sympy.compute accepts bounded math expressions with simple numeric substitutions only",
                "expression_preview": expression[:200],
            },
            kind="sympy_compute",
        )
    operation = str(action.payload.get("operation") or "simplify").strip().lower()
    precision = _positive_int(action.payload.get("precision"), default=28, maximum=80)
    try:
        locals_map = {str(key): sympy.Symbol(str(key)) for key in variables}
        parsed = sympy.sympify(expression, locals=locals_map)
        substitutions = {
            locals_map[str(key)]: sympy.sympify(str(value))
            for key, value in variables.items()
            if str(key) in locals_map and value is not None
        }
        substituted = parsed.subs(substitutions) if substitutions else parsed
        if operation in {"expand"}:
            result = sympy.expand(substituted)
        elif operation in {"factor"}:
            result = sympy.factor(substituted)
        elif operation in {"evaluate", "eval", "numeric", "n"}:
            result = sympy.N(substituted, precision)
        else:
            result = sympy.simplify(substituted)
        numeric = sympy.N(result, precision)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("sympy", exc), kind="sympy_compute")
    return _observation(
        action,
        "ok",
        {
            "component": "sympy",
            "expression": expression,
            "operation": operation,
            "variables": _json_sanitize(variables),
            "result": str(result),
            "numeric": str(numeric),
            "semantic_decision_owner": "model",
        },
        kind="sympy_compute",
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
    if import_name == "edgar":
        _prepare_edgar_environment()
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


def _prepare_edgar_environment() -> None:
    base = Path(os.environ.get("HOLO_EDGAR_CACHE_ROOT") or "/tmp/holo-edgar-cache")
    data_dir = Path(os.environ.get("EDGAR_LOCAL_DATA_DIR") or base / "data")
    cache_dir = Path(os.environ.get("EDGAR_CACHE_DIR") or base / "cache")
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", str(data_dir))
    os.environ.setdefault("EDGAR_CACHE_DIR", str(cache_dir))


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
            financials_attr = getattr(filing_obj, "financials", None)
            financials = financials_attr() if callable(financials_attr) else financials_attr
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


def _safe_readonly_sql(sql: str) -> bool:
    text = str(sql or "").strip()
    if not text or len(text) > 8_000:
        return False
    if ";" in text.rstrip(";"):
        return False
    lowered = re.sub(r"\s+", " ", text.casefold()).strip()
    if not lowered.startswith(("select ", "with ")):
        return False
    forbidden = (
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " create ",
        " attach ",
        " detach ",
        " copy ",
        " export ",
        " install ",
        " load ",
        " pragma ",
        " call ",
        " read_csv",
        " read_json",
        " read_parquet",
        " parquet_scan",
        " glob(",
        " httpfs",
        " sqlite_scan",
    )
    padded = f" {lowered} "
    return not any(item in padded for item in forbidden)


def _table_query_inputs(payload: JsonObject, pandas: Any) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    table_name = _safe_table_name(str(payload.get("table_name") or "evidence"))
    rows = payload.get("rows")
    if isinstance(rows, list) and rows:
        tables[table_name] = pandas.DataFrame([_record(row) for row in rows if isinstance(row, Mapping)])
    raw_tables = payload.get("tables")
    if isinstance(raw_tables, Mapping):
        for name, value in list(raw_tables.items())[:16]:
            if isinstance(value, list):
                tables[_safe_table_name(str(name))] = pandas.DataFrame(
                    [_record(row) for row in value if isinstance(row, Mapping)]
                )
    csv_text = payload.get("csv_text")
    if isinstance(csv_text, str) and csv_text.strip():
        tables[table_name] = pandas.read_csv(io.StringIO(csv_text[:1_000_000]))
    return {name: dataframe for name, dataframe in tables.items() if getattr(dataframe, "empty", True) is False}


def _safe_table_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "evidence").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"table_{cleaned or 'evidence'}"
    return cleaned[:64]


def _safe_sympy_expression(expression: str) -> bool:
    text = str(expression or "").strip()
    if not text or len(text) > 2_000:
        return False
    lowered = text.casefold()
    forbidden = ("__", "import", "exec", "eval", "open(", "compile(", "lambda", ";")
    if any(item in lowered for item in forbidden):
        return False
    if re.search(r"[A-Za-z_]\w*\s*\.", text):
        return False
    return re.fullmatch(r"[A-Za-z0-9_+\-*/().,\s^%<>=!]+", text) is not None


def _safe_sympy_variables(variables: Mapping[str, object]) -> bool:
    for key, value in variables.items():
        name = str(key)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) is None:
            return False
        if value is None:
            continue
        text = str(value).strip()
        if not text or len(text) > 200:
            return False
        if not _safe_sympy_expression(text):
            return False
        if re.fullmatch(r"[0-9eE+\-*/().,\s]+", text) is None:
            return False
    return True


def _json_sanitize(value: Any, *, depth: int = 0) -> JsonValue:
    if depth > 8:
        return str(value)[:1_000]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
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
