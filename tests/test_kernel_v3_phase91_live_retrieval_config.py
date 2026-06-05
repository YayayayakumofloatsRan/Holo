import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    HttpTransportResponse,
    LiveRetrievalConfig,
    inspect_retrieval_providers,
)


def test_phase91_live_retrieval_config_defaults_to_disabled_and_unconfigured() -> None:
    config = LiveRetrievalConfig.from_env({})

    assert config.enabled is False
    assert config.search.configured is False
    diagnostics = config.safe_diagnostics()
    assert diagnostics["enabled"] is False
    assert diagnostics["search"]["configured"] is False
    assert diagnostics["search"]["api_key_env_configured"] is False


def test_phase91_live_retrieval_config_is_env_gated_and_redacted() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_ENDPOINT": "https://api.example.com/search",
            "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS": "api.example.com",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "docs.example.com,static.example.com",
            "HOLO_V3_LIVE_SEARCH_API_KEY_ENV": "DEEPSEEK_API_KEY",
            "HOLO_V3_LIVE_SEARCH_API_KEY_HEADER": "Authorization",
            "HOLO_V3_LIVE_SEARCH_API_KEY_PREFIX": "Bearer ",
            "HOLO_V3_LIVE_SEARCH_RESULTS_PATH": "data.results",
            "HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS": "9",
            "HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES": "1234",
        }
    )

    assert config.enabled is True
    assert config.search.configured is True
    assert config.search.allowed_hosts == ["api.example.com"]
    assert config.fetch.allowed_hosts == ["docs.example.com", "static.example.com"]
    assert config.search.results_path == ["data", "results"]
    assert config.search.timeout_seconds == 9
    assert config.search.max_bytes == 1234
    diagnostics = config.safe_diagnostics()
    dumped = json.dumps(diagnostics, ensure_ascii=False)
    assert "api.example.com" not in dumped
    assert "docs.example.com" not in dumped
    assert "DEEPSEEK_API_KEY" not in dumped
    assert "Bearer" not in dumped


def test_phase91_live_retrieval_config_builds_inspectable_operator() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_ENDPOINT": "https://api.example.com/search",
            "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS": "api.example.com",
            "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS": "docs.example.com",
        }
    )
    transport = _Transport(response=HttpTransportResponse(status_code=200, body=b'{"results": []}'))

    operator = config.build_operator(search_transport=transport, fetch_transport=transport)
    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 9191)

    assert operator.network_access is True
    assert inspection.generated_at_ms == 9191
    assert inspection.network_access is True
    assert inspection.provider_capabilities[0]["provider_id"] == "adaptive_search"
    assert inspection.provider_capabilities[0]["diagnostics"]["default_strategy"] == "fallback"
    provider_ids = {item["provider_id"] for item in inspection.diagnostics["provider_chain"]}
    assert {
        "direct_url_search",
        "fiscaldata_structured_search",
        "fred_structured_search",
        "sec_edgar_structured_search",
        "research_source_query_search",
        "live_json_http_search",
        "research_source_directory_search",
    }.issubset(provider_ids)
    assert inspection.provider_capabilities[1]["provider_id"] == "live_http_fetch"
    assert inspection.provider_capabilities[1]["default_enabled"] is True
    assert inspection.issues[0]["code"] == "live_retrieval_provider_present"


def test_phase91_live_retrieval_inspection_flags_missing_allowed_hosts() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_ENDPOINT": "https://api.example.com/search",
        }
    )
    transport = _Transport(response=HttpTransportResponse(status_code=200, body=b'{"results": []}'))

    operator = config.build_operator(search_transport=transport, fetch_transport=transport)
    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 9192)

    assert inspection.status == "error"
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in inspection.issues
        if issue["code"] == "live_provider_without_allowed_hosts"
    }
    assert ("live_provider_without_allowed_hosts", "live_json_http_search", "search") in issue_keys
    assert ("live_provider_without_allowed_hosts", "live_http_fetch", "fetch") in issue_keys
    assert "configure allowed hosts for live retrieval providers" in inspection.recommended_actions


def test_phase91_cli_live_retrieval_preflight_accepts_explicit_allow_all_hosts() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_SEARCH_ENDPOINT": "https://api.example.com/search",
            "HOLO_V3_LIVE_RETRIEVAL_ALLOW_ALL_HOSTS": "1",
        }
    )

    assert cli._live_retrieval_allowed_host_issues(config) == []


