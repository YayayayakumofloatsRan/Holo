import json

from kernel_v3.agent.contracts import AgentRuntimeResult
from kernel_v3.agent.runtime import _bind_model_action_to_recipe, task_recipe
from kernel_v3.cli import _research_metadata
from kernel_v3.contracts import CandidateAction, ContextBundle, PolicyDecision
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.mission.contracts import MissionState
from kernel_v3.mission.supervisor import MissionSupervisor
from kernel_v3.processors.generation import adapt_generation_parameters
from kernel_v3.processors.routing import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO
from kernel_v3.research import ACADEMIC_RESEARCH_PROFILE_ID, FINANCE_FUNDAMENTALS_PROFILE_ID, profile_by_id
from kernel_v3.retrieval import FakeFetchProvider, FetchResponse, RetrievalOperator
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.live_config import LiveRetrievalConfig
from kernel_v3.retrieval.benchmark import retrieval_behavior_benchmark
from kernel_v3.retrieval.query_campaign import build_query_campaign
from kernel_v3.tools import ToolRegistry


def test_phase115_query_campaign_diversifies_entity_research_without_case_fixture():
    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-entity",
            query="Citadel Security scale operations business model",
            max_queries=16,
            max_sources=100,
            max_fetches=40,
            metadata={
                "research_depth": "balanced",
                "research_task_kind": "organization_research",
                "query_campaign": "auto",
            },
        )
    )

    joined = "\n".join(campaign.queries)
    assert '"Citadel Security" official source' in joined
    assert '"Citadel Security" profile operations scale' in joined
    assert len(campaign.queries) >= 8
    assert campaign.diagnostics["target_entities"] == ["Citadel Security"]


def test_phase115_academic_campaign_uses_profile_facets_and_avoids_dictionary_only_search():
    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-academic",
            query="hyperbolic dynamics frontier research",
            max_queries=16,
            max_sources=100,
            max_fetches=40,
            metadata={
                "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                "research_task_kind": "frontier_research",
                "query_campaign": "auto",
            },
        ),
        research_profile=profile_by_id(ACADEMIC_RESEARCH_PROFILE_ID),
    )

    joined = "\n".join(query.lower() for query in campaign.queries)
    assert "arxiv" in joined or "doi" in joined or "preprint" in joined
    assert "open problem" in joined or "survey" in joined or "state of the art" in joined
    assert "frontier_or_recent" in campaign.diagnostics["profile_facets"]


def test_phase115_general_research_report_gets_host_bounded_deep_campaign_defaults():
    recipe = task_recipe(
        "retrieval",
        metadata={
            "execution_metadata": {
                "retrieval": {"allow_network": True, "max_network_fetches": 1000},
                "answer_profile": {
                    "profile_id": "answer-profile-general",
                    "format": "detailed_report",
                    "detail_level": "detailed",
                    "target_sections": ["结论摘要", "证据", "分析", "局限"],
                    "citation_density": "normal",
                    "minimum_coverage": ["summary", "evidence", "analysis", "limitations"],
                    "language": "zh",
                    "min_answer_chars": 1200,
                    "min_section_count": 5,
                    "metadata": {"domain": "general_research", "quality_gate": "strict"},
                },
            }
        },
    )
    context = ContextBundle(
        context_id="ctx-general-research",
        thread_key="thread",
        event_ids=[],
        memory_refs=[],
        token_budget=4096,
        state={"run_id": "run-1", "agent_replan_hints": {"status": "none"}},
    )
    action = CandidateAction(
        action_id="act-general-research",
        kind="tool",
        name="retrieval.run",
        description="research",
        payload={"query": "Investigate a niche organization and write a report"},
        reasons=["research"],
        score=0.9,
        side_effect_class="network",
    )

    bound = _bind_model_action_to_recipe(
        action,
        goal="Investigate a niche organization and write a report",
        recipe=recipe,
        context=context,
    )

    assert bound.payload["max_queries"] >= 24
    assert bound.payload["max_sources"] >= 320
    assert bound.payload["max_fetches"] >= 96
    assert bound.payload["metadata"]["search_strategy"] == "aggregate"
    assert bound.payload["metadata"]["answer_profile"]["format"] == "detailed_report"


