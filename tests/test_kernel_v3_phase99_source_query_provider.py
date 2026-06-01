from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.research.contracts import ResearchSourceEntry
from kernel_v3.retrieval import (
    FakeFetchProvider,
    QueryPlan,
    ResearchSourceQuerySearchProvider,
    RetrievalOperator,
    SearchGoal,
)
import kernel_v3.retrieval.source_query_provider as source_query_module


def test_phase99_source_query_provider_expands_official_companies_house_search_url():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "Acme plc Companies House accounts filing history",
        goal=SearchGoal(
            goal_id="goal-source-query-ch",
            query="Acme plc Companies House accounts filing history",
            max_sources=10,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "company": "Acme plc",
            },
        ),
        plan=_plan(),
    )

    urls = [source.uri for source in sources]
    assert "https://find-and-update.company-information.service.gov.uk/search?q=Acme%20plc" in urls
    companies_house = next(source for source in sources if "company-information.service.gov.uk/search" in source.uri)
    assert companies_house.provider == "research_source_query_search"
    assert companies_house.metadata["source_family"] == "regulatory_filing"
    assert companies_house.metadata["authority_level"] == "primary"
    assert companies_house.metadata["source_kind"] == "official_search"
    assert provider.search_diagnostics()["source_count"] >= 1


def test_phase99_source_query_provider_is_profile_gated_and_host_validated():
    provider = ResearchSourceQuerySearchProvider()

    no_profile = provider.search(
        "Acme plc Companies House accounts",
        goal=SearchGoal(goal_id="goal-no-profile", query="Acme plc Companies House accounts"),
        plan=_plan(),
    )

    assert no_profile == []
    assert provider.search_diagnostics()["reason"] == "no_research_profile"


def test_phase99_source_query_provider_rejects_template_hosts_outside_entry_allowlist(monkeypatch):
    entry = ResearchSourceEntry(
        source_id="finance-template-safety",
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        title="Official source",
        source_family="regulatory_filing",
        authority_level="primary",
        base_url="https://official.example.test/",
        allowed_hosts=["official.example.test"],
        use_cases=["safety"],
        required_identifiers=["query"],
        query_hints=["official {query}"],
        crawl_notes=["test"],
        metadata={
            "query_url_templates": [
                {
                    "template_id": "bad-host",
                    "template": "https://attacker.example.test/search?q={query_url}",
                    "title": "Bad host",
                    "required_values": ["query"],
                }
            ]
        },
    )
    monkeypatch.setattr(source_query_module, "source_directory_for_profile", lambda profile_id: [entry])

    sources = source_query_module.ResearchSourceQuerySearchProvider().search(
        "official query",
        goal=SearchGoal(
            goal_id="goal-source-query-safety",
            query="official query",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan(),
    )

    assert sources == []


def test_phase99_source_query_provider_expands_macro_source_queries():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "FRED CPI inflation macro series",
        goal=SearchGoal(
            goal_id="goal-source-query-macro",
            query="FRED CPI inflation macro series",
            max_sources=10,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "metric": "CPI",
            },
        ),
        plan=_plan(),
    )

    urls = [source.uri for source in sources]
    assert "https://fred.stlouisfed.org/searchresults/?search_type=series&search=CPI" in urls
    fred = next(source for source in sources if source.uri.startswith("https://fred.stlouisfed.org/searchresults/"))
    assert fred.metadata["source_family"] == "government_statistic"
    assert fred.metadata["authority_level"] == "primary"


def test_phase99_source_query_provider_expands_common_market_data_portals():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "AAPL quote market data price market cap Nasdaq MarketWatch Yahoo",
        goal=SearchGoal(
            goal_id="goal-source-query-market-data",
            query="AAPL quote market data price market cap Nasdaq MarketWatch Yahoo",
            max_sources=20,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "ticker": "AAPL",
            },
        ),
        plan=_plan(),
    )

    urls = {source.uri for source in sources}
    assert "https://finance.yahoo.com/quote/AAPL" in urls
    assert "https://finance.yahoo.com/lookup?s=AAPL" in urls
    assert "https://www.nasdaq.com/market-activity/stocks/aapl" in urls
    assert "https://www.marketwatch.com/investing/stock/aapl" in urls
    market_sources = [source for source in sources if source.metadata["source_family"] == "market_data_provider"]
    assert market_sources
    assert all(source.metadata["authority_level"] == "secondary" for source in market_sources)


