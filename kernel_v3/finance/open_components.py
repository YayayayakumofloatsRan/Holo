from __future__ import annotations

import ast
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
from datetime import date, datetime
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
DOCUMENT_SEARCH_HYBRID_TOOL_NAME = "document.search.hybrid"
PROVIDED_CONTEXT_PARSE_TOOL_NAME = "provided_context.parse"
MARKET_OPENBB_FETCH_TOOL_NAME = "market.openbb.fetch"
DATA_TABLE_QUERY_TOOL_NAME = "data.table.query"
MATH_SYMPY_COMPUTE_TOOL_NAME = "math.sympy.compute"
CALENDAR_DAYS_BETWEEN_TOOL_NAME = "calendar.days_between"

FINANCE_OPEN_COMPONENT_TOOL_NAMES = [
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    PROVIDED_CONTEXT_PARSE_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    CALENDAR_DAYS_BETWEEN_TOOL_NAME,
]

FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES = [
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
]

FINANCE_OPEN_COMPONENT_READ_TOOL_NAMES = [
    PROVIDED_CONTEXT_PARSE_TOOL_NAME,
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    CALENDAR_DAYS_BETWEEN_TOOL_NAME,
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
        "consolidated statement of income",
        "statement of income",
        "net income attributable",
        "net income attributable to",
        "net income including noncontrolling interest",
        "noncontrolling interest",
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

    def focus_snippets(text, payload, limit=20):
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
    max_chars = max(1, min(int(payload.get("max_chars") or 8000), 50000))
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
                "fiscal_year": {
                    "type": "int",
                    "required": False,
                    "min": 1900,
                    "max": 2100,
                    "description": "Optional requested fiscal year, e.g. 2022 for FY2022 target documents.",
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
                "max_chars": {"type": "int", "required": False, "min": 500, "max": 50000},
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
                "max_result_size_chars": 70000,
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
        DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        lambda action: _execute_document_search_hybrid(action, artifact_store=artifact_store),
        manifest=ToolManifest(
            name=DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
            version="1",
            resource_kind="document",
            operator_kind="hybrid_search",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Search a converted/document artifact with mature open-source retrieval components. "
                "Use this instead of artifact.query for finance evidence discovery in long filings, "
                "tables, and Docling/SEC payload artifacts."
            ),
            input_schema={
                "artifact_id": {"type": "str", "required": True, "min_length": 1},
                "query": {"type": "str", "required": True, "min_length": 1},
                "focus_terms": {
                    "type": "list[str]",
                    "required": False,
                    "description": "Model-selected line-item aliases or table labels to boost during retrieval.",
                },
                "slot_names": {
                    "type": "list[str]",
                    "required": False,
                    "description": "Optional missing slot names such as capital_expenditures or ppe_net.",
                },
                "fiscal_year": {"type": "int", "required": False, "min": 1900, "max": 2100},
                "period": {"type": "str", "required": False, "min_length": 1, "aliases": ["target_period"]},
                "max_matches": {"type": "int", "required": False, "min": 1, "max": 50},
                "max_chars": {"type": "int", "required": False, "min": 1000, "max": 50000},
                "chunk_lines": {"type": "int", "required": False, "min": 1, "max": 12},
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
        PROVIDED_CONTEXT_PARSE_TOOL_NAME,
        lambda action: _execute_provided_context_parse(action, artifact_store=artifact_store),
        manifest=ToolManifest(
            name=PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            version="1",
            resource_kind="provided_context",
            operator_kind="parse_tables",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Parse benchmark/user-provided report context into text blocks and query-ready tables. "
                "Use for FinQA/FQA oracle_context or copied filing/table snippets before data.table.query."
            ),
            input_schema={
                "context": {"type": "str", "required": True, "min_length": 1},
                "context_format": {
                    "type": "str",
                    "required": False,
                    "description": "Optional hint: auto, finqa, html, markdown, json.",
                },
                "table_name_prefix": {"type": "str", "required": False, "min_length": 1},
                "max_rows": {"type": "int", "required": False, "min": 1, "max": 5000},
                "max_chars": {"type": "int", "required": False, "min": 500, "max": 50000},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "timeout_seconds": 20,
                "max_result_size_chars": 50000,
                "result_persistence_policy": "auto",
                "idempotent": True,
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
    registry.register(
        CALENDAR_DAYS_BETWEEN_TOOL_NAME,
        _execute_calendar_days_between,
        manifest=ToolManifest(
            name=CALENDAR_DAYS_BETWEEN_TOOL_NAME,
            version="1",
            resource_kind="calendar",
            operator_kind="days_between",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Compute bounded day counts between two model-provided dates. "
                "Use for fiscal-period day counts after evidence supplies beginning and ending dates; "
                "the model still decides whether a finance formula should use 365, inclusive days, or actual fiscal days."
            ),
            input_schema={
                "start_date": {"type": "str", "required": True, "min_length": 1},
                "end_date": {"type": "str", "required": True, "min_length": 1},
                "label": {"type": "str", "required": False, "min_length": 1},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "timeout_seconds": 5,
                "max_result_size_chars": 12000,
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
                component="pandas",
                import_name="pandas",
                package="pandas",
                tools=[PROVIDED_CONTEXT_PARSE_TOOL_NAME, DATA_TABLE_QUERY_TOOL_NAME],
                source="https://pandas.pydata.org/docs/",
            ),
            _component_status(
                component="lxml",
                import_name="lxml",
                package="lxml",
                tools=[PROVIDED_CONTEXT_PARSE_TOOL_NAME],
                source="https://lxml.de/lxmlhtml.html",
            ),
            _component_status(
                component="beautifulsoup4",
                import_name="bs4",
                package="beautifulsoup4",
                tools=[PROVIDED_CONTEXT_PARSE_TOOL_NAME],
                source="https://beautiful-soup-4.readthedocs.io/en/latest/",
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
                component="python_datetime",
                import_name="datetime",
                package="python-stdlib",
                tools=[CALENDAR_DAYS_BETWEEN_TOOL_NAME],
                source="https://docs.python.org/3/library/datetime.html",
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
    fiscal_year = _optional_int(action.payload.get("fiscal_year"))
    period = str(action.payload.get("period") or action.payload.get("target_period") or "").strip()
    limit = _positive_int(action.payload.get("limit"), default=10, maximum=200)
    fetch_limit = max(limit, 200) if fiscal_year is not None or period else limit
    try:
        company = edgar.Company(identifier)
        filings = company.get_filings(form=form) if form else company.get_filings()
        limited = filings.head(fetch_limit) if hasattr(filings, "head") else filings
        raw_records = _records_from_object(limited, limit=fetch_limit)
        records, period_filter = _filter_sec_filing_records_by_period(
            raw_records,
            fiscal_year=fiscal_year,
            period=period,
            limit=limit,
        )
        cik = _sec_cik_from_identifier(identifier)
        records = [_with_sec_archive_urls(record, cik=cik) for record in records]
    except Exception as exc:
        return _observation(action, "failed", _component_exception("edgartools", exc), kind="sec_edgar_result")
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "edgartools",
            "identifier": identifier,
            "form": form,
            "requested_fiscal_year": fiscal_year,
            "requested_period": period or None,
            "period_filter": period_filter,
            "limit": limit,
            "records": records,
            "semantic_decision_owner": "model",
        },
        kind="sec_edgar_result",
        artifact_store=artifact_store,
        artifact_kind="sec_edgar_company_filings_payload",
    )


def _filter_sec_filing_records_by_period(
    records: list[JsonObject],
    *,
    fiscal_year: int | None,
    period: str,
    limit: int,
) -> tuple[list[JsonObject], JsonObject]:
    target_year = fiscal_year
    if target_year is None:
        years = [int(match.group(1)) for match in re.finditer(r"\b((?:19|20)\d{2})\b", str(period or ""))]
        target_year = years[-1] if years else None
    if target_year is None:
        return records[:limit], {
            "filter_applied": False,
            "input_record_count": len(records),
            "output_record_count": min(len(records), limit),
            "host_boundary": "no period was provided; recent filings are returned without period inference",
        }
    filtered: list[JsonObject] = []
    for record in records:
        filing_in_window = _sec_record_date_within_target_window(
            record,
            keys=("filing_date", "filingDate", "acceptanceDateTime"),
            target_year=target_year,
        )
        report_in_window = _sec_record_date_within_target_window(
            record,
            keys=("reportDate", "report_date"),
            target_year=target_year,
        )
        if filing_in_window or report_in_window:
            filtered.append(record)
    if filtered:
        filtered = sorted(filtered, key=lambda record: _sec_filing_period_sort_key(record, target_year=target_year))
    selected = filtered[:limit] if filtered else records[:limit]
    return selected, {
        "filter_applied": True,
        "requested_fiscal_year": target_year,
        "input_record_count": len(records),
        "matched_record_count": len(filtered),
        "output_record_count": len(selected),
        "filing_window": {
            "start": f"{target_year}-01-01",
            "end": f"{target_year + 1}-04-30",
            "reason": "FY target documents are usually filed during the target year or the following annual-report/Q4-results season",
        },
        "fallback_to_recent": not bool(filtered),
        "host_boundary": (
            "period filtering only narrows filing candidates; the model still chooses the relevant accession, "
            "document, exhibit, and source evidence"
        ),
    }


def _sec_record_date_within_target_window(
    record: Mapping[str, Any],
    *,
    keys: Sequence[str],
    target_year: int,
) -> bool:
    for key in keys:
        parsed = _sec_record_date_parts(str(record.get(key) or ""))
        if parsed is None:
            continue
        year, month = parsed
        if year == target_year:
            return True
        if year == target_year + 1 and month <= 4:
            return True
    return False


def _sec_record_date_parts(value: str) -> tuple[int, int] | None:
    match = re.search(r"\b((?:19|20)\d{2})(?:-(\d{1,2}))?", str(value or ""))
    if not match:
        return None
    try:
        year = int(match.group(1))
        month = int(match.group(2) or 1)
    except ValueError:
        return None
    return year, month


def _sec_filing_period_sort_key(record: Mapping[str, Any], *, target_year: int) -> tuple[int, str]:
    parsed = _sec_record_date_parts(
        str(
            record.get("filing_date")
            or record.get("filingDate")
            or record.get("acceptanceDateTime")
            or record.get("reportDate")
            or ""
        )
    )
    if parsed is None:
        return (9, "")
    year, month = parsed
    date_text = str(record.get("filing_date") or record.get("filingDate") or record.get("acceptanceDateTime") or "")
    if year == target_year + 1 and month <= 2:
        priority = 0
    elif year == target_year + 1 and month <= 4:
        priority = 1
    elif year == target_year:
        priority = 2
    else:
        priority = 3
    return (priority, date_text)


def _with_sec_archive_urls(record: JsonObject, *, cik: str | None) -> JsonObject:
    enriched = dict(record)
    accession = str(
        enriched.get("accession_number")
        or enriched.get("accessionNumber")
        or enriched.get("accession")
        or ""
    ).strip()
    cik_value = str(enriched.get("cik") or enriched.get("CIK") or cik or "").strip()
    archive_base = _sec_archive_base_url(cik_value, accession)
    if not archive_base:
        return enriched
    primary_document = str(enriched.get("primaryDocument") or enriched.get("primary_document") or "").strip()
    enriched.setdefault("sec_archive_base_url", archive_base)
    enriched.setdefault("filing_index_url", f"{archive_base}/index.json")
    enriched.setdefault("complete_submission_text_url", f"{archive_base}/{accession}.txt")
    if primary_document:
        enriched.setdefault("primary_document_url", f"{archive_base}/{primary_document}")
    return enriched


def _sec_archive_base_url(cik: str, accession: str) -> str | None:
    digits = "".join(ch for ch in str(cik or "") if ch.isdigit())
    compact_accession = re.sub(r"[^0-9]", "", str(accession or ""))
    if not digits or not compact_accession:
        return None
    try:
        cik_path = str(int(digits))
    except ValueError:
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{compact_accession}"


def _execute_sec_financials(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
    edgar, error = _import_component("edgar", package="edgartools")
    if error is not None:
        fallback = _execute_sec_financials_companyfacts_fallback(
            action,
            artifact_store=artifact_store,
            fallback_from=error,
        )
        if _tool_result_status(fallback) == "ok":
            return fallback
        return _observation(action, "failed", error, kind="sec_edgar_result")
    identity_error = _configure_edgar_identity(edgar)
    if identity_error is not None:
        fallback = _execute_sec_financials_companyfacts_fallback(
            action,
            artifact_store=artifact_store,
            fallback_from=identity_error,
        )
        if _tool_result_status(fallback) == "ok":
            return fallback
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
        component_error = _component_exception("edgartools", exc)
        fallback = _execute_sec_financials_companyfacts_fallback(
            action,
            artifact_store=artifact_store,
            fallback_from=component_error,
        )
        if _tool_result_status(fallback) == "ok":
            return fallback
        return _observation(action, "failed", component_error, kind="sec_edgar_result")
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


def _execute_sec_financials_companyfacts_fallback(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None,
    fallback_from: JsonObject,
) -> Observation | ToolResult:
    identifier = str(action.payload.get("identifier") or "").strip()
    form = str(action.payload.get("form") or "10-K").strip() or "10-K"
    statement = _normalize_statement(str(action.payload.get("statement") or ""))
    fiscal_year = _optional_int(action.payload.get("fiscal_year"))
    period = str(action.payload.get("period") or action.payload.get("target_period") or "").strip()
    limit = _positive_int(action.payload.get("limit"), default=80, maximum=200)
    cik = _sec_cik_from_identifier(identifier)
    if not cik:
        return _observation(
            action,
            "failed",
            {
                "error": "sec_companyfacts_fallback_identifier_unresolved",
                "component": "sec_companyfacts_direct",
                "identifier": identifier,
                "fallback_from": fallback_from,
                "host_boundary": "tool did not infer SEC facts without a resolvable CIK",
            },
            kind="sec_edgar_result",
        )
    try:
        payload = _fetch_sec_companyfacts_json(cik)
        raw_records = _sec_companyfacts_financial_records(
            payload,
            statement=statement,
            form=form,
            fiscal_year=fiscal_year,
            period=period,
        )
    except Exception as exc:
        return _observation(
            action,
            "failed",
            {
                **_component_exception("sec_companyfacts_direct", exc),
                "fallback_from": fallback_from,
            },
            kind="sec_edgar_result",
        )
    records = raw_records[:limit]
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "sec_companyfacts_direct",
            "fallback_from": fallback_from,
            "identifier": identifier,
            "cik": cik,
            "form": form,
            "statement": statement or "auto",
            "requested_fiscal_year": fiscal_year,
            "requested_period": period or None,
            "period_filter": {
                "requested_fiscal_year": fiscal_year,
                "requested_period": period or None,
                "input_record_count": len(raw_records),
                "output_record_count": len(records),
                "source": "official_sec_companyfacts_json",
                "host_boundary": "fallback only exposes SEC/XBRL candidate records; the model still chooses line items and formulas",
            },
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
    max_chars = _positive_int(action.payload.get("max_chars"), default=8000, maximum=50000)
    sec_text = _try_sec_archive_text_document_convert(
        action,
        source=source,
        output_format=output_format,
        max_chars=max_chars,
        artifact_store=artifact_store,
    )
    if sec_text is not None:
        return sec_text
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


def _try_sec_archive_text_document_convert(
    action: CandidateAction,
    *,
    source: str,
    output_format: str,
    max_chars: int,
    artifact_store: ArtifactStore | None,
) -> Observation | ToolResult | None:
    sec_text_url = _sec_archive_text_url_from_source(source)
    if not sec_text_url:
        return None
    try:
        data, metadata = _download_document_bytes(sec_text_url, byte_limit=_DOCUMENT_DOWNLOAD_BYTE_LIMIT)
        body = data.decode("utf-8", errors="replace")
        document = FetchedDocument(
            document_id=f"doc-{action.action_id}-sec-text",
            goal_id=f"goal-{action.action_id}",
            source_id=f"source-{action.action_id}-sec-text",
            uri=sec_text_url,
            title=Path(urllib.parse.urlparse(sec_text_url).path).name or sec_text_url,
            artifact_id=f"artifact-{action.action_id}-sec-text",
            payload_hash=str(metadata.get("sha256") or ""),
            preview=body[:500],
            size_bytes=len(data),
            metadata={"mime_type": metadata.get("mime_type") or "text/plain", "source_url": sec_text_url},
        )
        text, mode, diagnostics = readable_document_text_with_diagnostics(body, document=document)
    except Exception:
        return None
    text = str(text or body or "")
    if not text.strip():
        return None
    return _artifact_tool_result(
        action,
        "ok",
        {
            "component": "docling",
            "component_execution": "sec_archive_text_before_pdf",
            "source": source,
            "source_materialization": {
                "downloaded": True,
                "bytes": len(data),
                "mime_type": metadata.get("mime_type"),
                "sha256": metadata.get("sha256"),
                "alternate_source_url": sec_text_url,
                "alternate_source_reason": "source URL contains an SEC accession; official SEC complete submission text is better for filing table retrieval",
            },
            "output_format": output_format,
            "focus_snippets": _document_focus_snippets(text, action_payload=action.payload),
            "text": _truncate(text, max_chars),
            "text_chars": len(text),
            "truncated": len(text) > max_chars,
            "reader_mode": mode,
            "reader_diagnostics": diagnostics,
            "semantic_decision_owner": "model",
            "host_boundary": "SEC complete-submission text supplies source text candidates; finance interpretation remains model-owned",
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


def _execute_document_search_hybrid(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
    if artifact_store is None:
        return _observation(
            action,
            "blocked",
            {
                "error": "missing_artifact_store",
                "reason": "document.search.hybrid requires host artifact access",
            },
            kind="document_hybrid_search",
        )
    artifact_id = str(action.payload.get("artifact_id") or "").strip()
    query = str(action.payload.get("query") or "").strip()
    if not artifact_id or not query:
        return _observation(
            action,
            "blocked",
            {
                "error": "missing_artifact_or_query",
                "reason": "provide artifact_id and query",
                "artifact_id": artifact_id or None,
            },
            kind="document_hybrid_search",
        )
    ref = artifact_store.get(artifact_id)
    if ref is None:
        return _observation(
            action,
            "failed",
            {"error": "artifact_not_found", "artifact_id": artifact_id},
            kind="document_hybrid_search",
        )
    max_matches = _positive_int(action.payload.get("max_matches"), default=12, maximum=50)
    max_chars = _positive_int(action.payload.get("max_chars"), default=20000, maximum=50000)
    chunk_lines = _positive_int(action.payload.get("chunk_lines"), default=4, maximum=12)
    if artifact_store.has_blob(artifact_id):
        payload = artifact_store.read_blob(
            artifact_id,
            record_access=True,
            access_context={
                "tool": DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
                "action_id": action.action_id,
                "artifact_id": artifact_id,
            },
        )
        raw_text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        text, extraction = _document_search_text_from_artifact_payload(raw_text)
    else:
        text = str(ref.metadata.get("preview") or "")
        extraction = {"mode": "artifact_metadata_preview", "blob_available": False}
    if not text.strip():
        return _observation(
            action,
            "blocked",
            {
                "error": "empty_artifact_text",
                "artifact": ref.to_dict(),
                "extraction": extraction,
            },
            kind="document_hybrid_search",
        )

    rank_bm25, rank_error = _import_component("rank_bm25", package="rank-bm25")
    query_tokens, query_aliases = _document_search_query_tokens(action.payload)
    chunks = _document_search_chunks(text, chunk_lines=chunk_lines)
    matches = _rank_document_search_chunks(
        chunks,
        query_tokens=query_tokens,
        query_aliases=query_aliases,
        rank_bm25=rank_bm25,
        max_matches=max_matches,
        max_chars=max_chars,
        fiscal_year=_optional_int(action.payload.get("fiscal_year")),
        period=str(action.payload.get("period") or action.payload.get("target_period") or "").strip(),
    )
    status = "ok" if matches else "blocked"
    content: JsonObject = {
        "schema": "holo.kernel_v3.document_hybrid_search_result.v1",
        "component": "rank_bm25",
        "component_status": "ok" if rank_error is None else "fallback_lexical",
        "component_error": rank_error,
        "open_source_component_policy": {
            "active_now": ["rank-bm25"],
            "source_clones": [
                ".holo_components/src/haystack",
                ".holo_components/src/llama_index",
                ".holo_components/src/qdrant-client",
                ".holo_components/src/docling",
            ],
            "next_backend_targets": ["haystack", "qdrant-client", "llama-index"],
        },
        "artifact": ref.to_dict(),
        "artifact_id": artifact_id,
        "query": query,
        "query_aliases": query_aliases[:40],
        "extraction": extraction,
        "chunk_count": len(chunks),
        "matches": matches,
        "match_count": len(matches),
        "legacy_replacement_for": "artifact.query",
        "semantic_decision_owner": "model",
        "host_boundary": (
            "document.search.hybrid returns open-source retrieval candidates only; "
            "the model must still bind slots, choose periods, and request calculator/verifier tools."
        ),
    }
    if status != "ok":
        content["reason"] = "no_matching_chunks"
    return _artifact_tool_result(
        action,
        status,
        content,
        kind="document_hybrid_search",
        artifact_store=artifact_store,
        artifact_kind="document_hybrid_search_payload",
    )


def _document_search_text_from_artifact_payload(raw_text: str) -> tuple[str, JsonObject]:
    parsed = _parse_context_literal(raw_text)
    if isinstance(parsed, Mapping):
        parts: list[str] = []
        preferred_keys = ("text", "markdown", "content", "preview")
        for key in preferred_keys:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
        snippets = parsed.get("focus_snippets")
        if isinstance(snippets, list):
            for item in snippets[:80]:
                if isinstance(item, Mapping) and isinstance(item.get("snippet"), str):
                    parts.append(str(item.get("snippet")))
        for key in ("records", "tables", "text_blocks", "data_table_payloads"):
            value = parsed.get(key)
            _collect_document_search_strings(value, parts, max_parts=500)
        if not parts:
            _collect_document_search_strings(parsed, parts, max_parts=500)
        text = "\n".join(part for part in parts if str(part).strip())
        return text, {
            "mode": "json_payload",
            "top_level_keys": sorted(str(key) for key in list(parsed.keys())[:40]),
            "text_chars": len(text),
            "blob_available": True,
        }
    return raw_text, {
        "mode": "raw_text",
        "text_chars": len(raw_text),
        "blob_available": True,
    }


def _collect_document_search_strings(value: object, parts: list[str], *, max_parts: int, depth: int = 0) -> None:
    if len(parts) >= max_parts or depth > 6:
        return
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value).strip()
        if len(text) >= 12:
            parts.append(text[:5000])
        return
    if isinstance(value, Mapping):
        for key, item in list(value.items())[:100]:
            if len(parts) >= max_parts:
                break
            if isinstance(item, (str, Mapping, list, tuple)):
                if isinstance(item, str) and str(key).casefold() in {"id", "artifact_id", "hash", "schema"}:
                    continue
                _collect_document_search_strings(item, parts, max_parts=max_parts, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in list(value)[:300]:
            if len(parts) >= max_parts:
                break
            _collect_document_search_strings(item, parts, max_parts=max_parts, depth=depth + 1)


def _document_search_query_tokens(payload: JsonObject) -> tuple[list[str], list[str]]:
    aliases: list[str] = []
    raw_items: list[str] = [str(payload.get("query") or "")]
    for key in ("focus_terms", "slot_names"):
        value = payload.get(key)
        if isinstance(value, str):
            raw_items.append(value)
        elif isinstance(value, list):
            raw_items.extend(str(item) for item in value[:40])
    fiscal_year = _optional_int(payload.get("fiscal_year"))
    period = str(payload.get("period") or payload.get("target_period") or "").strip()
    if fiscal_year is not None:
        raw_items.extend([str(fiscal_year), f"FY{fiscal_year}", f"fiscal {fiscal_year}"])
    if period:
        raw_items.append(period)
    for item in raw_items:
        cleaned = " ".join(str(item or "").replace("_", " ").replace("-", " ").split())
        if not cleaned:
            continue
        aliases.append(cleaned)
        aliases.extend(_document_finance_aliases(cleaned))
    ordered_aliases = _ordered_unique_strings(aliases)
    tokens: list[str] = []
    for alias in ordered_aliases:
        tokens.extend(_document_search_tokenize(alias))
    return _ordered_unique_strings(tokens), ordered_aliases


def _document_finance_aliases(text: str) -> list[str]:
    normalized = _period_tokenize(text)
    aliases: list[str] = []
    if "capitalexpenditure" in normalized or "capex" in normalized:
        aliases.extend([
            "capital expenditures",
            "capex",
            "purchases of property plant and equipment",
            "purchase of property plant and equipment",
            "additions to property plant and equipment",
            "investing activities",
        ])
    if "propertyplantandequipment" in normalized or normalized in {"ppe", "ppenet"}:
        aliases.extend([
            "property plant and equipment net",
            "property, plant and equipment - net",
            "property, plant and equipment — net",
            "pp&e net",
            "ppe net",
        ])
    if "operatingcashflow" in normalized or "cashflowfromoperations" in normalized:
        aliases.extend([
            "net cash provided by operating activities",
            "cash flows provided by operating activities",
            "operating activities",
        ])
    if "revenue" in normalized or "netsales" in normalized:
        aliases.extend(["net sales", "revenue", "sales"])
    if "totalassets" in normalized or normalized == "assets":
        aliases.extend(["total assets", "assets"])
    if "netincome" in normalized or "netearnings" in normalized:
        aliases.extend(["net income", "net earnings"])
    return aliases


def _document_search_chunks(text: str, *, chunk_lines: int) -> list[JsonObject]:
    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in raw_lines if line]
    if len(lines) < 4:
        lines = [
            item.strip()
            for item in re.split(r"(?<=[.;:])\s+|\s{3,}", re.sub(r"\s+", " ", str(text or "")).strip())
            if item.strip()
        ]
    if not lines:
        return []
    chunk_lines = max(1, min(12, chunk_lines))
    step = max(1, chunk_lines // 2)
    chunks: list[JsonObject] = []
    seen: set[str] = set()
    for start in range(0, len(lines), step):
        selected = lines[start : start + chunk_lines]
        if not selected:
            continue
        chunk_text = "\n".join(selected)
        key = hashlib.sha1(chunk_text.encode("utf-8", errors="ignore")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        chunks.append(
            {
                "chunk_id": f"chunk-{len(chunks) + 1}",
                "start_line": start + 1,
                "end_line": start + len(selected),
                "text": chunk_text,
                "tokens": _document_search_tokenize(chunk_text),
            }
        )
        if len(chunks) >= 2500:
            break
    return chunks


def _rank_document_search_chunks(
    chunks: list[JsonObject],
    *,
    query_tokens: list[str],
    query_aliases: list[str],
    rank_bm25: Any,
    max_matches: int,
    max_chars: int,
    fiscal_year: int | None,
    period: str,
) -> list[JsonObject]:
    if not chunks or not query_tokens:
        return []
    tokenized = [list(chunk.get("tokens") or []) for chunk in chunks]
    scores: list[float]
    if rank_bm25 is not None:
        try:
            bm25 = rank_bm25.BM25Okapi(tokenized)
            scores = [float(score) for score in bm25.get_scores(query_tokens)]
        except Exception:
            scores = _lexical_document_search_scores(tokenized, query_tokens)
    else:
        scores = _lexical_document_search_scores(tokenized, query_tokens)
    target_tokens = _period_target_tokens(fiscal_year=fiscal_year, period=period)
    query_context = _document_search_query_context(query_tokens=query_tokens, query_aliases=query_aliases)
    scored: list[tuple[float, JsonObject]] = []
    for index, chunk in enumerate(chunks):
        text = str(chunk.get("text") or "")
        score = scores[index] if index < len(scores) else 0.0
        matched_aliases = [alias for alias in query_aliases if alias and alias.casefold() in text.casefold()]
        if matched_aliases:
            score += _document_search_alias_bonus(matched_aliases)
        score += _document_search_exact_signal_bonus(text, query_aliases=query_aliases, query_context=query_context)
        if target_tokens and _text_matches_period_target(text, target_tokens):
            score += 2.0
        noise_flags = _document_search_noise_flags(text)
        if "table_of_contents_like" in noise_flags:
            score -= 1.5
        if "delta_or_variance_language" in noise_flags:
            score -= 0.75
        if "disaggregated_revenue_detail" in noise_flags and query_context.get("asks_net_income"):
            score -= 1.25
        if score > 0:
            enriched = dict(chunk)
            enriched["score"] = round(score, 6)
            enriched["matched_aliases"] = matched_aliases[:16]
            enriched["period_signals"] = _document_search_period_signals(text)
            enriched["numeric_values"] = _document_search_numeric_values(text)
            enriched["noise_flags"] = noise_flags
            enriched.pop("tokens", None)
            scored.append((score, enriched))
    scored.sort(key=lambda item: item[0], reverse=True)
    matches: list[JsonObject] = []
    used_chars = 0
    for rank, (_, chunk) in enumerate(scored[: max_matches * 3], start=1):
        text = str(chunk.get("text") or "")
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        clipped = _truncate(text, min(remaining, 3000))
        used_chars += len(clipped)
        match = dict(chunk)
        match["rank"] = rank
        match["text"] = clipped
        match["truncated"] = len(clipped) < len(text)
        matches.append(match)
        if len(matches) >= max_matches:
            break
    return matches


def _document_search_query_context(*, query_tokens: list[str], query_aliases: list[str]) -> JsonObject:
    token_set = set(query_tokens)
    aliases_text = " ".join(query_aliases).casefold()
    requested_table_ids = [
        match.group(1)
        for alias in query_aliases
        for match in re.finditer(r"\bhtml\s+table(?:\s+fact)?\s+(\d{1,3})\b", alias.casefold())
    ]
    return {
        "asks_net_income": "net" in token_set and "income" in token_set,
        "asks_income_statement": "income" in token_set and "statement" in token_set,
        "aliases_text": aliases_text,
        "requested_html_table_ids": _ordered_unique_strings(requested_table_ids),
    }


def _document_search_alias_bonus(matched_aliases: list[str]) -> float:
    score = 0.0
    for alias in matched_aliases[:40]:
        token_count = len(_document_search_tokenize(alias))
        if token_count >= 5:
            score += 1.75
        elif token_count >= 3:
            score += 1.1
        elif token_count == 2:
            score += 0.65
        else:
            score += 0.15
    return min(7.0, score)


def _document_search_exact_signal_bonus(
    text: str,
    *,
    query_aliases: list[str],
    query_context: JsonObject,
) -> float:
    text_tokens = _document_search_tokenize(text)
    if not text_tokens:
        return 0.0
    text_token_set = set(text_tokens)
    normalized_text = " ".join(text_tokens)
    score = 0.0
    for alias in query_aliases[:60]:
        alias_tokens = _document_search_tokenize(alias)
        if len(alias_tokens) < 2:
            continue
        phrase = " ".join(alias_tokens)
        if phrase and phrase in normalized_text:
            score += min(3.0, 0.35 * len(alias_tokens))
        elif len(alias_tokens) >= 4 and all(token in text_token_set for token in alias_tokens):
            score += min(1.5, 0.15 * len(alias_tokens))
    requested_table_ids = [str(item) for item in query_context.get("requested_html_table_ids", [])]
    if requested_table_ids:
        table_ids = _document_search_html_table_ids(text)
        if any(table_id in table_ids for table_id in requested_table_ids):
            score += 3.0
        elif table_ids:
            score -= 1.0
    if query_context.get("asks_income_statement") and "statement of income" in str(text).casefold():
        score += 2.0
    if query_context.get("asks_net_income") and "net income attributable" in str(text).casefold():
        score += 2.0
    return score


def _document_search_html_table_ids(text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(
            r"\bhtml_table(?:_fact)?_(\d{1,3})(?:_|\b)",
            str(text or "").casefold(),
        )
    }


def _lexical_document_search_scores(tokenized: list[list[str]], query_tokens: list[str]) -> list[float]:
    query_set = set(query_tokens)
    return [float(sum(1 for token in tokens if token in query_set)) for tokens in tokenized]


def _document_search_tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", str(text or "").casefold())
        if len(token) > 1 or token.isdigit()
    ]


def _document_search_noise_flags(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    flags: list[str] = []
    note_count = len(re.findall(r"\bnote\s+\d+\b", lowered))
    if "table of contents" in lowered or (note_count >= 2 and re.search(r"\b(revenue|assets|income|cash flows?)\s+\d{1,3}\b", lowered)):
        flags.append("table_of_contents_like")
    if re.search(r"\b(decreased|increased|change[ds]?|compared to)\b", lowered):
        flags.append("delta_or_variance_language")
    if re.search(r"\baccession|cik|commission file number\b", lowered):
        flags.append("identifier_noise_possible")
    if "disaggregated revenue" in lowered or "disaggregated disclosures" in lowered:
        flags.append("disaggregated_revenue_detail")
    return flags


def _document_search_period_signals(text: str) -> list[str]:
    signals = re.findall(r"\b(?:FY\s*)?(?:19|20)\d{2}\b", str(text or ""), flags=re.IGNORECASE)
    signals.extend(re.findall(r"\b(?:year|years)\s+ended\s+[A-Za-z]+\s+\d{1,2},\s+(?:19|20)\d{2}\b", str(text or ""), flags=re.IGNORECASE))
    return _ordered_unique_strings(signals)[:16]


def _document_search_numeric_values(text: str) -> list[JsonObject]:
    values: list[JsonObject] = []
    pattern = re.compile(r"(?P<raw>\(?\$?\s?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?\s?(?:million|billion|%)?)", re.IGNORECASE)
    for match in pattern.finditer(str(text or "")):
        raw = match.group("raw").strip()
        if not raw or raw in {"(", ")"}:
            continue
        values.append({"raw": raw, "start": match.start(), "end": match.end()})
        if len(values) >= 32:
            break
    return values


def _ordered_unique_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _execute_provided_context_parse(
    action: CandidateAction,
    *,
    artifact_store: ArtifactStore | None = None,
) -> Observation | ToolResult:
    context = str(action.payload.get("context") or "")
    if not context.strip():
        return _observation(
            action,
            "blocked",
            {"error": "missing_context", "reason": "provided_context.parse requires a non-empty context string"},
            kind="provided_context_parse",
        )
    pandas, pandas_error = _import_component("pandas", package="pandas")
    if pandas_error is not None:
        return _observation(action, "failed", pandas_error, kind="provided_context_parse")
    context_format = str(action.payload.get("context_format") or "auto").strip().lower() or "auto"
    table_name_prefix = _safe_table_name(str(action.payload.get("table_name_prefix") or "provided_context_table"))
    max_rows = _positive_int(action.payload.get("max_rows"), default=500, maximum=5000)
    max_chars = _positive_int(action.payload.get("max_chars"), default=12000, maximum=50000)
    try:
        parsed = _parse_provided_context_to_tables(
            context,
            pandas=pandas,
            context_format=context_format,
            table_name_prefix=table_name_prefix,
            max_rows=max_rows,
            max_chars=max_chars,
        )
    except Exception as exc:
        return _observation(action, "failed", _component_exception("provided_context_parse", exc), kind="provided_context_parse")
    status = "ok" if parsed.get("text_blocks") or parsed.get("tables") else "blocked"
    if status != "ok":
        parsed["error"] = "no_parseable_context"
        parsed["reason"] = "no text blocks or table-like structures were found"
    return _artifact_tool_result(
        action,
        status,
        parsed,
        kind="provided_context_parse",
        artifact_store=artifact_store,
        artifact_kind="provided_context_parse_payload",
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


def _execute_calendar_days_between(action: CandidateAction) -> Observation:
    start_raw = str(action.payload.get("start_date") or "").strip()
    end_raw = str(action.payload.get("end_date") or "").strip()
    start_date = _parse_calendar_date(start_raw)
    end_date = _parse_calendar_date(end_raw)
    if start_date is None or end_date is None:
        return _observation(
            action,
            "failed",
            {
                "error": "date_parse_failed",
                "start_date": start_raw,
                "end_date": end_raw,
                "accepted_examples": ["2025-02-02", "2025/02/02", "February 2, 2025", "Feb 2, 2025"],
                "host_boundary": "date parsing failed; the model must provide evidence-backed date strings or choose a different formula basis",
            },
            kind="calendar_days_between",
        )
    days_exclusive = (end_date - start_date).days
    step = 1 if days_exclusive >= 0 else -1
    days_inclusive = days_exclusive + step
    return _observation(
        action,
        "ok",
        {
            "component": "python_datetime",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "label": str(action.payload.get("label") or "").strip(),
            "days_exclusive": days_exclusive,
            "days_inclusive": days_inclusive,
            "absolute_days_exclusive": abs(days_exclusive),
            "absolute_days_inclusive": abs(days_inclusive),
            "year_fraction_365_exclusive": days_exclusive / 365,
            "year_fraction_366_exclusive": days_exclusive / 366,
            "semantic_decision_owner": "model",
            "host_boundary": "returns calendar transforms only; model chooses the financial day-count basis",
        },
        kind="calendar_days_between",
    )


def _parse_calendar_date(value: str) -> date | None:
    text = " ".join(str(value or "").strip().replace(",", ", ").split())
    if not text:
        return None
    normalized = text.replace(".", "")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _parse_provided_context_to_tables(
    context: str,
    *,
    pandas: Any,
    context_format: str,
    table_name_prefix: str,
    max_rows: int,
    max_chars: int,
) -> JsonObject:
    sections = _provided_context_sections(context)
    text_blocks: list[JsonObject] = []
    table_candidates: list[tuple[str, object]] = []
    if sections:
        for section, raw_value in sections:
            parsed = _parse_context_literal(raw_value)
            if section in {"pre_text", "post_text", "context", "text"}:
                text_blocks.extend(_context_text_blocks(section, parsed, fallback=raw_value, max_chars=max_chars))
            elif section in {"table", "tables"}:
                table_candidates.extend(_context_table_candidates(section, parsed))
    else:
        parsed = _parse_context_literal(context)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                normalized = _safe_context_section_name(key)
                if normalized in {"pre_text", "post_text", "context", "text"}:
                    text_blocks.extend(_context_text_blocks(normalized, value, fallback=str(value), max_chars=max_chars))
                elif normalized in {"table", "tables"}:
                    table_candidates.extend(_context_table_candidates(normalized, value))
        elif isinstance(parsed, list) and _looks_like_matrix(parsed):
            table_candidates.append(("json_matrix", parsed))
        else:
            text_blocks.extend(_context_text_blocks("context", parsed, fallback=context, max_chars=max_chars))
    html_tables = _html_tables_from_context(context, pandas=pandas) if "<table" in context.casefold() else []
    markdown_tables = _markdown_tables_from_context(context)
    table_candidates.extend(("html_table", table) for table in html_tables)
    table_candidates.extend(("markdown_table", table) for table in markdown_tables)
    tables: list[JsonObject] = []
    for index, (source_section, value) in enumerate(table_candidates, start=1):
        table = _normal_table_from_value(
            value,
            name=f"{table_name_prefix}_{index}",
            source_section=source_section,
            max_rows=max_rows,
        )
        if table is not None:
            tables.append(table)
    data_table_payloads = [
        {
            "table_name": table["name"],
            "rows": table.get("rows", []),
            "sql_example": f"select * from {table['name']} limit 20",
            "limit": min(20, max_rows),
        }
        for table in tables
    ]
    return {
        "schema": "holo.kernel_v3.provided_context_parse_result.v1",
        "component": "pandas+lxml+beautifulsoup4",
        "context_format": context_format,
        "text_blocks": text_blocks,
        "text_block_count": len(text_blocks),
        "tables": tables,
        "table_count": len(tables),
        "data_table_payloads": data_table_payloads,
        "data_table_query_tool": DATA_TABLE_QUERY_TOOL_NAME,
        "host_boundary": (
            "provided_context.parse only structures given context into text/table candidates; "
            "the model still chooses relevant rows, formulas, and finance conclusions"
        ),
        "semantic_decision_owner": "model",
    }


def _provided_context_sections(context: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?im)(?:^|\n)\s*(pre_text|post_text|table|tables|context|text)\s*:\s*")
    matches = list(pattern.finditer(context))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        section = _safe_context_section_name(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(context)
        value = context[start:end].strip()
        if value:
            sections.append((section, value))
    return sections


def _parse_context_literal(text: object) -> object:
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped[0] in "[{":
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                return stripped
    return stripped


def _context_text_blocks(section: str, value: object, *, fallback: str, max_chars: int) -> list[JsonObject]:
    values: list[object]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
    elif isinstance(value, str) and value.strip():
        values = [value]
    elif fallback.strip():
        values = [fallback]
    else:
        values = []
    blocks: list[JsonObject] = []
    for index, item in enumerate(values, start=1):
        text = _normalize_snippet(item if isinstance(item, str) else json.dumps(_json_sanitize(item), ensure_ascii=False))
        if not text:
            continue
        blocks.append(
            {
                "section": section,
                "index": index,
                "text": _truncate(text, max_chars),
                "text_chars": len(text),
                "truncated": len(text) > max_chars,
            }
        )
    return blocks


def _context_table_candidates(section: str, value: object) -> list[tuple[str, object]]:
    if _looks_like_matrix(value):
        return [(section, value)]
    if isinstance(value, dict):
        candidates: list[tuple[str, object]] = []
        for key, item in value.items():
            if _looks_like_matrix(item) or _looks_like_records(item):
                candidates.append((f"{section}.{key}", item))
        return candidates
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if _looks_like_records(value):
            return [(section, value)]
        candidates = []
        for index, item in enumerate(value, start=1):
            if _looks_like_matrix(item) or _looks_like_records(item):
                candidates.append((f"{section}.{index}", item))
        return candidates
    return []


def _html_tables_from_context(context: str, *, pandas: Any) -> list[object]:
    try:
        frames = pandas.read_html(io.StringIO(context))
    except Exception:
        return []
    return [frame for frame in frames[:12]]


def _markdown_tables_from_context(context: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for raw_line in context.splitlines():
        line = raw_line.strip()
        if "|" not in line:
            if len(current) >= 2:
                tables.append(current)
            current = []
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells if cell):
            continue
        current.append(cells)
    if len(current) >= 2:
        tables.append(current)
    return tables[:12]


def _normal_table_from_value(value: object, *, name: str, source_section: str, max_rows: int) -> JsonObject | None:
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict(orient="records")
        except TypeError:
            records = value.to_dict()
        if isinstance(records, list):
            rows = [_record(item) for item in records if isinstance(item, dict)]
            columns = _ordered_columns_from_rows(rows)
            return _table_payload(name=name, source_section=source_section, columns=columns, rows=rows, max_rows=max_rows)
    if _looks_like_records(value):
        rows = [_record(item) for item in list(value) if isinstance(item, dict)]  # type: ignore[arg-type]
        columns = _ordered_columns_from_rows(rows)
        return _table_payload(name=name, source_section=source_section, columns=columns, rows=rows, max_rows=max_rows)
    if not _looks_like_matrix(value):
        return None
    matrix = [list(row) for row in value if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray))]  # type: ignore[union-attr]
    if not matrix:
        return None
    max_width = max(len(row) for row in matrix)
    normalized_matrix = [list(row) + [""] * (max_width - len(row)) for row in matrix]
    header = [str(cell or "").strip() for cell in normalized_matrix[0]]
    has_header = any(header) and len(normalized_matrix) > 1
    original_columns = header if has_header else [f"col_{index}" for index in range(1, max_width + 1)]
    columns = _safe_column_names(original_columns)
    data_rows = normalized_matrix[1:] if has_header else normalized_matrix
    rows = [
        {columns[index]: _cell_value(row[index]) for index in range(max_width)}
        for row in data_rows
    ]
    return _table_payload(
        name=name,
        source_section=source_section,
        columns=columns,
        rows=rows,
        max_rows=max_rows,
        original_columns=original_columns,
        matrix_preview=[[str(cell) for cell in row] for row in normalized_matrix[:8]],
    )


def _table_payload(
    *,
    name: str,
    source_section: str,
    columns: list[str],
    rows: list[JsonObject],
    max_rows: int,
    original_columns: list[str] | None = None,
    matrix_preview: list[list[str]] | None = None,
) -> JsonObject:
    safe_name = _safe_table_name(name)
    bounded_rows = rows[:max_rows]
    payload: JsonObject = {
        "name": safe_name,
        "source_section": source_section,
        "columns": columns,
        "rows": bounded_rows,
        "row_count": len(rows),
        "rows_truncated": len(rows) > len(bounded_rows),
        "data_table_query_payload": {"table_name": safe_name, "rows": bounded_rows},
    }
    if original_columns is not None:
        payload["original_columns"] = original_columns
    if matrix_preview is not None:
        payload["matrix_preview"] = matrix_preview
    return payload


def _looks_like_matrix(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and bool(value)
        and all(isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) for row in list(value)[:20])
    )


def _looks_like_records(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and bool(value)
        and all(isinstance(row, dict) for row in list(value)[:20])
    )


def _safe_context_section_name(value: object) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().casefold()).strip("_")
    return text or "context"


def _safe_column_names(values: list[str]) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        base = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_") or f"col_{index}"
        count = counts.get(base, 0) + 1
        counts[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def _ordered_columns_from_rows(rows: list[JsonObject]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            text = str(key)
            if text not in seen:
                seen.add(text)
                columns.append(text)
    return columns


def _cell_value(value: object) -> JsonValue:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


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
    "consolidated statement of income",
    "statement of income",
    "net income attributable",
    "net income attributable to",
    "net income including noncontrolling interest",
    "noncontrolling interest",
    "net income",
)


def _document_focus_snippets(text: str, *, action_payload: JsonObject, limit: int = 20) -> list[JsonObject]:
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


def _sec_archive_text_url_from_source(source: str) -> str | None:
    text = urllib.parse.unquote(str(source or ""))
    if not text:
        return None
    match = re.search(r"(?P<cik>\d{10})-(?P<year>\d{2})-(?P<seq>\d{6})", text)
    if not match:
        return None
    cik_padded = match.group("cik")
    try:
        cik_path = str(int(cik_padded))
    except ValueError:
        return None
    accession = f"{cik_padded}-{match.group('year')}-{match.group('seq')}"
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{compact}/{accession}.txt"


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


def _sec_cik_from_identifier(identifier: str) -> str | None:
    text = str(identifier or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits and (text.isdigit() or text.upper().startswith("CIK")):
        return digits.zfill(10)[-10:]
    try:
        from kernel_v3.research.issuer_registry import builtin_issuers_for_text

        for issuer in builtin_issuers_for_text(text):
            cik = str(issuer.get("sec_cik") or "").strip()
            if cik:
                return "".join(ch for ch in cik if ch.isdigit()).zfill(10)[-10:]
    except Exception:
        pass
    return None


def _fetch_sec_companyfacts_json(cik: str) -> JsonObject:
    url = _sec_companyfacts_source_uri(cik)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _finance_document_user_agent(),
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


def _sec_companyfacts_source_uri(cik: str) -> str:
    padded = "".join(ch for ch in str(cik or "") if ch.isdigit()).zfill(10)[-10:]
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json"


def _sec_companyfacts_financial_records(
    payload: JsonObject,
    *,
    statement: str,
    form: str,
    fiscal_year: int | None,
    period: str,
) -> list[JsonObject]:
    entity = str(payload.get("entityName") or "").strip()
    cik = str(payload.get("cik") or "").strip()
    source_uri = _sec_companyfacts_source_uri(cik)
    source_title = f"SEC companyfacts JSON for CIK {''.join(ch for ch in cik if ch.isdigit()).zfill(10)[-10:]}"
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    us_gaap = facts.get("us-gaap") if isinstance(facts.get("us-gaap"), dict) else {}
    concepts = _sec_companyfacts_concepts_for_statement(statement)
    records: list[JsonObject] = []
    for concept, metric in concepts:
        concept_payload = us_gaap.get(concept)
        if not isinstance(concept_payload, dict):
            continue
        label = str(concept_payload.get("label") or concept).strip()
        units = concept_payload.get("units") if isinstance(concept_payload.get("units"), dict) else {}
        for unit, unit_records in units.items():
            if not isinstance(unit_records, list):
                continue
            for record in unit_records:
                if not isinstance(record, dict):
                    continue
                if form and str(record.get("form") or "").upper() != form.upper():
                    continue
                if fiscal_year is not None and _optional_int(record.get("fy")) != fiscal_year:
                    continue
                if period and not _sec_companyfacts_record_matches_period(record, period):
                    continue
                value = record.get("val")
                if value in (None, ""):
                    continue
                records.append(
                    {
                        "entityName": entity,
                        "cik": cik,
                        "taxonomy": "us-gaap",
                        "concept": concept,
                        "label": label,
                        "metric": metric,
                        "unit": str(unit),
                        "scale": "actual",
                        "period": "annual" if str(record.get("fp") or "").upper() == "FY" else str(record.get("fp") or ""),
                        "fy": record.get("fy"),
                        "fp": record.get("fp"),
                        "form": record.get("form"),
                        "filed": record.get("filed"),
                        "start": record.get("start"),
                        "end": record.get("end"),
                        "frame": record.get("frame"),
                        "accn": record.get("accn"),
                        "value": value,
                        "val": value,
                        "source": "sec_xbrl_companyfacts_direct",
                        "source_uri": source_uri,
                        "source_title": source_title,
                        "source_kind": "sec_companyfacts_json",
                    }
                )
    records.sort(key=_sec_companyfacts_record_sort_key)
    return records


def _sec_companyfacts_concepts_for_statement(statement: str) -> list[tuple[str, str]]:
    balance_sheet = [
        ("Assets", "assets"),
        ("Liabilities", "liabilities"),
        ("StockholdersEquity", "shareholders equity"),
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "shareholders equity including noncontrolling interest"),
        ("PropertyPlantAndEquipmentNet", "property plant and equipment net"),
        ("InventoryNet", "inventory"),
        ("CashAndCashEquivalentsAtCarryingValue", "cash and cash equivalents"),
        ("DebtLongtermAndShorttermCombinedAmount", "debt"),
        ("LongTermDebt", "long-term debt"),
        ("LongTermDebtCurrent", "current long-term debt"),
        ("DebtCurrent", "short-term debt"),
    ]
    income_statement = [
        ("Revenues", "revenue"),
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "revenue"),
        ("SalesRevenueNet", "net sales"),
        ("NetIncomeLoss", "net income"),
        ("GrossProfit", "gross profit"),
        ("OperatingIncomeLoss", "operating income"),
        ("CostOfRevenue", "cost of revenue"),
        ("CostOfGoodsAndServicesSold", "cost of goods sold"),
    ]
    cash_flow_statement = [
        ("PaymentsToAcquirePropertyPlantAndEquipment", "capital expenditures"),
        ("NetCashProvidedByUsedInOperatingActivities", "operating cash flow"),
    ]
    if statement == "balance_sheet":
        return balance_sheet
    if statement == "income_statement":
        return income_statement
    if statement == "cash_flow_statement":
        return cash_flow_statement
    return [*balance_sheet, *income_statement, *cash_flow_statement]


def _sec_companyfacts_record_matches_period(record: JsonObject, period: str) -> bool:
    target = re.sub(r"[^a-z0-9]+", "", str(period or "").casefold())
    if not target:
        return True
    text = " ".join(str(record.get(key) or "") for key in ("fy", "fp", "start", "end", "frame", "filed"))
    normalized = re.sub(r"[^a-z0-9]+", "", text.casefold())
    return target in normalized


def _sec_companyfacts_record_sort_key(record: JsonObject) -> tuple[int, int, str]:
    metric_rank = {
        "property plant and equipment net": 0,
        "assets": 1,
        "liabilities": 2,
        "shareholders equity": 3,
        "inventory": 4,
        "cash and cash equivalents": 5,
        "capital expenditures": 6,
        "operating cash flow": 7,
        "revenue": 8,
        "net sales": 9,
        "net income": 10,
    }
    metric = str(record.get("metric") or "")
    return (metric_rank.get(metric, 50), -_sec_companyfacts_date_sort_value(record.get("end")), str(record.get("concept") or ""))


def _sec_companyfacts_date_sort_value(value: object) -> int:
    match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$", str(value or ""))
    if not match:
        return 0
    return int(match.group("year")) * 372 + int(match.group("month")) * 31 + int(match.group("day"))


def _tool_result_status(result: Observation | ToolResult) -> str:
    observation = result.observation if isinstance(result, ToolResult) else result
    return str(observation.status or "")


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
