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
    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=revenue "
        "concept=RevenueFromContractWithCustomerExcludingAssessedTax value=193414000000",
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


def test_finance_metric_intent_prefers_statement_net_revenues_over_derivative_amounts() -> None:
    query = "What were Goldman Sachs' net revenues for fiscal year 2024?"

    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=net revenues "
        "concept=RevenuesNetOfInterestExpense label=Net revenues value=53512000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=derivative revenues "
        "concept=DerivativeFinancialInstrumentsRevenue label=Derivative instruments value=112000000000",
        query=query,
    )

    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=total net revenues label=Total net revenues value=53512000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=interest income label=Interest income value=81200000000",
        query=query,
    )


def test_finance_metric_intent_prefers_liabilities_and_equity_for_debt_to_equity() -> None:
    query = "What was JPMorgan Chase's debt-to-equity ratio as of year-end 2024?"

    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=liabilities concept=Liabilities value=3658056000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=revenue concept=Revenues value=177556000000",
        query=query,
    )
    assert finance_metric_intent_score(
        "fy=2024 period=annual metric=shareholders equity concept=StockholdersEquity value=344758000000",
        query=query,
    ) > finance_metric_intent_score(
        "fy=2024 period=annual metric=net income concept=NetIncomeLoss value=58500000000",
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


def test_evidence_compaction_preserves_target_bound_line_item_slots() -> None:
    goal = SearchGoal(
        goal_id="goal-3m-capital-intensity",
        query="Is 3M a capital-intensive business based on FY2022 data?",
        metadata={"research_profile": "finance_fundamentals"},
    )
    selected, rejected, diagnostics = compact_evidence_candidates(
        [
            _candidate(
                "fair-value-revenue",
                "fy=2022 period=annual metric=revenue concept=FairValueAssetSales value=3000000",
                target_line_item="revenue",
                target_period="FY2022",
                start_offset=500,
            ),
            _candidate(
                "primary-revenue",
                "fy=2022 period=annual metric=revenue concept=Revenues value=34229000000",
                target_line_item="revenue",
                target_period="FY2022",
                start_offset=10,
            ),
            _candidate(
                "operating-cash-flow",
                "fy=2022 period=annual metric=operating cash flow concept=NetCashProvidedByUsedInOperatingActivities value=5591000000",
                target_line_item="operating cash flow",
                target_period="FY2022",
                start_offset=20,
            ),
            _candidate(
                "capex",
                "fy=2022 period=annual metric=capital expenditures concept=PaymentsToAcquirePropertyPlantAndEquipment value=1749000000",
                target_line_item="capital expenditures",
                target_period="FY2022",
                start_offset=30,
            ),
            _candidate(
                "ppe",
                "fy=2022 period=annual metric=property plant and equipment net concept=PropertyPlantAndEquipmentNet value=9178000000",
                target_line_item="property plant and equipment net",
                target_period="FY2022",
                start_offset=40,
            ),
            _candidate(
                "assets",
                "fy=2022 period=annual metric=assets concept=Assets value=46455000000",
                target_line_item="assets",
                target_period="FY2022",
                start_offset=50,
            ),
        ],
        goal=goal,
        research_profile=None,
        limit=5,
    )

    selected_ids = [candidate.evidence.evidence_id for candidate in selected]
    assert "primary-revenue" in selected_ids
    assert "fair-value-revenue" not in selected_ids
    assert "operating-cash-flow" in selected_ids
    assert "capex" in selected_ids
    assert diagnostics["selected_target_line_items"] == [
        "revenue",
        "operating cash flow",
        "capital expenditures",
        "property plant and equipment net",
        "assets",
    ]
    assert any(item["target_line_item"] == "revenue" for item in rejected)


def _candidate(
    evidence_id: str,
    text: str,
    *,
    target_line_item: str | None = None,
    target_period: str | None = None,
    start_offset: int = 0,
) -> EvidenceCandidate:
    metadata = {}
    if target_line_item:
        metadata["target_line_item"] = target_line_item
    if target_period:
        metadata["target_period"] = target_period
    span = ExtractedSpan(
        span_id=f"span-{evidence_id}",
        goal_id="goal-chevron",
        document_id=f"doc-{evidence_id}",
        source_id="sec-companyfacts",
        text=text,
        start_offset=start_offset,
        end_offset=len(text),
        score=0.9,
        metadata=metadata,
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
            "span_metadata": metadata,
        },
    )
    return EvidenceCandidate(evidence=evidence, span=span)
