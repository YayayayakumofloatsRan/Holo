from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.http_provider import HttpTransport, HttpTransportResponse


WEB_SEARCH_QUERY_TEXT_LIMIT = 1_000
WEB_SEARCH_TITLE_LIMIT = 240
WEB_SEARCH_SNIPPET_LIMIT = 800
WEB_SEARCH_URL_LIMIT = 2_048
SAFE_RESULT_URI_SCHEMES = {"http", "https"}

DUCKDUCKGO_HTML_HOST = "html.duckduckgo.com"
DUCKDUCKGO_LITE_HOST = "lite.duckduckgo.com"
BING_HTML_HOST = "www.bing.com"

SEARCH_ENGINE_HOSTS = {
    "duckduckgo_html": [DUCKDUCKGO_HTML_HOST, "duckduckgo.com"],
    "duckduckgo_lite": [DUCKDUCKGO_LITE_HOST, "duckduckgo.com"],
    "bing_html": [BING_HTML_HOST, "bing.com"],
}

DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*\bresult__a\b[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
DDG_SNIPPET_RE = re.compile(
    r'<(?:a|div)[^>]+class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(?P<snippet>.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
BING_RESULT_RE = re.compile(
    r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?<h2[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?(?:<p[^>]*>(?P<snippet>.*?)</p>)?',
    re.IGNORECASE | re.DOTALL,
)
BING_BLOCK_RE = re.compile(
    r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>(?P<block>.*?)(?=<li[^>]+class="[^"]*\bb_algo\b|</ol>|$)',
    re.IGNORECASE | re.DOTALL,
)
BING_TITLE_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
BING_SNIPPET_RE = re.compile(
    r'<div[^>]+class="[^"]*\bb_caption\b[^"]*"[^>]*>.*?<p[^>]*>(?P<snippet>.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, kw_only=True)
class WebSearchEngine:
    engine_id: str
    endpoint_url: str
    query_param: str = "q"
    result_parser: str = "generic"


class LiveWebSearchProvider:
    provider_id = "live_web_search"
    live_network = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(
        self,
        *,
        enabled: bool = False,
        engines: list[str] | None = None,
        allowed_hosts: list[str] | None = None,
        allow_all_hosts: bool = False,
        allowed_schemes: list[str] | None = None,
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        max_results_per_engine: int = 10,
        user_agent: str = "Mozilla/5.0",
        transport: HttpTransport | None = None,
    ) -> None:
        self.default_enabled = bool(enabled)
        self.engines = [_engine_for_id(engine_id) for engine_id in _normalize_engines(engines or [])]
        self.allowed_hosts = _normalize_hosts([*(allowed_hosts or []), *web_search_engine_hosts(engines or [])])
        self.allow_all_hosts = bool(allow_all_hosts)
        self.allowed_schemes = _normalize_schemes(allowed_schemes or ["https"])
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.max_results_per_engine = max(1, int(max_results_per_engine))
        self.user_agent = user_agent
        self.transport = transport or _urllib_transport
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "live_web_search",
            "enabled": self.default_enabled,
            "engine_ids": [engine.engine_id for engine in self.engines],
            "engine_count": len(self.engines),
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_host_count": len(self.allowed_hosts),
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_results_per_engine": self.max_results_per_engine,
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        query_text = _bounded_text(query, WEB_SEARCH_QUERY_TEXT_LIMIT)
        if not self.default_enabled:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "disabled_by_default",
                "query_hash": _hash(query_text),
                "plan_id": plan.plan_id,
            }
            return []
        if not self.engines:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "no_web_search_engines_configured",
                "query_hash": _hash(query_text),
                "plan_id": plan.plan_id,
            }
            return []
        if not query_text or contains_secret_like_content(query_text):
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "unsafe_or_empty_query",
                "query_hash": _hash(query_text),
                "plan_id": plan.plan_id,
            }
            return []

        attempts: list[JsonObject] = []
        collected: list[SearchSource] = []
        seen_uris: set[str] = set()
        source_limit = max(0, int(goal.max_sources))
        for engine in self.engines:
            if source_limit and len(collected) >= source_limit:
                break
            search_url = _url_with_query(engine.endpoint_url, engine.query_param, query_text)
            validation = _validate_url(
                search_url,
                allowed_schemes=self.allowed_schemes,
                allowed_hosts=self.allowed_hosts,
                allow_all_hosts=self.allow_all_hosts,
            )
            if validation.get("status") != "ok":
                attempts.append(
                    {
                        "engine_id": engine.engine_id,
                        "status": "failed",
                        "reason": validation.get("reason", "url_not_allowed"),
                        **_safe_url_diagnostics(search_url),
                    }
                )
                continue
            try:
                response = self.transport(
                    search_url,
                    {"User-Agent": self.user_agent, "Accept": "text/html,text/plain,application/xhtml+xml"},
                    self.timeout_seconds,
                    self.max_bytes,
                )
            except Exception as exc:  # pragma: no cover - concrete transports are tested with injected callables.
                attempts.append(
                    {
                        "engine_id": engine.engine_id,
                        "status": "failed",
                        "reason": "http_transport_error",
                        "error": type(exc).__name__,
                        **_safe_url_diagnostics(search_url),
                    }
                )
                continue
            if response.status_code < 200 or response.status_code >= 300:
                attempts.append(
                    {
                        "engine_id": engine.engine_id,
                        "status": "failed",
                        "reason": "http_status_error",
                        "status_code": response.status_code,
                        **_safe_url_diagnostics(search_url),
                    }
                )
                continue
            if len(response.body) > self.max_bytes:
                attempts.append(
                    {
                        "engine_id": engine.engine_id,
                        "status": "failed",
                        "reason": "http_body_too_large",
                        "max_bytes": self.max_bytes,
                        **_safe_url_diagnostics(search_url),
                    }
                )
                continue
            body = response.body.decode("utf-8", errors="replace")
            parsed = _parse_search_results(
                body,
                engine=engine,
                max_results=min(self.max_results_per_engine, source_limit or self.max_results_per_engine),
            )
            accepted = 0
            for result in parsed:
                uri = str(result.get("uri") or "")
                if not uri or uri in seen_uris:
                    continue
                seen_uris.add(uri)
                accepted += 1
                collected.append(
                    SearchSource(
                        source_id=f"{self.provider_id}-{_hash(uri)[:12]}-{len(collected) + 1}",
                        uri=uri,
                        title=_safe_result_text(str(result.get("title") or uri), WEB_SEARCH_TITLE_LIMIT),
                        snippet=_safe_result_text(str(result.get("snippet") or ""), WEB_SEARCH_SNIPPET_LIMIT),
                        provider=self.provider_id,
                        metadata={
                            "rank": len(collected) + 1,
                            "engine_id": engine.engine_id,
                            "source_kind": "web_search_result",
                            "search_result_fetch_allowed": True,
                            "result_host_hash": _host_hash(uri),
                        },
                    )
                )
                if source_limit and len(collected) >= source_limit:
                    break
            attempts.append(
                {
                    "engine_id": engine.engine_id,
                    "status": "ok" if parsed else "empty",
                    "result_count": len(parsed),
                    "accepted_source_count": accepted,
                    "status_code": response.status_code,
                    "byte_count": len(response.body),
                    **_safe_url_diagnostics(search_url),
                }
            )

        self._last_search_diagnostics = {
            "provider_id": self.provider_id,
            "status": "ok" if collected else _empty_status(attempts),
            "attempts": attempts,
            "engine_count": len(self.engines),
            "returned_source_count": len(collected),
            "query_hash": _hash(query_text),
            "plan_id": plan.plan_id,
        }
        return collected[:source_limit] if source_limit else []

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def web_search_engine_hosts(engine_ids: list[str] | None) -> list[str]:
    hosts: list[str] = []
    for engine_id in _normalize_engines(engine_ids or []):
        hosts.extend(SEARCH_ENGINE_HOSTS.get(engine_id, []))
    return _ordered_unique(hosts)


