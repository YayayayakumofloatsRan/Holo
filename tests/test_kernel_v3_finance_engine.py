from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.contracts import FinalAnswer, SemanticIntake
from kernel_v3.agent.execution_profile import execution_profile, execution_profile_runtime_metadata
from kernel_v3.agent.runtime import (
    _AgentContextCompiler,
    _RecipeBoundPlanner,
    _RecipeEvaluator,
    _agent_replan_hints,
    _apply_recipe_profile_defaults,
    _benchmark_doc_retrieval_primary_citation_satisfies_required_source,
    _compiled_task_hint_for_retrieval,
    _enforce_benchmark_doc_retrieval_binding,
    _augment_finance_modeling_retrieval_payload,
    _finance_fallback_fact_lines,
    _finance_missing_fact_retrieval_action,
    _finance_missing_fact_retrieval_payload,
    _finance_formula_preflight_plans,
    _can_synthesize_partial_retrieval,
    _compact_finance_synthesis_rescue_packet,
    _finance_fact_judge_summary,
    _finance_formula_trace_synthesis_policy,
    _finance_formula_traces_for_synthesis,
    _finance_working_state_for_prompt,
    _model_compiled_program_authorizes_numeric_preflight,
    _finance_slot_bind_plans_from_model,
    _finance_slot_bind_prompt,
    _report_with_finance_formula_traces,
    _host_semantic_fallbacks_enabled,
    _rank_finance_facts_for_model,
    _finance_capability_execute_clarification_as_retrieval,
    _finance_numeric_judge_accepts_answer,
    _finance_numeric_judge_prompt,
    _planner_directive,
    _planner_allowed_tool_names,
    _candidate_fact_evidence_text,
    _report_with_finance_fact_context,
    _retrieval_and_toolchain_grounding,
    _retrieval_payload,
    _retrieval_capability_args,
    _toolchain_candidate_facts,
    _toolchain_state_for_prompt,
    _workspace_grounding,
    task_recipe,
)
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation, ProcessorRequest, ProcessorResult
from kernel_v3.bench import convert_public_finance_benchmark, load_finance_benchmark_items
from kernel_v3.context import ArtifactStore
from kernel_v3.finance import (
    CALCULATOR_TOOL_NAME,
    FINANCE_VERIFY_NUMERIC_TOOL_NAME,
    FinanceFact,
    FormulaTrace,
    attach_target_binding_to_facts,
    build_finance_fact_ledger,
    compile_finance_task_program,
    compile_finance_task_program_model_first,
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
from kernel_v3.finance.task_compiler import TASK_COMPILE_FACT_LIMIT, _model_task_compile_prompt
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.processors import FakeJsonProvider, ModelPlanner, ProcessorFabric, ProcessorRouter
from kernel_v3.policy import PolicyGate
from kernel_v3.processors.adapters import _synthesizer_prompt
from kernel_v3.research.profiles import finance_fundamentals_profile
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, FetchedDocument, RetrievalReport, SearchGoal
from kernel_v3.retrieval.evaluate import qualify_evidence_candidate
from kernel_v3.retrieval.extract import extract_spans, readable_document_text
from kernel_v3.retrieval.targeting import target_entity_phrases
from kernel_v3.session import TaskState
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
    capex_intensity = compute_formula(
        expression="abs(capex_raw) / revenue",
        variables={"capex_raw": "-1749000000", "revenue": "34229000000"},
        unit="percent",
        formula_name="capex_intensity",
    )

    assert abs((Decimal(cagr.result_value) * Decimal(100)) - Decimal("22.62")) < Decimal("0.01")
    assert Decimal(dio.result_value).quantize(Decimal("0.01")) == Decimal("34.15")
    assert Decimal(bps.result_value) == Decimal("42")
    assert Decimal(ev_revenue.result_value) == Decimal("4")
    assert Decimal(capex_intensity.result_value).quantize(Decimal("0.0001")) == Decimal("0.0511")


def test_finance_formula_traces_for_synthesis_prefers_slot_bound_traces() -> None:
    exploratory = FormulaTrace(
        formula_id="formula-early-ppe-assets",
        formula_name="capital_intensity",
        expression="ppe_net / total_assets",
        input_fact_ids=["fact-ppe-net-2022", "fact-total-assets-2022"],
        result_value="0.221",
        unit="ratio",
        diagnostics={"semantic_decision_owner": "model"},
    )
    slot_bound = FormulaTrace(
        formula_id="formula-slot-ppe-assets",
        formula_name="ppe_to_assets",
        expression="ppe_net / assets",
        input_fact_ids=["finfact-ppe", "finfact-assets"],
        result_value="0.1976",
        unit="percent",
        diagnostics={"source": "finance_slot_bind_model"},
    )

    ordered = _finance_formula_traces_for_synthesis([exploratory, slot_bound])

    assert [trace.formula_id for trace in ordered] == ["formula-slot-ppe-assets", "formula-early-ppe-assets"]


def test_finance_formula_trace_policy_preserves_capital_intensity_roa() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-slot-capex-revenue",
            formula_name="capital_intensity_capex_revenue",
            expression="abs(capex_raw) / revenue",
            input_fact_ids=["finfact-capex", "finfact-revenue"],
            result_value="0.0511",
            unit="percent",
            diagnostics={"source": "finance_slot_bind_model", "formatted_value": "5.11%", "method": "capex_to_revenue"},
        ),
        FormulaTrace(
            formula_id="formula-slot-roa",
            formula_name="capital_intensity_return_on_assets",
            expression="net_income / assets",
            input_fact_ids=["finfact-net-income", "finfact-assets"],
            result_value="0.1244",
            unit="percent",
            diagnostics={"source": "finance_slot_bind_model", "formatted_value": "12.44%", "method": "roa"},
        ),
    ]

    policy = _finance_formula_trace_synthesis_policy(traces)

    assert policy["task_family"] == "capital_intensity_assessment"
    assert "capex_to_revenue" in policy["available_lenses"]
    assert "return_on_assets" in policy["available_lenses"]
    assert "roa_preservation_instruction" in policy
    assert policy["supported_trace_outputs"][0]["formatted_value"] == "5.11%"
    assert "generic industry thresholds" in policy["unsupported_comparison_number_policy"]


def test_finance_formula_trace_support_links_traces_to_fact_citations_in_synthesizer_prompt() -> None:
    journal = JournalStore.in_memory()
    trace = FormulaTrace(
        formula_id="formula-slot-capex-revenue",
        formula_name="capital_intensity_capex_revenue",
        expression="abs(capex_raw) / revenue",
        input_fact_ids=["fact-capex", "fact-revenue"],
        result_value="0.0511",
        unit="percent",
        diagnostics={
            "source": "finance_slot_bind_model",
            "formatted_value": "5.11%",
            "method": "capex_to_revenue",
            "output_attribute": "capex_to_revenue",
        },
    )
    journal.append(
        task_id="task-trace-support",
        run_id="run-1",
        step_id=None,
        kind="observation",
        data={
            "source": f"tool:{CALCULATOR_TOOL_NAME}",
            "status": "ok",
            "content": {"formula_trace": trace.to_dict()},
        },
    )
    journal.append(
        task_id="task-trace-support",
        run_id="run-1",
        step_id=None,
        kind="finance_slot_bind",
        data={
            "schema": "holo.kernel_v3.finance_slot_bind.v1",
            "status": "ready",
            "decision": "ready",
            "accepted_formula_plan_count": 1,
            "period_basis": [
                {"slot_name": "capex", "fact_id": "fact-capex", "selected_period": "FY2022", "reason": "10-K FY fact"}
            ],
            "line_item_basis": [
                {
                    "slot_name": "capex",
                    "fact_id": "fact-capex",
                    "selected_line_item": "capital expenditures",
                    "reason": "cash-flow PP&E purchases row",
                }
            ],
            "reason_summary": "Model bound capex and net sales from FY2022 filing facts.",
        },
    )
    report = replace(
        _retrieval_report(evidence=[], citations=[]),
        diagnostics={
            "finance_fact_ledger": [
                {
                    "fact_id": "fact-capex",
                    "metric": "capital expenditures",
                    "value": "-1749000000",
                    "unit": "USD",
                    "fiscal_year": 2022,
                    "evidence_ref": "evidence-capex",
                    "citation_ref": "cite-capex",
                    "metadata": {
                        "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
                        "label": "Capital expenditures",
                        "form": "10-K",
                        "fp": "FY",
                        "source_uri": "https://www.sec.gov/example/mmm-2022.htm",
                    },
                },
                {
                    "fact_id": "fact-revenue",
                    "metric": "net sales",
                    "value": "34229000000",
                    "unit": "USD",
                    "fiscal_year": 2022,
                    "evidence_ref": "evidence-revenue",
                    "citation_ref": "cite-revenue",
                    "metadata": {
                        "concept": "Revenues",
                        "label": "Net sales",
                        "form": "10-K",
                        "fp": "FY",
                        "source_uri": "https://www.sec.gov/example/mmm-2022.htm",
                    },
                },
            ]
        },
    )

    enriched = _report_with_finance_formula_traces(journal, report, task_id="task-trace-support", run_id="run-1")
    prompt_payload = json.loads(_synthesizer_prompt(enriched, [], []))
    diagnostics = prompt_payload["retrieval_report"]["diagnostics"]
    support = diagnostics["finance_formula_trace_support"][0]

    assert support["formula_id"] == "formula-slot-capex-revenue"
    assert support["support_status"] == "linked_to_fact_ledger"
    assert support["citation_refs"] == ["cite-capex", "cite-revenue"]
    assert support["evidence_refs"] == ["evidence-capex", "evidence-revenue"]
    assert [item["fact_id"] for item in support["input_facts"]] == ["fact-capex", "fact-revenue"]
    assert support["input_facts"][0]["raw_fields"]["concept"] == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert diagnostics["finance_slot_bind_state"]["period_basis"][0]["selected_period"] == "FY2022"
    assert diagnostics["finance_slot_bind_state"]["line_item_basis"][0]["selected_line_item"] == "capital expenditures"
    assert diagnostics["finance_slot_bind_basis_policy"]["semantic_decision_owner"] == "model"


def test_compact_finance_synthesis_rescue_packet_exposes_formula_trace_support() -> None:
    journal = JournalStore.in_memory()
    trace = FormulaTrace(
        formula_id="formula-slot-bridge",
        formula_name="bridge_subtotal",
        expression="base + addback",
        input_fact_ids=["fact-base", "fact-addback"],
        result_value="5669000000",
        unit="USD",
        diagnostics={"source": "finance_slot_bind_model", "formatted_value": "$5.669B"},
    )
    journal.append(
        task_id="task-compact-trace-support",
        run_id="run-1",
        step_id=None,
        kind="observation",
        data={
            "source": f"tool:{CALCULATOR_TOOL_NAME}",
            "status": "ok",
            "content": {"formula_trace": trace.to_dict()},
        },
    )
    journal.append(
        task_id="task-compact-trace-support",
        run_id="run-1",
        step_id=None,
        kind="finance_slot_bind",
        data={
            "schema": "holo.kernel_v3.finance_slot_bind.v1",
            "status": "ready",
            "decision": "ready",
            "accepted_formula_plan_count": 1,
            "period_basis": [
                {"slot_name": "base", "fact_id": "fact-base", "selected_period": "FY bridge", "reason": "same bridge table"}
            ],
            "line_item_basis": [
                {"slot_name": "addback", "fact_id": "fact-addback", "selected_line_item": "add-back", "reason": "bridge row label"}
            ],
            "reason_summary": "Model bound the bridge subtotal inputs.",
        },
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-base",
            title="KHC adjusted EBITDA bridge",
            text="Adjusted EBITDA base value was 2,846 and add-back was 2,823.",
        ),
        _finance_evidence(
            evidence_id="evidence-addback",
            title="KHC adjusted EBITDA bridge",
            text="The add-back line item was 2,823.",
        ),
    ]
    citations = [
        _finance_citation(evidence[0], citation_id="cite-base"),
        _finance_citation(evidence[1], citation_id="cite-addback"),
    ]
    report = _retrieval_report(evidence=evidence, citations=citations)
    recipe = task_recipe("retrieval_answer", metadata={"goal": "Compute KHC adjusted EBITDA bridge subtotal."})

    rescue_report, _rescue_evidence, _rescue_citations = _compact_finance_synthesis_rescue_packet(
        journal,
        task_id="task-compact-trace-support",
        run_id="run-1",
        recipe=recipe,
        report=report,
        evidence=evidence,
        citations=citations,
        synthesis_error="test_compaction",
    )

    support = rescue_report.diagnostics["finance_formula_trace_support"][0]
    assert support["formula_id"] == "formula-slot-bridge"
    assert support["support_status"] in {"linked_to_fact_ledger", "trace_only"}
    assert "citation_refs" in support
    assert "input_facts" in support
    assert rescue_report.diagnostics["finance_slot_bind_state"]["period_basis"][0]["selected_period"] == "FY bridge"
    assert rescue_report.diagnostics["finance_slot_bind_state"]["line_item_basis"][0]["selected_line_item"] == "add-back"


def test_compact_finance_synthesis_rescue_packet_exposes_competing_fact_clusters() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-total-revenues",
            text=(
                "SEC companyfacts official financial statement entityName=Chevron Corp "
                "concept=Revenues label=Revenues metric=revenue unit=USD period=annual fy=2024 "
                "form=10-K value=202792000000"
            ),
        ),
        _finance_evidence(
            evidence_id="evidence-sales-revenues",
            text=(
                "SEC filing statement entityName=Chevron Corp concept=SalesAndOtherOperatingRevenue "
                "label=Sales and Other Operating Revenues metric=sales and other operating revenues "
                "unit=USD period=annual fy=2024 form=10-K value=193414000000"
            ),
        ),
    ]
    evidence[0].diagnostics.update(
        {
            "span_metadata": {
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 2.5,
                    "matched_preferred": ["metric=revenue"],
                    "matched_demoted": [],
                }
            }
        }
    )
    evidence[1].diagnostics.update(
        {
            "span_metadata": {
                "target_line_item": "total revenues",
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 13.5,
                    "matched_preferred": ["metric=sales and other operating revenues"],
                    "matched_demoted": [],
                },
            }
        }
    )
    citations = [_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence]
    report = _retrieval_report(evidence=evidence, citations=citations)
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"goal": "What was Chevron's total revenues for fiscal year 2024?"},
    )

    rescue_report, _rescue_evidence, _rescue_citations = _compact_finance_synthesis_rescue_packet(
        JournalStore.in_memory(),
        task_id="task-compact-clusters",
        run_id="run-1",
        recipe=recipe,
        report=report,
        evidence=evidence,
        citations=citations,
        synthesis_error="test_compaction",
    )

    clusters = rescue_report.diagnostics["finance_competing_fact_clusters"]
    assert clusters
    assert clusters[0]["host_role"] == "attention_grouping_only_no_semantic_preference"
    assert clusters[0]["candidate_ordering"] == "source_order_from_raw_facts"
    assert [item["value"] for item in clusters[0]["candidates"]] == ["202792000000", "193414000000"]


def test_compact_finance_synthesis_rescue_packet_exposes_numeric_repair_context_to_synthesizer() -> None:
    journal = JournalStore.in_memory()
    task_id = "task-compact-repair-context"
    run_id = "run-1"
    question = "What was Example Co FY2024 revenue from the 2024 10-K?"
    target_url = "https://www.sec.gov/Archives/example/example-2024-10k.htm"
    binding = target_document_binding_from_metadata(
        {
            "company": "Example Co",
            "doc_link": target_url,
            "doc_period": "2024",
            "doc_type": "10-K",
            "required_statement": "income_statement",
            "required_line_item": "revenue",
            "primary_source_required": True,
        }
    )
    facts = [
        FinanceFact(
            fact_id="target-revenue",
            entity="Example Co",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="10",
            unit="USD",
            scale=None,
            source_ref="target",
            evidence_ref="ev-target",
            citation_ref="cite-target",
            metadata={
                "source_uri": target_url,
                "source_title": "Example Co 2024 10-K",
                "statement": "income_statement",
                "form": "10-K",
                "context": "Revenue 10",
            },
        ),
        FinanceFact(
            fact_id="secondary-revenue",
            entity="Example Co",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="11",
            unit="USD",
            scale=None,
            source_ref="secondary",
            evidence_ref="ev-secondary",
            citation_ref="cite-secondary",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/exm/financials/",
                "source_title": "Example Co Financials - StockAnalysis",
                "context": "Revenue 11",
            },
        ),
    ]
    verification = verify_finance_answer(
        answer="Example Co FY2024 revenue was 10%.",
        facts=facts,
        question=question,
        target_binding=binding,
    )
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=None,
        kind="finance_numeric_verification",
        data={**verification.to_dict(), "schema": "holo.kernel_v3.finance_numeric_verification.v1"},
    )
    evidence = [
        _finance_evidence(
            evidence_id="ev-target",
            uri=target_url,
            title="Example Co 2024 10-K",
            text="entityName=Example Co metric=revenue unit=USD fy=2024 form=10-K value=10",
        ),
        _finance_evidence(
            evidence_id="ev-secondary",
            uri="https://stockanalysis.com/stocks/exm/financials/",
            title="Example Co Financials - StockAnalysis",
            text="entityName=Example Co metric=revenue unit=USD fy=2024 value=11",
        ),
    ]
    citations = [
        _finance_citation(evidence[0], citation_id="cite-target"),
        _finance_citation(evidence[1], citation_id="cite-secondary"),
    ]
    report = _retrieval_report(evidence=evidence, citations=citations)
    recipe = task_recipe("retrieval_answer", metadata={"goal": question, "target_document_binding": binding})

    rescue_report, rescue_evidence, rescue_citations = _compact_finance_synthesis_rescue_packet(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
        report=report,
        evidence=evidence,
        citations=citations,
        synthesis_error="finance_numeric_judge_repair:test",
    )
    prompt_payload = json.loads(_synthesizer_prompt(rescue_report, rescue_evidence, rescue_citations))
    repair_context = prompt_payload["retrieval_report"]["diagnostics"]["finance_numeric_repair_context"]

    assert repair_context["status"] == "failed"
    assert repair_context["semantic_decision_owner"] == "model"
    assert repair_context["host_role"] == "diagnostic_carrier_only"
    assert repair_context["unit_mismatch_examples"][0]["raw"] == "10%"
    assert repair_context["unit_mismatch_examples"][0]["support_units"] == ["usd"]
    assert "unit or scale wording" in " ".join(repair_context["repair_options"])
    assert repair_context["target_document_binding"]["doc_period"] == "2024"
    assert repair_context["target_document_binding"]["required_line_item"] == "revenue"
    binding_context = repair_context["primary_source_numeric_binding"]
    assert binding_context["status"] == "selected"
    assert binding_context["selected_fact_ids"] == ["target-revenue"]
    assert binding_context["rejected_count"] == 1
    assert binding_context["rejected_candidates"][0]["fact_id"] == "secondary-revenue"


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


def test_finance_numeric_verifier_is_registered_as_read_only_tool() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    manifests = {item.name: item for item in registry.manifests()}
    fact = FinanceFact(
        fact_id="fact-revenue",
        entity="Example Co",
        ticker="EXM",
        period="FY2024",
        fiscal_year=2024,
        metric="revenue",
        value="10000000",
        unit="USD",
        scale=None,
        source_ref="src-1",
        evidence_ref="ev-1",
        citation_ref="cite-1",
        metadata={},
    )
    action = CandidateAction(
        action_id="act-verify-1",
        kind="tool",
        name=FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        description="verify model answer numeric support",
        score=0.9,
        payload={
            "answer": "Example Co FY2024 revenue was $10 million.",
            "facts": [fact.to_dict()],
            "question": "What was Example Co FY2024 revenue?",
        },
        reasons=["the answer has a material numeric finance claim"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_only").validate(
        run_id="run-finance-verify",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert manifests[FINANCE_VERIFY_NUMERIC_TOOL_NAME].side_effect_class == "read"
    assert manifests[FINANCE_VERIFY_NUMERIC_TOOL_NAME].permissions_required == []
    assert manifests[FINANCE_VERIFY_NUMERIC_TOOL_NAME].input_schema["answer"]["required"] is True
    assert decision.allowed
    assert observation.status == "ok"
    assert observation.kind == "finance_numeric_verification"
    assert observation.source == f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}"
    assert observation.content["verifier_status"] == "passed"
    assert observation.content["verification"]["status"] == "passed"
    assert observation.content["matched_value_count"] >= 1
    assert observation.content["repair_guidance"]["schema"] == "holo.kernel_v3.finance_numeric_repair_guidance.v1"
    assert observation.content["repair_options"] == []
    assert observation.content["missing_value_examples"] == []


def test_finance_numeric_verifier_tool_observation_exposes_repair_guidance() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    fact = FinanceFact(
        fact_id="fact-revenue",
        entity="Example Co",
        ticker="EXM",
        period="FY2024",
        fiscal_year=2024,
        metric="revenue",
        value="10000000",
        unit="USD",
        scale=None,
        source_ref="src-1",
        evidence_ref="ev-1",
        citation_ref="cite-1",
        metadata={},
    )
    action = CandidateAction(
        action_id="act-verify-repair",
        kind="tool",
        name=FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        description="verify model answer numeric support",
        score=0.9,
        payload={
            "answer": "Example Co FY2024 revenue was $12 million.",
            "facts": [fact.to_dict()],
            "question": "What was Example Co FY2024 revenue?",
        },
        reasons=["the answer has a material numeric finance claim"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_only").validate(
        run_id="run-finance-verify",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert observation.status == "ok"
    assert observation.content["verifier_status"] == "failed"
    assert observation.content["repair_guidance"]["schema"] == "holo.kernel_v3.finance_numeric_repair_guidance.v1"
    assert observation.content["repair_guidance"]["issue_codes"] == [
        "unsupported_answer_number",
        "ledger_extraction_gap",
    ]
    assert observation.content["missing_value_examples"] == [
        {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": ""}
    ]
    repair_options = " ".join(observation.content["repair_options"])
    assert "remove or replace unsupported answer numbers" in repair_options
    assert "FinanceFact records" in repair_options
    assert "model still owns semantic repair" in observation.content["repair_guidance"]["host_boundary"]


def test_finance_numeric_verifier_tool_observation_exposes_unit_mismatch_examples() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    fact = FinanceFact(
        fact_id="fact-revenue",
        entity="Example Co",
        ticker="EXM",
        period="FY2024",
        fiscal_year=2024,
        metric="revenue",
        value="10",
        unit="USD",
        scale=None,
        source_ref="src-1",
        evidence_ref="ev-1",
        citation_ref="cite-1",
        metadata={},
    )
    action = CandidateAction(
        action_id="act-verify-unit-repair",
        kind="tool",
        name=FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        description="verify model answer numeric support",
        score=0.9,
        payload={
            "answer": "Example Co FY2024 revenue was 10%.",
            "facts": [fact.to_dict()],
            "question": "What was Example Co FY2024 revenue?",
        },
        reasons=["the answer has a material numeric finance claim"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_only").validate(
        run_id="run-finance-verify",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert observation.status == "ok"
    assert observation.content["verifier_status"] == "failed"
    assert observation.content["repair_guidance"]["issue_codes"] == ["unit_mismatch"]
    assert observation.content["missing_value_examples"] == []
    assert observation.content["unit_mismatch_examples"] == [
        {
            "raw": "10%",
            "value": "10",
            "unit": "percent",
            "support_units": ["usd"],
            "support_kinds": ["finance_fact"],
            "support_refs": ["fact-revenue"],
        }
    ]
    repair_options = " ".join(observation.content["repair_options"])
    assert "unit or scale wording" in repair_options
    assert "model still owns semantic repair" in observation.content["repair_guidance"]["host_boundary"]


def test_finance_numeric_verifier_tool_schema_rejects_non_object_fact_rows() -> None:
    registry = register_finance_tools(ToolRegistry.with_builtin_respond())
    action = CandidateAction(
        action_id="act-verify-bad-facts",
        kind="tool",
        name=FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        description="verify bad payload",
        score=0.9,
        payload={
            "answer": "Example Co FY2024 revenue was $10 million.",
            "facts": ["not-a-finance-fact-object"],
        },
        reasons=["schema_boundary_test"],
        side_effect_class="read",
    )
    decision = PolicyGate(permission="read_only").validate(
        run_id="run-finance-verify",
        action=action,
        manifest=registry.manifest_for_action(action),
    )

    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert decision.allowed
    assert observation.status == "blocked"
    assert observation.content["reason"] == "invalid_tool_payload"
    assert observation.content["error"] == "invalid_field_type:facts:list[object]"


def test_formula_planner_does_not_force_generic_growth_into_yoy_formula() -> None:
    plan = plan_finance_formula(
        question="If we exclude the impact of M&A, which segment dragged down 3M's overall growth in 2022?",
        facts=[],
    )

    assert plan.status == "not_applicable"
    assert plan.formula_name is None


def test_formula_planner_keeps_explicit_growth_rate_formula() -> None:
    plan = plan_finance_formula(question="What is the year-over-year revenue growth rate?", facts=[])

    assert plan.status == "missing_facts"
    assert plan.formula_name == "yoy_growth"
    assert plan.missing_facts == ["prior_period_value", "current_period_value"]


def test_retrieval_compiled_hint_prefers_model_execution_program_over_fallback() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "execution_program": {
                "schema": "holo.kernel_v3.compiled_task_program.v1",
                "program_id": "program-model-disclosure",
                "domain": "finance",
                "source": "task_compile_model",
                "task_spec": {
                    "task_type": "disclosure_analysis",
                    "objective": "Identify the segment driver from the target filing discussion.",
                    "target_entities": ["3M"],
                    "target_periods": ["FY2022"],
                    "success_criteria": ["cite the target filing discussion"],
                    "diagnostics": {"source": "task_compile_model"},
                },
                "evidence_specs": [
                    {
                        "slot_name": "segment_discussion",
                        "accepted_attributes": ["business segment discussion", "organic sales change"],
                        "source_role": "primary_filing",
                        "required_source_families": ["regulatory_filing"],
                        "target_period": "FY2022",
                        "statement": "business segment discussion",
                        "line_item": "net sales by business segment",
                        "required": True,
                    }
                ],
                "transform_specs": [],
                "slot_frame": {
                    "task_type": "disclosure_analysis",
                    "required_slots": [{"name": "segment_discussion"}],
                    "missing_slots": ["segment_discussion"],
                },
                "diagnostics": {
                    "source": "task_compile_model",
                    "tool_chain_plan": {
                        "schema": "holo.kernel_v3.tool_chain_plan.v1",
                        "decision_owner": "model",
                        "recommended_steps": [{"step": "read_target_filing_discussion", "tool": "retrieval.run"}],
                    },
                },
            }
        },
    )

    hint = _compiled_task_hint_for_retrieval(
        question="If we exclude the impact of M&A, which segment dragged down growth in 2022?",
        binding={"company": "3M", "doc_period": "FY2022", "doc_type": "10-K"},
        recipe=recipe,
    )

    assert hint["diagnostics"]["source"] == "recipe_execution_program"
    assert hint["task_spec"]["task_type"] == "disclosure_analysis"
    assert hint["evidence_specs"][0]["slot_name"] == "segment_discussion"
    assert hint["transform_specs"] == []
    assert hint["missing_slots"] == ["segment_discussion"]


def test_benchmark_retrieval_payload_uses_recipe_execution_program_hint() -> None:
    goal = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself.\n"
        "Company: 3M\n"
        "Document: 3M_2022_10K\n"
        "Document type: 10-K\n"
        "Document period: 2022\n"
        "Source URL: https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/mmm-20221231.htm\n\n"
        "If we exclude the impact of M&A, which segment dragged down 3M's overall growth in 2022?"
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": goal,
            "execution_program": {
                "schema": "holo.kernel_v3.compiled_task_program.v1",
                "program_id": "program-model-disclosure-payload",
                "domain": "finance",
                "source": "task_compile_model",
                "task_spec": {
                    "task_type": "disclosure_analysis",
                    "objective": "Use the target filing to identify the segment driver.",
                    "target_entities": ["3M"],
                    "target_periods": ["FY2022"],
                    "success_criteria": ["cite the target filing segment discussion"],
                },
                "evidence_specs": [
                    {
                        "slot_name": "segment_discussion",
                        "accepted_attributes": ["business segment discussion"],
                        "source_role": "primary_filing",
                        "required_source_families": ["regulatory_filing"],
                        "target_period": "FY2022",
                        "statement": "business segment discussion",
                        "line_item": "net sales by business segment",
                        "required": True,
                    }
                ],
                "transform_specs": [],
                "slot_frame": {
                    "task_type": "disclosure_analysis",
                    "required_slots": [{"name": "segment_discussion"}],
                    "missing_slots": ["segment_discussion"],
                },
                "diagnostics": {"source": "task_compile_model"},
            },
        },
    )

    payload = _retrieval_payload(goal, recipe)
    hint = payload["metadata"]["compiled_task_hint"]

    assert hint["program_id"] == "program-model-disclosure-payload"
    assert hint["diagnostics"]["source"] == "recipe_execution_program"
    assert hint["task_spec"]["task_type"] == "disclosure_analysis"
    assert hint["transform_specs"] == []


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


def test_finance_fact_ledger_preserves_specific_revenue_concepts() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="gs-net-revenues",
            title="SEC companyfacts JSON for CIK 0000886982",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000886982.json",
            text=(
                "SEC companyfacts official financial statement entityName=Goldman Sachs "
                "concept=RevenuesNetOfInterestExpense label=Revenues, Net of Interest Expense "
                "metric=RevenuesNetOfInterestExpense unit=USD period=annual fy=2024 "
                "form=10-K value=53512000000"
            ),
        ),
        _finance_evidence(
            evidence_id="xom-total-revenues-other-income",
            title="ExxonMobil 2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/34088/000003408825000018/xom-20241231.htm",
            text=(
                "Consolidated statement of income, dollars in millions 2024 2023 2022 "
                "Total revenues and other income 349,585 344,582 413,680"
            ),
        ),
        _finance_evidence(
            evidence_id="cvx-sales-other-operating-revenues",
            title="Chevron 2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/93410/000009341025000009/cvx-20241231.htm",
            text=(
                "Consolidated statement of income, dollars in millions 2024 2023 "
                "Sales and other operating revenues 193,414 196,913"
            ),
        ),
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence],
    )

    by_metric = {(fact.metric, fact.fiscal_year): fact for fact in facts}
    assert by_metric[("net revenues", 2024)].value == "53512000000"
    assert by_metric[("total revenues and other income", 2024)].value == "349585000000"
    assert by_metric[("sales and other operating revenues", 2024)].value == "193414000000"


