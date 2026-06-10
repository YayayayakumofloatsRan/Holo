import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, finance_fundamentals_profile
from kernel_v3.retrieval import (
    CitationItem,
    EvidenceItem,
    ExtractedSpan,
    FakeFetchProvider,
    FakeSearchProvider,
    FetchedDocument,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)
from kernel_v3.retrieval.evaluate import EvidenceEvaluator, qualify_evidence_candidate
from kernel_v3.retrieval.evidence_compaction import EvidenceCandidate, compact_evidence_candidates
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.rank import rank_sources


def test_retrieval_expands_issuer_ir_page_links_into_report_documents():
    ir_page = SearchSource(
        source_id="issuer-ir-annuals",
        uri="https://ir.blackrock.com/financials/annual-reports-and-proxy/default.aspx",
        title="BlackRock annual reports",
        snippet="Issuer-hosted annual report and proxy materials page.",
        provider="fake_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "company_ir",
            "authority_level": "primary",
            "source_kind": "issuer_annual_reports",
        },
    )
    report_url = "https://ir.blackrock.com/files/doc_downloads/2025/02/Q4-24-10-K-Final.pdf"
    old_report_url = "https://s24.q4cdn.com/856567660/files/doc_financials/2012/ar/2012-Annual-Report.pdf"
    proxy_url = "https://s24.q4cdn.com/856567660/files/doc_financials/2024/ar/2024-Proxy-Statement_vF.pdf"
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider({"BlackRock 2024 total revenues annual report": [ir_page]}),
        fetch_provider=FakeFetchProvider(
            {
                ir_page.uri: (
                    "<html><body>"
                    f"<a href=\"{old_report_url}\">2012 Annual Report</a>"
                    f"<a href=\"{proxy_url}\">2024 Proxy Statement</a>"
                    "<a href=\"/files/doc_downloads/2025/02/Q4-24-10-K-Final.pdf\">"
                    "2024 Form 10-K annual report</a>"
                    "</body></html>"
                ),
                report_url: (
                    "BlackRock 2024 annual report. Total revenues were $20.4 billion in 2024. "
                    "This issuer-hosted Form 10-K filing also discusses net income and operations."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-ir-doc-expansion",
            query="BlackRock 2024 total revenues annual report",
            max_sources=4,
            max_fetches=2,
            max_spans_per_document=2,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-ir-doc-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-ir-doc-expansion", kind="retrieval_fetch_attempt")
    ]
    assert report_url in fetch_uris
    assert old_report_url not in fetch_uris
    assert proxy_url not in fetch_uris
    assert journal.records(task_id="task-ir-doc-expansion", kind="retrieval_document_expansion")
    assert report.diagnostics["document_expanded_source_count"] >= 1
    assert report.status == "sufficient"
    assert any(
        "20.4 billion" in record.data["text"]
        for record in journal.records(task_id="task-ir-doc-expansion", kind="retrieval_evidence")
    )


def test_finance_valuation_compaction_keeps_market_data_facts_with_sec_facts():
    sec_candidate = _evidence_candidate(
        evidence_id="sec-revenue",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001397187.json",
        title="SEC companyfacts JSON",
        text="entityName=lululemon athletica inc. metric=revenue value=11102600000 unit=USD fy=2025 form=10-K",
        source_family="structured_regulatory_data",
        authority_score=0.97,
        facets=["official_financial_statement", "financial_metric"],
    )
    market_candidate = _evidence_candidate(
        evidence_id="nasdaq-market-cap",
        uri="https://api.nasdaq.com/api/quote/LULU/summary?assetclass=stocks",
        title="Nasdaq market summary JSON for LULU",
        text="ticker=LULU metric=market cap value=13160030462 unit=USD source=market_data_json",
        source_family="market_data_provider",
        authority_score=0.72,
        facets=["financial_metric"],
    )

    selected, _, diagnostics = compact_evidence_candidates(
        [sec_candidate, market_candidate],
        goal=SearchGoal(
            goal_id="goal-valuation-compaction",
            query="Compare LULU EV/EBITDA market cap enterprise value EBITDA",
            max_sources=4,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        research_profile=finance_fundamentals_profile(),
        limit=2,
    )

    selected_ids = {candidate.evidence.evidence_id for candidate in selected}
    assert "nasdaq-market-cap" in selected_ids
    assert diagnostics["selected_count"] == 2


def test_finance_valuation_compaction_keeps_each_target_ticker():
    lulu_a = _evidence_candidate(
        evidence_id="lulu-market-a",
        uri="https://api.nasdaq.com/api/quote/LULU/summary?assetclass=stocks",
        title="Nasdaq market summary JSON for LULU",
        text="ticker=LULU metric=market cap value=13160030462 unit=USD source=market_data_json",
        source_family="market_data_provider",
        authority_score=0.72,
        facets=["valuation", "financial_metric"],
    )
    lulu_b = _evidence_candidate(
        evidence_id="lulu-market-b",
        uri="https://stockanalysis.com/stocks/lulu/statistics/",
        title="StockAnalysis statistics for LULU",
        text="ticker=LULU metric=enterprise value value=12000000000 unit=USD metric=ebitda value=2400000000 unit=USD",
        source_family="market_data_provider",
        authority_score=0.68,
        facets=["valuation", "financial_metric"],
    )
    vsco = _evidence_candidate(
        evidence_id="vsco-market",
        uri="https://stockanalysis.com/stocks/vsco/statistics/",
        title="StockAnalysis statistics for VSCO",
        text="ticker=VSCO metric=enterprise value value=1500000000 unit=USD metric=ebitda value=500000000 unit=USD",
        source_family="market_data_provider",
        authority_score=0.68,
        facets=["valuation", "financial_metric"],
    )

    selected, _, diagnostics = compact_evidence_candidates(
        [lulu_a, lulu_b, vsco],
        goal=SearchGoal(
            goal_id="goal-valuation-multi-target-compaction",
            query="Compare LULU and VSCO EV/EBITDA market cap enterprise value EBITDA",
            max_sources=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "target_tickers": ["LULU", "VSCO"],
            },
        ),
        research_profile=finance_fundamentals_profile(),
        limit=2,
    )

    selected_ids = {candidate.evidence.evidence_id for candidate in selected}
    assert any(item.startswith("lulu-") for item in selected_ids)
    assert "vsco-market" in selected_ids
    assert diagnostics["selected_count"] == 2


def test_stockanalysis_visible_market_metrics_are_extracted_for_ev_ebitda():
    body = """
    <html><body>
      <main>
        <h1>LULU Statistics</h1>
        <section>Valuation Market Cap 42.41B Enterprise Value 43.03B</section>
        <section>Financials Revenue 11.20B EBITDA 2.57B Net Income 1.46B</section>
        <section>Balance Sheet Cash &amp; Cash Equivalents 1.51B Total Debt 2.14B</section>
      </main>
    </body></html>
    """

    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-ev-ebitda",
            query="LULU EV EBITDA market cap enterprise value total debt total cash",
            max_sources=5,
            max_fetches=5,
            max_spans_per_document=4,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        document=FetchedDocument(
            document_id="doc-stockanalysis",
            goal_id="goal-ev-ebitda",
            source_id="source-stockanalysis",
            uri="https://stockanalysis.com/stocks/lulu/statistics/",
            title="StockAnalysis statistics for LULU",
            artifact_id="artifact-stockanalysis",
            payload_hash="hash-stockanalysis",
            preview="StockAnalysis statistics for LULU",
            size_bytes=len(body),
            metadata={"source_kind": "market_data_statistics", "mime_type": "text/html"},
        ),
        body=body,
    )

    text = " ".join(span.text for span in spans)
    assert "Market Cap 42.41B" in text
    assert "Enterprise Value 43.03B" in text
    assert "Total Debt 2.14B" in text


def test_sec_submissions_expand_to_primary_filing_even_when_companyfacts_exists():
    companyfacts = SearchSource(
        source_id="sec-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001364742",
        },
    )
    submissions = SearchSource(
        source_id="sec-submissions",
        uri="https://data.sec.gov/submissions/CIK0001364742.json",
        title="SEC submissions JSON for CIK 0001364742",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001364742",
        },
    )
    primary_url = "https://www.sec.gov/Archives/edgar/data/1364742/000136474225000010/blk-20241231.htm"
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"BlackRock total revenues fiscal year 2024 SEC 10-K": [companyfacts, submissions]}
        ),
        fetch_provider=FakeFetchProvider(
            {
                companyfacts.uri: (
                    "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
                    "fy=2023 period=annual form=10-K filed=2024-02-23 end=2023-12-31 "
                    "facts=metric=revenue value=11012000000"
                ),
                submissions.uri: json.dumps(
                    {
                        "cik": "1364742",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0001364742-25-000010", "0001364742-24-000009"],
                                "form": ["10-K", "10-K"],
                                "primaryDocument": ["blk-20241231.htm", "blk-20231231.htm"],
                                "reportDate": ["2024-12-31", "2023-12-31"],
                                "filingDate": ["2025-02-28", "2024-02-23"],
                            }
                        },
                    }
                ),
                primary_url: (
                    "BlackRock 2024 Form 10-K. Total revenues for fiscal year 2024 were "
                    "$20.4 billion. This official SEC filing covers reportDate=2024-12-31."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-sec-submission-expansion",
            query="BlackRock total revenues fiscal year 2024 SEC 10-K",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "deep",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-sec-submission-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-sec-submission-expansion", kind="retrieval_fetch_attempt")
    ]
    assert companyfacts.uri in fetch_uris
    assert submissions.uri in fetch_uris
    assert primary_url in fetch_uris
    assert report.status == "sufficient"
    assert any(
        "20.4 billion" in record.data["text"]
        for record in journal.records(task_id="task-sec-submission-expansion", kind="retrieval_evidence")
    )


