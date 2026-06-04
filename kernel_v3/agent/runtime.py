from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from kernel_v3.capabilities import capability_catalog, semantic_state_space_catalog
from kernel_v3.agent.contracts import (
    AgentRuntimeResult,
    FailureReport,
    FinalAnswer,
    SemanticIntake,
    TaskExecutionPlan,
    TaskGraphProposal,
    TaskGraphValidation,
    TaskRecipe,
)
from kernel_v3.agent.answer_profile import (
    answer_profile_from_dict,
    answer_quality_gaps,
    infer_answer_profile,
    research_mission_metadata,
)
from kernel_v3.agent.semantics import analyze_goal, analyze_goal_with_processor
from kernel_v3.agent.state_space import summarize_state_profiles
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.workloop import WorkloopConfig, WorkloopEvaluator
from kernel_v3.context import ArtifactStore, ContextPackCompiler, ProjectProfile, merge_context_budget
from kernel_v3.contracts import CandidateAction, ContextBundle, Event, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.interaction import interaction_preferences, normalize_response_language
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.loop import LoopControllerV3
from kernel_v3.memory import MEMORY_RECALL_TOOL_NAME, MemoryPipeline, MemoryStore, register_memory_tools
from kernel_v3.mission.thread_rag import ThreadWorkingMemoryProvider
from kernel_v3.planner import Planner
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import FakeJsonProvider, ModelEvaluator, ModelPlanner, ProcessorFabric, ProcessorRouter, Synthesizer
from kernel_v3.research import (
    ACADEMIC_RESEARCH_PROFILE_ID,
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    ResearchCorpusStore,
    TECHNICAL_DOCUMENTATION_PROFILE_ID,
    research_depth_defaults,
    resolve_issuer_identity,
    source_directory_for_profile,
)
from kernel_v3.retrieval import (
    CorpusFetchProvider,
    CorpusSearchProvider,
    DirectUrlSearchProvider,
    FallbackSearchProvider,
    ResearchSourceQuerySearchProvider,
    RetrievalOperator,
    SecEdgarSearchProvider,
    SourceDirectorySearchProvider,
    UnconfiguredFetchProvider,
    UnconfiguredSearchProvider,
    register_retrieval_tool,
)
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
from kernel_v3.retrieval.source_directory_rank import rank_source_directory_entries
from kernel_v3.session import TaskState
from kernel_v3.tools import ToolManifest, ToolRegistry


_FINANCE_RESEARCH_PROFILE_CAPABILITIES = {
    "finance.fundamentals_research",
    "finance.market_news",
    "finance.market_data",
    "finance.macro_data",
    "finance.competitive_landscape",
}
_FINANCE_INTENT_KINDS = {
    "finance_fundamentals",
    "finance_fundamentals_research",
    "finance_fundamentals_research_plan",
    "financial_research",
    "fundamentals_research",
    "market_research",
}
_FINANCE_DOMAINS = {
    "finance",
    "finance_fundamentals",
    "financial_research",
    "fundamentals_research",
    "market_research",
}
_ACADEMIC_RESEARCH_PROFILE_CAPABILITIES = {
    "academic.research",
    "academic.frontier_research",
    "academic.literature_review",
    "academic.paper_search",
    "academic.scholarly_sources",
}
_ACADEMIC_INTENT_KINDS = {
    "academic_research",
    "academic_frontier_research",
    "frontier_research",
    "literature_review",
    "paper_search",
    "scholarly_research",
    "scholarly_literature_review",
}
_ACADEMIC_DOMAINS = {
    "academic",
    "academic_research",
    "scholarly_literature",
    "scholarly_research",
    "mathematics_research",
    "physics_research",
    "science_research",
}
_TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES = {
    "technical.documentation_research",
    "technical.api_documentation",
    "technical.developer_docs",
    "technical.source_repository",
}
_TECHNICAL_DOCUMENTATION_INTENT_KINDS = {
    "technical_documentation",
    "technical_documentation_research",
    "api_documentation",
    "developer_docs",
    "sdk_documentation",
}
_TECHNICAL_DOCUMENTATION_DOMAINS = {
    "technical",
    "technical_research",
    "technical_documentation",
    "technical_documentation_research",
    "developer_docs",
    "api_documentation",
}

DEFAULT_RETRIEVAL_MAX_STEPS = 2048
DEFAULT_RETRIEVAL_MAX_TOOL_CALLS = 1024
DEFAULT_RETRIEVAL_MAX_ARTIFACT_BYTES = 4_000_000_000
DEFAULT_MODEL_DYNAMIC_MAX_STEPS = 2048
DEFAULT_MODEL_DYNAMIC_MAX_TOOL_CALLS = 1024
DEFAULT_MODEL_DYNAMIC_MAX_ARTIFACT_BYTES = 4_000_000_000
LOOP_GUARD_STOP_REASONS = {
    "max_tool_calls",
    "max_network_fetches",
    "max_total_artifact_bytes",
    "max_steps",
    "max_duration_ms",
}
PARTIAL_RETRIEVAL_TERMINAL_REASONS = {
    "max_network_fetches",
    "repeated_missing_evidence",
    "repeated_no_progress",
    "network_budget_guard_with_partial_evidence",
}