def test_finance_fact_context_keeps_competing_facts_model_owned() -> None:
    facts = [
        FinanceFact(
            fact_id="generic-revenues",
            entity="Chevron Corp",
            ticker=None,
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="202792000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-generic",
            citation_ref="cite-generic",
            metadata={
                "concept": "Revenues",
                "label": "Revenues",
                "form": "10-K",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
                "target_document_binding_accepted": True,
                "target_document_binding_score": 105,
            },
        ),
        FinanceFact(
            fact_id="sales-other-operating",
            entity="Chevron Corp",
            ticker=None,
            period="annual",
            fiscal_year=2024,
            metric="sales and other operating revenues",
            value="193414000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-specific",
            citation_ref="cite-specific",
            metadata={
                "concept": "SalesAndOtherOperatingRevenue",
                "label": "Sales and Other Operating Revenues",
                "form": "10-K",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
                "target_document_binding_accepted": True,
                "target_document_binding_score": 105,
            },
        ),
    ]

    ranked = _rank_finance_facts_for_model(
        facts,
        question="What was Chevron's total revenues for fiscal year 2024?",
    )

    assert [fact.fact_id for fact in ranked] == ["generic-revenues", "sales-other-operating"]
    summary = _finance_fact_judge_summary(ranked[0])
    assert "finance_metric_intent" not in summary["metadata"]
    assert "finance_question_period_scope" not in summary["metadata"]
    assert summary["metadata"]["concept"] == "Revenues"


def test_finance_fact_context_exposes_competing_clusters_to_synthesizer_prompt() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-total-revenues",
            title="Chevron 2024 Form 10-K companyfacts",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000093410.json",
            text=(
                "SEC companyfacts official financial statement entityName=Chevron Corp "
                "concept=Revenues label=Revenues metric=revenue unit=USD period=annual fy=2024 "
                "form=10-K value=202792000000"
            ),
        ),
        _finance_evidence(
            evidence_id="evidence-sales-revenues",
            title="Chevron 2024 Form 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/93410/000009341025000009/cvx-20241231.htm",
            text=(
                "SEC filing statement entityName=Chevron Corp concept=SalesAndOtherOperatingRevenue "
                "label=Sales and Other Operating Revenues metric=sales and other operating revenues "
                "unit=USD period=annual fy=2024 form=10-K value=193414000000"
            ),
        ),
    ]
    evidence[0].diagnostics.update(
        {
            "span_metadata": {
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 2.5,
                    "matched_preferred": ["metric=revenue"],
                    "matched_demoted": [],
                }
            }
        }
    )
    evidence[1].diagnostics.update(
        {
            "span_metadata": {
                "target_line_item": "total revenues",
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 13.5,
                    "matched_preferred": ["metric=sales and other operating revenues"],
                    "matched_demoted": [],
                },
            }
        }
    )
    citations = [_finance_citation(item, citation_id=f"cite-{item.evidence_id}") for item in evidence]
    report = _report_with_finance_fact_context(
        _retrieval_report(evidence=evidence, citations=citations),
        recipe=task_recipe(
            "retrieval_answer",
            metadata={"goal": "What was Chevron's total revenues for fiscal year 2024?"},
        ),
        evidence=evidence,
        citations=citations,
    )

    prompt_payload = json.loads(_synthesizer_prompt(report, evidence, citations))
    diagnostics = prompt_payload["retrieval_report"]["diagnostics"]
    clusters = diagnostics["finance_competing_fact_clusters"]
    policy = diagnostics["finance_competing_fact_cluster_policy"]
    metric_hints = diagnostics["finance_metric_intent_hints"]

    assert clusters
    assert policy["semantic_decision_owner"] == "model"
    assert policy["host_role"] == "attention_grouping_only_no_semantic_preference"
    assert clusters[0]["host_role"] == "attention_grouping_only_no_semantic_preference"
    assert clusters[0]["candidate_ordering"] == "source_order_from_raw_facts"
    assert [item["value"] for item in clusters[0]["candidates"]] == ["202792000000", "193414000000"]
    assert diagnostics["finance_metric_intent_hint_policy"]["semantic_decision_owner"] == "model"
    assert diagnostics["finance_metric_intent_hint_policy"]["host_role"] == "weak_attention_hint_carrier_only"
    assert [item["value"] for item in metric_hints] == ["202792000000", "193414000000"]
    assert metric_hints[1]["target_line_item"] == "total revenues"
    assert metric_hints[1]["intent"]["matched_preferred"] == ["metric=sales and other operating revenues"]
    assert any("not a host ranking" in item for item in prompt_payload["answer_requirements"])


def test_finance_fact_context_does_not_host_prefer_annual_over_quarterly() -> None:
    facts = [
        FinanceFact(
            fact_id="quarterly-net-revenues",
            entity="Mastercard",
            ticker="MA",
            period="2024",
            fiscal_year=2024,
            metric="net revenues",
            value="6348000000",
            unit="USD",
            scale=None,
            source_ref="sec-10q",
            evidence_ref="evidence-10q",
            citation_ref="cite-10q",
            metadata={
                "source_title": "SEC 10-Q primary filing document reportDate=2024-03-31",
                "target_document_binding_accepted": True,
                "target_document_binding_score": 90,
            },
        ),
        FinanceFact(
            fact_id="annual-revenues",
            entity="Mastercard",
            ticker="MA",
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="28167000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-companyfacts",
            citation_ref="cite-companyfacts",
            metadata={
                "concept": "Revenues",
                "label": "Revenues",
                "form": "10-K",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001141391.json",
                "target_document_binding_accepted": False,
                "target_document_binding_score": 5,
            },
        ),
        FinanceFact(
            fact_id="annual-contract-liability-revenue",
            entity="Mastercard",
            ticker="MA",
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="2800000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-contract-liability",
            citation_ref="cite-contract-liability",
            metadata={
                "concept": "ContractWithCustomerLiabilityRevenueRecognized",
                "label": "Contract with Customer, Liability, Revenue Recognized",
                "form": "10-K",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001141391.json",
                "target_document_binding_accepted": False,
                "target_document_binding_score": 5,
            },
        ),
    ]

    ranked = _rank_finance_facts_for_model(
        facts,
        question="What was Mastercard's net revenues for fiscal year 2024?",
    )

    assert [fact.fact_id for fact in ranked] == [
        "quarterly-net-revenues",
        "annual-revenues",
        "annual-contract-liability-revenue",
    ]
    summary = _finance_fact_judge_summary(ranked[0])
    assert "finance_question_period_scope" not in summary["metadata"]


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


def test_finance_capability_profile_uses_model_evaluator() -> None:
    profile = execution_profile("finance-capability")

    assert profile.planner_mode == "model"
    assert profile.evaluator_mode == "model"
    assert profile.synthesizer_mode == "model"


def test_toolchain_state_for_prompt_summarizes_tools_without_controlling_next_action() -> None:
    journal = JournalStore.in_memory()
    _append_toolchain_state_fixture(journal)

    state = _toolchain_state_for_prompt(journal, task_id="task-toolchain", run_id="run-1")

    assert state["schema"] == "holo.kernel_v3.toolchain_state.v1"
    assert state["action_count"] == 3
    assert state["observation_count"] == 2
    assert state["tool_source_counts"] == {
        "tool:calculator.compute": 1,
        "tool:retrieval.run": 1,
    }
    assert state["failed_tool_count"] == 1
    assert state["failed_tools"][0]["source"] == "tool:retrieval.run"
    assert state["failed_tools"][0]["observation_diagnostics"]["error"] == "network_failed"
    assert state["repeated_tool_names"] == ["calculator.compute"]
    assert len(state["repeated_action_fingerprints"]) == 1
    assert state["recent_tool_actions"][0]["payload_summary"]["query_preview"] == "example finance filing"
    calc_summary = state["recent_tool_actions"][1]["payload_summary"]
    assert calc_summary["payload_keys"] == ["expression", "variables"]
    assert calc_summary["expression_fingerprint"]
    assert calc_summary["variable_names"] == ["assets", "revenue"]
    assert "expression" not in calc_summary
    assert state["repeated_action_groups"][0]["tool"] == "calculator.compute"
    assert state["repeated_action_groups"][0]["attempt_count"] == 2
    assert state["repeated_action_groups"][0]["latest_observation_status"] == "ok"
    assert state["toolchain_presence"] == {
        "retrieval": True,
        "calculator": True,
        "finance_verify_numeric": False,
    }
    assert state["terminal_seen"] is True
    assert state["post_final_record_count"] == 1
    assert state["post_final_record_kind_counts"] == {"memory_proposal": 1}
    assert state["host_boundary"].startswith("observational compact state only")
    assert any("failed tool" in item for item in state["model_attention"])
    assert any("observation diagnostics" in item for item in state["model_attention"])
    assert any("terminal record" in item for item in state["model_attention"])


def test_toolchain_state_exposes_compact_verifier_repair_guidance_without_raw_tool_body() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-toolchain-verifier",
        run_id="run-1",
        step_id="step-verify",
        kind="observation",
        data={
            "source": f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}",
            "status": "ok",
            "observation_id": "obs-verify",
            "action_id": "act-verify",
            "content": {
                "verifier_status": "failed",
                "issue_count": 2,
                "matched_value_count": 0,
                "missing_value_count": 1,
                "verification": {
                    "status": "failed",
                    "issues": [{"code": "unsupported_answer_number"}],
                    "raw_large_body": "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK",
                },
                "repair_guidance": {
                    "schema": "holo.kernel_v3.finance_numeric_repair_guidance.v1",
                    "issue_codes": ["unsupported_answer_number", "ledger_extraction_gap"],
                    "repair_options": [
                        "ask synthesis to remove or replace unsupported answer numbers using only supported facts",
                        "retrieve or parse authoritative finance evidence to produce FinanceFact records",
                    ],
                    "missing_value_examples": [
                        {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": "revenue"}
                    ],
                    "host_boundary": "diagnostic verifier guidance only; the model still owns semantic repair",
                },
            },
        },
    )

    state = _toolchain_state_for_prompt(journal, task_id="task-toolchain-verifier", run_id="run-1")

    assert state["toolchain_presence"]["finance_verify_numeric"] is True
    diagnostics = state["recent_tool_observations"][-1]["observation_diagnostics"]
    assert diagnostics["verifier_status"] == "failed"
    assert diagnostics["issue_codes"] == ["unsupported_answer_number", "ledger_extraction_gap"]
    assert diagnostics["repair_options"][0].startswith("ask synthesis to remove")
    assert diagnostics["missing_value_examples"] == [
        {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": "revenue"}
    ]
    encoded = json.dumps(state, ensure_ascii=False)
    assert "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK" not in encoded
    assert "model still owns semantic repair" in diagnostics["host_boundary"]
    assert any("observation diagnostics" in item for item in state["model_attention"])


def test_toolchain_state_for_prompt_is_absent_without_tool_history() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-no-tools",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={
            "kind": "respond",
            "name": None,
            "action_id": "act-respond",
            "payload": {"text": "hello"},
            "side_effect_class": "none",
        },
    )
    journal.append(
        task_id="task-no-tools",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "source": "respond",
            "status": "ok",
            "observation_id": "obs-respond",
            "content": {"text": "hello"},
        },
    )

    state = _toolchain_state_for_prompt(journal, task_id="task-no-tools", run_id="run-1")

    assert state == {}


def test_agent_context_compiler_injects_compact_toolchain_state_for_model_planner() -> None:
    journal = JournalStore.in_memory()
    _append_toolchain_state_fixture(journal)
    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=profile_metadata)
    registry = register_finance_tools(ToolRegistry())
    compiler = _AgentContextCompiler(recipe=recipe, tool_manifests=registry.manifests())

    context = compiler.compile(
        TaskState(
            task_id="task-toolchain",
            run_id="run-1",
            thread_id="thread-toolchain",
            input_text="Compute a supported finance metric.",
            status="running",
            step_id="step-3",
        ),
        journal,
    )

    toolchain_state = context.state["toolchain_state"]
    assert toolchain_state["toolchain_presence"]["retrieval"] is True
    assert toolchain_state["toolchain_presence"]["calculator"] is True
    assert toolchain_state["repeated_tool_names"] == ["calculator.compute"]
    assert toolchain_state["recent_tool_actions"][-1]["payload_fingerprint"]
    assert toolchain_state["recent_tool_actions"][-1]["payload_summary"]["expression_fingerprint"]
    assert toolchain_state["repeated_action_groups"][0]["payload_summary"]["variable_names"] == ["assets", "revenue"]
    assert "revenue / assets" not in json.dumps(toolchain_state, ensure_ascii=False)
    assert "model still chooses the next action" in toolchain_state["host_boundary"]


def test_finance_working_state_for_prompt_summarizes_facts_traces_and_verifier_without_deciding_answer() -> None:
    journal = JournalStore.in_memory()
    _append_finance_working_state_fixture(journal)

    state = _finance_working_state_for_prompt(journal, task_id="task-finance-state", run_id="run-1")

    assert state["schema"] == "holo.kernel_v3.finance_working_state.v1"
    assert state["fact_count"] == 2
    assert state["facts"][0]["fact_id"] == "finfact-revenue"
    assert state["facts"][0]["metric"] == "revenue"
    assert state["slot_frame"]["task_type"] == "compute"
    assert state["slot_frame"]["evidence_policy"]["required_source_families"] == ["sec_filing"]
    assert state["slot_bind"]["decision"] == "ready"
    assert state["slot_bind"]["accepted_formula_plan_count"] == 1
    assert state["slot_bind"]["period_basis"][0]["selected_period"] == "FY2024"
    assert state["slot_bind"]["line_item_basis"][0]["selected_line_item"] == "Revenue"
    assert state["missing_slots"] == ["net_income", "margin"]
    assert state["transform_plan"]["method"] == "margin"
    assert state["formula_trace_count"] == 1
    assert state["formula_traces"][0]["formula_name"] == "gross_margin"
    assert state["formula_trace_support"][0]["support_status"] == "linked_to_fact_ledger"
    assert state["formula_trace_support"][0]["citation_refs"] == ["cite-profit", "cite-revenue"]
    assert state["numeric_verification"]["status"] == "failed"
    assert state["numeric_verification"]["issue_codes"] == ["missing_margin"]
    assert state["numeric_verification"]["missing_value_examples"][0]["slot"] == "net_income"
    assert "inspect missing numeric values" in state["numeric_verification"]["repair_options"][0]
    assert state["presence"] == {
        "finance_facts": True,
        "slot_frame": True,
        "slot_bind": True,
        "missing_slots": True,
        "formula_trace": True,
        "numeric_verification": True,
    }
    encoded = json.dumps(state, ensure_ascii=False)
    assert "gross profit / revenue" in encoded
    assert "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK" not in encoded
    assert "model owns metric binding" in state["host_boundary"]


def test_finance_working_state_verifier_repair_options_are_model_visible_without_deciding_answer() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-finance-repair-options",
        run_id="run-1",
        step_id="step-verify",
        kind="finance_numeric_verification",
        data={
            "schema": "holo.kernel_v3.finance_numeric_verification.v1",
            "status": "failed",
            "issues": [
                {"code": "unsupported_answer_number"},
                {"code": "missing_formula_trace"},
                {"code": "primary_source_numeric_binding_failed"},
            ],
            "matched_values": [],
            "missing_values": [{"raw": "$43.0B", "value": "43000000000", "unit": "USD", "slot": "enterprise_value"}],
            "formula_traces": [],
        },
    )

    state = _finance_working_state_for_prompt(journal, task_id="task-finance-repair-options", run_id="run-1")

    verification = state["numeric_verification"]
    assert verification["issue_codes"] == [
        "unsupported_answer_number",
        "missing_formula_trace",
        "primary_source_numeric_binding_failed",
    ]
    assert verification["missing_value_examples"] == [
        {"raw": "$43.0B", "value": "43000000000", "unit": "USD", "slot": "enterprise_value"}
    ]
    repair_options = " ".join(verification["repair_options"])
    assert "remove or replace unsupported answer numbers" in repair_options
    assert "calculator.compute" in repair_options
    assert "target document" in repair_options
    assert "model owns metric binding" in state["host_boundary"]


def test_finance_working_state_exposes_unit_mismatch_examples_without_deciding_answer() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-finance-unit-repair",
        run_id="run-1",
        step_id="step-verify",
        kind="finance_numeric_verification",
        data={
            "schema": "holo.kernel_v3.finance_numeric_verification.v1",
            "status": "failed",
            "issues": [{"code": "unit_mismatch"}],
            "matched_values": [
                {
                    "raw": "10%",
                    "value": "10",
                    "unit": "percent",
                    "support": {"kind": "finance_fact", "ref": "fact-revenue", "unit": "usd"},
                }
            ],
            "missing_values": [],
            "unit_mismatches": [
                {
                    "code": "unit_mismatch",
                    "value": {"raw": "10%", "value": "10", "unit": "percent"},
                    "support_units": ["usd"],
                    "support_kinds": ["finance_fact"],
                    "support_refs": ["fact-revenue"],
                }
            ],
            "formula_traces": [],
        },
    )

    state = _finance_working_state_for_prompt(journal, task_id="task-finance-unit-repair", run_id="run-1")

    verification = state["numeric_verification"]
    assert verification["issue_codes"] == ["unit_mismatch"]
    assert verification["missing_value_examples"] == []
    assert verification["unit_mismatch_examples"] == [
        {
            "raw": "10%",
            "value": "10",
            "unit": "percent",
            "support_units": ["usd"],
            "support_kinds": ["finance_fact"],
            "support_refs": ["fact-revenue"],
        }
    ]
    assert "unit or scale wording" in " ".join(verification["repair_options"])
    assert "model owns metric binding" in state["host_boundary"]


def test_finance_working_state_includes_verify_numeric_tool_observation() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-finance-tool-verifier-state",
        run_id="run-1",
        step_id="step-verify-tool",
        kind="observation",
        data={
            "observation_id": "obs-verify-tool",
            "source": f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}",
            "kind": "finance_numeric_verification",
            "status": "ok",
            "content": {
                "verifier_status": "failed",
                "verification": {
                    "schema": "holo.kernel_v3.finance_numeric_verification.v1",
                    "status": "failed",
                    "issues": [{"code": "unsupported_answer_number"}],
                    "matched_values": [],
                    "missing_values": [
                        {"raw": "21.91x", "value": "21.91", "unit": "x", "slot": "ev_revenue_multiple"}
                    ],
                    "formula_traces": [],
                },
            },
        },
    )

    state = _finance_working_state_for_prompt(journal, task_id="task-finance-tool-verifier-state", run_id="run-1")

    assert state["presence"]["numeric_verification"] is True
    verification = state["numeric_verification"]
    assert verification["status"] == "failed"
    assert verification["issue_codes"] == ["unsupported_answer_number"]
    assert verification["missing_value_examples"] == [
        {"raw": "21.91x", "value": "21.91", "unit": "x", "slot": "ev_revenue_multiple"}
    ]
    assert "remove or replace unsupported answer numbers" in " ".join(verification["repair_options"])
    assert any("latest finance numeric verification failed" in item for item in state["model_attention"])


def test_finance_working_state_includes_slot_bind_basis_without_fact_ledger() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-finance-slot-basis-only",
        run_id="run-1",
        step_id="step-slot-bind",
        kind="finance_slot_bind",
        data={
            "schema": "holo.kernel_v3.finance_slot_bind.v1",
            "status": "ready",
            "decision": "ready",
            "accepted_formula_plan_count": 1,
            "period_basis": [
                {
                    "slot_name": "revenue",
                    "fact_id": "finfact-revenue",
                    "selected_period": "FY2024",
                    "raw_fields_used": ["form", "fp", "start", "end"],
                    "reason": "Model selected the annual FY fact.",
                }
            ],
            "line_item_basis": [
                {
                    "slot_name": "revenue",
                    "fact_id": "finfact-revenue",
                    "selected_line_item": "Revenue",
                    "raw_fields_used": ["concept", "label"],
                    "reason": "Model selected the revenue line item.",
                }
            ],
            "reason_summary": "Model-owned slot binding basis is available before synthesis.",
        },
    )

    state = _finance_working_state_for_prompt(journal, task_id="task-finance-slot-basis-only", run_id="run-1")

    assert state["presence"]["slot_bind"] is True
    assert state["slot_bind"]["period_basis"][0]["selected_period"] == "FY2024"
    assert state["slot_bind"]["line_item_basis"][0]["selected_line_item"] == "Revenue"
    assert any("model-owned slot binding basis" in item for item in state["model_attention"])
    assert "model owns metric binding" in state["host_boundary"]


def test_finance_working_state_for_prompt_is_absent_without_finance_anchor() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-generic-state",
        run_id="run-1",
        step_id="step-slot",
        kind="slot_frame",
        data={
            "schema": "holo.kernel_v3.slot_frame.v1",
            "source": "generic_source_grounded_workflow_trace",
            "domain": "source_grounded_research",
            "task_type": "summarize",
            "missing_slots": ["citation"],
        },
    )
    journal.append(
        task_id="task-generic-state",
        run_id="run-1",
        step_id="step-transform",
        kind="transform_plan",
        data={
            "schema": "holo.kernel_v3.transform_plan.v1",
            "domain": "source_grounded_research",
            "operation": "synthesize",
            "status": "missing_slots",
            "method": "source_grounded_synthesis",
            "missing_slots": ["citation"],
        },
    )

    state = _finance_working_state_for_prompt(journal, task_id="task-generic-state", run_id="run-1")

    assert state == {}


