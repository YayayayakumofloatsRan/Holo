import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval import (
    FakeSearchProvider,
    HttpFetchProvider,
    HttpTransportResponse,
    JsonHttpSearchProvider,
    RetrievalOperator,
    SearchSource,
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


def test_phase92_cli_agent_live_retrieval_blocks_structured_path_without_fetch_allowed_hosts(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
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
    assert payload["reason"] == "live_retrieval_allowed_hosts_not_configured"
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in payload["issues"]
    }
    assert ("live_provider_without_allowed_hosts", "live_http_fetch", "fetch") in issue_keys
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_agent_live_retrieval_allows_structured_search_without_endpoint(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "data.sec.gov")
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL SEC companyfacts revenue evidence from structured live fetch.",
        )
    )
    monkeypatch.setattr(
        cli.LiveRetrievalConfig,
        "build_operator",
        lambda _self: _structured_live_operator(fetch_transport=fetch_transport),
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
                "AAPL CIK0000320193 revenue",
                "--mode",
                "retrieval",
                "--research-profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--live-retrieval",
                "--live-max-network-fetches",
                "8",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    journal = JournalStore(journal_path, index_path=index_path)

    assert payload["status"] == "completed"
    assert len(fetch_transport.calls) == 1
    action = journal.records(task_id=payload["task_id"], kind="action")[0].data
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert action["payload"]["network_fetch_count"] <= action["payload"]["max_network_fetches"]
    assert journal.records(task_id=payload["task_id"], kind="retrieval_report")[-1].data["status"] == "sufficient"


def test_phase92_cli_agent_live_retrieval_blocks_without_allowed_hosts(tmp_path: Path, capsys, monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
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
    assert payload["reason"] == "live_retrieval_allowed_hosts_not_configured"
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in payload["issues"]
    }
    assert ("live_provider_without_allowed_hosts", "live_json_http_search", "search") in issue_keys
    assert ("live_provider_without_allowed_hosts", "live_http_fetch", "fetch") in issue_keys
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_chat_live_retrieval_blocks_without_env_gate(tmp_path: Path, capsys, monkeypatch) -> None:
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
                "chat",
                "--offline",
                "--thread",
                "live-chat",
                "--once",
                "research AAPL revenue",
                "--live-retrieval",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "live_retrieval_not_enabled"
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_resident_live_retrieval_blocks_without_env_gate(tmp_path: Path, capsys, monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--resident-db",
        str(resident_db),
    ]

    assert cli.main([*base, "resident", "enqueue", "research AAPL revenue", "--thread", "live-resident"]) == 0
    capsys.readouterr()
    assert cli.main([*base, "resident", "run-once", "--worker-id", "worker-live", "--live-retrieval"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "live_retrieval_not_enabled"
    records = JournalStore(journal_path, index_path=index_path).records()
    assert [record.kind for record in records] == ["resident_inbox_enqueued"]


def test_phase92_cli_resident_doctor_reports_live_retrieval_config_gap(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "--resident-db",
                str(resident_db),
                "resident",
                "doctor",
                "--live-retrieval",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "error"
    issue_codes = {issue["code"] for issue in payload["live_retrieval_issues"]}
    assert {"live_retrieval_not_enabled", "live_provider_without_allowed_hosts"}.issubset(issue_codes)
    assert payload["live_retrieval_config"]["enabled"] is False
    assert payload["doctor"]["retrieval_provider_inspection"] is not None
    event = _resident_doctor_record(journal_path, index_path)
    assert event["status"] == "error"
    assert event["doctor_status"] == payload["doctor"]["status"]
    assert event["live_retrieval"]["status"] == "error"
    assert {"live_retrieval_not_enabled", "live_provider_without_allowed_hosts"}.issubset(
        {issue["code"] for issue in event["live_retrieval"]["issues"]}
    )
    assert event["live_retrieval"]["config"]["enabled"] is False


def test_phase92_cli_resident_doctor_inspects_live_retrieval_without_network(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "--resident-db",
                str(resident_db),
                "resident",
                "doctor",
                "--live-retrieval",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["live_retrieval_issues"] == []
    assert payload["live_retrieval_config"]["enabled"] is True
    provider_ids = {
        item["provider_id"]
        for item in payload["doctor"]["retrieval_provider_inspection"]["diagnostics"]["provider_chain"]
    }
    assert {"live_json_http_search", "live_http_fetch"}.issubset(provider_ids)
    event = _resident_doctor_record(journal_path, index_path)
    assert event["status"] == "attention"
    assert event["live_retrieval"]["status"] == "ok"
    assert event["live_retrieval"]["issue_count"] == 0
    assert event["live_retrieval"]["config"]["enabled"] is True
    assert event["retrieval_summary"]["network_access"] is True


def test_phase92_cli_resident_doctor_flags_live_retrieval_without_allowed_hosts(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "--resident-db",
                str(resident_db),
                "resident",
                "doctor",
                "--live-retrieval",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "error"
    provider_issues = payload["doctor"]["retrieval_provider_inspection"]["issues"]
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in provider_issues
        if issue["code"] == "live_provider_without_allowed_hosts"
    }
    assert ("live_provider_without_allowed_hosts", "live_json_http_search", "search") in issue_keys
    assert ("live_provider_without_allowed_hosts", "live_http_fetch", "fetch") in issue_keys
    event = _resident_doctor_record(journal_path, index_path)
    assert event["status"] == "error"
    assert event["retrieval_summary"]["network_access"] is True
    assert {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in event["issues"]
        if issue["code"] == "live_provider_without_allowed_hosts"
    } == issue_keys


def test_phase92_cli_agent_live_retrieval_uses_policy_gate_and_budget(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
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


def test_phase92_cli_agent_live_research_depth_counts_query_and_fetch_budget(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
    search_transport, fetch_transport = _live_success_transports()
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
                "--research-profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--research-depth",
                "balanced",
                "--live-retrieval",
                "--live-max-network-fetches",
                "3",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    journal = JournalStore(journal_path, index_path=index_path)

    assert payload["status"] == "failed"
    assert search_transport.calls == []
    assert fetch_transport.calls == []
    action = journal.records(task_id=payload["task_id"], kind="action")[0].data
    guard = journal.records(task_id=payload["task_id"], kind="guard")[-1].data
    assert action["payload"]["network_fetch_count"] == 4
    assert guard["stop_reason"] == "max_network_fetches"
    assert guard["requested_network_fetches"] == 4
    assert guard["max_network_fetches"] == 3


def test_phase92_cli_chat_live_retrieval_forces_retrieval_recipe(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
    search_transport, fetch_transport = _live_success_transports()
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
                "chat",
                "--offline",
                "--thread",
                "live-chat",
                "--once",
                "research AAPL revenue",
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
    recipe = journal.records(task_id=payload["task_id"], kind="agent_recipe")[-1].data
    assert recipe["mode"] == "retrieval_answer"
    assert recipe["metadata"]["allowed_permissions"] == ["network:fetch"]


def test_phase92_cli_resident_live_retrieval_processes_retrieval_task(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ENDPOINT", "https://api.example.com/search")
    monkeypatch.setenv("HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "docs.example.com")
    search_transport, fetch_transport = _live_success_transports()
    monkeypatch.setattr(
        cli.LiveRetrievalConfig,
        "build_operator",
        lambda _self: _live_operator(search_transport=search_transport, fetch_transport=fetch_transport),
    )
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    resident_db = tmp_path / "resident.sqlite"
    base = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--resident-db",
        str(resident_db),
    ]

    assert cli.main([*base, "resident", "enqueue", "research AAPL revenue", "--thread", "live-resident"]) == 0
    capsys.readouterr()
    assert (
        cli.main(
            [
                *base,
                "resident",
                "run-once",
                "--worker-id",
                "worker-live",
                "--live-retrieval",
                "--live-max-network-fetches",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    journal = JournalStore(journal_path, index_path=index_path)

    assert payload["status"] == "processed"
    assert len(search_transport.calls) == 1
    assert len(fetch_transport.calls) == 1
    recipe = journal.records(kind="agent_recipe")[-1].data
    assert recipe["mode"] == "retrieval_answer"
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


def _structured_live_operator(*, fetch_transport: _Transport) -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=FakeSearchProvider(
            {
                "AAPL CIK0000320193 revenue": [
                    SearchSource(
                        source_id="src-structured-live",
                        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                        title="SEC companyfacts JSON",
                        snippet="AAPL revenue companyfacts structured source.",
                        provider="research_source_query_search",
                        metadata={
                            "source_family": "structured_regulatory_data",
                            "authority_level": "primary",
                            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                        },
                    )
                ]
            }
        ),
        fetch_provider=HttpFetchProvider(
            enabled=True,
            allowed_hosts=["data.sec.gov"],
            transport=fetch_transport,
        ),
    )


def _live_success_transports() -> tuple[_Transport, _Transport]:
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
    return search_transport, fetch_transport


def _resident_doctor_record(journal_path: Path, index_path: Path) -> dict[str, object]:
    records = JournalStore(journal_path, index_path=index_path).records(kind="resident_doctor_report")
    assert len(records) == 1
    return records[0].data


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
    ]:
        monkeypatch.delenv(name, raising=False)
