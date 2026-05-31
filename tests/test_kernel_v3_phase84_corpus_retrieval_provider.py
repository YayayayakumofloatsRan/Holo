import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore, finance_fundamentals_profile
from kernel_v3.research.corpus import corpus_document_from_retrieval
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import (
    CorpusFetchProvider,
    CorpusSearchProvider,
    FakeFetchProvider,
    FakeSearchProvider,
    FallbackSearchProvider,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
)
from kernel_v3.retrieval.contracts import FetchedDocument


RAW_ONLY_SENTINEL = "RAW_CORPUS_PROVIDER_BODY_ONLY_SECRET"


def test_phase84_corpus_backed_retrieval_reuses_indexed_page_without_network() -> None:
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 404)
    uri = "https://www.sec.gov/Archives/edgar/data/320193/filing.htm"
    body = "AAPL 2024 10-K revenue from annual report. " + ("x" * 240) + RAW_ONLY_SENTINEL
    source = _source("src-sec", uri, "Apple Form 10-K", "AAPL 2024 10-K revenue.")
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload=body,
        metadata={"uri": uri, "source_id": source.source_id, "title": source.title},
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=_document(source=source, artifact_id=artifact.artifact_id, payload_hash=artifact.payload_hash),
            source=source,
            goal=SearchGoal(
                goal_id="goal-seed",
                query="AAPL revenue",
                metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
            ),
            task_id="task-seed",
            run_id="run-seed",
            fetched_at_ms=404,
            source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
        )
    )
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=CorpusSearchProvider(corpus),
        fetch_provider=CorpusFetchProvider(artifacts),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-corpus-reuse",
            query="AAPL 2024 revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-corpus-reuse",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert operator.network_access is False
    capabilities = report.diagnostics["provider_capabilities"]
    assert capabilities[0]["provider_id"] == "research_corpus"
    assert capabilities[0]["profile_aware"] is True
    assert capabilities[0]["supported_research_profiles"] == ["*"]
    assert capabilities[1]["provider_id"] == "research_corpus_fetch"
    search = journal.records(task_id="task-corpus-reuse", kind="retrieval_search_attempt")[0].data
    assert search["sources"][0]["provider"] == "research_corpus"
    assert search["sources"][0]["metadata"]["corpus_document_id"]
    assert search["sources"][0]["metadata"]["source_family"] == "regulatory_filing"
    assert journal.records(task_id="task-corpus-reuse", kind="retrieval_source_assessment")
    assert RAW_ONLY_SENTINEL in str(artifacts.read_blob(report.artifact_refs[0]))
    encoded = json.dumps([record.to_dict() for record in journal.records(task_id="task-corpus-reuse")], ensure_ascii=False)
    assert RAW_ONLY_SENTINEL not in encoded


def test_phase84_corpus_search_provider_filters_by_research_profile() -> None:
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 505)
    finance_source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL revenue.",
    )
    generic_source = _source(
        "src-generic",
        "https://example.com/aapl",
        "AAPL summary",
        "AAPL revenue.",
    )
    _seed_document(
        artifacts=artifacts,
        corpus=corpus,
        source=finance_source,
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    _seed_document(artifacts=artifacts, corpus=corpus, source=generic_source, profile_id=None)

    sources = CorpusSearchProvider(corpus).search(
        "AAPL revenue",
        goal=SearchGoal(
            goal_id="goal-profile-filter",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=_plan_stub(),
    )

    assert [source.uri for source in sources] == [finance_source.uri]


def test_phase84_corpus_search_provider_filters_stale_profile_documents_and_journals_reason() -> None:
    artifacts = ArtifactStore.in_memory()
    profile = finance_fundamentals_profile()
    max_age_ms = int(profile.metadata["freshness_max_age_ms"])
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: max_age_ms + 10_000)
    stale_source = _source(
        "src-stale-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/stale-filing.htm",
        "Stale Apple Form 10-K",
        "AAPL stale revenue.",
    )
    _seed_document(
        artifacts=artifacts,
        corpus=corpus,
        source=stale_source,
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        fetched_at_ms=1,
    )
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=CorpusSearchProvider(corpus),
        fetch_provider=CorpusFetchProvider(artifacts),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-stale-corpus",
            query="AAPL stale revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-stale-corpus",
        run_id="run-1",
    )

    search = journal.records(task_id="task-stale-corpus", kind="retrieval_search_attempt")[0].data
    diagnostics = search["diagnostics"]["provider_diagnostics"]
    assert report.status == "insufficient_evidence"
    assert search["status"] == "empty"
    assert search["sources"] == []
    assert diagnostics["freshness_filter_enabled"] is True
    assert diagnostics["freshness"]["stale_count"] == 1
    assert diagnostics["freshness"]["document_ids"]


