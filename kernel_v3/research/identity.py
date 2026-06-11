from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from kernel_v3.contracts import Contract, JsonObject
from kernel_v3.research.issuer_registry import builtin_issuer_for_text


_CIK_PATTERN = re.compile(r"\bCIK\s*0*([0-9]{1,10})\b", re.IGNORECASE)
_TICKER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9.]{0,4}\b")
_ASX_PATTERN = re.compile(r"\bASX\s*[:：]?\s*([A-Z][A-Z0-9]{1,5})\b", re.IGNORECASE)
_HK_PATTERN = re.compile(r"\b(?:HKEX|HKG|HK)\s*[:：]?\s*([0-9]{1,5})\b", re.IGNORECASE)
_SGX_PATTERN = re.compile(r"\bSGX\s*[:：]?\s*([A-Z0-9]{1,6})\b", re.IGNORECASE)
_IGNORED_TICKERS = {
    "API",
    "ASX",
    "CIK",
    "CPI",
    "CAGR",
    "DIO",
    "EDGAR",
    "EV",
    "EPS",
    "FRED",
    "GAAP",
    "GDP",
    "HK",
    "HKEX",
    "HKG",
    "IFRS",
    "IMF",
    "IR",
    "JSON",
    "K",
    "NYSE",
    "NYSEARCA",
    "OECD",
    "Q",
    "SEC",
    "SEDAR",
    "SGX",
    "UK",
    "US",
    "URL",
    "USD",
}


@dataclass(frozen=True, kw_only=True)
class IssuerIdentity(Contract):
    ticker: str | None = None
    cik: str | None = None
    company: str | None = None
    issuer: str | None = None
    stock_code: str | None = None
    asx_code: str | None = None
    hkex_code: str | None = None
    sgx_code: str | None = None
    edinet_code: str | None = None
    market: str | None = None
    identifiers: JsonObject = field(default_factory=dict)
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)


def resolve_issuer_identity(query: str, metadata: JsonObject | None = None) -> IssuerIdentity:
    metadata = metadata or {}
    flattened = _flatten_metadata(metadata)
    sources: list[str] = []
    company = _first_string(flattened, "company", "company_name")
    issuer = _first_string(flattened, "issuer", "issuer_name")
    stock_code = _first_string(flattened, "stock_code", "exchange_code", "code")
    asx_code = _first_string(flattened, "asx_code") or _asx_from_query(query)
    hkex_code = _first_string(flattened, "hkex_code", "hk_code", "stock_code_hk") or _hk_from_query(query)
    sgx_code = _first_string(flattened, "sgx_code") or _sgx_from_query(query)
    edinet_code = _first_string(flattened, "edinet_code")
    investor_relations_url = _first_string(flattened, "investor_relations_url", "ir_url")
    annual_reports_url = _first_string(flattened, "annual_reports_url", "annual_report_url")
    earnings_url = _first_string(flattened, "earnings_url", "results_url")
    market = _first_string(flattened, "market", "exchange", "listing_market") or _market_from_identifiers(
        asx_code=asx_code,
        hkex_code=hkex_code,
        sgx_code=sgx_code,
        edinet_code=edinet_code,
    )

    ticker = _first_string(flattened, "ticker", "sec_ticker")
    if ticker:
        sources.append("metadata_ticker")
    elif not _non_us_market(market):
        ticker = _ticker_from_query(query)
        if ticker:
            sources.append("query_ticker")

    cik = (
        _normalize_cik(flattened.get("sec_cik"))
        or _normalize_cik(flattened.get("cik"))
        or _normalize_cik(flattened.get("company_cik"))
        or _cik_from_query(query)
    )
    if cik:
        sources.append("metadata_or_query_cik")
    if ticker and not cik:
        cik = _normalize_cik(_ticker_cik_map(flattened).get(ticker.upper()))
        if cik:
            sources.append("metadata_ticker_cik_map")
    if _allow_builtin_issuer_registry(query, flattened):
        registered = builtin_issuer_for_text(" ".join(item for item in (query, ticker or "", company or "") if item))
        if registered:
            ticker = ticker or _first_string(registered, "ticker")
            cik = cik or _normalize_cik(registered.get("sec_cik"))
            company = company or _first_string(registered, "company")
            market = market or _first_string(registered, "market")
            investor_relations_url = investor_relations_url or _first_string(registered, "investor_relations_url")
            annual_reports_url = annual_reports_url or _first_string(registered, "annual_reports_url")
            earnings_url = earnings_url or _first_string(registered, "earnings_url")
            if "builtin_issuer_registry" not in sources:
                sources.append("builtin_issuer_registry")

    identifiers = {
        key: value
        for key, value in {
            "ticker": ticker.upper() if ticker else None,
            "sec_cik": cik,
            "company": company,
            "issuer": issuer,
            "stock_code": stock_code,
            "asx_code": asx_code.upper() if asx_code else None,
            "hkex_code": _normalize_hk_code(hkex_code),
            "sgx_code": sgx_code.upper() if sgx_code else None,
            "edinet_code": edinet_code.upper() if edinet_code else None,
            "market": market,
            "investor_relations_url": investor_relations_url,
            "annual_reports_url": annual_reports_url,
            "earnings_url": earnings_url,
        }.items()
        if isinstance(value, str) and value
    }
    confidence = _confidence(identifiers=identifiers, sources=sources)
    return IssuerIdentity(
        ticker=identifiers.get("ticker"),
        cik=identifiers.get("sec_cik"),
        company=identifiers.get("company"),
        issuer=identifiers.get("issuer"),
        stock_code=identifiers.get("stock_code"),
        asx_code=identifiers.get("asx_code"),
        hkex_code=identifiers.get("hkex_code"),
        sgx_code=identifiers.get("sgx_code"),
        edinet_code=identifiers.get("edinet_code"),
        market=identifiers.get("market"),
        identifiers=identifiers,
        confidence=confidence,
        sources=_ordered_unique(sources),
        diagnostics={
            "query_hash": _hash(query),
            "metadata_keys": sorted(key for key in flattened if isinstance(key, str)),
            "identifier_count": len(identifiers),
        },
    )


