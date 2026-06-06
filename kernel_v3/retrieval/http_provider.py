from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.providers import FetchResponse


SEARCH_QUERY_TEXT_LIMIT = 1_000
SEARCH_RESULT_URL_LIMIT = 2_048
SEARCH_RESULT_TITLE_LIMIT = 240
SEARCH_RESULT_SNIPPET_LIMIT = 800
SEARCH_RESULT_ID_LIMIT = 160
SAFE_RESULT_URI_SCHEMES = {"http", "https"}
SECRET_QUERY_KEYS = {
    "api_key",
    "apikey",
    "key",
    "secret",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "signature",
    "sig",
    "x_amz_signature",
    "x_goog_signature",
}
SECRET_TEXT_PLACEHOLDER = "[omitted_secret_like_content]"

HttpTransport = Callable[[str, dict[str, str], int, int], "HttpTransportResponse"]


@dataclass(frozen=True, kw_only=True)
class HttpTransportResponse:
    status_code: int
    body: bytes
    mime_type: str = "text/plain"
    headers: JsonObject | None = None


class HttpFetchProvider:
    provider_id = "live_http_fetch"
    live_network = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(
        self,
        *,
        enabled: bool = False,
        allowed_hosts: list[str] | None = None,
        allow_all_hosts: bool = False,
        allow_discovered_search_hosts: bool = False,
        discovered_search_provider_ids: list[str] | None = None,
        allowed_schemes: list[str] | None = None,
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        user_agent: str = "holo-kernel-v3/1.0",
        transport: HttpTransport | None = None,
    ) -> None:
        self.default_enabled = bool(enabled)
        self.allowed_hosts = _normalize_hosts(allowed_hosts or [])
        self.allow_all_hosts = bool(allow_all_hosts)
        self.allow_discovered_search_hosts = bool(allow_discovered_search_hosts)
        self.discovered_search_provider_ids = tuple(
            str(item).strip()
            for item in (discovered_search_provider_ids or ["live_web_search"])
            if str(item).strip()
        )
        self.allowed_schemes = _normalize_schemes(allowed_schemes or ["https"])
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.user_agent = user_agent
        self.transport = transport or _urllib_transport
        self.capability_diagnostics = {
            "source": "http_fetch",
            "enabled": self.default_enabled,
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_host_count": len(self.allowed_hosts),
            "allow_discovered_search_hosts": self.allow_discovered_search_hosts,
            "discovered_search_provider_ids": list(self.discovered_search_provider_ids),
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
        }

    def fetch(self, source: SearchSource) -> FetchResponse:
        if not self.default_enabled:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={
                    "reason": "disabled_by_default",
                    "source": "http_fetch",
                    **_safe_url_diagnostics(source.uri),
                },
            )
        validation = _validate_url(
            source.uri,
            allowed_schemes=self.allowed_schemes,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=(
                self.allow_all_hosts
                or self._allows_discovered_search_host(source)
                or self._allows_discovery_expansion_host(source)
            ),
        )
        if validation.get("status") != "ok":
            return FetchResponse(status="failed", body="", diagnostics=validation)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,text/plain,application/xhtml+xml,application/pdf,application/json,text/csv",
        }
        try:
            response = self.transport(source.uri, headers, self.timeout_seconds, self.max_bytes)
        except Exception as exc:  # pragma: no cover - urllib transport has concrete containment below.
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={
                    "reason": "http_transport_error",
                    "error": type(exc).__name__,
                    **_safe_url_diagnostics(source.uri),
                    **self._source_discovery_diagnostics(source),
                },
            )
        if response.status_code < 200 or response.status_code >= 300:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={
                    "reason": "http_status_error",
                    "status_code": response.status_code,
                    **_safe_url_diagnostics(source.uri),
                    **self._source_discovery_diagnostics(source),
                },
            )
        if len(response.body) > self.max_bytes:
            return FetchResponse(
                status="failed",
                body="",
                diagnostics={
                    "reason": "http_body_too_large",
                    "max_bytes": self.max_bytes,
                    **_safe_url_diagnostics(source.uri),
                    **self._source_discovery_diagnostics(source),
                },
            )
        return FetchResponse(
            status="ok",
            body=_decode_http_body(response.body, mime_type=response.mime_type),
            mime_type=response.mime_type or "text/plain",
            diagnostics={
                "source": "http_fetch",
                "status_code": response.status_code,
                "byte_count": len(response.body),
                **_safe_url_diagnostics(source.uri),
                **self._source_discovery_diagnostics(source),
            },
        )

    def _allows_discovered_search_host(self, source: SearchSource) -> bool:
        if not self.allow_discovered_search_hosts:
            return False
        if source.provider not in self.discovered_search_provider_ids:
            return False
        metadata = source.metadata if isinstance(source.metadata, dict) else {}
        return (
            metadata.get("source_kind") == "web_search_result"
            and metadata.get("search_result_fetch_allowed") is True
        )

    def _allows_discovery_expansion_host(self, source: SearchSource) -> bool:
        metadata = source.metadata if isinstance(source.metadata, dict) else {}
        if metadata.get("discovery_expanded") is not True:
            return False
        allowed_hosts = _normalize_hosts(_string_list(metadata.get("fetch_allowed_hosts")))
        if not allowed_hosts:
            return False
        host = urllib.parse.urlparse(source.uri).hostname or ""
        return host.lower() in allowed_hosts

    def _source_discovery_diagnostics(self, source: SearchSource) -> JsonObject:
        if self._allows_discovery_expansion_host(source):
            return {
                "host_allowed_by": "discovery_expansion",
                "source_provider": source.provider,
            }
        if self._allows_discovered_search_host(source):
            return {
                "host_allowed_by": "web_search_result",
                "source_provider": source.provider,
            }
        return {}