def test_finance_valuation_fetch_queue_preserves_market_data_provider():
    companyfacts = SearchSource(
        source_id="lulu-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001397187.json",
        title="SEC companyfacts JSON for CIK 0001397187",
        snippet="Official SEC XBRL companyfacts JSON for lululemon.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001397187",
        },
    )
    submissions = SearchSource(
        source_id="lulu-submissions",
        uri="https://data.sec.gov/submissions/CIK0001397187.json",
        title="SEC submissions JSON for CIK 0001397187",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001397187",
        },
    )
    sec_search = SearchSource(
        source_id="lulu-edgar-search",
        uri="https://www.sec.gov/edgar/search/#/q=LULU%2010-K%20enterprise%20value%20EBITDA",
        title="SEC EDGAR search for LULU 10-K enterprise value EBITDA",
        snippet="SEC filing search page.",
        provider="research_source_directory_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "regulatory_filing",
            "authority_level": "primary",
            "source_kind": "sec_edgar_search",
        },
    )
    market = SearchSource(
        source_id="lulu-yahoo-stats",
        uri="https://finance.yahoo.com/quote/LULU/key-statistics/",
        title="LULU key statistics",
        snippet="Market cap enterprise value EBITDA valuation statistics.",
        provider="research_source_query_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "market_data_provider",
            "authority_level": "secondary",
            "source_kind": "finance_quote_key_statistics",
        },
    )
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"LULU EV/EBITDA enterprise value EBITDA 10-K": [companyfacts, submissions, sec_search, market]}
        ),
        fetch_provider=FakeFetchProvider(
            {
                companyfacts.uri: "SEC companyfacts entityName=lululemon facts=metric=revenue value=10000000000 form=10-K",
                submissions.uri: json.dumps({"cik": "1397187", "filings": {"recent": {"form": ["10-K"]}}}),
                sec_search.uri: "<html><body>SEC search page</body></html>",
                market.uri: (
                    "<html><body>Market statistics</body><script>"
                    'window.__DATA__={"marketCap":{"raw":36400000000,"fmt":"36.4B"},'
                    '"enterpriseValue":{"raw":34800000000,"fmt":"34.8B"},'
                    '"ebitda":{"raw":2600000000,"fmt":"2.6B"}};'
                    "</script></html>"
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-market-data-fetch-coverage",
            query="LULU EV/EBITDA enterprise value EBITDA 10-K",
            max_sources=8,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-market-data-fetch-coverage",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-market-data-fetch-coverage", kind="retrieval_fetch_attempt")
    ]
    assert market.uri in fetch_uris


def test_finance_valuation_retrieval_accepts_structured_market_data_evidence():
    companyfacts = SearchSource(
        source_id="lulu-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001397187.json",
        title="SEC companyfacts JSON for CIK 0001397187",
        snippet="Official SEC XBRL companyfacts JSON for lululemon.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001397187",
        },
    )
    nasdaq_summary = SearchSource(
        source_id="lulu-nasdaq-summary",
        uri="https://api.nasdaq.com/api/quote/LULU/summary?assetclass=stocks",
        title="Nasdaq market summary JSON for LULU",
        snippet="Structured market data summary with market cap.",
        provider="research_source_query_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "market_data_provider",
            "authority_level": "secondary",
            "source_kind": "market_data_statistics",
        },
    )
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"LULU EV/EBITDA market cap EBITDA": [companyfacts, nasdaq_summary]}
        ),
        fetch_provider=FakeFetchProvider(
            {
                companyfacts.uri: (
                    "SEC companyfacts annual financial summary entityName=lululemon athletica inc. "
                    "facts=metric=revenue value=11102600000 unit=USD fy=2025 form=10-K"
                ),
                nasdaq_summary.uri: json.dumps(
                    {
                        "data": {
                            "symbol": "LULU",
                            "summaryData": {
                                "MarketCap": {"label": "Market Cap", "value": "13,160,030,462"}
                            },
                        }
                    }
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-market-data-evidence",
            query="LULU EV/EBITDA market cap EBITDA",
            max_sources=4,
            max_fetches=2,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "secondary_or_better",
                "preferred_source_families": ["market_data_provider", "structured_regulatory_data"],
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-market-data-evidence",
        run_id="run-1",
    )

    evidence_texts = [
        record.data["text"]
        for record in journal.records(task_id="task-market-data-evidence", kind="retrieval_evidence")
    ]
    assert any("metric=market cap value=13160030462" in text for text in evidence_texts)


def test_finance_transaction_query_ranks_filing_text_before_companyfacts():
    companyfacts = SearchSource(
        source_id="pfe-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000078003.json",
        title="SEC companyfacts JSON for CIK 0000078003",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0000078003",
        },
    )
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    filing_text = SearchSource(
        source_id="pfe-8k-text",
        uri="https://www.sec.gov/Archives/edgar/data/78003/example/0000078003-23-000001.txt",
        title="SEC complete submission text for Pfizer Seagen acquisition 8-K",
        snippet="Official SEC 8-K complete submission text for acquisition transaction value.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "regulatory_filing",
            "authority_level": "primary",
            "source_kind": "sec_complete_submission_text",
            "sec_cik": "0000078003",
        },
    )

    ranked = rank_sources(
        SearchGoal(
            goal_id="goal-pfe-sgen",
            query="Pfizer Seagen acquisition transaction EV revenue multiple 8-K consideration",
            max_sources=5,
            max_fetches=5,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        [companyfacts, submissions, filing_text],
        research_profile=finance_fundamentals_profile(),
    )

    assert ranked[0].source_id == "pfe-8k-text"
    assert ranked[1].source_id == "pfe-submissions"
    assert ranked[-1].source_id == "pfe-companyfacts"


def test_finance_transaction_root_goal_controls_subquery_ranking():
    companyfacts = SearchSource(
        source_id="sgen-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json",
        title="SEC companyfacts JSON for CIK 0001060736",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001060736",
        },
    )
    submissions = SearchSource(
        source_id="sgen-submissions",
        uri="https://data.sec.gov/submissions/CIK0001060736.json",
        title="SEC submissions JSON for CIK 0001060736",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001060736",
        },
    )

    ranked = rank_sources(
        SearchGoal(
            goal_id="goal-sgen-revenue",
            query="SGEN 2022 revenue 10-K",
            max_sources=5,
            max_fetches=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "root_goal": "Pfizer Seagen acquisition transaction EV revenue multiple using 8-K disclosures",
            },
        ),
        [companyfacts, submissions],
        research_profile=finance_fundamentals_profile(),
    )

    assert ranked[0].source_id == "sgen-submissions"


