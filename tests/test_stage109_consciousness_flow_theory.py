from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage105_provider_packet_stream import stage105_packet_stream_plan
from holo_host.stage107_provider_interaction_loop import build_stage107_interaction_loop
from holo_host.stage108_expression_stream import build_stage108_expression_stream
from holo_host.stage109_consciousness_flow_theory import build_stage109_theory_frame


QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"


def _stage108_stream() -> dict:
    stage105 = stage105_packet_stream_plan(
        {
            "semantic_attractor_lines": [
                "Stage104 attractor: finite context packets shape continuity.",
                "Stage104 attractor: expression is not one-to-one with internal packets.",
            ],
            "uncertainty_level": 0.68,
            "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
        },
        query=QUERY,
        max_packets=4,
    )
    stage107 = build_stage107_interaction_loop(
        stage105,
        provider_returns=[
            {"text": "Continuity emerges from local compression over finite provider packets."},
            {"text": "Expression granularity should follow the internal packet role."},
            {"text": "Final response should preserve source links without dumping internal state."},
        ],
    )
    return build_stage108_expression_stream(stage107)


def test_stage109_theory_maps_all_recent_stages_to_mechanisms() -> None:
    frame = build_stage109_theory_frame(_stage108_stream(), query=QUERY)

    assert frame["schema"] == "holo.stage109.consciousness_flow_theory.v1"
    assert frame["stage"] == 109
    mapped = {item["stage"]: item["mechanism"] for item in frame["stage_mechanism_map"]}
    assert mapped[104] == "semantic_attractors"
    assert mapped[105] == "finite_provider_packet_stream"
    assert mapped[106] == "provider_tool_affordance_adapter"
    assert mapped[107] == "packet_return_delta_loop"
    assert mapped[108] == "expression_stream_realization"


def test_stage109_contains_falsifiable_hypotheses_and_metrics() -> None:
    frame = build_stage109_theory_frame(_stage108_stream(), query=QUERY)

    hypothesis_ids = {item["id"] for item in frame["research_hypotheses"]}
    metric_ids = {item["id"] for item in frame["measurement_plan"]["metrics"]}

    assert {"H1_attractor_stability", "H2_compression_continuity", "H3_grounded_tool_perturbation"} <= hypothesis_ids
    assert {"source_event_coverage", "delta_retention", "grounding_ratio", "expression_granularity_fit"} <= metric_ids
    assert all(item["falsifiable"] for item in frame["research_hypotheses"])


def test_stage109_theory_preserves_expression_decoupling() -> None:
    frame = build_stage109_theory_frame(_stage108_stream(), query=QUERY)

    bridge = frame["internal_external_bridge"]
    assert bridge["one_internal_event_can_drive_multiple_surface_forms"] is True
    assert bridge["multiple_internal_events_can_merge_into_one_surface_form"] is True
    assert bridge["external_reply_is_not_equal_to_provider_packet"] is True


def test_stage109_links_to_foundational_agent_research_without_copying_it() -> None:
    frame = build_stage109_theory_frame(_stage108_stream(), query=QUERY)

    source_ids = {item["id"] for item in frame["literature_bridge"]}
    assert {"chain_of_thought", "react", "toolformer", "reflexion", "generative_agents", "self_refine"} <= source_ids
    assert frame["claim_boundary"]["base_model_training_required"] is False
    assert frame["claim_boundary"]["provider_above_adaptation"] is True


def test_stage109_cli_dry_run_builds_theory_frame(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: (
            {
                "mind_packet": {
                    "semantic_attractor_lines": ["Stage104 attractor: provider packet control is the research surface."],
                    "uncertainty_level": 0.68,
                    "selected_action": {"action_type": "reply_once", "why_now": "needs continuity"},
                }
            },
            "test",
        ),
    )

    result = cli.main(["stage109-consciousness-theory", "--query", QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 109
    assert payload["source"] == "test"
    assert payload["stage108"]["stage"] == 108
