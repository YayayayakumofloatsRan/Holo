from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.http_provider import HttpTransport, HttpTransportResponse


DEFAULT_LIVE_DOWNLOAD_BYTE_BUDGET = 512_000_000
DEFAULT_LIVE_CACHE_DIR = ".state/kernel_v3/retrieval/http-cache"


@dataclass
class LiveFetchBudget:
    max_download_bytes: int = DEFAULT_LIVE_DOWNLOAD_BYTE_BUDGET
    cache_dir: Path | None = None
    downloaded_bytes: int = 0
    network_miss_count: int = 0
    cache_hit_count: int = 0
    blocked_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.max_download_bytes = max(1, int(self.max_download_bytes))
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def before_network(self) -> JsonObject | None:
        with self._lock:
            if self.downloaded_bytes >= self.max_download_bytes:
                self.blocked_count += 1
                return self._diagnostics(reason="download_byte_budget_exhausted", cache_hit=False)
            return None

    def record_network_bytes(self, byte_count: int) -> JsonObject:
        with self._lock:
            self.downloaded_bytes += max(0, int(byte_count))
            self.network_miss_count += 1
            return self._diagnostics(reason=None, cache_hit=False)

    def record_cache_hit(self, byte_count: int) -> JsonObject:
        with self._lock:
            self.cache_hit_count += 1
            return self._diagnostics(reason=None, cache_hit=True, cached_byte_count=max(0, int(byte_count)))

    def _diagnostics(
        self,
        *,
        reason: str | None,
        cache_hit: bool,
        cached_byte_count: int | None = None,
    ) -> JsonObject:
        remaining = max(0, self.max_download_bytes - self.downloaded_bytes)
        payload: JsonObject = {
            "holo_fetch_budget": True,
            "downloaded_bytes": self.downloaded_bytes,
            "max_download_bytes": self.max_download_bytes,
            "remaining_download_bytes": remaining,
            "network_miss_count": self.network_miss_count,
            "cache_hit_count": self.cache_hit_count,
            "blocked_count": self.blocked_count,
            "cache_hit": cache_hit,
        }
        if cached_byte_count is not None:
            payload["cached_byte_count"] = cached_byte_count
        if reason:
            payload["reason"] = reason
        return payload


class BudgetedHttpTransport:
    def __init__(self, transport: HttpTransport, *, budget: LiveFetchBudget) -> None:
        self.transport = transport
        self.budget = budget

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: int,
        max_bytes: int,
    ) -> HttpTransportResponse:
        cached = _read_cached_response(self.budget.cache_dir, url, max_bytes=max_bytes)
        if cached is not None:
            diagnostics = self.budget.record_cache_hit(len(cached.body))
            return _with_budget_headers(cached, diagnostics)

        blocked = self.budget.before_network()
        if blocked is not None:
            return HttpTransportResponse(
                status_code=599,
                body=b"",
                mime_type="text/plain",
                headers=_budget_headers(blocked),
            )

        response = self.transport(url, headers, timeout_seconds, max_bytes)
        diagnostics = self.budget.record_network_bytes(len(response.body))
        if 200 <= response.status_code < 300:
            _write_cached_response(self.budget.cache_dir, url, response, max_bytes=max_bytes)
        return _with_budget_headers(response, diagnostics)


_BUDGETS: dict[tuple[str, int], LiveFetchBudget] = {}
_BUDGETS_LOCK = threading.Lock()


def shared_live_fetch_budget(*, cache_dir: Path | None, max_download_bytes: int) -> LiveFetchBudget:
    if cache_dir is None:
        return LiveFetchBudget(max_download_bytes=max_download_bytes, cache_dir=None)
    key = (str(cache_dir.resolve()) if cache_dir is not None else "", max(1, int(max_download_bytes)))
    with _BUDGETS_LOCK:
        existing = _BUDGETS.get(key)
        if existing is not None:
            return existing
        budget = LiveFetchBudget(max_download_bytes=max_download_bytes, cache_dir=cache_dir)
        _BUDGETS[key] = budget
        return budget


