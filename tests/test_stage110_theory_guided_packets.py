from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage107_provider_interaction_loop import build_stage107_interaction_loop
from holo_host.stage108_expression_stream import build_stage108_expression_stream
from holo_host.stage109_consciousness_flow_theory import build_stage109_theory_frame
from holo_host.stage110_theory_guided_packets import build_stage110_packet_guidance


BROAD_RECALL_QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"
LOOKUP_QUERY = "\u67e5\u4e00\u4e0b\u6700\u65b0\u72b6\u6001"


def _stage109_frame(stage105: dict) -> dict:
    stage107 = build_stage107_interaction_loop(stage105)
    stage108 = build_stage108_expression_stream(stage107)
    return build_stage109_theory_frame(stage108, query=stage105.get("query", ""))


def test_stage110_broad_recall_expands_packet_budget_and_keeps_multi_packet_stream() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "semantic_attractor_lines": [
                "Stage104 attractor: finite context packets shape continuity.",
                "Stage104 attractor: memory compression determines continuity.",
                "Stage104 attractor: expression is not one-to-one with internal packets.",
            ],
            "uncertainty_level": 0.72,
            "selected_action": {"action_type": "reply_once", "why_now": "broad recall needs continuity"},
        },
        query=BROAD_RECALL_QUERY,
        max_packets=4,
        packet_budget_tokens=2400,
    )

    guidance = build_stage110_packet_guidance(stage105, _stage109_frame(stage105))

    assert guidance["schema"] == "holo.stage110.theory_guided_packets.v1"
    assert guidance["stage"] == 110
    assert guidance["recommended_packet_count"] == 3
    assert guidance["recommended_packet_budget_tokens"] > 2400
    assert "A2_local_continuity" in guidance["applied_axioms"]
    assert guidance["packet_rules"][0]["rule_id"] == "preserve_context_seed"


def test_stage110_lookup_is_tool_first_before_more_provider_packets() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.81,
            "selected_action": {"action_type": "reply_once", "why_now": "needs current evidence"},
        },
        query=LOOKUP_QUERY,
        max_packets=4,
    )

    guidance = build_stage110_packet_guidance(stage105, _stage109_frame(stage105))

    assert guidance["next_action"] == "execute_tool_locally"
    assert guidance["send_decision"] == "tool_first"
    assert "A4_grounded_perturbation" in guidance["applied_axioms"]
    assert guidance["tool_policy"]["must_observe_before_reply_commit"] is True


def test_stage110_no_send_preserves_stop_control() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "uncertainty_level": 0.1,
            "selected_action": {"action_type": "silence", "why_now": "no reply should be sent"},
        },
        query="\u6682\u65f6\u4e0d\u8981\u56de",
        max_packets=4,
    )

    guidance = build_stage110_packet_guidance(stage105, _stage109_frame(stage105))

    assert guidance["send_decision"] == "do_not_send"
    assert guidance["next_action"] == "stop"
    assert guidance["recommended_packet_count"] == 0
    assert "A5_expression_decoupling" in guidance["applied_axioms"]


def test_stage110_ready_to_continue_waits_for_internal_return_before_expression() -> None:
    stage105 = stage105_packet_stream_plan(
        {
            "semantic_attractor_lines": ["Stage104 attractor: finite packet loops."],
            "uncertainty_level": 0.64,
            "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
        },
        query=BROAD_RECALL_QUERY,
        max_packets=4,
    )
    frame = _stage109_frame(stage105)

    guidance = build_stage110_packet_guidance(stage105, frame)

    assert guidance["expression_policy"]["may_emit_before_provider_return"] is False
    assert guidance["expression_policy"]["required_stage108_status"] in {"awaiting_internal_event", "ready_to_emit"}
    assert "A5_expression_decoupling" in guidance["applied_axioms"]


def test_stage110_cli_dry_run_builds_guidance(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: (
            {
                "mind_packet": {
                    "semantic_attractor_lines": ["Stage104 attractor: theory should guide packet budgets."],
                    "uncertainty_level": 0.68,
                    "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
                }
            },
            "test",
        ),
    )

    result = cli.main(["stage110-theory-guided-packets", "--query", BROAD_RECALL_QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 110
    assert payload["source"] == "test"
    assert payload["stage109"]["stage"] == 109
