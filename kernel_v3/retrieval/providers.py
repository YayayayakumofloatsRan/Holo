from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


class SearchProvider(Protocol):
    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        ...


class FetchProvider(Protocol):
    def fetch(self, source: SearchSource) -> "FetchResponse":
        ...


@dataclass(frozen=True, kw_only=True)
class FetchResponse:
    status: str
    body: str
    mime_type: str = "text/plain"
    diagnostics: JsonObject = field(default_factory=dict)


class FakeSearchProvider:
    def __init__(self, results_by_query: dict[str, list[SearchSource | JsonObject]]) -> None:
        self.results_by_query = {
            query.lower(): [_coerce_source(source) for source in sources]
            for query, sources in results_by_query.items()
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        return list(self.results_by_query.get(query.lower(), []))


class FakeFetchProvider:
    def __init__(self, responses_by_uri: dict[str, str | FetchResponse | JsonObject]) -> None:
        self.responses_by_uri = {
            uri: _coerce_fetch_response(response)
            for uri, response in responses_by_uri.items()
        }

    def fetch(self, source: SearchSource) -> FetchResponse:
        response = self.responses_by_uri.get(source.uri)
        if response is None:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={"reason": "missing_fake_fetch_fixture", "uri": source.uri},
            )
        return response


def _coerce_source(source: SearchSource | JsonObject) -> SearchSource:
    if isinstance(source, SearchSource):
        return source
    return SearchSource(
        source_id=str(source["source_id"]),
        uri=str(source["uri"]),
        title=str(source.get("title", "")),
        snippet=str(source.get("snippet", "")),
        provider=str(source.get("provider", "fake")),
        metadata=dict(source.get("metadata", {})),
    )


def _coerce_fetch_response(response: str | FetchResponse | JsonObject) -> FetchResponse:
    if isinstance(response, FetchResponse):
        return response
    if isinstance(response, str):
        return FetchResponse(status="ok", body=response)
    return FetchResponse(
        status=str(response.get("status", "ok")),
        body=str(response.get("body", "")),
        mime_type=str(response.get("mime_type", "text/plain")),
        diagnostics=dict(response.get("diagnostics", {})),
    )
