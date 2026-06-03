from __future__ import annotations

import hashlib
import os
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, source_directory_for_profile
from kernel_v3.retrieval.http_provider import (
    HttpFetchProvider,
    HttpTransport,
    JsonHttpSearchProvider,
)
from kernel_v3.retrieval.web_search_provider import LiveWebSearchProvider, web_search_engine_hosts
from kernel_v3.retrieval.composite import AdaptiveSearchProvider, AggregateSearchProvider, FallbackSearchProvider, RoutingFetchProvider
from kernel_v3.retrieval.corpus_provider import CorpusFetchProvider, CorpusSearchProvider
from kernel_v3.retrieval.crawl_provider import (
    BoundedCrawlSearchProvider,
    DirectUrlSearchProvider,
    SourceDirectorySearchProvider,
)
from kernel_v3.retrieval.fiscaldata_provider import FiscalDataSearchProvider
from kernel_v3.retrieval.fred_provider import FredSearchProvider
from kernel_v3.retrieval.sec_edgar_provider import SecEdgarSearchProvider
from kernel_v3.retrieval.source_query_provider import ResearchSourceQuerySearchProvider
from kernel_v3.retrieval.operator import RetrievalOperator


LIVE_RETRIEVAL_ENV = "HOLO_V3_LIVE_RETRIEVAL"
LIVE_SEARCH_ENDPOINT_ENV = "HOLO_V3_LIVE_SEARCH_ENDPOINT"
LIVE_SEARCH_ALLOWED_HOSTS_ENV = "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS"
LIVE_FETCH_ALLOWED_HOSTS_ENV = "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS"
LIVE_ALLOW_ALL_HOSTS_ENV = "HOLO_V3_LIVE_RETRIEVAL_ALLOW_ALL_HOSTS"
LIVE_ALLOWED_SCHEMES_ENV = "HOLO_V3_LIVE_RETRIEVAL_ALLOWED_SCHEMES"
LIVE_SEARCH_QUERY_PARAM_ENV = "HOLO_V3_LIVE_SEARCH_QUERY_PARAM"
LIVE_SEARCH_RESULTS_PATH_ENV = "HOLO_V3_LIVE_SEARCH_RESULTS_PATH"
LIVE_SEARCH_API_KEY_ENV_ENV = "HOLO_V3_LIVE_SEARCH_API_KEY_ENV"
LIVE_SEARCH_API_KEY_HEADER_ENV = "HOLO_V3_LIVE_SEARCH_API_KEY_HEADER"
LIVE_SEARCH_API_KEY_PREFIX_ENV = "HOLO_V3_LIVE_SEARCH_API_KEY_PREFIX"
LIVE_WEB_SEARCH_PROVIDERS_ENV = "HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS"
LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE_ENV = "HOLO_V3_LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE"
LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV = "HOLO_V3_LIVE_FETCH_DISCOVERED_SEARCH_HOSTS"
LIVE_CRAWL_SEED_URLS_ENV = "HOLO_V3_LIVE_CRAWL_SEED_URLS"
LIVE_CRAWL_MAX_PAGES_ENV = "HOLO_V3_LIVE_CRAWL_MAX_PAGES"
LIVE_CRAWL_MAX_LINKS_PER_PAGE_ENV = "HOLO_V3_LIVE_CRAWL_MAX_LINKS_PER_PAGE"
LIVE_CRAWL_INCLUDE_SITEMAPS_ENV = "HOLO_V3_LIVE_CRAWL_INCLUDE_SITEMAPS"
LIVE_CRAWL_MAX_SITEMAP_URLS_ENV = "HOLO_V3_LIVE_CRAWL_MAX_SITEMAP_URLS"
LIVE_CRAWL_SOURCE_DIRECTORY_ENV = "HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY"
LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS_ENV = "HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS"
LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV = "HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST"
LIVE_SEARCH_STRATEGY_ENV = "HOLO_V3_LIVE_SEARCH_STRATEGY"
LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER_ENV = "HOLO_V3_LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER"
LIVE_TIMEOUT_SECONDS_ENV = "HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS"
LIVE_MAX_BYTES_ENV = "HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES"
DEFAULT_LIVE_MAX_BYTES = 16_000_000


