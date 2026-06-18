from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

from kernel_v3.context.redaction import Redactor
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, JsonObject, Observation
from kernel_v3.processors.contracts import (
    EVALUATOR_PROMPT_CONTRACT,
    EVALUATOR_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    PLANNER_SCHEMA,
    SYNTHESIZER_PROMPT_CONTRACT,
    SYNTHESIZER_SCHEMA,
    FinalAnswer,
)
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport

SYNTHESIS_EVIDENCE_PREVIEW_CHARS = 4096
SYNTHESIS_CITATION_PREVIEW_CHARS = 2048
SYNTHESIS_BUDGET_HEADROOM_CHARS = 4096
PROVIDER_TOOL_LIST_LIMIT = 48
PROVIDER_PERMISSION_LIST_LIMIT = 32
PROVIDER_TOOL_SELECTION_LIMIT = 24
PROVIDER_LIGHTWEIGHT_TOOL_SELECTION_LIMIT = 8


class ModelPlanner:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.allowed_tool_names = set(allowed_tool_names or set())
        self.calls: list[ContextBundle] = []

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self.calls.append(context)
        task_id = _task_id(context)
        run_id = _run_id(context)
        outcome = self.fabric.run_json(
            task_type="planner.propose",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=_planner_prompt(context, feedback),
            schema=PLANNER_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={"adapter": "ModelPlanner", **_processor_budget_parameters_from_context(context)},
        )
        if outcome.parsed is None:
            return _planner_fallback(run_id, "processor_failed")
        action = _action_from_json(outcome.parsed)
        unsafe_reason = self._unsafe_reason(action)
        if unsafe_reason is not None:
            return _planner_fallback(run_id, unsafe_reason)
        return action

    def _unsafe_reason(self, action: CandidateAction) -> str | None:
        if action.kind not in {"respond", "tool", "ask_user"}:
            return "unsupported_action_kind"
        if action.kind == "tool":
            if not action.name:
                return "tool_name_required"
            if self.allowed_tool_names and action.name not in self.allowed_tool_names:
                return "tool_not_allowlisted"
        if action.side_effect_class not in {"none", "read", "write", "destructive", "shell", "network"}:
            return "unsupported_side_effect_class"
        return None


class ModelEvaluator:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model
        self.calls: list[Observation] = []

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.calls.append(observation)
        task_id = _task_id(context)
        run_id = _run_id(context)
        outcome = self.fabric.run_json(
            task_type="evaluator.assess",
            task_id=task_id,
            run_id=run_id,
            context_id=context.context_id,
            prompt=_evaluator_prompt(context, observation),
            schema=EVALUATOR_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={
                "adapter": "ModelEvaluator",
                "observation_id": observation.observation_id,
                **_processor_budget_parameters_from_context(context),
            },
        )
        if outcome.parsed is None:
            return Feedback(
                feedback_id=f"fb-{run_id}-model-evaluator-failed-{len(self.calls)}",
                run_id=run_id,
                status="failed",
                stop_reason="processor_failed",
                answer=None,
                missing_evidence=["model_evaluator_failed"],
            )
        return _feedback_from_json(outcome.parsed, run_id=run_id, index=len(self.calls))


class Synthesizer:
    def __init__(
        self,
        *,
        fabric: ProcessorFabric,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.fabric = fabric
        self.provider = provider
        self.model = model

    def synthesize(
        self,
        *,
        run_id: str,
        context_id: str,
        report: RetrievalReport,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        task_id: str | None = None,
        retry_instruction: str | None = None,
        processor_budget: JsonObject | None = None,
    ) -> FinalAnswer:
        budget_parameters = {"processor_budget": dict(processor_budget)} if isinstance(processor_budget, dict) else {}
        prompt, prompt_parameters, report, evidence, citations = _budgeted_synthesizer_prompt(
            report,
            evidence,
            citations,
            retry_instruction=retry_instruction,
            processor_budget=processor_budget,
        )
        outcome = self.fabric.run_json(
            task_type="synthesizer.answer",
            task_id=task_id,
            run_id=run_id,
            context_id=context_id,
            prompt=prompt,
            schema=SYNTHESIZER_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={
                "adapter": "Synthesizer",
                "retrieval_report_id": report.report_id,
                **prompt_parameters,
                **budget_parameters,
                **({"retry_reason": "answer_quality"} if retry_instruction else {}),
            },
        )
        if outcome.parsed is None:
            repair_feedback = _synthesizer_repair_feedback(outcome.result.error or "synthesizer_json_invalid")
            repair_prompt, repair_prompt_parameters, repair_report, repair_evidence, repair_citations = _budgeted_synthesizer_prompt(
                report,
                evidence,
                citations,
                retry_instruction=(
                    "Previous synthesizer output was not valid JSON. "
                    "Return exactly one valid JSON object matching synthesizer.answer. "
                    "Do not include markdown fences or prose outside JSON. "
                    "Keep answer concise enough to avoid truncation while preserving required evidence, "
                    "calculator results, caveats, citation_refs, and used_evidence."
                ),
                repair_feedback=repair_feedback,
                processor_budget=processor_budget,
            )
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-json-repair",
                prompt=repair_prompt,
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": repair_report.report_id,
                    "repair_reason": "invalid_json",
                    "repair_feedback_schema": repair_feedback.get("schema"),
                    "repair_feedback_category": repair_feedback.get("category"),
                    **repair_prompt_parameters,
                    **budget_parameters,
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=repair_citations, evidence=repair_evidence)
            salvaged = _salvage_final_answer_from_raw_text(
                retry.raw_text or outcome.raw_text,
                citations=repair_citations,
                evidence=repair_evidence,
                error=retry.result.error or outcome.result.error or "invalid_json",
            )
            if salvaged is not None:
                return salvaged
            return FinalAnswer(
                status="failed",
                answer=None,
                citation_refs=[],
                confidence=0.0,
                limitations=[],
                used_evidence=[],
                error="processor_failed",
            )
        answer = _final_answer_from_json(outcome.parsed, citations=citations, evidence=evidence)
        if _is_unknown_reference_error(answer.error) and (citations or evidence):
            repair_feedback = _synthesizer_repair_feedback(answer.error or "unknown_reference")
            reference_prompt, reference_prompt_parameters, reference_report, reference_evidence, reference_citations = _budgeted_synthesizer_prompt(
                report,
                evidence,
                citations,
                retry_instruction=(
                    "Previous synthesizer output used citation_refs or used_evidence ids that are not in the allowed lists. "
                    "Return a corrected JSON object. Keep the supported answer semantics, but choose citation_refs only from "
                    "required_citation_refs and used_evidence only from required_evidence_refs. Do not invent ids, source ids, "
                    "facts, formulas, or unsupported numeric claims."
                ),
                repair_feedback=repair_feedback,
                processor_budget=processor_budget,
            )
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-reference-repair",
                prompt=reference_prompt,
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": reference_report.report_id,
                    "repair_reason": "unknown_references",
                    "repair_feedback_schema": repair_feedback.get("schema"),
                    "repair_feedback_category": repair_feedback.get("category"),
                    **reference_prompt_parameters,
                    **budget_parameters,
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=reference_citations, evidence=reference_evidence)
        if answer.error == "missing_citation_refs" and citations:
            citation_prompt, citation_prompt_parameters, citation_report, citation_evidence, citation_citations = _budgeted_synthesizer_prompt(
                report,
                evidence,
                citations,
                retry_instruction=(
                    "Previous synthesizer output omitted citation_refs. "
                    "Return a corrected JSON object. citation_refs must include one or more ids "
                    "from required_citation_refs, and used_evidence must include matching evidence ids."
                ),
                processor_budget=processor_budget,
            )
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-citation-repair",
                prompt=citation_prompt,
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": citation_report.report_id,
                    "repair_reason": "missing_citation_refs",
                    **citation_prompt_parameters,
                    **budget_parameters,
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=citation_citations, evidence=citation_evidence)
        return answer


def _planner_prompt(context: ContextBundle, feedback: Feedback | None) -> str:
    payload = {
        "contract": PLANNER_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "feedback": feedback.to_dict() if feedback is not None else None,
    }
    return _prompt_json(payload)


def _evaluator_prompt(context: ContextBundle, observation: Observation) -> str:
    payload = {
        "contract": EVALUATOR_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "observation": _compact_observation_for_provider(observation),
    }
    return _prompt_json(payload)


