from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.contracts import SearchSource
from kernel_v3.retrieval.providers import FetchResponse


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
        allowed_schemes: list[str] | None = None,
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        user_agent: str = "holo-kernel-v3/1.0",
        transport: HttpTransport | None = None,
    ) -> None:
        self.default_enabled = bool(enabled)
        self.allowed_hosts = _normalize_hosts(allowed_hosts or [])
        self.allow_all_hosts = bool(allow_all_hosts)
        self.allowed_schemes = tuple(allowed_schemes or ["https"])
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.user_agent = user_agent
        self.transport = transport or _urllib_transport
        self.capability_diagnostics = {
            "source": "http_fetch",
            "enabled": self.default_enabled,
            "allow_all_hosts": self.allow_all_hosts,
            "allowed_host_count": len(self.allowed_hosts),
            "allowed_schemes": list(self.allowed_schemes),
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
        }

    def fetch(self, source: SearchSource) -> FetchResponse:
        validation = _validate_url(
            source.uri,
            allowed_schemes=self.allowed_schemes,
            allowed_hosts=self.allowed_hosts,
            allow_all_hosts=self.allow_all_hosts,
        )
        if validation.get("status") != "ok":
            return FetchResponse(status="failed", body="", diagnostics=validation)
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,text/plain,application/xhtml+xml"}
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
                },
            )
        return FetchResponse(
            status="ok",
            body=response.body.decode("utf-8", errors="replace"),
            mime_type=response.mime_type or "text/plain",
            diagnostics={
                "source": "http_fetch",
                "status_code": response.status_code,
                "byte_count": len(response.body),
                **_safe_url_diagnostics(source.uri),
            },
        )


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
    host = parsed.hostname.lower()
    if not allow_all_hosts and not _host_allowed(host, allowed_hosts):
        return {"status": "failed", "reason": "host_not_allowed", "allowed_host_count": len(allowed_hosts), **diagnostics}
    return {"status": "ok", **diagnostics}


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    return host in allowed_hosts or any(host.endswith("." + allowed) for allowed in allowed_hosts)


def _normalize_hosts(hosts: list[str]) -> set[str]:
    return {host.strip().lower() for host in hosts if host.strip()}


def _safe_url_diagnostics(uri: str) -> JsonObject:
    parsed = urllib.parse.urlparse(uri)
    host = parsed.hostname or ""
    return {
        "url_scheme": parsed.scheme,
        "host_hash": hashlib.sha256(host.lower().encode("utf-8")).hexdigest() if host else "",
    }
