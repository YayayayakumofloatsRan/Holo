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
    investor_relations_url: str | None = None
    annual_reports_url: str | None = None
    earnings_url: str | None = None


BUILTIN_US_ISSUERS: tuple[BuiltinIssuerEntry, ...] = (
    BuiltinIssuerEntry(
        ticker="AAPL",
        cik="0000320193",
        company="Apple Inc.",
        aliases=("apple inc", "apple corporation", "apple computer"),
        investor_relations_url="https://investor.apple.com/",
    ),
    BuiltinIssuerEntry(
        ticker="MSFT",
        cik="0000789019",
        company="Microsoft Corporation",
        aliases=("microsoft", "microsoft corporation"),
        investor_relations_url="https://www.microsoft.com/en-us/investor",
    ),
    BuiltinIssuerEntry(
        ticker="NVDA",
        cik="0001045810",
        company="NVIDIA Corporation",
        aliases=("nvidia", "nvidia corporation", "nvidia corp"),
        investor_relations_url="https://investor.nvidia.com/",
    ),
    BuiltinIssuerEntry(
        ticker="ORCL",
        cik="0001341439",
        company="Oracle Corporation",
        aliases=("oracle", "oracle corporation", "oracle corp"),
        investor_relations_url="https://investor.oracle.com/",
    ),
    BuiltinIssuerEntry(
        ticker="GOOGL",
        cik="0001652044",
        company="Alphabet Inc.",
        aliases=("alphabet", "alphabet inc", "google parent"),
        investor_relations_url="https://abc.xyz/investor/",
    ),
    BuiltinIssuerEntry(
        ticker="AMZN",
        cik="0001018724",
        company="Amazon.com, Inc.",
        aliases=("amazon", "amazon.com", "amazon com inc"),
        investor_relations_url="https://ir.aboutamazon.com/",
    ),
    BuiltinIssuerEntry(
        ticker="META",
        cik="0001326801",
        company="Meta Platforms, Inc.",
        aliases=("meta platforms", "meta", "facebook"),
        investor_relations_url="https://investor.atmeta.com/",
    ),
    BuiltinIssuerEntry(
        ticker="TSLA",
        cik="0001318605",
        company="Tesla, Inc.",
        aliases=("tesla", "tesla inc", "tesla motors"),
        investor_relations_url="https://ir.tesla.com/",
    ),
    BuiltinIssuerEntry(
        ticker="JPM",
        cik="0000019617",
        company="JPMorgan Chase & Co.",
        aliases=("jpmorgan chase", "jp morgan chase", "jpmorgan", "jpmorgan chase & co", "jpmorgan chase and co"),
        market="NYSE",
        investor_relations_url="https://www.jpmorganchase.com/ir",
    ),
    BuiltinIssuerEntry(
        ticker="BAC",
        cik="0000070858",
        company="Bank of America Corporation",
        aliases=("bank of america", "bank of america corporation", "bofa"),
        market="NYSE",
        investor_relations_url="https://investor.bankofamerica.com/",
    ),
    BuiltinIssuerEntry(
        ticker="GS",
        cik="0000886982",
        company="The Goldman Sachs Group, Inc.",
        aliases=("goldman sachs", "goldman sachs group", "the goldman sachs group"),
        market="NYSE",
        investor_relations_url="https://www.goldmansachs.com/investor-relations/",
    ),
    BuiltinIssuerEntry(
        ticker="BLK",
        cik="0002012383",
        company="BlackRock, Inc.",
        aliases=("blackrock", "blackrock inc", "blackrock, inc"),
        market="NYSE",
        investor_relations_url="https://ir.blackrock.com/",
        annual_reports_url="https://ir.blackrock.com/financials/annual-reports-and-proxy/default.aspx",
        earnings_url="https://ir.blackrock.com/financials/quarterly-results/default.aspx",
    ),
    BuiltinIssuerEntry(
        ticker="V",
        cik="0001403161",
        company="Visa Inc.",
        aliases=("visa", "visa inc"),
        market="NYSE",
        investor_relations_url="https://investor.visa.com/",
    ),
    BuiltinIssuerEntry(
        ticker="MA",
        cik="0001141391",
        company="Mastercard Incorporated",
        aliases=("mastercard", "mastercard incorporated", "mastercard inc"),
        market="NYSE",
        investor_relations_url="https://investor.mastercard.com/",
    ),
    BuiltinIssuerEntry(
        ticker="PFE",
        cik="0000078003",
        company="Pfizer Inc.",
        aliases=("pfizer", "pfizer inc"),
        market="NYSE",
        investor_relations_url="https://investors.pfizer.com/",
    ),
    BuiltinIssuerEntry(
        ticker="CVX",
        cik="0000093410",
        company="Chevron Corporation",
        aliases=("chevron", "chevron corporation"),
        market="NYSE",
        investor_relations_url="https://www.chevron.com/investors",
    ),
    BuiltinIssuerEntry(
        ticker="COP",
        cik="0001163165",
        company="ConocoPhillips",
        aliases=("conocophillips", "conoco phillips"),
        market="NYSE",
        investor_relations_url="https://www.conocophillips.com/investor-relations/",
    ),
    BuiltinIssuerEntry(
        ticker="NEE",
        cik="0000753308",
        company="NextEra Energy, Inc.",
        aliases=("nextera", "nextera energy", "nextera energy inc"),
        market="NYSE",
        investor_relations_url="https://www.investor.nexteraenergy.com/",
    ),
    BuiltinIssuerEntry(
        ticker="MCD",
        cik="0000063908",
        company="McDonald's Corporation",
        aliases=("mcdonalds", "mcdonald's", "mcdonald's corporation", "mcdonalds corporation"),
        market="NYSE",
        investor_relations_url="https://corporate.mcdonalds.com/corpmcd/investors.html",
    ),
    BuiltinIssuerEntry(
        ticker="NKE",
        cik="0000320187",
        company="NIKE, Inc.",
        aliases=("nike", "nike inc"),
        market="NYSE",
        investor_relations_url="https://investors.nike.com/",
    ),
    BuiltinIssuerEntry(
        ticker="CRM",
        cik="0001108524",
        company="Salesforce, Inc.",
        aliases=("salesforce", "salesforce inc", "salesforce.com", "salesforce com"),
        market="NYSE",
        investor_relations_url="https://investor.salesforce.com/",
    ),
    BuiltinIssuerEntry(
        ticker="UNH",
        cik="0000731766",
        company="UnitedHealth Group Incorporated",
        aliases=("unitedhealth", "unitedhealth group", "unitedhealth group incorporated"),
        market="NYSE",
        investor_relations_url="https://www.unitedhealthgroup.com/investors.html",
    ),
    BuiltinIssuerEntry(
        ticker="JNJ",
        cik="0000200406",
        company="Johnson & Johnson",
        aliases=("johnson & johnson", "johnson and johnson", "jnj"),
        market="NYSE",
        investor_relations_url="https://www.investor.jnj.com/",
    ),
    BuiltinIssuerEntry(
        ticker="ABBV",
        cik="0001551152",
        company="AbbVie Inc.",
        aliases=("abbvie", "abbvie inc"),
        market="NYSE",
        investor_relations_url="https://investors.abbvie.com/",
    ),
    BuiltinIssuerEntry(
        ticker="LLY",
        cik="0000059478",
        company="Eli Lilly and Company",
        aliases=("eli lilly", "eli lilly and company", "lilly"),
        market="NYSE",
        investor_relations_url="https://investor.lilly.com/",
    ),
    BuiltinIssuerEntry(
        ticker="MRK",
        cik="0000310158",
        company="Merck & Co., Inc.",
        aliases=("merck", "merck & co", "merck and co", "merck co inc"),
        market="NYSE",
        investor_relations_url="https://www.merck.com/investor-relations/",
    ),
    BuiltinIssuerEntry(
        ticker="KO",
        cik="0000021344",
        company="The Coca-Cola Company",
        aliases=("coca cola", "coca-cola", "the coca cola company", "the coca-cola company"),
        market="NYSE",
        investor_relations_url="https://investors.coca-colacompany.com/",
    ),
    BuiltinIssuerEntry(
        ticker="WMT",
        cik="0000104169",
        company="Walmart Inc.",
        aliases=("walmart", "walmart inc", "wal-mart"),
        market="NYSE",
        investor_relations_url="https://stock.walmart.com/",
    ),
    BuiltinIssuerEntry(
        ticker="COST",
        cik="0000909832",
        company="Costco Wholesale Corporation",
        aliases=("costco", "costco wholesale", "costco wholesale corporation"),
        market="NASDAQ",
        investor_relations_url="https://investor.costco.com/",
    ),
    BuiltinIssuerEntry(
        ticker="XOM",
        cik="0000034088",
        company="Exxon Mobil Corporation",
        aliases=("exxon", "exxon mobil", "exxonmobil", "exxon mobil corporation"),
        market="NYSE",
        investor_relations_url="https://corporate.exxonmobil.com/investors",
    ),
    BuiltinIssuerEntry(
        ticker="EOG",
        cik="0000821189",
        company="EOG Resources, Inc.",
        aliases=("eog", "eog resources", "eog resources inc"),
        market="NYSE",
        investor_relations_url="https://investors.eogresources.com/",
    ),
    BuiltinIssuerEntry(
        ticker="SLB",
        cik="0000087347",
        company="SLB",
        aliases=("slb", "schlumberger", "schlumberger limited"),
        market="NYSE",
        investor_relations_url="https://investorcenter.slb.com/",
    ),
    BuiltinIssuerEntry(
        ticker="MS",
        cik="0000895421",
        company="Morgan Stanley",
        aliases=("morgan stanley",),
        market="NYSE",
        investor_relations_url="https://www.morganstanley.com/about-us-ir",
    ),
    BuiltinIssuerEntry(
        ticker="C",
        cik="0000831001",
        company="Citigroup Inc.",
        aliases=("citigroup", "citigroup inc", "citi"),
        market="NYSE",
        investor_relations_url="https://www.citigroup.com/global/investors",
    ),
    BuiltinIssuerEntry(
        ticker="WFC",
        cik="0000072971",
        company="Wells Fargo & Company",
        aliases=("wells fargo", "wells fargo company", "wells fargo & company"),
        market="NYSE",
        investor_relations_url="https://www.wellsfargo.com/about/investor-relations/",
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
    payload = {
        "ticker": entry.ticker,
        "sec_cik": entry.cik,
        "company": entry.company,
        "market": entry.market,
        "matched_alias": matched,
    }
    for key, value in {
        "investor_relations_url": entry.investor_relations_url,
        "annual_reports_url": entry.annual_reports_url,
        "earnings_url": entry.earnings_url,
    }.items():
        if value:
            payload[key] = value
    return payload


def _phrase_present(normalized: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {normalized} "


def _normalize_text(text: str) -> str:
    lowered = str(text or "").lower()
    chars = [ch if ch.isalnum() else " " for ch in lowered]
    return " ".join("".join(chars).split())
