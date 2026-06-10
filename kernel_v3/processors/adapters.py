from __future__ import annotations

import hashlib
import json

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
        outcome = self.fabric.run_json(
            task_type="synthesizer.answer",
            task_id=task_id,
            run_id=run_id,
            context_id=context_id,
            prompt=_synthesizer_prompt(report, evidence, citations, retry_instruction=retry_instruction),
            schema=SYNTHESIZER_SCHEMA,
            provider=self.provider,
            model=self.model,
            parameters={
                "adapter": "Synthesizer",
                "retrieval_report_id": report.report_id,
                **budget_parameters,
                **({"retry_reason": "answer_quality"} if retry_instruction else {}),
            },
        )
        if outcome.parsed is None:
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-json-repair",
                prompt=_synthesizer_prompt(
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
                ),
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": report.report_id,
                    "repair_reason": "invalid_json",
                    **budget_parameters,
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=citations, evidence=evidence)
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
        if answer.error == "missing_citation_refs" and citations:
            retry = self.fabric.run_json(
                task_type="synthesizer.answer",
                task_id=task_id,
                run_id=run_id,
                context_id=f"{context_id}-citation-repair",
                prompt=_synthesizer_prompt(
                    report,
                    evidence,
                    citations,
                    retry_instruction=(
                        "Previous synthesizer output omitted citation_refs. "
                        "Return a corrected JSON object. citation_refs must include one or more ids "
                        "from required_citation_refs, and used_evidence must include matching evidence ids."
                    ),
                ),
                schema=SYNTHESIZER_SCHEMA,
                provider=self.provider,
                model=self.model,
                parameters={
                    "adapter": "Synthesizer",
                    "retrieval_report_id": report.report_id,
                    "repair_reason": "missing_citation_refs",
                    **budget_parameters,
                },
            )
            if retry.parsed is not None:
                return _final_answer_from_json(retry.parsed, citations=citations, evidence=evidence)
        return answer


def _planner_prompt(context: ContextBundle, feedback: Feedback | None) -> str:
    payload = {
        "contract": PLANNER_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "feedback": feedback.to_dict() if feedback is not None else None,
    }
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


def _evaluator_prompt(context: ContextBundle, observation: Observation) -> str:
    payload = {
        "contract": EVALUATOR_PROMPT_CONTRACT,
        "context": _compact_context(context),
        "observation": _compact_observation_for_provider(observation),
    }
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


def _synthesizer_prompt(
    report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    *,
    retry_instruction: str | None = None,
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
    payload = {
        "contract": SYNTHESIZER_PROMPT_CONTRACT,
        "task_goal": _task_goal_from_report(report),
        "interaction_preferences": preferences,
        "response_language": preferences.get("response_language"),
        "answer_profile": _json_object(report.diagnostics.get("answer_profile")) if isinstance(report.diagnostics, dict) else {},
        "research_mission": _json_object(report.diagnostics.get("research_mission")) if isinstance(report.diagnostics, dict) else {},
        "host_situation": _json_object(report.diagnostics.get("host_situation")) if isinstance(report.diagnostics, dict) else {},
        "required_citation_refs": [item.citation_id for item in citations],
        "required_evidence_refs": [item.evidence_id for item in evidence],
        "answer_requirements": [
            "Answer every explicit question or subtask in task_goal when supported by provided evidence.",
            "If any part is unsupported, include it in limitations.",
            "Use only provided citation_refs and evidence ids.",
            "If required_citation_refs is non-empty, citation_refs must include at least one provided citation id.",
            "Use the response_language preference as the default user-visible language unless the user explicitly requested another language.",
            "If answer_profile.format is detailed_report, deep_report, or memo, write a sectioned report that covers answer_profile.target_sections and answer_profile.minimum_coverage.",
            "If the evidence does not support a required section, include that section with a clear limitation instead of collapsing the whole answer into a short summary.",
            "For finance research, distinguish facts, source-backed metrics, analysis, risks, and limitations; do not rely on generic product or encyclopedia pages as if they were financial statements.",
            "For finance calculations, if retrieval_report.diagnostics.finance_formula_traces is present, use those host calculator results as authoritative computed values and do not recompute them mentally.",
            "For finance answers, every material numeric claim must be supported by retrieval_report.diagnostics.finance_formula_traces, finance fact or claim ledger evidence, or an explicit assumption label. Omit unsupported numbers or move them into limitations; do not invent bridging figures, multiples, growth rates, margins, or dates.",
            "Use host_situation as the source of truth for whether live retrieval, tools, permissions, and finance research are available.",
            "Do not say live retrieval, network access, or finance research is unavailable unless host_situation.retrieval or host_situation.failure says so.",
            "If host_situation says retrieval was attempted but evidence is insufficient, describe the real failure as search/fetch/extraction/citation/coverage quality instead of a permission problem.",
        ],
        "retrieval_report": _compact_retrieval_report_for_provider(report),
        "evidence": [_compact_evidence_for_provider(item, preview_chars=evidence_preview_chars) for item in evidence],
        "citations": [_compact_citation_for_provider(item, preview_chars=citation_preview_chars) for item in citations],
    }
    if retry_instruction:
        payload["retry_instruction"] = retry_instruction
    return json.dumps(_redacted_prompt_payload(payload), ensure_ascii=False, sort_keys=True)


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
    result["host_situation"] = _compact_prompt_value(state.get("host_situation"))
    result["agent_recipe"] = _compact_agent_recipe_for_provider(_json_object(state.get("agent_recipe")))
    result["agent_runtime_directive"] = _compact_runtime_directive_for_provider(
        _json_object(state.get("agent_runtime_directive"))
    )
    result["capability_catalog"] = _compact_capability_catalog_for_provider(
        _json_object(state.get("capability_catalog"))
    )
    result["retrieval_capability_state"] = _compact_prompt_value(state.get("retrieval_capability_state"))
    result["agent_retrieval_plan_state"] = _compact_prompt_value(state.get("agent_retrieval_plan_state"))
    result["agent_replan_hints"] = _compact_replan_hints_for_provider(
        _json_object(state.get("agent_replan_hints"))
    )
    result["mission_context"] = _compact_prompt_value(state.get("mission_context"))
    result["thread_working_context"] = _compact_prompt_value(state.get("thread_working_context"))
    result["thread_rag_context"] = _compact_prompt_value(state.get("thread_rag_context"))
    result["durable_memory_context"] = _compact_prompt_value(state.get("durable_memory_context"))
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


def _compact_agent_recipe_for_provider(recipe: JsonObject) -> JsonObject:
    metadata = _json_object(recipe.get("metadata"))
    execution = _json_object(metadata.get("execution_metadata"))
    return {
        "recipe_id": recipe.get("recipe_id"),
        "mode": recipe.get("mode"),
        "allowed_tools": _string_list(recipe.get("allowed_tools"))[:16],
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
            "allowed_permissions": _string_list(execution.get("allowed_permissions"))[:16],
            "semantic_intake": _compact_prompt_value(metadata.get("semantic_intake")),
            "task_execution_plan": _compact_prompt_value(metadata.get("task_execution_plan")),
            "answer_profile": _compact_prompt_value(metadata.get("answer_profile")),
            "research_mission": _compact_prompt_value(metadata.get("research_mission")),
        },
    }


