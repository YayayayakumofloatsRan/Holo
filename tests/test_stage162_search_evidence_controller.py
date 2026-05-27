from __future__ import annotations

import holo_host.stage151_tool_decision_loop as stage151
from holo_host.stage151_tool_decision_loop import build_stage151_live_trace, build_tool_decision_report, execute_tool_decision
from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage162_search_evidence_controller import (
    build_search_evidence_plan,
    evaluate_search_evidence,
    run_search_evidence_controller,
    score_web_observation,
)


def _result(title: str, url: str, snippet: str = "") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet}


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        html = (
            '<a class="result__a" href="https://developers.openai.com/codex/cli">OpenAI Codex CLI</a>'
            '<div class="result__snippet">Official Codex CLI documentation.</div>'
        )
        return html.encode("utf-8")


class _FakeOpener:
    addheaders: list[tuple[str, str]]

    def open(self, url: str, timeout: int = 0) -> _FakeResponse:
        return _FakeResponse()


def test_search_plan_expands_official_docs_query() -> None:
    plan = build_search_evidence_plan(
        "Codex CLI docs",
        user_text="联网搜索 Codex 的官方文档",
        max_attempts=3,
    )

    queries = [item["query"] for item in plan["attempts"]]
    assert plan["required_source_type"] == "official_docs"
    assert queries[0] == "Codex CLI docs"
    assert any("official" in query.lower() or "docs" in query.lower() for query in queries[1:])


def test_default_web_search_respects_environment_proxy_opener(monkeypatch) -> None:
    calls: list[tuple] = []

    def build_opener(*args: object) -> _FakeOpener:
        calls.append(args)
        return _FakeOpener()

    monkeypatch.setattr(stage151.request, "build_opener", build_opener)

    result = stage151.default_web_search("OpenAI Codex CLI docs")

    assert calls == [()]
    assert result["status"] == "ok"
    assert result["results"][0]["url"] == "https://developers.openai.com/codex/cli"


def test_stage151_decision_preserves_user_text_for_source_requirements() -> None:
    report = build_tool_decision_report("联网搜索 OpenAI Codex 官方文档")

    assert "官方" in report["user_text"]


def test_score_web_observation_requires_official_source_for_official_request() -> None:
    weak = score_web_observation(
        {
            "status": "ok",
            "query": "DeepSeek tool calling docs",
            "results": [_result("Random blog", "https://example.com/blog", "DeepSeek tool calling notes")],
            "source_urls": ["https://example.com/blog"],
        },
        user_text="查一下 DeepSeek 官方 tool calling 文档",
        required_source_type="official_docs",
    )
    strong = score_web_observation(
        {
            "status": "ok",
            "query": "DeepSeek tool calling docs",
            "results": [_result("DeepSeek Tool Calls", "https://api-docs.deepseek.com/guides/tool_calls", "official API docs")],
            "source_urls": ["https://api-docs.deepseek.com/guides/tool_calls"],
        },
        user_text="查一下 DeepSeek 官方 tool calling 文档",
        required_source_type="official_docs",
    )

    assert weak["status"] == "weak"
    assert "official_source" in weak["missing_evidence"]
    assert strong["status"] == "sufficient"
    assert strong["official_source_count"] == 1


def test_controller_retries_until_source_is_sufficient() -> None:
    calls: list[str] = []

    def search(query: str) -> dict:
        calls.append(query)
        if len(calls) == 1:
            return {"query": query, "status": "empty", "results": [], "provider": "mock"}
        return {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official Codex CLI docs")],
        }

    report = run_search_evidence_controller(
        "OpenAI Codex CLI docs",
        user_text="搜索 OpenAI Codex 官方文档",
        network_enabled=True,
        web_search_fn=search,
        max_attempts=3,
    )

    assert report["status"] == "sufficient"
    assert report["attempt_count"] == 2
    assert report["stop_reason"] == "sufficient_evidence"
    assert len(calls) == 2
    assert report["observations"][-1]["search_evidence"]["status"] == "sufficient"


def test_controller_reports_evidence_exhausted_after_failed_attempts() -> None:
    report = run_search_evidence_controller(
        "OpenAI Codex CLI docs",
        user_text="搜索 OpenAI Codex 官方文档",
        network_enabled=True,
        web_search_fn=lambda query: {"query": query, "status": "error", "results": [], "provider": "mock", "error": "timeout"},
        max_attempts=2,
    )

    assert report["status"] == "failed"
    assert report["attempt_count"] == 2
    assert report["stop_reason"] == "evidence_exhausted"
    assert all(row["status"] == "error" for row in report["observations"])