def test_agent_context_compiler_injects_compact_finance_working_state_for_model_planner() -> None:
    journal = JournalStore.in_memory()
    _append_finance_working_state_fixture(journal)
    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=profile_metadata)
    registry = register_finance_tools(ToolRegistry())
    compiler = _AgentContextCompiler(recipe=recipe, tool_manifests=registry.manifests())

    context = compiler.compile(
        TaskState(
            task_id="task-finance-state",
            run_id="run-1",
            thread_id="thread-finance-state",
            input_text="Compute a supported finance metric.",
            status="running",
            step_id="step-3",
        ),
        journal,
    )

    finance_state = context.state["finance_working_state"]
    assert finance_state["presence"]["finance_facts"] is True
    assert finance_state["presence"]["formula_trace"] is True
    assert finance_state["numeric_verification"]["status"] == "failed"
    assert finance_state["formula_trace_support"][0]["input_fact_ids"] == ["finfact-profit", "finfact-revenue"]
    assert "model owns metric binding" in finance_state["host_boundary"]


def test_loop_recompiles_context_so_second_planner_step_sees_finance_working_state() -> None:
    journal = JournalStore.in_memory()
    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))
    recipe = task_recipe("retrieval_answer", metadata=profile_metadata)
    registry = ToolRegistry.with_builtin_respond()
    registry.register("finance.seed_state", _finance_seed_state_executor(journal))

    class CapturingPlanner:
        def __init__(self) -> None:
            self.context_states: list[dict] = []

        def propose(self, context: ContextBundle, feedback=None):
            self.context_states.append(context.state)
            if len(self.context_states) == 1:
                assert context.state.get("finance_working_state") == {}
                return CandidateAction(
                    action_id="act-seed-finance-state",
                    kind="tool",
                    name="finance.seed_state",
                    description="seed finance state for loop context refresh",
                    payload={},
                    score=1.0,
                    reasons=["test first step"],
                    side_effect_class="read",
                )
            finance_state = context.state["finance_working_state"]
            assert finance_state["presence"]["finance_facts"] is True
            assert finance_state["presence"]["formula_trace"] is True
            assert finance_state["formula_trace_support"][0]["citation_refs"] == ["cite-profit", "cite-revenue"]
            return CandidateAction(
                action_id="act-final",
                kind="respond",
                name=None,
                description="final answer after refreshed finance state",
                payload={"text": "The refreshed finance working state is visible."},
                score=1.0,
                reasons=["test second step"],
                side_effect_class="none",
            )

    class ContinueThenStopEvaluator:
        def __init__(self) -> None:
            self.count = 0
            self.context_states: list[dict] = []

        def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
            self.count += 1
            self.context_states.append(context.state)
            if self.count == 1:
                finance_state = context.state["finance_working_state"]
                assert finance_state["presence"]["finance_facts"] is True
                assert finance_state["presence"]["formula_trace"] is True
                return Feedback(
                    feedback_id="fb-continue",
                    run_id=observation.run_id,
                    status="continue",
                    answer=None,
                    stop_reason=None,
                    missing_evidence=["finance_working_state_refresh"],
                )
            return Feedback(
                feedback_id="fb-final",
                run_id=observation.run_id,
                status="final_answer_ready",
                answer="The refreshed finance working state is visible.",
                stop_reason="completed",
                    missing_evidence=[],
                )

    planner = CapturingPlanner()
    evaluator = ContinueThenStopEvaluator()
    result = LoopControllerV3(
        journal=journal,
        context_compiler=_AgentContextCompiler(recipe=recipe, tool_manifests=registry.manifests()),
        planner=planner,
        policy_gate=PolicyGate(),
        tool_registry=registry,
        evaluator=evaluator,
        max_steps=3,
    ).run("Compute a supported finance metric.")

    assert result.status == "completed"
    assert len(planner.context_states) == 2
    assert evaluator.context_states[0]["finance_working_state"]["presence"]["formula_trace"] is True
    assert planner.context_states[1]["finance_working_state"]["fact_count"] == 2
    context_records = journal.records(kind="context")
    assert len(context_records) == 2
    assert context_records[-1].data["state"]["finance_working_state"]["presence"]["formula_trace"] is True


def _append_toolchain_state_fixture(journal: JournalStore) -> None:
    journal.append(
        task_id="task-toolchain",
        run_id="run-1",
        step_id="step-1",
        kind="action",
        data={
            "kind": "tool",
            "name": "retrieval.run",
            "action_id": "act-retrieve",
            "payload": {"query": "example finance filing"},
            "side_effect_class": "network",
        },
    )
    for action_id in ("act-calc-1", "act-calc-2"):
        journal.append(
            task_id="task-toolchain",
            run_id="run-1",
            step_id="step-2",
            kind="action",
            data={
                "kind": "tool",
                "name": "calculator.compute",
                "action_id": action_id,
                "payload": {"expression": "revenue / assets", "variables": {"revenue": 10, "assets": 5}},
                "side_effect_class": "read",
            },
        )
    journal.append(
        task_id="task-toolchain",
        run_id="run-1",
        step_id="step-1",
        kind="observation",
        data={
            "source": "tool:retrieval.run",
            "status": "failed",
            "observation_id": "obs-retrieve",
            "action_id": "act-retrieve",
            "content": {"error": "network_failed", "query": "example finance filing"},
        },
    )
    journal.append(
        task_id="task-toolchain",
        run_id="run-1",
        step_id="step-2",
        kind="observation",
        data={
            "source": "tool:calculator.compute",
            "status": "ok",
            "observation_id": "obs-calc",
            "action_id": "act-calc-1",
            "content": {"formula_trace": {"formula_id": "formula-1", "result_value": "2"}},
        },
    )
    journal.append(
        task_id="task-toolchain",
        run_id="run-1",
        step_id="step-final",
        kind="agent_final_answer",
        data={"answer": "Final answer."},
    )
    journal.append(
        task_id="task-toolchain",
        run_id="run-1",
        step_id="step-post",
        kind="memory_proposal",
        data={"status": "pending"},
    )


def _append_finance_working_state_fixture(journal: JournalStore) -> None:
    facts = [
        FinanceFact(
            fact_id="finfact-revenue",
            entity="ExampleCo",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="1000",
            unit="USD",
            scale="millions",
            source_ref="src-10k",
            evidence_ref="ev-revenue",
            citation_ref="cite-revenue",
            metadata={
                "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "label": "Net revenues",
                "form": "10-K",
                "fp": "FY",
                "source_uri": "https://example.test/10k",
                "raw_body": "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK",
            },
        ),
        FinanceFact(
            fact_id="finfact-profit",
            entity="ExampleCo",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="gross_profit",
            value="400",
            unit="USD",
            scale="millions",
            source_ref="src-10k",
            evidence_ref="ev-profit",
            citation_ref="cite-profit",
            metadata={
                "concept": "GrossProfit",
                "label": "Gross profit",
                "form": "10-K",
                "fp": "FY",
                "source_uri": "https://example.test/10k",
            },
        ),
    ]
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-ledger",
        kind="finance_fact_ledger",
        data={
            "schema": "holo.kernel_v3.finance_fact_ledger.v1",
            "fact_count": len(facts),
            "facts": [fact.to_dict() for fact in facts],
        },
    )
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-slot",
        kind="slot_frame",
        data={
            "schema": "holo.kernel_v3.slot_frame.v1",
            "source": "test_fixture",
            "task_type": "compute",
            "required_slots": [{"name": "revenue"}, {"name": "gross_profit"}, {"name": "margin"}],
            "filled_slots": [{"slot_name": "revenue", "value": "1000"}],
            "missing_slots": ["net_income", "margin"],
            "evidence_policy": {
                "required_source_families": ["sec_filing"],
                "authority": "primary",
            },
        },
    )
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-transform",
        kind="transform_plan",
        data={
            "schema": "holo.kernel_v3.transform_plan.v1",
            "domain": "finance",
            "operation": "compute",
            "status": "missing_slots",
            "method": "margin",
            "input_claim_ids": ["claim-profit", "claim-revenue"],
            "output_attribute": "gross_margin",
            "missing_slots": ["margin"],
        },
    )
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-slot-bind",
        kind="finance_slot_bind",
        data={
            "schema": "holo.kernel_v3.finance_slot_bind.v1",
            "status": "ready",
            "decision": "ready",
            "processor_status": "ok",
            "repair_attempted": False,
            "accepted_formula_plan_count": 1,
            "missing_slots": [],
            "reason_summary": "Model selected FY revenue and gross profit from the 10-K.",
            "period_basis": [
                {
                    "slot_name": "revenue",
                    "fact_id": "finfact-revenue",
                    "selected_period": "FY2024",
                    "raw_fields_used": ["form", "fp"],
                    "reason": "10-K FY fact matches requested fiscal year.",
                }
            ],
            "line_item_basis": [
                {
                    "slot_name": "revenue",
                    "fact_id": "finfact-revenue",
                    "selected_line_item": "Revenue",
                    "raw_fields_used": ["concept", "label"],
                    "reason": "Revenue concept and label match the requested line item.",
                }
            ],
        },
    )
    trace = FormulaTrace(
        formula_id="formula-margin",
        formula_name="gross_margin",
        expression="gross profit / revenue",
        input_fact_ids=["finfact-profit", "finfact-revenue"],
        result_value="0.4",
        unit="ratio",
        diagnostics={"source": "finance_slot_bind_model", "formatted_value": "40.0%"},
    )
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-calc",
        kind="observation",
        data={
            "source": f"tool:{CALCULATOR_TOOL_NAME}",
            "status": "ok",
            "content": {"formula_trace": trace.to_dict()},
        },
    )
    journal.append(
        task_id="task-finance-state",
        run_id="run-1",
        step_id="step-verify",
        kind="finance_numeric_verification",
        data={
            "schema": "holo.kernel_v3.finance_numeric_verification.v1",
            "status": "failed",
            "issues": [{"code": "missing_margin"}],
            "matched_values": [{"value": "0.4"}],
            "missing_values": [{"slot": "net_income"}],
            "formula_traces": [trace.to_dict()],
            "verifier_gate_result": {"status": "failed"},
        },
    )


def _finance_seed_state_executor(journal: JournalStore):
    def execute(action: CandidateAction) -> Observation:
        host_context = action.payload.get("_host_context") if isinstance(action.payload, dict) else {}
        host_context = host_context if isinstance(host_context, dict) else {}
        task_id = str(host_context.get("task_id") or "task-loop-finance-state")
        run_id = str(host_context.get("run_id") or "run-1")
        step_id = str(host_context.get("step_id") or "step-seed")
        facts = [
            FinanceFact(
                fact_id="finfact-revenue",
                entity="ExampleCo",
                ticker="EXM",
                period="FY2024",
                fiscal_year=2024,
                metric="revenue",
                value="1000",
                unit="USD",
                scale="millions",
                source_ref="src-10k",
                evidence_ref="ev-revenue",
                citation_ref="cite-revenue",
                metadata={"concept": "Revenues", "label": "Revenue", "form": "10-K", "fp": "FY"},
            ),
            FinanceFact(
                fact_id="finfact-profit",
                entity="ExampleCo",
                ticker="EXM",
                period="FY2024",
                fiscal_year=2024,
                metric="gross_profit",
                value="400",
                unit="USD",
                scale="millions",
                source_ref="src-10k",
                evidence_ref="ev-profit",
                citation_ref="cite-profit",
                metadata={"concept": "GrossProfit", "label": "Gross profit", "form": "10-K", "fp": "FY"},
            ),
        ]
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="finance_fact_ledger",
            data={
                "schema": "holo.kernel_v3.finance_fact_ledger.v1",
                "fact_count": len(facts),
                "facts": [fact.to_dict() for fact in facts],
            },
        )
        trace = FormulaTrace(
            formula_id="formula-margin",
            formula_name="gross_margin",
            expression="gross_profit / revenue",
            input_fact_ids=["finfact-profit", "finfact-revenue"],
            result_value="0.4",
            unit="ratio",
            diagnostics={"source": "finance_slot_bind_model", "formatted_value": "40.0%"},
        )
        journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=step_id,
            kind="observation",
            data={
                "source": f"tool:{CALCULATOR_TOOL_NAME}",
                "status": "ok",
                "content": {"formula_trace": trace.to_dict()},
            },
        )
        return Observation(
            observation_id="obs-seed-finance-state",
            run_id=run_id,
            kind="tool_result",
            status="ok",
            source="tool:finance.seed_state",
            content={"status": "seeded"},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )

    return execute


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
    assert "https://www.sec.gov/Archives/example/pfe-8k.htm" in action.payload["metadata"]["source_urls"]
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json" in action.payload["metadata"]["source_urls"]
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


def test_finance_capability_preserves_model_ask_user_without_host_rewrite() -> None:
    class ClarifyingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-ask-for-ticker",
                kind="ask_user",
                name=None,
                description="Need ticker",
                score=0.2,
                payload={"question": "请提供上市公司名称或股票代码。"},
                reasons=["missing_company_ticker"],
                side_effect_class="none",
            )

    profile_metadata = execution_profile_runtime_metadata(execution_profile("finance-capability"))
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **profile_metadata,
            "semantic_intake": {
                "primary_intent": "financial_analysis",
                "suggested_mode": "retrieval_answer",
                "requires_clarification": False,
                "intents": [
                    {
                        "kind": "financial_analysis",
                        "required_capabilities": ["retrieval.run", "calculator.compute"],
                        "metadata": {
                            "domain": "finance",
                            "capability_args": {
                                "retrieval.run": [
                                    {
                                        "query": "Seagen Inc 10-K 2022 total revenue annual",
                                        "extract": "revenue",
                                        "source_family": "sec_edgar_structured_search",
                                    },
                                    {
                                        "query": "Pfizer Seagen acquisition consideration enterprise value 8-K EX-99.1 2023",
                                        "extract": "consideration",
                                        "source_family": "sec_edgar_structured_search",
                                    },
                                ]
                            },
                        },
                    }
                ],
            },
        },
    )
    planner = _RecipeBoundPlanner(
        inner=ClarifyingPlanner(),
        goal="For Pfizer's acquisition of Seagen, calculate transaction EV / revenue multiple.",
        recipe=recipe,
        journal=JournalStore.in_memory(),
    )
    context = ContextBundle(
        context_id="ctx-clarify-model-owned",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-pfe", "run_id": "run-pfe"},
        token_budget={},
    )

    action = planner.propose(context)

    assert action.kind == "ask_user"
    assert action.name is None
    assert action.payload["question"] == "请提供上市公司名称或股票代码。"
    assert "finance_capability_clarification_rescue" not in action.reasons


def test_non_llm_first_ask_user_is_not_rewritten_to_retrieval() -> None:
    class ClarifyingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-ask-missing-target",
                kind="ask_user",
                name=None,
                description="Need company",
                score=0.6,
                payload={"question": "Which company?"},
                reasons=["missing_target"],
                side_effect_class="none",
            )

    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "semantic_intake": {
                "primary_intent": "financial_analysis",
                "requires_clarification": True,
                "intents": [],
            }
        },
    )
    planner = _RecipeBoundPlanner(
        inner=ClarifyingPlanner(),
        goal="Analyze the company.",
        recipe=recipe,
        journal=JournalStore.in_memory(),
    )
    context = ContextBundle(
        context_id="ctx-ask-preserved",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-generic", "run_id": "run-generic"},
        token_budget={},
    )

    action = planner.propose(context)

    assert action.kind == "ask_user"
    assert action.name is None


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


def test_planner_preserves_model_selected_composable_tool_over_workbench_followup() -> None:
    class ShellPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-model-shell-parse",
                kind="tool",
                name="shell.exec",
                description="Run a local parser over cached filing text",
                score=0.91,
                payload={"argv": ["python3", "-c", "print('parse cached filing')"]},
                reasons=["model_selected_composable_tool", "execution_program_suggests_local_analysis"],
                side_effect_class="shell",
            )

    recipe = task_recipe("retrieval_answer", metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")))
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-shell-choice",
        run_id="run-shell-choice",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Need parsing of a target filing table.",
            "missing_slots": ["capital_expenditures"],
            "next_queries": ["https://www.sec.gov/Archives/example/adbe-10k.htm capital expenditures"],
            "next_source_families": ["primary_filing"],
            "next_document_targets": ["https://www.sec.gov/Archives/example/adbe-10k.htm"],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=ShellPlanner(),
        goal="Parse the cached Adobe target filing and extract capex.",
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-shell-choice",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-shell-choice", "run_id": "run-shell-choice"},
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "shell.exec"
    assert action.payload["argv"] == ["python3", "-c", "print('parse cached filing')"]
    assert "retrieval_workbench_followup" not in action.reasons


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


def test_finance_capability_workbench_missing_slots_without_next_query_are_advisory() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-model-ready",
                kind="respond",
                name="respond",
                description="Answer with available filing evidence",
                score=0.91,
                payload={"text": "Use the cited KHC filing table and state remaining limits."},
                reasons=["model_answer_ready"],
                side_effect_class="none",
            )

    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-capability"))},
    )
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-capability-workbench-advisory",
        run_id="run-capability-workbench-advisory",
        step_id="step-workbench",
        kind="retrieval_workbench_decision",
        data={
            "status": "ok",
            "decision": "continue",
            "reason_summary": "Some semantic slots remain uncertain, but no executable next search was proposed.",
            "missing_slots": ["base_metric", "adjusted_metric"],
            "next_queries": [],
            "next_source_families": [],
            "next_document_targets": [],
        },
    )
    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal="For KHC, explain the adjusted EBITDA bridge from public filings.",
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-capability-workbench-advisory",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={
            "task_id": "task-capability-workbench-advisory",
            "run_id": "run-capability-workbench-advisory",
        },
        token_budget={},
    )

    action = planner.propose(context)

    assert action.name == "respond"
    assert "retrieval_workbench_followup" not in action.reasons


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


def test_finance_fact_ledger_extracts_html_column_cash_flow_rows() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="ppe-html-column-table",
            title="3M 2018 Form 10-K",
            text=(
                "Cash Flows from Investing Activities: scale=millions "
                "html_table_165_row_1: Years ended December 31 | | | | | | | | | | "
                "html_table_165_row_2: (Millions) | | 2018 | | 2017 | | 2016 | "
                "html_table_165_row_3: Years_ended_December_31=Purchases of property, plant and equipment (PP&E) "
                "column_2= column_3=$ column_4=(1,577) column_5= column_6=$ column_7=(1,373) "
                "column_8= column_9=$ column_10=(1,420) column_11= "
                "html_table_165_row_4: Years_ended_December_31=Proceeds from sale of PP&E and other assets "
                "column_2= column_3= column_4=262 column_5= column_6= column_7=49"
            ),
        )
    ]

    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-ppe-html-column-table")],
    )
    capex_by_year = {
        fact.fiscal_year: fact
        for fact in facts
        if fact.metric == "capital expenditures" and fact.metadata.get("source") == "natural_table_row"
    }

    assert capex_by_year[2018].value == "-1577000000"
    assert capex_by_year[2017].value == "-1373000000"
    assert capex_by_year[2016].value == "-1420000000"
    assert capex_by_year[2018].metadata["row_marker"] == "purchases of property, plant and equipment"
    assert "column_4=(1,577)" in capex_by_year[2018].metadata["context"]


def test_html_table_fact_lines_preserve_parenthesized_capex_values() -> None:
    document = FetchedDocument(
        document_id="doc-3m-2022",
        goal_id="goal-3m-2022",
        source_id="src-3m-2022",
        uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.htm",
        title="3M 2022 Form 10-K",
        artifact_id="artifact-3m-2022",
        payload_hash="hash-3m-2022",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "text/html"},
    )
    body = """
    <html><body>
      <table>
        <tr><td>(Millions)</td><td>2022</td><td>2021</td><td>2020</td></tr>
        <tr><td>Net cash provided by (used in) operating activities</td><td>5,591</td><td>7,454</td><td>8,113</td></tr>
        <tr><td>Purchases of property, plant and equipment (PP&amp;E)</td><td>( 1,749 )</td><td>( 1,603 )</td><td>( 1,501 )</td></tr>
      </table>
    </body></html>
    """

    text, mode = readable_document_text(body, document=document)
    evidence = _finance_evidence(
        evidence_id="html-parenthesized-capex",
        title="3M 2022 Form 10-K",
        text=text,
    )
    facts = build_finance_fact_ledger(
        evidence=[evidence],
        citations=[_finance_citation(evidence, citation_id="cite-html-parenthesized-capex")],
    )
    capex = next(fact for fact in facts if fact.metric == "capital expenditures" and fact.fiscal_year == 2022)

    assert mode == "html_readable_text"
    assert "html_table_fact_1_3_2022" in text
    assert "value=(1,749)" in text
    assert capex.value == "-1749000000"
    assert capex.scale == "millions"


def test_html_table_fact_lines_extract_balance_sheet_ppe_and_assets() -> None:
    document = FetchedDocument(
        document_id="doc-3m-2022-balance",
        goal_id="goal-3m-2022-balance",
        source_id="src-3m-2022-balance",
        uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.htm",
        title="3M 2022 Form 10-K",
        artifact_id="artifact-3m-2022-balance",
        payload_hash="hash-3m-2022-balance",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "text/html"},
    )
    body = """
    <html><body>
      <table>
        <tr><td>(Dollars in millions)</td><td>2022</td><td>2021</td></tr>
        <tr><td>Property, plant and equipment - net</td><td>9,178</td><td>9,471</td></tr>
        <tr><td>Total assets</td><td>46,455</td><td>47,072</td></tr>
      </table>
    </body></html>
    """

    text, mode = readable_document_text(body, document=document)
    evidence = _finance_evidence(
        evidence_id="html-balance-sheet-ppe-assets",
        title="3M 2022 Form 10-K",
        text=text,
    )
    facts = build_finance_fact_ledger(
        evidence=[evidence],
        citations=[_finance_citation(evidence, citation_id="cite-html-balance-sheet-ppe-assets")],
    )
    by_metric_year = {(fact.metric, fact.fiscal_year): fact for fact in facts}

    assert mode == "html_readable_text"
    assert "html_table_fact_1_2_2022" in text
    assert "html_table_fact_1_3_2022" in text
    assert by_metric_year[("property plant and equipment net", 2022)].value == "9178000000"
    assert by_metric_year[("assets", 2022)].value == "46455000000"
    assert by_metric_year[("property plant and equipment net", 2022)].scale == "millions"


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


def test_target_document_binding_refines_generic_revenue_with_question_metric_phrase() -> None:
    reused = target_document_binding_from_metadata(
        {
            "target_document_binding": {
                "schema": "holo.kernel_v3.finance.target_document_binding.v1",
                "company": "Goldman Sachs",
                "doc_period": "2024",
                "doc_type": "10-K",
                "required_line_item": "revenue",
            }
        },
        question="What was Goldman Sachs' net revenues for fiscal year 2024?",
    )

    assert reused["required_line_item"] == "net revenues"
    assert reused["line_item_refined_from"] == "revenue"


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


def test_target_binding_distinguishes_net_revenues_from_component_revenue() -> None:
    binding = target_document_binding_from_metadata(
        {"company": "Goldman Sachs", "doc_period": "2024", "doc_type": "10-K"},
        question="What was Goldman Sachs' net revenues for fiscal year 2024?",
    )
    facts = [
        FinanceFact(
            fact_id="component-sales",
            entity="Goldman Sachs",
            ticker="GS",
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="885000000",
            unit="USD",
            scale="actual",
            source_ref="cite-component",
            evidence_ref="ev-component",
            citation_ref="cite-component",
            metadata={
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000886982.json",
                "source_title": "SEC companyfacts JSON for CIK 0000886982",
                "concept": "FairValueNetDerivativeAssetLiabilityMeasuredOnRecurringBasisUnobservableInputsReconciliationSales",
                "label": "Fair Value, Net Derivative Asset (Liability) Measured on Recurring Basis, Unobservable Inputs Reconciliation, Sales",
                "form": "10-K",
            },
        ),
        FinanceFact(
            fact_id="net-revenues",
            entity="Goldman Sachs",
            ticker="GS",
            period="annual",
            fiscal_year=2024,
            metric="net revenues",
            value="53512000000",
            unit="USD",
            scale="actual",
            source_ref="cite-net",
            evidence_ref="ev-net",
            citation_ref="cite-net",
            metadata={
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000886982.json",
                "source_title": "SEC companyfacts JSON for CIK 0000886982",
                "concept": "RevenuesNetOfInterestExpense",
                "label": "Revenues, Net of Interest Expense",
                "form": "10-K",
            },
        ),
    ]

    resolution = primary_source_numeric_binding_resolution(facts, binding, question="Goldman Sachs net revenues 2024")

    assert binding["required_line_item"] == "net revenues"
    assert resolution["status"] == "selected"
    assert resolution["selected_fact_ids"] == ["net-revenues"]
    rejected = {item["fact_id"]: item for item in resolution["rejected_candidates"]}
    assert "component-sales" in rejected


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
        "net_income",
    ]
    assert [spec.name for spec in program.transform_specs] == [
        "capital_intensity_capex_revenue",
        "capital_intensity_capex_operating_cash_flow",
        "capital_intensity_ppe_assets",
        "capital_intensity_return_on_assets",
    ]
    evidence_slots = {spec.slot_name: spec for spec in program.evidence_specs}
    assert evidence_slots["property_plant_and_equipment_net"].statement == "balance_sheet"
    assert evidence_slots["capital_expenditures"].statement == "cash_flow_statement"
    assert evidence_slots["net_income"].statement == "income_statement"
    tool_chain = program.diagnostics["tool_chain_plan"]
    assert tool_chain["schema"] == "holo.kernel_v3.tool_chain_plan.v1"
    assert tool_chain["decision_owner"] == "model"
    assert tool_chain["host_role"] == "verify_provenance_policy_budget_and_numeric_support"
    assert tool_chain["missing_slots"] == program.slot_frame.missing_slots
    tool_names = [item["name"] for item in tool_chain["available_tools"]]
    assert "retrieval.run" in tool_names
    assert "workspace.search" in tool_names
    assert "file.read" in tool_names
    assert "shell.exec" in tool_names
    assert "calculator.compute" in tool_names
    assert "host.verifier_gate" in tool_names
    assert tool_chain["next_action_candidates"][0]["tool"] == "retrieval.run"
    assert tool_chain["recommended_steps"][-1]["tool"] == "host.verifier_gate"


