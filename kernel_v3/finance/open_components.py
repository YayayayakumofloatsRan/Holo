from __future__ import annotations

import importlib
import importlib.util
import hashlib
import io
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import CandidateAction, JsonObject, JsonValue, Observation, ToolManifest
from kernel_v3.finance.tool_catalog import (
    FINANCE_TOOL_SURFACE_SCHEMA,
    finance_agent_loop_contract,
    finance_one_shot_tool_protocol,
    finance_tool_surface_catalog,
    finance_toolchain_install_summary,
)
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.extract import readable_document_text_with_diagnostics
from kernel_v3.tools import ToolRegistry, ToolResult


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

_ISOLATED_COMPONENT_ENV_VARS = {
    "docling": ("HOLO_DOCLING_PYTHON", "HOLO_FINANCE_COMPONENT_PYTHON"),
    "openbb": ("HOLO_OPENBB_PYTHON", "HOLO_FINANCE_COMPONENT_PYTHON"),
}
_ISOLATED_COMPONENT_IMPORT_NAMES = {
    "docling": "docling",
    "openbb": "openbb",
}
_ISOLATED_COMPONENT_TIMEOUT_SECONDS = 120
_DOCUMENT_DOWNLOAD_BYTE_LIMIT = 200_000_000
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ISOLATED_COMPONENT_PYTHONS = {
    "docling": _REPO_ROOT / ".holo_components" / "docling-worker" / "bin" / "python",
    "openbb": _REPO_ROOT / ".holo_components" / "openbb-worker" / "bin" / "python",
}
_LOCAL_OPENBB_HOME = _REPO_ROOT / ".holo_components" / "openbb-home"

_DOCLING_WORKER_SCRIPT = r"""
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

try:
    payload = json.load(sys.stdin)
    from docling.document_converter import DocumentConverter

    def export_document(document, output_format):
        if output_format in {"json", "dict"}:
            if hasattr(document, "export_to_dict"):
                return str(document.export_to_dict())
            if hasattr(document, "model_dump"):
                return str(document.model_dump())
        if output_format == "html" and hasattr(document, "export_to_html"):
            return str(document.export_to_html())
        if hasattr(document, "export_to_markdown"):
            return str(document.export_to_markdown())
        return str(document)

    def user_agent():
        return (
            os.environ.get("EDGAR_IDENTITY")
            or os.environ.get("SEC_EDGAR_IDENTITY")
            or os.environ.get("HOLO_SEC_IDENTITY")
            or "HoloKernelV3 finance document converter; contact=research@example.invalid"
        )

    def materialize_source(source, byte_limit):
        if not source.lower().startswith(("http://", "https://")):
            return source, None, {"downloaded": False}
        parsed = urllib.parse.urlparse(source)
        filename = Path(parsed.path).name or "document"
        suffix = Path(filename).suffix or ".bin"
        request = urllib.request.Request(
            source,
            headers={
                "User-Agent": user_agent(),
                "Accept": "application/pdf,text/html,application/xhtml+xml,*/*",
            },
            method="GET",
        )
        tmp_dir = tempfile.TemporaryDirectory(prefix="holo-docling-")
        target = Path(tmp_dir.name) / ("source" + suffix)
        total = 0
        with urllib.request.urlopen(request, timeout=45) as response:
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > byte_limit:
                        raise RuntimeError(f"document download exceeds byte limit: {byte_limit}")
                    handle.write(chunk)
        return target, tmp_dir, {
            "downloaded": True,
            "source_url": source,
            "local_name": target.name,
            "bytes": total,
        }

    DEFAULT_FOCUS_TERMS = (
        "purchases of property, plant and equipment",
        "property, plant and equipment",
        "capital expenditures",
        "cash flows from investing activities",
        "cash flows",
        "net cash provided by operating activities",
        "operating activities",
        "investing activities",
        "net sales",
        "revenue",
        "cost of sales",
        "cost of revenue",
        "inventories",
        "inventory",
        "total assets",
        "net income",
    )

    def ordered_focus_terms(value):
        terms = []
        seen = set()
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = [str(item) for item in value]
        else:
            candidates = []
        for candidate in candidates:
            term = str(candidate or "").strip()[:120]
            key = term.casefold()
            if term and key not in seen:
                seen.add(key)
                terms.append(term)
        for term in DEFAULT_FOCUS_TERMS:
            key = term.casefold()
            if key not in seen:
                seen.add(key)
                terms.append(term)
        return terms

    def focus_snippets(text, payload, limit=12):
        source_text = str(text or "")
        lowered = source_text.casefold()
        snippets = []
        used_ranges = []
        for term in ordered_focus_terms(payload.get("focus_terms")):
            needle = term.casefold().strip()
            if not needle:
                continue
            start = lowered.find(needle)
            if start < 0:
                continue
            left = max(0, start - 360)
            right = min(len(source_text), start + len(term) + 760)
            if any(not (right < used_left or left > used_right) for used_left, used_right in used_ranges):
                continue
            used_ranges.append((left, right))
            snippets.append({
                "term": term,
                "start_offset": start,
                "snippet": re.sub(r"\s+", " ", source_text[left:right]).strip(),
            })
            if len(snippets) >= limit:
                break
        return snippets

    source = str(payload.get("source") or "")
    output_format = str(payload.get("output_format") or "markdown").lower()
    max_chars = max(1, min(int(payload.get("max_chars") or 8000), 20000))
    byte_limit = max(1_000_000, min(int(payload.get("download_byte_limit") or 200_000_000), 500_000_000))
    converted_source, cleanup, materialization = materialize_source(source, byte_limit)
    try:
        result = DocumentConverter().convert(converted_source)
        exported = export_document(result.document, output_format)
    finally:
        if cleanup is not None:
            cleanup.cleanup()
    print(json.dumps({
        "status": "ok",
        "content": {
            "component": "docling",
            "source": source,
            "source_materialization": materialization,
            "output_format": output_format,
            "focus_snippets": focus_snippets(exported, payload),
            "text": exported[:max_chars - 3] + "..." if len(exported) > max_chars else exported,
            "text_chars": len(exported),
            "truncated": len(exported) > max_chars,
            "semantic_decision_owner": "model",
        },
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({
        "status": "failed",
        "content": {
            "error": "component_call_failed",
            "component": "docling",
            "error_type": type(exc).__name__,
            "message": str(exc)[:1000],
            "host_boundary": "isolated worker failure is an observation; no answer is inferred by host fallback",
        },
    }, ensure_ascii=False))
"""