@dataclass(frozen=True, kw_only=True)
class LiveJsonHttpSearchConfig:
    enabled: bool = False
    endpoint_url: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    query_param: str = "q"
    results_path: list[str] = field(default_factory=lambda: ["results"])
    api_key_env: str | None = None
    api_key_header: str | None = None
    api_key_prefix: str = ""
    timeout_seconds: int = 20
    max_bytes: int = DEFAULT_LIVE_MAX_BYTES
    user_agent: str = "holo-kernel-v3/1.0"

    @property
    def configured(self) -> bool:
        return bool(self.endpoint_url)

    def build_provider(self, *, transport: HttpTransport | None = None) -> JsonHttpSearchProvider:
        if not self.endpoint_url:
            raise ValueError("live_search_endpoint_not_configured")
        return JsonHttpSearchProvider(
            endpoint_url=self.endpoint_url,
            enabled=self.enabled,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
            allowed_schemes=self.allowed_schemes,
            query_param=self.query_param,
            results_path=self.results_path,
            api_key_env=self.api_key_env,
            api_key_header=self.api_key_header,
            api_key_prefix=self.api_key_prefix,
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.max_bytes,
            user_agent=self.user_agent,
            transport=transport,
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "endpoint": _safe_url_diagnostics(self.endpoint_url or ""),
            "allowed_host_count": len(self.allowed_hosts),
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_schemes": list(self.allowed_schemes),
            "query_param": self.query_param,
            "results_path": list(self.results_path),
            "api_key_env_configured": bool(self.api_key_env),
            "api_key_header_configured": bool(self.api_key_header),
            "api_key_prefix_configured": bool(self.api_key_prefix),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True, kw_only=True)
class LiveWebSearchConfig:
    enabled: bool = False
    providers: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    timeout_seconds: int = 20
    max_bytes: int = DEFAULT_LIVE_MAX_BYTES
    max_results_per_engine: int = 10
    user_agent: str = "Mozilla/5.0"

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def build_provider(self, *, transport: HttpTransport | None = None) -> LiveWebSearchProvider:
        return LiveWebSearchProvider(
            enabled=self.enabled,
            engines=self.providers,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
            allowed_schemes=self.allowed_schemes,
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.max_bytes,
            max_results_per_engine=self.max_results_per_engine,
            user_agent=self.user_agent,
            transport=transport,
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "provider_count": len(self.providers),
            "providers": list(self.providers),
            "allowed_host_count": len(self.allowed_hosts),
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_results_per_engine": self.max_results_per_engine,
        }


@dataclass(frozen=True, kw_only=True)
class LiveHttpFetchConfig:
    enabled: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    allow_discovered_search_hosts: bool = False
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    timeout_seconds: int = 20
    max_bytes: int = DEFAULT_LIVE_MAX_BYTES
    user_agent: str = "holo-kernel-v3/1.0"

    def build_provider(self, *, transport: HttpTransport | None = None) -> HttpFetchProvider:
        return HttpFetchProvider(
            enabled=self.enabled,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
            allow_discovered_search_hosts=self.allow_discovered_search_hosts,
            allowed_schemes=self.allowed_schemes,
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.max_bytes,
            user_agent=self.user_agent,
            transport=transport,
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "enabled": self.enabled,
            "allowed_host_count": len(self.allowed_hosts),
            "allow_all_hosts": self.allow_all_hosts,
            "allow_discovered_search_hosts": self.allow_discovered_search_hosts,
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True, kw_only=True)
class LiveCrawlSearchConfig:
    enabled: bool = False
    seed_urls: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    timeout_seconds: int = 20
    max_bytes: int = DEFAULT_LIVE_MAX_BYTES
    max_pages: int = 3
    max_links_per_page: int = 20
    include_sitemaps: bool = True
    max_sitemap_urls: int = 50
    include_source_directory_seeds: bool = False
    max_source_directory_seeds: int = 12
    user_agent: str = "holo-kernel-v3/1.0"

    @property
    def configured(self) -> bool:
        return bool(self.seed_urls or self.include_source_directory_seeds)

    def build_provider(self, *, transport: HttpTransport | None = None) -> BoundedCrawlSearchProvider:
        return BoundedCrawlSearchProvider(
            enabled=self.enabled,
            seed_urls=self.seed_urls,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
            allowed_schemes=self.allowed_schemes,
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.max_bytes,
            max_pages=self.max_pages,
            max_links_per_page=self.max_links_per_page,
            include_sitemaps=self.include_sitemaps,
            max_sitemap_urls=self.max_sitemap_urls,
            include_source_directory_seeds=self.include_source_directory_seeds,
            max_source_directory_seeds=self.max_source_directory_seeds,
            user_agent=self.user_agent,
            transport=transport,
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "seed_count": len(self.seed_urls),
            "allowed_host_count": len(self.allowed_hosts),
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_pages": self.max_pages,
            "max_links_per_page": self.max_links_per_page,
            "include_sitemaps": self.include_sitemaps,
            "max_sitemap_urls": self.max_sitemap_urls,
            "include_source_directory_seeds": self.include_source_directory_seeds,
            "max_source_directory_seeds": self.max_source_directory_seeds,
        }


