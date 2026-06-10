from kernel_v3.agent import AgentRuntime, FinalAnswer
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    DirectUrlSearchProvider,
    FakeFetchProvider,
    FakeSearchProvider,
    FallbackSearchProvider,
    FetchedDocument,
    QueryPlan,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
    SecEdgarSearchProvider,
)
from kernel_v3.retrieval.evaluate import EvidenceEvaluator
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.rank import rank_sources


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
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://www.sec.gov/edgar/browse/?CIK=0000320193",
        "https://www.sec.gov/files/company_tickers_exchange.json",
        "https://www.sec.gov/edgar/search/#/q=AAPL",
    ]
    assert all(source.metadata["authority_level"] == "primary" for source in sources)
    assert provider.search_diagnostics()["cik_present"] is True


def test_phase98_sec_companyfacts_ranks_before_submissions_for_finance_evidence():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-sec-ranking",
        query="CIK0001045810 Revenues NetIncomeLoss Assets Liabilities CashAndCashEquivalents",
        max_sources=5,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "sec_cik": "1045810",
            "source_authority_requirement": "primary",
        },
    )
    sources = provider.search(goal.query, goal=goal, plan=_plan())

    ranked = rank_sources(goal, sources)
    ranked_kinds = [item.metadata["source_kind"] for item in ranked]

    assert ranked_kinds.index("sec_companyfacts_json") < ranked_kinds.index("sec_submissions_json")


def test_sec_edgar_provider_uses_root_goal_for_issuer_candidates():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-root-issuer",
        query="target revenue 2022",
        max_sources=10,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "root_goal": "Pfizer acquisition of Seagen transaction EV revenue multiple",
        },
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    ciks = {source.metadata.get("sec_cik") for source in sources}

    assert "0000078003" in ciks
    assert "0001060736" in ciks


def test_phase98_sec_companyfacts_extracts_latest_annual_metric_summary_before_old_facts():
    goal = SearchGoal(
        goal_id="goal-sec-companyfacts-extract",
        query="AAPL CIK 320193 companyfacts revenue net income eps",
        max_spans_per_document=2,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-companyfacts",
        goal_id=goal.goal_id,
        source_id="source-sec-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        title="SEC companyfacts JSON for CIK 0000320193",
        artifact_id="artifact-sec-companyfacts",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_apple_companyfacts_json())

    assert spans
    first = spans[0].text
    assert "SEC companyfacts annual financial summary" in first
    assert "fy=2024" in first
    assert "metric=revenue" in first
    assert "value=391035000000" in first
    assert "metric=net income" in first
    assert "value=93736000000" in first
    assert "metric=diluted earnings per share" in first
    assert "value=6.08" in first
    assert "fy=2017" not in first


def test_sec_companyfacts_extracts_inventory_and_cost_inputs_for_dio():
    goal = SearchGoal(
        goal_id="goal-sec-companyfacts-dio",
        query="HD LOW FY2024 DIO inventory cost of goods sold companyfacts",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-companyfacts-dio",
        goal_id=goal.goal_id,
        source_id="source-sec-companyfacts-dio",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000354950.json",
        title="SEC companyfacts JSON for CIK 0000354950",
        artifact_id="artifact-sec-companyfacts-dio",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_retail_companyfacts_json())
    text = "\n".join(span.text for span in spans)

    assert "metric=inventory" in text
    assert "value=23511000000" in text
    assert "metric=cost of goods sold" in text
    assert "value=101899000000" in text


def test_sec_companyfacts_extracts_ev_ebitda_component_inputs():
    goal = SearchGoal(
        goal_id="goal-sec-companyfacts-ev-ebitda",
        query="EV/EBITDA market cap debt cash net income tax depreciation amortization companyfacts",
        max_spans_per_document=8,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "valuation",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-companyfacts-ev-ebitda",
        goal_id=goal.goal_id,
        source_id="source-sec-companyfacts-ev-ebitda",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000354950.json",
        title="SEC companyfacts JSON for CIK 0000354950",
        artifact_id="artifact-sec-companyfacts-ev-ebitda",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_retail_companyfacts_json())
    text = "\n".join(span.text for span in spans)

    assert "metric=cash and cash equivalents" in text
    assert "val=2800000000" in text
    assert "metric=debt" in text
    assert "val=12000000000" in text
    assert "metric=depreciation and amortization" in text
    assert "val=2600000000" in text
    assert "metric=income tax expense" in text
    assert "val=2100000000" in text


