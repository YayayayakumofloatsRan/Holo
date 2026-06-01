from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    FakeFetchProvider,
    FallbackSearchProvider,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SecEdgarSearchProvider,
)


def test_phase98_sec_edgar_provider_builds_structured_sources_from_cik_metadata():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "AAPL 2024 revenue",
        goal=SearchGoal(
            goal_id="goal-sec",
            query="AAPL 2024 revenue",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "ticker": "AAPL",
                "sec_cik": "320193",
            },
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources] == [
        "https://www.sec.gov/files/company_tickers_exchange.json",
        "https://www.sec.gov/edgar/search/#/q=AAPL",
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "https://www.sec.gov/edgar/browse/?CIK=0000320193",
    ]
    assert all(source.metadata["authority_level"] == "primary" for source in sources)
    assert provider.search_diagnostics()["cik_present"] is True


def test_phase98_sec_edgar_provider_uses_injected_ticker_cik_map_without_network():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "MSFT 10-K revenue",
        goal=SearchGoal(
            goal_id="goal-map",
            query="MSFT 10-K revenue",
            max_sources=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "sec_ticker_cik_map": {"MSFT": "789019"},
            },
        ),
        plan=_plan(),
    )

    assert "https://data.sec.gov/submissions/CIK0000789019.json" in [source.uri for source in sources]
    assert provider.search_diagnostics()["ticker"] == "MSFT"
    assert provider.search_diagnostics()["cik_present"] is True


def test_phase98_sec_edgar_provider_is_profile_gated():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "AAPL CIK0000320193",
        goal=SearchGoal(goal_id="goal-no-profile", query="AAPL CIK0000320193"),
        plan=_plan(),
    )

    assert sources == []
    assert provider.search_diagnostics()["reason"] == "not_finance_profile"


def test_phase98_agent_uses_sec_provider_in_multi_step_finance_loop():
    journal = JournalStore.in_memory()
    goal = "Research AAPL SEC revenue and companyfacts"
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
                        "text": "AAPL SEC submissions",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "AAPL SEC submissions",
                                    "metadata": {
                                        "ticker": "AAPL",
                                        "sec_cik": "320193",
                                    },
                                }
                            }
                        },
                    },
                    {
                        "kind": "finance_fundamentals",
                        "text": "AAPL SEC companyfacts revenue",
                        "sequence_index": 2,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "AAPL SEC companyfacts revenue",
                                    "metadata": {
                                        "ticker": "AAPL",
                                        "sec_cik": "320193",
                                    },
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
        search_provider=FallbackSearchProvider([SecEdgarSearchProvider()]),
        fetch_provider=FakeFetchProvider(
            {
                "https://data.sec.gov/submissions/CIK0000320193.json": (
                    "SEC submissions JSON shows Apple filed Form 10-K and 10-Q reports."
                ),
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json": (
                    "SEC companyfacts JSON includes Apple revenue facts with filing provenance."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(goal, mode="auto", semantic_mode="model")

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run"]
    assert all(
        record.data["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
        for record in actions
    )
    assert any(
        source["provider"] == "sec_edgar_structured_search"
        for record in journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
        for source in record.data["sources"]
    )
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    assert len(result.final_answer["citation_refs"]) == 2


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-sec-test",
        goal_id="goal-sec-test",
        queries=["test"],
        max_sources=5,
        max_fetches=3,
    )
