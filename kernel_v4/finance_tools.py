from __future__ import annotations

import re
import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from typing import Any

from kernel_v3.context import ArtifactStore as V3ArtifactStore
from kernel_v3.contracts import CandidateAction, PolicyDecision
from kernel_v3.finance.calculator import register_finance_tools
from kernel_v3.finance.open_components import (
    CALENDAR_DAYS_BETWEEN_TOOL_NAME,
    DATA_TABLE_QUERY_TOOL_NAME,
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    MATH_SYMPY_COMPUTE_TOOL_NAME,
    PROVIDED_CONTEXT_PARSE_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    _sec_cik_from_identifier,
    register_finance_open_component_tools,
)
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.extract import readable_document_text_with_diagnostics
from kernel_v3.tools import ToolRegistry as V3ToolRegistry
from kernel_v4.context import ToolUseContext
from kernel_v4.contracts import JsonObject, ToolManifest
from kernel_v4.runtime import ContextEdit
from kernel_v4.tooling import ToolRegistry

V4_FINANCE_TOOLCHAIN_DESCRIBE = "finance.toolchain.describe"
V4_FINANCE_TOOLCHAIN_AUDIT = "finance.toolchain.audit"
V4_FINANCE_WORKBENCH_OPEN = "finance.workbench.open"
V4_DOCUMENT_TEXT_EXTRACT = "document.text.extract"
V4_SEC_EDGAR_FILING_DOCUMENTS = "sec.edgar.filing_documents"
DOCUMENT_TEXT_EXTRACT_MAX_CHARS = 1_000_000
DOCUMENT_TEXT_EXTRACT_LEGAL_FOCUS_MIN_CHARS = 900_000
FORBIDDEN_LEGACY_TOOLS = {"finance.slot_bind"}


