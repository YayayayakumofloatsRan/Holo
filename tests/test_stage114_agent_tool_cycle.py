from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage114_agent_tool_cycle import run_stage114_agent_tool_cycle


def _stage105_multi_packet() -> dict:
    return stage105_packet_stream_plan(
        {
            "semantic_attractor_lines": [
                "provider packets need local observations",
                "tool evidence should re-enter the next packet",
            ],
            "uncertainty_level": 0.68,
            "selected_action": {"action_type": "reply_once", "why_now": "needs tool-grounded continuity"},
        },
        query="resolve provider packet continuity with local evidence",
        max_packets=4,
    )


def test_stage114_parses_executes_and_reenters_provider_tool_calls() -> None:
    decoded = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_memory",
                            "type": "function",
                            "function": {
                                "name": "memory_recall",
                                "arguments": json.dumps({"query": "provider packet continuity", "limit": 2}),
                            },
                        },
                        {
                            "id": "call_shell",
                            "type": "function",
                            "function": {
                                "name": "shell_exec",
                                "arguments": json.dumps({"cmd": "whoami"}),
                            },
                        },
                    ]
                },
            }
        ]
    }

    report = run_stage114_agent_tool_cycle(
        _stage105_multi_packet(),
        decoded_provider_response=decoded,
        memory_corpus=[{"id": "m1", "text": "provider packet continuity needs local tool observations"}],
    )

    assert report["schema"] == "holo.stage114.agent_tool_cycle.v1"
    assert report["stage"] == 114
    assert report["provider_tool_calls"]["accepted_names"] == ["memory_recall"]
    assert report["provider_tool_calls"]["rejected_errors"] == ["unknown_tool"]
    assert report["tool_execution"]["summary"]["executed_count"] == 1
    assert report["tool_execution"]["summary"]["skipped_count"] == 1
    assert report["reentry_loop"]["status"] == "ready_to_continue"
    assert report["next_provider_packet"]["available"] is True
    assert "tool_observation_summary" in report["next_provider_packet"]["inputs"]


def test_stage114_executes_stage105_tool_first_requests() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.82,
            "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
        },
        query="check latest provider status",
        max_packets=4,
    )

    report = run_stage114_agent_tool_cycle(
        stage105,
        external_lookup_fn=lambda query, max_results: {
            "query": query,
            "status": "ok",
            "results": [{"title": "Provider status", "url": "https://example.test/status", "snippet": "healthy"}],
        },
    )

    assert report["tool_execution"]["summary"]["executed_count"] == 1
    assert report["tool_execution"]["observations"][0]["tool"] == "external_lookup"
    assert report["reentry_loop"]["events"][0]["phase"] == "tool_request"
    assert report["reentry_loop"]["events"][1]["phase"] == "tool_observation"
    assert report["next_provider_packet"]["available"] is True


def test_stage114_cli_simulates_cycle_and_executes_memory(capsys, tmp_path: Path) -> None:
    corpus = tmp_path / "memory.jsonl"
    corpus.write_text(
        json.dumps({"id": "doc1", "text": "provider packet continuity needs local observation"}),
        encoding="utf-8",
    )

    result = cli.main(
        [
            "stage114-agent-tool-cycle",
            "--query",
            "provider packet continuity",
            "--simulate-tool",
            "memory_recall",
            "--memory-corpus",
            str(corpus),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 114
    assert payload["source"] == "cli"
    assert payload["tool_execution"]["summary"]["executed_count"] == 1
    assert payload["next_provider_packet"]["available"] is True