def test_execute_tool_decision_uses_search_evidence_controller() -> None:
    calls: list[str] = []

    def search(query: str) -> dict:
        calls.append(query)
        return {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official docs")],
        }

    rows = execute_tool_decision(
        {"selected_actions": [{"action_type": "web_search", "query": "OpenAI Codex CLI docs"}]},
        network_enabled=True,
        web_search_fn=search,
    )

    assert calls
    assert rows[0]["status"] == "ok"
    assert rows[0]["search_evidence"]["schema"] == "holo.stage162.search_evidence_score.v1"
    assert rows[0]["search_evidence"]["status"] == "sufficient"


def test_network_disabled_records_rejected_search_evidence() -> None:
    report = run_search_evidence_controller(
        "OpenAI Codex CLI docs",
        user_text="搜索 OpenAI Codex 官方文档",
        network_enabled=False,
        web_search_fn=lambda query: {"query": query, "status": "ok", "results": []},
    )

    assert report["status"] == "rejected"
    assert report["observations"][0]["status"] == "rejected_network_disabled"
    assert report["stop_reason"] == "network_disabled"


def test_search_evidence_evaluation_counts_quality() -> None:
    report = evaluate_search_evidence(
        [
            {
                "status": "ok",
                "query": "OpenAI Codex CLI docs",
                "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official docs")],
                "source_urls": ["https://developers.openai.com/codex/cli"],
            }
        ],
        query="OpenAI Codex CLI docs",
        user_text="搜索 OpenAI Codex 官方文档",
    )

    assert report["status"] == "sufficient"
    assert report["best_evidence_score"] >= 0.72
    assert report["best_source_urls"] == ["https://developers.openai.com/codex/cli"]


def test_stage151_live_trace_surfaces_search_evidence_status() -> None:
    trace = build_stage151_live_trace(
        user_text="搜索 OpenAI Codex 官方文档",
        tool_decision={"purpose": "gather_web_evidence", "action_candidates": [], "selected_actions": []},
        web_observation_ledger=[
            {
                "observation_id": "web:1",
                "action_type": "web_search",
                "query": "OpenAI Codex CLI docs",
                "status": "ok",
                "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official docs")],
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "search_evidence": {"status": "sufficient", "evidence_score": 0.9},
            }
        ],
        grounding={"status": "grounded"},
        final_text="grounded",
    )

    observation = [event for event in trace["events"] if event["event"] == "observation"][0]
    assert observation["search_evidence_status"] == "sufficient"
    assert observation["evidence_score"] == 0.9


def test_stage153_event_stream_renders_search_evidence_status() -> None:
    stream = build_agent_event_stream(
        {
            "text": "grounded",
            "web_observation_ledger": [
                {
                    "observation_id": "web:1",
                    "action_type": "web_search",
                    "query": "OpenAI Codex CLI docs",
                    "status": "ok",
                    "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official docs")],
                    "source_urls": ["https://developers.openai.com/codex/cli"],
                    "search_evidence": {"status": "sufficient", "evidence_score": 0.9},
                }
            ],
        },
        user_text="搜索 OpenAI Codex 官方文档",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)

    assert "evidence=sufficient" in rendered
    assert "score=0.9" in rendered


def test_stage135_topology_includes_search_evidence_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="搜索 OpenAI Codex 官方文档",
        channel="holo_cli",
        thread_key="holo_cli:stage162",
        chat_name="HoloCLI",
        stage151_tool_decision={"purpose": "gather_web_evidence"},
        stage152_deepseek_tool_loop={},
        network_health={"network_enabled": True},
        web_observation_ledger=[
            {
                "observation_id": "web:1",
                "action_type": "web_search",
                "query": "OpenAI Codex CLI docs",
                "status": "ok",
                "results": [_result("OpenAI Codex CLI", "https://developers.openai.com/codex/cli", "official docs")],
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "search_evidence": {"status": "sufficient", "evidence_score": 0.9},
            }
        ],
    )

    assert topology["metrics"]["search_evidence_controller_node_count"] == 1
    assert topology["metrics"]["search_evidence_best_status"] == "sufficient"