_OPENBB_WORKER_SCRIPT = r"""
import json
import math
import sys
from collections.abc import Mapping, Sequence

try:
    payload = json.load(sys.stdin)
    import openbb

    def sanitize(value, depth=0):
        if depth > 8:
            return str(value)[:1000]
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, Mapping):
            return {str(k): sanitize(v, depth + 1) for k, v in list(value.items())[:200]}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [sanitize(item, depth + 1) for item in list(value)[:500]]
        return str(value)[:2000]

    def object_to_records_source(value):
        for method_name in ("to_dataframe", "to_pandas", "to_df"):
            method = getattr(value, method_name, None)
            if callable(method):
                try:
                    value = method()
                    break
                except TypeError:
                    pass
        if hasattr(value, "results"):
            return object_to_records_source(getattr(value, "results"))
        if hasattr(value, "data"):
            return object_to_records_source(getattr(value, "data"))
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except TypeError:
                pass
        return value

    def dataframe_to_records(dataframe):
        to_dict = getattr(dataframe, "to_dict", None)
        if not callable(to_dict):
            return [{"value": str(dataframe)[:2000]}]
        try:
            records = to_dict(orient="records")
        except TypeError:
            records = to_dict()
        if isinstance(records, list):
            return [record(item) for item in records]
        if isinstance(records, dict):
            if all(isinstance(item, dict) for item in records.values()):
                return [record(item) for item in records.values()]
            return [record(records)]
        return [{"value": str(records)[:2000]}]

    def record(value):
        value = sanitize(value)
        return value if isinstance(value, dict) else {"value": value}

    def records_from_object(value, limit):
        value = object_to_records_source(value)
        if hasattr(value, "to_dict"):
            return dataframe_to_records(value)[:limit]
        if isinstance(value, list):
            return [record(item) for item in value[:limit]]
        if isinstance(value, Mapping):
            return [record(value)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [record(item) for item in list(value)[:limit]]
        return [{"value": str(value)[:2000]}]

    route = str(payload.get("route") or "").lower()
    kwargs = payload.get("kwargs") if isinstance(payload.get("kwargs"), dict) else {}
    limit = max(1, min(int(payload.get("limit") or 100), 500))
    endpoint = getattr(openbb, "obb")
    for part in route.split("."):
        endpoint = getattr(endpoint, part)
    result = endpoint(**kwargs)
    print(json.dumps({
        "status": "ok",
        "content": {
            "component": "openbb",
            "route": route,
            "kwargs": sanitize(kwargs),
            "limit": limit,
            "records": records_from_object(result, limit),
            "semantic_decision_owner": "model",
        },
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({
        "status": "failed",
        "content": {
            "error": "component_call_failed",
            "component": "openbb",
            "error_type": type(exc).__name__,
            "message": str(exc)[:1000],
            "host_boundary": "isolated worker failure is an observation; no answer is inferred by host fallback",
        },
    }, ensure_ascii=False))
"""


