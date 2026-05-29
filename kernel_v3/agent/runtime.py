from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kernel_v3.agent.contracts import AgentRuntimeResult, FailureReport, FinalAnswer, TaskRecipe
from kernel_v3.context import ArtifactStore, ContextPackCompiler, ProjectProfile
from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, JsonObject, Observation
from kernel_v3.evaluator import Evaluator
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
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
    ) -> None:
        self.journal = journal or JournalStore.in_memory()
        self.artifact_store = artifact_store or ArtifactStore.in_memory()
        self.processor_fabric = processor_fabric
        self.retrieval_operator = retrieval_operator
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None
        self.workspace_files = dict(workspace_files or {})

    def run(
        self,
        goal: str,
        *,
        mode: str = "auto",
        planner_mode: str = "fake",
        evaluator_mode: str = "fake",
        synthesizer_mode: str = "fake",
        citations_required: bool | None = None,
    ) -> AgentRuntimeResult:
        selected_mode = _select_mode(goal, mode)
        if selected_mode == "workspace_answer" and not _file_target(goal):
            selected_mode = "clarify_first"
        recipe = task_recipe(selected_mode, citations_required=citations_required)
        registry = self._registry(recipe, goal)
        planner = self._planner(goal, recipe, registry, planner_mode)
        evaluator = self._evaluator(recipe, evaluator_mode)
        loop = LoopControllerV3(
            journal=self.journal,
            context_compiler=_AgentContextCompiler(recipe=recipe, tool_manifests=registry.manifests()),
            planner=planner,
            policy_gate=PolicyGate(permission=recipe.permission_profile),
            tool_registry=registry,
            evaluator=evaluator,
            max_steps=recipe.max_steps,
            max_tool_calls=recipe.max_tool_calls,
            max_network_fetches=recipe.max_network_fetches,
            max_total_artifact_bytes=recipe.max_total_artifact_bytes,
        )
        result = loop.run(goal)
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
                return ToolRegistry.with_permissioned_workspace(root=self.workspace_root)
            return ToolRegistry.with_fake_workspace_tools(files=self.workspace_files or {"README.md": "Holo Kernel v3 workspace evidence."})
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
            text = loop_answer or _last_response_text(self.journal, task_id) or ""
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
            return self._finalize_retrieval(task_id, run_id, recipe=recipe, synthesizer_mode=synthesizer_mode)
        if recipe.mode == "workspace_answer":
            return self._finalize_workspace(task_id, run_id, recipe=recipe, synthesizer_mode=synthesizer_mode)
        return None, self._failure(task_id, run_id, "needs_user_input", next_action="provide_more_detail")

    def _finalize_retrieval(
        self,
        task_id: str,
        run_id: str,
        *,
        recipe: TaskRecipe,
        synthesizer_mode: str,
    ) -> tuple[FinalAnswer | None, FailureReport | None]:
        report = _latest_retrieval_report(self.journal, task_id)
        evidence = _retrieval_evidence(self.journal, task_id)
        citations = _retrieval_citations(self.journal, task_id)
        if report is None:
            return None, self._failure(task_id, run_id, "missing_retrieval_report", next_action="retry_retrieval")
        if report.status != "sufficient":
            return None, self._failure(
                task_id,
                run_id,
                f"retrieval_{report.status}",
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
        evidence, citations, report = _workspace_grounding(self.journal, task_id)
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

    def _append_recipe(self, recipe: TaskRecipe, *, task_id: str, run_id: str) -> None:
        self.journal.append(
            task_id=task_id,
            run_id=run_id,
            step_id=None,
            kind="agent_recipe",
            data=recipe.to_dict(),
            state_delta={"agent_recipe": recipe.recipe_id, "agent_mode": recipe.mode},
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
            attempted_actions=_attempted_actions(self.journal, task_id),
            attempted_sources=_attempted_sources(self.journal, task_id),
            missing_evidence=list(missing_evidence or _missing_evidence(self.journal, task_id)),
            next_possible_action=next_action,
            task_id=task_id,
            run_id=run_id,
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
    def __init__(self, *, recipe: TaskRecipe, tool_manifests: list[ToolManifest]) -> None:
        self.recipe = recipe
        self.tool_manifests = [
            manifest for manifest in tool_manifests if manifest.name in set(recipe.allowed_tools)
        ]

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
        return self._actions.pop(0)


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


def task_recipe(mode: str, *, citations_required: bool | None = None) -> TaskRecipe:
    normalized = _select_mode("", mode)
    required = citations_required if citations_required is not None else normalized == "retrieval_answer"
    if normalized == "retrieval_answer":
        return TaskRecipe(
            recipe_id="recipe-retrieval-answer",
            allowed_tools=["retrieval.run"],
            max_steps=3,
            max_tool_calls=1,
            max_network_fetches=0,
            max_total_artifact_bytes=1_000_000,
            permission_profile="read_write",
            citations_required=bool(required),
            finalizer="retrieval_synthesizer",
            context_budget_mode="truncate",
            mode=normalized,
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
                action_id="act-agent-retrieval",
                kind="tool",
                name="retrieval.run",
                description="run retrieval for grounded answer",
                score=1.0,
                payload={"goal_id": "goal-agent-retrieval", "query": goal, "max_spans_per_document": 2},
                reasons=["retrieval_answer recipe"],
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
        return [
            CandidateAction(
                action_id="act-agent-clarify",
                kind="ask_user",
                name=None,
                description="ask user to clarify target",
                score=1.0,
                payload={"question": "请明确目标、文件名或需要检索的问题。"},
                reasons=["clarification_required"],
                side_effect_class="none",
            )
        ]
    return [
        CandidateAction(
            action_id="act-agent-direct",
            kind="respond",
            name=None,
            description="answer directly",
            score=1.0,
            payload={"text": f"Direct answer: {goal}"},
            reasons=["direct_answer recipe"],
            side_effect_class="none",
        )
    ]


def _planner_directive(recipe: TaskRecipe) -> JsonObject:
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
        }
    if recipe.mode == "clarify_first":
        return {
            "mode": recipe.mode,
            "required_first_action": {"kind": "ask_user", "name": None, "side_effect_class": "none"},
            "allowed_tools": [],
            "forbidden": ["all tool actions"],
        }
    return {
        "mode": recipe.mode,
        "required_first_action": {"kind": "respond", "name": None, "side_effect_class": "none"},
        "allowed_tools": [],
        "forbidden": ["all tool actions"],
    }


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


def _latest_retrieval_report(journal: JournalStore, task_id: str) -> RetrievalReport | None:
    records = journal.records(task_id=task_id, kind="retrieval_report")
    if not records:
        return None
    return RetrievalReport.from_dict(records[-1].data)


def _retrieval_evidence(journal: JournalStore, task_id: str) -> list[EvidenceItem]:
    return [EvidenceItem.from_dict(record.data) for record in journal.records(task_id=task_id, kind="retrieval_evidence")]


def _retrieval_citations(journal: JournalStore, task_id: str) -> list[CitationItem]:
    return [CitationItem.from_dict(record.data) for record in journal.records(task_id=task_id, kind="retrieval_citation")]


def _workspace_grounding(journal: JournalStore, task_id: str) -> tuple[list[EvidenceItem], list[CitationItem], RetrievalReport]:
    evidence: list[EvidenceItem] = []
    citations: list[CitationItem] = []
    for index, record in enumerate(journal.records(task_id=task_id, kind="observation"), start=1):
        data = record.data
        if data.get("source") != "tool:file.read" or data.get("status") != "ok":
            continue
        content = data.get("content", {})
        if not isinstance(content, dict):
            continue
        path = str(content.get("path", "workspace"))
        text = str(content.get("text", ""))
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


def _last_response_text(journal: JournalStore, task_id: str) -> str | None:
    for record in reversed(journal.records(task_id=task_id, kind="observation")):
        content = record.data.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return str(content["text"])
    return None


def _trace_refs(journal: JournalStore, task_id: str) -> list[str]:
    return [record.record_id for record in journal.records(task_id=task_id)]


def _attempted_actions(journal: JournalStore, task_id: str) -> list[str]:
    actions = []
    for record in journal.records(task_id=task_id, kind="action"):
        name = record.data.get("name")
        kind = record.data.get("kind")
        actions.append(str(name or kind or record.action_ref))
    return actions


def _attempted_sources(journal: JournalStore, task_id: str) -> list[str]:
    sources: list[str] = []
    for record in journal.records(task_id=task_id):
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


def _missing_evidence(journal: JournalStore, task_id: str) -> list[str]:
    for record in reversed(journal.records(task_id=task_id, kind="feedback")):
        missing = record.data.get("missing_evidence")
        if isinstance(missing, list):
            return [str(item) for item in missing]
    return []


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
