from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import FinalAnswer
from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import (
    _RecipeBoundPlanner,
    _RecipeEvaluator,
    _apply_recipe_profile_defaults,
    _benchmark_doc_retrieval_primary_citation_satisfies_required_source,
    _augment_finance_modeling_retrieval_payload,
    _finance_fallback_fact_lines,
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
    attach_target_binding_to_facts,
    build_finance_fact_ledger,
    compile_finance_task_program,
    compute_formula,
    finance_facts_to_claims,
    finance_formula_plan_to_transform_plan,
    finance_slot_frame,
    finance_verification_to_gate_result,
    primary_source_numeric_binding_resolution,
    target_document_binding_from_metadata,
    plan_finance_formula,
    verify_finance_answer,
)
from kernel_v3.finance.calculator import register_finance_tools
from kernel_v3.journal import JournalStore
from kernel_v3.processors import FakeJsonProvider, ProcessorFabric, ProcessorRouter
from kernel_v3.research.profiles import finance_fundamentals_profile
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, FetchedDocument, RetrievalReport, SearchGoal
from kernel_v3.retrieval.evaluate import qualify_evidence_candidate
from kernel_v3.retrieval.extract import extract_spans, readable_document_text
from kernel_v3.retrieval.targeting import target_entity_phrases
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


def test_finance_fact_ledger_parses_period_fy_without_polluting_concept() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="mmm-capex-period-fy",
            title="SEC companyfacts JSON for CIK 0000066740",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
            text=(
                "SEC companyfacts official financial statement entityName=3M COMPANY cik=66740 "
                "taxonomy=us-gaap concept=PaymentsToAcquirePropertyPlantAndEquipment "
                "metric=capital expenditures label=Payments to Acquire Property, Plant, and Equipment "
                "unit=USD period=annual period_fy=2018 value=1577000000 val=1577000000 "
                "fy=2018 fp=FY form=10-K filed=2019-02-07 end=2018-12-31 "
                "start=2018-01-01 accn=0001558370-19-000470"
            ),
        )
    ]
    facts = build_finance_fact_ledger(evidence=evidence, citations=[_finance_citation(evidence[0], citation_id="cite-mmm")])

    assert len(facts) == 1
    assert facts[0].metric == "capital expenditures"
    assert facts[0].value == "1577000000"
    assert facts[0].fiscal_year == 2018
    assert facts[0].metadata["concept"] == "PaymentsToAcquirePropertyPlantAndEquipment"


def test_companyfacts_readable_text_prioritizes_target_year_missing_slots() -> None:
    body = json.dumps(
        {
            "entityName": "3M COMPANY",
            "cik": 66740,
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {
                            "USD": [
                                {
                                    "val": 24948000000,
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-03",
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "frame": "CY2025",
                                    "accn": "0000066740-26-000014",
                                },
                                {
                                    "val": 34229000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                },
                            ]
                        },
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "label": "Payments to Acquire Property, Plant, and Equipment",
                        "units": {
                            "USD": [
                                {
                                    "val": 910000000,
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-03",
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "frame": "CY2025",
                                    "accn": "0000066740-26-000014",
                                },
                                {
                                    "val": 1749000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                },
                            ]
                        },
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "label": "Net Cash Provided by (Used in) Operating Activities",
                        "units": {
                            "USD": [
                                {
                                    "val": 2306000000,
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-03",
                                    "start": "2025-01-01",
                                    "end": "2025-12-31",
                                    "frame": "CY2025",
                                    "accn": "0000066740-26-000014",
                                },
                                {
                                    "val": 5591000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                },
                            ]
                        },
                    },
                    "PropertyPlantAndEquipmentNet": {
                        "label": "Property, Plant and Equipment, Net",
                        "units": {
                            "USD": [
                                {
                                    "val": 7101000000,
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-03",
                                    "end": "2025-12-31",
                                    "accn": "0000066740-26-000014",
                                },
                                {
                                    "val": 9178000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                },
                            ]
                        },
                    },
                    "Assets": {
                        "label": "Assets",
                        "units": {
                            "USD": [
                                {
                                    "val": 37733000000,
                                    "fy": 2025,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2026-02-03",
                                    "end": "2025-12-31",
                                    "accn": "0000066740-26-000014",
                                },
                                {
                                    "val": 46455000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                },
                            ]
                        },
                    },
                }
            },
        }
    )
    document = FetchedDocument(
        document_id="doc-3m-companyfacts",
        goal_id="goal",
        source_id="source",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
        title="SEC companyfacts JSON for CIK 0000066740",
        artifact_id="artifact",
        payload_hash="hash",
        preview="",
        size_bytes=len(body),
        metadata={"mime_type": "application/json"},
    )
    goal = SearchGoal(
        goal_id="goal",
        query=(
            "3M FY2022 capital expenditures revenue operating cash flow total assets "
            "PropertyPlantAndEquipmentNet"
        ),
        metadata={
            "target_document_binding": {
                "company": "3M",
                "doc_link": (
                    "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
                    "0000066740-23-000014.pdf"
                ),
                "doc_type": "10k",
                "doc_period": "2022",
                "primary_source_required": True,
            }
        },
    )

    text, mode = readable_document_text(body, document=document, goal=goal)

    assert mode == "sec_companyfacts_readable_text"
    target_index = text.index("value=1749000000")
    assert target_index < text.index("value=910000000")
    assert "concept=Revenues metric=revenue" in text
    assert "value=34229000000" in text
    assert "concept=NetCashProvidedByUsedInOperatingActivities metric=operating cash flow" in text
    assert "value=5591000000" in text
    assert "concept=PropertyPlantAndEquipmentNet metric=property plant and equipment net" in text
    assert "value=9178000000" in text
    assert "concept=Assets metric=assets" in text
    assert "value=46455000000" in text


def test_companyfacts_target_bound_slots_are_qualified_finance_evidence() -> None:
    body = json.dumps(
        {
            "entityName": "3M COMPANY",
            "cik": 66740,
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {
                            "USD": [
                                {
                                    "val": 34229000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                }
                            ]
                        },
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "label": "Payments to Acquire Property, Plant, and Equipment",
                        "units": {
                            "USD": [
                                {
                                    "val": 1749000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                }
                            ]
                        },
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "label": "Net Cash Provided by (Used in) Operating Activities",
                        "units": {
                            "USD": [
                                {
                                    "val": 5591000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "start": "2022-01-01",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                }
                            ]
                        },
                    },
                    "PropertyPlantAndEquipmentNet": {
                        "label": "Property, Plant and Equipment, Net",
                        "units": {
                            "USD": [
                                {
                                    "val": 9178000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                }
                            ]
                        },
                    },
                    "Assets": {
                        "label": "Assets",
                        "units": {
                            "USD": [
                                {
                                    "val": 46455000000,
                                    "fy": 2022,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2023-02-08",
                                    "end": "2022-12-31",
                                    "accn": "0000066740-23-000014",
                                }
                            ]
                        },
                    },
                }
            },
        }
    )
    binding = {
        "company": "3M",
        "doc_link": (
            "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
            "0000066740-23-000014.pdf"
        ),
        "doc_type": "10k",
        "doc_period": "2022",
        "primary_source_required": True,
    }
    document = FetchedDocument(
        document_id="doc-3m-companyfacts",
        goal_id="goal",
        source_id="source",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
        title="SEC companyfacts JSON for CIK 0000066740",
        artifact_id="artifact",
        payload_hash="hash",
        preview="",
        size_bytes=len(body),
        metadata={
            "mime_type": "application/json",
            "source_metadata": {
                "source_kind": "sec_companyfacts_json",
                "source_family": "structured_regulatory_data",
                "authority_level": "primary",
            },
            "target_document_binding": binding,
        },
    )
    goal = SearchGoal(
        goal_id="goal",
        query=(
            "Benchmark target source follows. Source URL: "
            "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
            "0000066740-23-000014.pdf Company: 3M Document type: 10k Document period: 2022 "
            "Is 3M a capital-intensive business based on FY2022 data? SEC companyfacts capital expenditures "
            "revenue operating cash flow total assets PropertyPlantAndEquipmentNet PP&E net"
        ),
        metadata={
            "research_profile": "finance_fundamentals",
            "benchmark_doc_retrieval": True,
            "company": "3M",
            "issuer": "3M",
            "target_document_binding": binding,
        },
        max_spans_per_document=8,
    )

    spans = extract_spans(goal=goal, document=document, body=body)
    target_line_items = [str(span.metadata.get("target_line_item") or "") for span in spans]

    assert target_line_items[:5] == [
        "revenue",
        "operating cash flow",
        "capital expenditures",
        "property plant and equipment net",
        "assets",
    ]
    profile = finance_fundamentals_profile()
    for span in spans[:5]:
        evidence = EvidenceItem(
            evidence_id=f"evidence-{span.span_id}",
            goal_id=goal.goal_id,
            span_id=span.span_id,
            document_id=document.document_id,
            source_id=document.source_id,
            artifact_id=document.artifact_id,
            uri=document.uri,
            title=document.title,
            text=span.text,
            score=span.score,
            payload_hash=document.payload_hash,
            diagnostics={
                "source_kind": "direct_url",
                "span_metadata": span.metadata,
                "target_document_binding": binding,
            },
        )
        qualification = qualify_evidence_candidate(goal=goal, evidence=evidence, research_profile=profile)
        assert qualification["accepted"] is True
        assert qualification["reason"] == "qualified_finance_evidence"
        assert qualification["finance_numeric_fact_present"] is True


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