class AgentRuntime:
    def __init__(
        self,
        *,
        journal: JournalStore | None = None,
        artifact_store: ArtifactStore | None = None,
        processor_fabric: ProcessorFabric | None = None,
        retrieval_operator: RetrievalOperator | None = None,
        workspace_root: Path | str | None = None,
        workspace_files: dict[str, str] | None = None,
        workloop_config: WorkloopConfig | None = None,
        memory_store: MemoryStore | None = None,
        research_corpus_store: ResearchCorpusStore | None = None,
        response_language: str | None = None,
    ) -> None:
        self.journal = journal or JournalStore.in_memory()
        self.artifact_store = artifact_store or ArtifactStore.in_memory()
        self.processor_fabric = processor_fabric
        self.retrieval_operator = retrieval_operator
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None
        self.workspace_files = dict(workspace_files or {})
        self.workloop_config = workloop_config or WorkloopConfig()
        self.memory_store = memory_store
        self.memory_pipeline = MemoryPipeline(store=memory_store, journal=self.journal) if memory_store is not None else None
        self.research_corpus_store = research_corpus_store
        self.response_language = normalize_response_language(response_language)

    def run(
        self,
        goal: str,
        *,
        thread_id: str = "local:default",
        mode: str = "auto",
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        semantic_mode: str = "fake",
        citations_required: bool | None = None,
        execution_metadata: JsonObject | None = None,
        response_language: str | None = None,
    ) -> AgentRuntimeResult:
        return self._execute(
            goal,
            thread_id=thread_id,
            mode=mode,
            planner_mode=planner_mode,
            evaluator_mode=evaluator_mode,
            synthesizer_mode=synthesizer_mode,
            semantic_mode=semantic_mode,
            citations_required=citations_required,
            execution_metadata=execution_metadata,
            response_language=response_language,
            task_id=None,
        )

    def resume(
        self,
        task_id: str,
        user_input: str,
        *,
        thread_id: str = "local:default",
        mode: str = "auto",
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        semantic_mode: str = "fake",
        citations_required: bool | None = None,
        execution_metadata: JsonObject | None = None,
        response_language: str | None = None,
    ) -> AgentRuntimeResult:
        return self._execute(
            user_input,
            thread_id=thread_id,
            mode=mode,
            planner_mode=planner_mode,
            evaluator_mode=evaluator_mode,
            synthesizer_mode=synthesizer_mode,
            semantic_mode=semantic_mode,
            citations_required=citations_required,
            execution_metadata=execution_metadata,
            response_language=response_language,
            task_id=task_id,
        )

    def _execute(
        self,
        goal: str,
        *,
        thread_id: str,
        mode: str,
        planner_mode: str,
        evaluator_mode: str,
        synthesizer_mode: str,
        semantic_mode: str,
        citations_required: bool | None,
        execution_metadata: JsonObject | None,
        response_language: str | None,
        task_id: str | None,
    ) -> AgentRuntimeResult:
        effective_language = normalize_response_language(response_language or self.response_language)
        execution_metadata = _with_interaction_preferences(execution_metadata, response_language=effective_language)
        intake = self._semantic_intake(
            goal,
            semantic_mode=semantic_mode,
            task_id=task_id,
            response_language=effective_language,
            runtime_context=_semantic_runtime_context(execution_metadata),
        )
        task_graph = task_graph_from_semantic(intake)
        task_graph_validation = validate_task_graph(task_graph)
        task_plan = build_task_execution_plan(task_graph, task_graph_validation)
        selected_mode = task_plan.selected_mode if mode == "auto" else _select_mode(goal, mode)
        if _pending_answer_prefers_semantic_mode(
            execution_metadata,
            intake,
            requested_mode=mode,
            citations_required=citations_required,
        ):
            selected_mode = task_plan.selected_mode
            execution_metadata = dict(execution_metadata or {})
            execution_metadata["mode_override"] = {
                "from": mode,
                "to": selected_mode,
                "reason": "pending_answer_semantic_intake",
            }
        if (
            selected_mode == "workspace_answer"
            and _workspace_target(goal, task_plan) is None
            and not _task_plan_has_workspace_read_actions(task_plan)
            and _ambiguous_workspace_file_read(goal)
        ):
            selected_mode = "clarify_first"
        if selected_mode == "workspace_write" and planner_mode != "model" and _workspace_write_target(goal, task_plan) is None:
            selected_mode = "clarify_first"
        answer_profile = infer_answer_profile(
            goal,
            semantic_intake=intake,
            task_plan=task_plan,
            execution_metadata=execution_metadata,
            response_language=effective_language,
        )
        research_mission = research_mission_metadata(
            goal,
            answer_profile=answer_profile,
            semantic_intake=intake,
            task_plan=task_plan,
        )
        execution_metadata = _with_answer_profile_metadata(
            execution_metadata,
            answer_profile=answer_profile,
            research_mission=research_mission,
        )
        recipe = task_recipe(
            selected_mode,
            citations_required=citations_required,
            metadata={
                "semantic_intake": intake.to_dict(),
                "task_graph": task_graph.to_dict(),
                "task_graph_validation": task_graph_validation.to_dict(),
                "task_execution_plan": task_plan.to_dict(),
                "execution_metadata": dict(execution_metadata or {}),
                "answer_profile": answer_profile.to_dict(),
                "research_mission": research_mission,
                "thread_id": thread_id,
            },
        )
        recipe = _with_active_memory_access(recipe, enabled=self.memory_store is not None)
        recipe = _with_planned_action_count(goal, recipe)
        recipe = _with_runtime_loop_budget(recipe, planner_mode=planner_mode)
        registry = self._registry(recipe, goal)
        planner = self._planner(goal, recipe, registry, planner_mode)
        evaluator = WorkloopEvaluator(
            inner=self._evaluator(recipe, evaluator_mode),
            journal=self.journal,
            recipe=recipe,
            config=self.workloop_config,
        )
        loop = LoopControllerV3(
            journal=self.journal,
            context_compiler=_AgentContextCompiler(
                recipe=recipe,
                tool_manifests=registry.manifests(),
                memory_store=self.memory_store,
            ),
            planner=planner,
            policy_gate=PolicyGate(
                permission=recipe.permission_profile,
                allowed_permissions=_recipe_allowed_permissions(recipe),
            ),
            tool_registry=registry,
            evaluator=evaluator,
            max_steps=recipe.max_steps,
            max_tool_calls=recipe.max_tool_calls,
            max_network_fetches=recipe.max_network_fetches,
            max_total_artifact_bytes=recipe.max_total_artifact_bytes,
        )
        if task_id is None:
            result = loop.run_event(
                Event(
                    event_id=f"evt-chat-{_safe_id(thread_id)}-{len(self.journal.records()) + 1}",
                    run_id="run-1",
                    type="input.received",
                    timestamp_ms=len(self.journal.records()) + 1,
                    payload={"text": goal, "thread_id": thread_id},
                    source="chat" if thread_id != "local:default" else "user",
                )
            )
        else:
            result = loop.resume(task_id, user_input=goal, thread_id=thread_id)
        semantic_record = self._append_semantic_intake(intake, task_id=result.task_id, run_id=result.run_id)
        self._append_task_graph(
            task_graph,
            task_graph_validation,
            task_id=result.task_id,
            run_id=result.run_id,
        )
        self._append_task_plan(task_plan, task_id=result.task_id, run_id=result.run_id)
        self._append_state_profile(task_plan, task_id=result.task_id, run_id=result.run_id)
        self._maybe_propose_memory(
            intake,
            task_id=result.task_id,
            run_id=result.run_id,
            thread_id=thread_id,
            source_record_ref=semantic_record.record_id,
        )
        self._append_recipe(recipe, task_id=result.task_id, run_id=result.run_id)
        if result.status == "needs_user_input":
            if _latest_action_has_reason(self.journal, result.task_id, result.run_id, "processor_failed"):
                failure = self._failure(
                    result.task_id,
                    result.run_id,
                    "model_planner_processor_failed",
                    missing_evidence=_ordered_unique(
                        [
                            *_missing_evidence(self.journal, result.task_id, result.run_id),
                            "planner_action",
                        ]
                    ),
                    next_action="retry_model_planner_or_reduce_context",
                )
                return AgentRuntimeResult(
                    status="failed",
                    task_id=result.task_id,
                    run_id=result.run_id,
                    mode=recipe.mode,
                    recipe_id=recipe.recipe_id,
                    final_answer=None,
                    failure_report=failure.to_dict(),
                    trace_refs=_trace_refs(self.journal, result.task_id),
                )
            if recipe.mode == "retrieval_answer" and _latest_action_is_no_planned_action(self.journal, result.task_id, result.run_id):
                planned_missing = _planned_retrieval_missing_evidence(self.journal, result.task_id, result.run_id, recipe)
                failure = self._failure(
                    result.task_id,
                    result.run_id,
                    ("planned_retrieval_subgoals_incomplete" if planned_missing else None)
                    or _latest_termination_failure_reason(self.journal, result.task_id, result.run_id)
                    or result.stop_reason
                    or "no_executable_action",
                    missing_evidence=_ordered_unique(
                        [
                            *_missing_evidence(self.journal, result.task_id, result.run_id),
                            *planned_missing,
                        ]
                    ),
                    next_action="refine_plan_or_configure_more_tools",
                )
                return AgentRuntimeResult(
                    status="failed",
                    task_id=result.task_id,
                    run_id=result.run_id,
                    mode=recipe.mode,
                    recipe_id=recipe.recipe_id,
                    final_answer=None,
                    failure_report=failure.to_dict(),
                    trace_refs=_trace_refs(self.journal, result.task_id),
                )
            return AgentRuntimeResult(
                status="needs_user_input",
                task_id=result.task_id,
                run_id=result.run_id,
                mode=recipe.mode,
                recipe_id=recipe.recipe_id,
                final_answer=None,
                failure_report=None,
                trace_refs=_trace_refs(self.journal, result.task_id),
            )
        final_answer, failure = self._finalize(
            result.task_id,
            result.run_id,
            recipe=recipe,
            loop_answer=result.answer,
            loop_stop_reason=result.stop_reason,
            synthesizer_mode=synthesizer_mode,
        )
        status = "completed" if final_answer is not None else "failed"
        return AgentRuntimeResult(
            status=status,
            task_id=result.task_id,
            run_id=result.run_id,
            mode=recipe.mode,
            recipe_id=recipe.recipe_id,
            final_answer=final_answer.to_dict() if final_answer is not None else None,
            failure_report=failure.to_dict() if failure is not None else None,
            trace_refs=_trace_refs(self.journal, result.task_id),
        )

    def _registry(self, recipe: TaskRecipe, goal: str) -> ToolRegistry:
        if recipe.mode == "retrieval_answer":
            registry = ToolRegistry.with_builtin_respond()
            register_retrieval_tool(
                registry,
                operator=self.retrieval_operator or _default_retrieval_operator(
                    goal,
                    recipe=recipe,
                    artifact_store=self.artifact_store,
                    corpus_store=self.research_corpus_store,
                ),
                journal=self.journal,
                artifact_store=self.artifact_store,
            )
            return self._with_memory_tools(registry)
        if recipe.mode in {"workspace_answer", "workspace_write"}:
            if self.workspace_root is not None:
                return self._with_memory_tools(ToolRegistry.with_permissioned_workspace(root=self.workspace_root, artifact_store=self.artifact_store))
            if self.workspace_files:
                return self._with_memory_tools(ToolRegistry.with_fake_workspace_tools(files=self.workspace_files, artifact_store=self.artifact_store))
            return self._with_memory_tools(ToolRegistry.with_builtin_respond())
        if recipe.mode == "system_answer":
            return self._with_memory_tools(ToolRegistry.with_builtin_respond())
        return self._with_memory_tools(ToolRegistry.with_builtin_respond())

    def _with_memory_tools(self, registry: ToolRegistry) -> ToolRegistry:
        if self.memory_store is None:
            return registry
        return register_memory_tools(
            registry,
            store=self.memory_store,
            journal=self.journal,
        )

    def _planner(
        self,
        goal: str,
        recipe: TaskRecipe,
        registry: ToolRegistry,
        planner_mode: str,
    ) -> Planner:
        if planner_mode == "model":
            if self.processor_fabric is None:
                raise ValueError("model planner requires processor_fabric")
            planner = ModelPlanner(
                fabric=self.processor_fabric,
                allowed_tool_names=_planner_allowed_tool_names(recipe),
            )
            return _RecipeBoundPlanner(
                inner=planner,
                goal=goal,
                recipe=recipe,
                journal=self.journal,
            )
        return _RecipePlanner(goal=goal, recipe=recipe, journal=self.journal)

    def _evaluator(self, recipe: TaskRecipe, evaluator_mode: str) -> Evaluator:
        if evaluator_mode == "model":
            if self.processor_fabric is None:
                raise ValueError("model evaluator requires processor_fabric")
            return ModelEvaluator(fabric=self.processor_fabric)
        return _RecipeEvaluator(recipe)

    def _finalize(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        loop_answer: str | None,
        loop_stop_reason: str | None,
        synthesizer_mode: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        if recipe.mode in {"direct_answer", "semantic_answer"}:
            if recipe.citations_required:
                return None, self._failure(
                    task_id,
                    run_id,
                    "citations_required_but_missing",
                    missing_evidence=["citation_refs"],
                    next_action="use_retrieval_or_workspace_mode",
                )
            text = loop_answer or _last_response_text(self.journal, task_id, run_id) or ""
            if not text:
                return None, self._failure(task_id, run_id, "missing_direct_answer", next_action="ask_user")
            return self._append_final(
                FinalAnswer(
                    answer=text,
                    citation_refs=[],
                    used_evidence=[],
                    limitations=[],
                    confidence=0.68 if recipe.mode == "semantic_answer" else 0.6,
                    task_id=task_id,
                    run_id=run_id,
                    trace_refs=_trace_refs(self.journal, task_id),
                )
            ), None
        if recipe.mode == "retrieval_answer":
            return self._finalize_retrieval(
                task_id,
                run_id,
                recipe=recipe,
                loop_stop_reason=loop_stop_reason,
                synthesizer_mode=synthesizer_mode,
            )
        if recipe.mode == "workspace_answer":
            return self._finalize_workspace(task_id, run_id, recipe=recipe, synthesizer_mode=synthesizer_mode)
        if recipe.mode == "workspace_write":
            return self._finalize_workspace_write(task_id, run_id)
        if recipe.mode == "system_answer":
            return self._finalize_system(task_id, run_id)
        return None, self._failure(
            task_id,
            run_id,
            loop_stop_reason or "needs_user_input",
            next_action="provide_more_detail",
        )

    def _finalize_retrieval(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        loop_stop_reason: str | None,
        synthesizer_mode: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        report = _latest_retrieval_report(self.journal, task_id, run_id)
        evidence = _retrieval_evidence(self.journal, task_id, run_id)
        citations = _retrieval_citations(self.journal, task_id, run_id)
        terminal_reason = (
            _latest_guard_stop_reason(self.journal, task_id, run_id)
            or _latest_termination_failure_reason(self.journal, task_id, run_id)
            or loop_stop_reason
        )
        if report is None:
            reason = terminal_reason if terminal_reason in LOOP_GUARD_STOP_REASONS else "missing_retrieval_report"
            return None, self._failure(
                task_id,
                run_id,
                reason,
                missing_evidence=_missing_evidence(self.journal, task_id, run_id),
                next_action="increase_budget_or_retry_retrieval" if reason in LOOP_GUARD_STOP_REASONS else "retry_retrieval",
            )
        planned_coverage = _planned_retrieval_coverage(self.journal, task_id, run_id, recipe)
        if planned_coverage.get("required") is True and not planned_coverage.get("sufficient"):
            if _can_synthesize_partial_retrieval(
                terminal_reason=terminal_reason,
                evidence=evidence,
                citations=citations,
                recipe=recipe,
            ):
                report = _report_with_partial_retrieval_limitations(
                    report,
                    planned_coverage=planned_coverage,
                    missing_evidence=_planned_retrieval_missing_evidence(self.journal, task_id, run_id, recipe),
                    terminal_reason=terminal_reason,
                )
                return self._synthesize_retrieval_final(
                    task_id,
                    run_id,
                    recipe=recipe,
                    report=report,
                    evidence=evidence,
                    citations=citations,
                    synthesizer_mode=synthesizer_mode,
                )
            reason = terminal_reason if terminal_reason in LOOP_GUARD_STOP_REASONS else "planned_retrieval_subgoals_incomplete"
            return None, self._failure(
                task_id,
                run_id,
                reason,
                missing_evidence=_planned_retrieval_missing_evidence(self.journal, task_id, run_id, recipe),
                next_action=(
                    "increase_budget_or_refine_failed_retrieval_subgoals"
                    if reason in LOOP_GUARD_STOP_REASONS
                    else "refine_failed_retrieval_subgoals"
                ),
            )
        if report.status != "sufficient":
            reason = terminal_reason or f"retrieval_{report.status}"
            return None, self._failure(
                task_id,
                run_id,
                reason,
                missing_evidence=["sufficient_retrieval_evidence"],
                next_action=(
                    "increase_network_budget_or_enable_live_retrieval"
                    if reason in LOOP_GUARD_STOP_REASONS
                    else "refine_query_or_add_sources"
                ),
            )
        if recipe.citations_required and not citations:
            return None, self._failure(
                task_id,
                run_id,
                "citations_required_but_missing",
                missing_evidence=["citation_refs"],
                next_action="retry_retrieval_with_citable_sources",
            )
        return self._synthesize_retrieval_final(
            task_id,
            run_id,
            recipe=recipe,
            report=report,
            evidence=evidence,
            citations=citations,
            synthesizer_mode=synthesizer_mode,
        )

    def _synthesize_retrieval_final(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        report: RetrievalReport,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        synthesizer_mode: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        report = _report_with_task_goal(report, recipe)
        synthesized = self._synthesize(
            task_id,
            run_id,
            report=report,
            evidence=evidence,
            citations=citations,
            synthesizer_mode=synthesizer_mode,
        )
        if synthesized.status != "ok" or synthesized.answer is None:
            return None, self._failure(
                task_id,
                run_id,
                synthesized.error or "synthesis_failed",
                missing_evidence=list(synthesized.limitations),
                next_action="collect_more_evidence",
            )
        final = _agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))
        quality_gaps = self._final_answer_quality_gaps(final, recipe=recipe)
        self._append_final_quality_check(final, recipe=recipe, gaps=quality_gaps)
        if quality_gaps:
            return None, self._failure(
                task_id,
                run_id,
                "final_answer_quality_insufficient",
                missing_evidence=quality_gaps,
                next_action="expand_final_answer_or_collect_more_evidence",
            )
        final = self._append_final(final)
        self._maybe_propose_research_memory(final, recipe=recipe)
        return final, None

    def _finalize_workspace(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        synthesizer_mode: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        context_budget = _context_budget_metadata(recipe)
        evidence, citations, report = _workspace_grounding(
            self.journal,
            task_id,
            run_id,
            artifact_store=self.artifact_store,
            evidence_char_limit=int(context_budget["workspace_evidence_chars"]),
            citation_char_limit=int(context_budget["workspace_citation_chars"]),
            synthesis_evidence_preview_chars=int(context_budget["synthesis_evidence_preview_chars"]),
            synthesis_citation_preview_chars=int(context_budget["synthesis_citation_preview_chars"]),
        )
        if not evidence:
            return None, self._failure(
                task_id,
                run_id,
                "missing_workspace_evidence",
                missing_evidence=["file.read observation"],
                next_action="search_or_read_a_specific_file",
            )
        if recipe.citations_required and not citations:
            return None, self._failure(
                task_id,
                run_id,
                "citations_required_but_missing",
                missing_evidence=["workspace citation refs"],
                next_action="read_a_citable_file",
            )
        report = _report_with_task_goal(report, recipe)
        synthesized = self._synthesize(
            task_id,
            run_id,
            report=report,
            evidence=evidence,
            citations=citations,
            synthesizer_mode=synthesizer_mode,
        )
        if synthesized.status != "ok" or synthesized.answer is None:
            return None, self._failure(task_id, run_id, synthesized.error or "synthesis_failed", next_action="read_more_files")
        final = _agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))
        quality_gaps = self._final_answer_quality_gaps(final, recipe=recipe)
        self._append_final_quality_check(final, recipe=recipe, gaps=quality_gaps)
        if quality_gaps:
            return None, self._failure(
                task_id,
                run_id,
                "final_answer_quality_insufficient",
                missing_evidence=quality_gaps,
                next_action="expand_final_answer_or_read_more_files",
            )
        final = self._append_final(final)
        self._maybe_propose_research_memory(final, recipe=recipe)
        return final, None

    def _finalize_workspace_write(
        self,
        task_id: str,
        run_id: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        write_records = _workspace_write_observations(self.journal, task_id, run_id)
        if not write_records:
            return None, self._failure(
                task_id,
                run_id,
                "missing_workspace_write_observation",
                missing_evidence=["workspace.write observation"],
                next_action="propose_workspace_write",
            )
        latest = write_records[-1].data
        content = latest.get("content") if isinstance(latest, dict) else {}
        content = content if isinstance(content, dict) else {}
        path = str(content.get("path") or "workspace file")
        bytes_written = content.get("bytes")
        detail = f"{bytes_written} bytes" if isinstance(bytes_written, int) else "written"
        return self._append_final(
            FinalAnswer(
                answer=f"已写入 `{path}`（{detail}）。",
                citation_refs=[],
                used_evidence=[record.observation_ref or record.record_id for record in write_records],
                limitations=[],
                confidence=0.95,
                task_id=task_id,
                run_id=run_id,
                trace_refs=_trace_refs(self.journal, task_id),
            )
        ), None

    def _finalize_system(
        self,
        task_id: str,
        run_id: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        time_records = _system_time_observations(self.journal, task_id, run_id)
        if not time_records:
            return None, self._failure(
                task_id,
                run_id,
                "missing_system_observation",
                missing_evidence=["system.time observation"],
                next_action="use_system_time",
            )
        latest = time_records[-1].data
        content = latest.get("content") if isinstance(latest, dict) else {}
        content = content if isinstance(content, dict) else {}
        timezone = str(content.get("timezone") or "local")
        iso8601 = str(content.get("iso8601") or "")
        answer = f"当前时间是 {iso8601}（{timezone}）。" if iso8601 else f"已读取当前时间（{timezone}）。"
        return self._append_final(
            FinalAnswer(
                answer=answer,
                citation_refs=[],
                used_evidence=[record.observation_ref or record.record_id for record in time_records],
                limitations=[],
                confidence=0.95,
                task_id=task_id,
                run_id=run_id,
                trace_refs=_trace_refs(self.journal, task_id),
            )
        ), None

    def _synthesize(
        self,
        task_id: str,
        run_id: str,
        *,
        report: RetrievalReport,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        synthesizer_mode: str,
    ):
        if synthesizer_mode == "model":
            if self.processor_fabric is None:
                raise ValueError("model synthesizer requires processor_fabric")
            return Synthesizer(fabric=self.processor_fabric).synthesize(
                task_id=task_id,
                run_id=run_id,
                context_id=f"ctx-{task_id}-{run_id}-finalize",
                report=report,
                evidence=evidence,
                citations=citations,
            )
        answer = _grounded_answer(report=report, evidence=evidence, citations=citations)
        report_limitations = _string_list(report.diagnostics.get("limitations")) if isinstance(report.diagnostics, dict) else []
        fabric = ProcessorFabric(
            providers={
                "fake_json": FakeJsonProvider(
                    {
                        "synthesizer.answer": {
                            "answer": answer,
                            "citation_refs": [item.citation_id for item in citations],
                            "confidence": 0.8 if citations else 0.3,
                            "limitations": report_limitations or ([] if citations else ["missing_citation_refs"]),
                            "used_evidence": [item.evidence_id for item in evidence],
                        }
                    }
                )
            },
            router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
            journal=self.journal,
        )
        return Synthesizer(fabric=fabric).synthesize(
            task_id=task_id,
            run_id=run_id,
            context_id=f"ctx-{task_id}-{run_id}-finalize",
            report=report,
            evidence=evidence,
            citations=citations,
        )

    def _semantic_intake(
        self,
        goal: str,
        *,
        semantic_mode: str,
        task_id: str | None,
        response_language: str,
        runtime_context: JsonObject | None = None,
    ) -> SemanticIntake:
        if semantic_mode == "fake":
            return analyze_goal(goal)
        if semantic_mode != "model":
            raise ValueError(f"unsupported semantic_mode: {semantic_mode}")
        if self.processor_fabric is None:
            raise ValueError("model semantic intake requires processor_fabric")
        semantic_task_id = task_id or _next_task_id(self.journal)
        semantic_run_id = _next_run_id(self.journal, semantic_task_id)
        return analyze_goal_with_processor(
            goal,
            fabric=self.processor_fabric,
            task_id=semantic_task_id,
            run_id=semantic_run_id,
            context_id=f"ctx-semantic-{semantic_task_id}-{semantic_run_id}",
            response_language=response_language,
            runtime_context=runtime_context,
        )

    def _append_recipe(self, recipe: TaskRecipe, *, task_id: str, run_id: str) -> None:
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_recipe",
            data=redact_journal_data(recipe.to_dict()),
            state_delta={"agent_recipe": recipe.recipe_id, "agent_mode": recipe.mode},
        )

    def _append_semantic_intake(self, intake: SemanticIntake, *, task_id: str, run_id: str):
        return self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="semantic_intake",
            data=redact_journal_data(intake.to_dict()),
            state_delta={
                "primary_intent": intake.primary_intent,
                "suggested_mode": intake.suggested_mode,
                "compound": intake.compound,
            },
        )

    def _append_task_graph(
        self,
        proposal: TaskGraphProposal,
        validation: TaskGraphValidation,
        *,
        task_id: str,
        run_id: str,
    ):
        return self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="semantic_task_graph",
            data=redact_journal_data(
                {
                    "proposal": proposal.to_dict(),
                    "validation": validation.to_dict(),
                }
            ),
            state_delta={
                "task_graph": validation.status,
                "task_graph_selected_mode": validation.selected_mode,
            },
        )

    def _append_task_plan(self, plan: TaskExecutionPlan, *, task_id: str, run_id: str):
        return self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="semantic_task_plan",
            data=redact_journal_data(plan.to_dict()),
            state_delta={
                "task_plan": plan.status,
                "task_plan_selected_mode": plan.selected_mode,
                "task_plan_approval_required": plan.approval_required,
            },
        )

    def _append_state_profile(self, plan: TaskExecutionPlan, *, task_id: str, run_id: str):
        projection = _state_profile_projection_from_plan(plan)
        if not projection["profiles"]:
            return None
        summary = projection["summary"]
        return self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_state_profile",
            data=redact_journal_data(
                {
                    "plan_id": plan.plan_id,
                    "profiles": projection["profiles"],
                    "summary": summary,
                }
            ),
            state_delta={
                "agent_state_domains": list(summary.get("domains", [])),
                "agent_state_surfaces": list(summary.get("execution_surfaces", [])),
            },
        )

    def _maybe_propose_memory(
        self,
        intake: SemanticIntake,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> None:
        if self.memory_pipeline is None:
            return
        if not _has_memory_write_intent(intake):
            return
        try:
            self.memory_pipeline.propose_from_semantic_intake(
                intake,
                task_id=task_id,
                run_id=run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime isolation
            self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="memory_pipeline_error",
                data={"error_type": type(exc).__name__, "redaction": {"message": "omitted"}},
                state_delta={"memory_pipeline": "failed"},
            )

    def _append_final(self, answer: FinalAnswer) -> FinalAnswer:
        record = self.journal.append(
            task_id=answer.task_id,
            run_id=answer.run_id,
            step_id=None,
            kind="agent_final_answer",
            data=redact_journal_data(answer.to_dict()),
            state_delta={"agent_final_answer": "ok"},
        )
        return replace(answer, trace_refs=[*answer.trace_refs, record.record_id])

    def _final_answer_quality_gaps(self, answer: FinalAnswer, *, recipe: TaskRecipe) -> list[str]:
        profile = answer_profile_from_dict(_answer_profile_metadata(recipe))
        gaps = answer_quality_gaps(
            answer.answer,
            profile=profile,
            citation_refs=answer.citation_refs,
            used_evidence=answer.used_evidence,
        )
        required_urls = _required_retrieval_source_urls(recipe)
        if required_urls:
            citations = _retrieval_citations(self.journal, answer.task_id, answer.run_id)
            cited_urls = {
                citation.uri.strip()
                for citation in citations
                if citation.citation_id in set(answer.citation_refs) and citation.uri.strip()
            }
            if not any(_same_url_or_prefix(cited_url, required_url) for cited_url in cited_urls for required_url in required_urls):
                gaps.append("required_source_url_citation_missing")
        return gaps

    def _append_final_quality_check(self, answer: FinalAnswer, *, recipe: TaskRecipe, gaps: list[str]) -> None:
        profile = _answer_profile_metadata(recipe)
        if not profile:
            return
        self.journal.append(
            task_id=answer.task_id,
            run_id=answer.run_id,
            step_id=None,
            kind="final_answer_quality_check",
            data=redact_journal_data(
                {
                    "answer_profile": profile,
                    "passed": not gaps,
                    "gaps": list(gaps),
                    "answer_chars": len(answer.answer),
                    "citation_refs": list(answer.citation_refs),
                    "used_evidence": list(answer.used_evidence),
                }
            ),
            state_delta={"final_answer_quality": "passed" if not gaps else "insufficient"},
        )

    def _maybe_propose_research_memory(self, answer: FinalAnswer, *, recipe: TaskRecipe) -> None:
        if self.memory_pipeline is None:
            return
        profile = answer_profile_from_dict(_answer_profile_metadata(recipe))
        if profile is None or profile.format not in {"detailed_report", "deep_report", "memo"}:
            return
        try:
            self.memory_pipeline.propose_from_research_result(
                answer_text=answer.answer,
                task_id=answer.task_id,
                run_id=answer.run_id,
                thread_id=_thread_id_metadata(recipe),
                source_record_ref=answer.trace_refs[-1] if answer.trace_refs else None,
                metadata={
                    "answer_profile": profile.to_dict(),
                    "research_mission": _research_mission_metadata(recipe),
                    "citation_refs": list(answer.citation_refs),
                    "used_evidence": list(answer.used_evidence),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime isolation
            self.journal.append(
                task_id=answer.task_id,
                run_id=answer.run_id,
                step_id=None,
                kind="memory_pipeline_error",
                data={"error_type": type(exc).__name__, "redaction": {"message": "omitted"}},
                state_delta={"memory_pipeline": "failed"},
            )

    def _failure(
        self,
        task_id: str,
        run_id: str,
        reason: str,
        *,
        missing_evidence: list[str] | None = None,
        next_action: str | None,
    ) -> FailureReport:
        failure = FailureReport(
            reason=reason,
            attempted_actions=_attempted_actions(self.journal, task_id, run_id),
            attempted_sources=_attempted_sources(self.journal, task_id, run_id),
            missing_evidence=list(missing_evidence or _missing_evidence(self.journal, task_id, run_id)),
            last_observations=_last_observations(self.journal, task_id, run_id),
            user_help_needed=reason in {"needs_user_input", "clarification_required"} or next_action in {"ask_user", "provide_more_detail"},
            next_possible_action=next_action,
            task_id=task_id,
            run_id=run_id,
            trace_refs=_trace_refs(self.journal, task_id),
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_failure_report",
            data=redact_journal_data(failure.to_dict()),
            state_delta={"agent_final_answer": "failed", "reason": reason},
        )
        return failure


class _AgentContextCompiler:
    def __init__(self, *, recipe: TaskRecipe, tool_manifests: list[ToolManifest], memory_store: MemoryStore | None = None) -> None:
        self.recipe = recipe
        self.tool_manifests = [
            manifest for manifest in tool_manifests if manifest.name in set(recipe.allowed_tools)
        ]
        self.memory_store = memory_store
        self.thread_memory = ThreadWorkingMemoryProvider()

    def compile(self, task: TaskState, journal: JournalStore) -> ContextBundle:
        context_budget = _context_budget_metadata(self.recipe)
        pack = ContextPackCompiler(
            project_profile=ProjectProfile(
                project_id="holo-kernel-v3",
                root="",
                summary="Holo Kernel v3 is a host-owned single-agent harness. The model proposes; the host validates, executes, journals, and stops.",
                constraints=[
                    "Tools never execute without PolicyGate validation.",
                    "LoopControllerV3 must remain tool-name-agnostic.",
                    "Models cannot write memory, bypass policy, or execute tools directly.",
                    "Final answers must be grounded by host-collected evidence when citations are required.",
                ],
                redaction_markers=[],
            ),
            permission_state={
                "mode": self.recipe.permission_profile,
                "allowed_permissions": [],
            },
            budget_mode=self.recipe.context_budget_mode,
            durable_memory_store=self.memory_store,
            token_budget=int(context_budget["token_budget"]),
            section_budget=int(context_budget["section_budget"]),
        ).compile(
            task,
            journal,
            tool_briefs=[
                {
                    "name": manifest.name,
                    "side_effect": manifest.side_effect_class,
                    "input_schema": manifest.input_schema,
                }
                for manifest in self.tool_manifests
            ],
            step_id=task.step_id,
        )
        event_ids = [
            str(record.get("event_id"))
            for section in pack.sections
            if section["name"] == "user_event"
            for record in section["records"]
            if "event_id" in record
        ]
        semantic_profiles = _state_profiles_metadata(self.recipe)
        semantic_profile_summary = _state_profile_summary_metadata(self.recipe)
        capability_state = capability_catalog(
            tool_manifests=self.tool_manifests,
            allowed_tools=self.recipe.allowed_tools,
            allowed_permissions=_recipe_allowed_permissions(self.recipe),
            mode=self.recipe.mode,
        )
        mission_context = _compact_mission_context_for_prompt(_mission_context_metadata(self.recipe))
        thread_rag_context = _compact_thread_rag_context_for_prompt(
            _thread_rag_context_metadata(self.recipe)
        ) or self.thread_memory.compile(
            journal,
            thread_id=task.thread_id,
            task_id=task.task_id,
            mission_id=_mission_id_from_context(mission_context),
        )
        thread_rag_context = _compact_thread_rag_context_for_prompt(thread_rag_context)
        state = redact_journal_data(
            {
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "agent_recipe": _compact_agent_recipe_for_prompt(self.recipe),
                "capability_catalog": _compact_capability_catalog_for_prompt(
                    capability_state,
                    allowed_tools=self.recipe.allowed_tools,
                ),
                "semantic_state_space": _compact_semantic_state_space_for_prompt(semantic_state_space_catalog()),
                "semantic_state_profiles": semantic_profiles,
                "semantic_state_profile_summary": semantic_profile_summary,
                "research_source_directory": _compact_research_source_directory_for_prompt(
                    _research_source_directory_metadata(self.recipe)
                ),
                "retrieval_capability_state": _retrieval_capability_state(
                    self.tool_manifests,
                    recipe=self.recipe,
                ),
                "agent_runtime_directive": _compact_agent_runtime_directive_for_prompt(_planner_directive(self.recipe)),
                "agent_retrieval_plan_state": _agent_retrieval_plan_state(
                    journal,
                    task_id=task.task_id,
                    run_id=task.run_id,
                    recipe=self.recipe,
                ),
                "agent_replan_hints": _agent_replan_hints(
                    journal,
                    task_id=task.task_id,
                    run_id=task.run_id,
                    recipe=self.recipe,
                ),
                "mission_context": mission_context,
                "thread_working_context": _thread_working_context_metadata(self.recipe),
                "thread_rag_context": thread_rag_context,
                "answer_profile": _answer_profile_metadata(self.recipe),
                "research_mission": _research_mission_metadata(self.recipe),
                "context_pack_hash": pack.payload_hash,
                "sections": pack.sections,
                "source_refs": pack.source_refs,
                "redactions": pack.redactions,
                "budget": pack.budget,
            }
        )
        return ContextBundle(
            context_id=pack.context_id,
            thread_key=task.thread_id,
            event_ids=event_ids,
            memory_refs=pack.memory_refs,
            state=state,
            token_budget=int(pack.budget["token_budget"]),
        )


class _RecipeBoundPlanner:
    def __init__(self, *, inner: Planner, goal: str, recipe: TaskRecipe, journal: JournalStore | None = None) -> None:
        self.inner = inner
        self.goal = goal
        self.recipe = recipe
        self.journal = journal
        self._calls = 0
        self._journaled_plan_refs: set[str] = set()

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self._calls += 1
        self._journal_plan_if_needed(context)
        action = self.inner.propose(context, feedback)
        bound = _bind_model_action_to_recipe(action, goal=self.goal, recipe=self.recipe, context=context)
        self._journal_plan_update(context, bound, feedback)
        return bound

    def _journal_plan_if_needed(self, context: ContextBundle) -> None:
        if self.journal is None:
            return
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        plan_key = f"{task_id}:{run_id}"
        if not task_id or plan_key in self._journaled_plan_refs:
            return
        self._journaled_plan_refs.add(plan_key)
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_work_plan",
            data=redact_journal_data(
                {
                    "plan_id": f"agent-work-plan-{run_id}",
                    "goal": self.goal,
                    "mode": self.recipe.mode,
                    "revision": 1,
                    "planner_mode": "model",
                    "strategy": "dynamic_replan_each_iteration",
                    "status": "model_dynamic",
                    "max_steps": self.recipe.max_steps,
                    "max_tool_calls": self.recipe.max_tool_calls,
                    "allowed_tools": list(self.recipe.allowed_tools),
                }
            ),
            state_delta={"agent_work_plan": "model_dynamic"},
        )

    def _journal_plan_update(self, context: ContextBundle, action: CandidateAction, feedback: Feedback | None) -> None:
        if self.journal is None:
            return
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        if not task_id:
            return
        status = "waiting_for_user" if action.kind == "ask_user" else "running"
        if action.kind == "respond":
            status = "candidate_final_response"
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=str(context.state.get("step_id") or ""),
            kind="agent_work_plan_update",
            data=redact_journal_data(
                {
                    "plan_id": f"agent-work-plan-{run_id}",
                    "revision": self._calls,
                    "planner_mode": "model",
                    "feedback_status": feedback.status if feedback is not None else None,
                    "feedback_stop_reason": feedback.stop_reason if feedback is not None else None,
                    "feedback_missing_evidence": list(feedback.missing_evidence) if feedback is not None else [],
                    "retrieval_plan_state": context.state.get("agent_retrieval_plan_state", {}),
                    "replan_hints": context.state.get("agent_replan_hints", {}),
                    "selected_action": _action_plan_preview(action),
                    "status": status,
                }
            ),
            action_ref=action.action_id,
            state_delta={"agent_work_plan_revision": self._calls},
        )


class _RecipePlanner:
    def __init__(self, *, goal: str, recipe: TaskRecipe, journal: JournalStore | None = None) -> None:
        self.goal = goal
        self.recipe = recipe
        self.journal = journal
        self._actions = _recipe_actions(goal, recipe)
        self._total_actions = len(self._actions)
        self._journaled_plan_refs: set[str] = set()

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self._journal_plan_if_needed(context)
        if not self._actions:
            return CandidateAction(
                action_id=f"act-{context.state['run_id']}-agent-noop",
                kind="ask_user",
                name=None,
                description="no further planned actions",
                score=0.0,
                payload={"question": "No safe next action is available."},
                reasons=["no_planned_action"],
                side_effect_class="none",
            )
        action = _bind_recipe_action_to_run(self._actions.pop(0), context)
        self._journal_plan_update(context, action)
        return action

    def _journal_plan_if_needed(self, context: ContextBundle) -> None:
        if self.journal is None:
            return
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        plan_key = f"{task_id}:{run_id}"
        if not task_id or plan_key in self._journaled_plan_refs:
            return
        self._journaled_plan_refs.add(plan_key)
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_work_plan",
            data=redact_journal_data(
                {
                    "plan_id": f"agent-work-plan-{run_id}",
                    "goal": self.goal,
                    "mode": self.recipe.mode,
                    "revision": 1,
                    "total_actions": self._total_actions,
                    "pending_actions": [_action_plan_preview(action) for action in self._actions],
                    "status": "running" if self._actions else "empty",
                }
            ),
            state_delta={"agent_work_plan": "running" if self._actions else "empty"},
        )

    def _journal_plan_update(self, context: ContextBundle, action: CandidateAction) -> None:
        if self.journal is None:
            return
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        if not task_id:
            return
        completed = self._total_actions - len(self._actions)
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=str(context.state.get("step_id") or ""),
            kind="agent_work_plan_update",
            data=redact_journal_data(
                {
                    "plan_id": f"agent-work-plan-{run_id}",
                    "selected_action": _action_plan_preview(action),
                    "completed_actions": completed,
                    "remaining_actions": len(self._actions),
                    "status": "complete" if not self._actions else "running",
                }
            ),
            action_ref=action.action_id,
            state_delta={"agent_work_plan_remaining": len(self._actions)},
        )


