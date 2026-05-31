import json
from dataclasses import replace

from kernel_v3.context import ArtifactStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore, finance_fundamentals_profile
from kernel_v3.research.corpus import (
    CORPUS_SAMPLE_LIMIT_CAP,
    CORPUS_SEARCH_LIMIT_CAP,
    corpus_document_from_retrieval,
)
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


def test_phase83_corpus_store_reobserves_same_document_without_conflict(tmp_path) -> None:
    log_path = tmp_path / "corpus.jsonl"
    index_path = tmp_path / "corpus.sqlite"
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-sec",
            payload_hash="hash-sec",
            preview="AAPL annual report revenue preview.",
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-aapl",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-1",
        run_id="run-1",
        fetched_at_ms=101,
        source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
    )
    store = ResearchCorpusStore(log_path=log_path, index_path=index_path, clock_ms=lambda: 303)

    first = store.record_document(document)
    second = store.record_document(replace(document, task_id="task-2", run_id="run-2", fetched_at_ms=202))

    assert second.document_id == first.document_id
    assert second.fetched_at_ms == 202
    assert second.task_id == "task-2"
    assert second.run_id == "run-2"
    assert second.metadata["reobservation_count"] == 1
    assert len(store.documents()) == 1
    assert [event["event_type"] for event in store.audit_records()] == [
        "corpus_document_recorded",
        "corpus_document_reobserved",
    ]
    reloaded = ResearchCorpusStore(log_path=log_path, index_path=index_path)
    assert len(reloaded.documents()) == 1
    assert reloaded.get(document.document_id).fetched_at_ms == 202
    assert reloaded.index_documents()[0]["fetched_at_ms"] == 202


def test_phase83_corpus_status_and_inspection_report_authority_health() -> None:
    strong_source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    weak_source = _source(
        "src-blog",
        "https://example.com/aapl-opinion",
        "AAPL Opinion",
        "Unofficial commentary.",
    )
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: 909)
    for source, artifact_id in ((strong_source, "artifact-sec"), (weak_source, "artifact-blog")):
        store.record_document(
            corpus_document_from_retrieval(
                document=_document(
                    source=source,
                    artifact_id=artifact_id,
                    payload_hash=f"hash-{source.source_id}",
                    preview=source.snippet,
                ),
                source=source,
                goal=SearchGoal(
                    goal_id="goal-aapl",
                    query="AAPL revenue",
                    metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
                ),
                task_id="task-1",
                run_id="run-1",
                fetched_at_ms=909,
                source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
            )
        )

    status = store.status()
    inspection = store.inspect(sample_limit=1)

    assert status.document_count == 2
    assert status.profile_counts[FINANCE_FUNDAMENTALS_PROFILE_ID] == 2
    assert status.source_family_counts["regulatory_filing"] == 1
    assert status.primary_usable_count == 1
    assert status.audit_record_count == 2
    assert inspection.status == "ok"
    assert inspection.samples["documents"][0]["payload_hash"]
    assert "preview" not in inspection.samples["documents"][0]