def test_phase98_sec_companyfacts_extracts_financial_sector_revenue_concepts():
    goal = SearchGoal(
        goal_id="goal-sec-financial-sector-companyfacts",
        query="Goldman Sachs net revenues 2024 10-K",
        max_spans_per_document=2,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-gs-companyfacts",
        goal_id=goal.goal_id,
        source_id="source-sec-gs-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000886982.json",
        title="SEC companyfacts JSON for CIK 0000886982",
        artifact_id="artifact-sec-gs-companyfacts",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_financial_companyfacts_json())

    assert spans
    first = spans[0].text
    assert "SEC companyfacts annual financial summary" in first
    assert "entityName=The Goldman Sachs Group, Inc." in first
    assert "fy=2024" in first
    assert "metric=net revenues" in first
    assert "concept=RevenuesNetOfInterestExpense" in first
    assert "value=53512000000" in first
    assert "metric=basic earnings per share" in first
    assert "value=40.62" in first


def test_sec_companyfacts_extracts_banking_interest_and_leverage_metrics():
    goal = SearchGoal(
        goal_id="goal-sec-bank-companyfacts",
        query="JPMorgan Chase net interest income liabilities equity debt to equity 2024",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-jpm-companyfacts",
        goal_id=goal.goal_id,
        source_id="source-sec-jpm-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000019617.json",
        title="SEC companyfacts JSON for CIK 0000019617",
        artifact_id="artifact-sec-jpm-companyfacts",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_bank_companyfacts_json())
    text = " ".join(span.text for span in spans)

    assert "metric=net interest income" in text
    assert "value=92583000000" in text
    assert "metric=liabilities" in text
    assert "value=3658056000000" in text
    assert "metric=shareholders equity" in text
    assert "value=344758000000" in text


def test_sec_companyfacts_extracts_sector_specific_revenue_concepts():
    goal = SearchGoal(
        goal_id="goal-sec-sector-revenue-companyfacts",
        query="Chevron sales and other operating revenues NextEra operating revenues 2024",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-sector-companyfacts",
        goal_id=goal.goal_id,
        source_id="source-sec-sector-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
        title="SEC companyfacts JSON for CIK 0000093410",
        artifact_id="artifact-sec-sector-companyfacts",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_sector_revenue_companyfacts_json())
    text = " ".join(span.text for span in spans)

    assert "metric=sales and other operating revenues" in text
    assert "value=193414000000" in text
    assert "metric=operating revenues" in text
    assert "value=24753000000" in text


def test_phase98_sec_companyfacts_compaction_selects_requested_income_metrics_over_newer_balance_sheet_noise():
    source = SearchSource(
        source_id="src-sec-companyfacts-aapl",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        title="SEC companyfacts JSON for CIK 0000320193",
        snippet="Official SEC XBRL companyfacts for Apple Inc.",
        provider="fake_search",
        metadata={
            "source_family": "structured_regulatory_data",
            "source_kind": "sec_companyfacts_json",
        },
    )
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"AAPL CIK 320193 companyfacts revenue net income eps": [source]}),
        fetch_provider=FakeFetchProvider(
            {
                source.uri: {
                    "status": "ok",
                    "body": _apple_companyfacts_json(),
                    "mime_type": "application/json",
                }
            }
        ),
        evaluator=EvidenceEvaluator(),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-sec-companyfacts-income",
            query="AAPL CIK 320193 companyfacts revenue net income eps",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "finance_fundamentals",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-sec-companyfacts-income",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    evidence_rows = [record.data for record in journal.records(task_id="task-sec-companyfacts-income", kind="retrieval_evidence")]
    assert evidence_rows
    selected_text = " ".join(row["text"] for row in evidence_rows)
    assert "fy=2024" in selected_text
    assert "metric=revenue" in selected_text
    assert "value=391035000000" in selected_text
    assert "metric=net income" in selected_text
    assert "value=93736000000" in selected_text
    assert "metric=diluted earnings per share" in selected_text
    assert "value=6.08" in selected_text
    assert "fy=2026" not in selected_text
    diagnostics = report.diagnostics["evidence_compaction"]
    assert "revenue" in diagnostics["selected_facets"]
    assert "net_income" in diagnostics["selected_facets"]
    assert "eps" in diagnostics["selected_facets"]


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