def wrap_transport_with_budget(
    transport: HttpTransport,
    *,
    cache_dir: Path | None,
    max_download_bytes: int,
) -> HttpTransport:
    return BudgetedHttpTransport(
        transport,
        budget=shared_live_fetch_budget(cache_dir=cache_dir, max_download_bytes=max_download_bytes),
    )


def _cache_key(url: str, *, max_bytes: int) -> str:
    import hashlib

    seed = f"{max(1, int(max_bytes))}\n{url}"
    return hashlib.sha256(seed.encode("utf-8", errors="surrogatepass")).hexdigest()


def _cache_paths(cache_dir: Path | None, url: str, *, max_bytes: int) -> tuple[Path, Path] | None:
    if cache_dir is None:
        return None
    key = _cache_key(url, max_bytes=max_bytes)
    bucket = cache_dir / key[:2]
    return bucket / f"{key}.body", bucket / f"{key}.json"


def _read_cached_response(cache_dir: Path | None, url: str, *, max_bytes: int) -> HttpTransportResponse | None:
    paths = _cache_paths(cache_dir, url, max_bytes=max_bytes)
    if paths is None:
        return None
    body_path, meta_path = paths
    if not body_path.exists() or not meta_path.exists():
        return None
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes()
    except (OSError, json.JSONDecodeError):
        return None
    return HttpTransportResponse(
        status_code=int(metadata.get("status_code") or 200),
        body=body,
        mime_type=str(metadata.get("mime_type") or "text/plain"),
        headers=dict(metadata.get("headers") or {}),
    )


def _write_cached_response(cache_dir: Path | None, url: str, response: HttpTransportResponse, *, max_bytes: int) -> None:
    paths = _cache_paths(cache_dir, url, max_bytes=max_bytes)
    if paths is None:
        return
    body_path, meta_path = paths
    try:
        body_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_body = body_path.with_suffix(".body.tmp")
        tmp_meta = meta_path.with_suffix(".json.tmp")
        tmp_body.write_bytes(response.body)
        tmp_meta.write_text(
            json.dumps(
                {
                    "schema": "holo.kernel_v3.live_fetch_cache.v1",
                    "status_code": response.status_code,
                    "mime_type": response.mime_type,
                    "headers": _cacheable_headers(response.headers),
                    "max_bytes": max(1, int(max_bytes)),
                    "stored_at_ms": int(time.time() * 1000),
                    "body_bytes": len(response.body),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp_body.replace(body_path)
        tmp_meta.replace(meta_path)
    except OSError:
        return


def _cacheable_headers(headers: JsonObject | None) -> JsonObject:
    if not isinstance(headers, dict):
        return {}
    result: JsonObject = {}
    for key, value in headers.items():
        text_key = str(key)
        if text_key.lower() in {"set-cookie", "authorization", "cookie"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[text_key] = value
    return result


def _with_budget_headers(response: HttpTransportResponse, diagnostics: JsonObject) -> HttpTransportResponse:
    return HttpTransportResponse(
        status_code=response.status_code,
        body=response.body,
        mime_type=response.mime_type,
        headers={**dict(response.headers or {}), **_budget_headers(diagnostics)},
    )


def _budget_headers(diagnostics: JsonObject) -> JsonObject:
    return {f"x-holo-{key.replace('_', '-')}": value for key, value in diagnostics.items()}


def budget_diagnostics_from_headers(headers: JsonObject | None) -> JsonObject:
    if not isinstance(headers, dict):
        return {}
    result: JsonObject = {}
    for key, value in headers.items():
        text_key = str(key).lower()
        if not text_key.startswith("x-holo-"):
            continue
        result[text_key.removeprefix("x-holo-").replace("-", "_")] = value
    return result
