from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, finance_fundamentals_profile
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.rank import plan_queries, rank_sources


def test_phase82_finance_profile_prefers_primary_filing_sources_over_generic_web() -> None:
    profile = finance_fundamentals_profile()
    weak = _source(
        "src-blog",
        "https://example.com/aapl-analysis",
        "AAPL Apple revenue risk analysis 10-K margin growth",
        "AAPL Apple revenue risk analysis 10-K margin growth",
    )
    filing = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "Apple annual report.",
    )

    ranked = rank_sources(
        SearchGoal(goal_id="goal-rank-finance", query="AAPL Apple revenue risk analysis 10-K margin growth"),
        [weak, filing],
        research_profile=profile,
    )

    assert ranked[0].source_id == "src-sec"
    assert ranked[0].metadata["source_assessment"]["source_family"] == "regulatory_filing"
    assert ranked[0].metadata["source_assessment"]["usable_as_primary"] is True
    assert "authority:primary" in ranked[0].reasons


def test_phase82_finance_profile_expands_queries_toward_primary_sources() -> None:
    queries = plan_queries(
        SearchGoal(
            goal_id="goal-finance-query-plan",
            query="AAPL revenue margin",
            max_queries=3,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        research_profile=finance_fundamentals_profile(),
    )

    assert queries[0] == "AAPL revenue margin"
    assert any("10-K" in query or "10-Q" in query for query in queries[1:])
    assert any("SEC EDGAR" in query or "investor relations" in query for query in queries[1:])


def test_phase82_finance_profile_ranks_structured_financial_sources_before_lookup_pages() -> None:
    profile = finance_fundamentals_profile()
    goal = SearchGoal(
        goal_id="goal-sec-ranking",
        query="AAPL revenue net income SEC companyfacts",
        metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )
    directory = _source(
        "sec-directory",
        "https://www.sec.gov/files/company_tickers_exchange.json",
        "SEC company ticker and CIK directory",
        "Official SEC ticker and CIK mapping lookup for AAPL.",
        metadata={"source_family": "structured_regulatory_data", "source_kind": "sec_ticker_cik_directory"},
    )
    companyfacts = _source(
        "sec-companyfacts",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "SEC companyfacts JSON for CIK 0000320193",
        "Official SEC XBRL companyfacts JSON for reported fundamentals.",
        metadata={"source_family": "structured_regulatory_data", "source_kind": "sec_companyfacts_json"},
    )
    search_page = _source(
        "sec-search",
        "https://www.sec.gov/edgar/search/#/q=AAPL",
        "SEC EDGAR search for AAPL",
        "Official SEC filing search page for AAPL.",
        metadata={"source_family": "regulatory_filing", "source_kind": "sec_edgar_search"},
    )

    ranked = rank_sources(goal, [directory, search_page, companyfacts], research_profile=profile)

    assert ranked[0].source_id == "sec-companyfacts"
    assert ranked[-1].source_id in {"sec-directory", "sec-search"}


def test_phase82_finance_profile_prioritizes_sec_ticker_browse_over_generic_sec_roots() -> None:
    profile = finance_fundamentals_profile()
    goal = SearchGoal(
        goal_id="goal-sec-ticker-browse",
        query="TJX Q4 fiscal 2025 pre-tax margin 10-K earnings",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "preferred_source_families": ["regulatory_filing", "company_ir"],
        },
    )
    browse_ticker = _source(
        "sec-browse-ticker",
        "https://www.sec.gov/cgi-bin/browse-edgar?CIK=TJX&owner=exclude&action=getcompany&count=100",
        "SEC EDGAR issuer browse page for ticker TJX",
        "Official SEC company filing browse page resolved by ticker TJX; use it to reach issuer-specific 10-K, 10-Q, and 8-K filings.",
        metadata={"source_family": "regulatory_filing", "source_kind": "sec_edgar_browse_ticker", "ticker": "TJX"},
    )
    generic_search = _source(
        "sec-search-root",
        "https://www.sec.gov/edgar/search/",
        "SEC EDGAR search",
        "Official SEC EDGAR filing search page.",
        metadata={"source_family": "regulatory_filing", "source_kind": "source_directory_entry"},
    )
    generic_archive = _source(
        "sec-archives-root",
        "https://www.sec.gov/Archives/edgar/data/",
        "SEC Archives root",
        "Official SEC Archives root directory.",
        metadata={"source_family": "regulatory_filing", "source_kind": "source_directory_entry"},
    )

    ranked = rank_sources(goal, [generic_search, generic_archive, browse_ticker], research_profile=profile)

    assert ranked[0].source_id == "sec-browse-ticker"
    assert ranked[0].metadata["source_kind"] == "sec_edgar_browse_ticker"


