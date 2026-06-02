import json
from pathlib import Path

from kernel_v3.context import ArtifactStore, ContextCompiler
from kernel_v3.contracts import CandidateAction
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.retrieval import (
    FakeFetchProvider,
    FakeSearchProvider,
    FetchResponse,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
    register_retrieval_tool,
)
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry
from kernel_v3.trace import TraceRenderer


RAW_ONLY_SENTINEL = "RAW_BODY_ONLY_SECRET"


def test_phase4_retrieval_fsm_journals_all_steps_and_keeps_raw_body_in_artifact_store():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = _operator(
        body=(
            "Holo Kernel v3 retrieval cites bounded evidence with artifact backed citations. "
            + "x" * 240
            + RAW_ONLY_SENTINEL
        )
    )

    report = operator.run(
        SearchGoal(goal_id="goal-1", query="Kernel v3 retrieval", max_spans_per_document=1),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-1",
        run_id="run-1",
        step_id_prefix="phase4",
    )

    kinds = [record.kind for record in journal.records(task_id="task-1")]
    assert kinds == [
        "retrieval_query_plan",
        "retrieval_search_attempt",
        "retrieval_rank_sources",
        "retrieval_fetch_attempt",
        "retrieval_extraction",
        "retrieval_evidence",
        "retrieval_citation",
        "retrieval_evaluation_decision",
        "retrieval_report",
    ]
    assert report.status == "sufficient"
    assert report.artifact_refs
    artifact_id = report.artifact_refs[0]
    assert artifacts.read_blob(artifact_id).endswith(RAW_ONLY_SENTINEL)
    assert RAW_ONLY_SENTINEL not in json.dumps(
        [record.to_dict() for record in journal.records(task_id="task-1")],
        ensure_ascii=False,
    )
    trace = TraceRenderer(journal).render_retrieval_trace("task-1")
    assert "query_plan=plan-goal-1" in trace
    assert "search=search-goal-1-1 status=ok" in trace
    assert "fetch=fetch-goal-1-1 status=ok" in trace
    assert "evidence=evidence-" in trace
    assert "citation=cite-" in trace
    assert "evaluation=eval-goal-1 sufficient=True" in trace
    assert "report=report-goal-1 status=sufficient" in trace
    assert RAW_ONLY_SENTINEL not in trace


def test_phase4_retrieval_bounds_sources_fetches_and_spans():
    sources = [
        _source("src-1", "https://example.test/one", "Kernel v3 retrieval", "best source"),
        _source("src-2", "https://example.test/two", "Kernel v3 retrieval", "second source"),
        _source("src-3", "https://example.test/three", "Kernel v3 retrieval", "third source"),
    ]
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"Kernel v3 retrieval": sources}),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.test/one": "Kernel v3 retrieval first match. retrieval second match.",
                "https://example.test/two": "Kernel v3 retrieval second document.",
            }
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-bounds",
            query="Kernel v3 retrieval",
            max_sources=2,
            max_fetches=1,
            max_spans_per_document=1,
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-bounds",
        run_id="run-1",
    )

    search = journal.records(task_id="task-bounds", kind="retrieval_search_attempt")[0]
    plan = journal.records(task_id="task-bounds", kind="retrieval_query_plan")[0]
    ranking = journal.records(task_id="task-bounds", kind="retrieval_rank_sources")[0]
    assert plan.data["diagnostics"]["network_access"] is False
    assert plan.data["diagnostics"]["budget"] == {
        "max_queries": 1,
        "max_sources": 2,
        "max_fetches": 1,
        "max_spans_per_document": 1,
    }
    capabilities = plan.data["diagnostics"]["provider_capabilities"]
    assert [capability["provider_kind"] for capability in capabilities] == ["search", "fetch"]
    assert [capability["provider_id"] for capability in capabilities] == ["fake_search", "fake_fetch"]
    assert {capability["live_network"] for capability in capabilities} == {False}
    assert len(search.data["sources"]) == 2
    assert len(ranking.data["ranked_sources"]) == 2
    assert len(journal.records(task_id="task-bounds", kind="retrieval_fetch_attempt")) == 1
    assert len(journal.records(task_id="task-bounds", kind="retrieval_evidence")) == 1
    assert report.diagnostics["fetch_attempt_count"] == 1
    assert report.diagnostics["network_access"] is False
    assert report.diagnostics["budget"]["max_fetches"] == 1
    assert report.diagnostics["provider_capabilities"] == capabilities


