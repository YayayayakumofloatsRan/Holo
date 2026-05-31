from __future__ import annotations

from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchProvider, FetchResponse, SearchProvider


class FallbackSearchProvider:
    live_network = False

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = list(providers)
        self.live_network = any(bool(getattr(provider, "live_network", False)) for provider in self.providers)

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        last_empty: list[SearchSource] = []
        for provider in self.providers:
            sources = provider.search(query, goal=goal, plan=plan)
            if sources:
                return sources
            last_empty = sources
        return last_empty


class RoutingFetchProvider:
    live_network = False

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

    def fetch(self, source: SearchSource) -> FetchResponse:
        provider = self.routes.get(source.provider, self.fallback)
        return provider.fetch(source)