def test_phase99_source_query_provider_expands_reputable_market_news_sources():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "AAPL latest market news Reuters CNBC Bloomberg FT earnings",
        goal=SearchGoal(
            goal_id="goal-source-query-market-news",
            query="AAPL latest market news Reuters CNBC Bloomberg FT earnings",
            max_sources=20,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "company": "Apple",
            },
        ),
        plan=_plan(),
    )

    urls = {source.uri for source in sources}
    assert "https://www.reuters.com/site-search/?query=Apple" in urls
    assert "https://www.bloomberg.com/search?query=Apple" in urls
    assert "https://www.ft.com/search?q=Apple" in urls
    assert "https://www.cnbc.com/search/?query=Apple" in urls
    news_sources = [source for source in sources if source.metadata["source_family"] == "reputable_news"]
    assert news_sources
    assert all(source.metadata["authority_level"] == "secondary" for source in news_sources)


def test_phase99_source_query_provider_expands_rate_fund_transcript_and_credit_sources():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "SPY ETF fund prospectus N-PORT holdings Federal Reserve rate Treasury yield Apple transcript Fitch credit rating",
        goal=SearchGoal(
            goal_id="goal-source-query-expanded-finance-databases",
            query=(
                "SPY ETF fund prospectus N-PORT holdings Federal Reserve rate "
                "Treasury yield Apple transcript Fitch credit rating"
            ),
            max_sources=40,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "ticker": "SPY",
                "company": "Apple",
                "metric": "policy rate",
            },
        ),
        plan=_plan(),
    )

    urls = {source.uri for source in sources}
    assert "https://www.federalreserve.gov/searchresults.htm?searchtext=policy%20rate" in urls
    assert "https://data.ecb.europa.eu/search-results?searchTerm=policy%20rate" in urls
    assert "https://home.treasury.gov/search?keys=policy%20rate" in urls
    assert "https://fiscaldata.treasury.gov/datasets/?search=policy%20rate" in urls
    assert "https://www.sec.gov/edgar/search/#/q=SPY" in urls
    assert "https://seekingalpha.com/search?q=Apple%20transcript" in urls
    assert "https://www.fitchratings.com/search?query=Apple" in urls
    by_family = {}
    for source in sources:
        by_family.setdefault(source.metadata["source_family"], []).append(source)
    assert by_family["central_bank_statistic"][0].metadata["authority_level"] == "primary"
    assert by_family["treasury_data"][0].metadata["authority_level"] == "primary"
    assert by_family["fund_disclosure"][0].metadata["authority_level"] == "primary"
    assert by_family["earnings_transcript"][0].metadata["authority_level"] == "secondary"
    assert by_family["credit_rating_agency"][0].metadata["authority_level"] == "secondary"


def test_phase99_source_query_provider_expands_exchange_official_query_urls():
    provider = ResearchSourceQuerySearchProvider()

    sources = provider.search(
        "ASX HKEX SGX EDINET announcements annual securities report financial results",
        goal=SearchGoal(
            goal_id="goal-source-query-exchanges",
            query="ASX HKEX SGX EDINET announcements annual securities report financial results",
            max_sources=20,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "asx_code": "BHP",
                "hkex_code": "700",
                "sgx_code": "D05",
                "edinet_code": "E12345",
            },
        ),
        plan=_plan(),
    )

    urls = {source.uri for source in sources}
    assert (
        "https://www.asx.com.au/asx/v2/statistics/announcements.do?"
        "asxCode=BHP&by=asxCode&timeframe=D&period=M6"
    ) in urls
    assert "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN&market=SEHK&category=0" in urls
    assert "https://www.sgx.com/securities/company-announcements" in urls
    assert "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx" in urls
    assert all(source.metadata["authority_level"] == "primary" for source in sources)


def test_phase99_source_query_provider_expands_cninfo_without_cross_market_false_positive():
    provider = ResearchSourceQuerySearchProvider()

    cninfo_sources = provider.search(
        "CNINFO 000001 年报 公告",
        goal=SearchGoal(
            goal_id="goal-source-query-cninfo",
            query="CNINFO 000001 年报 公告",
            max_sources=10,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "stock_code": "000001",
            },
        ),
        plan=_plan(),
    )
    asx_sources = provider.search(
        "ASX:BHP annual report announcement",
        goal=SearchGoal(
            goal_id="goal-source-query-asx-only",
            query="ASX:BHP annual report announcement",
            max_sources=10,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            },
        ),
        plan=_plan(),
    )

    assert "https://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyWord=000001" in [
        source.uri for source in cninfo_sources
    ]
    assert all("cninfo.com.cn" not in source.uri for source in asx_sources)


