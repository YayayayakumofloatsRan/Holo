from __future__ import annotations

from kernel_v3.research.contracts import ResearchSourceEntry
from kernel_v3.research.profiles import FINANCE_FUNDAMENTALS_PROFILE_ID


def source_directory_for_profile(profile_id: str | None) -> list[ResearchSourceEntry]:
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return finance_fundamentals_source_directory()
    return []


def finance_fundamentals_source_directory() -> list[ResearchSourceEntry]:
    profile = FINANCE_FUNDAMENTALS_PROFILE_ID
    return [
        ResearchSourceEntry(
            source_id="finance-sec-edgar-filings",
            profile_id=profile,
            title="SEC EDGAR filings and company submissions",
            source_family="regulatory_filing",
            authority_level="primary",
            base_url="https://www.sec.gov/edgar/search/",
            allowed_hosts=["sec.gov", "www.sec.gov", "edgar.sec.gov"],
            use_cases=["10-K/10-Q filings", "8-K events", "company CIK lookup", "filing text evidence"],
            required_identifiers=["ticker or company name", "CIK when available", "filing type", "period"],
            query_hints=["{ticker} 10-K revenue site:sec.gov", "{company} 10-Q margin filing"],
            crawl_notes=[
                "Prefer filing documents and official company submissions over summaries.",
                "Respect SEC fair-access guidance and bounded fetch budgets.",
            ],
        ),
        ResearchSourceEntry(
            source_id="finance-sec-companyfacts",
            profile_id=profile,
            title="SEC companyfacts and submissions JSON",
            source_family="structured_regulatory_data",
            authority_level="primary",
            base_url="https://data.sec.gov/",
            allowed_hosts=["data.sec.gov"],
            use_cases=["standardized XBRL facts", "reported revenue", "assets", "shares", "filing chronology"],
            required_identifiers=["CIK"],
            query_hints=["CIK companyfacts revenue", "SEC submissions {ticker} CIK"],
            crawl_notes=[
                "Use a descriptive User-Agent.",
                "Treat JSON facts as structured evidence with filing provenance.",
            ],
        ),
        ResearchSourceEntry(
            source_id="finance-company-investor-relations",
            profile_id=profile,
            title="Company investor relations pages",
            source_family="company_ir",
            authority_level="primary",
            base_url="https://investor.example.com/",
            allowed_hosts=["investor.*", "investors.*", "ir.*"],
            use_cases=["earnings releases", "presentations", "press releases", "webcast transcripts when hosted by issuer"],
            required_identifiers=["company name", "ticker", "period"],
            query_hints=["{company} investor relations earnings release", "{ticker} quarterly results investor relations"],
            crawl_notes=["Issuer-hosted materials are primary; third-party mirrors are not primary by default."],
        ),
        ResearchSourceEntry(
            source_id="finance-us-official-statistics",
            profile_id=profile,
            title="US official macro and labor statistics",
            source_family="government_statistic",
            authority_level="primary",
            base_url="https://fred.stlouisfed.org/",
            allowed_hosts=["fred.stlouisfed.org", "bea.gov", "www.bea.gov", "bls.gov", "www.bls.gov"],
            use_cases=["rates", "inflation", "GDP", "employment", "macro inputs for fundamentals"],
            required_identifiers=["series name or economic concept", "date range"],
            query_hints=["FRED {metric}", "BEA {metric}", "BLS {metric}"],
            crawl_notes=["Record series identifiers, release dates, and revision caveats."],
        ),
        ResearchSourceEntry(
            source_id="finance-china-exchange-disclosures",
            profile_id=profile,
            title="China exchange and disclosure portals",
            source_family="exchange_filing",
            authority_level="primary",
            base_url="https://www.cninfo.com.cn/",
            allowed_hosts=[
                "cninfo.com.cn",
                "www.cninfo.com.cn",
                "static.cninfo.com.cn",
                "sse.com.cn",
                "www.sse.com.cn",
                "static.sse.com.cn",
                "szse.cn",
                "www.szse.cn",
                "disclosure.szse.cn",
            ],
            use_cases=["annual reports", "quarterly reports", "exchange announcements"],
            required_identifiers=["ticker", "company Chinese name", "report period"],
            query_hints=["{ticker} 年报 site:cninfo.com.cn", "{company} 季度报告 site:sse.com.cn"],
            crawl_notes=["Prefer original PDF disclosures and exchange-hosted pages."],
        ),
        ResearchSourceEntry(
            source_id="finance-hkex-disclosures",
            profile_id=profile,
            title="HKEX issuer disclosure portal",
            source_family="exchange_filing",
            authority_level="primary",
            base_url="https://www.hkexnews.hk/",
            allowed_hosts=["hkexnews.hk", "www.hkexnews.hk"],
            use_cases=["HK listed issuer announcements", "annual/interim reports"],
            required_identifiers=["stock code", "issuer name", "announcement category"],
            query_hints=["{stock_code} annual report site:hkexnews.hk", "{issuer} announcement HKEX"],
            crawl_notes=["Record announcement date, stock code, and issuer name."],
        ),
        ResearchSourceEntry(
            source_id="finance-market-data-secondary",
            profile_id=profile,
            title="Market data and reputable news secondary sources",
            source_family="market_data_provider",
            authority_level="secondary",
            base_url="https://finance.yahoo.com/",
            allowed_hosts=[
                "finance.yahoo.com",
                "eastmoney.com",
                "www.eastmoney.com",
                "reuters.com",
                "www.reuters.com",
                "bloomberg.com",
                "www.bloomberg.com",
                "ft.com",
                "www.ft.com",
            ],
            use_cases=["price context", "news chronology", "cross-checking facts before primary-source confirmation"],
            required_identifiers=["ticker or company", "date range"],
            query_hints=["{ticker} market cap Reuters", "{company} latest earnings Reuters"],
            crawl_notes=["Use as secondary context; do not satisfy primary-source requirements alone."],
        ),
    ]
