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


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-source-query-test",
        goal_id="goal-source-query-test",
        queries=["test"],
        max_sources=10,
        max_fetches=4,
    )
