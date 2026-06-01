from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research import source_directory_for_profile
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.http_provider import HttpTransport, HttpTransportResponse


URL_PATTERN = re.compile(r"https?://[^\s<>'\")\]]+", re.IGNORECASE)
SAFE_SCHEMES = {"http", "https"}


class DirectUrlSearchProvider:
    provider_id = "direct_url_search"
    live_network = False
    default_enabled = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {"source": "direct_url_search"}

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        urls = _candidate_urls(query, goal.metadata)
        sources = _sources_from_urls(
            urls,
            provider_id=self.provider_id,
            snippet="Direct URL supplied by user or host metadata.",
            max_sources=goal.max_sources,
        )
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "candidate_url_count": len(urls),
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


class SourceDirectorySearchProvider:
    provider_id = "research_source_directory_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = ["*"]

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {"source": "research_source_directory"}

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        profile_id = _research_profile_id(goal.metadata)
        if profile_id is None:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "no_research_profile",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        entries = source_directory_for_profile(profile_id)
        sources: list[SearchSource] = []
        for entry in entries:
            if not _safe_url(entry.base_url):
                continue
            sources.append(
                SearchSource(
                    source_id=f"{self.provider_id}-{_hash(entry.source_id)[:12]}-{len(sources) + 1}",
                    uri=entry.base_url,
                    title=entry.title,
                    snippet="; ".join(entry.query_hints[:3]) or entry.title,
                    provider=self.provider_id,
                    metadata={
                        "rank": len(sources) + 1,
                        "research_profile": profile_id,
                        "source_directory_id": entry.source_id,
                        "source_family": entry.source_family,
                        "authority_level": entry.authority_level,
                        "allowed_hosts": list(entry.allowed_hosts),
                    },
                )
            )
            if len(sources) >= max(0, int(goal.max_sources)):
                break
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "research_profile": profile_id,
            "entry_count": len(entries),
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


