import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    BoundedCrawlSearchProvider,
    DirectUrlSearchProvider,
    FakeFetchProvider,
    HttpFetchProvider,
    HttpTransportResponse,
    LiveRetrievalConfig,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SourceDirectorySearchProvider,
    provider_capability,
)
from kernel_v3.retrieval.rank import rank_sources


def test_phase95_direct_url_search_provider_extracts_safe_urls_without_network() -> None:
    provider = DirectUrlSearchProvider()

    sources = provider.search(
        "read https://docs.example.com/aapl, and ignore https://docs.example.com/leak?access_token=secret-token-1234567890",
        goal=SearchGoal(
            goal_id="goal-direct-url",
            query="direct url",
            max_sources=5,
            metadata={"source_urls": ["https://ir.example.com/report"]},
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources] == [
        "https://docs.example.com/aapl",
        "https://ir.example.com/report",
    ]
    assert provider_capability(provider, provider_kind="search").live_network is False
    dumped = json.dumps([source.to_dict() for source in sources], ensure_ascii=False)
    assert "secret-token" not in dumped
    assert "access_token" not in dumped


def test_phase95_source_directory_search_provider_exposes_finance_sources() -> None:
    provider = SourceDirectorySearchProvider()

    sources = provider.search(
        "AAPL fundamentals",
        goal=SearchGoal(
            goal_id="goal-directory",
            query="AAPL fundamentals",
            max_sources=8,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan(),
    )

    assert sources
    assert {source.metadata["source_family"] for source in sources} >= {"regulatory_filing", "structured_regulatory_data"}
    assert all(source.provider == "research_source_directory_search" for source in sources)
    assert provider.search_diagnostics()["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID


def test_phase95_source_directory_ranks_finance_sources_by_query_and_task_metadata() -> None:
    provider = SourceDirectorySearchProvider()

    news_sources = provider.search(
        "Apple latest Reuters CNBC market news earnings",
        goal=SearchGoal(
            goal_id="goal-news-directory",
            query="Apple latest Reuters CNBC market news earnings",
            max_sources=3,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "market_news",
                "source_authority_requirement": "secondary_or_better",
            },
        ),
        plan=_plan(),
    )
    data_sources = provider.search(
        "AAPL quote price market cap Nasdaq Yahoo",
        goal=SearchGoal(
            goal_id="goal-data-directory",
            query="AAPL quote price market cap Nasdaq Yahoo",
            max_sources=3,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "market_data",
                "source_authority_requirement": "secondary_or_better",
            },
        ),
        plan=_plan(),
    )
    macro_sources = provider.search(
        "Federal Reserve policy rate Treasury yield curve",
        goal=SearchGoal(
            goal_id="goal-macro-directory",
            query="Federal Reserve policy rate Treasury yield curve",
            max_sources=3,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "macro_rates",
                "source_authority_requirement": "primary",
            },
        ),
        plan=_plan(),
    )

    assert news_sources[0].metadata["source_family"] == "reputable_news"
    assert data_sources[0].metadata["source_family"] == "market_data_provider"
    assert macro_sources[0].metadata["source_family"] in {
        "central_bank_statistic",
        "treasury_data",
        "government_statistic",
    }
    assert float(news_sources[0].metadata["source_directory_relevance_score"]) > 0
    assert provider.search_diagnostics()["query_aware_ranking"] is True


