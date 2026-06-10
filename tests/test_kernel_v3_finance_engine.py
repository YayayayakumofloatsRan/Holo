from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import (
    _RecipeEvaluator,
    _apply_recipe_profile_defaults,
    _finance_missing_fact_retrieval_action,
    _finance_missing_fact_retrieval_payload,
    _finance_formula_preflight_plans,
    task_recipe,
)
from kernel_v3.contracts import CandidateAction, ContextBundle, Observation
from kernel_v3.bench import convert_public_finance_benchmark, load_finance_benchmark_items
from kernel_v3.finance import (
    CALCULATOR_TOOL_NAME,
    FinanceFact,
    FormulaTrace,
    build_finance_fact_ledger,
    compute_formula,
    plan_finance_formula,
    verify_finance_answer,
)
from kernel_v3.finance.calculator import register_finance_tools
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, FetchedDocument, RetrievalReport
from kernel_v3.retrieval.extract import readable_document_text
from kernel_v3.tools import ToolRegistry


def test_calculator_compute_handles_common_finance_formulas() -> None:
    cagr = compute_formula(
        expression="(revenue_2024 / revenue_2022) ** 0.5 - 1",
        variables={"revenue_2024": 2_865_507, "revenue_2022": 1_905_871},
        unit="percent",
        formula_name="cagr",
    )
    dio = compute_formula(
        expression="avg_inventory / cogs * fiscal_days",
        variables={"avg_inventory": 22_000, "cogs": 239_000, "fiscal_days": 371},
        unit="days",
        formula_name="dio",
    )
    bps = compute_formula(
        expression="(reported_margin - cash_adjusted_margin) * 10000",
        variables={"reported_margin": "0.2462", "cash_adjusted_margin": "0.2420"},
        unit="bps",
        formula_name="bps_difference",
    )
    ev_revenue = compute_formula(
        expression="(equity_value + debt - cash) / revenue",
        variables={"equity_value": 80_000, "debt": 12_000, "cash": 4_000, "revenue": 22_000},
        unit="x",
        formula_name="ev_revenue",
    )

    assert abs((Decimal(cagr.result_value) * Decimal(100)) - Decimal("22.62")) < Decimal("0.01")
    assert Decimal(dio.result_value).quantize(Decimal("0.01")) == Decimal("34.15")
    assert Decimal(bps.result_value) == Decimal("42")
    assert Decimal(ev_revenue.result_value) == Decimal("4")


def test_calculator_rejects_unsafe_expressions() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())

    manifest = [item for item in registry.manifests() if item.name == CALCULATOR_TOOL_NAME][0]

    assert manifest.side_effect_class == "read"
    assert manifest.permissions_required == []
    try:
        compute_formula(expression="__import__('os').system('echo unsafe')", variables={})
    except Exception as exc:
        assert "unsupported" in str(exc) or "unknown_variable" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unsafe expression was accepted")


def test_finance_fact_ledger_extracts_sec_companyfacts_spans() -> None:
    evidence, citations = _sec_revenue_evidence(value="391035000000")

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert len(facts) == 1
    assert facts[0].entity == "Apple Inc."
    assert facts[0].ticker == "AAPL"
    assert facts[0].metric == "revenue"
    assert facts[0].value == "391035000000"
    assert facts[0].fiscal_year == 2024
    assert facts[0].citation_ref == "cite-1"