def test_planner_processor_failure_rescues_to_targeted_finance_retrieval() -> None:
    class FailedPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-processor-failed",
                kind="respond",
                name="respond",
                description="processor failed",
                score=0.0,
                payload={"error": "processor_failed"},
                reasons=["processor_failed"],
                side_effect_class="none",
            )

    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **profile_metadata,
            "semantic_intake": {
                "goal": "For Pfizer's acquisition of Seagen, compute transaction value / Seagen revenue.",
            },
        },
    )
    planner = _RecipeBoundPlanner(
        inner=FailedPlanner(),
        goal="For Pfizer's acquisition of Seagen, compute transaction value / Seagen revenue.",
        recipe=recipe,
        journal=JournalStore.in_memory(),
    )
    context = ContextBundle(
        context_id="ctx-pfe-rescue",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-pfe",
            "run_id": "run-pfe",
            "sections": [
                {
                    "name": "recent_observations",
                    "content": [
                        {
                            "source": "tool:retrieval.run",
                            "status": "failed",
                            "content": {
                                "error": "tool_execution_failed",
                                "query": "Pfizer Seagen transaction value",
                                "source_urls": ["https://www.sec.gov/Archives/example/pfe-8k.htm"],
                            },
                        }
                    ],
                }
            ],
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.kind == "tool"
    assert "host_planner_failure_rescue" in action.reasons
    assert action.payload["metadata"]["host_rescue"] is True
    assert action.payload["metadata"]["source_urls"] == ["https://www.sec.gov/Archives/example/pfe-8k.htm"]
    assert "Pfizer" in action.payload["query"]
    assert action.payload["max_sources"] >= 24


def test_planner_processor_failure_preserves_benchmark_doc_target() -> None:
    class FailedPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-processor-failed",
                kind="respond",
                name="respond",
                description="processor failed",
                score=0.0,
                payload={"error": "processor_failed"},
                reasons=["processor_failed"],
                side_effect_class="none",
            )

    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf\n"
        "Company: 3M\n"
        "Document: 3M_2018_10K\n"
        "Document type: 10k\n"
        "Document period: 2018\n\n"
        "What is the FY2018 capital expenditure amount for 3M?"
    )
    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=profile_metadata)
    planner = _RecipeBoundPlanner(
        inner=FailedPlanner(),
        goal=goal,
        recipe=recipe,
        journal=JournalStore.in_memory(),
    )
    context = ContextBundle(
        context_id="ctx-financebench-doc-rescue",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-doc",
            "run_id": "run-doc",
            "sections": [
                {
                    "name": "recent_observations",
                    "content": [
                        {
                            "source": "tool:retrieval.run",
                            "status": "ok",
                            "content": {
                                "query": "SEC companyfacts official financial statements entityName=TARGET CORPORATION",
                                "queries": ["SEC companyfacts official financial statements entityName=TARGET CORPORATION"],
                            },
                        }
                    ],
                }
            ],
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.payload["metadata"]["benchmark_doc_retrieval"] is True
    assert action.payload["metadata"]["company"] == "3M"
    source_urls = action.payload["metadata"]["source_urls"]
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470.txt" in source_urls
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470-index.html" in source_urls
    assert "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf" in source_urls
    assert "3M 2018 10k" in action.payload["query"]
    assert "TARGET CORPORATION" not in action.payload["query"]


def test_planner_processor_failure_prefers_retrieval_workbench_followup() -> None:
    class FailedPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-processor-failed",
                kind="respond",
                name="respond",
                description="processor failed",
                score=0.0,
                payload={"error": "processor_failed"},
                reasons=["processor_failed"],
                side_effect_class="none",
            )

    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf\n"
        "Company: 3M\n"
        "Document: 3M_2018_10K\n"
        "Document type: 10k\n"
        "Document period: 2018\n\n"
        "What is the FY2018 capital expenditure amount for 3M?"
    )
    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=profile_metadata)
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-workbench-followup",
        run_id="run-workbench-followup",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Need a targeted companyfacts concept query.",
            "missing_slots": ["capital_expenditure_fy2018"],
            "next_queries": ["PaymentsToAcquirePropertyPlantAndEquipment 3M 2018"],
            "next_source_families": ["sec_edgar"],
            "next_document_targets": ["https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000066740&type=10-K&dateb=20181231"],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=FailedPlanner(),
        goal=goal,
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-workbench-followup",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-workbench-followup",
            "run_id": "run-workbench-followup",
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert "retrieval_workbench_followup" in action.reasons
    assert action.payload["query"] == "PaymentsToAcquirePropertyPlantAndEquipment 3M 2018"
    assert action.payload["metadata"]["workbench_followup"] is True
    assert action.payload["metadata"]["benchmark_doc_retrieval"] is True
    assert action.payload["metadata"]["target_document_binding"]["doc_period"] == "2018"
    assert action.payload["metadata"]["target_document_binding"]["required_line_item"] == "capital expenditures"
    assert action.payload["metadata"]["semantic_missing_slots"] == ["capital_expenditure_fy2018"]
    assert "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000066740&type=10-K&dateb=20181231" in action.payload["metadata"]["source_urls"]
    assert all("TARGET CORPORATION" not in query for query in action.payload["queries"])


def test_planner_uses_retrieval_workbench_followup_before_premature_answer() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-premature-answer",
                kind="respond",
                name="respond",
                description="Premature answer",
                score=0.55,
                payload={"text": "A partial formula result is available."},
                reasons=["model_answer_ready"],
                side_effect_class="none",
            )

    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf\n"
        "Company: 3M\n"
        "Document: 3M_2022_10K\n"
        "Document type: 10k\n"
        "Document period: 2022\n\n"
        "What drove operating margin change as of FY2022 for 3M?"
    )
    recipe = task_recipe("retrieval_answer", metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")))
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-workbench-normal",
        run_id="run-workbench-normal",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Need the filing discussion of operating margin drivers.",
            "missing_slots": ["operating_margin_driver", "cost_structure", "segment_breakdown"],
            "next_queries": ["3M 2022 10-K operating margin cost of sales SG&A drivers"],
            "next_source_families": ["regulatory_filing"],
            "next_document_targets": ["https://www.sec.gov/Archives/edgar/data/66740/0000066740-23-000014/0000066740-23-000014-index.html"],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal=goal,
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-workbench-normal",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-workbench-normal",
            "run_id": "run-workbench-normal",
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.payload["query"] == "3M 2022 10-K operating margin cost of sales SG&A drivers"
    assert "retrieval_workbench_followup" in action.reasons
    assert "workbench_semantic_continue" in action.reasons
    assert "planner_processor_failed" not in action.reasons
    assert action.payload["metadata"]["workbench_followup"] is True
    assert action.payload["metadata"]["semantic_missing_slots"] == [
        "operating_margin_driver",
        "cost_structure",
        "segment_breakdown",
    ]
    source_urls = action.payload["metadata"]["source_urls"]
    assert "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt" in source_urls
    assert "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014-index.html" in source_urls
    assert "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf" in source_urls


def test_planner_compiles_workbench_missing_slots_into_target_source_followup() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-premature-answer-no-query",
                kind="respond",
                name="respond",
                description="Premature answer",
                score=0.55,
                payload={"text": "Answer from partial facts."},
                reasons=["model_answer_ready"],
                side_effect_class="none",
            )

    source_url = "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf"
    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        f"Source URL: {source_url}\n"
        "Company: 3M\n"
        "Document: 3M_2022_10K\n"
        "Document type: 10k\n"
        "Document period: 2022\n\n"
        "What drove operating margin change as of FY2022 for 3M?"
    )
    recipe = task_recipe("retrieval_answer", metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")))
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-workbench-missing-no-query",
        run_id="run-workbench-missing-no-query",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Need operating margin driver discussion from the target filing.",
            "missing_slots": ["operating_margin_change_drivers", "mdna_analysis"],
            "next_queries": [],
            "next_source_families": [],
            "next_document_targets": [],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal=goal,
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-workbench-missing-no-query",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-workbench-missing-no-query",
            "run_id": "run-workbench-missing-no-query",
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.payload["query"].startswith(source_url)
    assert "operating_margin_change_drivers" in action.payload["query"]
    assert source_url in action.payload["metadata"]["source_urls"]
    assert action.payload["metadata"]["semantic_missing_slots"] == [
        "operating_margin_change_drivers",
        "mdna_analysis",
    ]


def test_planner_uses_workbench_semantic_missing_slots_for_followup() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-premature-answer-semantic-only",
                kind="respond",
                name="respond",
                description="Premature answer",
                score=0.55,
                payload={"text": "Answer from partial facts."},
                reasons=["model_answer_ready"],
                side_effect_class="none",
            )

    source_url = "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf"
    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        f"Source URL: {source_url}\n"
        "Company: 3M\n"
        "Document: 3M_2022_10K\n"
        "Document type: 10k\n"
        "Document period: 2022\n\n"
        "What drove operating margin change as of FY2022 for 3M?"
    )
    recipe = task_recipe("retrieval_answer", metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")))
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-workbench-semantic-only",
        run_id="run-workbench-semantic-only",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Need operating margin driver discussion from the target filing.",
            "semantic_missing_slots": ["operating_margin_change", "mdna_analysis"],
            "next_queries": [],
            "next_source_families": [],
            "next_document_targets": [],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal=goal,
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-workbench-semantic-only",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-workbench-semantic-only",
            "run_id": "run-workbench-semantic-only",
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.payload["query"].startswith(source_url)
    assert "mdna_analysis" in action.payload["query"]
    assert action.payload["metadata"]["semantic_missing_slots"] == [
        "operating_margin_change",
        "mdna_analysis",
    ]


def test_model_retrieval_action_enforces_benchmark_doc_binding_when_query_drifts() -> None:
    class DriftedPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-drifted-retrieval",
                kind="tool",
                name="retrieval.run",
                description="Drifted secondary-source retrieval",
                score=0.8,
                payload={
                    "query": "in profits. Earnings per share was 899M current market statistics StockAnalysis",
                    "queries": ["in profits. Earnings per share was 899M current market statistics StockAnalysis"],
                    "metadata": {"research_profile": "finance_fundamentals"},
                },
                reasons=["model_retrieval_strategy"],
                side_effect_class="network",
            )

    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.\n\n"
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf\n"
        "Company: 3M\n"
        "Document: 3M_2018_10K\n"
        "Document type: 10k\n"
        "Document period: 2018\n\n"
        "What is the FY2018 capital expenditure amount for 3M?"
    )
    recipe = task_recipe("retrieval_answer", metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")))
    planner = _RecipeBoundPlanner(
        inner=DriftedPlanner(),
        goal=goal,
        recipe=recipe,
        journal=JournalStore.in_memory(),
    )
    context = ContextBundle(
        context_id="ctx-drifted-query",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-drifted", "run_id": "run-drifted"},
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "retrieval.run"
    assert action.payload["query"] == "3M 2018 10k What is the FY2018 capital expenditure amount for 3M?"
    assert all("899M" not in query and "StockAnalysis" not in query for query in action.payload["queries"])
    assert action.payload["metadata"]["benchmark_doc_retrieval"] is True
    assert action.payload["metadata"]["benchmark_binding_enforced"] is True
    assert action.payload["metadata"]["target_document_binding"]["required_statement"] == "cash_flow_statement"
    assert action.payload["metadata"]["target_document_binding"]["required_line_item"] == "capital expenditures"
    source_urls = action.payload["metadata"]["source_urls"]
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470.txt" in source_urls
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470-index.html" in source_urls
    assert "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf" in source_urls


def test_target_entity_extraction_does_not_bind_leading_for_as_entity() -> None:
    phrases = target_entity_phrases(
        "For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple."
    )

    assert "For Pfizer" not in phrases


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


def test_finance_fact_ledger_extracts_modeling_cash_flow_metrics() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="cash-flow",
            text=(
                "entityName=Salesforce ticker=CRM facts="
                "metric=net cash provided by operating activities unit=USD fy=2024 form=10-K value=10234000000 ; "
                "metric=capital expenditures unit=USD fy=2024 form=10-K value=710000000"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-cash-flow")],
    )
    by_metric = {fact.metric: fact.value for fact in facts}

    assert by_metric["operating cash flow"] == "10234000000"
    assert by_metric["capital expenditures"] == "710000000"


def test_finance_fact_ledger_extracts_ppe_purchase_rows_with_millions_header() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="ppe-cash-flow-table",
            title="3M 2018 Form 10-K",
            text=(
                "Consolidated Statement of Cash Flows Years ended December 31 (Millions) "
                "2018 2017 2016 Cash Flows from Investing Activities "
                "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420) "
                "Proceeds from sale of PP&E and other assets 262 49 58"
            ),
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-ppe-table")],
    )

    capex_values = {fact.value for fact in facts if fact.metric == "capital expenditures"}
    assert "-1577000000" in capex_values


def test_finance_fallback_prefers_sec_companyfacts_over_secondary_market_sources() -> None:
    facts = [
        FinanceFact(
            fact_id="secondary-capex",
            entity="3M Company",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="899000000",
            unit="USD",
            scale="actual",
            source_ref="cite-stockanalysis",
            evidence_ref="ev-stockanalysis",
            citation_ref="cite-stockanalysis",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/mmm/statistics/",
                "source_title": "3M Statistics - StockAnalysis",
                "supported_metric": True,
            },
        ),
        FinanceFact(
            fact_id="sec-capex",
            entity="3M COMPANY",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="1577000000",
            unit="USD",
            scale="actual",
            source_ref="cite-sec-companyfacts",
            evidence_ref="ev-sec-companyfacts",
            citation_ref="cite-sec-companyfacts",
            metadata={
                "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
                "source_title": "SEC companyfacts JSON for CIK 0000066740",
                "supported_metric": True,
            },
        ),
    ]

    lines = _finance_fallback_fact_lines(
        facts,
        question="What is the FY2018 capital expenditure amount in USD millions for 3M?",
        limit=1,
    )

    assert lines == ["- FY2018 capital expenditures: 1577（USD millions 口径） [cite-sec-companyfacts]"]