def test_phase84_corpus_fetch_provider_fails_closed_when_artifact_is_missing() -> None:
    source = SearchSource(
        source_id="corpus-missing",
        uri="https://example.test/missing",
        title="Missing",
        snippet="Missing",
        provider="research_corpus",
        metadata={"artifact_id": "artifact-missing"},
    )

    response = CorpusFetchProvider(ArtifactStore.in_memory()).fetch(source)

    assert response.status == "failed"
    assert response.body == ""
    assert response.diagnostics["reason"] == "missing_corpus_artifact_ref"


def test_phase84_fallback_search_provider_continues_after_provider_exception() -> None:
    fallback_source = _source(
        "src-fallback-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/fallback.htm",
        "Fallback Apple Form 10-K",
        "AAPL fallback revenue.",
    )
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider(
            [
                _FailingSearchProvider(),
                FakeSearchProvider({"AAPL fallback": [fallback_source]}),
            ]
        ),
        fetch_provider=FakeFetchProvider({fallback_source.uri: "AAPL fallback revenue from 10-K filing."}),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-fallback-search",
            query="AAPL fallback",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-fallback-search",
        run_id="run-1",
    )

    search = journal.records(task_id="task-fallback-search", kind="retrieval_search_attempt")[0].data
    diagnostics = search["diagnostics"]["provider_diagnostics"]
    attempts = diagnostics["attempts"]
    assert report.status == "sufficient"
    assert search["status"] == "ok"
    assert attempts[0]["provider_id"] == "failing_search"
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error"] == "RuntimeError"
    assert attempts[1]["provider_id"] == "fake_search"
    assert attempts[1]["status"] == "ok"
    assert diagnostics["selected_provider_id"] == "fake_search"
    assert diagnostics["status"] == "ok"


def test_phase84_fallback_search_provider_reports_failed_when_all_providers_fail() -> None:
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FallbackSearchProvider([_FailingSearchProvider()]),
        fetch_provider=FakeFetchProvider({}),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-all-provider-fail",
            query="AAPL fallback",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-all-provider-fail",
        run_id="run-1",
    )

    search = journal.records(task_id="task-all-provider-fail", kind="retrieval_search_attempt")[0].data
    diagnostics = search["diagnostics"]["provider_diagnostics"]
    assert report.status == "insufficient_evidence"
    assert search["status"] == "failed"
    assert search["diagnostics"]["error"] == "provider_chain_failed"
    assert diagnostics["status"] == "failed"
    assert diagnostics["selected_provider_id"] is None
    assert diagnostics["attempts"][0]["status"] == "failed"


def _seed_document(
    *,
    artifacts: ArtifactStore,
    corpus: ResearchCorpusStore,
    source: SearchSource,
    profile_id: str | None,
    fetched_at_ms: int = 101,
) -> None:
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload=f"{source.title} {source.snippet}",
        metadata={"uri": source.uri, "source_id": source.source_id, "title": source.title},
    )
    profile = finance_fundamentals_profile() if profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID else None
    corpus.record_document(
        corpus_document_from_retrieval(
            document=_document(source=source, artifact_id=artifact.artifact_id, payload_hash=artifact.payload_hash),
            source=source,
            goal=SearchGoal(
                goal_id=f"goal-{source.source_id}",
                query=source.snippet,
                metadata={"research_profile": profile_id} if profile_id is not None else {},
            ),
            task_id=None,
            run_id="run-seed",
            fetched_at_ms=fetched_at_ms,
            source_assessment=assess_search_source(source, profile=profile) if profile is not None else None,
        )
    )


def _source(source_id: str, uri: str, title: str, snippet: str) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
    )


def _document(*, source: SearchSource, artifact_id: str, payload_hash: str) -> FetchedDocument:
    return FetchedDocument(
        document_id=f"doc-{source.source_id}",
        goal_id="goal-seed",
        source_id=source.source_id,
        uri=source.uri,
        title=source.title,
        artifact_id=artifact_id,
        payload_hash=payload_hash,
        preview=f"{source.title} {source.snippet}",
        size_bytes=len(source.snippet.encode("utf-8")),
        metadata={"mime_type": "text/plain"},
    )


def _plan_stub():
    from kernel_v3.retrieval import QueryPlan

    return QueryPlan(
        plan_id="plan-stub",
        goal_id="goal-profile-filter",
        queries=["AAPL revenue"],
        max_sources=5,
        max_fetches=3,
    )


class _FailingSearchProvider:
    provider_id = "failing_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = [FINANCE_FUNDAMENTALS_PROFILE_ID]

    def search(self, query: str, *, goal: SearchGoal, plan) -> list[SearchSource]:
        raise RuntimeError("raw provider failure must not escape")

    def search_diagnostics(self) -> dict:
        return {"source": "test_failure"}