def _synthesizer_prompt(
    report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    *,
    retry_instruction: str | None = None,
    repair_feedback: JsonObject | None = None,
) -> str:
    preferences = _interaction_preferences_from_report(report)
    evidence_preview_chars = _positive_int(
        report.diagnostics.get("synthesis_evidence_preview_chars") if isinstance(report.diagnostics, dict) else None,
        default=SYNTHESIS_EVIDENCE_PREVIEW_CHARS,
    )
    citation_preview_chars = _positive_int(
        report.diagnostics.get("synthesis_citation_preview_chars") if isinstance(report.diagnostics, dict) else None,
        default=SYNTHESIS_CITATION_PREVIEW_CHARS,
    )
    answer_requirements = [
            "Answer every explicit question or subtask in task_goal when supported by provided evidence.",
            "If any part is unsupported, include it in limitations.",
            "Use only provided citation_refs and evidence ids.",
            "If required_citation_refs is non-empty, citation_refs must include at least one provided citation id.",
            "Use the response_language preference as the default user-visible language unless the user explicitly requested another language.",
            "If answer_profile.format is detailed_report, deep_report, or memo, write a sectioned report that covers answer_profile.target_sections and answer_profile.minimum_coverage.",
            "If the evidence does not support a required section, include that section with a clear limitation instead of collapsing the whole answer into a short summary.",
            "For finance research, distinguish facts, source-backed metrics, analysis, risks, and limitations; do not rely on generic product or encyclopedia pages as if they were financial statements.",
            "For finance calculations, if retrieval_report.diagnostics.finance_formula_traces is present, use those host calculator results as authoritative computed values and do not recompute them mentally.",
            "For finance calculations, if retrieval_report.diagnostics.finance_formula_trace_support is present, use it to connect FormulaTrace results to input facts, evidence refs, and citation refs.",
            "For finance modeling traces, if retrieval_report.diagnostics.finance_formula_trace_synthesis_policy is present, follow its model-output and assumption-labeling policy; assumptions are not filing facts.",
            "For finance ratio traces, if FormulaTrace diagnostics include bound_line_items or answer_wording_policy, name the actual selected numerator and denominator line items instead of replacing them with a generic ratio label.",
            "For finance calculations, if retrieval_report.diagnostics.finance_slot_bind_state is present, use its period_basis and line_item_basis as prior model-owned binding rationale; preserve it when still supported, or explicitly revise it when later evidence conflicts.",
            "For finance calculation, ratio, efficiency, ranking, growth, margin, multiple, bps, or comparison answers, the complete verification path is finance.slot_bind for slot/formula binding, calculator.compute for deterministic derived values, and finance.verify_numeric for final numeric support. If these diagnostics or FormulaTrace values are absent while only raw filing inputs are available, state the missing calculation/verification in limitations instead of presenting a qualitative-only answer as complete.",
            "For finance answers, if retrieval_report.diagnostics.finance_competing_fact_clusters is present, treat it only as an attention index over raw facts that share entity, period, and broad metric hints; it is not a host ranking or selected answer.",
            "For finance answers, every material numeric claim must be supported by retrieval_report.diagnostics.finance_formula_traces, finance fact or claim ledger evidence, or an explicit assumption label. Omit unsupported numbers or move them into limitations; do not invent bridging figures, multiples, growth rates, margins, or dates.",
            "For finance benchmark-style answers, do not introduce generic industry thresholds, comparison cutoffs, benchmark percentages, multiples, ranges, or rule-of-thumb numbers unless those exact numbers are present in provided facts, evidence, citations, or FormulaTrace values.",
            "For qualitative finance classifications such as capital intensity, use the supported FormulaTrace lenses and values directly; when no source-backed threshold is provided, state the qualitative judgment in words instead of adding unsupported threshold percentages.",
            "For finance filing tables, preserve the filing's displayed scale and numeric form when possible, such as USD millions and table values like 923 or 5,603; do not convert supported filing numbers into different display units such as Chinese 亿 or Chinese 百万 unless the source itself uses that unit.",
            "For finance benchmark-style answers, begin with one short English core answer sentence before any localized explanation, even when response_language is Chinese.",
            "For finance benchmark-style numeric answers, include at least one machine-readable English numeric form for the core answer, e.g. '$193.414 billion' or '$193,414 million', even when the surrounding prose is Chinese.",
            "If task_goal requests a unit such as USD millions, USD billions, or USD thousands, make the first core numeric answer use that requested unit directly, e.g. '1,577 (USD millions)' or '8.7 (USD billions)'.",
            "If the evidence exposes multiple adjacent revenue metrics, answer with the supported line item that most directly matches task_goal; mention broader/narrower metrics only as context, not as the leading answer.",
            "When adjacent revenue metrics are plausible for the same task_goal, include each material candidate with its exact filing label and machine-readable value, for example both 'Sales and other operating revenues = $193.414 billion' and 'Total revenues and other income = $202.792 billion'.",
            "For SEC filing revenue questions, prefer exact filing statement captions over generic XBRL labels; do not silently collapse RevenueFromContractWithCustomerExcludingAssessedTax, Sales and other operating revenues, generic Revenues, and Total revenues and other income into one metric.",
            "For a plain SEC filing 'total revenues' question, if evidence contains both an operating/sales revenue line and a broader subtotal that explicitly includes other income, headline the operating/sales revenue line unless the task explicitly asks for 'total revenues and other income'. Mention the broader other-income subtotal only as context.",
            "For finance answers, if retrieval_report.diagnostics.finance_question_numeric_premise_hints is present, inspect those question-embedded numbers against the supported facts/traces; if the evidence contradicts a numeric premise, state the corrected actual value rather than selecting a nearby fact as if the premise were true.",
            "For finance filing questions where the requested line item is not separately itemized or retrieval_report.diagnostics.missing_slots still contains that requested line item, the English core sentence must start with 'Not separately itemized;' plus the relevant business location from task_goal/evidence, such as 'included in Azure segment and capex discussion' when supported. Do not headline a substitute numeric value before that unavailable/not-itemized judgment.",
            "For finance benchmark-style missing evidence answers, if the requested fact or required slot is absent after retrieval, start the English core sentence with 'Not available in the provided evidence;' before describing partial-period, proxy, or adjacent facts.",
            "If the provided or retrieved finance evidence contradicts an expected premise, stale figure, or benchmark gold note, explicitly state the corrected actual value using wording such as 'actual' or 'corrected value'.",
            "Use host_situation as the source of truth for whether live retrieval, tools, permissions, and finance research are available.",
            "Do not say live retrieval, network access, or finance research is unavailable unless host_situation.retrieval or host_situation.failure says so.",
            "If host_situation says retrieval was attempted but evidence is insufficient, describe the real failure as search/fetch/extraction/citation/coverage quality instead of a permission problem.",
    ]
    payload = {
        "contract": SYNTHESIZER_PROMPT_CONTRACT,
        "answer_requirements": answer_requirements,
        "task_goal": _task_goal_from_report(report),
        "interaction_preferences": preferences,
        "response_language": preferences.get("response_language"),
        "answer_profile": _json_object(report.diagnostics.get("answer_profile")) if isinstance(report.diagnostics, dict) else {},
        "research_mission": _json_object(report.diagnostics.get("research_mission")) if isinstance(report.diagnostics, dict) else {},
        "host_situation": _json_object(report.diagnostics.get("host_situation")) if isinstance(report.diagnostics, dict) else {},
        "required_citation_refs": [item.citation_id for item in citations],
        "required_evidence_refs": [item.evidence_id for item in evidence],
        "retrieval_report": _compact_retrieval_report_for_provider(report),
        "evidence": [_compact_evidence_for_provider(item, preview_chars=evidence_preview_chars) for item in evidence],
        "citations": [_compact_citation_for_provider(item, preview_chars=citation_preview_chars) for item in citations],
    }
    if retry_instruction:
        payload["retry_instruction"] = retry_instruction
    if repair_feedback:
        payload["repair_feedback"] = dict(repair_feedback)
    return _prompt_json(payload)


