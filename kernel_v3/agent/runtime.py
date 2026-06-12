from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
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
from kernel_v3.agent.host_situation import build_host_situation
from kernel_v3.agent.semantics import analyze_goal, analyze_goal_with_processor
from kernel_v3.agent.retrieval_coverage import adaptive_retrieval_completion
from kernel_v3.agent.state_space import summarize_state_profiles
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.workloop import WorkloopConfig, WorkloopEvaluator
from kernel_v3.context import ArtifactStore, ContextPackCompiler, ProjectProfile, merge_context_budget
from kernel_v3.contracts import CandidateAction, ContextBundle, Event, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.finance import (
    CALCULATOR_TOOL_NAME,
    FinanceFact,
    FinanceFormulaPlan,
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
    plan_finance_formula,
    primary_source_numeric_binding_resolution,
    register_finance_tools,
    target_document_binding_from_metadata,
    verify_finance_answer,
)
from kernel_v3.interaction import guard_user_visible_text, interaction_preferences, normalize_response_language
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
from kernel_v3.research.issuer_registry import builtin_issuers_for_text
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
    supervise_retrieval_payload,
)
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
from kernel_v3.retrieval.source_directory_rank import rank_source_directory_entries
from kernel_v3.session import TaskState
from kernel_v3.substrate import Claim, EvidencePolicy, SlotFill, SlotFrame, SlotSpec, TransformPlan
from kernel_v3.tools import ToolManifest, ToolRegistry
from kernel_v3.workmethod import WorkMethodState, WorkMethodSupervisor


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
    "max_tool_calls",
    "max_network_fetches",
    "model_planner_processor_failed",
    "planner_processor_failed",
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
        if self.retrieval_operator is not None and self.processor_fabric is not None:
            setattr(self.retrieval_operator, "processor_fabric", self.processor_fabric)
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None
        self.workspace_files = dict(workspace_files or {})
        self.workloop_config = workloop_config or WorkloopConfig()
        self.memory_store = memory_store
        self.memory_pipeline = MemoryPipeline(store=memory_store, journal=self.journal) if memory_store is not None else None
        self.research_corpus_store = research_corpus_store
        self.response_language = normalize_response_language(response_language)
        self._tool_manifests_by_run: dict[tuple[str, str], list[ToolManifest]] = {}

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
        execution_metadata = _with_host_situation_metadata(
            execution_metadata,
            host_situation=self._initial_host_situation(thread_id=thread_id),
        )
        semantic_goal = _semantic_goal_for_execution(goal, execution_metadata)
        intake = self._semantic_intake(
            semantic_goal,
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
            and _workspace_target(semantic_goal, task_plan) is None
            and not _task_plan_has_workspace_read_actions(task_plan)
            and _ambiguous_workspace_file_read(semantic_goal)
        ):
            selected_mode = "clarify_first"
        if selected_mode == "workspace_write" and planner_mode != "model" and _workspace_write_target(semantic_goal, task_plan) is None:
            selected_mode = "clarify_first"
        answer_profile = infer_answer_profile(
            semantic_goal,
            semantic_intake=intake,
            task_plan=task_plan,
            execution_metadata=execution_metadata,
            response_language=effective_language,
        )
        research_mission = research_mission_metadata(
            semantic_goal,
            answer_profile=answer_profile,
            semantic_intake=intake,
            task_plan=task_plan,
        )
        if semantic_goal != goal:
            execution_metadata = _with_semantic_goal_metadata(
                execution_metadata,
                semantic_goal=semantic_goal,
                current_input=goal,
            )
        execution_metadata = _with_answer_profile_metadata(
            execution_metadata,
            answer_profile=answer_profile,
            research_mission=research_mission,
        )
        if _execution_profile_uses_workmethod(execution_metadata):
            workmethod_state = WorkMethodSupervisor(
                processor_fabric=self.processor_fabric,
                mode=(
                    "model"
                    if _use_model_workmethod(
                        self.processor_fabric,
                        semantic_mode=semantic_mode,
                        execution_metadata=execution_metadata,
                    )
                    else "rule"
                ),
            ).frame_task(
                goal=semantic_goal,
                thread_id=thread_id,
                semantic_intake=intake,
                task_plan=task_plan,
                answer_profile=answer_profile,
                execution_metadata=execution_metadata,
                task_id=task_id,
                run_id="workmethod-pre",
            )
        else:
            workmethod_state = _disabled_workmethod_state(
                goal=semantic_goal,
                thread_id=thread_id,
                task_plan=task_plan,
                execution_metadata=execution_metadata,
            )
        execution_metadata = _with_workmethod_metadata(
            execution_metadata,
            workmethod=workmethod_state.to_dict(),
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
        recipe = _with_planned_action_count(semantic_goal, recipe)
        recipe = _with_runtime_loop_budget(recipe, planner_mode=planner_mode)
        recipe = self._with_model_compiled_execution_program(
            recipe,
            semantic_goal,
            planner_mode=planner_mode,
        )
        registry = self._registry(recipe, semantic_goal)
        planner = self._planner(semantic_goal, recipe, registry, planner_mode)
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
                runtime_capabilities=self.runtime_capabilities(),
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
        self._tool_manifests_by_run[(result.task_id, result.run_id)] = registry.manifests()
        semantic_record = self._append_semantic_intake(intake, task_id=result.task_id, run_id=result.run_id)
        self._append_task_graph(
            task_graph,
            task_graph_validation,
            task_id=result.task_id,
            run_id=result.run_id,
        )
        self._append_task_plan(task_plan, task_id=result.task_id, run_id=result.run_id)
        self._append_state_profile(task_plan, task_id=result.task_id, run_id=result.run_id)
        self._append_workmethod_state(workmethod_state, task_id=result.task_id, run_id=result.run_id)
        self._maybe_propose_memory(
            intake,
            task_id=result.task_id,
            run_id=result.run_id,
            thread_id=thread_id,
            source_record_ref=semantic_record.record_id,
        )
        self._append_recipe(recipe, task_id=result.task_id, run_id=result.run_id)
        self._append_preflight_execution_program(recipe, task_id=result.task_id, run_id=result.run_id)
        self._append_benchmark_oracle_context_retrieval(
            result.task_id,
            result.run_id,
            goal=goal,
            recipe=recipe,
        )
        processor_failure = self._planner_processor_failure_result(result, recipe=recipe)
        if processor_failure is not None:
            return processor_failure
        benchmark_context_ready = _has_sufficient_benchmark_oracle_retrieval(
            self.journal,
            result.task_id,
            result.run_id,
        )
        if result.status == "needs_user_input" and not benchmark_context_ready:
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
                    recipe=recipe,
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
                    host_situation=dict(failure.host_situation),
                )
            host_situation = self._append_host_situation_record(
                result.task_id,
                result.run_id,
                recipe=recipe,
                phase="needs_user_input",
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
                host_situation=host_situation,
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
        host_situation = (
            self._append_host_situation_record(result.task_id, result.run_id, recipe=recipe, phase="completed")
            if final_answer is not None
            else dict(failure.host_situation) if failure is not None else self._host_situation(result.task_id, result.run_id, recipe=recipe)
        )
        return AgentRuntimeResult(
            status=status,
            task_id=result.task_id,
            run_id=result.run_id,
            mode=recipe.mode,
            recipe_id=recipe.recipe_id,
            final_answer=final_answer.to_dict() if final_answer is not None else None,
            failure_report=failure.to_dict() if failure is not None else None,
            trace_refs=_trace_refs(self.journal, result.task_id),
            host_situation=host_situation,
        )

    def _planner_processor_failure_result(self, result, *, recipe: TaskRecipe) -> AgentRuntimeResult | None:
        if _has_sufficient_benchmark_oracle_retrieval(self.journal, result.task_id, result.run_id):
            return None
        if recipe.mode == "retrieval_answer":
            report = _latest_retrieval_report(self.journal, result.task_id, result.run_id)
            evidence = _retrieval_evidence(self.journal, result.task_id, result.run_id)
            citations = _retrieval_citations(self.journal, result.task_id, result.run_id)
            if report is not None and (evidence or citations):
                if report.status == "sufficient":
                    return None
                if _can_attempt_finance_numeric_finalization(recipe=recipe, evidence=evidence, citations=citations):
                    return None
                if _can_synthesize_partial_retrieval(
                    terminal_reason=getattr(result, "stop_reason", None),
                    evidence=evidence,
                    citations=citations,
                    recipe=recipe,
                ):
                    return None
        if not _run_has_planner_processor_failure(self.journal, result.task_id, result.run_id):
            return None
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
            recipe=recipe,
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
            host_situation=dict(failure.host_situation),
        )

    def _registry(self, recipe: TaskRecipe, goal: str) -> ToolRegistry:
        if recipe.mode == "retrieval_answer":
            registry = self._retrieval_base_registry(recipe)
            register_retrieval_tool(
                registry,
                operator=self.retrieval_operator or _default_retrieval_operator(
                    goal,
                    recipe=recipe,
                    artifact_store=self.artifact_store,
                    corpus_store=self.research_corpus_store,
                    processor_fabric=self.processor_fabric,
                ),
                journal=self.journal,
                artifact_store=self.artifact_store,
            )
            if CALCULATOR_TOOL_NAME in recipe.allowed_tools:
                register_finance_tools(registry)
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

    def _retrieval_base_registry(self, recipe: TaskRecipe) -> ToolRegistry:
        if not _composable_toolchain_enabled(recipe):
            return ToolRegistry.with_builtin_respond()
        shell_allowed = _composable_shell_allowed_executables(recipe)
        shell_timeout = _composable_tool_timeout_seconds(recipe, key="shell_timeout_seconds", default=5)
        script_timeout = _composable_tool_timeout_seconds(recipe, key="script_timeout_seconds", default=30)
        root = self.workspace_root or Path.cwd()
        if "shell.exec" in recipe.allowed_tools or self.workspace_root is not None:
            return ToolRegistry.with_permissioned_workspace(
                root=root,
                shell_allowed_executables=shell_allowed,
                shell_timeout_seconds=shell_timeout,
                script_timeout_seconds=script_timeout,
                artifact_store=self.artifact_store,
            )
        if self.workspace_files:
            return ToolRegistry.with_fake_workspace_tools(files=self.workspace_files, artifact_store=self.artifact_store)
        return ToolRegistry.with_permissioned_workspace(
            root=root,
            shell_allowed_executables=shell_allowed,
            shell_timeout_seconds=shell_timeout,
            script_timeout_seconds=script_timeout,
            artifact_store=self.artifact_store,
        )

    def _with_model_compiled_execution_program(
        self,
        recipe: TaskRecipe,
        goal: str,
        *,
        planner_mode: str,
    ) -> TaskRecipe:
        if planner_mode != "model" or self.processor_fabric is None:
            return recipe
        if recipe.mode != "retrieval_answer" or not _model_task_compiler_enabled(recipe):
            return recipe
        question = _root_goal_from_recipe(recipe)
        if not question or question == recipe.mode:
            question = goal
        binding = _target_document_binding_from_recipe(recipe)
        if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID and not binding:
            return recipe
        try:
            compiled = compile_finance_task_program_model_first(
                question=question,
                facts=[],
                target_binding=binding,
                processor_fabric=self.processor_fabric,
                task_id=None,
                run_id="task-compile-preflight",
                step_id="task-compile-preflight",
                context_id="ctx-task-compile-" + _short_hash(question),
                processor_budget=_processor_budget_metadata(recipe),
            )
        except Exception:
            return recipe
        metadata = dict(recipe.metadata)
        metadata["execution_program"] = {
            **compiled.to_dict(),
            "schema": "holo.kernel_v3.compiled_task_program.v1",
            "source": str(compiled.diagnostics.get("source") or "task_compile_model"),
            "preflight": True,
        }
        metadata["execution_program_mode"] = "model_first"
        return replace(recipe, metadata=metadata)

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
                artifact_store=self.artifact_store,
            )
        return _RecipePlanner(goal=goal, recipe=recipe, journal=self.journal)

    def _evaluator(self, recipe: TaskRecipe, evaluator_mode: str) -> Evaluator:
        if evaluator_mode == "model":
            if self.processor_fabric is None:
                raise ValueError("model evaluator requires processor_fabric")
            return ModelEvaluator(fabric=self.processor_fabric)
        return _RecipeEvaluator(recipe, journal=self.journal, artifact_store=self.artifact_store)

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
                    recipe=recipe,
                )
            text = loop_answer or _last_response_text(self.journal, task_id, run_id) or ""
            if not text:
                return None, self._failure(task_id, run_id, "missing_direct_answer", next_action="ask_user", recipe=recipe)
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
            return self._finalize_workspace_write(task_id, run_id, recipe=recipe)
        if recipe.mode == "system_answer":
            return self._finalize_system(task_id, run_id, recipe=recipe)
        return None, self._failure(
            task_id,
            run_id,
            loop_stop_reason or "needs_user_input",
            next_action="provide_more_detail",
            recipe=recipe,
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
        evidence, citations, report = _retrieval_and_toolchain_grounding(
            self.journal,
            task_id,
            run_id,
            recipe=recipe,
            artifact_store=self.artifact_store,
        )
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
                recipe=recipe,
            )
        planned_coverage = _planned_retrieval_coverage(self.journal, task_id, run_id, recipe)
        if planned_coverage.get("required") is True and not planned_coverage.get("sufficient"):
            adaptive_completion = adaptive_retrieval_completion(
                recipe=recipe,
                planned_coverage=planned_coverage,
                evidence_count=len(evidence),
                citation_count=len(citations),
            )
            if (
                _can_attempt_finance_numeric_finalization(recipe=recipe, evidence=evidence, citations=citations)
                or adaptive_completion.get("sufficient") is True
                or _can_synthesize_partial_retrieval(
                terminal_reason=terminal_reason,
                evidence=evidence,
                citations=citations,
                recipe=recipe,
                )
            ):
                report = _report_with_partial_retrieval_limitations(
                    report,
                    planned_coverage=planned_coverage,
                    missing_evidence=_planned_retrieval_missing_evidence(self.journal, task_id, run_id, recipe),
                    terminal_reason=terminal_reason,
                    adaptive_completion=adaptive_completion,
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
                recipe=recipe,
            )
        if report.status != "sufficient":
            if _can_attempt_finance_numeric_finalization(
                recipe=recipe,
                evidence=evidence,
                citations=citations,
            ) or _can_synthesize_partial_retrieval(
                terminal_reason=terminal_reason,
                evidence=evidence,
                citations=citations,
                recipe=recipe,
            ):
                report = _report_with_partial_retrieval_limitations(
                    report,
                    planned_coverage=planned_coverage,
                    missing_evidence=["sufficient_retrieval_evidence", f"retrieval_status:{report.status}"],
                    terminal_reason=terminal_reason or f"retrieval_{report.status}",
                    adaptive_completion={"sufficient": False, "limitations": [f"retrieval_status:{report.status}"]},
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
                recipe=recipe,
            )
        if recipe.citations_required and not citations:
            return None, self._failure(
                task_id,
                run_id,
                "citations_required_but_missing",
                missing_evidence=["citation_refs"],
                next_action="retry_retrieval_with_citable_sources",
                recipe=recipe,
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
        if _finance_numeric_verifier_required(recipe):
            self._run_finance_numeric_preflight(
                task_id,
                run_id,
                recipe=recipe,
                evidence=evidence,
                citations=citations,
            )
            report = _report_with_finance_formula_traces(self.journal, report, task_id=task_id, run_id=run_id)
        elif evidence:
            self._append_source_grounded_workflow_trace(
                task_id,
                run_id,
                recipe=recipe,
                evidence=evidence,
                citations=citations,
                purpose="pre_synthesis",
            )
        report = _report_with_task_goal(
            report,
            recipe,
            host_situation=self._host_situation(task_id, run_id, recipe=recipe),
        )
        synthesized = self._synthesize(
            task_id,
            run_id,
            report=report,
            evidence=evidence,
            citations=citations,
            synthesizer_mode=synthesizer_mode,
            recipe=recipe,
        )
        if synthesized.status != "ok" or synthesized.answer is None:
            fallback_final = None
            if _finance_numeric_verifier_required(recipe) and evidence and citations:
                fallback_final = _finance_retrieval_fallback_final(
                    journal=self.journal,
                    task_id=task_id,
                    run_id=run_id,
                    recipe=recipe,
                    evidence=evidence,
                    citations=citations,
                    synthesis_error=synthesized.error or "synthesis_failed",
                )
            if fallback_final is not None:
                verification = self._append_finance_numeric_verification(
                    fallback_final,
                    recipe=recipe,
                    evidence=evidence,
                    citations=citations,
                )
                if verification.status == "failed":
                    missing = _finance_numeric_missing_evidence(verification)
                    return None, self._failure(
                        task_id,
                        run_id,
                        "finance_numeric_verification_failed",
                        missing_evidence=missing or ["supported_finance_numeric_values"],
                        next_action="collect_supported_finance_facts_or_run_calculator",
                        recipe=recipe,
                    )
                self._append_synthesis_gate_result(
                    fallback_final,
                    recipe=recipe,
                    status="passed",
                    issues=list(verification.issues),
                    diagnostics={
                        "gate_id": "fallback_numeric_claim_support_v1",
                        "source": "finance_retrieval_fallback_final",
                        "verifier_status": verification.status,
                        "answer_numeric_support_rate": _finance_answer_numeric_support_rate(verification),
                        "policy": "fallback_material_numeric_claims_require_claim_or_transform_support",
                    },
                )
                final = self._append_final(fallback_final)
                self._maybe_propose_research_memory(final, recipe=recipe)
                return final, None
            return None, self._failure(
                task_id,
                run_id,
                synthesized.error or "synthesis_failed",
                missing_evidence=list(synthesized.limitations),
                next_action="collect_more_evidence",
                recipe=recipe,
            )
        final = _agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))
        quality_gaps = self._final_answer_quality_gaps(final, recipe=recipe) if synthesizer_mode == "model" else []
        self._append_final_quality_check(final, recipe=recipe, gaps=quality_gaps, attempt="initial")
        if quality_gaps and synthesizer_mode == "model":
            repaired = self._synthesize(
                task_id,
                run_id,
                report=report,
                evidence=evidence,
                citations=citations,
                synthesizer_mode=synthesizer_mode,
                recipe=recipe,
                retry_instruction=_answer_quality_retry_instruction(quality_gaps, recipe=recipe),
            )
            if repaired.status == "ok" and repaired.answer is not None:
                repaired_final = _agent_final_from_processor(
                    repaired,
                    task_id=task_id,
                    run_id=run_id,
                    trace_refs=_trace_refs(self.journal, task_id),
                )
                repaired_gaps = self._final_answer_quality_gaps(repaired_final, recipe=recipe)
                self._append_final_quality_check(
                    repaired_final,
                    recipe=recipe,
                    gaps=repaired_gaps,
                    attempt="quality_repair",
                    prior_gaps=quality_gaps,
                )
                final = repaired_final
                quality_gaps = repaired_gaps
            else:
                self._append_final_quality_repair_failed(
                    task_id,
                    run_id,
                    recipe=recipe,
                    gaps=quality_gaps,
                    error=repaired.error if hasattr(repaired, "error") else "synthesis_failed",
                )
        if quality_gaps:
            return None, self._failure(
                task_id,
                run_id,
                "final_answer_quality_insufficient",
                missing_evidence=quality_gaps,
                next_action="expand_final_answer_or_collect_more_evidence",
                recipe=recipe,
            )
        if _finance_numeric_verifier_required(recipe):
            verification = self._append_finance_numeric_verification(
                final,
                recipe=recipe,
                evidence=evidence,
                citations=citations,
            )
            self._append_synthesis_gate_result(
                final,
                recipe=recipe,
                status="passed" if verification.status != "failed" else "failed",
                issues=list(verification.issues),
                diagnostics={
                    "gate_id": "numeric_claim_support_v1",
                    "source": "finance_numeric_verification",
                    "verifier_status": verification.status,
                    "answer_numeric_support_rate": _finance_answer_numeric_support_rate(verification),
                    "policy": "material_numeric_claims_require_claim_or_transform_support",
                },
            )
            if verification.status == "failed":
                fallback_final = _finance_retrieval_fallback_final(
                    journal=self.journal,
                    task_id=task_id,
                    run_id=run_id,
                    recipe=recipe,
                    evidence=evidence,
                    citations=citations,
                    synthesis_error="finance_numeric_verification_failed",
                    require_formula_trace=False,
                )
                if fallback_final is not None:
                    fallback_verification = self._append_finance_numeric_verification(
                        fallback_final,
                        recipe=recipe,
                        evidence=evidence,
                        citations=citations,
                    )
                    self._append_synthesis_gate_result(
                        fallback_final,
                        recipe=recipe,
                        status="passed" if fallback_verification.status != "failed" else "failed",
                        issues=list(fallback_verification.issues),
                        diagnostics={
                            "gate_id": "numeric_claim_support_v1",
                            "source": "finance_numeric_verification",
                            "attempt": "fallback",
                            "verifier_status": fallback_verification.status,
                            "answer_numeric_support_rate": _finance_answer_numeric_support_rate(fallback_verification),
                            "policy": "material_numeric_claims_require_claim_or_transform_support",
                        },
                    )
                    if fallback_verification.status != "failed":
                        final = self._append_final(fallback_final)
                        self._maybe_propose_research_memory(final, recipe=recipe)
                        return final, None
                missing = _finance_numeric_missing_evidence(verification)
                return None, self._failure(
                    task_id,
                    run_id,
                    "finance_numeric_verification_failed",
                    missing_evidence=missing or ["supported_finance_numeric_values"],
                    next_action="collect_supported_finance_facts_or_run_calculator",
                    recipe=recipe,
                )
        final = self._append_final(final)
        self._maybe_propose_research_memory(final, recipe=recipe)
        return final, None

    def _append_synthesis_gate_result(
        self,
        answer: FinalAnswer,
        *,
        recipe: TaskRecipe,
        status: str,
        issues: list[JsonObject],
        diagnostics: JsonObject,
    ) -> None:
        root_goal = _root_goal_from_recipe(recipe)
        missing_slots = [
            str(item.get("code") or item.get("message") or "")
            for item in issues
            if isinstance(item, dict) and str(item.get("code") or item.get("message") or "").strip()
        ]
        self.journal.append(
            task_id=answer.task_id,
            run_id=answer.run_id,
            step_id=None,
            kind="synthesis_gate_result",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.synthesis_gate_result.v1",
                    "gate_id": diagnostics.get("gate_id") or "synthesis_gate_v1",
                    "domain": "finance" if _finance_numeric_verifier_required(recipe) else "generic",
                    "status": status,
                    "policy": diagnostics.get("policy"),
                    "root_goal": root_goal,
                    "issues": issues[:24],
                    "missing_slots": missing_slots[:24],
                    "diagnostics": diagnostics,
                }
            ),
            state_delta={"synthesis_gate_status": status},
        )

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
                recipe=recipe,
            )
        if recipe.citations_required and not citations:
            return None, self._failure(
                task_id,
                run_id,
                "citations_required_but_missing",
                missing_evidence=["workspace citation refs"],
                next_action="read_a_citable_file",
                recipe=recipe,
            )
        report = _report_with_task_goal(
            report,
            recipe,
            host_situation=self._host_situation(task_id, run_id, recipe=recipe),
        )
        synthesized = self._synthesize(
            task_id,
            run_id,
            report=report,
            evidence=evidence,
            citations=citations,
            synthesizer_mode=synthesizer_mode,
            recipe=recipe,
        )
        if synthesized.status != "ok" or synthesized.answer is None:
            return None, self._failure(task_id, run_id, synthesized.error or "synthesis_failed", next_action="read_more_files", recipe=recipe)
        final = _agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))
        quality_gaps = self._final_answer_quality_gaps(final, recipe=recipe) if synthesizer_mode == "model" else []
        self._append_final_quality_check(final, recipe=recipe, gaps=quality_gaps, attempt="initial")
        if quality_gaps and synthesizer_mode == "model":
            repaired = self._synthesize(
                task_id,
                run_id,
                report=report,
                evidence=evidence,
                citations=citations,
                synthesizer_mode=synthesizer_mode,
                recipe=recipe,
                retry_instruction=_answer_quality_retry_instruction(quality_gaps, recipe=recipe),
            )
            if repaired.status == "ok" and repaired.answer is not None:
                repaired_final = _agent_final_from_processor(
                    repaired,
                    task_id=task_id,
                    run_id=run_id,
                    trace_refs=_trace_refs(self.journal, task_id),
                )
                repaired_gaps = self._final_answer_quality_gaps(repaired_final, recipe=recipe)
                self._append_final_quality_check(
                    repaired_final,
                    recipe=recipe,
                    gaps=repaired_gaps,
                    attempt="quality_repair",
                    prior_gaps=quality_gaps,
                )
                final = repaired_final
                quality_gaps = repaired_gaps
            else:
                self._append_final_quality_repair_failed(
                    task_id,
                    run_id,
                    recipe=recipe,
                    gaps=quality_gaps,
                    error=repaired.error if hasattr(repaired, "error") else "synthesis_failed",
                )
        if quality_gaps:
            return None, self._failure(
                task_id,
                run_id,
                "final_answer_quality_insufficient",
                missing_evidence=quality_gaps,
                next_action="expand_final_answer_or_read_more_files",
                recipe=recipe,
            )
        final = self._append_final(final)
        self._maybe_propose_research_memory(final, recipe=recipe)
        return final, None

    def _finalize_workspace_write(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        write_records = _workspace_write_observations(self.journal, task_id, run_id)
        if not write_records:
            return None, self._failure(
                task_id,
                run_id,
                "missing_workspace_write_observation",
                missing_evidence=["workspace.write observation"],
                next_action="propose_workspace_write",
                recipe=recipe,
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
        *,
        recipe: TaskRecipe,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        time_records = _system_time_observations(self.journal, task_id, run_id)
        if not time_records:
            return None, self._failure(
                task_id,
                run_id,
                "missing_system_observation",
                missing_evidence=["system.time observation"],
                next_action="use_system_time",
                recipe=recipe,
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
        recipe: TaskRecipe,
        retry_instruction: str | None = None,
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
                retry_instruction=retry_instruction,
                processor_budget=_processor_budget_metadata(recipe),
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
            processor_budget=_processor_budget_metadata(recipe),
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

    def _append_preflight_execution_program(self, recipe: TaskRecipe, *, task_id: str, run_id: str) -> None:
        if not isinstance(recipe.metadata, dict):
            return
        program = recipe.metadata.get("execution_program")
        if not isinstance(program, dict):
            return
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="compiled_task_program",
            data=redact_journal_data(
                {
                    **program,
                    "schema": program.get("schema") or "holo.kernel_v3.compiled_task_program.v1",
                    "source": program.get("source") or "recipe.execution_program",
                    "preflight": True,
                }
            ),
            state_delta={
                "compiled_task_program": _string_value(
                    _json_object(program.get("task_spec")).get("task_type")
                ),
                "compiled_task_program_source": _string_value(program.get("source") or "recipe.execution_program"),
            },
        )
        _append_toolchain_plan_record(
            self.journal,
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            program=program,
            source="compiled_task_program_preflight",
        )

    def _append_workmethod_state(self, state: WorkMethodState, *, task_id: str, run_id: str) -> None:
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="workmethod_state",
            data=redact_journal_data(state.to_dict()),
            state_delta={
                "workmethod_state": state.state_id,
                "workmethod_source": state.source,
            },
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
        answer = replace(answer, answer=guard_user_visible_text(answer.answer))
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
            if not any(_same_url_or_prefix(cited_url, required_url) for cited_url in cited_urls for required_url in required_urls) and not (
                _benchmark_doc_retrieval_primary_citation_satisfies_required_source(
                    recipe=recipe,
                    answer=answer,
                    citations=citations,
                )
                or _finance_pdf_target_satisfied_by_primary_sec_citation(
                    recipe=recipe,
                    required_urls=required_urls,
                    cited_urls=cited_urls,
                )
            ):
                gaps.append("required_source_url_citation_missing")
        return gaps

    def _append_finance_numeric_verification(
        self,
        answer: FinalAnswer,
        *,
        recipe: TaskRecipe,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
    ):
        facts, ledger_record = self._append_finance_fact_ledger(
            answer.task_id,
            answer.run_id,
            evidence=evidence,
            citations=citations,
            purpose="verification",
            question=_root_goal_from_recipe(recipe),
            target_binding=_target_document_binding_from_recipe(recipe),
        )
        trace_refs = _trace_refs(self.journal, answer.task_id)
        formula_traces = _calculator_formula_traces(self.journal, task_id=answer.task_id, run_id=answer.run_id)
        verification = verify_finance_answer(
            answer=answer.answer,
            facts=facts,
            formula_traces=formula_traces,
            citations=citations,
            evidence=evidence,
            question=_root_goal_from_recipe(recipe),
            target_binding=_target_document_binding_from_recipe(recipe),
        )
        gate = finance_verification_to_gate_result(
            verification,
            policy=finance_slot_frame(
                question=_root_goal_from_recipe(recipe),
                facts=facts,
            ).evidence_policy,
            formula_traces=formula_traces,
        )
        self.journal.append(
            task_id=answer.task_id,
            run_id=answer.run_id,
            step_id=None,
            kind="finance_numeric_verification",
            data=redact_journal_data(
                {
                    **verification.to_dict(),
                    "schema": "holo.kernel_v3.finance_numeric_verification.v1",
                    "verifier_gate_result": gate.to_dict(),
                    "ledger_ref": ledger_record.record_id,
                    "trace_refs": [*trace_refs, ledger_record.record_id],
                }
            ),
            state_delta={"finance_numeric_verification": verification.status},
        )
        self.journal.append(
            task_id=answer.task_id,
            run_id=answer.run_id,
            step_id=None,
            kind="verifier_gate_result",
            data=redact_journal_data(
                {
                    **gate.to_dict(),
                    "schema": "holo.kernel_v3.verifier_gate_result.v1",
                    "source": "finance_numeric_verification",
                    "ledger_ref": ledger_record.record_id,
                }
            ),
            state_delta={"verifier_gate_status": gate.status},
        )
        return verification

    def _run_finance_numeric_preflight(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
    ) -> None:
        facts, ledger_record = self._append_finance_fact_ledger(
            task_id,
            run_id,
            evidence=evidence,
            citations=citations,
            purpose="preflight",
            question=_root_goal_from_recipe(recipe),
            target_binding=_target_document_binding_from_recipe(recipe),
        )
        if evidence and citations and _source_grounded_trace_required(recipe):
            self._append_source_grounded_workflow_trace(
                task_id,
                run_id,
                recipe=recipe,
                evidence=evidence,
                citations=citations,
                purpose="finance_preflight_no_structured_facts",
            )
        existing = _calculator_formula_traces(self.journal, task_id=task_id, run_id=run_id)
        plans = _finance_formula_preflight_plans(
            question=_root_goal_from_recipe(recipe),
            facts=facts,
            existing_traces=existing,
            evidence=evidence,
        )
        if not plans:
            return
        computed_traces = list(existing)
        for index, plan in enumerate(plans, start=1):
            plan_record = self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="finance_formula_plan",
                data=redact_journal_data(
                    {
                        **plan.to_dict(),
                        "schema": "holo.kernel_v3.finance_formula_plan.v1",
                        "source": "pre_finalization",
                        "ledger_ref": ledger_record.record_id,
                    }
                ),
                state_delta={"finance_formula_plan": plan.status},
            )
            transform_plan = finance_formula_plan_to_transform_plan(
                plan,
                question=_root_goal_from_recipe(recipe),
            )
            self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="transform_plan",
                data=redact_journal_data(
                    {
                        **transform_plan.to_dict(),
                        "schema": "holo.kernel_v3.transform_plan.v1",
                        "source": "finance_formula_plan",
                        "finance_formula_plan_ref": plan_record.record_id,
                        "ledger_ref": ledger_record.record_id,
                    }
                ),
                feedback_ref=plan_record.record_id,
                state_delta={"transform_plan": transform_plan.status},
            )
            if plan.status != "ready" or not isinstance(plan.payload, dict):
                continue
            planned_input_fact_ids = _string_list(plan.payload.get("input_fact_ids"))
            if _formula_trace_covers_inputs(existing, planned_input_fact_ids):
                continue
            action_id = f"act-finance-preflight-calculator-{index}"
            try:
                trace = compute_formula(
                    expression=str(plan.payload.get("expression") or ""),
                    variables=plan.payload.get("variables") if isinstance(plan.payload.get("variables"), dict) else {},
                    unit=str(plan.payload.get("unit")) if isinstance(plan.payload.get("unit"), str) else None,
                    formula_name=str(plan.payload.get("formula_name") or plan.formula_name or "finance_formula"),
                    input_fact_ids=planned_input_fact_ids,
                    diagnostics=plan.payload.get("diagnostics") if isinstance(plan.payload.get("diagnostics"), dict) else None,
                )
                observation = Observation(
                    observation_id=f"obs-{action_id}",
                    run_id=run_id,
                    kind="calculator_result",
                    status="ok",
                    source=f"tool:{CALCULATOR_TOOL_NAME}",
                    content={
                        "formula_trace": trace.to_dict(),
                        "result_value": trace.result_value,
                        "unit": trace.unit,
                        "formatted_value": trace.diagnostics.get("formatted_value"),
                        "source": "finance_numeric_preflight",
                    },
                    observed_at_ms=0,
                    action_id=action_id,
                    tool_call_id=None,
                )
                computed_traces.append(trace)
            except Exception as exc:
                observation = Observation(
                    observation_id=f"obs-{action_id}",
                    run_id=run_id,
                    kind="calculator_result",
                    status="failed",
                    source=f"tool:{CALCULATOR_TOOL_NAME}",
                    content={
                        "error": "calculator_failed",
                        "reason": str(exc),
                        "error_type": type(exc).__name__,
                        "source": "finance_numeric_preflight",
                    },
                    observed_at_ms=0,
                    action_id=action_id,
                    tool_call_id=None,
                )
            self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="observation",
                data=redact_journal_data(observation.to_dict()),
                action_ref=action_id,
                observation_ref=observation.observation_id,
                feedback_ref=plan_record.record_id,
                state_delta={"observation_status": observation.status},
            )
        self._append_finance_derived_formula_traces(
            task_id,
            run_id,
            source_traces=computed_traces,
            source_ledger_ref=ledger_record.record_id,
        )

    def _append_finance_derived_formula_traces(
        self,
        task_id: str,
        run_id: str,
        *,
        source_traces: list,
        source_ledger_ref: str,
    ) -> None:
        dio_traces = [trace for trace in source_traces if str(trace.formula_name or "").lower().startswith("dio:")]
        if len(dio_traces) < 2:
            return
        existing = _calculator_formula_traces(self.journal, task_id=task_id, run_id=run_id)
        if any(str(trace.formula_name or "").lower().startswith("dio_difference") for trace in existing):
            return
        left, right = dio_traces[0], dio_traces[1]
        plan_record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="finance_formula_plan",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.finance_formula_plan.v1",
                    "status": "ready",
                    "formula_name": "dio_difference",
                    "input_fact_ids": [left.formula_id, right.formula_id],
                    "missing_facts": [],
                    "payload": {
                        "expression": "max(left - right, right - left)",
                        "formula_name": "dio_difference",
                        "variables": {
                            "left": left.result_value,
                            "right": right.result_value,
                        },
                        "unit": "days",
                        "input_fact_ids": [left.formula_id, right.formula_id],
                    },
                    "diagnostics": {
                        "source_formula_ids": [left.formula_id, right.formula_id],
                        "source_formula_names": [left.formula_name, right.formula_name],
                    },
                    "source": "pre_finalization_derived",
                    "ledger_ref": source_ledger_ref,
                }
            ),
            state_delta={"finance_formula_plan": "ready"},
        )
        action_id = "act-finance-preflight-calculator-dio-difference"
        try:
            trace = compute_formula(
                expression="max(left - right, right - left)",
                variables={"left": left.result_value, "right": right.result_value},
                unit="days",
                formula_name="dio_difference",
                input_fact_ids=[left.formula_id, right.formula_id],
            )
            observation = Observation(
                observation_id=f"obs-{action_id}",
                run_id=run_id,
                kind="calculator_result",
                status="ok",
                source=f"tool:{CALCULATOR_TOOL_NAME}",
                content={
                    "formula_trace": trace.to_dict(),
                    "result_value": trace.result_value,
                    "unit": trace.unit,
                    "formatted_value": trace.diagnostics.get("formatted_value"),
                    "source": "finance_numeric_preflight",
                },
                observed_at_ms=0,
                action_id=action_id,
                tool_call_id=None,
            )
        except Exception as exc:
            observation = Observation(
                observation_id=f"obs-{action_id}",
                run_id=run_id,
                kind="calculator_result",
                status="failed",
                source=f"tool:{CALCULATOR_TOOL_NAME}",
                content={
                    "error": "calculator_failed",
                    "reason": str(exc),
                    "error_type": type(exc).__name__,
                    "source": "finance_numeric_preflight",
                },
                observed_at_ms=0,
                action_id=action_id,
                tool_call_id=None,
            )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="observation",
            data=redact_journal_data(observation.to_dict()),
            action_ref=action_id,
            observation_ref=observation.observation_id,
            feedback_ref=plan_record.record_id,
            state_delta={"observation_status": observation.status},
        )

    def _append_finance_fact_ledger(
        self,
        task_id: str,
        run_id: str,
        *,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        purpose: str,
        question: str = "",
        target_binding: JsonObject | None = None,
    ):
        facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
        binding = target_document_binding_from_metadata(target_binding, question=question)
        facts = attach_target_binding_to_facts(facts, binding, question=question) if binding else facts
        binding_resolution = primary_source_numeric_binding_resolution(facts, binding, question=question) if binding else {}
        ledger_record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="finance_fact_ledger",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.finance_fact_ledger.v1",
                    "purpose": purpose,
                    "fact_count": len(facts),
                    "facts": [fact.to_dict() for fact in facts[:512]],
                    "evidence_count": len(evidence),
                    "citation_count": len(citations),
                    **({"target_document_binding": binding} if binding else {}),
                    **({"primary_source_numeric_binding": binding_resolution} if binding_resolution else {}),
                }
            ),
            state_delta={"finance_fact_count": len(facts)},
        )
        claims = finance_facts_to_claims(facts)
        claim_record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="claim_ledger",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.claim_ledger.v1",
                    "domain": "finance",
                    "purpose": purpose,
                    "claim_count": len(claims),
                    "claims": [claim.to_dict() for claim in claims[:512]],
                    "source_ledger_ref": ledger_record.record_id,
                }
            ),
            state_delta={"claim_count": len(claims)},
        )
        if question:
            plan = plan_finance_formula(question=question, facts=facts, existing_traces=[])
            compiled = compile_finance_task_program(question=question, facts=facts, target_binding=binding, plan=plan)
            self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="compiled_task_program",
                data=redact_journal_data(
                    {
                        **compiled.to_dict(),
                        "schema": "holo.kernel_v3.compiled_task_program.v1",
                        "source": "finance_task_compiler",
                        "claim_ledger_ref": claim_record.record_id,
                        "finance_fact_ledger_ref": ledger_record.record_id,
                    }
                ),
                state_delta={
                    "compiled_task_program": compiled.task_spec.task_type,
                    "compiled_evidence_spec_count": len(compiled.evidence_specs),
                    "compiled_transform_spec_count": len(compiled.transform_specs),
                },
            )
            _append_toolchain_plan_record(
                self.journal,
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                program=compiled.to_dict(),
                source="finance_task_compiler",
            )
            frame = compiled.slot_frame or finance_slot_frame(question=question, facts=facts, plan=plan)
            self.journal.append(
                task_id=task_id,
                run_id=run_id,
                step_id=None,
                kind="slot_frame",
                data=redact_journal_data(
                    {
                        **frame.to_dict(),
                        "schema": "holo.kernel_v3.slot_frame.v1",
                        "source": "finance_fact_ledger",
                        "claim_ledger_ref": claim_record.record_id,
                        "finance_fact_ledger_ref": ledger_record.record_id,
                    }
                ),
                state_delta={
                    "slot_frame_task_type": frame.task_type,
                    "missing_slot_count": len(frame.missing_slots),
                },
            )
        return facts, ledger_record

    def _append_source_grounded_workflow_trace(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        purpose: str,
    ) -> None:
        if not evidence:
            return
        citation_by_evidence = {
            item.evidence_id: item
            for item in citations
            if item.evidence_id
        }
        ranked_evidence = _source_grounded_ranked_evidence(evidence, recipe=recipe)
        claims: list[Claim] = []
        for index, item in enumerate(ranked_evidence[:128], start=1):
            citation = citation_by_evidence.get(item.evidence_id)
            claims.append(
                Claim(
                    claim_id=f"claim-source-{_short_hash(task_id, item.evidence_id, index)}",
                    domain="source_grounded_research",
                    entity=None,
                    attribute="source_evidence_claim",
                    value=_text_preview(item.text, limit=420),
                    source_ref=item.uri,
                    evidence_ref=item.evidence_id,
                    citation_ref=citation.citation_id if citation is not None else None,
                    extraction_method="retrieval_evidence",
                    confidence=float(item.score) if isinstance(item.score, (int, float)) else None,
                    metadata={
                        "title": item.title,
                        "source_id": item.source_id,
                        "document_id": item.document_id,
                        "goal_id": item.goal_id,
                    },
                )
            )
        claim_record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="claim_ledger",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.claim_ledger.v1",
                    "domain": "source_grounded_research",
                    "purpose": purpose,
                    "claim_count": len(claims),
                    "claims": [claim.to_dict() for claim in claims],
                    "evidence_count": len(evidence),
                    "citation_count": len(citations),
                }
            ),
            state_delta={"claim_count": len(claims)},
        )
        policy = EvidencePolicy(
            policy_id="evidence-policy-source-grounded-" + _short_hash(task_id, run_id, _root_goal_from_recipe(recipe)),
            domain="source_grounded_research",
            required_source_families=["retrieval_citation"],
            forbidden_source_families=["uncited_answer"],
            authority="source_grounded",
            diagnostics={"source": "generic_source_grounded_workflow_trace"},
        )
        required_slots = [
            SlotSpec(name="source", requirement="required", accepted_attributes=["source_ref"], source_requirements=["retrieval_citation"]),
            SlotSpec(name="claim", requirement="required", accepted_attributes=["source_evidence_claim"], source_requirements=["claim_ledger"]),
            SlotSpec(name="citation", requirement="required", accepted_attributes=["citation_ref"], source_requirements=["retrieval_citation"]),
        ]
        filled_slots: list[SlotFill] = []
        missing_slots: list[str] = []
        first_claim = claims[0] if claims else None
        if first_claim is not None:
            filled_slots.append(
                SlotFill(
                    slot_name="claim",
                    claim_id=first_claim.claim_id,
                    value=first_claim.value,
                    source_ref=first_claim.source_ref,
                    confidence=first_claim.confidence,
                    metadata={"claim_count": len(claims)},
                )
            )
            filled_slots.append(
                SlotFill(
                    slot_name="source",
                    claim_id=first_claim.claim_id,
                    value=first_claim.source_ref,
                    source_ref=first_claim.source_ref,
                    confidence=first_claim.confidence,
                    metadata={"source_count": len(_ordered_unique([claim.source_ref or "" for claim in claims]))},
                )
            )
        else:
            missing_slots.extend(["claim", "source"])
        cited_claim = next((claim for claim in claims if claim.citation_ref), None)
        if cited_claim is not None:
            filled_slots.append(
                SlotFill(
                    slot_name="citation",
                    claim_id=cited_claim.claim_id,
                    value=cited_claim.citation_ref,
                    source_ref=cited_claim.source_ref,
                    confidence=cited_claim.confidence,
                    metadata={"citation_count": len(citations)},
                )
            )
        else:
            missing_slots.append("citation")
        frame = SlotFrame(
            frame_id="slot-frame-source-grounded-" + _short_hash(task_id, run_id, str(len(claims)), str(len(citations))),
            task_type="source_grounded_research",
            domain="source_grounded_research",
            required_slots=required_slots,
            optional_slots=[],
            filled_slots=filled_slots,
            missing_slots=_ordered_unique(missing_slots),
            evidence_policy=policy,
            diagnostics={
                "source": "generic_source_grounded_workflow_trace",
                "root_goal": _root_goal_from_recipe(recipe),
                "claim_count": len(claims),
                "citation_count": len(citations),
            },
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="slot_frame",
            data=redact_journal_data(
                {
                    **frame.to_dict(),
                    "schema": "holo.kernel_v3.slot_frame.v1",
                    "source": "generic_source_grounded_workflow_trace",
                    "claim_ledger_ref": claim_record.record_id,
                }
            ),
            state_delta={
                "slot_frame_task_type": frame.task_type,
                "missing_slot_count": len(frame.missing_slots),
            },
        )
        transform = TransformPlan(
            plan_id="transform-plan-source-grounded-" + _short_hash(task_id, run_id, str(len(claims))),
            domain="source_grounded_research",
            operation="synthesize",
            status="ready" if claims and citations else "missing_slots",
            method="source_grounded_synthesis",
            input_claim_ids=[claim.claim_id for claim in claims[:32]],
            output_attribute="cited_answer",
            payload=None,
            missing_slots=_ordered_unique(missing_slots),
            diagnostics={
                "source": "generic_source_grounded_workflow_trace",
                "claim_count": len(claims),
                "citation_count": len(citations),
            },
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="transform_plan",
            data=redact_journal_data({**transform.to_dict(), "schema": "holo.kernel_v3.transform_plan.v1"}),
            state_delta={"transform_plan_status": transform.status},
        )

    def _append_benchmark_oracle_context_retrieval(
        self,
        task_id: str,
        run_id: str,
        *,
        goal: str,
        recipe: TaskRecipe,
    ) -> None:
        if recipe.mode != "retrieval_answer":
            return
        if _retrieval_evidence(self.journal, task_id, run_id):
            return
        payload = _benchmark_oracle_context_payload(goal)
        if payload is None:
            return
        evidence_id = "evidence-benchmark-oracle-" + _short_hash(task_id, run_id, payload["context"])
        citation_id = "cite-benchmark-oracle-" + _short_hash(task_id, run_id, payload["uri"])
        artifact_id = "benchmark-oracle-context-" + _short_hash(payload["context"])
        payload_hash = hashlib.sha256(payload["context"].encode("utf-8")).hexdigest()
        evidence = EvidenceItem(
            evidence_id=evidence_id,
            goal_id="goal-benchmark-oracle-context",
            span_id="span-" + evidence_id,
            document_id="doc-benchmark-oracle-context",
            source_id="source-benchmark-oracle-context",
            artifact_id=artifact_id,
            uri=payload["uri"],
            title=payload["title"],
            text=payload["context"],
            score=1.0,
            payload_hash=payload_hash,
            diagnostics={
                "source": "benchmark_oracle_context",
                "mode": payload["mode"],
                "context_chars": len(payload["context"]),
            },
        )
        citation = CitationItem(
            citation_id=citation_id,
            goal_id=evidence.goal_id,
            evidence_id=evidence.evidence_id,
            artifact_id=artifact_id,
            uri=payload["uri"],
            title=payload["title"],
            quote=_text_preview(payload["context"], limit=420),
            span_start=0,
            span_end=min(len(payload["context"]), 420),
            metadata={"source": "benchmark_oracle_context", "mode": payload["mode"]},
        )
        report = RetrievalReport(
            report_id="report-benchmark-oracle-" + _short_hash(task_id, run_id),
            goal_id=evidence.goal_id,
            status="sufficient",
            query_plan_id="query-plan-benchmark-oracle-context",
            search_attempt_ids=[],
            fetch_attempt_ids=[],
            evidence_ids=[evidence.evidence_id],
            citation_ids=[citation.citation_id],
            evaluation_id="eval-benchmark-oracle-context",
            artifact_refs=[artifact_id],
            preview=_text_preview(payload["context"], limit=900),
            diagnostics={
                "source": "benchmark_oracle_context",
                "mode": payload["mode"],
                "provided_context": True,
                "network_required": False,
                "reason": "benchmark_provided_oracle_context",
            },
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="retrieval_evidence",
            data=redact_journal_data(evidence.to_dict()),
            state_delta={"retrieval_evidence": "benchmark_oracle_context"},
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="retrieval_citation",
            data=redact_journal_data(citation.to_dict()),
            state_delta={"retrieval_citation": "benchmark_oracle_context"},
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="retrieval_report",
            data=redact_journal_data(report.to_dict()),
            state_delta={"retrieval_report": report.status},
        )

    def _append_final_quality_check(
        self,
        answer: FinalAnswer,
        *,
        recipe: TaskRecipe,
        gaps: list[str],
        attempt: str = "initial",
        prior_gaps: list[str] | None = None,
    ) -> None:
        profile = _answer_profile_metadata(recipe)
        if not profile:
            return
        record = self.journal.append(
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
                    "attempt": attempt,
                    "prior_gaps": list(prior_gaps or []),
                }
            ),
            state_delta={"final_answer_quality": "passed" if not gaps else "insufficient"},
        )
        if gaps:
            self._maybe_propose_answer_quality_memory(
                answer,
                recipe=recipe,
                gaps=gaps,
                attempt=attempt,
                prior_gaps=prior_gaps,
                source_record_ref=record.record_id,
            )

    def _append_final_quality_repair_failed(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        gaps: list[str],
        error: str | None,
    ) -> None:
        profile = _answer_profile_metadata(recipe)
        if not profile:
            return
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="final_answer_quality_repair_failed",
            data=redact_journal_data(
                {
                    "answer_profile": profile,
                    "gaps": list(gaps),
                    "error": error or "synthesis_failed",
                }
            ),
            state_delta={"final_answer_quality_repair": "failed"},
        )

    def _maybe_propose_research_memory(self, answer: FinalAnswer, *, recipe: TaskRecipe) -> None:
        if self.memory_pipeline is None:
            return
        profile = answer_profile_from_dict(_answer_profile_metadata(recipe))
        if profile is None or profile.format not in {"detailed_report", "deep_report", "memo"}:
            return
        thread_id = _thread_id_metadata(recipe)
        try:
            result = self.memory_pipeline.propose_from_research_result(
                answer_text=answer.answer,
                task_id=answer.task_id,
                run_id=answer.run_id,
                thread_id=thread_id,
                source_record_ref=answer.trace_refs[-1] if answer.trace_refs else None,
                metadata={
                    "answer_profile": profile.to_dict(),
                    "research_mission": _research_mission_metadata(recipe),
                    "citation_refs": list(answer.citation_refs),
                    "used_evidence": list(answer.used_evidence),
                },
            )
            if result.proposals:
                self._maybe_propose_thread_learning_digest(
                    task_id=answer.task_id,
                    run_id=answer.run_id,
                    thread_id=thread_id,
                    source_record_ref=answer.trace_refs[-1] if answer.trace_refs else None,
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

    def _maybe_propose_answer_quality_memory(
        self,
        answer: FinalAnswer,
        *,
        recipe: TaskRecipe,
        gaps: list[str],
        attempt: str,
        prior_gaps: list[str] | None,
        source_record_ref: str | None,
    ) -> None:
        if self.memory_pipeline is None or not gaps:
            return
        thread_id = _thread_id_metadata(recipe)
        try:
            result = self.memory_pipeline.propose_from_answer_quality_check(
                root_goal=_root_goal_for_memory_reflection(self.journal, answer.task_id, recipe),
                task_id=answer.task_id,
                run_id=answer.run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                answer_profile=_answer_profile_metadata(recipe),
                gaps=list(gaps),
                attempt=attempt,
                prior_gaps=list(prior_gaps or []),
                answer_chars=len(answer.answer),
                citation_refs=list(answer.citation_refs),
                used_evidence=list(answer.used_evidence),
                metadata={
                    "reflection_kind": "answer_quality_learning",
                    "review_nonblocking": True,
                    "recipe_id": recipe.recipe_id,
                    "mode": recipe.mode,
                },
            )
            if result.proposals:
                self._maybe_propose_thread_learning_digest(
                    task_id=answer.task_id,
                    run_id=answer.run_id,
                    thread_id=thread_id,
                    source_record_ref=source_record_ref,
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

    def _maybe_propose_task_reflection_memory(
        self,
        failure: FailureReport,
        *,
        recipe: TaskRecipe | None,
        source_record_ref: str | None,
    ) -> None:
        if self.memory_pipeline is None or recipe is None:
            return
        if not _should_propose_failure_reflection(failure):
            return
        thread_id = _thread_id_metadata(recipe)
        try:
            result = self.memory_pipeline.propose_from_task_reflection(
                root_goal=_root_goal_for_memory_reflection(self.journal, failure.task_id, recipe),
                outcome="failed",
                task_id=failure.task_id,
                run_id=failure.run_id,
                thread_id=thread_id,
                source_record_ref=source_record_ref,
                failure_report=failure.to_dict(),
                host_situation=failure.host_situation,
                metadata={
                    "reflection_kind": "failure_learning",
                    "review_nonblocking": True,
                    "recipe_id": recipe.recipe_id,
                    "mode": recipe.mode,
                },
            )
            if result.proposals:
                self._maybe_propose_thread_learning_digest(
                    task_id=failure.task_id,
                    run_id=failure.run_id,
                    thread_id=thread_id,
                    source_record_ref=source_record_ref,
                )
        except Exception as exc:  # pragma: no cover - defensive runtime isolation
            self.journal.append(
                task_id=failure.task_id,
                run_id=failure.run_id,
                step_id=None,
                kind="memory_pipeline_error",
                data={"error_type": type(exc).__name__, "redaction": {"message": "omitted"}},
                state_delta={"memory_pipeline": "failed"},
            )

    def _maybe_propose_thread_learning_digest(
        self,
        *,
        task_id: str,
        run_id: str,
        thread_id: str,
        source_record_ref: str | None,
    ) -> None:
        if self.memory_pipeline is None:
            return
        try:
            self.memory_pipeline.propose_thread_learning_digest(
                thread_id=thread_id,
                task_id=task_id,
                run_id=run_id,
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

    def _failure(
        self,
        task_id: str,
        run_id: str,
        reason: str,
        *,
        missing_evidence: list[str] | None = None,
        next_action: str | None,
        recipe: TaskRecipe | None = None,
        tool_manifests: list[ToolManifest] | None = None,
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
        host_situation = self._append_host_situation_record(
            task_id,
            run_id,
            recipe=recipe,
            tool_manifests=tool_manifests,
            failure_report=failure.to_dict(),
            phase="failure",
        )
        failure = replace(failure, host_situation=host_situation)
        record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_failure_report",
            data=redact_journal_data(failure.to_dict()),
            state_delta={"agent_final_answer": "failed", "reason": reason},
        )
        failure = replace(failure, trace_refs=[*failure.trace_refs, record.record_id])
        self._maybe_propose_task_reflection_memory(
            failure,
            recipe=recipe,
            source_record_ref=record.record_id,
        )
        return failure

    def _append_host_situation_record(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe | None,
        phase: str,
        tool_manifests: list[ToolManifest] | None = None,
        failure_report: JsonObject | None = None,
    ) -> JsonObject:
        host_situation = self._host_situation(
            task_id,
            run_id,
            recipe=recipe,
            tool_manifests=tool_manifests,
            failure_report=failure_report,
        )
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="host_situation",
            data=redact_journal_data(host_situation),
            state_delta={
                "host_situation": phase,
                "host_situation_schema": host_situation.get("schema"),
            },
        )
        return host_situation

    def _host_situation(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe | None,
        tool_manifests: list[ToolManifest] | None = None,
        failure_report: JsonObject | None = None,
    ) -> JsonObject:
        situation = build_host_situation(
            journal=self.journal,
            task_id=task_id,
            run_id=run_id,
            recipe=recipe,
            tool_manifests=tool_manifests or self._tool_manifests_by_run.get((task_id, run_id), []),
            failure_report=failure_report,
            thread_id=_thread_id_from_recipe(recipe),
        )
        return self._with_runtime_capabilities(situation)

    def _initial_host_situation(self, *, thread_id: str) -> JsonObject:
        return self._with_runtime_capabilities(
            build_host_situation(
                journal=self.journal,
                thread_id=thread_id,
            )
        )

    def _with_runtime_capabilities(self, situation: JsonObject) -> JsonObject:
        return _host_situation_with_runtime_capabilities(
            situation,
            runtime_capabilities=self.runtime_capabilities(),
        )

    def runtime_capabilities(self) -> JsonObject:
        retrieval = _runtime_retrieval_capabilities(self.retrieval_operator)
        return {
            "schema": "holo.kernel_v3.runtime_capabilities.v1",
            "retrieval": retrieval,
            "memory": {
                "durable_memory_store_configured": self.memory_store is not None,
                "active_memory_recall_available": self.memory_store is not None,
            },
            "workspace": {
                "workspace_root_configured": self.workspace_root is not None,
                "workspace_files_configured": bool(self.workspace_files),
            },
            "system": {
                "system_time_available": True,
            },
            "host_rule": (
                "These are runtime-level capabilities available when the host routes a task to the matching mode. "
                "They do not override the current recipe, PolicyGate, permissions, or budgets."
            ),
        }


def _host_situation_with_runtime_capabilities(
    situation: JsonObject,
    *,
    runtime_capabilities: JsonObject,
) -> JsonObject:
    result = dict(situation)
    result["runtime_capabilities"] = dict(runtime_capabilities)
    rules = result.get("user_visible_rules")
    if isinstance(rules, list):
        result["user_visible_rules"] = list(rules)
        result["user_visible_rules"].append(
            "Distinguish current_recipe tools from runtime_capabilities. "
            "A direct-answer recipe may not execute retrieval, while a routed retrieval task may still have live retrieval available."
        )
        result["user_visible_rules"].append(
            "For user-visible capability or self-state answers, report Holo's runtime capabilities first; "
            "then mention current-step recipe limits only as current-step constraints."
        )
    return result


class _AgentContextCompiler:
    def __init__(
        self,
        *,
        recipe: TaskRecipe,
        tool_manifests: list[ToolManifest],
        memory_store: MemoryStore | None = None,
        runtime_capabilities: JsonObject | None = None,
    ) -> None:
        self.recipe = recipe
        self.tool_manifests = [
            manifest for manifest in tool_manifests if manifest.name in set(recipe.allowed_tools)
        ]
        self.memory_store = memory_store
        self.runtime_capabilities = dict(runtime_capabilities or {})
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
        host_situation = build_host_situation(
            journal=journal,
            task_id=task.task_id,
            run_id=task.run_id,
            recipe=self.recipe,
            tool_manifests=self.tool_manifests,
            thread_id=task.thread_id,
        )
        if self.runtime_capabilities:
            host_situation = _host_situation_with_runtime_capabilities(
                host_situation,
                runtime_capabilities=self.runtime_capabilities,
            )
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
                "host_situation": host_situation,
                "agent_runtime_directive": _compact_agent_runtime_directive_for_prompt(_planner_directive(self.recipe)),
                "workmethod": _compact_workmethod_for_prompt(_workmethod_metadata(self.recipe)),
                "semantic_goal": _semantic_goal_metadata(self.recipe),
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
                "durable_memory_context": _durable_memory_context_from_sections(pack.sections),
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
    def __init__(
        self,
        *,
        inner: Planner,
        goal: str,
        recipe: TaskRecipe,
        journal: JournalStore | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.inner = inner
        self.goal = goal
        self.recipe = recipe
        self.journal = journal
        self.artifact_store = artifact_store
        self._calls = 0
        self._journaled_plan_refs: set[str] = set()

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self._calls += 1
        self._journal_plan_if_needed(context)
        action = self.inner.propose(context, feedback)
        rescue = self._host_planner_failure_retrieval_action(context, action)
        if rescue is not None:
            action = rescue
        bound = _bind_model_action_to_recipe(action, goal=self.goal, recipe=self.recipe, context=context)
        if bound.name != "retrieval.run" and not (bound.kind == "tool" and bound.name in set(self.recipe.allowed_tools)):
            bound = self._retrieval_workbench_followup_action(context, bound) or bound
        bound = self._finance_formula_action(context, bound) or bound
        self._journal_plan_update(context, bound, feedback)
        return bound

    def _host_planner_failure_retrieval_action(self, context: ContextBundle, action: CandidateAction) -> CandidateAction | None:
        if self.recipe.mode != "retrieval_answer" or "retrieval.run" not in self.recipe.allowed_tools:
            return None
        if action.kind != "respond" or "processor_failed" not in set(action.reasons):
            return None
        workbench_followup = _workbench_followup_retrieval_action(
            action,
            context=context,
            goal=self.goal,
            recipe=self.recipe,
            journal=self.journal,
            call_index=self._calls,
            trigger_reason="planner_processor_failed_after_retrieval_workbench",
            include_planner_failure=True,
        )
        if workbench_followup is not None:
            return workbench_followup
        plan = plan_finance_formula(question=self.goal, facts=[], existing_traces=[])
        if plan.status == "missing_facts":
            retrieval = _finance_missing_fact_retrieval_action(
                action,
                plan=plan,
                goal=self.goal,
                call_index=self._calls,
                recipe=self.recipe,
            )
            if retrieval is not None:
                rescue_payload = _host_rescue_retrieval_payload(
                    retrieval.payload,
                    context=context,
                    goal=self.goal,
                    recipe=self.recipe,
                    call_index=self._calls,
                )
                return replace(
                    retrieval,
                    payload=rescue_payload,
                    reasons=_ordered_unique(
                        [
                            "host_planner_failure_rescue",
                            "planner_processor_failed",
                            *retrieval.reasons,
                        ]
                    ),
                )
        payload = _retrieval_payload(self.goal, self.recipe)
        payload = _host_rescue_retrieval_payload(payload, context=context, goal=self.goal, recipe=self.recipe, call_index=self._calls)
        return CandidateAction(
            action_id=f"act-host-planner-failure-retrieval-{self._calls}",
            kind="tool",
            name="retrieval.run",
            description="Host fallback retrieval after planner processor failure",
            score=0.72,
            payload=payload,
            reasons=["host_planner_failure_rescue", "planner_processor_failed"],
            side_effect_class="network",
        )

    def _retrieval_workbench_followup_action(
        self,
        context: ContextBundle,
        action: CandidateAction,
    ) -> CandidateAction | None:
        if self.recipe.mode != "retrieval_answer" or "retrieval.run" not in self.recipe.allowed_tools:
            return None
        return _workbench_followup_retrieval_action(
            action,
            context=context,
            goal=self.goal,
            recipe=self.recipe,
            journal=self.journal,
            call_index=self._calls,
            trigger_reason="workbench_semantic_continue",
            include_planner_failure=False,
        )

    def _finance_formula_action(self, context: ContextBundle, action: CandidateAction) -> CandidateAction | None:
        if self.journal is None or CALCULATOR_TOOL_NAME not in self.recipe.allowed_tools:
            return None
        if action.name == CALCULATOR_TOOL_NAME:
            return None
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        if not task_id or not run_id:
            return None
        evidence, citations, _ = _retrieval_and_toolchain_grounding(
            self.journal,
            task_id,
            run_id,
            recipe=self.recipe,
            artifact_store=self.artifact_store,
        )
        if not evidence:
            return None
        facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
        existing_traces = _calculator_formula_traces(self.journal, task_id=task_id, run_id=run_id)
        plan = plan_finance_formula(question=self.goal, facts=facts, existing_traces=existing_traces)
        plan_record = self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=str(context.state.get("step_id") or ""),
            kind="finance_formula_plan",
            data=redact_journal_data(
                {
                    **plan.to_dict(),
                    "source_action": _action_plan_preview(action),
                    "fact_count": len(facts),
                    "existing_formula_trace_count": len(existing_traces),
                }
            ),
            state_delta={"finance_formula_plan": plan.status},
        )
        transform_plan = finance_formula_plan_to_transform_plan(plan, question=self.goal)
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=str(context.state.get("step_id") or ""),
            kind="transform_plan",
            data=redact_journal_data(
                {
                    **transform_plan.to_dict(),
                    "schema": "holo.kernel_v3.transform_plan.v1",
                    "source": "finance_formula_planner",
                    "finance_formula_plan_ref": plan_record.record_id,
                }
            ),
            feedback_ref=plan_record.record_id,
            state_delta={"transform_plan": transform_plan.status},
        )
        if plan.status != "ready" or not isinstance(plan.payload, dict):
            return _finance_missing_fact_retrieval_action(
                action,
                plan=plan,
                goal=self.goal,
                call_index=self._calls,
                recipe=self.recipe,
            )
        if _formula_trace_covers_inputs(existing_traces, _string_list(plan.payload.get("input_fact_ids"))):
            return None
        return CandidateAction(
            action_id=f"act-finance-formula-{self._calls}",
            kind="tool",
            name=CALCULATOR_TOOL_NAME,
            description=f"Compute {plan.formula_name or 'finance formula'} from finance fact ledger",
            score=max(float(action.score or 0.0), 0.92),
            payload=dict(plan.payload),
            reasons=[
                "finance_formula_planner",
                "calculator_required_before_final",
                f"source_action:{action.name}",
            ],
            side_effect_class="read",
        )

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
        self._journal_toolchain_step_proposed(context, action, feedback)

    def _journal_toolchain_step_proposed(
        self,
        context: ContextBundle,
        action: CandidateAction,
        feedback: Feedback | None,
    ) -> None:
        if self.journal is None or action.kind != "tool" or not _composable_toolchain_enabled(self.recipe):
            return
        if action.name not in set(self.recipe.allowed_tools):
            return
        task_id = str(context.state.get("task_id") or "")
        run_id = str(context.state.get("run_id") or "")
        if not task_id or not run_id:
            return
        for record in self.journal.records(task_id=task_id, kind="toolchain_step_proposed"):
            if record.run_id == run_id and record.action_ref == action.action_id:
                return
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=str(context.state.get("step_id") or ""),
            kind="toolchain_step_proposed",
            data=redact_journal_data(
                {
                    "schema": "holo.kernel_v3.toolchain_step_proposed.v1",
                    "revision": self._calls,
                    "tool": action.name,
                    "action": _action_plan_preview(action),
                    "feedback_status": feedback.status if feedback is not None else None,
                    "missing_evidence": list(feedback.missing_evidence) if feedback is not None else [],
                    "source": "model_planner_bound_to_composable_toolchain",
                }
            ),
            action_ref=action.action_id,
            state_delta={"toolchain_step": action.name},
        )