def test_finance_task_compiler_emits_fixed_asset_turnover_program_missing_slots() -> None:
    program = compile_finance_task_program(
        question=(
            "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
            "Fixed asset turnover ratio is defined as: FY2019 revenue / "
            "(average PP&E between FY2018 and FY2019)."
        ),
        facts=[],
    )

    assert program.task_spec.task_type == "compute"
    assert program.slot_frame is not None
    assert program.slot_frame.missing_slots == [
        "revenue",
        "property_plant_and_equipment_net_current",
        "property_plant_and_equipment_net_prior",
    ]
    assert [spec.name for spec in program.transform_specs] == ["fixed_asset_turnover"]
    transform = program.transform_specs[0]
    assert transform.required_slots == [
        "revenue",
        "property_plant_and_equipment_net_current",
        "property_plant_and_equipment_net_prior",
    ]
    assert transform.expression == (
        "revenue / ((property_plant_and_equipment_net_current + property_plant_and_equipment_net_prior) / 2)"
    )
    evidence_slots = {spec.slot_name: spec for spec in program.evidence_specs}
    assert evidence_slots["revenue"].statement == "income_statement"
    assert evidence_slots["property_plant_and_equipment_net_current"].statement == "balance_sheet"
    assert evidence_slots["property_plant_and_equipment_net_prior"].statement == "balance_sheet"
    tool_chain = program.diagnostics["tool_chain_plan"]
    assert tool_chain["formula_name"] == "fixed_asset_turnover"
    assert tool_chain["recommended_steps"][0]["decision_owner"] == "model"


def test_target_document_extraction_exposes_fixed_asset_turnover_statement_rows() -> None:
    question = (
        "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
        "Fixed asset turnover ratio is defined as: FY2019 revenue / "
        "(average PP&E between FY2018 and FY2019)."
    )
    binding = {
        "company": "Activision Blizzard",
        "doc_link": "https://investor.activision.com/static-files/example",
        "doc_type": "10k",
        "doc_period": "2019",
        "required_line_item": "revenue",
        "required_statement": "income_statement",
        "primary_source_required": True,
    }
    hint = _compiled_task_hint_for_retrieval(question=question, binding=binding)
    body = """
    ACTIVISION BLIZZARD, INC. AND SUBSIDIARIES
    CONSOLIDATED BALANCE SHEETS
    (Amounts in millions, except share data)
    At December 31, 2019 At December 31, 2018
    Assets
    Current assets:
    Total current assets 7,292 6,106
    Property and equipment, net 253 282
    Total assets $ 19,845 $ 17,890

    ACTIVISION BLIZZARD, INC. AND SUBSIDIARIES
    CONSOLIDATED STATEMENTS OF OPERATIONS
    (Amounts in millions, except per share data)
    For the Years Ended December 31,
    2019 2018 2017
    Total net revenues 6,489 7,500 7,017
    Net income $ 1,503 $ 1,848 $ 273
    """
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-fixed-asset-turnover-extract",
            query=question,
            max_spans_per_document=8,
            metadata={
                "target_document_binding": binding,
                "compiled_task_hint": hint,
            },
        ),
        document=FetchedDocument(
            document_id="doc-fixed-asset-turnover",
            goal_id="goal-fixed-asset-turnover-extract",
            source_id="source-fixed-asset-turnover",
            uri=binding["doc_link"],
            title="Activision 2019 10-K",
            artifact_id="artifact-fixed-asset-turnover",
            payload_hash="hash",
            preview=body[:120],
            size_bytes=len(body),
            metadata={"target_document_binding": binding},
        ),
        body=body,
    )

    slots = {span.metadata.get("target_slot") for span in spans}
    assert "revenue" in slots
    assert "property_plant_and_equipment_net_current" in slots
    assert "property_plant_and_equipment_net_prior" in slots
    assert any("Property and equipment, net 253 282" in span.text for span in spans)


def test_fixed_asset_turnover_filing_rows_feed_formula_planner() -> None:
    question = (
        "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
        "Fixed asset turnover ratio is defined as: FY2019 revenue / "
        "(average PP&E between FY2018 and FY2019)."
    )
    binding = {
        "company": "Activision Blizzard",
        "doc_link": "https://investor.activision.com/static-files/example",
        "doc_type": "10k",
        "doc_period": "2019",
        "required_line_item": "revenue",
        "required_statement": "income_statement",
        "primary_source_required": True,
    }
    hint = _compiled_task_hint_for_retrieval(question=question, binding=binding)
    body = """
    Item 6. SELECTED FINANCIAL DATA
    For the Years Ended December 31, 2019 2018 2017 2016 2015
    Statement of Operations Data:
    Net revenues $ 6,489 $ 7,500 $ 7,017 $ 6,608 $ 4,664
    Net income 1,503 1,848 273 966 892

    ACTIVISION BLIZZARD, INC. AND SUBSIDIARIES
    CONSOLIDATED BALANCE SHEETS
    At December 31, 2019 At December 31, 2018
    Assets
    Current assets:
    Accounts receivable, net of allowances of $132 and $190, at December 31, 2019 and December 31, 2018, respectively 848 1,035
    Software development 54 65
    Property and equipment, net 253 282
    Deferred income taxes, net 1,293 458
    Total assets $ 19,845 $ 17,890

    6. Property and Equipment, Net
    Property and equipment, net was comprised of the following (amounts in millions):
    At December 31, 2019 2018
    Land $ 1 $ 1
    Buildings 4 4
    Total cost of property and equipment 1,002 1,052
    Less accumulated depreciation (749) (770)
    Property and equipment, net $ 253 $ 282
    """
    goal = SearchGoal(
        goal_id="goal-fixed-asset-turnover-ledger",
        query=question,
        max_spans_per_document=8,
        metadata={
            "target_document_binding": binding,
            "compiled_task_hint": hint,
        },
    )
    document = FetchedDocument(
        document_id="doc-fixed-asset-turnover-ledger",
        goal_id=goal.goal_id,
        source_id="source-fixed-asset-turnover-ledger",
        uri=binding["doc_link"],
        title="Activision 2019 10-K",
        artifact_id="artifact-fixed-asset-turnover-ledger",
        payload_hash="hash",
        preview=body[:120],
        size_bytes=len(body),
        metadata={"target_document_binding": binding},
    )
    spans = extract_spans(goal=goal, document=document, body=body)
    evidence = []
    citations = []
    for index, span in enumerate(spans, start=1):
        evidence_id = f"evidence-fixed-asset-turnover-{index}"
        evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
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
                diagnostics=span.metadata,
            )
        )
        citations.append(
            CitationItem(
                citation_id=f"cite-fixed-asset-turnover-{index}",
                goal_id=goal.goal_id,
                evidence_id=evidence_id,
                artifact_id=document.artifact_id,
                uri=document.uri,
                title=document.title,
                quote=span.text[:120],
                span_start=span.start_offset,
                span_end=span.end_offset,
            )
        )

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    formula_plan = plan_finance_formula(question=question, facts=facts)

    assert formula_plan.status == "ready"
    assert formula_plan.payload["variables"] == {
        "revenue": "6489000000",
        "property_plant_and_equipment_net_current": "253000000",
        "property_plant_and_equipment_net_prior": "282000000",
    }
    assert all(fact_id.startswith("finfact-table-row-") for fact_id in formula_plan.input_fact_ids)


def test_model_first_finance_task_compiler_overrides_host_scaffold() -> None:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {
                            "task_type": "filing_metric_lookup",
                            "objective": "Find Adobe FY2018 capex from the target filing.",
                            "target_entities": ["Adobe"],
                            "target_periods": ["FY2018"],
                            "success_criteria": ["primary filing row supports the metric"],
                        },
                        "evidence_specs": [
                            {
                                "slot_name": "capital_expenditures",
                                "accepted_attributes": ["capital expenditures", "purchases of property and equipment"],
                                "source_role": "primary_filing",
                                "required_source_families": ["SEC 10-K"],
                                "target_period": "FY2018",
                                "statement": "cash_flow_statement",
                                "line_item": "purchases of property and equipment",
                                "required": True,
                            }
                        ],
                        "transform_specs": [
                            {
                                "name": "metric_lookup",
                                "required_slots": ["capital_expenditures"],
                                "expression": None,
                                "output_unit": "USD",
                                "output_attribute": "capital_expenditures",
                            }
                        ],
                        "slot_frame": {
                            "task_type": "filing_metric_lookup",
                            "required_slots": [{"name": "capital_expenditures"}],
                            "missing_slots": ["capital_expenditures"],
                        },
                        "tool_chain_plan": {
                            "decision_owner": "model",
                            "recommended_steps": [{"step": "read_target_filing", "tool": "retrieval.run"}],
                        },
                        "reason_summary": "The question is a target filing metric lookup, not a broad capital intensity comparison.",
                    }
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=JournalStore.in_memory(),
    )

    program = compile_finance_task_program_model_first(
        question="What was Adobe's capital expenditures in FY2018?",
        facts=[],
        target_binding={"company": "Adobe", "doc_period": "FY2018", "doc_type": "10-K"},
        processor_fabric=fabric,
    )

    assert program.diagnostics["source"] == "task_compile_model"
    assert program.task_spec.task_type == "filing_metric_lookup"
    assert program.evidence_specs[0].line_item == "purchases of property and equipment"
    assert program.transform_specs[0].name == "metric_lookup"
    assert program.slot_frame is not None
    assert program.slot_frame.missing_slots == ["capital_expenditures"]
    assert program.diagnostics["tool_chain_plan"]["decision_owner"] == "model"


def test_finance_task_compile_prompt_keeps_cacheable_contract_before_dynamic_packet() -> None:
    question = (
        "For NYSE: HD and NYSE: LOW, calculate FY2024 days inventory outstanding (DIO) "
        "and compare inventory efficiency. Use public filings and show the formula inputs."
    )
    facts = [
        FinanceFact(
            fact_id=f"fact-{index}",
            entity="Home Depot" if index % 2 == 0 else "Lowe's",
            ticker="HD" if index % 2 == 0 else "LOW",
            period="FY2024",
            fiscal_year=2024,
            metric="inventory" if index % 3 else "cost of revenue",
            value=str(1000 + index),
            unit="USD",
            scale="millions",
            source_ref=f"source-{index}",
            evidence_ref=f"evidence-{index}",
            citation_ref=f"cite-{index}",
            metadata={
                "form": "10-K",
                "concept": "InventoryNet",
                "label": "Inventories, net " + ("x" * 200),
                "statement": "balance_sheet",
                "line_item": "inventory",
                "source_title": "long dynamic title should stay out of task.compile prompt",
            },
        )
        for index in range(80)
    ]
    fallback = compile_finance_task_program(
        question=question,
        facts=facts,
        target_binding={"company": "HD LOW", "doc_period": "FY2024", "doc_type": "10-K"},
    )

    prompt = _model_task_compile_prompt(
        question=question,
        facts=facts,
        target_binding={"company": "HD LOW", "doc_period": "FY2024", "doc_type": "10-K"},
        fallback=fallback,
    )
    payload = json.loads(prompt)
    packet = payload["task_packet"]

    assert prompt.index('"contract"') < prompt.index('"task_packet"')
    assert prompt.index('"output_schema"') < prompt.index('"task_packet"')
    assert list(packet).index("fact_ledger") < list(packet).index("objective")
    assert len(prompt) < 22000
    assert len(packet["fact_ledger"]) == TASK_COMPILE_FACT_LIMIT
    assert packet["fact_ledger_count"] == len(facts)
    assert all("source_title" not in item.get("metadata", {}) for item in packet["fact_ledger"])
    assert "host_boundary" not in json.dumps(packet["host_fallback_program"], ensure_ascii=False)
    assert "calculator.compute" in json.dumps(packet["host_fallback_program"], ensure_ascii=False)


def test_finance_task_compile_prompt_guides_capital_intensity_roa_program() -> None:
    fallback = compile_finance_task_program(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[],
        target_binding={"company": "3M", "doc_period": "FY2022", "doc_type": "10-K"},
    )

    prompt = _model_task_compile_prompt(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[],
        target_binding={"company": "3M", "doc_period": "FY2022", "doc_type": "10-K"},
        fallback=fallback,
    )
    payload = json.loads(prompt)
    risks = payload["task_packet"]["host_fallback_risks"]

    assert "return on assets" in payload["contract"]
    assert "net_income / assets" in payload["contract"]
    assert any(item["risk"] == "capital_intensity_needs_complete_ratio_lens" for item in risks)


def test_model_first_finance_task_compiler_retries_invalid_model_json_with_model_recompile() -> None:
    valid_program = {
        "task_spec": {
            "task_type": "filing_metric_lookup",
            "objective": "Find Adobe FY2018 capex from the target filing.",
            "target_entities": ["Adobe"],
            "target_periods": ["FY2018"],
            "success_criteria": ["primary filing row supports the metric"],
        },
        "evidence_specs": [
            {
                "slot_name": "capital_expenditures",
                "accepted_attributes": ["capital expenditures", "purchases of property and equipment"],
                "source_role": "primary_filing",
                "required_source_families": ["SEC 10-K"],
                "target_period": "FY2018",
                "statement": "cash_flow_statement",
                "line_item": "purchases of property and equipment",
                "required": True,
            }
        ],
        "transform_specs": [],
        "slot_frame": {
            "task_type": "filing_metric_lookup",
            "required_slots": [{"name": "capital_expenditures"}],
            "missing_slots": ["capital_expenditures"],
        },
        "tool_chain_plan": {
            "decision_owner": "model",
            "recommended_steps": [{"tool": "retrieval.run", "reason": "read target filing"}],
        },
        "reason_summary": "The retry returns a valid model-owned work program.",
    }
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": [
                        {"task_spec": {}, "evidence_specs": "bad", "transform_specs": []},
                        valid_program,
                    ]
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )

    program = compile_finance_task_program_model_first(
        question="What was Adobe's capital expenditures in FY2018?",
        facts=[],
        target_binding={"company": "Adobe", "doc_period": "FY2018", "doc_type": "10-K"},
        processor_fabric=fabric,
        task_id="task-retry-compile",
        step_id="task-compile",
        llm_judgment_required=True,
    )

    assert program.diagnostics["source"] == "task_compile_model"
    assert program.task_spec.task_type == "filing_metric_lookup"
    assert program.evidence_specs[0].slot_name == "capital_expenditures"
    requests = journal.records(task_id="task-retry-compile", kind="processor_request")
    assert [record.data["processor"] for record in requests] == ["task.compile", "task.compile"]
    assert requests[-1].step_id == "task-compile-retry"


def test_model_first_finance_task_compiler_retry_prompt_has_structured_feedback() -> None:
    valid_program = {
        "task_spec": {
            "task_type": "filing_metric_lookup",
            "objective": "Find Adobe FY2018 capex from the target filing.",
            "target_entities": ["Adobe"],
            "target_periods": ["FY2018"],
            "success_criteria": ["primary filing row supports the metric"],
        },
        "evidence_specs": [
            {
                "slot_name": "capital_expenditures",
                "accepted_attributes": ["capital expenditures"],
                "source_role": "primary_filing",
                "required_source_families": ["SEC 10-K"],
                "target_period": "FY2018",
                "statement": "cash_flow_statement",
                "line_item": "purchases of property and equipment",
                "required": True,
            }
        ],
        "transform_specs": [],
        "slot_frame": {
            "task_type": "filing_metric_lookup",
            "required_slots": [{"name": "capital_expenditures"}],
            "missing_slots": ["capital_expenditures"],
        },
        "tool_chain_plan": {
            "decision_owner": "model",
            "recommended_steps": [{"tool": "retrieval.run", "reason": "read target filing"}],
        },
        "reason_summary": "The retry returns a valid model-owned work program.",
    }
    provider = MalformedThenTaskJsonProvider("task.compile", valid_program)
    fabric = ProcessorFabric(
        providers={"fake_repair": provider},
        router=ProcessorRouter(default_provider="fake_repair", default_model="fake-repair"),
        journal=JournalStore.in_memory(),
    )

    program = compile_finance_task_program_model_first(
        question="What was Adobe's capital expenditures in FY2018?",
        facts=[],
        target_binding={"company": "Adobe", "doc_period": "FY2018", "doc_type": "10-K"},
        processor_fabric=fabric,
        task_id="task-compile-structured-repair",
        step_id="task-compile",
        llm_judgment_required=True,
    )

    assert program.diagnostics["source"] == "task_compile_model"
    assert len(provider.prompts) == 2
    retry_prompt = json.loads(provider.prompts[-1])
    assert list(retry_prompt)[:3] == ["contract", "output_schema", "previous_failure"]
    assert provider.prompts[-1].index('"contract"') < provider.prompts[-1].index('"previous_failure"')
    assert provider.prompts[-1].index('"output_schema"') < provider.prompts[-1].index('"previous_failure"')
    assert provider.prompts[-1].index('"previous_failure"') < provider.prompts[-1].index('"task_packet"')
    structured_feedback = retry_prompt["previous_failure"]["structured_feedback"]
    assert structured_feedback["schema"] == "holo.kernel_v3.task_compile_repair_feedback.v1"
    assert structured_feedback["category"] == "malformed_json"
    assert structured_feedback["required_fields"] == ["task_spec", "evidence_specs", "transform_specs"]
    assert "Return exactly one JSON object" in structured_feedback["repair_checklist"][0]


def test_model_first_finance_task_compiler_does_not_let_fallback_override_model_judgment() -> None:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {
                            "task_type": "filing_metric_lookup",
                            "objective": "Find Activision Blizzard FY2019 revenue from the target filing.",
                            "target_entities": ["Activision Blizzard"],
                            "target_periods": ["FY2019", "FY2018"],
                            "success_criteria": ["cite the target filing"],
                        },
                        "evidence_specs": [
                            {
                                "slot_name": "revenue",
                                "accepted_attributes": ["revenue"],
                                "source_role": "primary_filing",
                                "required_source_families": ["regulatory_filing"],
                                "target_period": "FY2019",
                                "statement": "income_statement",
                                "line_item": "revenue",
                                "required": True,
                            }
                        ],
                        "transform_specs": [],
                        "slot_frame": {
                            "task_type": "filing_metric_lookup",
                            "required_slots": [{"name": "revenue"}],
                            "missing_slots": ["revenue"],
                        },
                        "tool_chain_plan": {
                            "decision_owner": "model",
                            "recommended_steps": [{"step": "read_target_filing", "tool": "retrieval.run"}],
                        },
                        "reason_summary": "The model incorrectly treated the explicit ratio formula as a lookup.",
                    }
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=JournalStore.in_memory(),
    )

    program = compile_finance_task_program_model_first(
        question=(
            "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
            "Fixed asset turnover ratio is defined as: FY2019 revenue / "
            "(average PP&E between FY2018 and FY2019)."
        ),
        facts=[],
        target_binding={"company": "Activision Blizzard", "doc_period": "2019", "doc_type": "10-K"},
        processor_fabric=fabric,
    )

    assert program.diagnostics["source"] == "task_compile_model"
    assert program.task_spec.task_type == "filing_metric_lookup"
    assert [spec.slot_name for spec in program.evidence_specs] == ["revenue"]
    assert program.transform_specs == []
    assert program.slot_frame is not None
    assert program.slot_frame.task_type == "filing_metric_lookup"
    assert program.slot_frame.missing_slots == ["revenue"]
    assert program.diagnostics["semantic_decision_owner"] == "model"
    assert program.diagnostics["host_fallback_role"] == "scaffold_only_no_semantic_override"
    assert program.diagnostics["tool_chain_plan"]["decision_owner"] == "model"


def test_model_first_capital_intensity_compile_preserves_fallback_roa_scaffold() -> None:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {
                            "task_type": "compute",
                            "objective": "Assess 3M FY2022 capital intensity.",
                            "target_entities": ["3M"],
                            "target_periods": ["2022"],
                            "success_criteria": ["compute capex/revenue, capex/OCF, and PP&E/assets"],
                            "diagnostics": {"formula_name": "capital_intensity"},
                        },
                        "evidence_specs": [
                            {"slot_name": "capital_expenditures", "line_item": "capital expenditures", "required": True},
                            {"slot_name": "revenue", "line_item": "revenue", "required": True},
                            {"slot_name": "operating_cash_flow", "line_item": "operating cash flow", "required": True},
                            {
                                "slot_name": "property_plant_and_equipment_net",
                                "line_item": "property plant and equipment net",
                                "required": True,
                            },
                            {"slot_name": "assets", "line_item": "assets", "required": True},
                        ],
                        "transform_specs": [
                            {
                                "name": "capital_intensity_capex_revenue",
                                "required_slots": ["capital_expenditures", "revenue"],
                                "expression": "capital_expenditures / revenue",
                                "output_unit": "percent",
                            },
                            {
                                "name": "capital_intensity_capex_operating_cash_flow",
                                "required_slots": ["capital_expenditures", "operating_cash_flow"],
                                "expression": "capital_expenditures / operating_cash_flow",
                                "output_unit": "percent",
                            },
                            {
                                "name": "capital_intensity_ppe_assets",
                                "required_slots": ["property_plant_and_equipment_net", "assets"],
                                "expression": "property_plant_and_equipment_net / assets",
                                "output_unit": "percent",
                            },
                        ],
                        "slot_frame": {
                            "task_type": "compute",
                            "required_slots": [
                                {"name": "capital_expenditures"},
                                {"name": "revenue"},
                                {"name": "operating_cash_flow"},
                                {"name": "property_plant_and_equipment_net"},
                                {"name": "assets"},
                            ],
                            "missing_slots": [
                                "capital_expenditures",
                                "revenue",
                                "operating_cash_flow",
                                "property_plant_and_equipment_net",
                                "assets",
                            ],
                        },
                        "tool_chain_plan": {"decision_owner": "model", "recommended_steps": [{"tool": "retrieval.run"}]},
                    }
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=JournalStore.in_memory(),
    )

    program = compile_finance_task_program_model_first(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[],
        processor_fabric=fabric,
    )

    evidence_slots = {spec.slot_name for spec in program.evidence_specs}
    transform_names = {spec.name for spec in program.transform_specs}
    assert "net_income" in evidence_slots
    assert "capital_intensity_return_on_assets" in transform_names
    assert program.slot_frame is not None
    assert "net_income" in program.slot_frame.missing_slots
    assert program.slot_frame.diagnostics["fallback_formula_contract_preserved"] is True


def test_model_first_finance_task_compiler_falls_back_on_invalid_model_output() -> None:
    fabric = ProcessorFabric(
        providers={"fake_json": FakeJsonProvider({"task.compile": {"task_spec": {}, "evidence_specs": "bad", "transform_specs": []}})},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=JournalStore.in_memory(),
    )

    program = compile_finance_task_program_model_first(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[],
        processor_fabric=fabric,
    )

    assert program.diagnostics["source"] == "finance_task_compiler"
    assert program.diagnostics["task_compile_model"]["status"] == "fallback"
    assert "capital_expenditures" in program.diagnostics["missing_slots"]


def test_finance_capability_task_compiler_blocks_host_semantic_fallback_without_llm() -> None:
    program = compile_finance_task_program_model_first(
        question="Is 3M a capital-intensive business based on FY2022 data?",
        facts=[],
        processor_fabric=None,
        llm_judgment_required=True,
    )

    assert program.diagnostics["source"] == "task_compile_model_unavailable"
    assert program.diagnostics["status"] == "llm_judgment_unavailable"
    assert program.diagnostics["semantic_decision_owner"] == "model"
    assert program.diagnostics["host_fallback_role"] == "blocked_no_semantic_override"
    assert program.task_spec.task_type == "model_judgment_unavailable"
    assert program.evidence_specs == []
    assert program.transform_specs == []
    assert program.slot_frame is not None
    assert program.slot_frame.missing_slots == ["llm_task_compile_judgment"]


def test_planner_replan_hints_include_execution_program_for_model_tool_assembly() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "research_profile": "finance_fundamentals",
            "goal": "Is 3M a capital-intensive business based on FY2022 data?",
        },
    )

    hints = _agent_replan_hints(
        JournalStore.in_memory(),
        task_id="task-execution-program",
        run_id="run-execution-program",
        recipe=recipe,
    )

    program = hints["execution_program"]
    assert program["schema"] == "holo.kernel_v3.execution_program_prompt.v1"
    assert program["task_spec"]["task_type"] == "compute"
    assert "capital_expenditures" in program["missing_slots"]
    assert program["tool_chain_plan"]["decision_owner"] == "model"
    assert "retrieval.run" in [item["name"] for item in program["tool_chain_plan"]["available_tools"]]
    assert any(
        item["tool"] == "retrieval.run"
        for item in program["tool_chain_plan"]["next_action_candidates"]
    )


def test_finance_capability_replan_hints_require_llm_task_compile_not_host_formula_fallback() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "research_profile": "finance_fundamentals",
            "goal": "Is 3M a capital-intensive business based on FY2022 data?",
        },
    )

    hints = _agent_replan_hints(
        JournalStore.in_memory(),
        task_id="task-capability-execution-program",
        run_id="run-capability-execution-program",
        recipe=recipe,
    )

    program = hints["execution_program"]
    assert program["schema"] == "holo.kernel_v3.execution_program_prompt.v1"
    assert program["task_spec"]["task_type"] == "model_judgment_unavailable"
    assert program["missing_slots"] == ["llm_task_compile_judgment"]
    assert program["tool_chain_plan"]["decision_owner"] == "model"
    assert program["tool_chain_plan"]["host_role"] == "tool_interface_only_until_model_judgment_returns"
    assert "capital_expenditures" not in program["missing_slots"]