def identity_template_values(identity: IssuerIdentity) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in identity.identifiers.items():
        if isinstance(value, str) and value:
            values[key] = value
    if identity.company and "company_or_query" not in values:
        values["company_or_query"] = identity.company
    if identity.issuer and "issuer_or_query" not in values:
        values["issuer_or_query"] = identity.issuer
    return values


def _flatten_metadata(metadata: JsonObject) -> JsonObject:
    result: JsonObject = {}
    for key, value in metadata.items():
        if key == "metadata" and isinstance(value, dict):
            result.update(_flatten_metadata(value))
        else:
            result[key] = value
    return result


def _first_string(metadata: JsonObject, *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
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


def _asx_from_query(query: str) -> str | None:
    match = _ASX_PATTERN.search(query)
    return match.group(1).upper() if match else None


def _hk_from_query(query: str) -> str | None:
    match = _HK_PATTERN.search(query)
    return _normalize_hk_code(match.group(1)) if match else None


def _sgx_from_query(query: str) -> str | None:
    match = _SGX_PATTERN.search(query)
    return match.group(1).upper() if match else None


def _normalize_cik(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return digits[-10:].zfill(10)


def _normalize_hk_code(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits.zfill(5) if digits else None


def _ticker_cik_map(metadata: JsonObject) -> dict[str, str]:
    value = metadata.get("ticker_cik_map") or metadata.get("sec_ticker_cik_map")
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


def _market_from_identifiers(
    *,
    asx_code: str | None,
    hkex_code: str | None,
    sgx_code: str | None,
    edinet_code: str | None,
) -> str | None:
    if asx_code:
        return "ASX"
    if hkex_code:
        return "HKEX"
    if sgx_code:
        return "SGX"
    if edinet_code:
        return "EDINET"
    return None


def _non_us_market(market: str | None) -> bool:
    if not market:
        return False
    return market.upper() in {"ASX", "HKEX", "HKG", "HK", "SGX", "LSE", "SEDAR", "EDINET"}


def _allow_builtin_issuer_registry(query: str, metadata: JsonObject) -> bool:
    profile = str(metadata.get("research_profile") or metadata.get("research_profile_id") or "")
    if profile == "finance_fundamentals":
        return True
    lowered = str(query or "").lower()
    return any(
        marker in lowered
        for marker in (
            "10-k",
            "10-q",
            "sec",
            "edgar",
            "companyfacts",
            "fundamental",
            "fundamentals",
            "revenue",
            "net income",
            "market cap",
            "valuation",
        )
    )


def _confidence(*, identifiers: JsonObject, sources: list[str]) -> float:
    if identifiers.get("sec_cik") and identifiers.get("ticker"):
        return 0.92
    if identifiers.get("sec_cik"):
        return 0.86
    if any(key in identifiers for key in ("ticker", "asx_code", "hkex_code", "sgx_code", "edinet_code")):
        return 0.74 if "query_ticker" in sources else 0.82
    if identifiers.get("company") or identifiers.get("issuer"):
        return 0.64
    return 0.0


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
