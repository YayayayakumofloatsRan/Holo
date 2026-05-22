from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage107_provider_interaction_loop import build_stage107_interaction_loop
from holo_host.stage113_agent_tool_executor import execute_stage113_agent_tools


def test_stage113_executes_accepted_tool_calls_and_skips_rejected() -> None:
    tool_calls = [
        {
            "id": "call_lookup",
            "name": "external_lookup",
            "arguments": {"query": "latest provider status", "max_results": 2},
            "allowed": True,
            "status": "accepted",
            "error": "",
        },
        {
            "id": "call_memory",
            "name": "memory_recall",
            "arguments": {"query": "provider packet continuity", "limit": 2},
            "allowed": True,
            "status": "accepted",
            "error": "",
        },
        {
            "id": "call_shell",
            "name": "shell_exec",
            "arguments": {"cmd": "whoami"},
            "allowed": False,
            "status": "rejected",
            "error": "unknown_tool",
        },
    ]

    report = execute_stage113_agent_tools(
        tool_calls,
        external_lookup_fn=lambda query, max_results: {
            "query": query,
            "status": "ok",
            "results": [{"title": "Provider status", "url": "https://example.test/status", "snippet": "healthy"}],
        },
        memory_corpus=[
            {"id": "m1", "text": "provider packet continuity depends on local compression"},
            {"id": "m2", "text": "irrelevant note"},
        ],
    )

    assert report["schema"] == "holo.stage113.agent_tool_executor.v1"
    assert report["stage"] == 113
    assert report["summary"]["executed_count"] == 2
    assert report["summary"]["skipped_count"] == 1
    assert [item["tool"] for item in report["observations"]] == ["external_lookup", "memory_recall"]
    assert report["observations"][0]["status"] == "ok"
    assert report["observations"][1]["data"]["matches"][0]["id"] == "m1"
    assert report["skipped"][0]["reason"] == "unknown_tool"


def test_stage113_observations_reenter_stage107_provider_packet() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.82,
            "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
        },
        query="check latest provider status",
        max_packets=4,
    )
    tool_call = {
        "id": "call_lookup",
        "name": "external_lookup",
        "arguments": {"query": "latest provider status"},
        "allowed": True,
        "status": "accepted",
        "error": "",
    }

    execution = execute_stage113_agent_tools(
        [tool_call],
        external_lookup_fn=lambda query, max_results: {
            "query": query,
            "status": "ok",
            "results": [{"title": "Provider status", "url": "https://example.test/status", "snippet": "healthy"}],
        },
    )
    loop = build_stage107_interaction_loop(stage105, tool_observations=execution["observations"])

    assert [event["phase"] for event in loop["events"][:3]] == [
        "tool_request",
        "tool_observation",
        "provider_packet",
    ]
    assert "Provider status" in loop["events"][2]["inputs"]["tool_observation_summary"]


def test_stage113_cli_executes_memory_recall(capsys, tmp_path: Path) -> None:
    corpus = tmp_path / "memory.jsonl"
    corpus.write_text(
        "\n".join(
            [
                json.dumps({"id": "doc1", "text": "finite provider packets create observable continuity"}),
                json.dumps({"id": "doc2", "text": "unrelated"}),
            ]
        ),
        encoding="utf-8",
    )

    result = cli.main(
        [
            "stage113-agent-tools",
            "--tool",
            "memory_recall",
            "--query",
            "provider packet continuity",
            "--memory-corpus",
            str(corpus),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 113
    assert payload["source"] == "cli"
    assert payload["summary"]["executed_count"] == 1
    assert payload["observations"][0]["tool"] == "memory_recall"
    assert payload["observations"][0]["data"]["matches"][0]["id"] == "doc1"
