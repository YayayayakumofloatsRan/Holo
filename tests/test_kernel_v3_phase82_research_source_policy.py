from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, finance_fundamentals_profile
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.rank import rank_sources


def test_phase82_finance_profile_prefers_primary_filing_sources_over_generic_web() -> None:
    profile = finance_fundamentals_profile()
    weak = _source(
        "src-blog",
        "https://example.com/aapl-analysis",
        "AAPL Apple revenue risk analysis 10-K margin growth",
        "AAPL Apple revenue risk analysis 10-K margin growth",
    )
    filing = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "Apple annual report.",
    )

    ranked = rank_sources(
        SearchGoal(goal_id="goal-rank-finance", query="AAPL Apple revenue risk analysis 10-K margin growth"),
        [weak, filing],
        research_profile=profile,
    )

    assert ranked[0].source_id == "src-sec"
    assert ranked[0].metadata["source_assessment"]["source_family"] == "regulatory_filing"
    assert ranked[0].metadata["source_assessment"]["usable_as_primary"] is True
    assert "authority:primary" in ranked[0].reasons


def test_phase82_finance_retrieval_rejects_generic_web_as_final_primary_evidence() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 10-K revenue": [
                    _source(
                        "src-generic",
                        "https://example.com/aapl",
                        "AAPL 2024 10-K revenue",
                        "A third-party summary repeats Apple revenue.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({"https://example.com/aapl": "AAPL 2024 10-K revenue was discussed here."}),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-weak",
            query="AAPL 2024 10-K revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-weak",
        run_id="run-1",
    )

    assert report.status == "insufficient_evidence"
    assert report.diagnostics["reason"] == "no_primary_source_for_research_profile"
    assert report.diagnostics["source_authority"]["primary_source_count"] == 0
    assessment = journal.records(task_id="task-finance-weak", kind="retrieval_source_assessment")[0].data
    assert assessment["assessments"][0]["authority_level"] == "weak"
    assert assessment["assessments"][0]["warnings"] == ["not_primary_source_for_profile", "weak_source_family"]


def test_phase82_finance_retrieval_with_no_sources_keeps_plain_insufficient_evidence_reason() -> None:
    journal = JournalStore.in_memory()
    report = RetrievalOperator(
        search_provider=FakeSearchProvider({"missing": []}),
        fetch_provider=FakeFetchProvider({}),
    ).run(
        SearchGoal(
            goal_id="goal-finance-empty",
            query="missing",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-finance-empty",
        run_id="run-1",
    )

    assert report.status == "insufficient_evidence"
    assert report.diagnostics["reason"] == "insufficient_evidence"
    assert report.diagnostics["source_authority"]["primary_source_count"] == 0


def test_phase82_finance_retrieval_accepts_primary_filing_evidence_and_journals_assessment() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 10-K revenue": [
                    _source(
                        "src-sec",
                        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
                        "Apple Form 10-K",
                        "AAPL 2024 10-K revenue from annual report.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider(
            {"https://www.sec.gov/Archives/edgar/data/320193/filing.htm": "AAPL 2024 10-K revenue from annual report."}
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-finance-sec",
            query="AAPL 2024 10-K revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-finance-sec",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert report.diagnostics["source_authority"]["primary_source_count"] == 1
    assert report.diagnostics["network_access"] is False
    assert report.diagnostics["budget"]["max_spans_per_document"] == 1
    plan = journal.records(task_id="task-finance-sec", kind="retrieval_query_plan")[0].data
    assert plan["diagnostics"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert plan["diagnostics"]["budget"]["max_fetches"] == 3
    evidence = journal.records(task_id="task-finance-sec", kind="retrieval_evidence")[0].data
    assert evidence["diagnostics"]["source_assessment"]["source_family"] == "regulatory_filing"
    assert evidence["diagnostics"]["source_assessment"]["usable_as_primary"] is True
    kinds = [record.kind for record in journal.records(task_id="task-finance-sec")]
    assert "retrieval_source_assessment" in kinds
    assert kinds.index("retrieval_source_assessment") < kinds.index("retrieval_rank_sources")


def test_phase82_source_family_can_be_declared_by_provider_metadata() -> None:
    assessment = assess_search_source(
        _source(
            "src-ir",
            "https://assets.example.test/report.pdf",
            "Investor presentation",
            "Quarterly investor deck",
            metadata={"source_family": "company_ir"},
        ),
        profile=finance_fundamentals_profile(),
    )

    assert assessment.source_family == "company_ir"
    assert assessment.usable_as_primary is True
    assert assessment.reasons[0] == "metadata_source_family"


def test_phase82_model_taskgraph_capability_args_reach_retrieval_without_agent_domain_logic() -> None:
    goal = "AAPL 2024 10-K revenue"
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieval_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "retrieval_research",
                        "text": goal,
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}
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
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                goal: [
                    _source(
                        "src-generic",
                        "https://example.com/aapl",
                        "AAPL 2024 10-K revenue",
                        "A third-party summary repeats Apple revenue.",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({"https://example.com/aapl": "AAPL 2024 10-K revenue was discussed."}),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(goal, mode="auto", semantic_mode="model")

    assert result.status == "failed"
    action = journal.records(task_id=result.task_id, kind="action")[0].data
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[0].data
    assert report["status"] == "insufficient_evidence"
    assert report["diagnostics"]["reason"] == "no_primary_source_for_research_profile"


def _source(
    source_id: str,
    uri: str,
    title: str,
    snippet: str,
    *,
    metadata: dict | None = None,
) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
        metadata=dict(metadata or {}),
    )
