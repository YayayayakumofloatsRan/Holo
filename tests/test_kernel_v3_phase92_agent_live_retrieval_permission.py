import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import (
    HttpFetchProvider,
    HttpTransportResponse,
    JsonHttpSearchProvider,
    RetrievalOperator,
)


def test_phase92_retrieval_recipe_grants_network_only_from_host_metadata() -> None:
    offline = task_recipe("retrieval_answer")
    live = task_recipe(
        "retrieval_answer",
        metadata={
            "execution_metadata": {
                "retrieval": {
                    "allow_network": True,
                    "max_network_fetches": 2,
                    "max_fetches": 2,
                }
            }
        },
    )

    assert offline.max_network_fetches == 0
    assert offline.metadata.get("allowed_permissions") is None
    assert live.max_network_fetches == 2
    assert live.metadata["allowed_permissions"] == ["network:fetch"]


def test_phase92_live_retrieval_operator_is_blocked_without_host_network_permission() -> None:
    journal = JournalStore.in_memory()
    search_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b'{"results": [{"url": "https://docs.example.com/aapl", "title": "AAPL filing"}]}',
        )
    )
    fetch_transport = _Transport(HttpTransportResponse(status_code=200, body=b"AAPL revenue evidence."))
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=_live_operator(search_transport=search_transport, fetch_transport=fetch_transport),
    )

    result = runtime.run("AAPL revenue", mode="retrieval")

    assert result.status == "failed"
    assert search_transport.calls == []
    assert fetch_transport.calls == []
    decisions = journal.records(task_id=result.task_id, kind="policy_decision")
    assert decisions[-1].data["allowed"] is False
    assert decisions[-1].data["reason"] == "missing_permissions:network:fetch"


def test_phase92_live_retrieval_operator_runs_with_host_network_permission_and_budget() -> None:
    journal = JournalStore.in_memory()
    search_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=(
                b'{"results": [{"url": "https://docs.example.com/aapl", '
                b'"title": "AAPL filing", "snippet": "AAPL revenue evidence"}]}'
            ),
        )
    )
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL revenue evidence from a live-configured HTTP provider.",
        )
    )
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        retrieval_operator=_live_operator(search_transport=search_transport, fetch_transport=fetch_transport),
    )

    result = runtime.run(
        "AAPL revenue",
        mode="retrieval",
        execution_metadata={
            "retrieval": {
                "allow_network": True,
                "max_network_fetches": 1,
                "max_fetches": 1,
            }
        },
    )

    assert result.status == "completed"
    assert len(search_transport.calls) == 1
    assert len(fetch_transport.calls) == 1
    decisions = journal.records(task_id=result.task_id, kind="policy_decision")
    assert decisions[-1].data["allowed"] is True
    assert decisions[-1].data["constraints"]["required_permissions"] == ["network:fetch"]
    assert decisions[-1].data["constraints"]["allowed_permissions"] == ["network:fetch"]
    recipe = journal.records(task_id=result.task_id, kind="agent_recipe")[-1].data
    assert recipe["max_network_fetches"] == 1
    assert recipe["metadata"]["allowed_permissions"] == ["network:fetch"]


def test_phase92_cli_agent_live_retrieval_blocks_without_env_gate(tmp_path: Path, capsys, monkeypatch) -> None:
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
                "agent",
                "AAPL revenue",
                "--mode",
                "retrieval",
                "--live-retrieval",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "live_retrieval_not_enabled"
    assert "HOLO_V3_LIVE_RETRIEVAL" in payload["live_config"]["env_gate"]
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_agent_live_retrieval_blocks_without_endpoint(tmp_path: Path, capsys, monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "agent",
                "AAPL revenue",
                "--mode",
                "retrieval",
                "--live-retrieval",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "live_search_endpoint_not_configured"
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_agent_live_retrieval_uses_policy_gate_and_budget(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    search_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=(
                b'{"results": [{"url": "https://docs.example.com/aapl", '
                b'"title": "AAPL filing", "snippet": "AAPL revenue evidence"}]}'
            ),
        )
    )
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL revenue evidence from a live-configured HTTP provider.",
        )
    )
    monkeypatch.setattr(
        cli.LiveRetrievalConfig,
        "build_operator",
        lambda _self: _live_operator(search_transport=search_transport, fetch_transport=fetch_transport),
    )
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "agent",
                "AAPL revenue",
                "--mode",
                "retrieval",
                "--live-retrieval",
                "--live-max-network-fetches",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    journal = JournalStore(journal_path, index_path=index_path)

    assert payload["status"] == "completed"
    assert len(search_transport.calls) == 1
    assert len(fetch_transport.calls) == 1
    decision = journal.records(task_id=payload["task_id"], kind="policy_decision")[-1].data
    assert decision["allowed"] is True
    assert decision["constraints"]["required_permissions"] == ["network:fetch"]
    assert decision["constraints"]["allowed_permissions"] == ["network:fetch"]
    recipe = journal.records(task_id=payload["task_id"], kind="agent_recipe")[-1].data
    assert recipe["max_network_fetches"] == 1
    assert recipe["metadata"]["allowed_permissions"] == ["network:fetch"]


class _Transport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
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


def _live_operator(*, search_transport: _Transport, fetch_transport: _Transport) -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=JsonHttpSearchProvider(
            endpoint_url="https://api.example.com/search",
            enabled=True,
            allowed_hosts=["api.example.com"],
            transport=search_transport,
        ),
        fetch_provider=HttpFetchProvider(
            enabled=True,
            allowed_hosts=["docs.example.com"],
            transport=fetch_transport,
        ),
    )


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
