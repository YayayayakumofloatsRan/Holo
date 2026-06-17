from kernel_v3.agent import AgentRuntime, FinalAnswer
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.context import ArtifactStore
from kernel_v3.finance.fact_ledger import build_finance_fact_ledger
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    DirectUrlSearchProvider,
    CitationItem,
    EvidenceItem,
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
        "https://www.sec.gov/cgi-bin/browse-edgar?CIK=AAPL&owner=exclude&action=getcompany&count=100",
        "https://www.sec.gov/files/company_tickers_exchange.json",
    ]
    assert all(source.metadata["authority_level"] == "primary" for source in sources)
    assert provider.search_diagnostics()["cik_present"] is True


def test_sec_edgar_provider_adds_issuer_browse_source_for_ticker_only_queries():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "TJX Q4 fiscal 2025 pre-tax margin 10-K earnings",
        goal=SearchGoal(
            goal_id="goal-ticker-only-sec",
            query="TJX Q4 fiscal 2025 pre-tax margin 10-K earnings",
            max_sources=5,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan(),
    )

    kinds = [source.metadata["source_kind"] for source in sources]
    assert "sec_edgar_browse_ticker" in kinds
    assert "sec_ticker_cik_directory" in kinds
    assert any(source.uri.endswith("CIK=TJX&owner=exclude&action=getcompany&count=100") for source in sources)


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


def test_sec_edgar_provider_adds_targeted_companyconcept_sources_for_leverage_questions():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-sec-companyconcept-debt-equity",
        query="JPMorgan Chase debt-to-equity ratio 2024 liabilities stockholders equity SEC companyfacts",
        max_sources=12,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "ticker": "JPM",
            "sec_cik": "19617",
        },
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    concept_sources = [source for source in sources if source.metadata.get("source_kind") == "sec_companyconcept_json"]
    concept_names = {source.metadata.get("sec_concept") for source in concept_sources}
    uris = {source.uri for source in concept_sources}

    assert "Liabilities" in concept_names
    assert "StockholdersEquity" in concept_names
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000019617/us-gaap/Liabilities.json" in uris
    assert (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000019617/us-gaap/StockholdersEquity.json"
        in uris
    )


def test_sec_companyconcept_sources_are_kept_together_for_formula_inputs():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-sec-companyconcept-rank",
        query="JPMorgan Chase debt-to-equity ratio 2024 liabilities stockholders equity",
        max_sources=12,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "ticker": "JPM",
            "sec_cik": "19617",
        },
    )

    ranked = rank_sources(goal, provider.search(goal.query, goal=goal, plan=_plan()))
    ranked_concepts = [
        source.metadata.get("sec_concept")
        for source in ranked
        if source.metadata.get("source_kind") == "sec_companyconcept_json"
    ]

    assert set(ranked_concepts[:3]) == {
        "StockholdersEquity",
        "Liabilities",
        "DebtLongtermAndShorttermCombinedAmount",
    }


def test_sec_edgar_provider_adds_capital_intensity_companyconcept_sources():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-sec-companyconcept-capital-intensity",
        query="Is 3M a capital-intensive business based on FY2022 data?",
        max_sources=16,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "ticker": "MMM",
            "sec_cik": "66740",
        },
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    concept_names = {
        source.metadata.get("sec_concept")
        for source in sources
        if source.metadata.get("source_kind") == "sec_companyconcept_json"
    }

    assert {
        "Revenues",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "NetCashProvidedByUsedInOperatingActivities",
        "PropertyPlantAndEquipmentNet",
        "Assets",
        "NetIncomeLoss",
    }.issubset(concept_names)


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


def test_sec_edgar_provider_uses_benchmark_doc_metadata_for_issuer_candidate():
    provider = SecEdgarSearchProvider()
    goal = SearchGoal(
        goal_id="goal-financebench-doc-target",
        query="3M 2018 10k capital expenditure cash flow statement",
        max_sources=8,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "benchmark_doc_retrieval": True,
            "company": "3M",
            "doc_type": "10k",
            "doc_period": "2018",
            "source_url": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
        },
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    ciks = [source.metadata.get("sec_cik") for source in sources]

    assert "0000066740" in ciks
    assert all(cik != "0000027419" for cik in ciks if cik)