def test_runtime_preflight_task_compile_injects_model_execution_program() -> None:
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {
                            "task_type": "filing_metric_lookup",
                            "objective": "Find the target filing metric.",
                            "target_entities": ["Adobe"],
                            "target_periods": ["FY2018"],
                            "success_criteria": ["primary filing evidence supports the value"],
                        },
                        "evidence_specs": [
                            {
                                "slot_name": "capital_expenditures",
                                "accepted_attributes": ["purchases of property and equipment"],
                                "source_role": "primary_filing",
                                "target_period": "FY2018",
                                "statement": "cash_flow_statement",
                                "line_item": "purchases of property and equipment",
                            }
                        ],
                        "transform_specs": [],
                        "slot_frame": {
                            "task_type": "filing_metric_lookup",
                            "required_slots": [{"name": "capital_expenditures"}],
                            "missing_slots": ["capital_expenditures"],
                        },
                    },
                    "planner.propose": {
                        "action_id": "act-stop-after-preflight",
                        "kind": "respond",
                        "name": None,
                        "description": "stop after preflight for test",
                        "payload": {"text": "preflight observed"},
                        "score": 0.1,
                        "reasons": ["test_stop"],
                        "side_effect_class": "none",
                    },
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=JournalStore.in_memory(),
    )
    metadata = {
        **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
        "research_profile": "finance_fundamentals",
        "target_document_binding": {"company": "Adobe", "doc_period": "FY2018", "doc_type": "10-K"},
    }
    runtime = AgentRuntime(journal=fabric.journal, processor_fabric=fabric)

    result = runtime.run(
        "What was Adobe's capital expenditures in FY2018?",
        mode="retrieval_answer",
        planner_mode="model",
        evaluator_mode="fake",
        synthesizer_mode="fake",
        semantic_mode="fake",
        execution_metadata=metadata,
    )

    records = fabric.journal.records(kind="compiled_task_program")
    assert result.task_id
    assert records
    preflight = records[0].data
    assert preflight["source"] == "task_compile_model"
    assert preflight["preflight"] is True
    assert preflight["task_spec"]["task_type"] == "filing_metric_lookup"
    assert preflight["evidence_specs"][0]["line_item"] == "purchases of property and equipment"
    toolchain_plans = fabric.journal.records(task_id=result.task_id, kind="toolchain_plan")
    assert toolchain_plans
    assert toolchain_plans[0].data["decision_owner"] == "model"


def test_finance_fast_recipe_exposes_composable_toolchain_tools(tmp_path) -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
    )

    assert "retrieval.run" in recipe.allowed_tools
    assert CALCULATOR_TOOL_NAME in recipe.allowed_tools
    assert FINANCE_VERIFY_NUMERIC_TOOL_NAME in recipe.allowed_tools
    assert "workspace.list" in recipe.allowed_tools
    assert "workspace.search" in recipe.allowed_tools
    assert "file.read" in recipe.allowed_tools
    assert "shell.exec" in recipe.allowed_tools
    assert "shell:exec" in recipe.metadata["allowed_permissions"]

    runtime = AgentRuntime(journal=JournalStore.in_memory(), workspace_root=tmp_path)
    registry = runtime._registry(recipe, "Analyze local finance evidence with a temporary script.")
    manifests = {manifest.name: manifest for manifest in registry.manifests()}

    assert {"retrieval.run", CALCULATOR_TOOL_NAME, FINANCE_VERIFY_NUMERIC_TOOL_NAME, "workspace.search", "file.read", "shell.exec"} <= set(manifests)
    shell_action = CandidateAction(
        action_id="act-shell-readonly-analysis",
        kind="tool",
        name="shell.exec",
        description="Run a tiny local analysis command",
        score=1.0,
        payload={"argv": ["python3", "-c", "print('toolchain-ok')"]},
        reasons=["composable_toolchain_test"],
        side_effect_class="shell",
    )
    decision = PolicyGate(permission=recipe.permission_profile, allowed_permissions=set(recipe.metadata["allowed_permissions"])).validate(
        run_id="run-toolchain",
        action=shell_action,
        manifest=manifests["shell.exec"],
    )
    result = registry.execute_with_artifacts(
        shell_action,
        policy_decision=decision,
        execution_context={"run_id": "run-toolchain"},
    )

    assert decision.allowed is True
    assert result.observation.status == "ok"
    assert result.observation.content["stdout"].strip() == "toolchain-ok"


def test_finance_capability_profile_exposes_write_and_script_exec_tools(tmp_path) -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )

    assert "workspace.write" in recipe.allowed_tools
    assert "script.exec" in recipe.allowed_tools
    assert "workspace:write" in recipe.metadata["allowed_permissions"]
    assert "shell:exec" in recipe.metadata["allowed_permissions"]

    runtime = AgentRuntime(journal=JournalStore.in_memory(), workspace_root=tmp_path)
    registry = runtime._registry(recipe, "Parse a local filing with a temporary script.")
    manifests = {manifest.name: manifest for manifest in registry.manifests()}
    assert {"workspace.write", "script.exec", "shell.exec", "retrieval.run", CALCULATOR_TOOL_NAME} <= set(manifests)

    script_action = CandidateAction(
        action_id="act-script-exec-json",
        kind="tool",
        name="script.exec",
        description="Run temporary parser",
        score=1.0,
        payload={
            "language": "python",
            "script": (
                "import json\n"
                "print(json.dumps({'facts':["
                "{'entityName':'TestCo','ticker':'TCO','concept':'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax','label':'Revenue','metric':'revenue','unit':'USD','fy':2024,'form':'10-K','value':200}"
                "]}))\n"
            ),
            "expected_output": "json",
            "timeout_seconds": 10,
        },
        reasons=["capability_profile_script_exec_test"],
        side_effect_class="shell",
    )
    decision = PolicyGate(permission=recipe.permission_profile, allowed_permissions=set(recipe.metadata["allowed_permissions"])).validate(
        run_id="run-script",
        action=script_action,
        manifest=manifests["script.exec"],
    )
    result = registry.execute_with_artifacts(
        script_action,
        policy_decision=decision,
        execution_context={"run_id": "run-script"},
    )

    assert decision.allowed is True
    assert result.observation.status == "ok"
    assert result.observation.content["stdout_json"]["facts"][0]["metric"] == "revenue"
    assert result.observation.content["script_path"].startswith(".holo_toolchain/scripts/")
    assert len(result.artifact_refs) >= 2


def test_finance_fast_planner_directive_shows_composable_toolchain() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
    )

    directive = _planner_directive(recipe)
    tool_names = [item["name"] for item in directive["tool_selection"]]

    assert "retrieval.run" in tool_names
    assert CALCULATOR_TOOL_NAME in tool_names
    assert FINANCE_VERIFY_NUMERIC_TOOL_NAME in tool_names
    assert "workspace.list" in tool_names
    assert "workspace.search" in tool_names
    assert "file.read" in tool_names
    assert "shell.exec" in tool_names
    assert "shell.exec" not in directive["forbidden"]


def test_finance_fast_model_planner_can_select_verify_numeric_tool() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
    )
    fact = FinanceFact(
        fact_id="fact-revenue",
        entity="Example Co",
        ticker="EXM",
        period="FY2024",
        fiscal_year=2024,
        metric="revenue",
        value="10000000",
        unit="USD",
        scale=None,
        source_ref="src-1",
        evidence_ref="ev-1",
        citation_ref="cite-1",
        metadata={},
    )
    action_payload = {
        "action_id": "act-verify-from-planner",
        "kind": "tool",
        "name": FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        "description": "verify draft answer numeric support",
        "payload": {
            "answer": "Example Co FY2024 revenue was $10 million.",
            "facts": [fact.to_dict()],
            "formula_traces": [],
            "citations": [],
            "evidence": [],
            "question": "What was Example Co FY2024 revenue?",
        },
        "score": 0.92,
        "reasons": ["draft answer should be checked against finance facts"],
        "side_effect_class": "read",
    }
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"fake_json": FakeJsonProvider({"planner.propose": action_payload})},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    planner = ModelPlanner(
        fabric=fabric,
        allowed_tool_names=_planner_allowed_tool_names(recipe),
    )
    context = ContextBundle(
        context_id="ctx-verify-tool",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-verify-tool", "run_id": "run-verify-tool", "input_text": "verify finance answer"},
        token_budget=4096,
    )
    runtime = AgentRuntime(journal=journal)
    registry = runtime._registry(recipe, "verify finance answer")

    action = planner.propose(context)
    decision = PolicyGate(permission=recipe.permission_profile).validate(
        run_id="run-verify-tool",
        action=action,
        manifest=registry.manifest_for_action(action),
    )
    observation = registry.execute_with_artifacts(action, policy_decision=decision).observation

    assert action.name == FINANCE_VERIFY_NUMERIC_TOOL_NAME
    assert FINANCE_VERIFY_NUMERIC_TOOL_NAME in _planner_allowed_tool_names(recipe)
    assert decision.allowed
    assert observation.status == "ok"
    assert observation.source == f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}"
    assert observation.content["verification"]["status"] == "passed"


def test_finance_capability_planner_directive_shows_script_toolchain() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )

    directive = _planner_directive(recipe)
    tool_names = [item["name"] for item in directive["tool_selection"]]

    assert "workspace.write" in tool_names
    assert "script.exec" in tool_names
    assert "script.exec" not in directive["forbidden"]
    script_entry = next(item for item in directive["tool_selection"] if item["name"] == "script.exec")
    assert any(str(item).startswith("expected_output: json") for item in script_entry["payload_requirements"])


def test_retrieval_finalizer_uses_shell_exec_output_as_toolchain_evidence() -> None:
    journal = JournalStore.in_memory()
    runtime = AgentRuntime(journal=journal)
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "goal": "What was TestCo revenue in FY2024?",
        },
    )
    journal.append(
        task_id="task-shell-grounding",
        run_id="run-shell-grounding",
        step_id="step-shell",
        kind="observation",
        data={
            "observation_id": "obs-shell-grounding",
            "run_id": "run-shell-grounding",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:shell.exec",
            "content": {
                "argv": ["python3", "parse_filing.py"],
                "exit_code": 0,
                "stdout": "entity: TestCo metric: revenue value: 123000000 unit: USD period: FY2024",
                "stderr": "",
            },
            "observed_at_ms": 1,
            "action_id": "act-shell-grounding",
            "tool_call_id": None,
        },
        observation_ref="obs-shell-grounding",
        state_delta={"observation_status": "ok"},
    )

    final, failure = runtime._finalize_retrieval(
        "task-shell-grounding",
        "run-shell-grounding",
        recipe=recipe,
        loop_stop_reason="completed",
        synthesizer_mode="fake",
    )

    assert failure is None
    assert final is not None
    assert final.citation_refs == ["workspace-cite-1"]
    ledgers = journal.records(task_id="task-shell-grounding", kind="finance_fact_ledger")
    assert ledgers
    facts = ledgers[-1].data["facts"]
    assert any(fact["metric"] == "revenue" and fact["value"] == "123000000" for fact in facts)


def test_shell_exec_facts_trigger_finance_calculator_before_final_answer() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-premature-shell-answer",
                kind="respond",
                name="respond",
                description="Answer after local parsing",
                score=0.58,
                payload={"text": "TestCo net margin can now be answered."},
                reasons=["model_answer_ready_after_shell_exec"],
                side_effect_class="none",
            )

    journal = JournalStore.in_memory()
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "goal": "Calculate TestCo FY2024 net margin.",
        },
    )
    for index, stdout in enumerate(
        [
            (
                "entityName=TestCo ticker=TCO "
                "concept=us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax "
                "label=Revenue metric=revenue unit=USD fy=2024 form=10-K filed=2024-11-01 value=200"
            ),
            (
                "entityName=TestCo ticker=TCO concept=us-gaap:NetIncomeLoss "
                "label=Net income metric=net income unit=USD fy=2024 form=10-K filed=2024-11-01 value=50"
            ),
        ],
        start=1,
    ):
        journal.append(
            task_id="task-shell-formula",
            run_id="run-shell-formula",
            step_id=f"step-shell-{index}",
            kind="observation",
            data={
                "observation_id": f"obs-shell-formula-{index}",
                "run_id": "run-shell-formula",
                "kind": "tool_result",
                "status": "ok",
                "source": "tool:shell.exec",
                "content": {
                    "argv": ["python3", "parse_cached_filing.py", str(index)],
                    "exit_code": 0,
                    "stdout": stdout,
                    "stderr": "",
                },
                "observed_at_ms": index,
                "action_id": f"act-shell-formula-{index}",
                "tool_call_id": None,
            },
            observation_ref=f"obs-shell-formula-{index}",
            state_delta={"observation_status": "ok"},
        )

    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal="Calculate TestCo FY2024 net margin.",
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-shell-formula",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-shell-formula", "run_id": "run-shell-formula"},
        token_budget=4096,
    )

    action = planner.propose(context)

    assert action.name == CALCULATOR_TOOL_NAME
    assert action.payload["formula_name"] == "margin"
    assert action.payload["variables"] == {"numerator": "50", "denominator": "200"}
    assert "calculator_required_before_final" in action.reasons
    plans = journal.records(task_id="task-shell-formula", kind="finance_formula_plan")
    assert plans[-1].data["fact_count"] == 2


def test_finance_capability_script_exec_json_facts_do_not_trigger_host_calculator_rewrite() -> None:
    class RespondingPlanner:
        def propose(self, context, feedback=None):
            return CandidateAction(
                action_id="act-premature-script-answer",
                kind="respond",
                name="respond",
                description="Answer after script parser",
                score=0.58,
                payload={"text": "TestCo net margin can now be answered."},
                reasons=["model_answer_ready_after_script_exec"],
                side_effect_class="none",
            )

    journal = JournalStore.in_memory()
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "goal": "Calculate TestCo FY2024 net margin.",
        },
    )
    journal.append(
        task_id="task-script-formula",
        run_id="run-script-formula",
        step_id="step-script",
        kind="observation",
        data={
            "observation_id": "obs-script-formula",
            "run_id": "run-script-formula",
            "kind": "tool_result",
            "status": "ok",
            "source": "tool:script.exec",
            "content": {
                "language": "python",
                "script_path": ".holo_toolchain/scripts/parser.py",
                "argv": ["python3", ".holo_toolchain/scripts/parser.py"],
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "facts": [
                            {
                                "entityName": "TestCo",
                                "ticker": "TCO",
                                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                                "label": "Revenue",
                                "metric": "revenue",
                                "unit": "USD",
                                "fy": 2024,
                                "form": "10-K",
                                "value": 200,
                            },
                            {
                                "entityName": "TestCo",
                                "ticker": "TCO",
                                "concept": "us-gaap:NetIncomeLoss",
                                "label": "Net income",
                                "metric": "net income",
                                "unit": "USD",
                                "fy": 2024,
                                "form": "10-K",
                                "value": 50,
                            },
                        ]
                    }
                ),
                "stderr": "",
                "expected_output": "json",
            },
            "observed_at_ms": 1,
            "action_id": "act-script-formula",
            "tool_call_id": None,
        },
        observation_ref="obs-script-formula",
        state_delta={"observation_status": "ok"},
    )

    planner = _RecipeBoundPlanner(
        inner=RespondingPlanner(),
        goal="Calculate TestCo FY2024 net margin.",
        recipe=recipe,
        journal=journal,
    )
    context = ContextBundle(
        context_id="ctx-script-formula",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-script-formula", "run_id": "run-script-formula"},
        token_budget=4096,
    )

    action = planner.propose(context)

    assert action.kind == "respond"
    assert action.name == "respond"
    assert action.payload["text"] == "TestCo net margin can now be answered."
    assert not journal.records(task_id="task-script-formula", kind="finance_formula_plan")
    assert not journal.records(task_id="task-script-formula", kind="toolchain_step_proposed")


def test_script_exec_table_rows_become_scaled_candidate_facts() -> None:
    candidates = _toolchain_candidate_facts(
        {
            "stdout": json.dumps(
                {
                    "entityName": "3M Company",
                    "ticker": "MMM",
                    "unit": "USD",
                    "scale": "millions",
                    "form": "10-K",
                    "tables": [
                        {
                            "name": "cash flow statement",
                            "rows": [
                                {
                                    "line_item": "Payments to Acquire Property, Plant, and Equipment",
                                    "2018": "(1,577)",
                                }
                            ],
                        }
                    ],
                }
            )
        },
        source="tool:script.exec",
    )

    assert candidates
    evidence = [
        _finance_evidence(
            evidence_id="toolchain-table-capex",
            title="script exec candidate fact",
            uri="workspace://parser.py",
            text=_candidate_fact_evidence_text(candidates[0]),
        )
    ]
    facts = build_finance_fact_ledger(evidence=evidence, citations=[_finance_citation(evidence[0], citation_id="cite-script")])

    assert len(facts) == 1
    assert facts[0].entity == "3M Company"
    assert facts[0].metric == "capital expenditures"
    assert facts[0].fiscal_year == 2018
    assert facts[0].value == "-1577000000"
    assert facts[0].scale == "millions"
    assert facts[0].citation_ref == "cite-script"


def test_structured_metric_value_evidence_does_not_emit_unscaled_natural_duplicate() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="html-table-fact",
            title="html table candidate fact",
            uri="workspace://html-table",
            text=(
                "html_table_fact_1_2_2022: metric=Safety and Industrial net sales "
                "fy=2022 value=11639 scale=millions"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-html-table")],
    )

    assert len(facts) == 1
    assert facts[0].metric == "safety and industrial net sales"
    assert facts[0].fiscal_year == 2022
    assert facts[0].value == "11639000000"
    assert facts[0].scale == "millions"


def test_sec_metadata_taxonomy_header_does_not_emit_natural_revenue_fact() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="sec-header-noise",
            title="0000066740 23 000014",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt",
            text=(
                "FORMER CONFORMED NAME: MINNESOTA MINING & MANUFACTURING CO "
                "DATE OF NAME CHANGE: 19920703 10-K 1 mmm-20221231.htm "
                "http://fasb.org/us-gaap/2022#Revenues 0000066740 FALSE 2022 FY"
            ),
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-sec-header-noise")],
    )

    assert facts == []


def test_toolchain_grounding_journals_failed_script_observation_for_replanning() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-script-fail",
        run_id="run-script-fail",
        step_id="step-script",
        kind="observation",
        data={
            "observation_id": "obs-script-fail",
            "run_id": "run-script-fail",
            "kind": "tool_result",
            "status": "failed",
            "source": "tool:script.exec",
            "content": {
                "language": "python",
                "script_path": ".holo_toolchain/scripts/failing_parser.py",
                "exit_code": 1,
                "stdout": "",
                "stderr": "ValueError: table columns did not align",
                "script_artifact_id": "artifact-script-source",
                "output_artifact_id": "artifact-script-output",
            },
            "action_id": "act-script-fail",
        },
        observation_ref="obs-script-fail",
        action_ref="act-script-fail",
        artifact_refs=["artifact-script-source", "artifact-script-output"],
    )

    evidence, citations, report = _workspace_grounding(
        journal,
        "task-script-fail",
        "run-script-fail",
        artifact_store=ArtifactStore.in_memory(),
    )

    assert evidence == []
    assert citations == []
    assert report.status == "insufficient_evidence"
    failures = journal.records(task_id="task-script-fail", kind="toolchain_failure")
    artifacts = journal.records(task_id="task-script-fail", kind="toolchain_artifact")
    executed = journal.records(task_id="task-script-fail", kind="toolchain_step_executed")
    assert failures
    assert failures[-1].data["stderr_preview"] == "ValueError: table columns did not align"
    assert failures[-1].data["artifact_refs"] == ["artifact-script-source", "artifact-script-output"]
    assert artifacts[-1].data["artifact_refs"] == ["artifact-script-source", "artifact-script-output"]
    assert executed[-1].data["status"] == "failed"


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


def test_finance_formula_planner_uses_net_income_for_net_profit_margin() -> None:
    plan = plan_finance_formula(
        question="What was Apple's net profit margin for fiscal year 2024?",
        facts=[
            _year_fact(
                "revenue",
                "391035000000",
                2024,
                fact_id="apple-revenue",
                metadata={"source": "sec_companyfacts", "form": "10-K", "fp": "FY", "end": "2024-09-28"},
            ),
            _year_fact(
                "net income",
                "36330000000",
                2024,
                fact_id="apple-net-income-quarterly-after-fy",
                metadata={
                    "source": "sec_companyfacts",
                    "form": "10-Q",
                    "fp": "Q1",
                    "frame": "CY2024Q4",
                    "end": "2024-12-28",
                },
            ),
            _year_fact(
                "net income",
                "93736000000",
                2024,
                fact_id="apple-net-income",
                metadata={"source": "sec_companyfacts", "form": "10-K", "fp": "FY", "end": "2024-09-28"},
            ),
            _year_fact(
                "net income",
                "26102000000",
                2024,
                fact_id="apple-income-taxes-paid-net-pollution",
                metadata={
                    "source": "sec_companyfacts",
                    "concept": "IncomeTaxesPaidNet",
                    "label": "Income Taxes Paid, Net",
                    "form": "10-K",
                    "fp": "FY",
                    "end": "2024-09-28",
                    "filed": "2025-10-31",
                },
            ),
            _year_fact("operating income", "123216000000", 2024, fact_id="apple-operating-income"),
        ],
    )

    assert plan.status == "ready"
    assert plan.payload["variables"] == {"numerator": "93736000000", "denominator": "391035000000"}
    assert plan.input_fact_ids == ["apple-net-income", "apple-revenue"]


def test_finance_formula_planner_rejects_contract_liability_revenue_denominator() -> None:
    plan = plan_finance_formula(
        question="What was Apple's net profit margin for fiscal year 2024?",
        facts=[
            _year_fact(
                "revenue",
                "7728000000",
                2024,
                fact_id="apple-contract-liability-revenue",
                metadata={"concept": "ContractWithCustomerLiabilityRevenueRecognized"},
            ),
            _year_fact("net income", "93736000000", 2024, fact_id="apple-net-income"),
        ],
    )

    assert plan.status == "missing_facts"
    assert "revenue_denominator" in plan.missing_facts


def test_finance_formula_planner_uses_gross_profit_for_gross_margin() -> None:
    plan = plan_finance_formula(
        question="What was NVIDIA's gross margin for fiscal year 2024?",
        facts=[
            _year_fact("revenue", "60922000000", 2024, fact_id="nvda-revenue"),
            _year_fact("gross profit", "44301000000", 2024, fact_id="nvda-gross-profit"),
            _year_fact("net income", "29760000000", 2024, fact_id="nvda-net-income"),
        ],
    )

    assert plan.status == "ready"
    assert plan.payload["variables"] == {"numerator": "44301000000", "denominator": "60922000000"}
    assert plan.input_fact_ids == ["nvda-gross-profit", "nvda-revenue"]


def test_finance_formula_planner_uses_requested_metric_for_growth() -> None:
    plan = plan_finance_formula(
        question="What was Meta's net income growth from fiscal year 2023 to 2024?",
        facts=[
            _year_fact("revenue", "134902000000", 2023, fact_id="meta-revenue-2023"),
            _year_fact("revenue", "164501000000", 2024, fact_id="meta-revenue-2024"),
            _year_fact("net income", "39098000000", 2023, fact_id="meta-net-income-2023"),
            _year_fact("net income", "62360000000", 2024, fact_id="meta-net-income-2024"),
        ],
    )

    assert plan.status == "ready"
    assert plan.formula_name == "yoy_growth"
    assert plan.payload["variables"] == {"prior_value": "39098000000", "current_value": "62360000000"}
    assert plan.input_fact_ids == ["meta-net-income-2023", "meta-net-income-2024"]


def test_finance_formula_planner_supports_debt_to_equity_ratio() -> None:
    plan = plan_finance_formula(
        question="What was JPMorgan Chase's debt-to-equity ratio as of year-end 2024?",
        facts=[
            _year_fact("liabilities", "3658056000000", 2024, fact_id="jpm-liabilities"),
            _year_fact("shareholders equity", "344758000000", 2024, fact_id="jpm-equity"),
        ],
    )

    assert plan.status == "ready"
    assert plan.formula_name == "debt_to_equity"
    assert plan.payload["variables"] == {
        "liabilities_or_debt": "3658056000000",
        "shareholders_equity": "344758000000",
    }


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
        FinanceFact(
            fact_id="net-income",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="net income",
            value="5777000000",
            unit="USD",
            scale="actual",
            source_ref="cite-net-income",
            evidence_ref="ev-net-income",
            citation_ref="cite-net-income",
            metadata={},
        ),
    ]

    plan = plan_finance_formula(question="Is 3M a capital-intensive business based on FY2022 data?", facts=facts)

    assert plan.status == "ready"
    assert plan.formula_name == "capital_intensity"
    assert plan.payload["expression"] == "capital_expenditures / revenue"
    assert plan.payload["variables"]["capital_expenditures"] == "1334000000"
    assert set(plan.input_fact_ids) == {"capex", "revenue", "ocf", "ppe", "assets", "net-income"}
    assert set(plan.payload["diagnostics"]["model_outputs"]) == {
        "capex_to_revenue",
        "capex_to_operating_cash_flow",
        "ppe_to_assets",
        "return_on_assets",
    }