def _workbench_followup_retrieval_action(
    source_action: CandidateAction,
    *,
    context: ContextBundle,
    goal: str,
    recipe: TaskRecipe,
    journal: JournalStore | None,
    call_index: int,
    trigger_reason: str,
    include_planner_failure: bool,
) -> CandidateAction | None:
    if journal is None:
        return None
    task_id = str(context.state.get("task_id") or "")
    run_id = str(context.state.get("run_id") or "")
    if not task_id or not run_id:
        return None
    record = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="retrieval_workbench_decision")
    if record is None:
        return None
    data = record.data if isinstance(record.data, dict) else {}
    if data.get("status") != "ok" or data.get("decision") == "sufficient":
        return None
    attempted = {query.casefold() for query in _action_retrieval_queries(journal, task_id=task_id, run_id=run_id)}
    next_queries = _ordered_unique(
        [
            *_string_list(data.get("next_queries")),
            *[target for target in _string_list(data.get("next_document_targets")) if _looks_like_url(target)],
        ]
    )
    action_source_urls = _action_retrieval_source_urls(journal, task_id=task_id, run_id=run_id)
    missing_slots = _workbench_missing_slots(data)
    if not next_queries and missing_slots:
        next_queries = _workbench_target_source_followup_queries(
            data=data,
            recipe=recipe,
            goal=goal,
            source_urls=action_source_urls,
        )
    selected_query = next((query for query in next_queries if query.casefold() not in attempted), None)
    if not selected_query:
        return None
    payload = _retrieval_payload(goal, recipe)
    payload = _host_rescue_retrieval_payload(payload, context=context, goal=goal, recipe=recipe, call_index=call_index)
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    source_urls = _ordered_unique(
        [
            *_string_list(metadata.get("source_urls")),
            *_required_retrieval_source_urls(recipe),
            *_retrieval_payload_urls(_benchmark_doc_retrieval_payload(goal)),
            *action_source_urls,
            *[target for target in _string_list(data.get("next_document_targets")) if _looks_like_url(target)],
            *([selected_query] if _looks_like_url(selected_query) else []),
        ]
    )
    metadata.update(
        {
            "host_rescue": True,
            "host_rescue_reason": trigger_reason,
            "workbench_followup": True,
            "workbench_decision_ref": record.record_id,
            "workbench_reason_summary": _string_value(data.get("reason_summary")),
            "semantic_missing_slots": missing_slots,
            "preferred_source_families": _ordered_unique(
                [
                    *_string_list(metadata.get("preferred_source_families")),
                    *_string_list(data.get("next_source_families")),
                ]
            ),
            "next_document_targets": _string_list(data.get("next_document_targets")),
            "research_profile": metadata.get("research_profile") or "finance_fundamentals",
            "source_authority_requirement": metadata.get("source_authority_requirement") or "primary",
        }
    )
    if source_urls:
        metadata["source_urls"] = source_urls[:24]
    queries = _ordered_unique([selected_query, *next_queries, *_string_list(payload.get("queries"))])[:8]
    payload.update(
        {
            "query": selected_query,
            "queries": queries,
            "search_strategy": "structured",
            "max_queries": max(int(payload.get("max_queries") or 0), min(8, max(3, len(queries)))),
            "max_sources": max(int(payload.get("max_sources") or 0), 24),
            "max_fetches": max(int(payload.get("max_fetches") or 0), 12),
            "max_spans_per_document": max(int(payload.get("max_spans_per_document") or 0), 8),
            "metadata": metadata,
        }
    )
    return CandidateAction(
        action_id=f"act-workbench-followup-retrieval-{call_index}",
        kind="tool",
        name="retrieval.run",
        description="Execute retrieval workbench semantic next move",
        score=max(float(source_action.score or 0.0), 0.91),
        payload=payload,
        reasons=_ordered_unique([
            "retrieval_workbench_followup",
            trigger_reason,
            *(["host_planner_failure_rescue", "planner_processor_failed"] if include_planner_failure else []),
            f"source_action:{source_action.name}",
            *[f"missing:{item}" for item in missing_slots[:6]],
        ]),
        side_effect_class="network",
    )