def test_transaction_retrieval_reserves_fetch_budget_for_sec_document_expansion():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    companyfacts = SearchSource(
        source_id="pfe-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000078003.json",
        title="SEC companyfacts JSON for CIK 0000078003",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0000078003",
        },
    )
    primary_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000001/pfe-20230313.htm"
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"Pfizer Seagen acquisition transaction EV revenue multiple 8-K consideration": [companyfacts, submissions]}
        ),
        fetch_provider=FakeFetchProvider(
            {
                companyfacts.uri: "SEC companyfacts official financial statements entityName=Pfizer Inc.",
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0000078003-23-000001", "0000078003-22-000010"],
                                "form": ["8-K", "10-K"],
                                "primaryDocument": ["pfe-20230313.htm", "pfe-20221231.htm"],
                                "reportDate": ["2023-03-13", "2022-12-31"],
                                "filingDate": ["2023-03-13", "2023-02-23"],
                            }
                        },
                    }
                ),
                primary_url: (
                    "Pfizer Seagen acquisition Form 8-K. The transaction value was $43 billion "
                    "and the filing discusses public deal disclosures."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-expansion",
            query="Pfizer Seagen acquisition transaction EV revenue multiple 8-K consideration",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-expansion", kind="retrieval_fetch_attempt")
    ]
    assert submissions.uri in fetch_uris
    assert primary_url in fetch_uris
    assert journal.records(task_id="task-transaction-expansion", kind="retrieval_document_expansion")
    assert report.diagnostics["document_expanded_source_count"] >= 1


def test_transaction_submission_prioritizes_merger_8k_over_earnings_8k():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    merger_url = "https://www.sec.gov/Archives/edgar/data/78003/000119312523068538/d408093d8k.htm"
    earnings_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000099/pfe-20231013.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider({"Pfizer Seagen acquisition enterprise value revenue 2023": [submissions]}),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": [
                                    "0000078003-23-000019",
                                    "0000078003-23-000099",
                                    "0000078003-23-000118",
                                    "0001193125-23-068538",
                                ],
                                "form": ["8-K", "8-K", "8-K", "8-K"],
                                "primaryDocument": [
                                    "pfe-20230221.htm",
                                    "pfe-20231013.htm",
                                    "pfe-20231207.htm",
                                    "d408093d8k.htm",
                                ],
                                "primaryDocDescription": [
                                    "PFIZER 8-K FEB 21 2023",
                                    "PFIZER 8-K OCTOBER 13 2023",
                                    "PFIZER 8-K DECEMBER 7 2023",
                                    "8-K",
                                ],
                                "items": ["8.01", "2.02,2.05,7.01,9.01", "5.02,7.01,9.01", "1.01,7.01,8.01,9.01"],
                                "reportDate": ["2023-02-21", "2023-10-13", "2023-12-07", "2023-03-12"],
                                "filingDate": ["2023-02-21", "2023-10-13", "2023-12-12", "2023-03-13"],
                            }
                        },
                    }
                ),
                merger_url: "Pfizer Seagen merger agreement Form 8-K. Transaction enterprise value was $43 billion.",
                earnings_url: "Pfizer October 2023 8-K costs and earnings release.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-merger-priority",
            query="Pfizer Seagen acquisition enterprise value revenue 2023",
            max_sources=5,
            max_fetches=3,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-merger-priority",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-merger-priority", kind="retrieval_fetch_attempt")
    ]
    assert merger_url in fetch_uris
    assert earnings_url not in fetch_uris


def test_transaction_amount_span_ranks_within_tight_span_budget():
    body = """
    <html><body>
    <p>Pfizer and Seagen announced various risks related to the proposed acquisition and transaction.</p>
    <p>Pfizer and Seagen noted litigation, regulatory actions, financing risks, unknown liabilities,
    and other risks related to the proposed acquisition and transaction.</p>
    <p>On March 12, 2023, Pfizer entered into an Agreement and Plan of Merger with Seagen.</p>
    <p>At the effective time of the Merger, each share of common stock of Seagen will be converted
    into the right to receive $229.00 in cash, subject to limited exceptions.</p>
    <p>Pfizer and Seagen also entered into voting agreements and made other transaction disclosures.</p>
    </body></html>
    """
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-transaction-span-ranking",
            query="Pfizer Seagen acquisition transaction value revenue 2023",
            max_sources=5,
            max_fetches=3,
            max_spans_per_document=4,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        document=FetchedDocument(
            document_id="doc-transaction-span-ranking",
            goal_id="goal-transaction-span-ranking",
            source_id="source",
            uri="https://www.sec.gov/Archives/edgar/data/78003/000119312523068538/d408093d8k.htm",
            title="SEC 8-K merger agreement",
            artifact_id="artifact",
            payload_hash="hash",
            preview="",
            size_bytes=len(body),
            metadata={"mime_type": "text/html"},
        ),
        body=body,
    )

    assert any("$229.00" in span.text for span in spans)