def test_phase95_agent_uses_relevant_source_directory_entry_under_tight_source_budget() -> None:
    journal = JournalStore.in_memory()
    query = "Apple latest Reuters CNBC market news earnings"
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "semantic.intake": {
                        "primary_intent": "market_news_research",
                        "suggested_mode": "retrieval_answer",
                        "compound": False,
                        "requires_clarification": False,
                        "intents": [
                            {
                                "kind": "market_news_research",
                                "text": query,
                                "sequence_index": 1,
                                "required_capabilities": ["finance.market_news"],
                                "risk": "read",
                                "status": "ready",
                                "metadata": {
                                    "capability_args": {
                                        "retrieval.run": {
                                            "query": query,
                                            "max_sources": 1,
                                            "max_fetches": 1,
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
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=SourceDirectorySearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                "https://www.reuters.com/": (
                    "Apple latest Reuters CNBC market news earnings chronology. "
                    "This secondary market news source provides citable event context."
                )
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run("Research Apple market news", mode="auto", semantic_mode="model")

    assert result.status == "completed"
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    assert search.data["sources"][0]["metadata"]["source_directory_id"] == "finance-reputable-market-news"
    assert search.data["sources"][0]["metadata"]["source_family"] == "reputable_news"
    assert search.data["diagnostics"]["provider_diagnostics"]["top_source_directory_ids"] == [
        "finance-reputable-market-news"
    ]
    fetch = journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")[0]
    assert fetch.data["uri"] == "https://www.reuters.com/"
    assert result.final_answer is not None
    assert result.final_answer["citation_refs"]


def test_phase95_bounded_crawl_search_provider_discovers_links_with_host_allowlist() -> None:
    transport = _Transport(
        {
            "https://docs.example.com/index.html": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=(
                    b'<html><body>'
                    b'<a href="/filings/aapl-10k.html">AAPL 10-K filing</a>'
                    b'<a href="https://other.example.net/skip">Skip other host</a>'
                    b"</body></html>"
                ),
            )
        }
    )
    provider = BoundedCrawlSearchProvider(
        enabled=True,
        seed_urls=["https://docs.example.com/index.html"],
        allowed_hosts=["docs.example.com"],
        max_links_per_page=5,
        transport=transport,
    )

    sources = provider.search("AAPL filing", goal=_goal(max_sources=5), plan=_plan())

    assert [source.uri for source in sources] == [
        "https://docs.example.com/index.html",
        "https://docs.example.com/filings/aapl-10k.html",
    ]
    assert sources[1].title == "AAPL 10-K filing"
    diagnostics = provider.search_diagnostics()
    assert diagnostics["fetched_seed_count"] == 1
    dumped = json.dumps(diagnostics, ensure_ascii=False)
    assert "AAPL 10-K" not in dumped
    assert "docs.example.com" not in dumped


def test_phase95_bounded_crawl_query_ranking_preserves_relevant_links_under_source_limit() -> None:
    transport = _Transport(
        {
            "https://docs.example.com/index.html": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=(
                    b"<html><body>"
                    b'<a href="/about.html">About the site</a>'
                    b'<a href="/support/contact.html">Contact support</a>'
                    b'<a href="/investor/aapl-10-k-revenue.html">AAPL 10-K revenue filing</a>'
                    b"</body></html>"
                ),
            )
        }
    )
    provider = BoundedCrawlSearchProvider(
        enabled=True,
        seed_urls=["https://docs.example.com/index.html"],
        allowed_hosts=["docs.example.com"],
        max_links_per_page=5,
        include_sitemaps=False,
        transport=transport,
    )

    sources = provider.search("AAPL 10-K revenue filing", goal=_goal(max_sources=2), plan=_plan())

    assert [source.uri for source in sources] == [
        "https://docs.example.com/index.html",
        "https://docs.example.com/investor/aapl-10-k-revenue.html",
    ]
    assert float(sources[1].metadata["query_relevance_score"]) > 0
    assert "revenue" in sources[1].metadata["matched_query_terms"]
    diagnostics = provider.search_diagnostics()
    assert diagnostics["query_aware_ranking"] is True
    assert diagnostics["candidate_source_count"] == 3
    assert diagnostics["matched_candidate_count"] >= 1


def test_phase95_bounded_crawl_search_provider_does_not_fetch_when_source_budget_is_zero() -> None:
    transport = _Transport(
        {
            "https://docs.example.com/index.html": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=b'<a href="/filings/aapl-10k.html">AAPL 10-K filing</a>',
            )
        }
    )
    provider = BoundedCrawlSearchProvider(
        enabled=True,
        seed_urls=["https://docs.example.com/index.html"],
        allowed_hosts=["docs.example.com"],
        transport=transport,
    )

    assert provider.search("AAPL filing", goal=_goal(max_sources=0), plan=_plan()) == []
    assert transport.calls == []
    assert provider.search_diagnostics()["reason"] == "max_sources_exhausted"


def test_phase95_bounded_crawl_search_provider_discovers_sitemap_urls_and_rank_prefers_relevant_pages() -> None:
    transport = _Transport(
        {
            "https://docs.example.com/": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=b"<html><body>No static anchors in this shell.</body></html>",
            ),
            "https://docs.example.com/sitemap.xml": HttpTransportResponse(
                status_code=200,
                mime_type="application/xml",
                body=(
                    b"<urlset>"
                    b"<url><loc>https://docs.example.com/</loc></url>"
                    b"<url><loc>https://docs.example.com/quick_start/token_usage</loc></url>"
                    b"<url><loc>https://docs.example.com/quick_start/pricing</loc></url>"
                    b"<url><loc>https://docs.example.com/news/changelog</loc></url>"
                    b"</urlset>"
                ),
            ),
        }
    )
    provider = BoundedCrawlSearchProvider(
        enabled=True,
        seed_urls=["https://docs.example.com/"],
        allowed_hosts=["docs.example.com"],
        transport=transport,
    )
    goal = SearchGoal(
        goal_id="goal-sitemap",
        query="DeepSeek API 文档 模型 鉴权方式",
        max_sources=5,
        max_fetches=2,
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    ranked = rank_sources(goal, sources)

    assert provider.search_diagnostics()["fetched_sitemap_count"] == 1
    assert {source.metadata["source_kind"] for source in sources} >= {"crawl_seed", "crawl_sitemap"}
    assert {item.uri for item in ranked[:2]} == {
        "https://docs.example.com/quick_start/pricing",
        "https://docs.example.com/quick_start/token_usage",
    }


def test_phase95_bounded_crawl_can_seed_from_finance_source_directory() -> None:
    transport = _Transport(
        {
            "https://www.sec.gov/edgar/search/": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=(
                    b"<html><body>"
                    b'<a href="/Archives/edgar/data/320193/aapl-10k-revenue.htm">AAPL 10-K revenue filing</a>'
                    b'<a href="https://untrusted.example.net/skip">Skip untrusted host</a>'
                    b"</body></html>"
                ),
            )
        }
    )
    provider = BoundedCrawlSearchProvider(
        enabled=True,
        allowed_hosts=["sec.gov", "www.sec.gov"],
        include_source_directory_seeds=True,
        include_sitemaps=False,
        max_source_directory_seeds=1,
        max_links_per_page=5,
        transport=transport,
    )
    goal = SearchGoal(
        goal_id="goal-source-dir-crawl",
        query="AAPL 10-K revenue filing",
        max_sources=3,
        max_fetches=1,
        metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())

    assert [source.uri for source in sources] == [
        "https://www.sec.gov/edgar/search/",
        "https://www.sec.gov/Archives/edgar/data/320193/aapl-10k-revenue.htm",
    ]
    diagnostics = provider.search_diagnostics()
    assert diagnostics["configured_seed_count"] == 0
    assert diagnostics["source_directory_seed_count"] == 1
    assert diagnostics["fetched_seed_count"] == 1
    assert [call["url"] for call in transport.calls] == ["https://www.sec.gov/edgar/search/"]


def test_phase95_agent_live_crawl_uses_sitemap_discovery_for_relevant_fetches() -> None:
    journal = JournalStore.in_memory()
    crawl_transport = _Transport(
        {
            "https://docs.example.com/": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=b"<html><body>No static anchors in this shell.</body></html>",
            ),
            "https://docs.example.com/sitemap.xml": HttpTransportResponse(
                status_code=200,
                mime_type="application/xml",
                body=(
                    b"<urlset>"
                    b"<url><loc>https://docs.example.com/</loc></url>"
                    b"<url><loc>https://docs.example.com/quick_start/token_usage</loc></url>"
                    b"<url><loc>https://docs.example.com/quick_start/pricing</loc></url>"
                    b"</urlset>"
                ),
            ),
        }
    )
    fetch_transport = _Transport(
        {
            "https://docs.example.com/quick_start/pricing": HttpTransportResponse(
                status_code=200,
                body=b"Models and Pricing: deepseek-chat and deepseek-reasoner are API models.",
                mime_type="text/plain",
            ),
            "https://docs.example.com/quick_start/token_usage": HttpTransportResponse(
                status_code=200,
                body=b"Token Usage and authentication: use the Authorization header with a Bearer token.",
                mime_type="text/plain",
            ),
        }
    )
    operator = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_CRAWL_SEED_URLS": "https://docs.example.com/",
            "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS": "docs.example.com",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "docs.example.com",
        }
    ).build_operator(crawl_transport=crawl_transport, fetch_transport=fetch_transport)
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=operator,
    )

    result = runtime.run(
        "Research DeepSeek API 文档 模型 鉴权方式",
        mode="retrieval",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 2,
                "max_fetches": 2,
            }
        },
    )

    assert result.status == "completed"
    assert {call["url"] for call in fetch_transport.calls} == {
        "https://docs.example.com/quick_start/pricing",
        "https://docs.example.com/quick_start/token_usage",
    }
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    assert search.data["diagnostics"]["provider_diagnostics"]["selected_provider_id"] == "bounded_crawl_search"


