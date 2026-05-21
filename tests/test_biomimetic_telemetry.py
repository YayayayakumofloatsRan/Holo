from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.biomimetic_telemetry import (
    build_biomimetic_frame,
    load_biomimetic_frames,
    record_biomimetic_event,
    summarize_biomimetic_telemetry,
)
from holo_host.biomimetic_visualization import build_biomimetic_visualization_payload


def test_build_biomimetic_frame_is_redacted_and_extracts_reply_state(tmp_path: Path) -> None:
    frame = build_biomimetic_frame(
        tmp_path,
        event_type="reply",
        source="reply_api.http",
        input_payload={
            "text": "private user text",
            "chat_name": "ResearchThread",
            "thread_key": "wechat:ResearchThread",
            "channel": "wechat",
            "message_id": "msg-1",
        },
        output_payload={
            "action": "reply",
            "text": "private reply text",
            "bubbles": ["private bubble"],
            "route": "deep_recall",
            "processor": "deepseek",
            "timing_ms": {"total_ms": 90000, "processor_ms": 1000},
            "selected_memory_ids": ["memory-1", "memory-2"],
            "activation_trace_ids": ["trace-1"],
            "emotion_state": {"valence": 0.6, "arousal": 0.4, "control": 0.7},
            "graph_confidence": 0.42,
            "expression_budget": 72,
        },
    )

    assert frame["schema"] == "holo.biomimetic_frame.v1"
    assert frame["event_type"] == "reply"
    assert frame["context"]["channel"] == "wechat"
    assert frame["context"]["thread_key"] == "wechat:ResearchThread"
    assert frame["observables"]["action"] == "reply"
    assert frame["observables"]["route"] == "deep_recall"
    assert frame["observables"]["selected_memory_count"] == 2
    assert frame["observables"]["activation_trace_count"] == 1
    assert frame["vector"]["values"]["deep_recall"] == 1.0
    assert frame["privacy"]["raw_text_included"] is False
    serialized = json.dumps(frame, ensure_ascii=False)
    assert "private user text" not in serialized
    assert "private reply text" not in serialized
    assert "private bubble" not in serialized


def test_record_and_load_biomimetic_frames_jsonl(tmp_path: Path) -> None:
    first = record_biomimetic_event(
        tmp_path,
        event_type="memory_doctor",
        source="cli.memory_doctor",
        output_payload={"biomimetic_health": {"semantic_consolidation": {"status": "critical"}}},
    )
    second = record_biomimetic_event(
        tmp_path,
        event_type="promotion_plan",
        source="cli.promote_memory",
        output_payload={"status": "plan", "candidate_count": 9, "would_apply": [{"candidate_id": "c1"}]},
    )

    rows = load_biomimetic_frames(tmp_path, limit=5)

    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["observables"]["health_status_counts"]["critical"] == 1
    assert rows[1]["observables"]["promotion_would_apply"] == 1
    assert summarize_biomimetic_telemetry(tmp_path)["total_frames"] == 2


def test_visualization_prefers_recorded_biomimetic_frames(tmp_path: Path) -> None:
    record_biomimetic_event(
        tmp_path,
        event_type="reply",
        source="reply_api.http",
        input_payload={"text": "private live turn", "thread_key": "holo_cli:main", "channel": "holo_cli"},
        output_payload={"action": "reply", "route": "fast", "timing_ms": {"total_ms": 120}},
    )

    payload = build_biomimetic_visualization_payload(tmp_path)

    assert payload["trajectory"]["source"] == "biomimetic_telemetry"
    assert len(payload["trajectory"]["frames"]) == 1
    assert "private live turn" not in json.dumps(payload, ensure_ascii=False)


def test_show_biomimetic_telemetry_cli(monkeypatch, capsys, tmp_path: Path) -> None:
    record_biomimetic_event(
        tmp_path,
        event_type="reply",
        source="reply_api.http",
        output_payload={"action": "reply", "route": "fast"},
    )
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(["show-biomimetic-telemetry", "--limit", "5"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["total_frames"] == 1
    assert payload["frames"][0]["event_type"] == "reply"