def test_phase4_retrieval_operator_clamps_oversized_goal_budgets():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    sources = [
        _source(
            f"src-{index}",
            f"https://example.test/kernel-v3/{index}",
            f"Kernel v3 source {index}",
            "Kernel v3 retrieval evidence.",
        )
        for index in range(30)
    ]
    responses = {
        source.uri: f"Kernel v3 retrieval evidence from source {source.source_id}."
        for source in sources
    }
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"Kernel v3 retrieval": sources}),
        fetch_provider=FakeFetchProvider(responses),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-oversized-budget",
            query="Kernel v3 retrieval",
            max_queries=99_999,
            max_sources=99_999,
            max_fetches=99_999,
            max_spans_per_document=99_999,
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-oversized-budget",
        run_id="run-1",
    )

    plan = journal.records(task_id="task-oversized-budget", kind="retrieval_query_plan")[0].data
    assert plan["diagnostics"]["budget"] == {
        "max_queries": 256,
        "max_sources": 10_000,
        "max_fetches": 4_096,
        "max_spans_per_document": 128,
    }
    assert plan["diagnostics"]["requested_budget"] == {
        "max_queries": 99_999,
        "max_sources": 99_999,
        "max_fetches": 99_999,
        "max_spans_per_document": 99_999,
    }
    assert plan["diagnostics"]["budget_clamped"] is True
    assert len(journal.records(task_id="task-oversized-budget", kind="retrieval_fetch_attempt")) == 30
    assert report.diagnostics["budget"] == plan["diagnostics"]["budget"]
    assert report.diagnostics["requested_budget"] == plan["diagnostics"]["requested_budget"]


def test_phase4_retrieval_deduplicates_repeated_query_terms():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"Kernel Kernel": [_source("src-1", "https://example.test/dup", "Kernel", "Kernel")]}
        ),
        fetch_provider=FakeFetchProvider({"https://example.test/dup": "Kernel appears once."}),
    ).run(
        SearchGoal(goal_id="goal-duplicate-terms", query="Kernel Kernel", max_spans_per_document=4),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-duplicate-terms",
        run_id="run-1",
    )

    assert len(journal.records(task_id="task-duplicate-terms", kind="retrieval_evidence")) == 1


def test_phase4_retrieval_reports_insufficient_evidence_for_empty_search_fetch_or_extract():
    empty_search = RetrievalOperator(
        search_provider=FakeSearchProvider({"missing": []}),
        fetch_provider=FakeFetchProvider({}),
    ).run(
        SearchGoal(goal_id="goal-empty", query="missing"),
        journal=JournalStore.in_memory(),
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-empty",
        run_id="run-1",
    )
    assert empty_search.status == "insufficient_evidence"

    failed_fetch_journal = JournalStore.in_memory()
    failed_fetch = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"Kernel": [_source("src-1", "https://example.test/missing", "Kernel", "")]}
        ),
        fetch_provider=FakeFetchProvider({}),
    ).run(
        SearchGoal(goal_id="goal-fetch-fail", query="Kernel"),
        journal=failed_fetch_journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-fetch-fail",
        run_id="run-1",
    )
    assert failed_fetch.status == "insufficient_evidence"
    assert failed_fetch_journal.records(task_id="task-fetch-fail", kind="retrieval_fetch_attempt")[0].data["status"] == "failed"

    empty_extract = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"Kernel": [_source("src-1", "https://example.test/nohit", "Kernel", "")]}
        ),
        fetch_provider=FakeFetchProvider(
            {"https://example.test/nohit": FetchResponse(status="ok", body="unrelated body")}
        ),
    ).run(
        SearchGoal(goal_id="goal-no-extract", query="Kernel"),
        journal=JournalStore.in_memory(),
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-no-extract",
        run_id="run-1",
    )
    assert empty_extract.status == "insufficient_evidence"


