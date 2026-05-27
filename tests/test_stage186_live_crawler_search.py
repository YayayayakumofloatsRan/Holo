from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.live_crawler_search import (
    STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA,
    render_live_crawler_trace,
    run_live_crawler_search,
    write_live_crawler_search_artifacts,
)
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _weak_then_official_search(query: str) -> dict:
    if "official" not in query.lower() and "docs" not in query.lower():
        return {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [
                {
                    "title": "Unofficial overview",
                    "url": "https://example.com/codex-overview",
                    "snippet": "A generic overview with weak source authority.",
                }
            ],
        }
    return {
        "query": query,
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "OpenAI Codex CLI documentation",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI docs for a terminal coding agent.",
            }
        ],
    }


def _page(url: str) -> dict:
    if "developers.openai.com/codex/cli" in url:
        return {
            "url": url,
            "status": "ok",
            "provider": "mock_page",
            "html": "<html><title>Codex CLI</title><body>Codex CLI is OpenAI official documentation for a terminal coding agent that can read, edit, and run commands.</body></html>",
        }
    return {
        "url": url,
        "status": "ok",
        "provider": "mock_page",
        "html": "<html><title>Weak overview</title><body>This is an unofficial overview without enough evidence.</body></html>",
    }


def _failing_search(query: str) -> dict:
    return {"query": query, "status": "error", "provider": "mock_search", "results": [], "error": "simulated_search_failure"}


def test_crawler_runs_multiple_queries_until_evidence_is_sufficient() -> None:
    report = run_live_crawler_search(
        user_text="联网检索 Codex CLI 官方文档并给出来源",
        web_search_fn=_weak_then_official_search,
        open_page_fn=_page,
        network_enabled=True,
        max_queries=3,
        max_pages_per_query=2,
    )

    assert report["schema"] == STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA
    assert report["status"] == "sufficient"
    assert report["query_count"] >= 2
    assert report["opened_page_count"] >= 1
    assert report["stop_reason"] == "sufficient_evidence"
    assert "https://developers.openai.com/codex/cli" in report["source_urls"]
    assert "https://example.com/codex-overview" not in report["source_urls"]


def test_crawler_records_search_open_and_evaluate_steps() -> None:
    report = run_live_crawler_search(
        user_text="search official Codex CLI docs",
        web_search_fn=_weak_then_official_search,
        open_page_fn=_page,
        network_enabled=True,
    )

    phases = [row["phase"] for row in report["crawler_ledger"]]

    assert "query" in phases
    assert "open_page" in phases
    assert "evaluate" in phases
    assert report["web_observation_ledger"]
    assert report["page_observation_ledger"]


def test_network_disabled_records_rejection_without_fake_success() -> None:
    report = run_live_crawler_search(
        user_text="联网搜索 DeepSeek tool calling 最新文档",
        web_search_fn=_weak_then_official_search,
        open_page_fn=_page,
        network_enabled=False,
    )

    assert report["status"] == "rejected_network_disabled"
    assert report["stop_reason"] == "boundary_or_permission"
    assert report["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert "不能把它当成当前联网证据" in report["final_summary"]


def test_failed_search_reports_attempted_failure_not_future_intent() -> None:
    report = run_live_crawler_search(
        user_text="search Apple latest annual report",
        web_search_fn=_failing_search,
        open_page_fn=_page,
        network_enabled=True,
        max_queries=2,
    )

    assert report["status"] == "failed"
    assert report["stop_reason"] == "tool_failure_report"
    assert report["query_count"] == 2
    assert "attempted web_search" in report["final_summary"]
    assert "will search" not in report["final_summary"].lower()
    assert "need to complete" not in report["final_summary"].lower()


def test_rendered_trace_is_cli_friendly_and_auditable() -> None:
    report = run_live_crawler_search(
        user_text="search official Codex CLI docs",
        web_search_fn=_weak_then_official_search,
        open_page_fn=_page,
        network_enabled=True,
    )
    rendered = render_live_crawler_trace(report)

    assert "[crawl:query]" in rendered
    assert "[crawl:open]" in rendered
    assert "[crawl:evaluate]" in rendered
    assert "[crawl:stop]" in rendered
    assert "reasoning_content" not in rendered


def test_write_artifacts_and_cli_dry_run(tmp_path: Path) -> None:
    output = tmp_path / "stage186_live_crawler_search.html"

    report = write_live_crawler_search_artifacts(output=output, dry_run=True)

    assert report["schema"] == STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA

    cli_output = tmp_path / "stage186_cli.html"
    code = cli.main(["run-live-crawler-search", "--output", str(cli_output), "--dry-run"])
    assert code == 0
    assert cli_output.exists()


def test_public_payload_has_no_hidden_reasoning() -> None:
    report = run_live_crawler_search(
        user_text="search official Codex CLI docs",
        web_search_fn=_weak_then_official_search,
        open_page_fn=_page,
        network_enabled=True,
    )

    ok, paths = assert_no_private_reasoning(report)

    assert ok, paths


def test_stage135_topology_includes_live_crawler_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="stage186 crawler search",
        stage186_live_crawler_search={
            "schema": STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA,
            "status": "sufficient",
            "query_count": 2,
            "opened_page_count": 2,
            "source_urls": ["https://developers.openai.com/codex/cli"],
        },
    )

    assert topology["metrics"]["live_crawler_search_node_count"] == 1
    assert topology["metrics"]["live_crawler_search_status"] == "sufficient"
    assert any(node["id"] == "stage186_live_crawler_search" for node in topology["nodes"])