def test_target_document_binding_preserves_required_line_item_when_reused() -> None:
    binding = target_document_binding_from_metadata(
        {
            "company": "3M",
            "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
            "doc_type": "10-K",
            "doc_period": "2018",
            "required_statement": "cash_flow_statement",
            "required_line_item": "capital expenditures",
            "primary_source_required": True,
        }
    )

    reused = target_document_binding_from_metadata(binding, question="What is the FY2018 capex amount?")

    assert reused["required_statement"] == "cash_flow_statement"
    assert reused["required_line_item"] == "capital expenditures"
    assert reused["doc_period"] == "2018"
    assert reused["primary_source_required"] is True


def test_primary_source_numeric_binding_selects_target_capex_and_rejects_secondary_value() -> None:
    binding = target_document_binding_from_metadata(
        {
            "company": "3M",
            "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
            "doc_type": "10-K",
            "doc_period": "2018",
            "required_statement": "cash_flow_statement",
            "required_line_item": "capital expenditures",
            "primary_source_required": True,
        },
        question="What is 3M FY2018 capital expenditures from the cash flow statement?",
    )
    facts = [
        FinanceFact(
            fact_id="secondary-899m",
            entity="3M",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="899000000",
            unit="USD",
            scale="actual",
            source_ref="cite-secondary",
            evidence_ref="ev-secondary",
            citation_ref="cite-secondary",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/mmm/financials/cash-flow-statement/",
                "source_title": "3M Cash Flow Statement - StockAnalysis",
                "context": "Capital expenditures 899",
            },
        ),
        FinanceFact(
            fact_id="target-1577m",
            entity="3M",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="-1577000000",
            unit="USD",
            scale="actual",
            source_ref="cite-target",
            evidence_ref="ev-target",
            citation_ref="cite-target",
            metadata={
                "source_uri": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
                "source_title": "3M 2018 10-K",
                "context": "Consolidated Statement of Cash Flows Purchases of property, plant and equipment 2018 (1,577)",
            },
        ),
    ]

    bound = attach_target_binding_to_facts(facts, binding, question="FY2018 capital expenditures")
    resolution = primary_source_numeric_binding_resolution(bound, binding, question="FY2018 capital expenditures")

    assert resolution["status"] == "selected"
    assert resolution["selected_fact_ids"] == ["target-1577m"]
    rejected = {item["fact_id"]: item for item in resolution["rejected_candidates"]}
    assert "secondary-899m" in rejected
    assert "secondary_market_source_rejected_for_primary_binding" in rejected["secondary-899m"]["reasons"]


def test_primary_source_numeric_binding_selects_balance_sheet_net_ppne() -> None:
    binding = target_document_binding_from_metadata(
        {
            "company": "3M",
            "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
            "doc_type": "10-K",
            "doc_period": "2018",
            "root_goal": "Assume that you are a public equities analyst. What is the year end FY2018 net PPNE shown in the balance sheet?",
            "primary_source_required": True,
        }
    )
    facts = [
        FinanceFact(
            fact_id="target-net-ppne",
            entity="3M",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="property plant and equipment net",
            value="4366000000",
            unit="USD",
            scale="actual",
            source_ref="cite-target",
            evidence_ref="ev-target",
            citation_ref="cite-target",
            metadata={
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
                "source_title": "SEC companyfacts JSON for CIK 0000066740",
                "concept": "PropertyPlantAndEquipmentNet",
                "context": "Property, plant and equipment, net 2018",
            },
        )
    ]

    bound = attach_target_binding_to_facts(facts, binding, question="FY2018 net PPNE from balance sheet")
    resolution = primary_source_numeric_binding_resolution(bound, binding, question="FY2018 net PPNE from balance sheet")

    assert binding["required_line_item"] == "property plant and equipment net"
    assert binding["required_statement"] == "balance_sheet"
    assert resolution["status"] == "selected"
    assert resolution["selected_fact_ids"] == ["target-net-ppne"]


def test_primary_source_numeric_binding_accepts_target_period_sec_structured_companion_for_compute_task() -> None:
    binding = target_document_binding_from_metadata(
        {
            "company": "3M",
            "doc_link": "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf",
            "doc_type": "10-K",
            "doc_period": "2022",
            "primary_source_required": True,
        },
        question="Is 3M a capital-intensive business based on FY2022 data?",
    )
    facts = [
        FinanceFact(
            fact_id="target-revenue-2022",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="revenue",
            value="34229000000",
            unit="USD",
            scale="actual",
            source_ref="cite-sec-companyfacts",
            evidence_ref="ev-sec-companyfacts",
            citation_ref="cite-sec-companyfacts",
            metadata={
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
                "source_title": "SEC companyfacts JSON for CIK 0000066740",
                "concept": "Revenues",
                "context": "FY2022 target-bound SEC companyfacts",
            },
        ),
        FinanceFact(
            fact_id="secondary-revenue",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="revenue",
            value="34229000000",
            unit="USD",
            scale="actual",
            source_ref="cite-secondary",
            evidence_ref="ev-secondary",
            citation_ref="cite-secondary",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/mmm/revenue/",
                "source_title": "3M Revenue - StockAnalysis",
                "context": "FY2022 revenue",
            },
        ),
    ]

    resolution = primary_source_numeric_binding_resolution(
        attach_target_binding_to_facts(facts, binding, question="FY2022 capital intensity"),
        binding,
        question="FY2022 capital intensity",
    )

    assert binding.get("required_line_item") is None
    assert resolution["status"] == "selected"
    assert resolution["selected_fact_ids"] == ["target-revenue-2022"]
    rejected = {item["fact_id"]: item for item in resolution["rejected_candidates"]}
    assert "secondary-revenue" in rejected
    assert "secondary_market_source_rejected_for_primary_binding" in rejected["secondary-revenue"]["reasons"]


def test_finance_task_compiler_emits_capital_intensity_program_missing_slots() -> None:
    program = compile_finance_task_program(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[
            FinanceFact(
                fact_id="rev-2022",
                entity="3M",
                ticker="MMM",
                period="2022",
                fiscal_year=2022,
                metric="revenue",
                value="26161000000",
                unit="USD",
                scale="actual",
                source_ref="cite-revenue",
                evidence_ref="ev-revenue",
                citation_ref="cite-revenue",
                metadata={"source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"},
            )
        ],
    )

    assert program.task_spec.task_type == "compute"
    assert program.slot_frame is not None
    assert program.slot_frame.missing_slots == [
        "capital_expenditures",
        "operating_cash_flow",
        "property_plant_and_equipment_net",
        "assets",
    ]
    assert [spec.name for spec in program.transform_specs] == [
        "capital_intensity_capex_revenue",
        "capital_intensity_capex_operating_cash_flow",
        "capital_intensity_ppe_assets",
    ]
    evidence_slots = {spec.slot_name: spec for spec in program.evidence_specs}
    assert evidence_slots["property_plant_and_equipment_net"].statement == "balance_sheet"
    assert evidence_slots["capital_expenditures"].statement == "cash_flow_statement"


def test_finance_formula_planner_does_not_turn_driver_explanation_into_margin_formula() -> None:
    plan = plan_finance_formula(
        question=(
            "What drove operating margin change as of FY2022 for 3M? "
            "If operating margin is not a useful metric for a company like this, then please state that and explain why."
        ),
        facts=[],
    )

    assert plan.status == "not_applicable"


def test_finance_formula_planner_still_allows_explicit_margin_calculation() -> None:
    plan = plan_finance_formula(
        question="Calculate FY2022 operating margin for 3M.",
        facts=[
            FinanceFact(
                fact_id="operating-income-2022",
                entity="3M",
                ticker="MMM",
                period="2022",
                fiscal_year=2022,
                metric="operating income",
                value="3130000000",
                unit="USD",
                scale="actual",
                source_ref="cite-operating-income",
                evidence_ref="ev-operating-income",
                citation_ref="cite-operating-income",
                metadata={},
            ),
            FinanceFact(
                fact_id="revenue-2022",
                entity="3M",
                ticker="MMM",
                period="2022",
                fiscal_year=2022,
                metric="revenue",
                value="34229000000",
                unit="USD",
                scale="actual",
                source_ref="cite-revenue",
                evidence_ref="ev-revenue",
                citation_ref="cite-revenue",
                metadata={},
            ),
        ],
    )

    assert plan.status == "ready"
    assert plan.formula_name == "margin"


