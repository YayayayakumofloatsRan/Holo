from __future__ import annotations

import hashlib
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
from kernel_v3.agent.semantics import analyze_goal, analyze_goal_with_processor
from kernel_v3.agent.taskgraph import build_task_execution_plan, task_graph_from_semantic, validate_task_graph
from kernel_v3.agent.workloop import WorkloopConfig, WorkloopEvaluator
from kernel_v3.context import ArtifactStore, ContextPackCompiler, ProjectProfile, merge_context_budget
from kernel_v3.contracts import CandidateAction, ContextBundle, Event, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.interaction import interaction_preferences, normalize_response_language
from kernel_v3.journal import JournalStore
from kernel_v3.journal_redaction import redact_journal_data
from kernel_v3.loop import LoopControllerV3
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.planner import Planner
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import FakeJsonProvider, ModelEvaluator, ModelPlanner, ProcessorFabric, ProcessorRouter, Synthesizer
from kernel_v3.research import (
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    ResearchCorpusStore,
    research_depth_defaults,
    source_directory_for_profile,
)
from kernel_v3.retrieval import (
    CorpusFetchProvider,
    CorpusSearchProvider,
    FakeFetchProvider,
    FallbackSearchProvider,
    RetrievalOperator,
    RoutingFetchProvider,
    SearchSource,
    register_retrieval_tool,
)
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
from kernel_v3.session import TaskState
from kernel_v3.tools import ToolManifest, ToolRegistry


