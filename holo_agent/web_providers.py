from __future__ import annotations

from dataclasses import asdict, dataclass, field
import queue
import re
import threading
import time
from typing import Any, Protocol
from urllib.parse import quote_plus, urlparse


@dataclass(slots=True)
class SearchAttempt:
    provider: str
    query: str
    status: str
    results: list[dict[str, str]] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SearchProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> SearchAttempt:
        ...


def domain_allowed(url: str, *, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None) -> bool:
    domain = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    if not domain:
        return False
    blocked = [item.lower().removeprefix("www.") for item in blocked_domains or [] if item]
    if any(domain == item or domain.endswith("." + item) for item in blocked):
        return False
    allowed = [item.lower().removeprefix("www.") for item in allowed_domains or [] if item]
    if not allowed:
        return True
    return any(domain == item or domain.endswith("." + item) for item in allowed)


def filter_results_by_domain(
    results: list[dict[str, str]],
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> list[dict[str, str]]:
    return [item for item in results if domain_allowed(item.get("url", ""), allowed_domains=allowed_domains, blocked_domains=blocked_domains)]


def _run_with_timeout(provider: SearchProvider, kwargs: dict[str, Any], timeout_seconds: float) -> SearchAttempt:
    output: queue.Queue[SearchAttempt | BaseException] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            output.put(provider.search(**kwargs))
        except BaseException as exc:  # noqa: BLE001
            output.put(exc)

    started = time.perf_counter()
    thread = threading.Thread(target=target, name=f"holo-search-{provider.name}", daemon=True)
    thread.start()
    try:
        value = output.get(timeout=max(0.001, timeout_seconds))
    except queue.Empty:
        elapsed = int((time.perf_counter() - started) * 1000)
        return SearchAttempt(provider=provider.name, query=str(kwargs.get("query", "")), status="timeout", error="provider_timeout", elapsed_ms=elapsed)
    elapsed = int((time.perf_counter() - started) * 1000)
    if isinstance(value, BaseException):
        return SearchAttempt(provider=provider.name, query=str(kwargs.get("query", "")), status="error", error=str(value), elapsed_ms=elapsed)
    value.elapsed_ms = value.elapsed_ms or elapsed
    return value


@dataclass(slots=True)
class SearchProviderRegistry:
    providers: list[SearchProvider]
    provider_timeout_seconds: float = 8.0
    network_enabled: bool = True
    _attempts: list[SearchAttempt] = field(default_factory=list)
    _last_status: str = "not_run"
    _last_error: str = ""

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> SearchAttempt:
        self._attempts = []
        self._last_error = ""
        if not self.network_enabled:
            attempt = SearchAttempt(provider="network_gate", query=query, status="rejected_network_disabled", error="network_disabled")
            self._attempts.append(attempt)
            self._last_status = attempt.status
            self._last_error = attempt.error
            return attempt
        for provider in self.providers:
            attempt = _run_with_timeout(
                provider,
                {
                    "query": query,
                    "max_results": max_results,
                    "allowed_domains": allowed_domains or [],
                    "blocked_domains": blocked_domains or [],
                    "region": region,
                },
                self.provider_timeout_seconds,
            )
            attempt.results = [
                dict(item)
                for item in filter_results_by_domain(
                    attempt.results,
                    allowed_domains=allowed_domains,
                    blocked_domains=blocked_domains,
                )
            ][:max_results]
            self._attempts.append(attempt)
            if attempt.status == "ok" and attempt.results:
                self._last_status = "ok"
                return attempt
            self._last_error = attempt.error or ("empty_results" if attempt.status == "ok" else attempt.status)
        final_status = "empty" if any(item.status == "ok" for item in self._attempts) else self._attempts[-1].status if self._attempts else "error"
        self._last_status = final_status
        return SearchAttempt(
            provider=self._attempts[-1].provider if self._attempts else "none",
            query=query,
            status=final_status,
            results=[],
            error=self._last_error or "no search results",
            elapsed_ms=sum(item.elapsed_ms for item in self._attempts),
        )

    def health(self) -> dict[str, Any]:
        return {
            "schema": "holo.web_provider_health.v1",
            "network_enabled": self.network_enabled,
            "providers": [provider.name for provider in self.providers],
            "last_status": self._last_status,
            "last_error": self._last_error,
            "attempts": [attempt.to_dict() for attempt in self._attempts],
        }


@dataclass(slots=True)
class HtmlSearchProvider:
    name: str
    search_url_template: str
    fetch_text: Any

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> SearchAttempt:
        started = time.perf_counter()
        page = self.fetch_text(self.search_url_template.format(query=quote_plus(query)))
        results: list[dict[str, str]] = []
        for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.I | re.S):
            if len(results) >= max_results:
                break
            results.append({"title": re.sub(r"<[^>]+>", " ", title).strip(), "url": href, "snippet": "", "provider": self.name})
        return SearchAttempt(provider=self.name, query=query, status="ok", results=results, elapsed_ms=int((time.perf_counter() - started) * 1000))
