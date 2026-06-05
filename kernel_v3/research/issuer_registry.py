from __future__ import annotations

from dataclasses import dataclass

from kernel_v3.contracts import JsonObject


@dataclass(frozen=True, kw_only=True)
class BuiltinIssuerEntry:
    ticker: str
    cik: str
    company: str
    aliases: tuple[str, ...]
    market: str = "NASDAQ"


BUILTIN_US_ISSUERS: tuple[BuiltinIssuerEntry, ...] = (
    BuiltinIssuerEntry(
        ticker="AAPL",
        cik="0000320193",
        company="Apple Inc.",
        aliases=("apple inc", "apple corporation", "apple computer"),
    ),
    BuiltinIssuerEntry(
        ticker="MSFT",
        cik="0000789019",
        company="Microsoft Corporation",
        aliases=("microsoft", "microsoft corporation"),
    ),
    BuiltinIssuerEntry(
        ticker="NVDA",
        cik="0001045810",
        company="NVIDIA Corporation",
        aliases=("nvidia", "nvidia corporation", "nvidia corp"),
    ),
    BuiltinIssuerEntry(
        ticker="ORCL",
        cik="0001341439",
        company="Oracle Corporation",
        aliases=("oracle", "oracle corporation", "oracle corp"),
    ),
    BuiltinIssuerEntry(
        ticker="GOOGL",
        cik="0001652044",
        company="Alphabet Inc.",
        aliases=("alphabet", "alphabet inc", "google parent"),
    ),
    BuiltinIssuerEntry(
        ticker="AMZN",
        cik="0001018724",
        company="Amazon.com, Inc.",
        aliases=("amazon", "amazon.com", "amazon com inc"),
    ),
    BuiltinIssuerEntry(
        ticker="META",
        cik="0001326801",
        company="Meta Platforms, Inc.",
        aliases=("meta platforms", "meta", "facebook"),
    ),
    BuiltinIssuerEntry(
        ticker="TSLA",
        cik="0001318605",
        company="Tesla, Inc.",
        aliases=("tesla", "tesla inc", "tesla motors"),
    ),
)


def builtin_issuer_for_text(text: str) -> JsonObject:
    normalized = _normalize_text(text)
    if not normalized:
        return {}
    for entry in BUILTIN_US_ISSUERS:
        if entry.ticker.lower() in normalized.split():
            return _entry_payload(entry, matched=entry.ticker)
        for alias in entry.aliases:
            if _phrase_present(normalized, _normalize_text(alias)):
                return _entry_payload(entry, matched=alias)
    return {}


def _entry_payload(entry: BuiltinIssuerEntry, *, matched: str) -> JsonObject:
    return {
        "ticker": entry.ticker,
        "sec_cik": entry.cik,
        "company": entry.company,
        "market": entry.market,
        "matched_alias": matched,
    }


def _phrase_present(normalized: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {normalized} "


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower()
    chars = [ch if ch.isalnum() else " " for ch in lowered]
    return " ".join("".join(chars).split())