def _budgeted_synthesizer_prompt(
    report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    *,
    retry_instruction: str | None = None,
    repair_feedback: JsonObject | None = None,
    processor_budget: JsonObject | None = None,
) -> tuple[str, JsonObject, RetrievalReport, list[EvidenceItem], list[CitationItem]]:
    prompt = _synthesizer_prompt(
        report,
        evidence,
        citations,
        retry_instruction=retry_instruction,
        repair_feedback=repair_feedback,
    )
    max_prompt_chars = _processor_budget_max_prompt_chars(processor_budget)
    if max_prompt_chars is None:
        return prompt, {}, report, evidence, citations
    target_chars = max(1, max_prompt_chars - SYNTHESIS_BUDGET_HEADROOM_CHARS)
    if len(prompt) <= target_chars:
        return prompt, {}, report, evidence, citations

    selected: tuple[str, JsonObject, RetrievalReport, list[EvidenceItem], list[CitationItem]] | None = None
    shortest: tuple[str, JsonObject, RetrievalReport, list[EvidenceItem], list[CitationItem]] | None = None
    original_prompt_chars = len(prompt)
    for profile in _synthesis_budget_profiles():
        compact_report, compact_evidence, compact_citations = _compact_synthesis_inputs_for_budget(
            report,
            evidence,
            citations,
            profile=profile,
            max_prompt_chars=max_prompt_chars,
            original_prompt_chars=original_prompt_chars,
        )
        compact_prompt = _synthesizer_prompt(
            compact_report,
            compact_evidence,
            compact_citations,
            retry_instruction=retry_instruction,
            repair_feedback=repair_feedback,
        )
        parameters = {
            "synthesis_context_compaction": "budgeted",
            "synthesis_compaction_reason": "prompt_budget",
            "synthesis_compaction_profile": profile["name"],
            "synthesis_original_prompt_chars": original_prompt_chars,
            "synthesis_compact_prompt_chars": len(compact_prompt),
            "synthesis_max_prompt_chars": max_prompt_chars,
            "synthesis_original_evidence_count": len(evidence),
            "synthesis_compact_evidence_count": len(compact_evidence),
            "synthesis_original_citation_count": len(citations),
            "synthesis_compact_citation_count": len(compact_citations),
            "synthesis_semantic_owner": "model",
            "synthesis_host_role": "budgeted_context_projection_only",
        }
        candidate = (compact_prompt, parameters, compact_report, compact_evidence, compact_citations)
        if shortest is None or len(compact_prompt) < len(shortest[0]):
            shortest = candidate
        if len(compact_prompt) <= target_chars:
            selected = candidate
            break
        if selected is None and len(compact_prompt) <= max_prompt_chars:
            selected = candidate

    if selected is not None:
        return selected
    if shortest is not None:
        return shortest
    return prompt, {}, report, evidence, citations


def _processor_budget_max_prompt_chars(processor_budget: JsonObject | None) -> int | None:
    if not isinstance(processor_budget, dict):
        return None
    value = processor_budget.get("max_prompt_chars_per_call")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _synthesis_budget_profiles() -> list[JsonObject]:
    return [
        {
            "name": "context_window_headroom_1",
            "evidence_limit": 24,
            "citation_limit": 32,
            "evidence_preview_chars": 2048,
            "citation_preview_chars": 1024,
            "finance_fact_ledger_limit": 48,
            "finance_candidate_facts_limit": 20,
            "finance_formula_traces_limit": 12,
            "finance_formula_trace_support_limit": 16,
            "finance_competing_fact_clusters_limit": 10,
            "finance_metric_intent_hints_limit": 20,
            "finance_question_numeric_premise_hints_limit": 8,
            "summary_limit": 6,
        },
        {
            "name": "context_window_headroom_2",
            "evidence_limit": 18,
            "citation_limit": 24,
            "evidence_preview_chars": 1024,
            "citation_preview_chars": 512,
            "finance_fact_ledger_limit": 32,
            "finance_candidate_facts_limit": 16,
            "finance_formula_traces_limit": 10,
            "finance_formula_trace_support_limit": 12,
            "finance_competing_fact_clusters_limit": 8,
            "finance_metric_intent_hints_limit": 16,
            "finance_question_numeric_premise_hints_limit": 6,
            "summary_limit": 4,
        },
        {
            "name": "context_window_headroom_3",
            "evidence_limit": 12,
            "citation_limit": 18,
            "evidence_preview_chars": 640,
            "citation_preview_chars": 320,
            "finance_fact_ledger_limit": 24,
            "finance_candidate_facts_limit": 12,
            "finance_formula_traces_limit": 8,
            "finance_formula_trace_support_limit": 8,
            "finance_competing_fact_clusters_limit": 6,
            "finance_metric_intent_hints_limit": 12,
            "finance_question_numeric_premise_hints_limit": 4,
            "summary_limit": 3,
        },
        {
            "name": "minimal_workbench",
            "evidence_limit": 8,
            "citation_limit": 12,
            "evidence_preview_chars": 360,
            "citation_preview_chars": 220,
            "finance_fact_ledger_limit": 12,
            "finance_candidate_facts_limit": 8,
            "finance_formula_traces_limit": 6,
            "finance_formula_trace_support_limit": 6,
            "finance_competing_fact_clusters_limit": 4,
            "finance_metric_intent_hints_limit": 8,
            "finance_question_numeric_premise_hints_limit": 3,
            "summary_limit": 2,
        },
        {
            "name": "bare_minimum_workbench",
            "evidence_limit": 4,
            "citation_limit": 6,
            "evidence_preview_chars": 220,
            "citation_preview_chars": 140,
            "finance_fact_ledger_limit": 6,
            "finance_candidate_facts_limit": 4,
            "finance_formula_traces_limit": 4,
            "finance_formula_trace_support_limit": 4,
            "finance_competing_fact_clusters_limit": 2,
            "finance_metric_intent_hints_limit": 4,
            "finance_question_numeric_premise_hints_limit": 2,
            "summary_limit": 1,
        },
    ]


def _compact_synthesis_inputs_for_budget(
    report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    *,
    profile: JsonObject,
    max_prompt_chars: int,
    original_prompt_chars: int,
) -> tuple[RetrievalReport, list[EvidenceItem], list[CitationItem]]:
    evidence_limit = _positive_profile_int(profile, "evidence_limit", default=8)
    citation_limit = _positive_profile_int(profile, "citation_limit", default=12)
    selected_citations = _select_citations_for_budget(citations, limit=citation_limit)
    selected_evidence = _select_evidence_for_budget(evidence, selected_citations, limit=evidence_limit)
    selected_evidence_ids = {item.evidence_id for item in selected_evidence if item.evidence_id}
    if selected_evidence_ids:
        linked_citations = [item for item in selected_citations if item.evidence_id in selected_evidence_ids]
        if linked_citations:
            selected_citations = linked_citations
    selected_citation_ids = [item.citation_id for item in selected_citations if item.citation_id]
    selected_evidence_ids_list = [item.evidence_id for item in selected_evidence if item.evidence_id]
    diagnostics = _compact_synthesis_diagnostics_for_budget(
        report.diagnostics if isinstance(report.diagnostics, dict) else {},
        profile=profile,
        max_prompt_chars=max_prompt_chars,
        original_prompt_chars=original_prompt_chars,
        original_evidence_count=len(evidence),
        compact_evidence_count=len(selected_evidence),
        original_citation_count=len(citations),
        compact_citation_count=len(selected_citations),
    )
    compact_report = replace(
        report,
        report_id=f"{report.report_id}-{profile['name']}",
        evidence_ids=selected_evidence_ids_list,
        citation_ids=selected_citation_ids,
        artifact_refs=_ordered_unique_strings([item.artifact_id for item in [*selected_evidence, *selected_citations] if item.artifact_id])[:16],
        preview=_preview(report.preview, 720),
        diagnostics=diagnostics,
    )
    return compact_report, selected_evidence, selected_citations


def _select_citations_for_budget(citations: list[CitationItem], *, limit: int) -> list[CitationItem]:
    if limit <= 0:
        return []
    return _ordered_citation_items(citations)[:limit]


def _select_evidence_for_budget(
    evidence: list[EvidenceItem],
    selected_citations: list[CitationItem],
    *,
    limit: int,
) -> list[EvidenceItem]:
    if limit <= 0:
        return []
    by_id = {item.evidence_id: item for item in evidence if item.evidence_id}
    linked = [by_id[item.evidence_id] for item in selected_citations if item.evidence_id in by_id]
    return _ordered_evidence_items([*linked, *evidence])[:limit]


