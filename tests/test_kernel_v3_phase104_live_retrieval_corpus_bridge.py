from kernel_v3.agent import AgentRuntime
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, ResearchCorpusStore, finance_fundamentals_profile
from kernel_v3.research.corpus import corpus_document_from_retrieval
from kernel_v3.research.source_policy import assess_search_source
from kernel_v3.retrieval import SearchGoal, SearchSource
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.http_provider import HttpTransportResponse
from kernel_v3.retrieval.live_config import LiveRetrievalConfig


def test_phase104_live_retrieval_operator_searches_corpus_before_live_fetch() -> None:
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 1010)
    source = _source("https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm")
    body = "AAPL 2024 Form 10-K revenue was $391.0 billion in the official SEC filing."
    artifact = artifacts.write_blob(
        kind="retrieval_fetched_document",
        payload=body,
        metadata={"uri": source.uri, "source_id": source.source_id, "title": source.title},
    )
    corpus.record_document(
        corpus_document_from_retrieval(
            document=_document(source=source, artifact_id=artifact.artifact_id, payload_hash=artifact.payload_hash),
            source=source,
            goal=SearchGoal(
                goal_id="goal-seed-corpus",
                query="AAPL 2024 revenue",
                metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
            ),
            task_id="task-seed",
            run_id="run-seed",
            fetched_at_ms=1010,
            source_assessment=assess_search_source(source, profile=finance_fundamentals_profile()),
        )
    )
    transport = _Transport({})
    operator = _live_config().build_operator(
        artifact_store=artifacts,
        corpus_store=corpus,
        fetch_transport=transport,
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-cache-first",
            query="AAPL 2024 revenue",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=1,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        journal=JournalStore.in_memory(),
        artifact_store=artifacts,
        task_id="task-cache-first",
        run_id="run-1",
    )

    assert report.status == "sufficient"
    assert transport.calls == []
    capabilities = report.diagnostics["provider_capabilities"]
    assert capabilities[0]["provider_id"] == "adaptive_search"
    assert capabilities[0]["diagnostics"]["default_strategy"] == "fallback"
    assert capabilities[0]["diagnostics"]["providers"][0]["provider_id"] == "research_corpus"
    assert capabilities[1]["provider_id"] == "routing_fetch"
    assert "research_corpus" in capabilities[1]["diagnostics"]["routes"]


def test_phase104_agent_live_fetch_indexes_corpus_then_reuses_it_without_network() -> None:
    query = "AAPL 2024 10-K revenue"
    sec_url = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"
    artifacts = ArtifactStore.in_memory()
    corpus = ResearchCorpusStore.in_memory(clock_ms=lambda: 2020)
    first_transport = _Transport(
        {
            sec_url: "AAPL 2024 Form 10-K revenue was $391.0 billion in the official SEC filing.",
        }
    )
    first_runtime = AgentRuntime(
        journal=JournalStore.in_memory(),
        artifact_store=artifacts,
        processor_fabric=fake_fabric({"semantic.intake": _finance_intake(query, source_url=sec_url)}),
        retrieval_operator=_live_config().build_operator(
            artifact_store=artifacts,
            corpus_store=corpus,
            fetch_transport=first_transport,
        ),
        research_corpus_store=corpus,
    )

    first = first_runtime.run(
        query,
        mode="auto",
        semantic_mode="model",
        execution_metadata=_network_budget(),
    )

    assert first.status == "completed"
    assert first_transport.calls == [sec_url]
    assert len(corpus.documents(profile_id=FINANCE_FUNDAMENTALS_PROFILE_ID)) == 1

    second_journal = JournalStore.in_memory()
    second_transport = _Transport({})
    second_runtime = AgentRuntime(
        journal=second_journal,
        artifact_store=artifacts,
        processor_fabric=fake_fabric({"semantic.intake": _finance_intake(query)}),
        retrieval_operator=_live_config().build_operator(
            artifact_store=artifacts,
            corpus_store=corpus,
            fetch_transport=second_transport,
        ),
        research_corpus_store=corpus,
    )

    second = second_runtime.run(
        query,
        mode="auto",
        semantic_mode="model",
        execution_metadata=_network_budget(),
    )

    assert second.status == "completed"
    assert second_transport.calls == []
    second_search = second_journal.records(task_id=second.task_id, kind="retrieval_search_attempt")[0].data
    assert second_search["sources"][0]["provider"] == "research_corpus"
    assert second.final_answer["citation_refs"]


def _live_config() -> LiveRetrievalConfig:
    return LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "www.sec.gov,sec.gov",
        }
    )


def _network_budget() -> dict:
    return {
        "retrieval": {
            "allow_network": True,
            "max_network_fetches": 1,
            "max_sources": 1,
            "max_fetches": 1,
        }
    }


def _finance_intake(query: str, *, source_url: str | None = None) -> dict:
    retrieval_args = {
        "max_sources": 1,
        "max_fetches": 1,
    }
    if source_url is not None:
        retrieval_args["source_url"] = source_url
    return {
        "primary_intent": "finance_fundamentals",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "finance_fundamentals",
                "text": query,
                "sequence_index": 1,
                "required_capabilities": ["finance.fundamentals_research"],
                "risk": "read",
                "status": "ready",
                "metadata": {
                    "capability_args": {
                        "retrieval.run": retrieval_args,
                    }
                },
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _source(uri: str) -> SearchSource:
    return SearchSource(
        source_id="src-sec-aapl-10k",
        uri=uri,
        title="Apple 2024 Form 10-K",
        snippet="AAPL 2024 Form 10-K revenue was $391.0 billion in the official SEC filing.",
        provider="direct_url_search",
    )


def _document(*, source: SearchSource, artifact_id: str, payload_hash: str) -> FetchedDocument:
    return FetchedDocument(
        document_id="doc-seed-sec",
        goal_id="goal-seed-corpus",
        source_id=source.source_id,
        uri=source.uri,
        title=source.title,
        artifact_id=artifact_id,
        payload_hash=payload_hash,
        preview=source.snippet,
        size_bytes=128,
        metadata={"mime_type": "text/plain"},
    )


class _Transport:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = dict(responses)
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
        self.calls.append(url)
        body = self.responses.get(url)
        if body is None:
            return HttpTransportResponse(status_code=404, body=b"missing", mime_type="text/plain")
        return HttpTransportResponse(status_code=200, body=body.encode("utf-8"), mime_type="text/plain")