def test_sec_complete_submission_extracts_transaction_value_after_default_prefix_limit():
    prefix = "<SEC-DOCUMENT><HTML><BODY>" + ("irrelevant filing boilerplate " * 9000)
    body = (
        prefix
        + "EX-99.1 Pfizer Invests $43 Billion to Battle Cancer. "
        + "Pfizer to acquire Seagen for $229 per Seagen share in cash, "
        + "for a total enterprise value of approximately $43 billion. "
        + "Transaction value of approximately $43 billion, inclusive of net debt."
    )
    assert len(prefix) > 200_000
    document = FetchedDocument(
        document_id="doc-sec-complete-submission",
        goal_id="goal-sec-complete-transaction-value",
        source_id="source-sec-complete-submission",
        uri="https://www.sec.gov/Archives/edgar/data/78003/000119312523068538/0001193125-23-068538.txt",
        title="SEC complete submission text for Pfizer Seagen acquisition 8-K",
        artifact_id="artifact-sec-complete-submission",
        payload_hash="hash",
        preview=body[:200],
        size_bytes=len(body.encode("utf-8")),
        metadata={"source_kind": "sec_complete_submission_text"},
    )

    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-sec-complete-transaction-value",
            query="Pfizer Seagen acquisition total consideration enterprise value",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=4,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        document=document,
        body=body,
    )

    assert any("$43 billion" in span.text for span in spans)
    assert any("enterprise value" in span.text.lower() or "transaction value" in span.text.lower() for span in spans)


def test_transaction_retrieval_fetches_sec_submissions_before_generic_pages():
    submissions = SearchSource(
        source_id="sgen-submissions",
        uri="https://data.sec.gov/submissions/CIK0001060736.json",
        title="SEC submissions JSON for CIK 0001060736",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001060736",
        },
    )
    generic_page = SearchSource(
        source_id="generic-search-page",
        uri="https://www.sec.gov/edgar/search/#/q=Seagen%20acquisition",
        title="SEC EDGAR search page",
        snippet="Generic search page for Seagen acquisition.",
        provider="live_web_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "regulatory_filing",
            "authority_level": "primary",
            "source_kind": "sec_edgar_search",
            "sec_cik": "0001060736",
        },
    )
    companyfacts = SearchSource(
        source_id="sgen-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json",
        title="SEC companyfacts JSON for CIK 0001060736",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001060736",
        },
    )
    primary_url = "https://www.sec.gov/Archives/edgar/data/1060736/000106073623000010/sgen-20221231.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "SGEN revenue needed for Pfizer Seagen acquisition EV revenue multiple": [
                    generic_page,
                    companyfacts,
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                generic_page.uri: "<html><body>SEC search navigation without filing facts.</body></html>",
                companyfacts.uri: "SEC companyfacts official financial statements entityName=Seagen Inc.",
                submissions.uri: json.dumps(
                    {
                        "cik": "1060736",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0001060736-23-000010"],
                                "form": ["10-K"],
                                "primaryDocument": ["sgen-20221231.htm"],
                                "reportDate": ["2022-12-31"],
                                "filingDate": ["2023-02-15"],
                            }
                        },
                    }
                ),
                primary_url: "Seagen 2022 Form 10-K. Total revenues were $1.96 billion.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-priority",
            query="SGEN revenue needed for Pfizer Seagen acquisition EV revenue multiple",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "root_goal": "Pfizer Seagen acquisition transaction EV revenue multiple using 8-K and 10-K filings",
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-priority",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-priority", kind="retrieval_fetch_attempt")
    ]
    assert fetch_uris[0] == submissions.uri
    assert generic_page.uri not in fetch_uris
    assert primary_url in fetch_uris


def test_bridge_reconciliation_prefers_annual_filing_over_event_8k():
    submissions = SearchSource(
        source_id="khc-submissions",
        uri="https://data.sec.gov/submissions/CIK0001637459.json",
        title="SEC submissions JSON for CIK 0001637459",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001637459",
        },
    )
    tenk_url = "https://www.sec.gov/Archives/edgar/data/1637459/000163745925000011/khc-20241228.htm"
    eightk_url = "https://www.sec.gov/Archives/edgar/data/1637459/000119312524228000/d833675d8k.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Kraft Heinz KHC 10-K adjusted EBITDA bridge non-GAAP reconciliation": [
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "1637459",
                        "filings": {
                            "recent": {
                                "accessionNumber": [
                                    "0001193125-24-228000",
                                    "0001637459-25-000011",
                                ],
                                "form": ["8-K", "10-K"],
                                "primaryDocument": ["d833675d8k.htm", "khc-20241228.htm"],
                                "primaryDocDescription": ["8-K", "10-K"],
                                "items": ["1.01,9.01", ""],
                                "reportDate": ["2024-09-27", "2024-12-28"],
                                "filingDate": ["2024-09-27", "2025-02-13"],
                            }
                        },
                    }
                ),
                tenk_url: (
                    "Kraft Heinz 2024 Form 10-K. Adjusted EBITDA reconciliation: "
                    "net income was $1.0 billion, restructuring add-backs were $0.2 billion, "
                    "and Adjusted EBITDA was $6.0 billion."
                ),
                eightk_url: "Kraft Heinz 8-K acquisition agreement with no adjusted EBITDA bridge.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-khc-bridge-filing-priority",
            query="Kraft Heinz KHC 10-K adjusted EBITDA bridge non-GAAP reconciliation",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-khc-bridge-filing-priority",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-khc-bridge-filing-priority", kind="retrieval_fetch_attempt")
    ]
    assert tenk_url in fetch_uris
    if eightk_url in fetch_uris:
        assert fetch_uris.index(tenk_url) < fetch_uris.index(eightk_url)


