from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.biomimetic_telemetry import (
    build_biomimetic_frame,
    build_recall_trajectory,
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


def test_build_recall_trajectory_redacts_raw_hits_and_keeps_search_motion(tmp_path: Path) -> None:
    output_payload = {
        "query": "private recall query",
        "channel": "holo_cli",
        "thread_key": "holo_cli:main",
        "tier": "deep_recall",
        "query_focus": "recall",
        "retrieval_mode": "graph-led",
        "memory_route": "hybrid",
        "recall_confidence": 0.82,
        "graph_confidence": 0.61,
        "graph_hits": [
            {
                "node_id": "raw-node-1",
                "score": 1.2,
                "memory_class": "episodic_memory",
                "source": "graph",
                "activation_reason": ["thread_match", "private reason text"],
                "text": "private graph memory text",
            }
        ],
        "vector_hits": [
            {
                "node_id": "raw-node-2",
                "score": 0.72,
                "memory_class": "durable_memory",
                "text": "private vector memory text",
            }
        ],
        "trace": [
            {
                "node_id": "raw-node-1",
                "hybrid_score": 1.44,
                "graph_score": 1.2,
                "vector_score": 0.4,
                "activation_boost": 0.2,
                "semantic_overlap": 3,
                "memory_class": "episodic_memory",
                "source": "hybrid",
                "rerank_reason": ["semantic_overlap:3", "private reason text"],
                "text": "private reranked memory text",
            }
        ],
    }

    trajectory = build_recall_trajectory(output_payload)
    frame = build_biomimetic_frame(
        tmp_path,
        event_type="hybrid_recall_trace",
        source="cli.trace_hybrid_recall",
        input_payload={"text": "private recall query", "thread_key": "holo_cli:main", "channel": "holo_cli"},
        output_payload=output_payload,
    )

    serialized = json.dumps({"trajectory": trajectory, "frame": frame}, ensure_ascii=False)
    assert trajectory["schema"] == "holo.recall_trajectory.v1"
    assert trajectory["stage_counts"] == {"graph": 1, "vector": 1, "rerank": 1}
    assert trajectory["candidate_count"] == 3
    assert trajectory["max_score"] == 1.44
    assert trajectory["stages"][0]["node_hash"].startswith("node-")
    assert trajectory["stages"][0]["reason_count"] == 2
    assert frame["observables"]["recall_candidate_count"] == 3
    assert frame["observables"]["recall_stage_count"] == 3
    assert frame["recall_trajectory"]["stage_counts"]["rerank"] == 1
    assert any(node.startswith("recall_stage:") for node in frame["topology_refs"]["nodes"])
    assert "private recall query" not in serialized
    assert "private graph memory text" not in serialized
    assert "private vector memory text" not in serialized
    assert "private reranked memory text" not in serialized
    assert "raw-node-1" not in serialized


def test_trace_hybrid_recall_cli_records_redacted_telemetry(monkeypatch, capsys, tmp_path: Path) -> None:
    class _Memory:
        def trace_hybrid_recall(self, query: str, *, thread_key: str | None, chat_name: str | None, channel: str, limit: int, record: bool) -> dict:
            return {
                "query": query,
                "channel": channel,
                "thread_key": thread_key or "",
                "chat_name": chat_name or "",
                "tier": "deep_recall",
                "memory_route": "hybrid",
                "trace": [{"node_id": "raw-node-1", "hybrid_score": 1.2, "text": "private memory"}],
            }

    monkeypatch.setattr(cli, "_live_api_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "build_daemon", lambda config_path=None: SimpleNamespace(memory=_Memory()))
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(
        [
            "trace-hybrid-recall",
            "--query",
            "private cli query",
            "--thread-key",
            "holo_cli:main",
            "--chat-name",
            "Main",
            "--channel",
            "holo_cli",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["biomimetic_telemetry"]["frame_id"].startswith("bf-")
    telemetry_text = (tmp_path / ".holo_runtime" / "biomimetic_frames.jsonl").read_text(encoding="utf-8")
    assert "private cli query" not in telemetry_text
    assert "private memory" not in telemetry_text
    assert "raw-node-1" not in telemetry_text
    frame = json.loads(telemetry_text.strip())
    assert frame["event_type"] == "hybrid_recall_trace"
    assert frame["recall_trajectory"]["candidate_count"] == 1