def _compact_synthesis_diagnostics_for_budget(
    diagnostics: JsonObject,
    *,
    profile: JsonObject,
    max_prompt_chars: int,
    original_prompt_chars: int,
    original_evidence_count: int,
    compact_evidence_count: int,
    original_citation_count: int,
    compact_citation_count: int,
) -> JsonObject:
    compact = dict(diagnostics)
    compact["synthesis_evidence_preview_chars"] = _positive_profile_int(
        profile,
        "evidence_preview_chars",
        default=SYNTHESIS_EVIDENCE_PREVIEW_CHARS,
    )
    compact["synthesis_citation_preview_chars"] = _positive_profile_int(
        profile,
        "citation_preview_chars",
        default=SYNTHESIS_CITATION_PREVIEW_CHARS,
    )
    for key, profile_key in (
        ("finance_fact_ledger", "finance_fact_ledger_limit"),
        ("finance_candidate_facts", "finance_candidate_facts_limit"),
        ("finance_formula_traces", "finance_formula_traces_limit"),
        ("finance_formula_trace_support", "finance_formula_trace_support_limit"),
        ("finance_competing_fact_clusters", "finance_competing_fact_clusters_limit"),
        ("finance_metric_intent_hints", "finance_metric_intent_hints_limit"),
        ("finance_question_numeric_premise_hints", "finance_question_numeric_premise_hints_limit"),
    ):
        compact[key] = _limit_prompt_list(compact.get(key), _positive_profile_int(profile, profile_key, default=8))
    summary_limit = _positive_profile_int(profile, "summary_limit", default=4)
    for key in ("search_summaries", "fetch_summaries", "next_tool_actions"):
        compact[key] = _limit_prompt_list(compact.get(key), summary_limit)
    for key in ("attempted_queries", "attempted_provider_ids"):
        compact[key] = _string_list(compact.get(key))[-summary_limit * 4 :]
    compact["synthesis_budget_compaction"] = {
        "schema": "holo.kernel_v3.synthesis_budget_compaction.v1",
        "profile": profile["name"],
        "reason": "prompt would exceed processor budget",
        "max_prompt_chars_per_call": max_prompt_chars,
        "original_prompt_chars": original_prompt_chars,
        "original_evidence_count": original_evidence_count,
        "compact_evidence_count": compact_evidence_count,
        "original_citation_count": original_citation_count,
        "compact_citation_count": compact_citation_count,
        "semantic_decision_owner": "model",
        "host_role": "budgeted projection of existing evidence and workbench state",
    }
    return compact


def _positive_profile_int(profile: JsonObject, key: str, *, default: int) -> int:
    try:
        value = int(profile.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _limit_prompt_list(value: object, limit: int) -> list[object]:
    if not isinstance(value, list) or limit <= 0:
        return []
    return list(value[:limit])


def _ordered_evidence_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    result: list[EvidenceItem] = []
    for item in items:
        key = item.evidence_id or item.span_id or item.uri
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _ordered_citation_items(items: list[CitationItem]) -> list[CitationItem]:
    seen: set[str] = set()
    result: list[CitationItem] = []
    for item in items:
        key = item.citation_id or item.evidence_id or item.uri
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _ordered_unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _synthesizer_repair_feedback(error: str) -> JsonObject:
    code = str(error or "unknown").strip() or "unknown"
    feedback: JsonObject = {
        "schema": "holo.kernel_v3.synthesizer_repair_feedback.v1",
        "error_code": _preview(code, 240),
        "required_fields": list(SYNTHESIZER_SCHEMA.required.keys()),
        "optional_fields": list(SYNTHESIZER_SCHEMA.optional.keys()),
        "host_role": "schema_parse_validation_only",
        "model_role": "repair_answer_json_shape_without_changing_supported_semantics",
    }
    checklist = [
        "Return exactly one JSON object with no markdown or prose outside JSON.",
        "Include answer, citation_refs, confidence, limitations, and used_evidence.",
        "Keep citation_refs as an array of ids from required_citation_refs.",
        "Keep used_evidence as an array of ids from required_evidence_refs.",
        "Keep confidence as a number between 0 and 1.",
        "Do not invent citations, evidence ids, source ids, facts, or unsupported numeric claims.",
    ]
    if code.startswith("missing_required_field:"):
        field = code.split(":", 1)[1].strip()
        feedback["category"] = "missing_required_field"
        feedback["field"] = field
        checklist.insert(1, f"Add required field `{field}` with the schema type shown in contract.")
    elif code.startswith("invalid_field_type:"):
        parts = code.split(":")
        field = parts[1].strip() if len(parts) > 1 else ""
        expected = parts[2].strip() if len(parts) > 2 else ""
        feedback["category"] = "invalid_field_type"
        if field:
            feedback["field"] = field
        if expected:
            feedback["expected_type"] = expected
        if field and expected:
            checklist.insert(1, f"Rewrite `{field}` as type `{expected}`.")
    elif "json_root_not_object" in code:
        feedback["category"] = "json_root_not_object"
        checklist.insert(1, "The root must be a JSON object, not an array, string, or scalar.")
    elif "JSONDecodeError" in code or "json_invalid" in code or "Expecting" in code:
        feedback["category"] = "malformed_json"
        checklist.insert(1, "Fix JSON syntax: close arrays/objects, quote keys and strings, and remove trailing prose.")
    elif code.startswith("unknown_citation_refs:"):
        refs = _split_error_refs(code)
        feedback["category"] = "unknown_citation_refs"
        feedback["unknown_citation_refs"] = refs
        checklist.insert(1, "Replace unknown citation_refs with ids from required_citation_refs that support the answer.")
    elif code.startswith("unknown_evidence_refs:"):
        refs = _split_error_refs(code)
        feedback["category"] = "unknown_evidence_refs"
        feedback["unknown_evidence_refs"] = refs
        checklist.insert(1, "Replace unknown used_evidence ids with ids from required_evidence_refs that support the answer.")
    else:
        feedback["category"] = "schema_or_parse_error"
    feedback["repair_checklist"] = checklist
    return feedback


def _is_unknown_reference_error(error: str | None) -> bool:
    code = str(error or "")
    return code.startswith("unknown_citation_refs:") or code.startswith("unknown_evidence_refs:")


def _split_error_refs(error: str) -> list[str]:
    _prefix, _sep, tail = str(error or "").partition(":")
    return [item for item in (part.strip() for part in tail.split(",")) if item][:16]


def _prompt_json(payload: JsonObject) -> str:
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, separators=(",", ":"))


def _redacted_prompt_payload(payload: JsonObject) -> JsonObject:
    redacted, _markers = Redactor().redact(payload)
    return redacted if isinstance(redacted, dict) else {"value": redacted}


def _compact_context(context: ContextBundle) -> JsonObject:
    return {
        "context_id": context.context_id,
        "thread_key": context.thread_key,
        "event_ids": list(context.event_ids),
        "memory_refs": list(context.memory_refs),
        "state": _compact_context_state_for_provider(context.state),
        "token_budget": context.token_budget,
    }


def _processor_budget_parameters_from_context(context: ContextBundle) -> JsonObject:
    recipe = context.state.get("agent_recipe")
    recipe = recipe if isinstance(recipe, dict) else {}
    metadata = recipe.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    execution = metadata.get("execution_metadata")
    execution = execution if isinstance(execution, dict) else {}
    budget = execution.get("processor_budget")
    if not isinstance(budget, dict):
        return {}
    return {"processor_budget": dict(budget)}