def test_finance_formula_planner_generates_capital_intensity_payload() -> None:
    facts = [
        FinanceFact(
            fact_id="capex",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="capital expenditures",
            value="-1334000000",
            unit="USD",
            scale="actual",
            source_ref="cite-capex",
            evidence_ref="ev-capex",
            citation_ref="cite-capex",
            metadata={},
        ),
        FinanceFact(
            fact_id="revenue",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="revenue",
            value="26161000000",
            unit="USD",
            scale="actual",
            source_ref="cite-revenue",
            evidence_ref="ev-revenue",
            citation_ref="cite-revenue",
            metadata={},
        ),
        FinanceFact(
            fact_id="ocf",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="operating cash flow",
            value="6680000000",
            unit="USD",
            scale="actual",
            source_ref="cite-ocf",
            evidence_ref="ev-ocf",
            citation_ref="cite-ocf",
            metadata={},
        ),
        FinanceFact(
            fact_id="ppe",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="property plant and equipment net",
            value="5544000000",
            unit="USD",
            scale="actual",
            source_ref="cite-ppe",
            evidence_ref="ev-ppe",
            citation_ref="cite-ppe",
            metadata={},
        ),
        FinanceFact(
            fact_id="assets",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="assets",
            value="46455000000",
            unit="USD",
            scale="actual",
            source_ref="cite-assets",
            evidence_ref="ev-assets",
            citation_ref="cite-assets",
            metadata={},
        ),
    ]

    plan = plan_finance_formula(question="Is 3M a capital-intensive business based on FY2022 data?", facts=facts)

    assert plan.status == "ready"
    assert plan.formula_name == "capital_intensity"
    assert plan.payload["expression"] == "capital_expenditures / revenue"
    assert plan.payload["variables"]["capital_expenditures"] == "1334000000"
    assert set(plan.input_fact_ids) == {"capex", "revenue", "ocf", "ppe", "assets"}


def test_finance_formula_planner_does_not_fill_capital_intensity_with_wrong_year_or_cost_of_revenue() -> None:
    facts = [
        FinanceFact(
            fact_id="revenue-2022",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="revenue",
            value="26161000000",
            unit="USD",
            scale="actual",
            source_ref="cite-revenue",
            evidence_ref="ev-revenue",
            citation_ref="cite-revenue",
            metadata={"concept": "Revenues"},
        ),
        FinanceFact(
            fact_id="cost-2025",
            entity="3M",
            ticker="MMM",
            period="2025",
            fiscal_year=2025,
            metric="cost of revenue",
            value="14991000000",
            unit="USD",
            scale="actual",
            source_ref="cite-cost",
            evidence_ref="ev-cost",
            citation_ref="cite-cost",
            metadata={"concept": "CostOfRevenue"},
        ),
        FinanceFact(
            fact_id="capex-2025",
            entity="3M",
            ticker="MMM",
            period="2025",
            fiscal_year=2025,
            metric="capital expenditures",
            value="910000000",
            unit="USD",
            scale="actual",
            source_ref="cite-capex",
            evidence_ref="ev-capex",
            citation_ref="cite-capex",
            metadata={"concept": "PaymentsToAcquirePropertyPlantAndEquipment"},
        ),
        FinanceFact(
            fact_id="ocf-2025",
            entity="3M",
            ticker="MMM",
            period="2025",
            fiscal_year=2025,
            metric="operating cash flow",
            value="2306000000",
            unit="USD",
            scale="actual",
            source_ref="cite-ocf",
            evidence_ref="ev-ocf",
            citation_ref="cite-ocf",
            metadata={"concept": "NetCashProvidedByUsedInOperatingActivities"},
        ),
        FinanceFact(
            fact_id="ppe-2025",
            entity="3M",
            ticker="MMM",
            period="2025",
            fiscal_year=2025,
            metric="property plant and equipment net",
            value="7101000000",
            unit="USD",
            scale="actual",
            source_ref="cite-ppe",
            evidence_ref="ev-ppe",
            citation_ref="cite-ppe",
            metadata={"concept": "PropertyPlantAndEquipmentNet"},
        ),
        FinanceFact(
            fact_id="assets-2025",
            entity="3M",
            ticker="MMM",
            period="2025",
            fiscal_year=2025,
            metric="assets",
            value="37733000000",
            unit="USD",
            scale="actual",
            source_ref="cite-assets",
            evidence_ref="ev-assets",
            citation_ref="cite-assets",
            metadata={"concept": "Assets"},
        ),
    ]

    plan = plan_finance_formula(question="Is 3M a capital-intensive business based on FY2022 data?", facts=facts)

    assert plan.status == "missing_facts"
    assert plan.input_fact_ids == ["revenue-2022"]
    assert plan.missing_facts == [
        "capital_expenditures",
        "operating_cash_flow",
        "property_plant_and_equipment_net",
        "assets",
    ]


def test_numeric_verifier_filters_secondary_value_when_target_binding_requires_primary_source() -> None:
    binding = target_document_binding_from_metadata(
        {
            "company": "3M",
            "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
            "doc_period": "2018",
            "required_statement": "cash_flow_statement",
            "required_line_item": "capital expenditures",
            "primary_source_required": True,
        }
    )
    facts = [
        FinanceFact(
            fact_id="secondary-899m",
            entity="3M",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="899000000",
            unit="USD",
            scale="actual",
            source_ref="cite-secondary",
            evidence_ref="ev-secondary",
            citation_ref="cite-secondary",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/mmm/financials/cash-flow-statement/",
                "source_title": "3M Cash Flow Statement - StockAnalysis",
                "context": "Capital expenditures 899",
            },
        ),
        FinanceFact(
            fact_id="target-1577m",
            entity="3M",
            ticker="MMM",
            period="2018",
            fiscal_year=2018,
            metric="capital expenditures",
            value="-1577000000",
            unit="USD",
            scale="actual",
            source_ref="cite-target",
            evidence_ref="ev-target",
            citation_ref="cite-target",
            metadata={
                "source_uri": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
                "source_title": "3M 2018 10-K",
                "context": "Consolidated Statement of Cash Flows Purchases of property, plant and equipment 2018 (1,577)",
            },
        ),
    ]

    bad = verify_finance_answer(
        answer="The FY2018 capital expenditure amount was $899 million.",
        facts=facts,
        question="What is 3M FY2018 capital expenditures?",
        target_binding=binding,
    )
    good = verify_finance_answer(
        answer="The FY2018 capital expenditure amount was $1,577 million.",
        facts=facts,
        question="What is 3M FY2018 capital expenditures?",
        target_binding=binding,
    )

    assert bad.status == "failed"
    assert any(issue["code"] == "unsupported_answer_number" for issue in bad.issues)
    assert good.status == "passed"
    assert good.diagnostics["primary_source_numeric_binding"]["selected_fact_ids"] == ["target-1577m"]


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
                "Adjusted EBITDA was $1.1 billion."
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


def test_finance_substrate_adapter_projects_slots_claims_transforms_and_verifier_gate() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-substrate-bridge",
            title="Kraft Heinz 2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20241228.htm",
            text=(
                "Kraft Heinz 2024 Form 10-K non-GAAP reconciliation. "
                "Net income was $1.0 billion. Restructuring add-backs were $0.2 billion. "
                "Less license income was $0.1 billion. Adjusted EBITDA was $1.1 billion."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-khc-substrate")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    plan = plan_finance_formula(question="Explain the adjusted EBITDA add-back bridge.", facts=facts)
    claims = finance_facts_to_claims(facts)
    frame = finance_slot_frame(question="Explain the adjusted EBITDA add-back bridge.", facts=facts, plan=plan)
    transform = finance_formula_plan_to_transform_plan(plan, question="Explain the adjusted EBITDA add-back bridge.")
    verification = verify_finance_answer(
        answer="The bridge is $1.0B + $0.2B - $0.1B = $1.1B.",
        facts=facts,
        formula_traces=[],
        question="Explain the adjusted EBITDA add-back bridge.",
    )
    gate = finance_verification_to_gate_result(verification, policy=frame.evidence_policy)

    assert claims
    assert all(claim.domain == "finance" for claim in claims)
    assert frame.task_type == "reconcile"
    assert frame.evidence_policy is not None
    assert "market_data_provider" in frame.evidence_policy.forbidden_source_families
    assert transform.domain == "finance"
    assert transform.operation == "calculate"
    assert transform.status == "ready"
    assert gate.domain == "finance"
    assert gate.policy_id == frame.evidence_policy.policy_id


def test_finance_slot_frame_fills_reconciliation_period_series_and_source_table() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-substrate-bridge-periods",
            title="Kraft Heinz 2023 Form 10-K complete submission text",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/000163745924000018/khc-20231230.htm",
            text=(
                "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                "December 30, 2023 December 31, 2022 "
                "Net income/(loss) $ 2,846 $ 2,368 "
                "Interest expense 912 921 "
                "Provision for income taxes 787 598 "
                "Depreciation and amortization 923 922 "
                "Adjusted EBITDA $ 5,468 $ 4,809"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-khc-periods")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    plan = plan_finance_formula(question="Explain the adjusted EBITDA reconciliation bridge.", facts=facts)
    frame = finance_slot_frame(question="Explain the adjusted EBITDA reconciliation bridge.", facts=facts, plan=plan)
    fills = {fill.slot_name: fill for fill in frame.filled_slots}

    assert plan.status == "ready"
    assert "period_series" in fills
    assert fills["period_series"].metadata["period_count"] >= 2
    assert "source_table" in fills
    assert "Form 10-K" in str(fills["source_table"].value)
    assert "period_series" not in frame.missing_slots
    assert "source_table" not in frame.missing_slots


def test_finance_bridge_planner_accepts_income_from_continuing_operations_base() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="wsc-continuing-ops-bridge",
            title="WillScot Mobile Mini 2023 Form 10-K complete submission text",
            uri="https://www.sec.gov/Archives/edgar/data/1647088/example/wsc-20231231.htm",
            text=(
                "The following table provides unaudited reconciliations of Income from continuing "
                "operations to Adjusted EBITDA: Year Ended December 31, (in thousands) 2023 2022 2021 "
                "Income from continuing operations $ 341,844 $ 276,341 $ 114,895 "
                "Interest expense 205,040 146,278 116,358 "
                "Depreciation and amortization 338,654 319,099 280,567 "
                "Adjusted EBITDA $ 885,538 $ 741,718 $ 511,820"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-wsc-continuing-ops")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    metrics = {fact.metric for fact in facts}
    plan = plan_finance_formula(question="Investigate the adjusted EBITDA add-back trend.", facts=facts)
    frame = finance_slot_frame(question="Investigate the adjusted EBITDA add-back trend.", facts=facts, plan=plan)

    assert "income from continuing operations" in metrics
    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["variables"]["base"] == "341844000"
    assert "base_metric" not in frame.missing_slots


def test_finance_fact_ledger_keeps_adjusted_ebitda_before_eps_table_title() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-adjusted-ebitda-before-eps",
            title="Kraft Heinz 2023 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20231230.htm",
            text=(
                "The Kraft Heinz Company Reconciliation of Net Income/(Loss) to Adjusted EBITDA "
                "(in millions) (Unaudited) December 30, 2023 December 31, 2022 "
                "Net income/(loss) $ 2,846 $ 2,368 "
                "Interest expense 912 921 "
                "Other expense/(income) 27 (253) "
                "Provision for/(benefit from) income taxes 787 598 "
                "Depreciation and amortization (excluding restructuring activities) 923 922 "
                "Restructuring activities 60 74 "
                "Equity award compensation expense 141 148 "
                "Adjusted EBITDA $ 5,696 $ 4,778 "
                "The Kraft Heinz Company Reconciliation of Diluted EPS to Adjusted EPS"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-khc-adjusted-ebitda-before-eps")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    metrics = {fact.metric for fact in facts}
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert "adjusted ebitda" in metrics
    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["formula_name"] == "bridge_subtotal"


def test_finance_bridge_planner_keeps_reconciliation_table_columns_together() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-quarterly-noise",
            title="Kraft Heinz 2023 Form 10-Q",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20230930.htm",
            text=(
                "Quarterly adjusted EBITDA reconciliation. "
                "Net income was $254 million. Interest expense was $230 million. "
                "Adjusted EBITDA was $1,480 million."
            ),
        ),
        _finance_evidence(
            evidence_id="khc-annual-bridge",
            title="Kraft Heinz 2023 Form 10-K complete submission text",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20231230.htm",
            text=(
                "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                "December 30, 2023 December 31, 2022 "
                "Net income/(loss) $ 2,846 $ 2,368 "
                "Interest expense 912 921 "
                "Provision for income taxes 787 598 "
                "Depreciation and amortization 923 922 "
                "Restructuring activities 60 74 "
                "Equity award compensation expense 141 148 "
                "Adjusted EBITDA $ 5,669 $ 5,031"
            ),
        ),
    ]
    citations = [
        _finance_citation(evidence[0], citation_id="cite-khc-quarterly-noise"),
        _finance_citation(evidence[1], citation_id="cite-khc-annual-bridge"),
    ]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.diagnostics["bridge_group_key"] == "source:cite-khc-annual-bridge"
    assert plan.diagnostics["bridge_detected_column_count"] == 2
    assert plan.payload["variables"]["base"] == "2846000000"
    assert plan.payload["variables"]["reported_adjusted"] == "5669000000"
    assert "921000000" not in set(plan.payload["variables"].values())
    trace = compute_formula(**plan.payload)
    assert trace.result_value == "5669000000"


def test_finance_bridge_planner_does_not_mix_all_evidence_groups() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="khc-prior-bridge",
            title="Kraft Heinz 2022 Form 10-K",
            text=(
                "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                "December 31, 2022 December 25, 2021 "
                "Net income/(loss) $ 2,368 $ 1,024 "
                "Interest expense 921 2,047 "
                "Provision for income taxes 598 684 "
                "Depreciation and amortization 922 910 "
                "Adjusted EBITDA $ 4,809 $ 4,665"
            ),
        ),
        _finance_evidence(
            evidence_id="khc-current-bridge",
            title="Kraft Heinz 2023 Form 10-K",
            text=(
                "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                "December 30, 2023 December 31, 2022 "
                "Net income/(loss) $ 2,846 $ 2,368 "
                "Interest expense 912 921 "
                "Provision for income taxes 787 598 "
                "Depreciation and amortization 923 922 "
                "Adjusted EBITDA $ 5,468 $ 4,809"
            ),
        ),
    ]
    citations = [
        _finance_citation(evidence[0], citation_id="cite-khc-prior-bridge"),
        _finance_citation(evidence[1], citation_id="cite-khc-current-bridge"),
    ]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert plan.status == "ready"
    assert plan.diagnostics["bridge_group_key"] in {
        "source:cite-khc-current-bridge",
        "citation:cite-khc-current-bridge",
        "evidence:khc-current-bridge",
    }
    assert plan.diagnostics["bridge_group_key"] != "all"
    assert plan.diagnostics["bridge_detected_column_count"] == 2
    trace = compute_formula(**plan.payload)
    assert trace.result_value == "5468000000"