def test_bridge_reconciliation_metadata_prefers_annual_filing_even_with_target_year():
    submissions = SearchSource(
        source_id="wsc-submissions",
        uri="https://data.sec.gov/submissions/CIK0001699136.json",
        title="SEC submissions JSON for CIK 0001699136",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001699136",
        },
    )
    tenk_url = "https://www.sec.gov/Archives/edgar/data/1699136/000169913625000011/wsc-20241231.htm"
    eightk_url = "https://www.sec.gov/Archives/edgar/data/1699136/000169913624000066/wsc-20240930.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider({"WillScot Mobile Mini 2024 adjusted EBITDA": [submissions]}),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "1699136",
                        "filings": {
                            "recent": {
                                "accessionNumber": [
                                    "0001699136-24-000066",
                                    "0001699136-25-000011",
                                ],
                                "form": ["8-K", "10-K"],
                                "primaryDocument": ["wsc-20240930.htm", "wsc-20241231.htm"],
                                "primaryDocDescription": ["8-K earnings release", "10-K annual report"],
                                "items": ["2.02,9.01", ""],
                                "reportDate": ["2024-09-30", "2024-12-31"],
                                "filingDate": ["2024-10-30", "2025-02-20"],
                            }
                        },
                    }
                ),
                tenk_url: (
                    "WillScot Mobile Mini 2024 Form 10-K. Non-GAAP reconciliation table. "
                    "Adjusted EBITDA add-back components include restructuring, transaction costs, "
                    "and stock-based compensation."
                ),
                eightk_url: "WillScot Mobile Mini third quarter 2024 earnings release.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-wsc-bridge-policy",
            query="WillScot Mobile Mini 2024 adjusted EBITDA",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "root_goal": "Investigate WSC adjusted EBITDA add-back trend in 2024 filings.",
                "required_evidence_terms": ["reconciliation", "non-GAAP", "add-back"],
                "missing_slots": ["base_metric", "addback_components", "adjusted_metric"],
                "evidence_policy": {
                    "authority": "primary",
                    "required_terms": ["reconciliation", "non-GAAP", "add-back"],
                    "required_source_families": ["regulatory_filing"],
                    "forbidden_source_families": ["market_data_provider"],
                },
                "slot_frame": {
                    "task_type": "reconcile",
                    "missing_slots": ["base_metric", "addback_components", "adjusted_metric"],
                    "required_slots": [
                        {"name": "base_metric", "accepted_attributes": ["net income"]},
                        {"name": "addback_components", "accepted_attributes": ["addback"]},
                        {"name": "adjusted_metric", "accepted_attributes": ["adjusted ebitda"]},
                    ],
                },
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-wsc-bridge-policy",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-wsc-bridge-policy", kind="retrieval_fetch_attempt")
    ]
    assert tenk_url in fetch_uris
    if eightk_url in fetch_uris:
        assert fetch_uris.index(tenk_url) < fetch_uris.index(eightk_url)


def test_bridge_reconciliation_prefers_recent_annual_filings_with_no_target_year():
    submissions = SearchSource(
        source_id="wsc-submissions-recent",
        uri="https://data.sec.gov/submissions/CIK0001647088.json",
        title="SEC submissions JSON for CIK 0001647088",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001647088",
        },
    )
    recent_url = "https://www.sec.gov/Archives/edgar/data/1647088/000164708825000009/wsc-20241231.htm"
    old_url = "https://www.sec.gov/Archives/edgar/data/1647088/000164708818000006/wsc123117-10k.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider({"WSC adjusted EBITDA add-back reconciliation": [submissions]}),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "1647088",
                        "filings": {
                            "recent": {
                                "accessionNumber": [
                                    "0001647088-25-000009",
                                    "0001647088-18-000006",
                                ],
                                "form": ["10-K", "10-K"],
                                "primaryDocument": ["wsc-20241231.htm", "wsc123117-10k.htm"],
                                "primaryDocDescription": ["10-K annual report", "10-K annual report"],
                                "items": ["", ""],
                                "reportDate": ["2024-12-31", "2017-12-31"],
                                "filingDate": ["2025-02-20", "2018-03-16"],
                            }
                        },
                    }
                ),
                recent_url: (
                    "WillScot 2024 Form 10-K. Reconciliation of Income from continuing operations "
                    "to Adjusted EBITDA with add-back components."
                ),
                old_url: (
                    "WillScot 2017 Form 10-K. Older reconciliation of Income from continuing operations "
                    "to Adjusted EBITDA."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-wsc-bridge-recent",
            query="WSC adjusted EBITDA add-back reconciliation",
            max_sources=5,
            max_fetches=3,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "root_goal": "Investigate WSC adjusted EBITDA add-back trend across relevant public filings.",
                "required_evidence_terms": ["reconciliation", "non-GAAP", "add-back"],
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-wsc-bridge-recent",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-wsc-bridge-recent", kind="retrieval_fetch_attempt")
    ]
    assert recent_url in fetch_uris
    if old_url in fetch_uris:
        assert fetch_uris.index(recent_url) < fetch_uris.index(old_url)


def test_sec_primary_filing_extraction_finds_late_adjusted_ebitda_bridge_table():
    filler = "<p>Risk factors and business overview without non-GAAP bridge detail.</p>" * 5000
    bridge_table = """
    <table>
      <tr><th>Reconciliation of Income from continuing operations to Adjusted EBITDA</th></tr>
      <tr><td>Income from continuing operations</td><td>$341.8</td><td>$276.3</td></tr>
      <tr><td>Depreciation and amortization</td><td>$513.0</td><td>$482.0</td></tr>
      <tr><td>Stock-based compensation</td><td>$73.0</td><td>$68.0</td></tr>
      <tr><td>Restructuring and transaction costs</td><td>$40.0</td><td>$32.0</td></tr>
      <tr><td>Adjusted EBITDA</td><td>$967.8</td><td>$858.3</td></tr>
    </table>
    """
    body = f"<html><body>{filler}{bridge_table}</body></html>"

    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-wsc-late-bridge-table",
            query="WSC adjusted EBITDA add-back trend reconciliation",
            max_sources=5,
            max_fetches=5,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "root_goal": "Investigate WSC adjusted EBITDA add-back trend from relevant filings.",
            },
        ),
        document=FetchedDocument(
            document_id="doc-wsc-10k-late-table",
            goal_id="goal-wsc-late-bridge-table",
            source_id="source-wsc-10k-late-table",
            uri="https://www.sec.gov/Archives/edgar/data/1647088/000164708825000009/wsc-20241231.htm",
            title="WillScot Holdings 2024 Form 10-K",
            artifact_id="artifact-wsc-10k-late-table",
            payload_hash="hash-wsc-10k-late-table",
            preview="WillScot Holdings 2024 Form 10-K",
            size_bytes=len(body),
            metadata={
                "source_kind": "sec_primary_filing_document",
                "source_family": "regulatory_filing",
                "mime_type": "text/html",
            },
        ),
        body=body,
    )

    text = " ".join(span.text for span in spans).lower()
    assert "income from continuing operations" in text
    assert "adjusted ebitda" in text
    assert "depreciation and amortization" in text


