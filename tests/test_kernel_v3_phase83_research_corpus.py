import json

from kernel_v3.context import ArtifactStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore, finance_fundamentals_profile
from kernel_v3.research.corpus import corpus_document_from_retrieval
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.journal import JournalStore


RAW_ONLY_SENTINEL = "RAW_CORPUS_BODY_ONLY_SECRET"


def test_phase83_corpus_store_records_rebuilds_and_searches_safe_document_metadata(tmp_path) -> None:
    log_path = tmp_path / "corpus.jsonl"
    index_path = tmp_path / "corpus.sqlite"
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    document = _document(
        source=source,
        artifact_id="artifact-sec",
        payload_hash="hash-sec",
        preview="AAPL annual report revenue preview.",
    )
    assessment = assess_search_source(source, profile=finance_fundamentals_profile())
    store = ResearchCorpusStore(log_path=log_path, index_path=index_path, clock_ms=lambda: 101)

    recorded = store.record_document(
        corpus_document_from_retrieval(
            document=document,
            source=source,
            goal=SearchGoal(
                goal_id="goal-aapl",
                query="AAPL revenue",
                metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
            ),
            task_id="task-1",
            run_id="run-1",
            fetched_at_ms=101,
            source_assessment=assessment,
        )
    )
    repeated = store.record_document(recorded)

    assert repeated.document_id == recorded.document_id
    assert len(store.audit_records()) == 1
    assert store.search("revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID).total == 1
    assert store.search("not-present").total == 0
    assert store.index_documents()[0]["source_family"] == "regulatory_filing"

    reloaded = ResearchCorpusStore(log_path=log_path, index_path=index_path, clock_ms=lambda: 202)
    assert reloaded.get(recorded.document_id) is not None
    assert reloaded.search("annual report").documents[0]["document_id"] == recorded.document_id
    assert reloaded.index_documents()[0]["usable_as_primary"] == 1


def test_phase83_retrieval_indexes_fetched_documents_when_corpus_store_is_configured() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 303)
    uri = "https://www.sec.gov/Archives/edgar/data/320193/filing.htm"
    body = "AAPL 2024 10-K revenue from annual report. " + ("x" * 240) + RAW_ONLY_SENTINEL
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL 2024 10-K revenue": [
                    _source(
                        "src-sec",
                        uri,
                        "Apple Form 10-K",
                        "AAPL 2024 10-K revenue.",
                        metadata={"raw_response": RAW_ONLY_SENTINEL, "nested": {"body": RAW_ONLY_SENTINEL}},
                    )
                ]
            }
        ),
        fetch_provider=FakeFetchProvider({uri: body}),
        corpus_store=corpus,
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-corpus",
            query="AAPL 2024 10-K revenue",
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-corpus",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert RAW_ONLY_SENTINEL in str(artifacts.read_blob(report.artifact_refs[0]))
    indexed = corpus.documents(profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID)
    assert len(indexed) == 1
    assert indexed[0].artifact_id == report.artifact_refs[0]
    assert indexed[0].source_assessment is not None
    assert indexed[0].source_assessment["usable_as_primary"] is True
    assert corpus.search("revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID).total == 1

    encoded_corpus = json.dumps(corpus.audit_records(), ensure_ascii=False)
    encoded_journal = json.dumps([record.to_dict() for record in journal.records(task_id="task-corpus")], ensure_ascii=False)
    assert RAW_ONLY_SENTINEL not in encoded_corpus
    assert RAW_ONLY_SENTINEL not in encoded_journal
    assert journal.records(task_id="task-corpus", kind="retrieval_corpus_document")


def test_phase83_retrieval_without_corpus_store_keeps_existing_journal_shape() -> None:
    journal = JournalStore.in_memory()
    uri = "https://www.sec.gov/Archives/edgar/data/320193/filing.htm"

    RetrievalOperator(
        search_provider=FakeSearchProvider(
            {"AAPL revenue": [_source("src-sec", uri, "Apple Form 10-K", "AAPL revenue.")]}
        ),
        fetch_provider=FakeFetchProvider({uri: "AAPL revenue from annual report."}),
    ).run(
        SearchGoal(goal_id="goal-no-corpus", query="AAPL revenue", max_spans_per_document=1),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-no-corpus",
        run_id="run-1",
    )

    assert not journal.records(task_id="task-no-corpus", kind="retrieval_corpus_document")


def _source(
    source_id: str,
    uri: str,
    title: str,
    snippet: str,
    *,
    metadata: dict | None = None,
) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider="fake",
        metadata=dict(metadata or {}),
    )


def _document(*, source: SearchSource, artifact_id: str, payload_hash: str, preview: str) -> FetchedDocument:
    return FetchedDocument(
        document_id=f"doc-{source.source_id}",
        goal_id="goal-aapl",
        source_id=source.source_id,
        uri=source.uri,
        title=source.title,
        artifact_id=artifact_id,
        payload_hash=payload_hash,
        preview=preview,
        size_bytes=len(preview.encode("utf-8")),
        metadata={"mime_type": "text/plain"},
    )
