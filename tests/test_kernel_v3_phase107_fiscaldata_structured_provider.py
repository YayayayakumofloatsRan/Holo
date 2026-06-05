from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    FakeFetchProvider,
    FallbackSearchProvider,
    FiscalDataSearchProvider,
    LiveRetrievalConfig,
    QueryPlan,
    ResearchSourceQuerySearchProvider,
    RetrievalOperator,
    SearchGoal,
)


DEBT_TO_PENNY_PATH = "/services/api/fiscal_service/v2/accounting/od/debt_to_penny"


def test_phase107_fiscaldata_provider_generates_official_api_candidate() -> None:
    provider = FiscalDataSearchProvider()

    sources = provider.search(
        "FiscalData public debt to the penny official API",
        goal=SearchGoal(
            goal_id="goal-fiscaldata-api",
            query="FiscalData public debt to the penny official API",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fiscaldata_api_path": DEBT_TO_PENNY_PATH,
                "fiscaldata_fields": ["record_date", "tot_pub_debt_out_amt"],
                "fiscaldata_filter": "record_date:gte:2024-01-01",
                "fiscaldata_sort": "-record_date",
                "page_size": 50,
            },
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources] == [
        (
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
            "?fields=record_date%2Ctot_pub_debt_out_amt&filter=record_date%3Agte%3A2024-01-01"
            "&sort=-record_date&page%5Bsize%5D=50&format=json"
        )
    ]
    assert sources[0].provider == "fiscaldata_structured_search"
    assert sources[0].metadata["source_family"] == "treasury_data"
    assert sources[0].metadata["authority_level"] == "primary"
    assert sources[0].metadata["source_kind"] == "fiscaldata_api_endpoint"
    assert provider.search_diagnostics()["fiscaldata_api_path"] == DEBT_TO_PENNY_PATH


def test_phase107_fiscaldata_provider_is_profile_gated_and_rejects_unsafe_paths() -> None:
    provider = FiscalDataSearchProvider()

    no_profile = provider.search(
        "FiscalData debt",
        goal=SearchGoal(goal_id="goal-no-profile", query="FiscalData debt", metadata={"fiscaldata_api_path": DEBT_TO_PENNY_PATH}),
        plan=_plan(),
    )
    assert no_profile == []
    assert provider.search_diagnostics()["reason"] == "not_finance_profile"

    unsafe = provider.search(
        "FiscalData unsafe",
        goal=SearchGoal(
            goal_id="goal-unsafe-fiscaldata",
            query="FiscalData unsafe",
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fiscaldata_api_path": "/services/api/fiscal_service/../../secret",
            },
        ),
        plan=_plan(),
    )
    assert unsafe == []
    assert provider.search_diagnostics()["reason"] == "invalid_fiscaldata_api_path"

    secret_filter = provider.search(
        "FiscalData secret",
        goal=SearchGoal(
            goal_id="goal-secret-fiscaldata",
            query="FiscalData secret",
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fiscaldata_api_path": DEBT_TO_PENNY_PATH,
                "fiscaldata_filter": "api_key:secret:live-secret-token-1234567890",
            },
        ),
        plan=_plan(),
    )
    assert secret_filter == []
    assert provider.search_diagnostics()["reason"] == "invalid_fiscaldata_query_params"


def test_phase107_live_config_structured_strategy_includes_fiscaldata_provider() -> None:
    operator = LiveRetrievalConfig(search_strategy="adaptive").build_operator()

    sources = operator.search_provider.search(
        "FiscalData public debt official API",
        goal=SearchGoal(
            goal_id="goal-live-config-fiscaldata",
            query="FiscalData public debt official API",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "search_strategy": "structured",
                "fiscaldata_api_path": DEBT_TO_PENNY_PATH,
            },
        ),
        plan=_plan(),
    )

    assert any(source.provider == "fiscaldata_structured_search" for source in sources)
    diagnostics = operator.search_provider.search_diagnostics()
    assert diagnostics["selected_strategy"] == "structured"
    assert "fiscaldata_structured_search" in diagnostics["selected_provider_ids"]