def test_finance_fact_ledger_extracts_transaction_value_from_filing_text() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="deal-value",
            title="Pfizer Seagen acquisition 8-K",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/pfe-8k.htm",
            text=(
                "Pfizer announced the acquisition of Seagen in a transaction valued at "
                "$43 billion. Seagen generated revenue of $2.2 billion for fiscal 2022."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-deal")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    metrics = {fact.metric for fact in facts}

    assert "transaction value" in metrics
    assert "revenue" in metrics
    assert any(fact.value == "43000000000" for fact in facts)
    assert any(fact.value == "2200000000" for fact in facts)


def test_finance_fact_ledger_extracts_enterprise_value_phrase_from_filing_text() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="enterprise-value",
            title="Pfizer Seagen acquisition 8-K exhibit",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/exhibit-991.htm",
            text=(
                "Pfizer to acquire Seagen for $229 per Seagen share in cash, "
                "for a total enterprise value of approximately $43 billion. "
                "Transaction value of approximately $43 billion, inclusive of net debt."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-enterprise-value")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert any(fact.metric == "transaction value" and fact.value == "43000000000" for fact in facts)
    assert any(fact.metric == "purchase price" and fact.value == "229" for fact in facts)
    transaction_fact = next(
        fact for fact in facts if fact.metric == "transaction value" and fact.value == "43000000000"
    )
    assert transaction_fact.metadata["per_share"] is False


def test_finance_fact_ledger_extracts_market_data_page_metrics() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="market-data",
            title="LULU quote statistics",
            uri="https://finance.yahoo.com/quote/LULU/key-statistics/",
            text=(
                "Lululemon Athletica Inc. valuation measures. Market Cap 36.4B. "
                "Enterprise Value 34.8B. Total Debt 1.2B. Total Cash 2.8B. "
                "EBITDA 2.6B."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-market-data")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    by_metric = {fact.metric: fact.value for fact in facts}

    assert by_metric["market cap"] == "36400000000"
    assert by_metric["enterprise value"] == "34800000000"
    assert by_metric["debt"] == "1200000000"
    assert by_metric["cash and cash equivalents"] == "2800000000"
    assert by_metric["ebitda"] == "2600000000"


def test_finance_fact_ledger_extracts_adjusted_ebitda_bridge_components() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-adjusted-ebitda-bridge",
            title="Kraft Heinz 2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20241228.htm",
            text=(
                "Kraft Heinz 2024 Form 10-K non-GAAP reconciliation. "
                "Net income was $1.0 billion. "
                "Restructuring add-backs were $0.2 billion. "
                "Less divestiture gains were $0.1 billion. "
                "Adjusted EBITDA was $6.0 billion."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-khc-bridge")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    metrics = {fact.metric for fact in facts}
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge and subtotal.", facts=facts)

    assert "net income" in metrics
    assert "addback" in metrics
    assert "deduction" in metrics
    assert "adjusted ebitda" in metrics
    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["formula_name"] == "bridge_subtotal"


def test_finance_fact_ledger_does_not_extract_dividend_per_share_as_ebitda() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="wsc-market-stat-noise",
            title="WillScot Holdings market statistics",
            uri="https://stockanalysis.com/stocks/wsc/statistics/",
            text=(
                "WillScot Holdings market statistics. EBITDA Margin was 25.94%. "
                "Dividend Per Share was $0.28. Dividend Yield was 1.2%."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-wsc-market-noise")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert all(fact.metric not in {"ebitda", "adjusted ebitda", "addback"} for fact in facts)


def test_finance_fact_ledger_scales_in_millions_bridge_table_for_formula_planner() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-adjusted-ebitda-millions",
            title="Kraft Heinz 2023 Form 10-K complete submission text",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/000163745924000018/0001637459-24-000018.txt",
            text=(
                "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                "December 30, 2023 December 31, 2022 "
                "Net income/(loss) $ 2,846 $ 2,368 "
                "Interest expense 912 921 "
                "Provision for/(benefit from) income taxes 787 598 "
                "Depreciation and amortization (excluding restructuring activities) 923 922 "
                "Adjusted EBITDA $ 6,697 $ 6,327"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-khc-millions")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    by_metric = {}
    for fact in facts:
        by_metric.setdefault(fact.metric, []).append(fact.value)
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert "2846000000" in by_metric["net income"]
    assert "912000000" in by_metric["interest expense"]
    assert "787000000" in by_metric["tax"]
    assert "923000000" in by_metric["depreciation and amortization"]
    assert "6697000000" in by_metric["adjusted ebitda"]
    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["formula_name"] == "bridge_subtotal"
    assert plan.payload["variables"]["base"] == "2846000000"


def test_finance_fact_ledger_extracts_market_metrics_from_bounded_html_script_snippets() -> None:
    body = """
    <html>
      <body>
        <main>Lululemon Athletica Inc. key statistics page.</main>
        <script>
          window.__DATA__ = {
            "quoteSummary": {
              "result": [{
                "summaryDetail": {
                  "marketCap": {"raw": 36400000000, "fmt": "36.4B"},
                  "enterpriseValue": {"raw": 34800000000, "fmt": "34.8B"},
                  "totalDebt": {"raw": 1200000000, "fmt": "1.2B"},
                  "totalCash": {"raw": 2800000000, "fmt": "2.8B"},
                  "ebitda": {"raw": 2600000000, "fmt": "2.6B"}
                }
              }]
            }
          };
        </script>
      </body>
    </html>
    """
    document = FetchedDocument(
        document_id="doc-market-script",
        goal_id="goal-market-script",
        source_id="source-market-script",
        uri="https://finance.yahoo.com/quote/LULU/key-statistics/",
        title="LULU key statistics",
        artifact_id="artifact-market-script",
        payload_hash="hash-market-script",
        preview="",
        size_bytes=len(body),
        metadata={"mime_type": "text/html"},
    )

    text, mode = readable_document_text(body, document=document)
    evidence = [
        _finance_evidence(
            evidence_id="market-script",
            uri=document.uri,
            title=document.title,
            text=text,
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-market-script")],
    )
    by_metric = {fact.metric: fact.value for fact in facts}

    assert mode == "html_readable_text"
    assert "Market data structured snippets" in text
    assert by_metric["market cap"] == "36400000000"
    assert by_metric["enterprise value"] == "34800000000"
    assert by_metric["debt"] == "1200000000"
    assert by_metric["cash and cash equivalents"] == "2800000000"
    assert by_metric["ebitda"] == "2600000000"


def test_finance_fact_ledger_extracts_market_cap_from_nasdaq_summary_json() -> None:
    body = json.dumps(
        {
            "data": {
                "symbol": "LULU",
                "summaryData": {
                    "Exchange": {"label": "Exchange", "value": "NASDAQ-GS"},
                    "MarketCap": {"label": "Market Cap", "value": "13,160,030,462"},
                },
            }
        }
    )
    document = FetchedDocument(
        document_id="doc-nasdaq-summary",
        goal_id="goal-nasdaq-summary",
        source_id="source-nasdaq-summary",
        uri="https://api.nasdaq.com/api/quote/LULU/summary?assetclass=stocks",
        title="Nasdaq market summary JSON for LULU",
        artifact_id="artifact-nasdaq-summary",
        payload_hash="hash-nasdaq-summary",
        preview="",
        size_bytes=len(body),
        metadata={"mime_type": "application/json"},
    )

    text, mode = readable_document_text(body, document=document)
    evidence = [
        _finance_evidence(
            evidence_id="nasdaq-summary",
            uri=document.uri,
            title=document.title,
            text=text,
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-nasdaq-summary")],
    )

    assert mode == "json_readable_text"
    market_cap = next(fact for fact in facts if fact.metric == "market cap")
    assert market_cap.ticker == "LULU"
    assert market_cap.value == "13160030462"


def test_finance_missing_fact_payload_for_ev_ebitda_is_ticker_aware_and_market_enabled() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="ev_ebitda",
        missing=["enterprise_value_or_market_cap", "debt", "cash", "ebitda_or_ebitda_components"],
        goal=(
            "Compare LULU and VSCO EV / EBITDA multiples using public market and filing data. "
            "Show enterprise value inputs, EBITDA inputs, calculation, and caveats."
        ),
    )

    assert payload["query"].startswith("LULU VSCO EV EBITDA")
    assert payload["queries"][0].startswith("LULU VSCO EV EBITDA")
    assert any("LULU key statistics" in query for query in payload["queries"])
    assert any("VSCO key statistics" in query for query in payload["queries"])
    assert any("LULU 10-K EBITDA debt cash SEC" in query for query in payload["queries"])
    assert any("VSCO 10-K EBITDA debt cash SEC" in query for query in payload["queries"])
    assert payload["max_queries"] >= 6
    assert payload["max_fetches"] >= 24
    assert payload["metadata"]["source_authority_requirement"] == "secondary_or_better"
    assert payload["metadata"]["preferred_source_families"][0] == "market_data_provider"
    assert payload["metadata"]["target_tickers"] == ["LULU", "VSCO"]


def test_finance_valuation_retrieval_defaults_allow_market_data_sources() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "research_profile": "finance_fundamentals",
            "execution_metadata": {
                "execution_profile": execution_profile("finance-fact-fast").to_dict(),
            }
        },
    )

    payload = _apply_recipe_profile_defaults(
        {"query": "Compare LULU and VSCO EV/EBITDA multiples using market cap and EBITDA."},
        recipe,
    )

    metadata = payload["metadata"]
    assert metadata["source_authority_requirement"] == "secondary_or_better"
    assert metadata["preferred_source_families"][0] == "market_data_provider"
    assert metadata["research_task_kind"] == "valuation"


def test_recipe_evaluator_continues_until_finance_formula_trace_exists() -> None:
    profile = execution_profile("finance-fact-fast")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "Calculate LULU EV/EBITDA from market cap, debt, cash, and EBITDA.",
            "execution_metadata": execution_profile_runtime_metadata(profile),
        },
    )
    journal = JournalStore.in_memory()
    evidence = [
        _finance_evidence(
            evidence_id="market-data",
            title="LULU key statistics",
            uri="https://finance.yahoo.com/quote/LULU/key-statistics/",
            text=(
                "Lululemon Athletica Inc. valuation measures. Market Cap 36.4B. "
                "Total Debt 1.2B. Total Cash 2.8B. EBITDA 2.6B."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-market")]
    for item in evidence:
        journal.append(
            task_id="task-1",
            run_id="run-1",
            step_id=None,
            kind="retrieval_evidence",
            data=item.to_dict(),
        )
    for item in citations:
        journal.append(
            task_id="task-1",
            run_id="run-1",
            step_id=None,
            kind="retrieval_citation",
            data=item.to_dict(),
        )

    evaluator = _RecipeEvaluator(recipe, journal=journal)
    context = ContextBundle(
        context_id="ctx-1",
        thread_key="thread-1",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-1", "run_id": "run-1"},
        token_budget=4096,
    )
    observation = Observation(
        observation_id="obs-1",
        run_id="run-1",
        kind="tool_result",
        status="ok",
        source="tool:retrieval.run",
        content={"report": _retrieval_report(evidence=evidence, citations=citations).to_dict()},
        observed_at_ms=1,
        action_id="act-1",
        tool_call_id="tool-1",
    )

    feedback = evaluator.evaluate(context, observation)

    assert feedback.status == "continue"
    assert "finance_formula_trace_required" in feedback.missing_evidence


def test_finance_fact_ledger_ignores_press_release_time_and_exhibit_identifiers() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="press-release-exhibit",
            title="SEC 8-K exhibit",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/d408093dex991.htm",
            text=(
                "EX-99.1 d408093dex991.htm Exhibit 99.1. Pfizer to acquire Seagen "
                "for $229 per Seagen share in cash, for a total enterprise value of "
                "approximately $43 billion. Seagen expected to contribute more than "
                "$10 billion in risk-adjusted revenues in 2030. Pfizer and Seagen "
                "to hold analyst and investor call at 8 a.m. EDT today, March 13, 2023."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-press-release-exhibit")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    values = {fact.value for fact in facts}

    assert "43000000000" in values
    assert "229" in values
    assert "10000000000" in values
    assert "8" not in values
    assert "13" not in values
    assert "99.1" not in values
    assert "408093" not in values


def test_finance_fact_ledger_ignores_discovery_page_numbers() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="sec-search",
            title="SEC EDGAR search",
            uri="https://www.sec.gov/edgar/search/",
            text="SEC EDGAR search page. Results per page 10 30. Less options 5.",
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-search")],
    )

    assert facts == []


def test_finance_formula_planner_uses_transaction_value_for_ev_revenue() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="deal-value",
            title="Pfizer Seagen acquisition 8-K",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/pfe-8k.htm",
            text=(
                "Pfizer announced the acquisition of Seagen in a transaction valued at "
                "$43 billion. Seagen generated revenue of $2.2 billion for fiscal 2022."
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-deal")],
    )

    plan = plan_finance_formula(question="Calculate transaction EV / revenue multiple.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["formula_name"] == "ev_revenue"
    assert plan.payload["variables"]["equity_value"] == "43000000000"
    assert plan.payload["variables"]["revenue"] == "2200000000"


def test_numeric_verifier_passes_supported_scaled_finance_values() -> None:
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer="Apple 2024 财年营收为 3910.35 亿美元，引用 cite-1。",
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Apple 2024 revenue?",
    )

    assert verification.status == "passed"
    assert verification.matched_values
    assert verification.missing_values == []


def test_numeric_verifier_passes_supported_hundred_million_display_without_unit() -> None:
    evidence, citations = _sec_revenue_evidence(value="20976000000")
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer="Home Depot 的库存为 209.76，引用 cite-1。",
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Home Depot inventory?",
    )

    assert verification.status == "passed"
    assert verification.matched_values
    assert verification.missing_values == []


def test_numeric_verifier_fails_unsupported_answer_values() -> None:
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer="Apple 2024 revenue was $999 billion.",
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Apple 2024 revenue?",
    )

    assert verification.status == "failed"
    assert verification.missing_values[0]["raw"] == "$999 billion"
    assert "unsupported_answer_number" in [issue["code"] for issue in verification.issues]


def test_numeric_verifier_accepts_comparison_difference_between_formula_traces() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-lulu",
            formula_name="ev_ebitda",
            expression="enterprise_value / ebitda",
            input_fact_ids=["lulu-ev", "lulu-ebitda"],
            result_value="14.21",
            unit="x",
        ),
        FormulaTrace(
            formula_id="formula-vsco",
            formula_name="ev_ebitda",
            expression="enterprise_value / ebitda",
            input_fact_ids=["vsco-ev", "vsco-ebitda"],
            result_value="14.64",
            unit="x",
        ),
    ]

    verification = verify_finance_answer(
        answer="EV/EBITDA multiple: LULU trades at 14.21x, VSCO trades at 14.64x, so LULU is -0.43x lower.",
        facts=[],
        formula_traces=traces,
        question="Compare LULU and VSCO EV/EBITDA multiples.",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []
    assert any(item["support"]["kind"] == "formula_comparison" for item in verification.matched_values)


def test_numeric_verifier_ignores_formula_trace_identifier_digits() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-c80087538433",
            formula_name="dio:HD",
            expression="avg_inventory / cogs * fiscal_days",
            input_fact_ids=["inventory", "cogs"],
            result_value="76.34",
            unit="days",
        )
    ]

    verification = verify_finance_answer(
        answer="DIO is 76.34 days based on formula-c80087538433.",
        facts=[],
        formula_traces=traces,
        question="Calculate DIO.",
    )

    assert verification.status == "passed"
    assert all(item["raw"] != "80087538433" for item in verification.missing_values)


def test_numeric_verifier_keeps_compact_billion_unit_numbers() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="market-cap",
            text="ticker=TEST metric=market cap value=11200000000 unit=USD source=market_data_json",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-market-cap")]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer="Market cap was 11.20B.",
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Verify market cap.",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []


def test_finance_fact_ledger_filters_eps_and_net_cash_from_ev_inputs() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="market-stats",
            title="StockAnalysis statistics for TEST",
            uri="https://stockanalysis.com/stocks/test/statistics/",
            text=(
                "Revenue 11.20B Net Income 1.46B EBITDA 2.57B Earnings Per Share (EPS) $12.40 "
                "Balance Sheet The company has $1.51 billion in cash and $2.14 billion in debt, "
                "with a net cash position of -$621.28 million or -$33.26 per share. "
                "Cash & Cash Equivalents 1.51B Total Debt 2.14B Net Cash -621.28M"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-market")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    market_values = [fact for fact in facts if fact.metric in {"market cap", "equity value", "enterprise value"}]
    debt_values = [Decimal(fact.value) for fact in facts if fact.metric == "debt"]

    assert all(Decimal(fact.value) != Decimal("12.4") for fact in market_values)
    assert all(value >= 0 for value in debt_values)
    assert Decimal("2140000000") in debt_values
    assert Decimal("-621280000") not in debt_values


def test_finance_formula_planner_rejects_unscaled_stock_price_as_market_cap() -> None:
    facts = [
        _finance_fact(
            "market cap",
            "117.55",
            fact_id="price-like-market-cap",
            metadata={
                "source": "natural_text",
                "source_uri": "https://stockanalysis.com/stocks/vsco/statistics/",
                "source_title": "StockAnalysis statistics for VSCO",
            },
        ),
        _finance_fact("debt", "845000000", fact_id="debt"),
        _finance_fact("cash and cash equivalents", "990501000", fact_id="cash"),
        _finance_fact("ebitda", "669000000", fact_id="ebitda"),
    ]

    plan = plan_finance_formula(question="Compare EV/EBITDA multiples.", facts=facts)

    assert plan.status == "missing_facts"
    assert "shares_outstanding_or_enterprise_value" in plan.missing_facts
    assert "price-like-market-cap" not in plan.input_fact_ids


def test_numeric_verifier_ignores_sec_filing_item_numbers() -> None:
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer=(
            "The relevant SEC 8-K references Item 7.01 and Item 8.01. "
            "Apple 2024 revenue was $391.035 billion."
        ),
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Verify finance values while ignoring SEC filing item codes.",
    )

    assert verification.status == "passed"
    assert all(item["raw"] not in {"7.01", "8.01"} for item in verification.missing_values)


def test_numeric_verifier_ignores_sec_form_codes_and_reference_markers() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="deal",
            title="Pfizer Seagen 8-K",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/d408093dex991.htm",
            text=(
                "Pfizer to acquire Seagen for $229 per Seagen share in cash, "
                "for a total enterprise value of approximately $43 billion. "
                "Seagen expected to contribute more than $10 billion in risk-adjusted revenues in 2030."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-deal")]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    trace = compute_formula(
        expression="equity_value / revenue",
        variables={"equity_value": "43000000000", "revenue": "10000000000"},
        unit="x",
        formula_name="ev_revenue",
        input_fact_ids=[fact.fact_id for fact in facts if fact.metric in {"transaction value", "revenue"}],
    )

    verification = verify_finance_answer(
        answer=(
            "根据SEC 8-K文件：\n"
            "1. 企业价值为430亿美元（引用[1]）。\n"
            "2. 2030年风险调整后收入超过100亿美元（来源[3]）。\n"
            "3. EV/Revenue = 430亿 / 100亿 = 4.3x。"
        ),
        facts=facts,
        formula_traces=[trace],
        citations=citations,
        evidence=evidence,
        question="Calculate Pfizer / Seagen EV/Revenue multiple.",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []


def test_numeric_verifier_still_blocks_unsupported_material_number_near_references() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="deal",
            title="Pfizer Seagen 8-K",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/d408093dex991.htm",
            text="Pfizer to acquire Seagen for a total enterprise value of approximately $43 billion.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-deal")]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    verification = verify_finance_answer(
        answer="引用[1]支持该交易价值为999亿美元。",
        facts=facts,
        citations=citations,
        evidence=evidence,
        question="Verify Pfizer / Seagen transaction value.",
    )

    assert verification.status == "failed"
    assert verification.missing_values[0]["raw"] == "999亿"


