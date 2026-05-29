from __future__ import annotations

from kernel_v3.retrieval.contracts import SearchSource
from kernel_v3.retrieval.operator import RetrievalOperator
from kernel_v3.retrieval.providers import FakeFetchProvider, FakeSearchProvider, FetchResponse


def fake_source(
    source_id: str,
    *,
    uri: str,
    title: str,
    snippet: str,
    provider: str = "fake",
) -> SearchSource:
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider=provider,
    )


def fake_operator(
    *,
    results_by_query: dict[str, list[SearchSource]],
    bodies_by_uri: dict[str, str | FetchResponse],
) -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=FakeSearchProvider(results_by_query),
        fetch_provider=FakeFetchProvider(bodies_by_uri),
    )