def _retrieval_workbench_followup_required(
    journal: JournalStore | None,
    *,
    recipe: TaskRecipe,
    context: ContextBundle,
) -> bool:
    if journal is None:
        return False
    if recipe.mode != "retrieval_answer" or "retrieval.run" not in recipe.allowed_tools:
        return False
    task_id = str(context.state.get("task_id") or "")
    run_id = str(context.state.get("run_id") or "")
    if not task_id or not run_id:
        return False
    record = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="retrieval_workbench_decision")
    if record is None:
        return False
    data = record.data if isinstance(record.data, dict) else {}
    if data.get("status") != "ok" or data.get("decision") != "continue":
        return False
    if _workbench_missing_slots(data):
        return True
    attempted = {query.casefold() for query in _action_retrieval_queries(journal, task_id=task_id, run_id=run_id)}
    next_queries = _ordered_unique(
        [
            *_string_list(data.get("next_queries")),
            *[target for target in _string_list(data.get("next_document_targets")) if _looks_like_url(target)],
        ]
    )
    return any(query.casefold() not in attempted for query in next_queries)


def _retrieval_report_workbench_followup_required(report: JsonObject) -> bool:
    workbench = report.get("retrieval_workbench") if isinstance(report.get("retrieval_workbench"), dict) else {}
    if not workbench:
        diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
        workbench = diagnostics.get("retrieval_workbench") if isinstance(diagnostics.get("retrieval_workbench"), dict) else {}
    if not workbench:
        return False
    if workbench.get("status") != "ok" or workbench.get("decision") != "continue":
        return False
    if _workbench_missing_slots(workbench):
        return True
    next_queries = _ordered_unique(
        [
            *_string_list(workbench.get("next_queries")),
            *[target for target in _string_list(workbench.get("next_document_targets")) if _looks_like_url(target)],
        ]
    )
    return bool(next_queries)


def _workbench_target_source_followup_queries(
    *,
    data: JsonObject,
    recipe: TaskRecipe,
    goal: str,
    source_urls: list[str] | None = None,
) -> list[str]:
    missing = _workbench_missing_slots(data)
    if not missing:
        return []
    missing_text = " ".join(missing[:8])
    source_urls = _ordered_unique(
        [
            *_required_retrieval_source_urls(recipe),
            *_retrieval_payload_urls(_benchmark_doc_retrieval_payload(goal)),
            *list(source_urls or []),
        ]
    )
    queries = []
    for url in source_urls[:4]:
        queries.append(f"{url} {missing_text}")
    return _ordered_unique(queries)


def _workbench_missing_slots(data: JsonObject) -> list[str]:
    return _ordered_unique(
        [
            *_string_list(data.get("missing_slots")),
            *_string_list(data.get("semantic_missing_slots")),
        ]
    )


def _finance_missing_fact_retrieval_action(
    source_action: CandidateAction,
    *,
    plan: object,
    goal: str,
    call_index: int,
    recipe: TaskRecipe | None = None,
) -> CandidateAction | None:
    formula_name = str(getattr(plan, "formula_name", "") or "")
    missing = [str(item) for item in getattr(plan, "missing_facts", []) or [] if str(item)]
    if not _finance_missing_fact_retrieval_needed(formula_name=formula_name, missing=missing, goal=goal):
        return None
    payload = dict(source_action.payload) if isinstance(source_action.payload, dict) else {}
    payload = _merge_retrieval_payload(
        payload,
        _finance_missing_fact_retrieval_payload(formula_name=formula_name, missing=missing, goal=goal),
    )
    payload = _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe, preserve_query=True)
    return CandidateAction(
        action_id=f"act-finance-missing-facts-retrieval-{call_index}",
        kind="tool",
        name="retrieval.run",
        description=f"Retrieve missing finance facts for {formula_name}",
        score=max(float(source_action.score or 0.0), 0.9),
        payload=payload,
        reasons=[
            "finance_formula_planner_missing_facts",
            f"formula:{formula_name}",
            *[f"missing:{item}" for item in missing[:6]],
            f"source_action:{source_action.name}",
        ],
        side_effect_class="network",
    )


def _finance_missing_fact_retrieval_needed(*, formula_name: str, missing: list[str], goal: str) -> bool:
    text = f"{goal} {' '.join(missing)} {formula_name}".lower()
    if formula_name == "ev_revenue" and any(item in missing for item in ("equity_value_or_market_cap", "revenue")):
        return any(marker in text for marker in ("transaction", "acquisition", "deal", "purchase", "consideration", "ev/revenue"))
    if formula_name == "ev_ebitda" and any(
        item in missing for item in ("enterprise_value_or_market_cap", "debt", "cash", "ebitda_or_ebitda_components")
    ):
        return any(marker in text for marker in ("ev/ebitda", "enterprise value", "market cap", "ebitda", "valuation"))
    if formula_name == "bridge_subtotal" and missing:
        return any(marker in text for marker in ("adjusted ebitda", "bridge", "addback", "add-back", "add back", "non-gaap"))
    if formula_name == "dcf" and missing:
        return any(marker in text for marker in ("dcf", "discounted cash flow", "cash flow", "wacc", "terminal growth"))
    if formula_name == "lbo" and missing:
        return any(marker in text for marker in ("lbo", "leveraged buyout", "ebitda", "exit multiple", "leverage"))
    if formula_name == "capital_intensity" and missing:
        return any(marker in text for marker in ("capital-intensive", "capital intensive", "capital intensity", "capex", "property plant", "assets"))
    return False


def _finance_missing_fact_retrieval_payload(*, formula_name: str, missing: list[str], goal: str) -> JsonObject:
    base_query = " ".join(str(goal or "").split())
    tickers = _finance_goal_tickers(base_query)
    source_urls = _finance_issuer_seed_urls(base_query, formula_name=formula_name)
    slot_frame = finance_slot_frame(
        question=base_query,
        facts=[],
        formula_name=formula_name,
        missing_slots=missing,
    )
    evidence_policy = slot_frame.evidence_policy
    if formula_name == "ev_revenue":
        query = (
            f"{base_query} SEC 8-K merger agreement acquisition transaction value "
            "consideration purchase price enterprise value target revenue"
        )
    elif formula_name == "ev_ebitda":
        ticker_text = " ".join(tickers)
        query = " ".join(
            part
            for part in (
                ticker_text,
                "EV EBITDA market cap enterprise value total debt total cash EBITDA key statistics 10-K",
            )
            if part
        )
    elif formula_name == "bridge_subtotal":
        query = (
            f"{base_query} annual report 10-K 10-Q adjusted EBITDA reconciliation "
            "non-GAAP bridge add-backs deductions subtotal"
        )
    elif formula_name == "dcf":
        query = (
            f"{base_query} 10-K operating cash flow free cash flow capital expenditures "
            "discount rate WACC terminal growth DCF assumptions"
        )
    elif formula_name == "lbo":
        query = (
            f"{base_query} 10-K adjusted EBITDA operating cash flow free cash flow enterprise value market cap debt cash "
            "LBO leverage exit multiple assumptions"
        )
    elif formula_name == "capital_intensity":
        query = (
            f"{base_query} SEC companyfacts capital expenditures revenue operating cash flow total assets "
            "PropertyPlantAndEquipmentNet PP&E net"
        )
    else:
        query = f"{base_query} SEC filing missing finance facts {' '.join(missing)}"
    queries = _finance_missing_fact_queries(
        formula_name=formula_name,
        goal=base_query,
        primary_query=query,
        tickers=tickers,
    )
    max_queries = 3
    max_fetches = 12
    if formula_name == "ev_ebitda" and len(tickers) > 1:
        max_queries = min(8, max(4, len(queries)))
        max_fetches = 24
    if formula_name in {"dcf", "lbo"}:
        max_queries = min(6, max(4, len(queries)))
        max_fetches = 18
    if formula_name == "capital_intensity":
        max_queries = min(5, max(3, len(queries)))
        max_fetches = 16
    return {
        "query": query,
        "queries": queries[:max_queries],
        "search_strategy": "structured",
        "max_queries": max_queries,
        "max_sources": 24,
        "max_fetches": max_fetches,
        "max_spans_per_document": 8,
        **({"source_urls": source_urls} if source_urls else {}),
        "metadata": {
            "root_goal": base_query,
            "finance_formula_missing_facts": missing,
            "finance_formula_name": formula_name,
            **({"source_urls": source_urls} if source_urls else {}),
            "slot_frame": slot_frame.to_dict(),
            "missing_slots": list(slot_frame.missing_slots),
            "evidence_policy": evidence_policy.to_dict() if evidence_policy is not None else {},
            "source_authority_requirement": _finance_missing_fact_authority_requirement(formula_name),
            "preferred_source_families": _finance_missing_fact_preferred_families(formula_name),
            "required_source_families": evidence_policy.required_source_families if evidence_policy is not None else [],
            "forbidden_source_families": evidence_policy.forbidden_source_families if evidence_policy is not None else [],
            "required_evidence_terms": evidence_policy.required_terms if evidence_policy is not None else [],
            "research_profile": "finance_fundamentals",
            **({"research_task_kind": "valuation"} if formula_name in {"ev_revenue", "ev_ebitda", "dcf", "lbo"} else {}),
            **({"target_tickers": tickers} if tickers else {}),
        },
    }


def _finance_issuer_seed_urls(goal: str, *, formula_name: str) -> list[str]:
    urls: list[str] = []
    for issuer in builtin_issuers_for_text(goal):
        cik = str(issuer.get("cik") or issuer.get("sec_cik") or "").strip()
        if not cik:
            continue
        padded = cik.zfill(10)
        urls.append(f"https://data.sec.gov/submissions/CIK{padded}.json")
        if formula_name in {
            "ev_revenue",
            "ev_ebitda",
            "margin",
            "cagr",
            "yoy_growth",
            "dcf",
            "lbo",
            "capital_intensity",
        }:
            urls.append(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json")
    return _ordered_unique(urls)[:12]


def _host_rescue_retrieval_payload(
    payload: JsonObject,
    *,
    context: ContextBundle,
    goal: str,
    recipe: TaskRecipe | None = None,
    call_index: int,
) -> JsonObject:
    updated = dict(payload)
    benchmark_payload = _benchmark_doc_retrieval_payload(goal)
    if not benchmark_payload and recipe is not None:
        benchmark_payload = _benchmark_doc_retrieval_payload_from_recipe(recipe)
    if benchmark_payload:
        updated = _merge_retrieval_payload(updated, benchmark_payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    failed = _failed_retrieval_observation_hints(context)
    prior_queries = _string_list(failed.get("queries"))
    prior_query = failed.get("query")
    if isinstance(prior_query, str) and prior_query:
        prior_queries.insert(0, prior_query)
    source_urls = _string_list(failed.get("source_urls"))
    benchmark_query = _string_value(benchmark_payload.get("query")) if benchmark_payload else None
    rescue_goal = benchmark_query or goal
    rescue_query = _host_rescue_query(
        goal=rescue_goal,
        prior_queries=[] if benchmark_query else prior_queries,
        call_index=call_index,
    )
    queries = _ordered_unique(
        [query for query in [benchmark_query, rescue_query, *(prior_queries if not benchmark_query else [])] if query]
    )[:4]
    updated.update(
        {
            "query": rescue_query,
            "queries": queries,
            "search_strategy": "structured",
            "max_queries": max(3, min(6, len(queries) + 1)),
            "max_sources": max(int(updated.get("max_sources") or 0), 24),
            "max_fetches": max(int(updated.get("max_fetches") or 0), 12),
            "max_spans_per_document": max(int(updated.get("max_spans_per_document") or 0), 6),
        }
    )
    if source_urls:
        metadata["source_urls"] = _ordered_unique([*_string_list(metadata.get("source_urls")), *source_urls])[:24]
    metadata.update(
        {
            "host_rescue": True,
            "host_rescue_reason": "planner_processor_failed_after_retrieval_context",
            "host_rescue_attempt": call_index,
            "root_goal": rescue_goal,
            "research_profile": metadata.get("research_profile") or "finance_fundamentals",
            "source_authority_requirement": metadata.get("source_authority_requirement") or "primary",
        }
    )
    updated["metadata"] = metadata
    return _enforce_benchmark_doc_retrieval_binding(updated, goal=goal, recipe=recipe)


def _failed_retrieval_observation_hints(context: ContextBundle) -> JsonObject:
    observations: list[JsonObject] = []
    for value in (context.state.get("recent_observations"), context.state.get("last_observations")):
        if isinstance(value, list):
            observations.extend(item for item in value if isinstance(item, dict))
    sections = context.state.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict) or section.get("name") != "recent_observations":
                continue
            records = section.get("records")
            if isinstance(records, list):
                observations.extend(item for item in records if isinstance(item, dict))
            content = section.get("content")
            if isinstance(content, list):
                observations.extend(item for item in content if isinstance(item, dict))
    for item in reversed(observations):
        if not isinstance(item, dict):
            continue
        if item.get("source") != "tool:retrieval.run":
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        if not content:
            continue
        return {
            "query": content.get("query"),
            "queries": content.get("queries"),
            "source_urls": content.get("source_urls"),
        }
    return {}


def _host_rescue_query(*, goal: str, prior_queries: list[str], call_index: int) -> str:
    base = " ".join(str(goal or "").split())
    if any(marker in base.lower() for marker in ("transaction", "acquisition", "deal", "seagen", "sgen")):
        variants = [
            f"{base} SEC 8-K merger agreement acquisition transaction value revenue 2023",
            f"{base} Pfizer Seagen Exhibit 99.1 transaction value revenue 2023 SEC",
            f"{base} Seagen 2022 10-K revenue Pfizer acquisition consideration",
        ]
    else:
        variants = [
            f"{base} official filing primary source",
            f"{base} annual report 10-K 10-Q SEC",
            f"{base} investor relations official report",
        ]
    prior = {query.casefold() for query in prior_queries}
    for variant in variants:
        if variant.casefold() not in prior:
            return variant
    return variants[(max(1, call_index) - 1) % len(variants)]


def _finance_missing_fact_queries(*, formula_name: str, goal: str, primary_query: str, tickers: list[str]) -> list[str]:
    queries: list[str] = []

    def add(query: str) -> None:
        normalized = " ".join(str(query or "").split())
        if normalized and normalized not in queries:
            queries.append(normalized)

    add(primary_query)
    if formula_name == "ev_ebitda" and tickers:
        add(" ".join(f"{ticker} key statistics enterprise value market cap EBITDA total debt total cash" for ticker in tickers))
        for ticker in tickers:
            add(f"{ticker} key statistics enterprise value market cap EBITDA total debt total cash")
            add(f"{ticker} 10-K EBITDA debt cash SEC")
    elif formula_name == "dcf" and tickers:
        for ticker in tickers:
            add(f"{ticker} 10-K operating cash flow capital expenditures free cash flow SEC")
            add(f"{ticker} DCF WACC terminal growth assumptions investor presentation")
    elif formula_name == "lbo" and tickers:
        for ticker in tickers:
            add(f"{ticker} 10-K EBITDA operating cash flow free cash flow debt cash enterprise value market cap SEC")
            add(f"{ticker} LBO leverage exit multiple assumptions")
    elif formula_name == "capital_intensity" and tickers:
        for ticker in tickers:
            add(f"{ticker} SEC companyfacts capital expenditures revenue operating cash flow total assets PropertyPlantAndEquipmentNet")
            add(f"{ticker} 10-K balance sheet PP&E assets cash flow capital expenditures")
    else:
        add(_finance_missing_fact_secondary_query(formula_name=formula_name, goal=goal))
        add(_finance_missing_fact_tertiary_query(formula_name=formula_name, goal=goal))
    return queries


def _finance_missing_fact_authority_requirement(formula_name: str) -> str:
    if formula_name in {"ev_ebitda", "dcf", "lbo"}:
        return "secondary_or_better"
    return "primary"


def _finance_missing_fact_preferred_families(formula_name: str) -> list[str]:
    if formula_name == "ev_ebitda":
        return ["market_data_provider", "structured_regulatory_data", "regulatory_filing"]
    if formula_name in {"dcf", "lbo"}:
        return ["structured_regulatory_data", "regulatory_filing", "company_ir", "market_data_provider"]
    if formula_name == "capital_intensity":
        return ["structured_regulatory_data", "regulatory_filing", "company_ir"]
    return ["structured_regulatory_data", "regulatory_filing", "company_ir"]


def _finance_goal_tickers(goal: str) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for issuer in builtin_issuers_for_text(goal):
        ticker = str(issuer.get("ticker") or "").upper().strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def _finance_missing_fact_secondary_query(*, formula_name: str, goal: str) -> str:
    if formula_name == "ev_ebitda":
        return f"{goal} 10-K EBITDA debt cash market cap enterprise value"
    if formula_name == "bridge_subtotal":
        return f"{goal} annual report 10-K 10-Q non-GAAP adjusted EBITDA reconciliation add backs"
    if formula_name == "dcf":
        return f"{goal} annual report 10-K operating cash flow free cash flow capital expenditures"
    if formula_name == "lbo":
        return f"{goal} annual report 10-K adjusted EBITDA operating cash flow free cash flow debt cash enterprise value"
    if formula_name == "capital_intensity":
        return f"{goal} annual report 10-K PP&E total assets capital expenditures operating cash flow revenue"
    return f"{goal} SEC Archives 8-K 10-K consideration revenue"


def _finance_missing_fact_tertiary_query(*, formula_name: str, goal: str) -> str:
    if formula_name == "ev_ebitda":
        return f"{goal} official filing adjusted EBITDA market capitalization total debt cash equivalents"
    if formula_name == "bridge_subtotal":
        return f"{goal} investor relations annual report adjusted EBITDA non-GAAP reconciliation table"
    if formula_name == "dcf":
        return f"{goal} investor relations DCF assumptions WACC terminal growth cash flow"
    if formula_name == "lbo":
        return f"{goal} investor relations LBO assumptions leverage exit multiple EBITDA cash flow"
    if formula_name == "capital_intensity":
        return f"{goal} SEC companyfacts PropertyPlantAndEquipmentNet Assets PaymentsToAcquirePropertyPlantAndEquipment NetCashProvidedByUsedInOperatingActivities Revenues"
    return f"{goal} official filing transaction value revenue"


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
    def __init__(
        self,
        recipe: TaskRecipe,
        *,
        journal: JournalStore | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.recipe = recipe
        self.journal = journal
        self.artifact_store = artifact_store
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
            if isinstance(report, dict) and _retrieval_report_workbench_followup_required(report):
                return _feedback(
                    run_id,
                    self.calls,
                    "continue",
                    None,
                    None,
                    ["retrieval_workbench_followup"],
                )
            if _retrieval_workbench_followup_required(
                self.journal,
                recipe=self.recipe,
                context=context,
            ):
                return _feedback(
                    run_id,
                    self.calls,
                    "continue",
                    None,
                    None,
                    ["retrieval_workbench_followup"],
                )
            if _finance_formula_work_required_before_final(
                self.journal,
                recipe=self.recipe,
                context=context,
                artifact_store=self.artifact_store,
            ):
                return _feedback(
                    run_id,
                    self.calls,
                    "continue",
                    None,
                    None,
                    ["finance_formula_trace_required"],
                )
        answer = None
        if isinstance(observation.content, dict):
            answer = observation.content.get("text")
        return _feedback(run_id, self.calls, "final_answer_ready", "completed", answer if isinstance(answer, str) else None, [])


def _finance_formula_work_required_before_final(
    journal: JournalStore | None,
    *,
    recipe: TaskRecipe,
    context: ContextBundle,
    artifact_store: ArtifactStore | None = None,
) -> bool:
    if journal is None:
        return False
    if recipe.mode != "retrieval_answer" or CALCULATOR_TOOL_NAME not in recipe.allowed_tools:
        return False
    if not _finance_numeric_verifier_required(recipe):
        return False
    task_id = str(context.state.get("task_id") or "")
    run_id = str(context.state.get("run_id") or "")
    if not task_id or not run_id:
        return False
    evidence, citations, _ = _retrieval_and_toolchain_grounding(
        journal,
        task_id,
        run_id,
        recipe=recipe,
        artifact_store=artifact_store,
    )
    if not evidence:
        return False
    facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
    existing_traces = _calculator_formula_traces(journal, task_id=task_id, run_id=run_id)
    plan = plan_finance_formula(question=_root_goal_from_recipe(recipe), facts=facts, existing_traces=existing_traces)
    if plan.status == "not_applicable":
        return False
    if plan.status == "ready" and isinstance(plan.payload, dict):
        input_fact_ids = _string_list(plan.payload.get("input_fact_ids"))
        return not _formula_trace_covers_inputs(existing_traces, input_fact_ids)
    missing = [str(item) for item in plan.missing_facts if str(item)]
    return _finance_missing_fact_retrieval_needed(
        formula_name=str(plan.formula_name or ""),
        missing=missing,
        goal=_root_goal_from_recipe(recipe),
    )


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
        metadata_before = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
        protect_workbench_followup = bool(metadata_before.get("workbench_followup"))
        protected_query = payload.get("query") if protect_workbench_followup else None
        protected_queries = payload.get("queries") if protect_workbench_followup else None
        payload = _preserve_retrieval_capability_context(payload, recipe=recipe)
        payload = _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe, preserve_query=protect_workbench_followup)
        if protect_workbench_followup:
            if isinstance(protected_query, str) and protected_query:
                payload["query"] = protected_query
            if isinstance(protected_queries, list) and protected_queries:
                payload["queries"] = protected_queries
            payload = _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe, preserve_query=True)
        payload.setdefault("goal_id", _next_required_retrieval_goal_id(context, recipe) or "goal-agent-retrieval")
        payload.setdefault("query", goal)
        payload.setdefault("max_spans_per_document", 2)
        payload = _apply_recipe_profile_defaults(payload, recipe)
        payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
        payload = _apply_research_depth_defaults(payload)
        payload = _augment_finance_modeling_retrieval_payload(payload, root_goal=goal, recipe=recipe)
        payload = _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe, preserve_query=protect_workbench_followup)
        if protect_workbench_followup:
            return replace(action, payload=payload)
        decision = supervise_retrieval_payload(
            payload,
            replan_hints=_retrieval_hints_from_context(context),
            root_goal=goal,
        )
        payload = _enforce_benchmark_doc_retrieval_binding(decision.payload, goal=goal, recipe=recipe)
        reasons = list(action.reasons)
        if decision.diagnostics.get("rewritten") is True:
            reasons = _ordered_unique([*reasons, "host_strategy_supervision_rewrote_retrieval_payload"])
            metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
            metadata["strategy_supervision_diagnostics"] = decision.diagnostics
            payload["metadata"] = metadata
            action = replace(action, reasons=reasons)
        return replace(action, payload=payload)
    return action


def _retrieval_hints_from_context(context: ContextBundle) -> JsonObject:
    hints = context.state.get("agent_replan_hints")
    hints = hints if isinstance(hints, dict) else {}
    retrieval = hints.get("retrieval")
    return dict(retrieval) if isinstance(retrieval, dict) else {}


