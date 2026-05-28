from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import CodexResult, OutgoingMessage, ProcessorTaskResult
from holo_host.public_thought_stream import build_public_thought_stream
from holo_host.reply_api import HoloReplyService
from holo_host.stage211_persistent_action_recall import (
    build_persistent_action_recall_reply,
    extract_previous_action_payload,
)
from holo_host.store import QueueStore


OFFICIAL_URL = "https://developers.openai.com/codex/cli"
WEAK_URL = "https://example.com/codex-overview"


class CountingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.task_calls: list[dict] = []

    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        self.calls.append((prompt, session_id))
        return CodexResult(reply_text="provider should not be called", session_id="unused", returncode=0)

    def run_task(self, request) -> ProcessorTaskResult:
        self.task_calls.append(request.to_dict())
        return ProcessorTaskResult(task_type=request.task_type, text="{}", returncode=0)


class UnusedMemory:
    pass


def _previous_search_metadata() -> dict:
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
                    "phase": "evaluate",
                    "query": "official Codex CLI docs",
                    "status": "supported",
                    "score": 1.0,
                    "stop_reason": "page_supported",
                    "authority_status": "sufficient",
                },
                {"phase": "stop", "status": "sufficient", "stop_reason": "sufficient_evidence"},
            ],
            "web_observation_ledger": [
                {
                    "schema": "holo.web_observation.v1",
                    "action_type": "web_search",
                    "query": "Codex CLI",
                    "status": "ok",
                    "source_urls": [WEAK_URL],
                    "results": [{"title": "Weak overview", "url": WEAK_URL, "snippet": "weak"}],
                    "page_evidence": {"status": "weak", "selected_url": WEAK_URL, "best_evidence_score": 0.53},
                    "source_authority": {"status": "insufficient"},
                },
                {
                    "schema": "holo.web_observation.v1",
                    "action_type": "web_search",
                    "query": "official Codex CLI docs",
                    "status": "ok",
                    "source_urls": [OFFICIAL_URL],
                    "results": [{"title": "OpenAI Codex CLI documentation", "url": OFFICIAL_URL, "snippet": "official"}],
                    "page_evidence": {"status": "supported", "selected_url": OFFICIAL_URL, "best_evidence_score": 1.0},
                    "source_authority": {"status": "sufficient"},
                },
            ],
        }
    }


def _history_rows() -> list[dict]:
    return [
        {
            "id": 1,
            "direction": "outbound",
            "body_text": f"Completed search with source {OFFICIAL_URL}",
            "payload_json": json.dumps({"metadata": _previous_search_metadata()}, ensure_ascii=False),
        },
        {
            "id": 2,
            "direction": "inbound",
            "body_text": "what exactly did you search on the web?",
            "payload_json": "{}",
        },
    ]


def test_extracts_previous_action_payload_from_outbound_metadata() -> None:
    payload = extract_previous_action_payload(_history_rows())

    assert payload["stage186_live_crawler_search"]["schema"] == "holo.stage186.live_crawler_search.v1"
    assert payload["stage211_source_message_id"] == 1


def test_persistent_action_recall_answers_from_history_without_provider() -> None:
    reply = build_persistent_action_recall_reply(
        "what exactly did you search on the web?",
        recent_messages=_history_rows(),
        thread_key="holo_cli:stage211",
        chat_name="HoloCLI",
        channel="holo_cli",
    )

    assert reply["action"] == "reply"
    assert reply["canonical_stop_source"] == "stage211_persistent_action_recall"
    assert reply["stage211_persistent_action_recall"]["status"] == "answered"
    assert reply["stage210_last_action_recall"]["status"] == "answered"
    assert "Codex CLI" in reply["text"]
    assert "official Codex CLI docs" in reply["text"]
    assert OFFICIAL_URL in reply["text"]
    assert WEAK_URL in reply["text"]
    assert "reasoning_content" not in json.dumps(reply)


def test_reply_api_short_circuits_persistent_last_action_recall() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        contact = store.ensure_contact("holo_cli:holo_cli:stage211", "HoloCLI")
        thread, _ = store.ensure_thread(
            channel="holo_cli",
            contact_id=int(contact["id"]),
            thread_key="holo_cli:stage211",
            subject="HoloCLI",
        )
        store.record_outbound(
            thread_id=int(thread["id"]),
            contact_id=int(contact["id"]),
            remote_message_id="out-stage211-search",
            outgoing=OutgoingMessage(
                recipient_email="holo_cli:holo_cli:stage211",
                subject="HoloCLI",
                body_text=f"Completed search with source {OFFICIAL_URL}",
                thread_key="holo_cli:stage211",
                channel="holo_cli",
                metadata=_previous_search_metadata(),
            ),
        )
        runner = CountingRunner()
        service = HoloReplyService(config, store=store, runner=runner, memory=UnusedMemory())
        try:
            result = service.handle_reply(
                {
                    "text": "what exactly did you search on the web?",
                    "chat_name": "HoloCLI",
                    "thread_key": "holo_cli:stage211",
                    "channel": "holo_cli",
                    "sender": "Operator",
                    "message_id": "in-stage211-meta",
                }
            )
        finally:
            store.close()
            logging.shutdown()

    assert runner.calls == []
    assert runner.task_calls == []
    assert result["action"] == "reply"
    assert result["canonical_stop_reason"] == "final_answer_ready"
    assert result["canonical_stop_source"] == "stage211_persistent_action_recall"
    assert result["stage211_persistent_action_recall"]["status"] == "answered"
    assert "official Codex CLI docs" in result["text"]
    assert "stage153_agent_event_stream" in result


def test_last_action_recall_enters_public_thought_stream() -> None:
    reply = build_persistent_action_recall_reply(
        "what exactly did you search on the web?",
        recent_messages=_history_rows(),
        thread_key="holo_cli:stage211",
        chat_name="HoloCLI",
        channel="holo_cli",
    )
    thought = build_public_thought_stream(reply, user_text="what exactly did you search on the web?")

    summaries = " ".join(str(card.get("summary", "")) for card in thought["cards"])
    assert "last_action" in summaries or "web_search" in summaries
    assert thought["hidden_reasoning_exposed"] is False