def register_finance_tool_surface(
    registry: ToolRegistry,
    *,
    allow_network: bool = True,
    artifact_store: V3ArtifactStore | None = None,
) -> ToolRegistry:
    """Register finance tools without importing v3's semantic gates."""

    artifact_store = artifact_store or V3ArtifactStore.in_memory()
    v3_registry = V3ToolRegistry.with_builtin_respond()
    register_finance_tools(v3_registry)
    register_finance_open_component_tools(v3_registry, artifact_store=artifact_store)
    registry.register(
        ToolManifest(
            name="artifact.read",
            description="Read a Kernel v4 artifact or a document/tool artifact produced by delegated mature finance tools.",
            input_schema={
                "artifact_id": {"type": "string", "required": True},
                "start": {"type": "integer", "required": False},
                "max_chars": {"type": "integer", "required": False},
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=50_000,
        ),
        _artifact_read_executor(artifact_store),
    )
    registry.register(
        ToolManifest(
            name="artifact.inspect",
            description="Inspect Kernel v4 artifacts and delegated finance document/tool artifacts.",
            input_schema={
                "artifact_id": {"type": "string", "required": False},
                "max_items": {"type": "integer", "required": False},
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=20_000,
        ),
        _artifact_inspect_executor(artifact_store),
    )
    registry.register(
        ToolManifest(
            name="artifact.search",
            description="Search Kernel v4 artifacts or delegated finance artifacts and return compact evidence snippets.",
            input_schema={
                "query": {"type": "string", "required": True},
                "artifact_id": {"type": "string", "required": False},
                "max_matches": {"type": "integer", "required": False},
                "window_chars": {"type": "integer", "required": False},
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=30_000,
        ),
        _artifact_search_executor(artifact_store),
    )
    if allow_network:
        registry.register(
            ToolManifest(
                name=V4_DOCUMENT_TEXT_EXTRACT,
                description=(
                    "Fast open-source URL/PDF/HTML text extraction using PyMuPDF/pypdf/readable HTML fallbacks. "
                    "Use for static company filing PDFs, 8-K Item 5.07 voting tables, proxy/vote tables, or when "
                    "document.docling.convert is slow or fails. Writes a readable text artifact for artifact.search/read."
                ),
                input_schema={
                    "source": {"type": "string", "required": True},
                    "focus_terms": {"type": "array", "required": False},
                    "max_chars": {"type": "integer", "required": False},
                },
                side_effect_class="network",
                concurrency_safe=True,
                always_load=True,
                timeout_seconds=90,
                max_result_chars=20_000,
            ),
            _document_text_extract_executor(artifact_store),
        )
        registry.register(
            ToolManifest(
                name=V4_SEC_EDGAR_FILING_DOCUMENTS,
                description=(
                    "Expand an official SEC EDGAR filing accession into primary document, complete submission text, "
                    "and exhibit/document URLs from the SEC archive index.json. Use after sec.edgar.company_filings "
                    "finds an accession, especially for earnings-release 8-K Exhibit 99.1, proxy exhibits, and target "
                    "filing documents when a company static URL is unavailable."
                ),
                input_schema={
                    "accession_number": {"type": "string", "required": True},
                    "identifier": {"type": "string", "required": False},
                    "cik": {"type": "string", "required": False},
                    "query": {"type": "string", "required": False},
                    "max_documents": {"type": "integer", "required": False},
                },
                side_effect_class="network",
                concurrency_safe=True,
                always_load=True,
                timeout_seconds=45,
                max_result_chars=25_000,
            ),
            _sec_edgar_filing_documents_executor(artifact_store),
        )

    for v3_manifest in v3_registry.manifests():
        if v3_manifest.name in {"__respond__", "__ask_user__", "system.time", V4_FINANCE_TOOLCHAIN_DESCRIBE}:
            continue
        if v3_manifest.name in FORBIDDEN_LEGACY_TOOLS:
            continue
        if not allow_network and v3_manifest.side_effect_class == "network":
            continue
        manifest = _from_v3_manifest(v3_manifest)
        registry.register(
            manifest,
            _v3_tool_executor(v3_registry=v3_registry, manifest_name=v3_manifest.name),
        )

    registry.register(
        ToolManifest(
            name=V4_FINANCE_WORKBENCH_OPEN,
            description=(
                "Open a finance task workbench for FinanceBench/FQA/FinQA-style tasks. It returns task-family "
                "evidence, transform, artifact, and verification contracts; semantic decisions remain with the model."
            ),
            input_schema={
                "query": {"type": "string", "required": False},
                "task_family": {
                    "type": "string",
                    "required": False,
                    "description": "Optional comma-separated finance task families to emphasize.",
                },
                "max_profiles": {"type": "integer", "required": False},
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=35_000,
        ),
        _finance_workbench_open,
    )
    registry.register(
        ToolManifest(
            name=V4_FINANCE_TOOLCHAIN_AUDIT,
            description=(
                "Audit the Kernel v4 finance toolchain for FB/FQA/FInQA theoretical closure. "
                "It reports profile/tool/schema coverage only; it does not solve benchmark tasks."
            ),
            input_schema={
                "mode": {
                    "type": "string",
                    "required": False,
                    "description": "Optional audit mode: full or no_network_fqa.",
                }
            },
            concurrency_safe=True,
            always_load=True,
            max_result_chars=30_000,
        ),
        _finance_toolchain_audit_executor(registry=registry, allow_network=allow_network),
    )
    registry.register(
        ToolManifest(
            name=V4_FINANCE_TOOLCHAIN_DESCRIBE,
            description=(
                "Describe the Kernel v4 finance tool surface. This is a tool catalog only; "
                "there is no FactLedger, SlotFrame, or finance.slot_bind gate."
            ),
            input_schema={},
            concurrency_safe=True,
            always_load=True,
            max_result_chars=60_000,
        ),
        _finance_toolchain_describe,
    )
    return registry


def register_calculator_tool_surface(registry: ToolRegistry) -> ToolRegistry:
    """Register only the mature calculator tool for focused tool-loop smoke tests."""

    v3_registry = V3ToolRegistry.with_builtin_respond()
    register_finance_tools(v3_registry)
    for v3_manifest in v3_registry.manifests():
        if v3_manifest.name != "calculator.compute":
            continue
        registry.register(
            _from_v3_manifest(v3_manifest),
            _v3_tool_executor(v3_registry=v3_registry, manifest_name=v3_manifest.name),
        )
    return registry


def finance_tool_names() -> list[str]:
    return [
        V4_FINANCE_WORKBENCH_OPEN,
        V4_FINANCE_TOOLCHAIN_AUDIT,
        V4_FINANCE_TOOLCHAIN_DESCRIBE,
        "tool.workbench",
        "tool.discovery",
        "artifact.inspect",
        "artifact.search",
        "artifact.read",
        V4_DOCUMENT_TEXT_EXTRACT,
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        V4_SEC_EDGAR_FILING_DOCUMENTS,
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
        DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        PROVIDED_CONTEXT_PARSE_TOOL_NAME,
        MARKET_OPENBB_FETCH_TOOL_NAME,
        DATA_TABLE_QUERY_TOOL_NAME,
        MATH_SYMPY_COMPUTE_TOOL_NAME,
        CALENDAR_DAYS_BETWEEN_TOOL_NAME,
        "calculator.compute",
        "finance.verify_numeric",
    ]


def _from_v3_manifest(manifest: Any) -> ToolManifest:
    runtime = dict(getattr(manifest, "runtime", {}) or {})
    side_effect = str(getattr(manifest, "side_effect_class", "read") or "read")
    input_schema = dict(manifest.input_schema or {})
    if manifest.name == PROVIDED_CONTEXT_PARSE_TOOL_NAME:
        input_schema.setdefault("context_ref", {"type": "string", "required": False})
    description = str(manifest.description or manifest.name)
    if manifest.name == DOCUMENT_DOCLING_CONVERT_TOOL_NAME:
        description = (
            description
            + " If a prior conversion used narrow focus_terms and a later required fact is missing, call this tool "
            "again on the original source with focus_terms for that missing line item or table. When an SEC accession "
            "is derivable from a filing URL, the tool may prefer the official SEC complete-submission text over a PDF."
        )
    elif manifest.name == DOCUMENT_SEARCH_HYBRID_TOOL_NAME:
        description = (
            description
            + " Search the artifact you actually want to inspect; if the artifact came from a narrow focused "
            "conversion and lacks a required fact, reconvert the original source with better focus_terms. "
            "When the returned snippet or a follow-up read contains the required line items for the formula, "
            "stop retrieval and compute instead of continuing broad search."
        )
    elif manifest.name == MARKET_OPENBB_FETCH_TOOL_NAME:
        description = (
            description
            + " Use only for explicit market-data needs such as prices, quotes, trading data, analyst estimates, "
            "or non-filing market fundamentals. Do not use for FinanceBench-style filing-accounting questions "
            "when SEC, company filing, provided context, or document artifacts contain the needed line items."
        )
    elif manifest.name == SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME:
        description = (
            description
            + " Include fiscal_year or period for target-document tasks so older 10-K, 8-K, proxy, or earnings "
            "filings are returned instead of only the latest recent filings. Returned records include SEC archive "
            "URLs when available; call sec.edgar.filing_documents on a relevant accession to list Exhibit 99.1 and "
            "other official filing documents."
        )
    elif manifest.name == SEC_EDGAR_FINANCIALS_TOOL_NAME:
        description = (
            description
            + " For target-document FinanceBench-style tasks, include the requested fiscal_year or period when "
            "known; otherwise the underlying component may default to the latest filing, including amended filings "
            "that lack full XBRL. For trend or change tasks, use explicit target/prior periods or the target filing "
            "document text instead of relying on an unqualified latest-period call."
        )
    return ToolManifest(
        name=str(manifest.name),
        description=description,
        input_schema=input_schema,
        side_effect_class=side_effect,
        concurrency_safe=bool(runtime.get("concurrency_safe", side_effect in {"read", "network", "none"})),
        enabled=bool(manifest.enabled),
        should_defer=bool(runtime.get("should_defer", False)),
        always_load=bool(runtime.get("always_load", True)),
        timeout_seconds=_int_or_none(runtime.get("timeout_seconds")),
        max_result_chars=_int_or_none(runtime.get("max_result_size_chars")) or 50_000,
    )


def _document_text_extract_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        source = str(payload.get("source") or payload.get("url") or "").strip()
        if not source:
            return {"error": "missing_source", "required": "source"}
        if not source.lower().startswith(("http://", "https://")):
            return {"error": "unsupported_source", "source": source, "supported": "http(s) URL"}
        max_chars = _bounded_positive_int(
            payload.get("max_chars"),
            default=80_000,
            upper=DOCUMENT_TEXT_EXTRACT_MAX_CHARS,
        )
        focus_terms = _payload_string_list(payload.get("focus_terms"))
        body_bytes, mime_type, final_url = _download_document_bytes(source)
        payload_hash = hashlib.sha256(body_bytes).hexdigest()
        body_text = _decode_document_body(body_bytes, mime_type=mime_type)
        document = FetchedDocument(
            document_id=f"doc-text-{payload_hash[:16]}",
            goal_id=context.run_id,
            source_id=f"url-{payload_hash[:12]}",
            uri=final_url or source,
            title=urllib.parse.urlparse(final_url or source).path.rsplit("/", 1)[-1] or "document",
            artifact_id="",
            payload_hash=payload_hash,
            preview=body_text[:256],
            size_bytes=len(body_bytes),
            metadata={
                "mime_type": mime_type,
                "source_kind": "direct_url",
                "source_metadata": {
                    "explicit_source_url": True,
                    "source_family": "company_filing",
                    "tool": V4_DOCUMENT_TEXT_EXTRACT,
                },
                "target_document_binding": {"source_url": source},
            },
        )
        full_text, mode, diagnostics = readable_document_text_with_diagnostics(body_text, document=document)
        full_text = str(full_text or "")
        legal_focus_expanded = False
        if _has_legal_focus_terms(focus_terms) and len(full_text) > max_chars:
            expanded_chars = min(len(full_text), DOCUMENT_TEXT_EXTRACT_LEGAL_FOCUS_MIN_CHARS)
            if expanded_chars > max_chars:
                max_chars = expanded_chars
                legal_focus_expanded = True
        text = _select_document_text(full_text, max_chars=max_chars, focus_terms=focus_terms)
        artifact = artifact_store.write_blob(
            kind="document_text_extract_payload",
            payload=text,
            mime_type="text/plain",
            metadata={
                "tool": V4_DOCUMENT_TEXT_EXTRACT,
                "source": source,
                "final_url": final_url or source,
                "mode": mode,
                "mime_type": mime_type,
                "body_bytes": len(body_bytes),
                "text_chars": len(text),
                "full_text_chars": len(full_text),
                "legal_focus_expanded": legal_focus_expanded,
                "payload_hash": payload_hash,
            },
            redaction_status="unredacted_finance_document_text",
        )
        context.metadata.setdefault("v3_artifacts", {})[artifact.artifact_id] = artifact.to_dict()
        return {
            "schema": "holo.kernel_v4.document_text_extract_result.v1",
            "tool": V4_DOCUMENT_TEXT_EXTRACT,
            "status": "ok",
            "source": source,
            "final_url": final_url or source,
            "artifact_id": artifact.artifact_id,
            "artifact_refs": [artifact.to_dict()],
            "mode": mode,
            "mime_type": mime_type,
            "body_bytes": len(body_bytes),
            "text_chars": len(text),
            "full_text_chars": len(full_text),
            "legal_focus_expanded": legal_focus_expanded,
            "preview": " ".join(text[:1200].split()),
            "focus_snippets": _focus_snippets(full_text, focus_terms=focus_terms),
            "diagnostics": diagnostics,
            "instruction": "Use artifact.search with this artifact_id for exact labels/tables, or artifact.read for broader context.",
            "host_boundary": "Text extraction only; semantic decisions remain with the model.",
        }

    return execute


def _sec_edgar_filing_documents_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        accession = str(payload.get("accession_number") or payload.get("accession") or "").strip()
        if not accession:
            return {"error": "missing_accession_number", "required": "accession_number"}
        cik = _sec_cik_for_filing_documents(payload)
        if not cik:
            return {
                "error": "missing_or_unresolved_cik",
                "required": "cik or identifier",
                "accession_number": accession,
                "host_boundary": "SEC accession expansion requires a CIK or resolvable company identifier.",
            }
        max_documents = _bounded_positive_int(payload.get("max_documents"), default=30, upper=200)
        query = str(payload.get("query") or "").strip()
        archive_base = _sec_archive_base_url(cik, accession)
        index_url = f"{archive_base}/index.json"
        request = urllib.request.Request(
            index_url,
            headers={
                "User-Agent": "HoloKernelV4 SEC filing document expander; contact=research@example.invalid",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            index_payload = json.load(response)
        documents = _sec_index_documents(index_payload, archive_base=archive_base, query=query)
        selected = documents[:max_documents]
        artifact = artifact_store.write_blob(
            kind="sec_edgar_filing_documents_payload",
            payload=json.dumps(
                {
                    "schema": "holo.kernel_v4.sec_edgar_filing_documents_payload.v1",
                    "accession_number": accession,
                    "cik": cik,
                    "index_url": index_url,
                    "query": query or None,
                    "documents": documents,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            mime_type="application/json",
            metadata={
                "tool": V4_SEC_EDGAR_FILING_DOCUMENTS,
                "accession_number": accession,
                "cik": cik,
                "index_url": index_url,
                "document_count": len(documents),
            },
            redaction_status="unredacted_sec_filing_document_index",
        )
        context.metadata.setdefault("v3_artifacts", {})[artifact.artifact_id] = artifact.to_dict()
        return {
            "schema": "holo.kernel_v4.sec_edgar_filing_documents_result.v1",
            "tool": V4_SEC_EDGAR_FILING_DOCUMENTS,
            "status": "ok",
            "accession_number": accession,
            "cik": cik,
            "archive_base_url": archive_base,
            "index_url": index_url,
            "complete_submission_text_url": f"{archive_base}/{accession}.txt",
            "query": query or None,
            "document_count": len(documents),
            "documents": selected,
            "truncated": len(documents) > len(selected),
            "artifact_id": artifact.artifact_id,
            "artifact_refs": [artifact.to_dict()],
            "instruction": (
                "Use document.text.extract or document.docling.convert on the selected document url, often an Exhibit 99.1 "
                "for earnings-release tables. If an exhibit HTML contains image-only tables or lacks the needed numeric rows, "
                "call document.text.extract on complete_submission_text_url with focus_terms for the missing table/line items. "
                "Use artifact.search/read on this artifact if you need the full document list."
            ),
            "host_boundary": "SEC filing document expansion returns official archive URLs only; semantic document choice remains with the model.",
        }

    return execute


def _sec_cik_for_filing_documents(payload: JsonObject) -> str:
    explicit = str(payload.get("cik") or "").strip()
    if explicit:
        digits = "".join(ch for ch in explicit if ch.isdigit())
        if digits:
            return digits.zfill(10)[-10:]
    identifier = str(payload.get("identifier") or "").strip()
    return _sec_cik_from_identifier(identifier) or ""


def _sec_archive_base_url(cik: str, accession: str) -> str:
    digits = "".join(ch for ch in str(cik or "") if ch.isdigit()).zfill(10)[-10:]
    accession_digits = re.sub(r"[^0-9]", "", str(accession or ""))
    cik_path = str(int(digits))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_digits}"


def _sec_index_documents(index_payload: JsonObject, *, archive_base: str, query: str) -> list[JsonObject]:
    directory = index_payload.get("directory")
    items = directory.get("item") if isinstance(directory, dict) else None
    if not isinstance(items, list):
        items = []
    rows: list[JsonObject] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        description = str(item.get("description") or item.get("type") or "").strip()
        row = {
            "name": name,
            "description": description or None,
            "type": str(item.get("type") or "").strip() or None,
            "size": item.get("size"),
            "last_modified": item.get("last-modified") or item.get("last_modified"),
            "url": f"{archive_base}/{name}",
        }
        row["score"] = _sec_document_query_score(row, query=query)
        rows.append(row)
    rows.sort(key=lambda row: (-float(row.get("score") or 0.0), _sec_document_sort_key(row)))
    return rows


def _sec_document_query_score(row: JsonObject, *, query: str) -> float:
    haystack = " ".join(str(row.get(key) or "") for key in ("name", "description", "type")).casefold()
    score = 0.0
    if re.search(r"ex(?:hibit)?[-_ ]?99", haystack):
        score += 5.0
    if "ex-99" in haystack or "ex99" in haystack or "exhibit 99" in haystack:
        score += 3.0
    if "earnings" in haystack or "release" in haystack or "results" in haystack:
        score += 2.0
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(query or "").casefold()) if len(token) >= 3]
    score += sum(1.0 for token in tokens if token in haystack)
    return score


def _sec_document_sort_key(row: JsonObject) -> str:
    name = str(row.get("name") or "")
    if name.lower().endswith((".htm", ".html")):
        return "0:" + name
    if name.lower().endswith(".txt"):
        return "1:" + name
    return "2:" + name


def _download_document_bytes(source: str) -> tuple[bytes, str, str]:
    try:
        return _download_document_bytes_once(source)
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        if not _is_ssl_unexpected_eof(exc):
            raise
        context = ssl._create_unverified_context()
        return _download_document_bytes_once(source, ssl_context=context)


def _download_document_bytes_once(source: str, *, ssl_context: ssl.SSLContext | None = None) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        source,
        headers={
            "User-Agent": "HoloKernelV4 finance document text extractor; contact=research@example.invalid",
            "Accept": "application/pdf,text/html,application/xhtml+xml,text/plain,*/*",
        },
        method="GET",
    )
    urlopen_kwargs: dict[str, Any] = {"timeout": 45}
    if ssl_context is not None:
        urlopen_kwargs["context"] = ssl_context
    with urllib.request.urlopen(request, **urlopen_kwargs) as response:
        data = response.read(75_000_000 + 1)
        if len(data) > 75_000_000:
            raise RuntimeError("document_text_extract_byte_limit_exceeded")
        mime_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        final_url = str(response.geturl() or source)
    if not mime_type:
        path = urllib.parse.urlparse(final_url).path.lower()
        if path.endswith(".pdf") or data[:8].startswith(b"%PDF"):
            mime_type = "application/pdf"
        elif path.endswith((".htm", ".html")) or data[:256].lstrip().lower().startswith((b"<!doctype html", b"<html")):
            mime_type = "text/html"
        else:
            mime_type = "text/plain"
    return data, mime_type, final_url


def _is_ssl_unexpected_eof(exc: BaseException) -> bool:
    text = str(exc)
    reason = getattr(exc, "reason", None)
    if reason is not None:
        text = f"{text} {reason}"
    return "UNEXPECTED_EOF_WHILE_READING" in text or "EOF occurred in violation of protocol" in text


def _decode_document_body(body: bytes, *, mime_type: str) -> str:
    if "pdf" in mime_type or body[:8].startswith(b"%PDF"):
        return body.decode("latin-1", errors="ignore")
    return body.decode("utf-8", errors="replace")


def _select_document_text(text: str, *, max_chars: int, focus_terms: list[str]) -> str:
    source = str(text or "")
    if len(source) <= max_chars:
        return source
    windows = _focus_windows(source, focus_terms=focus_terms)
    if not windows:
        return source[:max_chars]
    intro_chars = min(len(source), max_chars, max(1_000, min(12_000, max_chars // 5)))
    parts = [source[:intro_chars]]
    used = len(parts[0])
    for index, (left, right, term) in enumerate(windows, start=1):
        header = f"\n\n[focus_window {index} start={left} end={right}]\n"
        window_text = source[left:right]
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(header) >= remaining:
            break
        window_budget = remaining - len(header)
        if len(window_text) > window_budget:
            window_text = _fit_focus_window(window_text, focus_terms=focus_terms, max_chars=window_budget)
        block = f"{header}{window_text}"
        if len(block) > remaining:
            block = block[:remaining]
        parts.append(block)
        used += len(block)
        if used >= max_chars:
            break
    return "".join(parts)


def _has_legal_focus_terms(focus_terms: list[str]) -> bool:
    legal_markers = (
        "legal",
        "litigation",
        "lawsuit",
        "settlement",
        "contingenc",
        "regulatory proceeding",
        "government investigation",
        "subpoena",
        "qui tam",
    )
    return any(
        marker in str(term or "").casefold()
        for term in focus_terms
        for marker in legal_markers
    )


def _fit_focus_window(text: str, *, focus_terms: list[str], max_chars: int) -> str:
    source = str(text or "")
    if len(source) <= max_chars:
        return source
    lowered = source.casefold()
    positions = [
        lowered.find(str(term or "").casefold().strip())
        for term in focus_terms
        if str(term or "").strip()
    ]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return source[:max_chars]
    start = max(0, min(positions) - min(500, max_chars // 4))
    return source[start : start + max_chars]


def _focus_windows(
    text: str,
    *,
    focus_terms: list[str],
    before_chars: int = 2_000,
    after_chars: int = 6_000,
    per_term_limit: int = 3,
    window_limit: int = 24,
) -> list[tuple[int, int, str]]:
    if not focus_terms:
        return []
    source = str(text or "")
    lowered = source.casefold()
    raw_windows: list[tuple[int, int, str]] = []
    for term in focus_terms:
        needle = str(term or "").casefold().strip()
        if not needle:
            continue
        position = 0
        found_for_term = 0
        while found_for_term < per_term_limit and len(raw_windows) < window_limit:
            start = lowered.find(needle, position)
            if start < 0:
                break
            left = max(0, start - before_chars)
            right = min(len(source), start + len(needle) + after_chars)
            raw_windows.append((left, right, str(term)))
            found_for_term += 1
            position = start + max(len(needle), 1)
        if len(raw_windows) >= window_limit:
            break
    raw_windows.sort(key=lambda item: item[0])
    merged: list[tuple[int, int, str]] = []
    for left, right, term in raw_windows:
        if not merged or left > merged[-1][1] + 200:
            merged.append((left, right, term))
            continue
        prev_left, prev_right, prev_term = merged[-1]
        terms = prev_term if term in prev_term.split("|") else f"{prev_term}|{term}"
        merged[-1] = (prev_left, max(prev_right, right), terms)
    return merged


def _focus_snippets(text: str, *, focus_terms: list[str], limit: int = 12) -> list[JsonObject]:
    if not focus_terms:
        return []
    source = str(text or "")
    lowered = source.casefold()
    snippets: list[JsonObject] = []
    used: list[tuple[int, int]] = []
    for term in focus_terms:
        needle = str(term or "").casefold().strip()
        if not needle:
            continue
        start = lowered.find(needle)
        if start < 0:
            continue
        left = max(0, start - 500)
        right = min(len(source), start + len(term) + 1200)
        if any(not (right < prev_left or left > prev_right) for prev_left, prev_right in used):
            continue
        used.append((left, right))
        snippets.append(
            {
                "term": term,
                "start": start,
                "snippet": " ".join(source[left:right].split()),
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


def _v3_tool_executor(*, v3_registry: V3ToolRegistry, manifest_name: str):
    async def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        payload = _hydrate_v3_payload(manifest_name=manifest_name, payload=payload, context=context)
        if manifest_name == MARKET_OPENBB_FETCH_TOOL_NAME:
            blocked = _target_filing_openbb_guard(payload=payload, context=context)
            if blocked is not None:
                return blocked
        action_id = f"v4-{manifest_name}-{len(context.messages)}"
        action = CandidateAction(
            action_id=action_id,
            kind="tool",
            name=manifest_name,
            description=f"Kernel v4 delegated call to {manifest_name}",
            score=1.0,
            payload=dict(payload),
            reasons=["kernel_v4_model_requested_tool"],
            side_effect_class=_side_effect(v3_registry, manifest_name),
        )
        policy = PolicyDecision(
            decision_id=f"policy-{action_id}",
            run_id=context.run_id,
            action_id=action.action_id,
            allowed=True,
            reason="kernel_v4_tool_policy",
            constraints={"tool_name": manifest_name, "side_effect_class": action.side_effect_class},
        )
        result = v3_registry.execute_with_artifacts(
            action,
            policy_decision=policy,
            execution_context={"run_id": context.run_id, "task_id": context.thread_key},
        )
        for artifact in result.artifact_refs:
            context.metadata.setdefault("v3_artifacts", {})[artifact.artifact_id] = artifact.to_dict()
        observation = result.observation
        return {
            "schema": "holo.kernel_v4.v3_tool_observation.v1",
            "tool": manifest_name,
            "status": observation.status,
            "kind": observation.kind,
            "source": observation.source,
            "content": observation.content,
            "artifact_refs": [artifact.to_dict() for artifact in result.artifact_refs],
            "host_boundary": "v4 delegated execution only; semantic decisions remain with the model",
        }

    return execute


def _target_filing_openbb_guard(*, payload: JsonObject, context: ToolUseContext) -> JsonObject | None:
    if not _context_has_target_filing_metadata(context):
        return None
    question = str(context.metadata.get("task_question") or "")
    if _question_has_market_data_intent(question):
        return None
    kwargs = payload.get("kwargs") if isinstance(payload.get("kwargs"), dict) else {}
    if _payload_has_explicit_period(payload) or _payload_has_explicit_period(kwargs):
        return None
    return {
        "schema": "holo.kernel_v4.v3_tool_observation.v1",
        "tool": MARKET_OPENBB_FETCH_TOOL_NAME,
        "status": "blocked",
        "kind": "openbb_result",
        "source": "kernel_v4_target_filing_guard",
        "content": {
            "error": "target_filing_openbb_period_required",
            "route": str(payload.get("route") or ""),
            "reason": (
                "This task names a target filing/document period and does not ask for market data. "
                "An unqualified OpenBB call can drift to the latest period instead of the target filing."
            ),
            "guidance": (
                "Use the supplied filing URL, SEC/EDGAR, document.docling.convert, document.search.hybrid, "
                "or existing artifacts for filing evidence. If OpenBB is genuinely needed, call it with an explicit "
                "fiscal_year, period, date, start_date/end_date, or other period-bounding argument."
            ),
            "host_boundary": "guard blocks only unqualified latest-period market calls; semantic decisions remain with the model",
        },
        "artifact_refs": [],
        "host_boundary": "v4 delegated execution only; semantic decisions remain with the model",
    }


def _hydrate_v3_payload(*, manifest_name: str, payload: JsonObject, context: ToolUseContext) -> JsonObject:
    hydrated = dict(payload)
    if manifest_name in {SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME}:
        _hydrate_target_period_payload(hydrated, context)
    if manifest_name == DOCUMENT_SEARCH_HYBRID_TOOL_NAME:
        hydrated.setdefault("max_chars", 8_000)
        hydrated.setdefault("max_matches", 8)
        return hydrated
    if manifest_name != PROVIDED_CONTEXT_PARSE_TOOL_NAME:
        return hydrated
    if str(hydrated.get("context") or "").strip():
        return hydrated
    context_ref = str(hydrated.get("context_ref") or "").strip()
    if context_ref != "task_provided_context":
        return hydrated
    provided = context.metadata.get("task_provided_context")
    if isinstance(provided, str) and provided.strip():
        hydrated["context"] = provided
    return hydrated


def _context_has_target_filing_metadata(context: ToolUseContext) -> bool:
    safe_metadata = context.metadata.get("task_safe_metadata")
    if not isinstance(safe_metadata, dict):
        return False
    has_source = any(str(safe_metadata.get(key) or "").strip() for key in ("doc_link", "filing_url", "source_url"))
    has_period = any(str(safe_metadata.get(key) or "").strip() for key in ("doc_period", "period", "fiscal_year", "fiscal_period"))
    return has_source and has_period


def _question_has_market_data_intent(question: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"stock price|share price|market price|quote|trading|volume|market cap|market capitalization|"
            r"beta|return|total return|price return|volatility|analyst|estimate|consensus|target price"
            r")\b",
            question,
            flags=re.IGNORECASE,
        )
    )


def _payload_has_explicit_period(payload: JsonObject) -> bool:
    period_keys = {
        "period",
        "target_period",
        "fiscal_year",
        "fiscal_period",
        "year",
        "date",
        "start_date",
        "end_date",
        "from_date",
        "to_date",
    }
    for key in period_keys:
        if str(payload.get(key) or "").strip():
            return True
    return False


def _hydrate_target_period_payload(payload: JsonObject, context: ToolUseContext) -> None:
    if _int_or_none(payload.get("fiscal_year")) is not None or str(payload.get("period") or payload.get("target_period") or "").strip():
        return
    safe_metadata = context.metadata.get("task_safe_metadata")
    if not isinstance(safe_metadata, dict):
        safe_metadata = {}
    fiscal_year = _target_fiscal_year_from_metadata(safe_metadata)
    if fiscal_year is None:
        fiscal_year = _target_fiscal_year_from_text(str(context.metadata.get("task_question") or ""))
    if fiscal_year is None:
        return
    payload["fiscal_year"] = fiscal_year
    payload.setdefault("period", f"FY{fiscal_year}")


def _target_fiscal_year_from_metadata(metadata: JsonObject) -> int | None:
    for key in ("fiscal_year", "doc_period", "period", "fiscal_period"):
        year = _target_fiscal_year_from_text(str(metadata.get(key) or ""))
        if year is not None:
            return year
    return None


def _target_fiscal_year_from_text(text: str) -> int | None:
    years = [int(match.group(1)) for match in re.finditer(r"\b(?:FY|fiscal\s+year\s*)?((?:19|20)\d{2})\b", text, flags=re.IGNORECASE)]
    if not years:
        return None
    return years[-1]


def _finance_workbench_open(payload: JsonObject, context: ToolUseContext) -> JsonObject:
    query = str(payload.get("query") or "").casefold().strip()
    requested_families = set(_payload_string_list(payload.get("task_family")))
    max_profiles = _bounded_positive_int(payload.get("max_profiles"), default=8, upper=32)
    profiles = _finance_workbench_profiles()
    rows: list[JsonObject] = []
    for profile in profiles:
        family = str(profile["family"])
        haystack = " ".join(
            [
                family,
                str(profile.get("when") or ""),
                " ".join(str(item) for item in profile.get("required_evidence", [])),
                " ".join(str(item) for item in profile.get("primary_tools", [])),
                " ".join(str(item) for item in profile.get("search_terms", [])),
            ]
        ).casefold()
        score = 1.0 if not query else _score_text(query, haystack)
        if requested_families and family in requested_families:
            score += 5.0
        elif requested_families:
            score *= 0.25
        if score <= 0:
            continue
        row = dict(profile)
        row["score"] = score
        rows.append(row)
    rows.sort(key=lambda item: (-float(item["score"]), str(item["family"])))
    selected = rows[:max_profiles]
    if not selected:
        selected = profiles[: min(max_profiles, 4)]
    discovered = set(_payload_string_list(context.metadata.get("discovered_tool_names")))
    for profile in selected:
        discovered.update(str(tool) for tool in profile.get("primary_tools", []) if str(tool))
        discovered.update(str(tool) for tool in profile.get("support_tools", []) if str(tool))
    discovered.update(
        [
            "artifact.inspect",
            "artifact.search",
            "artifact.read",
            "tool.workbench",
            "tool.discovery",
            V4_FINANCE_TOOLCHAIN_DESCRIBE,
        ]
    )
    context.apply_edit(
        ContextEdit(
            operation="metadata.set",
            key="discovered_tool_names",
            value=sorted(discovered),
            source=V4_FINANCE_WORKBENCH_OPEN,
        )
    )
    return {
        "schema": "holo.kernel_v4.finance_workbench.v1",
        "query": query,
        "requested_families": sorted(requested_families),
        "selected_profiles": selected,
        "global_contract": {
            "decision_owner": "model",
            "host_role": "validate_execute_record_compact_only",
            "no_gold_policy": "Benchmark gold/reference answers are never model context.",
            "tool_first_policy": (
                "Use tool observations for source evidence, table transforms, deterministic arithmetic, and numeric "
                "verification. Do not rely on hidden host computation or memorized benchmark answers."
            ),
            "artifact_lifecycle": [
                "Use artifact.inspect to see generated v4/delegated artifacts and their previews.",
                "Use artifact.search to locate candidate snippets before reading broad artifacts.",
                "Use artifact.read with start/max_chars to inspect the surrounding context of a selected snippet.",
            ],
            "final_answer_contract": [
                "Answer the exact question directly.",
                "Name source line items, periods, units, dates, and artifact/source ids.",
                "Show formulas and methodological choices such as average versus ending balance.",
                "Use calculator.compute or data.table.query for material derived numbers when available.",
                "Use finance.verify_numeric for final material finance numbers when available.",
                "Explain comparison direction and business context without hard-coded thresholds.",
            ],
        },
        "capability_matrix": _finance_capability_matrix(),
        "current_artifacts": context.artifact_summary(recent_limit=10),
        "host_boundary": (
            "Finance workbench returns contracts only; semantic decisions remain with the model. It does not bind "
            "facts, compute hidden answers, or judge final semantics for the model."
        ),
    }


def _finance_toolchain_audit_executor(*, registry: ToolRegistry, allow_network: bool):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        del context
        mode = str(payload.get("mode") or "full").casefold().strip()
        registered = {manifest.name for manifest in registry.all_manifests()}
        all_profiles = _finance_workbench_profiles()
        profiles = _audit_profiles_for_mode(all_profiles, mode=mode)
        profile_rows: list[JsonObject] = []
        missing_by_profile: dict[str, list[str]] = {}
        incomplete_profiles: list[str] = []
        for profile in profiles:
            family = str(profile["family"])
            tools = sorted(set(_profile_tool_names(profile)))
            missing_tools = [tool for tool in tools if tool not in registered]
            if missing_tools:
                missing_by_profile[family] = missing_tools
            if not profile.get("required_evidence") or not profile.get("workflow"):
                incomplete_profiles.append(family)
            profile_rows.append(
                {
                    "family": family,
                    "tool_count": len(tools),
                    "missing_tools": missing_tools,
                    "has_required_evidence": bool(profile.get("required_evidence")),
                    "has_workflow": bool(profile.get("workflow")),
                }
            )
        coverage_families = {str(item["family"]) for item in _finance_toolchain_coverage_families()}
        profile_families = {str(profile["family"]) for profile in profiles}
        expected_core = _audit_required_tools_for_mode(mode=mode)
        missing_core = sorted(tool for tool in expected_core if tool not in registered)
        forbidden_present = sorted(tool for tool in FORBIDDEN_LEGACY_TOOLS if tool in registered)
        no_network_fqa_missing: list[str] = []
        if mode in {"full", "no_network_fqa", "fqa", "finqa"} and not allow_network:
            fqa_profile = next((profile for profile in profiles if profile["family"] == "provided_context_fqa_finqa"), None)
            if fqa_profile is not None:
                no_network_fqa_missing = sorted(tool for tool in _profile_tool_names(fqa_profile) if tool not in registered)
        status = "ok"
        if missing_by_profile or incomplete_profiles or missing_core or forbidden_present or no_network_fqa_missing:
            status = "failed"
        return {
            "schema": "holo.kernel_v4.finance_toolchain_audit.v1",
            "status": status,
            "mode": mode,
            "allow_network": allow_network,
            "registered_tool_count": len(registered),
            "profile_count": len(profiles),
            "total_profile_count": len(all_profiles),
            "coverage_family_count": len(coverage_families),
            "profile_rows": profile_rows,
            "missing_tools_by_profile": missing_by_profile,
            "incomplete_profiles": incomplete_profiles,
            "missing_core_tools": missing_core,
            "forbidden_legacy_tools_present": forbidden_present,
            "coverage_profiles_missing_from_describe": sorted(profile_families - coverage_families),
            "describe_families_without_profile": sorted(coverage_families - profile_families),
            "no_network_fqa_missing_tools": no_network_fqa_missing,
            "no_gold_policy": "Audit uses tool manifests and static contracts only; benchmark gold/reference material is not read.",
            "host_boundary": "Audit reports theoretical toolchain closure only; it does not solve tasks or score benchmark answers.",
        }

    return execute


def _finance_toolchain_describe(payload: JsonObject, context: ToolUseContext) -> JsonObject:
    del payload, context
    return {
        "schema": "holo.kernel_v4.finance_toolchain.v1",
        "architecture": "single_agent_reference_style_loop",
        "removed_legacy_gates": ["FactLedger", "SlotFrame", "finance.slot_bind", "host semantic slot completion gate"],
        "one_shot_loop_contract": {
            "decision_owner": "model",
            "host_role": "validate_execute_record_compact_only",
            "tool_use_boundary": (
                "All finance evidence retrieval, parsing, transformation, calculation, and verification must happen "
                "through model-requested tool calls inside this loop; the host does not create hidden finance answers."
            ),
            "benchmark_solvability_policy": (
                "Assume FinanceBench/FQA/FinQA-style tasks are intended to be solvable from public filings, supplied "
                "context, or allowed tools. Continue with another source/tool strategy while budget remains."
            ),
            "no_gold_policy": "Gold/reference answers are not model context and must not be inferred from benchmark ids.",
            "stop_rule": (
                "Finalize only after observed evidence supports the answer, required arithmetic has a calculator/table "
                "observation when tools are available, and final material numeric claims have been verified when "
                "finance.verify_numeric is available; otherwise call the next relevant tool or state a precise blocker."
            ),
            "answer_output_contract": {
                "required_elements": [
                    "direct answer to the exact question",
                    "source-backed inputs with line item labels, periods, units, dates, and artifact/source ids",
                    "formula and methodological choices such as average versus ending balance or fiscal day basis",
                    "calculator.compute or data.table.query observation for derived finance numbers when available",
                    "finance.verify_numeric observation for final material numeric claims when available",
                    "verifier payloads bind facts/formula inputs to observed evidence or citation text instead of self-authored answer numbers",
                    "comparison direction and business-context reasoning without hard-coded thresholds",
                    "for capital-intensity or asset-intensity judgments, use net income / total assets as ROA when net income is available; operating income / assets is supplemental unless operating ROA is requested",
                ],
                "forbidden_elements": [
                    "generic failure text when partial cited evidence can answer",
                    "hard-coded threshold substituted for finance judgment",
                    "unsourced generic industry threshold numbers in a final business-characterization answer",
                    "typically/often industry benchmark percentages that were not retrieved as evidence",
                    "benchmark-id lookup or cached gold answer",
                    "mental arithmetic for material derived finance numbers when calculator.compute is available",
                    "self-certified numeric verification where the answer number is also the only model-supplied fact or constant formula",
                ],
            },
        },
        "coverage_families": _finance_toolchain_coverage_families(),
        "tool_protocol": [
            "Use SEC/EDGAR or retrieval tools for authoritative evidence.",
            "For target-document earnings/proxy/8-K tasks, use sec.edgar.company_filings with fiscal_year/period and sec.edgar.filing_documents to expand accession exhibits when a company static URL is unavailable.",
            "Use document conversion and document.search.hybrid for long filings or tables.",
            "If a converted document artifact was created with narrow focus_terms and lacks a later required fact, call document.docling.convert again on the original source with focus_terms for the missing line item/table.",
            "For SEC accession filing URLs, document.docling.convert may use the official SEC complete-submission text as a better table retrieval source than the company PDF.",
            "Use provided_context.parse for FinQA/FQA supplied contexts; prefer context_ref='task_provided_context' for large supplied context.",
            "After provided_context.parse, document.search.hybrid, SEC/EDGAR, or artifact.read succeeds, do not repeat the same call with the same input unless the result was unusable; move to the next transform, verification, or final answer step.",
            "Use data.table.query for table filtering, grouping, ranking, and aggregation.",
            "Use calendar.days_between for model-selected fiscal date differences.",
            "Use calculator.compute for deterministic arithmetic once you have observed inputs.",
            "Use finance.verify_numeric before final material finance numeric claims when available.",
            "For finance.verify_numeric, include source-bound facts or calculator traces tied to observed evidence/citation text; do not use the answer number as its own proof.",
            "Use tool.discovery when a needed registered tool is not visible in the current provider tool surface.",
            "Use finance.workbench.open or tool.workbench to assemble task-family contracts and relevant tools without relying on hidden host logic.",
        ],
        "available_tools": finance_tool_names(),
        "workbench_tools": [V4_FINANCE_WORKBENCH_OPEN, "tool.workbench"],
        "decision_owner": "model",
        "host_role": "validate_execute_record_compact_only",
    }


def _artifact_read_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "")
        start = _bounded_non_negative_int(payload.get("start"), default=0, upper=10**9)
        max_chars = _int_or_none(payload.get("max_chars")) or 8_000
        max_chars = max(1, min(max_chars, 200_000))
        if artifact_id in context.artifacts:
            content = context.read_artifact(artifact_id)
            end = min(len(content), start + max_chars)
            return {
                "schema": "holo.kernel_v4.artifact_read_result.v1",
                "artifact_id": artifact_id,
                "source": "kernel_v4_context",
                "chars": len(content),
                "start": start,
                "end": end,
                "text": content[start:end],
                "truncated": end < len(content),
                "instruction": (
                    "This is a bounded window. Use artifact.search for targeted snippets, or call artifact.read "
                    "again with start/end-focused max_chars if broader context is necessary."
                ),
            }
        if artifact_store.has_blob(artifact_id):
            raw = artifact_store.read_blob(artifact_id, record_access=True, access_context={"reader": "kernel_v4"})
            content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            end = min(len(content), start + max_chars)
            return {
                "schema": "holo.kernel_v4.artifact_read_result.v1",
                "artifact_id": artifact_id,
                "source": "delegated_finance_artifact_store",
                "chars": len(content),
                "start": start,
                "end": end,
                "text": content[start:end],
                "truncated": end < len(content),
                "instruction": (
                    "This is a bounded window. Use artifact.search for targeted snippets, or call artifact.read "
                    "again with start/end-focused max_chars if broader context is necessary."
                ),
            }
        raise KeyError(f"unknown artifact: {artifact_id}")

    return execute


def _artifact_inspect_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        artifact_id = str(payload.get("artifact_id") or "").strip() or None
        max_items = _bounded_positive_int(payload.get("max_items"), default=20, upper=100)
        v4_artifacts = context.artifact_summary(artifact_id=artifact_id, recent_limit=max_items)
        delegated_artifacts = _delegated_artifact_summaries(
            artifact_store=artifact_store,
            context=context,
            artifact_id=artifact_id,
            max_items=max_items,
        )
        if artifact_id and not v4_artifacts and not delegated_artifacts:
            return {"error": "artifact_not_found", "artifact_id": artifact_id}
        return {
            "schema": "holo.kernel_v4.artifact_inspect_result.v1",
            "artifact_id": artifact_id,
            "kernel_v4_artifacts": v4_artifacts,
            "delegated_artifacts": delegated_artifacts,
            "artifact_count": len(context.artifacts) + len(_delegated_artifact_summaries(artifact_store=artifact_store, context=context, max_items=10_000)),
            "host_boundary": "Artifact inspection exposes lifecycle metadata only; the model chooses search/read/next tool calls.",
        }

    return execute


def _artifact_search_executor(artifact_store: V3ArtifactStore):
    def execute(payload: JsonObject, context: ToolUseContext) -> JsonObject:
        query = str(payload.get("query") or "").strip()
        artifact_id = str(payload.get("artifact_id") or "").strip() or None
        max_matches = _bounded_positive_int(payload.get("max_matches"), default=8, upper=50)
        window_chars = _bounded_positive_int(payload.get("window_chars"), default=260, upper=2_000)
        if not query:
            return {"error": "missing_query", "required": "query"}
        matches: list[JsonObject] = []
        searched = 0
        for candidate_id, content in _v4_artifact_candidates(context, artifact_id=artifact_id):
            searched += 1
            matches.extend(
                _search_text(
                    artifact_id=candidate_id,
                    source="kernel_v4_context",
                    text=content,
                    query=query,
                    max_matches=max_matches,
                    window_chars=window_chars,
                )
            )
        for candidate_id, content in _delegated_artifact_candidates(
            artifact_store=artifact_store,
            context=context,
            artifact_id=artifact_id,
        ):
            searched += 1
            matches.extend(
                _search_text(
                    artifact_id=candidate_id,
                    source="delegated_finance_artifact_store",
                    text=content,
                    query=query,
                    max_matches=max_matches,
                    window_chars=window_chars,
                )
            )
        matches.sort(key=lambda item: (str(item["artifact_id"]), int(item["offset"])))
        return {
            "schema": "holo.kernel_v4.artifact_search_result.v1",
            "query": query,
            "artifact_id": artifact_id,
            "matches": matches[:max_matches],
            "searched_artifacts": searched,
            "host_boundary": "Artifact search returns snippets only; call artifact.read for broader context if needed.",
        }

    return execute


def _finance_workbench_profiles() -> list[JsonObject]:
    artifact_tools = ["artifact.inspect", "artifact.search", "artifact.read"]
    compute_tools = ["calculator.compute", DATA_TABLE_QUERY_TOOL_NAME, MATH_SYMPY_COMPUTE_TOOL_NAME]
    filing_tools = [
        SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        V4_SEC_EDGAR_FILING_DOCUMENTS,
        SEC_EDGAR_FINANCIALS_TOOL_NAME,
        V4_DOCUMENT_TEXT_EXTRACT,
        DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
        DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        *artifact_tools,
    ]
    return [
        {
            "family": "public_filing_evidence",
            "when": "Public-company tasks requiring authoritative filing facts, exact line items, notes, table labels, or SEC/XBRL facts.",
            "primary_tools": filing_tools,
            "support_tools": ["tool.workbench", "tool.discovery"],
            "required_evidence": [
                "target company identifiers, filing form, fiscal period, source URL/accession when available",
                "exact line item labels, period columns, units, and statement/table names",
                "artifact ids for converted filing text or retrieved document snippets",
            ],
            "workflow": [
                "Locate filing if needed; include fiscal_year/period when the task names a target period.",
                "If a company static URL fails, use sec.edgar.company_filings for the target form/period, then sec.edgar.filing_documents to list official SEC primary/exhibit URLs.",
                "Use standardized financials for candidate facts when possible.",
                "Convert/search filing text for exact labels, notes, MD&A, and table context.",
                "Search/read artifacts instead of repeating broad retrieval.",
            ],
            "search_terms": ["10-k", "annual report", "8-k", "exhibit 99.1", "earnings", "line item", "statement", "note", "xbrl", "edgar"],
        },
        {
            "family": "provided_context_fqa_finqa",
            "when": "FQA/FinQA-style prompts that provide report context, oracle_context, copied tables, markdown, CSV, or HTML snippets.",
            "primary_tools": [PROVIDED_CONTEXT_PARSE_TOOL_NAME, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute", *artifact_tools],
            "support_tools": ["tool.workbench", "tool.discovery"],
            "required_evidence": [
                "provided context parse result or context_ref='task_provided_context'",
                "relevant text block/table id and row/column labels",
                "calculator/table observation for derived answer",
            ],
            "workflow": [
                "Parse supplied context before external retrieval.",
                "Use data.table.query for row selection, ranking, joins, and aggregations.",
                "Use calculator.compute for arithmetic transforms.",
            ],
            "search_terms": ["provided context", "oracle_context", "finqa", "fqa", "table", "paragraph"],
        },
        {
            "family": "table_ranking_aggregation",
            "when": "Questions requiring filtering, sorting, ranking, grouping, joining, or aggregation over observed rows.",
            "primary_tools": [DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            "support_tools": [PROVIDED_CONTEXT_PARSE_TOOL_NAME, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools],
            "required_evidence": [
                "table source and complete comparable rows",
                "row/column labels used for ranking or aggregation",
                "query/calculation observation supporting the selected row or aggregate",
            ],
            "workflow": [
                "Extract the table or comparable rows.",
                "Run the table query instead of ranking mentally.",
                "Report comparison direction and all relevant comparable values.",
            ],
            "search_terms": ["rank", "highest", "lowest", "aggregate", "sum", "average", "table"],
        },
        {
            "family": "shareholder_vote_results",
            "when": "Questions about shareholder votes, board nominee election results, annual meeting proposals, Item 5.07, votes against/withheld, abstentions, or broker non-votes.",
            "primary_tools": [V4_DOCUMENT_TEXT_EXTRACT, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, V4_SEC_EDGAR_FILING_DOCUMENTS, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, "tool.workbench", "tool.discovery"],
            "required_evidence": [
                "target 8-K/proxy-related filing URL or accession and Item 5.07 section",
                "complete nominee/proposal vote table with all comparable rows",
                "Votes For, Votes Against or Withheld, Abstentions, and Broker Non-Votes columns when present",
                "source artifact id, filing date, and proposal label such as Proposal 1",
            ],
            "workflow": [
                "Use document.text.extract for static company filing PDFs or target 8-K URLs, then artifact.search for Item 5.07, Proposal 1, Votes Against, and nominee names.",
                "Gather all nominee rows before comparing who has substantially more votes against.",
                "Use data.table.query or calculator.compute for ranking/comparison when table rows are structured enough.",
            ],
            "search_terms": [
                "Item 5.07",
                "Submission of Matters to a Vote of Security Holders",
                "Proposal 1",
                "Board of Directors",
                "Votes For",
                "Votes Against",
                "Withheld",
                "Abstentions",
                "Broker Non-Votes",
                "nominees",
                "annual meeting",
            ],
        },
        {
            "family": "finance_transforms",
            "when": "Ratios, margins, growth, bps, averages, multiples, per-share values, DSO/DPO/DIO, and comparisons.",
            "primary_tools": compute_tools,
            "support_tools": [*artifact_tools, "finance.verify_numeric"],
            "required_evidence": [
                "observed source inputs with units and periods",
                "formula and normalization choice",
                "calculator/table/symbolic observation for material derived numbers",
            ],
            "workflow": [
                "Select the formula based on the question and finance context.",
                "Normalize units/signs explicitly.",
                "Use deterministic compute tools and verify final material numbers.",
            ],
            "search_terms": ["ratio", "margin", "growth", "bps", "average", "multiple", "percent", "formula"],
        },
        {
            "family": "cash_flow_conversion",
            "when": "Free cash flow conversion, FCF conversion, cash-flow conversion quality, or trend/improvement questions comparing cash generation to earnings.",
            "primary_tools": [*filing_tools, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [MARKET_OPENBB_FETCH_TOOL_NAME, DATA_TABLE_QUERY_TOOL_NAME, "tool.workbench", "tool.discovery"],
            "required_evidence": [
                "net cash provided by operating activities for each compared period",
                "capital expenditures, purchases of property and equipment, or purchases of property, plant and equipment for each compared period",
                "net income for each compared period",
                "period labels, units, and statement/table source for all three inputs",
            ],
            "workflow": [
                "Use the prompt/source definition if provided; otherwise define free cash flow as operating cash flow minus capex.",
                "For trend/improvement, compute latest-period and prior comparable-period conversion ratios and the percentage-point change.",
                "Do not substitute operating cash flow divided by net income for free cash flow conversion when capex evidence is available or can be searched.",
                "If capex is not found in an initial artifact, run a focused search for purchases of property and equipment, property plant and equipment, or capital expenditures.",
            ],
            "formulas": [
                "free cash flow = net cash provided by operating activities - capital expenditures",
                "free cash flow conversion = free cash flow / net income",
                "percentage-point change = latest conversion percentage - prior conversion percentage",
            ],
            "search_terms": [
                "free cash flow conversion",
                "cashflow conversion",
                "cash flow conversion",
                "net cash provided by operating activities",
                "purchases of property and equipment",
                "capital expenditures",
                "net income",
            ],
        },
        {
            "family": "multi_company_comparison",
            "when": "Tasks comparing two or more companies across the same period and metric.",
            "primary_tools": [*filing_tools, "calculator.compute", DATA_TABLE_QUERY_TOOL_NAME, "finance.verify_numeric"],
            "support_tools": ["tool.workbench", "tool.discovery"],
            "required_evidence": [
                "same metric definitions for every company",
                "same or explicitly reconciled period basis",
                "calculation observations for every company before comparison",
            ],
            "workflow": [
                "Gather comparable facts for all companies first.",
                "Do not compare ending balance for one company with average balance for another.",
                "Compute every company using the same formula and then compare direction.",
            ],
            "search_terms": ["compare", "more efficient", "which company", "versus", "vs", "peer"],
        },
        {
            "family": "inventory_efficiency_dio",
            "when": "Days inventory outstanding, inventory turnover, or inventory efficiency questions.",
            "primary_tools": [*filing_tools, "calculator.compute", CALENDAR_DAYS_BETWEEN_TOOL_NAME, "finance.verify_numeric"],
            "support_tools": [DATA_TABLE_QUERY_TOOL_NAME],
            "required_evidence": [
                "beginning inventory and ending inventory or explicit average inventory",
                "cost of sales or cost of goods sold",
                "fiscal day basis or model-selected day convention",
                "formula choice such as average inventory versus ending inventory",
            ],
            "workflow": [
                "Prefer average inventory when the task asks for DIO unless the question specifies ending inventory.",
                "Use comparable inventory and COGS definitions across companies.",
                "Lower DIO means faster inventory turnover and higher inventory efficiency.",
            ],
            "formulas": ["DIO = average inventory / cost of sales * day basis"],
            "search_terms": ["inventory", "cost of sales", "cogs", "days inventory", "turnover", "average inventory"],
        },
        {
            "family": "liquidity_quick_ratio",
            "when": "Quick ratio, liquidity health, or near-term current-liability coverage questions.",
            "primary_tools": [DOCUMENT_DOCLING_CONVERT_TOOL_NAME, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME],
            "required_evidence": [
                "total current assets",
                "inventories",
                "total current liabilities",
                "cash, marketable securities, receivables, prepaids, or other current assets if needed for a supplemental definition",
            ],
            "workflow": [
                "If the prompt does not define quick ratio, use current assets minus inventories over current liabilities as the primary filing-benchmark convention.",
                "Label stricter cash/securities/receivables definitions as supplemental if computed.",
                "Use calculator.compute for the ratio and finance.verify_numeric for the final number.",
            ],
            "formulas": ["quick ratio = (current assets - inventories) / current liabilities"],
            "search_terms": ["quick ratio", "current assets", "inventories", "current liabilities", "liquidity"],
        },
        {
            "family": "liquidation_per_share_recovery",
            "when": "Questions asking what shareholders would receive in bankruptcy, liquidation, residual recovery, book value per share, or tangible book value per share.",
            "primary_tools": [*filing_tools, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [DATA_TABLE_QUERY_TOOL_NAME, "tool.workbench", "tool.discovery"],
            "required_evidence": [
                "total assets and total liabilities or total stockholders' equity",
                "common stockholders' equity and shares outstanding",
                "preferred stock or non-common equity claims when common-share recovery is requested",
                "goodwill and intangible asset balances or tangible common equity/tangible book value per share when liquidation/recovery wording makes intangibles material",
                "source labels, period/date, units, and whether the result is book value per common share or tangible book value per common share",
            ],
            "workflow": [
                "Treat liquidation/recovery wording as a metric-definition ambiguity rather than immediately using common equity per share.",
                "Search for tangible book value, book value per share, goodwill, intangible assets, preferred stock, common stockholders' equity, and shares outstanding.",
                "Compare candidate bases such as total equity, common equity, and tangible common equity; select the basis that best matches the question wording and filing evidence.",
                "Use calculator.compute for residual-to-common and per-share calculations, then finance.verify_numeric for the final material number.",
            ],
            "formulas": [
                "book value per common share = common stockholders' equity / common shares outstanding",
                "tangible common equity = common stockholders' equity - goodwill - other intangible assets when those exclusions are appropriate or disclosed",
                "tangible book value per common share = tangible common equity / common shares outstanding",
            ],
            "search_terms": [
                "bankruptcy",
                "liquidation",
                "liquidated all assets",
                "pay shareholders",
                "shareholder recovery",
                "book value per share",
                "tangible book value",
                "tangible common equity",
                "goodwill",
                "intangible assets",
                "preferred stock",
                "common stockholders equity",
                "shares outstanding",
            ],
        },
        {
            "family": "capital_intensity_asset_intensity",
            "when": "Business characterization tasks asking whether a company is capital-intensive or asset-intensive.",
            "primary_tools": [*filing_tools, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [DATA_TABLE_QUERY_TOOL_NAME],
            "required_evidence": [
                "revenue or net sales",
                "capex or purchases of property, plant and equipment",
                "operating cash flow when capex funding is relevant",
                "PP&E net and total assets",
                "net income and ROA/profitability context when available",
            ],
            "workflow": [
                "Select relevant ratios yourself; do not use host hard-coded thresholds.",
                "Distinguish having fixed assets from being primarily driven by heavy fixed assets.",
                "Reason from observed ratios, profitability, cash funding, and business context.",
            ],
            "formulas": [
                "capex / revenue",
                "capex / operating cash flow",
                "PP&E net / revenue",
                "PP&E net / total assets",
                "net income / total assets when net income is available",
            ],
            "search_terms": ["capital intensive", "capex", "property plant equipment", "total assets", "net income", "sales", "revenue"],
        },
        {
            "family": "gross_margin_profile",
            "when": "Questions asking whether a company has an improving gross margin profile, whether gross margin is useful, or how gross profit/gross margin changed across periods.",
            "primary_tools": [DOCUMENT_SEARCH_HYBRID_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, *artifact_tools, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME, "tool.workbench", "tool.discovery"],
            "required_evidence": [
                "revenue or sales for every requested comparable period",
                "all cost-of-sales rows such as cost of products, cost of services, cost of revenue, or total costs and expenses",
                "directly reported gross profit/subtotal immediately following revenue and cost rows when present",
                "business/accounting context such as program accounting only as a limitation, not a reason to discard an available gross-margin calculation",
            ],
            "workflow": [
                "Search exact table labels such as Sales of products, Sales of services, Cost of products, Cost of services, Total costs and expenses, Gross profit, and Consolidated Statements of Operations.",
                "If one extraction snippet is truncated before cost or subtotal rows, search/read the full filing artifact or rerun extraction with the missing line labels instead of finalizing a limitation.",
                "Prefer filing-reported gross profit/subtotal when present, reconcile it to component rows, then compute gross margin and percentage-point changes.",
                "Do not answer that gross margin is not useful merely because specialized accounting creates limitations when the filing provides revenue, cost, and subtotal evidence.",
            ],
            "formulas": [
                "gross margin = filing-reported gross profit/subtotal / revenue when a reported subtotal is present",
                "gross profit = revenue - cost rows only when no reported subtotal is present or after reconciling the subtotal",
                "percentage-point change = latest gross margin percentage - prior gross margin percentage",
            ],
            "search_terms": [
                "gross margin",
                "gross profit",
                "Consolidated Statements of Operations",
                "Sales of products",
                "Sales of services",
                "Cost of products",
                "Cost of services",
                "Total costs and expenses",
                "program accounting",
            ],
        },
        {
            "family": "margin_driver_bridge",
            "when": "Questions asking what drove margin, operating margin, gross margin, or expense-ratio changes.",
            "primary_tools": [DOCUMENT_SEARCH_HYBRID_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, *artifact_tools, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME],
            "required_evidence": [
                "numeric margin table or calculated margin change",
                "MD&A Results of Operations discussion tied to the margin change",
                "percentage-point bridge rows when provided",
                "named drivers such as cost of sales, SG&A, R&D, gains, impairments, litigation, restructuring, divestitures, or special items",
            ],
            "workflow": [
                "Retrieve both quantitative bridge and qualitative management discussion.",
                "Prefer drivers explicitly tied by management to the margin change.",
                "Do not treat a ratio change alone as a driver explanation.",
            ],
            "search_terms": ["margin", "operating margin", "gross margin", "results of operations", "drivers", "percentage points"],
        },
        {
            "family": "segment_growth_mna_exclusion",
            "when": "Questions asking which segment drove or dragged growth after excluding M&A, acquisitions, divestitures, or currency translation.",
            "primary_tools": [DOCUMENT_SEARCH_HYBRID_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, *artifact_tools, DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, SEC_EDGAR_FINANCIALS_TOOL_NAME],
            "required_evidence": [
                "segment sales bridge table",
                "organic sales/organic growth values for every comparable segment",
                "acquisitions, divestitures, translation, and total sales change columns when available",
            ],
            "workflow": [
                "Map M&A exclusion to organic sales/organic growth when the filing provides that bridge.",
                "Compare all segments on the organic row, not total sales change.",
                "Use data.table.query for ranking if the rows are tabular.",
            ],
            "search_terms": ["organic sales", "organic growth", "worldwide sales change", "acquisitions", "divestitures", "translation", "segment"],
        },
        {
            "family": "dividend_stability_trend",
            "when": "Questions asking whether dividends were paid to common shareholders, the per-share dividend amount, quarterly/annual dividend facts, or whether dividend distribution is stable, routine, maintained, increasing, or shareholder-return oriented.",
            "primary_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools, "calculator.compute", "finance.verify_numeric"],
            "support_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME],
            "required_evidence": [
                "Item 5 Market for Registrant's Common Equity / Dividends text when available",
                "quarterly cash dividend, annual dividend, dividend per share, dividends declared, or dividends paid disclosure",
                "shareholder class such as common shareholders or common stock",
                "management statement or filing disclosure about consecutive annual dividend increases when available",
                "annual dividend or dividends per share history",
                "shareholders' equity or dividends note as supporting evidence",
            ],
            "workflow": [
                "Search Item 5 Dividends and the shareholders' equity/dividends note before relying on cash-flow totals.",
                "For a specific quarter, treat a filing statement that the quarterly cash dividend for that year was a specified amount as quarter-level evidence unless the filing distinguishes quarters.",
                "Do not confuse dividends paid by regulated subsidiaries to the parent with dividends paid to common shareholders.",
                "For stability/trend questions, search for consecutive years, annual dividend, dividend increase, dividend record, and dividends per share.",
            ],
            "search_terms": [
                "Dividends",
                "Item 5",
                "quarterly cash dividend",
                "common shareholders",
                "common stock",
                "dividends per share",
                "dividends declared",
                "dividends paid",
                "shareholders equity",
                "consecutive years",
                "annual dividend",
                "dividend increase",
                "dividend record",
            ],
        },
        {
            "family": "legal_proceedings_disclosure",
            "when": "Questions asking whether the company reported material legal battles, legal proceedings, litigation, lawsuits, regulatory investigations, settlements, contingencies, or similar disclosed matters.",
            "primary_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools],
            "support_tools": ["tool.workbench", "tool.discovery", "calculator.compute"],
            "required_evidence": [
                "actual Item 3 Legal Proceedings text for each requested fiscal year when available",
                "relevant legal, commitments, contingencies, litigation, environmental, regulatory, or settlement note text",
                "named proceedings or matter categories, year/period, status, regulator/court/counterparty when disclosed",
                "disclosed amounts, accruals, settlement amounts, materiality qualifiers, or explicit no-material-proceedings statements when present",
            ],
            "workflow": [
                "Search Item 3 Legal Proceedings and legal/contingency notes for each requested filing period.",
                "If Item 3 incorporates a financial-statement note by reference, search/read that exact note text and do not stop at the table of contents or cross-reference.",
                "If an income-statement legal charge is found, still search for named proceedings and settlement/accrual amounts in the incorporated legal and contingency note.",
                "Do not treat a table of contents entry, risk-factor boilerplate, or forward-looking caution as proceedings evidence.",
                "Group the final answer by requested year/period and separate actual proceedings from generic risks.",
            ],
            "search_terms": [
                "Item 3",
                "Legal Proceedings",
                "litigation",
                "lawsuit",
                "settlement",
                "government investigation",
                "subpoena",
                "regulatory",
                "commitments and contingencies",
                "Legal and Regulatory Proceedings",
                "contingencies",
                "usual and customary",
                "settlement agreement",
                "accrual",
                "range of loss",
                "opioid",
                "PFAS",
                "qui tam",
            ],
        },
        {
            "family": "debt_securities_terms",
            "when": "Questions asking about debt securities, notes, maturities, coupon rates, principal amounts, or bond terms.",
            "primary_tools": [SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME, DOCUMENT_DOCLING_CONVERT_TOOL_NAME, DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools],
            "support_tools": ["calculator.compute", "finance.verify_numeric"],
            "required_evidence": [
                "exact security title or note series",
                "principal amount, coupon/rate, maturity date, and table/footnote context",
                "currency and units",
            ],
            "workflow": [
                "Search the debt note and securities table, not only balance sheet totals.",
                "Preserve sign, rate, and year labels exactly.",
                "Use calculator only for totals or comparisons requested by the question.",
            ],
            "search_terms": ["debt securities", "notes", "coupon", "maturity", "principal", "long-term debt"],
        },
        {
            "family": "fiscal_dates",
            "when": "Tasks requiring actual fiscal day counts, period length, inclusive/exclusive date choices, or fiscal year-end comparison.",
            "primary_tools": [CALENDAR_DAYS_BETWEEN_TOOL_NAME, "calculator.compute"],
            "support_tools": [DOCUMENT_SEARCH_HYBRID_TOOL_NAME, *artifact_tools],
            "required_evidence": [
                "start date and end date",
                "inclusive/exclusive or fiscal-day convention if specified",
                "model-selected convention if the task leaves day basis open",
            ],
            "workflow": [
                "Retrieve the relevant dates first.",
                "Use calendar.days_between when actual day count matters.",
                "State whether the calculation uses 365 or actual fiscal days.",
            ],
            "search_terms": ["fiscal days", "fiscal year", "period ended", "days between", "date"],
        },
        {
            "family": "market_data",
            "when": "Questions requiring prices, market data, or non-filing fundamentals not answered by supplied context or SEC filings.",
            "primary_tools": [MARKET_OPENBB_FETCH_TOOL_NAME],
            "support_tools": ["calculator.compute", "finance.verify_numeric"],
            "required_evidence": [
                "ticker or instrument identifier",
                "requested date/range and market-data field",
                "source/provider metadata returned by the market tool",
            ],
            "workflow": [
                "Use market tools only when the requested data source is market data.",
                "Do not replace filing evidence with market data for filing-accounting questions.",
            ],
            "search_terms": ["price", "market", "quote", "ticker", "openbb"],
        },
        {
            "family": "numeric_verification",
            "when": "Final material finance numeric claims before answer delivery.",
            "primary_tools": ["finance.verify_numeric"],
            "support_tools": ["calculator.compute", DATA_TABLE_QUERY_TOOL_NAME],
            "required_evidence": [
                "calculated numeric claim",
                "formula and input values",
                "rounding basis and unit normalization",
                "evidence/citation text containing source input values or source-bound calculator input facts",
            ],
            "workflow": [
                "Verify final material numbers after calculation.",
                "Do not use a newly asserted answer number as its own fact or constant formula proof.",
                "Bind verifier facts to observed evidence/citation text or to calculator traces with source-bound inputs.",
                "If verification fails, correct the calculation or state the precise blocker.",
            ],
            "search_terms": ["verify", "numeric", "rounding", "final answer"],
        },
    ]


def _finance_toolchain_coverage_families() -> list[JsonObject]:
    coverage: list[JsonObject] = []
    for profile in _finance_workbench_profiles():
        row: JsonObject = {
            "family": profile["family"],
            "when": profile["when"],
            "primary_tools": list(profile.get("primary_tools", [])),
        }
        if profile.get("support_tools"):
            row["support_tools"] = list(profile.get("support_tools", []))
        if profile.get("required_evidence"):
            row["required_evidence"] = list(profile.get("required_evidence", []))
        if profile.get("workflow"):
            row["workflow"] = list(profile.get("workflow", []))
        if profile.get("formulas"):
            row["formulas"] = list(profile.get("formulas", []))
        coverage.append(row)
    return coverage


def _audit_profiles_for_mode(profiles: list[JsonObject], *, mode: str) -> list[JsonObject]:
    if mode in {"no_network_fqa", "fqa", "finqa"}:
        required = {
            "provided_context_fqa_finqa",
            "table_ranking_aggregation",
            "finance_transforms",
            "numeric_verification",
        }
        return [profile for profile in profiles if profile.get("family") in required]
    return profiles


def _audit_required_tools_for_mode(*, mode: str) -> set[str]:
    if mode in {"no_network_fqa", "fqa", "finqa"}:
        return {
            V4_FINANCE_WORKBENCH_OPEN,
            V4_FINANCE_TOOLCHAIN_AUDIT,
            V4_FINANCE_TOOLCHAIN_DESCRIBE,
            "tool.workbench",
            "tool.discovery",
            "artifact.inspect",
            "artifact.search",
            "artifact.read",
            PROVIDED_CONTEXT_PARSE_TOOL_NAME,
            DATA_TABLE_QUERY_TOOL_NAME,
            MATH_SYMPY_COMPUTE_TOOL_NAME,
            CALENDAR_DAYS_BETWEEN_TOOL_NAME,
            "calculator.compute",
            "finance.verify_numeric",
        }
    return set(finance_tool_names())


def _profile_tool_names(profile: JsonObject) -> list[str]:
    tools: list[str] = []
    for key in ("primary_tools", "support_tools"):
        value = profile.get(key)
        if isinstance(value, list):
            tools.extend(str(tool) for tool in value if str(tool))
    return tools


def _finance_capability_matrix() -> list[JsonObject]:
    return [
        {
            "layer": "task_intake_no_gold",
            "purpose": "Receive FB/FQA/FinQA question packets while excluding gold/reference/scoring material.",
            "interfaces": ["FinanceQuestionSpec", "finance.workbench.open", "tool.workbench"],
            "model_decides": ["task decomposition", "source choice", "formula choice", "final readiness"],
        },
        {
            "layer": "source_or_context_acquisition",
            "purpose": "Acquire public filing evidence or parse supplied FQA/FinQA context.",
            "interfaces": [
                SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
                SEC_EDGAR_FINANCIALS_TOOL_NAME,
                PROVIDED_CONTEXT_PARSE_TOOL_NAME,
                MARKET_OPENBB_FETCH_TOOL_NAME,
            ],
            "model_decides": ["which source family applies", "whether public filing or supplied context is authoritative"],
        },
        {
            "layer": "document_artifact_context",
            "purpose": "Convert, inspect, search, and window-read long filing/document/tool outputs.",
            "interfaces": [
                DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
                DOCUMENT_TRAFILATURA_EXTRACT_TOOL_NAME,
                DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
                "artifact.inspect",
                "artifact.search",
                "artifact.read",
            ],
            "model_decides": ["which snippets are evidence", "when to reconvert or search a broader artifact"],
        },
        {
            "layer": "table_and_transform_compute",
            "purpose": "Execute deterministic table selection, aggregation, arithmetic, symbolic math, and day-count transforms.",
            "interfaces": [DATA_TABLE_QUERY_TOOL_NAME, "calculator.compute", MATH_SYMPY_COMPUTE_TOOL_NAME, CALENDAR_DAYS_BETWEEN_TOOL_NAME],
            "model_decides": ["formula", "unit normalization", "average versus ending balance", "fiscal day basis"],
        },
        {
            "layer": "numeric_verification",
            "purpose": "Verify material final finance numeric claims before final answer.",
            "interfaces": ["finance.verify_numeric"],
            "model_decides": ["which claims are material", "how to repair a failed verification"],
        },
        {
            "layer": "answer_synthesis",
            "purpose": "Produce the concise final answer with citations, formulas, method choices, comparison direction, and business context.",
            "interfaces": ["model final answer", "workflow_context_summary", "recent_tool_calls"],
            "model_decides": ["business judgment", "limitations", "whether the answer is sufficiently supported"],
        },
    ]


def _v4_artifact_candidates(context: ToolUseContext, *, artifact_id: str | None) -> list[tuple[str, str]]:
    if artifact_id:
        if artifact_id not in context.artifacts:
            return []
        return [(artifact_id, context.read_artifact(artifact_id))]
    return [(candidate_id, context.read_artifact(candidate_id)) for candidate_id in sorted(context.artifacts)]


def _delegated_artifact_candidates(
    *,
    artifact_store: V3ArtifactStore,
    context: ToolUseContext,
    artifact_id: str | None,
) -> list[tuple[str, str]]:
    known_ids = {artifact.artifact_id for artifact in artifact_store.list()}
    raw = context.metadata.get("v3_artifacts")
    if isinstance(raw, dict):
        known_ids.update(str(key) for key in raw)
    if artifact_id:
        known_ids = {artifact_id} if artifact_id in known_ids else set()
    candidates: list[tuple[str, str]] = []
    for candidate_id in sorted(known_ids):
        if not artifact_store.has_blob(candidate_id):
            continue
        raw_blob = artifact_store.read_blob(
            candidate_id,
            record_access=True,
            access_context={"reader": "kernel_v4", "tool": "artifact.search"},
        )
        text = raw_blob.decode("utf-8", errors="replace") if isinstance(raw_blob, bytes) else raw_blob
        candidates.append((candidate_id, text))
    return candidates


def _delegated_artifact_summaries(
    *,
    artifact_store: V3ArtifactStore,
    context: ToolUseContext,
    artifact_id: str | None = None,
    max_items: int = 20,
) -> list[JsonObject]:
    by_id: dict[str, JsonObject] = {}
    raw = context.metadata.get("v3_artifacts")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if artifact_id and str(key) != artifact_id:
                continue
            row = dict(value) if isinstance(value, dict) else {"metadata": value}
            row.setdefault("artifact_id", str(key))
            row.setdefault("source", "delegated_finance_artifact_store")
            by_id[str(key)] = row
    for artifact in artifact_store.list():
        if artifact_id and artifact.artifact_id != artifact_id:
            continue
        row = dict(artifact.to_dict())
        row.setdefault("source", "delegated_finance_artifact_store")
        if artifact_store.has_blob(artifact.artifact_id):
            try:
                row.update(artifact_store.preview(artifact.artifact_id, limit=500))
            except KeyError:
                pass
        by_id[artifact.artifact_id] = {**by_id.get(artifact.artifact_id, {}), **row}
    return [by_id[key] for key in sorted(by_id)[: max(1, max_items)]]


def _search_text(
    *,
    artifact_id: str,
    source: str,
    text: str,
    query: str,
    max_matches: int,
    window_chars: int,
) -> list[JsonObject]:
    terms = _query_terms(query)
    if not terms:
        return []
    haystack = text.casefold()
    offsets: list[int] = []
    for term in terms:
        start = 0
        while len(offsets) < max_matches:
            index = haystack.find(term, start)
            if index < 0:
                break
            offsets.append(index)
            start = index + max(1, len(term))
    matches: list[JsonObject] = []
    for offset in sorted(set(offsets))[:max_matches]:
        start = max(0, offset - window_chars // 2)
        end = min(len(text), offset + window_chars // 2)
        matches.append(
            {
                "artifact_id": artifact_id,
                "source": source,
                "offset": offset,
                "start": start,
                "end": end,
                "snippet": " ".join(text[start:end].split()),
            }
        )
    return matches


def _query_terms(query: str) -> list[str]:
    return [term for term in query.casefold().replace("/", " ").replace("_", " ").replace("-", " ").split() if len(term) >= 2]


def _payload_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.casefold().strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).casefold().strip() for item in value if str(item).strip()]
    return []


def _score_text(query: str, haystack: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 1.0
    return float(sum(1 for term in terms if term in haystack))


def _bounded_positive_int(value: object, *, default: int, upper: int) -> int:
    parsed = _int_or_none(value) or default
    return max(1, min(parsed, upper))


def _bounded_non_negative_int(value: object, *, default: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, upper))


def _side_effect(v3_registry: V3ToolRegistry, name: str) -> str:
    dummy = CandidateAction(
        action_id="manifest-probe",
        kind="tool",
        name=name,
        description="manifest probe",
        score=1.0,
        payload={},
        reasons=[],
    )
    manifest = v3_registry.manifest_for_action(dummy)
    return str(manifest.side_effect_class if manifest is not None else "read")


def _int_or_none(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
