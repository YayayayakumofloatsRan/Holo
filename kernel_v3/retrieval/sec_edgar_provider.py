from __future__ import annotations

import hashlib

from kernel_v3.contracts import JsonObject
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, resolve_issuer_identity
from kernel_v3.research.issuer_registry import builtin_issuers_for_text
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


class SecEdgarSearchProvider:
    provider_id = "sec_edgar_structured_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = [FINANCE_FUNDAMENTALS_PROFILE_ID]

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "sec_edgar_structured_search",
            "network_access": "none",
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        profile_id = _research_profile_id(goal.metadata)
        if profile_id != FINANCE_FUNDAMENTALS_PROFILE_ID:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "not_finance_profile",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        identities = _issuer_identifier_candidates(query, goal.metadata)
        identity = resolve_issuer_identity(query, goal.metadata)
        identifiers = identities[0] if identities else {"ticker": identity.ticker, "cik": identity.cik}
        filing = _filing_metadata(goal.metadata)
        if identifiers.get("cik") is None and filing.get("sec_accession_compact"):
            identifiers["cik"] = _normalize_cik(str(filing["sec_accession_compact"])[:10])
        sources = _sources_for_identifier_set(identities or [identifiers], max_sources=goal.max_sources, filing=filing)
        resolved_cik = identifiers.get("cik") or _first_source_cik(sources)
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "reason": "ok" if sources else "missing_sec_identifier",
            "ticker": identifiers.get("ticker"),
            "cik_present": bool(resolved_cik),
            "issuer_candidate_count": len(identities) if identities else int(bool(identifiers.get("ticker") or identifiers.get("cik"))),
            "issuer_candidates": identities[:8],
            "accession_present": bool(filing.get("sec_accession_number")),
            "primary_document_present": bool(filing.get("sec_primary_document")),
            "identity_confidence": identity.confidence,
            "identity_sources": list(identity.sources),
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _issuer_identifier_candidates(query: str, metadata: JsonObject) -> list[JsonObject]:
    candidates: list[JsonObject] = []
    seen: set[tuple[str | None, str | None]] = set()
    intent_text = _issuer_intent_text(query, metadata)
    for issuer in builtin_issuers_for_text(intent_text):
        identifiers = {
            "ticker": _string_or_none(issuer.get("ticker")),
            "cik": _normalize_cik(issuer.get("sec_cik")),
        }
        key = (identifiers["ticker"], identifiers["cik"])
        if key in seen or not any(key):
            continue
        seen.add(key)
        candidates.append({key: value for key, value in identifiers.items() if value})
    identity = resolve_issuer_identity(intent_text, metadata)
    identifiers = {
        "ticker": identity.ticker,
        "cik": identity.cik,
    }
    key = (identifiers["ticker"], identifiers["cik"])
    if any(key) and key not in seen:
        candidates.insert(0, {key: value for key, value in identifiers.items() if value})
    return candidates


