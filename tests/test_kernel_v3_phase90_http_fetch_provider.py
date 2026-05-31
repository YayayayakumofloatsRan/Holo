from __future__ import annotations

import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    FakeSearchProvider,
    HttpFetchProvider,
    HttpTransportResponse,
    RetrievalOperator,
    SearchGoal,
    SearchSource,
    inspect_retrieval_providers,
    provider_capability,
)


def test_phase90_http_fetch_provider_is_live_and_disabled_by_default() -> None:
    provider = HttpFetchProvider()

    capability = provider_capability(provider, provider_kind="fetch").to_dict()

    assert capability["provider_id"] == "live_http_fetch"
    assert capability["provider_kind"] == "fetch"
    assert capability["live_network"] is True
    assert capability["default_enabled"] is False
    assert capability["diagnostics"]["allow_all_hosts"] is False
    assert capability["diagnostics"]["allowed_host_count"] == 0


def test_phase90_http_fetch_provider_fails_closed_without_allowed_host() -> None:
    transport = _Transport()
    provider = HttpFetchProvider(transport=transport)

    response = provider.fetch(_source("https://example.com/report"))

    assert response.status == "failed"
    assert response.body == ""
    assert response.diagnostics["reason"] == "host_not_allowed"
    assert transport.calls == []
    dumped = json.dumps(response.diagnostics, ensure_ascii=False)
    assert "example.com" not in dumped
    assert "https://example.com/report" not in dumped


def test_phase90_http_fetch_provider_allows_explicit_host_and_returns_body() -> None:
    transport = _Transport(
        response=HttpTransportResponse(
            status_code=200,
            body="AAPL annual report revenue evidence.".encode("utf-8"),
            mime_type="text/plain",
        )
    )
    provider = HttpFetchProvider(enabled=True, allowed_hosts=["example.com"], transport=transport)

    response = provider.fetch(_source("https://www.example.com/report"))

    assert response.status == "ok"
    assert response.body == "AAPL annual report revenue evidence."
    assert response.mime_type == "text/plain"
    assert response.diagnostics["source"] == "http_fetch"
    assert response.diagnostics["byte_count"] == len(response.body.encode("utf-8"))
    assert transport.calls[0]["url"] == "https://www.example.com/report"


def test_phase90_http_fetch_provider_rejects_oversized_body_without_returning_raw_body() -> None:
    transport = _Transport(response=HttpTransportResponse(status_code=200, body=b"0123456789"))
    provider = HttpFetchProvider(
        enabled=True,
        allowed_hosts=["example.com"],
        max_bytes=4,
        transport=transport,
    )

    response = provider.fetch(_source("https://example.com/large"))

    assert response.status == "failed"
    assert response.body == ""
    assert response.diagnostics["reason"] == "http_body_too_large"
    assert response.diagnostics["max_bytes"] == 4
    assert "0123456789" not in json.dumps(response.diagnostics, ensure_ascii=False)


def test_phase90_http_fetch_provider_keeps_retrieval_network_gated_and_auditable() -> None:
    source = _source("https://example.com/report")
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"AAPL revenue": [source]}),
        fetch_provider=HttpFetchProvider(
            enabled=True,
            allowed_hosts=["example.com"],
            transport=_Transport(response=HttpTransportResponse(status_code=200, body=b"AAPL revenue evidence.")),
        ),
    )
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()

    report = operator.run(
        SearchGoal(goal_id="goal-http-fetch", query="AAPL revenue"),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-http-fetch",
        run_id="run-http-fetch",
    )
    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 9090)

    assert operator.network_access is True
    assert inspection.network_access is True
    assert inspection.issues[0]["code"] == "live_retrieval_provider_present"
    assert report.status == "sufficient"
    fetch = journal.records(task_id="task-http-fetch", kind="retrieval_fetch_attempt")[0]
    assert fetch.data["diagnostics"]["source"] == "http_fetch"
    assert fetch.data["diagnostics"]["byte_count"] == len("AAPL revenue evidence.".encode("utf-8"))


def _source(uri: str) -> SearchSource:
    return SearchSource(
        source_id="src-http",
        uri=uri,
        title="HTTP source",
        snippet="HTTP source snippet",
        provider="live_http_search",
    )


class _Transport:
    def __init__(self, *, response: HttpTransportResponse | None = None) -> None:
        self.response = response or HttpTransportResponse(status_code=200, body=b"")
        self.calls: list[dict[str, object]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "max_bytes": max_bytes,
            }
        )
        return self.response
