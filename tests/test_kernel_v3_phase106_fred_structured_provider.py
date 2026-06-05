from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    FakeFetchProvider,
    FallbackSearchProvider,
    FredSearchProvider,
    LiveRetrievalConfig,
    QueryPlan,
    ResearchSourceQuerySearchProvider,
    RetrievalOperator,
    SearchGoal,
)


def test_phase106_fred_provider_generates_official_series_and_csv_candidates() -> None:
    provider = FredSearchProvider()

    sources = provider.search(
        "FRED CPIAUCSL Consumer Price Index observations",
        goal=SearchGoal(
            goal_id="goal-fred-series",
            query="FRED CPIAUCSL Consumer Price Index observations",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fred_series_id": "CPIAUCSL",
                "observation_start": "2024-01-01",
            },
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources] == [
        "https://fred.stlouisfed.org/series/CPIAUCSL",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
    ]
    assert all(source.provider == "fred_structured_search" for source in sources)
    assert all(source.metadata["source_family"] == "government_statistic" for source in sources)
    assert all(source.metadata["authority_level"] == "primary" for source in sources)
    assert sources[1].metadata["source_kind"] == "fred_observations_csv"
    assert sources[0].metadata["observation_start"] == "2024-01-01"
    assert provider.search_diagnostics()["fred_series_id"] == "CPIAUCSL"


def test_phase106_fred_provider_is_profile_gated_and_rejects_unsafe_series_ids() -> None:
    provider = FredSearchProvider()

    no_profile = provider.search(
        "FRED CPIAUCSL",
        goal=SearchGoal(goal_id="goal-no-profile", query="FRED CPIAUCSL", metadata={"fred_series_id": "CPIAUCSL"}),
        plan=_plan(),
    )
    assert no_profile == []
    assert provider.search_diagnostics()["reason"] == "not_finance_profile"

    unsafe = provider.search(
        "FRED unsafe",
        goal=SearchGoal(
            goal_id="goal-unsafe-fred",
            query="FRED unsafe",
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fred_series_id": "CPIAUCSL?api_key=secret",
            },
        ),
        plan=_plan(),
    )
    assert unsafe == []
    assert provider.search_diagnostics()["reason"] == "invalid_fred_series_id"


def test_phase106_live_config_structured_strategy_includes_fred_provider() -> None:
    operator = LiveRetrievalConfig(search_strategy="adaptive").build_operator()

    sources = operator.search_provider.search(
        "FRED CPIAUCSL official CSV observations",
        goal=SearchGoal(
            goal_id="goal-live-config-fred",
            query="FRED CPIAUCSL official CSV observations",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "search_strategy": "structured",
                "fred_series_id": "CPIAUCSL",
            },
        ),
        plan=_plan(),
    )

    assert any(source.provider == "fred_structured_search" for source in sources)
    diagnostics = operator.search_provider.search_diagnostics()
    assert diagnostics["selected_strategy"] == "structured"
    assert "fred_structured_search" in diagnostics["selected_provider_ids"]


def test_phase106_model_planner_continues_from_fred_search_to_structured_csv() -> None:
    query = "Research CPI inflation from FRED and then fetch the official CPIAUCSL observations"
    search_query = "FRED CPI inflation series search CPIAUCSL"
    search_url = "https://fred.stlouisfed.org/searchresults/?search_type=series&search=CPI"
    series_url = "https://fred.stlouisfed.org/series/CPIAUCSL"
    csv_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"
    hinted_payload = {
        "goal_id": "goal-plan-1-2",
        "query": "FRED series CPIAUCSL official CSV observations",
        "max_fetches": 2,
        "metadata": {
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "fred_series_id": "CPIAUCSL",
            "source_authority_requirement": "primary",
            "source_family": "government_statistic",
            "preferred_source_families": ["government_statistic", "central_bank_statistic", "treasury_data"],
            "research_task_kind": "macro_data",
            "search_strategy": "structured",
        },
    }
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _macro_semantic_intake(query, search_query),
            "planner.propose": [
                {
                    "action_id": "act-fred-series-search",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "find the official FRED series identifier",
                    "payload": {
                        "goal_id": "goal-plan-1-1",
                        "query": search_query,
                        "max_fetches": 1,
                        "metadata": {
                            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                            "metric": "CPI",
                            "research_task_kind": "macro_data",
                            "search_strategy": "structured",
                        },
                    },
                    "score": 0.9,
                    "reasons": ["planned macro data discovery subgoal"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-fred-structured-csv",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "use host macro series continuation hint",
                    "payload": hinted_payload,
                    "score": 0.94,
                    "reasons": ["context exposed suggested_macro_series"],
                    "side_effect_class": "read",
                },
            ],
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([FredSearchProvider(), ResearchSourceQuerySearchProvider()]),
        fetch_provider=FakeFetchProvider(
            {
                search_url: (
                    "FRED official CPI inflation search result: series_id=CPIAUCSL "
                    "Consumer Price Index for All Urban Consumers."
                ),
                series_url: (
                    "FRED series CPIAUCSL official Consumer Price Index source page, "
                    "seasonally adjusted monthly observations."
                ),
                csv_url: (
                    "observation_date,CPIAUCSL\n"
                    "2024-01-01,309.685\n"
                    "2024-02-01,311.054\n"
                ),
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
    planner_requests = [
        record
        for record in journal.records(task_id=result.task_id, kind="processor_request")
        if record.data["task_type"] == "planner.propose"
    ]
    assert len(planner_requests) == 2
    contexts = journal.records(task_id=result.task_id, kind="context")
    macro_hints = contexts[1].data["state"]["agent_replan_hints"]["retrieval"]["suggested_macro_series"]
    assert macro_hints[0]["fred_series_id"] == "CPIAUCSL"
    assert macro_hints[0]["suggested_payload"]["metadata"] == hinted_payload["metadata"]
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["payload"]["goal_id"] for record in actions] == ["goal-plan-1-1", "goal-plan-1-2"]
    action_metadata = actions[1].data["payload"]["metadata"]
    for key, value in hinted_payload["metadata"].items():
        assert action_metadata[key] == value
    searches = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
    assert any(
        source["provider"] == "fred_structured_search"
        for record in searches
        for source in record.data["sources"]
    )
    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")
        if record.data["status"] == "ok"
    ]
    assert csv_url in fetch_uris
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    assert result.final_answer["citation_refs"]


def _macro_semantic_intake(query: str, search_query: str) -> dict:
    return {
        "primary_intent": "macro_data_research",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "macro_data_research",
                "text": query,
                "sequence_index": 1,
                "required_capabilities": ["finance.macro_data"],
                "risk": "read",
                "status": "ready",
                "metadata": {
                    "domain": "finance",
                    "activity": "research",
                    "resource": "dataset",
                    "capability_args": {
                        "retrieval.run": [
                            {
                                "goal_id": "goal-plan-1-1",
                                "query": search_query,
                                "metadata": {"metric": "CPI", "research_task_kind": "macro_data"},
                            },
                            {
                                "goal_id": "goal-plan-1-2",
                                "query": "FRED CPIAUCSL official observations",
                                "metadata": {"research_task_kind": "macro_data"},
                            },
                        ]
                    },
                    "state_axes": {
                        "goal_structure": "compound_ordered",
                        "domain_profile": "macro_data_research",
                        "resource_kind": "dataset",
                        "authority": "primary_source_required",
                    },
                },
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-fred-test",
        goal_id="goal-fred-test",
        queries=["test"],
        max_sources=10,
        max_fetches=4,
    )