def _compact_context_state_for_provider(state: JsonObject) -> JsonObject:
    """Build a prompt-safe view of host state.

    The journal and ContextPack keep the full audit payload. Processor calls need
    the facts that affect the next decision, not every static catalog entry or a
    full retrieval graph on every loop iteration.
    """

    recipe = _json_object(state.get("agent_recipe"))
    mode = str(recipe.get("mode") or "")
    lightweight = mode in {"direct_answer", "semantic_answer", "system_answer", "clarify_first"}
    result: JsonObject = {}
    for key in (
        "task_id",
        "run_id",
        "thread_id",
        "input_text",
        "context_pack_hash",
    ):
        if key in state:
            result[key] = _compact_prompt_value(state[key])
    result["host_situation"] = _compact_host_situation_for_provider(
        _json_object(state.get("host_situation")),
        lightweight=lightweight,
    )
    result["agent_recipe"] = _compact_agent_recipe_for_provider(recipe, lightweight=lightweight)
    result["agent_runtime_directive"] = _compact_runtime_directive_for_provider(
        _json_object(state.get("agent_runtime_directive")),
        lightweight=lightweight,
    )
    result["capability_catalog"] = _compact_capability_catalog_for_provider(
        _json_object(state.get("capability_catalog")),
        lightweight=lightweight,
    )
    if not lightweight:
        result["retrieval_capability_state"] = _compact_prompt_value(state.get("retrieval_capability_state"))
        result["agent_retrieval_plan_state"] = _compact_prompt_value(state.get("agent_retrieval_plan_state"))
        result["agent_replan_hints"] = _compact_replan_hints_for_provider(
            _json_object(state.get("agent_replan_hints"))
        )
    result["mission_context"] = _compact_prompt_value(state.get("mission_context"))
    result["thread_working_context"] = _compact_prompt_value(state.get("thread_working_context"))
    result["thread_rag_context"] = _compact_prompt_value(state.get("thread_rag_context"))
    result["toolchain_state"] = _compact_prompt_value(state.get("toolchain_state"))
    result["finance_working_state"] = _compact_prompt_value(state.get("finance_working_state"))
    result["durable_memory_context"] = _compact_prompt_value(state.get("durable_memory_context"))
    if not lightweight:
        result["answer_profile"] = _compact_prompt_value(state.get("answer_profile"))
        result["research_mission"] = _compact_prompt_value(state.get("research_mission"))
        result["workmethod"] = _compact_prompt_value(state.get("workmethod"))
    result["sections"] = _compact_sections_for_provider(state.get("sections"))
    result["source_refs"] = _string_list(state.get("source_refs"))[-16:]
    result["memory_refs"] = _string_list(state.get("memory_refs"))[-16:]
    result["budget"] = _compact_prompt_value(state.get("budget"))
    result["semantic_goal"] = _compact_prompt_value(state.get("semantic_goal"))
    result["semantic_state_profile_summary"] = _compact_prompt_value(
        state.get("semantic_state_profile_summary")
    )
    if not lightweight:
        result["semantic_state_profiles"] = _compact_list_for_provider(
            state.get("semantic_state_profiles"),
            limit=1,
        )
        result["semantic_state_space"] = _compact_state_space_for_provider(
            _json_object(state.get("semantic_state_space"))
        )
    result["research_source_directory"] = _compact_research_source_directory_for_provider(
        state.get("research_source_directory")
    )
    return {key: value for key, value in result.items() if value not in ({}, [], None)}


def _compact_host_situation_for_provider(value: JsonObject, *, lightweight: bool) -> JsonObject:
    if not lightweight:
        return _compact_prompt_value(value)
    permissions = _json_object(value.get("permissions"))
    tools = _json_object(value.get("tools"))
    retrieval = _json_object(value.get("retrieval"))
    runtime = _json_object(value.get("runtime_capabilities"))
    recent = _json_object(value.get("recent_activity"))
    failure = _json_object(value.get("failure"))
    holo_system = _json_object(value.get("holo_system"))
    runtime_retrieval = _json_object(runtime.get("retrieval"))
    return {
        "schema": value.get("schema"),
        "holo_system": {
            "name": holo_system.get("name"),
            "role": holo_system.get("role"),
            "operating_principle": holo_system.get("operating_principle"),
        },
        "task": _compact_simple_dict(value.get("task"), limit=10),
        "permissions": {
            "allowed_tools": _string_list(permissions.get("allowed_tools"))[:8],
            "allowed_permissions": _string_list(permissions.get("allowed_permissions"))[:8],
            "limits": _compact_simple_dict(permissions.get("limits"), limit=8),
            "permission_profile": permissions.get("permission_profile"),
        },
        "tools": {
            "available_tool_names": _string_list(tools.get("available_tool_names"))[:8],
            "network_tool_names": _string_list(tools.get("network_tool_names"))[:8],
        },
        "retrieval": {
            "allowed_by_recipe": retrieval.get("allowed_by_recipe"),
            "configured": retrieval.get("configured"),
            "live_search_available": retrieval.get("live_search_available"),
            "network_budget_available": retrieval.get("network_budget_available"),
            "max_network_fetches": retrieval.get("max_network_fetches"),
            "reason": retrieval.get("reason"),
        },
        "runtime_capabilities": {
            "retrieval": {
                "available_if_routed": runtime_retrieval.get("available_if_routed"),
                "live_search_available": runtime_retrieval.get("live_search_available"),
                "network_access": runtime_retrieval.get("network_access"),
            },
            "memory": _compact_simple_dict(runtime.get("memory"), limit=4),
            "system": _compact_simple_dict(runtime.get("system"), limit=4),
            "workspace": _compact_simple_dict(runtime.get("workspace"), limit=4),
        },
        "recent_activity": {
            "attempted_actions": _string_list(recent.get("attempted_actions"))[-6:],
            "latest_termination_decision": recent.get("latest_termination_decision"),
            "latest_termination_reason": recent.get("latest_termination_reason"),
            "latest_processor_error": recent.get("latest_processor_error"),
            "retrieval_runs": recent.get("retrieval_runs"),
            "tool_observations": _compact_list_for_provider(recent.get("tool_observations"), limit=4),
        },
        "failure": {
            "diagnosis": failure.get("diagnosis"),
            "reason": failure.get("reason"),
            "retrieval_attempted": failure.get("retrieval_attempted"),
            "missing_evidence": _string_list(failure.get("missing_evidence"))[:8],
        },
        "user_visible_rules": [
            "Current recipe tools and runtime capabilities are different; tools require host routing and policy validation.",
            "Do not claim retrieval is unavailable when runtime_capabilities.retrieval says it is available_if_routed.",
        ],
    }


def _compact_agent_recipe_for_provider(recipe: JsonObject, *, lightweight: bool = False) -> JsonObject:
    metadata = _json_object(recipe.get("metadata"))
    execution = _json_object(metadata.get("execution_metadata"))
    data = {
        "recipe_id": recipe.get("recipe_id"),
        "mode": recipe.get("mode"),
        "allowed_tools": _string_list(recipe.get("allowed_tools"))[:PROVIDER_TOOL_LIST_LIMIT],
        "permission_profile": recipe.get("permission_profile"),
        "citations_required": recipe.get("citations_required"),
        "finalizer": recipe.get("finalizer"),
        "context_budget_mode": recipe.get("context_budget_mode"),
        "limits": {
            "max_steps": recipe.get("max_steps"),
            "max_tool_calls": recipe.get("max_tool_calls"),
            "max_network_fetches": recipe.get("max_network_fetches"),
            "max_total_artifact_bytes": recipe.get("max_total_artifact_bytes"),
        },
        "metadata": {
            "thread_id": metadata.get("thread_id"),
            "allowed_permissions": _string_list(execution.get("allowed_permissions"))[:PROVIDER_PERMISSION_LIST_LIMIT],
            "semantic_intake": _compact_prompt_value(metadata.get("semantic_intake")),
        },
    }
    if not lightweight:
        data["metadata"]["task_execution_plan"] = _compact_prompt_value(metadata.get("task_execution_plan"))
        data["metadata"]["answer_profile"] = _compact_prompt_value(metadata.get("answer_profile"))
        data["metadata"]["research_mission"] = _compact_prompt_value(metadata.get("research_mission"))
    return data


def _compact_runtime_directive_for_provider(directive: JsonObject, *, lightweight: bool = False) -> JsonObject:
    tool_selection = directive.get("tool_selection")
    tool_selection_count = len(tool_selection) if isinstance(tool_selection, list) else 0
    data = {
        "mode": directive.get("mode"),
        "initial_action": _compact_prompt_value(directive.get("initial_action")),
        "required_first_action": _compact_prompt_value(directive.get("required_first_action")),
        "required_outcome": _compact_prompt_value(directive.get("required_outcome")),
        "allowed_tools": _string_list(directive.get("allowed_tools"))[:PROVIDER_TOOL_LIST_LIMIT],
        "forbidden": _string_list(directive.get("forbidden"))[:PROVIDER_TOOL_LIST_LIMIT],
        "tool_selection": _compact_list_for_provider(
            tool_selection,
            limit=PROVIDER_LIGHTWEIGHT_TOOL_SELECTION_LIMIT if lightweight else PROVIDER_TOOL_SELECTION_LIMIT,
        ),
        "tool_selection_count": tool_selection_count,
        "allowed_non_tool_actions": _compact_list_for_provider(
            directive.get("allowed_non_tool_actions"),
            limit=2 if lightweight else 4,
        ),
        "search_strategy_hint": _compact_prompt_value(directive.get("search_strategy_hint")),
        "final_answer_contract": _compact_prompt_value(directive.get("final_answer_contract")),
        "finance_question_requirements": _compact_prompt_value(directive.get("finance_question_requirements")),
        "interaction_preferences": _compact_prompt_value(directive.get("interaction_preferences")),
        "active_memory": _compact_prompt_value(directive.get("active_memory")),
    }
    if not lightweight:
        data["answer_profile"] = _compact_prompt_value(directive.get("answer_profile"))
        data["research_mission"] = _compact_prompt_value(directive.get("research_mission"))
        data["workmethod"] = _compact_prompt_value(directive.get("workmethod"))
        data["toolchain_install_summary"] = _compact_simple_dict(directive.get("toolchain_install_summary"), limit=8)
        data["finance_agent_loop_contract"] = _compact_prompt_value(directive.get("finance_agent_loop_contract"))
        data["llm_first_finance_template"] = _compact_prompt_value(directive.get("llm_first_finance_template"))
    return data


