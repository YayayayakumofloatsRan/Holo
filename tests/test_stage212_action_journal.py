from __future__ import annotations

import io
import json
from pathlib import Path
from unittest import mock

from holo_host import cli
from holo_host.config import load_config
from holo_host.models import OutgoingMessage
from holo_host.stage212_action_journal import (
    build_action_journal_from_messages,
    render_action_journal,
)
from holo_host.store import QueueStore


OFFICIAL_URL = "https://developers.openai.com/codex/cli"
WEAK_URL = "https://example.com/codex-overview"


def _crawler_metadata() -> dict:
    return {
        "stage186_live_crawler_search": {
            "schema": "holo.stage186.live_crawler_search.v1",
            "status": "sufficient",
            "stop_reason": "sufficient_evidence",
            "query_count": 2,
            "opened_page_count": 2,
            "source_urls": [OFFICIAL_URL],
            "crawler_ledger": [
                {"phase": "query", "query": "Codex CLI", "query_index": 1, "purpose": "broad_first"},
                {"phase": "observe_search", "query": "Codex CLI", "status": "ok", "result_count": 1, "source_count": 1},
                {"phase": "open_page", "query": "Codex CLI", "url": WEAK_URL, "status": "ok"},
                {
                    "phase": "evaluate",
                    "query": "Codex CLI",
                    "status": "weak",
                    "score": 0.53,
                    "stop_reason": "authority_insufficient",
                    "authority_status": "insufficient",
                },
                {"phase": "query", "query": "official Codex CLI docs", "query_index": 2, "purpose": "official_source"},
                {
                    "phase": "observe_search",
                    "query": "official Codex CLI docs",
                    "status": "ok",
                    "result_count": 1,
                    "source_count": 1,
                },
                {"phase": "open_page", "query": "official Codex CLI docs", "url": OFFICIAL_URL, "status": "ok"},
                {
                    "phase": "evaluate",
                    "query": "official Codex CLI docs",
                    "status": "supported",
                    "score": 1.0,
                    "stop_reason": "page_supported",
                    "authority_status": "sufficient",
                },
                {"phase": "stop", "status": "sufficient", "stop_reason": "sufficient_evidence"},
            ],
        },
        "stage190_self_feedback_loop": {
            "steps": [
                {
                    "action": "web_search",
                    "combined_sufficiency_score": 0.53,
                    "marginal_utility": 0.47,
                    "next_action": "official_source_retry",
                    "stop_reason": "authority_insufficient",
                }
            ]
        },
    }


def _messages() -> list[dict]:
    return [
        {
            "id": 1,
            "direction": "outbound",
            "created_at": "2026-05-28T00:00:00Z",
            "body_text": "Completed search.",
            "payload_json": json.dumps({"metadata": _crawler_metadata()}, ensure_ascii=False),
        },
        {
            "id": 2,
            "direction": "outbound",
            "created_at": "2026-05-28T00:01:00Z",
            "body_text": "No tool action.",
            "payload_json": json.dumps({"metadata": {"note": "no action"}}, ensure_ascii=False),
        },
    ]


def test_builds_persistent_action_journal_from_outbound_metadata() -> None:
    journal = build_action_journal_from_messages(_messages(), limit=5)

    assert journal["schema"] == "holo.stage212.action_journal.v1"
    assert journal["entry_count"] == 1
    entry = journal["entries"][0]
    assert entry["action_type"] == "web_search"
    assert entry["status"] == "sufficient"
    assert entry["stop_reason"] == "sufficient_evidence"
    assert entry["query_count"] == 2
    assert entry["opened_page_count"] == 2
    assert OFFICIAL_URL in entry["promoted_source_urls"]
    assert entry["step_count"] >= 8


def test_renders_action_journal_as_cli_friendly_auditable_flow() -> None:
    rendered = render_action_journal(build_action_journal_from_messages(_messages(), limit=5))

    assert "[journal]" in rendered
    assert "[action:1] web_search status=sufficient" in rendered
    assert "[crawl:query] Codex CLI" in rendered
    assert "[crawl:open]" in rendered
    assert "[crawl:evaluate] status=supported" in rendered
    assert "[feedback] action=web_search" in rendered
    assert OFFICIAL_URL in rendered
    assert "reasoning_content" not in rendered


def test_action_journal_cli_reads_persisted_thread_metadata(tmp_path: Path) -> None:
    config = load_config(repo_root=tmp_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    contact = store.ensure_contact("holo_cli:holo_cli:stage212", "HoloCLI")
    thread, _ = store.ensure_thread(
        channel="holo_cli",
        contact_id=int(contact["id"]),
        thread_key="holo_cli:stage212",
        subject="HoloCLI",
    )
    store.record_outbound(
        thread_id=int(thread["id"]),
        contact_id=int(contact["id"]),
        remote_message_id="stage212-search",
        outgoing=OutgoingMessage(
            recipient_email="holo_cli:holo_cli:stage212",
            subject="HoloCLI",
            body_text="Completed search.",
            thread_key="holo_cli:stage212",
            channel="holo_cli",
            metadata=_crawler_metadata(),
        ),
    )
    store.close()

    with mock.patch("holo_host.cli.load_config", return_value=config), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        rc = cli.command_action_journal(
            None,
            thread_key="holo_cli:stage212",
            chat_name="HoloCLI",
            channel="holo_cli",
            limit=5,
            json_output=False,
        )

    output = stdout.getvalue()
    assert rc == 0
    assert "[action:1] web_search status=sufficient" in output
    assert "official Codex CLI docs" in output
    assert OFFICIAL_URL in output