def test_finance_bridge_planner_rejects_subtotal_that_does_not_match_reported_adjusted() -> None:
    facts = [
        _finance_fact("net income", "4572", fact_id="fact-base"),
        _finance_fact("addback", "2368", fact_id="fact-addback"),
        _finance_fact("adjusted ebitda", "6307", fact_id="fact-adjusted"),
    ]
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["expression"] == "reported_adjusted"
    assert plan.diagnostics["bridge_formula_source"] == "reported_adjusted_only"


def test_finance_bridge_planner_scales_reported_adjusted_from_related_context() -> None:
    facts = [
        _finance_fact(
            "net income",
            "2846000000",
            fact_id="fact-base",
            metadata={
                "context": (
                    "Reconciliation of Net Income/(Loss) to Adjusted EBITDA (in millions) "
                    "Net income/(loss) $ 2,846 $ 2,368"
                )
            },
        ),
        _finance_fact("addback", "2368000000", fact_id="fact-addback"),
        _finance_fact(
            "adjusted ebitda",
            "6003",
            fact_id="fact-adjusted",
            metadata={
                "context": (
                    "Certain non-ordinary course legal and regulatory matters 2 210 "
                    "Equity award compensation expense 141 148 Adjusted EBITDA $ 6,307 $ 6,003"
                )
            },
        ),
    ]
    plan = plan_finance_formula(question="Explain the adjusted EBITDA bridge subtotal.", facts=facts)

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["expression"] == "reported_adjusted"
    assert plan.payload["variables"]["reported_adjusted"] == "6003000000"
    assert plan.diagnostics["reported_adjusted_scale_multiplier"] == "1000000"


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
                "Adjusted EBITDA $ 5,468 $ 4,809"
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
    assert "5468000000" in by_metric["adjusted ebitda"]
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


def test_finance_missing_fact_payload_for_bridge_uses_slot_frame_and_evidence_policy() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="bridge_subtotal",
        missing=["base_metric", "addback_components", "adjusted_metric"],
        goal="For WSC, investigate the adjusted EBITDA add-back trend across public filings.",
    )

    metadata = payload["metadata"]
    assert "annual report" in payload["query"].lower()
    assert "10-k" in payload["query"].lower()
    assert "reconciliation" in payload["query"].lower()
    assert metadata["slot_frame"]["task_type"] == "reconcile"
    assert metadata["missing_slots"] == ["base_metric", "addback_components", "adjusted_metric"]
    assert "regulatory_filing" in metadata["required_source_families"]
    assert "market_data_provider" in metadata["forbidden_source_families"]
    assert "reconciliation" in metadata["required_evidence_terms"]
    assert metadata["evidence_policy"]["authority"] == "primary"


def test_finance_missing_fact_payload_for_transaction_ev_revenue_seeds_sec_issuer_sources() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="ev_revenue",
        missing=["equity_value_or_market_cap"],
        goal=(
            "For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple "
            "using public deal disclosures and filing evidence."
        ),
    )

    source_urls = payload["metadata"]["source_urls"]
    assert "https://data.sec.gov/submissions/CIK0000078003.json" in source_urls
    assert "https://data.sec.gov/submissions/CIK0001060736.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json" in source_urls
    assert payload["source_urls"] == source_urls
    assert payload["metadata"]["preferred_source_families"][0] == "structured_regulatory_data"


def test_finance_missing_fact_payload_for_capital_intensity_seeds_companyfacts() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="capital_intensity",
        missing=["capital_expenditures", "operating_cash_flow", "property_plant_and_equipment_net", "assets"],
        goal=(
            "Benchmark target source follows. Source URL: "
            "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
            "0000066740-23-000014.pdf Company: 3M Document: 3M_2022_10K Document type: 10k "
            "Document period: 2022 Is 3M a capital-intensive business based on FY2022 data?"
        ),
    )

    source_urls = payload["metadata"]["source_urls"]
    assert "https://data.sec.gov/submissions/CIK0000066740.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json" in source_urls
    assert payload["source_urls"] == source_urls
    assert payload["metadata"]["missing_slots"] == [
        "capital_expenditures",
        "operating_cash_flow",
        "property_plant_and_equipment_net",
        "assets",
    ]


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


def test_recipe_evaluator_continues_on_report_workbench_semantic_missing_slots() -> None:
    profile = execution_profile("finance-fact-fast")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "What drove operating margin change as of FY2022 for 3M?",
            "execution_metadata": execution_profile_runtime_metadata(profile),
        },
    )
    evaluator = _RecipeEvaluator(recipe, journal=JournalStore.in_memory())
    context = ContextBundle(
        context_id="ctx-workbench-report",
        thread_key="thread-1",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-workbench-report", "run_id": "run-1"},
        token_budget=4096,
    )
    observation = Observation(
        observation_id="obs-workbench-report",
        run_id="run-1",
        kind="tool_result",
        status="ok",
        source="tool:retrieval.run",
        content={
            "report": {
                "status": "sufficient",
                "diagnostics": {
                    "retrieval_workbench": {
                        "status": "ok",
                        "decision": "continue",
                        "semantic_missing_slots": ["operating_margin_change", "mdna_analysis"],
                        "next_queries": [],
                        "next_document_targets": [],
                    }
                },
            }
        },
        observed_at_ms=1,
        action_id="act-1",
        tool_call_id="tool-1",
    )

    feedback = evaluator.evaluate(context, observation)

    assert feedback.status == "continue"
    assert "retrieval_workbench_followup" in feedback.missing_evidence


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


def test_numeric_verifier_ignores_bare_compact_scale_entity_tokens() -> None:
    facts = [_finance_fact("operating margin change", "1.7", fact_id="margin-change")]

    verification = verify_finance_answer(
        answer="3M 的经营利润率下降了 1.7，引用 cite-1。",
        facts=facts,
        question="Verify 3M operating margin change.",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []


def test_numeric_verifier_keeps_explicit_compact_currency_amounts() -> None:
    facts = [_finance_fact("operating margin change", "1.7", fact_id="margin-change")]

    verification = verify_finance_answer(
        answer="3M 的经营利润率下降了 1.7，但现金为 $3M。",
        facts=facts,
        question="Verify 3M operating margin and cash.",
    )

    assert verification.status == "failed"
    assert any(item["raw"] == "$3M" for item in verification.missing_values)
    assert all(item["raw"] != "3M" for item in verification.missing_values)


def test_finance_fact_ledger_extracts_margin_percentage_point_changes() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="margin-change",
            title="Company margin disclosure",
            uri="https://www.sec.gov/Archives/edgar/data/66740/example.htm",
            text="Operating margin decreased by 1.7 percentage points primarily due to lower gross margin and one-off charges.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-margin-change")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert any(fact.metric == "margin" and Decimal(fact.value) == Decimal("1.7") and fact.unit == "percent" for fact in facts)


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


