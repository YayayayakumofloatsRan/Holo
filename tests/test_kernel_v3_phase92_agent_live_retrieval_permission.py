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