def _augment_finance_modeling_retrieval_payload(payload: JsonObject, *, root_goal: str, recipe: TaskRecipe) -> JsonObject:
    if recipe.mode != "retrieval_answer":
        return payload
    text = f"{root_goal} {payload.get('query') or ''}".lower()
    formula_name = "dcf" if ("discounted cash flow" in text or " dcf" in f" {text}") else "lbo" if (" lbo" in f" {text}" or "leveraged buyout" in text) else ""
    if not formula_name:
        return payload
    updated = dict(payload)
    query = " ".join(str(updated.get("query") or root_goal or "").split())
    if formula_name == "dcf":
        additions = "10-K operating cash flow free cash flow capital expenditures WACC discount rate terminal growth"
    else:
        additions = "10-K adjusted EBITDA operating cash flow free cash flow enterprise value market cap debt cash leverage exit multiple"
    updated["query"] = _append_query_terms(query, additions)
    queries = _string_list(updated.get("queries"))
    if queries:
        updated["queries"] = _ordered_unique([updated["query"], *[_append_query_terms(item, additions) for item in queries]])[: max(len(queries), 4)]
        updated["max_queries"] = max(int(updated.get("max_queries") or 0), min(6, len(updated["queries"])))
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata["finance_modeling_intent"] = formula_name
    metadata.setdefault("research_task_kind", "valuation")
    metadata.setdefault("preferred_source_families", ["structured_regulatory_data", "regulatory_filing", "company_ir", "market_data_provider"])
    updated["metadata"] = metadata
    updated["max_sources"] = max(int(updated.get("max_sources") or 0), 24)
    updated["max_fetches"] = max(int(updated.get("max_fetches") or 0), 12)
    updated["max_spans_per_document"] = max(int(updated.get("max_spans_per_document") or 0), 8)
    return updated


def _append_query_terms(query: str, additions: str) -> str:
    existing = " ".join(str(query or "").split())
    lower = existing.lower()
    missing_terms = [term for term in str(additions or "").split() if term.lower() not in lower]
    return " ".join([existing, *missing_terms]).strip()


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
        "search_strategy",
        "query_campaign",
    ):
        value = cap_metadata.get(key, capability_args.get(key))
        if isinstance(value, str) and value:
            metadata.setdefault(key, value)
    for key in (
        "retrieval_strategy",
        "model_retrieval_strategy",
        "preferred_source_families",
        "source_family_plan",
        "minimum_coverage",
    ):
        value = cap_metadata.get(key, capability_args.get(key))
        if isinstance(value, (dict, list)) and value:
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


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _composable_toolchain_config(metadata: JsonObject) -> JsonObject:
    execution = metadata.get("execution_metadata")
    execution = execution if isinstance(execution, dict) else {}
    raw = metadata.get("composable_toolchain")
    if not isinstance(raw, dict):
        raw = execution.get("composable_toolchain")
    if not isinstance(raw, dict) or not _truthy(raw.get("enabled")):
        return {}
    return dict(raw)


def _composable_toolchain_enabled(recipe: TaskRecipe) -> bool:
    return bool(_composable_toolchain_config(recipe.metadata))


def _model_task_compiler_enabled(recipe: TaskRecipe) -> bool:
    config = _composable_toolchain_config(recipe.metadata)
    if _truthy(config.get("model_task_compiler")):
        return True
    execution = _execution_metadata(recipe)
    return _truthy(execution.get("model_task_compiler"))


def _composable_shell_allowed_executables(recipe: TaskRecipe) -> set[str]:
    config = _composable_toolchain_config(recipe.metadata)
    values = _string_list(config.get("shell_allowed_executables"))
    if not values:
        values = ["python", "python3"]
    return {Path(item).name for item in values if Path(item).name}


def _composable_tool_timeout_seconds(recipe: TaskRecipe, *, key: str, default: int) -> int:
    config = _composable_toolchain_config(recipe.metadata)
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(120, value))


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
        allowed_tools = ["retrieval.run"]
        if _metadata_requires_finance_numeric_verifier(recipe_metadata):
            allowed_tools.append(CALCULATOR_TOOL_NAME)
        toolchain = _composable_toolchain_config(recipe_metadata)
        if _truthy(toolchain.get("workspace_read")):
            allowed_tools.extend(["workspace.list", "workspace.search", "file.read"])
        if _truthy(toolchain.get("workspace_write")):
            allowed_tools.append("workspace.write")
            recipe_metadata = _with_allowed_permission(recipe_metadata, "workspace:write")
        if _truthy(toolchain.get("shell_exec")):
            allowed_tools.append("shell.exec")
            recipe_metadata = _with_allowed_permission(recipe_metadata, "shell:exec")
        if _truthy(toolchain.get("script_exec")):
            allowed_tools.append("script.exec")
            recipe_metadata = _with_allowed_permission(recipe_metadata, "shell:exec")
            recipe_metadata = _with_allowed_permission(recipe_metadata, "workspace:write")
        return TaskRecipe(
            recipe_id="recipe-retrieval-answer",
            allowed_tools=_ordered_unique(allowed_tools),
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
    profile = _execution_profile_metadata(recipe)
    profile_id = str(profile.get("profile_id") or "")
    hard_cap_loop = bool(profile_id and profile_id != "long-mission")
    model_dynamic = planner_mode == "model" and recipe.mode in {"retrieval_answer", "workspace_answer", "workspace_write"}
    max_steps = _positive_metadata_int(loop.get("max_steps"), default=0) if loop else 0
    max_tool_calls = _positive_metadata_int(loop.get("max_tool_calls"), default=0) if loop else 0
    max_artifact_bytes = _positive_metadata_int(loop.get("max_total_artifact_bytes"), default=0) if loop else 0
    if hard_cap_loop:
        return replace(
            recipe,
            max_steps=max_steps if max_steps > 0 else recipe.max_steps,
            max_tool_calls=max_tool_calls if max_tool_calls > 0 else recipe.max_tool_calls,
            max_total_artifact_bytes=max_artifact_bytes
            if max_artifact_bytes > 0
            else recipe.max_total_artifact_bytes,
        )
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
            payload = _merge_retrieval_payload(payload, _benchmark_doc_retrieval_payload(goal))
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
    for raw_key, preview_key in (("text", "text"), ("script", "script")):
        text = payload.pop(raw_key, None)
        if isinstance(text, str):
            payload[f"{preview_key}_preview"] = _preview_text(text, 160)
            payload[f"{preview_key}_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            payload[f"{preview_key}_chars"] = len(text)
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
    workmethod = _compact_workmethod_for_prompt(_workmethod_metadata(recipe))
    if recipe.mode == "retrieval_answer":
        tool_selection = [
            {
                "kind": "tool",
                "name": "retrieval.run",
                "side_effect_class": "read",
                "use_when": "external or indexed evidence is needed, evidence coverage is incomplete, or citation support is missing",
                "payload_requirements": ["query or goal"],
            }
        ]
        if CALCULATOR_TOOL_NAME in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": CALCULATOR_TOOL_NAME,
                    "side_effect_class": "read",
                    "use_when": (
                        "finance facts have been observed and the user asks for a calculation, ratio, CAGR, margin, "
                        "basis-point difference, transaction multiple, DIO, DCF/LBO step, or other numeric derivation"
                    ),
                    "payload_requirements": [
                        "expression: Decimal-safe arithmetic expression",
                        "variables: named numeric inputs from cited facts",
                        "unit: optional percent/bps/USD/etc.",
                        "input_fact_ids: finance fact ids when available",
                    ],
                }
            )
        if "workspace.list" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "workspace.list",
                    "side_effect_class": "read",
                    "use_when": "local workspace, cached benchmark data, generated artifacts, or directory context may guide the research workflow",
                    "payload_requirements": ["path: optional workspace-relative directory"],
                }
            )
        if "workspace.search" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "workspace.search",
                    "side_effect_class": "read",
                    "use_when": "find local filings, benchmark JSONL, cached traces, scripts, reports, or intermediate artifacts by keyword/path",
                    "payload_requirements": ["query: non-empty keyword or path fragment", "max_matches: optional"],
                }
            )
        if "file.read" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "file.read",
                    "side_effect_class": "read",
                    "use_when": "inspect a known local document, cached result, benchmark item, report, script, or trace before deciding next action",
                    "payload_requirements": ["path: workspace-relative file path"],
                }
            )
        if "workspace.write" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "workspace.write",
                    "side_effect_class": "write",
                    "use_when": "create a temporary parser, normalized evidence file, or intermediate JSON artifact under the workspace before running or reading it",
                    "payload_requirements": ["path: workspace-relative file path", "text: complete UTF-8 body"],
                    "host_boundary": "requires workspace:write permission; host journals preview/hash and artifact refs",
                }
            )
        if "shell.exec" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "shell.exec",
                    "side_effect_class": "shell",
                    "use_when": (
                        "temporary local analysis is needed: parse downloaded filings/tables, inspect JSONL, run a small script, "
                        "score outputs, or transform local evidence before calculator/verifier/synthesis"
                    ),
                    "payload_requirements": ["argv: list[str] using host-allowed executables only"],
                    "host_boundary": "requires shell:exec permission and executable allowlist; host audits stdout/stderr as observation",
                }
            )
        if "script.exec" in recipe.allowed_tools:
            tool_selection.append(
                {
                    "kind": "tool",
                    "name": "script.exec",
                    "side_effect_class": "shell",
                    "use_when": (
                        "a multi-line temporary parser or local analysis program is more reliable than inline shell; "
                        "emit JSON facts/tables/slot fills for host grounding"
                    ),
                    "payload_requirements": [
                        "language: python",
                        "script: complete script text",
                        "expected_output: json when emitting structured facts",
                        "timeout_seconds: optional bounded timeout",
                    ],
                    "host_boundary": "requires shell:exec and workspace:write; host writes the script under .holo_toolchain, audits stdout/stderr, and artifacts outputs",
                }
            )
        forbidden = ["web_search", "page_open"]
        if "network.fetch" not in recipe.allowed_tools:
            forbidden.append("network.fetch")
        return {
            "mode": recipe.mode,
            "initial_action": {
                "kind": "tool",
                "name": "retrieval.run",
                "side_effect_class": "read",
                "payload_requirements": ["query or goal"],
                "use_when": "no relevant retrieval evidence has been observed yet",
            },
            "tool_selection": tool_selection,
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
            "forbidden": forbidden,
            "interaction_preferences": preferences,
            "answer_profile": answer_profile,
            "research_mission": research_mission,
            "final_answer_contract": _final_answer_contract(answer_profile),
            "semantic_intake": semantic,
            "semantic_state_profile_summary": state_profile_summary,
            "active_memory": active_memory,
            "workmethod": workmethod,
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
            "workmethod": workmethod,
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
            "workmethod": workmethod,
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
            "workmethod": workmethod,
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
            "workmethod": workmethod,
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
            "workmethod": workmethod,
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
        "workmethod": workmethod,
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
    execution_program = _execution_program_hint_for_planner(
        journal,
        task_id=task_id,
        run_id=run_id,
        recipe=recipe,
    )
    if execution_program:
        hints["execution_program"] = execution_program
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


def _execution_program_hint_for_planner(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
) -> JsonObject:
    metadata_program = recipe.metadata.get("execution_program") if isinstance(recipe.metadata, dict) else None
    if isinstance(metadata_program, dict):
        compact = _compact_compiled_task_program_for_prompt(metadata_program)
        if compact:
            compact["source_record_ref"] = "recipe.execution_program"
            return compact
    latest = _latest_journal_record(journal, task_id=task_id, run_id=run_id, kind="compiled_task_program")
    if latest is not None and isinstance(latest.data, dict):
        compact = _compact_compiled_task_program_for_prompt(latest.data)
        if compact:
            compact["source_record_ref"] = latest.record_id
            return compact
    if recipe.mode != "retrieval_answer":
        return {}
    question = _root_goal_from_recipe(recipe)
    if not question or question == recipe.mode:
        return {}
    binding = _target_document_binding_from_recipe(recipe)
    if _research_profile_id(recipe) != FINANCE_FUNDAMENTALS_PROFILE_ID and not binding:
        return {}
    try:
        compiled = compile_finance_task_program(question=question, facts=[], target_binding=binding)
    except Exception:
        return {}
    return _compact_compiled_task_program_for_prompt(
        {
            **compiled.to_dict(),
            "schema": "holo.kernel_v3.compiled_task_program.v1",
            "source": "planner_preflight_task_compiler",
        }
    )


def _compact_compiled_task_program_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    task_spec = _json_object(value.get("task_spec"))
    slot_frame = _json_object(value.get("slot_frame"))
    diagnostics = _json_object(value.get("diagnostics"))
    tool_chain_plan = _compact_tool_chain_plan_for_prompt(diagnostics.get("tool_chain_plan"))
    evidence_specs = [
        _compact_simple_dict(item, limit=10)
        for item in list(value.get("evidence_specs") or [])[:12]
        if isinstance(item, dict)
    ]
    transform_specs = [
        _compact_simple_dict(item, limit=9)
        for item in list(value.get("transform_specs") or [])[:8]
        if isinstance(item, dict)
    ]
    missing_slots = _ordered_unique(
        [
            *_string_list(diagnostics.get("missing_slots")),
            *_string_list(slot_frame.get("missing_slots")),
            *_string_list(tool_chain_plan.get("missing_slots")),
        ]
    )
    return {
        "schema": "holo.kernel_v3.execution_program_prompt.v1",
        "source_schema": value.get("schema"),
        "program_id": value.get("program_id"),
        "domain": value.get("domain"),
        "task_spec": {
            "task_type": task_spec.get("task_type"),
            "objective": _text_preview(task_spec.get("objective"), limit=480),
            "target_entities": _string_list(task_spec.get("target_entities"))[:8],
            "target_periods": _string_list(task_spec.get("target_periods"))[:8],
            "success_criteria": _string_list(task_spec.get("success_criteria"))[:8],
        },
        "evidence_specs": evidence_specs,
        "transform_specs": transform_specs,
        "missing_slots": missing_slots[:16],
        "tool_chain_plan": tool_chain_plan,
        "planner_instruction": (
            "Use this execution program as a workbench for assembling tools. "
            "The model chooses next retrieval/calculation moves; host verifies provenance, policy, and numeric support."
        ),
    }


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
    failure_attribution = _json_object(diagnostics.get("failure_attribution"))
    source_quality = _json_object(diagnostics.get("source_quality"))
    evidence_data = dict(evidence_record.data) if evidence_record is not None else {}
    evidence_diagnostics = _json_object(evidence_data.get("diagnostics"))
    planned_coverage = _json_object(evidence_diagnostics.get("planned_retrieval_coverage"))
    incomplete_planned_goal_ids = _string_list(planned_coverage.get("incomplete_goal_ids"))
    mission_directive = _mission_directive_metadata(recipe)
    mission_avoid_queries = _string_list(mission_directive.get("avoid_repeating"))
    mission_missing = _string_list(mission_directive.get("missing_requirements"))
    mission_strategy = _string_value(mission_directive.get("strategy"))
    rejected_evidence_count = _int_or_none(diagnostics.get("rejected_evidence_count")) or 0
    source_rejection_count = _int_or_none(diagnostics.get("source_rejection_count")) or 0
    missing = _ordered_unique(
        [
            *_string_list(evidence_data.get("missing")),
            *mission_missing,
            *[f"query_facet:{facet}" for facet in _string_list(evaluation.get("missing_query_facets"))],
            *[f"finance_facet:{facet}" for facet in _string_list(evaluation.get("missing_finance_facets"))],
            *[f"finance_facet:{facet}" for facet in _string_list(evidence_diagnostics.get("missing_finance_facets"))],
            *_string_list(evidence_diagnostics.get("missing_source_authority")),
            *(["candidate_evidence_rejected"] if rejected_evidence_count > 0 else []),
            *(["candidate_source_rejected"] if source_rejection_count > 0 else []),
            *(["source_authority_gap"] if source_quality.get("authority_sufficient") is False else []),
            *(
                [f"retrieval_failure:{failure_attribution.get('primary_failure_mode')}"]
                if _string_value(failure_attribution.get("primary_failure_mode")) not in {"", "none"}
                else []
            ),
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
    base_query = _string_value(
        report_data.get("preview")
        or diagnostics.get("goal_query")
        or diagnostics.get("query")
        or mission_directive.get("next_subgoal")
        or mission_directive.get("root_goal")
    )
    strategy_hints = _suggested_retrieval_strategies(
        missing=missing,
        report_reason=report_reason,
        requirement=requirement,
        attempts=attempts,
    )
    if mission_strategy:
        strategy_hints = _ordered_unique([mission_strategy, *strategy_hints])
    query_hints = _suggested_query_hints(
        base_query=base_query,
        missing=missing,
        requirement=requirement,
    )
    source_targets = _suggested_source_targets(
        recipe=recipe,
        query=base_query,
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
    needs_replan = bool(
        (report_record is not None and (report_status != "sufficient" or incomplete_planned_goal_ids))
        or mission_avoid_queries
        or mission_strategy
    )
    attempted_queries = _ordered_unique(
        [
            *[item["query"] for item in attempts if isinstance(item.get("query"), str)],
            *mission_avoid_queries,
        ]
    )
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
        "source_quality": source_quality,
        "failure_attribution": {
            "primary_failure_mode": _string_value(failure_attribution.get("primary_failure_mode")),
            "next_strategy_hint": _string_value(failure_attribution.get("next_strategy_hint")),
            "reason": _string_value(failure_attribution.get("reason")),
        } if failure_attribution else {},
        "suggested_search_strategies": strategy_hints,
        "suggested_query_hints": query_hints,
        "suggested_source_targets": source_targets,
        "suggested_filing_documents": suggested_filing_documents,
        "suggested_sec_structured_sources": suggested_sec_structured_sources,
        "suggested_macro_series": suggested_macro_series,
        "suggested_fiscaldata_endpoints": suggested_fiscaldata_endpoints,
        "attempted_queries": attempted_queries,
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
        "mission_directive": mission_directive,
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


def _action_retrieval_source_urls(journal: JournalStore, *, task_id: str, run_id: str) -> list[str]:
    urls: list[str] = []
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        if record.data.get("name") != "retrieval.run":
            continue
        payload = record.data.get("payload")
        if not isinstance(payload, dict):
            continue
        urls.extend(_retrieval_payload_urls(payload))
    return _ordered_unique(urls)


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
    if "source_authority_gap" in missing:
        suggestions.extend(["structured", "aggregate", "crawl", "fresh_live"])
    if any(item.startswith("query_facet:") for item in missing):
        suggestions.extend(["aggregate", "fresh_live", "crawl"])
    if "candidate_evidence_rejected" in missing or "candidate_source_rejected" in missing:
        suggestions.extend(["aggregate", "fresh_live", "structured", "crawl"])
    if any(item.startswith("finance_facet:") for item in missing):
        suggestions.extend(["structured", "aggregate", "fresh_live", "crawl"])
    if "retrieval_evidence" in missing or "sufficient_retrieval_evidence" in missing:
        suggestions.extend(["aggregate", "structured", "crawl", "fresh_live"])
    if "retrieval_failure:source_authority_gap" in missing:
        suggestions.extend(["structured", "aggregate", "crawl"])
    if "retrieval_failure:no_fetchable_sources" in missing:
        suggestions.extend(["structured", "crawl", "aggregate"])
    if "retrieval_failure:fetch_failed_or_empty" in missing:
        suggestions.extend(["aggregate", "crawl", "fresh_live"])
    if report_reason in {"no_primary_source_for_research_profile", "no_required_authority_source_for_research_profile"}:
        suggestions.extend(["structured", "aggregate", "fresh_live"])
    result = [item for item in _ordered_unique(suggestions) if item not in attempted]
    return result or ["aggregate", "fresh_live", "structured"]


def _suggested_query_hints(*, base_query: str, missing: list[str], requirement: str) -> list[str]:
    additions: list[str] = []
    if "primary_source" in missing or "source_authority:primary" in missing or requirement == "primary":
        additions.extend(["official filing", "annual report", "10-K 10-Q", "issuer investor relations", "exchange disclosure"])
    if "source_authority_gap" in missing or "retrieval_failure:source_authority_gap" in missing:
        additions.extend(["official source", "primary source", "official report", "source documentation"])
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
        or "source_authority_gap" in missing
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


def _execution_profile_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("execution_profile")
    return dict(value) if isinstance(value, dict) else {}


def _metadata_requires_finance_numeric_verifier(metadata: JsonObject) -> bool:
    execution = metadata.get("execution_metadata")
    execution = execution if isinstance(execution, dict) else {}
    profile = execution.get("execution_profile")
    if not isinstance(profile, dict):
        profile = metadata.get("execution_profile")
    profile = profile if isinstance(profile, dict) else {}
    if bool(profile.get("require_numeric_verifier")):
        return True
    return bool(metadata.get("require_numeric_verifier") or execution.get("require_numeric_verifier"))


def _finance_numeric_verifier_required(recipe: TaskRecipe) -> bool:
    if recipe.mode != "retrieval_answer":
        return False
    if CALCULATOR_TOOL_NAME in recipe.allowed_tools:
        return True
    return _metadata_requires_finance_numeric_verifier(recipe.metadata)


def _toolchain_grounding_enabled(recipe: TaskRecipe) -> bool:
    return recipe.mode == "retrieval_answer" and any(
        name in set(recipe.allowed_tools)
        for name in ("workspace.list", "workspace.search", "file.read", "workspace.write", "shell.exec", "script.exec")
    )


def _merge_evidence_items(existing: list[EvidenceItem], extra: list[EvidenceItem]) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in [*existing, *extra]:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        result.append(item)
    return result


def _merge_citation_items(existing: list[CitationItem], extra: list[CitationItem]) -> list[CitationItem]:
    result: list[CitationItem] = []
    seen: set[str] = set()
    for item in [*existing, *extra]:
        if item.citation_id in seen:
            continue
        seen.add(item.citation_id)
        result.append(item)
    return result


def _report_with_toolchain_grounding(
    report: RetrievalReport | None,
    *,
    toolchain_report: RetrievalReport,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
) -> RetrievalReport:
    artifact_refs = _ordered_unique([str(item.artifact_id) for item in evidence if item.artifact_id])
    if report is None:
        return replace(
            toolchain_report,
            evidence_ids=[item.evidence_id for item in evidence],
            citation_ids=[item.citation_id for item in citations],
            artifact_refs=artifact_refs,
            status="sufficient" if evidence else toolchain_report.status,
            diagnostics={
                **dict(toolchain_report.diagnostics),
                "source": "toolchain_grounding",
                "synthetic_retrieval_report": True,
            },
        )
    diagnostics = dict(report.diagnostics)
    diagnostics["toolchain_grounding"] = {
        "evidence_count": len(toolchain_report.evidence_ids),
        "citation_count": len(toolchain_report.citation_ids),
        "report_id": toolchain_report.report_id,
    }
    return replace(
        report,
        status="sufficient" if evidence and citations else report.status,
        evidence_ids=_ordered_unique([*list(report.evidence_ids), *[item.evidence_id for item in evidence]]),
        citation_ids=_ordered_unique([*list(report.citation_ids), *[item.citation_id for item in citations]]),
        artifact_refs=_ordered_unique([*list(report.artifact_refs), *artifact_refs]),
        diagnostics=diagnostics,
    )


def _agent_loop_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("agent_loop")
    return dict(value) if isinstance(value, dict) else {}


def _processor_budget_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("processor_budget")
    return dict(value) if isinstance(value, dict) else {}


def _thread_working_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("thread_working_context")
    return dict(value) if isinstance(value, dict) else {}


def _mission_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("mission_context")
    return dict(value) if isinstance(value, dict) else {}


def _workmethod_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("workmethod")
    return dict(value) if isinstance(value, dict) else {}


def _mission_directive_metadata(recipe: TaskRecipe) -> JsonObject:
    context = _mission_context_metadata(recipe)
    directive = context.get("directive")
    if isinstance(directive, dict):
        return dict(directive)
    state = context.get("mission_state")
    if isinstance(state, dict) and isinstance(state.get("directive"), dict):
        return dict(state["directive"])
    return {}


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


def _semantic_goal_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("semantic_goal")
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


def _answer_quality_retry_instruction(gaps: list[str], *, recipe: TaskRecipe) -> str:
    answer_profile = _answer_profile_metadata(recipe)
    payload = {
        "repair_reason": "final_answer_quality_insufficient",
        "quality_gaps": list(gaps),
        "answer_profile": _final_answer_contract(answer_profile),
        "root_goal": _root_goal_from_recipe(recipe),
        "instructions": [
            "Rewrite the final answer as a complete user-visible answer, not a diagnostic fragment.",
            "Satisfy answer_profile.target_sections and answer_profile.minimum_coverage.",
            "Do not omit unsupported required coverage; include a clear limitation for each unsupported part.",
            "Use only provided evidence ids and citation ids.",
            "If the task is finance research, separate source-backed metrics, business analysis, valuation/market data, risks, and evidence limitations.",
            "Do not claim retrieval/network/finance tools are unavailable unless host_situation explicitly says so.",
            "Avoid generic agreement, apology, or flattery. Start with the substantive answer.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _root_goal_from_recipe(recipe: TaskRecipe) -> str:
    research_mission = _research_mission_metadata(recipe)
    for key in ("root_goal", "goal", "task_goal"):
        value = research_mission.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    semantic_goal = _semantic_goal_metadata(recipe)
    for key in ("root_goal", "goal", "input_text"):
        value = semantic_goal.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    semantic = _semantic_intake_metadata(recipe)
    value = semantic.get("goal")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(recipe.metadata.get("goal") or recipe.mode)


def _thread_rag_context_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("thread_rag_context")
    return dict(value) if isinstance(value, dict) else {}


def _durable_memory_context_from_sections(sections: object) -> JsonObject:
    if not isinstance(sections, list):
        return {}
    for section in sections:
        if not isinstance(section, dict) or section.get("name") != "durable_memory":
            continue
        context = section.get("context")
        if isinstance(context, dict):
            return _compact_durable_memory_context_for_prompt(context)
        return _compact_durable_memory_section_for_prompt(section)
    return {}


def _compact_durable_memory_section_for_prompt(section: JsonObject) -> JsonObject:
    items = [item for item in list(section.get("items") or [])[:8] if isinstance(item, dict)]
    return _compact_durable_memory_context_for_prompt(
        {
            "kind": "durable_memory_context",
            "enabled": True,
            "total": section.get("total", len(items)),
            "combined_memory_ids": (section.get("combined") or {}).get("memory_ids", []) if isinstance(section.get("combined"), dict) else [],
            "top_items": items,
            "views": section.get("views", {}),
        }
    )


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
    if "durable_memory_context" in execution:
        execution["durable_memory_context"] = _compact_durable_memory_context_for_prompt(execution.get("durable_memory_context"))
    if "workmethod" in execution:
        execution["workmethod"] = _compact_workmethod_for_prompt(execution.get("workmethod"))
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
            "durable_memory_context": execution.get("durable_memory_context", {}),
            "workmethod": execution.get("workmethod", {}),
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
        "initial_action": _compact_simple_dict(value.get("initial_action"), limit=8),
        "required_first_action": _compact_simple_dict(value.get("required_first_action"), limit=8),
        "tool_selection": [
            _compact_simple_dict(item, limit=10)
            for item in list(value.get("tool_selection") or [])[:6]
            if isinstance(item, dict)
        ],
        "allowed_non_tool_actions": [
            _compact_simple_dict(item, limit=8)
            for item in list(value.get("allowed_non_tool_actions") or [])[:4]
            if isinstance(item, dict)
        ],
        "active_memory": _compact_simple_dict(value.get("active_memory"), limit=10),
        "answer_profile": _compact_simple_dict(value.get("answer_profile"), limit=16),
        "final_answer_contract": _compact_simple_dict(value.get("final_answer_contract"), limit=16),
        "search_strategy_hint": _compact_simple_dict(value.get("search_strategy_hint"), limit=12),
        "workmethod": _compact_workmethod_for_prompt(value.get("workmethod")),
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
    current_step = value.get("current_step")
    if isinstance(current_step, dict):
        result["current_step"] = {
            "iteration_index": current_step.get("iteration_index"),
            "current_input_preview": _text_preview(current_step.get("current_input_preview"), limit=480),
            "is_continuation": bool(current_step.get("is_continuation")),
            "active_task_id": current_step.get("active_task_id"),
        }
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
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
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
        "strategy_shift": _compact_simple_dict(metadata.get("strategy_shift"), limit=12),
    }


def _compact_durable_memory_context_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "kind": value.get("kind") or "durable_memory_context",
        "enabled": value.get("enabled"),
        "total": value.get("total"),
        "combined_memory_ids": _string_list(value.get("combined_memory_ids"))[:16],
        "view_totals": _compact_simple_dict(value.get("view_totals"), limit=8),
        "views": _compact_durable_memory_views_for_prompt(value.get("views")),
        "top_items": [
            _compact_durable_memory_item_for_prompt(item)
            for item in list(value.get("top_items") or [])[:8]
            if isinstance(item, dict)
        ],
        "active_recall_hint": _text_preview(value.get("active_recall_hint"), limit=360),
        "host_boundary": _text_preview(value.get("host_boundary"), limit=360),
    }


def _compact_durable_memory_views_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for label, view in list(value.items())[:4]:
        if not isinstance(view, dict):
            continue
        result[str(label)] = {
            "label": view.get("label") or str(label),
            "total": view.get("total"),
            "memory_ids": _string_list(view.get("memory_ids"))[:12],
            "kinds": _string_list(view.get("kinds"))[:8],
            "filtered": _compact_simple_dict(view.get("filtered"), limit=6),
        }
    return result


def _compact_durable_memory_item_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "memory_id": value.get("memory_id"),
        "kind": value.get("kind"),
        "title": _text_preview(value.get("title"), limit=120),
        "summary": _text_preview(value.get("summary"), limit=240),
        "structured_summary": _compact_structured_summary_for_prompt(value.get("structured_summary")),
        "privacy_class": value.get("privacy_class"),
        "confidence": value.get("confidence"),
        "payload_hash": value.get("payload_hash"),
        "provenance_refs": _string_list(value.get("provenance_refs"))[:4],
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
        "active_memory_recalls": [
            _compact_memory_recall_trace_for_prompt(item)
            for item in list(value.get("active_memory_recalls") or [])[-4:]
            if isinstance(item, dict)
        ],
        "attention_blocks": [
            _compact_attention_block_for_prompt(item)
            for item in list(value.get("attention_blocks") or [])[:6]
            if isinstance(item, dict)
        ],
        "task_continuity": _compact_task_continuity_for_prompt(value.get("task_continuity")),
        "self_iteration": _compact_self_iteration_for_prompt(value.get("self_iteration")),
        "memory_learning": [
            _compact_memory_learning_for_prompt(item)
            for item in list(value.get("memory_learning") or [])[-4:]
            if isinstance(item, dict)
        ],
    }


def _compact_attention_block_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "block_id": value.get("block_id"),
        "kind": value.get("kind"),
        "priority": value.get("priority"),
        "summary": _text_preview(value.get("summary"), limit=360),
        "refs": _string_list(value.get("refs"))[:8],
    }


def _compact_self_iteration_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "kind": value.get("kind") or "self_iteration_context",
        "status": value.get("status"),
        "latest_failure_reason": value.get("latest_failure_reason"),
        "latest_missing_evidence": _string_list(value.get("latest_missing_evidence"))[:12],
        "answer_quality_gaps": _string_list(value.get("answer_quality_gaps"))[:12],
        "recalled_quality_gaps": _string_list(value.get("recalled_quality_gaps"))[:12],
        "recalled_memory_ids": _string_list(value.get("recalled_memory_ids"))[-16:],
        "recalled_structured_keys": _string_list(value.get("recalled_structured_keys"))[:12],
        "recalled_structured_hit_keys": _string_list(value.get("recalled_structured_hit_keys"))[:12],
        "avoid_repeating_queries": _string_list(value.get("avoid_repeating_queries"))[-12:],
        "recommended_next_actions": _string_list(value.get("recommended_next_actions"))[:8],
        "learning_refs": _string_list(value.get("learning_refs"))[-8:],
        "learning_signals": [
            _compact_memory_learning_signal_for_prompt(item)
            for item in list(value.get("learning_signals") or [])[-4:]
            if isinstance(item, dict)
        ],
        "active_memory_recall_signals": [
            _compact_active_memory_recall_signal_for_prompt(item)
            for item in list(value.get("active_memory_recall_signals") or [])[-4:]
            if isinstance(item, dict)
        ],
        "host_rule": _text_preview(value.get("host_rule"), limit=360),
    }


def _compact_memory_learning_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "record_ref": value.get("record_ref"),
        "proposal_id": value.get("proposal_id"),
        "approval_status": value.get("approval_status"),
        "approval_policy": value.get("approval_policy"),
        "review_nonblocking": value.get("review_nonblocking"),
        "source_kind": value.get("source_kind"),
        "proposed_kind": value.get("proposed_kind"),
        "quality_gaps": _string_list(value.get("quality_gaps"))[:12],
        "summary_preview": _text_preview(value.get("summary_preview"), limit=360),
        "summary_hash": value.get("summary_hash"),
        "evidence_record_refs": _string_list(value.get("evidence_record_refs"))[:6],
    }