class BoundedCrawlSearchProvider:
    provider_id = "bounded_crawl_search"
    live_network = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(
        self,
        *,
        enabled: bool = False,
        seed_urls: list[str] | None = None,
        allowed_hosts: list[str] | None = None,
        allow_all_hosts: bool = False,
        allowed_schemes: list[str] | None = None,
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        max_pages: int = 3,
        max_links_per_page: int = 20,
        user_agent: str = "holo-kernel-v3/1.0",
        transport: HttpTransport | None = None,
    ) -> None:
        self.default_enabled = bool(enabled)
        self.seed_urls = _safe_unique_urls(seed_urls or [])
        self.allowed_hosts = _normalize_hosts(allowed_hosts or [])
        self.allow_all_hosts = bool(allow_all_hosts)
        self.allowed_schemes = _normalize_schemes(allowed_schemes or ["https"])
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.max_pages = max(0, int(max_pages))
        self.max_links_per_page = max(0, int(max_links_per_page))
        self.user_agent = user_agent
        self.transport = transport or _urllib_transport
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "bounded_crawl_search",
            "enabled": self.default_enabled,
            "seed_count": len(self.seed_urls),
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_host_count": len(self.allowed_hosts),
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_pages": self.max_pages,
            "max_links_per_page": self.max_links_per_page,
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        if int(goal.max_sources) <= 0:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "max_sources_exhausted",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        if not self.default_enabled:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "disabled_by_default",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        seeds = _safe_unique_urls([*self.seed_urls, *_candidate_seed_urls(query, goal.metadata)])
        if not seeds:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "no_seed_urls",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        sources: list[SearchSource] = []
        fetched = 0
        failed = 0
        for seed in seeds[: self.max_pages]:
            validation = _validate_url(
                seed,
                allowed_schemes=self.allowed_schemes,
                allowed_hosts=self.allowed_hosts,
                allow_all_hosts=self.allow_all_hosts,
            )
            if validation.get("status") != "ok":
                failed += 1
                continue
            seed_source = _source_from_url(
                seed,
                provider_id=self.provider_id,
                index=len(sources) + 1,
                title="crawl seed",
                snippet="Seed URL for bounded crawl discovery.",
                metadata={"source_kind": "crawl_seed"},
            )
            if seed_source is not None:
                sources.append(seed_source)
            try:
                response = self.transport(
                    seed,
                    {"User-Agent": self.user_agent, "Accept": "text/html,text/plain,application/xhtml+xml"},
                    self.timeout_seconds,
                    self.max_bytes,
                )
            except Exception:
                failed += 1
                continue
            fetched += 1
            if response.status_code < 200 or response.status_code >= 300 or len(response.body) > self.max_bytes:
                failed += 1
                continue
            body = response.body.decode("utf-8", errors="replace")
            for link in _extract_links(body, base_url=seed)[: self.max_links_per_page]:
                if len(sources) >= max(0, int(goal.max_sources)):
                    break
                if not _validate_url(
                    link["url"],
                    allowed_schemes=self.allowed_schemes,
                    allowed_hosts=self.allowed_hosts,
                    allow_all_hosts=self.allow_all_hosts,
                ).get("status") == "ok":
                    continue
                source = _source_from_url(
                    link["url"],
                    provider_id=self.provider_id,
                    index=len(sources) + 1,
                    title=link["text"] or "discovered page",
                    snippet=f"Discovered from seed page. Query: {_bounded_text(query, 160)}",
                    metadata={"source_kind": "crawl_discovered", "seed_hash": _hash(seed)},
                )
                if source is not None and source.uri not in {item.uri for item in sources}:
                    sources.append(source)
        self._last_search_diagnostics = {
            "status": "ok" if sources else "failed" if failed else "empty",
            "seed_count": len(seeds),
            "fetched_seed_count": fetched,
            "failed_seed_count": failed,
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources[: max(0, int(goal.max_sources))]

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if isinstance(href, str) and href.strip():
            self._current_href = href.strip()
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        self.links.append(
            {
                "href": self._current_href,
                "text": _bounded_text(" ".join("".join(self._current_text).split()), 240),
            }
        )
        self._current_href = None
        self._current_text = []


def _extract_links(body: str, *, base_url: str) -> list[JsonObject]:
    parser = _LinkParser()
    parser.feed(body)
    links = []
    for item in parser.links:
        href = str(item.get("href") or "")
        url = urllib.parse.urljoin(base_url, href)
        if not _safe_url(url):
            continue
        links.append({"url": url, "text": str(item.get("text") or "")})
    return links


def _candidate_urls(query: str, metadata: JsonObject) -> list[str]:
    values: list[str] = []
    values.extend(URL_PATTERN.findall(query or ""))
    values.extend(_metadata_urls(metadata, keys=("url", "urls", "source_url", "source_urls")))
    return _safe_unique_urls(values)


def _candidate_seed_urls(query: str, metadata: JsonObject) -> list[str]:
    values = _candidate_urls(query, metadata)
    values.extend(_metadata_urls(metadata, keys=("seed_url", "seed_urls", "crawl_seed_url", "crawl_seed_urls")))
    return _safe_unique_urls(values)


def _metadata_urls(metadata: JsonObject, *, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        values.extend(_metadata_urls(nested, keys=keys))
    return values


def _sources_from_urls(urls: list[str], *, provider_id: str, snippet: str, max_sources: int) -> list[SearchSource]:
    sources: list[SearchSource] = []
    for url in urls:
        source = _source_from_url(
            url,
            provider_id=provider_id,
            index=len(sources) + 1,
            title="direct URL",
            snippet=snippet,
            metadata={"source_kind": "direct_url"},
        )
        if source is None:
            continue
        sources.append(source)
        if len(sources) >= max(0, int(max_sources)):
            break
    return sources


def _source_from_url(
    url: str,
    *,
    provider_id: str,
    index: int,
    title: str,
    snippet: str,
    metadata: JsonObject,
) -> SearchSource | None:
    if not _safe_url(url):
        return None
    parsed = urllib.parse.urlparse(url)
    display_title = title if title and title != "direct URL" else (parsed.path.strip("/") or parsed.hostname or url)
    return SearchSource(
        source_id=f"{provider_id}-{_hash(url)[:12]}-{index}",
        uri=url,
        title=_bounded_text(display_title, 240),
        snippet=_bounded_text(snippet, 800),
        provider=provider_id,
        metadata={"rank": index, **metadata},
    )


def _research_profile_id(metadata: JsonObject) -> str | None:
    for key in ("research_profile_id", "research_profile"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _research_profile_id(nested)
    return None


def _validate_url(
    uri: str,
    *,
    allowed_schemes: tuple[str, ...],
    allowed_hosts: set[str],
    allow_all_hosts: bool,
) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in allowed_schemes:
        return {"status": "failed", "reason": "url_scheme_not_allowed", **_safe_url_diagnostics(uri)}
    if not parsed.hostname:
        return {"status": "failed", "reason": "missing_url_host", **_safe_url_diagnostics(uri)}
    if parsed.username or parsed.password:
        return {"status": "failed", "reason": "url_credentials_not_allowed", **_safe_url_diagnostics(uri)}
    if contains_secret_like_content(parsed.geturl()):
        return {"status": "failed", "reason": "url_secret_like_content_not_allowed", **_safe_url_diagnostics(uri)}
    host = parsed.hostname.lower()
    if not allow_all_hosts and not _host_allowed(host, allowed_hosts):
        return {"status": "failed", "reason": "host_not_allowed", "allowed_host_count": len(allowed_hosts), **_safe_url_diagnostics(uri)}
    return {"status": "ok", **_safe_url_diagnostics(uri)}


def _safe_url(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in SAFE_SCHEMES:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return not contains_secret_like_content(parsed.geturl())


def _safe_unique_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_url(value)
        if not normalized or normalized in seen or not _safe_url(normalized):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_url(value: str) -> str:
    text = str(value or "").strip().strip("<>()[]{}'\"")
    text = text.rstrip(".,;:")
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme:
        return ""
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def _normalize_hosts(hosts: list[str]) -> set[str]:
    normalized: set[str] = set()
    for raw in hosts:
        parsed = urllib.parse.urlparse(str(raw) if "://" in str(raw) else f"//{raw}")
        host = (parsed.hostname or "").lower().rstrip(".")
        if host:
            normalized.add(host)
    return normalized


def _normalize_schemes(schemes: list[str]) -> tuple[str, ...]:
    return tuple(scheme.strip().lower() for scheme in schemes if scheme.strip())


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    return host in allowed_hosts or any(host.endswith("." + allowed) for allowed in allowed_hosts)


def _safe_url_diagnostics(uri: str) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    return {
        "url_scheme": parsed.scheme,
        "host_hash": hashlib.sha256(host.lower().encode("utf-8")).hexdigest() if host else "",
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(text: str, limit: int) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _urllib_transport(url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(max_bytes + 1)
            mime_type = str(response.headers.get_content_type() or "text/plain")
            status_code = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        return HttpTransportResponse(status_code=int(exc.code), body=b"", mime_type="text/plain")
    except urllib.error.URLError as exc:
        raise RuntimeError(type(exc).__name__) from exc
    return HttpTransportResponse(status_code=status_code, body=body, mime_type=mime_type)