def test_transaction_retrieval_fetches_issuer_event_page_under_tight_budget():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    issuer_event = SearchSource(
        source_id="pfe-seagen-event-page",
        uri="https://www.pfizer.com/about/programs-policies/pfizer-seagen",
        title="Pfizer Seagen acquisition announcement",
        snippet="Issuer-hosted acquisition page with transaction value and deal announcement.",
        provider="research_source_query_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "company_ir",
            "authority_level": "primary",
            "source_kind": "issuer_investor_relations",
        },
    )
    primary_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/pfe-20230313.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures": [
                    submissions,
                    issuer_event,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0000078003-23-000016"],
                                "form": ["8-K"],
                                "primaryDocument": ["pfe-20230313.htm"],
                                "primaryDocDescription": ["Definitive merger agreement for Seagen acquisition"],
                                "items": ["1.01,8.01,9.01"],
                                "reportDate": ["2023-03-13"],
                                "filingDate": ["2023-03-13"],
                            }
                        },
                    }
                ),
                issuer_event.uri: "Pfizer announced the Seagen acquisition transaction value was $43 billion.",
                primary_url: "Pfizer Seagen acquisition Form 8-K.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-event-page-budget",
            query="Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-event-page-budget",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-event-page-budget", kind="retrieval_fetch_attempt")
    ]
    assert submissions.uri in fetch_uris
    assert issuer_event.uri in fetch_uris
    assert primary_url in fetch_uris


def test_transaction_event_page_fetch_failure_suggests_alternate_event_source():
    issuer_event = SearchSource(
        source_id="pfe-seagen-event-page",
        uri="https://www.pfizer.com/about/programs-policies/pfizer-seagen",
        title="Pfizer Seagen acquisition announcement",
        snippet="Issuer-hosted acquisition page with transaction value and deal announcement.",
        provider="research_source_query_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "company_ir",
            "authority_level": "primary",
            "source_kind": "issuer_investor_relations",
        },
    )
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures": [
                    issuer_event,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                issuer_event.uri: {
                    "status": "failed",
                    "body": "",
                    "diagnostics": {"reason": "http_status_error"},
                },
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-event-fetch-failure",
            query="Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures",
            max_sources=5,
            max_fetches=2,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-event-fetch-failure",
        run_id="run-1",
    )

    fetch_attempt = journal.records(
        task_id="task-transaction-event-fetch-failure",
        kind="retrieval_fetch_attempt",
    )[0]
    assert fetch_attempt.data["diagnostics"]["reason"] == "http_status_error"

    actions = report.diagnostics["next_tool_actions"]
    assert any(action["action"] == "find_alternate_event_source" for action in actions)
    event_action = next(action for action in actions if action["action"] == "find_alternate_event_source")
    assert event_action["payload_hint"]["strategy"] == "event_source_fallback"
    assert event_action["payload_hint"]["failed_sources"][0]["uri"] == issuer_event.uri


def test_transaction_submission_expansion_diversifies_8k_years_when_event_year_unknown():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    accessions = [f"0000078003-25-{index:06d}" for index in range(30, 0, -1)]
    forms = ["8-K"] * len(accessions)
    primary_documents = [f"pfe-2025-{index:02d}.htm" for index in range(30, 0, -1)]
    report_dates = [f"2025-{((index - 1) % 12) + 1:02d}-01" for index in range(30, 0, -1)]
    filing_dates = list(report_dates)
    accessions.extend(["0000078003-24-000010", "0000078003-23-000016"])
    forms.extend(["8-K", "8-K"])
    primary_documents.extend(["pfe-20240110.htm", "pfe-20230313.htm"])
    report_dates.extend(["2024-01-10", "2023-03-13"])
    filing_dates.extend(["2024-01-10", "2023-03-13"])
    event_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/pfe-20230313.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures": [
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": accessions,
                                "form": forms,
                                "primaryDocument": primary_documents,
                                "reportDate": report_dates,
                                "filingDate": filing_dates,
                            }
                        },
                    }
                ),
                event_url: "Pfizer Seagen acquisition Form 8-K. Transaction value was $43 billion.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-year-diversity",
            query="Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures",
            max_sources=5,
            max_fetches=8,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-year-diversity",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-year-diversity", kind="retrieval_fetch_attempt")
    ]
    assert event_url in fetch_uris


def test_transaction_submission_expands_archive_files_for_older_event_filings():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    archive_url = "https://data.sec.gov/submissions/CIK0000078003-submissions-001.json"
    event_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/pfe-20230313.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures": [
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0000078003-25-000111"],
                                "form": ["8-K"],
                                "primaryDocument": ["pfe-20250429.htm"],
                                "reportDate": ["2025-04-29"],
                                "filingDate": ["2025-04-29"],
                            },
                            "files": [
                                {
                                    "name": "CIK0000078003-submissions-001.json",
                                    "filingFrom": "2022-01-01",
                                    "filingTo": "2023-12-31",
                                }
                            ],
                        },
                    }
                ),
                archive_url: json.dumps(
                    {
                        "accessionNumber": ["0000078003-23-000016"],
                        "form": ["8-K"],
                        "primaryDocument": ["pfe-20230313.htm"],
                        "reportDate": ["2023-03-13"],
                        "filingDate": ["2023-03-13"],
                    }
                ),
                event_url: "Pfizer Seagen acquisition Form 8-K. Transaction value was $43 billion.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-archive-expansion",
            query="Pfizer Seagen acquisition transaction EV revenue multiple public deal disclosures",
            max_sources=5,
            max_fetches=8,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-archive-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-archive-expansion", kind="retrieval_fetch_attempt")
    ]
    assert archive_url in fetch_uris
    assert event_url in fetch_uris


def test_transaction_submission_scans_deep_recent_filings_for_target_year():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    accessions = [f"0000078003-25-{index:06d}" for index in range(260, 0, -1)]
    forms = ["8-K"] * len(accessions)
    primary_documents = [f"pfe-2025-{index:03d}.htm" for index in range(260, 0, -1)]
    report_dates = ["2025-04-24"] * len(accessions)
    filing_dates = ["2025-04-24"] * len(accessions)
    accessions.append("0000078003-23-000016")
    forms.append("8-K")
    primary_documents.append("pfe-20230313.htm")
    report_dates.append("2023-03-13")
    filing_dates.append("2023-03-13")
    event_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/pfe-20230313.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer 8-K March 13 2023 Seagen acquisition total consideration enterprise value": [
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": accessions,
                                "form": forms,
                                "primaryDocument": primary_documents,
                                "reportDate": report_dates,
                                "filingDate": filing_dates,
                            }
                        },
                    }
                ),
                event_url: "Pfizer Seagen acquisition Form 8-K. Transaction value was $43 billion.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-deep-recent",
            query="Pfizer 8-K March 13 2023 Seagen acquisition total consideration enterprise value",
            max_sources=5,
            max_fetches=6,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-deep-recent",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-deep-recent", kind="retrieval_fetch_attempt")
    ]
    assert event_url in fetch_uris