def test_finance_fact_ledger_ignores_sec_filing_item_codes() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="evidence-sec-item",
            goal_id="goal",
            span_id="span-sec-item",
            document_id="doc",
            source_id="source",
            artifact_id="artifact",
            uri="https://www.sec.gov/Archives/edgar/data/78003/000007800323000099/pfe-20231013.htm",
            title="SEC 8-K primary filing document items=2.02,2.05,7.01,9.01",
            text=(
                "Item 2.05. Costs Associated with Exit or Disposal Activities. "
                "In the fourth quarter of 2023, Pfizer announced that, to realign "
                "Pfizer's costs with its longer-term revenue expectations, Pfizer would reduce costs."
            ),
            score=0.9,
            payload_hash="hash",
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-sec-item")],
    )

    assert facts == []


def test_finance_fact_ledger_extracts_merger_per_share_cash_consideration() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="evidence-merger-consideration",
            goal_id="goal",
            span_id="span-merger-consideration",
            document_id="doc",
            source_id="source",
            artifact_id="artifact",
            uri="https://www.sec.gov/Archives/edgar/data/78003/000119312523068538/d408093d8k.htm",
            title="SEC 8-K merger agreement",
            text=(
                "At the effective time of the Merger, each share of common stock of Seagen "
                "will be converted into the right to receive $229.00 in cash."
            ),
            score=0.9,
            payload_hash="hash",
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-merger-consideration")],
    )

    price_fact = next(fact for fact in facts if fact.metric == "purchase price" and fact.value == "229")
    assert price_fact.metadata["per_share"] is True


