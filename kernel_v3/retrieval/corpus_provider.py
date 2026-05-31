from __future__ import annotations

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import JsonObject
from kernel_v3.research.corpus import ResearchCorpusStore
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchResponse


class CorpusSearchProvider:
    live_network = False

    def __init__(self, corpus_store: ResearchCorpusStore, *, provider_name: str = "research_corpus") -> None:
        self.corpus_store = corpus_store
        self.provider_name = provider_name

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        result = self.corpus_store.search(
            query,
            profile_id=_research_profile_id(goal),
            limit=goal.max_sources,
        )
        return [_source_from_document(document, provider_name=self.provider_name) for document in result.documents]


class CorpusFetchProvider:
    live_network = False

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def fetch(self, source: SearchSource) -> FetchResponse:
        artifact_id = _string_value(source.metadata.get("artifact_id"))
        if artifact_id is None:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={"reason": "missing_corpus_artifact_id", "source_id": source.source_id},
            )
        artifact = self.artifact_store.get(artifact_id)
        if artifact is None:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={"reason": "missing_corpus_artifact_ref", "artifact_id": artifact_id},
            )
        try:
            payload = self.artifact_store.read_blob(artifact_id)
        except KeyError:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={"reason": "missing_corpus_artifact_blob", "artifact_id": artifact_id},
            )
        body = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        return FetchResponse(
            status="ok",
            body=body,
            mime_type=str(artifact.metadata.get("mime_type", "text/plain")),
            diagnostics={
                "source": "research_corpus",
                "artifact_id": artifact_id,
                "payload_hash": artifact.payload_hash,
                "corpus_document_id": source.metadata.get("corpus_document_id"),
            },
        )


def _source_from_document(document: JsonObject, *, provider_name: str) -> SearchSource:
    source_assessment = _json_object(document.get("source_assessment"))
    metadata = {
        "corpus_document_id": document.get("document_id"),
        "artifact_id": document.get("artifact_id"),
        "payload_hash": document.get("payload_hash"),
        "research_profile_id": document.get("research_profile_id"),
        "source_assessment": source_assessment,
        "source_family": source_assessment.get("source_family"),
    }
    return SearchSource(
        source_id=f"corpus-{document.get('document_id')}",
        uri=str(document.get("uri") or ""),
        title=str(document.get("title") or ""),
        snippet=str(document.get("preview") or ""),
        provider=provider_name,
        metadata=metadata,
    )


def _research_profile_id(goal: SearchGoal) -> str | None:
    value = goal.metadata.get("research_profile_id", goal.metadata.get("research_profile"))
    return value if isinstance(value, str) and value else None


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
