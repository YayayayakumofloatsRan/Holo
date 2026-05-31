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
    assert inspection.provider_capabilities[0]["provider_id"] == "live_json_http_search"
    assert inspection.provider_capabilities[0]["default_enabled"] is True
    assert inspection.provider_capabilities[1]["provider_id"] == "live_http_fetch"
    assert inspection.provider_capabilities[1]["default_enabled"] is True
    assert inspection.issues[0]["code"] == "live_retrieval_provider_present"


def test_phase91_cli_live_http_provider_inspection_blocks_without_endpoint(tmp_path: Path, capsys, monkeypatch) -> None:
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
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "live_search_endpoint_not_configured"
    assert payload["network_access"] is False
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
    assert payload["provider_capabilities"][0]["default_enabled"] is False
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "api.example.com" not in dumped
    assert "docs.example.com" not in dumped
    assert "DEEPSEEK_API_KEY" not in dumped
    assert JournalStore(journal_path, index_path=index_path).records() == []


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
    ]:
        monkeypatch.delenv(name, raising=False)