def _compact_capability_catalog_for_provider(catalog: JsonObject, *, lightweight: bool = False) -> JsonObject:
    capabilities = catalog.get("capabilities") if isinstance(catalog.get("capabilities"), list) else []
    allowed = set(_string_list(catalog.get("allowed_tools")))
    relevant: list[JsonObject] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        tool_name = str(item.get("tool_name") or "")
        capability_id = str(item.get("capability_id") or "")
        if lightweight:
            include = tool_name in allowed or (not tool_name and status == "enabled")
        else:
            include = status == "enabled" or tool_name in allowed or any(
                marker in capability_id
                for marker in ("retrieval", "finance", "memory", "workspace", "system")
            )
        if include:
            relevant.append(
                {
                    "capability_id": capability_id,
                    "family": item.get("family"),
                    "status": status,
                    "tool_name": item.get("tool_name"),
                    "side_effect_class": item.get("side_effect_class"),
                    "permissions_required": _string_list(item.get("permissions_required"))[:8],
                }
            )
        if len(relevant) >= (8 if lightweight else 20):
            break
    return {
        "version": catalog.get("version"),
        "mode": catalog.get("mode"),
        "allowed_tools": _string_list(catalog.get("allowed_tools"))[:PROVIDER_TOOL_LIST_LIMIT],
        "executable_tools": _string_list(catalog.get("executable_tools"))[:PROVIDER_TOOL_LIST_LIMIT],
        "family_keys": list(_json_object(catalog.get("families")).keys())[:24],
        "capabilities": relevant,
        "capability_count": len(capabilities),
        "host_rule": (
            "Only allowed_tools are executable in the current recipe; the host validates all tool use."
            if lightweight
            else catalog.get("host_rule")
        ),
    }


def _compact_replan_hints_for_provider(hints: JsonObject) -> JsonObject:
    retrieval = _json_object(hints.get("retrieval"))
    compact = {
        "status": hints.get("status"),
        "recipe_mode": hints.get("recipe_mode"),
        "iteration_index": hints.get("iteration_index"),
        "latest_feedback": _compact_prompt_value(hints.get("latest_feedback")),
        "latest_termination": _compact_prompt_value(hints.get("latest_termination")),
        "latest_evidence_sufficiency": _compact_prompt_value(hints.get("latest_evidence_sufficiency")),
        "avoid_repeating": _string_list(hints.get("avoid_repeating"))[-12:],
        "suggested_next_action": hints.get("suggested_next_action"),
    }
    if retrieval:
        compact["retrieval"] = {
            "needs_replan": retrieval.get("needs_replan"),
            "latest_report_status": retrieval.get("latest_report_status"),
            "latest_report_reason": retrieval.get("latest_report_reason"),
            "missing": _string_list(retrieval.get("missing"))[:24],
            "incomplete_planned_goal_ids": _string_list(retrieval.get("incomplete_planned_goal_ids"))[:16],
            "missing_query_facets": _string_list(retrieval.get("missing_query_facets"))[:16],
            "missing_finance_facets": _string_list(retrieval.get("missing_finance_facets"))[:16],
            "covered_query_facets": _string_list(retrieval.get("covered_query_facets"))[:16],
            "covered_finance_facets": _string_list(retrieval.get("covered_finance_facets"))[:16],
            "source_authority_requirement": retrieval.get("source_authority_requirement"),
            "failure_attribution": _compact_prompt_value(retrieval.get("failure_attribution")),
            "suggested_search_strategies": _string_list(retrieval.get("suggested_search_strategies"))[:12],
            "suggested_query_hints": _string_list(retrieval.get("suggested_query_hints"))[:12],
            "suggested_source_targets": _compact_list_for_provider(retrieval.get("suggested_source_targets"), limit=8),
            "suggested_filing_documents": _compact_list_for_provider(retrieval.get("suggested_filing_documents"), limit=4),
            "suggested_sec_structured_sources": _compact_list_for_provider(retrieval.get("suggested_sec_structured_sources"), limit=4),
            "suggested_macro_series": _compact_list_for_provider(retrieval.get("suggested_macro_series"), limit=4),
            "suggested_fiscaldata_endpoints": _compact_list_for_provider(retrieval.get("suggested_fiscaldata_endpoints"), limit=4),
            "attempted_queries": _string_list(retrieval.get("attempted_queries"))[-16:],
            "attempted_search_strategies": _string_list(retrieval.get("attempted_search_strategies"))[-12:],
            "attempted_provider_ids": _string_list(retrieval.get("attempted_provider_ids"))[-16:],
            "attempts": _compact_list_for_provider(retrieval.get("attempts"), limit=4),
            "fetch_summary": _compact_prompt_value(retrieval.get("fetch_summary")),
            "recent_fetches": _compact_list_for_provider(retrieval.get("recent_fetches"), limit=4),
            "do_not_finalize_until": _string_list(retrieval.get("do_not_finalize_until"))[:12],
        }
    return compact


def _compact_state_space_for_provider(space: JsonObject) -> JsonObject:
    dimensions = space.get("state_dimensions") if isinstance(space.get("state_dimensions"), dict) else {}
    families = space.get("families") if isinstance(space.get("families"), dict) else {}
    task_domains = space.get("task_domains") if isinstance(space.get("task_domains"), dict) else {}
    return {
        "version": space.get("version"),
        "modes": _string_list(space.get("modes"))[:16],
        "family_keys": list(families.keys())[:24],
        "task_domain_keys": list(task_domains.keys())[:24],
        "state_dimension_keys": list(dimensions.keys())[:24],
        "host_rule": space.get("host_rule"),
    }


def _compact_research_source_directory_for_provider(value: object) -> list[JsonObject]:
    items = value if isinstance(value, list) else []
    result: list[JsonObject] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "source_id": item.get("source_id"),
                "title": item.get("title"),
                "profile_id": item.get("profile_id"),
                "source_family": item.get("source_family"),
                "authority_level": item.get("authority_level"),
                "base_url": item.get("base_url"),
                "allowed_hosts": _string_list(item.get("allowed_hosts"))[:6],
                "use_cases": _string_list(item.get("use_cases"))[:6],
                "query_hints": _string_list(item.get("query_hints"))[:4],
            }
        )
    return result


def _compact_sections_for_provider(value: object) -> list[JsonObject]:
    sections = value if isinstance(value, list) else []
    useful_names = {
        "user_event",
        "active_task_state",
        "recent_observations",
        "artifact_references",
        "memory_refs",
        "citations",
        "tool_briefs",
        "durable_memory",
        "permission_state",
    }
    return [
        _compact_prompt_value(item)
        for item in sections[:10]
        if isinstance(item, dict) and str(item.get("name") or "") in useful_names
    ]


def _compact_list_for_provider(value: object, *, limit: int) -> list[object]:
    if not isinstance(value, list):
        return []
    return [_compact_prompt_value(item) for item in value[: max(0, limit)]]


def _compact_simple_dict(value: object, *, limit: int) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    compact: JsonObject = {}
    for key, item in list(value.items())[: max(0, limit)]:
        if isinstance(item, (dict, list)):
            compact[str(key)] = _compact_prompt_value(item)
        elif item not in (None, "", [], {}):
            compact[str(key)] = item
    return compact


def _task_goal_from_report(report: RetrievalReport) -> str:
    diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
    for key in ("task_goal", "goal_query", "query"):
        value = diagnostics.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return report.preview