def test_phase115_balanced_auto_generation_upshifts_only_for_replan_or_deep_research():
    routine = adapt_generation_parameters(
        task_type="planner.propose",
        prompt="large routine planner context\n" + ("x" * 25_000),
        parameters={
            "provider": "deepseek",
            "model": DEEPSEEK_V4_FLASH,
            "generation_mode": "auto",
            "latency_target": "balanced",
            "thinking": "disabled",
        },
    )
    assert routine["model"] == DEEPSEEK_V4_FLASH
    assert routine["thinking"] == "disabled"
    assert routine["generation_policy"]["assessment"]["task_difficulty"] == "routine"

    replan_prompt = json.dumps(
        {
            "contract": "planner",
            "context": {
                "agent_replan_hints": {
                    "status": "needs_replan",
                    "retrieval": {
                        "needs_replan": True,
                        "failure_attribution": {"primary_failure_mode": "source_authority_gap"},
                    },
                }
            },
        },
        ensure_ascii=False,
    )
    replan = adapt_generation_parameters(
        task_type="planner.propose",
        prompt=replan_prompt,
        parameters={
            "provider": "deepseek",
            "model": DEEPSEEK_V4_FLASH,
            "generation_mode": "auto",
            "latency_target": "balanced",
            "thinking": "disabled",
        },
    )

    assert replan["model"] == DEEPSEEK_V4_PRO
    assert replan["thinking"] == "enabled"
    assert replan["reasoning_effort"] == "medium"
    assert replan["generation_policy"]["assessment"]["task_difficulty"] == "replan"


def test_phase115_finance_campaign_uses_profile_facets_from_research_policy():
    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-finance",
            query="Oracle Corporation revenue cash flow valuation",
            max_queries=24,
            max_sources=200,
            max_fetches=80,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "research_task_kind": "finance_fundamentals_research",
            },
        ),
        research_profile=profile_by_id(FINANCE_FUNDAMENTALS_PROFILE_ID),
    )

    joined = "\n".join(query.lower() for query in campaign.queries)
    assert "annual report" in joined or "10-k" in joined
    assert "cash flow" in joined
    assert "market cap" in joined or "pe ratio" in joined or "valuation" in joined
    assert "revenue" in campaign.diagnostics["profile_facets"]


def test_phase115_mission_directive_carries_real_attempted_queries_not_evidence_preview():
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-q",
        run_id="run-q",
        step_id=None,
        kind="retrieval_report",
        data={
            "report_id": "report-q",
            "goal_id": "goal-q",
            "status": "insufficient_evidence",
            "preview": "irrelevant extracted evidence preview",
            "diagnostics": {
                "goal_query": "Citadel Security scale operations",
                "search_summaries": [
                    {"query": "Citadel Security company size employees revenue", "status": "ok", "source_count": 5},
                    {"query": '"Citadel Security" official source', "status": "empty", "source_count": 0},
                ],
            },
        },
    )
    result = AgentRuntimeResult(
        status="failed",
        task_id="task-q",
        run_id="run-q",
        mode="retrieval_answer",
        recipe_id="recipe-retrieval-answer",
        final_answer=None,
        failure_report={
            "reason": "insufficient_evidence",
            "attempted_actions": ["retrieval.run"],
            "attempted_sources": [],
            "missing_evidence": ["operations_evidence"],
            "last_observations": [],
            "user_help_needed": False,
            "next_possible_action": "refine_query_or_add_sources",
            "task_id": "task-q",
            "run_id": "run-q",
            "trace_refs": [],
        },
        trace_refs=[],
    )
    mission = MissionState(
        mission_id="mission-q",
        thread_id="thread-q",
        root_goal="Research Citadel Security scale and operations",
        status="running",
        requirements=[{"requirement_id": "req-1", "text": "operations_evidence", "status": "open"}],
        coverage_map={"missing_requirements": ["operations_evidence"], "evidence_refs": [], "citation_refs": []},
        attempted_strategies=[],
        open_gaps=["operations_evidence"],
        blocked_reasons=[],
        iteration_count=0,
        metadata={},
    )

    _, assessment = MissionSupervisor(journal=journal).assess(mission, result, index=1)

    avoid_repeating = assessment.next_directive["avoid_repeating"]
    assert "Citadel Security company size employees revenue" in avoid_repeating
    assert '"Citadel Security" official source' in avoid_repeating
    assert "irrelevant extracted evidence preview" not in avoid_repeating


def test_phase115_live_retrieval_default_is_adaptive_so_payload_strategy_can_drive_depth():
    config = LiveRetrievalConfig.from_env({"HOLO_V3_LIVE_RETRIEVAL": "1"})
    operator = config.build_operator()

    capability = operator.provider_capabilities()[0]
    diagnostics = capability["diagnostics"]

    assert config.safe_diagnostics()["search_strategy"] == "adaptive"
    assert capability["provider_id"] == "adaptive_search"
    assert "aggregate" in diagnostics["supported_strategies"]
    assert diagnostics["default_strategy"] == "fallback"


def test_phase115_cli_research_profile_metadata_uses_deep_aggregate_campaign_defaults():
    metadata = _research_metadata(ACADEMIC_RESEARCH_PROFILE_ID)

    assert metadata["research_profile"] == ACADEMIC_RESEARCH_PROFILE_ID
    assert metadata["research_depth"] == "deep"
    assert metadata["search_strategy"] == "aggregate"
    assert metadata["query_campaign"] == "auto"