def test_numeric_verifier_accepts_cited_evidence_numbers_for_explanatory_source_grounded_question() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-3m-margin-drivers",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt",
            text=(
                "Operating income margin 19.1% 20.8% (1.7)%. "
                "Cost of sales increased primarily due to litigation, raw materials and logistics costs. "
                "SG&A increased due to Combat Arms Earplugs litigation, PFAS exit costs, Russia exit costs, "
                "and divestiture-related restructuring charges."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-3m-margin")]

    verification = verify_finance_answer(
        answer=(
            "3M FY2022 operating margin decreased by 1.7%, mainly because cost of sales and SG&A rose; "
            "the cited filing links those increases to litigation, PFAS exit costs, Russia exit costs, and restructuring."
        ),
        facts=[],
        formula_traces=[],
        citations=citations,
        evidence=evidence,
        question="What drove operating margin change as of FY2022 for 3M?",
    )

    assert verification.status == "passed"
    assert verification.diagnostics["cited_evidence_numeric_support_count"] > 0


def test_numeric_verifier_still_requires_formula_or_fact_support_for_calculation_question() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-3m-margin-values",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt",
            text="Operating income margin 19.1% 20.8% (1.7)%.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-3m-margin")]

    verification = verify_finance_answer(
        answer="The calculated operating-margin change is 1.7%.",
        facts=[],
        formula_traces=[],
        citations=citations,
        evidence=evidence,
        question="Calculate the operating margin change for 3M in FY2022.",
    )

    assert verification.status == "failed"
    assert any(issue["code"] == "missing_formula_trace" for issue in verification.issues)


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


def test_finance_formula_preflight_binds_average_per_question_from_provided_table() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="finqa-context",
            text=(
                "Provided report context. table: "
                '[["Company", "Revenue", "Employees"], ["ExampleCo", "$300", "10"]]'
            ),
        )
    ]

    plans = _finance_formula_preflight_plans(
        question="What is the average revenue per employee for ExampleCo?",
        facts=[],
        existing_traces=[],
        evidence=evidence,
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan.status == "ready"
    assert plan.formula_name == "table_average_per"
    assert plan.payload is not None
    assert plan.payload["expression"] == "numerator / denominator"
    assert plan.payload["variables"] == {"numerator": "300", "denominator": "10"}
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) == Decimal("30")


def test_finance_formula_preflight_binds_common_finqa_table_formula_patterns() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="finqa-return",
            text=(
                'table: [["date", "citi", "s&p 500"], ["31-dec-2012", "100.0", "100.0"], '
                '["31-dec-2017", "193.5", "208.1"]]'
            ),
        ),
        _finance_evidence(
            evidence_id="finqa-share",
            text=(
                'table: [["", "oil ( mmbbls )", "total ( mmboe )"], '
                '["canada", "23", "60"], ["total", "66", "243"]]'
            ),
        ),
        _finance_evidence(
            evidence_id="finqa-change",
            text=(
                'table: [["( in millions )", "2017", "2016"], '
                '["operating income", "11503", "10815"]]'
            ),
        ),
    ]

    return_plan = _finance_formula_preflight_plans(
        question="what was the percentage cumulative total return for the five year period ended 31-dec-2017 of citi common stock?",
        facts=[],
        existing_traces=[],
        evidence=[evidence[0]],
    )[0]
    share_plan = _finance_formula_preflight_plans(
        question="what percentage of the total oil and gas mmboe comes from canada?",
        facts=[],
        existing_traces=[],
        evidence=[evidence[1]],
    )[0]
    change_plan = _finance_formula_preflight_plans(
        question="what was the change in millions of operating income from 2016 to 2017?",
        facts=[],
        existing_traces=[],
        evidence=[evidence[2]],
    )[0]

    assert return_plan.formula_name == "cumulative_return_percent"
    assert compute_formula(**return_plan.payload).diagnostics["formatted_value"] == "93.5%"
    assert share_plan.formula_name == "percentage_of_total_source"
    assert compute_formula(**share_plan.payload).diagnostics["formatted_value"] == "24.69135802469135802469135802%"
    assert change_plan.formula_name == "period_change"
    assert Decimal(compute_formula(**change_plan.payload).result_value) == Decimal("688")


def test_finance_formula_preflight_binds_text_tax_difference() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="finqa-aftertax",
            text="These unrealized losses totaled $303 million, or $189 million after-tax.",
        )
    ]

    plan = _finance_formula_preflight_plans(
        question="in 2011 what was the amount of tax related to the unrealized losses reclassifications totaled $303 million, or $189 million after-tax?",
        facts=[],
        existing_traces=[],
        evidence=evidence,
    )[0]

    assert plan.formula_name == "pretax_aftertax_difference"
    assert Decimal(compute_formula(**plan.payload).result_value) == Decimal("114")


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


