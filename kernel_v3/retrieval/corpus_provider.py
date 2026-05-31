from __future__ import annotations

from kernel_v3.context import ArtifactStore
from kernel_v3.contracts import JsonObject
from kernel_v3.research.corpus import ResearchCorpusStore
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchResponse


class CorpusSearchProvider:
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = ["*"]

    def __init__(self, corpus_store: ResearchCorpusStore, *, provider_name: str = "research_corpus") -> None:
        self.corpus_store = corpus_store
        self.provider_name = provider_name
        self.provider_id = provider_name
        self.capability_diagnostics = {"source": "research_corpus", "freshness_filter": "profile_aware"}
        self._last_search_diagnostics: JsonObject = {}

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        profile_id = _research_profile_id(goal)
        freshness = (
            self.corpus_store.freshness_summary(profile_id=profile_id, sample_limit=goal.max_sources)
            if profile_id
            else {"checked": False, "reason": "no_research_profile"}
        )
        freshness_now = _int_value(freshness.get("generated_at_ms"))
        result = self.corpus_store.search(
            query,
            profile_id=profile_id,
            limit=goal.max_sources,
            exclude_stale=profile_id is not None,
            now_ms=freshness_now,
            record_access=True,
            access_context={
                "surface": "retrieval_provider",
                "provider_id": self.provider_id,
                "goal_id": goal.goal_id,
                "plan_id": plan.plan_id,
            },
        )
        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "profile_id": profile_id,
            "freshness_filter_enabled": profile_id is not None,
            "freshness": freshness,
            "returned_count": result.total,
        }
        return [_source_from_document(document, provider_name=self.provider_name) for document in result.documents]

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


class CorpusFetchProvider:
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []
    provider_id = "research_corpus_fetch"
    capability_diagnostics = {"source": "artifact_store"}

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
            payload = self.artifact_store.read_blob(
                artifact_id,
                record_access=True,
                access_context={
                    "surface": "corpus_fetch_provider",
                    "provider_id": self.provider_id,
                    "source_id": source.source_id,
                    "corpus_document_id": source.metadata.get("corpus_document_id"),
                },
            )
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


def _int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