def test_transaction_submission_event_metadata_prioritizes_relevant_8k():
    submissions = SearchSource(
        source_id="pfe-submissions",
        uri="https://data.sec.gov/submissions/CIK0000078003.json",
        title="SEC submissions JSON for CIK 0000078003",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0000078003",
        },
    )
    event_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/pfe-20230313.htm"
    unrelated_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000001/pfe-20230131.htm"
    journal = JournalStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Pfizer Seagen acquisition transaction EV revenue multiple merger agreement 2023": [
                    submissions,
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                submissions.uri: json.dumps(
                    {
                        "cik": "78003",
                        "filings": {
                            "recent": {
                                "accessionNumber": [
                                    "0000078003-23-000001",
                                    "0000078003-23-000016",
                                    "0000078003-23-000015",
                                ],
                                "form": ["8-K", "8-K", "8-K"],
                                "primaryDocument": [
                                    "pfe-20230131.htm",
                                    "pfe-20230313.htm",
                                    "pfe-20230301.htm",
                                ],
                                "primaryDocDescription": [
                                    "Fourth quarter financial results",
                                    "Definitive merger agreement for Seagen acquisition",
                                    "Executive compensation update",
                                ],
                                "items": ["2.02,9.01", "1.01,8.01,9.01", "5.02"],
                                "reportDate": ["2023-01-31", "2023-03-13", "2023-03-01"],
                                "filingDate": ["2023-01-31", "2023-03-13", "2023-03-01"],
                            }
                        },
                    }
                ),
                event_url: "Pfizer Seagen acquisition Form 8-K. Transaction value was $43 billion.",
                unrelated_url: "Pfizer fourth quarter financial results.",
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-transaction-event-metadata",
            query="Pfizer Seagen acquisition transaction EV revenue multiple merger agreement 2023",
            max_sources=5,
            max_fetches=3,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "light",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-transaction-event-metadata",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-transaction-event-metadata", kind="retrieval_fetch_attempt")
    ]
    event_text_url = "https://www.sec.gov/Archives/edgar/data/78003/000007800323000016/0000078003-23-000016.txt"
    assert event_url in fetch_uris
    assert event_text_url in fetch_uris
    assert unrelated_url not in fetch_uris


def test_finance_evaluator_does_not_accept_filing_year_as_target_fiscal_year():
    evidence = EvidenceItem(
        evidence_id="ev-2023",
        goal_id="goal-period",
        span_id="span-2023",
        document_id="doc-2023",
        source_id="source-2023",
        artifact_id="artifact-2023",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        text=(
            "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
            "fy=2023 period=annual form=10-K filed=2024-02-23 end=2023-12-31 "
            "facts=metric=revenue value=11012000000"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-2023",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="fy=2023 period=annual form=10-K filed=2024-02-23",
        span_start=0,
        span_end=48,
        metadata={},
    )

    decision = EvidenceEvaluator().evaluate(
        goal=SearchGoal(
            goal_id="goal-period",
            query="What was BlackRock's total revenues for fiscal year 2024?",
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
            },
        ),
        evidence=[evidence],
        citations=[citation],
    )

    assert decision.status == "insufficient_evidence"
    assert decision.reason == "finance_target_period_missing"
    assert decision.diagnostics["finance_target_period"]["missing_years"] == ["2024"]


def test_finance_evaluator_rejects_companyfacts_subsidiary_entity_for_parent_company():
    evidence = EvidenceItem(
        evidence_id="ev-blackrock-finance",
        goal_id="goal-blackrock-parent",
        span_id="span-blackrock-finance",
        document_id="doc-blackrock-finance",
        source_id="source-blackrock-finance",
        artifact_id="artifact-blackrock-finance",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        text=(
            "SEC companyfacts official financial statements entityName=BLACKROCK FINANCE, INC. "
            "cik=1364742 source=SEC_XBRL_companyfacts "
            "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
            "cik=1364742 fy=2024 period=annual form=10-K filed=2025-02-23 end=2024-12-31 "
            "facts=metric=revenue concept=Revenues value=11012000000 val=11012000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-blackrock-finance",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="entityName=BLACKROCK FINANCE, INC.",
        span_start=0,
        span_end=36,
        metadata={},
    )

    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="What was BlackRock Inc.'s total revenues for fiscal year 2024?",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )
    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[], citations=[])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_companyfacts_entity_mismatch"
    assert decision.status == "insufficient_evidence"
    assert decision.reason == "insufficient_evidence"