def register_finance_open_component_tools(
    registry: ToolRegistry,
    *,
    artifact_store: ArtifactStore | None = None,
) -> ToolRegistry:
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "max_result_size_chars": 20000,
                "result_persistence_policy": "never",
                "idempotent": True,
            },
        ),
    )
    registry.register(
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        lambda action: _execute_sec_company_filings(action, artifact_store=artifact_store),
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "open_world": True,
                "always_load": True,
                "timeout_seconds": 45,
                "max_result_size_chars": 40000,
                "result_persistence_policy": "auto",
                "idempotent": False,
            },
        ),
    )
    registry.register(
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        lambda action: _execute_sec_financials(action, artifact_store=artifact_store),
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
                "fiscal_year": {
                    "type": "int",
                    "required": False,
                    "min": 1900,
                    "max": 2100,
                    "description": "Optional requested fiscal year, e.g. 2022 for FY2022.",
                },
                "period": {
                    "type": "str",
                    "required": False,
                    "min_length": 1,
                    "aliases": ["target_period"],
                    "description": "Optional requested period label such as FY2022 or fiscal 2024.",
                },
                "limit": {"type": "int", "required": False, "min": 1, "max": 200},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "open_world": True,
                "always_load": True,
                "timeout_seconds": 60,
                "max_result_size_chars": 50000,
                "result_persistence_policy": "auto",
                "idempotent": False,
            },
        ),
    )
    registry.register(
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        lambda action: _execute_docling_convert(action, artifact_store=artifact_store),
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
                "focus_terms": {
                    "type": "list[str]",
                    "required": False,
                    "description": "Optional model-selected terms to index in the converted document.",
                },
            },
            runtime={
                "concurrency_safe": False,
                "read_only": True,
                "open_world": True,
                "always_load": True,
                "interrupt_behavior": "cancel",
                "timeout_seconds": 120,
                "max_result_size_chars": 30000,
                "result_persistence_policy": "auto",
                "idempotent": False,
            },
        ),
    )
    registry.register(
        DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        lambda action: _execute_trafilatura_extract(action, artifact_store=artifact_store),
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "open_world": True,
                "always_load": True,
                "timeout_seconds": 45,
                "max_result_size_chars": 30000,
                "result_persistence_policy": "auto",
                "idempotent": False,
            },
        ),
    )
    registry.register(
        MARKET_OPENBB_FETCH_TOOL_NAME,
        lambda action: _execute_openbb_fetch(action, artifact_store=artifact_store),
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "open_world": True,
                "always_load": True,
                "timeout_seconds": 45,
                "max_result_size_chars": 50000,
                "result_persistence_policy": "auto",
                "idempotent": False,
            },
        ),
    )
    registry.register(
        DATA_TABLE_QUERY_TOOL_NAME,
        lambda action: _execute_data_table_query(action, artifact_store=artifact_store),
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "timeout_seconds": 30,
                "max_result_size_chars": 50000,
                "result_persistence_policy": "auto",
                "idempotent": True,
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
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "timeout_seconds": 15,
                "max_result_size_chars": 20000,
                "result_persistence_policy": "never",
                "idempotent": True,
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
        "agent_loop_contract": finance_agent_loop_contract(),
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


def _execute_sec_company_filings(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
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
    return _artifact_tool_result(
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
        artifact_store=artifact_store,
        artifact_kind="sec_edgar_company_filings_payload",
    )


def _execute_sec_financials(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
    edgar, error = _import_component("edgar", package="edgartools")
    if error is not None:
        return _observation(action, "failed", error, kind="sec_edgar_result")
    identity_error = _configure_edgar_identity(edgar)
    if identity_error is not None:
        return _observation(action, "failed", identity_error, kind="sec_edgar_result")
    identifier = str(action.payload.get("identifier") or "").strip()
    form = str(action.payload.get("form") or "10-K").strip() or "10-K"
    statement = _normalize_statement(str(action.payload.get("statement") or ""))
    fiscal_year = _optional_int(action.payload.get("fiscal_year"))
    period = str(action.payload.get("period") or action.payload.get("target_period") or "").strip()
    limit = _positive_int(action.payload.get("limit"), default=80, maximum=200)
    try:
        company = edgar.Company(identifier)
        financials = _edgar_financials_for_company(company, form=form)
        statement_obj = _edgar_statement(financials, statement=statement)
        raw_records = _records_from_object(statement_obj, limit=max(limit, 200))
        records, period_filter = _filter_financial_records_by_period(
            raw_records,
            fiscal_year=fiscal_year,
            period=period,
            limit=limit,
        )
    except Exception as exc:
        return _observation(action, "failed", _component_exception("edgartools", exc), kind="sec_edgar_result")
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "edgartools",
            "identifier": identifier,
            "form": form,
            "statement": statement or "auto",
            "requested_fiscal_year": fiscal_year,
            "requested_period": period or None,
            "period_filter": period_filter,
            "limit": limit,
            "records": records,
            "semantic_decision_owner": "model",
        },
        kind="sec_edgar_result",
        artifact_store=artifact_store,
        artifact_kind="sec_edgar_financials_payload",
    )


def _execute_docling_convert(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
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
    output_format = str(action.payload.get("output_format") or "markdown").strip().lower()
    max_chars = _positive_int(action.payload.get("max_chars"), default=8000, maximum=20000)
    light_pdf = _try_light_pdf_document_convert(
        action,
        source=source,
        output_format=output_format,
        max_chars=max_chars,
        artifact_store=artifact_store,
    )
    if light_pdf is not None:
        return light_pdf
    docling_converter, error = _import_component("docling.document_converter", package="docling")
    if error is not None:
        isolated = _run_isolated_docling_convert(
            action,
            source=source,
            output_format=output_format,
            max_chars=max_chars,
            import_error=error,
        )
        if isolated is not None:
            return _artifact_result_from_observation(
                isolated,
                artifact_store=artifact_store,
                artifact_kind="docling_conversion_payload",
            )
        return _observation(action, "failed", _with_isolated_component_hint(error, "docling"), kind="docling_conversion")
    try:
        converter = docling_converter.DocumentConverter()
        result = converter.convert(source)
        document = result.document
        exported = _docling_export(document, output_format=output_format)
    except Exception as exc:
        return _observation(action, "failed", _component_exception("docling", exc), kind="docling_conversion")
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "docling",
            "source": source,
            "output_format": output_format,
            "focus_snippets": _document_focus_snippets(exported, action_payload=action.payload),
            "text": _truncate(exported, max_chars),
            "text_chars": len(exported),
            "truncated": len(exported) > max_chars,
            "semantic_decision_owner": "model",
        },
        kind="docling_conversion",
        artifact_store=artifact_store,
        artifact_kind="docling_conversion_payload",
    )