def _issuer_intent_text(query: str, metadata: JsonObject) -> str:
    if isinstance(metadata, dict) and metadata.get("benchmark_doc_retrieval") is True:
        parts: list[str] = []
        for key in (
            "company",
            "issuer",
            "ticker",
            "sec_cik",
            "doc_name",
            "doc_type",
            "doc_period",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        text_query = str(query or "").strip()
        if text_query and "Benchmark target source follows." not in text_query:
            parts.append(text_query)
        return "\n".join(parts)
    parts = [str(query or "")]
    for key in ("root_goal", "task_goal", "original_goal", "user_goal"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    mission = metadata.get("research_mission") if isinstance(metadata, dict) else None
    if isinstance(mission, dict):
        value = mission.get("root_goal")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _sources_for_identifier_set(
    identities: list[JsonObject],
    *,
    max_sources: int,
    filing: JsonObject | None = None,
) -> list[SearchSource]:
    sources: list[SearchSource] = []
    seen_uris: set[str] = set()
    per_issuer_limit = max(5, int(max_sources))
    buckets = [
        _sources_for_identifiers(identifiers, max_sources=per_issuer_limit, filing=filing)
        for identifiers in identities
    ]
    for index in range(max((len(bucket) for bucket in buckets), default=0)):
        for bucket in buckets:
            if index >= len(bucket):
                continue
            source = bucket[index]
            if source.uri in seen_uris:
                continue
            seen_uris.add(source.uri)
            sources.append(source)
            if len(sources) >= max(0, int(max_sources)):
                return sources
    return sources[: max(0, int(max_sources))]


def _sources_for_identifiers(
    identifiers: JsonObject,
    *,
    max_sources: int,
    filing: JsonObject | None = None,
) -> list[SearchSource]:
    ticker = _string_or_none(identifiers.get("ticker"))
    cik = _normalize_cik(identifiers.get("cik"))
    filing = dict(filing or {})
    sources: list[SearchSource] = []
    if cik:
        _append_filing_document_sources(sources, ticker=ticker, cik=cik, filing=filing)
        padded = str(cik)
        _append_source(
            sources,
            uri=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json",
            title=f"SEC companyfacts JSON for CIK {padded}",
            snippet="Official SEC XBRL companyfacts JSON for reported fundamentals with filing provenance.",
            source_family="structured_regulatory_data",
            source_kind="sec_companyfacts_json",
            ticker=ticker,
            cik=padded,
        )
        _append_source(
            sources,
            uri=f"https://data.sec.gov/submissions/CIK{padded}.json",
            title=f"SEC submissions JSON for CIK {padded}",
            snippet="Official SEC submissions metadata, filing chronology, forms, accession numbers, and report periods.",
            source_family="structured_regulatory_data",
            source_kind="sec_submissions_json",
            ticker=ticker,
            cik=padded,
        )
        _append_source(
            sources,
            uri=f"https://www.sec.gov/edgar/browse/?CIK={padded}",
            title=f"SEC EDGAR browse page for CIK {padded}",
            snippet="Official SEC EDGAR browse page for primary filing documents and filing detail pages.",
            source_family="regulatory_filing",
            source_kind="sec_edgar_browse",
            ticker=ticker,
            cik=padded,
        )
    if ticker:
        _append_source(
            sources,
            uri="https://www.sec.gov/files/company_tickers_exchange.json",
            title="SEC company ticker and CIK directory",
            snippet=f"Official SEC ticker and CIK mapping lookup for {ticker}.",
            source_family="structured_regulatory_data",
            source_kind="sec_ticker_cik_directory",
            ticker=ticker,
            cik=cik,
        )
        _append_source(
            sources,
            uri=f"https://www.sec.gov/edgar/search/#/q={ticker}",
            title=f"SEC EDGAR search for {ticker}",
            snippet=f"Official SEC EDGAR filing search page for {ticker}.",
            source_family="regulatory_filing",
            source_kind="sec_edgar_search",
            ticker=ticker,
            cik=cik,
        )
    return sources[: max(0, int(max_sources))]


def _append_filing_document_sources(
    sources: list[SearchSource],
    *,
    ticker: str | None,
    cik: str,
    filing: JsonObject,
) -> None:
    accession_compact = _string_or_none(filing.get("sec_accession_compact"))
    accession_number = _string_or_none(filing.get("sec_accession_number"))
    if not accession_compact:
        return
    cik_path = str(int(cik))
    primary_document = _safe_document_name(filing.get("sec_primary_document"))
    base_uri = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_compact}"
    common = {
        key: value
        for key, value in {
            "sec_accession_number": accession_number,
            "sec_accession_compact": accession_compact,
            "sec_primary_document": primary_document,
            "sec_form": _string_or_none(filing.get("sec_form")),
            "report_date": _string_or_none(filing.get("report_date")),
        }.items()
        if value
    }
    label = _filing_label(
        form=common.get("sec_form"),
        report_date=common.get("report_date"),
        accession=accession_number,
    )
    if primary_document:
        _append_source(
            sources,
            uri=f"{base_uri}/{primary_document}",
            title=f"SEC primary filing document for {label}",
            snippet=(
                "Official SEC Archives primary filing document derived from CIK, "
                "accession number, and primaryDocument metadata."
            ),
            source_family="regulatory_filing",
            source_kind="sec_primary_filing_document",
            ticker=ticker,
            cik=cik,
            extra_metadata=common,
        )
    if accession_number:
        _append_source(
            sources,
            uri=f"{base_uri}/{accession_number}.txt",
            title=f"SEC complete submission text for {label}",
            snippet="Official SEC Archives complete submission text for the accession number.",
            source_family="regulatory_filing",
            source_kind="sec_complete_submission_text",
            ticker=ticker,
            cik=cik,
            extra_metadata=common,
        )
    _append_source(
        sources,
        uri=f"{base_uri}/",
        title=f"SEC filing directory for {label}",
        snippet="Official SEC Archives filing directory for primary documents and exhibits.",
        source_family="regulatory_filing",
        source_kind="sec_filing_directory",
        ticker=ticker,
        cik=cik,
        extra_metadata=common,
    )


def _append_source(
    sources: list[SearchSource],
    *,
    uri: str,
    title: str,
    snippet: str,
    source_family: str,
    source_kind: str,
    ticker: str | None,
    cik: str | None,
    extra_metadata: JsonObject | None = None,
) -> None:
    extra_metadata = dict(extra_metadata or {})
    sources.append(
        SearchSource(
            source_id=f"{SecEdgarSearchProvider.provider_id}-{_hash(uri)[:12]}-{len(sources) + 1}",
            uri=uri,
            title=title,
            snippet=snippet,
            provider=SecEdgarSearchProvider.provider_id,
            metadata={
                "rank": len(sources) + 1,
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_family": source_family,
                "authority_level": "primary",
                "source_kind": source_kind,
                **({"ticker": ticker} if ticker else {}),
                **({"sec_cik": cik} if cik else {}),
                **extra_metadata,
            },
        )
    )


def _first_source_cik(sources: list[SearchSource]) -> str | None:
    for source in sources:
        cik = _string_or_none(source.metadata.get("sec_cik"))
        if cik is not None:
            return cik
    return None


def _research_profile_id(metadata: JsonObject) -> str | None:
    value = metadata.get("research_profile_id", metadata.get("research_profile"))
    return value if isinstance(value, str) and value else None


def _filing_metadata(metadata: JsonObject) -> JsonObject:
    accession = _first_metadata_string(
        metadata,
        "sec_accession_number",
        "accession_number",
        "accession_no",
        "accessionNumber",
        "accession",
    )
    accession_data = _normalize_accession(accession)
    primary_document = _safe_document_name(
        _first_metadata_string(
            metadata,
            "sec_primary_document",
            "primary_document",
            "primaryDocument",
            "filing_document",
            "document_name",
        )
    )
    result: JsonObject = {}
    if accession_data:
        result.update(accession_data)
    if primary_document:
        result["sec_primary_document"] = primary_document
    form = _first_metadata_string(metadata, "sec_form", "form", "filing_form")
    report_date = _first_metadata_string(metadata, "report_date", "period_of_report", "filing_date")
    if form:
        result["sec_form"] = form
    if report_date:
        result["report_date"] = report_date
    return result


def _first_metadata_string(metadata: JsonObject, *keys: str) -> str | None:
    for key in keys:
        value = _string_or_none(metadata.get(key))
        if value is not None:
            return value
    for parent_key in ("sec_filing", "filing", "filing_metadata", "document"):
        parent = metadata.get(parent_key)
        if not isinstance(parent, dict):
            continue
        for key in keys:
            value = _string_or_none(parent.get(key))
            if value is not None:
                return value
    return None


def _normalize_accession(value: object) -> JsonObject | None:
    text = _string_or_none(value)
    if text is None:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 18:
        return None
    compact = digits[-18:]
    dashed = _accession_with_dashes(text, compact)
    if dashed is None:
        return None
    return {
        "sec_accession_number": dashed,
        "sec_accession_compact": compact,
    }


def _accession_with_dashes(text: str, compact: str) -> str | None:
    parts = [part for part in text.strip().split("-") if part]
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[0].zfill(10)}-{parts[1].zfill(2)}-{parts[2].zfill(6)}"
    if len(compact) == 18:
        return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
    return None


def _safe_document_name(value: object) -> str | None:
    text = _string_or_none(value)
    if text is None:
        return None
    if any(marker in text for marker in ("/", "\\", "?", "#")):
        return None
    if text in {".", ".."}:
        return None
    return text


def _filing_label(*, form: object, report_date: object, accession: object) -> str:
    parts = [
        _string_or_none(form),
        _string_or_none(report_date),
        _string_or_none(accession),
    ]
    return " ".join(part for part in parts if part) or "SEC filing"


def _normalize_cik(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return digits[-10:].zfill(10)


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