def test_phase91_cli_live_retrieval_flags_are_explicit_config_without_env_gate(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
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
                "--live-allow-all-hosts",
                "--live-search-endpoint",
                "https://api.example.com/search",
                "--live-crawl-seed-url",
                "https://docs.example.com/index.html",
                "--live-search-strategy",
                "adaptive",
                "--live-crawl-max-pages",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["live_config"]["enabled"] is True
    assert payload["live_config"]["search"]["enabled"] is True
    assert payload["live_config"]["search"]["allow_all_hosts"] is True
    assert payload["live_config"]["crawl"]["seed_count"] == 1
    assert payload["live_config"]["crawl"]["max_pages"] == 2
    assert payload["live_config"]["search_strategy"] == "adaptive"
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase91_cli_live_http_provider_inspection_allows_structured_search_without_endpoint(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
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
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["mode"] == "live-http"
    assert payload["network_access"] is True
    provider_ids = {
        item["provider_id"]
        for item in payload["inspection"]["diagnostics"]["provider_chain"]
    }
    assert {
        "fiscaldata_structured_search",
        "fred_structured_search",
        "sec_edgar_structured_search",
        "research_source_query_search",
        "live_http_fetch",
    }.issubset(provider_ids)
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase91_cli_live_http_provider_inspection_is_read_only_and_redacted(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_API_KEY_ENV", "DEEPSEEK_API_KEY")
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
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["mode"] == "live-http"
    assert payload["network_access"] is True
    chain = payload["inspection"]["diagnostics"]["provider_chain"]
    live_json = next(item for item in chain if item["provider_id"] == "live_json_http_search")
    assert live_json["default_enabled"] is False
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "api.example.com" not in dumped
    assert "docs.example.com" not in dumped
    assert "DEEPSEEK_API_KEY" not in dumped
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase91_cli_live_http_provider_inspection_accepts_crawl_only_config(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_CRAWL_SEED_URLS", "https://docs.example.com/index.html")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "docs.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
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
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    provider_ids = {
        item["provider_id"]
        for item in payload["inspection"]["diagnostics"]["provider_chain"]
    }
    assert payload["status"] == "attention"
    assert "bounded_crawl_search" in provider_ids
    assert "live_json_http_search" not in provider_ids
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase91_live_retrieval_can_enable_source_directory_crawl_and_allowlist() -> None:
    config = LiveRetrievalConfig.from_env(
        {
            "HOLO_V3_LIVE_RETRIEVAL": "1",
            "HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY": "1",
            "HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST": "1",
            "HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS": "4",
            "HOLO_V3_LIVE_SEARCH_STRATEGY": "adaptive",
        }
    )

    assert config.crawl.configured is True
    assert config.crawl.include_source_directory_seeds is True
    assert config.crawl.max_source_directory_seeds == 4
    assert "www.sec.gov" in config.crawl.allowed_hosts
    assert "www.sec.gov" in config.fetch.allowed_hosts
    diagnostics = config.safe_diagnostics()
    dumped = json.dumps(diagnostics, ensure_ascii=False)
    assert diagnostics["search_strategy"] == "adaptive"
    assert diagnostics["crawl"]["include_source_directory_seeds"] is True
    assert diagnostics["crawl"]["allowed_host_count"] > 0
    assert "www.sec.gov" not in dumped

    operator = config.build_operator()
    inspection = inspect_retrieval_providers(operator, clock_ms=lambda: 9105)
    provider_ids = {
        item["provider_id"]
        for item in inspection.diagnostics["provider_chain"]
    }
    assert "adaptive_search" in [item["provider_id"] for item in inspection.provider_capabilities]
    assert "bounded_crawl_search" in provider_ids


class _Transport:
    def __init__(self, *, response: HttpTransportResponse) -> None:
        self.response = response

    def __call__(self, url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
        return self.response


def _clear_live_env(monkeypatch) -> None:
    for name in [
        "HOLO_V3_LIVE_RETRIEVAL",
        "HOLO_V3_LIVE_SEARCH_ENDPOINT",
        "HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS",
        "HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS",
        "HOLO_V3_LIVE_RETRIEVAL_ALLOW_ALL_HOSTS",
        "HOLO_V3_LIVE_RETRIEVAL_ALLOWED_SCHEMES",
        "HOLO_V3_LIVE_SEARCH_QUERY_PARAM",
        "HOLO_V3_LIVE_SEARCH_RESULTS_PATH",
        "HOLO_V3_LIVE_SEARCH_API_KEY_ENV",
        "HOLO_V3_LIVE_SEARCH_API_KEY_HEADER",
        "HOLO_V3_LIVE_SEARCH_API_KEY_PREFIX",
        "HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS",
        "HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES",
        "HOLO_V3_LIVE_CRAWL_SEED_URLS",
        "HOLO_V3_LIVE_CRAWL_MAX_PAGES",
        "HOLO_V3_LIVE_CRAWL_MAX_LINKS_PER_PAGE",
        "HOLO_V3_LIVE_CRAWL_INCLUDE_SITEMAPS",
        "HOLO_V3_LIVE_CRAWL_MAX_SITEMAP_URLS",
        "HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY",
        "HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS",
        "HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST",
        "HOLO_V3_LIVE_SEARCH_STRATEGY",
        "HOLO_V3_LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER",
    ]:
        monkeypatch.delenv(name, raising=False)