def _try_light_pdf_document_convert(
    action: CandidateAction,
    *,
    source: str,
    output_format: str,
    max_chars: int,
    artifact_store: ArtifactStore | None,
) -> Observation | ToolResult | None:
    if not _looks_like_pdf_url(source):
        return None
    try:
        data, metadata = _download_document_bytes(source, byte_limit=_DOCUMENT_DOWNLOAD_BYTE_LIMIT)
        body = data.decode("latin-1", errors="ignore")
        document = FetchedDocument(
            document_id=f"doc-{action.action_id}",
            goal_id=f"goal-{action.action_id}",
            source_id=f"source-{action.action_id}",
            uri=source,
            title=Path(urllib.parse.urlparse(source).path).name or source,
            artifact_id=f"artifact-{action.action_id}-download",
            payload_hash=str(metadata.get("sha256") or ""),
            preview=body[:500],
            size_bytes=len(data),
            metadata={"mime_type": metadata.get("mime_type") or "application/pdf", "source_url": source},
        )
        text, mode, diagnostics = readable_document_text_with_diagnostics(body, document=document)
    except Exception:
        return None
    text = str(text or "")
    if not text.strip():
        return None
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "docling",
            "component_execution": "light_pdf_reader_before_docling",
            "source": source,
            "source_materialization": {
                "downloaded": True,
                "bytes": len(data),
                "mime_type": metadata.get("mime_type"),
                "sha256": metadata.get("sha256"),
            },
            "output_format": output_format,
            "focus_snippets": _document_focus_snippets(text, action_payload=action.payload),
            "text": _truncate(text, max_chars),
            "text_chars": len(text),
            "truncated": len(text) > max_chars,
            "reader_mode": mode,
            "reader_diagnostics": diagnostics,
            "semantic_decision_owner": "model",
            "host_boundary": "light PDF extraction supplies text candidates; finance interpretation remains model-owned",
        },
        kind="docling_conversion",
        artifact_store=artifact_store,
        artifact_kind="docling_conversion_payload",
    )


