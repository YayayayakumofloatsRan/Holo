from __future__ import annotations

import hashlib
import re

from kernel_v3.contracts import JsonObject
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


_TICKER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9.]{0,5}\b")
_CIK_PATTERN = re.compile(r"\bCIK\s*0*([0-9]{1,10})\b", re.IGNORECASE)
_IGNORED_TICKERS = {
    "API",
    "ASX",
    "CIK",
    "EDGAR",
    "EPS",
    "GAAP",
    "HKEX",
    "IFRS",
    "IR",
    "JSON",
    "Q",
    "SEC",
    "SGX",
    "US",
}


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
        identifiers = _identifiers(query, goal.metadata)
        sources = _sources_for_identifiers(identifiers, max_sources=goal.max_sources)
        resolved_cik = identifiers.get("cik") or _first_source_cik(sources)
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "reason": "ok" if sources else "missing_sec_identifier",
            "ticker": identifiers.get("ticker"),
            "cik_present": bool(resolved_cik),
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _sources_for_identifiers(identifiers: JsonObject, *, max_sources: int) -> list[SearchSource]:
    ticker = _string_or_none(identifiers.get("ticker"))
    cik = _normalize_cik(identifiers.get("cik"))
    sources: list[SearchSource] = []
    if ticker and not cik:
        cik = _normalize_cik(_ticker_cik_map(identifiers).get(ticker.upper()))
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
    if cik:
        padded = str(cik)
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
            uri=f"https://www.sec.gov/edgar/browse/?CIK={padded}",
            title=f"SEC EDGAR browse page for CIK {padded}",
            snippet="Official SEC EDGAR browse page for primary filing documents and filing detail pages.",
            source_family="regulatory_filing",
            source_kind="sec_edgar_browse",
            ticker=ticker,
            cik=padded,
        )
    return sources[: max(0, int(max_sources))]


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
) -> None:
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
            },
        )
    )


def _identifiers(query: str, metadata: JsonObject) -> JsonObject:
    ticker = _string_or_none(metadata.get("ticker"))
    if ticker is None:
        ticker = _string_or_none(metadata.get("sec_ticker"))
    if ticker is None:
        ticker = _ticker_from_query(query)
    cik = (
        _normalize_cik(metadata.get("sec_cik"))
        or _normalize_cik(metadata.get("cik"))
        or _normalize_cik(metadata.get("company_cik"))
        or _cik_from_query(query)
    )
    return {
        "ticker": ticker.upper() if isinstance(ticker, str) else None,
        "cik": cik,
        "ticker_cik_map": metadata.get("ticker_cik_map") or metadata.get("sec_ticker_cik_map"),
    }


def _first_source_cik(sources: list[SearchSource]) -> str | None:
    for source in sources:
        cik = _string_or_none(source.metadata.get("sec_cik"))
        if cik is not None:
            return cik
    return None


def _ticker_from_query(query: str) -> str | None:
    for match in _TICKER_PATTERN.findall(query):
        ticker = match.strip(".").upper()
        if ticker and ticker not in _IGNORED_TICKERS:
            return ticker
    return None


def _cik_from_query(query: str) -> str | None:
    match = _CIK_PATTERN.search(query)
    if not match:
        return None
    return _normalize_cik(match.group(1))


def _ticker_cik_map(identifiers: JsonObject) -> dict[str, str]:
    value = identifiers.get("ticker_cik_map")
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_ticker, raw_cik in value.items():
        if not isinstance(raw_ticker, str):
            continue
        cik = _normalize_cik(raw_cik)
        if cik is not None:
            result[raw_ticker.upper()] = cik
    return result


def _research_profile_id(metadata: JsonObject) -> str | None:
    value = metadata.get("research_profile_id", metadata.get("research_profile"))
    return value if isinstance(value, str) and value else None


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