class _RecipeEvaluator:
    def __init__(self, recipe: TaskRecipe) -> None:
        self.recipe = recipe
        self.calls = 0
        self.expected_action_count = _expected_action_count(recipe)

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.calls += 1
        run_id = str(context.state["run_id"])
        if observation.status == "needs_user_input":
            return _feedback(run_id, self.calls, "needs_user_input", "needs_user_input", None, [])
        if observation.source == "loop_guard" and observation.status == "blocked":
            content = observation.content if isinstance(observation.content, dict) else {}
            reason = content.get("reason")
            stop_reason = reason if isinstance(reason, str) and reason else "loop_guard"
            return _feedback(run_id, self.calls, "step_limit_exceeded", stop_reason, None, [stop_reason])
        if observation.status == "blocked" and observation.source == "loop_guard":
            content = observation.content if isinstance(observation.content, dict) else {}
            reason = content.get("reason")
            reason = reason if isinstance(reason, str) and reason else "loop_guard"
            return _feedback(run_id, self.calls, "step_limit_exceeded", reason, None, [reason])
        if observation.status == "blocked":
            return _feedback(run_id, self.calls, "blocked", "blocked", None, ["policy_block"])
        if (
            self.recipe.mode == "workspace_answer"
            and observation.source in {"tool:workspace.list", "tool:workspace.search"}
            and self.expected_action_count > self.calls
        ):
            return _feedback(run_id, self.calls, "continue", None, None, ["remaining_plan_actions"])
        if self.recipe.mode == "workspace_write" and observation.source in {"tool:workspace.search", "tool:file.read"}:
            return _feedback(run_id, self.calls, "continue", None, None, ["workspace.write observation"])
        if self.recipe.mode == "workspace_write" and observation.source == "tool:workspace.write" and observation.status == "ok":
            content = observation.content if isinstance(observation.content, dict) else {}
            path = content.get("path")
            answer = f"已写入 `{path}`。" if isinstance(path, str) and path else None
            return _feedback(run_id, self.calls, "final_answer_ready", "completed", answer, [])
        if observation.source == f"tool:{MEMORY_RECALL_TOOL_NAME}" and observation.status == "ok":
            return _feedback(run_id, self.calls, "continue", None, None, ["respond_from_memory_recall"])
        if observation.status in {"failed", "not_implemented"}:
            return _feedback(run_id, self.calls, "failed", "observation_failed", None, ["successful observation"])
        if self.expected_action_count > self.calls:
            return _feedback(run_id, self.calls, "continue", None, None, ["remaining_plan_actions"])
        if self.recipe.mode == "retrieval_answer":
            report = _nested(observation.content, "report")
            if isinstance(report, dict) and report.get("status") != "sufficient":
                return _feedback(run_id, self.calls, "failed", "insufficient_evidence", None, ["sufficient retrieval evidence"])
        answer = None
        if isinstance(observation.content, dict):
            answer = observation.content.get("text")
        return _feedback(run_id, self.calls, "final_answer_ready", "completed", answer if isinstance(answer, str) else None, [])


def _planner_allowed_tool_names(recipe: TaskRecipe) -> set[str]:
    allowed = set(recipe.allowed_tools)
    if recipe.mode == "retrieval_answer":
        allowed.add("respond")
    return allowed or {"__no_tools_allowed__"}


def _bind_recipe_action_to_run(action: CandidateAction, context: ContextBundle) -> CandidateAction:
    run_id = str(context.state.get("run_id") or "")
    if not run_id:
        return action
    suffix = f"-{run_id}"
    if action.action_id.endswith(suffix):
        return action
    return replace(action, action_id=f"{action.action_id}{suffix}")


def _bind_model_action_to_recipe(
    action: CandidateAction,
    *,
    goal: str,
    recipe: TaskRecipe,
    context: ContextBundle,
) -> CandidateAction:
    action = _bind_recipe_action_to_run(action, context)
    if action.kind != "tool":
        return action
    if action.name == "retrieval.run":
        payload = dict(action.payload)
        payload = _preserve_retrieval_capability_context(payload, recipe=recipe)
        payload.setdefault("goal_id", _next_required_retrieval_goal_id(context, recipe) or "goal-agent-retrieval")
        payload.setdefault("query", goal)
        payload.setdefault("max_spans_per_document", 2)
        payload = _apply_recipe_profile_defaults(payload, recipe)
        payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
        payload = _apply_research_depth_defaults(payload)
        return replace(action, payload=payload)
    return action


def _preserve_retrieval_capability_context(payload: JsonObject, *, recipe: TaskRecipe) -> JsonObject:
    """Keep source seeds and semantic extraction targets separate for retrieval.run."""

    capability_args = _retrieval_capability_args(recipe)
    if not capability_args:
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    urls = _retrieval_payload_urls(capability_args)
    urls.extend(_retrieval_payload_urls(updated))
    if urls:
        existing = _metadata_url_values(metadata, keys=("source_url", "source_urls"))
        source_urls = _ordered_unique([*existing, *urls])
        metadata["source_urls"] = source_urls
    cap_metadata = capability_args.get("metadata")
    cap_metadata = cap_metadata if isinstance(cap_metadata, dict) else {}
    for key in (
        "research_profile",
        "research_profile_id",
        "research_depth",
        "research_task_kind",
        "source_authority_requirement",
    ):
        value = cap_metadata.get(key, capability_args.get(key))
        if isinstance(value, str) and value:
            metadata.setdefault(key, value)
    cap_query = capability_args.get("query")
    current_query = updated.get("query")
    if (
        isinstance(cap_query, str)
        and cap_query.strip()
        and not _looks_like_url(cap_query)
        and (not isinstance(current_query, str) or _looks_like_url(current_query))
    ):
        updated["query"] = cap_query.strip()
    if metadata:
        updated["metadata"] = metadata
    return updated


def _next_required_retrieval_goal_id(context: ContextBundle, recipe: TaskRecipe) -> str | None:
    hints = context.state.get("agent_replan_hints")
    hints = hints if isinstance(hints, dict) else {}
    retrieval = hints.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    for key in ("incomplete_planned_goal_ids", "pending_goal_ids"):
        values = _string_list(retrieval.get(key))
        if values:
            return values[0]
    plan_state = context.state.get("agent_retrieval_plan_state")
    plan_state = plan_state if isinstance(plan_state, dict) else {}
    next_goal = plan_state.get("next_recommended_goal_id")
    if isinstance(next_goal, str) and next_goal:
        return next_goal
    goal_ids = _planned_retrieval_goal_ids_from_recipe(recipe)
    return goal_ids[0] if goal_ids else None


