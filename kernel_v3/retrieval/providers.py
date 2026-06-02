from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.contracts import QueryPlan, RetrievalProviderCapability, SearchGoal, SearchSource


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
    provider_id = "fake_search"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, results_by_query: dict[str, list[SearchSource | JsonObject]]) -> None:
        self.results_by_query = {
            query.lower(): [_coerce_source(source) for source in sources]
            for query, sources in results_by_query.items()
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        return list(self.results_by_query.get(query.lower(), []))


class UnconfiguredSearchProvider:
    provider_id = "unconfigured_search"
    live_network = False
    default_enabled = False
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, *, reason: str = "retrieval_source_not_configured") -> None:
        self.reason = reason
        self.capability_diagnostics = {"reason": reason}
        self._last_search_diagnostics: JsonObject = {}

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "status": "empty",
            "reason": self.reason,
            "query_preview": query[:160],
        }
        return []

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


class FakeFetchProvider:
    provider_id = "fake_fetch"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

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


class UnconfiguredFetchProvider:
    provider_id = "unconfigured_fetch"
    live_network = False
    default_enabled = False
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self, *, reason: str = "retrieval_fetch_not_configured") -> None:
        self.reason = reason
        self.capability_diagnostics = {"reason": reason}

    def fetch(self, source: SearchSource) -> FetchResponse:
        return FetchResponse(
            status="failed",
            body="",
            diagnostics={"reason": self.reason, "uri": source.uri},
        )


def provider_capability(provider: object, *, provider_kind: str) -> RetrievalProviderCapability:
    raw = getattr(provider, "capability", None)
    if callable(raw):
        capability = raw(provider_kind=provider_kind)
        if isinstance(capability, RetrievalProviderCapability):
            return capability
        if isinstance(capability, dict):
            return RetrievalProviderCapability.from_dict(
                {
                    "provider_id": _provider_id(provider),
                    "provider_kind": provider_kind,
                    "live_network": bool(getattr(provider, "live_network", False)),
                    "default_enabled": bool(getattr(provider, "default_enabled", True)),
                    "profile_aware": bool(getattr(provider, "profile_aware", False)),
                    "supported_research_profiles": _string_list(getattr(provider, "supported_research_profiles", [])),
                    "diagnostics": {},
                    **capability,
                }
            )
    return RetrievalProviderCapability(
        provider_id=_provider_id(provider),
        provider_kind=provider_kind,
        live_network=bool(getattr(provider, "live_network", False)),
        default_enabled=bool(getattr(provider, "default_enabled", True)),
        profile_aware=bool(getattr(provider, "profile_aware", False)),
        supported_research_profiles=_string_list(getattr(provider, "supported_research_profiles", [])),
        diagnostics={
            "provider_class": provider.__class__.__name__,
            **_dict_or_empty(getattr(provider, "capability_diagnostics", {})),
        },
    )


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


def _provider_id(provider: object) -> str:
    value = getattr(provider, "provider_id", "")
    if isinstance(value, str) and value:
        return value
    return provider.__class__.__name__


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _dict_or_empty(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


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
