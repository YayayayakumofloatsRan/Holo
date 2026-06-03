import json
from pathlib import Path
from types import SimpleNamespace

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


def test_phase92_cli_live_retrieval_allows_source_directory_hosts_without_explicit_profile() -> None:
    config = cli._live_retrieval_config_from_args(
        _runtime_args(live_retrieval=True, research_profile=None),
        enable=True,
    )

    assert "api-docs.deepseek.com" in config.fetch.allowed_hosts


def test_phase92_live_retrieval_operator_is_blocked_without_host_network_permission() -> None:
    journal = JournalStore.in_memory()
    search_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b'{"results": [{"url": "https://docs.example.com/aapl", "title": "AAPL filing"}]}',
        )
    )
    fetch_transport = _Transport(HttpTransportResponse(status_code=200, body=b"AAPL revenue was USD 391035 million."))
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
                b'"title": "AAPL filing", "snippet": "AAPL revenue was USD 391035 million"}]}'
            ),
        )
    )
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL revenue was USD 391035 million from a live-configured HTTP provider.",
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


def test_phase92_cli_agent_live_retrieval_blocks_without_allowed_hosts(tmp_path: Path, capsys, monkeypatch) -> None:
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
                "--offline",
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
    assert payload["live_config"]["enabled"] is True
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in payload["issues"]
    }
    assert ("live_provider_without_allowed_hosts", "live_http_fetch", "fetch") in issue_keys
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_cli_live_retrieval_defaults_to_web_discovery_without_allowed_hosts(
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
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["network_access"] is True
    assert payload["live_config"]["web_search"]["configured"] is True
    assert payload["live_config"]["web_search"]["providers"] == ["bing_html", "duckduckgo_html"]
    assert payload["live_config"]["search_strategy"] == "aggregate"
    assert payload["live_config"]["fetch"]["allow_discovered_search_hosts"] is True
    assert payload["live_config"]["fetch"]["allow_all_hosts"] is False
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
            body=b"AAPL SEC companyfacts revenue was USD 391035 million from structured live fetch.",
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
                "--offline",
                "AAPL CIK0000320193 revenue",
                "--mode",
                "retrieval",
                "--research-profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--live-retrieval",
                "--live-max-network-fetches",
                "4096",
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
                "--offline",
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
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase92_online_chat_defaults_to_bounded_live_retrieval_metadata(monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    args = _runtime_args(command="chat", online=True, live_retrieval=None)

    config = cli._live_retrieval_config_for_args(args)
    metadata = cli._runtime_execution_metadata(args)

    assert not isinstance(config, dict)
    assert config is not None
    assert config.web_search.providers == ["bing_html", "duckduckgo_html"]
    assert config.fetch.allow_discovered_search_hosts is True
    assert metadata is not None
    assert metadata["retrieval"]["allow_network"] is True
    assert metadata["retrieval"]["max_network_fetches"] == cli.DEFAULT_LIVE_NETWORK_FETCH_BUDGET


def test_phase92_online_chat_can_opt_out_of_live_retrieval(monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    args = _runtime_args(command="chat", online=True, live_retrieval=False)

    config = cli._live_retrieval_config_for_args(args)
    metadata = cli._runtime_execution_metadata(args)

    assert config is None
    assert metadata is not None
    assert "retrieval" not in metadata


def test_phase92_online_resident_defaults_to_bounded_live_retrieval_metadata(monkeypatch) -> None:
    _clear_live_env(monkeypatch)
    args = _runtime_args(command="resident", resident_command="run-once", online=True, live_retrieval=None)

    config = cli._live_retrieval_config_for_args(args)
    metadata = cli._runtime_execution_metadata(args)

    assert not isinstance(config, dict)
    assert config is not None
    assert config.web_search.configured is True
    assert metadata is not None
    assert metadata["retrieval"]["allow_network"] is True


def test_phase92_cli_resident_doctor_reports_default_live_web_retrieval(
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
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "attention"
    assert payload["live_retrieval_issues"] == []
    assert payload["live_retrieval_config"]["enabled"] is True
    assert payload["live_retrieval_config"]["web_search"]["providers"] == ["bing_html", "duckduckgo_html"]
    assert payload["live_retrieval_config"]["fetch"]["allow_discovered_search_hosts"] is True
    assert payload["doctor"]["retrieval_provider_inspection"] is not None
    event = _resident_doctor_record(journal_path, index_path)
    assert event["status"] == "attention"
    assert event["doctor_status"] == payload["doctor"]["status"]
    assert event["live_retrieval"]["status"] == "ok"
    assert event["live_retrieval"]["issue_count"] == 0
    assert event["live_retrieval"]["config"]["enabled"] is True


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
    provider_issues = payload["live_retrieval_issues"]
    issue_keys = {
        (issue["code"], issue["provider_id"], issue["provider_kind"])
        for issue in provider_issues
        if issue["code"] == "live_provider_without_allowed_hosts"
    }
    assert ("live_provider_without_allowed_hosts", "live_json_http_search", "search") in issue_keys
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
                b'"title": "AAPL filing", "snippet": "AAPL revenue was USD 391035 million"}]}'
            ),
        )
    )
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL revenue was USD 391035 million from a live-configured HTTP provider.",
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
                "--offline",
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


def test_phase92_cli_agent_live_retrieval_allow_all_is_explicit_cli_authorization(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
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
                "--offline",
                "AAPL revenue",
                "--mode",
                "retrieval",
                "--live-retrieval",
                "--live-allow-all-hosts",
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
    assert recipe["metadata"]["allowed_permissions"] == ["network:fetch"]


def test_phase92_cli_retrieve_live_retrieval_uses_configured_operator(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _clear_live_env(monkeypatch)
    search_transport, fetch_transport = _live_success_transports()
    monkeypatch.setattr(
        cli.LiveRetrievalConfig,
        "build_operator",
        lambda _self, **_kwargs: _live_operator(search_transport=search_transport, fetch_transport=fetch_transport),
    )
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    artifact_log = tmp_path / "artifacts.jsonl"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "--artifact-log",
                str(artifact_log),
                "retrieve",
                "AAPL revenue",
                "--live-retrieval",
                "--live-allow-all-hosts",
                "--max-fetches",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["mode"] == "live-http"
    assert payload["network_access"] is True
    assert len(search_transport.calls) == 1
    assert len(fetch_transport.calls) == 1
    assert payload["report"]["status"] == "sufficient"


def test_phase92_cli_agent_live_research_depth_uses_manifest_fetch_budget_not_bound_query_count(
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
                "--offline",
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
    assert search_transport.calls
    assert fetch_transport.calls
    action = journal.records(task_id=payload["task_id"], kind="action")[0].data
    assert action["payload"]["network_fetch_count"] == 65
    assert action["payload"]["max_fetches"] == 1
    assert not journal.records(task_id=payload["task_id"], kind="guard")
    reports = journal.records(task_id=payload["task_id"], kind="retrieval_report")
    assert reports
    assert reports[-1].data["diagnostics"]["reason"] == "no_primary_source_for_research_profile"


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
                    "--offline",
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


def _runtime_args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "command": "chat",
        "resident_command": None,
        "online": True,
        "planner": "fake",
        "evaluator": "fake",
        "synthesizer": "fake",
        "semantic_intake": "fake",
        "turn_router": "fake",
        "live_retrieval": None,
        "live_allow_all_hosts": False,
        "live_search_endpoint": None,
        "live_web_search_provider": None,
        "live_web_search_max_results_per_engine": None,
        "live_fetch_discovered_search_hosts": None,
        "live_search_allowed_host": None,
        "live_fetch_allowed_host": None,
        "live_crawl_seed_url": None,
        "live_crawl_source_directory": False,
        "live_source_directory_allowlist": False,
        "live_crawl_include_sitemaps": True,
        "live_crawl_max_pages": None,
        "live_crawl_max_links_per_page": None,
        "live_crawl_max_sitemap_urls": None,
        "live_crawl_max_source_directory_seeds": None,
        "live_search_strategy": None,
        "live_search_max_sources_per_provider": None,
        "live_timeout_seconds": None,
        "live_max_bytes": None,
        "live_max_network_fetches": cli.DEFAULT_LIVE_NETWORK_FETCH_BUDGET,
        "response_language": None,
        "context_profile": "provider",
        "context_token_budget": None,
        "context_section_budget": None,
        "workspace_evidence_chars": None,
        "synthesis_evidence_preview_chars": None,
        "max_agent_steps": None,
        "max_agent_tool_calls": None,
        "max_agent_artifact_bytes": None,
        "research_profile": None,
        "research_depth": "deep",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
                b'"title": "AAPL filing", "snippet": "AAPL revenue was USD 391035 million"}]}'
            ),
        )
    )
    fetch_transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            body=b"AAPL revenue was USD 391035 million from a live-configured HTTP provider.",
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
        "HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS",
        "HOLO_V3_LIVE_WEB_SEARCH_MAX_RESULTS_PER_ENGINE",
        "HOLO_V3_LIVE_FETCH_DISCOVERED_SEARCH_HOSTS",
        "HOLO_V3_LIVE_SEARCH_STRATEGY",
        "HOLO_V3_LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER",
        "HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST",
        "HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS",
        "HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES",
        "HOLO_V3_LIVE_CRAWL_SEED_URLS",
        "HOLO_V3_LIVE_CRAWL_MAX_PAGES",
        "HOLO_V3_LIVE_CRAWL_MAX_LINKS_PER_PAGE",
        "HOLO_V3_LIVE_CRAWL_INCLUDE_SITEMAPS",
        "HOLO_V3_LIVE_CRAWL_MAX_SITEMAP_URLS",
        "HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY",
        "HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS",
    ]:
        monkeypatch.delenv(name, raising=False)