def test_finance_fact_ledger_extracts_named_per_share_cash_consideration() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="evidence-named-per-share",
            goal_id="goal",
            span_id="span-named-per-share",
            document_id="doc",
            source_id="source",
            artifact_id="artifact",
            uri="https://www.sec.gov/Archives/edgar/data/78003/000119312523068538/d408093dex991.htm",
            title="SEC 8-K acquisition press release",
            text="Pfizer to acquire Seagen for $229 per Seagen share in cash.",
            score=0.9,
            payload_hash="hash",
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-named-per-share")],
    )

    price_fact = next(fact for fact in facts if fact.metric == "purchase price" and fact.value == "229")
    assert price_fact.metadata["per_share"] is True


def test_finance_formula_planner_does_not_treat_per_share_price_as_ev() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="per-share-price",
            title="SEC 8-K merger agreement",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/pfe-8k.htm",
            text=(
                "Each share of common stock of Seagen will be converted into the right "
                "to receive $229.00 in cash. Seagen generated revenue of $2.2 billion."
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-per-share")],
    )

    plan = plan_finance_formula(question="Calculate transaction EV / revenue multiple.", facts=facts)

    assert plan.status == "missing_facts"
    assert "shares_outstanding_or_transaction_value" in plan.missing_facts
    assert "revenue" not in plan.missing_facts