class JsonHttpSearchProvider:
    provider_id = "live_json_http_search"
    live_network = True
    profile_aware = False
    supported_research_profiles: list[str] = []

    def __init__(
        self,
        *,
        endpoint_url: str,
        enabled: bool = False,
        allowed_hosts: list[str] | None = None,
        allow_all_hosts: bool = False,
        allowed_schemes: list[str] | None = None,
        query_param: str = "q",
        results_path: list[str] | None = None,
        api_key_env: str | None = None,
        api_key_header: str | None = None,
        api_key_prefix: str = "",
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        user_agent: str = "holo-kernel-v3/1.0",
        transport: HttpTransport | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.default_enabled = bool(enabled)
        self.allowed_hosts = _normalize_hosts(allowed_hosts or [])
        self.allow_all_hosts = bool(allow_all_hosts)
        self.allowed_schemes = _normalize_schemes(allowed_schemes or ["https"])
        self.query_param = query_param or "q"
        self.results_path = list(results_path or ["results"])
        self.api_key_env = api_key_env
        self.api_key_header = api_key_header
        self.api_key_prefix = api_key_prefix
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.user_agent = user_agent
        self.transport = transport or _urllib_transport
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "json_http_search",
            "enabled": self.default_enabled,
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_host_count": len(self.allowed_hosts),
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "query_param": self.query_param,
            "results_path": list(self.results_path),
            "api_key_env_configured": bool(self.api_key_env),
            "api_key_header_configured": bool(self.api_key_header),
            **_safe_url_diagnostics(self.endpoint_url),
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        if not self.default_enabled:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "disabled_by_default",
                "source": "json_http_search",
                **_safe_url_diagnostics(self.endpoint_url),
                "query_hash": _text_hash(query),
            }
            return []
        url = _url_with_query(self.endpoint_url, self.query_param, query, max_results=goal.max_sources)
        validation = _validate_url(
            url,
            allowed_schemes=self.allowed_schemes,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
        )
        if validation.get("status") != "ok":
            self._last_search_diagnostics = {"status": "failed", **validation, "query_hash": _text_hash(query)}
            return []
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        api_key = _api_key_from_env(self.api_key_env)
        if self.api_key_header:
            if not api_key:
                self._last_search_diagnostics = {
                    "status": "failed",
                    "reason": "missing_api_key_env",
                    "api_key_env_configured": bool(self.api_key_env),
                    **_safe_url_diagnostics(url),
                    "query_hash": _text_hash(query),
                }
                return []
            headers[self.api_key_header] = f"{self.api_key_prefix}{api_key}"
        try:
            response = self.transport(url, headers, self.timeout_seconds, self.max_bytes)
        except Exception as exc:  # pragma: no cover - urllib transport has concrete containment below.
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_transport_error",
                "error": type(exc).__name__,
                **_safe_url_diagnostics(url),
                "query_hash": _text_hash(query),
            }
            return []
        if response.status_code < 200 or response.status_code >= 300:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_status_error",
                "status_code": response.status_code,
                **_safe_url_diagnostics(url),
                "query_hash": _text_hash(query),
            }
            return []
        if len(response.body) > self.max_bytes:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_body_too_large",
                "max_bytes": self.max_bytes,
                **_safe_url_diagnostics(url),
                "query_hash": _text_hash(query),
            }
            return []
        try:
            payload = json.loads(response.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "malformed_json_response",
                **_safe_url_diagnostics(url),
                "query_hash": _text_hash(query),
            }
            return []
        results = _extract_results(payload, path=self.results_path)
        sources = _sources_from_json_results(results, provider_id=self.provider_id, max_sources=goal.max_sources)
        self._last_search_diagnostics = {
            "status": "ok",
            "returned_count": len(sources),
            "result_count": len(results),
            "status_code": response.status_code,
            "byte_count": len(response.body),
            **_safe_url_diagnostics(url),
            "query_hash": _text_hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


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


def _decode_http_body(body: bytes, *, mime_type: str) -> str:
    normalized = (mime_type or "").lower()
    if "pdf" in normalized:
        return body.decode("latin-1", errors="replace")
    return body.decode("utf-8", errors="replace")


def _validate_url(
    uri: str,
    *,
    allowed_schemes: tuple[str, ...],
    allowed_hosts: set[str],
    allow_all_hosts: bool,
) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    diagnostics = _safe_url_diagnostics(uri)
    if parsed.scheme not in allowed_schemes:
        return {"status": "failed", "reason": "url_scheme_not_allowed", "allowed_schemes": list(allowed_schemes), **diagnostics}
    if not parsed.hostname:
        return {"status": "failed", "reason": "missing_url_host", **diagnostics}
    if parsed.username or parsed.password:
        return {"status": "failed", "reason": "url_credentials_not_allowed", **diagnostics}
    if _parsed_url_has_secret_like_content(parsed):
        return {"status": "failed", "reason": "url_secret_like_content_not_allowed", **diagnostics}
    host = parsed.hostname.lower()
    if not allow_all_hosts and not _host_allowed(host, allowed_hosts):
        return {"status": "failed", "reason": "host_not_allowed", "allowed_host_count": len(allowed_hosts), **diagnostics}
    return {"status": "ok", **diagnostics}


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    return host in allowed_hosts or any(host.endswith("." + allowed) for allowed in allowed_hosts)


def _normalize_hosts(hosts: list[str]) -> set[str]:
    normalized: set[str] = set()
    for raw in hosts:
        host = _normalize_host(raw)
        if host:
            normalized.add(host)
    return normalized


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _normalize_host(value: str) -> str:
    text = str(value or "").strip().lower().rstrip(".")
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text if "://" in text else f"//{text}")
    host = parsed.hostname or ""
    return host.lower().rstrip(".")