def task_recipe(
    mode: str,
    *,
    citations_required: bool | None = None,
    metadata: JsonObject | None = None,
) -> TaskRecipe:
    normalized = _select_mode("", mode)
    required = citations_required if citations_required is not None else normalized == "retrieval_answer"
    recipe_metadata = dict(metadata or {})
    if normalized == "retrieval_answer":
        max_network_fetches = _retrieval_network_fetch_budget(recipe_metadata)
        if max_network_fetches > 0:
            recipe_metadata = _with_allowed_permission(recipe_metadata, "network:fetch")
        return TaskRecipe(
            recipe_id="recipe-retrieval-answer",
            allowed_tools=["retrieval.run"],
            max_steps=DEFAULT_RETRIEVAL_MAX_STEPS,
            max_tool_calls=DEFAULT_RETRIEVAL_MAX_TOOL_CALLS,
            max_network_fetches=max_network_fetches,
            max_total_artifact_bytes=DEFAULT_RETRIEVAL_MAX_ARTIFACT_BYTES,
            permission_profile="read_write",
            citations_required=bool(required),
            finalizer="retrieval_synthesizer",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    if normalized == "workspace_answer":
        return TaskRecipe(
            recipe_id="recipe-workspace-answer",
            allowed_tools=["workspace.list", "workspace.search", "file.read"],
            max_steps=4,
            max_tool_calls=3,
            max_network_fetches=0,
            max_total_artifact_bytes=1_000_000,
            permission_profile="read_write",
            citations_required=bool(required),
            finalizer="workspace_synthesizer",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    if normalized == "workspace_write":
        recipe_metadata = _with_allowed_permission(recipe_metadata, "workspace:write")
        return TaskRecipe(
            recipe_id="recipe-workspace-write",
            allowed_tools=["workspace.list", "workspace.search", "file.read", "workspace.write"],
            max_steps=8,
            max_tool_calls=6,
            max_network_fetches=0,
            max_total_artifact_bytes=2_000_000,
            permission_profile="read_write",
            citations_required=bool(required),
            finalizer="workspace_write_ack",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    if normalized == "system_answer":
        return TaskRecipe(
            recipe_id="recipe-system-answer",
            allowed_tools=["system.time"],
            max_steps=2,
            max_tool_calls=1,
            max_network_fetches=0,
            max_total_artifact_bytes=128_000,
            permission_profile="read_only",
            citations_required=bool(required),
            finalizer="system_observation",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    if normalized == "clarify_first":
        return TaskRecipe(
            recipe_id="recipe-clarify-first",
            allowed_tools=[],
            max_steps=1,
            max_tool_calls=0,
            max_network_fetches=0,
            max_total_artifact_bytes=128_000,
            permission_profile="read_only",
            citations_required=False,
            finalizer="none",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    if normalized == "semantic_answer":
        return TaskRecipe(
            recipe_id="recipe-semantic-answer",
            allowed_tools=[],
            max_steps=2,
            max_tool_calls=0,
            max_network_fetches=0,
            max_total_artifact_bytes=256_000,
            permission_profile="read_only",
            citations_required=bool(required),
            finalizer="semantic_observation",
            context_budget_mode="truncate",
            mode=normalized,
            metadata=recipe_metadata,
        )
    return TaskRecipe(
        recipe_id="recipe-direct-answer",
        allowed_tools=[],
        max_steps=1,
        max_tool_calls=0,
        max_network_fetches=0,
        max_total_artifact_bytes=128_000,
        permission_profile="read_only",
        citations_required=bool(required),
        finalizer="direct_observation",
        context_budget_mode="truncate",
        mode="direct_answer",
        metadata=recipe_metadata,
    )


def _with_active_memory_access(recipe: TaskRecipe, *, enabled: bool) -> TaskRecipe:
    if not enabled or recipe.mode == "clarify_first":
        return recipe
    if recipe.citations_required and recipe.mode in {"direct_answer", "semantic_answer"}:
        return recipe
    if MEMORY_RECALL_TOOL_NAME in recipe.allowed_tools:
        return recipe
    metadata = dict(recipe.metadata)
    metadata["active_memory_recall"] = {
        "enabled": True,
        "tool": MEMORY_RECALL_TOOL_NAME,
        "scope_modes": ["workspace", "thread", "both"],
        "rule": "The model may propose memory.recall; the host validates and returns previews/refs only.",
    }
    return replace(
        recipe,
        allowed_tools=[*recipe.allowed_tools, MEMORY_RECALL_TOOL_NAME],
        max_steps=max(recipe.max_steps, 4),
        max_tool_calls=max(recipe.max_tool_calls, 2),
        max_total_artifact_bytes=max(recipe.max_total_artifact_bytes, 512_000),
        metadata=metadata,
    )


def _with_planned_action_count(goal: str, recipe: TaskRecipe) -> TaskRecipe:
    actions = _actions_from_task_plan(goal, recipe)
    if not actions and recipe.mode in {"workspace_answer", "workspace_write"}:
        actions = _recipe_actions(goal, recipe)
    if not actions:
        return recipe
    metadata = dict(recipe.metadata)
    metadata["planned_action_count"] = len(actions)
    tool_count = sum(1 for action in actions if action.kind == "tool")
    return replace(
        recipe,
        max_steps=max(recipe.max_steps, len(actions) + 2),
        max_tool_calls=max(recipe.max_tool_calls, tool_count + 1),
        max_total_artifact_bytes=max(recipe.max_total_artifact_bytes, max(1_000_000, tool_count * 512_000)),
        metadata=metadata,
    )


def _with_runtime_loop_budget(recipe: TaskRecipe, *, planner_mode: str) -> TaskRecipe:
    loop = _agent_loop_metadata(recipe)
    model_dynamic = planner_mode == "model" and recipe.mode in {"retrieval_answer", "workspace_answer", "workspace_write"}
    max_steps = _positive_metadata_int(loop.get("max_steps"), default=0) if loop else 0
    max_tool_calls = _positive_metadata_int(loop.get("max_tool_calls"), default=0) if loop else 0
    max_artifact_bytes = _positive_metadata_int(loop.get("max_total_artifact_bytes"), default=0) if loop else 0
    if model_dynamic:
        max_steps = max(max_steps, DEFAULT_MODEL_DYNAMIC_MAX_STEPS)
        max_tool_calls = max(max_tool_calls, DEFAULT_MODEL_DYNAMIC_MAX_TOOL_CALLS)
        max_artifact_bytes = max(max_artifact_bytes, DEFAULT_MODEL_DYNAMIC_MAX_ARTIFACT_BYTES)
    if max_steps <= 0 and max_tool_calls <= 0 and max_artifact_bytes <= 0:
        return recipe
    return replace(
        recipe,
        max_steps=max(recipe.max_steps, max_steps) if max_steps > 0 else recipe.max_steps,
        max_tool_calls=max(recipe.max_tool_calls, max_tool_calls) if max_tool_calls > 0 else recipe.max_tool_calls,
        max_total_artifact_bytes=max(recipe.max_total_artifact_bytes, max_artifact_bytes)
        if max_artifact_bytes > 0
        else recipe.max_total_artifact_bytes,
    )


def _expected_action_count(recipe: TaskRecipe) -> int:
    value = recipe.metadata.get("planned_action_count")
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _select_mode(goal: str, mode: str) -> str:
    aliases = {
        "direct": "direct_answer",
        "semantic": "semantic_answer",
        "retrieval": "retrieval_answer",
        "workspace": "workspace_answer",
        "write": "workspace_write",
        "workspace-write": "workspace_write",
        "system": "system_answer",
        "time": "system_answer",
        "clarify": "clarify_first",
    }
    normalized = aliases.get(mode, mode)
    if normalized != "auto":
        if normalized not in {
            "direct_answer",
            "semantic_answer",
            "retrieval_answer",
            "workspace_answer",
            "workspace_write",
            "system_answer",
            "clarify_first",
        }:
            raise ValueError(f"unsupported agent mode: {mode}")
        return normalized
    if not goal.strip() or goal.strip() in {"?", "？", ".", "。"}:
        return "clarify_first"
    return "direct_answer"


def _recipe_actions(goal: str, recipe: TaskRecipe) -> list[CandidateAction]:
    plan_actions = _actions_from_task_plan(goal, recipe)
    if plan_actions:
        return plan_actions
    if recipe.mode == "retrieval_answer":
        first_payload = _retrieval_payload(goal, recipe)
        retry_payload = dict(first_payload)
        return [
            CandidateAction(
                action_id="act-agent-retrieval-1",
                kind="tool",
                name="retrieval.run",
                description="run retrieval for grounded answer",
                score=1.0,
                payload=first_payload,
                reasons=["retrieval_answer recipe"],
                side_effect_class="read",
            ),
            CandidateAction(
                action_id="act-agent-retrieval-2",
                kind="tool",
                name="retrieval.run",
                description="retry retrieval once if evidence remains insufficient",
                score=0.6,
                payload=retry_payload,
                reasons=["retrieval_answer retry budget"],
                side_effect_class="read",
            )
        ]
    if recipe.mode == "workspace_answer":
        target = _workspace_target(goal, _task_execution_plan_metadata(recipe))
        if target is None:
            if _ambiguous_workspace_file_read(goal):
                return _recipe_actions(goal, task_recipe("clarify_first"))
            list_path = _workspace_list_target(goal, _task_execution_plan_metadata(recipe))
            return [
                CandidateAction(
                    action_id="act-agent-workspace-list",
                    kind="tool",
                    name="workspace.list",
                    description="list workspace directory",
                    score=1.0,
                    payload={"path": list_path},
                    reasons=["workspace_answer recipe"],
                    side_effect_class="read",
                )
            ]
        query, path = target
        return [
            CandidateAction(
                action_id="act-agent-workspace-search",
                kind="tool",
                name="workspace.search",
                description="search workspace for requested file",
                score=1.0,
                payload={"query": query},
                reasons=["workspace_answer recipe"],
                side_effect_class="read",
            ),
            CandidateAction(
                action_id="act-agent-file-read",
                kind="tool",
                name="file.read",
                description="read workspace file for grounded answer",
                score=1.0,
                payload={"path": path},
                reasons=["workspace_answer recipe"],
                side_effect_class="read",
            ),
        ]
    if recipe.mode == "workspace_write":
        target = _workspace_write_target(goal, _task_execution_plan_metadata(recipe))
        if target is None:
            return _recipe_actions(goal, task_recipe("clarify_first"))
        path, text = target
        actions: list[CandidateAction] = []
        read_target = _workspace_target(goal, _task_execution_plan_metadata(recipe))
        if read_target is not None:
            query, read_path = read_target
            actions.extend(
                [
                    CandidateAction(
                        action_id="act-agent-write-workspace-search",
                        kind="tool",
                        name="workspace.search",
                        description="search workspace before writing",
                        score=0.8,
                        payload={"query": query},
                        reasons=["workspace_write recipe optional read preflight"],
                        side_effect_class="read",
                    ),
                    CandidateAction(
                        action_id="act-agent-write-file-read",
                        kind="tool",
                        name="file.read",
                        description="read workspace input before writing",
                        score=0.8,
                        payload={"path": read_path},
                        reasons=["workspace_write recipe optional read preflight"],
                        side_effect_class="read",
                    ),
                ]
            )
        actions.append(
            CandidateAction(
                action_id="act-agent-workspace-write",
                kind="tool",
                name="workspace.write",
                description="write host-validated workspace artifact",
                score=1.0,
                payload={"path": path, "text": text},
                reasons=["workspace_write recipe"],
                side_effect_class="write",
            )
        )
        return actions
    if recipe.mode == "system_answer":
        payload = _capability_args_from_plan(
            _task_execution_plan_metadata(recipe),
            "system.time",
            capability_markers={"system.time"},
        )
        return [
            CandidateAction(
                action_id="act-agent-system-time",
                kind="tool",
                name="system.time",
                description="read current host time",
                score=1.0,
                payload=payload,
                reasons=["system_answer recipe"],
                side_effect_class="read",
            )
        ]
    if recipe.mode == "clarify_first":
        question = _semantic_clarification_question(recipe) or "请明确目标、文件名或需要检索的问题。"
        return [
            CandidateAction(
                action_id="act-agent-clarify",
                kind="ask_user",
                name=None,
                description="ask user to clarify target",
                score=1.0,
                payload={"question": question},
                reasons=["clarification_required"],
                side_effect_class="none",
            )
        ]
    if recipe.mode == "semantic_answer":
        response_hint = _semantic_response_hint(recipe)
        return [
            CandidateAction(
                action_id="act-agent-semantic",
                kind="respond",
                name=None,
                description="answer through broad semantic state without tool execution",
                score=1.0,
                payload={"text": response_hint or _semantic_answer_text(goal, recipe)},
                reasons=["semantic_answer recipe"],
                side_effect_class="none",
            )
        ]
    response_hint = _semantic_response_hint(recipe)
    return [
        CandidateAction(
            action_id="act-agent-direct",
            kind="respond",
            name=None,
            description="answer directly",
            score=1.0,
            payload={"text": response_hint or _direct_answer_text(goal, recipe)},
            reasons=["direct_answer recipe"],
            side_effect_class="none",
        )
    ]


def _actions_from_task_plan(goal: str, recipe: TaskRecipe) -> list[CandidateAction]:
    plan = _task_execution_plan_metadata(recipe)
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    actions: list[CandidateAction] = []
    for step in sorted([dict(item) for item in steps if isinstance(item, dict)], key=_plan_step_index):
        if str(step.get("status") or "") != "ready":
            continue
        if str(step.get("action_kind") or "") != "tool":
            continue
        actions.extend(_actions_from_plan_step(goal, recipe, step))
    return [
        action
        for _, action in sorted(
            enumerate(actions),
            key=lambda item: (not _candidate_action_required(item[1]), item[0]),
        )
    ]


def _actions_from_plan_step(goal: str, recipe: TaskRecipe, step: JsonObject) -> list[CandidateAction]:
    tool_name = str(step.get("tool_name") or "")
    sequence = _plan_step_index(step)
    if tool_name == "retrieval.run":
        retrieval_payloads = _capability_payloads_from_step(step, "retrieval.run")
        if not retrieval_payloads:
            retrieval_payloads = [_capability_args_from_step(step, "retrieval.run") or {}]
        actions: list[CandidateAction] = []
        total_payloads = len(retrieval_payloads)
        for item_index, args in enumerate(retrieval_payloads, start=1):
            payload = {
                "goal_id": f"goal-plan-{sequence}" if total_payloads == 1 else f"goal-plan-{sequence}-{item_index}",
                "query": str(step.get("goal") or goal),
                "max_spans_per_document": 2,
            }
            payload = _merge_retrieval_payload(payload, args)
            payload = _apply_profile_capability_defaults(payload, step)
            payload = _apply_recipe_profile_defaults(payload, recipe)
            payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
            payload = _apply_research_depth_defaults(payload)
            payload.setdefault("query", str(step.get("goal") or goal))
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-retrieval"
                    if total_payloads == 1
                    else f"act-plan-{sequence}-{item_index}-retrieval",
                    kind="tool",
                    name="retrieval.run",
                    description=str(payload.get("query") or step.get("goal") or "run retrieval"),
                    score=1.0,
                    payload=payload,
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    if tool_name == "workspace.search,file.read":
        target = _workspace_target(goal, {"steps": [step]})
        if target is None:
            return []
        query, path = target
        return [
            CandidateAction(
                action_id=f"act-plan-{sequence}-workspace-search",
                kind="tool",
                name="workspace.search",
                description=str(step.get("goal") or "search workspace"),
                score=1.0,
                payload={"query": query},
                reasons=["semantic_task_plan"],
                side_effect_class="read",
            ),
            CandidateAction(
                action_id=f"act-plan-{sequence}-file-read",
                kind="tool",
                name="file.read",
                description=str(step.get("goal") or "read workspace file"),
                score=1.0,
                payload={"path": path},
                reasons=["semantic_task_plan"],
                side_effect_class="read",
            ),
        ]
    if tool_name == "workspace.list":
        payloads = _capability_payloads_from_step(step, "workspace.list")
        if not payloads:
            payloads = [{"path": _workspace_list_target(goal, {"steps": [step]})}]
        actions = []
        for item_index, args in enumerate(payloads, start=1):
            path = _string_value(args.get("path")) or "."
            payload: JsonObject = {"path": path}
            max_entries = args.get("max_entries")
            if isinstance(max_entries, int):
                payload["max_entries"] = max_entries
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-workspace-list",
                    kind="tool",
                    name="workspace.list",
                    description=str(step.get("goal") or "list workspace directory"),
                    score=1.0,
                    payload=payload,
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    if tool_name == "workspace.search":
        payloads = _capability_payloads_from_step(step, "workspace.search")
        if not payloads:
            payloads = [{"query": _string_value(step.get("goal")) or goal}]
        actions = []
        for item_index, args in enumerate(payloads, start=1):
            query = _string_value(args.get("query")) or _string_value(step.get("goal")) or goal
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-workspace-search",
                    kind="tool",
                    name="workspace.search",
                    description=str(step.get("goal") or "search workspace"),
                    score=1.0,
                    payload={"query": query},
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    if tool_name == "file.read":
        payloads = _capability_payloads_from_step(step, "file.read")
        if not payloads:
            fallback = _file_target(str(step.get("goal") or goal))
            payloads = [{"path": fallback}] if fallback is not None else []
        actions = []
        for item_index, args in enumerate(payloads, start=1):
            path = _string_value(args.get("path"))
            if path is None:
                continue
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-file-read",
                    kind="tool",
                    name="file.read",
                    description=str(step.get("goal") or "read workspace file"),
                    score=1.0,
                    payload={"path": path},
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    if tool_name == "workspace.write":
        actions: list[CandidateAction] = []
        read_target = _workspace_target(goal, {"steps": [step]})
        if read_target is not None:
            query, path = read_target
            actions.extend(
                [
                    CandidateAction(
                        action_id=f"act-plan-{sequence}-workspace-search",
                        kind="tool",
                        name="workspace.search",
                        description=str(step.get("goal") or "search before writing"),
                        score=0.8,
                        payload={"query": query},
                        reasons=["semantic_task_plan_write_preflight"],
                        side_effect_class="read",
                    ),
                    CandidateAction(
                        action_id=f"act-plan-{sequence}-file-read",
                        kind="tool",
                        name="file.read",
                        description=str(step.get("goal") or "read before writing"),
                        score=0.8,
                        payload={"path": path},
                        reasons=["semantic_task_plan_write_preflight"],
                        side_effect_class="read",
                    ),
                ]
            )
        write_payloads = _capability_payloads_from_step(step, "workspace.write")
        if not write_payloads:
            target = _workspace_write_target(goal, {"steps": [step]})
            write_payloads = [{"path": target[0], "text": target[1]}] if target is not None else []
        if not write_payloads:
            return actions
        for item_index, args in enumerate(write_payloads, start=1):
            path = _string_value(args.get("path"))
            text = _write_text_value(args.get("text")) or _write_text_value(args.get("content")) or _write_text_value(args.get("body"))
            if path is None or text is None:
                continue
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-workspace-write",
                    kind="tool",
                    name="workspace.write",
                    description=str(step.get("goal") or "write workspace file"),
                    score=1.0,
                    payload={"path": path, "text": text},
                    reasons=["semantic_task_plan"],
                    side_effect_class="write",
                )
            )
        return actions
    if tool_name == MEMORY_RECALL_TOOL_NAME:
        payloads = _capability_payloads_from_step(step, MEMORY_RECALL_TOOL_NAME)
        if not payloads:
            memory_args = _capability_args_from_step(step, "durable_memory.search") or _capability_args_from_step(step, "durable_memory.read")
            payloads = [memory_args or {}]
        actions = []
        for item_index, args in enumerate(payloads, start=1):
            query = _string_value(args.get("query")) or _string_value(args.get("goal")) or _string_value(step.get("goal")) or goal
            scope_mode = _string_value(args.get("scope_mode")) or _string_value(args.get("scope")) or "both"
            payload: JsonObject = {"query": query, "scope_mode": scope_mode}
            limit = args.get("limit")
            if isinstance(limit, int):
                payload["limit"] = limit
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-memory-recall",
                    kind="tool",
                    name=MEMORY_RECALL_TOOL_NAME,
                    description=str(step.get("goal") or "recall durable memory"),
                    score=1.0,
                    payload=payload,
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    if tool_name == "system.time":
        payloads = _capability_payloads_from_step(step, "system.time")
        if not payloads:
            payloads = [{}]
        actions = []
        for item_index, args in enumerate(payloads, start=1):
            payload = {}
            timezone = _string_value(args.get("timezone"))
            if timezone is not None:
                payload["timezone"] = timezone
            actions.append(
                CandidateAction(
                    action_id=f"act-plan-{sequence}-{item_index}-system-time",
                    kind="tool",
                    name="system.time",
                    description=str(step.get("goal") or "read current host time"),
                    score=1.0,
                    payload=payload,
                    reasons=["semantic_task_plan"],
                    side_effect_class="read",
                )
            )
        return actions
    return []


def _candidate_action_required(action: CandidateAction) -> bool:
    payload = action.payload
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    for container in (payload, metadata):
        value = container.get("subgoal_required") if isinstance(container, dict) else None
        if isinstance(value, bool):
            return value
    return True


def _plan_step_index(step: JsonObject) -> int:
    value = step.get("sequence_index")
    return value if isinstance(value, int) and value > 0 else 1_000_000


def _action_plan_preview(action: CandidateAction) -> JsonObject:
    payload = dict(action.payload)
    text = payload.pop("text", None)
    if isinstance(text, str):
        payload["text_preview"] = _preview_text(text, 160)
        payload["text_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        payload["text_chars"] = len(text)
    return {
        "action_id": action.action_id,
        "kind": action.kind,
        "name": action.name,
        "side_effect_class": action.side_effect_class,
        "payload": payload,
    }


def _planner_directive(recipe: TaskRecipe) -> JsonObject:
    semantic = _semantic_intake_metadata(recipe)
    preferences = _interaction_preferences_metadata(recipe)
    state_profile_summary = _state_profile_summary_metadata(recipe)
    active_memory = _active_memory_directive(recipe)
    answer_profile = _answer_profile_metadata(recipe)
    research_mission = _research_mission_metadata(recipe)
    if recipe.mode == "retrieval_answer":
        return {
            "mode": recipe.mode,
            "required_first_action": {
                "kind": "tool",
                "name": "retrieval.run",
                "side_effect_class": "read",
                "payload_requirements": ["query or goal"],
            },
            "search_strategy_hint": {
                "payload_path": "metadata.search_strategy",
                "allowed_values": ["fallback", "aggregate", "corpus_only", "fresh_live", "structured", "crawl"],
                "meaning": "Optional host-validated selector among configured search providers; does not grant network permission.",
                "use_when": {
                    "corpus_only": "try existing indexed corpus evidence first",
                    "fresh_live": "skip corpus after cached evidence was insufficient or stale",
                    "aggregate": "merge multiple configured source providers when one provider may hide stronger evidence",
                    "structured": "prefer official/source-directory structured candidates",
                    "crawl": "use configured crawl discovery seeds when page discovery is needed",
                },
            },
            "allowed_tools": list(recipe.allowed_tools),
            "allowed_non_tool_actions": [
                {
                    "kind": "respond",
                    "use_when": (
                        "retrieval is budget-limited, repeatedly unproductive, or sufficient partial evidence exists; "
                        "summarize only observed evidence/citations and state limitations"
                    ),
                },
                {
                    "kind": "ask_user",
                    "use_when": "the host needs explicit user permission or a missing target cannot be inferred from context",
                },
            ],
            "forbidden": ["web_search", "page_open", "network.fetch"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "final_answer_contract": _final_answer_contract(answer_profile),
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
        }
    if recipe.mode == "workspace_answer":
        return {
            "mode": recipe.mode,
            "tool_selection": [
                {
                    "kind": "tool",
                    "name": "workspace.list",
                    "side_effect_class": "read",
                    "use_when": "the user asks to list, inspect, or read a directory/workspace root rather than a specific file body",
                    "payload_requirements": ["path: workspace-relative directory path; use . for workspace root"],
                    "sufficient_for_final": True,
                },
                {
                    "kind": "tool",
                    "name": "workspace.search",
                    "side_effect_class": "read",
                    "use_when": "the user asks to locate files or search workspace content before reading a specific file",
                    "payload_requirements": ["query: non-empty string; use the target path as query when known"],
                    "sufficient_for_final": True,
                },
                {
                    "kind": "tool",
                    "name": "file.read",
                    "side_effect_class": "read",
                    "use_when": "the user asks for the content of a known file or search results identify a file that must be read",
                    "payload_requirements": ["path: non-empty workspace-relative file path"],
                    "sufficient_for_final": True,
                },
            ],
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["retrieval.run", "web_search", "page_open", "network.fetch", "workspace.write"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "final_answer_contract": _final_answer_contract(answer_profile),
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
        }
    if recipe.mode == "workspace_write":
        return {
            "mode": recipe.mode,
            "required_outcome": "write a host-validated workspace artifact, then stop after the write observation succeeds",
            "allowed_sequence": [
                {
                    "kind": "tool",
                    "name": "workspace.search",
                    "side_effect_class": "read",
                    "payload_requirements": ["query: non-empty string"],
                    "optional": True,
                },
                {
                    "kind": "tool",
                    "name": "file.read",
                    "side_effect_class": "read",
                    "payload_requirements": ["path: non-empty workspace-relative file path"],
                    "optional": True,
                },
                {
                    "kind": "tool",
                    "name": "workspace.write",
                    "side_effect_class": "write",
                    "payload_requirements": ["path: non-empty workspace-relative file path", "text: complete UTF-8 file body"],
                },
            ],
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["retrieval.run", "web_search", "page_open", "network.fetch", "shell.exec"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
        }
    if recipe.mode == "semantic_answer":
        return {
            "mode": recipe.mode,
            "required_outcome": "answer the user; use memory.recall first when prior workspace/thread memory is needed",
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["memory writes", "external side effects"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
            "state_space_rule": (
                "Preserve broad semantic domains and limitations. Do not collapse "
                "professional, planning, communication, data, resident, transport, "
                "memory, or boundary tasks into workspace unless the host plan "
                "explicitly asks for workspace tools."
            ),
        }
    if recipe.mode == "clarify_first":
        return {
            "mode": recipe.mode,
            "required_first_action": {"kind": "ask_user", "name": None, "side_effect_class": "none"},
            "allowed_tools": [],
            "forbidden": ["all tool actions"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
        }
    if recipe.mode == "system_answer":
        return {
            "mode": recipe.mode,
            "required_first_action": {
                "kind": "tool",
                "name": "system.time",
                "side_effect_class": "read",
                "payload_requirements": ["timezone optional; prefer explicit IANA timezone when user asks"],
            },
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["workspace.write", "network.fetch", "shell.exec", "live_transport:*"],
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
        }
    return {
        "mode": recipe.mode,
        "required_outcome": "answer the user; use memory.recall first when prior workspace/thread memory is needed",
        "allowed_tools": list(recipe.allowed_tools),
        "forbidden": ["memory writes", "external side effects"],
        "interaction_preferences": preferences,
        "answer_profile": answer_profile,
        "research_mission": research_mission,
        "semantic_intake": semantic,
        "semantic_state_profile_summary": state_profile_summary,
        "active_memory": active_memory,
    }


def _active_memory_directive(recipe: TaskRecipe) -> JsonObject:
    if MEMORY_RECALL_TOOL_NAME not in recipe.allowed_tools:
        return {"enabled": False}
    metadata = recipe.metadata.get("active_memory_recall")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "enabled": True,
        "tool": MEMORY_RECALL_TOOL_NAME,
        "side_effect_class": "read",
        "use_when": [
            "the user asks about prior memory, preferences, or previous conversation",
            "workspace/project conventions could affect the answer",
            "thread continuity is required before responding",
        ],
        "payload_contract": {
            "query": "short semantic query for memory recall",
            "scope_mode": "workspace, thread, or both",
            "limit": "optional items per scope",
        },
        "host_boundary": metadata.get("rule")
        or "The host validates, executes, journals, and returns previews/refs only.",
    }


def _agent_retrieval_plan_state(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> JsonObject:
    if recipe.mode != "retrieval_answer":
        return {"status": "not_applicable", "planned_subgoals": []}
    subgoals = _planned_retrieval_subgoals_from_recipe(recipe)
    coverage = _planned_retrieval_coverage(journal, task_id, run_id, recipe)
    status_by_goal = _json_object(coverage.get("latest_status_by_goal_id"))
    incomplete = _string_list(coverage.get("incomplete_goal_ids"))
    complete = _string_list(coverage.get("complete_goal_ids"))
    pending = [goal_id for goal_id in incomplete if status_by_goal.get(goal_id) == "missing_report"]
    subgoal_records = []
    for subgoal in subgoals:
        goal_id = str(subgoal.get("goal_id") or "")
        status = str(status_by_goal.get(goal_id) or ("missing_report" if goal_id else "unknown"))
        state = "complete" if status == "sufficient" else "pending" if status == "missing_report" else "incomplete"
        subgoal_records.append({**subgoal, "latest_status": status, "state": state})
    if not subgoal_records:
        status = "unplanned"
    elif incomplete:
        status = "needs_retrieval" if len(incomplete) == len(subgoal_records) and len(complete) == 0 else "needs_replan"
    else:
        status = "complete"
    return {
        "status": status,
        "planned_subgoals": subgoal_records,
        "planned_goal_ids": _string_list(coverage.get("planned_goal_ids")),
        "complete_goal_ids": complete,
        "pending_goal_ids": pending,
        "incomplete_goal_ids": incomplete,
        "latest_status_by_goal_id": status_by_goal,
        "next_recommended_goal_id": incomplete[0] if incomplete else None,
        "planner_instructions": [
            "Use goal_id from planned_subgoals when proposing retrieval.run for this plan.",
            "Prefer next_recommended_goal_id unless feedback identifies a different urgent subgoal.",
            "Do not finalize until incomplete_goal_ids is empty.",
        ],
    }


def _agent_replan_hints(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> JsonObject:
    feedback = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="feedback")
    termination = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="termination_decision")
    evidence = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="evidence_sufficiency")
    report = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="retrieval_report")
    actions = [
        record for record in journal.records(task_id=task_id, kind="action")
        if record.run_id == run_id
    ]
    hints: JsonObject = {
        "status": "none",
        "recipe_mode": recipe.mode,
        "iteration_index": len(actions) + 1,
        "latest_feedback": _feedback_hint(feedback),
        "latest_termination": _termination_hint(termination),
        "latest_evidence_sufficiency": _evidence_sufficiency_hint(evidence),
        "avoid_repeating": _avoid_repeating_hints(actions),
        "suggested_next_action": "follow_recipe_or_answer_if_sufficient",
    }
    if recipe.mode != "retrieval_answer":
        return hints
    retrieval = _retrieval_replan_hints(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
        report_record=report,
        evidence_record=evidence,
    )
    hints["retrieval"] = retrieval
    if retrieval.get("needs_replan") is True:
        hints["status"] = "needs_replan"
        if retrieval.get("incomplete_planned_goal_ids"):
            hints["suggested_next_action"] = "retry_incomplete_planned_retrieval_subgoals"
        else:
            hints["suggested_next_action"] = "propose_materially_new_retrieval_run"
    elif _evidence_sufficient(evidence):
        hints["status"] = "ready_to_finalize"
        hints["suggested_next_action"] = "finalize_without_more_retrieval"
    elif actions:
        hints["status"] = "continue_or_fail_under_host_guards"
        hints["suggested_next_action"] = "change_query_source_or_strategy_if_continuing"
    return hints


def _retrieval_replan_hints(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
    report_record,
    evidence_record,
) -> JsonObject:
    report_data = dict(report_record.data) if report_record is not None else {}
    diagnostics = _json_object(report_data.get("diagnostics"))
    evaluation = _json_object(diagnostics.get("evaluation_diagnostics"))
    evidence_data = dict(evidence_record.data) if evidence_record is not None else {}
    evidence_diagnostics = _json_object(evidence_data.get("diagnostics"))
    planned_coverage = _json_object(evidence_diagnostics.get("planned_retrieval_coverage"))
    incomplete_planned_goal_ids = _string_list(planned_coverage.get("incomplete_goal_ids"))
    rejected_evidence_count = _int_or_none(diagnostics.get("rejected_evidence_count")) or 0
    source_rejection_count = _int_or_none(diagnostics.get("source_rejection_count")) or 0
    missing = _ordered_unique(
        [
            *_string_list(evidence_data.get("missing")),
            *[f"query_facet:{facet}" for facet in _string_list(evaluation.get("missing_query_facets"))],
            *[f"finance_facet:{facet}" for facet in _string_list(evaluation.get("missing_finance_facets"))],
            *[f"finance_facet:{facet}" for facet in _string_list(evidence_diagnostics.get("missing_finance_facets"))],
            *_string_list(evidence_diagnostics.get("missing_source_authority")),
            *(["candidate_evidence_rejected"] if rejected_evidence_count > 0 else []),
            *(["candidate_source_rejected"] if source_rejection_count > 0 else []),
        ]
    )
    attempts = _retrieval_attempt_hints(journal, task_id=task_id, run_id=run_id)
    fetches = _retrieval_fetch_hints(journal, task_id=task_id, run_id=run_id)
    source_authority = _json_object(evaluation.get("source_authority") or evidence_diagnostics.get("source_authority"))
    requirement = _string_value(
        evaluation.get("source_authority_requirement")
        or evidence_diagnostics.get("source_authority_requirement")
    )
    report_status = _string_value(report_data.get("status"))
    report_reason = _string_value(diagnostics.get("reason") or evaluation.get("reason") or report_status)
    strategy_hints = _suggested_retrieval_strategies(
        missing=missing,
        report_reason=report_reason,
        requirement=requirement,
        attempts=attempts,
    )
    query_hints = _suggested_query_hints(
        base_query=_string_value(report_data.get("preview") or diagnostics.get("goal_query") or diagnostics.get("query")),
        missing=missing,
        requirement=requirement,
    )
    source_targets = _suggested_source_targets(
        recipe=recipe,
        query=_string_value(report_data.get("preview") or diagnostics.get("goal_query") or diagnostics.get("query")),
        missing=missing,
        requirement=requirement,
        strategy_hints=strategy_hints,
    )
    suggested_filing_documents = _suggested_sec_filing_documents(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
    )
    suggested_sec_structured_sources = _suggested_sec_structured_sources(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
        report_data=report_data,
    )
    suggested_macro_series = _suggested_fred_series(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
    )
    suggested_fiscaldata_endpoints = _suggested_fiscaldata_endpoints(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
    )
    needs_replan = bool(report_record is not None and (report_status != "sufficient" or incomplete_planned_goal_ids))
    return {
        "needs_replan": needs_replan,
        "latest_report_status": report_status,
        "latest_report_reason": report_reason,
        "candidate_span_count": _int_or_none(diagnostics.get("candidate_span_count")),
        "source_rejection_count": source_rejection_count,
        "source_rejection_reasons": _json_object(diagnostics.get("source_rejection_reasons")),
        "rejected_evidence_count": rejected_evidence_count,
        "rejected_evidence_reasons": _json_object(diagnostics.get("rejected_evidence_reasons")),
        "missing": missing,
        "planned_retrieval_coverage": planned_coverage,
        "incomplete_planned_goal_ids": incomplete_planned_goal_ids,
        "missing_query_facets": _string_list(evaluation.get("missing_query_facets")),
        "missing_finance_facets": _string_list(evaluation.get("missing_finance_facets")),
        "covered_finance_facets": _string_list(evaluation.get("covered_finance_facets")),
        "covered_query_facets": _string_list(evaluation.get("covered_query_facets")),
        "source_authority_requirement": requirement,
        "source_authority": source_authority,
        "suggested_search_strategies": strategy_hints,
        "suggested_query_hints": query_hints,
        "suggested_source_targets": source_targets,
        "suggested_filing_documents": suggested_filing_documents,
        "suggested_sec_structured_sources": suggested_sec_structured_sources,
        "suggested_macro_series": suggested_macro_series,
        "suggested_fiscaldata_endpoints": suggested_fiscaldata_endpoints,
        "attempted_queries": _ordered_unique([item["query"] for item in attempts if isinstance(item.get("query"), str)]),
        "attempted_search_strategies": _ordered_unique(
            [item["search_strategy"] for item in attempts if isinstance(item.get("search_strategy"), str)]
        ),
        "attempted_provider_ids": _ordered_unique(
            [
                provider
                for item in attempts
                for provider in item.get("provider_ids", [])
                if isinstance(provider, str)
            ]
        ),
        "attempts": attempts[-6:],
        "fetch_summary": _retrieval_fetch_summary(fetches),
        "recent_fetches": fetches[-8:],
        "do_not_finalize_until": _do_not_finalize_until(missing=missing, requirement=requirement),
    }


def _suggested_sec_structured_sources(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
    report_data: JsonObject,
) -> list[JsonObject]:
    if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID:
        return []
    identity_text = " ".join(
        item
        for item in [
            _string_value(report_data.get("preview")),
            _string_value(_json_object(report_data.get("diagnostics")).get("goal_query")),
            *_action_retrieval_queries(journal, task_id=task_id, run_id=run_id),
        ]
        if item
    )
    identity = resolve_issuer_identity(identity_text)
    target_ticker = identity.ticker
    candidates: list[JsonObject] = []
    seen: set[str] = set()
    for record in journal.records(task_id=task_id, kind="retrieval_extraction"):
        if record.run_id != run_id:
            continue
        document = _json_object(record.data.get("document"))
        uri = _string_value(document.get("uri"))
        if "company_tickers" not in uri and "company_tickers_exchange" not in uri:
            continue
        spans = record.data.get("spans")
        span_text = " ".join(
            str(span.get("text") or "")
            for span in (spans if isinstance(spans, list) else [])
            if isinstance(span, dict)
        )
        for row in _sec_ticker_cik_rows_from_text(span_text):
            ticker = str(row.get("ticker") or "").upper()
            cik = _pad_sec_cik(row.get("cik"))
            if not ticker or not cik:
                continue
            if not _sec_identity_row_matches(row, target_ticker=target_ticker, identity_text=identity_text):
                continue
            key = f"{ticker.upper()}:{cik}"
            if key in seen:
                continue
            seen.add(key)
            query = f"{ticker.upper()} SEC CIK {cik} companyfacts submissions fundamentals"
            payload_metadata = {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "ticker": ticker.upper(),
                "sec_cik": cik,
                "source_authority_requirement": "primary",
                "search_strategy": "structured",
            }
            candidates.append(
                {
                    "source": "sec_ticker_cik_directory",
                    "source_record_id": record.record_id,
                    "source_uri": uri,
                    "ticker": ticker.upper(),
                    "sec_cik": cik,
                    "query": query,
                    "suggested_payload": {
                        "query": query,
                        "metadata": payload_metadata,
                    },
                }
            )
            if len(candidates) >= 3:
                return candidates
    return candidates


def _action_retrieval_queries(journal: JournalStore, *, task_id: str, run_id: str) -> list[str]:
    queries: list[str] = []
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        if record.data.get("name") != "retrieval.run":
            continue
        payload = record.data.get("payload")
        if not isinstance(payload, dict):
            continue
        query = _string_value(payload.get("query"))
        if query:
            queries.append(query)
    return queries


def _sec_ticker_cik_pairs_from_text(text: str) -> list[tuple[str, str]]:
    return [
        (str(row["ticker"]), str(row["cik"]))
        for row in _sec_ticker_cik_rows_from_text(text)
        if isinstance(row.get("ticker"), str) and isinstance(row.get("cik"), str)
    ]


def _sec_ticker_cik_rows_from_text(text: str) -> list[JsonObject]:
    if not text:
        return []
    rows: list[JsonObject] = []
    patterns = [
        re.compile(r"cik_str=(?P<cik>\d{1,10})\b.{0,160}?\bticker=(?P<ticker>[A-Z0-9.]{1,8})\b", re.IGNORECASE),
        re.compile(r"\bticker=(?P<ticker>[A-Z0-9.]{1,8})\b.{0,160}?\bcik_str=(?P<cik>\d{1,10})\b", re.IGNORECASE),
        re.compile(r"\bcik=(?P<cik>\d{1,10})\b.{0,160}?\bticker=(?P<ticker>[A-Z0-9.]{1,8})\b", re.IGNORECASE),
        re.compile(r"\bticker=(?P<ticker>[A-Z0-9.]{1,8})\b.{0,160}?\bcik=(?P<cik>\d{1,10})\b", re.IGNORECASE),
        re.compile(
            r"\[(?P<cik>\d{1,10})\s+(?P<company>[A-Z][A-Z0-9_.,& -]{1,120}?)\s+(?P<ticker>[A-Z][A-Z0-9.]{0,7})\s+(?P<exchange>Nasdaq|NYSE|AMEX|OTC|Cboe)\]",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            ticker = match.group("ticker").strip().upper()
            cik = _pad_sec_cik(match.group("cik"))
            if ticker and cik:
                rows.append(
                    {
                        "ticker": ticker,
                        "cik": cik,
                        "company": _sec_directory_company_name(match.groupdict().get("company")),
                    }
                )
    return _ordered_unique_sec_rows(rows)


def _sec_identity_row_matches(row: JsonObject, *, target_ticker: str | None, identity_text: str) -> bool:
    ticker = str(row.get("ticker") or "").upper()
    if target_ticker and ticker == target_ticker.upper():
        return True
    company = str(row.get("company") or "")
    if not company:
        return False
    identity_normalized = _normalized_issuer_text(identity_text)
    company_tokens = _issuer_significant_tokens(company)
    return bool(company_tokens) and all(token in identity_normalized for token in company_tokens)


def _sec_directory_company_name(value: object) -> str:
    return " ".join(str(value or "").replace("_", " ").replace(",", " ").split())


def _normalized_issuer_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _issuer_significant_tokens(value: str) -> list[str]:
    ignored = {"inc", "corp", "corporation", "company", "co", "ltd", "plc", "class", "com", "the"}
    return [
        token
        for token in _normalized_issuer_text(value).split()
        if len(token) >= 3 and token not in ignored
    ][:4]


def _pad_sec_cik(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    return digits[-10:].zfill(10)


def _ordered_unique_pairs(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ordered_unique_sec_rows(values: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[str, str]] = set()
    result: list[JsonObject] = []
    for value in values:
        key = (str(value.get("ticker") or "").upper(), str(value.get("cik") or ""))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _suggested_sec_filing_documents(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> list[JsonObject]:
    if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID:
        return []
    candidates: list[JsonObject] = []
    seen: set[str] = set()
    for record in journal.records(task_id=task_id, kind="retrieval_extraction"):
        if record.run_id != run_id:
            continue
        document = _json_object(record.data.get("document"))
        uri = _string_value(document.get("uri"))
        if "data.sec.gov/submissions/" not in uri:
            continue
        cik = _sec_cik_from_submissions_uri(uri)
        if not cik:
            continue
        spans = record.data.get("spans")
        span_items = spans if isinstance(spans, list) else []
        span_text = " ".join(
            str(span.get("text") or "")
            for span in span_items
            if isinstance(span, dict)
        )
        filings = _sec_filings_from_extracted_text(span_text)
        for filing in filings:
            accession = _string_value(filing.get("sec_accession_number"))
            primary_document = _string_value(filing.get("sec_primary_document"))
            if not accession:
                continue
            form = _string_value(filing.get("sec_form"))
            if not _is_sec_financial_report_form(form):
                continue
            key = f"{cik}:{accession}:{primary_document}"
            if key in seen:
                continue
            seen.add(key)
            report_date = _string_value(filing.get("report_date"))
            query = _sec_filing_document_query(cik=cik, form=form, report_date=report_date, accession=accession)
            payload_metadata = {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "sec_cik": cik,
                "sec_accession_number": accession,
                **({"sec_primary_document": primary_document} if primary_document else {}),
                **({"sec_form": form} if form else {}),
                **({"report_date": report_date} if report_date else {}),
                "source_authority_requirement": "primary",
                "search_strategy": "structured",
            }
            candidates.append(
                {
                    "source": "sec_submissions_json",
                    "source_record_id": record.record_id,
                    "source_uri": uri,
                    "sec_cik": cik,
                    "sec_accession_number": accession,
                    **({"sec_primary_document": primary_document} if primary_document else {}),
                    **({"sec_form": form} if form else {}),
                    **({"report_date": report_date} if report_date else {}),
                    "query": query,
                    "suggested_payload": {
                        "query": query,
                        "metadata": payload_metadata,
                    },
                }
            )
            if len(candidates) >= 5:
                return candidates
    return candidates


def _sec_filings_from_extracted_text(text: str) -> list[JsonObject]:
    if not text:
        return []
    by_index: dict[str, JsonObject] = {}
    fields = {
        "sec_form": ("form",),
        "sec_accession_number": ("accessionNumber", "accession_number", "accession"),
        "sec_primary_document": ("primaryDocument", "primary_document", "document_name"),
        "report_date": ("reportDate", "report_date"),
    }
    for output_key, names in fields.items():
        for name in names:
            for match in _indexed_sec_field_pattern(name).finditer(text):
                index = match.group("index")
                value = match.group("value").strip()
                if not value:
                    continue
                by_index.setdefault(index, {})[output_key] = _normalize_sec_field(output_key, value)
    filings = []
    for index in sorted(by_index, key=lambda item: int(item) if item.isdigit() else item):
        item = by_index[index]
        if item.get("sec_accession_number"):
            filings.append(item)
    return filings


def _is_sec_financial_report_form(form: str | None) -> bool:
    normalized = str(form or "").strip().upper().replace(" ", "")
    return normalized in {"10-K", "10-Q", "20-F", "40-F"}


def _indexed_sec_field_pattern(field_name: str) -> re.Pattern[str]:
    escaped = re.escape(field_name)
    return re.compile(
        rf"(?:^|\s)(?:[A-Za-z0-9_.]+\.)?{escaped}\[(?P<index>\d+)\]:\s*(?P<value>[^\s]+)",
        re.IGNORECASE,
    )


def _normalize_sec_field(field: str, value: str) -> str:
    if field == "sec_accession_number":
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) >= 18:
            compact = digits[-18:]
            return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
    return value


def _sec_cik_from_submissions_uri(uri: str) -> str | None:
    match = re.search(r"/submissions/CIK(?P<cik>\d{1,10})\.json", uri)
    if not match:
        return None
    return match.group("cik").zfill(10)


def _sec_filing_document_query(*, cik: str, form: str, report_date: str, accession: str) -> str:
    parts = ["SEC", "CIK", cik]
    if form:
        parts.append(form)
    if report_date:
        parts.append(report_date)
    parts.extend([accession, "primary filing document"])
    return " ".join(parts)


def _suggested_fred_series(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> list[JsonObject]:
    if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID:
        return []
    candidates: list[JsonObject] = []
    seen: set[str] = set()
    for record in journal.records(task_id=task_id, kind="retrieval_extraction"):
        if record.run_id != run_id:
            continue
        document = _json_object(record.data.get("document"))
        uri = _string_value(document.get("uri"))
        spans = record.data.get("spans")
        span_items = spans if isinstance(spans, list) else []
        span_text = " ".join(
            str(span.get("text") or "")
            for span in span_items
            if isinstance(span, dict)
        )
        for series_id in _fred_series_ids_from_extracted_text(f"{uri} {span_text}"):
            key = series_id.upper()
            if key in seen:
                continue
            seen.add(key)
            query = f"FRED series {key} official CSV observations"
            payload_metadata = {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fred_series_id": key,
                "source_authority_requirement": "primary",
                "source_family": "government_statistic",
                "preferred_source_families": ["government_statistic", "central_bank_statistic", "treasury_data"],
                "research_task_kind": "macro_data",
                "search_strategy": "structured",
            }
            candidates.append(
                {
                    "source": "fred_extracted_series_id",
                    "source_record_id": record.record_id,
                    "source_uri": uri,
                    "fred_series_id": key,
                    "query": query,
                    "suggested_payload": {
                        "query": query,
                        "metadata": payload_metadata,
                    },
                }
            )
            if len(candidates) >= 5:
                return candidates
    return candidates


def _fred_series_ids_from_extracted_text(text: str) -> list[str]:
    if not text:
        return []
    candidates: list[str] = []
    patterns = [
        re.compile(r"fred\.stlouisfed\.org/series/(?P<series>[A-Za-z][A-Za-z0-9_.-]{1,63})", re.IGNORECASE),
        re.compile(
            r"(?:fred_series_id|series_id|series id|fred series|series)\s*[:=]\s*(?P<series>[A-Za-z][A-Za-z0-9_.-]{1,63})",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            series_id = _normalize_fred_series_id(match.group("series"))
            if series_id:
                candidates.append(series_id)
    return _ordered_unique(candidates)


def _normalize_fred_series_id(value: str) -> str | None:
    normalized = value.strip().strip(".,;:)(").upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_.-]{1,63}", normalized):
        return None
    if normalized in {"FRED", "SERIES", "DATA", "SEARCH", "OFFICIAL", "CSV", "MACRO"}:
        return None
    return normalized


def _suggested_fiscaldata_endpoints(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> list[JsonObject]:
    if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID:
        return []
    candidates: list[JsonObject] = []
    seen: set[str] = set()
    for record in journal.records(task_id=task_id, kind="retrieval_extraction"):
        if record.run_id != run_id:
            continue
        document = _json_object(record.data.get("document"))
        uri = _string_value(document.get("uri"))
        spans = record.data.get("spans")
        span_items = spans if isinstance(spans, list) else []
        span_text = " ".join(
            str(span.get("text") or "")
            for span in span_items
            if isinstance(span, dict)
        )
        for endpoint_path in _fiscaldata_paths_from_extracted_text(f"{uri} {span_text}"):
            if endpoint_path in seen:
                continue
            seen.add(endpoint_path)
            label = endpoint_path.rsplit("/", 1)[-1]
            query = f"FiscalData {label} official Treasury API data"
            payload_metadata = {
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "fiscaldata_api_path": endpoint_path,
                "source_authority_requirement": "primary",
                "source_family": "treasury_data",
                "preferred_source_families": ["treasury_data", "government_statistic", "central_bank_statistic"],
                "research_task_kind": "macro_data",
                "search_strategy": "structured",
            }
            candidates.append(
                {
                    "source": "fiscaldata_extracted_endpoint",
                    "source_record_id": record.record_id,
                    "source_uri": uri,
                    "fiscaldata_api_path": endpoint_path,
                    "query": query,
                    "suggested_payload": {
                        "query": query,
                        "metadata": payload_metadata,
                    },
                }
            )
            if len(candidates) >= 5:
                return candidates
    return candidates


def _fiscaldata_paths_from_extracted_text(text: str) -> list[str]:
    if not text:
        return []
    candidates: list[str] = []
    patterns = [
        re.compile(
            r"api\.fiscaldata\.treasury\.gov(?P<path>/services/api/fiscal_service/[A-Za-z0-9_./-]{3,240})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:fiscaldata_api_path|fiscaldata_endpoint|treasury_api_path|endpoint_path)\s*[:=]\s*"
            r"(?P<path>/services/api/fiscal_service/[A-Za-z0-9_./-]{3,240})",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            path = _normalize_fiscaldata_api_path(match.group("path"))
            if path:
                candidates.append(path)
    return _ordered_unique(candidates)


def _normalize_fiscaldata_api_path(value: str) -> str | None:
    text = value.strip().rstrip(".,;:)")
    if not text.startswith("/services/api/fiscal_service/"):
        return None
    if ".." in text or not re.fullmatch(r"/services/api/fiscal_service/[A-Za-z0-9_./-]{3,240}", text):
        return None
    return text


def _feedback_hint(record) -> JsonObject:
    if record is None:
        return {}
    return {
        "status": _string_value(record.data.get("status")),
        "stop_reason": _string_value(record.data.get("stop_reason")),
        "missing_evidence": _string_list(record.data.get("missing_evidence")),
    }


def _termination_hint(record) -> JsonObject:
    if record is None:
        return {}
    diagnostics = _json_object(record.data.get("diagnostics"))
    return {
        "decision": _string_value(record.data.get("decision")),
        "reason": _string_value(record.data.get("reason")),
        "override": bool(record.data.get("override")),
        "evidence_missing": _string_list(diagnostics.get("evidence_missing")),
        "progress_type": _string_value(diagnostics.get("progress_type")),
        "no_progress_count": diagnostics.get("no_progress_count") if isinstance(diagnostics.get("no_progress_count"), int) else None,
    }


def _evidence_sufficiency_hint(record) -> JsonObject:
    if record is None:
        return {}
    return {
        "sufficient": bool(record.data.get("sufficient")),
        "reason": _string_value(record.data.get("reason")),
        "missing": _string_list(record.data.get("missing")),
        "evidence_count": record.data.get("evidence_count") if isinstance(record.data.get("evidence_count"), int) else None,
        "citation_count": record.data.get("citation_count") if isinstance(record.data.get("citation_count"), int) else None,
        "planned_retrieval_coverage": _json_object(_json_object(record.data.get("diagnostics")).get("planned_retrieval_coverage")),
    }


def _avoid_repeating_hints(actions: list) -> JsonObject:
    recent = actions[-6:]
    return {
        "recent_action_count": len(actions),
        "recent_action_names": _ordered_unique(
            [str(record.data.get("name") or record.data.get("kind") or "") for record in recent if record.data]
        ),
        "recent_payload_hashes": _ordered_unique(
            [
                hashlib.sha256(
                    json.dumps(record.data.get("payload", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                for record in recent
            ]
        ),
    }


def _retrieval_attempt_hints(journal: JournalStore, *, task_id: str, run_id: str) -> list[JsonObject]:
    attempts: list[JsonObject] = []
    action_records = [
        record for record in journal.records(task_id=task_id, kind="action")
        if record.run_id == run_id
    ]
    payload_by_action = {record.action_ref: _json_object(record.data.get("payload")) for record in action_records if record.action_ref}
    for record in journal.records(task_id=task_id, kind="retrieval_search_attempt"):
        if record.run_id != run_id:
            continue
        payload = payload_by_action.get(record.action_ref, {})
        metadata = _json_object(payload.get("metadata"))
        diagnostics = _json_object(record.data.get("diagnostics"))
        provider_diagnostics = _json_object(diagnostics.get("provider_diagnostics"))
        provider_ids = _string_list(provider_diagnostics.get("selected_provider_ids"))
        if not provider_ids and _string_value(provider_diagnostics.get("selected_provider_id")):
            provider_ids = [_string_value(provider_diagnostics.get("selected_provider_id"))]
        sources = record.data.get("sources")
        source_families = []
        source_authority_levels = []
        if isinstance(sources, list):
            for source in sources[:8]:
                if not isinstance(source, dict):
                    continue
                source_metadata = _json_object(source.get("metadata"))
                source_families.append(_string_value(source_metadata.get("source_family")))
                source_authority_levels.append(_string_value(source_metadata.get("authority_level")))
        attempts.append(
            {
                "query": _string_value(record.data.get("query") or payload.get("query")),
                "search_strategy": _string_value(metadata.get("search_strategy") or provider_diagnostics.get("selected_strategy")),
                "provider_ids": provider_ids,
                "status": _string_value(record.data.get("status")),
                "source_count": len(sources) if isinstance(sources, list) else 0,
                "source_families": _ordered_unique([item for item in source_families if item]),
                "source_authority_levels": _ordered_unique([item for item in source_authority_levels if item]),
            }
        )
    return attempts


def _retrieval_fetch_hints(journal: JournalStore, *, task_id: str, run_id: str) -> list[JsonObject]:
    fetches: list[JsonObject] = []
    for record in journal.records(task_id=task_id, kind="retrieval_fetch_attempt"):
        if record.run_id != run_id:
            continue
        fetches.append(
            {
                "uri": _preview_text(_string_value(record.data.get("uri")), 180),
                "status": _string_value(record.data.get("status")),
                "size_bytes": record.data.get("size_bytes") if isinstance(record.data.get("size_bytes"), int) else 0,
                "source_id": _string_value(record.data.get("source_id")),
                "diagnostics": _json_object(record.data.get("diagnostics")),
            }
        )
    return fetches


def _retrieval_fetch_summary(fetches: list[JsonObject]) -> JsonObject:
    total = len(fetches)
    ok = len([item for item in fetches if item.get("status") == "ok"])
    failed = len([item for item in fetches if item.get("status") not in {"ok", ""}])
    empty_success = len(
        [
            item for item in fetches
            if item.get("status") == "ok" and int(item.get("size_bytes") or 0) == 0
        ]
    )
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "empty_success": empty_success,
        "recent_failed_uris": [
            str(item.get("uri"))
            for item in fetches
            if item.get("status") not in {"ok", ""}
        ][-6:],
    }


def _suggested_retrieval_strategies(
    *,
    missing: list[str],
    report_reason: str,
    requirement: str,
    attempts: list[JsonObject],
) -> list[str]:
    attempted = {
        str(item.get("search_strategy"))
        for item in attempts
        if isinstance(item.get("search_strategy"), str) and item.get("search_strategy")
    }
    suggestions: list[str] = []
    if "primary_source" in missing or "source_authority:primary" in missing or requirement == "primary":
        suggestions.extend(["structured", "aggregate", "fresh_live", "crawl"])
    if any(item.startswith("query_facet:") for item in missing):
        suggestions.extend(["aggregate", "fresh_live", "crawl"])
    if "candidate_evidence_rejected" in missing or "candidate_source_rejected" in missing:
        suggestions.extend(["aggregate", "fresh_live", "structured", "crawl"])
    if any(item.startswith("finance_facet:") for item in missing):
        suggestions.extend(["structured", "aggregate", "fresh_live", "crawl"])
    if "retrieval_evidence" in missing or "sufficient_retrieval_evidence" in missing:
        suggestions.extend(["aggregate", "structured", "crawl", "fresh_live"])
    if report_reason in {"no_primary_source_for_research_profile", "no_required_authority_source_for_research_profile"}:
        suggestions.extend(["structured", "aggregate", "fresh_live"])
    result = [item for item in _ordered_unique(suggestions) if item not in attempted]
    return result or ["aggregate", "fresh_live", "structured"]


def _suggested_query_hints(*, base_query: str, missing: list[str], requirement: str) -> list[str]:
    additions: list[str] = []
    if "primary_source" in missing or "source_authority:primary" in missing or requirement == "primary":
        additions.extend(["official filing", "annual report", "10-K 10-Q", "issuer investor relations", "exchange disclosure"])
    facet_terms = {
        "candidate_evidence_rejected": "different primary source quoted facts relevant passages",
        "query_facet:model": "models",
        "query_facet:authentication": "authentication API key bearer token",
        "query_facet:pricing": "pricing billing",
        "query_facet:token": "token context length",
        "query_facet:rate_limit": "rate limit quota",
        "query_facet:endpoint": "endpoint base URL",
        "finance_facet:official_financial_statement": "official annual report 10-K 10-Q SEC EDGAR investor relations financial statements",
        "finance_facet:financial_metric": "revenue net income cash flow balance sheet key financial metrics",
        "finance_facet:revenue": "revenue net sales annual report",
        "finance_facet:net_income": "net income net earnings annual report",
        "finance_facet:cash_flow": "cash flow operating cash flow free cash flow annual report",
        "finance_facet:balance_sheet": "balance sheet assets liabilities equity annual report",
        "finance_facet:valuation": "stock price PE ratio market cap valuation",
        "finance_facet:numeric_financial_fact": "reported figures amounts percentages revenue net income cash flow annual report",
    }
    additions.extend(term for marker, term in facet_terms.items() if marker in missing)
    if not additions:
        return []
    base = base_query.strip()
    if not base:
        return _ordered_unique(additions)[:6]
    return _ordered_unique([f"{base} {addition}" for addition in additions])[:6]


def _suggested_source_targets(
    *,
    recipe: TaskRecipe,
    query: str,
    missing: list[str],
    requirement: str,
    strategy_hints: list[str],
) -> list[JsonObject]:
    profile_id = _research_profile_id(recipe)
    if not profile_id:
        return []
    entries = source_directory_for_profile(profile_id)
    if not entries:
        return []
    ranking_metadata: JsonObject = {
        "research_profile": profile_id,
        "source_authority_requirement": requirement,
        "missing": missing,
        "suggested_search_strategies": strategy_hints,
    }
    if (
        "primary_source" in missing
        or "source_authority:primary" in missing
        or requirement == "primary"
        or any(item.startswith("finance_facet:") for item in missing)
    ):
        ranking_metadata["preferred_source_families"] = [
            "regulatory_filing",
            "structured_regulatory_data",
            "company_ir",
            "exchange_filing",
        ]
    ranked = rank_source_directory_entries(entries, query=query, metadata=ranking_metadata)
    targets: list[JsonObject] = []
    for ranked_entry in ranked[:6]:
        entry = ranked_entry.entry
        metadata = getattr(entry, "metadata", {})
        templates = _source_target_query_templates(metadata)
        source_family = _string_value(getattr(entry, "source_family", "")) or ""
        authority_level = _string_value(getattr(entry, "authority_level", "")) or ""
        payload_metadata: JsonObject = {
            "research_profile": profile_id,
            "source_family": source_family,
            "source_authority_requirement": requirement or authority_level,
        }
        if strategy_hints:
            payload_metadata["search_strategy"] = strategy_hints[0]
        targets.append(
            {
                "source_id": _string_value(getattr(entry, "source_id", "")) or "",
                "title": _preview_text(_string_value(getattr(entry, "title", "")) or "", limit=140),
                "source_family": source_family,
                "authority_level": authority_level,
                "base_url": _string_value(getattr(entry, "base_url", "")) or "",
                "allowed_hosts": _string_list(getattr(entry, "allowed_hosts", []))[:8],
                "matched_query_terms": ranked_entry.matched_terms[:12],
                "relevance_score": round(ranked_entry.score, 6),
                "query_hints": _string_list(getattr(entry, "query_hints", []))[:4],
                "crawl_notes": _string_list(getattr(entry, "crawl_notes", []))[:3],
                "query_template_ids": [
                    _string_value(template.get("template_id"))
                    for template in templates[:4]
                    if isinstance(template, dict) and _string_value(template.get("template_id"))
                ],
                "suggested_payload_metadata": payload_metadata,
            }
        )
    return targets


def _source_target_query_templates(metadata: object) -> list[JsonObject]:
    if not isinstance(metadata, dict):
        return []
    value = metadata.get("query_url_templates")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _do_not_finalize_until(*, missing: list[str], requirement: str) -> list[str]:
    rules: list[str] = []
    if "citation_refs" in missing:
        rules.append("valid citation_refs exist")
    if "retrieval_evidence" in missing or "sufficient_retrieval_evidence" in missing:
        rules.append("retrieval report status is sufficient")
    if "primary_source" in missing or "source_authority:primary" in missing or requirement == "primary":
        rules.append("primary source authority requirement is satisfied")
    for item in missing:
        if item.startswith("query_facet:"):
            rules.append(f"{item} covered")
        if item.startswith("finance_facet:"):
            rules.append(f"{item} covered")
        if item.startswith("retrieval_subgoal:"):
            rules.append(f"{item} sufficient")
    return _ordered_unique(rules)


def _latest_journal_record(journal: JournalStore, *, task_id: str, run_id: str, kind: str):
    records = [
        record for record in journal.records(task_id=task_id, kind=kind)
        if record.run_id == run_id
    ]
    return records[-1] if records else None


def _evidence_sufficient(record) -> bool:
    return bool(record is not None and record.data.get("sufficient") is True)


def _semantic_intake_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("semantic_intake")
    return dict(value) if isinstance(value, dict) else {}


def _task_execution_plan_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("task_execution_plan")
    return dict(value) if isinstance(value, dict) else {}


def _state_profile_summary_metadata(recipe: TaskRecipe) -> JsonObject:
    task_graph = recipe.metadata.get("task_graph")
    if isinstance(task_graph, dict):
        metadata = task_graph.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("state_profile_summary"), dict):
            return dict(metadata["state_profile_summary"])
    return summarize_state_profiles(_state_profiles_metadata(recipe))


def _state_profiles_metadata(recipe: TaskRecipe) -> list[JsonObject]:
    task_plan = _task_execution_plan_metadata(recipe)
    return _state_profiles_from_plan_steps(task_plan.get("steps"))


def _state_profile_projection_from_plan(plan: TaskExecutionPlan) -> JsonObject:
    profiles = _state_profiles_from_plan_steps(plan.steps)
    return {
        "profiles": profiles,
        "summary": summarize_state_profiles(profiles),
    }


def _state_profiles_from_plan_steps(steps: object) -> list[JsonObject]:
    profiles: list[JsonObject] = []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            metadata = step.get("metadata")
            if not isinstance(metadata, dict):
                continue
            node_metadata = metadata.get("node_metadata")
            if not isinstance(node_metadata, dict):
                continue
            profile = node_metadata.get("state_profile")
            if isinstance(profile, dict):
                profiles.append(dict(profile))
    return profiles


def _execution_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("execution_metadata")
    return dict(value) if isinstance(value, dict) else {}


def _agent_loop_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("agent_loop")
    return dict(value) if isinstance(value, dict) else {}


def _thread_working_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("thread_working_context")
    return dict(value) if isinstance(value, dict) else {}


def _mission_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("mission_context")
    return dict(value) if isinstance(value, dict) else {}


def _thread_id_metadata(recipe: TaskRecipe) -> str:
    value = recipe.metadata.get("thread_id")
    if isinstance(value, str) and value:
        return value
    value = _execution_metadata(recipe).get("thread_id")
    if isinstance(value, str) and value:
        return value
    return "local:default"


def _answer_profile_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("answer_profile")
    if isinstance(value, dict):
        return dict(value)
    value = _execution_metadata(recipe).get("answer_profile")
    return dict(value) if isinstance(value, dict) else {}


def _research_mission_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("research_mission")
    if isinstance(value, dict):
        return dict(value)
    value = _execution_metadata(recipe).get("research_mission")
    return dict(value) if isinstance(value, dict) else {}


def _final_answer_contract(answer_profile: JsonObject) -> JsonObject:
    if not answer_profile:
        return {"format": "answer", "detail_level": "normal"}
    return {
        "format": answer_profile.get("format"),
        "detail_level": answer_profile.get("detail_level"),
        "target_sections": list(answer_profile.get("target_sections") or []),
        "minimum_coverage": list(answer_profile.get("minimum_coverage") or []),
        "min_answer_chars": answer_profile.get("min_answer_chars"),
        "min_section_count": answer_profile.get("min_section_count"),
        "citation_density": answer_profile.get("citation_density"),
        "host_rule": "Do not finalize detailed/deep research until this output contract is satisfied.",
    }


def _thread_rag_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("thread_rag_context")
    return dict(value) if isinstance(value, dict) else {}


def _compact_agent_recipe_for_prompt(recipe: TaskRecipe) -> JsonObject:
    data = recipe.to_dict()
    metadata = dict(data.get("metadata")) if isinstance(data.get("metadata"), dict) else {}
    execution = dict(metadata.get("execution_metadata")) if isinstance(metadata.get("execution_metadata"), dict) else {}
    if "mission_context" in execution:
        execution["mission_context"] = _compact_mission_context_for_prompt(execution.get("mission_context"))
    if "thread_rag_context" in execution:
        execution["thread_rag_context"] = _compact_thread_rag_context_for_prompt(execution.get("thread_rag_context"))
    if "thread_working_context" in execution:
        execution["thread_working_context"] = _compact_thread_working_context_for_prompt(execution.get("thread_working_context"))
    metadata = {
        "allowed_permissions": _string_list(metadata.get("allowed_permissions")),
        "active_memory_recall": _compact_simple_dict(metadata.get("active_memory_recall"), limit=8),
        "answer_profile": _compact_simple_dict(metadata.get("answer_profile"), limit=16),
        "research_mission": _compact_simple_dict(metadata.get("research_mission"), limit=16),
        "execution_metadata": {
            "agent_loop": _compact_simple_dict(execution.get("agent_loop"), limit=8),
            "context_budget": _compact_simple_dict(execution.get("context_budget"), limit=12),
            "interaction_preferences": _compact_simple_dict(execution.get("interaction_preferences"), limit=8),
            "answer_profile": _compact_simple_dict(execution.get("answer_profile"), limit=16),
            "research_mission": _compact_simple_dict(execution.get("research_mission"), limit=16),
            "mission_context": execution.get("mission_context", {}),
            "thread_rag_context": execution.get("thread_rag_context", {}),
            "thread_working_context": execution.get("thread_working_context", {}),
        },
    }
    data["metadata"] = metadata
    return data


def _compact_capability_catalog_for_prompt(value: object, *, allowed_tools: list[str]) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    capabilities = []
    for item in value.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        capabilities.append(
            {
                "capability_id": item.get("capability_id"),
                "family": item.get("family"),
                "tool_name": item.get("tool_name"),
                "status": item.get("status"),
                "side_effect_class": item.get("side_effect_class"),
                "permissions_required": _string_list(item.get("permissions_required"))[:4],
                "description": _text_preview(item.get("description"), limit=96),
            }
        )
    return {
        "version": value.get("version"),
        "mode": value.get("mode"),
        "families": value.get("families"),
        "executable_tools": _string_list(value.get("executable_tools")),
        "not_configured": _string_list(value.get("not_configured")),
        "planned": _string_list(value.get("planned")),
        "capabilities": capabilities,
        "allowed_tools": list(allowed_tools),
        "host_rule": "The model proposes only these high-level actions; the host validates payload schema and policy before execution.",
    }


def _compact_research_source_directory_for_prompt(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    entries: list[JsonObject] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        templates = metadata.get("query_url_templates") if isinstance(metadata.get("query_url_templates"), list) else []
        entries.append(
            {
                "source_id": item.get("source_id"),
                "title": _text_preview(item.get("title"), limit=180),
                "profile_id": item.get("profile_id"),
                "source_family": item.get("source_family"),
                "authority_level": item.get("authority_level"),
                "base_url": item.get("base_url"),
                "allowed_hosts": _string_list(item.get("allowed_hosts"))[:6],
                "query_hints": _string_list(item.get("query_hints"))[:4],
                "use_cases": _string_list(item.get("use_cases"))[:4],
                "crawl_notes": _string_list(item.get("crawl_notes"))[:3],
                "query_url_templates": [
                    {
                        "template_id": template.get("template_id"),
                        "title": _text_preview(template.get("title"), limit=120),
                        "source_kind": template.get("source_kind"),
                        "required_values": _string_list(template.get("required_values"))[:4],
                    }
                    for template in templates[:3]
                    if isinstance(template, dict)
                ],
            }
        )
    return entries


def _compact_semantic_state_space_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    families = value.get("families") if isinstance(value.get("families"), dict) else {}
    selected_families = {
        str(key): _string_list(item)[:16]
        for key, item in families.items()
    }
    return {
        "version": value.get("version"),
        "modes": _string_list(value.get("modes"))[:16],
        "task_domains": _string_list(value.get("task_domains"))[:24],
        "state_dimensions": _compact_state_dimensions_for_prompt(value.get("state_dimensions")),
        "families": selected_families,
        "semantic_slots": _string_list(value.get("semantic_slots"))[:24],
        "host_rule": "Use this as a semantic map only; concrete execution still requires a valid ActionProposal.",
    }


def _compact_agent_runtime_directive_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "mode": value.get("mode"),
        "allowed_tools": _string_list(value.get("allowed_tools")),
        "forbidden": _string_list(value.get("forbidden")),
        "required_first_action": _compact_simple_dict(value.get("required_first_action"), limit=8),
        "allowed_non_tool_actions": [
            _compact_simple_dict(item, limit=8)
            for item in list(value.get("allowed_non_tool_actions") or [])[:4]
            if isinstance(item, dict)
        ],
        "active_memory": _compact_simple_dict(value.get("active_memory"), limit=10),
        "answer_profile": _compact_simple_dict(value.get("answer_profile"), limit=16),
        "final_answer_contract": _compact_simple_dict(value.get("final_answer_contract"), limit=16),
        "search_strategy_hint": _compact_simple_dict(value.get("search_strategy_hint"), limit=12),
        "interaction_preferences": _compact_simple_dict(value.get("interaction_preferences"), limit=8),
        "semantic_state_profile_summary": _compact_simple_dict(value.get("semantic_state_profile_summary"), limit=16),
        "state_space_rule": _text_preview(value.get("state_space_rule"), limit=360),
        "host_rule": "Do not ask the user unless critical permission or missing target cannot be inferred; tool failures are observations for replanning.",
    }


def _compact_state_dimensions_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key, item in list(value.items())[:40]:
        if isinstance(item, list):
            result[str(key)] = _string_list(item)[:16]
    return result


def _compact_mission_context_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    state = value.get("mission_state")
    directive = value.get("directive")
    result: JsonObject = {
        "instruction": _text_preview(value.get("instruction"), limit=360),
    }
    if isinstance(state, dict):
        coverage = state.get("coverage_map") if isinstance(state.get("coverage_map"), dict) else {}
        result["mission_state"] = {
            "mission_id": state.get("mission_id"),
            "thread_id": state.get("thread_id"),
            "root_goal": _text_preview(state.get("root_goal"), limit=720),
            "status": state.get("status"),
            "active_task_id": state.get("active_task_id"),
            "last_run_id": state.get("last_run_id"),
            "iteration_count": state.get("iteration_count"),
            "open_gaps": _string_list(state.get("open_gaps"))[:24],
            "blocked_reasons": _string_list(state.get("blocked_reasons"))[-8:],
            "attempted_strategies": _string_list(state.get("attempted_strategies"))[-16:],
            "coverage_map": _compact_coverage_map_for_prompt(coverage),
            "directive": _compact_mission_directive_for_prompt(state.get("directive")),
        }
    if isinstance(directive, dict):
        result["directive"] = _compact_mission_directive_for_prompt(directive)
    return {key: val for key, val in result.items() if val not in ({}, [], None, "")}


def _compact_coverage_map_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "mission_id": value.get("mission_id"),
        "coverage_score": value.get("coverage_score"),
        "missing_requirements": _string_list(value.get("missing_requirements"))[:24],
        "evidence_refs": _string_list(value.get("evidence_refs"))[:16],
        "citation_refs": _string_list(value.get("citation_refs"))[:16],
        "diagnostics": _compact_simple_dict(value.get("diagnostics"), limit=12),
        "requirements": [
            _compact_requirement_for_prompt(item)
            for item in list(value.get("requirements") or [])[:12]
            if isinstance(item, dict)
        ],
    }


def _compact_requirement_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "requirement_id": value.get("requirement_id"),
        "text": _text_preview(value.get("text"), limit=240),
        "status": value.get("status"),
        "missing_reason": _text_preview(value.get("missing_reason"), limit=160),
        "evidence_refs": _string_list(value.get("evidence_refs"))[:8],
        "citation_refs": _string_list(value.get("citation_refs"))[:8],
    }


def _compact_mission_directive_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "directive_id": value.get("directive_id"),
        "mission_id": value.get("mission_id"),
        "root_goal": _text_preview(value.get("root_goal"), limit=720),
        "strategy": value.get("strategy"),
        "next_subgoal": _text_preview(value.get("next_subgoal"), limit=240),
        "missing_requirements": _string_list(value.get("missing_requirements"))[:24],
        "avoid_repeating": _string_list(value.get("avoid_repeating"))[-12:],
        "stop_conditions": _string_list(value.get("stop_conditions"))[:8],
        "reason": _text_preview(value.get("reason"), limit=240),
        "suggested_actions": [
            _compact_simple_dict(item, limit=8)
            for item in list(value.get("suggested_actions") or [])[:4]
            if isinstance(item, dict)
        ],
    }


def _compact_thread_rag_context_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "kind": value.get("kind") or "thread_rag_context",
        "thread_id": value.get("thread_id"),
        "task_id": value.get("task_id"),
        "mission_id": value.get("mission_id"),
        "context_hash": value.get("context_hash"),
        "recent_turns": [_compact_simple_dict(item, limit=8) for item in list(value.get("recent_turns") or [])[-8:] if isinstance(item, dict)],
        "recent_results": [_compact_simple_dict(item, limit=8) for item in list(value.get("recent_results") or [])[-4:] if isinstance(item, dict)],
        "recent_task_trace": [_compact_trace_item_for_prompt(item) for item in list(value.get("recent_task_trace") or [])[-12:] if isinstance(item, dict)],
        "evidence_refs": _string_list(value.get("evidence_refs"))[:16],
        "citation_refs": _string_list(value.get("citation_refs"))[:16],
        "failure_diagnostics": [_compact_failure_for_prompt(item) for item in list(value.get("failure_diagnostics") or [])[-3:] if isinstance(item, dict)],
    }


def _compact_thread_working_context_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result = _compact_simple_dict(value, limit=24)
    for key in ("recent_turns", "recent_results", "recent_conversation", "recent_task_trace"):
        item = value.get(key)
        if isinstance(item, list):
            result[key] = [_compact_simple_dict(child, limit=8) for child in item[-8:] if isinstance(child, dict)]
    for key in ("pending_question", "original_task", "current_turn", "last_agent_result", "resume_semantics"):
        item = value.get(key)
        if isinstance(item, dict):
            result[key] = _compact_simple_dict(item, limit=12)
        elif isinstance(item, str):
            result[key] = _text_preview(item, limit=720)
    return result


def _compact_trace_item_for_prompt(value: JsonObject) -> JsonObject:
    kind = value.get("kind")
    if kind == "observation":
        return {
            "record_ref": value.get("record_ref"),
            "kind": kind,
            "source": value.get("source"),
            "status": value.get("status"),
            "content_preview": _text_preview(value.get("content_preview"), limit=220),
        }
    if kind == "action":
        return {
            "record_ref": value.get("record_ref"),
            "kind": kind,
            "name": value.get("name"),
            "side_effect_class": value.get("side_effect_class"),
            "description": _text_preview(value.get("description"), limit=180),
            "reasons": _string_list(value.get("reasons"))[:3],
            "payload_hash": value.get("payload_hash"),
        }
    if kind == "retrieval_report":
        return {
            "record_ref": value.get("record_ref"),
            "kind": kind,
            "goal_id": value.get("goal_id"),
            "status": value.get("status"),
            "reason": value.get("reason"),
            "missing_query_facets": _string_list(value.get("missing_query_facets"))[:12],
            "missing_finance_facets": _string_list(value.get("missing_finance_facets"))[:12],
            "rejected_evidence_count": value.get("rejected_evidence_count"),
            "preview": _text_preview(value.get("preview"), limit=220),
        }
    return _compact_simple_dict(value, limit=10)


def _compact_failure_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "record_ref": value.get("record_ref"),
        "reason": value.get("reason"),
        "missing_evidence": _string_list(value.get("missing_evidence"))[:16],
        "attempted_actions": _string_list(value.get("attempted_actions"))[-8:],
        "next_possible_action": value.get("next_possible_action"),
        "user_help_needed": value.get("user_help_needed"),
    }


def _compact_simple_dict(value: object, *, limit: int) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key, item in list(value.items())[:limit]:
        if isinstance(item, str):
            result[str(key)] = _text_preview(item, limit=240)
        elif isinstance(item, (int, float, bool)) or item is None:
            result[str(key)] = item
        elif isinstance(item, list):
            result[str(key)] = [
                _text_preview(child, limit=160) if isinstance(child, str) else child
                for child in item[:8]
                if isinstance(child, (str, int, float, bool)) or child is None
            ]
        elif isinstance(item, dict):
            result[str(key)] = _compact_simple_dict(item, limit=8)
    return result


def _text_preview(value: object, *, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _mission_id_from_context(context: JsonObject) -> str | None:
    state = context.get("mission_state")
    if isinstance(state, dict) and isinstance(state.get("mission_id"), str):
        return str(state["mission_id"])
    mission_id = context.get("mission_id")
    return str(mission_id) if isinstance(mission_id, str) and mission_id else None


def _semantic_runtime_context(metadata: JsonObject | None) -> JsonObject:
    if not isinstance(metadata, dict):
        return {}
    context: JsonObject = {}
    for key in (
        "thread_working_context",
        "thread_rag_context",
        "mission_context",
        "answer_profile",
        "research_mission",
        "task_execution_step",
        "interaction_preferences",
        "agent_loop",
    ):
        value = metadata.get(key)
        if isinstance(value, dict):
            if key == "mission_context":
                context[key] = _compact_mission_context_for_prompt(value)
            elif key == "thread_rag_context":
                context[key] = _compact_thread_rag_context_for_prompt(value)
            elif key == "thread_working_context":
                context[key] = _compact_thread_working_context_for_prompt(value)
            else:
                context[key] = dict(value)
    return context


def _with_answer_profile_metadata(
    metadata: JsonObject | None,
    *,
    answer_profile,
    research_mission: JsonObject,
) -> JsonObject:
    result = dict(metadata or {})
    result["answer_profile"] = answer_profile.to_dict()
    result["research_mission"] = dict(research_mission)
    if answer_profile.format in {"detailed_report", "deep_report", "memo"}:
        context_budget = dict(result.get("context_budget")) if isinstance(result.get("context_budget"), dict) else {}
        context_budget.setdefault("profile", "large" if answer_profile.format != "deep_report" else "huge")
        result["context_budget"] = context_budget
    return result


def _pending_answer_prefers_semantic_mode(
    metadata: JsonObject | None,
    intake: SemanticIntake,
    *,
    requested_mode: str,
    citations_required: bool | None,
) -> bool:
    if citations_required is True:
        return False
    if intake.requires_clarification or intake.blocked_capabilities:
        return False
    if intake.suggested_mode not in {"direct_answer", "semantic_answer"}:
        return False
    if requested_mode in {"auto", "direct", "direct_answer", "semantic", "semantic_answer"}:
        return False
    if not isinstance(metadata, dict):
        return False
    working = metadata.get("thread_working_context")
    if not isinstance(working, dict):
        return False
    resume = working.get("resume_semantics")
    resume = resume if isinstance(resume, dict) else {}
    return working.get("route") == "answer_pending_question" and resume.get("same_task") is True


def _research_source_directory_metadata(recipe: TaskRecipe) -> list[JsonObject]:
    profile_id = _research_profile_id(recipe)
    if profile_id is None:
        return []
    return [entry.to_dict() for entry in source_directory_for_profile(profile_id)]


def _retrieval_capability_state(tool_manifests: list[ToolManifest], *, recipe: TaskRecipe) -> JsonObject:
    manifest = next((item for item in tool_manifests if item.name == "retrieval.run"), None)
    if manifest is None:
        return {
            "available": False,
            "reason": "retrieval_tool_not_registered",
            "allowed": "retrieval.run" in recipe.allowed_tools,
            "max_network_fetches": recipe.max_network_fetches,
            "provider_capabilities": [],
        }
    schema = manifest.input_schema if isinstance(manifest.input_schema, dict) else {}
    provider_capabilities = schema.get("_provider_capabilities")
    if not isinstance(provider_capabilities, list):
        provider_capabilities = []
    search_providers = [
        item for item in provider_capabilities
        if isinstance(item, dict) and item.get("provider_kind") == "search"
    ]
    fetch_providers = [
        item for item in provider_capabilities
        if isinstance(item, dict) and item.get("provider_kind") == "fetch"
    ]
    network_access = bool(schema.get("_network_access") or manifest.side_effect_class == "network")
    return {
        "available": manifest.enabled,
        "tool_name": manifest.name,
        "side_effect_class": manifest.side_effect_class,
        "network_access": network_access,
        "network_permission_required": "network:fetch" in manifest.permissions_required,
        "network_budget_available": recipe.max_network_fetches > 0,
        "max_network_fetches": recipe.max_network_fetches,
        "max_tool_calls": recipe.max_tool_calls,
        "max_steps": recipe.max_steps,
        "provider_capabilities": provider_capabilities,
        "search_provider_ids": _provider_ids(search_providers),
        "fetch_provider_ids": _provider_ids(fetch_providers),
        "live_search_available": any(bool(item.get("live_network")) for item in search_providers),
        "live_fetch_available": any(bool(item.get("live_network")) for item in fetch_providers),
        "profile_aware_search_available": any(bool(item.get("profile_aware")) for item in search_providers),
        "diagnostics": {
            "required_permissions": list(manifest.permissions_required),
            "has_search_provider": bool(search_providers),
            "has_fetch_provider": bool(fetch_providers),
        },
    }


def _provider_ids(items: list[JsonObject]) -> list[str]:
    ids: list[str] = []
    for item in items:
        provider_id = item.get("provider_id")
        if isinstance(provider_id, str) and provider_id:
            ids.append(provider_id)
        diagnostics = item.get("diagnostics")
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        nested = diagnostics.get("providers")
        if isinstance(nested, list):
            ids.extend(_provider_ids([entry for entry in nested if isinstance(entry, dict)]))
    return _ordered_unique(ids)


def _research_profile_id(recipe: TaskRecipe) -> str | None:
    metadata = _execution_metadata(recipe)
    retrieval = metadata.get("retrieval")
    if isinstance(retrieval, dict):
        nested = retrieval.get("metadata")
        if isinstance(nested, dict):
            for key in ("research_profile_id", "research_profile"):
                value = nested.get(key)
                if isinstance(value, str) and value:
                    return value
    semantic = _semantic_intake_metadata(recipe)
    for key in ("research_profile_id", "research_profile"):
        value = semantic.get(key)
        if isinstance(value, str) and value:
            return value
    if _semantic_has_any_capability(semantic, _FINANCE_RESEARCH_PROFILE_CAPABILITIES):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _semantic_has_any_intent_kind(semantic, _FINANCE_INTENT_KINDS):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _semantic_has_any_domain(semantic, _FINANCE_DOMAINS):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _semantic_has_any_capability(semantic, _ACADEMIC_RESEARCH_PROFILE_CAPABILITIES):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _semantic_has_any_intent_kind(semantic, _ACADEMIC_INTENT_KINDS):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _semantic_has_any_domain(semantic, _ACADEMIC_DOMAINS):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _semantic_has_any_capability(semantic, _TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    if _semantic_has_any_intent_kind(semantic, _TECHNICAL_DOCUMENTATION_INTENT_KINDS):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    if _semantic_has_any_domain(semantic, _TECHNICAL_DOCUMENTATION_DOMAINS):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    plan = _task_execution_plan_metadata(recipe)
    if _plan_has_any_capability(plan, _FINANCE_RESEARCH_PROFILE_CAPABILITIES):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _plan_has_any_step_kind(plan, _FINANCE_INTENT_KINDS):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _plan_has_any_domain(plan, _FINANCE_DOMAINS):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
    if _plan_has_any_capability(plan, _ACADEMIC_RESEARCH_PROFILE_CAPABILITIES):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _plan_has_any_step_kind(plan, _ACADEMIC_INTENT_KINDS):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _plan_has_any_domain(plan, _ACADEMIC_DOMAINS):
        return ACADEMIC_RESEARCH_PROFILE_ID
    if _plan_has_any_capability(plan, _TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    if _plan_has_any_step_kind(plan, _TECHNICAL_DOCUMENTATION_INTENT_KINDS):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    if _plan_has_any_domain(plan, _TECHNICAL_DOCUMENTATION_DOMAINS):
        return TECHNICAL_DOCUMENTATION_PROFILE_ID
    return None


def _context_budget_metadata(recipe: TaskRecipe) -> JsonObject:
    metadata = _execution_metadata(recipe)
    context = metadata.get("context_budget")
    if isinstance(context, dict):
        return merge_context_budget(
            context.get("profile"),
            token_budget=context.get("token_budget"),
            section_budget=context.get("section_budget"),
            workspace_evidence_chars=context.get("workspace_evidence_chars"),
            synthesis_evidence_preview_chars=context.get("synthesis_evidence_preview_chars"),
        )
    return merge_context_budget("compact")


def _recipe_allowed_permissions(recipe: TaskRecipe) -> set[str]:
    value = recipe.metadata.get("allowed_permissions")
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _execution_step_metadata(recipe: TaskRecipe) -> JsonObject | None:
    value = _execution_metadata(recipe).get("task_execution_step")
    return dict(value) if isinstance(value, dict) else None


def _has_memory_write_intent(intake: SemanticIntake) -> bool:
    for intent in intake.intents:
        if not isinstance(intent, dict):
            continue
        if str(intent.get("kind") or "") == "memory_write":
            return True
        capabilities = intent.get("required_capabilities")
        if isinstance(capabilities, list) and "durable_memory:write" in capabilities:
            return True
    return "durable_memory:write" in intake.blocked_capabilities


def _semantic_response_hint(recipe: TaskRecipe) -> str | None:
    value = _semantic_intake_metadata(recipe).get("response_hint")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _semantic_clarification_question(recipe: TaskRecipe) -> str | None:
    value = _semantic_intake_metadata(recipe).get("clarification_question")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _direct_answer_text(goal: str, recipe: TaskRecipe) -> str:
    semantic = _semantic_intake_metadata(recipe)
    primary = str(semantic.get("primary_intent") or "direct_answer")
    if primary == "noop":
        return "好的，我不会执行任何工具、写入或外部操作。"
    if primary == "synthesis":
        return "可以。我可以在已有上下文、检索证据或 workspace 观察之上做总结和比较；如果缺少证据，我会先说明限制或请求补充。"
    cleaned = " ".join(goal.split())
    if not cleaned:
        return "请提供一个明确目标。"
    return (
        "我已收到这个直接问题，但当前运行的是离线 host fallback，"
        "不会编造未经模型或证据支持的事实答案。请启用 model 模式，"
        "或改用 retrieval/workspace 让宿主收集可审计证据后回答。"
    )


def _semantic_answer_text(goal: str, recipe: TaskRecipe) -> str:
    summary = _state_profile_summary_metadata(recipe)
    domains = ", ".join(str(item) for item in summary.get("domains", [])[:8]) if isinstance(summary, dict) else ""
    activities = ", ".join(str(item) for item in summary.get("activities", [])[:6]) if isinstance(summary, dict) else ""
    prefix = "我已将这个请求保留为广义语义任务"
    if domains:
        prefix += f"；状态域包括：{domains}"
    if activities:
        prefix += f"；活动包括：{activities}"
    return (
        prefix
        + "。当前是离线 host fallback，不会替模型编造完整内容；"
        "启用 model planner 后，LLM 会在这个结构化状态包内生成回应，"
        "宿主仍负责权限、工具、journal 和终止判断。"
    )


def _next_task_id(journal: JournalStore) -> str:
    task_ids = {
        int(record.task_id.split("-", 1)[1])
        for record in journal.records()
        if record.kind in {"task", "session_state"}
        and record.task_id
        and record.task_id.startswith("task-")
        and record.task_id.split("-", 1)[1].isdigit()
    }
    return f"task-{max(task_ids, default=0) + 1}"


def _next_run_id(journal: JournalStore, task_id: str) -> str:
    run_ids = {
        int(record.run_id.split("-", 1)[1])
        for record in journal.records(task_id=task_id)
        if record.kind in {"run", "session_state"}
        and record.run_id.startswith("run-")
        and record.run_id.split("-", 1)[1].isdigit()
    }
    return f"run-{max(run_ids, default=0) + 1}"


def _default_retrieval_operator(
    goal: str,
    *,
    recipe: TaskRecipe,
    artifact_store: ArtifactStore,
    corpus_store: ResearchCorpusStore | None,
) -> RetrievalOperator:
    if corpus_store is not None:
        return RetrievalOperator(
            search_provider=CorpusSearchProvider(corpus_store),
            fetch_provider=CorpusFetchProvider(artifact_store),
            corpus_store=corpus_store,
        )
    profile_id = _research_profile_id(recipe)
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return RetrievalOperator(
            search_provider=FallbackSearchProvider(
                [
                    DirectUrlSearchProvider(),
                    SecEdgarSearchProvider(),
                    ResearchSourceQuerySearchProvider(),
                    SourceDirectorySearchProvider(),
                ]
            ),
            fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
        )
    if profile_id == TECHNICAL_DOCUMENTATION_PROFILE_ID:
        return RetrievalOperator(
            search_provider=FallbackSearchProvider(
                [
                    DirectUrlSearchProvider(),
                    ResearchSourceQuerySearchProvider(),
                    SourceDirectorySearchProvider(),
                ]
            ),
            fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
        )
    if profile_id == ACADEMIC_RESEARCH_PROFILE_ID:
        return RetrievalOperator(
            search_provider=FallbackSearchProvider(
                [
                    DirectUrlSearchProvider(),
                    ResearchSourceQuerySearchProvider(),
                    SourceDirectorySearchProvider(),
                ]
            ),
            fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
        )
    return RetrievalOperator(
        search_provider=UnconfiguredSearchProvider(reason="retrieval_source_not_configured"),
        fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
    )


def _retrieval_payload(goal: str, recipe: TaskRecipe) -> JsonObject:
    payload: JsonObject = {
        "goal_id": "goal-agent-retrieval",
        "query": goal,
        "max_spans_per_document": 2,
    }
    payload = _merge_retrieval_payload(payload, _retrieval_capability_args(recipe))
    payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
    preferences = _interaction_preferences_metadata(recipe)
    if preferences:
        metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
        metadata.setdefault("interaction_preferences", preferences)
        if isinstance(preferences.get("response_language"), str):
            metadata.setdefault("response_language", preferences["response_language"])
        payload["metadata"] = metadata
    payload.setdefault("goal_id", "goal-agent-retrieval")
    payload.setdefault("query", goal)
    payload.setdefault("max_spans_per_document", 2)
    payload = _apply_research_depth_defaults(payload)
    return payload


def _apply_research_depth_defaults(payload: JsonObject) -> JsonObject:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return payload
    profile_id = metadata.get("research_profile_id", metadata.get("research_profile"))
    if not isinstance(profile_id, str) or not profile_id:
        return payload
    depth = payload.get("research_depth", metadata.get("research_depth"))
    explicit_depth = isinstance(depth, str) and bool(depth)
    defaults = research_depth_defaults(profile_id, depth if isinstance(depth, str) else None)
    if not defaults:
        return payload
    merged = dict(payload)
    floor_budget = not (explicit_depth and str(depth).strip().lower() == "light")
    for key in ("max_queries", "max_sources", "max_fetches", "max_spans_per_document"):
        if key not in merged and key in defaults:
            if key == "max_queries":
                merged[key] = max(int(defaults[key]), _explicit_retrieval_query_count(merged))
            else:
                merged[key] = defaults[key]
        elif floor_budget and key in defaults and _should_floor_research_budget(merged, key):
            current = _positive_metadata_int(merged.get(key), default=0)
            if current > 0:
                floor = int(defaults[key])
                if key == "max_queries":
                    floor = max(floor, _explicit_retrieval_query_count(merged))
                merged[key] = max(current, floor)
    if "research_depth" not in merged and isinstance(depth, str) and depth:
        merged["research_depth"] = depth
    return merged


def _should_floor_research_budget(payload: JsonObject, key: str) -> bool:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if bool(metadata.get("respect_explicit_budget") or payload.get("respect_explicit_budget")):
        return False
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in {"market_data", "market_news", "macro_data", "competitive_landscape"}:
        return False
    if key == "max_queries" and str(metadata.get("search_strategy") or "").strip().lower() in {"corpus_only", "crawl"}:
        return False
    if key == "max_fetches":
        return False
    return key in {"max_queries", "max_sources", "max_fetches", "max_spans_per_document"}


def _explicit_retrieval_query_count(payload: JsonObject) -> int:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for container in (payload, metadata):
        for key in ("queries", "query_templates"):
            value = container.get(key)
            if isinstance(value, list):
                count = sum(1 for item in value if isinstance(item, str) and item.strip())
                if count > 0:
                    return count
    return 0


def _apply_profile_capability_defaults(payload: JsonObject, step: JsonObject) -> JsonObject:
    capabilities = set(_step_capabilities(step))
    updated = _apply_finance_capability_defaults(payload, capabilities)
    updated = _apply_academic_research_capability_defaults(updated, capabilities)
    return _apply_technical_documentation_capability_defaults(updated, capabilities)


def _apply_recipe_profile_defaults(payload: JsonObject, recipe: TaskRecipe) -> JsonObject:
    capabilities = _recipe_research_profile_capabilities(recipe)
    updated = _apply_finance_capability_defaults(payload, capabilities)
    updated = _apply_academic_research_capability_defaults(updated, capabilities)
    updated = _apply_technical_documentation_capability_defaults(updated, capabilities)
    profile_id = _research_profile_id(recipe)
    if profile_id == TECHNICAL_DOCUMENTATION_PROFILE_ID:
        return _apply_technical_documentation_capability_defaults(
            updated,
            capabilities | {"technical.documentation_research"},
        )
    if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID:
        return _apply_finance_capability_defaults(
            updated,
            capabilities | {"finance.fundamentals_research"},
        )
    if profile_id == ACADEMIC_RESEARCH_PROFILE_ID:
        return _apply_academic_research_capability_defaults(
            updated,
            capabilities | {"academic.research"},
        )
    return updated


def _apply_finance_capability_defaults(payload: JsonObject, capabilities: set[str]) -> JsonObject:
    if not capabilities.intersection(_FINANCE_RESEARCH_PROFILE_CAPABILITIES):
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata.setdefault("research_profile", FINANCE_FUNDAMENTALS_PROFILE_ID)
    if capabilities.intersection({"finance.market_news", "finance.market_data", "finance.competitive_landscape"}):
        metadata.setdefault("source_authority_requirement", "secondary_or_better")
        updated.setdefault("max_queries", 1)
        updated.setdefault("query_templates", ["{query}"])
        if "finance.market_news" in capabilities:
            metadata.setdefault("research_task_kind", "market_news")
        elif "finance.market_data" in capabilities:
            metadata.setdefault("research_task_kind", "market_data")
        else:
            metadata.setdefault("research_task_kind", "competitive_landscape")
    elif "finance.macro_data" in capabilities:
        metadata.setdefault("source_authority_requirement", "primary")
        metadata.setdefault("research_task_kind", "macro_data")
        metadata.setdefault("preferred_source_families", ["government_statistic", "central_bank_statistic", "treasury_data"])
        updated.setdefault("max_queries", 1)
        updated.setdefault("query_templates", ["{query}"])
    updated["metadata"] = metadata
    return updated


def _apply_technical_documentation_capability_defaults(payload: JsonObject, capabilities: set[str]) -> JsonObject:
    if not capabilities.intersection(_TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES):
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata.setdefault("research_profile", TECHNICAL_DOCUMENTATION_PROFILE_ID)
    metadata.setdefault("source_authority_requirement", "primary")
    metadata.setdefault("search_strategy", "aggregate")
    metadata.setdefault("preferred_source_families", ["official_documentation", "source_repository", "standards_body"])
    if "technical.api_documentation" in capabilities:
        metadata.setdefault("research_task_kind", "api_documentation")
    elif "technical.source_repository" in capabilities:
        metadata.setdefault("research_task_kind", "source_repository")
    elif "technical.developer_docs" in capabilities:
        metadata.setdefault("research_task_kind", "developer_docs")
    else:
        metadata.setdefault("research_task_kind", "technical_documentation")
    updated["metadata"] = metadata
    return updated


def _apply_academic_research_capability_defaults(payload: JsonObject, capabilities: set[str]) -> JsonObject:
    if not capabilities.intersection(_ACADEMIC_RESEARCH_PROFILE_CAPABILITIES):
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata.setdefault("research_profile", ACADEMIC_RESEARCH_PROFILE_ID)
    metadata.setdefault("source_authority_requirement", "secondary_or_better")
    metadata.setdefault("search_strategy", "aggregate")
    metadata.setdefault(
        "preferred_source_families",
        ["scholarly_preprint", "scholarly_publisher", "academic_repository", "scholarly_index"],
    )
    if "academic.frontier_research" in capabilities:
        metadata.setdefault("research_task_kind", "frontier_research")
    elif "academic.literature_review" in capabilities:
        metadata.setdefault("research_task_kind", "literature_review")
    elif "academic.paper_search" in capabilities:
        metadata.setdefault("research_task_kind", "paper_search")
    else:
        metadata.setdefault("research_task_kind", "academic_research")
    updated["metadata"] = metadata
    return updated


def _recipe_research_profile_capabilities(recipe: TaskRecipe) -> set[str]:
    capabilities: set[str] = set()
    semantic = _semantic_intake_metadata(recipe)
    intents = semantic.get("intents")
    if isinstance(intents, list):
        for intent in intents:
            if isinstance(intent, dict):
                capabilities.update(_string_list(intent.get("required_capabilities")))
    plan = _task_execution_plan_metadata(recipe)
    steps = plan.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                capabilities.update(_step_capabilities(step))
    return capabilities.intersection(
        _FINANCE_RESEARCH_PROFILE_CAPABILITIES
        | _ACADEMIC_RESEARCH_PROFILE_CAPABILITIES
        | _TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES
    )


def _retrieval_capability_args(recipe: TaskRecipe) -> JsonObject:
    step = _execution_step_metadata(recipe)
    if step is not None:
        args = _capability_args_from_step(step, "retrieval.run")
        if args:
            return args
    return _capability_args_from_plan(
        _task_execution_plan_metadata(recipe),
        "retrieval.run",
        capability_markers={
            "retrieval.run",
            *_FINANCE_RESEARCH_PROFILE_CAPABILITIES,
            *_ACADEMIC_RESEARCH_PROFILE_CAPABILITIES,
            *_TECHNICAL_DOCUMENTATION_PROFILE_CAPABILITIES,
        },
    )


def _retrieval_execution_args(recipe: TaskRecipe) -> JsonObject:
    metadata = _execution_metadata(recipe)
    direct = _direct_tool_payload(metadata, "retrieval.run")
    if direct:
        return direct
    nested = _nested_json(metadata, "retrieval.run") or _nested_json(metadata, "retrieval")
    return _direct_tool_payload(nested, "retrieval.run") if nested else {}


def _retrieval_network_fetch_budget(recipe_metadata: JsonObject) -> int:
    execution = recipe_metadata.get("execution_metadata")
    if not isinstance(execution, dict):
        return 0
    retrieval = execution.get("retrieval")
    if not isinstance(retrieval, dict):
        return 0
    if not bool(retrieval.get("allow_network") or retrieval.get("live_network_enabled")):
        return 0
    return _positive_metadata_int(
        retrieval.get("max_network_fetches", retrieval.get("max_fetches")),
        default=3,
    )


def _with_allowed_permission(recipe_metadata: JsonObject, permission: str) -> JsonObject:
    updated = dict(recipe_metadata)
    current = updated.get("allowed_permissions")
    values = [item for item in current if isinstance(item, str) and item] if isinstance(current, list) else []
    if permission not in values:
        values.append(permission)
    updated["allowed_permissions"] = values
    return updated


def _merge_retrieval_payload(base: JsonObject, extra: JsonObject) -> JsonObject:
    if not extra:
        return dict(base)
    merged = dict(base)
    for key, value in extra.items():
        if key == "metadata" and isinstance(value, dict):
            current = merged.get("metadata")
            merged["metadata"] = {
                **(dict(current) if isinstance(current, dict) else {}),
                **dict(value),
            }
        else:
            merged[key] = value
    return merged


def _retrieval_payload_urls(payload: JsonObject) -> list[str]:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    values = _metadata_url_values(payload, keys=("url", "urls", "source_url", "source_urls"))
    values.extend(_metadata_url_values(metadata, keys=("url", "urls", "source_url", "source_urls")))
    query = payload.get("query")
    if isinstance(query, str):
        values.extend(_urls_in_text(query))
    return _ordered_unique(values)


def _metadata_url_values(container: JsonObject, *, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = container.get(key)
        if isinstance(value, str) and _looks_like_url(value):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and _looks_like_url(item))
    return values


def _urls_in_text(text: str) -> list[str]:
    return _ordered_unique([
        item.rstrip(").,;，。；")
        for item in re.findall(r"https?://[^\s\"'<>]+", text)
        if _looks_like_url(item.rstrip(").,;，。；"))
    ])


def _looks_like_url(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("https://") or stripped.startswith("http://")


def _required_retrieval_source_urls(recipe: TaskRecipe) -> list[str]:
    values: list[str] = []
    values.extend(_retrieval_payload_urls(_retrieval_capability_args(recipe)))
    execution = _execution_metadata(recipe)
    mission = execution.get("research_mission")
    if isinstance(mission, dict):
        root_goal = mission.get("root_goal")
        if isinstance(root_goal, str):
            values.extend(_urls_in_text(root_goal))
    mission_context = _mission_context_metadata(recipe)
    mission_state = mission_context.get("mission_state")
    if isinstance(mission_state, dict):
        root_goal = mission_state.get("root_goal")
        if isinstance(root_goal, str):
            values.extend(_urls_in_text(root_goal))
    return _ordered_unique(values)


def _same_url_or_prefix(actual: str, required: str) -> bool:
    left = actual.strip().rstrip("/")
    right = required.strip().rstrip("/")
    return left == right or left.startswith(f"{right}?") or left.startswith(f"{right}#")


def _file_target(goal: str) -> str | None:
    for raw in goal.replace("，", " ").replace(",", " ").split():
        token = raw.strip("'\"`。；;:：")
        lowered = token.lower()
        if lowered.endswith((".md", ".txt", ".py", ".json", ".toml", ".yaml", ".yml")):
            return token
    return None


def _workspace_target(goal: str, plan: TaskExecutionPlan | JsonObject | None) -> tuple[str, str] | None:
    capability_args = _workspace_capability_args(plan)
    search_args = _nested_json(capability_args, "workspace.search")
    read_args = _nested_json(capability_args, "file.read")
    query = _string_value(search_args.get("query"))
    path = _string_value(read_args.get("path"))
    fallback = _file_target(goal)
    if path is None:
        path = fallback
    if query is None:
        query = path or fallback
    if path is None:
        return None
    return query or path, path


def _workspace_list_target(goal: str, plan: TaskExecutionPlan | JsonObject | None) -> str:
    capability_args = _workspace_capability_args(plan)
    list_args = _nested_json(capability_args, "workspace.list")
    search_args = _nested_json(capability_args, "workspace.search")
    path = _string_value(list_args.get("path")) or _string_value(search_args.get("path"))
    if path is not None:
        return path
    return "."


def _ambiguous_workspace_file_read(goal: str) -> bool:
    if _file_target(goal) is not None:
        return False
    normalized = goal.lower()
    return "file" in normalized or "文件" in normalized


def _task_plan_has_workspace_read_actions(plan: TaskExecutionPlan | JsonObject | None) -> bool:
    if plan is None:
        return False
    steps = plan.steps if isinstance(plan, TaskExecutionPlan) else plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list):
        return False
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        if str(raw_step.get("status") or "") != "ready":
            continue
        if str(raw_step.get("tool_name") or "") in {"workspace.list", "workspace.search", "file.read", "workspace.search,file.read"}:
            return True
    return False


def _workspace_write_target(goal: str, plan: TaskExecutionPlan | JsonObject | None) -> tuple[str, str] | None:
    capability_args = _workspace_write_capability_args(plan)
    write_args = _nested_json(capability_args, "workspace.write")
    path = _string_value(write_args.get("path")) or _file_target(goal)
    text = (
        _write_text_value(write_args.get("text"))
        or _write_text_value(write_args.get("content"))
        or _write_text_value(write_args.get("body"))
    )
    if path is None or text is None:
        return None
    return path, text


def _workspace_capability_args(plan: TaskExecutionPlan | JsonObject | None) -> JsonObject:
    return _capability_args_from_plan(
        plan,
        None,
        capability_markers={"workspace.list", "workspace.search", "file.read", "workspace:read"},
    )


def _workspace_write_capability_args(plan: TaskExecutionPlan | JsonObject | None) -> JsonObject:
    return _capability_args_from_plan(
        plan,
        None,
        capability_markers={"workspace.write", "workspace:write"},
    )


def _capability_args_from_plan(
    plan: TaskExecutionPlan | JsonObject | None,
    tool_name: str | None,
    *,
    capability_markers: set[str],
) -> JsonObject:
    if plan is None:
        return {}
    steps: object
    if isinstance(plan, TaskExecutionPlan):
        steps = plan.steps
    elif isinstance(plan, dict):
        steps = plan.get("steps")
    else:
        return {}
    if not isinstance(steps, list):
        return {}
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        capabilities = raw_step.get("required_capabilities")
        if not isinstance(capabilities, list) or not any(
            capability in capability_markers
            for capability in capabilities
            if isinstance(capability, str)
        ):
            continue
        args = _capability_args_from_step(raw_step, tool_name)
        if args:
            return args
    return {}


def _semantic_has_capability(semantic: JsonObject, capability: str) -> bool:
    return _semantic_has_any_capability(semantic, {capability})


def _semantic_has_any_capability(semantic: JsonObject, capabilities: set[str]) -> bool:
    intents = semantic.get("intents")
    if not isinstance(intents, list):
        return False
    return any(
        bool(capabilities.intersection(_string_list(item.get("required_capabilities"))))
        for item in intents
        if isinstance(item, dict)
    )


def _semantic_has_any_intent_kind(semantic: JsonObject, kinds: set[str]) -> bool:
    primary = str(semantic.get("primary_intent") or "").strip().lower()
    if primary in kinds:
        return True
    intents = semantic.get("intents")
    if not isinstance(intents, list):
        return False
    return any(
        str(item.get("kind") or "").strip().lower() in kinds
        for item in intents
        if isinstance(item, dict)
    )


def _semantic_has_any_domain(semantic: JsonObject, domains: set[str]) -> bool:
    candidates = _semantic_domain_values(semantic)
    return bool(domains.intersection(candidates))


def _semantic_domain_values(semantic: JsonObject) -> set[str]:
    values: set[str] = set()
    for key in ("domain", "task_domain", "research_domain"):
        value = semantic.get(key)
        if isinstance(value, str) and value.strip():
            values.add(value.strip().lower())
    metadata = semantic.get("metadata")
    if isinstance(metadata, dict):
        for key in ("domain", "task_domain", "research_domain"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                values.add(value.strip().lower())
    intents = semantic.get("intents")
    if isinstance(intents, list):
        for item in intents:
            if not isinstance(item, dict):
                continue
            for key in ("domain", "task_domain", "research_domain"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    values.add(value.strip().lower())
            item_metadata = item.get("metadata")
            if isinstance(item_metadata, dict):
                for key in ("domain", "task_domain", "research_domain"):
                    value = item_metadata.get(key)
                    if isinstance(value, str) and value.strip():
                        values.add(value.strip().lower())
    return values


def _plan_has_capability(plan: JsonObject, capability: str) -> bool:
    return _plan_has_any_capability(plan, {capability})


def _plan_has_any_capability(plan: JsonObject, capabilities: set[str]) -> bool:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False
    return any(
        bool(capabilities.intersection(_step_capabilities(step)))
        for step in steps
        if isinstance(step, dict)
    )


def _plan_has_any_step_kind(plan: JsonObject, kinds: set[str]) -> bool:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False
    return any(
        str(step.get("kind") or "").strip().lower() in kinds
        for step in steps
        if isinstance(step, dict)
    )


def _plan_has_any_domain(plan: JsonObject, domains: set[str]) -> bool:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        metadata = step.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        node_metadata = metadata.get("node_metadata")
        node_metadata = node_metadata if isinstance(node_metadata, dict) else {}
        profile = node_metadata.get("state_profile")
        profile = profile if isinstance(profile, dict) else {}
        for container in (step, metadata, node_metadata, profile):
            for key in ("domain", "task_domain", "research_domain"):
                value = container.get(key)
                if isinstance(value, str) and value.strip().lower() in domains:
                    return True
    return False


def _step_capabilities(raw_step: JsonObject) -> list[str]:
    return _string_list(raw_step.get("required_capabilities"))


def _capability_args_from_step(raw_step: JsonObject, tool_name: str | None) -> JsonObject:
    metadata = raw_step.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    capability_args = metadata.get("capability_args")
    if isinstance(capability_args, dict):
        if tool_name is None:
            return dict(capability_args)
        nested = _nested_json(capability_args, tool_name)
        return nested or _direct_tool_payload(capability_args, tool_name)
    node_metadata = metadata.get("node_metadata")
    if isinstance(node_metadata, dict) and isinstance(node_metadata.get("capability_args"), dict):
        if tool_name is None:
            return dict(node_metadata["capability_args"])
        nested = _nested_json(node_metadata["capability_args"], tool_name)
        return nested or _direct_tool_payload(node_metadata["capability_args"], tool_name)
    return {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _capability_payloads_from_step(raw_step: JsonObject, tool_name: str) -> list[JsonObject]:
    values: list[object] = []
    metadata = raw_step.get("metadata")
    if isinstance(metadata, dict):
        capability_args = metadata.get("capability_args")
        if isinstance(capability_args, dict):
            values.append(capability_args.get(tool_name))
        node_metadata = metadata.get("node_metadata")
        if isinstance(node_metadata, dict):
            node_args = node_metadata.get("capability_args")
            if isinstance(node_args, dict):
                values.append(node_args.get(tool_name))
    payloads: list[JsonObject] = []
    seen: set[str] = set()
    for value in values:
        candidates: list[JsonObject] = []
        if isinstance(value, dict):
            candidates.append(dict(value))
        elif isinstance(value, list):
            candidates.extend(dict(item) for item in value if isinstance(item, dict))
        for candidate in candidates:
            marker = repr(sorted(candidate.items()))
            if marker in seen:
                continue
            seen.add(marker)
            payloads.append(candidate)
    return payloads


def _direct_tool_payload(capability_args: JsonObject, tool_name: str) -> JsonObject:
    if tool_name == "retrieval.run":
        retrieval_keys = {
            "goal_id",
            "query",
            "max_queries",
            "max_sources",
            "max_fetches",
            "max_spans_per_document",
            "metadata",
            "research_profile",
            "research_profile_id",
            "research_depth",
            "queries",
            "query_templates",
            "url",
            "urls",
            "source_url",
            "source_urls",
            "seed_url",
            "seed_urls",
            "crawl_seed_url",
            "crawl_seed_urls",
        }
        if any(key in capability_args for key in retrieval_keys):
            result = dict(capability_args)
            metadata = dict(result.get("metadata")) if isinstance(result.get("metadata"), dict) else {}
            profile = result.pop("research_profile", None)
            profile_id = result.pop("research_profile_id", None)
            if isinstance(profile, str) and profile:
                metadata["research_profile"] = profile
            if isinstance(profile_id, str) and profile_id:
                metadata["research_profile_id"] = profile_id
            if metadata:
                result["metadata"] = metadata
            return result
    if tool_name == "workspace.write":
        if any(key in capability_args for key in {"path", "text", "content", "body"}):
            result = dict(capability_args)
            if "text" not in result:
                for alias in ("content", "body"):
                    value = result.get(alias)
                    if isinstance(value, str):
                        result["text"] = value
                        break
            return result
    return {}


def _nested_json(data: JsonObject, key: str) -> JsonObject:
    value = data.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _write_text_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _preview_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _positive_metadata_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _feedback(
    run_id: str,
    index: int,
    status: str,
    stop_reason: str | None,
    answer: str | None,
    missing_evidence: list[str],
) -> Feedback:
    return Feedback(
        feedback_id=f"fb-{run_id}-agent-{index}",
        run_id=run_id,
        status=status,
        stop_reason=stop_reason,
        answer=answer,
        missing_evidence=missing_evidence,
    )


def _latest_retrieval_report(journal: JournalStore, task_id: str, run_id: str) -> RetrievalReport | None:
    records = [
        record for record in journal.records(task_id=task_id, kind="retrieval_report")
        if record.run_id == run_id
    ]
    if not records:
        return None
    return RetrievalReport.from_dict(records[-1].data)


def _planned_retrieval_coverage(journal: JournalStore, task_id: str, run_id: str, recipe: TaskRecipe) -> JsonObject:
    planned_goal_ids: list[str] = _planned_retrieval_goal_ids_from_recipe(recipe)
    optional_goal_ids: list[str] = _planned_retrieval_goal_ids_from_recipe(recipe, required=False)
    diagnostic_goal_ids: list[str] = [*planned_goal_ids, *optional_goal_ids]
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        if record.data.get("name") != "retrieval.run":
            continue
        payload = record.data.get("payload")
        if not isinstance(payload, dict):
            continue
        goal_id = payload.get("goal_id")
        if isinstance(goal_id, str) and goal_id.startswith("goal-plan-"):
            diagnostic_goal_ids.append(goal_id)
    planned_goal_ids = _ordered_unique(planned_goal_ids)
    optional_goal_ids = [goal_id for goal_id in _ordered_unique(optional_goal_ids) if goal_id not in set(planned_goal_ids)]
    diagnostic_goal_ids = _ordered_unique([*diagnostic_goal_ids, *planned_goal_ids, *optional_goal_ids])
    if not planned_goal_ids:
        return {
            "required": False,
            "sufficient": True,
            "planned_goal_ids": [],
            "optional_goal_ids": optional_goal_ids,
            "complete_goal_ids": [],
            "incomplete_goal_ids": [],
            "latest_status_by_goal_id": {},
        }
    reports_by_goal: dict[str, JsonObject] = {}
    for record in journal.records(task_id=task_id, kind="retrieval_report"):
        if record.run_id != run_id:
            continue
        goal_id = record.data.get("goal_id")
        if isinstance(goal_id, str):
            reports_by_goal[goal_id] = dict(record.data)
    incomplete: list[str] = []
    statuses: JsonObject = {}
    for goal_id in diagnostic_goal_ids:
        report = reports_by_goal.get(goal_id)
        status = str(report.get("status")) if report is not None else "missing_report"
        statuses[goal_id] = status
    for goal_id in planned_goal_ids:
        status = statuses.get(goal_id, "missing_report")
        if status != "sufficient":
            incomplete.append(goal_id)
    incomplete_set = set(incomplete)
    return {
        "required": True,
        "sufficient": not incomplete,
        "planned_goal_ids": planned_goal_ids,
        "optional_goal_ids": optional_goal_ids,
        "complete_goal_ids": [goal_id for goal_id in planned_goal_ids if goal_id not in incomplete_set],
        "incomplete_goal_ids": incomplete,
        "latest_status_by_goal_id": statuses,
    }


def _planned_retrieval_goal_ids_from_recipe(recipe: TaskRecipe, *, required: bool = True) -> list[str]:
    return _ordered_unique(
        [
            str(subgoal["goal_id"])
            for subgoal in _planned_retrieval_subgoals_from_recipe(recipe)
            if isinstance(subgoal.get("goal_id"), str) and bool(subgoal.get("required", True)) == required
        ]
    )


def _planned_retrieval_subgoals_from_recipe(recipe: TaskRecipe) -> list[JsonObject]:
    plan = _task_execution_plan_metadata(recipe)
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    subgoals: list[JsonObject] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        if str(raw_step.get("status") or "") != "ready":
            continue
        if str(raw_step.get("tool_name") or "") != "retrieval.run":
            continue
        sequence = _plan_step_index(raw_step)
        step_goal = _string_value(raw_step.get("goal")) or ""
        metadata = raw_step.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        capability_args = metadata.get("capability_args")
        capability_args = capability_args if isinstance(capability_args, dict) else {}
        payloads = _retrieval_payloads_from_capability_args(capability_args.get("retrieval.run"))
        if not payloads:
            continue
        total = len(payloads)
        for index, payload in enumerate(payloads, start=1):
            goal_id = payload.get("goal_id")
            normalized_goal_id = goal_id if isinstance(goal_id, str) and goal_id else f"goal-plan-{sequence}" if total == 1 else f"goal-plan-{sequence}-{index}"
            payload_metadata = _json_object(payload.get("metadata"))
            subgoals.append(
                {
                    "goal_id": normalized_goal_id,
                    "sequence_index": sequence,
                    "payload_index": index,
                    "required": _retrieval_payload_required(payload),
                    "query": _preview_text(_string_value(payload.get("query")) or step_goal, 180),
                    "research_profile": _string_value(
                        payload_metadata.get("research_profile")
                        or payload_metadata.get("research_profile_id")
                        or payload.get("research_profile")
                        or payload.get("research_profile_id")
                    ),
                    "research_task_kind": _string_value(payload_metadata.get("research_task_kind")),
                    "source_authority_requirement": _string_value(payload_metadata.get("source_authority_requirement")),
                    "search_strategy": _string_value(payload_metadata.get("search_strategy")),
                    "query_count": _explicit_retrieval_query_count(payload),
                }
            )
    seen: set[str] = set()
    unique: list[JsonObject] = []
    for subgoal in subgoals:
        goal_id = str(subgoal["goal_id"])
        if goal_id in seen:
            continue
        seen.add(goal_id)
        unique.append(subgoal)
    return unique


def _retrieval_payload_required(payload: JsonObject) -> bool:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for container in (payload, metadata):
        value = container.get("subgoal_required")
        if isinstance(value, bool):
            return value
    return True


def _retrieval_payloads_from_capability_args(value: object) -> list[JsonObject]:
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _planned_retrieval_missing_evidence(journal: JournalStore, task_id: str, run_id: str, recipe: TaskRecipe) -> list[str]:
    coverage = _planned_retrieval_coverage(journal, task_id, run_id, recipe)
    incomplete = _string_list(coverage.get("incomplete_goal_ids"))
    if not incomplete:
        return []
    return _ordered_unique(["sufficient_retrieval_evidence", *[f"retrieval_subgoal:{goal_id}" for goal_id in incomplete]])


def _latest_action_is_no_planned_action(journal: JournalStore, task_id: str, run_id: str) -> bool:
    records = [
        record for record in journal.records(task_id=task_id, kind="action")
        if record.run_id == run_id
    ]
    if not records:
        return False
    reasons = records[-1].data.get("reasons")
    return isinstance(reasons, list) and "no_planned_action" in reasons


def _latest_action_has_reason(journal: JournalStore, task_id: str, run_id: str, reason: str) -> bool:
    records = [
        record for record in journal.records(task_id=task_id, kind="action")
        if record.run_id == run_id
    ]
    if not records:
        return False
    reasons = records[-1].data.get("reasons")
    return isinstance(reasons, list) and reason in reasons


def _retrieval_evidence(journal: JournalStore, task_id: str, run_id: str) -> list[EvidenceItem]:
    return [
        EvidenceItem.from_dict(record.data)
        for record in journal.records(task_id=task_id, kind="retrieval_evidence")
        if record.run_id == run_id
    ]


def _retrieval_citations(journal: JournalStore, task_id: str, run_id: str) -> list[CitationItem]:
    return [
        CitationItem.from_dict(record.data)
        for record in journal.records(task_id=task_id, kind="retrieval_citation")
        if record.run_id == run_id
    ]


WORKSPACE_SYNTHESIS_EVIDENCE_CHARS = 12000
WORKSPACE_SYNTHESIS_CITATION_CHARS = 2048


def _workspace_grounding(
    journal: JournalStore,
    task_id: str,
    run_id: str,
    *,
    artifact_store: ArtifactStore,
    evidence_char_limit: int = WORKSPACE_SYNTHESIS_EVIDENCE_CHARS,
    citation_char_limit: int = WORKSPACE_SYNTHESIS_CITATION_CHARS,
    synthesis_evidence_preview_chars: int = 4096,
    synthesis_citation_preview_chars: int = 2048,
) -> tuple[list[EvidenceItem], list[CitationItem], RetrievalReport]:
    evidence: list[EvidenceItem] = []
    citations: list[CitationItem] = []
    observations = [
        record for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
    ]
    for index, record in enumerate(observations, start=1):
        data = record.data
        if data.get("source") not in {"tool:workspace.list", "tool:workspace.search", "tool:file.read"} or data.get("status") != "ok":
            continue
        content = data.get("content", {})
        if not isinstance(content, dict):
            continue
        text = _workspace_observation_text(
            content,
            artifact_store=artifact_store,
            evidence_char_limit=evidence_char_limit,
            source=str(data.get("source") or ""),
        )
        if not text.strip():
            continue
        path = _workspace_observation_title(content, source=str(data.get("source") or ""))
        evidence_id = f"workspace-evidence-{index}"
        citation_id = f"workspace-cite-{index}"
        artifact_id = record.artifact_refs[0] if record.artifact_refs else f"artifact-{record.observation_ref or evidence_id}"
        item = EvidenceItem(
            evidence_id=evidence_id,
            goal_id="goal-workspace",
            span_id=f"workspace-span-{index}",
            document_id=f"workspace-doc-{index}",
            source_id=path,
            artifact_id=artifact_id,
            uri=f"workspace://{path}",
            title=path,
            text=text,
            score=1.0,
            payload_hash=str(data.get("payload_hash") or record.payload_hash),
            diagnostics={"record_ref": record.record_id, "source": str(data.get("source") or "")},
        )
        evidence.append(item)
        citations.append(
            CitationItem(
                citation_id=citation_id,
                goal_id="goal-workspace",
                evidence_id=evidence_id,
                artifact_id=artifact_id,
                uri=f"workspace://{path}",
                title=path,
                quote=text[:citation_char_limit],
                span_start=0,
                span_end=min(len(text), citation_char_limit),
                metadata={"record_ref": record.record_id},
            )
        )
    evidence = sorted(evidence, key=_workspace_evidence_priority)
    citation_by_evidence = {item.evidence_id: item for item in citations}
    citations = [citation_by_evidence[item.evidence_id] for item in evidence if item.evidence_id in citation_by_evidence]
    report = RetrievalReport(
        report_id="workspace-report",
        goal_id="goal-workspace",
        status="sufficient" if evidence else "insufficient_evidence",
        query_plan_id="workspace-plan",
        search_attempt_ids=[],
        fetch_attempt_ids=[],
        evidence_ids=[item.evidence_id for item in evidence],
        citation_ids=[item.citation_id for item in citations],
        evaluation_id="workspace-eval",
        artifact_refs=[item.artifact_id for item in evidence],
        preview="; ".join(item.text[:120] for item in evidence),
        diagnostics={
            "evidence_count": len(evidence),
            "citation_count": len(citations),
            "workspace_evidence_char_limit": evidence_char_limit,
            "workspace_citation_char_limit": citation_char_limit,
            "synthesis_evidence_preview_chars": synthesis_evidence_preview_chars,
            "synthesis_citation_preview_chars": synthesis_citation_preview_chars,
        },
    )
    return evidence, citations, report


def _workspace_evidence_priority(item: EvidenceItem) -> tuple[int, str]:
    source = str(item.diagnostics.get("source") or "")
    if source == "tool:file.read":
        return 0, item.evidence_id
    if source == "tool:workspace.list":
        return 1, item.evidence_id
    return 2, item.evidence_id


def _workspace_write_observations(journal: JournalStore, task_id: str, run_id: str):
    return [
        record
        for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
        and record.data.get("source") == "tool:workspace.write"
        and record.data.get("status") == "ok"
    ]


def _system_time_observations(journal: JournalStore, task_id: str, run_id: str):
    return [
        record
        for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
        and record.data.get("source") == "tool:system.time"
        and record.data.get("status") == "ok"
    ]


def _workspace_observation_text(
    content: JsonObject,
    *,
    artifact_store: ArtifactStore,
    evidence_char_limit: int,
    source: str = "",
) -> str:
    if source == "tool:workspace.list":
        return _workspace_listing_text(content)[:evidence_char_limit]
    if source == "tool:workspace.search":
        return _workspace_search_text(content)[:evidence_char_limit]
    artifact_id = content.get("artifact_id")
    if isinstance(artifact_id, str) and artifact_store.has_blob(artifact_id):
        payload = artifact_store.read_blob(artifact_id)
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        return str(text)[:evidence_char_limit]
    text_value = content.get("text")
    preview_value = content.get("text_preview")
    text = str(text_value if isinstance(text_value, str) else preview_value if isinstance(preview_value, str) else "")
    return text[:evidence_char_limit]


def _workspace_observation_title(content: JsonObject, *, source: str) -> str:
    if source == "tool:workspace.search":
        query = content.get("query")
        return f"workspace search: {query}" if isinstance(query, str) and query else "workspace search"
    path = content.get("path")
    return str(path) if isinstance(path, str) and path else "workspace"


def _workspace_listing_text(content: JsonObject) -> str:
    path = str(content.get("path") or ".")
    entries = content.get("entries")
    lines = [f"Workspace directory `{path}`:"]
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            item_path = str(item.get("path") or "")
            if not item_path:
                continue
            kind = str(item.get("kind") or "entry")
            size = item.get("size_bytes")
            suffix = f" ({size} bytes)" if isinstance(size, int) else ""
            lines.append(f"- {kind}: {item_path}{suffix}")
    return "\n".join(lines)


def _workspace_search_text(content: JsonObject) -> str:
    query = str(content.get("query") or "")
    matches = content.get("matches")
    lines = [f"Workspace search `{query}`:"]
    if isinstance(matches, list):
        for item in matches:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path:
                continue
            preview = str(item.get("text_preview") or "")
            if preview:
                lines.append(f"- {path}: {preview}")
            else:
                lines.append(f"- {path}")
    return "\n".join(lines)


def _grounded_answer(*, report: RetrievalReport, evidence: list[EvidenceItem], citations: list[CitationItem]) -> str:
    if not evidence:
        return ""
    joined = " ".join(item.text.strip() for item in evidence if item.text.strip())
    preview = joined[:360]
    if citations:
        return f"{preview} [{citations[0].citation_id}]"
    return preview or report.preview


def _report_with_task_goal(report: RetrievalReport, recipe: TaskRecipe) -> RetrievalReport:
    semantic = _semantic_intake_metadata(recipe)
    task_goal = semantic.get("goal")
    diagnostics = dict(report.diagnostics)
    if isinstance(task_goal, str) and task_goal.strip():
        diagnostics.setdefault("task_goal", task_goal.strip())
    answer_profile = _answer_profile_metadata(recipe)
    if answer_profile:
        diagnostics.setdefault("answer_profile", answer_profile)
        diagnostics.setdefault("answer_requirements", _final_answer_contract(answer_profile))
    research_mission = _research_mission_metadata(recipe)
    if research_mission:
        diagnostics.setdefault("research_mission", research_mission)
    preferences = _interaction_preferences_metadata(recipe)
    if preferences:
        diagnostics.setdefault("interaction_preferences", preferences)
        if isinstance(preferences.get("response_language"), str):
            diagnostics.setdefault("response_language", preferences["response_language"])
    return replace(report, diagnostics=diagnostics)


def _can_synthesize_partial_retrieval(
    *,
    terminal_reason: str | None,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    recipe: TaskRecipe,
) -> bool:
    if terminal_reason not in PARTIAL_RETRIEVAL_TERMINAL_REASONS:
        return False
    if not evidence:
        return False
    if recipe.citations_required and not citations:
        return False
    return True


def _report_with_partial_retrieval_limitations(
    report: RetrievalReport,
    *,
    planned_coverage: JsonObject,
    missing_evidence: list[str],
    terminal_reason: str | None,
) -> RetrievalReport:
    diagnostics = dict(report.diagnostics)
    existing_limitations = diagnostics.get("limitations")
    limitations = [str(item) for item in existing_limitations if isinstance(item, str)] if isinstance(existing_limitations, list) else []
    limitations.extend(
        [
            "retrieval_completed_partially",
            *missing_evidence,
        ]
    )
    diagnostics.update(
        {
            "partial_answer": True,
            "partial_answer_reason": terminal_reason or "retrieval_partial",
            "planned_retrieval_coverage": planned_coverage,
            "missing_evidence": _ordered_unique(missing_evidence),
            "limitations": _ordered_unique(limitations),
        }
    )
    return replace(report, diagnostics=diagnostics)


def _with_interaction_preferences(metadata: JsonObject | None, *, response_language: str) -> JsonObject:
    result = dict(metadata or {})
    current = result.get("interaction_preferences")
    preferences = dict(current) if isinstance(current, dict) else {}
    preferences.update(interaction_preferences(response_language=response_language))
    result["interaction_preferences"] = preferences
    return result


def _interaction_preferences_metadata(recipe: TaskRecipe) -> JsonObject:
    metadata = _execution_metadata(recipe).get("interaction_preferences")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _agent_final_from_processor(processor_answer, *, task_id: str, run_id: str, trace_refs: list[str]) -> FinalAnswer:
    return FinalAnswer(
        answer=processor_answer.answer or "",
        citation_refs=list(processor_answer.citation_refs),
        used_evidence=list(processor_answer.used_evidence),
        limitations=list(processor_answer.limitations),
        confidence=float(processor_answer.confidence),
        task_id=task_id,
        run_id=run_id,
        trace_refs=trace_refs,
    )


def _last_response_text(journal: JournalStore, task_id: str, run_id: str) -> str | None:
    for record in reversed(journal.records(task_id=task_id, kind="observation")):
        if record.run_id != run_id:
            continue
        content = record.data.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return str(content["text"])
    return None


def _trace_refs(journal: JournalStore, task_id: str) -> list[str]:
    return [record.record_id for record in journal.records(task_id=task_id)]


def _attempted_actions(journal: JournalStore, task_id: str, run_id: str) -> list[str]:
    actions = []
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        name = record.data.get("name")
        kind = record.data.get("kind")
        actions.append(str(name or kind or record.action_ref))
    return actions


def _attempted_sources(journal: JournalStore, task_id: str, run_id: str) -> list[str]:
    sources: list[str] = []
    for record in journal.records(task_id=task_id):
        if record.run_id != run_id:
            continue
        data = record.data
        if record.kind == "retrieval_search_attempt":
            for source in data.get("sources", []) if isinstance(data.get("sources"), list) else []:
                if isinstance(source, dict) and isinstance(source.get("uri"), str):
                    sources.append(source["uri"])
        if record.kind == "observation":
            content = data.get("content")
            if isinstance(content, dict):
                for key in ("path", "uri"):
                    value = content.get(key)
                    if isinstance(value, str):
                        sources.append(value)
    return _ordered_unique(sources)


def _missing_evidence(journal: JournalStore, task_id: str, run_id: str) -> list[str]:
    for record in reversed(journal.records(task_id=task_id, kind="feedback")):
        if record.run_id != run_id:
            continue
        missing = record.data.get("missing_evidence")
        if isinstance(missing, list):
            return [str(item) for item in missing]
    return []


def _latest_termination_failure_reason(journal: JournalStore, task_id: str, run_id: str) -> str | None:
    for record in reversed(journal.records(task_id=task_id, kind="termination_decision")):
        if record.run_id != run_id:
            continue
        if record.data.get("decision") == "failure_report" and isinstance(record.data.get("reason"), str):
            return str(record.data["reason"])
    return None


def _latest_guard_stop_reason(journal: JournalStore, task_id: str, run_id: str) -> str | None:
    for record in reversed(journal.records(task_id=task_id, kind="guard")):
        if record.run_id != run_id:
            continue
        reason = record.data.get("stop_reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def _last_observations(journal: JournalStore, task_id: str, run_id: str, *, limit: int = 3) -> list[JsonObject]:
    observations = []
    records = [
        record for record in journal.records(task_id=task_id, kind="observation")
        if record.run_id == run_id
    ]
    for record in records[-limit:]:
        data = dict(record.data)
        content = data.get("content")
        if isinstance(content, dict):
            compacted = dict(content)
            text = compacted.get("text")
            if isinstance(text, str) and len(text) > 240:
                compacted["text"] = text[:240] + "..."
            data["content"] = compacted
        observations.append(data)
    return observations


def _nested(value, *path):
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower())
    return safe.strip("-") or "default"
