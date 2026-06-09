from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.bench import convert_public_finance_benchmark, load_finance_benchmark_items
from kernel_v3.finance import (
    CALCULATOR_TOOL_NAME,
    build_finance_fact_ledger,
    compute_formula,
    verify_finance_answer,
)
from kernel_v3.finance.calculator import register_finance_tools
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
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
    assert "unsupported_numeric_value:$999 billion" in failure.missing_evidence
    assert not journal.records(task_id="task-finance", kind="agent_final_answer")


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