def test_phase107_model_planner_continues_from_fiscaldata_search_to_api_endpoint() -> None:
    query = "Research US public debt from FiscalData and then fetch the official API endpoint"
    search_query = "FiscalData public debt dataset API endpoint"
    search_url = "https://fiscaldata.treasury.gov/datasets/?search=public%20debt"
    api_url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
        "?page%5Bsize%5D=100&format=json"
    )
    hinted_payload = {
        "goal_id": "goal-plan-1-2",
        "query": "FiscalData debt_to_penny official Treasury API data",
        "max_fetches": 1,
        "metadata": {
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "fiscaldata_api_path": DEBT_TO_PENNY_PATH,
            "source_authority_requirement": "primary",
            "source_family": "treasury_data",
            "preferred_source_families": ["treasury_data", "government_statistic", "central_bank_statistic"],
            "research_task_kind": "macro_data",
            "search_strategy": "structured",
        },
    }
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _fiscaldata_semantic_intake(query, search_query),
            "planner.propose": [
                {
                    "action_id": "act-fiscaldata-dataset-search",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "find the official FiscalData API endpoint",
                    "payload": {
                        "goal_id": "goal-plan-1-1",
                        "query": search_query,
                        "max_fetches": 1,
                        "metadata": {
                            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                            "metric": "public debt",
                            "research_task_kind": "macro_data",
                            "search_strategy": "structured",
                        },
                    },
                    "score": 0.9,
                    "reasons": ["planned FiscalData discovery subgoal"],
                    "side_effect_class": "read",
                },
                {
                    "action_id": "act-fiscaldata-api",
                    "kind": "tool",
                    "name": "retrieval.run",
                    "description": "use host FiscalData endpoint continuation hint",
                    "payload": hinted_payload,
                    "score": 0.94,
                    "reasons": ["context exposed suggested_fiscaldata_endpoints"],
                    "side_effect_class": "read",
                },
            ],
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([FiscalDataSearchProvider(), ResearchSourceQuerySearchProvider()]),
        fetch_provider=FakeFetchProvider(
            {
                search_url: (
                    "FiscalData public debt dataset API endpoint: "
                    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny "
                    "official Treasury public debt data."
                ),
                api_url: (
                    '{"data":[{"record_date":"2024-01-31","tot_pub_debt_out_amt":"34500000000000"}],'
                    '"meta":{"source":"official Treasury FiscalData debt_to_penny API data"}}'
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
    fiscaldata_hints = contexts[1].data["state"]["agent_replan_hints"]["retrieval"]["suggested_fiscaldata_endpoints"]
    assert fiscaldata_hints[0]["fiscaldata_api_path"] == DEBT_TO_PENNY_PATH
    assert fiscaldata_hints[0]["suggested_payload"]["metadata"] == hinted_payload["metadata"]
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["payload"]["goal_id"] for record in actions] == ["goal-plan-1-1", "goal-plan-1-2"]
    action_metadata = actions[1].data["payload"]["metadata"]
    for key, value in hinted_payload["metadata"].items():
        assert action_metadata[key] == value
    searches = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
    assert any(
        source["provider"] == "fiscaldata_structured_search"
        for record in searches
        for source in record.data["sources"]
    )
    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")
        if record.data["status"] == "ok"
    ]
    assert api_url in fetch_uris
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    assert result.final_answer["citation_refs"]


def _fiscaldata_semantic_intake(query: str, search_query: str) -> dict:
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
                                "metadata": {"metric": "public debt", "research_task_kind": "macro_data"},
                            },
                            {
                                "goal_id": "goal-plan-1-2",
                                "query": "FiscalData public debt official API",
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
        plan_id="plan-fiscaldata-test",
        goal_id="goal-fiscaldata-test",
        queries=["test"],
        max_sources=10,
        max_fetches=4,
    )