def test_phase98_sec_edgar_provider_uses_builtin_issuer_registry_for_common_company_name():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "NVIDIA fundamentals revenue net income",
        goal=SearchGoal(
            goal_id="goal-nvidia-name",
            query="NVIDIA fundamentals revenue net income",
            max_sources=8,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan(),
    )

    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json" in [source.uri for source in sources]
    diagnostics = provider.search_diagnostics()
    assert diagnostics["ticker"] == "NVDA"
    assert diagnostics["cik_present"] is True
    assert "builtin_issuer_registry" in diagnostics["identity_sources"]


def test_phase98_sec_edgar_provider_is_profile_gated():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "AAPL CIK0000320193",
        goal=SearchGoal(goal_id="goal-no-profile", query="AAPL CIK0000320193"),
        plan=_plan(),
    )

    assert sources == []
    assert provider.search_diagnostics()["reason"] == "not_finance_profile"


def test_phase98_agent_infers_finance_profile_from_finance_intent_kind_without_capability_marker():
    journal = JournalStore.in_memory()
    goal = "Use SEC companyfacts to summarize NVIDIA revenue."
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "finance_fundamentals_research",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "finance_fundamentals_research",
                        "text": goal,
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "CIK0001045810 Revenues NetIncomeLoss",
                                    "metadata": {"sec_cik": "1045810"},
                                }
                            }
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            },
            "planner.propose": {
                "action_id": "act-sec-companyfacts",
                "kind": "tool",
                "name": "retrieval.run",
                "description": "fetch SEC companyfacts",
                "payload": {
                    "query": "CIK0001045810 Revenues NetIncomeLoss",
                    "metadata": {"sec_cik": "1045810"},
                },
                "reasons": ["use official SEC companyfacts"],
                "score": 0.95,
                "side_effect_class": "read",
            },
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([SecEdgarSearchProvider()]),
        fetch_provider=FakeFetchProvider(
            {
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json": (
                    "SEC companyfacts JSON includes NVIDIA Revenues unit USD val 81615000000 "
                    "and NetIncomeLoss unit USD val 18775000000."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(goal, mode="auto", semantic_mode="model", planner_mode="model")

    action = journal.records(task_id=result.task_id, kind="action")[0]
    assert action.data["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    assert any(
        source["metadata"].get("source_kind") == "sec_companyfacts_json"
        for source in search.data["sources"]
    )


def test_phase98_agent_preserves_semantic_query_and_source_url_for_direct_sec_payload():
    journal = JournalStore.in_memory()
    sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    goal = f"Summarize NVIDIA revenue and net income from {sec_url}"
    fabric = fake_fabric(
        {
            "semantic.intake": {
                "primary_intent": "retrieve_and_summarize_financials",
                "suggested_mode": "retrieval_answer",
                "compound": False,
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "retrieve_and_summarize_financials",
                        "text": goal,
                        "sequence_index": 1,
                        "required_capabilities": ["retrieval.run"],
                        "risk": "read",
                        "status": "ready",
                        "metadata": {
                            "domain": "finance_fundamentals",
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "NVIDIA revenue net income SEC companyfacts",
                                    "url": sec_url,
                                }
                            },
                        },
                    }
                ],
                "blocked_capabilities": [],
                "warnings": [],
                "response_hint": None,
                "clarification_question": None,
            },
            "planner.propose": {
                "action_id": "act-sec-url-only",
                "kind": "tool",
                "name": "retrieval.run",
                "description": "fetch SEC companyfacts URL",
                "payload": {
                    "query": sec_url,
                    "metadata": {"search_strategy": "structured"},
                },
                "reasons": ["use supplied SEC URL"],
                "score": 0.95,
                "side_effect_class": "read",
            },
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([DirectUrlSearchProvider(), SecEdgarSearchProvider()]),
        fetch_provider=FakeFetchProvider(
            {
                sec_url: (
                    "SEC companyfacts official financial statements entityName=NVIDIA CORP "
                    "metric=revenue concept=Revenues value=81615000000 unit=USD form=10-K. "
                    "SEC companyfacts official financial statements entityName=NVIDIA CORP "
                    "metric=net income concept=NetIncomeLoss value=18775000000 unit=USD form=10-K."
                ),
            }
        ),
    )

    result = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=operator,
    ).run(goal, mode="auto", semantic_mode="model", planner_mode="model")

    action = journal.records(task_id=result.task_id, kind="action")[0]
    assert action.data["payload"]["query"] == "NVIDIA revenue net income SEC companyfacts"
    assert action.data["payload"]["metadata"]["source_urls"] == [sec_url]
    assert action.data["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    search = journal.records(task_id=result.task_id, kind="retrieval_search_attempt")[0]
    assert search.data["sources"][0]["uri"] == sec_url
    assert journal.records(task_id=result.task_id, kind="retrieval_evidence")


def test_phase98_final_answer_quality_requires_citation_from_explicit_source_url():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory())
    sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "execution_metadata": {
                "research_mission": {
                    "root_goal": f"Summarize NVIDIA revenue from {sec_url}",
                }
            }
        },
    )
    journal.append(
        task_id="task-quality",
        run_id="run-quality",
        step_id=None,
        kind="retrieval_citation",
        data={
            "citation_id": "cite-wrong",
            "goal_id": "goal-quality",
            "evidence_id": "ev-wrong",
            "artifact_id": "artifact-wrong",
            "uri": "https://example.com/not-sec",
            "title": "Wrong source",
            "quote": "Revenue example.",
            "span_start": 0,
            "span_end": 16,
            "metadata": {},
        },
    )
    wrong = FinalAnswer(
        answer="NVIDIA revenue was reported.",
        citation_refs=["cite-wrong"],
        used_evidence=["ev-wrong"],
        limitations=[],
        confidence=0.7,
        task_id="task-quality",
        run_id="run-quality",
        trace_refs=[],
    )

    assert "required_source_url_citation_missing" in runtime._final_answer_quality_gaps(wrong, recipe=recipe)

    journal.append(
        task_id="task-quality",
        run_id="run-quality",
        step_id=None,
        kind="retrieval_citation",
        data={
            "citation_id": "cite-sec",
            "goal_id": "goal-quality",
            "evidence_id": "ev-sec",
            "artifact_id": "artifact-sec",
            "uri": sec_url,
            "title": "SEC companyfacts",
            "quote": "Revenue SEC fact.",
            "span_start": 0,
            "span_end": 17,
            "metadata": {},
        },
    )
    correct = FinalAnswer(
        answer="NVIDIA revenue was reported.",
        citation_refs=["cite-sec"],
        used_evidence=["ev-sec"],
        limitations=[],
        confidence=0.9,
        task_id="task-quality",
        run_id="run-quality",
        trace_refs=[],
    )

    assert "required_source_url_citation_missing" not in runtime._final_answer_quality_gaps(correct, recipe=recipe)


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
                    "SEC companyfacts JSON includes Apple revenue facts with filing provenance. "
                    "Apple revenue was $391.0 billion and net income was $93.7 billion."
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
    assert len(citation_refs) >= 1
    evidence_kinds = [
        record.data["diagnostics"]["source_assessment"]["metadata"]["source_kind"]
        for record in journal.records(task_id=result.task_id, kind="retrieval_evidence")
    ]
    assert "sec_submissions_json" not in evidence_kinds
    assert "sec_companyfacts_json" in evidence_kinds


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
                    '{"filings":{"recent":{"form":["144","10-K"],'
                    '"accessionNumber":["0001950047-26-004044","0000320193-24-000123"],'
                    '"primaryDocument":["xslF345X05/primary_doc.xml","aapl-20240928.htm"],'
                    '"reportDate":["2026-05-05","2024-09-28"]}}}'
                ),
                primary_url: (
                    "Apple 2024 Form 10-K official SEC filing. "
                    "Net sales were $391.0 billion in the primary filing document."
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
    reports = journal.records(task_id=result.task_id, kind="retrieval_report")
    assert reports[0].data["diagnostics"]["reason"] in {
        "discovery_artifact_available",
        "evidence_with_citations",
    }
    if reports[0].data["diagnostics"]["reason"] == "discovery_artifact_available":
        assert reports[0].data["diagnostics"]["citation_count"] == 0
    decisions = journal.records(task_id=result.task_id, kind="termination_decision")
    assert [record.data["decision"] for record in decisions] == ["continue", "final_answer"]
    citation_refs = result.final_answer["citation_refs"]
    assert len(citation_refs) >= 1
    evidence_text = " ".join(
        record.data["text"]
        for record in journal.records(task_id=result.task_id, kind="retrieval_evidence")
    )
    assert "primary filing document" in evidence_text


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-sec-test",
        goal_id="goal-sec-test",
        queries=["test"],
        max_sources=5,
        max_fetches=3,
    )


