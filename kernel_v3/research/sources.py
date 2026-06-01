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
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "sec-edgar-full-text-search",
                        "template": "https://www.sec.gov/edgar/search/#/q={query_url}",
                        "title": "SEC EDGAR search for {query}",
                        "snippet": "Official SEC EDGAR full-text search entry point for the finance query.",
                        "source_kind": "official_search",
                        "required_values": ["query"],
                        "match_any": ["sec", "edgar", "10-k", "10-q", "companyfacts"],
                    }
                ]
            },
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
            source_id="finance-sec-company-tickers",
            profile_id=profile,
            title="SEC ticker, exchange, company, and CIK directory",
            source_family="structured_regulatory_data",
            authority_level="primary",
            base_url="https://www.sec.gov/files/company_tickers_exchange.json",
            allowed_hosts=["www.sec.gov", "sec.gov"],
            use_cases=["ticker to CIK mapping", "exchange association", "company identity resolution"],
            required_identifiers=["ticker or company name"],
            query_hints=["SEC company_tickers_exchange {ticker}", "{company} CIK SEC ticker directory"],
            crawl_notes=[
                "Use before companyfacts/submissions when a CIK is missing.",
                "Treat mappings as identity evidence, not financial statement evidence.",
            ],
        ),
        ResearchSourceEntry(
            source_id="finance-sec-edgar-archives",
            profile_id=profile,
            title="SEC EDGAR filing archive documents",
            source_family="regulatory_filing",
            authority_level="primary",
            base_url="https://www.sec.gov/Archives/edgar/data/",
            allowed_hosts=["www.sec.gov", "sec.gov"],
            use_cases=["primary filing HTML", "filing exhibits", "original 10-K/10-Q/8-K documents"],
            required_identifiers=["CIK", "accession number", "filing document name"],
            query_hints=[
                "{ticker} 10-K accession SEC Archives",
                "{company} 10-Q html sec.gov/Archives/edgar/data",
            ],
            crawl_notes=[
                "Prefer filing document pages over search result pages for quoted financial evidence.",
                "Record accession number and filing period when available.",
            ],
        ),
        ResearchSourceEntry(
            source_id="finance-sec-financial-statement-data-sets",
            profile_id=profile,
            title="SEC financial statement data sets",
            source_family="structured_regulatory_data",
            authority_level="primary",
            base_url="https://www.sec.gov/file/financial-statement-data-sets",
            allowed_hosts=["www.sec.gov", "sec.gov"],
            use_cases=["bulk financial statement facts", "cross-company fundamentals datasets"],
            required_identifiers=["period", "form family", "company identifiers"],
            query_hints=["SEC financial statement data sets {metric}", "SEC bulk financial statements {period}"],
            crawl_notes=[
                "Use for dataset discovery; connect values back to company filings where possible.",
                "Record dataset vintage and SEC caveats.",
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
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "fred-series-search",
                        "template": "https://fred.stlouisfed.org/searchresults/?search_type=series&search={metric_or_query_url}",
                        "title": "FRED series search for {metric_or_query}",
                        "snippet": "Official FRED search results for macro or rate series relevant to the finance query.",
                        "source_kind": "official_search",
                        "required_values": ["metric_or_query"],
                        "match_any": ["fred", "rate", "rates", "inflation", "cpi", "gdp", "employment", "macro"],
                    }
                ]
            },
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
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "cninfo-fulltext-search",
                        "template": "https://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyWord={stock_code_or_ticker_url}",
                        "title": "CNINFO disclosure search for {stock_code_or_ticker}",
                        "snippet": "Official CNINFO full-text search entry point for China A-share annual, quarterly, and announcement disclosures.",
                        "source_kind": "official_search",
                        "required_values": ["stock_code_or_ticker"],
                        "match_any": ["cninfo", "年报", "季报", "公告", "沪深", "a-share", "china"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-hkex-disclosures",
            profile_id=profile,
            title="HKEX issuer disclosure portal",
            source_family="exchange_filing",
            authority_level="primary",
            base_url="https://www.hkexnews.hk/",
            allowed_hosts=["hkexnews.hk", "www.hkexnews.hk", "www1.hkexnews.hk"],
            use_cases=["HK listed issuer announcements", "annual/interim reports"],
            required_identifiers=["stock code", "issuer name", "announcement category"],
            query_hints=["{stock_code} annual report site:hkexnews.hk", "{issuer} announcement HKEX"],
            crawl_notes=["Record announcement date, stock code, and issuer name."],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "hkex-title-search",
                        "template": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN&market=SEHK&category=0",
                        "title": "HKEX title search for {hkex_code}",
                        "snippet": "Official HKEXnews title-search entry point for stock-code announcements and reports.",
                        "source_kind": "official_search",
                        "required_values": ["hkex_code"],
                        "match_any": ["hkex", "hk", "announcement", "annual report", "interim report"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-uk-companies-house-filings",
            profile_id=profile,
            title="UK Companies House filings",
            source_family="regulatory_filing",
            authority_level="primary",
            base_url="https://find-and-update.company-information.service.gov.uk/",
            allowed_hosts=[
                "find-and-update.company-information.service.gov.uk",
                "api.company-information.service.gov.uk",
            ],
            use_cases=["UK company accounts", "confirmation statements", "company identity and officer filings"],
            required_identifiers=["company name", "company number", "filing type", "period"],
            query_hints=["{company} Companies House accounts", "{company_number} filing history Companies House"],
            crawl_notes=[
                "Prefer company filing history and original accounts documents.",
                "Record company number and filing date.",
            ],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "companies-house-company-search",
                        "template": "https://find-and-update.company-information.service.gov.uk/search?q={company_or_query_url}",
                        "title": "Companies House search for {company_or_query}",
                        "snippet": "Official Companies House search entry point for UK company accounts and filing history.",
                        "source_kind": "official_search",
                        "required_values": ["company_or_query"],
                        "match_any": ["companies house", "uk", "accounts", "filing history", "company number"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-canada-sedar-plus-filings",
            profile_id=profile,
            title="SEDAR+ Canadian issuer filings",
            source_family="regulatory_filing",
            authority_level="primary",
            base_url="https://www.sedarplus.ca/",
            allowed_hosts=["sedarplus.ca", "www.sedarplus.ca"],
            use_cases=["Canadian issuer annual reports", "financial statements", "MD&A", "material change reports"],
            required_identifiers=["issuer name", "ticker", "filing type", "period"],
            query_hints=["{company} SEDAR+ annual report", "{ticker} SEDAR financial statements"],
            crawl_notes=["Record filing date, issuer profile, and document type."],
        ),
        ResearchSourceEntry(
            source_id="finance-asx-announcements",
            profile_id=profile,
            title="ASX company announcements",
            source_family="exchange_filing",
            authority_level="primary",
            base_url="https://www.asx.com.au/markets/trade-our-cash-market/announcements",
            allowed_hosts=["asx.com.au", "www.asx.com.au"],
            use_cases=["ASX announcements", "annual reports", "half-year reports", "price-sensitive disclosures"],
            required_identifiers=["ASX code", "issuer name", "announcement type", "date range"],
            query_hints=["{asx_code} annual report ASX announcement", "{company} ASX results announcement"],
            crawl_notes=["Prefer issuer announcement PDFs hosted or linked from ASX."],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "asx-announcements-by-code",
                        "template": "https://www.asx.com.au/asx/v2/statistics/announcements.do?asxCode={asx_code_url}&by=asxCode&timeframe=D&period=M6",
                        "title": "ASX announcements for {asx_code}",
                        "snippet": "Official ASX announcements endpoint for issuer announcements and reports by ASX code.",
                        "source_kind": "official_search",
                        "required_values": ["asx_code"],
                        "match_any": ["asx", "announcement", "annual report", "half-year", "results"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-japan-edinet-filings",
            profile_id=profile,
            title="Japan EDINET disclosure system",
            source_family="regulatory_filing",
            authority_level="primary",
            base_url="https://disclosure2.edinet-fsa.go.jp/",
            allowed_hosts=["disclosure2.edinet-fsa.go.jp"],
            use_cases=["Japanese securities reports", "quarterly reports", "issuer disclosure documents"],
            required_identifiers=["issuer name", "EDINET code", "document type", "period"],
            query_hints=["{company} EDINET securities report", "{edinet_code} annual securities report"],
            crawl_notes=["Record EDINET code, document type, and filing date."],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "edinet-document-search",
                        "template": "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx",
                        "title": "EDINET document search for {edinet_code}",
                        "snippet": "Official EDINET document-search entry point for Japanese securities reports and quarterly reports.",
                        "source_kind": "official_search",
                        "required_values": ["edinet_code"],
                        "match_any": ["edinet", "securities report", "annual securities report", "quarterly report"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-sgx-announcements",
            profile_id=profile,
            title="SGX company announcements",
            source_family="exchange_filing",
            authority_level="primary",
            base_url="https://www.sgx.com/securities/company-announcements",
            allowed_hosts=["sgx.com", "www.sgx.com"],
            use_cases=["Singapore issuer announcements", "annual reports", "financial results"],
            required_identifiers=["stock code", "issuer name", "announcement category", "date range"],
            query_hints=["{issuer} annual report SGX announcement", "{stock_code} financial results SGX"],
            crawl_notes=["Record issuer, announcement category, and publication date."],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "sgx-company-announcements",
                        "template": "https://www.sgx.com/securities/company-announcements",
                        "title": "SGX announcements for {sgx_code}",
                        "snippet": "Official SGX company-announcements entry point for issuer announcements and financial results.",
                        "source_kind": "official_search",
                        "required_values": ["sgx_code"],
                        "match_any": ["sgx", "announcement", "annual report", "financial results"],
                    }
                ]
            },
        ),
        ResearchSourceEntry(
            source_id="finance-global-official-statistics",
            profile_id=profile,
            title="Global official macro and financial statistics",
            source_family="government_statistic",
            authority_level="primary",
            base_url="https://data.worldbank.org/",
            allowed_hosts=[
                "data.worldbank.org",
                "worldbank.org",
                "www.worldbank.org",
                "imf.org",
                "www.imf.org",
                "bis.org",
                "www.bis.org",
                "oecd.org",
                "www.oecd.org",
            ],
            use_cases=["country macro indicators", "rates", "credit aggregates", "industry and trade context"],
            required_identifiers=["country or region", "indicator", "date range"],
            query_hints=["World Bank {indicator} {country}", "IMF {indicator} {country}", "BIS {metric}"],
            crawl_notes=["Record series identifier, source agency, vintage, and revision caveats."],
            metadata={
                "query_url_templates": [
                    {
                        "template_id": "world-bank-indicator-search",
                        "template": "https://data.worldbank.org/search?q={metric_or_query_url}",
                        "title": "World Bank Data search for {metric_or_query}",
                        "snippet": "Official World Bank Data search entry point for country, sector, and macro indicators.",
                        "source_kind": "official_search",
                        "required_values": ["metric_or_query"],
                        "match_any": ["world bank", "country", "gdp", "indicator", "macro", "population", "trade"],
                    }
                ]
            },
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