def _normalize_schemes(schemes: list[str]) -> tuple[str, ...]:
    return tuple(scheme.strip().lower() for scheme in schemes if scheme.strip())


def _safe_url_diagnostics(uri: str) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    return {
        "url_scheme": parsed.scheme,
        "host_hash": hashlib.sha256(host.lower().encode("utf-8")).hexdigest() if host else "",
    }


def _url_with_query(endpoint_url: str, query_param: str, query: str, *, max_results: int) -> str:
    parsed = urllib.parse.urlparse(endpoint_url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(key, value) for key, value in pairs if key not in {query_param, "limit", "count", "max_results"}]
    pairs.append((query_param, _bounded_text(query, SEARCH_QUERY_TEXT_LIMIT)))
    pairs.append(("max_results", str(max(0, int(max_results)))))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


def _api_key_from_env(api_key_env: str | None) -> str | None:
    if not api_key_env:
        return None
    value = os.environ.get(api_key_env)
    return value if isinstance(value, str) and value else None


def _extract_results(payload: object, *, path: list[str]) -> list[JsonObject]:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, list):
        return []
    return [dict(item) for item in current if isinstance(item, dict)]


def _sources_from_json_results(results: list[JsonObject], *, provider_id: str, max_sources: int) -> list[SearchSource]:
    sources: list[SearchSource] = []
    for result in results:
        source = _source_from_json_result(result, index=len(sources) + 1, provider_id=provider_id)
        if source is None:
            continue
        sources.append(source)
        if len(sources) >= max(0, int(max_sources)):
            break
    return sources


