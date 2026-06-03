from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from html.parser import HTMLParser

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research import source_directory_for_profile
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.http_provider import HttpTransport, HttpTransportResponse
from kernel_v3.retrieval.source_directory_rank import rank_source_directory_entries


URL_PATTERN = re.compile(r"https?://[^\s<>'\")\]]+", re.IGNORECASE)
SITEMAP_LOC_PATTERN = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)
QUERY_TERM_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")
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
        ranked_entries = rank_source_directory_entries(entries, query=query, metadata=goal.metadata)
        sources: list[SearchSource] = []
        for ranked_entry in ranked_entries:
            entry = ranked_entry.entry
            if not _safe_url(entry.base_url):
                continue
            rank = len(sources) + 1
            source_metadata = {
                "rank": rank,
                "research_profile": profile_id,
                "source_directory_id": entry.source_id,
                "source_family": entry.source_family,
                "authority_level": entry.authority_level,
                "allowed_hosts": list(entry.allowed_hosts),
                "source_directory_relevance_score": round(ranked_entry.score, 6),
            }
            if ranked_entry.matched_terms:
                source_metadata["matched_query_terms"] = ranked_entry.matched_terms[:12]
            target_terms = _metadata_string_list(entry.metadata, "target_terms")
            if target_terms:
                source_metadata["target_terms"] = target_terms[:12]
            sources.append(
                SearchSource(
                    source_id=f"{self.provider_id}-{_hash(entry.source_id)[:12]}-{rank}",
                    uri=entry.base_url,
                    title=entry.title,
                    snippet="; ".join(entry.query_hints[:3]) or entry.title,
                    provider=self.provider_id,
                    metadata=source_metadata,
                )
            )
            if len(sources) >= max(0, int(goal.max_sources)):
                break
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "research_profile": profile_id,
            "entry_count": len(entries),
            "source_count": len(sources),
            "ranked_entry_count": len(ranked_entries),
            "query_aware_ranking": True,
            "top_source_directory_ids": [
                str(source.metadata.get("source_directory_id"))
                for source in sources[:5]
                if isinstance(source.metadata.get("source_directory_id"), str)
            ],
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
        include_sitemaps: bool = True,
        max_sitemap_urls: int = 50,
        include_source_directory_seeds: bool = False,
        max_source_directory_seeds: int = 12,
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
        self.include_sitemaps = bool(include_sitemaps)
        self.max_sitemap_urls = max(0, int(max_sitemap_urls))
        self.include_source_directory_seeds = bool(include_source_directory_seeds)
        self.max_source_directory_seeds = max(0, int(max_source_directory_seeds))
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
            "include_sitemaps": self.include_sitemaps,
            "max_sitemap_urls": self.max_sitemap_urls,
            "include_source_directory_seeds": self.include_source_directory_seeds,
            "max_source_directory_seeds": self.max_source_directory_seeds,
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        source_limit = max(0, int(goal.max_sources))
        if source_limit <= 0:
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
        source_directory_seeds = _source_directory_seed_urls(
            goal.metadata,
            enabled=self.include_source_directory_seeds,
            max_count=self.max_source_directory_seeds,
        )
        seeds = _safe_unique_urls([*self.seed_urls, *_candidate_seed_urls(query, goal.metadata), *source_directory_seeds])
        if not seeds:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "no_seed_urls",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        seed_sources: list[SearchSource] = []
        candidate_sources: list[SearchSource] = []
        fetched = 0
        failed = 0
        fetched_sitemaps = 0
        failed_sitemaps = 0
        seen_sitemaps: set[str] = set()
        seen_source_uris: set[str] = set()
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
                index=len(seed_sources) + 1,
                title="crawl seed",
                snippet="Seed URL for bounded crawl discovery.",
                metadata={"source_kind": "crawl_seed"},
            )
            if seed_source is not None:
                _append_unique_source(seed_sources, seed_source, seen_uris=seen_source_uris)
            response = self._fetch_discovery_url(seed)
            if response is None:
                failed += 1
            else:
                fetched += 1
            if response is not None and _response_ok(response, self.max_bytes):
                body = response.body.decode("utf-8", errors="replace")
                for link in _extract_links(body, base_url=seed)[: self.max_links_per_page]:
                    if not _validate_url(
                        link["url"],
                        allowed_schemes=self.allowed_schemes,
                        allowed_hosts=self.allowed_hosts,
                        allow_all_hosts=self.allow_all_hosts,
                    ).get("status") == "ok":
                        continue
                    _append_unique_source(
                        candidate_sources,
                        _source_from_url(
                            link["url"],
                            provider_id=self.provider_id,
                            index=len(seed_sources) + len(candidate_sources) + 1,
                            title=link["text"] or _title_from_url(link["url"]),
                            snippet=f"Discovered from seed page. Path: {_path_text(link['url'])}",
                            metadata={"source_kind": "crawl_discovered", "seed_hash": _hash(seed)},
                        ),
                        seen_uris=seen_source_uris,
                    )
            elif response is not None:
                failed += 1
            if self.include_sitemaps:
                for sitemap_url in _sitemap_candidates(seed):
                    if sitemap_url in seen_sitemaps:
                        break
                    seen_sitemaps.add(sitemap_url)
                    if not _validate_url(
                        sitemap_url,
                        allowed_schemes=self.allowed_schemes,
                        allowed_hosts=self.allowed_hosts,
                        allow_all_hosts=self.allow_all_hosts,
                    ).get("status") == "ok":
                        failed_sitemaps += 1
                        continue
                    sitemap_response = self._fetch_discovery_url(sitemap_url, accept="application/xml,text/xml,text/plain")
                    if sitemap_response is None:
                        failed_sitemaps += 1
                        continue
                    fetched_sitemaps += 1
                    if not _response_ok(sitemap_response, self.max_bytes):
                        failed_sitemaps += 1
                        continue
                    sitemap_body = sitemap_response.body.decode("utf-8", errors="replace")
                    for link in _extract_sitemap_links(sitemap_body, base_url=sitemap_url)[: self.max_sitemap_urls]:
                        if not _validate_url(
                            link,
                            allowed_schemes=self.allowed_schemes,
                            allowed_hosts=self.allowed_hosts,
                            allow_all_hosts=self.allow_all_hosts,
                        ).get("status") == "ok":
                            continue
                        _append_unique_source(
                            candidate_sources,
                            _source_from_url(
                                link,
                                provider_id=self.provider_id,
                                index=len(seed_sources) + len(candidate_sources) + 1,
                                title=_title_from_url(link),
                                snippet=f"Discovered from sitemap. Path: {_path_text(link)}",
                                metadata={"source_kind": "crawl_sitemap", "sitemap_hash": _hash(sitemap_url)},
                            ),
                            seen_uris=seen_source_uris,
                        )
        query_terms = _query_terms(query, goal.metadata)
        ranked_candidates = _rank_crawl_candidates(candidate_sources, query_terms=query_terms)
        sources = _reindex_sources([*seed_sources, *ranked_candidates][:source_limit], query_terms=query_terms)
        self._last_search_diagnostics = {
            "status": "ok" if sources else "failed" if failed or failed_sitemaps else "empty",
            "seed_count": len(seeds),
            "configured_seed_count": len(self.seed_urls),
            "source_directory_seed_count": len(source_directory_seeds),
            "fetched_seed_count": fetched,
            "failed_seed_count": failed,
            "fetched_sitemap_count": fetched_sitemaps,
            "failed_sitemap_count": failed_sitemaps,
            "candidate_source_count": len(candidate_sources),
            "ranked_candidate_count": len(ranked_candidates),
            "matched_candidate_count": sum(1 for source in ranked_candidates if float(source.metadata.get("query_relevance_score") or 0.0) > 0.0),
            "query_aware_ranking": True,
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def _fetch_discovery_url(self, url: str, *, accept: str = "text/html,text/plain,application/xhtml+xml") -> HttpTransportResponse | None:
        try:
            return self.transport(
                url,
                {"User-Agent": self.user_agent, "Accept": accept},
                self.timeout_seconds,
                self.max_bytes,
            )
        except Exception:
            return None

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


def _extract_sitemap_links(body: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    for raw in SITEMAP_LOC_PATTERN.findall(body):
        url = urllib.parse.urljoin(base_url, html_unescape(raw.strip()))
        if _safe_url(url):
            links.append(url)
    return _safe_unique_urls(links)


def html_unescape(value: str) -> str:
    return value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _sitemap_candidates(seed_url: str) -> list[str]:
    parsed = urllib.parse.urlparse(seed_url)
    if not parsed.scheme or not parsed.hostname:
        return []
    root = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
    candidates = [urllib.parse.urljoin(root, "sitemap.xml")]
    if parsed.path.lower().endswith("sitemap.xml"):
        candidates.insert(0, seed_url)
    return _safe_unique_urls(candidates)


def _response_ok(response: HttpTransportResponse, max_bytes: int) -> bool:
    return 200 <= response.status_code < 300 and len(response.body) <= max_bytes


def _append_unique_source(sources: list[SearchSource], source: SearchSource | None, *, seen_uris: set[str]) -> None:
    if source is None or source.uri in seen_uris:
        return
    seen_uris.add(source.uri)
    sources.append(source)


def _rank_crawl_candidates(sources: list[SearchSource], *, query_terms: list[str]) -> list[SearchSource]:
    scored: list[tuple[float, int, SearchSource]] = []
    for index, source in enumerate(sources):
        score, matched = _query_relevance(source, query_terms=query_terms)
        metadata = dict(source.metadata)
        metadata["query_relevance_score"] = round(score, 6)
        if matched:
            metadata["matched_query_terms"] = matched[:12]
        scored.append((score, index, replace(source, metadata=metadata)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [source for _score, _index, source in scored]


def _reindex_sources(sources: list[SearchSource], *, query_terms: list[str]) -> list[SearchSource]:
    result: list[SearchSource] = []
    for index, source in enumerate(sources, start=1):
        score, matched = _query_relevance(source, query_terms=query_terms)
        metadata = dict(source.metadata)
        metadata["rank"] = index
        metadata.setdefault("query_relevance_score", round(score, 6))
        if matched:
            metadata.setdefault("matched_query_terms", matched[:12])
        result.append(replace(source, metadata=metadata))
    return result


def _query_relevance(source: SearchSource, *, query_terms: list[str]) -> tuple[float, list[str]]:
    if not query_terms:
        return 0.0, []
    haystack = " ".join(
        [
            source.title,
            source.snippet,
            _path_text(source.uri),
            urllib.parse.urlparse(source.uri).hostname or "",
        ]
    ).lower()
    matched = [term for term in query_terms if term in haystack]
    if not matched:
        return 0.0, []
    return len(matched) / max(1, len(query_terms)), matched


def _query_terms(query: str, metadata: JsonObject) -> list[str]:
    raw_values = [query]
    raw_values.extend(_metadata_text_values(metadata))
    terms: list[str] = []
    for value in raw_values:
        for token in QUERY_TERM_PATTERN.findall(str(value).lower()):
            if len(token) >= 2:
                terms.append(token)
            if _contains_cjk(token) and len(token) >= 4:
                terms.extend(token[index : index + 2] for index in range(0, len(token) - 1))
    return _ordered_unique(terms)[:80]


def _metadata_text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if str(key).lower() in {"api_key", "token", "password", "secret", "authorization"}:
                continue
            result.extend(_metadata_text_values(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_metadata_text_values(item))
        return result
    return []


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _candidate_urls(query: str, metadata: JsonObject) -> list[str]:
    values: list[str] = []
    values.extend(URL_PATTERN.findall(query or ""))
    values.extend(_metadata_urls(metadata, keys=("url", "urls", "source_url", "source_urls")))
    return _safe_unique_urls(values)


def _candidate_seed_urls(query: str, metadata: JsonObject) -> list[str]:
    values = _candidate_urls(query, metadata)
    values.extend(_metadata_urls(metadata, keys=("seed_url", "seed_urls", "crawl_seed_url", "crawl_seed_urls")))
    return _safe_unique_urls(values)


def _source_directory_seed_urls(metadata: JsonObject, *, enabled: bool, max_count: int) -> list[str]:
    if not enabled or max_count <= 0:
        return []
    profile_id = _research_profile_id(metadata)
    if profile_id is None:
        return []
    urls: list[str] = []
    for entry in source_directory_for_profile(profile_id):
        candidates = [entry.base_url]
        extra = entry.metadata.get("crawl_seed_urls") if isinstance(entry.metadata, dict) else None
        if isinstance(extra, list):
            candidates.extend(str(item) for item in extra if isinstance(item, str))
        for url in candidates:
            if _source_directory_seed_is_usable(url):
                urls.append(url)
            if len(urls) >= max_count:
                return _safe_unique_urls(urls)
    return _safe_unique_urls(urls)


def _source_directory_seed_is_usable(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not _safe_url(url):
        return False
    if not host or "example." in host or "*" in host:
        return False
    return True


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
    display_title = title if title and title != "direct URL" else _title_from_url(url)
    return SearchSource(
        source_id=f"{provider_id}-{_hash(url)[:12]}-{index}",
        uri=url,
        title=_bounded_text(display_title, 240),
        snippet=_bounded_text(snippet, 800),
        provider=provider_id,
        metadata={"rank": index, **metadata},
    )


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return parsed.hostname or url
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if not stem:
        stem = path
    return _bounded_text(stem.replace("_", " ").replace("-", " "), 240)


def _path_text(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = " ".join(parsed.path.strip("/").replace("_", " ").replace("-", " ").split("/"))
    return _bounded_text(path or (parsed.hostname or ""), 240)


def _research_profile_id(metadata: JsonObject) -> str | None:
    for key in ("research_profile_id", "research_profile"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _research_profile_id(nested)
    return None


def _metadata_string_list(metadata: JsonObject, key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _metadata_string_list(nested, key)
    return []


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