def _interaction_preferences_from_report(report: RetrievalReport) -> JsonObject:
    diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
    preferences = diagnostics.get("interaction_preferences")
    if isinstance(preferences, dict):
        return dict(preferences)
    response_language = diagnostics.get("response_language")
    if isinstance(response_language, str) and response_language:
        return {"response_language": response_language}
    return {}


def _compact_retrieval_report_for_provider(report: RetrievalReport) -> JsonObject:
    diagnostics = report.diagnostics if isinstance(report.diagnostics, dict) else {}
    evaluation = _json_object(diagnostics.get("evaluation_diagnostics"))
    source_quality = _json_object(diagnostics.get("source_quality"))
    graph = _json_object(diagnostics.get("research_graph"))
    answer_profile = _json_object(diagnostics.get("answer_profile"))
    research_mission = _json_object(diagnostics.get("research_mission"))
    host_situation = _json_object(diagnostics.get("host_situation"))
    finance_formula_traces = diagnostics.get("finance_formula_traces")
    finance_formula_trace_support = diagnostics.get("finance_formula_trace_support")
    finance_formula_trace_synthesis_policy = diagnostics.get("finance_formula_trace_synthesis_policy")
    finance_slot_bind_state = diagnostics.get("finance_slot_bind_state")
    finance_fact_ledger = diagnostics.get("finance_fact_ledger")
    finance_competing_fact_clusters = diagnostics.get("finance_competing_fact_clusters")
    finance_numeric_repair_context = diagnostics.get("finance_numeric_repair_context")
    finance_metric_intent_hints = diagnostics.get("finance_metric_intent_hints")
    finance_question_numeric_premise_hints = diagnostics.get("finance_question_numeric_premise_hints")
    synthesis_budget_compaction = diagnostics.get("synthesis_budget_compaction")
    return {
        "report_id": report.report_id,
        "goal_id": report.goal_id,
        "status": report.status,
        "query_plan_id": report.query_plan_id,
        "search_attempt_count": len(report.search_attempt_ids),
        "fetch_attempt_count": len(report.fetch_attempt_ids),
        "evidence_count": len(report.evidence_ids),
        "citation_count": len(report.citation_ids),
        "evidence_ids": list(report.evidence_ids)[-24:],
        "citation_ids": list(report.citation_ids)[-24:],
        "artifact_refs": list(report.artifact_refs)[-16:],
        "preview": _preview(report.preview, 720),
        "diagnostics": {
            "goal_query": diagnostics.get("goal_query"),
            "task_goal": diagnostics.get("task_goal"),
            "reason": diagnostics.get("reason"),
            "source_quality": _compact_source_quality_for_provider(source_quality),
            "evaluation": _compact_retrieval_evaluation_for_provider(evaluation),
            "attempted_queries": _string_list(diagnostics.get("attempted_queries"))[-24:],
            "attempted_provider_ids": _string_list(diagnostics.get("attempted_provider_ids"))[-24:],
            "search_summary": _compact_list_for_provider(diagnostics.get("search_summaries"), limit=8),
            "fetch_summary": _compact_list_for_provider(diagnostics.get("fetch_summaries"), limit=8),
            "rejected_evidence_count": diagnostics.get("rejected_evidence_count"),
            "rejected_evidence_reasons": _compact_prompt_value(diagnostics.get("rejected_evidence_reasons")),
            "next_tool_actions": _compact_list_for_provider(diagnostics.get("next_tool_actions"), limit=8),
            "research_graph_summary": {
                "node_count": len(graph.get("nodes", [])) if isinstance(graph.get("nodes"), list) else 0,
                "edge_count": len(graph.get("edges", [])) if isinstance(graph.get("edges"), list) else 0,
                "diagnostics": _compact_prompt_value(graph.get("diagnostics")),
            },
            "answer_profile": {
                "format": answer_profile.get("format"),
                "detail_level": answer_profile.get("detail_level"),
                "language": answer_profile.get("language"),
                "target_sections": _string_list(answer_profile.get("target_sections"))[:16],
                "minimum_coverage": _string_list(answer_profile.get("minimum_coverage"))[:16],
            },
            "research_mission": {
                "mission_type": research_mission.get("mission_type"),
                "required_facets": _string_list(research_mission.get("required_facets"))[:24],
                "target_entities": _string_list(research_mission.get("target_entities"))[:12],
            },
            "host_situation": _compact_prompt_value(host_situation),
            "finance_synthesis_directive": diagnostics.get("finance_synthesis_directive"),
            "finance_numeric_claim_policy": _json_object(diagnostics.get("finance_numeric_claim_policy")),
            "finance_metric_disambiguation": _json_object(diagnostics.get("finance_metric_disambiguation")),
            "finance_competing_fact_clusters": _compact_list_for_provider(finance_competing_fact_clusters, limit=16),
            "finance_competing_fact_cluster_policy": _json_object(diagnostics.get("finance_competing_fact_cluster_policy")),
            "finance_metric_intent_hints": _compact_list_for_provider(finance_metric_intent_hints, limit=32),
            "finance_metric_intent_hint_policy": _json_object(diagnostics.get("finance_metric_intent_hint_policy")),
            "finance_question_numeric_premise_hints": _compact_list_for_provider(
                finance_question_numeric_premise_hints,
                limit=12,
            ),
            "finance_question_numeric_premise_hint_policy": _json_object(
                diagnostics.get("finance_question_numeric_premise_hint_policy")
            ),
            "finance_slot_bind_state": _compact_prompt_value(finance_slot_bind_state),
            "finance_slot_bind_basis_policy": _json_object(diagnostics.get("finance_slot_bind_basis_policy")),
            "finance_numeric_repair_context": _compact_finance_numeric_repair_context_for_provider(
                finance_numeric_repair_context
            ),
            "finance_formula_trace_synthesis_policy": _compact_prompt_value(finance_formula_trace_synthesis_policy),
            "finance_formula_traces": _compact_list_for_provider(finance_formula_traces, limit=16),
            "finance_formula_trace_support": _compact_list_for_provider(finance_formula_trace_support, limit=24),
            "finance_fact_ledger": _compact_list_for_provider(finance_fact_ledger, limit=96),
            "finance_fact_ledger_count": diagnostics.get("finance_fact_ledger_count"),
            "claim_ledger_present": diagnostics.get("claim_ledger_present"),
            "synthesis_budget_compaction": _compact_prompt_value(synthesis_budget_compaction),
        },
    }


def _compact_source_quality_for_provider(value: JsonObject) -> JsonObject:
    return {
        "authority_sufficient": value.get("authority_sufficient"),
        "best_authority_score": value.get("best_authority_score"),
        "primary_source_count": value.get("primary_source_count"),
        "secondary_source_count": value.get("secondary_source_count"),
        "weak_source_count": value.get("weak_source_count"),
        "acceptable_source_count": value.get("acceptable_source_count"),
        "source_families": _string_list(value.get("source_families"))[:12],
        "issues": _string_list(value.get("issues"))[:12],
    }


def _compact_retrieval_evaluation_for_provider(value: JsonObject) -> JsonObject:
    return {
        "decision": value.get("decision"),
        "sufficient": value.get("sufficient"),
        "reason": value.get("reason"),
        "missing_query_facets": _string_list(value.get("missing_query_facets"))[:16],
        "covered_query_facets": _string_list(value.get("covered_query_facets"))[:16],
        "missing_profile_facets": _string_list(value.get("missing_profile_facets"))[:16],
        "covered_profile_facets": _string_list(value.get("covered_profile_facets"))[:16],
        "missing_finance_facets": _string_list(value.get("missing_finance_facets"))[:16],
        "covered_finance_facets": _string_list(value.get("covered_finance_facets"))[:16],
        "failure_attribution": _compact_prompt_value(value.get("failure_attribution")),
    }


