from __future__ import annotations

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config


class MockCrawlerBroker(CapabilityBroker):
    def _external_lookup(self, text: str) -> dict:
        query = str(text)
        if "official" not in query.lower() and "docs" not in query.lower():
            return {
                "query": query,
                "status": "ok",
                "provider": "mock_search",
                "results": [
                    {
                        "title": "Generic Codex overview",
                        "url": "https://example.com/codex",
                        "snippet": "Weak overview.",
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
                    "snippet": "Official Codex CLI documentation for a terminal coding agent.",
                }
            ],
        }

    def _open_page_for_crawler(self, url: str) -> dict:
        if "developers.openai.com/codex/cli" in url:
            return {
                "url": url,
                "status": "ok",
                "provider": "mock_page",
                "html": "<html><title>Codex CLI</title><body>Codex CLI is OpenAI official documentation for a terminal coding agent that can read code, edit files, and run commands.</body></html>",
            }
        return {
            "url": url,
            "status": "ok",
            "provider": "mock_page",
            "html": "<html><title>Weak</title><body>Weak overview.</body></html>",
        }


def test_capability_broker_runs_stage186_crawler_for_eager_web_search() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    config.runtime.network_enabled = True
    broker = MockCrawlerBroker(config)

    payload = broker.summarize_turn(
        "联网检索 Codex CLI 官方文档并给出来源",
        {},
        eager_network=True,
        use_live_crawler=True,
    )

    crawler = payload["stage186_live_crawler_search"]
    assert crawler["status"] == "sufficient"
    assert crawler["query_count"] >= 2
    assert payload["web_observation_ledger"] == crawler["web_observation_ledger"]
    assert "https://developers.openai.com/codex/cli" in crawler["source_urls"]
    assert any("crawler query:" in line for line in payload["tool_context_lines"])
    assert any("crawler open:" in line for line in payload["tool_context_lines"])
    assert any(request["name"] == "live_crawler_search" for request in payload["tool_requests"])


def test_agent_event_stream_renders_stage186_crawl_events() -> None:
    config = load_config(repo_root="D:/Holo/holo")
    config.runtime.network_enabled = True
    payload = MockCrawlerBroker(config).summarize_turn(
        "联网检索 Codex CLI 官方文档并给出来源",
        {},
        eager_network=True,
        use_live_crawler=True,
    )
    payload["text"] = payload["stage186_live_crawler_search"]["final_summary"]

    rendered = render_agent_event_stream(
        build_agent_event_stream(
            payload,
            user_text="联网检索 Codex CLI 官方文档并给出来源",
            thread_key="holo_cli:default",
            chat_name="HoloCLI",
            channel="holo_cli",
        )
    )

    assert "[crawl:query]" in rendered
    assert "[crawl:open]" in rendered
    assert "[crawl:evaluate]" in rendered
    assert "[crawl:stop] status=sufficient reason=sufficient_evidence" in rendered