def supported_web_search_engines() -> list[str]:
    return sorted(SEARCH_ENGINE_HOSTS)


def _normalize_engines(engine_ids: list[str]) -> list[str]:
    values = []
    for raw in engine_ids:
        for part in str(raw or "").split(","):
            normalized = part.strip().lower().replace("-", "_")
            if normalized in {"default", "auto", "web"}:
                values.extend(["bing_html", "duckduckgo_html"])
                continue
            if normalized in {"duckduckgo", "ddg", "ddg_html"}:
                normalized = "duckduckgo_html"
            elif normalized in {"ddg_lite", "duckduckgo"}:
                normalized = "duckduckgo_lite"
            elif normalized in {"bing", "bing_search"}:
                normalized = "bing_html"
            if normalized in SEARCH_ENGINE_HOSTS:
                values.append(normalized)
    return _ordered_unique(values)


def _engine_for_id(engine_id: str) -> WebSearchEngine:
    if engine_id == "duckduckgo_lite":
        return WebSearchEngine(
            engine_id=engine_id,
            endpoint_url=f"https://{DUCKDUCKGO_LITE_HOST}/lite/",
            result_parser="duckduckgo",
        )
    if engine_id == "bing_html":
        return WebSearchEngine(
            engine_id=engine_id,
            endpoint_url=f"https://{BING_HTML_HOST}/search",
            result_parser="bing",
        )
    return WebSearchEngine(
        engine_id="duckduckgo_html",
        endpoint_url=f"https://{DUCKDUCKGO_HTML_HOST}/html/",
        result_parser="duckduckgo",
    )


