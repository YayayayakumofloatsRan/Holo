from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kernel_v3.agent.contracts import AgentRuntimeResult, FailureReport, FinalAnswer, SemanticIntake, TaskRecipe
from kernel_v3.agent.semantics import analyze_goal, analyze_goal_with_processor
from kernel_v3.agent.workloop import WorkloopConfig, WorkloopEvaluator
from kernel_v3.context import ArtifactStore, ContextPackCompiler, ProjectProfile
from kernel_v3.contracts import CandidateAction, ContextBundle, Event, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.memory import MemoryPipeline, MemoryStore
from kernel_v3.planner import Planner
from kernel_v3.policy import PolicyGate
from kernel_v3.processors import FakeJsonProvider, ModelEvaluator, ModelPlanner, ProcessorFabric, ProcessorRouter, Synthesizer
from kernel_v3.retrieval import FakeFetchProvider, RetrievalOperator, SearchSource, register_retrieval_tool
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, RetrievalReport
from kernel_v3.session import TaskState
from kernel_v3.tools import ToolManifest, ToolRegistry


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
        task_id: str | None,
    ) -> AgentRuntimeResult:
        intake = self._semantic_intake(goal, semantic_mode=semantic_mode, task_id=task_id)
        selected_mode = intake.suggested_mode if mode == "auto" else _select_mode(goal, mode)
        if selected_mode == "workspace_answer" and not _file_target(goal):
            selected_mode = "clarify_first"
        recipe = task_recipe(
            selected_mode,
            citations_required=citations_required,
            metadata={"semantic_intake": intake.to_dict()},
        )
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
            policy_gate=PolicyGate(permission=recipe.permission_profile),
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
        self._maybe_propose_memory(
            intake,
            task_id=result.task_id,
            run_id=result.run_id,
            thread_id=thread_id,
            source_record_ref=semantic_record.record_id,
        )
        self._append_recipe(recipe, task_id=result.task_id, run_id=result.run_id)
        if result.status == "needs_user_input":
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
                operator=self.retrieval_operator or _default_retrieval_operator(goal),
                journal=self.journal,
                artifact_store=self.artifact_store,
            )
            return registry
        if recipe.mode == "workspace_answer":
            if self.workspace_root is not None:
                return ToolRegistry.with_permissioned_workspace(root=self.workspace_root, artifact_store=self.artifact_store)
            return ToolRegistry.with_fake_workspace_tools(
                files=self.workspace_files or {"README.md": "Holo Kernel v3 workspace evidence."},
                artifact_store=self.artifact_store,
            )
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
            return ModelPlanner(
                fabric=self.processor_fabric,
                allowed_tool_names=set(recipe.allowed_tools) or {"__no_tools_allowed__"},
            )
        return _RecipePlanner(goal=goal, recipe=recipe)

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
        evidence, citations, report = _workspace_grounding(self.journal, task_id, run_id)
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

    def _semantic_intake(self, goal: str, *, semantic_mode: str, task_id: str | None) -> SemanticIntake:
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
        )

    def _append_recipe(self, recipe: TaskRecipe, *, task_id: str, run_id: str) -> None:
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_recipe",
            data=recipe.to_dict(),
            state_delta={"agent_recipe": recipe.recipe_id, "agent_mode": recipe.mode},
        )

    def _append_semantic_intake(self, intake: SemanticIntake, *, task_id: str, run_id: str):
        return self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="semantic_intake",
            data=intake.to_dict(),
            state_delta={
                "primary_intent": intake.primary_intent,
                "suggested_mode": intake.suggested_mode,
                "compound": intake.compound,
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
            data=answer.to_dict(),
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
            data=failure.to_dict(),
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
        ).compile(
            task,
            journal,
            tool_briefs=[
                {"name": manifest.name, "side_effect": manifest.side_effect_class}
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
        return ContextBundle(
            context_id=pack.context_id,
            thread_key=task.thread_id,
            event_ids=event_ids,
            memory_refs=pack.memory_refs,
            state={
                "task_id": task.task_id,
                "run_id": task.run_id,
                "thread_id": task.thread_id,
                "input_text": task.input_text,
                "agent_recipe": self.recipe.to_dict(),
                "agent_runtime_directive": _planner_directive(self.recipe),
                "context_pack_hash": pack.payload_hash,
                "sections": pack.sections,
                "source_refs": pack.source_refs,
                "redactions": pack.redactions,
                "budget": pack.budget,
            },
            token_budget=int(pack.budget["token_budget"]),
        )


class _RecipePlanner:
    def __init__(self, *, goal: str, recipe: TaskRecipe) -> None:
        self.goal = goal
        self.recipe = recipe
        self._actions = _recipe_actions(goal, recipe)

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
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
        return _bind_recipe_action_to_run(self._actions.pop(0), context)


class _RecipeEvaluator:
    def __init__(self, recipe: TaskRecipe) -> None:
        self.recipe = recipe
        self.calls = 0

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.calls += 1
        run_id = str(context.state["run_id"])
        if observation.status == "needs_user_input":
            return _feedback(run_id, self.calls, "needs_user_input", "needs_user_input", None, [])
        if observation.status == "blocked":
            return _feedback(run_id, self.calls, "blocked", "blocked", None, ["policy_block"])
        if self.recipe.mode == "workspace_answer" and observation.source == "tool:workspace.search":
            return _feedback(run_id, self.calls, "continue", None, None, ["file.read observation"])
        if observation.status in {"failed", "not_implemented"}:
            return _feedback(run_id, self.calls, "failed", "observation_failed", None, ["successful observation"])
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
        return TaskRecipe(
            recipe_id="recipe-retrieval-answer",
            allowed_tools=["retrieval.run"],
            max_steps=3,
            max_tool_calls=2,
            max_network_fetches=0,
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


def _select_mode(goal: str, mode: str) -> str:
    aliases = {
        "direct": "direct_answer",
        "retrieval": "retrieval_answer",
        "workspace": "workspace_answer",
        "clarify": "clarify_first",
    }
    normalized = aliases.get(mode, mode)
    if normalized != "auto":
        if normalized not in {"direct_answer", "retrieval_answer", "workspace_answer", "clarify_first"}:
            raise ValueError(f"unsupported agent mode: {mode}")
        return normalized
    lowered = goal.lower()
    if any(marker in lowered for marker in ("search", "retrieve", "web", "internet", "检索", "上网", "搜索")):
        return "retrieval_answer"
    if any(marker in lowered for marker in ("file", "readme", ".py", ".md", ".json", "workspace", "文件", "代码", "目录")):
        return "workspace_answer"
    if not goal.strip() or goal.strip() in {"?", "？", ".", "。"}:
        return "clarify_first"
    return "direct_answer"


def _recipe_actions(goal: str, recipe: TaskRecipe) -> list[CandidateAction]:
    if recipe.mode == "retrieval_answer":
        return [
            CandidateAction(
                action_id="act-agent-retrieval-1",
                kind="tool",
                name="retrieval.run",
                description="run retrieval for grounded answer",
                score=1.0,
                payload={"goal_id": "goal-agent-retrieval", "query": goal, "max_spans_per_document": 2},
                reasons=["retrieval_answer recipe"],
                side_effect_class="read",
            ),
            CandidateAction(
                action_id="act-agent-retrieval-2",
                kind="tool",
                name="retrieval.run",
                description="retry retrieval once if evidence remains insufficient",
                score=0.6,
                payload={"goal_id": "goal-agent-retrieval", "query": goal, "max_spans_per_document": 2},
                reasons=["retrieval_answer retry budget"],
                side_effect_class="read",
            )
        ]
    if recipe.mode == "workspace_answer":
        target = _file_target(goal)
        if target is None:
            return _recipe_actions(goal, task_recipe("clarify_first"))
        return [
            CandidateAction(
                action_id="act-agent-workspace-search",
                kind="tool",
                name="workspace.search",
                description="search workspace for requested file",
                score=1.0,
                payload={"query": target},
                reasons=["workspace_answer recipe"],
                side_effect_class="read",
            ),
            CandidateAction(
                action_id="act-agent-file-read",
                kind="tool",
                name="file.read",
                description="read workspace file for grounded answer",
                score=1.0,
                payload={"path": target},
                reasons=["workspace_answer recipe"],
                side_effect_class="read",
            ),
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


def _planner_directive(recipe: TaskRecipe) -> JsonObject:
    semantic = _semantic_intake_metadata(recipe)
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
            "semantic_intake": semantic,
        }
    if recipe.mode == "workspace_answer":
        return {
            "mode": recipe.mode,
            "required_sequence": [
                {"kind": "tool", "name": "workspace.search", "side_effect_class": "read"},
                {"kind": "tool", "name": "file.read", "side_effect_class": "read"},
            ],
            "allowed_tools": list(recipe.allowed_tools),
            "forbidden": ["retrieval.run", "web_search", "page_open", "network.fetch", "workspace.write"],
            "semantic_intake": semantic,
        }
    if recipe.mode == "clarify_first":
        return {
            "mode": recipe.mode,
            "required_first_action": {"kind": "ask_user", "name": None, "side_effect_class": "none"},
            "allowed_tools": [],
            "forbidden": ["all tool actions"],
            "semantic_intake": semantic,
        }
    return {
        "mode": recipe.mode,
        "required_first_action": {"kind": "respond", "name": None, "side_effect_class": "none"},
        "allowed_tools": [],
        "forbidden": ["all tool actions"],
        "semantic_intake": semantic,
    }


def _semantic_intake_metadata(recipe: TaskRecipe) -> JsonObject:
    value = recipe.metadata.get("semantic_intake")
    return dict(value) if isinstance(value, dict) else {}


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


def _default_retrieval_operator(goal: str) -> RetrievalOperator:
    source = SearchSource(
        source_id="src-agent-default",
        uri="https://example.test/holo-v3-agent",
        title="Holo v3 agent evidence",
        snippet=goal,
        provider="fake",
    )
    body = f"{goal} evidence from bounded fake retrieval for Holo Kernel v3 agent runtime."
    return RetrievalOperator(
        search_provider=_AnyQuerySearchProvider(source),
        fetch_provider=FakeFetchProvider({source.uri: body}),
    )


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


def _workspace_grounding(journal: JournalStore, task_id: str, run_id: str) -> tuple[list[EvidenceItem], list[CitationItem], RetrievalReport]:
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
        text_value = content.get("text")
        preview_value = content.get("text_preview")
        text = str(text_value if isinstance(text_value, str) else preview_value if isinstance(preview_value, str) else "")
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
                quote=text[:256],
                span_start=0,
                span_end=min(len(text), 256),
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
        diagnostics={"evidence_count": len(evidence), "citation_count": len(citations)},
    )
    return evidence, citations, report


def _grounded_answer(*, report: RetrievalReport, evidence: list[EvidenceItem], citations: list[CitationItem]) -> str:
    if not evidence:
        return ""
    joined = " ".join(item.text.strip() for item in evidence if item.text.strip())
    preview = joined[:360]
    if citations:
        return f"{preview} [{citations[0].citation_id}]"
    return preview or report.preview


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