@dataclass(frozen=True, kw_only=True)
class LiveRetrievalConfig:
    enabled: bool = False
    search: LiveJsonHttpSearchConfig = field(default_factory=LiveJsonHttpSearchConfig)
    web_search: LiveWebSearchConfig = field(default_factory=LiveWebSearchConfig)
    crawl: LiveCrawlSearchConfig = field(default_factory=LiveCrawlSearchConfig)
    fetch: LiveHttpFetchConfig = field(default_factory=LiveHttpFetchConfig)
    search_strategy: str = "fallback"
    max_sources_per_provider: int | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveRetrievalConfig":
        values = os.environ if env is None else env
        enabled = _truthy(values.get(LIVE_RETRIEVAL_ENV))
        allow_all_hosts = _truthy(values.get(LIVE_ALLOW_ALL_HOSTS_ENV))
        allowed_schemes = _csv(values.get(LIVE_ALLOWED_SCHEMES_ENV)) or ["https"]
        timeout_seconds = _positive_int(values.get(LIVE_TIMEOUT_SECONDS_ENV), default=20)
        max_bytes = _positive_int(values.get(LIVE_MAX_BYTES_ENV), default=DEFAULT_LIVE_MAX_BYTES)
        source_directory_allowlist = _truthy(values.get(LIVE_SOURCE_DIRECTORY_ALLOWLIST_ENV))
        source_directory_hosts = _source_directory_allowed_hosts() if source_directory_allowlist else []
        web_search_providers = _csv(values.get(LIVE_WEB_SEARCH_PROVIDERS_ENV))
        web_search_hosts = web_search_engine_hosts(web_search_providers)
        search_allowed_hosts = _ordered_unique(
            [*_csv(values.get(LIVE_SEARCH_ALLOWED_HOSTS_ENV)), *source_directory_hosts, *web_search_hosts]
        )
        fetch_allowed_hosts = _ordered_unique([*_csv(values.get(LIVE_FETCH_ALLOWED_HOSTS_ENV)), *source_directory_hosts])
        allow_discovered_search_hosts = _truthy(values.get(LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV)) or (
            bool(web_search_providers) and not _falsey(values.get(LIVE_FETCH_DISCOVERED_SEARCH_HOSTS_ENV))
        )
        return cls(
            enabled=enabled,
            search=LiveJsonHttpSearchConfig(
                enabled=enabled,
                endpoint_url=_optional(values.get(LIVE_SEARCH_ENDPOINT_ENV)),
                allowed_hosts=search_allowed_hosts,
                allow_all_hosts=allow_all_hosts,
                allowed_schemes=allowed_schemes,
                query_param=_optional(values.get(LIVE_SEARCH_QUERY_PARAM_ENV)) or "q",
                results_path=_path(values.get(LIVE_SEARCH_RESULTS_PATH_ENV)),
                api_key_env=_optional(values.get(LIVE_SEARCH_API_KEY_ENV_ENV)),
                api_key_header=_optional(values.get(LIVE_SEARCH_API_KEY_HEADER_ENV)),
                api_key_prefix=str(values.get(LIVE_SEARCH_API_KEY_PREFIX_ENV, "") or ""),
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
            web_search=LiveWebSearchConfig(
                enabled=enabled,
                providers=web_search_providers,
                allowed_hosts=search_allowed_hosts,
                allow_all_hosts=allow_all_hosts,
                allowed_schemes=allowed_schemes,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
                max_results_per_engine=_positive_int(values.get(LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE_ENV), default=10),
            ),
            crawl=LiveCrawlSearchConfig(
                enabled=enabled,
                seed_urls=_csv(values.get(LIVE_CRAWL_SEED_URLS_ENV)),
                allowed_hosts=search_allowed_hosts,
                allow_all_hosts=allow_all_hosts,
                allowed_schemes=allowed_schemes,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
                max_pages=_positive_int(values.get(LIVE_CRAWL_MAX_PAGES_ENV), default=3),
                max_links_per_page=_positive_int(values.get(LIVE_CRAWL_MAX_LINKS_PER_PAGE_ENV), default=20),
                include_sitemaps=not _falsey(values.get(LIVE_CRAWL_INCLUDE_SITEMAPS_ENV)),
                max_sitemap_urls=_positive_int(values.get(LIVE_CRAWL_MAX_SITEMAP_URLS_ENV), default=50),
                include_source_directory_seeds=_truthy(values.get(LIVE_CRAWL_SOURCE_DIRECTORY_ENV)),
                max_source_directory_seeds=_positive_int(values.get(LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS_ENV), default=12),
            ),
            fetch=LiveHttpFetchConfig(
                enabled=enabled,
                allowed_hosts=fetch_allowed_hosts,
                allow_all_hosts=allow_all_hosts,
                allow_discovered_search_hosts=allow_discovered_search_hosts,
                allowed_schemes=allowed_schemes,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
            search_strategy=_search_strategy(values.get(LIVE_SEARCH_STRATEGY_ENV)),
            max_sources_per_provider=_optional_positive_int(values.get(LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER_ENV)),
        )

    def build_operator(
        self,
        *,
        artifact_store: object | None = None,
        corpus_store: object | None = None,
        search_transport: HttpTransport | None = None,
        crawl_transport: HttpTransport | None = None,
        fetch_transport: HttpTransport | None = None,
    ) -> RetrievalOperator:
        corpus_enabled = corpus_store is not None and artifact_store is not None
        search_providers = []
        if corpus_enabled:
            search_providers.append(CorpusSearchProvider(corpus_store))
        search_providers.append(DirectUrlSearchProvider())
        search_providers.append(FredSearchProvider())
        search_providers.append(FiscalDataSearchProvider())
        search_providers.append(SecEdgarSearchProvider())
        search_providers.append(ResearchSourceQuerySearchProvider())
        if self.search.configured:
            search_providers.append(self.search.build_provider(transport=search_transport))
        if self.web_search.configured:
            search_providers.append(self.web_search.build_provider(transport=search_transport))
        if self.crawl.configured:
            search_providers.append(self.crawl.build_provider(transport=crawl_transport))
        search_providers.append(SourceDirectorySearchProvider())
        if self.search_strategy == "aggregate":
            search_provider = AggregateSearchProvider(
                search_providers,
                max_sources_per_provider=self.max_sources_per_provider,
            )
        elif self.search_strategy == "adaptive":
            search_provider = AdaptiveSearchProvider(
                search_providers,
                default_strategy="fallback",
                max_sources_per_provider=self.max_sources_per_provider,
            )
        else:
            search_provider = FallbackSearchProvider(search_providers)
        live_fetch_provider = self.fetch.build_provider(transport=fetch_transport)
        fetch_provider = (
            RoutingFetchProvider(
                routes={"research_corpus": CorpusFetchProvider(artifact_store)},
                fallback=live_fetch_provider,
            )
            if corpus_enabled
            else live_fetch_provider
        )
        return RetrievalOperator(
            search_provider=search_provider,
            fetch_provider=fetch_provider,
            corpus_store=corpus_store,
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "enabled": self.enabled,
            "env_gate": LIVE_RETRIEVAL_ENV,
            "search_strategy": self.search_strategy,
            "max_sources_per_provider": self.max_sources_per_provider,
            "search": self.search.safe_diagnostics(),
            "web_search": self.web_search.safe_diagnostics(),
            "crawl": self.crawl.safe_diagnostics(),
            "fetch": self.fetch.safe_diagnostics(),
        }


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsey(value: object) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


def _optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _csv(value: object) -> list[str]:
    text = str(value or "")
    return [part.strip().lower() for part in text.split(",") if part.strip()]


def _path(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return ["results"]
    separator = "." if "." in text else ","
    return [part.strip() for part in text.split(separator) if part.strip()] or ["results"]


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return max(1, parsed)


def _optional_positive_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _source_directory_allowed_hosts() -> list[str]:
    hosts: list[str] = []
    for entry in source_directory_for_profile(FINANCE_FUNDAMENTALS_PROFILE_ID):
        for host in entry.allowed_hosts:
            text = str(host or "").strip().lower()
            if not text or "*" in text or "example." in text:
                continue
            hosts.append(text)
    return _ordered_unique(hosts)


def _search_strategy(value: object) -> str:
    normalized = str(value or "fallback").strip().lower()
    if normalized in {"aggregate", "merged", "blend", "blended"}:
        return "aggregate"
    if normalized in {"adaptive", "dynamic", "planner", "model"}:
        return "adaptive"
    return "fallback"


def _safe_url_diagnostics(uri: str) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    return {
        "url_scheme": parsed.scheme,
        "host_hash": hashlib.sha256(host.lower().encode("utf-8")).hexdigest() if host else "",
    }


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