def test_finance_formula_planner_uses_enterprise_value_near_per_share_consideration() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="enterprise-value-and-per-share",
            title="SEC 8-K acquisition press release",
            uri="https://www.sec.gov/Archives/edgar/data/78003/example/d408093dex991.htm",
            text=(
                "Pfizer to acquire Seagen for $229 per Seagen share in cash, "
                "for a total enterprise value of approximately $43 billion. "
                "Seagen expected to contribute more than $10 billion in risk-adjusted revenues in 2030."
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-enterprise-value")],
    )

    plan = plan_finance_formula(
        question="For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple.",
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["variables"]["equity_value"] == "43000000000"
    assert plan.payload["variables"]["revenue"] == "10000000000"


def test_finance_formula_planner_generates_ev_ebitda_payload() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="ev",
            text="entityName=Retailer ticker=RTL metric=enterprise value unit=USD fy=2024 form=10-K value=12000",
        ),
        _finance_evidence(
            evidence_id="ebitda",
            text="entityName=Retailer ticker=RTL metric=adjusted ebitda unit=USD fy=2024 form=10-K value=3000",
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(question="Compare EV / EBITDA multiple.", facts=facts)

    assert plan.status == "ready"
    assert plan.formula_name == "ev_ebitda"
    assert plan.payload is not None
    assert plan.payload["expression"] == "(equity_value + debt - cash - investments) / ebitda"
    assert plan.payload["variables"]["equity_value"] == "12000"
    assert plan.payload["variables"]["ebitda"] == "3000"


def test_finance_formula_preflight_returns_missing_plan_when_no_entity_is_ready() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="lulu-market",
            text="entityName=lululemon ticker=LULU metric=market cap unit=USD fy=2025 value=13160030462",
        ),
        _finance_evidence(
            evidence_id="vsco-sales",
            text="entityName=Victoria's Secret ticker=VSCO metric=revenue unit=USD fy=2025 value=6553000000",
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plans = _finance_formula_preflight_plans(
        question="Compare LULU and VSCO EV/EBITDA multiples.",
        facts=facts,
        existing_traces=[],
    )

    assert len(plans) == 1
    assert plans[0].status == "missing_facts"
    assert plans[0].formula_name == "ev_ebitda"


def test_finance_formula_planner_derives_ebitda_from_components() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="ev",
            text="entityName=Retailer ticker=RTL metric=enterprise value unit=USD fy=2024 form=10-K value=12000",
        ),
        _finance_evidence(
            evidence_id="net-income",
            text="entityName=Retailer ticker=RTL metric=net income unit=USD fy=2024 form=10-K value=1000",
        ),
        _finance_evidence(
            evidence_id="interest",
            text="entityName=Retailer ticker=RTL metric=interest expense unit=USD fy=2024 form=10-K value=200",
        ),
        _finance_evidence(
            evidence_id="tax",
            text="entityName=Retailer ticker=RTL metric=income tax expense unit=USD fy=2024 form=10-K value=300",
        ),
        _finance_evidence(
            evidence_id="da",
            text=(
                "entityName=Retailer ticker=RTL metric=depreciation and amortization "
                "unit=USD fy=2024 form=10-K value=500"
            ),
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(question="Calculate EV/EBITDA.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert "net_income + interest_expense + tax_expense + depreciation_amortization" in plan.payload["expression"]
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) == Decimal("6")


def test_finance_missing_fact_retrieval_action_supports_ev_ebitda() -> None:
    plan = plan_finance_formula(question="Compare LULU and VSCO EV/EBITDA.", facts=[])
    source_action = CandidateAction(
        action_id="act-source",
        kind="respond",
        name=None,
        description="fallback",
        score=0.1,
        payload={"text": "fallback"},
        reasons=["fallback"],
        side_effect_class="none",
    )

    action = _finance_missing_fact_retrieval_action(
        source_action,
        plan=plan,
        goal="Compare LULU and VSCO EV/EBITDA multiples.",
        call_index=1,
    )

    assert action is not None
    assert action.name == "retrieval.run"
    assert action.payload["metadata"]["finance_formula_name"] == "ev_ebitda"
    assert "enterprise value" in action.payload["query"].lower()
    assert "ebitda" in action.payload["query"].lower()


def test_finance_fact_ledger_maps_pretax_income_concept_without_interest_pollution() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="pretax",
            text=(
                "entityName=Retailer ticker=RTL "
                "concept=IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest "
                "metric=IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest "
                "unit=USD fy=2024 form=10-K value=1234"
            ),
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-pretax")],
    )

    assert facts[0].metric == "pretax income"


