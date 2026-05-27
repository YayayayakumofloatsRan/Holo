from __future__ import annotations

import tempfile
import sys
from pathlib import Path

from holo_host.agent_event_stream import render_agent_event_stream
from holo_host.capabilities import CapabilityBroker
from holo_host.config import load_config
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_holo_host import FakeMemory, FakeRunner, close_service_handles


class ReplyCrawlerBroker(CapabilityBroker):
    def _external_lookup(self, text: str) -> dict:
        query = str(text)
        if "official" not in query.lower() and "docs" not in query.lower():
            return {
                "query": query,
                "status": "ok",
                "provider": "stage206_mock_search",
                "results": [
                    {
                        "title": "Weak Codex overview",
                        "url": "https://example.com/codex",
                        "snippet": "Weak third-party overview.",
                    }
                ],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "stage206_mock_search",
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
                "provider": "stage206_mock_page",
                "html": "<html><title>Codex CLI</title><body>Codex CLI is OpenAI official documentation for a terminal coding agent that can read code, edit files, run commands, and show auditable progress.</body></html>",
            }
        return {
            "url": url,
            "status": "ok",
            "provider": "stage206_mock_page",
            "html": "<html><title>Weak</title><body>Weak overview.</body></html>",
        }


class FailingReplyCrawlerBroker(ReplyCrawlerBroker):
    def _external_lookup(self, text: str) -> dict:
        return {
            "query": str(text),
            "status": "error",
            "provider": "stage206_mock_search",
            "results": [],
            "error": "simulated_search_failure",
        }


def _service(tmp_root: Path, *, broker_cls=ReplyCrawlerBroker, runner_text: str = "I will search this now.") -> HoloReplyService:
    config = load_config(repo_root=tmp_root)
    config.runtime.network_enabled = True
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    service = HoloReplyService(config, store=store, runner=FakeRunner(runner_text), memory=FakeMemory())
    service.capabilities = broker_cls(config)
    return service


def test_holo_cli_search_reply_uses_live_crawler_trace_and_grounded_final() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(Path(tmpdir))
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Operator",
                    "text": "search official Codex CLI docs and cite sources",
                    "channel": "holo_cli",
                    "message_id": "stage206-search-1",
                }
            )
        finally:
            close_service_handles(service)

    crawler = result["stage186_live_crawler_search"]
    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])

    assert crawler["status"] == "sufficient"
    assert "https://developers.openai.com/codex/cli" in crawler["source_urls"]
    assert "https://developers.openai.com/codex/cli" in result["text"]
    assert "will search" not in result["text"].lower()
    assert "[crawl:query]" in rendered
    assert "[crawl:open]" in rendered
    assert "[crawl:stop] status=sufficient reason=sufficient_evidence" in rendered
    assert result["canonical_stop_reason"] != "unknown"


def test_holo_cli_search_failure_reports_attempted_failure_not_future_intent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(Path(tmpdir), broker_cls=FailingReplyCrawlerBroker, runner_text="I will search this now.")
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Operator",
                    "text": "search official Codex CLI docs and cite sources",
                    "channel": "holo_cli",
                    "message_id": "stage206-search-fail-1",
                }
            )
        finally:
            close_service_handles(service)

    crawler = result["stage186_live_crawler_search"]
    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])

    assert crawler["status"] == "failed"
    assert "simulated_search_failure" in result["text"]
    assert "attempted web_search" in result["text"]
    assert "will search" not in result["text"].lower()
    assert "[crawl:stop] status=failed reason=tool_failure_report" in rendered
    assert result["canonical_stop_reason"] != "unknown"