def test_finance_formula_planner_generates_dcf_payload_with_assumptions() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="crm-cfo",
            text=(
                "entityName=Salesforce ticker=CRM facts="
                "metric=operating cash flow unit=USD fy=2024 form=10-K value=10234000000 ; "
                "metric=capital expenditures unit=USD fy=2024 form=10-K value=710000000 ; "
                "metric=debt unit=USD fy=2024 form=10-K value=8200000000 ; "
                "metric=cash and cash equivalents unit=USD fy=2024 form=10-K value=14000000000 ; "
                "metric=short-term investments unit=USD fy=2024 form=10-K value=3000000000 ; "
                "metric=shares outstanding unit=shares fy=2024 form=10-K value=1580000000"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-crm-cfo")],
    )

    plan = plan_finance_formula(
        question=(
            "Using a discounted cash flow analysis for CRM, forecast 5 years, "
            "cash flow growth 4%, discount rate 9%, terminal growth 2%."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.formula_name == "dcf"
    assert plan.payload is not None
    assert plan.payload["variables"]["base_cash_flow"] == "9524000000"
    assert plan.payload["variables"]["growth_rate"] == "0.04"
    assert plan.payload["variables"]["discount_rate"] == "0.09"
    assert plan.payload["variables"]["terminal_growth_rate"] == "0.02"
    expected_input_fact_ids = {fact.fact_id for fact in facts if fact.metric != "shares outstanding"}
    assert set(plan.payload["input_fact_ids"]) == expected_input_fact_ids
    assert plan.diagnostics["base_cash_flow_metric"] == "derived free cash flow"
    assert plan.diagnostics["assumptions"]["forecast_years"] == 5
    assert plan.diagnostics["defaulted_assumptions"] == []
    assert plan.diagnostics["model_outputs"]["enterprise_value"]
    assert len(plan.diagnostics["model_outputs"]["projection"]) == 5
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) > Decimal("10234000000")
    assert trace.diagnostics["model_outputs"]["enterprise_value"] == plan.diagnostics["model_outputs"]["enterprise_value"]
    assert trace.diagnostics["model_outputs"]["equity_value"]


def test_finance_formula_planner_dcf_can_report_equity_value_per_share() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="dcf-per-share",
            text=(
                "entityName=ExampleCo ticker=EXM facts="
                "metric=free cash flow unit=USD fy=2024 form=10-K value=1000000000 ; "
                "metric=debt unit=USD fy=2024 form=10-K value=2000000000 ; "
                "metric=cash and cash equivalents unit=USD fy=2024 form=10-K value=500000000 ; "
                "metric=shares outstanding unit=shares fy=2024 form=10-K value=100000000"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-dcf-per-share")],
    )

    plan = plan_finance_formula(
        question=(
            "Using a DCF, calculate equity value per share with forecast 5 years, "
            "FCF growth 3%, WACC 9%, terminal growth 2%."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["unit"] == "USD/share"
    assert plan.payload["variables"]["shares"] == "100000000"
    assert plan.diagnostics["reported_output"] == "equity_value_per_share"
    assert plan.diagnostics["model_outputs"]["equity_value_per_share"]
    trace = compute_formula(**plan.payload)
    assert trace.unit == "USD/share"
    assert Decimal(trace.result_value) > Decimal("0")


def test_finance_formula_planner_dcf_can_report_equity_value() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="dcf-equity-value",
            text=(
                "entityName=ExampleCo ticker=EXM facts="
                "metric=free cash flow unit=USD fy=2024 form=10-K value=1000000000 ; "
                "metric=debt unit=USD fy=2024 form=10-K value=2000000000 ; "
                "metric=cash and cash equivalents unit=USD fy=2024 form=10-K value=500000000 ; "
                "metric=short-term investments unit=USD fy=2024 form=10-K value=250000000"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-dcf-equity-value")],
    )

    plan = plan_finance_formula(
        question=(
            "Using a DCF, calculate equity value with forecast 5 years, "
            "FCF growth 3%, WACC 9%, terminal growth 2%."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.diagnostics["reported_output"] == "equity_value"
    trace = compute_formula(**plan.payload)
    assert trace.diagnostics["model_outputs"]["equity_value"] == trace.result_value
    assert Decimal(trace.result_value) < Decimal(trace.diagnostics["model_outputs"]["enterprise_value"])


def test_finance_formula_planner_generates_lbo_payload_with_assumptions() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="epam-market",
            text="entityName=EPAM ticker=EPAM metric=market cap unit=USD fy=2024 value=12000000000",
        ),
        _finance_evidence(
            evidence_id="epam-debt",
            text="entityName=EPAM ticker=EPAM metric=debt unit=USD fy=2024 form=10-K value=1000000000",
        ),
        _finance_evidence(
            evidence_id="epam-cash",
            text="entityName=EPAM ticker=EPAM metric=cash and cash equivalents unit=USD fy=2024 form=10-K value=500000000",
        ),
        _finance_evidence(
            evidence_id="epam-ebitda",
            text="entityName=EPAM ticker=EPAM metric=adjusted ebitda unit=USD fy=2024 form=10-K value=2000000000",
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(
        question=(
            "Build an LBO analysis for EPAM with leverage 4.0x, exit multiple 9.0x, "
            "exit EV/EBITDA convention, EBITDA growth 3%, annual debt paydown 0.5x, "
            "hold period 5 years."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.formula_name == "lbo"
    assert plan.payload is not None
    assert plan.payload["variables"]["debt_multiple"] == "4"
    assert plan.payload["variables"]["exit_multiple"] == "9"
    assert plan.payload["variables"]["ebitda_growth_rate"] == "0.03"
    assert plan.payload["variables"]["annual_debt_paydown_multiple"] == "0.5"
    assert plan.diagnostics["reported_output"] == "sponsor_irr"
    assert plan.diagnostics["model_outputs"]["initial_sponsor_equity"]
    assert plan.diagnostics["model_outputs"]["moic"]
    assert len(plan.diagnostics["model_outputs"]["projection"]) == 5
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) > Decimal("0")
    assert trace.diagnostics["model_outputs"]["sponsor_irr"] == plan.diagnostics["model_outputs"]["sponsor_irr"]


def test_finance_formula_planner_lbo_can_report_moic() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="lbo-moic-market",
            text="entityName=ExampleCo ticker=EXM metric=market cap unit=USD fy=2024 value=12000000000",
        ),
        _finance_evidence(
            evidence_id="lbo-moic-ebitda",
            text="entityName=ExampleCo ticker=EXM metric=adjusted ebitda unit=USD fy=2024 value=2000000000",
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(
        question=(
            "Build an LBO analysis and report MOIC with leverage 4.0x, "
            "exit multiple 9.0x, EBITDA growth 3%, annual debt paydown 0.5x, hold period 5 years."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.diagnostics["reported_output"] == "moic"
    assert plan.payload["unit"] == "x"
    trace = compute_formula(**plan.payload)
    assert trace.diagnostics["model_outputs"]["moic"] == trace.result_value
    assert trace.diagnostics["formatted_value"].endswith(" x")


def test_finance_formula_planner_lbo_can_report_exit_equity_value() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="lbo-exit-equity-market",
            text="entityName=ExampleCo ticker=EXM metric=market cap unit=USD fy=2024 value=12000000000",
        ),
        _finance_evidence(
            evidence_id="lbo-exit-equity-ebitda",
            text="entityName=ExampleCo ticker=EXM metric=adjusted ebitda unit=USD fy=2024 value=2000000000",
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    plan = plan_finance_formula(
        question=(
            "Build an LBO analysis and report exit equity value with leverage 4.0x, "
            "exit multiple 9.0x, EBITDA growth 3%, annual debt paydown 0.5x, hold period 5 years."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.diagnostics["reported_output"] == "exit_equity_value"
    assert plan.payload["unit"] == "USD"
    trace = compute_formula(**plan.payload)
    assert trace.diagnostics["model_outputs"]["exit_equity_value"] == trace.result_value


def test_finance_formula_planner_lbo_uses_assumed_entry_multiple_when_market_value_missing() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="epam-cfo",
            text=(
                "entityName=EPAM ticker=EPAM metric=operating cash flow "
                "unit=USD fy=2024 form=10-K value=800000000"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-epam-cfo")],
    )

    plan = plan_finance_formula(
        question=(
            "Build a compact LBO analysis for EPAM with entry multiple 9.0x, "
            "leverage 3.0x, exit multiple 10.0x, growth 4%, hold period 5 years."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.formula_name == "lbo"
    assert plan.payload is not None
    assert plan.payload["variables"]["equity_value"] == "7200000000"
    assert plan.payload["variables"]["debt"] == "0"
    assert plan.diagnostics["enterprise_value_source"] == "assumed_entry_enterprise_value_from_basis_multiple"
    assert plan.diagnostics["ebitda_source"] == "cash_flow_basis"
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) > Decimal("0")


def test_finance_formula_planner_lbo_can_use_revenue_with_ebitda_margin_assumption() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="epam-revenue",
            text="entityName=EPAM ticker=EPAM metric=revenue unit=USD fy=2024 form=10-K value=4650000000",
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-epam-revenue")],
    )

    plan = plan_finance_formula(
        question=(
            "Build a compact LBO analysis for EPAM with entry multiple 9.0x, "
            "EBITDA margin 18%, leverage 3.0x, exit multiple 10.0x, growth 4%, hold period 5 years."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.formula_name == "lbo"
    assert plan.payload is not None
    assert plan.payload["variables"]["ebitda"] == "837000000"
    assert plan.payload["variables"]["equity_value"] == "7533000000"
    assert plan.diagnostics["ebitda_source"] == "assumed_ebitda_margin_on_revenue"
    assert plan.diagnostics["basis_metric"] == "derived ebitda from revenue"
    trace = compute_formula(**plan.payload)
    assert Decimal(trace.result_value) > Decimal("0")


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


def test_finance_missing_fact_retrieval_action_preserves_target_document_binding() -> None:
    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search. Source URL: "
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf Company: 3M Document: 3M_2022_10K Document type: 10k "
        "Document period: 2022 Is 3M a capital-intensive business based on FY2022 data?"
    )
    binding = target_document_binding_from_metadata(
        {
            "benchmark_doc_retrieval": True,
            "company": "3M",
            "doc_name": "3M_2022_10K",
            "doc_type": "10k",
            "doc_period": "2022",
            "source_url": (
                "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
                "0000066740-23-000014.pdf"
            ),
        },
        question=goal,
    )
    source_action = CandidateAction(
        action_id="act-source",
        kind="tool",
        name="retrieval.run",
        description="initial retrieval",
        score=0.8,
        payload={
            "query": goal,
            "metadata": {
                "benchmark_doc_retrieval": True,
                "target_document_binding": binding,
                "source_urls": [binding["doc_link"]],
                "research_profile": "finance_fundamentals",
            },
        },
        reasons=["initial_retrieval"],
        side_effect_class="network",
    )
    plan = plan_finance_formula(
        question=goal,
        facts=[
            FinanceFact(
                fact_id="revenue-2022",
                entity="3M",
                ticker="MMM",
                period="FY2022",
                fiscal_year=2022,
                metric="revenue",
                value="34229000000",
                unit="USD",
                scale="actual",
                source_ref="source",
                evidence_ref="evidence",
                citation_ref="cite",
                metadata={"concept": "Revenues", "label": "Revenues", "end": "2022-12-31"},
            )
        ],
    )
    action = _finance_missing_fact_retrieval_action(
        source_action,
        plan=plan,
        goal=goal,
        call_index=2,
        recipe=task_recipe("retrieval_answer", metadata={"target_document_binding": binding}),
    )

    assert action is not None
    metadata = action.payload["metadata"]
    assert metadata["target_document_binding"]["doc_period"] == "2022"
    assert metadata["target_document_binding"]["doc_link"] == binding["doc_link"]
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json" in metadata["source_urls"]
    assert binding["doc_link"] in metadata["source_urls"]
    assert metadata["missing_slots"] == [
        "capital_expenditures",
        "operating_cash_flow",
        "property_plant_and_equipment_net",
        "assets",
    ]


def test_benchmark_doc_retrieval_required_source_rejects_generic_companyfacts_citation() -> None:
    source_url = (
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf"
    )
    metadata = {
        "benchmark_doc_retrieval": True,
        "source_url": source_url,
    }
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
                                    "query": "3M FY2022 operating margin drivers",
                                    "metadata": metadata,
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    companyfacts_answer = FinalAnswer(
        answer="3M operating margin changed by 1.7%.",
        citation_refs=["cite-companyfacts"],
        used_evidence=["evidence-companyfacts"],
        limitations=[],
        confidence=0.9,
        task_id="task-doc-source",
        run_id="run-1",
        trace_refs=[],
    )
    companyfacts_citations = [
        CitationItem(
            citation_id="cite-companyfacts",
            goal_id="goal-1",
            evidence_id="evidence-companyfacts",
            artifact_id="artifact-companyfacts",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
            title="SEC companyfacts JSON for CIK 0000066740",
            quote="entityName=3M COMPANY metric=operating income margin value=1.7",
            span_start=0,
            span_end=20,
        )
    ]
    filing_answer = FinalAnswer(
        answer="3M operating margin changed by 1.7%.",
        citation_refs=["cite-filing"],
        used_evidence=["evidence-filing"],
        limitations=[],
        confidence=0.9,
        task_id="task-doc-source",
        run_id="run-1",
        trace_refs=[],
    )
    filing_citations = [
        CitationItem(
            citation_id="cite-filing",
            goal_id="goal-1",
            evidence_id="evidence-filing",
            artifact_id="artifact-filing",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt",
            title="3M 2022 10-K complete submission text",
            quote="Operating income margin 19.1% 20.8% (1.7)%.",
            span_start=0,
            span_end=20,
        )
    ]

    assert not _benchmark_doc_retrieval_primary_citation_satisfies_required_source(
        recipe=recipe,
        answer=companyfacts_answer,
        citations=companyfacts_citations,
    )
    assert _benchmark_doc_retrieval_primary_citation_satisfies_required_source(
        recipe=recipe,
        answer=filing_answer,
        citations=filing_citations,
    )


def test_finance_missing_fact_payload_for_modeling_uses_slot_frame_and_evidence_policy() -> None:
    dcf_payload = _finance_missing_fact_retrieval_payload(
        formula_name="dcf",
        missing=["base_cash_flow", "growth_assumptions", "discount_rate", "terminal_value_assumption"],
        goal="Using a discounted cash flow analysis for CRM, estimate enterprise value.",
    )
    lbo_payload = _finance_missing_fact_retrieval_payload(
        formula_name="lbo",
        missing=["entry_value", "debt_assumption", "cash_flow_or_ebitda", "exit_assumption"],
        goal="Build a compact LBO-style analysis for EPAM using public filing data.",
    )

    assert dcf_payload["metadata"]["slot_frame"]["task_type"] == "model"
    assert "operating cash flow" in dcf_payload["query"].lower()
    assert dcf_payload["metadata"]["preferred_source_families"][0] == "structured_regulatory_data"
    assert "cash flow" in dcf_payload["metadata"]["required_evidence_terms"]
    assert lbo_payload["metadata"]["slot_frame"]["task_type"] == "model"
    assert "adjusted ebitda" in lbo_payload["query"].lower()
    assert "market_data_provider" in lbo_payload["metadata"]["preferred_source_families"]


def test_finance_modeling_retrieval_payload_is_augmented_before_first_fetch() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
    )

    payload = _augment_finance_modeling_retrieval_payload(
        {"query": "EPAM LBO public filings", "queries": ["EPAM LBO public filings"], "max_fetches": 3},
        root_goal="Build a compact LBO-style analysis for EPAM.",
        recipe=recipe,
    )

    assert "operating cash flow" in payload["query"].lower()
    assert "free cash flow" in payload["query"].lower()
    assert "adjusted ebitda" in payload["query"].lower()
    assert payload["max_fetches"] >= 12
    assert payload["metadata"]["finance_modeling_intent"] == "lbo"


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
    gate_records = journal.records(task_id="task-finance", kind="verifier_gate_result")
    assert gate_records
    assert gate_records[-1].data["domain"] == "finance"
    assert gate_records[-1].data["status"] == "passed"
    assert journal.records(task_id="task-finance", kind="finance_fact_ledger")
    assert journal.records(task_id="task-finance", kind="claim_ledger")
    assert journal.records(task_id="task-finance", kind="slot_frame")
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
    transform_plans = journal.records(task_id="task-finance-dio", kind="transform_plan")
    observations = journal.records(task_id="task-finance-dio", kind="observation")
    assert plans
    assert transform_plans
    assert any(record.data["method"] == "dio" for record in transform_plans)
    assert journal.records(task_id="task-finance-dio", kind="claim_ledger")
    slot_frames = journal.records(task_id="task-finance-dio", kind="slot_frame")
    assert slot_frames
    assert slot_frames[-1].data["task_type"] == "compute"
    assert any(record.data.get("source") == f"tool:{CALCULATOR_TOOL_NAME}" for record in observations)
    trace = observations[-1].data["content"]["formula_trace"]
    assert trace["formula_name"] == "dio"
    assert Decimal(trace["result_value"]).quantize(Decimal("0.01")) == Decimal("80.30")


def test_retrieval_finalization_repairs_unsupported_finance_numbers_without_calculator_trace() -> None:
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

    assert failure is None
    assert final is not None
    assert "$999 billion" not in final.answer
    assert final.citation_refs == ["cite-1"]
    assert "保守可验证回答" in final.answer
    assert "metric=revenue" in final.answer
    assert "value=[number]" in final.answer
    assert journal.records(task_id="task-finance", kind="agent_final_answer")
    synthesis_gates = journal.records(task_id="task-finance", kind="synthesis_gate_result")
    assert synthesis_gates
    assert [record.data["status"] for record in synthesis_gates] == ["failed", "passed"]
    assert synthesis_gates[-1].data["policy"] == "material_numeric_claims_require_claim_or_transform_support"
    assert synthesis_gates[-1].data["diagnostics"]["attempt"] == "fallback"


def test_source_grounded_retrieval_finalization_journals_generic_workflow_trace() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="Management describes AI as both an opportunity and a risk, supported by cite-ai.",
        citation_refs=["cite-ai"],
        used_evidence=["evidence-ai"],
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-ai",
            title="Company AI risk disclosure",
            uri="https://www.sec.gov/Archives/edgar/data/0000000000/example/10-k.htm",
            text="Management says artificial intelligence may improve product capabilities but creates security, privacy, and compliance risks.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-ai")]
    recipe = task_recipe("retrieval_answer", metadata={"goal": "Explain AI tailwinds and risks from disclosures."})

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-source-grounded",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    claim_ledgers = journal.records(task_id="task-source-grounded", kind="claim_ledger")
    slot_frames = journal.records(task_id="task-source-grounded", kind="slot_frame")
    transform_plans = journal.records(task_id="task-source-grounded", kind="transform_plan")
    assert claim_ledgers[-1].data["domain"] == "source_grounded_research"
    assert claim_ledgers[-1].data["claim_count"] == 1
    assert slot_frames[-1].data["task_type"] == "source_grounded_research"
    assert slot_frames[-1].data["missing_slots"] == []
    assert transform_plans[-1].data["method"] == "source_grounded_synthesis"
    assert transform_plans[-1].data["status"] == "ready"


def test_partial_retrieval_finalizes_when_max_tool_calls_but_citations_exist() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="The cited filing says litigation and PFAS-related costs pressured margins. [cite-margin]",
        citation_refs=["cite-margin"],
        used_evidence=["evidence-margin"],
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-margin",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/mmm-20221231.htm",
            text="Management says operating margin declined due to litigation, PFAS exit costs, raw materials and logistics costs.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-margin")]
    report = _retrieval_report(evidence=evidence, citations=citations, status="insufficient_evidence")
    for item in evidence:
        journal.append(task_id="task-partial", run_id="run-1", step_id=None, kind="retrieval_evidence", data=item.to_dict())
    for item in citations:
        journal.append(task_id="task-partial", run_id="run-1", step_id=None, kind="retrieval_citation", data=item.to_dict())
    journal.append(task_id="task-partial", run_id="run-1", step_id=None, kind="retrieval_report", data=report.to_dict())
    recipe = task_recipe("retrieval_answer", metadata={"goal": "What drove operating margin change as of FY2022 for 3M?"})

    final, failure = runtime._finalize_retrieval(  # noqa: SLF001
        "task-partial",
        "run-1",
        recipe=recipe,
        loop_stop_reason="max_tool_calls",
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    assert "litigation" in final.answer
    assert final.citation_refs == ["cite-margin"]
    final_records = journal.records(task_id="task-partial", kind="agent_final_answer")
    assert final_records
    assert journal.records(task_id="task-partial", kind="claim_ledger")
    assert final.trace_refs


def test_finance_preflight_without_structured_facts_journals_source_grounded_trace() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(journal, answer="fallback")
    evidence = [
        _finance_evidence(
            evidence_id="evidence-margin",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/mmm-20221231.htm",
            text="Management says operating margin declined due to lower gross margin and one-off charges.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-margin")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "What drove operating margin change as of FY2022 for 3M?",
            "require_numeric_verifier": True,
        },
    )

    runtime._run_finance_numeric_preflight(  # noqa: SLF001
        "task-source-grounded-preflight",
        "run-1",
        recipe=recipe,
        evidence=evidence,
        citations=citations,
    )

    claim_ledgers = journal.records(task_id="task-source-grounded-preflight", kind="claim_ledger")
    slot_frames = journal.records(task_id="task-source-grounded-preflight", kind="slot_frame")
    transform_plans = journal.records(task_id="task-source-grounded-preflight", kind="transform_plan")

    assert claim_ledgers[-1].data["domain"] == "source_grounded_research"
    assert claim_ledgers[-1].data["claim_count"] == 1
    assert slot_frames[-1].data["task_type"] == "source_grounded_research"
    assert any(record.data.get("method") == "source_grounded_synthesis" for record in transform_plans)


def test_source_grounded_finance_fallback_uses_cited_evidence_when_synthesizer_adds_unsupported_number() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="3M FY2022 operating margin changed by 999%, supported by cite-margin.",
        citation_refs=["cite-margin"],
        used_evidence=["evidence-margin"],
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-margin",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt",
            text=(
                "Operating Expenses: 2022 2021 Change. Cost of sales 56.2% 53.2% 3.0%. "
                "SG&A 26.5% 20.4% 6.1%. Operating income margin 19.1% 20.8% (1.7)%. "
                "Cost of sales increased primarily due to litigation, raw materials and logistics costs. "
                "SG&A increased due to Combat Arms Earplugs litigation, PFAS exit costs, Russia exit costs, "
                "and divestiture-related restructuring charges."
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-margin")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "What drove operating margin change as of FY2022 for 3M?",
            "workflow_type": "source_grounded_research",
            "require_numeric_verifier": True,
        },
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-source-grounded-repair",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    assert "999" not in final.answer
    assert "1.7" in final.answer
    assert final.citation_refs == ["cite-margin"]
    synthesis_gates = journal.records(task_id="task-source-grounded-repair", kind="synthesis_gate_result")
    assert synthesis_gates[-1].data["status"] == "passed"


def test_retrieval_finalization_repairs_unsupported_finance_numbers_with_calculator_trace() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="KHC adjusted EBITDA was 0.54 and $999 billion, supported by cite-1.",
    )
    trace = compute_formula(
        expression="base + addback_1",
        variables={"base": "2846000000", "addback_1": "2823000000"},
        unit="USD",
        formula_name="bridge_subtotal",
        input_fact_ids=["fact-base", "fact-addback"],
    )
    journal.append(
        task_id="task-finance-repair",
        run_id="run-1",
        step_id=None,
        kind="observation",
        data={
            "source": f"tool:{CALCULATOR_TOOL_NAME}",
            "status": "ok",
            "content": {"formula_trace": trace.to_dict()},
        },
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-1",
            title="Kraft Heinz 2023 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-20231230.htm",
            text="KHC adjusted EBITDA bridge evidence with source-backed calculator inputs.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-1")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance-repair",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    assert "5669000000 USD" in final.answer
    assert "$999 billion" not in final.answer
    verifications = journal.records(task_id="task-finance-repair", kind="finance_numeric_verification")
    assert verifications[-1].data["status"] == "passed"
    synthesis_gates = journal.records(task_id="task-finance-repair", kind="synthesis_gate_result")
    assert [record.data["status"] for record in synthesis_gates] == ["failed", "passed"]
    assert synthesis_gates[-1].data["diagnostics"]["attempt"] == "fallback"


def test_retrieval_finalization_fallback_preserves_dcf_model_outputs_and_assumptions() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="CRM DCF enterprise value is $999 billion, supported by cite-1.",
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-1",
            title="Salesforce FY2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/1108524/example/crm-20240131.htm",
            text=(
                "entityName=Salesforce ticker=CRM facts="
                "metric=operating cash flow unit=USD fy=2024 form=10-K value=10234000000 ; "
                "metric=capital expenditures unit=USD fy=2024 form=10-K value=710000000 ; "
                "metric=debt unit=USD fy=2024 form=10-K value=8200000000 ; "
                "metric=cash and cash equivalents unit=USD fy=2024 form=10-K value=14000000000 ; "
                "metric=short-term investments unit=USD fy=2024 form=10-K value=3000000000"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-1")]
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    plan = plan_finance_formula(
        question=(
            "Using a discounted cash flow analysis for CRM, forecast 5 years, "
            "cash flow growth 4%, discount rate 9%, terminal growth 2%."
        ),
        facts=facts,
    )
    assert plan.status == "ready"
    assert plan.payload is not None
    trace = compute_formula(**plan.payload)
    journal.append(
        task_id="task-dcf-repair",
        run_id="run-1",
        step_id=None,
        kind="observation",
        data={
            "source": f"tool:{CALCULATOR_TOOL_NAME}",
            "status": "ok",
            "content": {"formula_trace": trace.to_dict()},
        },
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-dcf-repair",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    assert "$999 billion" not in final.answer
    assert "建模假设" in final.answer
    assert "DCF 核心模型输出" in final.answer
    assert "enterprise_value" in final.answer
    assert "FormulaTrace" in final.answer
    verifications = journal.records(task_id="task-dcf-repair", kind="finance_numeric_verification")
    assert verifications[-1].data["status"] == "passed"
    synthesis_gates = journal.records(task_id="task-dcf-repair", kind="synthesis_gate_result")
    assert [record.data["status"] for record in synthesis_gates] == ["failed", "passed"]


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
    assert items[0].workflow_type == "multi_entity_compute_compare"
    assert "inventory_begin" in items[0].required_slots
    assert items[0].evidence_policy["required_source_families"] == ["sec_filings"]
    assert "dio" in items[0].required_transforms
    assert "synthesis_gate" in items[0].expected_trace
    assert items[1].metadata["category"] == "financial_modeling"
    assert items[1].workflow_type == "modeling_lite"
    assert "assumptions_labeled" in items[1].dealbreakers
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["prompt_policy"]["gold_answer_in_prompt"] is False
    assert "workflow_annotation" in manifest_payload["normalized_schema"]


def _runtime_with_synthesizer(
    journal: JournalStore,
    *,
    answer: str,
    citation_refs: list[str] | None = None,
    used_evidence: list[str] | None = None,
) -> AgentRuntime:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "synthesizer.answer": {
                        "answer": answer,
                        "citation_refs": citation_refs or ["cite-1"],
                        "confidence": 0.9,
                        "limitations": [],
                        "used_evidence": used_evidence or ["evidence-1"],
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


def _retrieval_report(
    *,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    status: str = "sufficient",
) -> RetrievalReport:
    return RetrievalReport(
        report_id="report-1",
        goal_id="goal-1",
        status=status,
        query_plan_id="query-plan-1",
        search_attempt_ids=["search-1"],
        fetch_attempt_ids=["fetch-1"],
        evidence_ids=[item.evidence_id for item in evidence],
        citation_ids=[item.citation_id for item in citations],
        evaluation_id="eval-1",
        artifact_refs=["artifact-1"],
        preview="SEC companyfacts evidence",
    )