def _source_from_json_result(result: JsonObject, *, index: int, provider_id: str) -> SearchSource | None:
    uri = _bounded_text(str(result.get("url") or result.get("uri") or result.get("link") or ""), SEARCH_RESULT_URL_LIMIT)
    if not uri or not _is_safe_result_uri(uri):
        return None
    title = _safe_result_text(str(result.get("title") or result.get("name") or uri), SEARCH_RESULT_TITLE_LIMIT)
    snippet = _safe_result_text(
        str(result.get("snippet") or result.get("description") or result.get("summary") or ""),
        SEARCH_RESULT_SNIPPET_LIMIT,
    )
    source_id = _source_id_from_result(result, uri=uri, index=index, provider_id=provider_id)
    metadata = {
        "rank": index,
        "result_payload_hash": _json_hash(result),
    }
    source_family = result.get("source_family")
    if isinstance(source_family, str) and source_family and not contains_secret_like_content(source_family):
        metadata["source_family"] = _bounded_text(source_family, SEARCH_RESULT_TITLE_LIMIT)
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=title,
        snippet=snippet,
        provider=provider_id,
        metadata=metadata,
    )


def _is_safe_result_uri(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in SAFE_RESULT_URI_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    return not _parsed_url_has_secret_like_content(parsed)


def _parsed_url_has_secret_like_content(parsed: urllib.parse.ParseResult) -> bool:
    if contains_secret_like_content(parsed.geturl()):
        return True
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if _query_pair_secret_like(key, value):
            return True
    return False


def _query_pair_secret_like(key: str, value: str) -> bool:
    normalized_key = key.strip().lower().replace("-", "_")
    if normalized_key in SECRET_QUERY_KEYS and len(value.strip()) >= 8:
        return True
    if contains_secret_like_content({normalized_key: value}):
        return True
    return contains_secret_like_content(value)


def _safe_result_text(text: str, limit: int) -> str:
    bounded = _bounded_text(text, limit)
    if contains_secret_like_content(bounded):
        return SECRET_TEXT_PLACEHOLDER
    return bounded


def _source_id_from_result(result: JsonObject, *, uri: str, index: int, provider_id: str) -> str:
    raw_source_id = result.get("source_id")
    if isinstance(raw_source_id, str) and raw_source_id and not contains_secret_like_content(raw_source_id):
        return _bounded_text(raw_source_id, SEARCH_RESULT_ID_LIMIT)
    return _bounded_text(f"{provider_id}-{_text_hash(uri)[:12]}-{index}", SEARCH_RESULT_ID_LIMIT)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_hash(payload: JsonObject) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."