def test_phase95_agent_can_crawl_from_finance_source_directory_seed() -> None:
    journal = JournalStore.in_memory()
    crawl_transport = _Transport(
        {
            "https://www.sec.gov/edgar/search/": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=(
                    b"<html><body>"
                    b'<a href="/Archives/edgar/data/320193/aapl-10k-revenue.htm">AAPL 10-K revenue filing</a>'
                    b"</body></html>"
                ),
            )
        }
    )
    fetch_transport = _Transport(
        {
                "https://www.sec.gov/Archives/edgar/data/320193/aapl-10k-revenue.htm": HttpTransportResponse(
                    status_code=200,
                    body=b"Apple AAPL 10-K revenue was $391.0 billion in the SEC archive.",
                    mime_type="text/plain",
                )
        }
    )
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "semantic.intake": {
                        "primary_intent": "finance_fundamentals",
                        "suggested_mode": "retrieval_answer",
                        "compound": False,
                        "requires_clarification": False,
                        "intents": [
                            {
                                "kind": "finance_fundamentals",
                                "text": "AAPL 10-K revenue filing",
                                "sequence_index": 1,
                                "required_capabilities": ["finance.fundamentals_research"],
                                "risk": "read",
                                "status": "ready",
                                "metadata": {
                                    "capability_args": {
                                        "retrieval.run": {
                                            "query": "AAPL 10-K revenue filing",
                                            "max_queries": 1,
                                            "max_sources": 3,
                                            "max_fetches": 1,
                                            "metadata": {
                                                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                                                "search_strategy": "crawl",
                                            },
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
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    operator = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_STRATEGY": "adaptive",
            "HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY": "1",
            "HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST": "1",
            "HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS": "1",
            "HOLO_V3_LIVE_CRAWL_MAX_PAGES": "1",
            "HOLO_V3_LIVE_CRAWL_INCLUDE_SITEMAPS": "0",
        }
    ).build_operator(crawl_transport=crawl_transport, fetch_transport=fetch_transport)

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        "Research AAPL 10-K revenue filing from official sources",
        mode="auto",
        semantic_mode="model",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 1,
            }
        },
    )

    assert result.status == "completed"
    assert [call["url"] for call in crawl_transport.calls] == ["https://www.sec.gov/edgar/search/"]
    assert [call["url"] for call in fetch_transport.calls] == [
        "https://www.sec.gov/Archives/edgar/data/320193/aapl-10k-revenue.htm"
    ]
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    provider_diagnostics = search.data["diagnostics"]["provider_diagnostics"]
    assert provider_diagnostics["selected_strategy"] == "crawl"
    assert "bounded_crawl_search" in provider_diagnostics["selected_provider_ids"]
    assert result.final_answer["citation_refs"]


def test_phase95_agent_live_retrieval_can_use_direct_url_search_provider() -> None:
    journal = JournalStore.in_memory()
    fetch_transport = _Transport(
        {
            "https://docs.example.com/aapl": HttpTransportResponse(
                status_code=200,
                body=b"AAPL revenue evidence from a direct URL retrieval source.",
                mime_type="text/plain",
            )
        }
    )
    operator = RetrievalOperator(
        search_provider=DirectUrlSearchProvider(),
        fetch_provider=HttpFetchProvider(
            enabled=True,
            allowed_hosts=["docs.example.com"],
            transport=fetch_transport,
        ),
    )
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=operator,
    )

    result = runtime.run(
        "Research AAPL revenue at https://docs.example.com/aapl",
        mode="retrieval",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 1,
                "max_fetches": 1,
            }
        },
    )

    assert result.status == "completed"
    assert result.final_answer["citation_refs"]
    assert len(fetch_transport.calls) == 1
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    assert search.data["status"] == "ok"
    assert search.data["diagnostics"]["provider_source_count"] == 1