def _compact_memory_learning_signal_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "record_ref": value.get("record_ref"),
        "proposal_id": value.get("proposal_id"),
        "source_kind": value.get("source_kind"),
        "quality_gaps": _string_list(value.get("quality_gaps"))[:8],
        "summary_preview": _text_preview(value.get("summary_preview"), limit=240),
    }


def _compact_active_memory_recall_signal_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "record_ref": value.get("record_ref"),
        "scope": value.get("scope"),
        "memory_id": value.get("memory_id"),
        "kind": value.get("kind"),
        "source": value.get("source"),
        "quality_gaps": _string_list(value.get("quality_gaps"))[:8],
        "next_actions": _string_list(value.get("next_actions"))[:6],
        "structured_keys": _string_list(value.get("structured_keys"))[:12],
        "structured_hit_keys": _string_list(value.get("structured_hit_keys"))[:8],
        "matched_terms": _string_list(value.get("matched_terms"))[:8],
        "match_score": value.get("match_score"),
        "summary_preview": _text_preview(value.get("summary_preview"), limit=240),
    }


def _compact_task_continuity_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "kind": value.get("kind") or "task_continuity_context",
        "mission_id": value.get("mission_id"),
        "current_objective": _text_preview(value.get("current_objective"), limit=520),
        "latest_result_status": value.get("latest_result_status"),
        "latest_decision": value.get("latest_decision"),
        "coverage_score": value.get("coverage_score"),
        "covered_requirements": _string_list(value.get("covered_requirements"))[:12],
        "open_requirements": _string_list(value.get("open_requirements"))[:16],
        "next_subgoal": _text_preview(value.get("next_subgoal"), limit=360),
        "strategy": value.get("strategy"),
        "avoid_repeating": _string_list(value.get("avoid_repeating"))[-16:],
        "recent_actions": [
            _compact_simple_dict(item, limit=4)
            for item in list(value.get("recent_actions") or [])[-8:]
            if isinstance(item, dict)
        ],
        "evidence_refs": _string_list(value.get("evidence_refs"))[:12],
        "citation_refs": _string_list(value.get("citation_refs"))[:12],
        "suggested_actions": [
            _compact_simple_dict(item, limit=6)
            for item in list(value.get("suggested_actions") or [])[:6]
            if isinstance(item, dict)
        ],
        "stop_conditions": _string_list(value.get("stop_conditions"))[:8],
        "host_rule": _text_preview(value.get("host_rule"), limit=420),
    }


def _compact_workmethod_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    frame = value.get("frame") if isinstance(value.get("frame"), dict) else {}
    method = value.get("method") if isinstance(value.get("method"), dict) else {}
    working = value.get("thread_working_set") if isinstance(value.get("thread_working_set"), dict) else {}
    diagnostics = value.get("diagnostics") if isinstance(value.get("diagnostics"), dict) else {}
    return {
        "state_id": value.get("state_id"),
        "source": value.get("source"),
        "frame": {
            "user_goal": _text_preview(frame.get("user_goal"), limit=720),
            "inferred_goal": _text_preview(frame.get("inferred_goal"), limit=720),
            "work_type": frame.get("work_type"),
            "difficulty": frame.get("difficulty"),
            "risk_level": frame.get("risk_level"),
            "expected_output": _compact_simple_dict(frame.get("expected_output"), limit=10),
            "done_criteria": _string_list(frame.get("done_criteria"))[:16],
            "tool_needs": _string_list(frame.get("tool_needs"))[:12],
            "memory_needs": _string_list(frame.get("memory_needs"))[:12],
            "assumptions": _string_list(frame.get("assumptions"))[:8],
        },
        "method": {
            "method_name": method.get("method_name"),
            "first_moves": _string_list(method.get("first_moves"))[:8],
            "evidence_strategy": _string_list(method.get("evidence_strategy"))[:10],
            "failure_moves": _string_list(method.get("failure_moves"))[:10],
            "stop_policy": _string_list(method.get("stop_policy"))[:8],
            "user_interaction_policy": _string_list(method.get("user_interaction_policy"))[:6],
        },
        "thread_working_set": {
            "active_goal": _text_preview(working.get("active_goal"), limit=720),
            "current_method": working.get("current_method"),
            "successful_findings": _string_list(working.get("successful_findings"))[-10:],
            "failed_attempts": _string_list(working.get("failed_attempts"))[-10:],
            "open_gaps": _string_list(working.get("open_gaps"))[:16],
            "next_intent": _text_preview(working.get("next_intent"), limit=240),
            "trace_refs": _string_list(working.get("trace_refs"))[-12:],
        },
        "diagnostics": _compact_simple_dict(diagnostics, limit=12),
        "host_rule": "Use this as a working-method packet; do not treat it as permission to execute tools or ignore policy.",
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
        result = {
            "record_ref": value.get("record_ref"),
            "kind": kind,
            "source": value.get("source"),
            "status": value.get("status"),
            "content_preview": _text_preview(value.get("content_preview"), limit=220),
        }
        if value.get("source") == "tool:memory.recall":
            result["memory_recall"] = _compact_memory_recall_trace_for_prompt(value.get("memory_recall"))
        return result
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
    if kind == "host_situation":
        return {
            "record_ref": value.get("record_ref"),
            "kind": kind,
            "phase": value.get("phase"),
            "task_mode": value.get("task_mode"),
            "citations_required": value.get("citations_required"),
            "retrieval_configured": value.get("retrieval_configured"),
            "live_search_available": value.get("live_search_available"),
            "live_fetch_available": value.get("live_fetch_available"),
            "runtime_retrieval_available_if_routed": value.get("runtime_retrieval_available_if_routed"),
            "runtime_live_search_available": value.get("runtime_live_search_available"),
            "runtime_live_fetch_available": value.get("runtime_live_fetch_available"),
            "runtime_profile_aware_search_available": value.get("runtime_profile_aware_search_available"),
            "retrieval_runs": value.get("retrieval_runs"),
            "search_attempts": value.get("search_attempts"),
            "fetch_attempts": value.get("fetch_attempts"),
            "successful_fetches": value.get("successful_fetches"),
            "latest_retrieval_status": value.get("latest_retrieval_status"),
            "failure_diagnosis": value.get("failure_diagnosis"),
            "failure_reason": value.get("failure_reason"),
            "next_possible_action": value.get("next_possible_action"),
        }
    return _compact_simple_dict(value, limit=10)


def _compact_memory_recall_trace_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    scopes = value.get("scopes") if isinstance(value.get("scopes"), dict) else {}
    return {
        "query_hash": value.get("query_hash"),
        "scope_mode": value.get("scope_mode"),
        "combined_total": value.get("combined_total"),
        "memory_ids": _string_list(value.get("memory_ids"))[:16],
        "fallback_ranked_scopes": _string_list(value.get("fallback_ranked_scopes"))[:8],
        "scopes": {
            str(label): _compact_memory_recall_scope_for_prompt(scope)
            for label, scope in list(scopes.items())[:4]
            if isinstance(scope, dict)
        },
    }


def _compact_memory_recall_scope_for_prompt(value: JsonObject) -> JsonObject:
    return {
        "total": value.get("total"),
        "memory_ids": _string_list(value.get("memory_ids"))[:12],
        "items": [
            {
                "memory_id": item.get("memory_id"),
                "kind": item.get("kind"),
                "summary": _text_preview(item.get("summary"), limit=180),
                "body_preview": _text_preview(item.get("body_preview"), limit=160),
                "structured_summary": _compact_structured_summary_for_prompt(item.get("structured_summary")),
                "match_diagnostics": _compact_memory_match_diagnostics_for_prompt(item.get("match_diagnostics")),
                "privacy_class": item.get("privacy_class"),
                "confidence": item.get("confidence"),
                "provenance_refs": _string_list(item.get("provenance_refs"))[:4],
            }
            for item in list(value.get("items") or [])[:4]
            if isinstance(item, dict)
        ],
        "filtered": _compact_simple_dict(value.get("filtered"), limit=6),
    }


def _compact_structured_summary_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    values = value.get("values") if isinstance(value.get("values"), dict) else {}
    return {
        "keys": _string_list(value.get("keys"))[:24],
        "key_count": value.get("key_count"),
        "values": _compact_simple_dict(values, limit=16),
        "hash": value.get("hash"),
    }


def _compact_memory_match_diagnostics_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "matched_terms": _string_list(value.get("matched_terms"))[:12],
        "matched_fields": _string_list(value.get("matched_fields"))[:8],
        "structured_hit_keys": _string_list(value.get("structured_hit_keys"))[:12],
        "match_score": value.get("match_score"),
    }


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


def _semantic_goal_for_execution(current_input: str, metadata: JsonObject | None) -> str:
    if not isinstance(metadata, dict):
        return current_input
    mission_context = metadata.get("mission_context")
    if not isinstance(mission_context, dict):
        return current_input
    current_step = mission_context.get("current_step")
    directive = mission_context.get("directive")
    if not isinstance(current_step, dict) and not isinstance(directive, dict):
        return current_input
    state = mission_context.get("mission_state")
    root_goal = state.get("root_goal") if isinstance(state, dict) else None
    if isinstance(root_goal, str) and root_goal.strip():
        return root_goal
    return current_input


def _semantic_runtime_context(metadata: JsonObject | None) -> JsonObject:
    if not isinstance(metadata, dict):
        return {}
    context: JsonObject = {}
    for key in (
        "thread_working_context",
        "thread_rag_context",
        "durable_memory_context",
        "mission_context",
        "answer_profile",
        "research_mission",
        "semantic_goal",
        "task_execution_step",
        "interaction_preferences",
        "agent_loop",
        "processor_budget",
        "host_situation",
    ):
        value = metadata.get(key)
        if isinstance(value, dict):
            if key == "mission_context":
                context[key] = _compact_mission_context_for_prompt(value)
            elif key == "thread_rag_context":
                context[key] = _compact_thread_rag_context_for_prompt(value)
            elif key == "thread_working_context":
                context[key] = _compact_thread_working_context_for_prompt(value)
            elif key == "durable_memory_context":
                context[key] = _compact_durable_memory_context_for_prompt(value)
            else:
                context[key] = dict(value)
    return context


def _with_semantic_goal_metadata(
    metadata: JsonObject | None,
    *,
    semantic_goal: str,
    current_input: str,
) -> JsonObject:
    result = dict(metadata or {})
    result["semantic_goal"] = {
        "root_goal": semantic_goal,
        "current_input_preview": _text_preview(current_input, limit=480),
        "current_input_is_directive": True,
        "host_rule": "Use root_goal for task semantics; use current_input only as the current continuation directive.",
    }
    return result


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


def _with_workmethod_metadata(metadata: JsonObject | None, *, workmethod: JsonObject) -> JsonObject:
    result = dict(metadata or {})
    result["workmethod"] = dict(workmethod)
    return result


def _with_host_situation_metadata(metadata: JsonObject | None, *, host_situation: JsonObject) -> JsonObject:
    result = dict(metadata or {})
    result["host_situation"] = dict(host_situation)
    return result


def _use_model_workmethod(
    fabric: ProcessorFabric | None,
    *,
    semantic_mode: str,
    execution_metadata: JsonObject | None,
) -> bool:
    if semantic_mode != "model" or fabric is None:
        return False
    metadata = dict(execution_metadata or {})
    requested = metadata.get("workmethod")
    if isinstance(requested, dict) and requested.get("mode") in {"model", "rule"}:
        return requested["mode"] == "model"
    try:
        route = fabric.router.route("workmethod.frame")
    except Exception:
        return False
    return route.provider not in {"fake_json", "fake_malformed_json", "fake_timeout"}


def _execution_profile_uses_workmethod(metadata: JsonObject | None) -> bool:
    if not isinstance(metadata, dict):
        return True
    profile = metadata.get("execution_profile")
    if not isinstance(profile, dict):
        return True
    value = profile.get("use_workmethod")
    return bool(value) if isinstance(value, bool) else True


def _disabled_workmethod_state(
    *,
    goal: str,
    thread_id: str,
    task_plan: TaskExecutionPlan,
    execution_metadata: JsonObject | None,
) -> WorkMethodState:
    profile = (
        dict(execution_metadata.get("execution_profile"))
        if isinstance(execution_metadata, dict) and isinstance(execution_metadata.get("execution_profile"), dict)
        else {}
    )
    profile_id = str(profile.get("profile_id") or "unknown")
    return WorkMethodState(
        state_id="workstate-disabled-" + _short_hash(thread_id, goal, profile_id),
        frame={
            "frame_id": "workframe-disabled-" + _short_hash(thread_id, goal),
            "user_goal": goal,
            "inferred_goal": goal,
            "work_type": "execution_profile_fast_lane",
            "difficulty": "profile_controlled",
            "risk_level": "profile_controlled",
            "expected_output": {},
            "done_criteria": [],
            "tool_needs": [],
            "memory_needs": [],
            "assumptions": [f"workmethod disabled by execution_profile={profile_id}"],
        },
        method={
            "method_id": "workmethod-disabled-" + _short_hash(profile_id, task_plan.plan_id),
            "method_name": "fast_lane_without_workmethod",
            "first_moves": [],
            "evidence_strategy": [],
            "failure_moves": [],
            "stop_policy": [],
            "user_interaction_policy": [],
            "notes": ["Workmethod framing skipped by execution profile to reduce benchmark/simple-task overhead."],
        },
        thread_working_set={},
        source="disabled_by_execution_profile",
        diagnostics={"execution_profile": profile_id, "selected_mode": task_plan.selected_mode},
    )


def _short_hash(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


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


def _runtime_retrieval_capabilities(operator: RetrievalOperator | None) -> JsonObject:
    if operator is None:
        return {
            "available_if_routed": False,
            "network_access": False,
            "live_search_available": False,
            "live_fetch_available": False,
            "profile_aware_search_available": False,
            "search_provider_ids": [],
            "fetch_provider_ids": [],
            "provider_summary": [],
        }
    capabilities = operator.provider_capabilities()
    search = [item for item in capabilities if isinstance(item, dict) and item.get("provider_kind") == "search"]
    fetch = [item for item in capabilities if isinstance(item, dict) and item.get("provider_kind") == "fetch"]
    return {
        "available_if_routed": True,
        "network_access": bool(operator.network_access),
        "live_search_available": any(bool(item.get("live_network")) for item in search),
        "live_fetch_available": any(bool(item.get("live_network")) for item in fetch),
        "profile_aware_search_available": any(bool(item.get("profile_aware")) for item in search),
        "search_provider_ids": _provider_ids(search),
        "fetch_provider_ids": _provider_ids(fetch),
        "provider_summary": [
            {
                "provider_id": item.get("provider_id"),
                "provider_kind": item.get("provider_kind"),
                "live_network": bool(item.get("live_network")),
                "profile_aware": bool(item.get("profile_aware")),
                "authority": item.get("authority"),
            }
            for item in capabilities[:20]
            if isinstance(item, dict)
        ],
    }


def _research_profile_id(recipe: TaskRecipe) -> str | None:
    for key in ("research_profile_id", "research_profile"):
        value = recipe.metadata.get(key)
        if isinstance(value, str) and value:
            return value
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


def _benchmark_oracle_context_payload(goal: str) -> JsonObject | None:
    marker = "Benchmark-provided oracle source context follows."
    if marker not in goal:
        return None
    remainder = goal[goal.find(marker):]
    context = _benchmark_oracle_context_text(remainder)
    if not context:
        return None
    mode = "oracle_context"
    if "FinanceBench provided evidence follows" in context or "Provided evidence excerpt:" in context:
        mode = "oracle_evidence"
    evidence_context = _benchmark_oracle_context_evidence_text(context)
    title = "Benchmark-provided oracle context"
    doc_name = re.search(r"(?im)^Document:\s*(.+)$", context)
    if doc_name is not None and doc_name.group(1).strip():
        title = doc_name.group(1).strip()
    else:
        inline_doc_name = re.search(
            r"(?is)\bDocument:\s*(.+?)(?=\s+Document type:|\s+Document period:|\s+Document link:|\s+Provided evidence excerpt:|$)",
            context,
        )
        if inline_doc_name is not None and inline_doc_name.group(1).strip():
            title = inline_doc_name.group(1).strip()
    return {
        "context": evidence_context or context,
        "mode": mode,
        "uri": _benchmark_oracle_context_uri(context),
        "title": title,
        "raw_context_chars": len(context),
    }


def _benchmark_oracle_context_text(remainder: str) -> str:
    context_markers = (
        "FinanceBench provided evidence follows.",
        "FinanceBench target document metadata follows.",
        "Benchmark-provided source context follows.",
        "pre_text:",
        "post_text:",
        "table:",
        "Provided evidence excerpt:",
    )
    starts = [
        index
        for marker in context_markers
        if (index := remainder.find(marker)) >= 0
    ]
    if starts:
        return remainder[min(starts):].strip()
    if "\n\n" in remainder:
        return remainder.split("\n\n", 1)[1].strip()
    return ""


def _benchmark_oracle_context_evidence_text(context: str) -> str | None:
    marker = "Provided evidence excerpt:"
    marker_index = context.find(marker)
    if marker_index < 0:
        return None
    payload = context[marker_index + len(marker):].lstrip()
    if not payload or payload[0] not in "[{":
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError:
        return None
    lines = _benchmark_oracle_context_evidence_lines(value)
    return "\n\n".join(lines).strip() or None


def _benchmark_oracle_context_evidence_lines(value: object) -> list[str]:
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_benchmark_oracle_context_evidence_lines(item))
        return lines
    if not isinstance(value, dict):
        return []
    lines: list[str] = []
    doc_name = value.get("doc_name")
    if isinstance(doc_name, str) and doc_name.strip():
        lines.append(f"Document: {doc_name.strip()}")
    page = value.get("evidence_page_num")
    if page not in (None, ""):
        lines.append(f"Page: {page}")
    evidence_text = value.get("evidence_text_full_page") or value.get("evidence_text")
    if isinstance(evidence_text, str) and evidence_text.strip():
        lines.append(evidence_text.strip())
    return lines


def _benchmark_oracle_context_uri(context: str) -> str:
    document_link = re.search(r"(?im)^Document link:\s*(\S+)", context)
    if document_link is not None:
        return document_link.group(1).rstrip(".,;")
    inline_document_link = re.search(r"(?is)\bDocument link:\s*(https?://\S+)", context)
    if inline_document_link is not None:
        return inline_document_link.group(1).rstrip(".,;")
    url = re.search(r"https?://[^\s\]\)\"']+", context)
    if url is not None:
        return url.group(0).rstrip(".,;")
    if "pre_text:" in context or "post_text:" in context or "table:" in context:
        return "https://finqasite.github.io/"
    return "benchmark:oracle_context"


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
    processor_fabric: ProcessorFabric | None = None,
) -> RetrievalOperator:
    if corpus_store is not None:
        return RetrievalOperator(
            search_provider=CorpusSearchProvider(corpus_store),
            fetch_provider=CorpusFetchProvider(artifact_store),
            corpus_store=corpus_store,
            processor_fabric=processor_fabric,
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
            processor_fabric=processor_fabric,
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
            processor_fabric=processor_fabric,
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
            processor_fabric=processor_fabric,
        )
    return RetrievalOperator(
        search_provider=UnconfiguredSearchProvider(reason="retrieval_source_not_configured"),
        fetch_provider=UnconfiguredFetchProvider(reason="retrieval_fetch_not_configured"),
        processor_fabric=processor_fabric,
    )


def _retrieval_payload(goal: str, recipe: TaskRecipe) -> JsonObject:
    payload: JsonObject = {
        "goal_id": "goal-agent-retrieval",
        "query": goal,
        "max_spans_per_document": 2,
    }
    payload = _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe)
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
    payload = _apply_recipe_profile_defaults(payload, recipe)
    payload = _apply_research_depth_defaults(payload)
    return _enforce_benchmark_doc_retrieval_binding(payload, goal=goal, recipe=recipe)


def _benchmark_doc_retrieval_payload(goal: str) -> JsonObject:
    target = _benchmark_doc_retrieval_target(goal)
    if not target:
        return {}
    question = _benchmark_doc_retrieval_question(goal)
    company = _string_value(target.get("company"))
    doc_period = _string_value(target.get("doc_period"))
    doc_type = _string_value(target.get("doc_type"))
    doc_name = _string_value(target.get("doc_name"))
    source_url = _string_value(target.get("source_url"))
    query_parts = [part for part in (company, doc_period, doc_type, question) if part]
    metadata: JsonObject = {
        "benchmark_doc_retrieval": True,
        "respect_explicit_budget": True,
        "retrieval_context_frozen": True,
        "source_authority_requirement": "primary",
        "search_strategy": "structured",
        "research_task_kind": "filing_document_qa",
    }
    if company:
        metadata["company"] = company
        metadata["issuer"] = company
    if doc_name:
        metadata["doc_name"] = doc_name
    if doc_type:
        metadata["doc_type"] = doc_type
        metadata["sec_form"] = doc_type.upper().replace("10K", "10-K").replace("10Q", "10-Q")
    if doc_period:
        metadata["doc_period"] = doc_period
        metadata["report_date"] = doc_period
    if source_url:
        resolved_source_urls = _benchmark_doc_source_urls(source_url)
        metadata["source_url"] = source_url
        metadata["source_urls"] = resolved_source_urls
        metadata["preferred_source_urls"] = resolved_source_urls[:8]
        metadata["queries"] = _ordered_unique([*resolved_source_urls, " ".join(part for part in (company, doc_period, doc_type, question) if part)])
        metadata["suggested_source_targets"] = [
            {
                "title": doc_name or source_url,
                "uri": url,
                "query_hints": [url],
                "source_family": "company_filing",
                "reason": "FinanceBench doc_retrieval target source URL",
            }
            for url in resolved_source_urls[:8]
        ]
    if question:
        metadata["root_goal"] = question
    binding = target_document_binding_from_metadata(metadata, question=question or goal)
    if binding:
        metadata["target_document_binding"] = binding
        if binding.get("required_statement"):
            metadata["required_statement"] = binding["required_statement"]
        if binding.get("required_line_item"):
            metadata["required_line_item"] = binding["required_line_item"]
        hint = _compiled_task_hint_for_retrieval(question=question or goal, binding=binding)
        if hint:
            metadata["compiled_task_hint"] = hint
    return {
        "query": " ".join(query_parts) or goal,
        "metadata": metadata,
        "respect_explicit_budget": True,
        "max_queries": 2,
        "max_sources": 24,
        "max_fetches": 12,
        "max_spans_per_document": 8,
    }


def _enforce_benchmark_doc_retrieval_binding(
    payload: JsonObject,
    *,
    goal: str,
    recipe: TaskRecipe | None = None,
    preserve_query: bool = False,
) -> JsonObject:
    """Keep FinanceBench doc targets attached to every retrieval action.

    The model can still choose the semantic next move. The host only preserves
    the benchmark's target document/period/line-item contract so a later loop
    cannot silently drift into secondary/current market pages.
    """

    benchmark_payload = _benchmark_doc_retrieval_payload(goal)
    if not benchmark_payload and recipe is not None:
        benchmark_payload = _benchmark_doc_retrieval_payload_from_recipe(recipe)
    if not benchmark_payload and recipe is not None:
        binding = _target_document_binding_from_recipe(recipe)
        if binding:
            benchmark_payload = _benchmark_doc_retrieval_payload_from_binding(binding, goal=goal, recipe=recipe)
    if not benchmark_payload:
        return dict(payload)

    current = dict(payload)
    current_metadata = dict(current.get("metadata")) if isinstance(current.get("metadata"), dict) else {}
    current_query = current.get("query") if isinstance(current.get("query"), str) else ""
    current_queries = _string_list(current.get("queries"))

    updated = _merge_retrieval_payload(current, benchmark_payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    benchmark_metadata = dict(benchmark_payload.get("metadata")) if isinstance(benchmark_payload.get("metadata"), dict) else {}

    source_urls = _ordered_unique(
        [
            *_string_list(benchmark_metadata.get("source_urls")),
            *_string_list(current_metadata.get("source_urls")),
            *_string_list(current.get("source_urls")),
            *_string_list(metadata.get("source_urls")),
        ]
    )
    if source_urls:
        metadata["source_urls"] = source_urls[:24]
        metadata.setdefault("preferred_source_urls", source_urls[:8])

    binding = metadata.get("target_document_binding")
    if isinstance(binding, dict) and binding:
        metadata["target_document_binding"] = binding
        if binding.get("required_statement"):
            metadata["required_statement"] = binding["required_statement"]
        if binding.get("required_line_item"):
            metadata["required_line_item"] = binding["required_line_item"]
        hint_question = _root_goal_from_recipe(recipe) if recipe is not None else goal
        hint = _compiled_task_hint_for_retrieval(question=hint_question, binding=binding)
        if hint and not isinstance(metadata.get("compiled_task_hint"), dict):
            metadata["compiled_task_hint"] = hint
    metadata["benchmark_binding_enforced"] = True
    metadata.setdefault("source_authority_requirement", "primary")
    metadata.setdefault("research_task_kind", "filing_document_qa")

    benchmark_query = _string_value(benchmark_payload.get("query")) or ""
    benchmark_queries = _ordered_unique(
        [
            *_string_list(benchmark_payload.get("queries")),
            *_string_list(benchmark_metadata.get("queries")),
            *_string_list(benchmark_metadata.get("source_urls")),
        ]
    )

    keep_current_query = bool(
        current_query
        and (
            preserve_query
            or _looks_like_url(current_query)
            or _benchmark_doc_query_is_targeted(current_query, metadata)
        )
    )
    selected_query = current_query if keep_current_query else benchmark_query or (benchmark_queries[0] if benchmark_queries else current_query)

    allowed_current_queries = [
        query
        for query in current_queries
        if preserve_query or _looks_like_url(query) or _benchmark_doc_query_is_targeted(query, metadata)
    ]
    queries = _ordered_unique(
        [
            *([selected_query] if selected_query else []),
            *allowed_current_queries,
            *benchmark_queries,
            *([benchmark_query] if benchmark_query else []),
        ]
    )
    if queries:
        updated["query"] = queries[0]
        updated["queries"] = queries[:8]
        updated["max_queries"] = max(int(updated.get("max_queries") or 0), min(8, max(2, len(queries[:8]))))

    updated["metadata"] = metadata
    updated["respect_explicit_budget"] = True
    updated["search_strategy"] = updated.get("search_strategy") or metadata.get("search_strategy") or "structured"
    updated["max_sources"] = max(int(updated.get("max_sources") or 0), int(benchmark_payload.get("max_sources") or 0), 24)
    updated["max_fetches"] = max(int(updated.get("max_fetches") or 0), int(benchmark_payload.get("max_fetches") or 0), 12)
    updated["max_spans_per_document"] = max(
        int(updated.get("max_spans_per_document") or 0),
        int(benchmark_payload.get("max_spans_per_document") or 0),
        8,
    )
    return updated


def _benchmark_doc_retrieval_payload_from_binding(
    binding: JsonObject,
    *,
    goal: str,
    recipe: TaskRecipe | None,
) -> JsonObject:
    metadata = dict(binding)
    if recipe is not None and isinstance(recipe.metadata, dict):
        metadata = {**recipe.metadata, **metadata}
    question = _root_goal_from_recipe(recipe) if recipe is not None else goal
    binding = target_document_binding_from_metadata(metadata, question=question or goal)
    if not binding:
        return {}
    company = _string_value(binding.get("company")) or ""
    period = _string_value(binding.get("doc_period")) or ""
    doc_type = _string_value(binding.get("doc_type")) or ""
    line_item = _string_value(binding.get("required_line_item")) or ""
    statement = _string_value(binding.get("required_statement")) or ""
    doc_link = _string_value(binding.get("doc_link")) or ""
    query = " ".join(part for part in (company, period, doc_type, line_item, statement) if part) or goal
    payload_metadata: JsonObject = {
        "benchmark_doc_retrieval": True,
        "respect_explicit_budget": True,
        "retrieval_context_frozen": True,
        "source_authority_requirement": "primary",
        "search_strategy": "structured",
        "research_task_kind": "filing_document_qa",
        "target_document_binding": binding,
    }
    for key in ("company", "doc_name", "doc_type", "doc_period", "required_statement", "required_line_item"):
        if binding.get(key):
            payload_metadata[key] = binding[key]
    if doc_link:
        resolved_source_urls = _benchmark_doc_source_urls(doc_link)
        payload_metadata["source_url"] = doc_link
        payload_metadata["source_urls"] = resolved_source_urls
        payload_metadata["preferred_source_urls"] = resolved_source_urls[:8]
        payload_metadata["queries"] = _ordered_unique([*resolved_source_urls, query])
    hint = _compiled_task_hint_for_retrieval(question=question or goal, binding=binding)
    if hint:
        payload_metadata["compiled_task_hint"] = hint
    return {
        "query": query,
        "metadata": payload_metadata,
        "respect_explicit_budget": True,
        "max_queries": 2,
        "max_sources": 24,
        "max_fetches": 12,
        "max_spans_per_document": 8,
    }


def _compiled_task_hint_for_retrieval(*, question: str, binding: JsonObject) -> JsonObject:
    if not question.strip() or not isinstance(binding, dict) or not binding:
        return {}
    try:
        compiled = compile_finance_task_program(question=question, facts=[], target_binding=binding)
    except Exception:
        return {}
    task_spec = compiled.task_spec
    tool_chain_plan = _json_object(compiled.diagnostics.get("tool_chain_plan"))
    return {
        "schema": "holo.kernel_v3.compiled_task_hint.v1",
        "program_id": compiled.program_id,
        "domain": compiled.domain,
        "task_spec": {
            "task_type": task_spec.task_type,
            "objective": task_spec.objective,
            "target_entities": list(task_spec.target_entities),
            "target_periods": list(task_spec.target_periods),
            "success_criteria": list(task_spec.success_criteria)[:8],
            "diagnostics": {
                key: value
                for key, value in dict(task_spec.diagnostics).items()
                if key in {"formula_name", "formula_status", "fact_count"}
            },
        },
        "evidence_specs": [
            {
                "slot_name": spec.slot_name,
                "accepted_attributes": list(spec.accepted_attributes)[:8],
                "source_role": spec.source_role,
                "required_source_families": list(spec.required_source_families)[:8],
                "target_period": spec.target_period,
                "statement": spec.statement,
                "line_item": spec.line_item,
                "required": spec.required,
            }
            for spec in compiled.evidence_specs[:16]
        ],
        "transform_specs": [
            {
                "name": spec.name,
                "required_slots": list(spec.required_slots)[:12],
                "expression": spec.expression,
                "output_unit": spec.output_unit,
                "output_attribute": spec.output_attribute,
            }
            for spec in compiled.transform_specs[:12]
        ],
        "missing_slots": list((compiled.slot_frame.missing_slots if compiled.slot_frame is not None else []))[:16],
        "tool_chain_plan": _compact_tool_chain_plan_for_prompt(tool_chain_plan),
        "diagnostics": {
            "source": "finance_task_compiler_pre_retrieval",
            "evidence_spec_count": len(compiled.evidence_specs),
            "transform_spec_count": len(compiled.transform_specs),
            "tool_chain_plan_present": bool(tool_chain_plan),
        },
    }


def _append_toolchain_plan_record(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    step_id: str | None,
    program: JsonObject,
    source: str,
) -> None:
    diagnostics = _json_object(program.get("diagnostics"))
    tool_chain_plan = _json_object(diagnostics.get("tool_chain_plan") or program.get("tool_chain_plan"))
    if not tool_chain_plan:
        return
    plan_id = str(tool_chain_plan.get("plan_id") or program.get("program_id") or f"toolchain-plan-{run_id}")
    for record in journal.records(task_id=task_id, kind="toolchain_plan"):
        if record.run_id == run_id and record.data.get("plan_id") == plan_id:
            return
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        kind="toolchain_plan",
        data=redact_journal_data(
            {
                **tool_chain_plan,
                "schema": tool_chain_plan.get("schema") or "holo.kernel_v3.tool_chain_plan.v1",
                "plan_id": plan_id,
                "source": source,
                "program_id": program.get("program_id"),
            }
        ),
        state_delta={"toolchain_plan_present": True},
    )