_FINANCE_RESEARCH_PROFILE_CAPABILITIES = {
    "finance.fundamentals_research",
    "finance.market_news",
    "finance.market_data",
    "finance.competitive_landscape",
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
        )
        task_graph = task_graph_from_semantic(intake)
        task_graph_validation = validate_task_graph(task_graph)
        task_plan = build_task_execution_plan(task_graph, task_graph_validation)
        selected_mode = task_plan.selected_mode if mode == "auto" else _select_mode(goal, mode)
        if (
            selected_mode == "workspace_answer"
            and _workspace_target(goal, task_plan) is None
            and not _task_plan_has_workspace_read_actions(task_plan)
        ):
            selected_mode = "clarify_first"
        if selected_mode == "workspace_write" and planner_mode != "model" and _workspace_write_target(goal, task_plan) is None:
            selected_mode = "clarify_first"
        recipe = task_recipe(
            selected_mode,
            citations_required=citations_required,
            metadata={
                "semantic_intake": intake.to_dict(),
                "task_graph": task_graph.to_dict(),
                "task_graph_validation": task_graph_validation.to_dict(),
                "task_execution_plan": task_plan.to_dict(),
                "execution_metadata": dict(execution_metadata or {}),
            },
        )
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
        self._maybe_propose_memory(
            intake,
            task_id=result.task_id,
            run_id=result.run_id,
            thread_id=thread_id,
            source_record_ref=semantic_record.record_id,
        )
        self._append_recipe(recipe, task_id=result.task_id, run_id=result.run_id)
        if result.status == "needs_user_input":
            if recipe.mode == "retrieval_answer" and _latest_action_is_no_planned_action(self.journal, result.task_id, result.run_id):
                failure = self._failure(
                    result.task_id,
                    result.run_id,
                    _latest_termination_failure_reason(self.journal, result.task_id, result.run_id)
                    or result.stop_reason
                    or "no_executable_action",
                    missing_evidence=_missing_evidence(self.journal, result.task_id, result.run_id),
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
                    artifact_store=self.artifact_store,
                    corpus_store=self.research_corpus_store,
                ),
                journal=self.journal,
                artifact_store=self.artifact_store,
            )
            return registry
        if recipe.mode in {"workspace_answer", "workspace_write"}:
            if self.workspace_root is not None:
                return ToolRegistry.with_permissioned_workspace(root=self.workspace_root, artifact_store=self.artifact_store)
            return ToolRegistry.with_fake_workspace_tools(
                files=self.workspace_files or {"README.md": "Holo Kernel v3 workspace evidence."},
                artifact_store=self.artifact_store,
            )
        if recipe.mode == "system_answer":
            return ToolRegistry.with_builtin_respond()
        return ToolRegistry.with_builtin_respond()

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
                allowed_tool_names=set(recipe.allowed_tools) or {"__no_tools_allowed__"},
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
        if recipe.mode == "direct_answer":
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
                    confidence=0.6,
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
        if report is None:
            return None, self._failure(task_id, run_id, "missing_retrieval_report", next_action="retry_retrieval")
        if report.status != "sufficient":
            reason = _latest_termination_failure_reason(self.journal, task_id, run_id) or loop_stop_reason or f"retrieval_{report.status}"
            return None, self._failure(
                task_id,
                run_id,
                reason,
                missing_evidence=["sufficient_retrieval_evidence"],
                next_action="refine_query_or_add_sources",
            )
        if recipe.citations_required and not citations:
            return None, self._failure(
                task_id,
                run_id,
                "citations_required_but_missing",
                missing_evidence=["citation_refs"],
                next_action="retry_retrieval_with_citable_sources",
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
            return None, self._failure(
                task_id,
                run_id,
                synthesized.error or "synthesis_failed",
                missing_evidence=list(synthesized.limitations),
                next_action="collect_more_evidence",
            )
        return self._append_final(_agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))), None

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
        return self._append_final(_agent_final_from_processor(synthesized, task_id=task_id, run_id=run_id, trace_refs=_trace_refs(self.journal, task_id))), None

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
        fabric = ProcessorFabric(
            providers={
                "fake_json": FakeJsonProvider(
                    {
                        "synthesizer.answer": {
                            "answer": answer,
                            "citation_refs": [item.citation_id for item in citations],
                            "confidence": 0.8 if citations else 0.3,
                            "limitations": [] if citations else ["missing_citation_refs"],
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
        state = redact_journal_data(
            {
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "agent_recipe": self.recipe.to_dict(),
                "capability_catalog": capability_catalog(
                    tool_manifests=self.tool_manifests,
                    allowed_tools=self.recipe.allowed_tools,
                    allowed_permissions=_recipe_allowed_permissions(self.recipe),
                    mode=self.recipe.mode,
                ),
                "semantic_state_space": semantic_state_space_catalog(),
                "research_source_directory": _research_source_directory_metadata(self.recipe),
                "agent_runtime_directive": _planner_directive(self.recipe),
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
        if observation.status == "blocked":
            return _feedback(run_id, self.calls, "blocked", "blocked", None, ["policy_block"])
        if self.recipe.mode == "workspace_answer" and observation.source == "tool:workspace.search":
            return _feedback(run_id, self.calls, "continue", None, None, ["file.read observation"])
        if self.recipe.mode == "workspace_write" and observation.source in {"tool:workspace.search", "tool:file.read"}:
            return _feedback(run_id, self.calls, "continue", None, None, ["workspace.write observation"])
        if self.recipe.mode == "workspace_write" and observation.source == "tool:workspace.write" and observation.status == "ok":
            content = observation.content if isinstance(observation.content, dict) else {}
            path = content.get("path")
            answer = f"已写入 `{path}`。" if isinstance(path, str) and path else None
            return _feedback(run_id, self.calls, "final_answer_ready", "completed", answer, [])
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
        payload.setdefault("goal_id", "goal-agent-retrieval")
        payload.setdefault("query", goal)
        payload.setdefault("max_spans_per_document", 2)
        payload = _apply_recipe_profile_defaults(payload, recipe)
        payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
        payload = _apply_research_depth_defaults(payload)
        return replace(action, payload=payload)
    return action


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
            max_steps=3,
            max_tool_calls=2,
            max_network_fetches=max_network_fetches,
            max_total_artifact_bytes=1_000_000,
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
            allowed_tools=["workspace.search", "file.read"],
            max_steps=4,
            max_tool_calls=2,
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
            allowed_tools=["workspace.search", "file.read", "workspace.write"],
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


def _with_planned_action_count(goal: str, recipe: TaskRecipe) -> TaskRecipe:
    actions = _actions_from_task_plan(goal, recipe)
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
        max_steps = max(max_steps, 12)
        max_tool_calls = max(max_tool_calls, 10)
        max_artifact_bytes = max(max_artifact_bytes, 4_000_000)
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
        if normalized not in {"direct_answer", "retrieval_answer", "workspace_answer", "workspace_write", "system_answer", "clarify_first"}:
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
            return _recipe_actions(goal, task_recipe("clarify_first"))
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
    return actions


def _actions_from_plan_step(goal: str, recipe: TaskRecipe, step: JsonObject) -> list[CandidateAction]:
    tool_name = str(step.get("tool_name") or "")
    sequence = _plan_step_index(step)
    if tool_name == "retrieval.run":
        payload = {
            "goal_id": f"goal-plan-{sequence}",
            "query": str(step.get("goal") or goal),
            "max_spans_per_document": 2,
        }
        payload = _merge_retrieval_payload(payload, _capability_args_from_step(step, "retrieval.run"))
        payload = _apply_profile_capability_defaults(payload, step)
        payload = _merge_retrieval_payload(payload, _retrieval_execution_args(recipe))
        payload = _apply_research_depth_defaults(payload)
        return [
            CandidateAction(
                action_id=f"act-plan-{sequence}-retrieval",
                kind="tool",
                name="retrieval.run",
                description=str(step.get("goal") or "run retrieval"),
                score=1.0,
                payload=payload,
                reasons=["semantic_task_plan"],
                side_effect_class="read",
            )
        ]
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
    if recipe.mode == "retrieval_answer":
        return {
            "mode": recipe.mode,
            "required_first_action": {
                "kind": "tool",
                "name": "retrieval.run",
                "side_effect_class": "read",
                "payload_requirements": ["query or goal"],
            },
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["web_search", "page_open", "network.fetch"],
            "interaction_preferences": preferences,
            "semantic_intake": semantic,
        }
    if recipe.mode == "workspace_answer":
        return {
            "mode": recipe.mode,
            "required_sequence": [
                {
                    "kind": "tool",
                    "name": "workspace.search",
                    "side_effect_class": "read",
                    "payload_requirements": ["query: non-empty string; use the target path as query when known"],
                },
                {
                    "kind": "tool",
                    "name": "file.read",
                    "side_effect_class": "read",
                    "payload_requirements": ["path: non-empty workspace-relative file path"],
                },
            ],
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["retrieval.run", "web_search", "page_open", "network.fetch", "workspace.write"],
            "interaction_preferences": preferences,
            "semantic_intake": semantic,
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
            "semantic_intake": semantic,
        }
    if recipe.mode == "clarify_first":
        return {
            "mode": recipe.mode,
            "required_first_action": {"kind": "ask_user", "name": None, "side_effect_class": "none"},
            "allowed_tools": [],
            "forbidden": ["all tool actions"],
            "interaction_preferences": preferences,
            "semantic_intake": semantic,
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
            "semantic_intake": semantic,
        }
    return {
        "mode": recipe.mode,
        "required_first_action": {"kind": "respond", "name": None, "side_effect_class": "none"},
        "allowed_tools": [],
        "forbidden": ["all tool actions"],
        "interaction_preferences": preferences,
        "semantic_intake": semantic,
    }


def _semantic_intake_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("semantic_intake")
    return dict(value) if isinstance(value, dict) else {}


def _task_execution_plan_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("task_execution_plan")
    return dict(value) if isinstance(value, dict) else {}


def _execution_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("execution_metadata")
    return dict(value) if isinstance(value, dict) else {}


def _agent_loop_metadata(recipe: TaskRecipe) -> JsonObject:
    value = _execution_metadata(recipe).get("agent_loop")
    return dict(value) if isinstance(value, dict) else {}


def _research_source_directory_metadata(recipe: TaskRecipe) -> list[JsonObject]:
    profile_id = _research_profile_id(recipe)
    if profile_id is None:
        return []
    return [entry.to_dict() for entry in source_directory_for_profile(profile_id)]


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
    plan = _task_execution_plan_metadata(recipe)
    if _plan_has_any_capability(plan, _FINANCE_RESEARCH_PROFILE_CAPABILITIES):
        return FINANCE_FUNDAMENTALS_PROFILE_ID
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
    artifact_store: ArtifactStore,
    corpus_store: ResearchCorpusStore | None,
) -> RetrievalOperator:
    source = SearchSource(
        source_id="src-agent-default",
        uri="https://example.test/holo-v3-agent",
        title="Holo v3 agent evidence",
        snippet=goal,
        provider="fake",
    )
    body = f"{goal} evidence from bounded fake retrieval for Holo Kernel v3 agent runtime."
    fake_fetch = FakeFetchProvider({source.uri: body})
    if corpus_store is not None:
        return RetrievalOperator(
            search_provider=FallbackSearchProvider(
                [
                    CorpusSearchProvider(corpus_store),
                    _AnyQuerySearchProvider(source),
                ]
            ),
            fetch_provider=RoutingFetchProvider(
                routes={"research_corpus": CorpusFetchProvider(artifact_store)},
                fallback=fake_fetch,
            ),
            corpus_store=corpus_store,
        )
    return RetrievalOperator(
        search_provider=_AnyQuerySearchProvider(source),
        fetch_provider=fake_fetch,
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
    defaults = research_depth_defaults(profile_id, depth if isinstance(depth, str) else None)
    if not defaults:
        return payload
    merged = dict(payload)
    for key in ("max_queries", "max_sources", "max_fetches", "max_spans_per_document"):
        if key not in merged and key in defaults:
            merged[key] = defaults[key]
    if "research_depth" not in merged and isinstance(depth, str) and depth:
        merged["research_depth"] = depth
    return merged


def _apply_profile_capability_defaults(payload: JsonObject, step: JsonObject) -> JsonObject:
    return _apply_finance_capability_defaults(payload, set(_step_capabilities(step)))


def _apply_recipe_profile_defaults(payload: JsonObject, recipe: TaskRecipe) -> JsonObject:
    return _apply_finance_capability_defaults(payload, _recipe_finance_capabilities(recipe))


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
    updated["metadata"] = metadata
    return updated


def _recipe_finance_capabilities(recipe: TaskRecipe) -> set[str]:
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
    return capabilities.intersection(_FINANCE_RESEARCH_PROFILE_CAPABILITIES)


def _retrieval_capability_args(recipe: TaskRecipe) -> JsonObject:
    step = _execution_step_metadata(recipe)
    if step is not None:
        args = _capability_args_from_step(step, "retrieval.run")
        if args:
            return args
    return _capability_args_from_plan(
        _task_execution_plan_metadata(recipe),
        "retrieval.run",
        capability_markers={"retrieval.run", *_FINANCE_RESEARCH_PROFILE_CAPABILITIES},
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


class _AnyQuerySearchProvider:
    def __init__(self, source: SearchSource) -> None:
        self.source = source

    def search(self, query, *, goal, plan):
        return [self.source]


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
        if str(raw_step.get("tool_name") or "") in {"workspace.search", "file.read", "workspace.search,file.read"}:
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
        capability_markers={"workspace.search", "file.read", "workspace:read"},
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


def _latest_action_is_no_planned_action(journal: JournalStore, task_id: str, run_id: str) -> bool:
    records = [
        record for record in journal.records(task_id=task_id, kind="action")
        if record.run_id == run_id
    ]
    if not records:
        return False
    reasons = records[-1].data.get("reasons")
    return isinstance(reasons, list) and "no_planned_action" in reasons


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
        if data.get("source") != "tool:file.read" or data.get("status") != "ok":
            continue
        content = data.get("content", {})
        if not isinstance(content, dict):
            continue
        path = str(content.get("path", "workspace"))
        text = _workspace_observation_text(content, artifact_store=artifact_store, evidence_char_limit=evidence_char_limit)
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
            diagnostics={"record_ref": record.record_id},
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


def _workspace_observation_text(content: JsonObject, *, artifact_store: ArtifactStore, evidence_char_limit: int) -> str:
    artifact_id = content.get("artifact_id")
    if isinstance(artifact_id, str) and artifact_store.has_blob(artifact_id):
        payload = artifact_store.read_blob(artifact_id)
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        return str(text)[:evidence_char_limit]
    text_value = content.get("text")
    preview_value = content.get("text_preview")
    text = str(text_value if isinstance(text_value, str) else preview_value if isinstance(preview_value, str) else "")
    return text[:evidence_char_limit]


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
    preferences = _interaction_preferences_metadata(recipe)
    if preferences:
        diagnostics.setdefault("interaction_preferences", preferences)
        if isinstance(preferences.get("response_language"), str):
            diagnostics.setdefault("response_language", preferences["response_language"])
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