def _parse_search_results(body: str, *, engine: WebSearchEngine, max_results: int) -> list[JsonObject]:
    if engine.result_parser == "duckduckgo":
        rows = _parse_duckduckgo_results(body, max_results=max_results)
    elif engine.result_parser == "bing":
        rows = _parse_bing_results(body, max_results=max_results)
    else:
        rows = []
    if len(rows) < max_results:
        rows = _merge_results(rows, _parse_anchor_results(body, engine=engine, max_results=max_results))
    return rows[:max_results]


def _parse_duckduckgo_results(body: str, *, max_results: int) -> list[JsonObject]:
    snippets = [_strip_tags(match.group("snippet"), WEB_SEARCH_SNIPPET_LIMIT) for match in DDG_SNIPPET_RE.finditer(body)]
    rows: list[JsonObject] = []
    for index, match in enumerate(DDG_RESULT_RE.finditer(body)):
        uri = _decode_duckduckgo_url(match.group("url"))
        if not _safe_result_url(uri):
            continue
        rows.append(
            {
                "uri": uri,
                "title": _strip_tags(match.group("title"), WEB_SEARCH_TITLE_LIMIT),
                "snippet": snippets[index] if index < len(snippets) else "",
            }
        )
        if len(rows) >= max_results:
            break
    return rows


