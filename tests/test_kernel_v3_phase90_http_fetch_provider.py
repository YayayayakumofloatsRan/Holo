from __future__ import annotations

import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    FakeSearchProvider,
    HttpFetchProvider,
    HttpTransportResponse,
    JsonHttpSearchProvider,
    QueryPlan,
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


def test_phase90_json_http_search_provider_is_live_and_disabled_by_default() -> None:
    provider = JsonHttpSearchProvider(endpoint_url="https://api.example.com/search")

    capability = provider_capability(provider, provider_kind="search").to_dict()

    assert capability["provider_id"] == "live_json_http_search"
    assert capability["provider_kind"] == "search"
    assert capability["live_network"] is True
    assert capability["default_enabled"] is False
    assert capability["diagnostics"]["source"] == "json_http_search"
    assert capability["diagnostics"]["allow_all_hosts"] is False
    assert capability["diagnostics"]["allowed_host_count"] == 0
    assert capability["diagnostics"]["api_key_env_configured"] is False
    assert capability["diagnostics"]["api_key_header_configured"] is False


def test_phase90_json_http_search_provider_fails_closed_without_allowed_host() -> None:
    transport = _Transport()
    provider = JsonHttpSearchProvider(endpoint_url="https://api.example.com/search", transport=transport)

    sources = provider.search("DeepSeek API docs", goal=_goal(), plan=_plan())

    assert sources == []
    assert transport.calls == []
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason"] == "host_not_allowed"
    dumped = json.dumps(diagnostics, ensure_ascii=False)
    assert "api.example.com" not in dumped
    assert "https://api.example.com/search" not in dumped
    assert "DeepSeek API docs" not in dumped


def test_phase90_json_http_search_provider_parses_bounded_results() -> None:
    transport = _Transport(
        response=HttpTransportResponse(
            status_code=200,
            mime_type="application/json",
            body=json.dumps(
                {
                    "results": [
                        {
                            "url": "https://docs.example.com/deepseek-api",
                            "title": "DeepSeek API",
                            "snippet": "Official API documentation.",
                            "source_family": "official",
                            "raw_body": "this raw field must not be copied into source metadata",
                        },
                        {
                            "link": "https://docs.example.com/deepseek-reasoner",
                            "name": "DeepSeek Reasoner",
                            "description": "Reasoner model documentation.",
                        },
                        {"title": "missing URL is ignored"},
                    ]
                }
            ).encode("utf-8"),
        )
    )
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        transport=transport,
    )

    sources = provider.search("DeepSeek API docs", goal=_goal(max_sources=5), plan=_plan())

    assert [source.uri for source in sources] == [
        "https://docs.example.com/deepseek-api",
        "https://docs.example.com/deepseek-reasoner",
    ]
    assert sources[0].provider == "live_json_http_search"
    assert sources[0].title == "DeepSeek API"
    assert sources[0].snippet == "Official API documentation."
    assert sources[0].metadata["rank"] == 1
    assert sources[0].metadata["source_family"] == "official"
    assert "result_payload_hash" in sources[0].metadata
    assert "DeepSeek+API+docs" in str(transport.calls[0]["url"])
    assert "max_results=5" in str(transport.calls[0]["url"])
    dumped_source = json.dumps(sources[0].to_dict(), ensure_ascii=False)
    assert "this raw field" not in dumped_source


def test_phase90_json_http_search_provider_handles_bad_responses_without_raw_body() -> None:
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        max_bytes=4,
        transport=_Transport(response=HttpTransportResponse(status_code=200, body=b"{not json")),
    )

    sources = provider.search("bad response", goal=_goal(), plan=_plan())

    assert sources == []
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason"] == "http_body_too_large"
    assert "{not json" not in json.dumps(diagnostics, ensure_ascii=False)


def test_phase90_json_http_search_provider_reports_http_status_safely() -> None:
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        transport=_Transport(response=HttpTransportResponse(status_code=429, body=b"rate limited")),
    )

    sources = provider.search("rate limited query", goal=_goal(), plan=_plan())

    assert sources == []
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason"] == "http_status_error"
    assert diagnostics["status_code"] == 429
    assert "rate limited" not in json.dumps(diagnostics, ensure_ascii=False)


def test_phase90_json_http_search_provider_reports_malformed_json_safely() -> None:
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        transport=_Transport(response=HttpTransportResponse(status_code=200, body=b"{not json")),
    )

    sources = provider.search("malformed response", goal=_goal(), plan=_plan())

    assert sources == []
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason"] == "malformed_json_response"
    assert "{not json" not in json.dumps(diagnostics, ensure_ascii=False)


def test_phase90_json_http_search_provider_uses_api_key_without_exposing_it(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-live-key")
    transport = _Transport(response=HttpTransportResponse(status_code=200, body=b'{"results": []}'))
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        api_key_env="DEEPSEEK_API_KEY",
        api_key_header="Authorization",
        api_key_prefix="Bearer ",
        transport=transport,
    )

    sources = provider.search("DeepSeek API docs", goal=_goal(), plan=_plan())

    assert sources == []
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer secret-live-key"
    capability = provider_capability(provider, provider_kind="search").to_dict()
    dumped = json.dumps({"capability": capability, "diagnostics": provider.search_diagnostics()}, ensure_ascii=False)
    assert "secret-live-key" not in dumped
    assert "DEEPSEEK_API_KEY" not in dumped


def test_phase90_json_http_search_provider_requires_configured_api_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    transport = _Transport(response=HttpTransportResponse(status_code=200, body=b'{"results": []}'))
    provider = JsonHttpSearchProvider(
        endpoint_url="https://api.example.com/search",
        enabled=True,
        allowed_hosts=["api.example.com"],
        api_key_env="DEEPSEEK_API_KEY",
        api_key_header="Authorization",
        transport=transport,
    )

    sources = provider.search("DeepSeek API docs", goal=_goal(), plan=_plan())

    assert sources == []
    assert transport.calls == []
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason"] == "missing_api_key_env"
    dumped = json.dumps(diagnostics, ensure_ascii=False)
    assert "DEEPSEEK_API_KEY" not in dumped


def _source(uri: str) -> SearchSource:
    return SearchSource(
        source_id="src-http",
        uri=uri,
        title="HTTP source",
        snippet="HTTP source snippet",
        provider="live_http_search",
    )


def _goal(max_sources: int = 2) -> SearchGoal:
    return SearchGoal(goal_id="goal-http-search", query="DeepSeek API docs", max_sources=max_sources)


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-http-search",
        goal_id="goal-http-search",
        queries=["DeepSeek API docs"],
        max_sources=2,
        max_fetches=2,
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
