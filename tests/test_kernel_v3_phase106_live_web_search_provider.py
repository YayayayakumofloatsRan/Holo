from __future__ import annotations

import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    HttpFetchProvider,
    HttpTransportResponse,
    LiveRetrievalConfig,
    QueryPlan,
    SearchGoal,
    SearchSource,
    inspect_retrieval_providers,
    provider_capability,
)
from kernel_v3.retrieval.web_search_provider import LiveWebSearchProvider


def test_phase106_live_web_search_provider_is_live_and_disabled_by_default() -> None:
    transport = _Transport({"https://html.duckduckgo.com/html/?q=DeepSeek+API": HttpTransportResponse(status_code=200, body=b"")})
    provider = LiveWebSearchProvider(engines=["duckduckgo_html"], transport=transport)

    sources = provider.search("DeepSeek API", goal=_goal(), plan=_plan())
    capability = provider_capability(provider, provider_kind="search").to_dict()

    assert sources == []
    assert transport.calls == []
    assert capability["provider_id"] == "live_web_search"
    assert capability["live_network"] is True
    assert capability["default_enabled"] is False
    assert capability["diagnostics"]["engine_ids"] == ["duckduckgo_html"]


def test_phase106_live_web_search_provider_parses_duckduckgo_html_results_safely() -> None:
    body = b"""
    <html><body>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fapi-docs.deepseek.com%2Fquick_start">DeepSeek API Quick Start</a>
      <a class="result__snippet">Official DeepSeek API docs with authentication and model usage.</a>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fleak%3Faccess_token%3Dlive-secret-token-1234567890">Leak</a>
    </body></html>
    """
    transport = _Transport(
        {
            "https://html.duckduckgo.com/html/?q=DeepSeek+API": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=body,
            )
        }
    )
    provider = LiveWebSearchProvider(
        enabled=True,
        engines=["duckduckgo_html"],
        allowed_hosts=["html.duckduckgo.com"],
        transport=transport,
    )

    sources = provider.search("DeepSeek API", goal=_goal(max_sources=5), plan=_plan())

    assert [source.uri for source in sources] == ["https://api-docs.deepseek.com/quick_start"]
    assert sources[0].title == "DeepSeek API Quick Start"
    assert sources[0].snippet == "Official DeepSeek API docs with authentication and model usage."
    assert sources[0].provider == "live_web_search"
    assert sources[0].metadata["source_kind"] == "web_search_result"
    assert sources[0].metadata["search_result_fetch_allowed"] is True
    diagnostics = provider.search_diagnostics()
    assert diagnostics["status"] == "ok"
    assert diagnostics["attempts"][0]["engine_id"] == "duckduckgo_html"
    dumped_sources = json.dumps([source.to_dict() for source in sources], ensure_ascii=False)
    dumped_diagnostics = json.dumps(diagnostics, ensure_ascii=False)
    assert "live-secret-token" not in dumped_sources
    assert "live-secret-token" not in dumped_diagnostics
    assert "DeepSeek API" not in dumped_diagnostics
    assert "api-docs.deepseek.com" in dumped_sources
    assert "html.duckduckgo.com" not in dumped_diagnostics


def test_phase106_http_fetch_can_allow_only_web_search_result_hosts() -> None:
    source = SearchSource(
        source_id="src-web",
        uri="https://docs.example.com/page",
        title="Docs",
        snippet="Search result",
        provider="live_web_search",
        metadata={"source_kind": "web_search_result", "search_result_fetch_allowed": True},
    )
    transport = _Transport({"https://docs.example.com/page": HttpTransportResponse(status_code=200, body=b"source body")})
    provider = HttpFetchProvider(
        enabled=True,
        allow_discovered_search_hosts=True,
        transport=transport,
    )

    response = provider.fetch(source)

    assert response.status == "ok"
    assert response.body == "source body"
    assert response.diagnostics["host_allowed_by"] == "web_search_result"
    assert transport.calls[0]["url"] == "https://docs.example.com/page"


