from __future__ import annotations

import hashlib
import os
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.http_provider import (
    HttpFetchProvider,
    HttpTransport,
    JsonHttpSearchProvider,
)
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
LIVE_TIMEOUT_SECONDS_ENV = "HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS"
LIVE_MAX_BYTES_ENV = "HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES"


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
    max_bytes: int = 1_000_000
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
class LiveHttpFetchConfig:
    enabled: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    allowed_schemes: list[str] = field(default_factory=lambda: ["https"])
    timeout_seconds: int = 20
    max_bytes: int = 1_000_000
    user_agent: str = "holo-kernel-v3/1.0"

    def build_provider(self, *, transport: HttpTransport | None = None) -> HttpFetchProvider:
        return HttpFetchProvider(
            enabled=self.enabled,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
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
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True, kw_only=True)
class LiveRetrievalConfig:
    enabled: bool = False
    search: LiveJsonHttpSearchConfig = field(default_factory=LiveJsonHttpSearchConfig)
    fetch: LiveHttpFetchConfig = field(default_factory=LiveHttpFetchConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveRetrievalConfig":
        values = os.environ if env is None else env
        enabled = _truthy(values.get(LIVE_RETRIEVAL_ENV))
        allow_all_hosts = _truthy(values.get(LIVE_ALLOW_ALL_HOSTS_ENV))
        allowed_schemes = _csv(values.get(LIVE_ALLOWED_SCHEMES_ENV)) or ["https"]
        timeout_seconds = _positive_int(values.get(LIVE_TIMEOUT_SECONDS_ENV), default=20)
        max_bytes = _positive_int(values.get(LIVE_MAX_BYTES_ENV), default=1_000_000)
        return cls(
            enabled=enabled,
            search=LiveJsonHttpSearchConfig(
                enabled=enabled,
                endpoint_url=_optional(values.get(LIVE_SEARCH_ENDPOINT_ENV)),
                allowed_hosts=_csv(values.get(LIVE_SEARCH_ALLOWED_HOSTS_ENV)),
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
            fetch=LiveHttpFetchConfig(
                enabled=enabled,
                allowed_hosts=_csv(values.get(LIVE_FETCH_ALLOWED_HOSTS_ENV)),
                allow_all_hosts=allow_all_hosts,
                allowed_schemes=allowed_schemes,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
        )

    def build_operator(
        self,
        *,
        search_transport: HttpTransport | None = None,
        fetch_transport: HttpTransport | None = None,
    ) -> RetrievalOperator:
        return RetrievalOperator(
            search_provider=self.search.build_provider(transport=search_transport),
            fetch_provider=self.fetch.build_provider(transport=fetch_transport),
        )

    def safe_diagnostics(self) -> JsonObject:
        return {
            "enabled": self.enabled,
            "env_gate": LIVE_RETRIEVAL_ENV,
            "search": self.search.safe_diagnostics(),
            "fetch": self.fetch.safe_diagnostics(),
        }


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _safe_url_diagnostics(uri: str) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    return {
        "url_scheme": parsed.scheme,
        "host_hash": hashlib.sha256(host.lower().encode("utf-8")).hexdigest() if host else "",
    }
