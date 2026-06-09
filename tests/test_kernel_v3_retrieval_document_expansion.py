import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    CitationItem,
    EvidenceItem,
    FakeFetchProvider,
    FakeSearchProvider,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)
from kernel_v3.retrieval.evaluate import EvidenceEvaluator, qualify_evidence_candidate


def test_retrieval_expands_issuer_ir_page_links_into_report_documents():
    ir_page = SearchSource(
        source_id="issuer-ir-annuals",
        uri="https://ir.blackrock.com/financials/annual-reports-and-proxy/default.aspx",
        title="BlackRock annual reports",
        snippet="Issuer-hosted annual report and proxy materials page.",
        provider="fake_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "company_ir",
            "authority_level": "primary",
            "source_kind": "issuer_annual_reports",
        },
    )
    report_url = "https://ir.blackrock.com/files/doc_downloads/2025/02/Q4-24-10-K-Final.pdf"
    old_report_url = "https://s24.q4cdn.com/856567660/files/doc_financials/2012/ar/2012-Annual-Report.pdf"
    proxy_url = "https://s24.q4cdn.com/856567660/files/doc_financials/2024/ar/2024-Proxy-Statement_vF.pdf"
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider({"BlackRock 2024 total revenues annual report": [ir_page]}),
        fetch_provider=FakeFetchProvider(
            {
                ir_page.uri: (
                    "<html><body>"
                    f"<a href=\"{old_report_url}\">2012 Annual Report</a>"
                    f"<a href=\"{proxy_url}\">2024 Proxy Statement</a>"
                    "<a href=\"/files/doc_downloads/2025/02/Q4-24-10-K-Final.pdf\">"
                    "2024 Form 10-K annual report</a>"
                    "</body></html>"
                ),
                report_url: (
                    "BlackRock 2024 annual report. Total revenues were $20.4 billion in 2024. "
                    "This issuer-hosted Form 10-K filing also discusses net income and operations."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-ir-doc-expansion",
            query="BlackRock 2024 total revenues annual report",
            max_sources=4,
            max_fetches=2,
            max_spans_per_document=2,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-ir-doc-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-ir-doc-expansion", kind="retrieval_fetch_attempt")
    ]
    assert report_url in fetch_uris
    assert old_report_url not in fetch_uris
    assert proxy_url not in fetch_uris
    assert journal.records(task_id="task-ir-doc-expansion", kind="retrieval_document_expansion")
    assert report.diagnostics["document_expanded_source_count"] >= 1
    assert report.status == "sufficient"
    assert any(
        "20.4 billion" in record.data["text"]
        for record in journal.records(task_id="task-ir-doc-expansion", kind="retrieval_evidence")
    )


def test_sec_submissions_expand_to_primary_filing_even_when_companyfacts_exists():
    companyfacts = SearchSource(
        source_id="sec-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_companyfacts_json",
            "sec_cik": "0001364742",
        },
    )
    submissions = SearchSource(
        source_id="sec-submissions",
        uri="https://data.sec.gov/submissions/CIK0001364742.json",
        title="SEC submissions JSON for CIK 0001364742",
        snippet="Official SEC submissions metadata and primary document chronology.",
        provider="sec_edgar_structured_search",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "structured_regulatory_data",
            "authority_level": "primary",
            "source_kind": "sec_submissions_json",
            "sec_cik": "0001364742",
        },
    )
    primary_url = "https://www.sec.gov/Archives/edgar/data/1364742/000136474225000010/blk-20241231.htm"
    journal = JournalStore.in_memory()

    report = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"BlackRock total revenues fiscal year 2024 SEC 10-K": [companyfacts, submissions]}
        ),
        fetch_provider=FakeFetchProvider(
            {
                companyfacts.uri: (
                    "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
                    "fy=2023 period=annual form=10-K filed=2024-02-23 end=2023-12-31 "
                    "facts=metric=revenue value=11012000000"
                ),
                submissions.uri: json.dumps(
                    {
                        "cik": "1364742",
                        "filings": {
                            "recent": {
                                "accessionNumber": ["0001364742-25-000010", "0001364742-24-000009"],
                                "form": ["10-K", "10-K"],
                                "primaryDocument": ["blk-20241231.htm", "blk-20231231.htm"],
                                "reportDate": ["2024-12-31", "2023-12-31"],
                                "filingDate": ["2025-02-28", "2024-02-23"],
                            }
                        },
                    }
                ),
                primary_url: (
                    "BlackRock 2024 Form 10-K. Total revenues for fiscal year 2024 were "
                    "$20.4 billion. This official SEC filing covers reportDate=2024-12-31."
                ),
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-sec-submission-expansion",
            query="BlackRock total revenues fiscal year 2024 SEC 10-K",
            max_sources=5,
            max_fetches=4,
            max_spans_per_document=4,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_depth": "deep",
                "source_authority_requirement": "primary",
            },
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-sec-submission-expansion",
        run_id="run-1",
    )

    fetch_uris = [
        record.data["uri"]
        for record in journal.records(task_id="task-sec-submission-expansion", kind="retrieval_fetch_attempt")
    ]
    assert companyfacts.uri in fetch_uris
    assert submissions.uri in fetch_uris
    assert primary_url in fetch_uris
    assert report.status == "sufficient"
    assert any(
        "20.4 billion" in record.data["text"]
        for record in journal.records(task_id="task-sec-submission-expansion", kind="retrieval_evidence")
    )