def _apple_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"Apple Inc.",'
        '"cik":320193,'
        '"facts":{"us-gaap":{'
        '"Revenues":{"label":"Revenues","units":{"USD":['
        '{"val":229234000000,"fy":2017,"fp":"FY","form":"10-K","filed":"2017-11-03","end":"2017-09-30","accn":"0000320193-17-000070"},'
        '{"val":391035000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"NetIncomeLoss":{"label":"Net income","units":{"USD":['
        '{"val":48351000000,"fy":2017,"fp":"FY","form":"10-K","filed":"2017-11-03","end":"2017-09-30","accn":"0000320193-17-000070"},'
        '{"val":93736000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"EarningsPerShareDiluted":{"label":"Diluted earnings per share","units":{"USD/shares":['
        '{"val":9.21,"fy":2017,"fp":"FY","form":"10-K","filed":"2017-11-03","end":"2017-09-30","accn":"0000320193-17-000070"},'
        '{"val":6.08,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"Assets":{"label":"Assets","units":{"USD":['
        '{"val":371082000000,"fy":2026,"fp":"Q2","form":"10-Q","filed":"2026-05-01","end":"2026-03-28","frame":"CY2026Q1I","accn":"0000320193-26-000013"}'
        "]}}"
        "}}}"
    )


def _retail_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"HOME DEPOT, INC.",'
        '"cik":354950,'
        '"facts":{"us-gaap":{'
        '"InventoryNet":{"label":"Merchandise inventories","units":{"USD":['
        '{"val":22119000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-03-15","end":"2024-02-01","accn":"0000354950-24-000010"},'
        '{"val":23511000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"CostOfGoodsAndServicesSold":{"label":"Cost of goods sold","units":{"USD":['
        '{"val":95520000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-03-15","end":"2024-02-01","accn":"0000354950-24-000010"},'
        '{"val":101899000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"RevenueFromContractWithCustomerExcludingAssessedTax":{"label":"Net sales","units":{"USD":['
        '{"val":157403000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"CashAndCashEquivalentsAtCarryingValue":{"label":"Cash and cash equivalents","units":{"USD":['
        '{"val":2800000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"DebtLongtermAndShorttermCombinedAmount":{"label":"Debt, long-term and short-term combined amount","units":{"USD":['
        '{"val":12000000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"DepreciationDepletionAndAmortization":{"label":"Depreciation, depletion and amortization","units":{"USD":['
        '{"val":2600000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}},"
        '"IncomeTaxExpenseBenefit":{"label":"Income tax expense","units":{"USD":['
        '{"val":2100000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-03-14","end":"2025-02-01","accn":"0000354950-25-000010"}'
        "]}}"
        "}}}"
    )