def test_phase115_fetch_queue_skips_discovery_sources_before_applying_source_limit():
    query = "hyperbolic dynamics recent paper open problem"
    paper_uri = "https://www.cambridge.org/core/journals/ergodic-theory-and-dynamical-systems/article/hyperbolic-dynamics-paper"
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_ListSearchProvider(
            [
                SearchSource(
                    source_id="discovery-search",
                    uri="https://arxiv.org/search/?query=hyperbolic+dynamics",
                    title="Hyperbolic dynamics arXiv search",
                    snippet="Search page for hyperbolic dynamics recent papers.",
                    provider="fixture",
                    metadata={"source_kind": "scholarly_search"},
                ),
                SearchSource(
                    source_id="paper-document",
                    uri=paper_uri,
                    title="A recent paper on hyperbolic dynamics",
                    snippet="Open problems and recent results in hyperbolic dynamics.",
                    provider="fixture",
                    metadata={},
                ),
            ]
        ),
        fetch_provider=FakeFetchProvider(
            {
                paper_uri: (
                    "This recent paper studies hyperbolic dynamics, frontier questions, "
                    "and open problems in the field."
                )
            }
        ),
    )

    operator.run(
        SearchGoal(
            goal_id="goal-fetchable-after-discovery",
            query=query,
            max_queries=1,
            max_sources=1,
            max_fetches=1,
            metadata={"research_profile": ACADEMIC_RESEARCH_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-fetchable-after-discovery",
        run_id="run-fetchable-after-discovery",
    )

    fetches = journal.records(task_id="task-fetchable-after-discovery", kind="retrieval_fetch_attempt")
    ranking = journal.records(task_id="task-fetchable-after-discovery", kind="retrieval_rank_sources")[0].data

    assert [record.data["uri"] for record in fetches] == [paper_uri]
    assert ranking["diagnostics"]["rejected_ranked_source_count"] >= 1


def test_phase115_discovery_expansion_turns_arxiv_search_into_fetchable_document_candidate():
    query = "hyperbolic dynamics frontier research open problems"
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=_ListSearchProvider(
            [
                SearchSource(
                    source_id="arxiv-discovery",
                    uri="https://arxiv.org/search/?query=hyperbolic+dynamics&searchtype=all",
                    title="arXiv search for hyperbolic dynamics",
                    snippet="arXiv search entry point for recent scholarly preprints and survey papers.",
                    provider="fixture",
                    metadata={
                        "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                        "source_family": "scholarly_preprint",
                        "authority_level": "primary",
                        "source_kind": "scholarly_search",
                    },
                )
            ]
        ),
        fetch_provider=_PrefixFetchProvider(
            "https://export.arxiv.org/api/query?",
            (
                "<feed><entry><title>Recent advances in hyperbolic dynamics</title>"
                "<summary>This paper surveys hyperbolic dynamics, frontier research, "
                "open problems, recent papers, and scholarly literature.</summary>"
                "<id>https://arxiv.org/abs/2601.00001</id></entry></feed>"
            ),
            mime_type="application/atom+xml",
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-arxiv-expansion",
            query=query,
            max_queries=1,
            max_sources=4,
            max_fetches=4,
            max_spans_per_document=3,
            metadata={
                "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                "research_task_kind": "frontier_research",
            },
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-arxiv-expansion",
        run_id="run-arxiv-expansion",
    )

    expansion = journal.records(task_id="task-arxiv-expansion", kind="retrieval_discovery_expansion")[0].data
    fetches = journal.records(task_id="task-arxiv-expansion", kind="retrieval_fetch_attempt")
    critic = journal.records(task_id="task-arxiv-expansion", kind="retrieval_operator_critic")[-1].data

    assert expansion["expanded_source_count"] >= 1
    assert any("export.arxiv.org/api/query" in record.data["uri"] for record in fetches)
    assert report.diagnostics["discovery_expanded_source_count"] >= 1
    assert report.status == "sufficient"
    assert report.diagnostics["next_tool_actions"] == []
    graph = report.diagnostics["research_graph"]
    assert graph["diagnostics"]["expansion_count"] >= 1
    assert graph["diagnostics"]["document_count"] >= 1
    assert graph["diagnostics"]["next_tool_action_count"] == 0
    assert critic["next_strategy_hint"] == "finalize_if_requirements_covered"
    assert critic["next_tool_actions"] == []


def test_phase115_retrieval_behavior_benchmark_reports_live_run_metrics_without_fixed_answer():
    journal = JournalStore.in_memory()
    for index, query in enumerate(["alpha", "alpha", "beta"], start=1):
        journal.append(
            task_id="task-benchmark",
            run_id="run-benchmark",
            step_id=f"step-search-{index}",
            kind="retrieval_search_attempt",
            data={"query": query, "status": "ok", "sources": []},
        )
    for index, status in enumerate(["ok", "failed"], start=1):
        journal.append(
            task_id="task-benchmark",
            run_id="run-benchmark",
            step_id=f"step-fetch-{index}",
            kind="retrieval_fetch_attempt",
            data={"fetch_id": f"fetch-{index}", "source_id": f"source-{index}", "status": status},
        )
    journal.append(
        task_id="task-benchmark",
        run_id="run-benchmark",
        step_id="step-evidence",
        kind="retrieval_evidence",
        data={"evidence_id": "ev-1"},
    )
    journal.append(
        task_id="task-benchmark",
        run_id="run-benchmark",
        step_id="step-citation",
        kind="retrieval_citation",
        data={"citation_id": "cite-1"},
    )
    journal.append(
        task_id="task-benchmark",
        run_id="run-benchmark",
        step_id="step-report",
        kind="retrieval_report",
        data={
            "status": "insufficient_evidence",
            "diagnostics": {
                "failure_attribution": {
                    "primary_failure_mode": "coverage_gap",
                    "next_strategy_hint": "target_missing_facets_with_new_queries",
                },
                "next_tool_actions": [{"action": "diversify_acquisition_plan"}],
                "research_graph": {"diagnostics": {"document_count": 1}},
            },
        },
    )

    benchmark = retrieval_behavior_benchmark(journal, "task-benchmark")

    assert benchmark["schema"] == "holo.kernel_v3.retrieval_behavior_benchmark.v1"
    assert benchmark["status"] == "retrieval_insufficient_evidence"
    assert benchmark["query_count"] == 3
    assert benchmark["unique_query_count"] == 2
    assert benchmark["query_repetition_rate"] > 0
    assert benchmark["fetch_success_rate"] == 0.5
    assert benchmark["latest_failure_mode"] == "coverage_gap"
    assert benchmark["latest_next_tool_actions"][0]["action"] == "diversify_acquisition_plan"


def test_phase115_workspace_observation_hides_holo_internal_state(tmp_path):
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "thread.jsonl").write_text("internal", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "notes.md").write_text("internal", encoding="utf-8")
    (tmp_path / ".holo-v3-journal.jsonl").write_text("internal", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("public workspace note", encoding="utf-8")
    registry = ToolRegistry.with_permissioned_workspace(
        root=tmp_path,
        artifact_store=ArtifactStore.in_memory(),
    )

    list_action = CandidateAction(
        action_id="act-list",
        kind="tool",
        name="workspace.list",
        description="list",
        payload={"path": "."},
        reasons=[],
        score=1.0,
        side_effect_class="read",
    )
    search_action = CandidateAction(
        action_id="act-search",
        kind="tool",
        name="workspace.search",
        description="search",
        payload={"query": "internal"},
        reasons=[],
        score=1.0,
        side_effect_class="read",
    )
    read_action = CandidateAction(
        action_id="act-read-hidden",
        kind="tool",
        name="file.read",
        description="read",
        payload={"path": ".state/thread.jsonl"},
        reasons=[],
        score=1.0,
        side_effect_class="read",
    )
    listing = registry.execute_with_artifacts(list_action, policy_decision=_allowed_decision(list_action)).observation
    search = registry.execute_with_artifacts(search_action, policy_decision=_allowed_decision(search_action)).observation
    read_hidden = registry.execute_with_artifacts(read_action, policy_decision=_allowed_decision(read_action)).observation

    listed_paths = {entry["path"] for entry in listing.content["entries"]}
    assert listed_paths == {"visible.txt"}
    assert search.content["matches"] == []
    assert read_hidden.status == "failed"


class _ListSearchProvider:
    provider_id = "list_search"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, sources: list[SearchSource]) -> None:
        self.sources = list(sources)

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        return list(self.sources)


class _PrefixFetchProvider:
    provider_id = "prefix_fetch"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, prefix: str, body: str, *, mime_type: str = "text/plain") -> None:
        self.prefix = prefix
        self.body = body
        self.mime_type = mime_type

    def fetch(self, source: SearchSource) -> FetchResponse:
        if source.uri.startswith(self.prefix):
            return FetchResponse(status="ok", body=self.body, mime_type=self.mime_type)
        return FetchResponse(status="failed", body="", diagnostics={"reason": "unexpected_uri", "uri": source.uri})


def _allowed_decision(action: CandidateAction) -> PolicyDecision:
    return PolicyDecision(
        decision_id=f"policy-{action.action_id}",
        run_id="run-test",
        action_id=action.action_id,
        allowed=True,
        reason="allowed",
        constraints={"permission": "test", "tool_name": action.name, "side_effect_class": action.side_effect_class},
    )
