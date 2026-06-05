from __future__ import annotations

import hashlib
from dataclasses import replace

from kernel_v3.research.profile_policy import profile_discovery_source_kinds
from kernel_v3.research.profiles import profile_by_id
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchProvider, FetchResponse, SearchProvider, provider_capability
from kernel_v3.retrieval.rank import rank_sources


class FallbackSearchProvider:
    provider_id = "fallback_search"
    live_network = False
    default_enabled = True
    profile_aware = False

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = list(providers)
        self.live_network = any(bool(getattr(provider, "live_network", False)) for provider in self.providers)
        self.default_enabled = any(bool(getattr(provider, "default_enabled", True)) for provider in self.providers)
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
            "enabled_provider_count": sum(1 for provider in self.providers if _provider_enabled(provider)),
            "disabled_provider_ids": [
                getattr(provider, "provider_id", provider.__class__.__name__)
                for provider in self.providers
                if not _provider_enabled(provider)
            ],
            "providers": [
                provider_capability(provider, provider_kind="search").to_dict()
                for provider in self.providers
            ],
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        last_empty: list[SearchSource] = []
        attempts = []
        for provider in self.providers:
            provider_id = getattr(provider, "provider_id", provider.__class__.__name__)
            if not _provider_enabled(provider):
                attempts.append(
                    {
                        "provider_id": provider_id,
                        "source_count": 0,
                        "status": "skipped",
                        "reason": "disabled_by_default",
                        "diagnostics": _provider_diagnostics(provider),
                    }
                )
                continue
            try:
                sources = provider.search(query, goal=goal, plan=plan)
                error = None
            except Exception as exc:
                sources = []
                error = type(exc).__name__
            attempts.append(
                {
                    "provider_id": provider_id,
                    "source_count": len(sources),
                    "status": "failed" if error else ("discovery_only" if _all_sources_discovery_only(sources, goal=goal) else "ok"),
                    "diagnostics": _provider_diagnostics(provider),
                    **({"error": error} if error else {}),
                }
            )
            if sources:
                if _all_sources_discovery_only(sources, goal=goal):
                    last_empty = sources
                    continue
                self._last_search_diagnostics = {
                    "provider_id": self.provider_id,
                    "status": "ok",
                    "selected_provider_id": getattr(provider, "provider_id", provider.__class__.__name__),
                    "attempts": attempts,
                }
                return sources
            last_empty = sources
        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "status": _empty_status(attempts),
            "selected_provider_id": None,
            "attempts": attempts,
        }
        return last_empty

    def search_diagnostics(self):
        return dict(getattr(self, "_last_search_diagnostics", {}))


class AggregateSearchProvider:
    provider_id = "aggregate_search"
    live_network = False
    default_enabled = True
    profile_aware = False

    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        max_sources_per_provider: int | None = None,
    ) -> None:
        self.providers = list(providers)
        self.max_sources_per_provider = max_sources_per_provider
        self.live_network = any(bool(getattr(provider, "live_network", False)) for provider in self.providers)
        self.default_enabled = any(bool(getattr(provider, "default_enabled", True)) for provider in self.providers)
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
            "enabled_provider_count": sum(1 for provider in self.providers if _provider_enabled(provider)),
            "max_sources_per_provider": self.max_sources_per_provider,
            "providers": [
                provider_capability(provider, provider_kind="search").to_dict()
                for provider in self.providers
            ],
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        attempts = []
        collected: list[SearchSource] = []
        seen_uris: set[str] = set()
        provider_goal = _provider_goal(goal, max_sources_per_provider=self.max_sources_per_provider)
        for provider in self.providers:
            provider_id = getattr(provider, "provider_id", provider.__class__.__name__)
            if not _provider_enabled(provider):
                attempts.append(
                    {
                        "provider_id": provider_id,
                        "source_count": 0,
                        "accepted_source_count": 0,
                        "status": "skipped",
                        "reason": "disabled_by_default",
                        "diagnostics": _provider_diagnostics(provider),
                    }
                )
                continue
            try:
                sources = provider.search(query, goal=provider_goal, plan=plan)
                error = None
            except Exception as exc:
                sources = []
                error = type(exc).__name__
            accepted = 0
            for source in sources:
                if source.uri in seen_uris:
                    continue
                seen_uris.add(source.uri)
                collected.append(source)
                accepted += 1
            attempts.append(
                {
                    "provider_id": provider_id,
                    "source_count": len(sources),
                    "accepted_source_count": accepted,
                    "status": "failed" if error else "ok",
                    "diagnostics": _provider_diagnostics(provider),
                    **({"error": error} if error else {}),
                }
            )
        ranked = rank_sources(
            goal,
            collected,
            research_profile=profile_by_id(_research_profile_id(goal)),
        )
        by_id = {source.source_id: source for source in collected}
        ordered = [
            by_id[item.source_id]
            for item in ranked
            if item.source_id in by_id
        ]
        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "status": "ok" if ordered else _empty_status(attempts),
            "attempts": attempts,
            "collected_source_count": len(collected),
            "returned_source_count": len(ordered[: goal.max_sources]),
            "query_hash": _hash_text(query),
        }
        return ordered[: goal.max_sources]

    def search_diagnostics(self):
        return dict(getattr(self, "_last_search_diagnostics", {}))