def test_sec_edgar_provider_freezes_benchmark_doc_target_when_mission_mentions_target_label():
    provider = SecEdgarSearchProvider()
    prompt = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself.\n\n"
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf\n"
        "Company: 3M\n"
        "Document: 3M_2018_10K\n"
        "Document type: 10k\n"
        "Document period: 2018\n\n"
        "What is the FY2018 capital expenditure amount for 3M?"
    )
    goal = SearchGoal(
        goal_id="goal-financebench-doc-target-frozen",
        query="3M 2018 10k capital expenditure cash flow statement",
        max_sources=8,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "benchmark_doc_retrieval": True,
            "company": "3M",
            "doc_type": "10k",
            "doc_period": "2018",
            "research_mission": {"root_goal": prompt},
        },
    )

    sources = provider.search(goal.query, goal=goal, plan=_plan())
    ciks = [source.metadata.get("sec_cik") for source in sources]

    assert "0000066740" in ciks
    assert all(cik != "0000027419" for cik in ciks if cik)


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


def test_sec_companyfacts_extracts_capital_expenditures_for_cash_flow_questions():
    goal = SearchGoal(
        goal_id="goal-sec-companyfacts-capex",
        query="3M FY2018 capital expenditure amount cash flow statement",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "filing_document_qa",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-companyfacts-capex",
        goal_id=goal.goal_id,
        source_id="source-sec-companyfacts-capex",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
        title="SEC companyfacts JSON for CIK 0000066740",
        artifact_id="artifact-sec-companyfacts-capex",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_capex_companyfacts_json())
    text = "\n".join(span.text for span in spans)

    assert "metric=capital expenditures" in text
    assert "value=1577000000" in text
    assert "fy=2018" in text


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


def test_sec_companyconcept_extracts_targeted_stockholders_equity_fact():
    goal = SearchGoal(
        goal_id="goal-sec-companyconcept-equity",
        query="JPMorgan Chase debt-to-equity ratio 2024 stockholders equity",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-jpm-companyconcept-equity",
        goal_id=goal.goal_id,
        source_id="source-sec-jpm-companyconcept-equity",
        uri="https://data.sec.gov/api/xbrl/companyconcept/CIK0000019617/us-gaap/StockholdersEquity.json",
        title="SEC companyconcept JSON for CIK 0000019617 concept StockholdersEquity",
        artifact_id="artifact-sec-jpm-companyconcept-equity",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyconcept_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_jpm_stockholders_equity_companyconcept_json())
    text = " ".join(span.text for span in spans)

    assert "SEC companyfacts official financial statement" in text
    assert "concept=StockholdersEquity" in text
    assert "metric=shareholders equity" in text
    assert "value=344758000000" in text
    assert "fy=2024" in text


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


def test_sec_companyfacts_prioritizes_revenue_contract_line_over_generic_total_revenues():
    goal = SearchGoal(
        goal_id="goal-sec-chevron-total-revenues",
        query="What was Chevron's total revenues for fiscal year 2024?",
        max_spans_per_document=2,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
            "target_document_binding": {
                "company": "Chevron",
                "doc_period": "2024",
                "doc_type": "10-K",
                "required_line_item": "total revenues",
            },
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-chevron-companyfacts",
        goal_id=goal.goal_id,
        source_id="source-sec-chevron-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
        title="SEC companyfacts JSON for CIK 0000093410",
        artifact_id="artifact-sec-chevron-companyfacts",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_chevron_companyfacts_json())

    assert spans
    assert "concept=RevenueFromContractWithCustomerExcludingAssessedTax" in spans[0].text
    assert "value=193414000000" in spans[0].text
    assert "concept=Revenues" not in spans[0].text