def _execute_trafilatura_extract(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
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
    return _artifact_tool_result(
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
        artifact_store=artifact_store,
        artifact_kind="trafilatura_extract_payload",
    )


def _execute_openbb_fetch(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
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
    kwargs = action.payload.get("kwargs") if isinstance(action.payload.get("kwargs"), dict) else {}
    limit = _positive_int(action.payload.get("limit"), default=100, maximum=500)
    openbb, error = _import_component("openbb", package="openbb")
    if error is not None:
        isolated = _run_isolated_openbb_fetch(
            action,
            route=route,
            kwargs=kwargs,
            limit=limit,
            import_error=error,
        )
        if isolated is not None:
            return _artifact_result_from_observation(
                isolated,
                artifact_store=artifact_store,
                artifact_kind="openbb_result_payload",
            )
        return _observation(action, "failed", _with_isolated_component_hint(error, "openbb"), kind="openbb_result")
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
    return _artifact_tool_result(
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
        artifact_store=artifact_store,
        artifact_kind="openbb_result_payload",
    )


def _execute_data_table_query(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
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
    return _artifact_tool_result(
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
        artifact_store=artifact_store,
        artifact_kind="data_table_query_payload",
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


def isolated_component_status(component: str) -> JsonObject:
    normalized = str(component or "").strip().lower()
    env_vars = list(_ISOLATED_COMPONENT_ENV_VARS.get(normalized, ()))
    python = _isolated_component_python(normalized)
    package_available = _isolated_component_package_available(normalized, python) if python else None
    return {
        "component": normalized,
        "configured": bool(python),
        "package_available": package_available.get("available") if isinstance(package_available, dict) else None,
        "package_probe_error": package_available.get("error") if isinstance(package_available, dict) else None,
        "python": python,
        "env_vars": env_vars,
        "timeout_seconds": _isolated_component_timeout_seconds(),
        "host_boundary": "isolated worker is optional; main Holo remains stable and reports worker failures as observations",
    }


def _run_isolated_docling_convert(
    action: CandidateAction,
    *,
    source: str,
    output_format: str,
    max_chars: int,
    import_error: JsonObject,
) -> Observation | None:
    worker = _run_isolated_component(
        "docling",
        payload={
            "source": source,
            "output_format": output_format,
            "max_chars": max_chars,
            "focus_terms": _ordered_focus_terms(action.payload.get("focus_terms")),
        },
        script=_DOCLING_WORKER_SCRIPT,
    )
    if worker is None:
        return None
    content = dict(worker.get("content")) if isinstance(worker.get("content"), dict) else {}
    content.setdefault("component", "docling")
    if isinstance(content.get("text"), str) and "focus_snippets" not in content:
        content["focus_snippets"] = _document_focus_snippets(str(content.get("text") or ""), action_payload=action.payload)
    content["component_execution"] = "isolated_worker"
    content["main_process_import_error"] = import_error
    return _observation(action, str(worker.get("status") or "failed"), _record(content), kind="docling_conversion")


def _run_isolated_openbb_fetch(
    action: CandidateAction,
    *,
    route: str,
    kwargs: JsonObject,
    limit: int,
    import_error: JsonObject,
) -> Observation | None:
    worker = _run_isolated_component(
        "openbb",
        payload={"route": route, "kwargs": kwargs, "limit": limit},
        script=_OPENBB_WORKER_SCRIPT,
    )
    if worker is None:
        return None
    content = dict(worker.get("content")) if isinstance(worker.get("content"), dict) else {}
    content.setdefault("component", "openbb")
    content["component_execution"] = "isolated_worker"
    content["main_process_import_error"] = import_error
    return _observation(action, str(worker.get("status") or "failed"), _record(content), kind="openbb_result")


def _run_isolated_component(component: str, *, payload: JsonObject, script: str) -> JsonObject | None:
    python = _isolated_component_python(component)
    if not python:
        return None
    env = _isolated_component_env(component)
    try:
        completed = subprocess.run(
            [python, "-c", script],
            input=json.dumps(payload, ensure_ascii=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_isolated_component_timeout_seconds(),
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "content": {
                "error": "isolated_component_timeout",
                "component": component,
                "timeout_seconds": _isolated_component_timeout_seconds(),
                "stderr": str(exc.stderr or "")[:1_000],
                "isolated_worker": isolated_component_status(component),
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "content": {
                "error": "isolated_component_launch_failed",
                "component": component,
                "error_type": type(exc).__name__,
                "message": str(exc)[:1_000],
                "isolated_worker": isolated_component_status(component),
            },
        }
    if completed.returncode != 0:
        return {
            "status": "failed",
            "content": {
                "error": "isolated_component_process_failed",
                "component": component,
                "returncode": completed.returncode,
                "stderr": completed.stderr[:2_000],
                "stdout_preview": completed.stdout[:1_000],
                "isolated_worker": isolated_component_status(component),
            },
        }
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "failed",
            "content": {
                "error": "isolated_component_invalid_json",
                "component": component,
                "error_type": type(exc).__name__,
                "stdout_preview": completed.stdout[:2_000],
                "stderr": completed.stderr[:1_000],
                "isolated_worker": isolated_component_status(component),
            },
        }
    content = parsed.get("content") if isinstance(parsed, dict) and isinstance(parsed.get("content"), dict) else {}
    content["isolated_worker"] = isolated_component_status(component)
    if completed.stderr:
        content["stderr_preview"] = completed.stderr[:1_000]
    return {
        "status": str(parsed.get("status") or "failed") if isinstance(parsed, dict) else "failed",
        "content": _record(content),
    }


_DEFAULT_DOCUMENT_FOCUS_TERMS = (
    "purchases of property, plant and equipment",
    "property, plant and equipment",
    "capital expenditures",
    "cash flows from investing activities",
    "cash flows",
    "net cash provided by operating activities",
    "operating activities",
    "investing activities",
    "net sales",
    "revenue",
    "cost of sales",
    "cost of revenue",
    "inventories",
    "inventory",
    "total assets",
    "net income",
)


def _document_focus_snippets(text: str, *, action_payload: JsonObject, limit: int = 12) -> list[JsonObject]:
    source_text = str(text or "")
    if not source_text:
        return []
    terms = _ordered_focus_terms(action_payload.get("focus_terms"))
    terms.extend(term for term in _DEFAULT_DOCUMENT_FOCUS_TERMS if term.casefold() not in {item.casefold() for item in terms})
    lowered = source_text.casefold()
    snippets: list[JsonObject] = []
    used_ranges: list[tuple[int, int]] = []
    for term in terms:
        needle = term.casefold().strip()
        if not needle:
            continue
        start = lowered.find(needle)
        if start < 0:
            continue
        left = max(0, start - 360)
        right = min(len(source_text), start + len(term) + 760)
        if any(not (right < used_left or left > used_right) for used_left, used_right in used_ranges):
            continue
        used_ranges.append((left, right))
        snippets.append(
            {
                "term": term,
                "start_offset": start,
                "snippet": _normalize_snippet(source_text[left:right]),
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


def _ordered_focus_terms(value: object) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = [str(item) for item in value]
    else:
        candidates = []
    seen: set[str] = set()
    for candidate in candidates:
        term = str(candidate or "").strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(term[:120])
    return result


def _normalize_snippet(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _looks_like_pdf_url(source: str) -> bool:
    parsed = urllib.parse.urlparse(str(source or ""))
    path = urllib.parse.unquote(parsed.path or "").lower()
    return path.endswith(".pdf")


def _download_document_bytes(source: str, *, byte_limit: int) -> tuple[bytes, JsonObject]:
    request = urllib.request.Request(
        source,
        headers={
            "User-Agent": _finance_document_user_agent(),
            "Accept": "application/pdf,text/html,application/xhtml+xml,*/*",
        },
        method="GET",
    )
    chunks: list[bytes] = []
    total = 0
    mime_type = ""
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            mime_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > byte_limit:
                    raise RuntimeError(f"document download exceeds byte limit: {byte_limit}")
                chunks.append(chunk)
    except urllib.error.URLError:
        raise
    data = b"".join(chunks)
    return data, {
        "mime_type": mime_type or ("application/pdf" if data.startswith(b"%PDF") else "application/octet-stream"),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _finance_document_user_agent() -> str:
    return (
        os.environ.get("EDGAR_IDENTITY")
        or os.environ.get("SEC_EDGAR_IDENTITY")
        or os.environ.get("HOLO_SEC_IDENTITY")
        or "HoloKernelV3 finance document converter; contact=research@example.invalid"
    )


def _isolated_component_python(component: str) -> str | None:
    normalized = str(component or "").strip().lower()
    for env_var in _ISOLATED_COMPONENT_ENV_VARS.get(normalized, ()):
        value = str(os.environ.get(env_var) or "").strip()
        if value:
            return value
    local_python = _LOCAL_ISOLATED_COMPONENT_PYTHONS.get(normalized)
    if local_python and local_python.exists():
        return str(local_python)
    return None


def _isolated_component_env(component: str) -> dict[str, str]:
    env = os.environ.copy()
    normalized = str(component or "").strip().lower()
    if normalized == "openbb":
        home = str(os.environ.get("HOLO_OPENBB_HOME") or "").strip()
        if not home:
            home = str(_LOCAL_OPENBB_HOME)
        env["HOME"] = home
    return env


def _isolated_component_package_available(component: str, python: str | None) -> JsonObject:
    if not python:
        return {"available": False, "error": "isolated_python_not_configured"}
    import_name = _ISOLATED_COMPONENT_IMPORT_NAMES.get(component)
    if not import_name:
        return {"available": None, "error": "unknown_component"}
    script = (
        "import importlib.util,json,sys;"
        "name=sys.argv[1];"
        "print(json.dumps({'available': importlib.util.find_spec(name) is not None}))"
    )
    try:
        completed = subprocess.run(
            [python, "-c", script, import_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=_isolated_component_env(component),
        )
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}:{str(exc)[:200]}"}
    if completed.returncode != 0:
        return {"available": False, "error": completed.stderr[:200] or f"returncode:{completed.returncode}"}
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"{type(exc).__name__}:{completed.stdout[:200]}"}
    return {"available": bool(parsed.get("available")), "error": None}


def _isolated_component_timeout_seconds() -> int:
    return _positive_int(
        os.environ.get("HOLO_FINANCE_COMPONENT_TIMEOUT_SECONDS"),
        default=_ISOLATED_COMPONENT_TIMEOUT_SECONDS,
        maximum=600,
    )


def _with_isolated_component_hint(error: JsonObject, component: str) -> JsonObject:
    updated = dict(error)
    updated["isolated_worker"] = isolated_component_status(component)
    return updated


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
    isolated = isolated_component_status(component)
    if isolated["env_vars"]:
        status["isolated_worker"] = isolated
    return status


def _import_component(import_name: str, *, package: str) -> tuple[Any | None, JsonObject | None]:
    if import_name == "edgar":
        _prepare_edgar_environment()
    try:
        spec = importlib.util.find_spec(import_name)
    except (ImportError, AttributeError, ValueError) as exc:
        return None, _dependency_missing(import_name=import_name, package=package, probe_error=exc)
    if spec is None:
        return None, _dependency_missing(import_name=import_name, package=package)
    try:
        return importlib.import_module(import_name), None
    except Exception as exc:
        return None, _component_exception(package, exc)


def _dependency_missing(
    *,
    import_name: str,
    package: str,
    probe_error: Exception | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "error": "dependency_missing",
        "component": package,
        "import_name": import_name,
        "install_hint": f"pip install {package}",
        "host_boundary": "tool did not run; no benchmark answer was inferred by host fallback",
    }
    if probe_error is not None:
        payload["probe_error_type"] = type(probe_error).__name__
        payload["probe_error_message"] = str(probe_error)[:500]
    return payload


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


def _filter_financial_records_by_period(
    records: list[JsonObject],
    *,
    fiscal_year: int | None,
    period: str,
    limit: int,
) -> tuple[list[JsonObject], JsonObject]:
    target_tokens = _period_target_tokens(fiscal_year=fiscal_year, period=period)
    diagnostics: JsonObject = {
        "requested_fiscal_year": fiscal_year,
        "requested_period": period or None,
        "input_record_count": len(records),
        "filter_applied": False,
        "period_signal_seen": False,
        "output_record_count": min(len(records), limit),
        "host_boundary": "period filtering only narrows SEC candidate records/columns; the model still chooses line items and formulas",
    }
    if not target_tokens:
        return records[:limit], diagnostics

    filtered: list[JsonObject] = []
    signal_seen = False
    for record in records:
        projected, projection = _project_financial_record_to_period(record, target_tokens=target_tokens)
        signal_seen = signal_seen or bool(projection.get("period_signal_seen"))
        if projection.get("matched"):
            filtered.append(projected)
        if len(filtered) >= limit:
            break

    diagnostics["period_signal_seen"] = signal_seen
    diagnostics["filter_applied"] = signal_seen
    if signal_seen:
        diagnostics["output_record_count"] = len(filtered)
        diagnostics["match_tokens"] = sorted(target_tokens)[:12]
        diagnostics["strict_no_match"] = not filtered
        return filtered, diagnostics

    diagnostics["reason"] = "no_period_columns_or_fields_detected"
    diagnostics["output_record_count"] = min(len(records), limit)
    return records[:limit], diagnostics


def _project_financial_record_to_period(record: JsonObject, *, target_tokens: set[str]) -> tuple[JsonObject, JsonObject]:
    projected: JsonObject = {}
    period_signal_seen = False
    matched = False
    dropped_period_keys: list[str] = []
    for key, value in record.items():
        key_text = str(key)
        value_text = str(value)
        key_has_period_signal = _looks_like_period_key(key_text)
        value_has_period_signal = _period_field_name(key_text) and _contains_year_or_fy(value_text)
        if key_has_period_signal or value_has_period_signal:
            period_signal_seen = True
            if _text_matches_period_target(key_text, target_tokens) or _text_matches_period_target(value_text, target_tokens):
                projected[key_text] = value
                matched = True
            else:
                dropped_period_keys.append(key_text)
            continue
        projected[key_text] = value
    if not period_signal_seen:
        for value in record.values():
            if isinstance(value, Mapping):
                nested = _json_sanitize(value)
                nested_text = json.dumps(nested, ensure_ascii=False, sort_keys=True, default=str)
                if _contains_year_or_fy(nested_text):
                    period_signal_seen = True
                    matched = _text_matches_period_target(nested_text, target_tokens)
                    break
    if matched:
        projected["_period_projection"] = {
            "matched": True,
            "dropped_period_keys": dropped_period_keys[:16],
        }
    return projected, {
        "period_signal_seen": period_signal_seen,
        "matched": matched,
    }


def _period_target_tokens(*, fiscal_year: int | None, period: str) -> set[str]:
    tokens: set[str] = set()
    if fiscal_year is not None:
        year = str(fiscal_year)
        tokens.update({year, f"fy{year}", f"fiscalyear{year}", f"fiscal{year}"})
    normalized_period = _period_tokenize(period)
    if normalized_period:
        tokens.add(normalized_period)
        match = re.search(r"(19|20)\d{2}", normalized_period)
        if match:
            year = match.group(0)
            tokens.update({year, f"fy{year}", f"fiscalyear{year}", f"fiscal{year}"})
    return {token for token in tokens if token}


def _text_matches_period_target(text: str, target_tokens: set[str]) -> bool:
    normalized = _period_tokenize(text)
    return any(token and token in normalized for token in target_tokens)


def _period_tokenize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def _period_field_name(key: str) -> bool:
    normalized = _period_tokenize(key)
    return any(marker in normalized for marker in ("period", "fiscal", "year", "fy", "date", "end", "frame"))


def _looks_like_period_key(key: str) -> bool:
    normalized = _period_tokenize(key)
    return bool(re.search(r"(19|20)\d{2}", normalized) or normalized.startswith("fy")) or _period_field_name(key)


def _contains_year_or_fy(text: str) -> bool:
    normalized = _period_tokenize(text)
    return bool(re.search(r"(19|20)\d{2}", normalized) or "fy" in normalized or "fiscal" in normalized)


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


def _artifact_tool_result(
    action: CandidateAction,
    status: str,
    content: JsonObject,
    *,
    kind: str,
    artifact_store: ArtifactStore | None,
    artifact_kind: str,
) -> Observation | ToolResult:
    observation = _observation(action, status, content, kind=kind)
    return _artifact_result_from_observation(
        observation,
        artifact_store=artifact_store,
        artifact_kind=artifact_kind,
    )


def _artifact_result_from_observation(
    observation: Observation,
    *,
    artifact_store: ArtifactStore | None,
    artifact_kind: str,
) -> Observation | ToolResult:
    if artifact_store is None or observation.status != "ok" or not isinstance(observation.content, dict):
        return observation
    content = _record(observation.content)
    payload_text = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    artifact = artifact_store.write_blob(
        kind=artifact_kind,
        payload=payload_text,
        mime_type="application/json",
        metadata={
            "tool": observation.source.removeprefix("tool:"),
            "action_id": observation.action_id or "",
            "observation_id": observation.observation_id,
            "observation_kind": observation.kind,
            "content_chars": len(payload_text),
        },
        redaction_status="unredacted_finance_tool_payload",
    )
    summary = _artifact_summary_content(
        content,
        artifact_id=artifact.artifact_id,
        artifact_uri=artifact.uri,
        artifact_kind=artifact.kind,
        payload_chars=len(payload_text),
    )
    return ToolResult(
        observation=Observation(
            observation_id=observation.observation_id,
            run_id=observation.run_id,
            kind=observation.kind,
            status=observation.status,
            source=observation.source,
            content=summary,
            observed_at_ms=observation.observed_at_ms,
            action_id=observation.action_id,
            tool_call_id=observation.tool_call_id,
        ),
        artifact_refs=[artifact],
    )


def _artifact_summary_content(
    content: JsonObject,
    *,
    artifact_id: str,
    artifact_uri: str,
    artifact_kind: str,
    payload_chars: int,
) -> JsonObject:
    summary: JsonObject = {}
    for key, value in content.items():
        if key == "records" and isinstance(value, list):
            preview_records = value[:20]
            summary["records"] = [_record(record) for record in preview_records]
            summary["records_preview_count"] = len(preview_records)
            summary["record_count"] = int(content.get("record_count") or len(value))
            if len(value) > len(preview_records):
                summary["records_truncated"] = True
            continue
        if key == "text" and isinstance(value, str):
            summary["text"] = _truncate(value, 4_000)
            summary["text_chars"] = int(content.get("text_chars") or len(value))
            summary["truncated"] = bool(content.get("truncated")) or len(value) > 4_000
            continue
        if key in {"record_count", "text_chars", "truncated"} and key in summary:
            continue
        if isinstance(value, str):
            summary[key] = _truncate(value, 1_000)
            continue
        if isinstance(value, list):
            summary[key] = [_json_sanitize(item) for item in value[:20]]
            if len(value) > 20:
                summary[f"{key}_truncated"] = True
            continue
        if isinstance(value, Mapping):
            summary[key] = _json_sanitize(value)
            continue
        summary[key] = _json_sanitize(value)
    summary["artifact_id"] = artifact_id
    summary["artifact_uri"] = artifact_uri
    summary["artifact_kind"] = artifact_kind
    summary["full_payload_artifact_id"] = artifact_id
    summary["full_payload_chars"] = payload_chars
    summary["artifact_read_hint"] = {
        "tool": "artifact.read",
        "payload": {"artifact_id": artifact_id, "mode": "read"},
    }
    return summary


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


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
