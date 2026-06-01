from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    AdaptiveSearchProvider,
    FakeFetchProvider,
    LiveRetrievalConfig,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)


def test_phase105_adaptive_search_strategy_can_skip_corpus_for_fresh_live_retry() -> None:
    provider = AdaptiveSearchProvider(
        [
            _StaticSearchProvider(
                "research_corpus",
                [
                    _source(
                        "cached-weak-aapl",
                        "https://example.com/aapl-cached-summary",
                        "Cached AAPL revenue summary",
                        "Cached third-party summary.",
                        provider="research_corpus",
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
                        provider="official_sec_search",
                    )
                ],
            ),
        ],
        default_strategy="fallback",
    )

    corpus_sources = provider.search(
        "AAPL 2024 10-K revenue",
        goal=_goal(metadata={"search_strategy": "corpus_only"}),
        plan=_plan(),
    )
    corpus_diagnostics = provider.search_diagnostics()
    fresh_sources = provider.search(
        "AAPL 2024 10-K revenue",
        goal=_goal(metadata={"search_strategy": "fresh_live"}),
        plan=_plan(),
    )
    fresh_diagnostics = provider.search_diagnostics()

    assert [source.provider for source in corpus_sources] == ["research_corpus"]
    assert corpus_diagnostics["selected_strategy"] == "corpus_only"
    assert corpus_diagnostics["selected_provider_ids"] == ["research_corpus"]
    assert [source.provider for source in fresh_sources] == ["official_sec_search"]
    assert fresh_diagnostics["selected_strategy"] == "fresh_live"
    assert "research_corpus" not in fresh_diagnostics["selected_provider_ids"]


def test_phase105_live_retrieval_config_can_build_adaptive_search_strategy() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_STRATEGY": "adaptive",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "www.sec.gov,sec.gov",
        }
    )

    operator = config.build_operator()

    assert config.safe_diagnostics()["search_strategy"] == "adaptive"
    assert operator.provider_capabilities()[0]["provider_id"] == "adaptive_search"
    diagnostics = operator.provider_capabilities()[0]["diagnostics"]
    assert "fresh_live" in diagnostics["supported_strategies"]
    assert diagnostics["default_strategy"] == "fallback"


def test_phase105_model_planner_replans_from_corpus_only_to_aggregate_primary_source() -> None:
    query = "AAPL 2024 10-K revenue"
    weak_url = "https://example.com/aapl-cached-summary"
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _finance_semantic_intake(query),
            "planner.propose": [
                {
                    "action_id": "act-corpus-only",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "try cached corpus evidence first",
                    "payload": {
                        "query": query,
                        "max_queries": 1,
                        "max_sources": 1,
                        "max_fetches": 1,
                        "metadata": {"search_strategy": "corpus_only"},
                    },
                    "score": 0.84,
                    "reasons": ["cache-first retrieval can avoid unnecessary network"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-aggregate-primary",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "aggregate configured providers for primary source evidence",
                    "payload": {
                        "query": query,
                        "max_queries": 1,
                        "max_sources": 1,
                        "max_fetches": 1,
                        "metadata": {"search_strategy": "aggregate"},
                    },
                    "score": 0.93,
                    "reasons": ["feedback requested primary source authority"],
                    "side_effect_class": "read",
                },
            ],
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=AdaptiveSearchProvider(
            [
                _StaticSearchProvider(
                    "research_corpus",
                    [
                        _source(
                            "cached-weak-aapl",
                            weak_url,
                            "Cached AAPL revenue summary",
                            "Cached third-party summary.",
                            provider="research_corpus",
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
                            provider="official_sec_search",
                        )
                    ],
                ),
            ],
            default_strategy="fallback",
            max_sources_per_provider=1,
        ),
        fetch_provider=FakeFetchProvider(
            {
                weak_url: "Cached third-party AAPL revenue summary from a generic web page.",
                sec_url: "Apple 2024 Form 10-K revenue evidence from the official SEC filing.",
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(
        query,
        mode="auto",
        semantic_mode="model",
        planner_mode="model",
    )

    assert result.status == "completed"
    searches = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
    first_diagnostics = searches[0].data["diagnostics"]["provider_diagnostics"]
    second_diagnostics = searches[1].data["diagnostics"]["provider_diagnostics"]
    assert first_diagnostics["selected_strategy"] == "corpus_only"
    assert first_diagnostics["selected_provider_ids"] == ["research_corpus"]
    assert second_diagnostics["selected_strategy"] == "aggregate"
    assert second_diagnostics["child_provider_id"] == "aggregate_search"
    assert journal.records(task_id=result.task_id, kind="retrieval_report")[0].data["status"] == "insufficient_evidence"
    assert journal.records(task_id=result.task_id, kind="retrieval_report")[-1].data["status"] == "sufficient"
    updates = journal.records(task_id=result.task_id, kind="agent_work_plan_update")
    assert "primary_source" in updates[1].data["feedback_missing_evidence"]
    assert [record.data["payload"]["metadata"]["search_strategy"] for record in journal.records(task_id=result.task_id, kind="action")] == [
        "corpus_only",
        "aggregate",
    ]


def _goal(*, metadata: dict | None = None) -> SearchGoal:
    merged = {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}
    if metadata:
        merged.update(metadata)
    return SearchGoal(
        goal_id="goal-adaptive-search",
        query="AAPL 2024 10-K revenue",
        max_sources=1,
        max_fetches=1,
        metadata=merged,
    )


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-adaptive-search",
        goal_id="goal-adaptive-search",
        queries=["AAPL 2024 10-K revenue"],
        max_sources=1,
        max_fetches=1,
    )


def _finance_semantic_intake(query: str) -> dict:
    return {
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
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


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


def _source(source_id: str, uri: str, title: str, snippet: str, *, provider: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider=provider,
    )