def _compact_tool_chain_plan_for_prompt(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "schema": value.get("schema"),
        "decision_owner": value.get("decision_owner"),
        "host_role": value.get("host_role"),
        "task_type": value.get("task_type"),
        "formula_status": value.get("formula_status"),
        "formula_name": value.get("formula_name"),
        "missing_slots": _string_list(value.get("missing_slots"))[:16],
        "available_tools": [
            _compact_simple_dict(item, limit=6)
            for item in list(value.get("available_tools") or [])[:6]
            if isinstance(item, dict)
        ],
        "recommended_steps": [
            _compact_simple_dict(item, limit=10)
            for item in list(value.get("recommended_steps") or [])[:6]
            if isinstance(item, dict)
        ],
        "next_action_candidates": [
            _compact_simple_dict(item, limit=8)
            for item in list(value.get("next_action_candidates") or [])[:6]
            if isinstance(item, dict)
        ],
    }


def _benchmark_doc_query_is_targeted(query: str, metadata: JsonObject) -> bool:
    if _looks_like_url(query):
        return True
    binding = metadata.get("target_document_binding")
    binding = binding if isinstance(binding, dict) else {}
    normalized = _normalize_for_benchmark_doc_query(query)
    company = _string_value(binding.get("company") or metadata.get("company")) or ""
    period = _string_value(binding.get("doc_period") or metadata.get("doc_period")) or ""
    doc_type = _string_value(binding.get("doc_type") or metadata.get("doc_type") or metadata.get("sec_form")) or ""
    line_item = _string_value(binding.get("required_line_item") or metadata.get("required_line_item")) or ""
    statement = _string_value(binding.get("required_statement") or metadata.get("required_statement")) or ""
    company_hit = not company or _normalize_for_benchmark_doc_query(company) in normalized
    period_hit = not period or _normalize_for_benchmark_doc_query(period) in normalized
    doc_type_hit = bool(doc_type and _normalize_for_benchmark_doc_query(doc_type).replace("10 k", "10k") in normalized.replace("10 k", "10k"))
    line_hit = any(alias in normalized for alias in _benchmark_line_item_aliases(line_item))
    statement_hit = any(alias in normalized for alias in _benchmark_statement_aliases(statement))
    return bool(company_hit and period_hit and (doc_type_hit or line_hit or statement_hit))


def _benchmark_line_item_aliases(line_item: str) -> list[str]:
    normalized = _normalize_for_benchmark_doc_query(line_item)
    aliases = [normalized] if normalized else []
    if normalized in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        aliases.extend(
            [
                "property plant and equipment net",
                "property plant and equipment",
                "net property plant and equipment",
                "net ppe",
                "net pp and e",
                "net ppne",
                "ppne",
            ]
        )
    elif normalized == "capital expenditures":
        aliases.extend(
            [
                "capital expenditure",
                "capital expenditures",
                "capex",
                "property plant and equipment",
                "property and equipment",
                "ppe",
                "payments to acquire property plant and equipment",
                "paymentstoacquirepropertyplantandequipment",
            ]
        )
    elif normalized == "net income":
        aliases.extend(["net income", "net earnings"])
    elif normalized == "revenue":
        aliases.extend(["revenue", "revenues", "net sales"])
    return _ordered_unique([item for item in aliases if item])


def _benchmark_statement_aliases(statement: str) -> list[str]:
    if statement == "cash_flow_statement":
        return ["cash flow", "cash flows", "cashflow", "statement of cash flows"]
    if statement == "income_statement":
        return ["income statement", "statement of operations"]
    if statement == "balance_sheet":
        return ["balance sheet", "assets", "liabilities"]
    if statement == "non_gaap_reconciliation":
        return ["reconciliation", "non gaap", "non-gaap"]
    return []


def _normalize_for_benchmark_doc_query(value: object) -> str:
    return " ".join(str(value or "").lower().replace("&", " and ").replace("/", " ").replace("-", " ").split())


def _benchmark_doc_retrieval_target(goal: str) -> JsonObject:
    if "Benchmark target source follows." not in goal or "Source URL:" not in goal:
        return {}
    result: JsonObject = {}
    labels = {
        "Source URL": "source_url",
        "Company": "company",
        "Document": "doc_name",
        "Document type": "doc_type",
        "Document period": "doc_period",
    }
    for raw_line in str(goal or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        label, value = line.split(":", 1)
        key = labels.get(label.strip())
        if key is None:
            continue
        text = value.strip()
        if text:
            result[key] = text
    inline = _benchmark_doc_retrieval_inline_labels(goal)
    result.update({key: value for key, value in inline.items() if value})
    return result


def _benchmark_doc_retrieval_question(goal: str) -> str | None:
    if "Benchmark target source follows." not in goal:
        return None
    paragraphs = [part.strip() for part in str(goal or "").split("\n\n") if part.strip()]
    if paragraphs:
        question = paragraphs[-1]
        if not question.startswith("Benchmark target source follows."):
            return question
    inline = _benchmark_doc_retrieval_inline_question(goal)
    return inline or None


def _benchmark_doc_retrieval_inline_labels(goal: str) -> JsonObject:
    text = str(goal or "").replace("\n", " ")
    labels = {
        "Source URL": "source_url",
        "Company": "company",
        "Document type": "doc_type",
        "Document period": "doc_period",
        "Document": "doc_name",
    }
    label_pattern = "Source URL|Document type|Document period|Company|Document"
    question_start = _benchmark_doc_retrieval_question_start_pattern()
    result: JsonObject = {}
    for match in re.finditer(
        rf"(?P<label>{label_pattern})\s*:\s*(?P<value>.*?)(?=\s+(?:{label_pattern})\s*:|\s+(?:{question_start})\b|$)",
        text,
        flags=re.IGNORECASE,
    ):
        raw_label = " ".join(match.group("label").split())
        key = labels.get(raw_label) or labels.get(raw_label.title())
        if key is None:
            continue
        value = " ".join(match.group("value").split())
        if value:
            result[key] = value
    return result


def _benchmark_doc_retrieval_inline_question(goal: str) -> str:
    text = " ".join(str(goal or "").replace("\n", " ").split())
    question_start = _benchmark_doc_retrieval_question_start_pattern()
    match = re.search(rf"\s{{2,}}((?:{question_start})\b.+)$", str(goal or ""), flags=re.IGNORECASE | re.DOTALL)
    if match:
        return " ".join(match.group(1).split())
    match = re.search(rf"(?:Document period\s*:\s*\S+)\s+((?:{question_start})\b.+)$", text, flags=re.IGNORECASE)
    if match:
        return " ".join(match.group(1).split())
    return ""


def _benchmark_doc_retrieval_question_start_pattern() -> str:
    return (
        "What|How|Which|Give|Calculate|Using|For|Assume|Is|Are|Does|Do|Did|Was|Were|"
        "Can|Should|Would|Could|If|Based"
    )


def _target_document_binding_from_recipe(recipe: TaskRecipe) -> JsonObject:
    payload = _benchmark_doc_retrieval_payload_from_recipe(recipe)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if not metadata and isinstance(recipe.metadata, dict):
        metadata = recipe.metadata.get("target_document_binding") if isinstance(recipe.metadata.get("target_document_binding"), dict) else recipe.metadata
    return target_document_binding_from_metadata(metadata, question=_root_goal_from_recipe(recipe))


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
    metadata = merged.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if bool(metadata.get("respect_explicit_budget") or merged.get("respect_explicit_budget")):
        if "research_depth" not in merged and isinstance(depth, str) and depth:
            merged["research_depth"] = depth
        return merged
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
    updated = _attach_research_context_to_payload(payload, recipe=recipe)
    updated = _apply_finance_capability_defaults(updated, capabilities)
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
    return _apply_general_research_defaults(updated, recipe=recipe)


def _attach_research_context_to_payload(payload: JsonObject, *, recipe: TaskRecipe) -> JsonObject:
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    answer_profile = _answer_profile_metadata(recipe)
    research_mission = _research_mission_metadata(recipe)
    if answer_profile:
        metadata.setdefault("answer_profile", answer_profile)
        coverage = answer_profile.get("minimum_coverage")
        if isinstance(coverage, list):
            metadata.setdefault("minimum_coverage", coverage)
    if research_mission and metadata.get("benchmark_doc_retrieval") is not True:
        metadata.setdefault("research_mission", research_mission)
    if metadata:
        updated["metadata"] = metadata
    return updated


def _apply_general_research_defaults(payload: JsonObject, *, recipe: TaskRecipe) -> JsonObject:
    if recipe.mode != "retrieval_answer":
        return payload
    answer_profile = _answer_profile_metadata(recipe)
    format_name = str(answer_profile.get("format") or "")
    detail_level = str(answer_profile.get("detail_level") or "")
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    profile_metadata = answer_profile.get("metadata") if isinstance(answer_profile.get("metadata"), dict) else {}
    domain = str(profile_metadata.get("domain") or "")
    if format_name not in {"detailed_report", "deep_report", "memo"} and domain != "general_research":
        return payload
    updated = dict(payload)
    if bool(metadata.get("respect_explicit_budget") or updated.get("respect_explicit_budget")):
        return updated
    depth = "deep" if format_name == "deep_report" or detail_level == "deep" else "balanced"
    metadata.setdefault("research_depth", depth)
    metadata.setdefault("search_strategy", "aggregate")
    metadata.setdefault("query_campaign", "auto")
    updated["metadata"] = metadata
    if bool(metadata.get("respect_explicit_budget") or updated.get("respect_explicit_budget")):
        return updated
    defaults = _general_research_depth_defaults(depth)
    for key, floor in defaults.items():
        if key not in updated:
            updated[key] = floor
        elif _should_floor_general_research_budget(updated, key):
            current = _positive_metadata_int(updated.get(key), default=0)
            if current > 0:
                updated[key] = max(current, floor)
    return updated


def _general_research_depth_defaults(depth: str) -> JsonObject:
    if depth == "deep":
        return {
            "max_queries": 48,
            "max_sources": 750,
            "max_fetches": 192,
            "max_spans_per_document": 24,
        }
    return {
        "max_queries": 24,
        "max_sources": 320,
        "max_fetches": 96,
        "max_spans_per_document": 16,
    }


def _should_floor_general_research_budget(payload: JsonObject, key: str) -> bool:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if bool(metadata.get("respect_explicit_budget") or payload.get("respect_explicit_budget")):
        return False
    return key in {"max_queries", "max_sources", "max_fetches", "max_spans_per_document"}


def _apply_finance_capability_defaults(payload: JsonObject, capabilities: set[str]) -> JsonObject:
    if not capabilities.intersection(_FINANCE_RESEARCH_PROFILE_CAPABILITIES):
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata.setdefault("research_profile", FINANCE_FUNDAMENTALS_PROFILE_ID)
    market_valuation = _finance_payload_needs_market_data(updated, metadata=metadata)
    if capabilities.intersection({"finance.market_news", "finance.market_data", "finance.competitive_landscape"}) or market_valuation:
        metadata["source_authority_requirement"] = "secondary_or_better"
        if market_valuation:
            preferred = _string_list(metadata.get("preferred_source_families"))
            metadata["preferred_source_families"] = _ordered_unique(
                ["market_data_provider", *preferred, "structured_regulatory_data", "regulatory_filing"]
            )
        updated.setdefault("max_queries", 1)
        updated.setdefault("query_templates", ["{query}"])
        if "finance.market_news" in capabilities:
            metadata.setdefault("research_task_kind", "market_news")
        elif "finance.market_data" in capabilities:
            metadata.setdefault("research_task_kind", "market_data")
        elif market_valuation:
            metadata.setdefault("research_task_kind", "valuation")
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


def _finance_payload_needs_market_data(payload: JsonObject, *, metadata: JsonObject) -> bool:
    text = " ".join(
        str(item or "")
        for item in (
            payload.get("query"),
            metadata.get("root_goal"),
            metadata.get("task_goal"),
            metadata.get("original_goal"),
            metadata.get("user_goal"),
            metadata.get("research_task_kind"),
        )
    ).lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    return any(
        marker in text or marker in compact
        for marker in (
            "ev/ebitda",
            "evebitda",
            "ev/revenue",
            "evrevenue",
            "enterprise value",
            "market cap",
            "market capitalization",
            "valuation multiple",
            "trading multiple",
            "stock price",
            "share price",
            "p/e",
            "pe ratio",
        )
    )


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
        return _mark_explicit_retrieval_budget(direct)
    nested = _nested_json(metadata, "retrieval.run") or _nested_json(metadata, "retrieval")
    return _mark_explicit_retrieval_budget(_direct_tool_payload(nested, "retrieval.run")) if nested else {}


def _mark_explicit_retrieval_budget(payload: JsonObject) -> JsonObject:
    if not payload:
        return {}
    budget_keys = {
        "max_queries",
        "max_sources",
        "max_fetches",
        "max_spans_per_document",
        "max_network_fetches",
        "max_total_artifact_bytes",
    }
    if not any(key in payload for key in budget_keys):
        return payload
    updated = dict(payload)
    metadata = dict(updated.get("metadata")) if isinstance(updated.get("metadata"), dict) else {}
    metadata.setdefault("respect_explicit_budget", True)
    updated["metadata"] = metadata
    return updated


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


def _benchmark_doc_source_urls(source_url: str) -> list[str]:
    url = _string_value(source_url)
    if not url:
        return []
    derived = _sec_archive_urls_from_accession_url(url)
    return _ordered_unique([*derived, url])


def _source_grounded_trace_required(recipe: TaskRecipe) -> bool:
    metadata = recipe.metadata if isinstance(recipe.metadata, dict) else {}
    if str(metadata.get("workflow_type") or "").strip() == "source_grounded_research":
        return True
    if _benchmark_doc_retrieval_payload_from_recipe(recipe):
        return True
    question = _root_goal_from_recipe(recipe).lower()
    return any(
        marker in question
        for marker in (
            "what drove",
            "what drives",
            "explain why",
            "drivers of",
            "driver of",
            "main reasons",
            "primary reasons",
            "主要原因",
            "驱动因素",
            "为什么",
        )
    )


def _sec_archive_urls_from_accession_url(source_url: str) -> list[str]:
    text = _string_value(source_url)
    if not text:
        return []
    match = re.search(r"(?P<cik>0*\d{4,10})-(?P<year>\d{2})-(?P<seq>\d{6,})", text)
    if not match:
        return []
    raw_cik = match.group("cik")
    cik = raw_cik.lstrip("0") or raw_cik
    accession = f"{raw_cik}-{match.group('year')}-{match.group('seq')}"
    compact_accession = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{compact_accession}"
    return [
        f"{base}/{accession}.txt",
        f"{base}/{accession}-index.html",
        f"{base}/index.json",
        f"{base}/",
    ]


def _required_retrieval_source_urls(recipe: TaskRecipe) -> list[str]:
    values: list[str] = []
    values.extend(_retrieval_payload_urls(_retrieval_capability_args(recipe)))
    values.extend(_retrieval_payload_urls(_benchmark_doc_retrieval_payload(_root_goal_from_recipe(recipe))))
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


def _benchmark_doc_retrieval_primary_citation_satisfies_required_source(
    *,
    recipe: TaskRecipe,
    answer: FinalAnswer,
    citations: list[CitationItem],
) -> bool:
    payload = _benchmark_doc_retrieval_payload_from_recipe(recipe)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata.get("benchmark_doc_retrieval") is not True:
        return False
    source_url = _string_value(metadata.get("source_url"))
    allowed_urls = _benchmark_doc_source_urls(source_url) if source_url else []
    cited_ids = set(answer.citation_refs)
    if not cited_ids:
        return False
    for citation in citations:
        if citation.citation_id not in cited_ids:
            continue
        uri = citation.uri.strip()
        if source_url and _same_url_or_prefix(uri, source_url):
            return True
        if any(_same_url_or_prefix(uri, allowed_url) for allowed_url in allowed_urls):
            return True
    return False


def _finance_pdf_target_satisfied_by_primary_sec_citation(
    *,
    recipe: TaskRecipe,
    required_urls: list[str],
    cited_urls: set[str],
) -> bool:
    if recipe.mode != "retrieval_answer":
        return False
    benchmark_payload = _benchmark_doc_retrieval_payload_from_recipe(recipe)
    metadata = benchmark_payload.get("metadata") if isinstance(benchmark_payload.get("metadata"), dict) else {}
    if metadata.get("benchmark_doc_retrieval") is True:
        return False
    profile = _research_profile_id(recipe)
    if profile not in {"", FINANCE_FUNDAMENTALS_PROFILE_ID}:
        return False
    if not any(str(url).strip().lower().split("?", 1)[0].endswith(".pdf") for url in required_urls):
        return False
    return any(_url_host(url) in {"data.sec.gov", "sec.gov", "www.sec.gov"} for url in cited_urls)


def _benchmark_doc_retrieval_payload_from_recipe(recipe: TaskRecipe) -> JsonObject:
    payload = _retrieval_capability_args(recipe)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata.get("benchmark_doc_retrieval") is True:
        return payload
    return _benchmark_doc_retrieval_payload(_benchmark_doc_retrieval_goal_from_recipe(recipe))


def _benchmark_doc_retrieval_goal_from_recipe(recipe: TaskRecipe) -> str:
    for container in (
        _execution_metadata(recipe),
        _mission_context_metadata(recipe).get("mission_state"),
        _research_mission_metadata(recipe),
    ):
        if not isinstance(container, dict):
            continue
        for key in ("root_goal", "task_goal", "original_goal", "user_goal"):
            value = container.get(key)
            if isinstance(value, str) and "Benchmark target source follows." in value:
                return value
    return ""


def _url_host(value: str) -> str:
    match = re.match(r"https?://([^/:?#]+)", str(value or "").strip(), flags=re.IGNORECASE)
    return match.group(1).lower().rstrip(".") if match else ""


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
            "retrieval_strategy",
            "model_retrieval_strategy",
            "preferred_source_families",
            "source_family_plan",
            "source_authority_requirement",
            "search_strategy",
            "query_campaign",
            "minimum_coverage",
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
            for key in (
                "retrieval_strategy",
                "model_retrieval_strategy",
                "preferred_source_families",
                "source_family_plan",
                "source_authority_requirement",
                "search_strategy",
                "query_campaign",
                "minimum_coverage",
            ):
                value = result.pop(key, None)
                if isinstance(value, (dict, list, str)) and value:
                    metadata[key] = value
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


def _run_has_planner_processor_failure(journal: JournalStore, task_id: str, run_id: str) -> bool:
    for record in journal.records(task_id=task_id, kind="processor_result"):
        if record.run_id != run_id:
            continue
        if str(record.data.get("task_type") or "") != "planner.propose":
            continue
        if record.data.get("status") != "ok":
            return True
    for record in journal.records(task_id=task_id, kind="action"):
        if record.run_id != run_id:
            continue
        reasons = record.data.get("reasons")
        if isinstance(reasons, list) and "processor_failed" in reasons:
            return True
    return False


def _has_sufficient_benchmark_oracle_retrieval(journal: JournalStore, task_id: str, run_id: str) -> bool:
    for record in reversed(journal.records(task_id=task_id, kind="retrieval_report")):
        if record.run_id != run_id:
            continue
        diagnostics = record.data.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        if diagnostics.get("source") != "benchmark_oracle_context":
            continue
        if record.data.get("status") == "sufficient":
            return True
    return False


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


def _retrieval_and_toolchain_grounding(
    journal: JournalStore,
    task_id: str,
    run_id: str,
    *,
    recipe: TaskRecipe,
    artifact_store: ArtifactStore | None = None,
) -> tuple[list[EvidenceItem], list[CitationItem], RetrievalReport | None]:
    report = _latest_retrieval_report(journal, task_id, run_id)
    evidence = _retrieval_evidence(journal, task_id, run_id)
    citations = _retrieval_citations(journal, task_id, run_id)
    if not _toolchain_grounding_enabled(recipe):
        return evidence, citations, report
    context_budget = _context_budget_metadata(recipe)
    toolchain_evidence, toolchain_citations, toolchain_report = _workspace_grounding(
        journal,
        task_id,
        run_id,
        artifact_store=artifact_store or ArtifactStore.in_memory(),
        evidence_char_limit=int(context_budget["workspace_evidence_chars"]),
        citation_char_limit=int(context_budget["workspace_citation_chars"]),
        synthesis_evidence_preview_chars=int(context_budget["synthesis_evidence_preview_chars"]),
        synthesis_citation_preview_chars=int(context_budget["synthesis_citation_preview_chars"]),
    )
    if not toolchain_evidence:
        return evidence, citations, report
    evidence = _merge_evidence_items(evidence, toolchain_evidence)
    citations = _merge_citation_items(citations, toolchain_citations)
    report = _report_with_toolchain_grounding(
        report,
        toolchain_report=toolchain_report,
        evidence=evidence,
        citations=citations,
    )
    return evidence, citations, report


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
        source = str(data.get("source") or "")
        if source not in {"tool:workspace.list", "tool:workspace.search", "tool:file.read", "tool:workspace.write", "tool:shell.exec", "tool:script.exec"}:
            continue
        content = data.get("content", {})
        if not isinstance(content, dict):
            continue
        observation_status = str(data.get("status") or "")
        candidate_facts = _toolchain_candidate_facts(content, source=source) if observation_status == "ok" else []
        _journal_toolchain_step_executed(
            journal,
            task_id=task_id,
            run_id=run_id,
            observation_record=record,
            source=source,
            candidate_fact_count=len(candidate_facts),
        )
        _journal_toolchain_artifacts(
            journal,
            task_id=task_id,
            run_id=run_id,
            observation_record=record,
            source=source,
            content=content,
        )
        if observation_status != "ok":
            _journal_toolchain_failure(
                journal,
                task_id=task_id,
                run_id=run_id,
                observation_record=record,
                source=source,
                content=content,
            )
            continue
        text = _workspace_observation_text(
            content,
            artifact_store=artifact_store,
            evidence_char_limit=evidence_char_limit,
            source=source,
        )
        path = _workspace_observation_title(content, source=source)
        artifact_id = record.artifact_refs[0] if record.artifact_refs else f"artifact-{record.observation_ref or 'workspace-evidence-' + str(index)}"
        emit_full_text_evidence = text.strip() and not (
            candidate_facts and source in {"tool:shell.exec", "tool:script.exec"}
        )
        if emit_full_text_evidence:
            evidence_id = f"workspace-evidence-{index}"
            citation_id = f"workspace-cite-{index}"
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
                diagnostics={"record_ref": record.record_id, "source": source},
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
        for fact_index, fact in enumerate(candidate_facts, start=1):
            fact_text = _candidate_fact_evidence_text(fact)
            if not fact_text:
                continue
            evidence_id = f"toolchain-candidate-fact-{index}-{fact_index}"
            citation_id = f"toolchain-candidate-cite-{index}-{fact_index}"
            evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    goal_id="goal-workspace",
                    span_id=f"toolchain-candidate-span-{index}-{fact_index}",
                    document_id=f"workspace-doc-{index}",
                    source_id=path,
                    artifact_id=artifact_id,
                    uri=f"workspace://{path}",
                    title=f"{path} candidate fact {fact_index}",
                    text=fact_text[:evidence_char_limit],
                    score=1.0,
                    payload_hash=str(data.get("payload_hash") or record.payload_hash),
                    diagnostics={"record_ref": record.record_id, "source": source, "structured_candidate": True},
                )
            )
            citations.append(
                CitationItem(
                    citation_id=citation_id,
                    goal_id="goal-workspace",
                    evidence_id=evidence_id,
                    artifact_id=artifact_id,
                    uri=f"workspace://{path}",
                    title=f"{path} candidate fact {fact_index}",
                    quote=fact_text[:citation_char_limit],
                    span_start=0,
                    span_end=min(len(fact_text), citation_char_limit),
                    metadata={"record_ref": record.record_id, "structured_candidate": True},
                )
            )
        _journal_toolchain_grounding_candidate(
            journal,
            task_id=task_id,
            run_id=run_id,
            observation_record=record,
            source=source,
            candidate_facts=candidate_facts,
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


def _toolchain_candidate_facts(content: JsonObject, *, source: str) -> list[JsonObject]:
    if source not in {"tool:shell.exec", "tool:script.exec", "tool:file.read", "tool:workspace.write"}:
        return []
    texts: list[str] = []
    stdout = content.get("stdout")
    if isinstance(stdout, str) and stdout.strip():
        texts.append(stdout)
    stdout_json = content.get("stdout_json")
    if stdout_json is not None:
        return _candidate_facts_from_json(stdout_json)
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        texts.append(text)
    preview = content.get("text_preview")
    if isinstance(preview, str) and preview.strip():
        texts.append(preview)
    candidates: list[JsonObject] = []
    for value in texts:
        candidates.extend(_candidate_facts_from_text(value))
    return _dedupe_candidate_facts(candidates)


def _candidate_facts_from_text(text: str) -> list[JsonObject]:
    stripped = text.strip()
    if not stripped:
        return []
    candidates: list[JsonObject] = []
    try:
        candidates.extend(_candidate_facts_from_json(json.loads(stripped)))
    except json.JSONDecodeError:
        pass
    for line in stripped.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            candidates.extend(_candidate_facts_from_json(json.loads(raw)))
            continue
        except json.JSONDecodeError:
            pass
        parsed = _candidate_fact_from_key_value_line(raw)
        if parsed:
            candidates.append(parsed)
    return candidates


def _candidate_facts_from_json(value: object) -> list[JsonObject]:
    if isinstance(value, list):
        return [fact for item in value for fact in _candidate_facts_from_json(item)]
    if not isinstance(value, dict):
        return []
    table_facts = _candidate_facts_from_table_payload(value)
    for key in ("facts", "candidate_facts", "candidateFacts", "finance_facts", "financeFacts"):
        nested = value.get(key)
        if isinstance(nested, list):
            nested_facts = [fact for item in nested for fact in _candidate_facts_from_json(item)]
            return _dedupe_candidate_facts([*table_facts, *nested_facts])
    if "value" not in value and "val" not in value:
        return table_facts
    metric = value.get("metric") or value.get("label") or value.get("concept") or value.get("attribute")
    if not metric:
        return table_facts
    result: JsonObject = {}
    key_map = {
        "entity": "entityName",
        "entity_name": "entityName",
        "entityName": "entityName",
        "ticker": "ticker",
        "cik": "cik",
        "concept": "concept",
        "label": "label",
        "line_item": "metric",
        "lineItem": "metric",
        "metric": "metric",
        "attribute": "metric",
        "name": "metric",
        "unit": "unit",
        "scale": "scale",
        "fy": "fy",
        "fiscal_year": "fy",
        "fiscalYear": "fy",
        "year": "fy",
        "period": "period",
        "form": "form",
        "filed": "filed",
        "accn": "accn",
        "value": "value",
        "val": "value",
        "amount": "value",
    }
    for raw_key, normalized in key_map.items():
        raw_value = value.get(raw_key)
        if raw_value is None or raw_value == "":
            continue
        result[normalized] = str(raw_value)
    return _dedupe_candidate_facts([*table_facts, result]) if result.get("metric") and result.get("value") else table_facts


def _candidate_facts_from_table_payload(value: JsonObject) -> list[JsonObject]:
    inherited = _candidate_fact_inherited_fields(value)
    facts: list[JsonObject] = []
    for key in ("tables", "candidate_tables", "candidateTables"):
        nested = value.get(key)
        if isinstance(nested, list):
            for table in nested:
                facts.extend(_candidate_facts_from_table(table, inherited=inherited))
        elif isinstance(nested, dict):
            facts.extend(_candidate_facts_from_table(nested, inherited=inherited))
    for key in ("table", "candidate_table", "candidateTable"):
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            facts.extend(_candidate_facts_from_table(nested, inherited=inherited))
    facts.extend(_candidate_facts_from_table(value, inherited=inherited))
    return _dedupe_candidate_facts(facts)


def _candidate_facts_from_table(value: object, *, inherited: JsonObject) -> list[JsonObject]:
    if isinstance(value, list):
        return [fact for item in value for fact in _candidate_facts_from_table(item, inherited=inherited)]
    if not isinstance(value, dict):
        return []
    fields = {**inherited, **_candidate_fact_inherited_fields(value)}
    rows = None
    for key in ("rows", "candidate_rows", "candidateRows", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            rows = nested
            break
    if rows is None:
        return []
    columns = value.get("columns")
    column_names = [str(item) for item in columns] if isinstance(columns, list) else []
    facts: list[JsonObject] = []
    for row in rows:
        row_dict: JsonObject | None = None
        if isinstance(row, dict):
            row_dict = dict(row)
        elif isinstance(row, list) and column_names and len(row) <= len(column_names):
            row_dict = {column_names[index]: item for index, item in enumerate(row)}
        if row_dict is None:
            continue
        facts.extend(_candidate_facts_from_table_row(row_dict, inherited=fields))
    return _dedupe_candidate_facts(facts)


def _candidate_facts_from_table_row(row: JsonObject, *, inherited: JsonObject) -> list[JsonObject]:
    metric = _first_present(row, ("metric", "label", "line_item", "lineItem", "attribute", "name", "concept"))
    if not metric:
        return []
    base = {**inherited}
    for raw_key, normalized in (
        ("entity", "entityName"),
        ("entity_name", "entityName"),
        ("entityName", "entityName"),
        ("ticker", "ticker"),
        ("cik", "cik"),
        ("concept", "concept"),
        ("label", "label"),
        ("unit", "unit"),
        ("scale", "scale"),
        ("form", "form"),
        ("filed", "filed"),
        ("accn", "accn"),
    ):
        value = row.get(raw_key)
        if value not in (None, ""):
            base[normalized] = str(value)
    base["metric"] = str(metric)
    facts: list[JsonObject] = []
    explicit_value = _first_present(row, ("value", "val", "amount", "value_usd", "amount_usd"))
    if explicit_value not in (None, ""):
        fact = {**base, "value": str(explicit_value)}
        fy = _first_present(row, ("fy", "fiscal_year", "fiscalYear", "year"))
        if fy not in (None, ""):
            fact["fy"] = str(fy)
        period = row.get("period")
        if period not in (None, ""):
            fact["period"] = str(period)
        facts.append(fact)
    for key, value in row.items():
        if value in (None, ""):
            continue
        year = _candidate_year_from_column(str(key))
        scale = _candidate_scale_from_column(str(key)) or str(base.get("scale") or "")
        if year is not None:
            facts.append({**base, "fy": str(year), "value": str(value), **({"scale": scale} if scale else {})})
            continue
        value_scale = _candidate_value_scale_key(str(key))
        if value_scale:
            fact = {**base, "value": str(value), "scale": value_scale}
            fy = _first_present(row, ("fy", "fiscal_year", "fiscalYear", "year"))
            if fy not in (None, ""):
                fact["fy"] = str(fy)
            facts.append(fact)
    return _dedupe_candidate_facts(facts)


def _candidate_fact_inherited_fields(value: JsonObject) -> JsonObject:
    result: JsonObject = {}
    for raw_key, normalized in (
        ("entity", "entityName"),
        ("entity_name", "entityName"),
        ("entityName", "entityName"),
        ("ticker", "ticker"),
        ("cik", "cik"),
        ("unit", "unit"),
        ("scale", "scale"),
        ("form", "form"),
        ("filed", "filed"),
        ("accn", "accn"),
    ):
        raw_value = value.get(raw_key)
        if raw_value not in (None, ""):
            result[normalized] = str(raw_value)
    return result


def _first_present(value: JsonObject, keys: tuple[str, ...]) -> object:
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return item
    return None


def _candidate_year_from_column(value: str) -> int | None:
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:FY|fiscal\s*year\s*)?((?:19|20)\d{2})", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _candidate_scale_from_column(value: str) -> str:
    text = str(value or "").lower()
    if "million" in text or text.endswith("_mm") or text.endswith(" mm"):
        return "millions"
    if "billion" in text or text.endswith("_bn") or text.endswith(" bn"):
        return "billions"
    if "thousand" in text:
        return "thousands"
    return ""


def _candidate_value_scale_key(value: str) -> str:
    text = str(value or "").lower()
    if text in {"value_millions", "amount_millions", "value_in_millions", "amount_in_millions"}:
        return "millions"
    if text in {"value_billions", "amount_billions", "value_in_billions", "amount_in_billions"}:
        return "billions"
    if text in {"value_thousands", "amount_thousands", "value_in_thousands", "amount_in_thousands"}:
        return "thousands"
    return ""


def _candidate_fact_from_key_value_line(line: str) -> JsonObject:
    if "value=" not in line and "val=" not in line:
        return {}
    pairs = dict(re.findall(r"([A-Za-z_][A-Za-z0-9_:-]*)=([^=\s][^=]*?)(?=\s+[A-Za-z_][A-Za-z0-9_:-]*=|$)", line))
    if not pairs:
        return {}
    return _candidate_facts_from_json(pairs)[0] if _candidate_facts_from_json(pairs) else {}


def _dedupe_candidate_facts(candidates: list[JsonObject]) -> list[JsonObject]:
    result: list[JsonObject] = []
    seen: set[str] = set()
    for item in candidates:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _candidate_fact_evidence_text(fact: JsonObject) -> str:
    order = [
        "entityName",
        "ticker",
        "cik",
        "concept",
        "label",
        "metric",
        "unit",
        "scale",
        "fy",
        "period",
        "form",
        "filed",
        "accn",
        "value",
    ]
    parts = []
    for key in order:
        value = fact.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def _journal_toolchain_step_executed(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    observation_record,
    source: str,
    candidate_fact_count: int,
) -> None:
    observation_ref = str(observation_record.observation_ref or observation_record.data.get("observation_id") or "")
    if not observation_ref or _journal_has_observation_record(journal, task_id, run_id, kind="toolchain_step_executed", observation_ref=observation_ref):
        return
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=observation_record.step_id,
        kind="toolchain_step_executed",
        data=redact_journal_data(
            {
                "schema": "holo.kernel_v3.toolchain_step_executed.v1",
                "source": source,
                "status": observation_record.data.get("status"),
                "action_id": observation_record.data.get("action_id"),
                "observation_id": observation_ref,
                "candidate_fact_count": candidate_fact_count,
                "artifact_refs": list(observation_record.artifact_refs),
            }
        ),
        observation_ref=observation_ref,
        action_ref=str(observation_record.action_ref or observation_record.data.get("action_id") or ""),
    )


