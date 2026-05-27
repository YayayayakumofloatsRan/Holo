from __future__ import annotations

import io
from unittest import mock

from holo_host import cli


OFFICIAL_URL = "https://developers.openai.com/codex/cli"
WEAK_URL = "https://example.com/codex-overview"


def _previous_search_payload() -> dict:
    return {
        "action": "reply",
        "text": f"Completed search with source {OFFICIAL_URL}",
        "canonical_stop_reason": "final_answer_ready",
        "stage186_live_crawler_search": {
            "schema": "holo.stage186.live_crawler_search.v1",
            "status": "sufficient",
            "stop_reason": "sufficient_evidence",
            "query_count": 2,
            "opened_page_count": 2,
            "source_urls": [OFFICIAL_URL],
            "crawler_ledger": [
                {"phase": "query", "query": "Codex CLI", "query_index": 1, "purpose": "broad_first"},
                {"phase": "observe_search", "query": "Codex CLI", "status": "ok", "source_count": 1},
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
                {"phase": "observe_search", "query": "official Codex CLI docs", "status": "ok", "source_count": 1},
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
        },
        "web_observation_ledger": [],
    }


def test_stage210_report_answers_last_search_from_crawler_ledger() -> None:
    from holo_host.stage210_last_action_recall import build_last_action_recall_report

    report = build_last_action_recall_report(
        "我的意思是，外网检索，你搜索的是什么？",
        previous_payload=_previous_search_payload(),
    )

    assert report["schema"] == "holo.stage210.last_action_recall.v1"
    assert report["status"] == "answered"
    assert report["action_type"] == "web_search"
    assert report["query_count"] == 2
    assert "Codex CLI" in report["queries"]
    assert "official Codex CLI docs" in report["queries"]
    assert OFFICIAL_URL in report["promoted_source_urls"]
    assert WEAK_URL in report["observed_weak_source_urls"]
    assert WEAK_URL not in report["promoted_source_urls"]
    assert "hidden" not in report["answer_text"].lower()


def test_stage210_interactive_cli_answers_last_search_without_second_live_call() -> None:
    calls: list[dict] = []

    def fake_live_request(config_path, *, method, path, payload=None, timeout=0, **kwargs):
        if path == "/reply":
            calls.append(dict(payload or {}))
            return _previous_search_payload()
        return {"status": "ok"}

    with mock.patch("holo_host.cli._live_api_request", side_effect=fake_live_request), mock.patch(
        "builtins.input", side_effect=["search official Codex CLI docs and cite sources", "我的意思是，外网检索，你搜索的是什么？", "/json", "/exit"]
    ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
        result = cli.command_chat(
            None,
            thread_key="holo_cli:stage210",
            chat_name="HoloCLI",
            channel="holo_cli",
            sender="Operator",
            once=None,
            json_output=False,
            trace_output=True,
            no_local_fallback=True,
            timeout=3.0,
        )

    output = stdout.getvalue()
    assert result == 0
    assert len(calls) == 1
    assert "[last_action] action=web_search status=answered" in output
    assert "Codex CLI" in output
    assert "official Codex CLI docs" in output
    assert OFFICIAL_URL in output
    assert "weak source not promoted" in output
    assert '"stage210_last_action_recall"' in output