def test_phase106_live_web_search_provider_parses_bing_blocks_with_snippets() -> None:
    target = "https://docs.example.com/deepseek-api"
    encoded = "a1" + "aHR0cHM6Ly9kb2NzLmV4YW1wbGUuY29tL2RlZXBzZWVrLWFwaQ"
    body = f"""
    <ol id="b_results">
      <li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u={encoded}">DeepSeek API docs</a></h2>
      <div class="b_caption"><p>Authentication uses bearer keys and the model field selects deepseek-chat.</p></div></li>
    </ol>
    """.encode("utf-8")
    transport = _Transport(
        {
            "https://www.bing.com/search?q=DeepSeek+API": HttpTransportResponse(
                status_code=200,
                mime_type="text/html",
                body=body,
            )
        }
    )
    provider = LiveWebSearchProvider(
        enabled=True,
        engines=["bing_html"],
        allowed_hosts=["www.bing.com"],
        transport=transport,
    )

    sources = provider.search("DeepSeek API", goal=_goal(max_sources=5), plan=_plan())

    assert [source.uri for source in sources] == [target]
    assert sources[0].snippet == "Authentication uses bearer keys and the model field selects deepseek-chat."


def test_phase106_http_fetch_rejects_unmarked_dynamic_hosts() -> None:
    source = SearchSource(
        source_id="src-web",
        uri="https://docs.example.com/page",
        title="Docs",
        snippet="Search result",
        provider="live_web_search",
        metadata={"source_kind": "direct_url"},
    )
    transport = _Transport({"https://docs.example.com/page": HttpTransportResponse(status_code=200, body=b"source body")})
    provider = HttpFetchProvider(
        enabled=True,
        allow_discovered_search_hosts=True,
        transport=transport,
    )

    response = provider.fetch(source)

    assert response.status == "failed"
    assert response.diagnostics["reason"] == "host_not_allowed"
    assert transport.calls == []


def test_phase106_live_retrieval_config_adds_web_search_and_dynamic_fetch() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS": "duckduckgo_html,bing_html",
            "HOLO_V3_LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE": "7",
        }
    )
    operator = config.build_operator()
    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 10600)

    assert config.web_search.configured is True
    assert config.web_search.providers == ["duckduckgo_html", "bing_html"]
    assert config.web_search.max_results_per_engine == 7
    assert config.fetch.allow_discovered_search_hosts is True
    provider_ids = {item["provider_id"] for item in inspection.diagnostics["provider_chain"]}
    assert "live_web_search" in provider_ids
    assert "live_http_fetch" in provider_ids
    fetch_capability = inspection.provider_capabilities[1]
    assert fetch_capability["diagnostics"]["allow_discovered_search_hosts"] is True


def test_phase106_live_web_search_default_alias_expands_to_multiple_engines() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS": "default",
        }
    )
    provider = config.web_search.build_provider(transport=_Transport({}))

    assert config.web_search.providers == ["default"]
    assert provider.capability_diagnostics["engine_ids"] == ["bing_html", "duckduckgo_html"]


def test_phase106_cli_exposes_live_web_search_without_journal_writes(tmp_path: Path, capsys, monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "retrieval-providers",
                "--mode",
                "live-http",
                "--live-retrieval",
                "--live-web-search-provider",
                "duckduckgo_html",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["live_config"]["web_search"]["configured"] is True
    assert payload["live_config"]["fetch"]["allow_discovered_search_hosts"] is True
    provider_ids = {item["provider_id"] for item in payload["inspection"]["diagnostics"]["provider_chain"]}
    assert "live_web_search" in provider_ids
    assert JournalStore(journal_path, index_path=index_path).records() == []


def _goal(max_sources: int = 2) -> SearchGoal:
    return SearchGoal(goal_id="goal-web-search", query="DeepSeek API", max_sources=max_sources)


def _plan() -> QueryPlan:
    return QueryPlan(
        plan_id="plan-web-search",
        goal_id="goal-web-search",
        queries=["DeepSeek API"],
        max_sources=2,
        max_fetches=2,
    )


def _clear_live_env(monkeypatch) -> None:
    for name in list("HOLO_V3_LIVE_RETRIEVAL HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS HOLO_V3_LIVE_FETCH_DISCOVERED_SEARCH_HOSTS".split()):
        monkeypatch.delenv(name, raising=False)


class _Transport:
    def __init__(self, responses: dict[str, HttpTransportResponse]) -> None:
        self.responses = dict(responses)
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
        return self.responses.get(url) or HttpTransportResponse(status_code=404, body=b"")