def test_phase4_retrieval_provider_errors_are_journaled_not_raised():
    search_journal = JournalStore.in_memory()
    search_report = RetrievalOperator(
        search_provider=RaisingSearchProvider(),
        fetch_provider=FakeFetchProvider({}),
    ).run(
        SearchGoal(goal_id="goal-search-error", query="Kernel"),
        journal=search_journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-search-error",
        run_id="run-1",
    )

    search_attempt = search_journal.records(task_id="task-search-error", kind="retrieval_search_attempt")[0]
    assert search_report.status == "insufficient_evidence"
    assert search_attempt.data["status"] == "failed"
    assert search_attempt.data["diagnostics"]["error"] == "RuntimeError"
    assert search_journal.records(task_id="task-search-error", kind="retrieval_report")

    fetch_journal = JournalStore.in_memory()
    fetch_report = RetrievalOperator(
        search_provider=FakeSearchProvider({"Kernel": [_source("src-1", "https://example.test/error", "Kernel", "")]}),
        fetch_provider=RaisingFetchProvider(),
    ).run(
        SearchGoal(goal_id="goal-fetch-error", query="Kernel"),
        journal=fetch_journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-fetch-error",
        run_id="run-1",
    )

    fetch_attempt = fetch_journal.records(task_id="task-fetch-error", kind="retrieval_fetch_attempt")[0]
    assert fetch_report.status == "insufficient_evidence"
    assert fetch_attempt.data["status"] == "failed"
    assert fetch_attempt.data["diagnostics"]["error"] == "RuntimeError"
    assert fetch_journal.records(task_id="task-fetch-error", kind="retrieval_report")