def test_finance_formula_planner_generates_fixed_asset_turnover_payload() -> None:
    facts = [
        FinanceFact(
            fact_id="revenue-2019",
            entity="Activision Blizzard",
            ticker="ATVI",
            period="2019",
            fiscal_year=2019,
            metric="revenue",
            value="6489",
            unit="USD millions",
            scale="millions",
            source_ref="cite-revenue-2019",
            evidence_ref="ev-revenue-2019",
            citation_ref="cite-revenue-2019",
            metadata={},
        ),
        FinanceFact(
            fact_id="ppe-2019",
            entity="Activision Blizzard",
            ticker="ATVI",
            period="2019",
            fiscal_year=2019,
            metric="property plant and equipment net",
            value="272",
            unit="USD millions",
            scale="millions",
            source_ref="cite-ppe-2019",
            evidence_ref="ev-ppe-2019",
            citation_ref="cite-ppe-2019",
            metadata={},
        ),
        FinanceFact(
            fact_id="ppe-2018",
            entity="Activision Blizzard",
            ticker="ATVI",
            period="2018",
            fiscal_year=2018,
            metric="property plant and equipment net",
            value="263",
            unit="USD millions",
            scale="millions",
            source_ref="cite-ppe-2018",
            evidence_ref="ev-ppe-2018",
            citation_ref="cite-ppe-2018",
            metadata={},
        ),
    ]

    plan = plan_finance_formula(
        question=(
            "What is the FY2019 fixed asset turnover ratio for Activision Blizzard? "
            "Fixed asset turnover ratio is defined as: FY2019 revenue / "
            "(average PP&E between FY2018 and FY2019)."
        ),
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.formula_name == "fixed_asset_turnover"
    assert plan.payload["expression"] == (
        "revenue / ((property_plant_and_equipment_net_current + property_plant_and_equipment_net_prior) / 2)"
    )
    assert plan.payload["variables"] == {
        "revenue": "6489",
        "property_plant_and_equipment_net_current": "272",
        "property_plant_and_equipment_net_prior": "263",
    }
    assert set(plan.input_fact_ids) == {"revenue-2019", "ppe-2019", "ppe-2018"}

    result = compute_formula(
        expression=plan.payload["expression"],
        variables=plan.payload["variables"],
        unit=plan.payload["unit"],
        formula_name=plan.formula_name,
    )
    assert Decimal(result.result_value).quantize(Decimal("0.01")) == Decimal("24.26")


def test_capital_intensity_model_outputs_support_verifier_answer_numbers() -> None:
    facts = [
        FinanceFact(
            fact_id="capex",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="capital expenditures",
            value="1749000000",
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
            value="34229000000",
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
            value="5591000000",
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
            value="9178000000",
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
        FinanceFact(
            fact_id="net-income",
            entity="3M",
            ticker="MMM",
            period="2022",
            fiscal_year=2022,
            metric="net income",
            value="5777000000",
            unit="USD",
            scale="actual",
            source_ref="cite-net-income",
            evidence_ref="ev-net-income",
            citation_ref="cite-net-income",
            metadata={},
        ),
    ]
    plan = plan_finance_formula(question="Is 3M a capital-intensive business based on FY2022 data?", facts=facts)

    assert plan.status == "ready"
    trace = compute_formula(**plan.payload)
    verification = verify_finance_answer(
        answer="FY2022 metrics: capex/revenue was 5.1%, PPE/assets was 19.8%, and ROA was 12.4%.",
        facts=facts,
        formula_traces=[trace],
        question="Is 3M a capital-intensive business based on FY2022 data?",
    )

    assert verification.status == "passed"


def test_numeric_verifier_accepts_absolute_percent_display_from_negative_capex_trace() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-capex-revenue",
            formula_name="capex_to_revenue",
            expression="capex_raw / revenue",
            input_fact_ids=["capex", "revenue"],
            result_value="-0.05109702299219959683309474422",
            unit="percent",
            diagnostics={"variables": {"capex_raw": "-1749000000", "revenue": "34229000000"}},
        ),
        FormulaTrace(
            formula_id="formula-capex-ocf",
            formula_name="capex_to_ocf",
            expression="capex_raw / ocf",
            input_fact_ids=["capex", "ocf"],
            result_value="-0.3128241817206224289035950635",
            unit="percent",
            diagnostics={"variables": {"capex_raw": "-1749000000", "ocf": "5591000000"}},
        ),
    ]

    verification = verify_finance_answer(
        answer=(
            "FY2022 capex was $1,749 million, revenue was $34,229 million, and operating cash flow was "
            "$5,591 million. Capex/revenue was 5.1% and capex/operating cash flow was 31.3%, so 3M "
            "does not look highly capital-intensive on these measures."
        ),
        facts=[],
        formula_traces=traces,
        question="Is 3M a capital-intensive business based on FY2022 data?",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []
    assert verification.unit_mismatches == []


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
        "net_income",
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


def test_semantic_retrieval_args_normalize_model_source_families_to_standard_interface() -> None:
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "semantic_intake": {
                "intents": [
                    {
                        "kind": "finance_fundamentals",
                        "required_capabilities": ["retrieval.run", "finance.fundamentals_research"],
                        "metadata": {
                            "capability_args": {
                                "retrieval.run": [
                                    {
                                        "query": "TJX Q4 FY2025 pre-tax profit margin guidance actual results",
                                        "source_families": ["sec_edgar", "earnings_release"],
                                    },
                                    {
                                        "query": "TJX Companies Q4 fiscal 2025 earnings release pre-tax margin",
                                        "metadata": {
                                            "source_family_plan": [
                                                {"family": "investor_relations"},
                                                {"source_family": "regulatory_filing"},
                                            ]
                                        },
                                    },
                                ]
                            }
                        },
                    }
                ]
            }
        },
    )

    payload = _retrieval_capability_args(recipe)

    preferred = payload["metadata"]["preferred_source_families"]
    assert payload["queries"] == [
        "TJX Q4 FY2025 pre-tax profit margin guidance actual results",
        "TJX Companies Q4 fiscal 2025 earnings release pre-tax margin",
    ]
    assert "regulatory_filing" in preferred
    assert "earnings_release" in preferred
    assert "company_ir" in preferred
    assert preferred.count("regulatory_filing") == 1


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
    assert any("Seagen SEC companyfacts annual revenue 10-K" in query for query in payload["queries"])


def test_finance_ev_revenue_retrieval_augmentation_adds_target_companyfacts_coverage() -> None:
    goal = (
        "For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple "
        "using public deal disclosures and filing evidence."
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )

    payload = _augment_finance_modeling_retrieval_payload(
        {
            "query": "Pfizer Seagen acquisition enterprise value deal terms",
            "queries": ["Seagen 2022 annual revenue 10-K"],
            "metadata": {},
        },
        root_goal=goal,
        recipe=recipe,
    )

    assert payload["query"] == "Pfizer Seagen acquisition enterprise value deal terms"
    assert any("Seagen SEC companyfacts annual revenue 10-K" in query for query in payload["queries"])
    assert any("SEC companyfacts" in query for query in payload["queries"])
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json" in payload["source_urls"]
    assert payload["metadata"]["target_revenue_structured_source_required"] is True
    assert payload["max_fetches"] >= 18


def test_finance_dio_retrieval_augmentation_adds_inventory_and_cogs_companyfacts_coverage() -> None:
    goal = "For NYSE: HD and NYSE: LOW, calculate FY2024 days inventory outstanding (DIO)."
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )

    payload = _augment_finance_modeling_retrieval_payload(
        {
            "query": "HD LOW FY2024 DIO inventory",
            "queries": ["HD LOW FY2024 inventory"],
            "metadata": {},
        },
        root_goal=goal,
        recipe=recipe,
    )

    joined_queries = " ".join(payload["queries"])
    assert payload["query"] == "HD LOW FY2024 DIO inventory"
    assert "cost of revenue" in joined_queries.lower()
    assert "HD SEC companyfacts inventory cost of revenue cost of sales COGS 10-K" in joined_queries
    assert "LOW SEC companyfacts inventory cost of revenue cost of sales COGS 10-K" in joined_queries
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000354950.json" in payload["source_urls"]
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000060667.json" in payload["source_urls"]
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000354950/us-gaap/InventoryNet.json" in payload["source_urls"]
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000060667/us-gaap/CostOfGoodsAndServicesSold.json" in payload["source_urls"]
    assert payload["metadata"]["target_inventory_and_cogs_structured_source_required"] is True


def test_finance_missing_fact_payload_for_capital_intensity_seeds_companyfacts() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="capital_intensity",
        missing=["capital_expenditures", "operating_cash_flow", "property_plant_and_equipment_net", "assets", "net_income"],
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
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Revenues.json" in source_urls
    assert (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment.json"
        in source_urls
    )
    assert (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/NetCashProvidedByUsedInOperatingActivities.json"
        in source_urls
    )
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/PropertyPlantAndEquipmentNet.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Assets.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/NetIncomeLoss.json" in source_urls
    assert source_urls.index("https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Assets.json") < source_urls.index(
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json"
    )
    assert source_urls.index("https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/NetIncomeLoss.json") < source_urls.index(
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/SalesRevenueNet.json"
    )
    assert payload["source_urls"] == source_urls
    assert any("net income" in query.lower() for query in payload["queries"])
    assert payload["metadata"]["missing_slots"] == [
        "capital_expenditures",
        "operating_cash_flow",
        "property_plant_and_equipment_net",
        "assets",
        "net_income",
    ]


def test_finance_modeling_payload_uses_model_compiled_capital_intensity_program_for_source_urls() -> None:
    goal = (
        "Benchmark target source follows. Source URL: "
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf Company: 3M Document: 3M_2022_10K Document type: 10k "
        "Document period: 2022 Is 3M a capital-intensive business based on FY2022 data?"
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "execution_program": {
                "schema": "holo.kernel_v3.compiled_task_program.v1",
                "source": "task_compile_model",
                "task_spec": {
                    "task_type": "compute",
                    "objective": "Assess FY2022 capital intensity from filing facts.",
                    "diagnostics": {"formula_name": "capital_intensity"},
                },
                "evidence_specs": [],
                "transform_specs": [
                    {
                        "name": "capital_intensity_capex_revenue",
                        "required_slots": ["capital_expenditures", "revenue"],
                    }
                ],
                "slot_frame": {"missing_slots": ["capital_expenditures", "revenue", "assets", "net_income"]},
            },
        },
    )

    payload = _augment_finance_modeling_retrieval_payload(
        {"query": "model selected first retrieval query", "queries": ["model selected first retrieval query"], "metadata": {}},
        root_goal=goal,
        recipe=recipe,
    )

    assert payload["query"] == "model selected first retrieval query"
    assert "model selected first retrieval query" in payload["queries"]
    assert any("capital expenditures" in query.lower() and "net income" in query.lower() for query in payload["queries"])
    source_urls = payload["metadata"]["source_urls"]
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Revenues.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Assets.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/NetIncomeLoss.json" in source_urls
    assert payload["metadata"]["target_capital_intensity_structured_source_required"] is True
    assert payload["max_fetches"] >= 20


def test_benchmark_binding_enforce_adds_capital_intensity_structured_sources_from_compiled_hint() -> None:
    goal = (
        "Benchmark target source follows. Source URL: "
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf Company: 3M Document: 3M_2022_10K Document type: 10k "
        "Document period: 2022 Is 3M a capital-intensive business based on FY2022 data?"
    )
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "goal": goal,
            "execution_program": {
                "schema": "holo.kernel_v3.compiled_task_program.v1",
                "source": "task_compile_model",
                "task_spec": {
                    "task_type": "compute",
                    "objective": "Assess FY2022 capital intensity.",
                    "diagnostics": {"formula_name": "capital_intensity"},
                },
                "evidence_specs": [],
                "transform_specs": [{"name": "capital_intensity_ppe_assets", "required_slots": ["property_plant_and_equipment_net", "assets"]}],
                "slot_frame": {"missing_slots": ["property_plant_and_equipment_net", "assets", "net_income"]},
            },
        },
    )

    payload = _enforce_benchmark_doc_retrieval_binding(
        {"query": "model query", "metadata": {}},
        goal=goal,
        recipe=recipe,
        preserve_query=True,
    )

    source_urls = payload["metadata"]["source_urls"]
    assert payload["max_fetches"] >= 20
    assert payload["source_urls"] == source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/Assets.json" in source_urls
    assert "https://data.sec.gov/api/xbrl/companyconcept/CIK0000066740/us-gaap/NetIncomeLoss.json" in source_urls
    assert payload["metadata"]["target_capital_intensity_structured_source_required"] is True


def test_finance_missing_fact_payload_for_fixed_asset_turnover_seeds_companyfacts() -> None:
    payload = _finance_missing_fact_retrieval_payload(
        formula_name="fixed_asset_turnover",
        missing=[
            "revenue",
            "property_plant_and_equipment_net_current",
            "property_plant_and_equipment_net_prior",
        ],
        goal=(
            "Benchmark target source follows. Source URL: "
            "https://investor.activision.com/static-files/32abe798-add2-4770-9c7d-4cd3a840ede2 "
            "Company: Activision Blizzard Document: ACTIVISIONBLIZZARD_2019_10K Document type: 10k "
            "Document period: 2019 What is the FY2019 fixed asset turnover ratio for Activision Blizzard?"
        ),
    )

    assert payload["metadata"]["missing_slots"] == [
        "revenue",
        "property_plant_and_equipment_net_current",
        "property_plant_and_equipment_net_prior",
    ]
    assert "PropertyPlantAndEquipmentNet" in payload["query"]
    assert "fixed asset turnover" in payload["query"]
    assert payload["metadata"]["preferred_source_families"][0] == "structured_regulatory_data"


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


def test_finance_capability_evaluator_treats_empty_workbench_followup_as_advisory() -> None:
    profile = execution_profile("finance-capability")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "goal": "For KHC, explain the adjusted EBITDA bridge from public filings.",
            "execution_metadata": execution_profile_runtime_metadata(profile),
        },
    )
    evaluator = _RecipeEvaluator(recipe, journal=JournalStore.in_memory())
    context = ContextBundle(
        context_id="ctx-capability-workbench-report",
        thread_key="thread-1",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-capability-workbench-report", "run_id": "run-1"},
        token_budget=4096,
    )
    observation = Observation(
        observation_id="obs-capability-workbench-report",
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
                        "missing_slots": ["base_metric", "adjusted_metric"],
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

    assert feedback.status == "final_answer_ready"
    assert "retrieval_workbench_followup" not in feedback.missing_evidence


def test_finance_capability_evaluator_does_not_block_on_planned_action_count() -> None:
    profile = execution_profile("finance-capability")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "planned_action_count": 2,
            "execution_metadata": execution_profile_runtime_metadata(profile),
        },
    )
    evaluator = _RecipeEvaluator(recipe, journal=JournalStore.in_memory())
    context = ContextBundle(
        context_id="ctx-capability-planned-count",
        thread_key="thread-1",
        event_ids=[],
        memory_refs=[],
        state={"task_id": "task-capability-planned-count", "run_id": "run-1"},
        token_budget=4096,
    )
    observation = Observation(
        observation_id="obs-capability-planned-count",
        run_id="run-1",
        kind="tool_result",
        status="ok",
        source="tool:retrieval.run",
        content={"report": {"status": "sufficient", "diagnostics": {}}},
        observed_at_ms=1,
        action_id="act-1",
        tool_call_id="tool-1",
    )

    feedback = evaluator.evaluate(context, observation)

    assert feedback.status == "final_answer_ready"
    assert "remaining_plan_actions" not in feedback.missing_evidence


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


def test_finance_formula_planner_prefers_acquired_target_revenue_for_ev_revenue() -> None:
    facts = [
        FinanceFact(
            fact_id="pfe-seagen-transaction-value",
            entity="Pfizer Inc.",
            ticker="PFE",
            period=None,
            fiscal_year=None,
            metric="transaction value",
            value="44234000000",
            unit="USD",
            scale="actual",
            source_ref="cite-deal",
            evidence_ref="ev-deal",
            citation_ref="cite-deal",
            metadata={"context": "Pfizer acquisition of Seagen total consideration transferred"},
        ),
        _year_fact(
            "revenue",
            "58496000000",
            2023,
            fact_id="pfe-revenue",
            metadata={"source_title": "Pfizer 2023 Form 10-K", "context": "Pfizer total revenues"},
        ),
        _year_fact(
            "revenue",
            "1962412000",
            2022,
            fact_id="seagen-revenue",
            metadata={
                "source_title": "SEC companyfacts JSON for CIK 0001060736",
                "source_uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json",
                "context": "SEC companyfacts annual financial summary entityName=Seagen Inc.",
            },
        ),
    ]

    plan = plan_finance_formula(
        question="For Pfizer's acquisition of Seagen, calculate the transaction EV / revenue multiple.",
        facts=facts,
    )

    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["variables"]["equity_value"] == "44234000000"
    assert plan.payload["variables"]["revenue"] == "1962412000"
    assert plan.input_fact_ids == ["pfe-seagen-transaction-value", "seagen-revenue"]


def test_retrieval_extraction_grounding_promotes_sec_companyfacts_spans() -> None:
    journal = JournalStore.in_memory()
    recipe = task_recipe(
        "retrieval_answer",
        metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )
    report = _retrieval_report(evidence=[], citations=[], status="insufficient_evidence")
    journal.append(
        task_id="task-extraction-grounding",
        run_id="run-extraction-grounding",
        step_id="step-report",
        kind="retrieval_report",
        data=report.to_dict(),
    )
    text = (
        "SEC companyfacts annual financial summary entityName=Seagen Inc. cik=1060736 "
        "fy=2022 period=annual form=10-K filed=2023-02-15 end=2022-12-31 "
        "facts=metric=revenue concept=RevenueFromContractWithCustomerExcludingAssessedTax "
        "period_fy=2022 value=1962412000 val=1962412000 unit=USD fy=2022 fp=FY "
        "form=10-K filed=2023-02-15 start=2022-01-01 end=2022-12-31 frame=CY2022"
    )
    journal.append(
        task_id="task-extraction-grounding",
        run_id="run-extraction-grounding",
        step_id="step-extraction",
        kind="retrieval_extraction",
        data={
            "goal_id": "goal-agent-retrieval",
            "document": {
                "document_id": "doc-sgen-companyfacts",
                "source_id": "src-sgen-companyfacts",
                "artifact_id": "artifact-sgen-companyfacts",
                "uri": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001060736.json",
                "title": "SEC companyfacts JSON for CIK 0001060736",
                "payload_hash": "hash-sgen-companyfacts",
            },
            "spans": [
                {
                    "span_id": "span-sgen-2022-revenue",
                    "text": text,
                    "score": 0.91,
                    "metadata": {"text_mode": "sec_companyfacts_readable_text", "target_line_item": "revenue"},
                }
            ],
        },
    )

    evidence, citations, updated_report = _retrieval_and_toolchain_grounding(
        journal,
        "task-extraction-grounding",
        "run-extraction-grounding",
        recipe=recipe,
    )
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert updated_report is not None
    assert updated_report.status == "sufficient"
    assert updated_report.diagnostics["retrieval_extraction_grounding"]["evidence_count"] == 1
    assert evidence[0].evidence_id == "evidence-span-sgen-2022-revenue"
    assert citations[0].evidence_id == "evidence-span-sgen-2022-revenue"
    assert any(fact.entity == "Seagen Inc." and fact.metric == "revenue" and fact.value == "1962412000" for fact in facts)


def test_html_table_fact_lines_feed_adjusted_ebitda_bridge_planner() -> None:
    text = (
        "The Kraft Heinz Company Reconciliation of Net Income/(Loss) to Adjusted EBITDA "
        "(in millions) (Unaudited) scale=millions "
        "html_table_fact_34_2_2022: metric=Net income/(loss) fy=2022 value=2,368 scale=millions "
        "html_table_fact_34_3_2022: metric=Interest expense fy=2022 value=921 scale=millions "
        "html_table_fact_34_4_2022: metric=Other expense/(income) fy=2022 value=(253) scale=millions "
        "html_table_fact_34_5_2022: metric=Provision for/(benefit from) income taxes fy=2022 value=598 scale=millions "
        "html_table_fact_34_7_2022: metric=Depreciation and amortization (excluding restructuring activities) fy=2022 value=922 scale=millions "
        "html_table_fact_34_8_2022: metric=Divestiture-related license income fy=2022 value=(56) scale=millions "
        "html_table_fact_34_9_2022: metric=Restructuring activities fy=2022 value=74 scale=millions "
        "html_table_fact_34_10_2022: metric=Deal costs fy=2022 value=9 scale=millions "
        "html_table_fact_34_11_2022: metric=Unrealized losses/(gains) on commodity hedges fy=2022 value=63 scale=millions "
        "html_table_fact_34_12_2022: metric=Impairment losses fy=2022 value=999 scale=millions "
        "html_table_fact_34_13_2022: metric=Certain non-ordinary course legal and regulatory matters fy=2022 value=210 scale=millions "
        "html_table_fact_34_14_2022: metric=Equity award compensation expense fy=2022 value=148 scale=millions "
        "html_table_fact_34_15_2022: metric=Adjusted EBITDA fy=2022 value=6,003 scale=millions"
    )
    evidence = [
        _finance_evidence(
            evidence_id="khc-bridge-table",
            title="KHC 10-K adjusted EBITDA reconciliation",
            uri="https://www.sec.gov/Archives/edgar/data/1637459/example/khc-10k.htm",
            text=text,
        )
    ]
    facts = build_finance_fact_ledger(
        evidence=evidence,
        citations=[_finance_citation(evidence[0], citation_id="cite-khc-bridge")],
    )

    plan = plan_finance_formula(
        question="For KHC, explain the adjusted EBITDA bridge and subtotal.",
        facts=facts,
    )

    assert any(fact.metric == "adjusted ebitda" and fact.value == "6003000000" for fact in facts)
    assert plan.status == "ready"
    assert plan.payload is not None
    assert plan.payload["formula_name"] == "bridge_subtotal"
    assert plan.payload["variables"]["reported_adjusted"] == "6003000000"


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


def test_numeric_verifier_ignores_complex_citation_identifier_digits() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-growth",
            formula_name="yoy_growth",
            expression="current_value / prior_value - 1",
            input_fact_ids=["current", "prior"],
            result_value="67.458",
            unit="percent",
            diagnostics={"formatted_value": "6745.8%"},
        )
    ]

    verification = verify_finance_answer(
        answer=(
            "该计算结果为 6745.8%，证据见 "
            "[cite-evidence-span-doc-goal-agent-retrieval-8-1]。"
        ),
        facts=[],
        formula_traces=traces,
        question="What is the year-over-year growth?",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []


def test_numeric_verifier_ignores_inline_formula_literal_numbers() -> None:
    traces = [
        FormulaTrace(
            formula_id="formula-growth",
            formula_name="yoy_growth",
            expression="current_value / prior_value - 1",
            input_fact_ids=["current", "prior"],
            result_value="67.458",
            unit="percent",
            diagnostics={"formatted_value": "6745.8%"},
        )
    ]

    verification = verify_finance_answer(
        answer="yoy_growth: 6745.8%，公式 `current_value / prior_value - 1`。",
        facts=[],
        formula_traces=traces,
        question="What is the year-over-year growth?",
    )

    assert verification.status == "passed"
    assert verification.missing_values == []


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
        "net_income",
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
        metadata={
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "host_semantic_fallbacks": {"enabled": True},
        },
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


def test_finance_capability_model_compiled_transform_authorizes_calculator_preflight() -> None:
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {
                            "task_type": "compute",
                            "objective": "Calculate FY2024 DIO in days.",
                            "target_entities": ["Retailer"],
                            "target_periods": ["FY2024"],
                            "success_criteria": ["calculator trace supports DIO"],
                        },
                        "evidence_specs": [
                            {"slot_name": "inventory_begin", "accepted_attributes": ["inventory"], "required": True},
                            {"slot_name": "inventory_end", "accepted_attributes": ["inventory"], "required": True},
                            {"slot_name": "cogs", "accepted_attributes": ["cost of sales"], "required": True},
                        ],
                        "transform_specs": [
                            {
                                "name": "dio",
                                "required_slots": ["inventory_begin", "inventory_end", "cogs", "fiscal_days"],
                                "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
                                "output_unit": "days",
                                "output_attribute": "dio",
                            }
                        ],
                        "slot_frame": {
                            "task_type": "compute",
                            "required_slots": [
                                {"name": "inventory_begin"},
                                {"name": "inventory_end"},
                                {"name": "cogs"},
                                {"name": "fiscal_days"},
                            ],
                            "missing_slots": [],
                        },
                        "tool_chain_plan": {
                            "decision_owner": "model",
                            "recommended_steps": [{"tool": "calculator.compute", "reason": "supported numeric transform"}],
                        },
                    },
                    "finance.slot_bind": {
                        "decision": "ready",
                        "slot_bindings": [
                            {"slot_name": "inventory_begin", "variable_name": "inventory_begin", "fact_id": "finfact-4254638f637a"},
                            {"slot_name": "inventory_end", "variable_name": "inventory_end", "fact_id": "finfact-9a157996131a"},
                            {"slot_name": "cogs", "variable_name": "cogs", "fact_id": "finfact-844cae959a62"},
                        ],
                        "calculations": [
                            {
                                "formula_name": "average_inventory",
                                "expression": "(inventory_begin + inventory_end) / 2",
                                "variables": {
                                    "inventory_begin": {"fact_id": "finfact-4254638f637a"},
                                    "inventory_end": {"fact_id": "finfact-9a157996131a"},
                                },
                                "unit": "USD",
                            },
                            {
                                "formula_name": "dio",
                                "expression": "average_inventory / cogs * fiscal_days",
                                "variables": {
                                    "average_inventory": "average_inventory",
                                    "cogs": {"fact_id": "finfact-844cae959a62"},
                                    "fiscal_days": 365,
                                },
                                "unit": "days",
                            }
                        ],
                        "missing_slots": [],
                        "next_action": "respond",
                        "reason_summary": "Model bound all calculator variables to observed facts.",
                    },
                    "synthesizer.answer": {
                        "answer": "Retailer FY2024 DIO is 80.3 days, supported by cite-1, cite-2, and cite-3.",
                        "citation_refs": ["cite-1", "cite-2", "cite-3"],
                        "confidence": 0.9,
                        "limitations": [],
                        "used_evidence": ["evidence-1", "evidence-2", "evidence-3"],
                    },
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric)
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
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-capability")),
        },
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance-capability-dio",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    preflight = journal.records(task_id="task-finance-capability-dio", kind="finance_numeric_preflight")
    assert any(record.data["status"] == "model_authorized" for record in preflight)
    compactions = journal.records(task_id="task-finance-capability-dio", kind="finance_synthesis_compaction")
    assert compactions
    assert compactions[-1].data["compact_evidence_count"] <= compactions[-1].data["original_evidence_count"]
    observations = journal.records(task_id="task-finance-capability-dio", kind="observation")
    assert any(record.data.get("source") == f"tool:{CALCULATOR_TOOL_NAME}" for record in observations)
    trace = observations[-1].data["content"]["formula_trace"]
    assert trace["formula_name"] == "dio"
    assert set(trace["input_fact_ids"]) == {
        "finfact-4254638f637a",
        "finfact-9a157996131a",
        "finfact-844cae959a62",
    }
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
        metadata={
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "host_semantic_fallbacks": {"enabled": True},
        },
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
    assert synthesis_gates[0].data["status"] == "failed"
    assert synthesis_gates[-1].data["status"] == "passed"
    assert any(
        record.data["diagnostics"].get("gate_id") == "llm_semantic_numeric_judge_unavailable_v1"
        for record in synthesis_gates
    )
    assert synthesis_gates[-1].data["policy"] == "material_numeric_claims_require_claim_or_transform_support"
    assert synthesis_gates[-1].data["diagnostics"]["attempt"] == "fallback"


