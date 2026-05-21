from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage107_provider_interaction_loop import build_stage107_interaction_loop
from holo_host.stage108_expression_stream import build_stage108_expression_stream


BROAD_RECALL_QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"
LOOKUP_QUERY = "\u67e5\u4e00\u4e0b\u6700\u65b0\u72b6\u6001"


def _broad_recall_stage105() -> dict:
    return stage105_packet_stream_plan(
        {
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


def _complete_broad_recall_loop() -> dict:
    return build_stage107_interaction_loop(
        _broad_recall_stage105(),
        provider_returns=[
            {"text": "I found the stable theme: Holo improves by compressing local memory into finite provider packets."},
            {"text": "The unresolved part is how inner packet phases should become visible language."},
            {"text": "The final reply should expose continuity without dumping internal state."},
        ],
    )


def test_stage108_complete_multi_packet_loop_becomes_multi_bubble_expression() -> None:
    stream = build_stage108_expression_stream(_complete_broad_recall_loop(), granularity="auto")

    assert stream["schema"] == "holo.stage108.expression_stream.v1"
    assert stream["stage"] == 108
    assert stream["status"] == "ready_to_emit"
    assert stream["segment_count"] == 3
    assert [segment["segment_role"] for segment in stream["segments"]] == [
        "acknowledge",
        "semantic_delta",
        "reply_commit",
    ]
    assert all(segment["surface_form"] == "bubble" for segment in stream["segments"])
    assert all(segment["source_events"] for segment in stream["segments"])
    assert stream["visualization"]["edges"][0]["label"] == "drives_expression"


def test_stage108_paragraph_granularity_merges_internal_events_without_losing_sources() -> None:
    stream = build_stage108_expression_stream(_complete_broad_recall_loop(), granularity="paragraph")

    assert stream["segment_count"] == 1
    segment = stream["segments"][0]
    assert segment["surface_form"] == "paragraph"
    assert segment["segment_role"] == "reply_commit"
    assert len(segment["source_events"]) >= 3
    assert segment["text_budget"] >= 360


def test_stage108_tool_observation_surfaces_as_evidence_segment() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.82,
            "selected_action": {"action_type": "external_lookup", "why_now": "needs current evidence"},
        },
        query=LOOKUP_QUERY,
        max_packets=4,
    )
    loop = build_stage107_interaction_loop(
        stage105,
        tool_observations=[
            {"tool": "external_lookup", "status": "ok", "summary": "Provider status is healthy."}
        ],
        provider_returns=[{"text": "The lookup confirms the provider path is healthy."}],
    )

    stream = build_stage108_expression_stream(loop, granularity="auto")

    assert stream["segments"][0]["segment_role"] == "evidence"
    assert stream["segments"][0]["surface_form"] == "bubble"
    assert "tool_observation" in stream["segments"][0]["source_phases"]


def test_stage108_no_send_loop_has_no_external_segments() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.1,
            "selected_action": {"action_type": "silence", "why_now": "no reply should be sent"},
        },
        query="\u6682\u65f6\u4e0d\u8981\u56de",
        max_packets=4,
    )
    loop = build_stage107_interaction_loop(stage105)

    stream = build_stage108_expression_stream(loop)

    assert stream["status"] == "no_output"
    assert stream["segment_count"] == 0
    assert stream["segments"] == []
    assert stream["policy"]["surface_granularity"] == "silence"


def test_stage108_ready_to_continue_emits_internal_wait_segment_only() -> None:
    loop = build_stage107_interaction_loop(_broad_recall_stage105())

    stream = build_stage108_expression_stream(loop)

    assert stream["status"] == "awaiting_internal_event"
    assert stream["segment_count"] == 0
    assert stream["next_action"] == "send_provider_packet"
    assert stream["internal_pending_packet"]["packet_role"] == "context_seed"


def test_stage108_cli_dry_run_builds_expression_stream(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: (
            {
                "mind_packet": {
                    "semantic_attractor_lines": ["Stage104 attractor: expression should map to packets."],
                    "uncertainty_level": 0.68,
                    "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
                }
            },
            "test",
        ),
    )

    result = cli.main(["stage108-expression-stream", "--query", BROAD_RECALL_QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 108
    assert payload["source"] == "test"
    assert payload["stage107"]["stage"] == 107