def test_phase95_agent_live_retrieval_can_use_bounded_crawl_without_search_endpoint() -> None:
    journal = JournalStore.in_memory()
    crawl_transport = _Transport(
        {
            "https://docs.example.com/index.html": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=(
                    b"<html><body>"
                    b'<a href="/filings/aapl-10k.html">AAPL 10-K filing</a>'
                    b"</body></html>"
                ),
            )
        }
    )
    fetch_transport = _Transport(
        {
            "https://docs.example.com/index.html": HttpTransportResponse(
                status_code=200,
                body=b"Index page for AAPL filings.",
                mime_type="text/plain",
            ),
            "https://docs.example.com/filings/aapl-10k.html": HttpTransportResponse(
                status_code=200,
                body=b"AAPL 10-K evidence: net sales increased in the filing period.",
                mime_type="text/plain",
            ),
        }
    )
    operator = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_CRAWL_SEED_URLS": "https://docs.example.com/index.html",
            "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS": "docs.example.com",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "docs.example.com",
            "HOLO_V3_LIVE_CRAWL_INCLUDE_SITEMAPS": "0",
        }
    ).build_operator(crawl_transport=crawl_transport, fetch_transport=fetch_transport)
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=operator,
    )

    result = runtime.run(
        "Research AAPL filing evidence",
        mode="retrieval",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 2,
                "max_fetches": 2,
            }
        },
    )

    assert result.status == "completed"
    assert result.final_answer["citation_refs"]
    assert len(crawl_transport.calls) == 1
    assert {call["url"] for call in fetch_transport.calls} == {
        "https://docs.example.com/index.html",
        "https://docs.example.com/filings/aapl-10k.html",
    }
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    diagnostics = search.data["diagnostics"]["provider_diagnostics"]
    assert diagnostics["provider_id"] == "fallback_search"
    assert diagnostics["selected_provider_id"] == "bounded_crawl_search"


