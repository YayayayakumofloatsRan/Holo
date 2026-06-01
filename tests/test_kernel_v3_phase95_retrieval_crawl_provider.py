import json

from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    BoundedCrawlSearchProvider,
    DirectUrlSearchProvider,
    HttpFetchProvider,
    HttpTransportResponse,
    LiveRetrievalConfig,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SourceDirectorySearchProvider,
    provider_capability,
)


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