def test_finance_capability_blocks_host_fallback_when_llm_numeric_judge_unavailable() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer="Apple 2024 revenue was $999 billion, supported by cite-1.",
    )
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-capability"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance-capability-strict",
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
    assert "llm_numeric_judge_unavailable" in " ".join(failure.missing_evidence)
    assert not journal.records(task_id="task-finance-capability-strict", kind="agent_final_answer")
    synthesis_gates = journal.records(task_id="task-finance-capability-strict", kind="synthesis_gate_result")
    assert synthesis_gates
    assert all(record.data["status"] == "failed" for record in synthesis_gates)
    assert any(
        record.data["diagnostics"].get("gate_id") == "llm_semantic_numeric_judge_unavailable_v1"
        for record in synthesis_gates
    )


def test_finance_capability_does_not_rewrite_semantic_clarification() -> None:
    intake = SemanticIntake(
        intake_id="intake-khc-clarify",
        goal=(
            "For KHC, use public filings to explain the adjusted EBITDA bridge for the requested period."
        ),
        primary_intent="financial_research",
        suggested_mode="clarify_first",
        compound=False,
        requires_clarification=True,
        intents=[
            {
                "kind": "financial_research",
                "text": "Research KHC adjusted EBITDA bridge from public filings.",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run", "finance.fundamentals_research"],
                "risk": "none",
                "status": "needs_user_input",
                "metadata": {"domain": "finance_fundamentals", "resource": "public_filings"},
            }
        ],
        blocked_capabilities=[],
        warnings=[],
        response_hint=None,
        clarification_question="Which period?",
    )

    updated = _finance_capability_execute_clarification_as_retrieval(
        intake,
        execution_metadata=execution_profile_runtime_metadata(execution_profile("finance-capability")),
    )

    assert updated == intake


def test_finance_numeric_verifier_failure_uses_llm_judge_before_failure() -> None:
    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={
            "fake_json": FakeJsonProvider(
                {
                    "task.compile": {
                        "task_spec": {"task_type": "lookup", "objective": "Apple revenue"},
                        "evidence_specs": [
                            {
                                "slot_name": "revenue",
                                "accepted_attributes": ["revenue"],
                                "source_role": "primary_filing",
                                "required": True,
                            }
                        ],
                        "transform_specs": [],
                        "slot_frame": {"task_type": "lookup", "required_slots": [{"name": "revenue"}], "missing_slots": []},
                    },
                    "synthesizer.answer": [
                        {
                            "answer": "Apple 2024 revenue was $999 billion, supported by cite-1.",
                            "citation_refs": ["cite-1"],
                            "confidence": 0.7,
                            "limitations": [],
                            "used_evidence": ["evidence-1"],
                        },
                        {
                            "answer": "Apple 2024 revenue was $391.035 billion, supported by cite-1.",
                            "citation_refs": ["cite-1"],
                            "confidence": 0.9,
                            "limitations": [],
                            "used_evidence": ["evidence-1"],
                        },
                    ],
                    "finance.numeric_judge": {
                        "decision": "repair_answer",
                        "reason_summary": "The answer addresses the question but the core revenue number should be repaired from the ledger.",
                        "answer_addresses_question": True,
                        "core_numeric_claims": ["$999 billion revenue"],
                        "non_core_numeric_claims": [],
                        "unsupported_core_values": ["$999 billion"],
                        "candidate_supported_values": ["$391.035 billion"],
                        "missing_slots": [],
                        "repair_instruction": "Replace $999 billion with the supported revenue value $391.035 billion and keep cite-1.",
                        "requires_more_work": False,
                        "confidence": 0.95,
                    },
                }
            )
        },
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric)
    evidence, citations = _sec_revenue_evidence(value="391035000000")
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast"))},
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-finance-llm-judge",
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
    assert "$391.035 billion" in final.answer
    assert journal.records(task_id="task-finance-llm-judge", kind="finance_numeric_judge")
    synthesis_gates = journal.records(task_id="task-finance-llm-judge", kind="synthesis_gate_result")
    assert synthesis_gates[-1].data["status"] == "passed"
    assert synthesis_gates[-1].data["diagnostics"]["source"] == "finance_numeric_judge"


def test_retrieval_fallback_prefers_fact_ledger_and_suppresses_accession_numbers() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(
        journal,
        answer=(
            "The filing accession 0001558370-19-000470 shows capital expenditures were $9.1 billion, "
            "supported by cite-mmm."
        ),
        citation_refs=["cite-mmm"],
        used_evidence=["evidence-mmm-capex"],
    )
    evidence = [
        _finance_evidence(
            evidence_id="evidence-mmm-capex",
            title="3M 2018 10-K",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm",
            text=(
                "entityName=3M Company ticker=MMM concept=PaymentsToAcquirePropertyPlantAndEquipment "
                "metric=capital expenditures label=Payments to Acquire Property, Plant, and Equipment "
                "unit=USD scale=millions fy=2018 form=10-K filed=2019-02-07 "
                "accn=0001558370-19-000470 value=(1,577)"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-mmm")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "host_semantic_fallbacks": {"enabled": True},
            "goal": "What was 3M's FY2018 capital expenditures in USD millions?",
        },
    )

    final, failure = runtime._synthesize_retrieval_final(  # noqa: SLF001
        "task-mmm-capex",
        "run-1",
        recipe=recipe,
        report=_retrieval_report(evidence=evidence, citations=citations),
        evidence=evidence,
        citations=citations,
        synthesizer_mode="model",
    )

    assert failure is None
    assert final is not None
    assert "$9.1 billion" not in final.answer
    assert "000470" not in final.answer
    assert "1577" in final.answer
    assert "已由证据账本支持的关键数值" in final.answer
    assert final.citation_refs == ["cite-mmm"]
    synthesis_gates = journal.records(task_id="task-mmm-capex", kind="synthesis_gate_result")
    assert synthesis_gates[0].data["status"] == "failed"
    assert synthesis_gates[-1].data["status"] == "passed"
    assert any(
        record.data["diagnostics"].get("gate_id") == "llm_semantic_numeric_judge_unavailable_v1"
        for record in synthesis_gates
    )


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


def test_finance_capability_partial_retrieval_synthesis_is_llm_first() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-margin",
            title="3M 2022 10-K MD&A",
            uri="https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/mmm-20221231.htm",
            text="Management says operating margin declined due to litigation, PFAS exit costs, raw materials and logistics costs.",
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-margin")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={"execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-capability"))},
    )

    assert _can_synthesize_partial_retrieval(
        terminal_reason=None,
        evidence=evidence,
        citations=citations,
        recipe=recipe,
    )


def test_finance_numeric_judge_semantic_pass_accepts_core_answer() -> None:
    assert _finance_numeric_judge_accepts_answer(
        {
            "decision": "passed_semantically",
            "answer_addresses_question": True,
            "requires_more_work": False,
            "core_numeric_claims": ["supported revenue value"],
            "non_core_numeric_claims": ["incidental document number"],
            "unsupported_core_values": [],
        }
    )
    assert not _finance_numeric_judge_accepts_answer(
        {
            "decision": "repair_answer",
            "answer_addresses_question": True,
            "requires_more_work": False,
            "core_numeric_claims": ["supported filing table values"],
            "unsupported_core_values": [],
        }
    )
    assert not _finance_numeric_judge_accepts_answer(
        {
            "decision": "passed_semantically",
            "answer_addresses_question": True,
            "requires_more_work": False,
            "unsupported_core_values": ["unsupported revenue value"],
        }
    )


def test_finance_numeric_judge_prompt_compacts_dynamic_context_for_cache() -> None:
    question = "What was Apple FY2024 revenue?"
    answer_text = "Apple FY2024 revenue was $999 billion. " + ("unsupported detail " * 700)
    evidence = [
        _finance_evidence(
            evidence_id=f"evidence-{index}",
            title=f"Apple filing row {index}",
            uri=f"https://www.sec.gov/example/{index}",
            text=(
                "entityName=Apple ticker=AAPL metric=revenue unit=USD fy=2024 form=10-K "
                "value=391035000000 " + ("long extracted filing text " * 80)
            ),
        )
        for index in range(50)
    ]
    citations = [_finance_citation(item, citation_id=f"cite-{index}") for index, item in enumerate(evidence)]
    facts = [
        FinanceFact(
            fact_id=f"fact-{index}",
            entity="Apple Inc.",
            ticker="AAPL",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="391035000000",
            unit="USD",
            scale="actual",
            source_ref=f"source-{index}",
            evidence_ref=f"evidence-{index % len(evidence)}",
            citation_ref=f"cite-{index % len(citations)}",
            metadata={
                "form": "10-K",
                "concept": "Revenues",
                "label": "Revenue " + ("x" * 400),
                "finance_metric_intent": {"score": 0.97, "matched_terms": ["revenue"]},
            },
        )
        for index in range(90)
    ]
    verification = verify_finance_answer(
        answer=answer_text,
        facts=facts,
        citations=citations,
        evidence=evidence,
        question=question,
    )
    final = FinalAnswer(
        answer=answer_text,
        citation_refs=["cite-0"],
        used_evidence=["evidence-0"],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-cache",
        run_id="run-judge-cache",
        trace_refs=[],
    )

    report = replace(
        _retrieval_report(evidence=evidence, citations=citations),
        diagnostics={
            "finance_slot_bind_state": {
                "decision": "ready",
                "period_basis": [{"slot_name": "revenue", "fact_id": "fact-0", "selected_period": "FY2024"}],
                "line_item_basis": [{"slot_name": "revenue", "fact_id": "fact-0", "selected_line_item": "Revenue"}],
            }
        },
    )

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=report,
        facts=facts,
        formula_traces=[],
        evidence=evidence,
        citations=citations,
        attempt="initial",
    )
    payload = json.loads(prompt)
    packet = payload["judge_packet"]

    assert prompt.index('"contract"') < prompt.index('"judge_packet"')
    assert len(prompt) < 55000
    assert packet["answer"]["truncated"] is True
    assert packet["answer"]["text_chars"] == len(answer_text)
    assert len(packet["answer"]["text"]) <= 6003
    assert len(packet["finance_facts"]) == 48
    assert len(packet["evidence"]) == 16
    assert len(packet["citations"]) == 16
    assert packet["finance_fact_count"] == len(facts)
    assert "finance_metric_intent" not in packet["finance_facts"][0]["metadata"]
    assert packet["finance_slot_bind_state"]["period_basis"][0]["selected_period"] == "FY2024"
    assert packet["finance_slot_bind_state"]["line_item_basis"][0]["selected_line_item"] == "Revenue"


def test_finance_numeric_judge_prompt_exposes_competing_fact_clusters() -> None:
    question = "What was Chevron's total revenues for fiscal year 2024?"
    facts = [
        FinanceFact(
            fact_id="generic-revenues",
            entity="Chevron Corp",
            ticker="CVX",
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="202792000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-total-revenues",
            citation_ref="cite-total-revenues",
            metadata={"concept": "Revenues", "label": "Revenues", "form": "10-K", "fp": "FY"},
        ),
        FinanceFact(
            fact_id="sales-other-operating",
            entity="Chevron Corp",
            ticker="CVX",
            period="annual",
            fiscal_year=2024,
            metric="sales and other operating revenues",
            value="193414000000",
            unit="USD",
            scale=None,
            source_ref="sec-filing",
            evidence_ref="evidence-sales-revenues",
            citation_ref="cite-sales-revenues",
            metadata={
                "concept": "SalesAndOtherOperatingRevenue",
                "label": "Sales and Other Operating Revenues",
                "form": "10-K",
                "fp": "FY",
            },
        ),
    ]
    final = FinalAnswer(
        answer="Chevron FY2024 total revenues were $202.792 billion.",
        citation_refs=["cite-total-revenues"],
        used_evidence=["evidence-total-revenues"],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-clusters",
        run_id="run-judge-clusters",
        trace_refs=[],
    )
    verification = verify_finance_answer(answer=final.answer, facts=facts, question=question)

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=_retrieval_report(evidence=[], citations=[]),
        facts=facts,
        formula_traces=[],
        evidence=[],
        citations=[],
        attempt="initial",
    )
    packet = json.loads(prompt)["judge_packet"]
    clusters = packet["competing_fact_clusters"]

    assert clusters
    assert packet["competing_fact_cluster_policy"]["semantic_decision_owner"] == "model"
    assert clusters[0]["host_role"] == "attention_grouping_only_no_semantic_preference"
    assert clusters[0]["candidate_ordering"] == "source_order_from_raw_facts"
    assert [item["fact_id"] for item in clusters[0]["candidates"]] == ["generic-revenues", "sales-other-operating"]
    assert [item["value"] for item in clusters[0]["candidates"]] == ["202792000000", "193414000000"]


def test_finance_numeric_judge_prompt_exposes_metric_intent_hints_without_polluting_facts() -> None:
    question = "What was Chevron's total revenues for fiscal year 2024?"
    facts = [
        FinanceFact(
            fact_id="generic-revenues",
            entity="Chevron Corp",
            ticker="CVX",
            period="annual",
            fiscal_year=2024,
            metric="revenue",
            value="202792000000",
            unit="USD",
            scale=None,
            source_ref="sec-companyfacts",
            evidence_ref="evidence-total-revenues",
            citation_ref="cite-total-revenues",
            metadata={
                "concept": "Revenues",
                "label": "Revenues",
                "form": "10-K",
                "fp": "FY",
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 2.5,
                    "matched_preferred": ["metric=revenue"],
                    "matched_demoted": [],
                },
            },
        ),
        FinanceFact(
            fact_id="sales-other-operating",
            entity="Chevron Corp",
            ticker="CVX",
            period="annual",
            fiscal_year=2024,
            metric="sales and other operating revenues",
            value="193414000000",
            unit="USD",
            scale=None,
            source_ref="sec-filing",
            evidence_ref="evidence-sales-revenues",
            citation_ref="cite-sales-revenues",
            metadata={
                "concept": "SalesAndOtherOperatingRevenue",
                "label": "Sales and Other Operating Revenues",
                "form": "10-K",
                "fp": "FY",
                "target_line_item": "total revenues",
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 13.5,
                    "matched_preferred": ["metric=sales and other operating revenues"],
                    "matched_demoted": [],
                },
            },
        ),
    ]
    final = FinalAnswer(
        answer="Chevron FY2024 total revenues were $202.792 billion.",
        citation_refs=["cite-total-revenues"],
        used_evidence=["evidence-total-revenues"],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-intent",
        run_id="run-judge-intent",
        trace_refs=[],
    )
    verification = verify_finance_answer(answer=final.answer, facts=facts, question=question)

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=_retrieval_report(evidence=[], citations=[]),
        facts=facts,
        formula_traces=[],
        evidence=[],
        citations=[],
        attempt="initial",
    )
    payload = json.loads(prompt)
    packet = payload["judge_packet"]

    assert "metric_intent_hints" in payload["contract"]
    assert packet["metric_intent_hint_policy"]["semantic_decision_owner"] == "model"
    assert packet["metric_intent_hint_policy"]["host_role"] == "weak_attention_hint_carrier_only"
    assert packet["metric_intent_hint_policy"]["candidate_ordering"] == "source_order_from_raw_facts"
    assert [item["fact_id"] for item in packet["metric_intent_hints"]] == ["generic-revenues", "sales-other-operating"]
    assert [item["value"] for item in packet["metric_intent_hints"]] == ["202792000000", "193414000000"]
    assert packet["metric_intent_hints"][1]["target_line_item"] == "total revenues"
    assert packet["metric_intent_hints"][1]["intent"]["matched_preferred"] == [
        "metric=sales and other operating revenues"
    ]
    assert "finance_metric_intent" not in packet["finance_facts"][0]["metadata"]
    assert "finance_metric_intent" not in packet["finance_facts"][1]["metadata"]


def test_finance_numeric_judge_prompt_exposes_unit_mismatch_examples() -> None:
    question = "What was Example Co FY2024 revenue?"
    facts = [
        FinanceFact(
            fact_id="fact-revenue",
            entity="Example Co",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="10",
            unit="USD",
            scale=None,
            source_ref="src-1",
            evidence_ref="ev-1",
            citation_ref="cite-1",
            metadata={},
        )
    ]
    final = FinalAnswer(
        answer="Example Co FY2024 revenue was 10%.",
        citation_refs=["cite-1"],
        used_evidence=["ev-1"],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-unit",
        run_id="run-judge-unit",
        trace_refs=[],
    )
    verification = verify_finance_answer(answer=final.answer, facts=facts, question=question)

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=_retrieval_report(evidence=[], citations=[]),
        facts=facts,
        formula_traces=[],
        evidence=[],
        citations=[],
        attempt="initial",
    )
    verifier = json.loads(prompt)["judge_packet"]["host_verifier_diagnostics"]

    assert verifier["status"] == "failed"
    assert verifier["unit_mismatches"][0]["value"]["raw"] == "10%"
    assert verifier["unit_mismatch_examples"] == [
        {
            "raw": "10%",
            "value": "10",
            "unit": "percent",
            "support_units": ["usd"],
            "support_kinds": ["finance_fact"],
            "support_refs": ["fact-revenue"],
        }
    ]
    assert "unit or scale wording" in " ".join(verifier["repair_options"])
    assert "model still owns semantic repair" in verifier["host_boundary"]


def test_finance_numeric_judge_prompt_exposes_primary_source_binding_diagnostics() -> None:
    question = "What was Example Co FY2024 revenue from the 2024 10-K?"
    binding = target_document_binding_from_metadata(
        {
            "company": "Example Co",
            "doc_link": "https://www.sec.gov/Archives/example/example-2024-10k.htm",
            "doc_period": "2024",
            "doc_type": "10-K",
            "required_statement": "income_statement",
            "required_line_item": "revenue",
            "primary_source_required": True,
        }
    )
    facts = [
        FinanceFact(
            fact_id="secondary-revenue",
            entity="Example Co",
            ticker="EXM",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="10",
            unit="USD",
            scale=None,
            source_ref="secondary",
            evidence_ref="ev-secondary",
            citation_ref="cite-secondary",
            metadata={
                "source_uri": "https://stockanalysis.com/stocks/exm/financials/",
                "source_title": "Example Co Financials - StockAnalysis",
                "context": "Revenue 10",
            },
        )
    ]
    final = FinalAnswer(
        answer="Example Co FY2024 revenue was $10.",
        citation_refs=["cite-secondary"],
        used_evidence=["ev-secondary"],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-binding",
        run_id="run-judge-binding",
        trace_refs=[],
    )
    verification = verify_finance_answer(
        answer=final.answer,
        facts=facts,
        question=question,
        target_binding=binding,
    )

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=_retrieval_report(evidence=[], citations=[]),
        facts=facts,
        formula_traces=[],
        evidence=[],
        citations=[],
        attempt="initial",
    )
    verifier = json.loads(prompt)["judge_packet"]["host_verifier_diagnostics"]

    assert verifier["status"] == "failed"
    assert "primary_source_numeric_binding_failed" in [item["code"] for item in verifier["issues"]]
    assert verifier["target_document_binding"]["required_line_item"] == "revenue"
    assert verifier["target_document_binding"]["doc_period"] == "2024"
    binding_state = verifier["primary_source_numeric_binding"]
    assert binding_state["status"] == "no_binding_match"
    assert binding_state["selected_fact_ids"] == []
    assert binding_state["rejected_count"] == 1
    assert binding_state["rejected_candidates"][0]["fact_id"] == "secondary-revenue"
    assert binding_state["rejected_candidates"][0]["source_uri"] == "https://stockanalysis.com/stocks/exm/financials/"
    assert binding_state["binding"]["doc_link"] == "https://www.sec.gov/Archives/example/example-2024-10k.htm"


def test_finance_numeric_judge_prompt_preserves_capital_intensity_roa_trace_context() -> None:
    question = "Is 3M a capital-intensive business based on FY2022 data?"
    answer_text = "3M does not appear capital-intensive: CapEx/revenue was 5.1%."
    facts = [
        _year_fact("net income", "4250000000", 2022, fact_id="finfact-net-income"),
        _year_fact("total assets", "34164000000", 2022, fact_id="finfact-assets"),
    ]
    trace = FormulaTrace(
        formula_id="formula-slot-roa",
        formula_name="capital_intensity_return_on_assets",
        expression="net_income / assets",
        input_fact_ids=["finfact-net-income", "finfact-assets"],
        result_value="0.1244",
        unit="percent",
        diagnostics={
            "source": "finance_slot_bind_model",
            "formatted_value": "12.44%",
            "method": "roa",
            "output_attribute": "return_on_assets",
        },
    )
    final = FinalAnswer(
        answer=answer_text,
        citation_refs=[],
        used_evidence=[],
        limitations=[],
        confidence=0.7,
        task_id="task-judge-roa",
        run_id="run-judge-roa",
        trace_refs=[],
    )
    verification = verify_finance_answer(
        answer=answer_text,
        facts=facts,
        formula_traces=[trace],
        question=question,
    )

    prompt = _finance_numeric_judge_prompt(
        question=question,
        answer=final,
        verification=verification,
        report=_retrieval_report(evidence=[], citations=[]),
        facts=facts,
        formula_traces=[trace],
        evidence=[],
        citations=[],
        attempt="initial",
    )
    packet = json.loads(prompt)["judge_packet"]

    assert packet["formula_trace_synthesis_policy"]["task_family"] == "capital_intensity_assessment"
    assert "return_on_assets" in packet["formula_trace_synthesis_policy"]["available_lenses"]
    assert "roa_preservation_instruction" in packet["formula_trace_synthesis_policy"]
    assert "generic industry thresholds" in packet["formula_trace_synthesis_policy"]["unsupported_comparison_number_policy"]
    assert packet["formula_traces"][0]["formatted_value"] == "12.44%"
    assert packet["formula_traces"][0]["diagnostics"]["output_attribute"] == "return_on_assets"
    support = packet["formula_trace_support"][0]
    assert support["formula_id"] == "formula-slot-roa"
    assert support["support_status"] == "linked_to_fact_ledger"
    assert support["citation_refs"] == ["cite-finfact-net-income", "cite-finfact-assets"]
    assert [item["fact_id"] for item in support["input_facts"]] == ["finfact-net-income", "finfact-assets"]


def test_finance_slot_bind_prompt_exposes_raw_fields_not_host_period_labels() -> None:
    facts = [
        FinanceFact(
            fact_id="fact-q",
            entity="Retailer",
            ticker="RTL",
            period="quarterly",
            fiscal_year=2024,
            metric="inventory",
            value="230",
            unit="USD",
            scale="actual",
            source_ref="source-q",
            evidence_ref="evidence-q",
            citation_ref="cite-q",
            metadata={
                "form": "10-Q",
                "fp": "Q2",
                "start": "2024-04-29",
                "end": "2024-07-28",
                "frame": "CY2024Q2I",
                "duration_days": 90,
                "concept": "InventoryNet",
                "context": "Condensed source row: inventory values appear in the quarterly balance sheet.",
                "line_item": "inventories",
                "raw": "Inventories, net 230",
                "raw_metric": "Inventories, net",
                "row_marker": "Inventories, net",
                "source": "html_table_fact",
                "statement": "balance_sheet",
                "target_document_binding_accepted": True,
                "target_document_binding_reasons": ["target_document_match", "target_period_match"],
                "target_document_binding_score": 130,
                "finance_metric_intent": {"score": 99},
                "finance_question_period_scope": "annual",
            },
        ),
        FinanceFact(
            fact_id="fact-a",
            entity="Retailer",
            ticker="RTL",
            period="annual",
            fiscal_year=2024,
            metric="inventory",
            value="500",
            unit="USD",
            scale="actual",
            source_ref="source-a",
            evidence_ref="evidence-a",
            citation_ref="cite-a",
            metadata={"form": "10-K", "fp": "FY", "duration_days": 365},
        ),
    ]
    prompt = _finance_slot_bind_prompt(
        question="Calculate FY2024 DIO.",
        facts=facts,
        compiled_program={
            "program_id": "program-1",
            "task_spec": {"task_type": "compare_compute", "objective": "Calculate DIO"},
            "evidence_specs": [
                {
                    "slot_name": "inventory_begin",
                    "line_item": "inventories",
                    "statement": "balance_sheet",
                    "target_period": "FY2023 ending balance",
                }
            ],
            "transform_specs": [
                {
                    "name": "dio",
                    "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
                    "required_slots": ["inventory_begin", "inventory_end", "cogs"],
                    "output_unit": "days",
                }
            ],
            "slot_frame": {"required_slots": [{"name": "inventory_begin"}, {"name": "inventory_end"}]},
        },
    )
    payload = json.loads(prompt)
    raw_fact = payload["slot_bind_packet"]["raw_facts"][0]

    assert prompt.index('"contract"') < prompt.index('"slot_bind_packet"')
    assert "metric, period, and scale labels as noisy hints" in payload["contract"]
    assert "finance_metric_intent_hints" in payload["contract"]
    assert "identity formula_request" in payload["contract"]
    assert "cash-flow outflows shown in parentheses" in payload["contract"]
    assert "Do not confuse cash-flow purchases" in payload["contract"]
    assert "requested financial statement" in payload["contract"]
    assert "directly states the requested metric and amount" in payload["contract"]
    assert "segment, regional, product-line, proxy" in payload["contract"]
    assert "page number, table-of-contents number" in payload["contract"]
    assert "target_document_binding_accepted=true" in payload["contract"]
    assert "later-filed restatement" in payload["contract"]
    assert "For revenue/net sales slots" in payload["contract"]
    assert "competing_fact_clusters" in payload["contract"]
    assert prompt.index('"raw_facts"') < prompt.index('"question"')
    assert prompt.index('"raw_facts"') < prompt.index('"compiled_program"')
    assert [item["fact_id"] for item in payload["slot_bind_packet"]["raw_facts"]] == ["fact-q", "fact-a"]
    clusters = payload["slot_bind_packet"]["competing_fact_clusters"]
    assert clusters
    cluster = clusters[0]
    assert cluster["metric_family_hint"] == "inventory"
    assert cluster["host_role"] == "attention_grouping_only_no_semantic_preference"
    assert cluster["candidate_ordering"] == "source_order_from_raw_facts"
    assert [item["fact_id"] for item in cluster["candidates"]] == ["fact-q", "fact-a"]
    assert cluster["candidates"][0]["raw_fields"]["form"] == "10-Q"
    assert cluster["candidates"][1]["raw_fields"]["form"] == "10-K"
    metric_hints = payload["slot_bind_packet"]["finance_metric_intent_hints"]
    assert payload["slot_bind_packet"]["finance_metric_intent_hint_policy"]["semantic_decision_owner"] == "model"
    assert payload["slot_bind_packet"]["finance_metric_intent_hint_policy"]["host_role"] == "weak_attention_hint_carrier_only"
    assert payload["slot_bind_packet"]["finance_metric_intent_hint_policy"]["candidate_ordering"] == "source_order_from_raw_facts"
    assert metric_hints[0]["fact_id"] == "fact-q"
    assert metric_hints[0]["intent"]["score"] == 99
    assert raw_fact["raw_fields"]["form"] == "10-Q"
    assert raw_fact["raw_fields"]["fp"] == "Q2"
    assert raw_fact["raw_fields"]["duration_days"] == 90
    assert "quarterly balance sheet" in raw_fact["raw_fields"]["context"]
    assert raw_fact["raw_fields"]["raw"] == "Inventories, net 230"
    assert raw_fact["raw_fields"]["raw_metric"] == "Inventories, net"
    assert raw_fact["raw_fields"]["row_marker"] == "Inventories, net"
    assert raw_fact["raw_fields"]["source"] == "html_table_fact"
    assert raw_fact["raw_fields"]["statement"] == "balance_sheet"
    assert raw_fact["raw_fields"]["target_document_binding_accepted"] is True
    assert raw_fact["raw_fields"]["target_document_binding_score"] == 130
    requirements = payload["slot_bind_packet"]["slot_requirements"]
    begin_requirement = next(item for item in requirements if item["slot_name"] == "inventory_begin")
    assert begin_requirement["evidence_specs"][0]["line_item"] == "inventories"
    assert begin_requirement["transform_consumers"][0]["name"] == "dio"
    assert "period_scope" not in json.dumps(raw_fact, ensure_ascii=False)
    assert "finance_metric_intent" not in json.dumps(raw_fact, ensure_ascii=False)
    assert "finance_question_period_scope" not in json.dumps(raw_fact, ensure_ascii=False)


