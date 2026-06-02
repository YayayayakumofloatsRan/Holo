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


def test_phase98_sec_edgar_provider_builds_archive_document_sources_from_accession_metadata():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "AAPL 2024 10-K primary document",
        goal=SearchGoal(
            goal_id="goal-sec-filing-document",
            query="AAPL 2024 10-K primary document",
            max_sources=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "ticker": "AAPL",
                "sec_cik": "320193",
                "sec_accession_number": "0000320193-24-000123",
                "sec_primary_document": "aapl-20240928.htm",
                "sec_form": "10-K",
                "report_date": "2024-09-28",
            },
        ),
        plan=_plan(),
    )

    assert [source.uri for source in sources[:3]] == [
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123.txt",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/",
    ]
    assert [source.metadata["source_kind"] for source in sources[:3]] == [
        "sec_primary_filing_document",
        "sec_complete_submission_text",
        "sec_filing_directory",
    ]
    assert sources[0].metadata["sec_accession_compact"] == "000032019324000123"
    assert sources[0].metadata["sec_primary_document"] == "aapl-20240928.htm"
    assert provider.search_diagnostics()["accession_present"] is True
    assert provider.search_diagnostics()["primary_document_present"] is True


def test_phase98_sec_edgar_provider_rejects_unsafe_primary_document_name():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "AAPL unsafe filing document",
        goal=SearchGoal(
            goal_id="goal-sec-unsafe-document",
            query="AAPL unsafe filing document",
            max_sources=3,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "sec_cik": "0000320193",
                "accessionNumber": "000032019324000123",
                "primaryDocument": "../secret.htm",
            },
        ),
        plan=_plan(),
    )

    assert "sec_primary_filing_document" not in [source.metadata["source_kind"] for source in sources]
    assert (
        sources[0].uri
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123.txt"
    )
    assert provider.search_diagnostics()["primary_document_present"] is False


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
    citation_refs = result.final_answer["citation_refs"]
    assert len(citation_refs) >= 2
    assert any("goal-plan-1" in ref for ref in citation_refs)
    assert any("goal-plan-2" in ref for ref in citation_refs)


def test_phase98_agent_continues_from_sec_submissions_to_primary_filing_document():
    journal = JournalStore.in_memory()
    submissions_query = "AAPL latest 10-K submissions metadata"
    filing_query = "AAPL 2024 10-K primary filing document"
    primary_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
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
                        "text": "Find AAPL SEC filing metadata.",
                        "sequence_index": 1,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": submissions_query,
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
                        "text": "Fetch the primary SEC 10-K document from accession metadata.",
                        "sequence_index": 2,
                        "required_capabilities": ["finance.fundamentals_research"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "depends_on": ["node-1-finance_fundamentals"],
                            "capability_args": {
                                "retrieval.run": {
                                    "query": filing_query,
                                    "metadata": {
                                        "ticker": "AAPL",
                                        "sec_cik": "320193",
                                        "sec_accession_number": "0000320193-24-000123",
                                        "sec_primary_document": "aapl-20240928.htm",
                                        "sec_form": "10-K",
                                        "report_date": "2024-09-28",
                                    },
                                }
                            },
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
                    '{"filings":{"recent":{"form":["10-K"],"accessionNumber":["0000320193-24-000123"],'
                    '"primaryDocument":["aapl-20240928.htm"],"reportDate":["2024-09-28"]}}}'
                ),
                primary_url: (
                    "Apple 2024 Form 10-K official SEC filing. Net sales were reported in the primary filing document."
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
        "Research AAPL 2024 Form 10-K from SEC metadata to the primary filing.",
        mode="auto",
        semantic_mode="model",
    )

    assert result.status == "completed"
    actions = journal.records(task_id=result.task_id, kind="action")
    assert [record.data["name"] for record in actions] == ["retrieval.run", "retrieval.run"]
    assert actions[1].data["payload"]["metadata"]["sec_accession_number"] == "0000320193-24-000123"
    contexts = journal.records(task_id=result.task_id, kind="context")
    continuation_hints = contexts[1].data["state"]["agent_replan_hints"]["retrieval"]["suggested_filing_documents"]
    assert continuation_hints
    assert continuation_hints[0]["sec_accession_number"] == "0000320193-24-000123"
    assert continuation_hints[0]["sec_primary_document"] == "aapl-20240928.htm"
    assert continuation_hints[0]["suggested_payload"]["metadata"]["search_strategy"] == "structured"
    assert continuation_hints[0]["suggested_payload"]["metadata"]["sec_cik"] == "0000320193"
    search_attempts = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")
    primary_attempts = [
        attempt
        for attempt in search_attempts
        if attempt.data["sources"]
        and attempt.data["sources"][0]["metadata"]["source_kind"] == "sec_primary_filing_document"
    ]
    assert primary_attempts
    assert primary_attempts[0].data["sources"][0]["uri"] == primary_url
    fetch_uris = [
        attempt.data["uri"]
        for attempt in journal.records(task_id=result.task_id, kind="retrieval_fetch_attempt")
    ]
    assert primary_url in fetch_uris
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    citation_refs = result.final_answer["citation_refs"]
    assert len(citation_refs) >= 2
    assert any("goal-plan-1" in ref for ref in citation_refs)
    assert any("goal-plan-2" in ref for ref in citation_refs)


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-sec-test",
        goal_id="goal-sec-test",
        queries=["test"],
        max_sources=5,
        max_fetches=3,
    )