def test_finance_evaluator_does_not_accept_filing_year_as_target_fiscal_year():
    evidence = EvidenceItem(
        evidence_id="ev-2023",
        goal_id="goal-period",
        span_id="span-2023",
        document_id="doc-2023",
        source_id="source-2023",
        artifact_id="artifact-2023",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        text=(
            "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
            "fy=2023 period=annual form=10-K filed=2024-02-23 end=2023-12-31 "
            "facts=metric=revenue value=11012000000"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-2023",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="fy=2023 period=annual form=10-K filed=2024-02-23",
        span_start=0,
        span_end=48,
        metadata={},
    )

    decision = EvidenceEvaluator().evaluate(
        goal=SearchGoal(
            goal_id="goal-period",
            query="What was BlackRock's total revenues for fiscal year 2024?",
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "source_authority_requirement": "primary",
            },
        ),
        evidence=[evidence],
        citations=[citation],
    )

    assert decision.status == "insufficient_evidence"
    assert decision.reason == "finance_target_period_missing"
    assert decision.diagnostics["finance_target_period"]["missing_years"] == ["2024"]


def test_finance_evaluator_rejects_companyfacts_subsidiary_entity_for_parent_company():
    evidence = EvidenceItem(
        evidence_id="ev-blackrock-finance",
        goal_id="goal-blackrock-parent",
        span_id="span-blackrock-finance",
        document_id="doc-blackrock-finance",
        source_id="source-blackrock-finance",
        artifact_id="artifact-blackrock-finance",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001364742.json",
        title="SEC companyfacts JSON for CIK 0001364742",
        text=(
            "SEC companyfacts official financial statements entityName=BLACKROCK FINANCE, INC. "
            "cik=1364742 source=SEC_XBRL_companyfacts "
            "SEC companyfacts annual financial summary entityName=BLACKROCK FINANCE, INC. "
            "cik=1364742 fy=2024 period=annual form=10-K filed=2025-02-23 end=2024-12-31 "
            "facts=metric=revenue concept=Revenues value=11012000000 val=11012000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-blackrock-finance",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="entityName=BLACKROCK FINANCE, INC.",
        span_start=0,
        span_end=36,
        metadata={},
    )

    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="What was BlackRock Inc.'s total revenues for fiscal year 2024?",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )
    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[], citations=[])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_companyfacts_entity_mismatch"
    assert decision.status == "insufficient_evidence"
    assert decision.reason == "insufficient_evidence"


def test_finance_evaluator_requires_specialized_segment_terms_for_segment_queries():
    evidence = EvidenceItem(
        evidence_id="ev-meta-total-revenue",
        goal_id="goal-meta-foa",
        span_id="span-meta-total-revenue",
        document_id="doc-meta-companyfacts",
        source_id="source-meta-companyfacts",
        artifact_id="artifact-meta-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0001326801.json",
        title="SEC companyfacts JSON for CIK 0001326801",
        text=(
            "SEC companyfacts annual financial summary entityName=Meta Platforms, Inc. "
            "cik=0001326801 fy=2024 period=annual form=10-K end=2024-12-31 "
            "facts=metric=revenue concept=RevenueFromContractWithCustomerExcludingAssessedTax "
            "value=164501000000 val=164501000000 unit=USD"
        ),
        score=0.9,
        payload_hash="hash",
        diagnostics={},
    )
    citation = CitationItem(
        citation_id="cite-meta-total-revenue",
        goal_id=evidence.goal_id,
        evidence_id=evidence.evidence_id,
        artifact_id=evidence.artifact_id,
        uri=evidence.uri,
        title=evidence.title,
        quote="fy=2024 revenue value=164501000000",
        span_start=0,
        span_end=36,
        metadata={},
    )
    goal = SearchGoal(
        goal_id=evidence.goal_id,
        query="What was Meta's Family of Apps segment revenue for fiscal year 2024?",
        metadata={
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_authority_requirement": "primary",
        },
    )

    qualification = qualify_evidence_candidate(goal=goal, evidence=evidence)
    decision = EvidenceEvaluator().evaluate(goal=goal, evidence=[evidence], citations=[citation])

    assert qualification["accepted"] is False
    assert qualification["reason"] == "finance_specialized_query_terms_missing"
    assert decision.status == "insufficient_evidence"
    assert decision.reason == "finance_specialized_query_terms_missing"
