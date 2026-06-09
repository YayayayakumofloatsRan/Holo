from kernel_v3.retrieval.contracts import EvidenceItem, ExtractedSpan, SearchGoal
from kernel_v3.retrieval.evidence_compaction import EvidenceCandidate, compact_evidence_candidates
from kernel_v3.retrieval.finance_metrics import finance_metric_intent_score


def test_finance_metric_intent_prefers_assets_over_equity_for_total_assets_query() -> None:
    query = "What was Bank of America's total assets as of year-end 2024?"

    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=assets concept=Assets value=3261519000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=shareholders equity concept=StockholdersEquity value=296000000000",
        query=query,
    )


def test_finance_metric_intent_prefers_energy_specific_total_revenue_concepts() -> None:
    chevron_query = "What was Chevron's total revenues for fiscal year 2024?"
    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=sales and other operating revenues "
        "concept=SalesAndOtherOperatingRevenue value=193414000000",
        query=chevron_query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=revenue concept=Revenues value=202792000000",
        query=chevron_query,
    )

    conoco_query = "What was ConocoPhillips' total revenues for fiscal year 2024?"
    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=total revenues and other income "
        "concept=TotalRevenuesAndOtherIncome value=56953000000",
        query=conoco_query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=revenue concept=Revenues value=54745000000",
        query=conoco_query,
    )


def test_finance_metric_intent_prefers_net_sales_for_costco_query() -> None:
    query = "What was Costco's net sales for fiscal year 2024?"

    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=net sales concept=SalesRevenueNet value=249625000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=revenue from contract "
        "concept=RevenueFromContractWithCustomerExcludingAssessedTax value=254453000000",
        query=query,
    )


def test_evidence_compaction_keeps_metric_intent_match_before_generic_metric() -> None:
    goal = SearchGoal(
        goal_id="goal-chevron",
        query="What was Chevron's total revenues for fiscal year 2024?",
        metadata={"research_profile": "finance_fundamentals"},
    )
    selected, rejected, diagnostics = compact_evidence_candidates(
        [
            _candidate(
                "generic-revenue",
                "fy=2024 period=annual metric=revenue concept=Revenues value=202792000000",
            ),
            _candidate(
                "sales-other",
                "fy=2024 period=annual metric=sales and other operating revenues "
                "concept=SalesAndOtherOperatingRevenue value=193414000000",
            ),
        ],
        goal=goal,
        research_profile=None,
        limit=1,
    )

    assert [candidate.evidence.evidence_id for candidate in selected] == ["sales-other"]
    assert [item["evidence_id"] for item in rejected] == ["generic-revenue"]
    assert diagnostics["selected_count"] == 1


def _candidate(evidence_id: str, text: str) -> EvidenceCandidate:
    span = ExtractedSpan(
        span_id=f"span-{evidence_id}",
        goal_id="goal-chevron",
        document_id=f"doc-{evidence_id}",
        source_id="sec-companyfacts",
        text=text,
        start_offset=0,
        end_offset=len(text),
        score=0.9,
        metadata={},
    )
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        goal_id=span.goal_id,
        span_id=span.span_id,
        document_id=span.document_id,
        source_id=span.source_id,
        artifact_id=f"artifact-{evidence_id}",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
        title="SEC companyfacts JSON",
        text=text,
        score=0.9,
        payload_hash="hash",
        diagnostics={
            "source_assessment": {"authority_score": 1.0},
            "qualification": {"profile_numeric_fact_present": True},
        },
    )
    return EvidenceCandidate(evidence=evidence, span=span)