def test_phase95_model_planner_retrieval_action_inherits_host_live_budget() -> None:
    journal = JournalStore.in_memory()
    fetch_transport = _Transport(
        {
            "https://docs.example.com/aapl": HttpTransportResponse(
                status_code=200,
                body=b"AAPL evidence from host-budgeted model planner retrieval.",
                mime_type="text/plain",
            )
        }
    )
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "planner.propose": {
                        "action_id": "act-model-retrieval",
                        "kind": "tool",
                        "name": "retrieval.run",
                        "description": "model proposes retrieval without host budget fields",
                        "payload": {"query": "AAPL evidence", "source_url": "https://docs.example.com/aapl"},
                        "score": 0.9,
                        "reasons": ["needs evidence"],
                        "side_effect_class": "read",
                    }
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake"),
        journal=journal,
    )
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=RetrievalOperator(
            search_provider=DirectUrlSearchProvider(),
            fetch_provider=HttpFetchProvider(
                enabled=True,
                allowed_hosts=["docs.example.com"],
                transport=fetch_transport,
            ),
        ),
    )

    result = runtime.run(
        "Research AAPL evidence",
        mode="retrieval",
        planner_mode="model",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 1,
                "max_fetches": 1,
            }
        },
    )

    assert result.status == "completed"
    action = journal.records(task_id=result.task_id, kind="action")[0].data
    assert action["payload"]["max_fetches"] == 1
    assert action["payload"]["max_network_fetches"] == 1
    assert not journal.records(task_id=result.task_id, kind="guard")
    assert len(fetch_transport.calls) == 1


def _goal(max_sources: int = 3) -> SearchGoal:
    return SearchGoal(goal_id="goal-crawl", query="AAPL filing", max_sources=max_sources, max_fetches=2)


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-crawl",
        goal_id="goal-crawl",
        queries=["AAPL filing"],
        max_sources=3,
        max_fetches=2,
    )


class _Transport:
    def __init__(self, responses: dict[str, HttpTransportResponse]) -> None:
        self.responses = dict(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "max_bytes": max_bytes,
            }
        )
        return self.responses.get(url, HttpTransportResponse(status_code=404, body=b""))
