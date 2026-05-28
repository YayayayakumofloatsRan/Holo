from __future__ import annotations

import time

from holo_agent.agent import AgentConfig, HoloAgent
from holo_agent.cli import main
from holo_agent.schema import Decision
from holo_agent.tools import OpenPageTool, ToolRegistry, WebClient, WebSearchTool
from holo_agent.web_providers import SearchAttempt, SearchProvider, SearchProviderRegistry


class StaticProvider(SearchProvider):
    def __init__(self, name: str, results: list[dict[str, str]] | None = None, error: Exception | None = None) -> None:
        self.name = name
        self.results = results or []
        self.error = error
        self.queries: list[dict] = []

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> SearchAttempt:
        self.queries.append({"query": query, "allowed_domains": allowed_domains or [], "blocked_domains": blocked_domains or []})
        if self.error:
            raise self.error
        return SearchAttempt(provider=self.name, query=query, status="ok", results=self.results[:max_results], elapsed_ms=1)


class SlowProvider(SearchProvider):
    name = "slow"

    def search(self, query: str, **kwargs) -> SearchAttempt:
        time.sleep(0.2)
        return SearchAttempt(provider=self.name, query=query, status="ok", results=[], elapsed_ms=200)


def test_provider_registry_falls_back_after_provider_error() -> None:
    bad = StaticProvider("bad", error=RuntimeError("provider unavailable"))
    good = StaticProvider("good", results=[{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""}])
    registry = SearchProviderRegistry([bad, good], provider_timeout_seconds=0.1)

    attempt = registry.search("OpenAI Codex CLI", max_results=5)

    assert attempt.status == "ok"
    assert attempt.provider == "good"
    assert registry.health()["last_status"] == "ok"
    assert registry.health()["attempts"][0]["status"] == "error"
    assert registry.health()["attempts"][1]["provider"] == "good"


def test_provider_registry_bounds_slow_provider() -> None:
    registry = SearchProviderRegistry(
        [SlowProvider(), StaticProvider("good", results=[{"title": "Docs", "url": "https://developers.openai.com/codex/cli", "snippet": ""}])],
        provider_timeout_seconds=0.02,
    )
    start = time.perf_counter()

    attempt = registry.search("OpenAI Codex CLI", max_results=5)

    assert time.perf_counter() - start < 0.15
    assert attempt.provider == "good"
    assert registry.health()["attempts"][0]["status"] == "timeout"


def test_web_client_filters_allowed_domains_before_returning_results() -> None:
    provider = StaticProvider(
        "mock",
        results=[
            {"title": "Linux find", "url": "https://www.runoob.com/linux/linux-comm-find.html", "snippet": ""},
            {"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": ""},
        ],
    )
    client = WebClient(providers=[provider])

    results = client.search("OpenAI Codex CLI", allowed_domains=["developers.openai.com"], max_results=5)

    assert results == [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "", "provider": "mock"}]
    assert provider.queries[0]["allowed_domains"] == ["developers.openai.com"]


def test_web_search_observation_includes_provider_health_on_failure() -> None:
    client = WebClient(providers=[StaticProvider("bad", error=RuntimeError("network blocked"))])

    obs = WebSearchTool(client).run(query="OpenAI Codex CLI", max_results=5)

    assert obs.status == "error"
    assert obs.data["provider_health"]["last_status"] == "error"
    assert obs.data["provider_health"]["attempts"][0]["provider"] == "bad"


def test_empty_provider_result_records_empty_health() -> None:
    client = WebClient(providers=[StaticProvider("empty", results=[])])

    obs = WebSearchTool(client).run(query="OpenAI Codex CLI", max_results=5)

    assert obs.status == "error"
    assert obs.summary == "empty_results"
    assert obs.data["provider_health"]["last_status"] == "empty"


def test_fallback_continues_to_next_planned_query_after_empty_results(tmp_path) -> None:
    queries: list[str] = []

    class Client(WebClient):
        def search(self, query: str, *, max_results: int = 5, allowed_domains=None, blocked_domains=None, region=None):
            queries.append(query)
            if len(queries) == 1:
                raise RuntimeError("empty_results")
            return [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "", "provider": "mock"}]

        def fetch_text(self, url: str) -> str:
            return "Codex CLI is a local coding agent that runs in your terminal."

        def health(self):
            return {"schema": "holo.web_provider_health.v1", "last_status": "ok", "providers": ["mock"], "attempts": []}

    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(Client()), OpenPageTool(Client())]),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official OpenAI Codex CLI docs and cite sources")

    assert result.status == "ok"
    assert queries[:2] == ["Find official OpenAI Codex CLI docs and cite sources", "OpenAI Codex CLI official documentation"]


def test_agent_metadata_includes_web_provider_health(tmp_path) -> None:
    class Client(WebClient):
        def search(self, query: str, *, max_results: int = 5, allowed_domains=None, blocked_domains=None, region=None):
            return [{"title": "Codex CLI", "url": "https://developers.openai.com/codex/cli", "snippet": "", "provider": "mock"}]

        def fetch_text(self, url: str) -> str:
            return "Codex CLI is a local coding agent that runs in your terminal."

        def health(self):
            return {"schema": "holo.web_provider_health.v1", "last_status": "ok", "providers": ["mock"], "attempts": []}

    class Model:
        def decide(self, *, user_text: str, context: dict, action_space: list[dict]) -> Decision:
            if not context["observations"]:
                return Decision(action="web_search", arguments={"query": "OpenAI Codex CLI", "allowed_domains": ["developers.openai.com"]})
            if len(context["observations"]) == 1:
                return Decision(action="open_page", arguments={"url": "https://developers.openai.com/codex/cli"})
            return Decision(action="answer_direct", can_answer=True)

        def finalize(self, *, user_text: str, observations: list[dict], context: dict) -> str:
            return "Official source found: https://developers.openai.com/codex/cli"

        def evaluate_source(self, *, query: str, source: dict, page_text: str, trajectory: list[dict]) -> dict:
            return {"accepted": True}

    client = Client()
    result = HoloAgent(
        tools=ToolRegistry([WebSearchTool(client), OpenPageTool(client)]),
        model=Model(),
        config=AgentConfig(log_path=tmp_path / "events.jsonl", workspace_root=tmp_path),
    ).run("Find official Codex CLI docs")

    assert result.metadata["web_provider_health"]["last_status"] == "ok"


def test_cli_status_includes_web_provider_health(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["status"]) == 0
    payload = capsys.readouterr().out

    assert "web_provider_health" in payload
    assert "holo.web_provider_health.v1" in payload