def test_finance_fact_fast_recipe_allows_calculator_tool() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    assert "retrieval.run" in recipe.allowed_tools
    assert CALCULATOR_TOOL_NAME in recipe.allowed_tools


def test_retrieval_finalization_journals_numeric_verification_and_final_answer() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="Apple 2024 revenue was $391.035 billion, supported by cite-1.",
    )
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    verification = journal.records(task_id="task-finance", kind="finance_numeric_verification")[-1]
    assert verification.data["status"] == "passed"
    assert journal.records(task_id="task-finance", kind="finance_fact_ledger")
    assert journal.records(task_id="task-finance", kind="agent_final_answer")


def test_retrieval_finalization_runs_finance_formula_preflight_before_synthesis() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="DIO 计算需要使用库存和销售成本，公式轨迹已记录。引用 cite-1。",
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-1",
            text="entityName=Retailer ticker=RTL metric=inventory unit=USD fy=2023 form=10-K value=200",
        ),
        _finance_evidence(
            evidence_id="evidence-2",
            text="entityName=Retailer ticker=RTL metric=inventory unit=USD fy=2024 form=10-K value=240",
        ),
        _finance_evidence(
            evidence_id="evidence-3",
            text="entityName=Retailer ticker=RTL metric=cost of sales unit=USD fy=2024 form=10-K value=1000",
        ),
    ]
    citations = [_finance_citation(item, citation_id=f"cite-{index}") for index, item in enumerate(evidence, start=1)]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "Calculate FY2024 DIO in days.",
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
        },
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance-dio",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    plans = journal.records(task_id="task-finance-dio", kind="finance_formula_plan")
    observations = journal.records(task_id="task-finance-dio", kind="observation")
    assert plans
    assert any(record.data.get("source") == f"tool:{CALCULATOR_TOOL_NAME}" for record in observations)
    trace = observations[-1].data["content"]["formula_trace"]
    assert trace["formula_name"] == "dio"
    assert Decimal(trace["result_value"]).quantize(Decimal("0.01")) == Decimal("80.30")


