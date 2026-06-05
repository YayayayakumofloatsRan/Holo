import subprocess
import sys

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.mission.thread_rag import collect_run_delta
from kernel_v3.retrieval.composite import FallbackSearchProvider
from kernel_v3.research import TECHNICAL_DOCUMENTATION_PROFILE_ID, profile_by_id, source_quality_summary
from kernel_v3.research.profiles import ACADEMIC_RESEARCH_PROFILE_ID
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, QueryPlan, RetrievalOperator, SearchGoal, SearchSource


def test_phase114_weak_profile_source_does_not_become_formal_citation() -> None:
    query = "Find the Example API endpoint and authentication method"
    source = SearchSource(
        source_id="forum-api-summary",
        uri="https://forum.example.test/thread/example-api-auth",
        title="Example API authentication forum answer",
        snippet="Endpoint and Bearer API key examples.",
        provider="fake",
        metadata={"source_family": "forum"},
    )
    journal = JournalStore.in_memory()
    report = RetrievalOperator(
        search_provider=FakeSearchProvider({query: [source]}),
        fetch_provider=FakeFetchProvider(
            {
                source.uri: (
                    "The Example API endpoint is https://api.example.test/v1/chat. "
                    "Authentication uses Authorization: Bearer API key."
                )
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-weak-docs",
            query=query,
            max_spans_per_document=2,
            metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-weak-docs",
        run_id="run-1",
    )

    assert report.status == "insufficient_evidence"
    assert report.citation_ids == []
    assert report.diagnostics["failure_attribution"]["primary_failure_mode"] == "source_authority_gap"
    assert report.diagnostics["failure_attribution"]["next_strategy_hint"] == "switch_to_higher_authority_source_family"
    assert report.diagnostics["source_quality"]["authority_sufficient"] is False
    assert report.diagnostics["source_quality"]["weak_source_count"] == 1
    rejections = journal.records(task_id="task-weak-docs", kind="retrieval_evidence_rejections")[-1].data
    assert rejections["diagnostics"]["reasons"]["weak_source_authority_for_research_profile"] == 1
    assert not journal.records(task_id="task-weak-docs", kind="retrieval_citation")


def test_phase114_run_delta_exposes_source_quality_for_next_loop_replanning() -> None:
    query = "Find the Example API endpoint and authentication method"
    source = SearchSource(
        source_id="forum-api-summary",
        uri="https://forum.example.test/thread/example-api-auth",
        title="Example API authentication forum answer",
        snippet="Endpoint and Bearer API key examples.",
        provider="fake",
        metadata={"source_family": "forum"},
    )
    journal = JournalStore.in_memory()
    RetrievalOperator(
        search_provider=FakeSearchProvider({query: [source]}),
        fetch_provider=FakeFetchProvider(
            {
                source.uri: (
                    "The Example API endpoint is https://api.example.test/v1/chat. "
                    "Authentication uses Authorization: Bearer API key."
                )
            }
        ),
    ).run(
        SearchGoal(
            goal_id="goal-run-delta-quality",
            query=query,
            max_spans_per_document=2,
            metadata={"research_profile": TECHNICAL_DOCUMENTATION_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-run-delta-quality",
        run_id="run-1",
    )

    delta = collect_run_delta(journal, task_id="task-run-delta-quality", run_id="run-1")
    compact_report = delta["retrieval_reports"][-1]
    assert compact_report["failure_attribution"]["primary_failure_mode"] == "source_authority_gap"
    assert compact_report["source_quality"]["authority_sufficient"] is False
    assert compact_report["source_quality"]["recommended_next_source_action"] == "switch_to_primary_or_official_source_family"


def test_phase114_source_quality_summary_is_profile_agnostic() -> None:
    primary_source = SearchSource(
        source_id="official-docs",
        uri="https://docs.example.test/api/authentication",
        title="Official API documentation",
        snippet="Endpoint and authentication reference.",
        provider="fake",
        metadata={"source_family": "official_documentation"},
    )
    weak_source = SearchSource(
        source_id="forum-summary",
        uri="https://forum.example.test/api-auth",
        title="Forum API answer",
        snippet="Community answer.",
        provider="fake",
        metadata={"source_family": "forum"},
    )
    profile = profile_by_id(TECHNICAL_DOCUMENTATION_PROFILE_ID)
    assert profile is not None

    summary = source_quality_summary(
        [
            assess_search_source(primary_source, profile=profile),
            assess_search_source(weak_source, profile=profile),
        ],
        authority_requirement="primary",
    )

    assert summary["authority_sufficient"] is True
    assert summary["acceptable_source_count"] == 1
    assert summary["primary_source_count"] == 1
    assert summary["weak_source_count"] == 1


def test_phase114_thread_rag_import_does_not_require_agent_package_preload() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from kernel_v3.mission.thread_rag import collect_run_delta; print(callable(collect_run_delta))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "True"


def test_phase114_fallback_search_continues_past_profile_discovery_only_sources() -> None:
    query = "hyperbolic dynamics frontier research recent papers"
    discovery = SearchSource(
        source_id="arxiv-search",
        uri="https://arxiv.org/search/?query=hyperbolic+dynamics",
        title="arXiv search",
        snippet="Search entry point.",
        provider="source_directory",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "source_family": "scholarly_preprint",
            "source_kind": "scholarly_search",
        },
    )
    paper = SearchSource(
        source_id="arxiv-paper",
        uri="https://arxiv.org/abs/2601.00001",
        title="Recent paper on hyperbolic dynamics",
        snippet="A recent paper about hyperbolic dynamics.",
        provider="arxiv_api",
        metadata={
            "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
            "source_family": "scholarly_preprint",
            "source_kind": "scholarly_preprint",
        },
    )
    provider = FallbackSearchProvider(
        [
            _StaticSearchProvider("source_directory", [discovery]),
            _StaticSearchProvider("arxiv_api", [paper]),
        ]
    )

    result = provider.search(
        query,
        goal=SearchGoal(
            goal_id="goal-academic-fallback",
            query=query,
            metadata={"research_profile": ACADEMIC_RESEARCH_PROFILE_ID},
        ),
        plan=QueryPlan(
            plan_id="plan-academic-fallback",
            goal_id="goal-academic-fallback",
            queries=[query],
            max_sources=5,
            max_fetches=3,
        ),
    )

    diagnostics = provider.search_diagnostics()
    assert [source.source_id for source in result] == ["arxiv-paper"]
    assert diagnostics["selected_provider_id"] == "arxiv_api"
    assert diagnostics["attempts"][0]["status"] == "discovery_only"


class _StaticSearchProvider:
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = ["*"]

    def __init__(self, provider_id: str, sources: list[SearchSource]) -> None:
        self.provider_id = provider_id
        self.sources = sources

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        return list(self.sources)