def test_phase99_agent_can_use_source_query_provider_for_multi_step_finance_research():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "text": "Acme plc Companies House accounts filing history",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "Acme plc Companies House accounts filing history",
                                    "metadata": {"company": "Acme plc"},
                                }
                            }
                        },
                    },
                    {
                        "kind": "finance_fundamentals",
                        "text": "FRED CPI inflation macro series",
                        "sequence_index": 2,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "FRED CPI inflation macro series",
                                    "metadata": {"metric": "CPI"},
                                }
                            }
                        },
                    },
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
        search_provider=ResearchSourceQuerySearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                "https://find-and-update.company-information.service.gov.uk/search?q=Acme%20plc": (
                    "Acme plc Companies House accounts filing history includes official accounts and revenue filings."
                ),
                "https://fred.stlouisfed.org/searchresults/?search_type=series&search=CPI": (
                    "FRED CPI inflation macro series provides official CPI context for rates and macro analysis."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run("Research Acme filings and CPI macro context", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run"]
    assert any(
        source["provider"] == "research_source_query_search"
        for record in journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
        for source in record.data["sources"]
    )
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    assert len(result.final_answer["citation_refs"]) == 2


def test_phase99_agent_can_use_exchange_query_provider_for_multi_step_finance_research():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "text": "ASX BHP annual report announcement",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "ASX BHP annual report announcement",
                                    "metadata": {"asx_code": "BHP"},
                                }
                            }
                        },
                    },
                    {
                        "kind": "finance_fundamentals",
                        "text": "HKEX 00700 annual report announcement",
                        "sequence_index": 2,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "HKEX 00700 annual report announcement",
                                    "metadata": {"hkex_code": "00700"},
                                }
                            }
                        },
                    },
                    {
                        "kind": "finance_fundamentals",
                        "text": "SGX D05 financial results announcement",
                        "sequence_index": 3,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "SGX D05 financial results announcement",
                                    "metadata": {"sgx_code": "D05"},
                                }
                            }
                        },
                    },
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    asx_url = (
        "https://www.asx.com.au/asx/v2/statistics/announcements.do?"
        "asxCode=BHP&by=asxCode&timeframe=D&period=M6"
    )
    hkex_url = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=EN&market=SEHK&category=0"
    sgx_url = "https://www.sgx.com/securities/company-announcements"
    operator = RetrievalOperator(
        search_provider=ResearchSourceQuerySearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                asx_url: "ASX BHP annual report announcement includes primary exchange filing evidence.",
                hkex_url: "HKEX 00700 annual report announcement includes primary exchange filing evidence.",
                sgx_url: "SGX D05 financial results announcement includes primary exchange filing evidence.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run("Research ASX, HKEX, and SGX issuer announcements", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run", "retrieval.run"]
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "continue", "final_answer"]
    assert len(result.final_answer["citation_refs"]) == 3


def test_phase99_agent_finance_market_news_and_data_use_source_directory_queries():
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "market_news_and_data_research",
                "suggested_mode": "retrieval_answer",
                "compound": True,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "market_data_research",
                        "text": "AAPL quote market data price market cap",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.market_data"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "AAPL quote market data price market cap",
                                    "metadata": {"ticker": "AAPL"},
                                }
                            }
                        },
                    },
                    {
                        "kind": "market_news_research",
                        "text": "Apple latest Reuters CNBC market news earnings",
                        "sequence_index": 2,
                        "required_capabilities": ["finance.market_news"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "Apple latest Reuters CNBC market news earnings",
                                    "metadata": {"company": "Apple"},
                                }
                            }
                        },
                    },
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            }
        },
        journal=journal,
    )
    yahoo_url = "https://finance.yahoo.com/quote/AAPL"
    reuters_url = "https://www.reuters.com/site-search/?query=Apple"
    operator = RetrievalOperator(
        search_provider=ResearchSourceQuerySearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                yahoo_url: "AAPL quote market data price and market cap secondary context.",
                reuters_url: "Apple latest Reuters market news and earnings chronology secondary context.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run("Research AAPL market data and current news", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run"]
    assert all(
        record.data["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
        for record in actions
    )
    fetched = {
        record.data["uri"]
        for record in journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")
        if record.data["status"] == "ok"
    }
    assert {yahoo_url, reuters_url}.issubset(fetched)
    assert len(result.final_answer["citation_refs"]) == 2


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-source-query-test",
        goal_id="goal-source-query-test",
        queries=["test"],
        max_sources=10,
        max_fetches=4,
    )