def test_phase82_finance_profile_multi_query_can_recover_primary_source() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    targeted_query = "AAPL revenue annual report 10-K 10-Q filing"
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL revenue": [
                    _source(
                        "src-generic",
                        "https://example.com/aapl-revenue",
                        "AAPL revenue summary",
                        "A third-party summary repeats Apple revenue.",
                    )
                ],
                targeted_query: [
                _source(
                    "src-sec",
                    "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
                    "Apple Form 10-K",
                    "AAPL revenue from annual report was USD 391035 million.",
                )
            ],
        }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.com/aapl-revenue": "AAPL revenue third-party summary.",
                "https://www.sec.gov/Archives/edgar/data/320193/filing.htm": "AAPL revenue from annual report was USD 391035 million.",
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-multi-query",
            query="AAPL revenue",
            max_queries=3,
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-multi-query",
        run_id="run-1",
    )

    plan = journal.records(task_id="task-finance-multi-query", kind="retrieval_query_plan")[0].data
    assert report.status == "sufficient"
    assert plan["queries"][1] == targeted_query
    assert plan["diagnostics"]["query_strategy"]["strategy_id"] == "finance_primary_source_expansion"
    assert len(journal.records(task_id="task-finance-multi-query", kind="retrieval_search_attempt")) == 3
    assert report.diagnostics["source_authority"]["primary_source_count"] == 1


def test_phase82_finance_retrieval_rejects_generic_web_as_final_primary_evidence() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 10-K revenue": [
                    _source(
                        "src-generic",
                        "https://example.com/aapl",
                        "AAPL 2024 10-K revenue",
                        "A third-party summary repeats Apple revenue.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({"https://example.com/aapl": "AAPL 2024 10-K revenue was discussed here."}),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-weak",
            query="AAPL 2024 10-K revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-weak",
        run_id="run-1",
    )

    assert report.status == "insufficient_evidence"
    assert report.diagnostics["reason"] == "no_primary_source_for_research_profile"
    assert report.diagnostics["source_quality"]["authority_sufficient"] is False
    assert report.diagnostics["rejected_evidence_count"] == 1
    assert not journal.records(task_id="task-finance-weak", kind="retrieval_evidence")
    assert not journal.records(task_id="task-finance-weak", kind="retrieval_citation")
    assert report.diagnostics["source_authority"]["primary_source_count"] == 0
    assessment = journal.records(task_id="task-finance-weak", kind="retrieval_source_assessment")[0].data
    assert assessment["assessments"][0]["authority_level"] == "weak"
    assert assessment["assessments"][0]["warnings"] == ["not_primary_source_for_profile", "weak_source_family"]