def test_finance_fact_ledger_carries_span_metric_intent_as_diagnostic_metadata() -> None:
    evidence = [
        _finance_evidence(
            evidence_id="evidence-sales-other",
            text=(
                "entityName=Chevron Corp ticker=CVX fy=2024 period=annual "
                "metric=sales and other operating revenues concept=SalesAndOtherOperatingRevenue "
                "value=193414000000 unit=USD"
            ),
            title="Chevron 2024 SEC companyfacts",
        )
    ]
    evidence[0].diagnostics.update(
        {
            "span_metadata": {
                "target_line_item": "total revenues",
                "target_slot": "revenue",
                "finance_metric_intent": {
                    "active": True,
                    "metric_family": "revenue",
                    "score": 13.5,
                    "matched_preferred": ["metric=sales and other operating revenues"],
                    "matched_demoted": [],
                },
            }
        }
    )
    citations = [_finance_citation(evidence[0], citation_id="cite-sales-other")]

    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)

    assert facts
    fact = facts[0]
    assert fact.metadata["target_line_item"] == "total revenues"
    assert fact.metadata["target_slot"] == "revenue"
    assert fact.metadata["finance_metric_intent"]["metric_family"] == "revenue"
    assert fact.metadata["finance_metric_intent"]["matched_preferred"] == ["metric=sales and other operating revenues"]


def test_model_compiled_program_authorizes_numeric_preflight_for_direct_filing_lookup() -> None:
    program = {
        "source": "task_compile_model",
        "task_spec": {
            "domain": "finance",
            "task_type": "filing_metric_lookup",
            "objective": "Look up a filing line item.",
        },
        "evidence_specs": [
            {
                "slot_name": "capital_expenditures",
                "line_item": "capital expenditures",
                "statement": "cash_flow_statement",
            }
        ],
        "transform_specs": [],
        "slot_frame": {"required_slots": [{"name": "capital_expenditures"}]},
        "diagnostics": {
            "source": "task_compile_model",
            "tool_chain_plan": {
                "recommended_steps": [{"tool": "retrieval.run"}],
                "decision_owner": "model",
            },
        },
    }

    assert _model_compiled_program_authorizes_numeric_preflight(program) is True


def test_model_compiled_program_does_not_authorize_empty_direct_program() -> None:
    program = {
        "source": "task_compile_model",
        "task_spec": {"domain": "finance", "task_type": "general_research"},
        "evidence_specs": [],
        "transform_specs": [],
        "slot_frame": {"required_slots": []},
        "diagnostics": {"source": "task_compile_model"},
    }

    assert _model_compiled_program_authorizes_numeric_preflight(program) is False


def test_finance_slot_bind_prompt_keeps_late_large_ledger_candidates_visible() -> None:
    facts: list[FinanceFact] = []
    special_index = 210
    for index in range(320):
        metric = "capital expenditures" if index == special_index else "revenue"
        facts.append(
            FinanceFact(
                fact_id=f"fact-{index}",
                entity="3M",
                ticker="MMM",
                period="2018",
                fiscal_year=2018,
                metric=metric,
                value="-1577" if index == special_index else str(index),
                unit="USD",
                scale="actual",
                source_ref=f"source-{index}",
                evidence_ref=f"evidence-{index}",
                citation_ref=f"cite-{index}",
                metadata={
                    "context": "Statement of cash flows row: Purchases of property, plant and equipment 1,577"
                    if index == special_index
                    else "Other filing table row",
                    "raw": "Purchases of property, plant and equipment (1,577)"
                    if index == special_index
                    else f"Revenue {index}",
                    "target_document_binding_accepted": index == special_index,
                    "source_uri": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
                },
            )
        )

    prompt = _finance_slot_bind_prompt(
        question="What is the FY2018 capital expenditure amount for 3M?",
        facts=facts,
        compiled_program={
            "program_id": "program-capex",
            "task_spec": {"task_type": "filing_metric_lookup", "objective": "Find FY2018 capital expenditures"},
            "evidence_specs": [{"slot_name": "capital_expenditures", "line_item": "capital expenditures"}],
            "slot_frame": {"required_slots": [{"name": "capital_expenditures"}]},
        },
    )
    payload = json.loads(prompt)
    raw_facts = payload["slot_bind_packet"]["raw_facts"]

    assert payload["slot_bind_packet"]["raw_fact_count"] == 320
    assert any(item["fact_id"] == f"fact-{special_index}" for item in raw_facts)
    late = next(item for item in raw_facts if item["fact_id"] == f"fact-{special_index}")
    assert late["metric"] == "capital expenditures"
    assert late["value"] == "-1577"
    assert "Purchases of property" in late["raw_fields"]["context"]
    assert late["raw_fields"]["target_document_binding_accepted"] is True


def test_finance_slot_bind_plans_use_model_selected_fact_ids_only() -> None:
    facts = [
        FinanceFact(
            fact_id="fact-inv-begin",
            entity="Retailer",
            ticker="RTL",
            period="FY2023 end",
            fiscal_year=2024,
            metric="inventory",
            value="200",
            unit="USD",
            scale="actual",
            source_ref="source-1",
            evidence_ref="evidence-1",
            citation_ref="cite-1",
            metadata={"form": "10-K", "fp": "FY", "end": "2024-01-28"},
        ),
        FinanceFact(
            fact_id="fact-inv-end",
            entity="Retailer",
            ticker="RTL",
            period="FY2024 end",
            fiscal_year=2025,
            metric="inventory",
            value="240",
            unit="USD",
            scale="actual",
            source_ref="source-2",
            evidence_ref="evidence-2",
            citation_ref="cite-2",
            metadata={"form": "10-K", "fp": "FY", "end": "2025-02-02"},
        ),
        FinanceFact(
            fact_id="fact-cogs",
            entity="Retailer",
            ticker="RTL",
            period="FY2024",
            fiscal_year=2025,
            metric="cost of revenue",
            value="1000",
            unit="USD",
            scale="actual",
            source_ref="source-3",
            evidence_ref="evidence-3",
            citation_ref="cite-3",
            metadata={"form": "10-K", "fp": "FY", "start": "2024-01-29", "end": "2025-02-02"},
        ),
    ]
    parsed = {
        "decision": "ready",
        "slot_bindings": [
            {"slot_name": "inventory_begin", "variable_name": "inventory_begin", "fact_id": "fact-inv-begin"},
            {"slot_name": "inventory_end", "variable_name": "inventory_end", "fact_id": "fact-inv-end"},
            {"slot_name": "cogs", "variable_name": "cogs", "fact_id": "fact-cogs"},
        ],
        "formula_requests": [
            {
                "formula_name": "dio:RTL",
                "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
                "variables": {
                    "inventory_begin": {"fact_id": "fact-inv-begin"},
                    "inventory_end": {"fact_id": "fact-inv-end"},
                    "cogs": {"fact_id": "fact-cogs"},
                    "fiscal_days": 365,
                },
                "unit": "days",
            }
        ],
        "reason_summary": "Model selected the fiscal-year inventory and COGS facts.",
    }

    plans, rejected = _finance_slot_bind_plans_from_model(parsed, facts=facts, ledger_ref="ledger-1")

    assert rejected == []
    assert len(plans) == 1
    assert plans[0].payload is not None
    assert plans[0].payload["variables"] == {
        "inventory_begin": "200",
        "inventory_end": "240",
        "cogs": "1000",
        "fiscal_days": 365,
    }
    assert plans[0].payload["input_fact_ids"] == ["fact-inv-begin", "fact-inv-end", "fact-cogs"]


def test_finance_slot_bind_plans_preserve_model_period_and_line_item_basis() -> None:
    facts = [
        FinanceFact(
            fact_id="fact-fy-revenue",
            entity="Retailer",
            ticker="RTL",
            period="FY2024",
            fiscal_year=2024,
            metric="revenue",
            value="1200",
            unit="USD",
            scale="actual",
            source_ref="source-1",
            evidence_ref="evidence-1",
            citation_ref="cite-1",
            metadata={"form": "10-K", "fp": "FY", "start": "2024-02-01", "end": "2025-01-31"},
        )
    ]
    parsed = {
        "decision": "ready",
        "slot_bindings": [
            {"slot_name": "revenue", "variable_name": "revenue", "fact_id": "fact-fy-revenue"},
        ],
        "formula_requests": [
            {
                "formula_name": "revenue",
                "expression": "revenue",
                "variables": {"revenue": {"fact_id": "fact-fy-revenue"}},
                "unit": "USD",
            }
        ],
        "period_basis": [
            {
                "slot_name": "revenue",
                "fact_id": "fact-fy-revenue",
                "selected_period": "FY2024",
                "raw_fields_used": ["form", "fp", "start", "end"],
                "reason": "10-K FY duration matches requested fiscal year.",
            }
        ],
        "line_item_basis": [
            {
                "slot_name": "revenue",
                "fact_id": "fact-fy-revenue",
                "selected_line_item": "Revenue",
                "raw_fields_used": ["concept", "label"],
                "reason": "Revenue concept directly matches requested line item.",
            }
        ],
        "reason_summary": "Model selected the FY revenue line using SEC period and line-item fields.",
    }

    plans, rejected = _finance_slot_bind_plans_from_model(parsed, facts=facts, ledger_ref="ledger-1")

    assert rejected == []
    assert len(plans) == 1
    assert plans[0].payload is not None
    diagnostics = plans[0].payload["diagnostics"]
    assert diagnostics["model_period_basis"][0]["selected_period"] == "FY2024"
    assert diagnostics["model_line_item_basis"][0]["selected_line_item"] == "Revenue"
    assert plans[0].diagnostics["model_period_basis"] == diagnostics["model_period_basis"]


def test_finance_slot_bind_plans_accept_model_selected_imperfect_metric_identity_formula() -> None:
    facts = [
        FinanceFact(
            fact_id="fact-capex-row",
            entity="3M",
            ticker="MMM",
            period="FY2018",
            fiscal_year=2018,
            metric="property plant and equipment net",
            value="1577",
            unit="USD",
            scale="actual",
            source_ref="source-1",
            evidence_ref="evidence-1",
            citation_ref="cite-1",
            metadata={
                "context": "Statement of cash flows row: Purchases of property, plant and equipment 1,577",
                "raw": "Purchases of property, plant and equipment (1,577)",
            },
        )
    ]
    parsed = {
        "decision": "ready",
        "slot_bindings": [
            {
                "slot_name": "capital_expenditures",
                "variable_name": "capex_millions",
                "fact_id": "fact-capex-row",
                "reason": "Raw cash-flow row matches capex despite noisy metric label.",
            }
        ],
        "formula_requests": [
            {
                "formula_name": "capital_expenditures_millions",
                "expression": "capex_millions",
                "variables": {"capex_millions": "capital_expenditures"},
                "unit": "USD millions",
            }
        ],
        "reason_summary": "Model used raw row/context and requested identity formula trace.",
    }

    plans, rejected = _finance_slot_bind_plans_from_model(parsed, facts=facts, ledger_ref="ledger-1")

    assert rejected == []
    assert len(plans) == 1
    assert plans[0].payload is not None
    assert plans[0].payload["expression"] == "capex_millions"
    assert plans[0].payload["variables"] == {"capex_millions": "1577"}
    assert plans[0].payload["input_fact_ids"] == ["fact-capex-row"]


def test_finance_slot_bind_plans_accept_formula_refs_for_chained_calculator() -> None:
    facts = [
        FinanceFact(
            fact_id="fact-inv-begin",
            entity="Retailer",
            ticker="RTL",
            period="FY2023 end",
            fiscal_year=2024,
            metric="inventory",
            value="200",
            unit="USD",
            scale="actual",
            source_ref="source-1",
            evidence_ref="evidence-1",
            citation_ref="cite-1",
            metadata={},
        ),
        FinanceFact(
            fact_id="fact-inv-end",
            entity="Retailer",
            ticker="RTL",
            period="FY2024 end",
            fiscal_year=2025,
            metric="inventory",
            value="240",
            unit="USD",
            scale="actual",
            source_ref="source-2",
            evidence_ref="evidence-2",
            citation_ref="cite-2",
            metadata={},
        ),
        FinanceFact(
            fact_id="fact-cogs",
            entity="Retailer",
            ticker="RTL",
            period="FY2024",
            fiscal_year=2025,
            metric="cost of revenue",
            value="1000",
            unit="USD",
            scale="actual",
            source_ref="source-3",
            evidence_ref="evidence-3",
            citation_ref="cite-3",
            metadata={},
        ),
    ]
    parsed = {
        "decision": "ready",
        "slot_bindings": [
            {"slot_name": "inventory_begin", "variable_name": "inventory_begin", "fact_id": "fact-inv-begin"},
            {"slot_name": "inventory_end", "variable_name": "inventory_end", "fact_id": "fact-inv-end"},
            {"slot_name": "cogs", "variable_name": "cogs", "fact_id": "fact-cogs"},
        ],
        "formula_requests": [
            {
                "formula_name": "average_inventory",
                "expression": "(inventory_begin + inventory_end) / 2",
                "variables": {
                    "inventory_begin": {"fact_id": "fact-inv-begin"},
                    "inventory_end": {"fact_id": "fact-inv-end"},
                },
                "unit": "USD",
            },
            {
                "formula_name": "dio",
                "expression": "average_inventory / cogs * fiscal_days",
                "variables": {
                    "average_inventory": {"formula_ref": "average_inventory"},
                    "cogs": {"fact_id": "fact-cogs"},
                    "fiscal_days": 365,
                },
                "unit": "days",
            },
        ],
        "reason_summary": "Model requested chained calculator formulas.",
    }

    plans, rejected = _finance_slot_bind_plans_from_model(parsed, facts=facts, ledger_ref="ledger-1")

    assert rejected == []
    assert len(plans) == 2
    assert plans[1].payload is not None
    assert plans[1].payload["variables"]["average_inventory"] == {"__formula_ref__": "average_inventory"}
    assert plans[1].payload["input_fact_ids"] == ["fact-cogs"]


def test_model_finance_slot_bind_repairs_malformed_json_without_host_semantic_binding() -> None:
    journal = JournalStore.in_memory()
    repaired_response = {
        "decision": "ready",
        "slot_bindings": [
            {"slot_name": "inventory_begin", "variable_name": "inventory_begin", "fact_id": "fact-inv-begin"},
            {"slot_name": "inventory_end", "variable_name": "inventory_end", "fact_id": "fact-inv-end"},
            {"slot_name": "cogs", "variable_name": "cogs", "fact_id": "fact-cogs"},
        ],
        "formula_requests": [
            {
                "formula_name": "dio",
                "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
                "variables": {
                    "inventory_begin": {"fact_id": "fact-inv-begin"},
                    "inventory_end": {"fact_id": "fact-inv-end"},
                    "cogs": {"fact_id": "fact-cogs"},
                    "fiscal_days": 365,
                },
                "unit": "days",
            }
        ],
        "missing_slots": [],
        "reason_summary": "Model repaired its JSON and kept fact-id bindings.",
    }
    provider = MalformedThenTaskJsonProvider("finance.slot_bind", repaired_response)
    fabric = ProcessorFabric(
        providers={"fake_repair": provider},
        router=ProcessorRouter(default_provider="fake_repair", default_model="fake-repair"),
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric)
    facts = [
        FinanceFact(
            fact_id="fact-inv-begin",
            entity="Retailer",
            ticker="RTL",
            period="FY2023 end",
            fiscal_year=2024,
            metric="inventory",
            value="200",
            unit="USD",
            scale="actual",
            source_ref="source-1",
            evidence_ref="evidence-1",
            citation_ref="cite-1",
            metadata={},
        ),
        FinanceFact(
            fact_id="fact-inv-end",
            entity="Retailer",
            ticker="RTL",
            period="FY2024 end",
            fiscal_year=2025,
            metric="inventory",
            value="240",
            unit="USD",
            scale="actual",
            source_ref="source-2",
            evidence_ref="evidence-2",
            citation_ref="cite-2",
            metadata={},
        ),
        FinanceFact(
            fact_id="fact-cogs",
            entity="Retailer",
            ticker="RTL",
            period="FY2024",
            fiscal_year=2025,
            metric="cost of revenue",
            value="1000",
            unit="USD",
            scale="actual",
            source_ref="source-3",
            evidence_ref="evidence-3",
            citation_ref="cite-3",
            metadata={},
        ),
    ]
    compiled_program = {
        "program_id": "program-1",
        "source": "task_compile_model",
        "task_spec": {"task_type": "compute", "objective": "Calculate FY2024 DIO."},
        "evidence_specs": [],
        "transform_specs": [
            {
                "name": "dio",
                "required_slots": ["inventory_begin", "inventory_end", "cogs", "fiscal_days"],
                "expression": "(inventory_begin + inventory_end) / 2 / cogs * fiscal_days",
            }
        ],
        "slot_frame": {"required_slots": [{"name": "inventory_begin"}, {"name": "inventory_end"}, {"name": "cogs"}]},
    }

    plans = runtime._model_finance_slot_bind_plans(  # noqa: SLF001
        "task-slot-repair",
        "run-slot-repair",
        recipe=task_recipe("retrieval_answer"),
        facts=facts,
        compiled_program=compiled_program,
        ledger_ref="ledger-1",
    )

    assert len(plans) == 1
    assert plans[0].payload is not None
    assert plans[0].payload["variables"] == {
        "inventory_begin": "200",
        "inventory_end": "240",
        "cogs": "1000",
        "fiscal_days": 365,
    }
    assert len(provider.prompts) == 2
    repair_prompt = json.loads(provider.prompts[-1])
    assert list(repair_prompt)[:3] == ["contract", "output_schema", "previous_failure"]
    assert provider.prompts[-1].index('"contract"') < provider.prompts[-1].index('"previous_failure"')
    assert provider.prompts[-1].index('"output_schema"') < provider.prompts[-1].index('"previous_failure"')
    assert provider.prompts[-1].index('"previous_failure"') < provider.prompts[-1].index('"slot_bind_packet"')
    assert "Previous output was rejected" in repair_prompt["contract"]
    assert repair_prompt["previous_failure"]["raw_output_preview"]
    structured_feedback = repair_prompt["previous_failure"]["structured_feedback"]
    assert structured_feedback["schema"] == "holo.kernel_v3.finance_slot_bind_repair_feedback.v1"
    assert structured_feedback["category"] == "malformed_json"
    assert structured_feedback["required_fields"] == ["decision", "slot_bindings", "formula_requests", "reason_summary"]
    assert "Return exactly one JSON object" in structured_feedback["repair_checklist"][0]
    slot_bind_record = journal.records(task_id="task-slot-repair", kind="finance_slot_bind")[-1]
    assert slot_bind_record.data["repair_attempted"] is True
    assert slot_bind_record.data["repair_feedback"]["category"] == "malformed_json"
    assert slot_bind_record.data["accepted_formula_plan_count"] == 1


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


def test_finance_capability_preflight_does_not_auto_compute_formula() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(journal, answer="fallback")
    evidence = [
        _finance_evidence(
            evidence_id="evidence-net-margin",
            title="TestCo 2024 10-K",
            uri="https://www.sec.gov/Archives/testco-2024.htm",
            text=(
                "entityName=TestCo metric=revenue label=Revenue unit=USD fy=2024 form=10-K value=200 "
                "entityName=TestCo metric=net income label=Net income unit=USD fy=2024 form=10-K value=50"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-net-margin")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "goal": "Calculate TestCo FY2024 net margin.",
        },
    )

    runtime._run_finance_numeric_preflight(  # noqa: SLF001
        "task-llm-owned-preflight",
        "run-1",
        recipe=recipe,
        evidence=evidence,
        citations=citations,
    )

    preflights = journal.records(task_id="task-llm-owned-preflight", kind="finance_numeric_preflight")
    assert preflights[-1].data["status"] == "skipped"
    assert preflights[-1].data["semantic_decision_owner"] == "model"
    assert journal.records(task_id="task-llm-owned-preflight", kind="finance_fact_ledger")
    assert not journal.records(task_id="task-llm-owned-preflight", kind="finance_formula_plan")
    assert not journal.records(task_id="task-llm-owned-preflight", kind="observation")


def test_host_semantic_fallbacks_are_disabled_by_default_and_in_finance_capability() -> None:
    legacy_recipe = task_recipe("retrieval_answer", metadata={"host_semantic_fallbacks": {"enabled": True}})
    default_recipe = task_recipe("retrieval_answer", metadata={})
    strict_recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-capability")),
            "host_semantic_fallbacks": {"enabled": True},
        },
    )

    assert _host_semantic_fallbacks_enabled(default_recipe) is False
    assert _host_semantic_fallbacks_enabled(legacy_recipe) is True
    assert _host_semantic_fallbacks_enabled(strict_recipe) is False


def test_non_strict_finance_preflight_skips_host_formula_without_explicit_legacy_flag() -> None:
    journal = JournalStore.in_memory()
    runtime = _runtime_with_synthesizer(journal, answer="fallback")
    evidence = [
        _finance_evidence(
            evidence_id="evidence-net-margin",
            title="TestCo 2024 10-K",
            uri="https://www.sec.gov/Archives/testco-2024.htm",
            text=(
                "entityName=TestCo metric=revenue label=Revenue unit=USD fy=2024 form=10-K value=200 "
                "entityName=TestCo metric=net income label=Net income unit=USD fy=2024 form=10-K value=50"
            ),
        )
    ]
    citations = [_finance_citation(evidence[0], citation_id="cite-net-margin")]
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            **execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "goal": "Calculate TestCo FY2024 net margin.",
        },
    )

    runtime._run_finance_numeric_preflight(  # noqa: SLF001
        "task-host-formula-disabled",
        "run-1",
        recipe=recipe,
        evidence=evidence,
        citations=citations,
    )

    preflights = journal.records(task_id="task-host-formula-disabled", kind="finance_numeric_preflight")
    assert preflights[-1].data["status"] == "skipped"
    assert preflights[-1].data["reason"] == "host_semantic_formula_preflight_disabled"
    assert not journal.records(task_id="task-host-formula-disabled", kind="finance_formula_plan")
    assert not journal.records(task_id="task-host-formula-disabled", kind="observation")


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
            "host_semantic_fallbacks": {"enabled": True},
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
        metadata={
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "host_semantic_fallbacks": {"enabled": True},
        },
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
    assert synthesis_gates[0].data["status"] == "failed"
    assert synthesis_gates[-1].data["status"] == "passed"
    assert any(
        record.data["diagnostics"].get("gate_id") == "llm_semantic_numeric_judge_unavailable_v1"
        for record in synthesis_gates
    )
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
        metadata={
            "execution_metadata": execution_profile_runtime_metadata(execution_profile("finance-fact-fast")),
            "host_semantic_fallbacks": {"enabled": True},
        },
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
    assert synthesis_gates[0].data["status"] == "failed"
    assert synthesis_gates[-1].data["status"] == "passed"
    assert any(
        record.data["diagnostics"].get("gate_id") == "llm_semantic_numeric_judge_unavailable_v1"
        for record in synthesis_gates
    )


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


class MalformedThenTaskJsonProvider:
    model = "fake-repair"

    def __init__(self, task_type: str, repaired_response: dict) -> None:
        self.name = "fake_repair"
        self.task_type = task_type
        self.repaired_response = dict(repaired_response)
        self.prompts: list[str] = []
        self.calls = 0

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        assert request.processor == self.task_type
        self.prompts.append(request.prompt)
        self.calls += 1
        if self.calls == 1:
            text = '{"decision":"ready","slot_bindings":['
        else:
            text = json.dumps(self.repaired_response, ensure_ascii=False, sort_keys=True)
        return ProcessorResult(
            result_id=f"result-{request.request_id}",
            request_id=request.request_id,
            status="ok",
            output={"text": text, "provider": self.name, "model": self.model},
            usage={
                "prompt_tokens": len(request.prompt),
                "completion_tokens": len(text),
                "total_tokens": len(request.prompt) + len(text),
            },
            error=None,
        )


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


def _year_fact(metric: str, value: str, fiscal_year: int, *, fact_id: str, metadata: dict | None = None) -> FinanceFact:
    return FinanceFact(
        fact_id=fact_id,
        entity=None,
        ticker=None,
        period=str(fiscal_year),
        fiscal_year=fiscal_year,
        metric=metric,
        value=value,
        unit="USD",
        scale="actual",
        source_ref=f"cite-{fact_id}",
        evidence_ref=f"ev-{fact_id}",
        citation_ref=f"cite-{fact_id}",
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