def test_sec_filing_html_extracts_annual_net_sales_sentence_fact():
    goal = SearchGoal(
        goal_id="goal-sec-costco-net-sales-html",
        query="What was Costco's net sales for fiscal year 2024?",
        max_spans_per_document=4,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-costco-10k-html",
        goal_id=goal.goal_id,
        source_id="source-sec-costco-10k-html",
        uri="https://www.sec.gov/Archives/edgar/data/909832/000090983224000049/cost-20240901.htm",
        title="SEC 10-K primary filing document reportDate=2024-09-01 filed=2024-10-09 description=10-K cost-20240901.htm",
        artifact_id="artifact-sec-costco-10k-html",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_primary_filing_document"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_costco_10k_html_with_net_sales_sentence())
    text = " ".join(span.text for span in spans)

    assert "html_sentence_fact" in text
    assert "metric=net sales" in text
    assert "fy=2024" in text
    assert "value=249,625" in text
    assert "scale=millions" in text

    evidence = [
        EvidenceItem(
            evidence_id="evidence-costco-net-sales",
            goal_id=goal.goal_id,
            span_id=spans[0].span_id,
            document_id=document.document_id,
            source_id=document.source_id,
            artifact_id=document.artifact_id,
            uri=document.uri,
            title=document.title,
            text=spans[0].text,
            score=spans[0].score,
            payload_hash=document.payload_hash,
        )
    ]
    citations = [
        CitationItem(
            citation_id="cite-costco-net-sales",
            goal_id=goal.goal_id,
            evidence_id=evidence[0].evidence_id,
            artifact_id=document.artifact_id,
            uri=document.uri,
            title=document.title,
            quote=spans[0].text[:240],
            span_start=0,
            span_end=min(240, len(spans[0].text)),
        )
    ]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert any(fact.metric == "net sales" and fact.fiscal_year == 2024 and fact.value == "249625000000" for fact in facts)


def test_sec_companyfacts_query_focus_exposes_rd_and_margin_inputs():
    goal = SearchGoal(
        goal_id="goal-sec-query-focus-margin",
        query="AAPL FY2024 research and development expense and net profit margin",
        max_spans_per_document=8,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-aapl-query-focus",
        goal_id=goal.goal_id,
        source_id="source-sec-aapl-query-focus",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        title="SEC companyfacts JSON for CIK 0000320193",
        artifact_id="artifact-sec-aapl-query-focus",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_apple_specialized_companyfacts_json())
    text = " ".join(span.text for span in spans)

    assert "metric=research and development expense" in text
    assert "value=31370000000" in text
    assert "metric=net income" in text
    assert "value=93736000000" in text
    assert "metric=revenue" in text
    assert "value=391035000000" in text


def test_sec_companyfacts_query_focus_exposes_segment_revenue_candidates():
    goal = SearchGoal(
        goal_id="goal-sec-meta-segment-query-focus",
        query="What was Meta's Family of Apps segment revenue for fiscal year 2024?",
        max_spans_per_document=6,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-meta-query-focus",
        goal_id=goal.goal_id,
        source_id="source-sec-meta-query-focus",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001326801.json",
        title="SEC companyfacts JSON for CIK 0001326801",
        artifact_id="artifact-sec-meta-query-focus",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_meta_segment_companyfacts_json())
    text = " ".join(span.text for span in spans)

    assert "metric=family of apps revenue" in text
    assert "value=164501000000" in text
    assert "metric=reality labs revenue" in text
    assert "value=2146000000" in text


def test_sec_companyfacts_query_focus_exposes_gross_and_operating_margin_inputs():
    goal = SearchGoal(
        goal_id="goal-sec-nvidia-margin-query-focus",
        query="Calculate NVIDIA gross margin and operating margin for fiscal year 2024 from SEC companyfacts.",
        max_spans_per_document=8,
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "research_task_kind": "finance_fundamentals",
        },
    )
    document = FetchedDocument(
        document_id="doc-sec-nvidia-query-focus",
        goal_id=goal.goal_id,
        source_id="source-sec-nvidia-query-focus",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
        title="SEC companyfacts JSON for CIK 0001045810",
        artifact_id="artifact-sec-nvidia-query-focus",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"source_metadata": {"source_kind": "sec_companyfacts_json"}},
    )

    spans = extract_spans(goal=goal, document=document, body=_nvidia_margin_companyfacts_json())
    text = " ".join(span.text for span in spans)

    assert "metric=gross profit" in text
    assert "value=44301000000" in text
    assert "metric=operating income" in text
    assert "value=32972000000" in text
    assert "metric=revenue" in text
    assert "value=60922000000" in text


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


def test_phase98_doc_retrieval_quality_accepts_cited_sec_structured_source_for_target_pdf():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory())
    target_pdf = "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf"
    sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"
    prompt = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        f"Source URL: {target_pdf}\n"
        "Company: 3M\n"
        "Document: 3M_2018_10K\n"
        "Document type: 10k\n"
        "Document period: 2018\n\n"
        "What is the FY2018 capital expenditure amount for 3M?"
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": {"research_mission": {"root_goal": prompt}}},
    )
    journal.append(
        task_id="task-doc-quality",
        run_id="run-doc-quality",
        step_id=None,
        kind="retrieval_citation",
        data={
            "citation_id": "cite-sec-companyfacts",
            "goal_id": "goal-doc-quality",
            "evidence_id": "ev-sec-companyfacts",
            "artifact_id": "artifact-sec-companyfacts",
            "uri": sec_url,
            "title": "SEC companyfacts JSON for CIK 0000066740",
            "quote": "metric=capital expenditures value=1577000000",
            "span_start": 0,
            "span_end": 46,
            "metadata": {},
        },
    )
    answer = FinalAnswer(
        answer="3M FY2018 capital expenditures were $1,577 million.",
        citation_refs=["cite-sec-companyfacts"],
        used_evidence=["ev-sec-companyfacts"],
        limitations=[],
        confidence=0.8,
        task_id="task-doc-quality",
        run_id="run-doc-quality",
        trace_refs=[],
    )

    assert "required_source_url_citation_missing" not in runtime._final_answer_quality_gaps(answer, recipe=recipe)