def test_retrieval_finalization_blocks_unsupported_finance_numbers() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="Apple 2024 revenue was $999 billion, supported by cite-1.",
    )
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert final is None
    assert failure is not None
    assert failure.reason == "finance_numeric_verification_failed"
    assert "unsupported_answer_number:$999 billion" in failure.missing_evidence
    assert not journal.records(task_id="task-finance", kind="agent_final_answer")


def test_finance_formula_planner_generates_dio_payload_from_ledger() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="evidence-inv-1",
            goal_id="goal-1",
            span_id="span-inv-1",
            document_id="doc-1",
            source_id="sec",
            artifact_id="artifact-1",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            title="Company facts",
            text="entityName=Retailer ticker=RTL metric=inventory unit=USD fy=2023 form=10-K value=200",
            score=0.9,
            payload_hash="hash-inv-1",
        ),
        EvidenceItem(
            evidence_id="evidence-inv-2",
            goal_id="goal-1",
            span_id="span-inv-2",
            document_id="doc-1",
            source_id="sec",
            artifact_id="artifact-1",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            title="Company facts",
            text="entityName=Retailer ticker=RTL metric=inventory unit=USD fy=2024 form=10-K value=240",
            score=0.9,
            payload_hash="hash-inv-2",
        ),
        EvidenceItem(
            evidence_id="evidence-cogs",
            goal_id="goal-1",
            span_id="span-cogs",
            document_id="doc-1",
            source_id="sec",
            artifact_id="artifact-1",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            title="Company facts",
            text="entityName=Retailer ticker=RTL metric=cost of sales unit=USD fy=2024 form=10-K value=1000",
            score=0.9,
            payload_hash="hash-cogs",
        ),
    ]
    citations = [
        CitationItem(
            citation_id=f"cite-{item.evidence_id}",
            goal_id=item.goal_id,
            evidence_id=item.evidence_id,
            artifact_id=item.artifact_id,
            uri=item.uri,
            title=item.title,
            quote=item.text,
            span_start=0,
            span_end=len(item.text),
            metadata={},
        )
        for item in evidence
    ]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    plan = plan_finance_formula(question="Calculate FY2024 DIO in days.", facts=facts)

    assert plan.status == "ready"
    assert plan.formula_name == "dio"
    assert plan.payload is not None
    assert plan.payload["expression"] == "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days"
    assert plan.payload["variables"]["fiscal_days"] == 365


