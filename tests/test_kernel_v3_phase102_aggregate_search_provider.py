from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    AggregateSearchProvider,
    FakeFetchProvider,
    LiveRetrievalConfig,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)


def test_phase102_aggregate_search_ranks_primary_source_across_providers_before_fetch() -> None:
    query = "AAPL 2024 10-K revenue"
    provider = AggregateSearchProvider(
        [
            _StaticSearchProvider(
                "generic_web_search",
                [
                    _source(
                        "generic-aapl-summary",
                        "https://example.com/aapl-10k-summary",
                        "AAPL 2024 10-K revenue summary",
                        "Third-party page repeats Apple revenue.",
                    )
                ],
            ),
            _StaticSearchProvider(
                "official_sec_search",
                [
                    _source(
                        "sec-aapl-10k",
                        "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
                        "Apple 2024 Form 10-K",
                        "Official SEC filing revenue evidence.",
                    )
                ],
            ),
        ],
        max_sources_per_provider=1,
    )

    sources = provider.search(
        query,
        goal=SearchGoal(
            goal_id="goal-aggregate-search",
            query=query,
            max_sources=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources] == [
        "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    ]
    diagnostics = provider.search_diagnostics()
    assert diagnostics["provider_id"] == "aggregate_search"
    assert diagnostics["collected_source_count"] == 2
    assert diagnostics["returned_source_count"] == 1
    assert [attempt["accepted_source_count"] for attempt in diagnostics["attempts"]] == [1, 1]


def test_phase102_agent_retrieval_uses_aggregate_sources_to_avoid_low_authority_stop() -> None:
    query = "AAPL 2024 10-K revenue"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "text": query,
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
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
        },
        journal=journal,
    )
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    operator = RetrievalOperator(
        search_provider=AggregateSearchProvider(
            [
                _StaticSearchProvider(
                    "generic_web_search",
                    [
                        _source(
                            "generic-aapl-summary",
                            "https://example.com/aapl-10k-summary",
                            "AAPL 2024 10-K revenue summary",
                            "Third-party page repeats Apple revenue.",
                        )
                    ],
                ),
                _StaticSearchProvider(
                    "official_sec_search",
                    [
                        _source(
                            "sec-aapl-10k",
                            sec_url,
                            "Apple 2024 Form 10-K",
                            "Official SEC filing revenue evidence.",
                        )
                    ],
                ),
            ],
            max_sources_per_provider=1,
        ),
        fetch_provider=FakeFetchProvider(
            {
                sec_url: (
                    "Apple 2024 Form 10-K revenue evidence from the official SEC filing."
                )
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(query, mode="auto", semantic_mode="model")

    assert result.status == "completed"
    assert result.final_answer["citation_refs"]
    fetched = journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")
    assert [record.data["uri"] for record in fetched] == [sec_url]
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    provider_diagnostics = search.data["diagnostics"]["provider_diagnostics"]
    assert provider_diagnostics["provider_id"] == "aggregate_search"
    assert provider_diagnostics["collected_source_count"] == 2


def test_phase102_live_retrieval_config_can_build_aggregate_search_strategy() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_STRATEGY": "aggregate",
            "HOLO_V3_LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER": "2",
            "HOLO_V3_LIVE_CRAWL_SEED_URLS": "https://docs.example.com/",
            "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS": "docs.example.com",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "docs.example.com",
        }
    )

    operator = config.build_operator()

    assert config.safe_diagnostics()["search_strategy"] == "aggregate"
    assert config.safe_diagnostics()["max_sources_per_provider"] == 2
    assert operator.provider_capabilities()[0]["provider_id"] == "aggregate_search"


class _StaticSearchProvider:
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, provider_id: str, sources: list[SearchSource]) -> None:
        self.provider_id = provider_id
        self.sources = list(sources)

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        return self.sources[: goal.max_sources]

    def search_diagnostics(self):
        return {"provider_id": self.provider_id, "source_count": len(self.sources)}


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="phase102",
    )


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-aggregate-search",
        goal_id="goal-aggregate-search",
        queries=["AAPL 2024 10-K revenue"],
        max_sources=1,
        max_fetches=1,
    )