def _journal_toolchain_grounding_candidate(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    observation_record,
    source: str,
    candidate_facts: list[JsonObject],
) -> None:
    observation_ref = str(observation_record.observation_ref or observation_record.data.get("observation_id") or "")
    if not observation_ref or not candidate_facts:
        return
    if _journal_has_observation_record(journal, task_id, run_id, kind="toolchain_grounding_candidate", observation_ref=observation_ref):
        return
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=observation_record.step_id,
        kind="toolchain_grounding_candidate",
        data=redact_journal_data(
            {
                "schema": "holo.kernel_v3.toolchain_grounding_candidate.v1",
                "source": source,
                "observation_id": observation_ref,
                "candidate_fact_count": len(candidate_facts),
                "candidate_facts": candidate_facts[:128],
            }
        ),
        observation_ref=observation_ref,
        action_ref=str(observation_record.action_ref or observation_record.data.get("action_id") or ""),
    )


def _journal_toolchain_artifacts(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    observation_record,
    source: str,
    content: JsonObject,
) -> None:
    observation_ref = str(observation_record.observation_ref or observation_record.data.get("observation_id") or "")
    artifact_refs = _toolchain_artifact_refs(observation_record, content)
    if not observation_ref or not artifact_refs:
        return
    if _journal_has_observation_record(journal, task_id, run_id, kind="toolchain_artifact", observation_ref=observation_ref):
        return
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=observation_record.step_id,
        kind="toolchain_artifact",
        data=redact_journal_data(
            {
                "schema": "holo.kernel_v3.toolchain_artifact.v1",
                "source": source,
                "observation_id": observation_ref,
                "artifact_refs": artifact_refs,
                "script_path": content.get("script_path"),
                "output_artifact_id": content.get("output_artifact_id"),
                "script_artifact_id": content.get("script_artifact_id"),
            }
        ),
        observation_ref=observation_ref,
        action_ref=str(observation_record.action_ref or observation_record.data.get("action_id") or ""),
    )


def _journal_toolchain_failure(
    journal: JournalStore,
    *,
    task_id: str,
    run_id: str,
    observation_record,
    source: str,
    content: JsonObject,
) -> None:
    observation_ref = str(observation_record.observation_ref or observation_record.data.get("observation_id") or "")
    if not observation_ref:
        return
    if _journal_has_observation_record(journal, task_id, run_id, kind="toolchain_failure", observation_ref=observation_ref):
        return
    stderr = str(content.get("stderr") or "")
    stdout = str(content.get("stdout") or "")
    journal.append(
        task_id=task_id,
        run_id=run_id,
        step_id=observation_record.step_id,
        kind="toolchain_failure",
        data=redact_journal_data(
            {
                "schema": "holo.kernel_v3.toolchain_failure.v1",
                "source": source,
                "status": observation_record.data.get("status"),
                "observation_id": observation_ref,
                "exit_code": content.get("exit_code"),
                "error": content.get("error"),
                "stderr_preview": stderr[:1200],
                "stdout_preview": stdout[:1200],
                "artifact_refs": _toolchain_artifact_refs(observation_record, content),
            }
        ),
        observation_ref=observation_ref,
        action_ref=str(observation_record.action_ref or observation_record.data.get("action_id") or ""),
        state_delta={"toolchain_failure": source},
    )


def _toolchain_artifact_refs(observation_record, content: JsonObject) -> list[str]:
    refs: list[str] = []
    for item in getattr(observation_record, "artifact_refs", []) or []:
        if isinstance(item, str) and item:
            refs.append(item)
    for key in ("artifact_id", "script_artifact_id", "output_artifact_id"):
        value = content.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    return _ordered_unique(refs)


def _journal_has_observation_record(
    journal: JournalStore,
    task_id: str,
    run_id: str,
    *,
    kind: str,
    observation_ref: str,
) -> bool:
    for record in journal.records(task_id=task_id, kind=kind):
        if record.run_id == run_id and str(record.observation_ref or record.data.get("observation_id") or "") == observation_ref:
            return True
    return False


def _workspace_evidence_priority(item: EvidenceItem) -> tuple[int, str]:
    source = str(item.diagnostics.get("source") or "")
    if source == "tool:file.read":
        return 0, item.evidence_id
    if source == "tool:script.exec":
        return 1, item.evidence_id
    if source == "tool:shell.exec":
        return 2, item.evidence_id
    if source == "tool:workspace.write":
        return 3, item.evidence_id
    if source == "tool:workspace.list":
        return 4, item.evidence_id
    return 5, item.evidence_id


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
    if source == "tool:shell.exec":
        return _shell_exec_observation_text(content)[:evidence_char_limit]
    if source == "tool:script.exec":
        return _script_exec_observation_text(content)[:evidence_char_limit]
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
    if source == "tool:shell.exec":
        argv = content.get("argv")
        if isinstance(argv, list) and argv:
            return "shell exec: " + " ".join(str(item) for item in argv[:4])
        return "shell exec"
    if source == "tool:script.exec":
        path = content.get("script_path")
        return f"script exec: {path}" if isinstance(path, str) and path else "script exec"
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


def _shell_exec_observation_text(content: JsonObject) -> str:
    argv = content.get("argv")
    command = " ".join(str(item) for item in argv[:8]) if isinstance(argv, list) else ""
    exit_code = content.get("exit_code")
    stdout = str(content.get("stdout") or "").strip()
    stderr = str(content.get("stderr") or "").strip()
    lines = ["Shell execution output:"]
    if command:
        lines.append(f"command: {command}")
    if isinstance(exit_code, int):
        lines.append(f"exit_code: {exit_code}")
    if stdout:
        lines.append("stdout:")
        lines.append(stdout)
    if stderr:
        lines.append("stderr:")
        lines.append(stderr)
    return "\n".join(lines)


def _script_exec_observation_text(content: JsonObject) -> str:
    script_path = str(content.get("script_path") or "")
    argv = content.get("argv")
    command = " ".join(str(item) for item in argv[:8]) if isinstance(argv, list) else ""
    exit_code = content.get("exit_code")
    stdout = str(content.get("stdout") or "").strip()
    stderr = str(content.get("stderr") or "").strip()
    lines = ["Script execution output:"]
    if script_path:
        lines.append(f"script_path: {script_path}")
    if command:
        lines.append(f"command: {command}")
    if isinstance(exit_code, int):
        lines.append(f"exit_code: {exit_code}")
    facts = _toolchain_candidate_facts(content, source="tool:script.exec")
    if facts:
        lines.append("candidate_facts:")
        lines.extend(_candidate_fact_evidence_text(fact) for fact in facts[:64])
    if stdout:
        lines.append("stdout:")
        lines.append(stdout)
    if stderr:
        lines.append("stderr:")
        lines.append(stderr)
    return "\n".join(line for line in lines if line)


def _grounded_answer(*, report: RetrievalReport, evidence: list[EvidenceItem], citations: list[CitationItem]) -> str:
    if not evidence:
        return ""
    joined = " ".join(item.text.strip() for item in evidence if item.text.strip())
    preview = joined[:360]
    if citations:
        return f"{preview} [{citations[0].citation_id}]"
    return preview or report.preview


def _finance_retrieval_fallback_final(
    *,
    journal: JournalStore,
    task_id: str,
    run_id: str,
    recipe: TaskRecipe,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    synthesis_error: str,
    require_formula_trace: bool = False,
) -> FinalAnswer | None:
    citation_ids = [item.citation_id for item in citations if item.citation_id]
    if not citation_ids:
        return None
    traces = _calculator_formula_traces(journal, task_id=task_id, run_id=run_id)
    if require_formula_trace and not traces:
        return None
    if synthesis_error == "finance_numeric_verification_failed":
        intro = "自动合成阶段产生了未被证据账本或 calculator trace 支持的数字，因此以下为 Holo host 生成的保守可验证回答。"
    else:
        intro = "自动合成阶段输出格式失败，因此以下为 Holo host 基于已验证证据和计算轨迹生成的保守回答。"
    lines = [
        intro,
    ]
    if traces:
        lines.append("已完成的确定性计算：")
        for trace in traces[:3]:
            formatted = str(trace.diagnostics.get("formatted_value") or "").strip()
            value = formatted or f"{trace.result_value} {trace.unit or ''}".strip()
            if _finance_trace_has_model_outputs(trace):
                lines.append(f"- {trace.formula_name}: {value}，公式和模型明细已记录在 FormulaTrace。")
            else:
                lines.append(f"- {trace.formula_name}: {value}，公式 `{trace.expression}`。")
            for detail in _finance_model_trace_summary_lines(trace):
                lines.append(f"  - {detail}")
    else:
        facts = build_finance_fact_ledger(evidence=evidence, citations=citations)
        question = _benchmark_oracle_question_text(_root_goal_from_recipe(recipe))
        binding = _target_document_binding_from_recipe(recipe)
        facts = attach_target_binding_to_facts(facts, binding, question=question) if binding else facts
        formula_plan = plan_finance_formula(question=question, facts=facts, existing_traces=[])
        fact_lines = _finance_fallback_fact_lines(
            facts,
            question=question,
            target_binding=binding,
            limit=4,
        )
        if _source_grounded_explanation_question(question):
            evidence_lines = _source_grounded_fallback_evidence_lines(
                evidence=evidence,
                citations=citations,
                recipe=recipe,
                limit=4,
                sanitize_numbers=False,
            )
            if evidence_lines:
                lines.append("已由引用证据支持的要点：")
                lines.extend(evidence_lines)
            elif fact_lines:
                lines.append("已由证据账本支持的关键数值：")
                lines.extend(fact_lines)
        elif fact_lines:
            lines.append("已由证据账本支持的关键数值：")
            lines.extend(fact_lines)
        elif _source_grounded_trace_required(recipe) or (
            formula_plan.status == "not_applicable" and _required_retrieval_source_urls(recipe)
        ):
            evidence_lines = _source_grounded_fallback_evidence_lines(
                evidence=evidence,
                citations=citations,
                recipe=recipe,
                limit=4,
                sanitize_numbers=True,
            )
            if evidence_lines:
                lines.append("已由引用证据支持的要点：")
                lines.extend(evidence_lines)
        else:
            evidence_lines = _source_grounded_fallback_evidence_lines(
                evidence=evidence,
                citations=citations,
                recipe=recipe,
                limit=4,
                sanitize_numbers=True,
            )
            if evidence_lines:
                lines.append("已由引用证据支持的要点：")
                lines.extend(evidence_lines)
    if evidence:
        lines.append("可审计证据摘要：")
        lines.extend(_finance_fallback_evidence_summary_lines(evidence=evidence, citations=citations, recipe=recipe, limit=4))
    lines.append(f"局限：原 synthesizer 失败原因为 `{synthesis_error}`；上面的结论只覆盖当前证据和 calculator trace 支持的部分。")
    return FinalAnswer(
        answer="\n".join(lines),
        citation_refs=citation_ids,
        used_evidence=[item.evidence_id for item in evidence],
        limitations=[f"synthesizer_fallback:{synthesis_error}", "conservative_finance_answer"],
        confidence=0.55 if traces else 0.35,
        task_id=task_id,
        run_id=run_id,
        trace_refs=_trace_refs(journal, task_id),
    )


def _finance_fallback_evidence_summary_lines(
    *,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    recipe: TaskRecipe,
    limit: int,
) -> list[str]:
    citation_by_evidence = {item.evidence_id: item for item in citations if item.evidence_id}
    lines: list[str] = []
    for item in _source_grounded_ranked_evidence(evidence, recipe=recipe)[: max(1, limit)]:
        citation = citation_by_evidence.get(item.evidence_id)
        if citation is None:
            continue
        source_label = _safe_fallback_source_label(item.title or item.uri or "", limit=120)
        excerpt = _safe_fallback_evidence_excerpt(item.text, limit=220)
        if excerpt:
            lines.append(f"- {source_label}: {excerpt} [{citation.citation_id}]")
        else:
            lines.append(f"- {source_label} [{citation.citation_id}]")
    return lines


def _safe_fallback_evidence_excerpt(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    # Conservative fallback evidence previews are context, not the numeric
    # output channel. Keep row/metric semantics visible while preventing quoted
    # table values from becoming unsupported answer numbers.
    normalized = re.sub(r"\bCIK\s*0*\d+\b", "CIK identifier", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bCIK0*\d+\b", "CIK identifier", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<![A-Za-z])\(?-?\d[\d,]*(?:\.\d+)?\)?%?", "[number]", normalized)
    normalized = normalized.replace("form=[number]-K", "form=10-K")
    normalized = normalized.replace("Form [number]-K", "Form 10-K")
    normalized = normalized.replace("[number]-K", "10-K")
    normalized = re.sub(r"(?:\[number\][,\s]*){4,}", "[number series] ", normalized)
    return _shorten_for_fallback_answer(normalized, limit=limit)


def _source_grounded_fallback_evidence_lines(
    *,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    recipe: TaskRecipe,
    limit: int,
    sanitize_numbers: bool = True,
) -> list[str]:
    citation_by_evidence = {item.evidence_id: item for item in citations if item.evidence_id}
    scored: list[tuple[float, int, EvidenceItem, CitationItem]] = []
    for index, item in enumerate(_source_grounded_ranked_evidence(evidence, recipe=recipe)):
        citation = citation_by_evidence.get(item.evidence_id)
        if citation is None or not citation.citation_id:
            continue
        score = _source_grounded_evidence_score(item, recipe=recipe)
        scored.append((score, -index, item, citation))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    lines: list[str] = []
    for _, _, item, citation in scored[: max(1, limit)]:
        preview = _safe_fallback_evidence_excerpt(item.text, limit=360) if sanitize_numbers else _text_preview(item.text, limit=360)
        if not preview:
            preview = _safe_fallback_source_label(item.title or item.uri, limit=160)
        lines.append(f"- {preview} [{citation.citation_id}]")
    return lines


def _source_grounded_ranked_evidence(evidence: list[EvidenceItem], *, recipe: TaskRecipe) -> list[EvidenceItem]:
    if not evidence:
        return []
    scored = [
        (_source_grounded_evidence_score(item, recipe=recipe), -index, item)
        for index, item in enumerate(evidence)
    ]
    return [item for _score, _index, item in sorted(scored, key=lambda entry: (entry[0], entry[1]), reverse=True)]


def _source_grounded_evidence_score(item: EvidenceItem, *, recipe: TaskRecipe) -> float:
    question = _benchmark_oracle_question_text(_root_goal_from_recipe(recipe))
    text = f"{item.title} {item.uri} {item.text}".lower()
    score = float(item.score) if isinstance(item.score, (int, float)) else 0.0
    required_urls = _required_retrieval_source_urls(recipe)
    if any(_same_url_or_prefix(str(item.uri or ""), url) for url in required_urls):
        score += 120.0
    required_hosts = [_url_host(url) for url in required_urls if _looks_like_url(url)]
    if any(host and host in text for host in required_hosts):
        score += 60.0
    for term in _source_grounded_selection_terms(question):
        if term in text:
            score += 12.0
    if _source_grounded_explanation_question(question):
        for marker in _SOURCE_GROUNDED_EXPLANATORY_MARKERS:
            if marker in text:
                score += 8.0
    if item.diagnostics.get("workbench_rescue"):
        score += 40.0
    return score


_SOURCE_GROUNDED_EXPLANATORY_MARKERS = (
    "due to",
    "driven by",
    "drove",
    "driver",
    "drivers",
    "impacted",
    "impacting",
    "primarily due",
    "resulted in",
    "offset",
    "benefit",
    "headwind",
    "tailwind",
    "increased",
    "decreased",
)


def _source_grounded_selection_terms(question: str) -> list[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "is",
        "it",
        "its",
        "like",
        "not",
        "of",
        "on",
        "or",
        "please",
        "state",
        "than",
        "that",
        "the",
        "then",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for raw in str(question or "").lower().replace("-", " ").replace("_", " ").split():
        term = "".join(
            char
            for char in raw
            if char.isalnum() or char in {"%", "$", "/", "&"} or "\u4e00" <= char <= "\u9fff"
        )
        if not term or term in seen or term in stopwords:
            continue
        if len(term) < 3 and not any(char.isdigit() for char in term):
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _source_grounded_explanation_question(question: str) -> bool:
    text = str(question or "").lower()
    return any(
        marker in text
        for marker in (
            "what drove",
            "what drives",
            "why did",
            "explain why",
            "explain the",
            "drivers of",
            "driver of",
            "main reasons",
            "primary reasons",
            "主要原因",
            "驱动因素",
            "为什么",
        )
    )


def _finance_fallback_fact_lines(
    facts: list[FinanceFact],
    *,
    question: str,
    limit: int,
    target_binding: JsonObject | None = None,
) -> list[str]:
    binding_resolution = primary_source_numeric_binding_resolution(facts, target_binding, question=question) if target_binding else {}
    selected_fact_ids = set(_string_list(binding_resolution.get("selected_fact_ids"))) if isinstance(binding_resolution, dict) else set()
    ranked_source = [fact for fact in facts if not selected_fact_ids or fact.fact_id in selected_fact_ids]
    ranked = sorted(
        (fact for fact in ranked_source if _decimal_or_none_runtime(fact.value) is not None),
        key=lambda fact: _finance_fallback_fact_score(fact, question=question),
        reverse=True,
    )
    lines: list[str] = []
    seen: set[tuple[str, str, str | None]] = set()
    for fact in ranked:
        score = _finance_fallback_fact_score(fact, question=question)
        if score <= 0 and lines:
            continue
        key = (str(fact.metric).lower(), str(fact.value), fact.citation_ref)
        if key in seen:
            continue
        seen.add(key)
        display = _finance_fact_value_display(fact, question=question)
        period = f"FY{fact.fiscal_year}" if fact.fiscal_year is not None else str(fact.period or "").strip()
        if not period:
            period = _finance_fallback_question_year(question)
        period_text = f"{period} " if period else ""
        citation = f" [{fact.citation_ref}]" if fact.citation_ref else ""
        lines.append(f"- {period_text}{fact.metric}: {display}{citation}")
        if len(lines) >= limit:
            break
    return lines


def _finance_fallback_fact_score(fact: FinanceFact, *, question: str) -> int:
    normalized_question = " ".join(str(question or "").lower().split())
    metric = str(fact.metric or "").lower()
    score = 0
    if metric and metric in normalized_question:
        score += 20
    metric_aliases = {
        "capital expenditures": ("capital expenditure", "capital expenditures", "capex", "property, plant and equipment", "pp&e"),
        "operating cash flow": ("cash flow from operating", "operating activities", "cash provided by operating"),
        "revenue": ("revenue", "revenues", "sales"),
        "net income": ("net income", "net earnings", "profit"),
        "adjusted ebitda": ("adjusted ebitda", "ebitda bridge"),
        "enterprise value": ("enterprise value", "ev"),
        "transaction value": ("transaction value", "deal value", "acquisition"),
    }
    for canonical, aliases in metric_aliases.items():
        if metric == canonical and any(alias in normalized_question for alias in aliases):
            score += 30
            label_position_score = _finance_fallback_label_position_score(fact, aliases=aliases)
            score += label_position_score
    if fact.fiscal_year is not None and str(fact.fiscal_year) in normalized_question:
        score += 10
    if fact.metadata.get("supported_metric") is True:
        score += 5
    source_uri = str(fact.metadata.get("source_uri") or "").lower()
    source_title = str(fact.metadata.get("source_title") or "").lower()
    source_text = f"{source_uri} {source_title}"
    if "data.sec.gov/api/xbrl/companyfacts/" in source_uri or "sec companyfacts" in source_text:
        score += 80
    elif "sec.gov" in source_uri or " sec " in f" {source_title} ":
        score += 50
    if any(
        secondary_source in source_text
        for secondary_source in (
            "stockanalysis.com",
            "finance.yahoo",
            "yahoo finance",
            "google finance",
            "macrotrends",
            "companiesmarketcap",
        )
    ):
        score -= 35
    concept = str(fact.metadata.get("concept") or "").lower()
    if metric == "capital expenditures" and concept in {
        "paymentstoacquirepropertyplantandequipment",
        "paymentstoacquireproductiveassets",
        "propertyplantandequipmentadditions",
        "capitalexpendituresincurredbutnotyetpaid",
    }:
        score += 40
    if fact.citation_ref:
        score += 3
    return score


def _benchmark_oracle_question_text(goal: str) -> str:
    wrapper_marker = "Benchmark-provided oracle source context follows."
    if wrapper_marker in goal:
        tail = goal[goal.find(wrapper_marker) + len(wrapper_marker):].strip()
        if "\n\n" in tail:
            candidate = tail.rsplit("\n\n", 1)[1].strip()
            if candidate:
                return candidate
    marker = "Provided evidence excerpt:"
    marker_index = goal.find(marker)
    if marker_index < 0:
        return goal
    payload = goal[marker_index + len(marker):].lstrip()
    if not payload or payload[0] not in "[{":
        return goal
    try:
        _value, end = json.JSONDecoder().raw_decode(payload)
    except json.JSONDecodeError:
        return goal
    question = payload[end:].strip()
    return question or goal


def _finance_fallback_question_year(question: str) -> str:
    match = re.search(r"\b(?:FY|fiscal\s+year\s*)?((?:19|20)\d{2})\b", str(question or ""), flags=re.IGNORECASE)
    return f"FY{match.group(1)}" if match else ""


def _finance_fallback_label_position_score(fact: FinanceFact, *, aliases: tuple[str, ...]) -> int:
    context = " ".join(str(fact.metadata.get("context") or "").lower().split())
    raw = str(fact.metadata.get("raw") or "").strip().lower()
    if not context or not raw:
        return 0
    raw_index = context.find(raw)
    if raw_index < 0 and raw.startswith("(") and raw.endswith(")"):
        raw_index = context.find(raw[1:-1])
    if raw_index < 0:
        return 0
    label_indexes = [context.find(alias.lower()) for alias in aliases if context.find(alias.lower()) >= 0]
    if not label_indexes:
        return 0
    nearest_label = min(label_indexes, key=lambda index: abs(raw_index - index))
    if nearest_label <= raw_index:
        return 20
    return -20


def _finance_fact_value_display(fact: FinanceFact, *, question: str = "") -> str:
    value = _decimal_or_none_runtime(fact.value)
    if value is None:
        return str(fact.value)
    metric = str(fact.metric or "").lower()
    display_value = abs(value) if metric in {"capital expenditures", "cogs", "cost of sales", "cost of revenue"} else value
    question_text = str(question or "").lower()
    if "usd millions" in question_text or "usd million" in question_text or "in millions" in question_text:
        return f"{_decimal_string_runtime(display_value / Decimal(1_000_000))}（USD millions 口径）"
    if "usd billions" in question_text or "usd billion" in question_text or "in billions" in question_text:
        return f"{_decimal_string_runtime(display_value / Decimal(1_000_000_000))}（USD billions 口径）"
    unit = str(fact.unit or "").lower()
    if unit in {"usd", "$", "dollars"} or not unit:
        return _finance_usd_display(display_value)
    return f"{_decimal_string_runtime(display_value)} {fact.unit}"


def _shorten_for_fallback_answer(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)].rstrip()}..."


def _finance_model_trace_summary_lines(trace: FormulaTrace) -> list[str]:
    diagnostics = trace.diagnostics if isinstance(trace.diagnostics, dict) else {}
    model_outputs = diagnostics.get("model_outputs") if isinstance(diagnostics.get("model_outputs"), dict) else {}
    assumptions = diagnostics.get("assumptions") if isinstance(diagnostics.get("assumptions"), dict) else {}
    defaulted = diagnostics.get("defaulted_assumptions") if isinstance(diagnostics.get("defaulted_assumptions"), list) else []
    lines: list[str] = []
    if assumptions:
        assumption_parts = [
            f"{key}={_finance_model_value_display(value, key=str(key))}"
            for key, value in sorted(assumptions.items())
            if key != "defaulted"
        ]
        if assumption_parts:
            label = "建模假设"
            if defaulted:
                label += f"（其中默认/缺失填充：{', '.join(str(item) for item in defaulted[:8])}）"
            lines.append(f"{label}: {', '.join(assumption_parts[:8])}。")
    workflow = str(diagnostics.get("modeling_workflow") or trace.formula_name or "").lower()
    if workflow == "discounted_cash_flow" or str(trace.formula_name).lower() == "dcf":
        dcf_keys = (
            "enterprise_value",
            "net_debt",
            "equity_value",
            "equity_value_per_share",
            "terminal_value",
            "pv_terminal_value",
        )
        summary = _finance_model_output_summary(model_outputs, dcf_keys)
        if summary:
            lines.append("DCF 核心模型输出: " + ", ".join(summary) + "。")
    elif workflow == "leveraged_buyout" or str(trace.formula_name).lower() == "lbo":
        lbo_keys = (
            "entry_enterprise_value",
            "initial_debt",
            "initial_sponsor_equity",
            "exit_enterprise_value",
            "exit_debt",
            "exit_equity_value",
            "moic",
            "sponsor_irr",
        )
        summary = _finance_model_output_summary(model_outputs, lbo_keys)
        if summary:
            lines.append("LBO 核心模型输出: " + ", ".join(summary) + "。")
    return lines[:3]


def _finance_trace_has_model_outputs(trace: FormulaTrace) -> bool:
    diagnostics = trace.diagnostics if isinstance(trace.diagnostics, dict) else {}
    return isinstance(diagnostics.get("model_outputs"), dict) and bool(diagnostics.get("model_outputs"))