def test_phase83_corpus_inspection_warns_when_profile_documents_are_stale() -> None:
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    profile = finance_fundamentals_profile()
    max_age_ms = int(profile.metadata["freshness_max_age_ms"])
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: max_age_ms + 10_000)
    document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-sec",
            payload_hash="hash-sec",
            preview=source.snippet,
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-stale-aapl",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-stale",
        run_id="run-stale",
        fetched_at_ms=1,
        source_assessment=assess_search_source(source, profile=profile),
    )
    store.record_document(document)

    inspection = store.inspect(sample_limit=1)

    assert inspection.status == "warning"
    stale = [issue for issue in inspection.issues if issue["code"] == "stale_research_corpus_documents"][0]
    assert stale["profile_id"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert stale["stale_count"] == 1
    assert stale["document_ids"] == [document.document_id]
    assert f"retrieve <query> --profile {FINANCE_FUNDAMENTALS_PROFILE_ID} --index-corpus" in inspection.recommended_actions


def test_phase83_profile_search_can_exclude_stale_documents() -> None:
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    profile = finance_fundamentals_profile()
    max_age_ms = int(profile.metadata["freshness_max_age_ms"])
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: max_age_ms + 10_000)
    document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-sec",
            payload_hash="hash-sec",
            preview=source.snippet,
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-stale-aapl",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-stale",
        run_id="run-stale",
        fetched_at_ms=1,
        source_assessment=assess_search_source(source, profile=profile),
    )
    store.record_document(document)

    all_results = store.search("AAPL revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID)
    fresh_results = store.search("AAPL revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID, exclude_stale=True)
    freshness = store.freshness_summary(profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID, sample_limit=1)

    assert all_results.total == 1
    assert fresh_results.total == 0
    assert freshness["stale_count"] == 1
    assert freshness["document_ids"] == [document.document_id]


def test_phase83_corpus_search_can_audit_access_without_raw_query_or_body() -> None:
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    secret_query = "AAPL revenue api_key=sk_12345678901234567890"
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: 2020)
    document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-sec",
            payload_hash="hash-sec",
            preview="AAPL annual report revenue preview.",
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-audit-corpus",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-audit-corpus",
        run_id="run-audit-corpus",
        fetched_at_ms=2020,
        source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
    )
    store.record_document(document)

    result = store.search(
        secret_query,
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        record_access=True,
        access_context={"surface": "test", "raw_body": RAW_ONLY_SENTINEL},
    )

    search_event = store.audit_records()[-1]
    dumped = json.dumps(store.audit_records(), ensure_ascii=False)
    assert result.total == 1
    assert search_event["event_type"] == "corpus_documents_searched"
    assert search_event["payload"]["profile_id"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert search_event["payload"]["query_hash"]
    assert search_event["payload"]["query_term_count"] == 3
    assert search_event["payload"]["document_ids"] == [document.document_id]
    assert search_event["payload"]["access_context"]["raw_body"] == "[omitted]"
    assert search_event["payload"]["redaction"] == {"query": "hash_only", "documents": "ids_only"}
    assert "sk_12345678901234567890" not in dumped
    assert "api_key" not in dumped
    assert RAW_ONLY_SENTINEL not in dumped


def test_phase83_corpus_metadata_redacts_secret_like_values() -> None:
    source = _source(
        "src-sec-secret-metadata",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    secret_value = "sk_12345678901234567890"
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: 2021)
    document = corpus_document_from_retrieval(
        document=replace(
            _document(
                source=source,
                artifact_id="artifact-sec-secret-metadata",
                payload_hash="hash-sec-secret-metadata",
                preview="AAPL annual report revenue preview.",
            ),
            metadata={
                "mime_type": "text/plain",
                "api_key": secret_value,
                "nested": {"access_token": secret_value, "note": f"token={secret_value}"},
                "headers": [{"authorization": f"Bearer {secret_value}"}],
            },
        ),
        source=replace(
            source,
            metadata={
                "api_key": secret_value,
                "nested": {"access_token": secret_value, "note": f"token={secret_value}"},
                "headers": [{"authorization": f"Bearer {secret_value}"}],
            },
        ),
        goal=SearchGoal(
            goal_id="goal-corpus-secret-metadata",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-corpus-secret-metadata",
        run_id="run-corpus-secret-metadata",
        fetched_at_ms=2021,
        source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
    )

    recorded = store.record_document(document)
    dumped = json.dumps(store.audit_records(), ensure_ascii=False)

    assert recorded.metadata["source_metadata"]["api_key"] == "[omitted]"
    assert recorded.metadata["source_metadata"]["nested"]["access_token"] == "[omitted]"
    assert recorded.metadata["source_metadata"]["nested"]["note"] == "[omitted]"
    assert recorded.metadata["source_metadata"]["headers"][0]["authorization"] == "[omitted]"
    assert secret_value not in dumped
    assert "api_key" in dumped
    assert "access_token" in dumped


def test_phase83_corpus_search_and_inspection_outputs_are_bounded() -> None:
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: 3030)
    profile = finance_fundamentals_profile()
    for index in range(CORPUS_SEARCH_LIMIT_CAP + 5):
        source = _source(
            f"src-sec-{index}",
            f"https://www.sec.gov/Archives/edgar/data/320193/filing-{index}.htm",
            f"Apple Form 10-K {index}",
            "AAPL annual report revenue.",
        )
        store.record_document(
            corpus_document_from_retrieval(
                document=_document(
                    source=source,
                    artifact_id=f"artifact-sec-{index}",
                    payload_hash=f"hash-sec-{index}",
                    preview="AAPL annual report revenue preview.",
                ),
                source=source,
                goal=SearchGoal(
                    goal_id=f"goal-audit-corpus-{index}",
                    query="AAPL revenue",
                    metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
                ),
                task_id="task-audit-corpus",
                run_id=f"run-audit-corpus-{index}",
                fetched_at_ms=3030 + index,
                source_assessment=assess_search_source(source, profile=profile),
            )
        )

    requested_search_limit = CORPUS_SEARCH_LIMIT_CAP + 99
    result = store.search(
        "AAPL revenue",
        profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID,
        limit=requested_search_limit,
        record_access=True,
        access_context={"surface": "test"},
    )
    search_event = store.audit_records()[-1]
    payload = search_event["payload"]

    assert result.total == CORPUS_SEARCH_LIMIT_CAP
    assert len(result.documents) == CORPUS_SEARCH_LIMIT_CAP
    assert search_event["event_type"] == "corpus_documents_searched"
    assert payload["limit"] == CORPUS_SEARCH_LIMIT_CAP
    assert payload["requested_limit"] == requested_search_limit
    assert payload["limit_cap"] == CORPUS_SEARCH_LIMIT_CAP
    assert payload["limit_clamped"] is True
    assert len(payload["document_ids"]) == CORPUS_SEARCH_LIMIT_CAP

    requested_sample_limit = CORPUS_SAMPLE_LIMIT_CAP + 99
    inspection = store.inspect(sample_limit=requested_sample_limit)

    assert len(inspection.samples["documents"]) == CORPUS_SAMPLE_LIMIT_CAP
    assert inspection.samples["requested_sample_limit"] == requested_sample_limit
    assert inspection.samples["sample_limit"] == CORPUS_SAMPLE_LIMIT_CAP
    assert inspection.samples["sample_limit_cap"] == CORPUS_SAMPLE_LIMIT_CAP
    assert inspection.samples["sample_limit_clamped"] is True


def test_phase83_reobserved_document_refreshes_freshness_and_artifact_ref(tmp_path) -> None:
    log_path = tmp_path / "corpus.jsonl"
    index_path = tmp_path / "corpus.sqlite"
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    profile = finance_fundamentals_profile()
    max_age_ms = int(profile.metadata["freshness_max_age_ms"])
    now_ms = max_age_ms + 10_000
    old_document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-sec-old",
            payload_hash="hash-sec",
            preview=source.snippet,
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-stale-aapl",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-old",
        run_id="run-old",
        fetched_at_ms=1,
        source_assessment=assess_search_source(source, profile=profile),
    )
    store = ResearchCorpusStore(log_path=log_path, index_path=index_path, clock_ms=lambda: now_ms)
    store.record_document(old_document)
    assert store.search("AAPL revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID, exclude_stale=True).total == 0

    fresh_document = replace(
        old_document,
        artifact_id="artifact-sec-refresh",
        task_id="task-refresh",
        run_id="run-refresh",
        fetched_at_ms=now_ms - 1_000,
        research_profile_id=None,
        source_assessment=None,
    )
    refreshed = store.record_document(fresh_document)

    assert refreshed.document_id == old_document.document_id
    assert refreshed.artifact_id == "artifact-sec-refresh"
    assert refreshed.fetched_at_ms == now_ms - 1_000
    assert refreshed.research_profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert store.search("AAPL revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID, exclude_stale=True).total == 1
    assert store.freshness_summary(profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID)["stale_count"] == 0

    reloaded = ResearchCorpusStore(log_path=log_path, index_path=index_path, clock_ms=lambda: now_ms)
    reloaded_document = reloaded.get(old_document.document_id)
    assert reloaded_document is not None
    assert reloaded_document.artifact_id == "artifact-sec-refresh"
    assert reloaded_document.fetched_at_ms == now_ms - 1_000
    assert reloaded.search("AAPL revenue", profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID, exclude_stale=True).total == 1
    assert reloaded.index_documents()[0]["artifact_id"] == "artifact-sec-refresh"


def test_phase83_empty_or_weak_corpus_inspection_is_actionable() -> None:
    empty = ResearchCorpusStore.in_memory(clock_ms=lambda: 1010)
    empty_inspection = empty.inspect()
    assert empty_inspection.status == "attention"
    assert empty_inspection.issues[0]["code"] == "empty_corpus"
    assert "retrieve <query> --index-corpus" in empty_inspection.recommended_actions

    weak_source = _source(
        "src-blog",
        "https://example.com/aapl-opinion",
        "AAPL Opinion",
        "Unofficial commentary.",
    )
    weak = ResearchCorpusStore.in_memory(clock_ms=lambda: 1011)
    weak.record_document(
        corpus_document_from_retrieval(
            document=_document(
                source=weak_source,
                artifact_id="artifact-blog",
                payload_hash="hash-blog",
                preview=weak_source.snippet,
            ),
            source=weak_source,
            goal=SearchGoal(goal_id="goal-blog", query="AAPL opinion"),
            task_id="task-blog",
            run_id="run-blog",
            fetched_at_ms=1011,
            source_assessment=assess_search_source(weak_source, profile=finance_fundamentals_profile()),
        )
    )
    weak_inspection = weak.inspect()
    codes = [issue["code"] for issue in weak_inspection.issues]
    assert weak_inspection.status == "warning"
    assert "no_primary_usable_sources" in codes
    assert "unprofiled_documents" in codes


def test_phase83_corpus_inspection_detects_missing_artifact_without_reading_body() -> None:
    source = _source(
        "src-sec",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple Form 10-K",
        "AAPL annual report revenue.",
    )
    store = ResearchCorpusStore.in_memory(clock_ms=lambda: 1111)
    document = corpus_document_from_retrieval(
        document=_document(
            source=source,
            artifact_id="artifact-missing",
            payload_hash="hash-missing",
            preview="AAPL annual report revenue preview.",
        ),
        source=source,
        goal=SearchGoal(
            goal_id="goal-aapl",
            query="AAPL revenue",
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        task_id="task-missing-artifact",
        run_id="run-missing-artifact",
        fetched_at_ms=1111,
        source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
    )
    store.record_document(document)

    inspection = store.inspect(artifact_store=ArtifactStore.in_memory())

    assert inspection.status == "error"
    assert inspection.artifact_consistency["checked"] is True
    assert inspection.artifact_consistency["missing_artifact_ref_count"] == 1
    assert inspection.issues[0]["code"] == "missing_corpus_artifacts"
    assert "repair artifact store or re-index affected corpus documents" in inspection.recommended_actions


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