def test_phase82_finance_retrieval_with_no_sources_keeps_plain_insufficient_evidence_reason() -> None:
    journal = JournalStore.in_memory()
    report = RetrievalOperator(
        search_provider=FakeSearchProvider({"missing": []}),
        fetch_provider=FakeFetchProvider({}),
    ).run(
        SearchGoal(
            goal_id="goal-finance-empty",
            query="missing",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-finance-empty",
        run_id="run-1",
    )

    assert report.status == "insufficient_evidence"
    assert report.diagnostics["reason"] == "insufficient_evidence"
    assert report.diagnostics["source_authority"]["primary_source_count"] == 0


def test_phase82_finance_retrieval_accepts_primary_filing_evidence_and_journals_assessment() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 10-K revenue": [
                    _source(
                        "src-sec",
                        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
                        "Apple Form 10-K",
                        "AAPL 2024 10-K revenue from annual report.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/Archives/edgar/data/320193/filing.htm": (
                    "AAPL 2024 Form 10-K revenue was $391.0 billion in the annual report."
                )
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-sec",
            query="AAPL 2024 10-K revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-sec",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert report.diagnostics["source_authority"]["primary_source_count"] == 1
    assert report.diagnostics["network_access"] is False
    assert report.diagnostics["budget"]["max_spans_per_document"] == 1
    plan = journal.records(task_id="task-finance-sec", kind="retrieval_query_plan")[0].data
    assert plan["diagnostics"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert plan["diagnostics"]["budget"]["max_fetches"] == 3
    evidence = journal.records(task_id="task-finance-sec", kind="retrieval_evidence")[0].data
    assert evidence["diagnostics"]["source_assessment"]["source_family"] == "regulatory_filing"
    assert evidence["diagnostics"]["source_assessment"]["usable_as_primary"] is True
    kinds = [record.kind for record in journal.records(task_id="task-finance-sec")]
    assert "retrieval_source_assessment" in kinds
    assert kinds.index("retrieval_source_assessment") < kinds.index("retrieval_rank_sources")


def test_phase82_finance_retrieval_accepts_primary_filing_net_sales_metric() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 Form 10-K primary filing document": [
                    _source(
                        "src-sec-primary-filing",
                        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
                        "Apple 2024 Form 10-K",
                        "Primary SEC filing document.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/Archives/edgar/data/320193/filing.htm": (
                    "Apple 2024 Form 10-K primary filing document reports net sales of $391.0 billion in the SEC filing."
                )
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-net-sales",
            query="AAPL 2024 Form 10-K primary filing document",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-net-sales",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert report.diagnostics["rejected_evidence_count"] == 0
    evidence = journal.records(task_id="task-finance-net-sales", kind="retrieval_evidence")[0].data
    qualification = evidence["diagnostics"]["qualification"]
    assert qualification["finance_numeric_fact_present"] is True
    assert "financial_metric" in qualification["covered_finance_facets"]


def test_phase82_finance_retrieval_rejects_primary_domain_without_financial_facets() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Apple Inc financial statements revenue net income": [
                    _source(
                        "src-sec-product-noise",
                        "https://www.sec.gov/Archives/edgar/data/320193/product-noise.htm",
                        "Apple product overview",
                        "Apple device and iCloud product page with no financial metrics.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/Archives/edgar/data/320193/product-noise.htm": (
                    "Apple iPhone, iCloud, and device services overview. "
                    "This text contains product marketing details, not company financial metrics."
                )
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-product-noise",
            query="Apple Inc financial statements revenue net income",
            max_spans_per_document=2,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "fundamentals",
            },
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-product-noise",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-finance-product-noise", kind="retrieval_evaluation_decision")[-1].data
    diagnostics = evaluation["diagnostics"]
    assert report.status == "insufficient_evidence"
    assert evaluation["reason"] == "insufficient_evidence"
    assert report.diagnostics["rejected_evidence_count"] == 1
    assert not journal.records(task_id="task-finance-product-noise", kind="retrieval_evidence")
    assert not journal.records(task_id="task-finance-product-noise", kind="retrieval_citation")
    assert "revenue" in diagnostics["missing_finance_facets"]
    assert "net_income" in diagnostics["missing_finance_facets"]
    assert "numeric_financial_fact" in diagnostics["missing_finance_facets"]
    source_assessment = journal.records(task_id="task-finance-product-noise", kind="retrieval_source_assessment")[0].data
    assert source_assessment["diagnostics"]["primary_source_count"] == 1


def test_phase82_finance_retrieval_rejects_sec_identity_directory_as_financial_fact() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Apple Inc 10-K revenue SEC CIK": [
                    _source(
                        "src-sec-directory",
                        "https://www.sec.gov/files/company_tickers_exchange.json",
                        "SEC ticker, exchange, company, and CIK directory",
                        "Apple Inc ticker AAPL CIK 0000320193 Nasdaq.",
                        metadata={"source_family": "structured_regulatory_data"},
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/files/company_tickers_exchange.json": (
                    "Apple Inc AAPL Nasdaq CIK 0000320193. "
                    "The directory maps ticker symbols, exchanges, company names, and CIK identifiers. "
                    "It does not report revenue, net income, cash flow, margins, or balance sheet values."
                )
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-sec-directory",
            query="Apple Inc 10-K revenue SEC CIK",
            max_spans_per_document=2,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "fundamentals",
            },
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-sec-directory",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-finance-sec-directory", kind="retrieval_evaluation_decision")[-1].data
    diagnostics = evaluation["diagnostics"]
    assert report.status == "insufficient_evidence"
    assert evaluation["reason"] == "insufficient_evidence"
    assert report.diagnostics["rejected_evidence_count"] == 1
    assert not journal.records(task_id="task-finance-sec-directory", kind="retrieval_evidence")
    assert not journal.records(task_id="task-finance-sec-directory", kind="retrieval_citation")
    assert "numeric_financial_fact" in diagnostics["missing_finance_facets"]
    assert diagnostics["finance_numeric_fact_present"] is False


def test_phase82_finance_retrieval_rejects_sec_search_page_for_financial_results_without_numeric_fact() -> None:
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "APPLE INC latest 10-K annual report SEC filing financial results": [
                    _source(
                        "src-sec-search",
                        "https://www.sec.gov/edgar/search/#/q=APPLE",
                        "SEC EDGAR search for APPLE",
                        "Official SEC filing search page for APPLE.",
                        metadata={"source_family": "regulatory_filing", "source_kind": "sec_edgar_search"},
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.sec.gov/edgar/search/#/q=APPLE": (
                    "SEC EDGAR search page for APPLE INC latest 10-K annual report financial results. "
                    "This page lists matching filings but does not quote any revenue, net income, or other reported values."
                )
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-sec-search-no-values",
            query="APPLE INC latest 10-K annual report SEC filing financial results",
            max_spans_per_document=4,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-finance-sec-search-no-values",
        run_id="run-1",
    )

    evaluation = journal.records(task_id="task-finance-sec-search-no-values", kind="retrieval_evaluation_decision")[-1].data
    assert report.status == "insufficient_evidence"
    assert report.diagnostics["rejected_evidence_count"] >= 1
    assert not journal.records(task_id="task-finance-sec-search-no-values", kind="retrieval_citation")
    assert "numeric_financial_fact" in evaluation["diagnostics"]["missing_finance_facets"]


def test_phase82_source_family_can_be_declared_by_provider_metadata() -> None:
    assessment = assess_search_source(
        _source(
            "src-ir",
            "https://assets.example.test/report.pdf",
            "Investor presentation",
            "Quarterly investor deck",
            metadata={"source_family": "company_ir"},
        ),
        profile=finance_fundamentals_profile(),
    )

    assert assessment.source_family == "company_ir"
    assert assessment.usable_as_primary is True
    assert assessment.reasons[0] == "metadata_source_family"


def test_phase82_finance_profile_treats_china_exchange_disclosure_as_primary() -> None:
    assessment = assess_search_source(
        _source(
            "src-cninfo",
            "https://static.cninfo.com.cn/finalpage/2025-04-01/annual-report.pdf",
            "年度报告",
            "公司年度报告披露收入与利润。",
        ),
        profile=finance_fundamentals_profile(),
    )

    assert assessment.source_family == "exchange_filing"
    assert assessment.authority_level == "primary"
    assert assessment.usable_as_primary is True
    assert assessment.reasons[0] == "recognized_exchange_domain"


def test_phase82_source_policy_matches_known_finance_subdomains() -> None:
    news = assess_search_source(
        _source(
            "src-reuters-subdomain",
            "https://markets.reuters.com/world/us/aapl",
            "Reuters Apple market report",
            "Reuters report.",
        ),
        profile=finance_fundamentals_profile(),
    )
    market_data = assess_search_source(
        _source(
            "src-eastmoney-data",
            "https://quote.eastmoney.com/us/AAPL.html",
            "AAPL market data",
            "AAPL market data.",
        ),
        profile=finance_fundamentals_profile(),
    )

    assert news.source_family == "reputable_news"
    assert news.authority_level == "secondary"
    assert market_data.source_family == "market_data_provider"
    assert market_data.authority_level == "secondary"

    marketwatch = assess_search_source(
        _source(
            "src-marketwatch-data",
            "https://www.marketwatch.com/investing/stock/aapl",
            "AAPL quote",
            "MarketWatch quote page.",
        ),
        profile=finance_fundamentals_profile(),
    )
    cnbc = assess_search_source(
        _source(
            "src-cnbc-news",
            "https://www.cnbc.com/search/?query=Apple",
            "CNBC Apple news",
            "CNBC market news search.",
        ),
        profile=finance_fundamentals_profile(),
    )

    assert marketwatch.source_family == "market_data_provider"
    assert marketwatch.authority_level == "secondary"
    assert cnbc.source_family == "reputable_news"
    assert cnbc.authority_level == "secondary"


def test_phase82_source_policy_matches_global_primary_finance_sources() -> None:
    profile = finance_fundamentals_profile()
    samples = [
        (
            "https://find-and-update.company-information.service.gov.uk/company/00000006/filing-history",
            "UK Companies House accounts",
            "regulatory_filing",
        ),
        (
            "https://www.sedarplus.ca/landingpage/",
            "SEDAR+ issuer filings",
            "regulatory_filing",
        ),
        (
            "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
            "ASX company announcements",
            "exchange_filing",
        ),
        (
            "https://disclosure2.edinet-fsa.go.jp/",
            "EDINET securities report",
            "regulatory_filing",
        ),
        (
            "https://www.sgx.com/securities/company-announcements",
            "SGX company announcements",
            "exchange_filing",
        ),
        (
            "https://data.worldbank.org/indicator/NY.GDP.MKTP.CD",
            "World Bank GDP indicator",
            "government_statistic",
        ),
        (
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            "SEC companyfacts JSON",
            "structured_regulatory_data",
        ),
        (
            "https://data.ecb.europa.eu/data/datasets/EXR",
            "ECB exchange-rate dataset",
            "central_bank_statistic",
        ),
        (
            "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics",
            "US Treasury yield curve",
            "treasury_data",
        ),
        (
            "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf",
            "iShares ETF holdings and prospectus",
            "fund_disclosure",
        ),
    ]

    for uri, title, expected_family in samples:
        assessment = assess_search_source(
            _source("src-global", uri, title, "official finance source"),
            profile=profile,
        )
        assert assessment.source_family == expected_family
        assert assessment.authority_level == "primary"
        assert assessment.usable_as_primary is True


def test_phase82_source_policy_classifies_secondary_finance_research_databases() -> None:
    profile = finance_fundamentals_profile()
    samples = [
        (
            "https://www.fitchratings.com/search?query=Apple",
            "Fitch Apple rating outlook",
            "credit_rating_agency",
        ),
        (
            "https://seekingalpha.com/search?q=Apple%20transcript",
            "Apple earnings call transcript",
            "earnings_transcript",
        ),
    ]

    for uri, title, expected_family in samples:
        assessment = assess_search_source(
            _source("src-secondary", uri, title, "secondary finance research database"),
            profile=profile,
        )
        assert assessment.source_family == expected_family
        assert assessment.authority_level == "secondary"
        assert assessment.usable_as_primary is False


def test_phase82_model_taskgraph_capability_args_reach_retrieval_without_agent_domain_logic() -> None:
    goal = "AAPL 2024 10-K revenue"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieval_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "retrieval_research",
                        "text": goal,
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}
                                }
                            }
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                goal: [
                    _source(
                        "src-generic",
                        "https://example.com/aapl",
                        "AAPL 2024 10-K revenue",
                        "A third-party summary repeats Apple revenue.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({"https://example.com/aapl": "AAPL 2024 10-K revenue was discussed."}),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(goal, mode="auto", semantic_mode="model")

    assert result.status == "failed"
    action = journal.records(task_id=result.task_id, kind="action")[0].data
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[0].data
    assert report["status"] == "insufficient_evidence"
    assert report["diagnostics"]["reason"] == "no_primary_source_for_research_profile"
    assert report["diagnostics"]["source_quality"]["authority_sufficient"] is False
    assert report["diagnostics"]["rejected_evidence_count"] == 1


def _source(
    source_id: str,
    uri: str,
    title: str,
    snippet: str,
    *,
    metadata: dict | None = None,
) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
        metadata=dict(metadata or {}),
    )