class AdaptiveSearchProvider:
    provider_id = "adaptive_search"
    live_network = False
    default_enabled = True
    profile_aware = False

    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        default_strategy: str = "fallback",
        max_sources_per_provider: int | None = None,
    ) -> None:
        self.providers = list(providers)
        self.default_strategy = _normalize_strategy(default_strategy)
        self.max_sources_per_provider = max_sources_per_provider
        self.live_network = any(bool(getattr(provider, "live_network", False)) for provider in self.providers)
        self.default_enabled = any(bool(getattr(provider, "default_enabled", True)) for provider in self.providers)
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
            "enabled_provider_count": sum(1 for provider in self.providers if _provider_enabled(provider)),
            "default_strategy": self.default_strategy,
            "supported_strategies": [
                "fallback",
                "aggregate",
                "corpus_only",
                "fresh_live",
                "structured",
                "crawl",
            ],
            "max_sources_per_provider": self.max_sources_per_provider,
            "providers": [
                provider_capability(provider, provider_kind="search").to_dict()
                for provider in self.providers
            ],
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        request = _strategy_request(goal.metadata, default_strategy=self.default_strategy)
        providers = _strategy_providers(self.providers, request=request)
        if request["mode"] == "aggregate":
            provider: SearchProvider = AggregateSearchProvider(
                providers,
                max_sources_per_provider=request.get("max_sources_per_provider") or self.max_sources_per_provider,
            )
        else:
            provider = FallbackSearchProvider(providers)
        sources = provider.search(query, goal=goal, plan=plan)
        child_diagnostics = _provider_diagnostics(provider)
        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "status": "ok" if sources else str(child_diagnostics.get("status") or "empty"),
            "requested_strategy": request["requested_strategy"],
            "selected_strategy": request["mode"],
            "selected_provider_ids": _provider_ids(providers),
            "selected_provider_id": child_diagnostics.get("selected_provider_id"),
            "provider_count": len(providers),
            "child_provider_id": getattr(provider, "provider_id", provider.__class__.__name__),
            "child_diagnostics": child_diagnostics,
            "query_hash": _hash_text(query),
        }
        return sources

    def search_diagnostics(self):
        return dict(getattr(self, "_last_search_diagnostics", {}))


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


def _provider_diagnostics(provider) -> dict:
    raw = getattr(provider, "search_diagnostics", None)
    if callable(raw):
        value = raw()
        return dict(value) if isinstance(value, dict) else {}
    value = getattr(provider, "last_search_diagnostics", {})
    return dict(value) if isinstance(value, dict) else {}


def _provider_enabled(provider) -> bool:
    return bool(getattr(provider, "default_enabled", True))