def _financial_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"The Goldman Sachs Group, Inc.",'
        '"cik":886982,'
        '"facts":{"us-gaap":{'
        '"RevenuesNetOfInterestExpense":{"label":"Revenues, net of interest expense","units":{"USD":['
        '{"val":46521000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-23","end":"2023-12-31","accn":"0000886982-24-000006"},'
        '{"val":53512000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000886982-25-000007"}'
        "]}},"
        '"EarningsPerShareBasic":{"label":"Basic earnings per share","units":{"USD/shares":['
        '{"val":22.95,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-23","end":"2023-12-31","accn":"0000886982-24-000006"},'
        '{"val":40.62,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000886982-25-000007"}'
        "]}},"
        '"Assets":{"label":"Assets","units":{"USD":['
        '{"val":1636994000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000886982-25-000007"}'
        "]}}"
        "}}}"
    )


def _bank_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"JPMorgan Chase & Co.",'
        '"cik":19617,'
        '"facts":{"us-gaap":{'
        '"NetInterestIncome":{"label":"Net interest income","units":{"USD":['
        '{"val":92583000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-14","end":"2024-12-31","accn":"0000019617-25-000257"}'
        "]}},"
        '"Liabilities":{"label":"Liabilities","units":{"USD":['
        '{"val":3658056000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-14","end":"2024-12-31","accn":"0000019617-25-000257"}'
        "]}},"
        '"StockholdersEquity":{"label":"Stockholders equity","units":{"USD":['
        '{"val":344758000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-14","end":"2024-12-31","accn":"0000019617-25-000257"}'
        "]}}"
        "}}}"
    )


def _sector_revenue_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"Sector Revenue Example",'
        '"cik":93410,'
        '"facts":{"us-gaap":{'
        '"SalesAndOtherOperatingRevenue":{"label":"Sales and Other Operating Revenues","units":{"USD":['
        '{"val":193414000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000093410-25-000009"}'
        "]}},"
        '"OperatingRevenues":{"label":"Operating revenues","units":{"USD":['
        '{"val":24753000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-15","end":"2024-12-31","accn":"0000753308-25-000010"}'
        "]}}"
        "}}}"
    )