def _parse_bing_results(body: str, *, max_results: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    blocks = [match.group("block") for match in BING_BLOCK_RE.finditer(body)]
    if not blocks:
        blocks = [match.group(0) for match in BING_RESULT_RE.finditer(body)]
    for block in blocks:
        title_match = BING_TITLE_RE.search(block)
        if title_match is None:
            continue
        snippet_match = BING_SNIPPET_RE.search(block)
        uri = _decode_bing_url(title_match.group("url"))
        if not _safe_result_url(uri) or _is_search_engine_url(uri):
            continue
        rows.append(
            {
                "uri": uri,
                "title": _strip_tags(title_match.group("title"), WEB_SEARCH_TITLE_LIMIT),
                "snippet": _strip_tags(snippet_match.group("snippet") if snippet_match else "", WEB_SEARCH_SNIPPET_LIMIT),
            }
        )
        if len(rows) >= max_results:
            break
    return rows


def _parse_anchor_results(body: str, *, engine: WebSearchEngine, max_results: int) -> list[JsonObject]:
    parser = _AnchorParser()
    parser.feed(body)
    rows: list[JsonObject] = []
    for anchor in parser.anchors:
        raw_uri = str(anchor.get("href") or "")
        if engine.result_parser == "duckduckgo":
            uri = _decode_duckduckgo_url(raw_uri)
        elif engine.result_parser == "bing":
            uri = _decode_bing_url(raw_uri)
        else:
            uri = raw_uri
        if not _safe_result_url(uri) or _is_search_engine_url(uri):
            continue
        title = _bounded_text(str(anchor.get("text") or ""), WEB_SEARCH_TITLE_LIMIT)
        if not title:
            continue
        rows.append({"uri": uri, "title": title, "snippet": ""})
        if len(rows) >= max_results:
            break
    return rows


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[JsonObject] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if isinstance(href, str) and href.strip():
            self._href = href.strip()
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.anchors.append({"href": self._href, "text": " ".join("".join(self._text).split())})
        self._href = None
        self._text = []


def _decode_duckduckgo_url(raw_url: str) -> str:
    current = str(raw_url or "").strip()
    if current.startswith("//"):
        current = "https:" + current
    elif current.startswith("/"):
        current = urllib.parse.urljoin("https://duckduckgo.com", current)
    current = unescape(current)
    parsed = urllib.parse.urlparse(current)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return urllib.parse.unquote(query["uddg"][0])
    return current


def _decode_bing_url(raw_url: str) -> str:
    current = unescape(str(raw_url or "").strip())
    parsed = urllib.parse.urlparse(current)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("url", "r"):
        if key in query and query[key]:
            candidate = urllib.parse.unquote(query[key][0])
            if _safe_result_url(candidate):
                return candidate
    encoded = query.get("u", [""])[0]
    if encoded.startswith("a1"):
        decoded = _decode_bing_base64_url(encoded[2:])
        if decoded and _safe_result_url(decoded):
            return decoded
    return current


def _decode_bing_base64_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    padded = text + ("=" * ((4 - len(text) % 4) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _merge_results(primary: list[JsonObject], fallback: list[JsonObject]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    seen: set[str] = set()
    for item in [*primary, *fallback]:
        uri = str(item.get("uri") or "")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        rows.append(item)
    return rows


def _url_with_query(endpoint_url: str, query_param: str, query: str) -> str:
    parsed = urllib.parse.urlparse(endpoint_url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(key, value) for key, value in pairs if key != query_param]
    pairs.append((query_param, _bounded_text(query, WEB_SEARCH_QUERY_TEXT_LIMIT)))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


def _validate_url(
    uri: str,
    *,
    allowed_schemes: tuple[str, ...],
    allowed_hosts: set[str],
    allow_all_hosts: bool,
) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    diagnostics = _safe_url_diagnostics(uri)
    if parsed.scheme.lower() not in allowed_schemes:
        return {"status": "failed", "reason": "url_scheme_not_allowed", "allowed_schemes": list(allowed_schemes), **diagnostics}
    if not parsed.hostname:
        return {"status": "failed", "reason": "missing_url_host", **diagnostics}
    if parsed.username or parsed.password:
        return {"status": "failed", "reason": "url_credentials_not_allowed", **diagnostics}
    if contains_secret_like_content(parsed.geturl()):
        return {"status": "failed", "reason": "url_secret_like_content_not_allowed", **diagnostics}
    host = parsed.hostname.lower()
    if not allow_all_hosts and not _host_allowed(host, allowed_hosts):
        return {"status": "failed", "reason": "host_not_allowed", "allowed_host_count": len(allowed_hosts), **diagnostics}
    return {"status": "ok", **diagnostics}


def _safe_result_url(uri: str) -> bool:
    parsed = urllib.parse.urlparse(str(uri or ""))
    if parsed.scheme.lower() not in SAFE_RESULT_URI_SCHEMES:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return not contains_secret_like_content(parsed.geturl())


def _is_search_engine_url(uri: str) -> bool:
    host = (urllib.parse.urlparse(uri).hostname or "").lower()
    return host in {"duckduckgo.com", DUCKDUCKGO_HTML_HOST, DUCKDUCKGO_LITE_HOST, "bing.com", BING_HTML_HOST}


def _strip_tags(value: str, limit: int) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(value or ""))
    return _bounded_text(unescape(" ".join(cleaned.split())), limit)


def _safe_result_text(text: str, limit: int) -> str:
    bounded = _bounded_text(text, limit)
    if contains_secret_like_content(bounded):
        return "[omitted_secret_like_content]"
    return bounded


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
    return {
        "url_scheme": parsed.scheme,
        "host_hash": _hash((parsed.hostname or "").lower()) if parsed.hostname else "",
    }


def _host_hash(uri: str) -> str:
    return _hash((urllib.parse.urlparse(uri).hostname or "").lower())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _empty_status(attempts: list[JsonObject]) -> str:
    if attempts and all(str(attempt.get("status") or "") == "failed" for attempt in attempts):
        return "failed"
    if attempts and any(str(attempt.get("status") or "") == "empty" for attempt in attempts):
        return "empty"
    return "empty"


def _urllib_transport(url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
    import urllib.error
    import urllib.request

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
