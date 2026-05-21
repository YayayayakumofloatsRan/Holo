from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.stage105_provider_packet_stream import (
    inject_stage105_packet_stream,
    stage105_packet_stream_plan,
)


BROAD_RECALL_QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"
LOOKUP_QUERY = "\u67e5\u4e00\u4e0b\u6700\u65b0\u72b6\u6001"


def _base_packet() -> dict:
    return {
        "stage104": {"context_learning_visible": True, "semantic_attractor_count": 4},
        "semantic_attractor_lines": [
            "Stage104 attractor: Holo is in the Stage100+ biomimetic-agent research arc.",
            "Stage104 attractor: Provider calls are stateless inference.",
        ],
        "selected_memory_ids": ["stage104:project_stage"],
        "uncertainty_level": 0.72,
        "selected_action": {"action_type": "reply_once", "why_now": "broad recall needs continuity"},
        "thread_recall_lines": ["recent echo should not dominate"],
    }


def test_stage105_broad_recall_uses_multi_packet_stream() -> None:
    plan = stage105_packet_stream_plan(_base_packet(), query=BROAD_RECALL_QUERY, max_packets=4)

    assert plan["schema"] == "holo.stage105.provider_packet_stream.v1"
    assert plan["stage"] == 105
    assert plan["packet_count"] == 3
    assert [step["packet_role"] for step in plan["packets"]] == [
        "context_seed",
        "deliberation_delta",
        "reply_commit",
    ]
    assert plan["policy"]["send_decision"] == "send_multi"
    assert plan["next_action"] == "provider_packet"


def test_stage105_stops_when_confident_and_no_tool_needed() -> None:
    packet = {
        "uncertainty_level": 0.12,
        "selected_action": {"action_type": "reply_once", "why_now": "direct continuation"},
        "semantic_attractor_lines": ["Stage104 attractor: continuity is already visible."],
    }

    plan = stage105_packet_stream_plan(packet, query="\u7ee7\u7eed", max_packets=4)

    assert plan["packet_count"] == 1
    assert plan["stop_reason"] == "sufficient_context"
    assert plan["policy"]["send_decision"] == "send_once"
    assert plan["next_action"] == "provider_packet"


def test_stage105_tool_affordance_preempts_more_provider_packets() -> None:
    packet = {
        "uncertainty_level": 0.82,
        "selected_action": {"action_type": "external_lookup", "why_now": "needs current facts"},
        "lookup_reason": "needs current facts",
    }

    plan = stage105_packet_stream_plan(packet, query=LOOKUP_QUERY, max_packets=4)

    assert plan["next_action"] == "tool_request"
    assert plan["packet_count"] == 1
    assert plan["stop_reason"] == "tool_first"
    assert plan["tool_requests"][0]["name"] == "external_lookup"


def test_stage105_lookup_query_triggers_tool_even_before_high_uncertainty() -> None:
    packet = {
        "uncertainty_level": 0.22,
        "selected_action": {"action_type": "reply_once", "why_now": "ordinary reply"},
    }

    plan = stage105_packet_stream_plan(packet, query=LOOKUP_QUERY, max_packets=4)

    assert plan["next_action"] == "tool_request"
    assert plan["stop_reason"] == "tool_first"
    assert plan["tool_requests"][0]["payload"]["query"] == LOOKUP_QUERY


def test_stage105_deadline_sends_punctual_single_packet() -> None:
    packet = {
        "uncertainty_level": 0.66,
        "selected_action": {"action_type": "reply_once", "why_now": "deadline pressure"},
        "semantic_attractor_lines": ["Stage104 attractor: deadline pressure matters."],
    }

    plan = stage105_packet_stream_plan(packet, query="\u51c6\u65f6\u56de\u590d", max_packets=4, deadline_ms=900)

    assert plan["packet_count"] == 1
    assert plan["stop_reason"] == "deadline_pressure"
    assert plan["policy"]["send_decision"] == "send_punctual"
    assert plan["packets"][0]["timing"] == "punctual"


def test_stage105_injects_plan_into_packet() -> None:
    packet = _base_packet()
    plan = stage105_packet_stream_plan(packet, query=BROAD_RECALL_QUERY, max_packets=4)

    injected = inject_stage105_packet_stream(packet, plan)

    assert injected["stage105"]["packet_count"] == 3
    assert injected["state"]["stage105"]["next_action"] == "provider_packet"
    assert injected["provider_packet_stream"]["packets"][0]["packet_role"] == "context_seed"


def test_stage105_cli_dispatches_packet_stream(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None, repo_root=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )
    monkeypatch.setattr(
        cli,
        "_inspect_mind_payload",
        lambda *args, **kwargs: ({"mind_packet": _base_packet(), "stage104": {"context_learning_visible": True}}, "test"),
    )

    result = cli.main(["stage105-packet-stream", "--query", BROAD_RECALL_QUERY, "--max-packets", "4"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 105
    assert payload["packet_count"] == 3
    assert payload["source"] == "test"