def test_phase4_retrieval_sanitizes_provider_metadata_and_diagnostics_raw_fields():
    sentinel = "PROVIDER_RAW_SENTINEL"
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    source = SearchSource(
        source_id="src-raw",
        uri="https://example.test/raw",
        title="Kernel",
        snippet="Kernel",
        provider="fake",
        metadata={"raw_body": sentinel, "nested": {"body_preview": sentinel}},
    )

    report = RetrievalOperator(
        search_provider=FakeSearchProvider({"Kernel": [source]}),
        fetch_provider=FakeFetchProvider(
            {
                "https://example.test/raw": FetchResponse(
                    status="ok",
                    body="Kernel public extracted span.",
                    diagnostics={"raw_response": sentinel, "nested": {"body": sentinel}},
                )
            }
        ),
    ).run(
        SearchGoal(goal_id="goal-sanitize", query="Kernel"),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-sanitize",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    encoded = json.dumps([record.to_dict() for record in journal.records(task_id="task-sanitize")], ensure_ascii=False)
    assert sentinel not in encoded
    assert artifacts.read_blob(report.artifact_refs[0]) == "Kernel public extracted span."


def test_phase4_retrieval_tool_uses_generic_registry_dispatch_without_loop_branches():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry.with_builtin_respond()
    register_retrieval_tool(
        registry,
        operator=_operator(body="Kernel v3 retrieval evidence for generic tool dispatch."),
        journal=journal,
        artifact_store=artifacts,
    )
    action = CandidateAction(
        action_id="act-retrieval",
        kind="tool",
        name="retrieval.run",
        description="run retrieval",
        score=1.0,
        payload={
            "task_id": "stale-task",
            "run_id": "stale-run",
            "query": "Kernel v3 retrieval",
            "goal_id": "goal-tool",
        },
        reasons=["phase4 fake retrieval"],
        side_effect_class="read",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write"),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("retrieval complete"),
    )

    result = loop.run("retrieve bounded evidence")

    assert result.status == "completed"
    assert registry.executed_actions == [action]
    assert journal.records(task_id=result.task_id, kind="retrieval_report")
    assert journal.records(task_id="stale-task", kind="retrieval_report") == []
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert observation.artifact_refs
    assert observation.data["content"]["report"]["status"] == "sufficient"
    loop_source = Path("kernel_v3/loop.py").read_text(encoding="utf-8")
    assert "web_search" not in loop_source
    assert "page_open" not in loop_source
    assert "retrieval.run" not in loop_source


def test_phase4_live_capable_retrieval_manifest_is_network_budgeted_before_fetch():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry()
    fetch_provider = LiveNetworkFetchProvider()
    operator = RetrievalOperator(
        search_provider=LiveNetworkSearchProvider(),
        fetch_provider=fetch_provider,
    )
    register_retrieval_tool(
        registry,
        operator=operator,
        journal=journal,
        artifact_store=artifacts,
    )
    action = CandidateAction(
        action_id="act-live-retrieval",
        kind="tool",
        name="retrieval.run",
        description="run live-capable retrieval",
        score=1.0,
        payload={"query": "Kernel v3 retrieval", "goal_id": "goal-live-budget"},
        reasons=["network-capable retrieval"],
        side_effect_class="read",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("should not execute"),
        max_network_fetches=0,
    )

    result = loop.run("retrieve live evidence")

    manifest = registry.manifest_for_action(action)
    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    assert manifest.side_effect_class == "network"
    assert result.stop_reason == "max_network_fetches"
    assert observation.data["content"]["reason"] == "max_network_fetches"
    assert fetch_provider.called is False


def test_phase4_network_budget_accounts_for_declared_fetch_cost_before_execution():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry()
    fetch_provider = LiveNetworkFetchProvider()
    operator = RetrievalOperator(
        search_provider=LiveNetworkSearchProvider(),
        fetch_provider=fetch_provider,
    )
    register_retrieval_tool(
        registry,
        operator=operator,
        journal=journal,
        artifact_store=artifacts,
    )
    action = CandidateAction(
        action_id="act-live-retrieval-cost",
        kind="tool",
        name="retrieval.run",
        description="run live-capable retrieval with multiple fetches",
        score=1.0,
        payload={
            "query": "Kernel v3 retrieval",
            "goal_id": "goal-live-budget-cost",
            "max_fetches": 3,
        },
        reasons=["network-capable retrieval"],
        side_effect_class="read",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("should not execute"),
        max_network_fetches=1,
    )

    result = loop.run("retrieve live evidence")

    observation = journal.records(task_id=result.task_id, kind="observation")[0]
    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert result.stop_reason == "max_network_fetches"
    assert observation.data["content"]["reason"] == "max_network_fetches"
    assert guard.data["network_fetches"] == 0
    assert guard.data["requested_network_fetches"] == 3
    assert guard.data["projected_network_fetches"] == 3
    assert guard.data["max_network_fetches"] == 1
    assert fetch_provider.called is False


def test_phase4_network_budget_uses_bounded_preflight_and_actual_fetch_attempts():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry.with_builtin_respond()
    fetch_provider = LiveNetworkFetchProvider()
    operator = RetrievalOperator(
        search_provider=LiveNetworkSearchProvider(),
        fetch_provider=fetch_provider,
    )
    register_retrieval_tool(
        registry,
        operator=operator,
        journal=journal,
        artifact_store=artifacts,
    )
    retrieval_action = CandidateAction(
        action_id="act-live-retrieval-large-declared-budget",
        kind="tool",
        name="retrieval.run",
        description="run live-capable retrieval with roomy declared budget",
        score=1.0,
        payload={
            "query": "Kernel v3 retrieval",
            "goal_id": "goal-live-large-declared-budget",
            "max_sources": 5,
            "max_fetches": 4096,
        },
        reasons=["network-capable retrieval"],
        side_effect_class="read",
    )
    respond_action = CandidateAction(
        action_id="act-budget-followup-response",
        kind="respond",
        name=None,
        description="summarize observed retrieval state",
        score=1.0,
        payload={"text": "retrieval observed"},
        reasons=["budget did not abort loop"],
        side_effect_class="none",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([retrieval_action, respond_action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator(
            [
                {"status": "continue", "stop_reason": None, "answer": None, "missing_evidence": ["continue"]},
                {"status": "final_answer_ready", "stop_reason": "completed", "answer": "done", "missing_evidence": []},
            ]
        ),
        max_network_fetches=6,
    )

    result = loop.run("retrieve live evidence")

    assert result.status == "completed"
    assert fetch_provider.called is True
    assert not journal.records(task_id=result.task_id, kind="guard")
    observations = journal.records(task_id=result.task_id, kind="observation")
    assert [item.data["source"] for item in observations] == ["tool:retrieval.run", "respond"]


def test_phase4_network_budget_uses_manifest_default_fetch_cost_when_payload_omits_cost():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry()
    fetch_provider = LiveNetworkFetchProvider()
    operator = RetrievalOperator(
        search_provider=LiveNetworkSearchProvider(),
        fetch_provider=fetch_provider,
    )
    register_retrieval_tool(
        registry,
        operator=operator,
        journal=journal,
        artifact_store=artifacts,
    )
    action = CandidateAction(
        action_id="act-live-retrieval-default-cost",
        kind="tool",
        name="retrieval.run",
        description="run live-capable retrieval with default fetch cost",
        score=1.0,
        payload={"query": "Kernel v3 retrieval", "goal_id": "goal-live-budget-default-cost"},
        reasons=["network-capable retrieval"],
        side_effect_class="read",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("should not execute"),
        max_network_fetches=1,
    )

    result = loop.run("retrieve live evidence")

    guard = journal.records(task_id=result.task_id, kind="guard")[0]
    assert result.stop_reason == "max_network_fetches"
    assert guard.data["requested_network_fetches"] == 3
    assert fetch_provider.called is False


def test_phase4_network_budget_ignores_model_supplied_network_fetch_count_when_manifest_declares_cost_field():
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    registry = ToolRegistry()
    fetch_provider = LiveNetworkFetchProvider()
    operator = RetrievalOperator(
        search_provider=LiveNetworkSearchProvider(),
        fetch_provider=fetch_provider,
    )
    register_retrieval_tool(
        registry,
        operator=operator,
        journal=journal,
        artifact_store=artifacts,
    )
    action = CandidateAction(
        action_id="act-live-retrieval-host-cost",
        kind="tool",
        name="retrieval.run",
        description="run live-capable retrieval with host-owned cost",
        score=1.0,
        payload={
            "query": "Kernel v3 retrieval",
            "goal_id": "goal-live-budget-host-cost",
            "max_fetches": 1,
            "network_fetch_count": 999,
        },
        reasons=["network-capable retrieval"],
        side_effect_class="read",
    )
    loop = LoopControllerV3(
        journal=journal,
        context_compiler=ContextCompiler(),
        planner=FakePlanner([action]),
        policy_gate=PolicyGate(permission="read_write", allowed_permissions={"network:fetch"}),
        tool_registry=registry,
        evaluator=FakeEvaluator.final_answer("retrieval executed"),
        max_network_fetches=2,
    )

    result = loop.run("retrieve live evidence")

    assert result.status == "completed"
    assert fetch_provider.called is True
    assert not journal.records(task_id=result.task_id, kind="guard")


def _operator(*, body: str) -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "Kernel v3 retrieval": [
                    _source(
                        "src-1",
                        "https://example.test/kernel-v3",
                        "Kernel v3 retrieval",
                        "retrieval evidence for Kernel v3",
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({"https://example.test/kernel-v3": body}),
    )


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
    )


class RaisingSearchProvider:
    def search(self, query, *, goal, plan):
        raise RuntimeError("search failed")


class RaisingFetchProvider:
    def fetch(self, source):
        raise RuntimeError("fetch failed")


class LiveNetworkSearchProvider:
    live_network = True

    def search(self, query, *, goal, plan):
        return [_source("src-live", "https://example.test/live", "Kernel", "Kernel")]


class LiveNetworkFetchProvider:
    live_network = True

    def __init__(self):
        self.called = False

    def fetch(self, source):
        self.called = True
        return FetchResponse(status="ok", body="Kernel live retrieval evidence.")
