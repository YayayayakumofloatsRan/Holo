from __future__ import annotations

from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchProvider, FetchResponse, SearchProvider, provider_capability


class FallbackSearchProvider:
    provider_id = "fallback_search"
    live_network = False
    default_enabled = True
    profile_aware = False

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = list(providers)
        self.live_network = any(bool(getattr(provider, "live_network", False)) for provider in self.providers)
        self.default_enabled = all(bool(getattr(provider, "default_enabled", True)) for provider in self.providers)
        self.profile_aware = any(bool(getattr(provider, "profile_aware", False)) for provider in self.providers)
        self.supported_research_profiles = _unique(
            [
                profile
                for provider in self.providers
                for profile in getattr(provider, "supported_research_profiles", [])
                if isinstance(profile, str)
            ]
        )
        self.capability_diagnostics = {
            "provider_count": len(self.providers),
            "providers": [
                provider_capability(provider, provider_kind="search").to_dict()
                for provider in self.providers
            ],
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        last_empty: list[SearchSource] = []
        for provider in self.providers:
            sources = provider.search(query, goal=goal, plan=plan)
            if sources:
                return sources
            last_empty = sources
        return last_empty


class RoutingFetchProvider:
    provider_id = "routing_fetch"
    live_network = False
    default_enabled = True
    profile_aware = False

    def __init__(
        self,
        *,
        routes: dict[str, FetchProvider],
        fallback: FetchProvider,
    ) -> None:
        self.routes = dict(routes)
        self.fallback = fallback
        self.live_network = bool(getattr(fallback, "live_network", False)) or any(
            bool(getattr(provider, "live_network", False)) for provider in self.routes.values()
        )
        providers = [self.fallback, *self.routes.values()]
        self.default_enabled = all(bool(getattr(provider, "default_enabled", True)) for provider in providers)
        self.supported_research_profiles = _unique(
            [
                profile
                for provider in providers
                for profile in getattr(provider, "supported_research_profiles", [])
                if isinstance(profile, str)
            ]
        )
        self.capability_diagnostics = {
            "route_count": len(self.routes),
            "routes": sorted(self.routes),
            "fallback": provider_capability(self.fallback, provider_kind="fetch").to_dict(),
            "route_providers": [
                provider_capability(provider, provider_kind="fetch").to_dict()
                for provider in self.routes.values()
            ],
        }

    def fetch(self, source: SearchSource) -> FetchResponse:
        provider = self.routes.get(source.provider, self.fallback)
        return provider.fetch(source)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
