from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage107_provider_interaction_loop import (
    build_stage107_interaction_loop,
    compress_provider_delta,
)


BROAD_RECALL_QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"
LOOKUP_QUERY = "\u67e5\u4e00\u4e0b\u6700\u65b0\u72b6\u6001"


def _broad_recall_stage105() -> dict:
    return stage105_packet_stream_plan(
        {
            "stage104": {"context_learning_visible": True, "semantic_attractor_count": 3},
            "semantic_attractor_lines": [
                "Stage104 attractor: Holo is a biomimetic agent research system.",
                "Stage104 attractor: Provider calls are finite packets.",
                "Stage104 attractor: Memory compression determines continuity.",
            ],
            "uncertainty_level": 0.72,
            "selected_action": {"action_type": "reply_once", "why_now": "broad recall needs continuity"},
        },
        query=BROAD_RECALL_QUERY,
        max_packets=4,
    )


def _lookup_stage105() -> dict:
    return stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.82,
            "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
        },
        query=LOOKUP_QUERY,
        max_packets=4,
    )


def test_stage107_broad_recall_alternates_provider_and_distill_phases() -> None:
    stage105 = _broad_recall_stage105()

    loop = build_stage107_interaction_loop(
        stage105,
        provider_returns=[
            {"text": "The remembered theme is continuity across stages and local compression."},
            {"text": "The unresolved part is how many packets to send before final reply."},
        ],
    )

    assert loop["schema"] == "holo.stage107.provider_interaction_loop.v1"
    assert loop["stage"] == 107
    assert loop["status"] == "ready_to_continue"
    assert [event["phase"] for event in loop["events"][:5]] == [
        "provider_packet",
        "provider_return",
        "distill_delta",
        "provider_packet",
        "provider_return",
    ]
    assert loop["events"][3]["inputs"]["previous_delta"]["available"] is True
    assert loop["visualization"]["edges"][0]["label"] == "provider_return"
    assert loop["visualization"]["edges"][1]["label"] == "distill_and_repack"


def test_stage107_tool_first_waits_for_local_observation_before_provider_packet() -> None:
    stage105 = _lookup_stage105()

    loop = build_stage107_interaction_loop(stage105)

    assert loop["status"] == "awaiting_tool_observation"
    assert loop["events"][0]["phase"] == "tool_request"
    assert loop["events"][0]["tool_requests"][0]["name"] == "external_lookup"
    assert loop["next_action"] == "execute_tool_locally"


def test_stage107_tool_observation_becomes_next_provider_packet_input() -> None:
    stage105 = _lookup_stage105()

    loop = build_stage107_interaction_loop(
        stage105,
        tool_observations=[
            {
                "tool": "external_lookup",
                "status": "ok",
                "summary": "Provider status is healthy; latest memory warehouse exists.",
            }
        ],
    )

    assert loop["status"] == "ready_to_continue"
    assert [event["phase"] for event in loop["events"][:3]] == [
        "tool_request",
        "tool_observation",
        "provider_packet",
    ]
    assert "Provider status is healthy" in loop["events"][2]["inputs"]["tool_observation_summary"]
    assert loop["events"][2]["metadata"]["enable_provider_tools"] is False


def test_stage107_provider_tool_call_interrupts_stream_for_local_execution() -> None:
    stage105 = _broad_recall_stage105()

    loop = build_stage107_interaction_loop(
        stage105,
        provider_returns=[
            {
                "text": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "memory_recall",
                        "arguments": {"query": "Stage104 Stage105 continuity"},
                        "allowed": True,
                        "status": "accepted",
                        "error": "",
                    }
                ],
            }
        ],
    )

    assert loop["status"] == "awaiting_tool_execution"
    assert loop["next_action"] == "execute_tool_locally"
    assert loop["events"][-1]["phase"] == "tool_request"
    assert loop["events"][-1]["source"] == "provider_tool_call"
    assert loop["events"][-1]["tool_requests"][0]["name"] == "memory_recall"


def test_stage107_preserves_no_send_stop_condition() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.1,
            "selected_action": {"action_type": "silence", "why_now": "no reply should be sent"},
        },
        query="\u6682\u65f6\u4e0d\u8981\u56de",
        max_packets=4,
    )

    loop = build_stage107_interaction_loop(stage105)

    assert loop["status"] == "complete"
    assert loop["next_action"] == "stop"
    assert loop["events"][0]["phase"] == "stop"
    assert loop["events"][0]["reason"] == "silence_selected"


def test_stage107_delta_compression_has_stable_budget() -> None:
    delta = compress_provider_delta(
        {
            "text": " ".join(["semantic continuity and finite packet compression"] * 80),
            "tool_calls": [],
        },
        budget_chars=180,
    )

    assert delta["available"] is True
    assert len(delta["summary"]) <= 180
    assert delta["digest"]


def test_stage107_cli_dry_run_builds_loop(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: (
            {
                "mind_packet": {
                    "semantic_attractor_lines": ["Stage104 attractor: finite provider packet streams."],
                    "uncertainty_level": 0.68,
                    "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
                }
            },
            "test",
        ),
    )

    result = cli.main(["stage107-interaction-loop", "--query", BROAD_RECALL_QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 107
    assert payload["source"] == "test"
    assert payload["stage105"]["packet_count"] >= 2