def _strategy_request(metadata: object, *, default_strategy: str) -> dict[str, object]:
    raw: object = {}
    if isinstance(metadata, dict):
        raw = metadata.get("search_strategy", metadata.get("retrieval_search_strategy", {}))
    requested = raw
    if isinstance(raw, str):
        mode = raw
        include = []
        exclude = []
        max_sources_per_provider = None
    elif isinstance(raw, dict):
        mode = str(raw.get("mode") or raw.get("strategy") or default_strategy)
        include = _string_list(raw.get("include_provider_ids") or raw.get("provider_ids"))
        exclude = _string_list(raw.get("exclude_provider_ids"))
        max_sources_per_provider = _positive_int_or_none(raw.get("max_sources_per_provider"))
    else:
        mode = default_strategy
        include = []
        exclude = []
        max_sources_per_provider = None
    mode = _normalize_strategy(mode)
    return {
        "requested_strategy": requested if isinstance(requested, (str, dict)) else None,
        "mode": mode,
        "include_provider_ids": include,
        "exclude_provider_ids": exclude,
        "max_sources_per_provider": max_sources_per_provider,
    }


def _strategy_providers(providers: list[SearchProvider], *, request: dict[str, object]) -> list[SearchProvider]:
    selected = list(providers)
    include = set(_string_list(request.get("include_provider_ids")))
    exclude = set(_string_list(request.get("exclude_provider_ids")))
    if include:
        selected = [provider for provider in selected if _provider_id(provider) in include]
    if exclude:
        selected = [provider for provider in selected if _provider_id(provider) not in exclude]
    mode = str(request.get("mode") or "fallback")
    if mode == "corpus_only":
        selected = [provider for provider in selected if _provider_id(provider) == "research_corpus"]
    elif mode == "fresh_live":
        selected = [provider for provider in selected if _provider_id(provider) != "research_corpus"]
    elif mode == "structured":
        selected = [
            provider
            for provider in selected
            if _provider_id(provider)
            in {
                "direct_url_search",
                "sec_edgar_structured_search",
                "fred_structured_search",
                "fiscaldata_structured_search",
                "research_source_query_search",
                "research_source_directory_search",
            }
        ]
    elif mode == "crawl":
        selected = [
            provider
            for provider in selected
            if _provider_id(provider) in {"direct_url_search", "bounded_crawl_search"}
        ]
    return selected


def _normalize_strategy(value: object) -> str:
    normalized = str(value or "fallback").strip().lower().replace("-", "_")
    if normalized in {"aggregate", "merged", "blend", "blended"}:
        return "aggregate"
    if normalized in {"corpus", "corpus_only", "cache", "cache_only"}:
        return "corpus_only"
    if normalized in {"fresh", "fresh_live", "live", "live_only", "network"}:
        return "fresh_live"
    if normalized in {"structured", "official", "source_directory"}:
        return "structured"
    if normalized in {"crawl", "crawl_only"}:
        return "crawl"
    return "fallback"


def _provider_ids(providers: list[SearchProvider]) -> list[str]:
    return [_provider_id(provider) for provider in providers]


def _provider_id(provider: object) -> str:
    value = getattr(provider, "provider_id", "")
    return value if isinstance(value, str) and value else provider.__class__.__name__


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _positive_int_or_none(value: object) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _all_attempts_failed(attempts: list[dict]) -> bool:
    return bool(attempts) and all(attempt.get("status") == "failed" for attempt in attempts)


def _all_attempts_skipped(attempts: list[dict]) -> bool:
    return bool(attempts) and all(attempt.get("status") == "skipped" for attempt in attempts)


def _empty_status(attempts: list[dict]) -> str:
    if _all_attempts_failed(attempts):
        return "failed"
    if _all_attempts_skipped(attempts):
        return "skipped"
    return "empty"


def _all_sources_discovery_only(sources: list[SearchSource], *, goal: SearchGoal) -> bool:
    if not sources:
        return False
    profile = profile_by_id(_research_profile_id(goal))
    discovery_kinds = profile_discovery_source_kinds(profile)
    if not discovery_kinds:
        return False
    return all(_source_kind(source) in discovery_kinds for source in sources)


def _source_kind(source: SearchSource) -> str:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    value = metadata.get("source_kind")
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _provider_goal(goal: SearchGoal, *, max_sources_per_provider: int | None) -> SearchGoal:
    if max_sources_per_provider is None:
        return goal
    limit = max(1, min(int(goal.max_sources), int(max_sources_per_provider)))
    return replace(goal, max_sources=limit)


def _research_profile_id(goal: SearchGoal) -> str | None:
    value = goal.metadata.get("research_profile_id", goal.metadata.get("research_profile"))
    return value if isinstance(value, str) and value else None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