def test_phase98_doc_retrieval_quality_reads_compiled_capability_target():
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal, artifact_store=ArtifactStore.in_memory())
    target_pdf = "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf"
    sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "task_execution_plan": {
                "steps": [
                    {
                        "required_capabilities": ["retrieval.run"],
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": {
                                    "query": "3M 2018 10-K capital expenditures",
                                    "metadata": {
                                        "benchmark_doc_retrieval": True,
                                        "source_url": target_pdf,
                                        "source_urls": [target_pdf],
                                        "company": "3M",
                                        "doc_period": "2018",
                                    },
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    journal.append(
        task_id="task-doc-quality-compiled",
        run_id="run-doc-quality",
        step_id=None,
        kind="retrieval_citation",
        data={
            "citation_id": "cite-sec-companyfacts",
            "goal_id": "goal-doc-quality",
            "evidence_id": "ev-sec-companyfacts",
            "artifact_id": "artifact-sec-companyfacts",
            "uri": sec_url,
            "title": "SEC companyfacts JSON for CIK 0000066740",
            "quote": "metric=capital expenditures value=1577000000",
            "span_start": 0,
            "span_end": 46,
            "metadata": {},
        },
    )
    answer = FinalAnswer(
        answer="3M FY2018 capital expenditures were $1,577 million.",
        citation_refs=["cite-sec-companyfacts"],
        used_evidence=["ev-sec-companyfacts"],
        limitations=[],
        confidence=0.8,
        task_id="task-doc-quality-compiled",
        run_id="run-doc-quality",
        trace_refs=[],
    )

    assert "required_source_url_citation_missing" not in runtime._final_answer_quality_gaps(answer, recipe=recipe)


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


def _apple_specialized_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"Apple Inc.",'
        '"cik":320193,'
        '"facts":{"us-gaap":{'
        '"Revenues":{"label":"Revenues","units":{"USD":['
        '{"val":383285000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03","end":"2023-09-30","accn":"0000320193-23-000106"},'
        '{"val":391035000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"NetIncomeLoss":{"label":"Net income","units":{"USD":['
        '{"val":96995000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03","end":"2023-09-30","accn":"0000320193-23-000106"},'
        '{"val":93736000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"ResearchAndDevelopmentExpense":{"label":"Research and development expense","units":{"USD":['
        '{"val":29915000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03","end":"2023-09-30","accn":"0000320193-23-000106"},'
        '{"val":31370000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-11-01","end":"2024-09-28","accn":"0000320193-24-000123"}'
        "]}},"
        '"Assets":{"label":"Assets","units":{"USD":['
        '{"val":371082000000,"fy":2026,"fp":"Q2","form":"10-Q","filed":"2026-05-01","end":"2026-03-28","frame":"CY2026Q1I","accn":"0000320193-26-000013"}'
        "]}}"
        "}}}"
    )


def _meta_segment_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"Meta Platforms, Inc.",'
        '"cik":1326801,'
        '"facts":{"us-gaap":{'
        '"FamilyOfAppsRevenue":{"label":"Family of Apps revenue","units":{"USD":['
        '{"val":133010000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-02","end":"2023-12-31","accn":"0001326801-24-000012"},'
        '{"val":164501000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-01-31","end":"2024-12-31","accn":"0001326801-25-000017"}'
        "]}},"
        '"RealityLabsRevenue":{"label":"Reality Labs revenue","units":{"USD":['
        '{"val":1896000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-02","end":"2023-12-31","accn":"0001326801-24-000012"},'
        '{"val":2146000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-01-31","end":"2024-12-31","accn":"0001326801-25-000017"}'
        "]}},"
        '"Revenues":{"label":"Revenues","units":{"USD":['
        '{"val":164501000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-01-31","end":"2024-12-31","accn":"0001326801-25-000017"}'
        "]}}"
        "}}}"
    )


def _nvidia_margin_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"NVIDIA CORP",'
        '"cik":1045810,'
        '"facts":{"us-gaap":{'
        '"RevenueFromContractWithCustomerExcludingAssessedTax":{"label":"Revenue from Contract with Customer, Excluding Assessed Tax","units":{"USD":['
        '{"val":26974000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-02-24","end":"2023-01-29","accn":"0001045810-23-000017"},'
        '{"val":60922000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-02-21","end":"2024-01-28","accn":"0001045810-24-000029"}'
        "]}},"
        '"GrossProfit":{"label":"Gross profit","units":{"USD":['
        '{"val":15356000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-02-24","end":"2023-01-29","accn":"0001045810-23-000017"},'
        '{"val":44301000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-02-21","end":"2024-01-28","accn":"0001045810-24-000029"}'
        "]}},"
        '"OperatingIncomeLoss":{"label":"Operating income","units":{"USD":['
        '{"val":4224000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-02-24","end":"2023-01-29","accn":"0001045810-23-000017"},'
        '{"val":32972000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2024-02-21","end":"2024-01-28","accn":"0001045810-24-000029"}'
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


def _capex_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"3M COMPANY",'
        '"cik":66740,'
        '"facts":{"us-gaap":{'
        '"PaymentsToAcquirePropertyPlantAndEquipment":{"label":"Purchases of property, plant and equipment","units":{"USD":['
        '{"val":1456000000,"fy":2017,"fp":"FY","form":"10-K","filed":"2018-02-08","start":"2017-01-01","end":"2017-12-31","accn":"0001558370-18-000535"},'
        '{"val":1577000000,"fy":2018,"fp":"FY","form":"10-K","filed":"2019-02-07","start":"2018-01-01","end":"2018-12-31","accn":"0001558370-19-000470"},'
        '{"val":1680000000,"fy":2019,"fp":"FY","form":"10-K","filed":"2020-02-06","start":"2019-01-01","end":"2019-12-31","accn":"0001558370-20-000470"},'
        '{"val":1510000000,"fy":2020,"fp":"FY","form":"10-K","filed":"2021-02-05","start":"2020-01-01","end":"2020-12-31","accn":"0001558370-21-000470"},'
        '{"val":1600000000,"fy":2021,"fp":"FY","form":"10-K","filed":"2022-02-04","start":"2021-01-01","end":"2021-12-31","accn":"0001558370-22-000470"},'
        '{"val":1750000000,"fy":2022,"fp":"FY","form":"10-K","filed":"2023-02-03","start":"2022-01-01","end":"2022-12-31","accn":"0001558370-23-000470"},'
        '{"val":1830000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-02","start":"2023-01-01","end":"2023-12-31","accn":"0001558370-24-000470"},'
        '{"val":1720000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-07","start":"2024-01-01","end":"2024-12-31","accn":"0001558370-25-000470"},'
        '{"val":1800000000,"fy":2025,"fp":"FY","form":"10-K","filed":"2026-02-06","start":"2025-01-01","end":"2025-12-31","accn":"0001558370-26-000470"}'
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


def _jpm_stockholders_equity_companyconcept_json() -> str:
    return (
        "{"
        '"entityName":"JPMorgan Chase & Co.",'
        '"cik":19617,'
        '"taxonomy":"us-gaap",'
        '"tag":"StockholdersEquity",'
        '"label":"Stockholders equity",'
        '"units":{"USD":['
        '{"val":327878000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-16","end":"2023-12-31","accn":"0000019617-24-000272"},'
        '{"val":344758000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-14","end":"2024-12-31","accn":"0000019617-25-000270"},'
        '{"val":344758000000,"fy":2025,"fp":"FY","form":"10-K","filed":"2026-02-13","end":"2024-12-31","frame":"CY2024Q4I","accn":"0001628280-26-008131"}'
        "]}"
        "}"
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


def _costco_10k_html_with_net_sales_sentence() -> str:
    return """
    <html>
      <body>
        <div>Costco Wholesale Corporation 2024 Form 10-K</div>
        <div>(amounts in millions, except per share, share, membership fee, and warehouse count data)</div>
        <div>Fiscal 2024 highlights included the following:</div>
        <div>
          Net sales increased 5% to $249,625, driven by an increase in comparable sales
          and sales at new warehouses opened in 2023 and 2024, partially offset by one less week of sales in 2024;
        </div>
      </body>
    </html>
    """


def _chevron_companyfacts_json() -> str:
    return (
        "{"
        '"entityName":"Chevron Corp",'
        '"cik":93410,'
        '"facts":{"us-gaap":{'
        '"Revenues":{"label":"Revenues","units":{"USD":['
        '{"val":202792000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000093410-25-000009"}'
        "]}},"
        '"RevenueFromContractWithCustomerExcludingAssessedTax":{"label":"Revenue from Contract with Customer, Excluding Assessed Tax","units":{"USD":['
        '{"val":193414000000,"fy":2024,"fp":"FY","form":"10-K","filed":"2025-02-21","end":"2024-12-31","accn":"0000093410-25-000009"}'
        "]}}"
        "}}}"
    )