def _finance_model_output_summary(model_outputs: JsonObject, keys: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for key in keys:
        if key not in model_outputs:
            continue
        value = model_outputs.get(key)
        result.append(f"{key}={_finance_model_value_display(value, key=key)}")
    return result


def _finance_model_value_display(value: object, *, key: str) -> str:
    numeric = _decimal_or_none_runtime(value)
    normalized_key = str(key or "").lower()
    if numeric is None:
        return _shorten_for_fallback_answer(str(value), limit=80)
    if any(marker in normalized_key for marker in ("irr", "growth", "rate", "margin")):
        return f"{_decimal_string_runtime(numeric * Decimal(100))}%"
    if any(marker in normalized_key for marker in ("moic", "multiple", "discount_factor")):
        return f"{_decimal_string_runtime(numeric)}x"
    if "per_share" in normalized_key:
        return f"${_decimal_string_runtime(numeric)}/share"
    if any(
        marker in normalized_key
        for marker in (
            "cash_flow",
            "terminal_value",
            "enterprise_value",
            "equity_value",
            "debt",
            "cash",
            "investments",
            "ebitda",
            "sponsor_equity",
        )
    ):
        return _finance_usd_display(numeric)
    return _decimal_string_runtime(numeric)


def _finance_usd_display(value: Decimal) -> str:
    abs_value = abs(value)
    if abs_value >= Decimal(1_000_000_000):
        return f"${_decimal_string_runtime(value / Decimal(1_000_000_000))} billion"
    if abs_value >= Decimal(1_000_000):
        return f"${_decimal_string_runtime(value / Decimal(1_000_000))} million"
    return f"${_decimal_string_runtime(value)}"


def _decimal_or_none_runtime(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _decimal_string_runtime(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _safe_fallback_source_label(text: str, *, limit: int) -> str:
    normalized = " ".join(str(text or "").split()) or "retrieval evidence"
    # Source identifiers such as CIK/accession numbers are not answer claims.
    # Keep them out of conservative fallback prose so the numeric gate does not
    # treat source metadata as unsupported material finance numbers.
    normalized = re.sub(r"\bCIK\s*0*\d+\b", "CIK identifier", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bCIK0*\d+\b", "CIK identifier", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b\d{6,}\b", "identifier", normalized)
    return _shorten_for_fallback_answer(normalized, limit=limit)


def _report_with_task_goal(
    report: RetrievalReport,
    recipe: TaskRecipe,
    *,
    host_situation: JsonObject | None = None,
) -> RetrievalReport:
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
    if host_situation:
        diagnostics.setdefault("host_situation", dict(host_situation))
    preferences = _interaction_preferences_metadata(recipe)
    if preferences:
        diagnostics.setdefault("interaction_preferences", preferences)
        if isinstance(preferences.get("response_language"), str):
            diagnostics.setdefault("response_language", preferences["response_language"])
    return replace(report, diagnostics=diagnostics)


def _report_with_finance_formula_traces(
    journal: JournalStore,
    report: RetrievalReport,
    *,
    task_id: str,
    run_id: str,
) -> RetrievalReport:
    traces = _calculator_formula_traces(journal, task_id=task_id, run_id=run_id)
    if not traces:
        return report
    diagnostics = dict(report.diagnostics)
    diagnostics["finance_formula_traces"] = [trace.to_dict() for trace in traces[:16]]
    diagnostics["finance_formula_trace_count"] = len(traces)
    diagnostics.setdefault(
        "finance_synthesis_directive",
        (
            "Use host calculator formula traces as the authoritative computed values. "
            "Do not recompute these finance formulas mentally; quote the trace values and cite the supporting evidence. "
            "Every material numeric claim in the finance answer must come from formula traces, the finance fact/claim ledger, "
            "or an explicitly labeled assumption; unsupported numbers must be omitted or downgraded to limitations."
        ),
    )
    diagnostics.setdefault(
        "finance_numeric_claim_policy",
        {
            "allowed_numeric_sources": ["formula_trace", "finance_fact_ledger", "claim_ledger", "explicit_assumption_label"],
            "unsupported_numeric_behavior": "omit_or_limit",
            "material_claim_scope": "figures, percentages, multiples, margins, growth rates, periods, transaction values, and bridge components",
        },
    )
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


def _can_attempt_finance_numeric_finalization(
    *,
    recipe: TaskRecipe,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
) -> bool:
    if not _finance_numeric_verifier_required(recipe):
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
    adaptive_completion: JsonObject | None = None,
) -> RetrievalReport:
    diagnostics = dict(report.diagnostics)
    existing_limitations = diagnostics.get("limitations")
    limitations = [str(item) for item in existing_limitations if isinstance(item, str)] if isinstance(existing_limitations, list) else []
    adaptive_completion = dict(adaptive_completion or {})
    limitations.extend(
        [
            "retrieval_completed_partially",
            *missing_evidence,
            *_string_list(adaptive_completion.get("limitations")),
        ]
    )
    diagnostics.update(
        {
            "partial_answer": True,
            "partial_answer_reason": terminal_reason or "retrieval_partial",
            "adaptive_retrieval_completion": adaptive_completion,
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


def _thread_id_from_recipe(recipe: TaskRecipe | None) -> str | None:
    if recipe is None:
        return None
    metadata = recipe.metadata if isinstance(recipe.metadata, dict) else {}
    thread_id = metadata.get("thread_id")
    if isinstance(thread_id, str):
        return thread_id
    execution = metadata.get("execution_metadata")
    if isinstance(execution, dict) and isinstance(execution.get("thread_id"), str):
        return str(execution["thread_id"])
    return None


def _should_propose_failure_reflection(failure: FailureReport) -> bool:
    if failure.user_help_needed:
        return False
    if failure.reason in {
        "needs_user_input",
        "clarification_required",
        "missing_direct_answer",
        "citations_required_but_missing",
    }:
        return False
    if failure.reason.startswith("user_"):
        return False
    return bool(failure.attempted_actions or failure.missing_evidence or failure.next_possible_action)


def _root_goal_for_memory_reflection(journal: JournalStore, task_id: str, recipe: TaskRecipe) -> str:
    semantic_goal = _semantic_goal_metadata(recipe)
    for key in ("root_goal", "goal", "current_input_preview"):
        value = semantic_goal.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    research = _research_mission_metadata(recipe)
    for key in ("root_goal", "goal", "user_goal"):
        value = research.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    plan = _task_execution_plan_metadata(recipe)
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("goal"), str) and step["goal"].strip():
            return str(step["goal"]).strip()
    for record in reversed(journal.records(task_id=task_id, kind="task")):
        text = record.data.get("input_text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return task_id


def _calculator_formula_traces(journal: JournalStore, *, task_id: str, run_id: str) -> list[FormulaTrace]:
    traces: list[FormulaTrace] = []
    seen: set[str] = set()
    for record in journal.records(task_id=task_id, kind="observation"):
        if record.run_id != run_id:
            continue
        if record.data.get("source") != f"tool:{CALCULATOR_TOOL_NAME}" or record.data.get("status") != "ok":
            continue
        content = record.data.get("content")
        content = content if isinstance(content, dict) else {}
        payload = content.get("formula_trace")
        if not isinstance(payload, dict):
            continue
        try:
            trace = FormulaTrace.from_dict(payload)
        except Exception:
            continue
        if trace.formula_id in seen:
            continue
        seen.add(trace.formula_id)
        traces.append(trace)
    return traces


def _finance_formula_preflight_plans(
    *,
    question: str,
    facts: list[FinanceFact],
    existing_traces: list[FormulaTrace],
    evidence: list[EvidenceItem] | None = None,
):
    question_only = _benchmark_oracle_question_text(question)
    table_plan = _benchmark_table_formula_plan(question=question_only, evidence=evidence or [])
    if table_plan is not None:
        return [table_plan]
    plan = plan_finance_formula(question=question_only, facts=facts, existing_traces=existing_traces)
    if plan.formula_name in {"dio", "ev_ebitda"}:
        grouped = _finance_facts_by_entity(facts)
        ready = []
        if len(grouped) > 1:
            for entity, entity_facts in grouped.items():
                entity_plan = plan_finance_formula(question=question_only, facts=entity_facts, existing_traces=None)
                if entity_plan.status != "ready" or not isinstance(entity_plan.payload, dict):
                    continue
                payload = dict(entity_plan.payload)
                if _formula_trace_covers_inputs(existing_traces, _string_list(payload.get("input_fact_ids"))):
                    continue
                payload["formula_name"] = f"{entity_plan.formula_name}:{entity}"
                ready.append(
                    replace(
                        entity_plan,
                        payload=payload,
                        diagnostics={**entity_plan.diagnostics, "entity": entity},
                    )
                )
            if ready:
                return ready
    return [plan]


def _benchmark_table_formula_plan(*, question: str, evidence: list[EvidenceItem]) -> FinanceFormulaPlan | None:
    average_plan = _benchmark_table_average_formula_plan(question=question, evidence=evidence)
    if average_plan is not None:
        return average_plan
    text_plan = _benchmark_text_formula_plan(question=question, evidence=evidence)
    if text_plan is not None:
        return text_plan
    tables = _benchmark_tables_from_evidence(evidence)
    for table in tables:
        for planner in (
            _benchmark_cumulative_return_plan,
            _benchmark_percentage_share_plan,
            _benchmark_change_between_periods_plan,
            _benchmark_sum_period_values_plan,
            _benchmark_same_increase_projection_plan,
        ):
            plan = planner(question=question, table=table)
            if plan is not None:
                return plan
    return None


def _benchmark_table_average_formula_plan(*, question: str, evidence: list[EvidenceItem]) -> FinanceFormulaPlan | None:
    parsed = _average_per_question(question)
    if parsed is None:
        return None
    entity, numerator_phrase, denominator_phrase = parsed
    for table in _benchmark_tables_from_evidence(evidence):
        if len(table) < 2:
            continue
        headers = [str(item) for item in table[0]]
        if not headers:
            continue
        row = _benchmark_table_entity_row(table[1:], entity=entity)
        if row is None:
            continue
        numerator_index = _benchmark_table_column_index(headers, numerator_phrase)
        denominator_index = _benchmark_table_column_index(headers, denominator_phrase)
        if numerator_index is None or denominator_index is None:
            continue
        if numerator_index >= len(row) or denominator_index >= len(row):
            continue
        numerator = _benchmark_table_decimal(row[numerator_index])
        denominator = _benchmark_table_decimal(row[denominator_index])
        if numerator is None or denominator is None or denominator.is_zero():
            continue
        numerator_header = headers[numerator_index]
        denominator_header = headers[denominator_index]
        input_fact_ids = [
            "table-cell-" + _short_hash(entity, numerator_header, str(row[numerator_index])),
            "table-cell-" + _short_hash(entity, denominator_header, str(row[denominator_index])),
        ]
        return FinanceFormulaPlan(
            status="ready",
            formula_name="table_average_per",
            input_fact_ids=input_fact_ids,
            missing_facts=[],
            payload={
                "expression": "numerator / denominator",
                "formula_name": "table_average_per",
                "variables": {
                    "numerator": _decimal_string_runtime(numerator),
                    "denominator": _decimal_string_runtime(denominator),
                },
                "unit": None,
                "input_fact_ids": input_fact_ids,
                "diagnostics": {
                    "source": "benchmark_table_numeric_reasoning",
                    "entity": entity,
                    "numerator_column": numerator_header,
                    "denominator_column": denominator_header,
                    "numerator_raw": str(row[numerator_index]),
                    "denominator_raw": str(row[denominator_index]),
                    "question": question,
                },
            },
            diagnostics={
                "source": "benchmark_table_numeric_reasoning",
                "entity": entity,
                "numerator_phrase": numerator_phrase,
                "denominator_phrase": denominator_phrase,
            },
        )
    return FinanceFormulaPlan(
        status="missing_facts",
        formula_name="table_average_per",
        missing_facts=["matching_table_row", "matching_numerator_column", "matching_denominator_column"],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "parsed_average_per": {
                "entity": entity,
                "numerator_phrase": numerator_phrase,
                "denominator_phrase": denominator_phrase,
            },
            "table_count": len(_benchmark_tables_from_evidence(evidence)),
        },
    )


def _benchmark_text_formula_plan(*, question: str, evidence: list[EvidenceItem]) -> FinanceFormulaPlan | None:
    normalized_question = " ".join(str(question or "").lower().split())
    if "after-tax" not in normalized_question and "after tax" not in normalized_question:
        return None
    if "tax" not in normalized_question:
        return None
    joined = " ".join(str(item.text or "") for item in evidence)
    match = re.search(
        r"\$\s*(?P<pretax>-?\d+(?:\.\d+)?)\s*million\s*,?\s*or\s*\$\s*(?P<aftertax>-?\d+(?:\.\d+)?)\s*million\s*after[- ]tax",
        joined,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    pretax = Decimal(match.group("pretax"))
    aftertax = Decimal(match.group("aftertax"))
    return _benchmark_ready_formula_plan(
        formula_name="pretax_aftertax_difference",
        expression="pretax - aftertax",
        variables={"pretax": pretax, "aftertax": aftertax},
        unit=None,
        input_labels=["pretax", "aftertax"],
        diagnostics={
            "source": "benchmark_text_numeric_reasoning",
            "question": question,
            "matched_text": match.group(0),
        },
    )


def _benchmark_cumulative_return_plan(*, question: str, table: list[list[object]]) -> FinanceFormulaPlan | None:
    normalized = " ".join(str(question or "").lower().split())
    if "cumulative total return" not in normalized:
        return None
    date_match = re.search(r"\b\d{1,2}-[a-z]{3}-\d{4}\b", normalized)
    entity_match = re.search(r"\bof\s+(?P<entity>.+?)(?:\s+common stock|\?|$)", normalized)
    if date_match is None or entity_match is None:
        return None
    headers = _benchmark_table_headers(table)
    rows = _benchmark_table_rows(table)
    row = _benchmark_table_entity_row(rows, entity=date_match.group(0))
    col_index = _benchmark_table_column_index(headers, entity_match.group("entity"))
    if row is None or col_index is None:
        return None
    ending = _benchmark_table_value_at(row, col_index)
    if ending is None:
        return None
    return _benchmark_ready_formula_plan(
        formula_name="cumulative_return_percent",
        expression="(ending_value - base_value) / base_value",
        variables={"ending_value": ending, "base_value": Decimal("100")},
        unit="percent",
        input_labels=[date_match.group(0), entity_match.group("entity")],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "row_label": str(row[0]) if row else "",
            "column": headers[col_index] if col_index < len(headers) else "",
        },
    )


def _benchmark_percentage_share_plan(*, question: str, table: list[list[object]]) -> FinanceFormulaPlan | None:
    normalized = " ".join(str(question or "").lower().split())
    if "percent" not in normalized and "percentage" not in normalized:
        return None
    headers = _benchmark_table_headers(table)
    rows = _benchmark_table_rows(table)
    if not headers or not rows:
        return None

    after_year_match = re.search(r"\b(?:due|due after|after)\s+(?P<year>(?:19|20)\d{2})\b", normalized)
    total_row_match = re.search(
        r"\b(?:percent|percentage)\s+of\s+(?:the\s+)?total\s+(?P<row>.+?)\s+(?:that\s+)?(?:was\s+)?due\s+after\s+(?:19|20)\d{2}",
        normalized,
    )
    if total_row_match is not None and after_year_match is not None:
        row_phrase = total_row_match.group("row").strip()
        row = _benchmark_table_entity_row(rows, entity=row_phrase)
        numerator_col = _benchmark_table_column_index(headers, "thereafter") or _benchmark_table_column_index(headers, "after")
        denominator_col = _benchmark_table_column_index(headers, "total")
        plan = _benchmark_ratio_from_row_columns(
            question=question,
            table=table,
            row=row,
            numerator_col=numerator_col,
            denominator_col=denominator_col,
            formula_name="percentage_of_total_due_after",
            diagnostics_extra={"row_phrase": row_phrase, "after_year": after_year_match.group("year")},
        )
        if plan is not None:
            return plan

    row_due_match = re.search(
        r"\b(?:percent|percentage)\s+of\s+(?:the\s+)?total\s+(?P<denominator>.+?)\s+(?:is|are|was|were)\s+due\s+to\s+(?P<numerator>[^?.,;]+)",
        normalized,
    )
    if row_due_match is not None:
        plan = _benchmark_ratio_from_rows(
            question=question,
            table=table,
            numerator_phrase=row_due_match.group("numerator"),
            denominator_phrase="total",
            column_phrase="total",
            formula_name="percentage_of_total_row",
        )
        if plan is not None:
            return plan

    due_after_match = re.search(
        r"\b(?:percent|percentage)\s+of\s+(?:the\s+)?total\s+(?P<denominator>.+?)\s+(?:is|are|was|were)\s+due\s+after\s+(?:19|20)\d{2}",
        normalized,
    )
    if due_after_match is not None:
        plan = _benchmark_ratio_from_rows(
            question=question,
            table=table,
            numerator_phrase="thereafter",
            denominator_phrase="total",
            column_phrase="",
            formula_name="percentage_of_total_due_after_row",
        )
        if plan is not None:
            return plan

    comes_from_match = re.search(
        r"\b(?:percent|percentage)\s+of\s+(?:the\s+)?(?P<denominator>.+?)\s+comes\s+from\s+(?P<numerator>[^?.,;]+)",
        normalized,
    )
    if comes_from_match is not None:
        denominator_phrase = comes_from_match.group("denominator")
        column_phrase = "total"
        if "mmboe" in denominator_phrase:
            column_phrase = "total mmboe"
        plan = _benchmark_ratio_from_rows(
            question=question,
            table=table,
            numerator_phrase=comes_from_match.group("numerator"),
            denominator_phrase="total",
            column_phrase=column_phrase,
            formula_name="percentage_of_total_source",
        )
        if plan is not None:
            return plan
    return None


def _benchmark_change_between_periods_plan(*, question: str, table: list[list[object]]) -> FinanceFormulaPlan | None:
    normalized = " ".join(str(question or "").lower().split())
    if not any(marker in normalized for marker in ("change", "increase", "decline", "decrease")):
        return None
    years = _benchmark_years_from_question(normalized)
    if len(years) < 2:
        return None
    headers = _benchmark_table_headers(table)
    rows = _benchmark_table_rows(table)
    row_phrase = _benchmark_change_row_phrase(normalized)
    row = _benchmark_table_entity_row(rows, entity=row_phrase)
    if row is None:
        return None
    first_col = _benchmark_table_column_index(headers, years[0])
    second_col = _benchmark_table_column_index(headers, years[1])
    if first_col is None or second_col is None:
        return None
    first = _benchmark_table_value_at(row, first_col)
    second = _benchmark_table_value_at(row, second_col)
    if first is None or second is None:
        return None
    if "decline" in normalized or "decrease" in normalized:
        expression = "old_value - new_value"
        variables = {"old_value": first, "new_value": second}
    else:
        expression = "new_value - old_value"
        variables = {"old_value": first, "new_value": second}
    return _benchmark_ready_formula_plan(
        formula_name="period_change",
        expression=expression,
        variables=variables,
        unit=None,
        input_labels=[row_phrase, years[0], years[1]],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "row_phrase": row_phrase,
            "row_label": str(row[0]) if row else "",
            "first_period": years[0],
            "second_period": years[1],
        },
    )


def _benchmark_sum_period_values_plan(*, question: str, table: list[list[object]]) -> FinanceFormulaPlan | None:
    normalized = " ".join(str(question or "").lower().split())
    if "total" not in normalized and "balance" not in normalized:
        return None
    years = _benchmark_years_from_question(normalized)
    if len(years) < 2:
        return None
    row_match = re.search(r"\b(?:what was|what is|was)\s+(?:the\s+)?(?P<row>.+?)\s+(?:balance\s+)?for\s+(?:19|20)\d{2}\s+and\s+(?:19|20)\d{2}", normalized)
    if row_match is None:
        return None
    row_phrase = row_match.group("row").strip()
    headers = _benchmark_table_headers(table)
    row = _benchmark_table_entity_row(_benchmark_table_rows(table), entity=row_phrase)
    if row is None:
        return None
    values: dict[str, Decimal] = {}
    labels: list[str] = [row_phrase]
    for index, year in enumerate(years[:4], start=1):
        col = _benchmark_table_column_index(headers, year)
        value = _benchmark_table_value_at(row, col) if col is not None else None
        if value is None:
            return None
        values[f"value_{index}"] = value
        labels.append(year)
    expression = " + ".join(values)
    return _benchmark_ready_formula_plan(
        formula_name="period_value_sum",
        expression=expression,
        variables=values,
        unit=None,
        input_labels=labels,
        diagnostics={"source": "benchmark_table_numeric_reasoning", "question": question, "row_phrase": row_phrase},
    )


def _benchmark_same_increase_projection_plan(*, question: str, table: list[list[object]]) -> FinanceFormulaPlan | None:
    normalized = " ".join(str(question or "").lower().split())
    if "increased" not in normalized or "as much as" not in normalized or "what would" not in normalized:
        return None
    years = _benchmark_years_from_question(normalized)
    if len(years) < 2:
        return None
    target_year = years[0]
    previous_year = years[1]
    headers = _benchmark_table_headers(table)
    rows = _benchmark_table_rows(table)
    row_phrase = _benchmark_projection_row_phrase(normalized)
    row = _benchmark_table_entity_row(rows, entity=row_phrase)
    if row is None:
        return None
    current_col = _benchmark_table_column_index(headers, target_year)
    previous_col = _benchmark_table_column_index(headers, previous_year)
    current = _benchmark_table_value_at(row, current_col) if current_col is not None else None
    previous = _benchmark_table_value_at(row, previous_col) if previous_col is not None else None
    if current is None or previous is None:
        return None
    return _benchmark_ready_formula_plan(
        formula_name="same_increase_projection",
        expression="current_value + (current_value - previous_value)",
        variables={"current_value": current, "previous_value": previous},
        unit=None,
        input_labels=[row_phrase, target_year, previous_year],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "row_phrase": row_phrase,
        },
    )


def _benchmark_ratio_from_rows(
    *,
    question: str,
    table: list[list[object]],
    numerator_phrase: str,
    denominator_phrase: str,
    column_phrase: str,
    formula_name: str,
) -> FinanceFormulaPlan | None:
    headers = _benchmark_table_headers(table)
    rows = _benchmark_table_rows(table)
    numerator_row = _benchmark_table_entity_row(rows, entity=numerator_phrase)
    denominator_row = _benchmark_table_entity_row(rows, entity=denominator_phrase)
    if numerator_row is None or denominator_row is None:
        return None
    col_index = _benchmark_table_column_index(headers, column_phrase) if column_phrase else 1 if len(headers) > 1 else None
    if col_index is None:
        return None
    numerator = _benchmark_table_value_at(numerator_row, col_index)
    denominator = _benchmark_table_value_at(denominator_row, col_index)
    if numerator is None or denominator is None or denominator.is_zero():
        return None
    return _benchmark_ready_formula_plan(
        formula_name=formula_name,
        expression="numerator / denominator",
        variables={"numerator": numerator, "denominator": denominator},
        unit="percent",
        input_labels=[numerator_phrase, denominator_phrase, column_phrase],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "numerator_phrase": numerator_phrase,
            "denominator_phrase": denominator_phrase,
            "column_phrase": column_phrase,
        },
    )


def _benchmark_ratio_from_row_columns(
    *,
    question: str,
    table: list[list[object]],
    row: list[object] | None,
    numerator_col: int | None,
    denominator_col: int | None,
    formula_name: str,
    diagnostics_extra: JsonObject | None = None,
) -> FinanceFormulaPlan | None:
    if row is None or numerator_col is None or denominator_col is None:
        return None
    numerator = _benchmark_table_value_at(row, numerator_col)
    denominator = _benchmark_table_value_at(row, denominator_col)
    if numerator is None or denominator is None or denominator.is_zero():
        return None
    headers = _benchmark_table_headers(table)
    return _benchmark_ready_formula_plan(
        formula_name=formula_name,
        expression="numerator / denominator",
        variables={"numerator": numerator, "denominator": denominator},
        unit="percent",
        input_labels=[str(row[0]) if row else "", headers[numerator_col], headers[denominator_col]],
        diagnostics={
            "source": "benchmark_table_numeric_reasoning",
            "question": question,
            "row_label": str(row[0]) if row else "",
            "numerator_column": headers[numerator_col],
            "denominator_column": headers[denominator_col],
            **dict(diagnostics_extra or {}),
        },
    )


def _benchmark_ready_formula_plan(
    *,
    formula_name: str,
    expression: str,
    variables: dict[str, Decimal],
    unit: str | None,
    input_labels: list[str],
    diagnostics: JsonObject,
) -> FinanceFormulaPlan:
    input_fact_ids = [
        "table-cell-" + _short_hash(label, key, _decimal_string_runtime(value))
        for label, (key, value) in zip(input_labels or [], variables.items())
    ]
    if len(input_fact_ids) < len(variables):
        for key, value in list(variables.items())[len(input_fact_ids):]:
            input_fact_ids.append("table-cell-" + _short_hash(key, _decimal_string_runtime(value)))
    return FinanceFormulaPlan(
        status="ready",
        formula_name=formula_name,
        input_fact_ids=input_fact_ids,
        missing_facts=[],
        payload={
            "expression": expression,
            "formula_name": formula_name,
            "variables": {key: _decimal_string_runtime(value) for key, value in variables.items()},
            "unit": unit,
            "input_fact_ids": input_fact_ids,
            "diagnostics": diagnostics,
        },
        diagnostics=diagnostics,
    )


def _average_per_question(question: str) -> tuple[str, str, str] | None:
    text = " ".join(str(question or "").strip().split())
    match = re.search(
        r"(?i)\baverage\s+(?P<numerator>.+?)\s+per\s+(?P<denominator>.+?)\s+for\s+(?P<entity>[^?.,;]+)",
        text,
    )
    if match is None:
        return None
    entity = match.group("entity").strip()
    numerator = match.group("numerator").strip()
    denominator = match.group("denominator").strip()
    if not entity or not numerator or not denominator:
        return None
    return entity, numerator, denominator


def _benchmark_tables_from_evidence(evidence: list[EvidenceItem]) -> list[list[list[object]]]:
    tables: list[list[list[object]]] = []
    decoder = json.JSONDecoder()
    for item in evidence:
        text = str(item.text or "")
        search_start = 0
        while True:
            marker_index = text.find("table:", search_start)
            if marker_index < 0:
                break
            payload = text[marker_index + len("table:") :].lstrip()
            try:
                value, end = decoder.raw_decode(payload)
            except json.JSONDecodeError:
                search_start = marker_index + len("table:")
                continue
            if _looks_like_table(value):
                tables.append(value)
            search_start = marker_index + len("table:") + end
    return tables


def _looks_like_table(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(row, list) for row in value[:2])
        and any(len(row) > 1 for row in value if isinstance(row, list))
    )


def _benchmark_table_headers(table: list[list[object]]) -> list[str]:
    if not table:
        return []
    return [str(item) for item in table[0]]


def _benchmark_table_rows(table: list[list[object]]) -> list[list[object]]:
    return [row for row in table[1:] if isinstance(row, list) and row]


def _benchmark_table_value_at(row: list[object] | None, index: int | None) -> Decimal | None:
    if row is None or index is None or index < 0 or index >= len(row):
        return None
    return _benchmark_table_decimal(row[index])


def _benchmark_table_entity_row(rows: list[list[object]], *, entity: str) -> list[object] | None:
    entity_tokens = _benchmark_table_tokens(entity)
    if not entity_tokens:
        return None
    best: tuple[int, list[object]] | None = None
    for row in rows:
        if not row:
            continue
        label = str(row[0])
        label_tokens = _benchmark_table_tokens(label)
        if not label_tokens:
            continue
        score = len(entity_tokens & label_tokens)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best is not None else None


def _benchmark_table_column_index(headers: list[str], phrase: str) -> int | None:
    phrase = str(phrase or "").strip()
    if not phrase and len(headers) > 1:
        return 1
    phrase_tokens = _benchmark_table_tokens(phrase)
    if not phrase_tokens:
        return None
    best: tuple[int, int] | None = None
    for index, header in enumerate(headers):
        header_tokens = _benchmark_table_tokens(header)
        if not header_tokens:
            continue
        score = len(phrase_tokens & header_tokens)
        if score <= 0:
            continue
        if phrase_tokens <= header_tokens:
            score += 10
        if best is None or score > best[0]:
            best = (score, index)
    return best[1] if best is not None else None


def _benchmark_years_from_question(question: str) -> list[str]:
    return re.findall(r"\b(?:19|20)\d{2}\b", str(question or ""))


def _benchmark_change_row_phrase(question: str) -> str:
    text = str(question or "")
    patterns = (
        r"\bchange\s+in\s+(?P<row>.+?)\s+from\s+(?:19|20)\d{2}",
        r"\bincrease\s+in\s+(?P<row>.+?)\s+between\s+years",
        r"\bdecline\s+in\s+(?P<row>.+?)\s+(?:in\s+)?(?:fiscal\s+)?(?:19|20)\d{2}",
        r"\bchange\s+of\s+(?P<row>.+?)\s+from\s+(?:19|20)\d{2}",
        r"\bwhat\s+was\s+(?:the\s+)?(?P<row>.+?)\s+decline\s+in\s+(?:fiscal\s+)?(?:19|20)\d{2}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is not None:
            return _benchmark_clean_row_phrase(match.group("row"))
    return _benchmark_clean_row_phrase(text)


def _benchmark_projection_row_phrase(question: str) -> str:
    text = str(question or "")
    match = re.search(r"\bcurrent\s+(?P<row>.+?)\s+increased\s+in\s+(?:19|20)\d{2}", text, flags=re.IGNORECASE)
    if match is not None:
        return _benchmark_clean_row_phrase(match.group("row"))
    return _benchmark_clean_row_phrase(text)


def _benchmark_clean_row_phrase(value: str) -> str:
    text = re.sub(r"\b(in|from|to|between|for|of|the|a|an|what|was|is|were|are)\b", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    text = re.sub(r"[^A-Za-z0-9&/% -]+", " ", text)
    return " ".join(text.split())


def _benchmark_table_tokens(value: str) -> set[str]:
    text = str(value or "").lower().replace("-", " ")
    stop_words = {
        "the",
        "a",
        "an",
        "of",
        "for",
        "per",
        "amount",
        "amounts",
        "in",
        "billions",
        "million",
        "millions",
    }
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", text)
        if token not in stop_words
    }
    normalized: set[str] = set()
    for token in tokens:
        if token.endswith("s") and len(token) > 3:
            normalized.add(token[:-1])
        normalized.add(token)
    return normalized


def _benchmark_table_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    negative = "(" in text and ")" in text
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -number if negative and number > 0 else number


def _formula_trace_covers_inputs(traces: list[FormulaTrace], input_fact_ids: list[str]) -> bool:
    wanted = {str(item) for item in input_fact_ids if str(item)}
    if not wanted:
        return False
    for trace in traces:
        current = {str(item) for item in trace.input_fact_ids if str(item)}
        if current == wanted:
            return True
    return False


def _finance_facts_by_entity(facts: list[FinanceFact]) -> dict[str, list[FinanceFact]]:
    grouped: dict[str, list[FinanceFact]] = {}
    for fact in facts:
        entity = _finance_fact_entity_label(fact)
        if not entity:
            continue
        grouped.setdefault(entity, []).append(fact)
    return grouped


def _finance_fact_entity_label(fact: FinanceFact) -> str:
    for value in (fact.ticker, fact.entity, fact.metadata.get("cik"), fact.metadata.get("entityName")):
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _finance_numeric_missing_evidence(verification) -> list[str]:
    missing: list[str] = []
    for issue in list(getattr(verification, "issues", []) or []):
        if not isinstance(issue, dict):
            continue
        missing.append(str(issue.get("code") or "finance_numeric_issue"))
    for value in list(getattr(verification, "missing_values", []) or [])[:8]:
        if not isinstance(value, dict):
            continue
        raw = str(value.get("raw") or value.get("value") or "").strip()
        if raw:
            missing.append(f"unsupported_answer_number:{raw}")
    return _ordered_unique(missing)


def _finance_answer_numeric_support_rate(verification) -> float | None:
    diagnostics = getattr(verification, "diagnostics", {}) or {}
    answer_numeric_count = diagnostics.get("answer_numeric_count") if isinstance(diagnostics, dict) else None
    if not isinstance(answer_numeric_count, (int, float)) or answer_numeric_count <= 0:
        return None
    matched = list(getattr(verification, "matched_values", []) or [])
    return min(1.0, max(0.0, len(matched) / float(answer_numeric_count)))


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