def _compact_runtime_directive_for_provider(directive: JsonObject) -> JsonObject:
    return {
        "mode": directive.get("mode"),
        "initial_action": _compact_prompt_value(directive.get("initial_action")),
        "required_first_action": _compact_prompt_value(directive.get("required_first_action")),
        "required_outcome": _compact_prompt_value(directive.get("required_outcome")),
        "allowed_tools": _string_list(directive.get("allowed_tools"))[:16],
        "forbidden": _string_list(directive.get("forbidden"))[:16],
        "tool_selection": _compact_list_for_provider(
            directive.get("tool_selection"),
            limit=6,
        ),
        "allowed_non_tool_actions": _compact_list_for_provider(
            directive.get("allowed_non_tool_actions"),
            limit=4,
        ),
        "search_strategy_hint": _compact_prompt_value(directive.get("search_strategy_hint")),
        "answer_profile": _compact_prompt_value(directive.get("answer_profile")),
        "final_answer_contract": _compact_prompt_value(directive.get("final_answer_contract")),
        "interaction_preferences": _compact_prompt_value(directive.get("interaction_preferences")),
        "research_mission": _compact_prompt_value(directive.get("research_mission")),
        "active_memory": _compact_prompt_value(directive.get("active_memory")),
        "workmethod": _compact_prompt_value(directive.get("workmethod")),
    }


def _compact_capability_catalog_for_provider(catalog: JsonObject) -> JsonObject:
    capabilities = catalog.get("capabilities") if isinstance(catalog.get("capabilities"), list) else []
    allowed = set(_string_list(catalog.get("allowed_tools")))
    relevant: list[JsonObject] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        tool_name = str(item.get("tool_name") or "")
        capability_id = str(item.get("capability_id") or "")
        if status == "enabled" or tool_name in allowed or any(
            marker in capability_id
            for marker in ("retrieval", "finance", "memory", "workspace", "system")
        ):
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
        if len(relevant) >= 20:
            break
    return {
        "version": catalog.get("version"),
        "mode": catalog.get("mode"),
        "allowed_tools": _string_list(catalog.get("allowed_tools"))[:16],
        "executable_tools": _string_list(catalog.get("executable_tools"))[:16],
        "family_keys": list(_json_object(catalog.get("families")).keys())[:24],
        "capabilities": relevant,
        "capability_count": len(capabilities),
        "host_rule": catalog.get("host_rule"),
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
            "finance_formula_traces": _compact_list_for_provider(finance_formula_traces, limit=16),
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