def test_finance_evaluator_accepts_requested_issuer_companyfacts_in_multi_entity_comparison():
    hd_evidence = EvidenceItem(
        evidence_id="ev-hd-companyfacts",
        goal_id="goal-hd-low-dio",
        span_id="span-hd-companyfacts",
        document_id="doc-hd-companyfacts",
        source_id="source-hd-companyfacts",
        artifact_id="artifact-hd-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000354950.json",
        title="SEC companyfacts JSON for CIK 0000354950",
        text=(
            "SEC companyfacts annual financial summary entityName=HOME DEPOT, INC. "
            "cik=0000354950 fy=2024 period=annual form=10-K filed=2025-03-21 end=2025-02-02 "
            "facts=metric=inventory concept=InventoryNet value=23511000000 val=23511000000 unit=USD "
            "metric=cogs concept=CostOfRevenue value=101899000000 val=101899000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    evidence = EvidenceItem(
        evidence_id="ev-low-companyfacts",
        goal_id="goal-hd-low-dio",
        span_id="span-low-companyfacts",
        document_id="doc-low-companyfacts",
        source_id="source-low-companyfacts",
        artifact_id="artifact-low-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000060667.json",
        title="SEC companyfacts JSON for CIK 0000060667",
        text=(
            "SEC companyfacts annual financial summary entityName=LOWE'S COMPANIES, INC. "
            "cik=0000060667 fy=2024 period=annual form=10-K filed=2025-03-21 end=2025-01-31 "
            "facts=metric=inventory concept=InventoryNet value=17412000000 val=17412000000 unit=USD "
            "metric=cogs concept=CostOfRevenue value=58888000000 val=58888000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-low-companyfacts",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="entityName=LOWE'S COMPANIES, INC.",
        span_start=0,
        span_end=36,
        metadata={},
    )
    hd_citation = CitationItem(
        citation_id="cite-hd-companyfacts",
        goal_id=hd_evidence.goal_id,
        evidence_id=hd_evidence.evidence_id,
        artifact_id=hd_evidence.artifact_id,
        uri=hd_evidence.uri,
        title=hd_evidence.title,
        quote="entityName=HOME DEPOT, INC.",
        span_start=0,
        span_end=30,
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="Compare Home Depot and Lowe's fiscal 2024 DIO using SEC 10-K companyfacts.",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[hd_evidence, evidence], citations=[hd_citation, citation])

    assert qualification["accepted"] is True
    assert qualification["target_entity"]["finance_requested_issuer_match"] is True
    assert decision.diagnostics["finance_requested_issuer_coverage"]["satisfied"] is True
    assert decision.diagnostics["finance_requested_issuer_coverage"]["covered"] == ["HD", "LOW"]


def test_finance_evaluator_rejects_unrequested_companyfacts_in_multi_entity_comparison():
    evidence = EvidenceItem(
        evidence_id="ev-costco-companyfacts",
        goal_id="goal-hd-low-dio",
        span_id="span-costco-companyfacts",
        document_id="doc-costco-companyfacts",
        source_id="source-costco-companyfacts",
        artifact_id="artifact-costco-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000909832.json",
        title="SEC companyfacts JSON for CIK 0000909832",
        text=(
            "SEC companyfacts annual financial summary entityName=COSTCO WHOLESALE CORPORATION "
            "cik=0000909832 fy=2024 period=annual form=10-K filed=2024-10-09 end=2024-09-01 "
            "facts=metric=inventory concept=InventoryNet value=18229000000 val=18229000000 unit=USD "
            "metric=cogs concept=CostOfRevenue value=210352000000 val=210352000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="Compare Home Depot and Lowe's fiscal 2024 DIO using SEC 10-K companyfacts.",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_companyfacts_entity_mismatch"
    assert qualification["target_entity"]["reason"] == "companyfacts_entity_not_requested_issuer"


def test_finance_evaluator_requires_specialized_segment_terms_for_segment_queries():
    evidence = EvidenceItem(
        evidence_id="ev-meta-total-revenue",
        goal_id="goal-meta-foa",
        span_id="span-meta-total-revenue",
        document_id="doc-meta-companyfacts",
        source_id="source-meta-companyfacts",
        artifact_id="artifact-meta-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001326801.json",
        title="SEC companyfacts JSON for CIK 0001326801",
        text=(
            "SEC companyfacts annual financial summary entityName=Meta Platforms, Inc. "
            "cik=0001326801 fy=2024 period=annual form=10-K end=2024-12-31 "
            "facts=metric=revenue concept=RevenueFromContractWithCustomerExcludingAssessedTax "
            "value=164501000000 val=164501000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-meta-total-revenue",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="fy=2024 revenue value=164501000000",
        span_start=0,
        span_end=36,
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="What was Meta's Family of Apps segment revenue for fiscal year 2024?",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[evidence], citations=[citation])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"
    assert decision.status == "insufficient_evidence"
    assert decision.diagnostics["finance_specialized_query_coverage"]["satisfied"] is False


def test_finance_evaluator_requires_bridge_terms_for_adjusted_ebitda_bridge_queries():
    evidence = EvidenceItem(
        evidence_id="ev-khc-total-sales",
        goal_id="goal-khc-bridge",
        span_id="span-khc-total-sales",
        document_id="doc-khc-10k",
        source_id="source-khc-10k",
        artifact_id="artifact-khc-10k",
        uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20241228.htm",
        title="Kraft Heinz 2024 Form 10-K",
        text=(
            "Kraft Heinz KHC 2024 Form 10-K. The company reported 2024 net sales of "
            "$26 billion in its consolidated financial statements."
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-khc-total-sales",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="2024 net sales of $26 billion",
        span_start=0,
        span_end=len(evidence.text),
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="Kraft Heinz KHC adjusted EBITDA bridge non-GAAP reconciliation from public filings",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[evidence], citations=[citation])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"
    assert decision.status == "insufficient_evidence"
    assert decision.diagnostics["finance_specialized_query_coverage"]["satisfied"] is False


def test_finance_evaluator_requires_addback_terms_for_addback_trend_queries():
    evidence = EvidenceItem(
        evidence_id="ev-wsc-ebitda-margin",
        goal_id="goal-wsc-addback-trend",
        span_id="span-wsc-ebitda-margin",
        document_id="doc-wsc-market-stats",
        source_id="source-wsc-market-stats",
        artifact_id="artifact-wsc-market-stats",
        uri="https://stockanalysis.com/stocks/wsc/statistics/",
        title="WillScot Holdings market statistics",
        text=(
            "WillScot Holdings market statistics. EBITDA Margin was 25.94%. "
            "Dividend Per Share was $0.28."
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-wsc-ebitda-margin",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=evidence.text,
        span_start=0,
        span_end=len(evidence.text),
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="WillScot WSC adjusted EBITDA add-back trend from public filings",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[evidence], citations=[citation])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"
    assert decision.status == "insufficient_evidence"
    coverage = decision.diagnostics["finance_specialized_query_coverage"]
    assert coverage["satisfied"] is False
    assert coverage["addback_required_terms"]


def test_finance_evaluator_requires_transaction_terms_for_transaction_multiple_queries():
    evidence = EvidenceItem(
        evidence_id="ev-sgen-stock-stats",
        goal_id="goal-pfe-sgen-transaction",
        span_id="span-sgen-stock-stats",
        document_id="doc-sgen-stock-stats",
        source_id="source-sgen-stock-stats",
        artifact_id="artifact-sgen-stock-stats",
        uri="https://stockanalysis.com/stocks/sgen/statistics/",
        title="StockAnalysis statistics for SGEN",
        text=(
            "Seagen stock statistics. Market cap was $146.48B, cash was $13.08B, "
            "debt was $64.73B, and revenue was $7.49B."
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-sgen-stock-stats",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote=evidence.text,
        span_start=0,
        span_end=len(evidence.text),
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="Pfizer Seagen acquisition transaction EV revenue multiple using public deal disclosures and 8-K filing evidence",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[evidence], citations=[citation])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"
    assert decision.status == "insufficient_evidence"
    assert decision.diagnostics["finance_specialized_query_coverage"]["satisfied"] is False


def test_finance_evaluator_uses_root_goal_for_transaction_specialized_terms():
    evidence = EvidenceItem(
        evidence_id="ev-sgen-stock-stats-root",
        goal_id="goal-pfe-sgen-root",
        span_id="span-sgen-stock-stats-root",
        document_id="doc-sgen-stock-stats-root",
        source_id="source-sgen-stock-stats-root",
        artifact_id="artifact-sgen-stock-stats-root",
        uri="https://stockanalysis.com/stocks/sgen/statistics/",
        title="StockAnalysis statistics for SGEN",
        text="Seagen stock statistics. Enterprise value was $198.13B and revenue was $7.49B.",
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="Pfizer Seagen acquisition enterprise value revenue 2023",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_mission": {
                "root_goal": "For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple using public deal disclosures and filing evidence."
            },
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"


def _evidence_candidate(
    *,
    evidence_id: str,
    uri: str,
    title: str,
    text: str,
    source_family: str,
    authority_score: float,
    facets: list[str],
) -> EvidenceCandidate:
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        goal_id="goal-valuation-compaction",
        span_id=f"span-{evidence_id}",
        document_id=f"doc-{evidence_id}",
        source_id=f"source-{evidence_id}",
        artifact_id=f"artifact-{evidence_id}",
        uri=uri,
        title=title,
        text=text,
        score=0.9,
        payload_hash=f"hash-{evidence_id}",
        diagnostics={
            "source_assessment": {
                "source_family": source_family,
                "authority_score": authority_score,
            },
            "qualification": {
                "covered_profile_facets": facets,
                "profile_numeric_fact_present": True,
            },
        },
    )
    span = ExtractedSpan(
        span_id=evidence.span_id,
        goal_id=evidence.goal_id,
        document_id=evidence.document_id,
        source_id=evidence.source_id,
        text=text,
        start_offset=0,
        end_offset=len(text),
        score=0.9,
    )
    return EvidenceCandidate(evidence=evidence, span=span)