def test_finance_formula_planner_filters_non_inventory_cost_concepts_for_dio() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="bad-inventory-cost",
            text=(
                "entityName=Retailer ticker=RTL concept=DeferredTaxLiabilitiesDeferredExpenseCapitalizedInventoryCosts "
                "metric=inventory unit=USD fy=2024 form=10-K value=999999"
            ),
        ),
        _finance_evidence(
            evidence_id="inventory-2023",
            text="entityName=Retailer ticker=RTL concept=InventoryNet metric=inventory unit=USD fy=2023 form=10-K value=200",
        ),
        _finance_evidence(
            evidence_id="inventory-2024",
            text="entityName=Retailer ticker=RTL concept=InventoryNet metric=inventory unit=USD fy=2024 form=10-K value=240",
        ),
        _finance_evidence(
            evidence_id="cogs-2024",
            text=(
                "entityName=Retailer ticker=RTL concept=CostOfGoodsAndServicesSold metric=cost of sales "
                "unit=USD fy=2024 form=10-K value=1000"
            ),
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(question="Calculate FY2024 DIO in days.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["variables"] == {
        "cogs": "1000",
        "fiscal_days": 365,
        "inventory_begin": "200",
        "inventory_end": "240",
    }


def test_finance_formula_planner_prefers_dio_period_end_dates() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="inventory-old",
            text=(
                "entityName=Retailer ticker=RTL concept=InventoryNet metric=inventory unit=USD "
                "fy=2023 form=10-K end=2023-01-29 value=24886"
            ),
        ),
        _finance_evidence(
            evidence_id="inventory-begin",
            text=(
                "entityName=Retailer ticker=RTL concept=InventoryNet metric=inventory unit=USD "
                "fy=2024 form=10-K end=2024-01-28 value=20976"
            ),
        ),
        _finance_evidence(
            evidence_id="inventory-end",
            text=(
                "entityName=Retailer ticker=RTL concept=InventoryNet metric=inventory unit=USD "
                "fy=2025 form=10-K end=2025-02-02 value=23451"
            ),
        ),
        _finance_evidence(
            evidence_id="cogs-prior",
            text=(
                "entityName=Retailer ticker=RTL concept=CostOfRevenue metric=cost of revenue unit=USD "
                "fy=2024 form=10-K end=2024-01-28 value=104625"
            ),
        ),
        _finance_evidence(
            evidence_id="cogs-target",
            text=(
                "entityName=Retailer ticker=RTL concept=CostOfRevenue metric=cost of revenue unit=USD "
                "fy=2025 form=10-K end=2025-02-02 value=106206"
            ),
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(question="Calculate FY2024 DIO in days.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["variables"] == {
        "cogs": "106206",
        "fiscal_days": 365,
        "inventory_begin": "20976",
        "inventory_end": "23451",
    }


def test_finance_agent_v2_public_imports_plain_text_without_gold(tmp_path: Path) -> None:
    source = tmp_path / "public.txt"
    output = tmp_path / "fabv2_public_dev.jsonl"
    manifest = tmp_path / "manifest.json"
    source.write_text(
        "For NYSE: HD and NYSE: LOW, calculate FY2024 DIO and compare inventory efficiency.\n"
        "Using a Discounted Cash Flow Analysis, what would the enterprise value of NYSE: CRM be?\n",
        encoding="utf-8",
    )

    summary = convert_public_finance_benchmark(
        benchmark="finance_agent_v2_public",
        input_path=source,
        output_path=output,
        manifest_path=manifest,
    )
    items = load_finance_benchmark_items(output)

    assert summary.item_count == 2
    assert items[0].source == "finance_agent_v2_public"
    assert items[0].gold_answer is None
    assert items[0].required_tools == ["retrieval.run", "calculator.compute", "finance.verify_numeric"]
    assert items[0].metadata["expected_capabilities"] == ["retrieval.run", "calculator.compute", "finance.verify_numeric"]
    assert items[1].metadata["category"] == "financial_modeling"
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["prompt_policy"]["gold_answer_in_prompt"] is False


def _runtime_with_synthesizer(journal: JournalStore, *, answer: str) -> AgentRuntime:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "synthesizer.answer": {
                        "answer": answer,
                        "citation_refs": ["cite-1"],
                        "confidence": 0.9,
                        "limitations": [],
                        "used_evidence": ["evidence-1"],
                    }
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    return AgentRuntime(journal=journal, processor_fabric=fabric)


def _sec_revenue_evidence(*, value: str) -> tuple[list[EvidenceItem], list[CitationItem]]:
    text = (
        "entityName=Apple Inc. ticker=AAPL cik=0000320193 "
        "concept=us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax "
        "label=Revenue metric=revenue unit=USD fy=2024 form=10-K filed=2024-11-01 "
        f"value={value}"
    )
    evidence = [
        EvidenceItem(
            evidence_id="evidence-1",
            goal_id="goal-1",
            span_id="span-1",
            document_id="doc-1",
            source_id="source-1",
            artifact_id="artifact-1",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            title="SEC companyfacts JSON for CIK 0000320193",
            text=text,
            score=1.0,
            payload_hash="hash-1",
        )
    ]
    citations = [
        CitationItem(
            citation_id="cite-1",
            goal_id="goal-1",
            evidence_id="evidence-1",
            artifact_id="artifact-1",
            uri=evidence[0].uri,
            title=evidence[0].title,
            quote=text,
            span_start=0,
            span_end=len(text),
        )
    ]
    return evidence, citations


def _finance_evidence(
    *,
    evidence_id: str,
    text: str,
    uri: str = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    title: str = "SEC companyfacts JSON",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        goal_id="goal-1",
        span_id=f"span-{evidence_id}",
        document_id="doc-1",
        source_id="source-1",
        artifact_id="artifact-1",
        uri=uri,
        title=title,
        text=text,
        score=1.0,
        payload_hash=f"hash-{evidence_id}",
    )


def _finance_citation(item: EvidenceItem, *, citation_id: str) -> CitationItem:
    return CitationItem(
        citation_id=citation_id,
        goal_id=item.goal_id,
        evidence_id=item.evidence_id,
        artifact_id=item.artifact_id,
        uri=item.uri,
        title=item.title,
        quote=item.text,
        span_start=0,
        span_end=len(item.text),
    )


def _finance_fact(
    metric: str,
    value: str,
    *,
    fact_id: str = "fact",
    metadata: dict | None = None,
) -> FinanceFact:
    return FinanceFact(
        fact_id=fact_id,
        entity=None,
        ticker=None,
        period=None,
        fiscal_year=None,
        metric=metric,
        value=value,
        unit="USD",
        scale="actual",
        source_ref="source",
        evidence_ref=None,
        citation_ref=None,
        metadata=dict(metadata or {}),
    )


def _retrieval_report(*, evidence: list[EvidenceItem], citations: list[CitationItem]) -> RetrievalReport:
    return RetrievalReport(
        report_id="report-1",
        goal_id="goal-1",
        status="sufficient",
        query_plan_id="query-plan-1",
        search_attempt_ids=["search-1"],
        fetch_attempt_ids=["fetch-1"],
        evidence_ids=[item.evidence_id for item in evidence],
        citation_ids=[item.citation_id for item in citations],
        evaluation_id="eval-1",
        artifact_refs=["artifact-1"],
        preview="SEC companyfacts evidence",
    )