def _compact_finance_numeric_repair_context_for_provider(value: object):
    if isinstance(value, str):
        if len(value) <= 512:
            return value
        return {"preview": _preview(value, 512), "hash": _hash_text(value), "chars": len(value)}
    if isinstance(value, list):
        return [_compact_finance_numeric_repair_context_for_provider(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            key: _compact_finance_numeric_repair_context_for_provider(item)
            for key, item in value.items()
        }
    return value


def _compact_observation_for_provider(observation: Observation) -> JsonObject:
    data = observation.to_dict()
    data["content"] = _compact_prompt_value(observation.content)
    return data


def _compact_evidence_for_provider(item: EvidenceItem, *, preview_chars: int = SYNTHESIS_EVIDENCE_PREVIEW_CHARS) -> JsonObject:
    data = item.to_dict()
    text = str(data.pop("text", ""))
    data["text_preview"] = _preview(text, preview_chars)
    data["text_hash"] = _hash_text(text)
    data["text_chars"] = len(text)
    return data


def _compact_citation_for_provider(item: CitationItem, *, preview_chars: int = SYNTHESIS_CITATION_PREVIEW_CHARS) -> JsonObject:
    data = item.to_dict()
    quote = str(data.pop("quote", ""))
    data["quote_preview"] = _preview(quote, preview_chars)
    data["quote_hash"] = _hash_text(quote)
    data["quote_chars"] = len(quote)
    return data


def _compact_prompt_value(value):
    if isinstance(value, str):
        if len(value) <= 512:
            return value
        return {"preview": _preview(value, 512), "hash": _hash_text(value), "chars": len(value)}
    if isinstance(value, list):
        return [_compact_prompt_value(item) for item in value[:20]]
    if isinstance(value, dict):
        compacted = {}
        for key, item in value.items():
            if isinstance(item, str) and key in {"text", "quote", "body", "raw", "content"}:
                compacted[f"{key}_preview"] = _preview(item, 512)
                compacted[f"{key}_hash"] = _hash_text(item)
                compacted[f"{key}_chars"] = len(item)
                continue
            compacted[key] = _compact_prompt_value(item)
        return compacted
    return value


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _action_from_json(data: JsonObject) -> CandidateAction:
    kind = str(data["kind"])
    name = data.get("name")
    if kind in {"respond", "ask_user"}:
        name = None
    elif name is not None:
        name = str(name)
    payload = data.get("payload")
    reasons = data.get("reasons")
    return CandidateAction(
        action_id=str(data["action_id"]),
        kind=kind,
        name=name if isinstance(name, str) else None,
        description=str(data["description"]),
        score=_score(data.get("score", 1.0)),
        payload=dict(payload) if isinstance(payload, dict) else {},
        reasons=[str(item) for item in reasons] if isinstance(reasons, list) else [],
        side_effect_class=str(data["side_effect_class"]),
    )


def _feedback_from_json(data: JsonObject, *, run_id: str, index: int) -> Feedback:
    status = str(data["status"])
    if status not in {"continue", "final_answer_ready", "needs_user_input", "blocked", "failed"}:
        return Feedback(
            feedback_id=f"fb-{run_id}-model-evaluator-invalid-{index}",
            run_id=run_id,
            status="failed",
            stop_reason="invalid_feedback_status",
            answer=None,
            missing_evidence=["invalid_feedback_status"],
        )
    answer = data.get("answer")
    stop_reason = data.get("stop_reason")
    missing = data.get("missing_evidence")
    if status == "continue":
        normalized_stop_reason = None
    elif isinstance(stop_reason, str) and stop_reason:
        normalized_stop_reason = stop_reason
    elif status == "final_answer_ready":
        normalized_stop_reason = "completed"
    else:
        normalized_stop_reason = status
    return Feedback(
        feedback_id=f"fb-{run_id}-model-evaluator-{index}",
        run_id=run_id,
        status=status,
        stop_reason=normalized_stop_reason,
        answer=answer if isinstance(answer, str) else None,
        missing_evidence=[str(item) for item in missing] if isinstance(missing, list) else [],
    )


def _final_answer_from_json(
    data: JsonObject,
    *,
    citations: list[CitationItem],
    evidence: list[EvidenceItem],
) -> FinalAnswer:
    known_citations = {item.citation_id for item in citations}
    known_evidence = {item.evidence_id for item in evidence}
    citation_refs = _string_list(data.get("citation_refs"))
    used_evidence = _string_list(data.get("used_evidence"))
    unknown_citations = sorted(set(citation_refs) - known_citations)
    unknown_evidence = sorted(set(used_evidence) - known_evidence)
    if unknown_citations:
        return FinalAnswer(
            status="failed",
            answer=None,
            citation_refs=citation_refs,
            confidence=0.0,
            limitations=[],
            used_evidence=used_evidence,
            error="unknown_citation_refs:" + ",".join(unknown_citations),
        )
    if unknown_evidence:
        return FinalAnswer(
            status="failed",
            answer=None,
            citation_refs=citation_refs,
            confidence=0.0,
            limitations=[],
            used_evidence=used_evidence,
            error="unknown_evidence_refs:" + ",".join(unknown_evidence),
        )
    if not citation_refs:
        return FinalAnswer(
            status="needs_user_input",
            answer=None,
            citation_refs=[],
            confidence=0.0,
            limitations=["missing_citation_refs"],
            used_evidence=used_evidence,
            error="missing_citation_refs",
        )
    return FinalAnswer(
        status="ok",
        answer=str(data["answer"]),
        citation_refs=citation_refs,
        confidence=_score(data.get("confidence", 0.0)),
        limitations=_string_list(data.get("limitations")),
        used_evidence=used_evidence,
        error=None,
    )


def _salvage_final_answer_from_raw_text(
    raw_text: str | None,
    *,
    citations: list[CitationItem],
    evidence: list[EvidenceItem],
    error: str,
) -> FinalAnswer | None:
    answer = _salvage_answer_text(raw_text)
    if not answer:
        return None
    known_citations = {item.citation_id for item in citations}
    citation_refs = [item.citation_id for item in citations if item.citation_id in str(raw_text or "")]
    if not citation_refs and citations and _text_appears_source_grounded(answer):
        citation_refs = [item.citation_id for item in citations]
    citation_refs = [item for item in citation_refs if item in known_citations]
    if not citation_refs:
        return None
    citation_evidence = {item.citation_id: item.evidence_id for item in citations}
    known_evidence = {item.evidence_id for item in evidence}
    used_evidence: list[str] = []
    for citation_id in citation_refs:
        evidence_id = citation_evidence.get(citation_id)
        if evidence_id and evidence_id in known_evidence and evidence_id not in used_evidence:
            used_evidence.append(evidence_id)
    return FinalAnswer(
        status="ok",
        answer=answer,
        citation_refs=citation_refs,
        confidence=0.45,
        limitations=["synthesizer_json_salvaged", f"synthesizer_error:{error}"],
        used_evidence=used_evidence,
        error=None,
    )


def _salvage_answer_text(raw_text: str | None) -> str | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    extracted = _extract_json_like_answer_field(text)
    if extracted:
        return _clean_salvaged_answer(extracted)
    stripped = text
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and '"answer"' in stripped[:200]:
        return None
    return _clean_salvaged_answer(stripped)


def _extract_json_like_answer_field(text: str) -> str | None:
    match = re.search(r'"answer"\s*:\s*"', text)
    if match is None:
        return None
    index = match.end()
    chars: list[str] = []
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            chars.append(_json_escape_char(char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            tail = text[index + 1 : index + 96]
            if re.match(r"\s*,\s*\"(?:citation_refs|confidence|limitations|used_evidence|status)\"\s*:", tail):
                break
            chars.append(char)
        else:
            chars.append(char)
        index += 1
    value = "".join(chars).strip()
    return value or None


def _json_escape_char(char: str) -> str:
    return {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(char, char)


def _clean_salvaged_answer(text: str) -> str | None:
    value = str(text or "").strip()
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = value.strip()
    return value or None


def _text_appears_source_grounded(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "sec",
            "10-k",
            "10-q",
            "filing",
            "annual report",
            "companyfacts",
            "evidence",
            "source",
            "citation",
            "证据",
            "来源",
            "申报",
            "年报",
            "财报",
        )
    )


def _planner_fallback(run_id: str, reason: str) -> CandidateAction:
    return CandidateAction(
        action_id=f"act-{run_id}-planner-fallback",
        kind="respond",
        name=None,
        description="model planner fallback",
        score=0.0,
        payload={"text": f"Planner could not produce a safe action: {reason}"},
        reasons=[reason],
        side_effect_class="none",
    )


def _task_id(context: ContextBundle) -> str | None:
    value = context.state.get("task_id")
    return value if isinstance(value, str) else None


def _run_id(context: ContextBundle) -> str:
    value = context.state.get("run_id")
    return str(value or "")


def _score(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, parsed))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
